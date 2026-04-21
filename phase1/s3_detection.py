"""
S3 Phase 1 waste detection.
Rules are independent: multiple findings can be produced for one bucket.
"""

import asyncpg

from .s3_models import S3Action, S3FindingResult, S3Rules, S3WasteType
from .s3_queries import get_all_buckets, get_bucket_request_total, get_latest_object_sample


async def run_s3_phase1(
    conn: asyncpg.Connection,
    rules: S3Rules,
) -> list[S3FindingResult]:
    buckets = await get_all_buckets(conn)
    findings: list[S3FindingResult] = []

    for bucket in buckets:
        bucket_findings = await _process_bucket(conn, bucket, rules)
        findings.extend(bucket_findings)

    return findings


async def _process_bucket(
    conn: asyncpg.Connection,
    bucket: dict,
    rules: S3Rules,
) -> list[S3FindingResult]:
    results: list[S3FindingResult] = []

    r1 = _rule1_missing_lifecycle(bucket)
    if r1.action != S3Action.CLEAN:
        results.append(r1)

    r2 = await _rule2_abandoned(conn, bucket, rules.abandoned)
    if r2.action != S3Action.CLEAN:
        results.append(r2)

    r3 = await _rule3_storage_mismatch(conn, bucket, rules.storage_mismatch)
    if r3.action != S3Action.CLEAN:
        results.append(r3)

    return results


def _rule1_missing_lifecycle(bucket: dict) -> S3FindingResult:
    bucket_name = bucket["bucket_name"]
    has_lifecycle = bucket["has_lifecycle"]
    object_count = bucket.get("object_count", 0) or 0

    if has_lifecycle or object_count == 0:
        return _clean(bucket_name, S3WasteType.MISSING_LIFECYCLE)

    policy = _generate_lifecycle_policy(bucket_name)

    return S3FindingResult(
        bucket_name=bucket_name,
        action=S3Action.RECOMMEND_LIFECYCLE,
        waste_type=S3WasteType.MISSING_LIFECYCLE,
        has_lifecycle=False,
        object_count=object_count,
        recommended_action=(
            "Add a tiered lifecycle policy: transition objects to Standard-IA "
            "after 30 days and Glacier after 90 days."
        ),
        lifecycle_policy_json=policy,
        detection_reason=(
            f"Bucket has {object_count} objects and no lifecycle policy. "
            "All objects remain in Standard storage indefinitely."
        ),
    )


async def _rule2_abandoned(
    conn: asyncpg.Connection,
    bucket: dict,
    rules,
) -> S3FindingResult:
    resource_id = int(bucket["resource_id"])
    bucket_name = bucket["bucket_name"]
    object_count = bucket.get("object_count", 0) or 0

    if object_count < rules.min_object_count:
        return _clean(bucket_name, S3WasteType.ABANDONED)

    total_requests = await get_bucket_request_total(conn, resource_id, rules.window_days)

    if total_requests is None:
        return _clean(bucket_name, S3WasteType.ABANDONED)

    if total_requests <= rules.max_total_requests:
        return S3FindingResult(
            bucket_name=bucket_name,
            action=S3Action.REVIEW,
            waste_type=S3WasteType.ABANDONED,
            detection_window=f"{rules.window_days} days",
            total_requests_30d=total_requests,
            object_count=object_count,
            recommended_action=(
                "Review bucket for deletion or archival. "
                "Verify it is not used for compliance, audit, or DR before acting."
            ),
            detection_reason=(
                f"Bucket has {object_count} objects but received {int(total_requests)} total requests "
                f"(GET + PUT) over the last {rules.window_days} days. Possible abandoned storage."
            ),
        )

    return _clean(bucket_name, S3WasteType.ABANDONED)


async def _rule3_storage_mismatch(
    conn: asyncpg.Connection,
    bucket: dict,
    rules,
) -> S3FindingResult:
    resource_id = int(bucket["resource_id"])
    bucket_name = bucket["bucket_name"]
    size_bytes = bucket.get("size_bytes", 0) or 0

    sample = await get_latest_object_sample(conn, resource_id)
    if sample is None:
        return _clean(bucket_name, S3WasteType.STORAGE_MISMATCH)

    pct_older_90 = sample["pct_older_than_90_days"]
    pct_standard = sample["pct_in_standard"]
    sample_size = sample["sample_size"]

    if (
        pct_older_90 >= rules.pct_older_90_days_threshold
        and pct_standard >= rules.min_pct_in_standard
    ):
        savings = _estimate_savings(size_bytes, pct_standard, rules)
        policy = _generate_lifecycle_policy(bucket_name)

        return S3FindingResult(
            bucket_name=bucket_name,
            action=S3Action.RECOMMEND_LIFECYCLE,
            waste_type=S3WasteType.STORAGE_MISMATCH,
            detection_window=f"{rules.window_days} days",
            pct_older_90_days=pct_older_90,
            estimated_monthly_savings=savings,
            recommended_action=(
                "Apply tiered lifecycle policy: transition to Standard-IA at 30 days, "
                "Glacier at 90 days. Estimated monthly savings shown."
            ),
            lifecycle_policy_json=policy,
            detection_reason=(
                f"{pct_older_90:.1f}% of sampled objects (sample size: {sample_size}) are older than 90 days "
                f"and {pct_standard:.1f}% remain in Standard storage. Objects are paying Standard prices "
                "despite low access frequency."
            ),
        )

    return _clean(bucket_name, S3WasteType.STORAGE_MISMATCH)


def _clean(bucket_name: str, waste_type: S3WasteType) -> S3FindingResult:
    return S3FindingResult(
        bucket_name=bucket_name,
        action=S3Action.CLEAN,
        waste_type=waste_type,
        detection_reason="No waste pattern detected for this rule.",
    )


def _generate_lifecycle_policy(bucket_name: str) -> dict:
    return {
        "Rules": [
            {
                "ID": f"finops-tiered-lifecycle-{bucket_name}",
                "Status": "Enabled",
                "Filter": {"Prefix": ""},
                "Transitions": [
                    {"Days": 30, "StorageClass": "STANDARD_IA"},
                    {"Days": 90, "StorageClass": "GLACIER"},
                ],
                "NoncurrentVersionTransitions": [
                    {"NoncurrentDays": 30, "StorageClass": "STANDARD_IA"},
                    {"NoncurrentDays": 90, "StorageClass": "GLACIER"},
                ],
            }
        ]
    }


def _estimate_savings(size_bytes: int, pct_in_standard: float, rules) -> float:
    if size_bytes == 0:
        return 0.0

    total_gb = size_bytes / (1024 ** 3)
    standard_gb = (pct_in_standard / 100.0) * total_gb
    price_diff = rules.standard_price_per_gb - rules.glacier_price_per_gb
    monthly_saving = standard_gb * price_diff

    return round(monthly_saving, 2)
