"""
S3 Phase 1 : Waste Detection

Three rules applied to every bucket Agent 0 discovered.
Rules run in order : ALL three can fire on the same bucket independently.
A bucket with no lifecycle policy AND zero requests gets TWO findings.

No AWS API calls. No writes. Pure in-memory logic reading from DB.
Results passed directly to the single write at the end of the pipeline.

Rule 1 : Missing lifecycle policy
    Source: s3_buckets.has_lifecycle
    Fires:  has_lifecycle = FALSE and object_count > 0
    Action: RECOMMEND_LIFECYCLE
    Fix:    lifecycle_policy_json generated here

Rule 2 : Abandoned bucket
    Source: s3_metrics (sum of get_requests + put_requests over 30 days)
    Fires:  total requests = 0 AND object_count >= min_object_count
    Action: REVIEW (never auto-act : bucket may be intentional cold storage)

Rule 3 : Storage class mismatch
    Source: s3_object_samples (pct_older_than_90_days, pct_in_standard)
    Fires:  pct_older_90_days > threshold AND pct_in_standard > threshold
    Action: RECOMMEND_LIFECYCLE with tiered transition policy
"""

import asyncpg
from .models import S3FindingResult, S3Action, S3WasteType, S3Rules
from .s3_queries import (
    get_all_buckets,
    get_bucket_request_total,
    get_latest_object_sample,
)


async def run_s3_phase1(
    conn: asyncpg.Connection,
    rules: S3Rules,
) -> list[S3FindingResult]:
    """
    Entry point. Returns all S3 findings in memory.
    CLEAN buckets are excluded : nothing to pass downstream.
    Multiple findings per bucket ARE possible and expected.
    Equivalent of run_phase1() for EC2.
    """
    buckets  = await get_all_buckets(conn)
    findings = []

    for bucket in buckets:
        bucket_findings = await _process_bucket(conn, bucket, rules)
        findings.extend(bucket_findings)

    return findings


async def _process_bucket(
    conn: asyncpg.Connection,
    bucket: dict,
    rules: S3Rules,
) -> list[S3FindingResult]:
    """
    Run all three rules against a single bucket.
    Collect every finding : rules are independent of each other.
    """
    results = []

    # Rule 1 : always runs, needs no external data beyond s3_buckets
    r1 = _rule1_missing_lifecycle(bucket)
    if r1.action != S3Action.CLEAN:
        results.append(r1)

    # Rule 2 : needs s3_metrics
    r2 = await _rule2_abandoned(conn, bucket, rules.abandoned)
    if r2.action != S3Action.CLEAN:
        results.append(r2)

    # Rule 3 : needs s3_object_samples
    r3 = await _rule3_storage_mismatch(conn, bucket, rules.storage_mismatch)
    if r3.action != S3Action.CLEAN:
        results.append(r3)

    return results


# =============================================================================
# Rule 1 : Missing lifecycle policy
# =============================================================================

def _rule1_missing_lifecycle(bucket: dict) -> S3FindingResult:
    """
    Highest confidence rule. Purely deterministic.
    If has_lifecycle is False and the bucket has objects : flag it.
    No metrics needed. No time window needed.
    Agent 0 wrote has_lifecycle by calling get_bucket_lifecycle_configuration.
    """
    bucket_name  = bucket["bucket_name"]
    has_lifecycle = bucket["has_lifecycle"]
    object_count  = bucket.get("object_count", 0) or 0

    # Empty buckets with no lifecycle policy are not wasteful : nothing to transition
    if has_lifecycle or object_count == 0:
        return _clean(bucket_name, S3WasteType.MISSING_LIFECYCLE)

    # Generate the standard tiered lifecycle policy as the fix artifact
    policy = _generate_lifecycle_policy(bucket_name)

    return S3FindingResult(
        bucket_name            = bucket_name,
        action                 = S3Action.RECOMMEND_LIFECYCLE,
        waste_type             = S3WasteType.MISSING_LIFECYCLE,
        has_lifecycle          = False,
        object_count           = object_count,
        recommended_action     = (
            "Add a tiered lifecycle policy: transition objects to Standard-IA "
            "after 30 days and Glacier after 90 days."
        ),
        lifecycle_policy_json  = policy,
        detection_reason       = (
            f"Bucket has {object_count} objects and no lifecycle policy. "
            f"All objects remain in Standard storage indefinitely."
        ),
    )


# =============================================================================
# Rule 2 : Abandoned bucket
# =============================================================================

async def _rule2_abandoned(
    conn: asyncpg.Connection,
    bucket: dict,
    rules,
) -> S3FindingResult:
    """
    Fires when a non-empty bucket has had zero API activity over the window.
    Action is always REVIEW : never recommend deletion automatically.
    Buckets can be used for audit, compliance, or DR with no recent traffic.
    """
    bucket_name  = bucket["bucket_name"]
    object_count = bucket.get("object_count", 0) or 0

    # Must have at least min_object_count objects to be considered abandoned
    # An empty bucket with no requests is just unused infrastructure : different problem
    if object_count < rules.min_object_count:
        return _clean(bucket_name, S3WasteType.ABANDONED)

    total_requests = await get_bucket_request_total(
        conn, bucket_name, rules.window_days
    )

    # No metric data at all : cannot make a safe determination
    if total_requests is None:
        return _clean(bucket_name, S3WasteType.ABANDONED)

    if total_requests <= rules.max_total_requests:
        return S3FindingResult(
            bucket_name        = bucket_name,
            action             = S3Action.REVIEW,
            waste_type         = S3WasteType.ABANDONED,
            detection_window   = f"{rules.window_days} days",
            total_requests_30d = total_requests,
            object_count       = object_count,
            recommended_action = (
                "Review bucket for deletion or archival. "
                "Verify it is not used for compliance, audit, or DR before acting."
            ),
            detection_reason   = (
                f"Bucket has {object_count} objects but received "
                f"{int(total_requests)} total requests (GET + PUT) "
                f"over the last {rules.window_days} days. "
                f"Possible abandoned storage."
            ),
        )

    return _clean(bucket_name, S3WasteType.ABANDONED)


# =============================================================================
# Rule 3 : Storage class mismatch
# =============================================================================

async def _rule3_storage_mismatch(
    conn: asyncpg.Connection,
    bucket: dict,
    rules,
) -> S3FindingResult:
    """
    Fires when most objects are old and still sitting in expensive Standard storage.
    Agent 0 already calculated the percentages from list_objects_v2 sampling.
    Agent 1 reads those percentages and applies the threshold check.
    Savings are estimated from object size and price difference per GB.
    """
    bucket_name = bucket["bucket_name"]
    size_bytes  = bucket.get("size_bytes", 0) or 0

    sample = await get_latest_object_sample(conn, bucket_name)

    # No sampling data : Agent 0 may not have run sampling for this bucket
    if sample is None:
        return _clean(bucket_name, S3WasteType.STORAGE_MISMATCH)

    pct_older_90  = sample["pct_older_than_90_days"]
    pct_standard  = sample["pct_in_standard"]
    sample_size   = sample["sample_size"]

    if (pct_older_90 >= rules.pct_older_90_days_threshold and
            pct_standard >= rules.min_pct_in_standard):

        savings = _estimate_savings(size_bytes, pct_standard, rules)
        policy  = _generate_lifecycle_policy(bucket_name)

        return S3FindingResult(
            bucket_name                = bucket_name,
            action                     = S3Action.RECOMMEND_LIFECYCLE,
            waste_type                 = S3WasteType.STORAGE_MISMATCH,
            detection_window           = f"{rules.window_days} days",
            pct_older_90_days          = pct_older_90,
            estimated_monthly_savings  = savings,
            recommended_action         = (
                "Apply tiered lifecycle policy: transition to Standard-IA at 30 days, "
                "Glacier at 90 days. Estimated monthly savings shown."
            ),
            lifecycle_policy_json      = policy,
            detection_reason           = (
                f"{pct_older_90:.1f}% of sampled objects (sample size: {sample_size}) "
                f"are older than 90 days and {pct_standard:.1f}% remain in Standard storage. "
                f"Objects are paying Standard prices despite low access frequency."
            ),
        )

    return _clean(bucket_name, S3WasteType.STORAGE_MISMATCH)


# =============================================================================
# Helpers
# =============================================================================

def _clean(bucket_name: str, waste_type: S3WasteType) -> S3FindingResult:
    """
    Equivalent of _clean() in detection.py.
    Returns a CLEAN result that gets filtered out before writing.
    """
    return S3FindingResult(
        bucket_name      = bucket_name,
        action           = S3Action.CLEAN,
        waste_type       = waste_type,
        detection_reason = "No waste pattern detected for this rule.",
    )


def _generate_lifecycle_policy(bucket_name: str) -> dict:
    """
    Generates the standard tiered S3 lifecycle policy JSON.
    This is the fix artifact the engineer downloads and applies.
    Equivalent of the Terraform script generated for EC2 findings.

    Transitions:
      Day 0  → STANDARD (current)
      Day 30 → STANDARD_IA  (58% cheaper than Standard)
      Day 90 → GLACIER       (68% cheaper than Standard-IA)
    """
    return {
        "Rules": [
            {
                "ID": f"finops-tiered-lifecycle-{bucket_name}",
                "Status": "Enabled",
                "Filter": {"Prefix": ""},   # applies to all objects
                "Transitions": [
                    {
                        "Days": 30,
                        "StorageClass": "STANDARD_IA"
                    },
                    {
                        "Days": 90,
                        "StorageClass": "GLACIER"
                    }
                ],
                "NoncurrentVersionTransitions": [
                    {
                        "NoncurrentDays": 30,
                        "StorageClass": "STANDARD_IA"
                    },
                    {
                        "NoncurrentDays": 90,
                        "StorageClass": "GLACIER"
                    }
                ]
            }
        ]
    }


def _estimate_savings(
    size_bytes: int,
    pct_in_standard: float,
    rules,
) -> float:
    """
    Estimates monthly savings from moving Standard objects to Glacier.
    Uses price difference from rules.yaml.

    Formula:
      standard_gb = (pct_in_standard / 100) * total_gb
      savings = standard_gb * (standard_price - glacier_price)
    """
    if size_bytes == 0:
        return 0.0

    total_gb      = size_bytes / (1024 ** 3)
    standard_gb   = (pct_in_standard / 100.0) * total_gb
    price_diff    = rules.standard_price_per_gb - rules.glacier_price_per_gb
    monthly_saving = standard_gb * price_diff

    return round(monthly_saving, 2)
