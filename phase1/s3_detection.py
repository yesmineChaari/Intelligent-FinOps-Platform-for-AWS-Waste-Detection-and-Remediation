"""
S3 Phase 1 waste detection.
Rules are independent: multiple findings can be produced for one bucket.
"""

import asyncpg

from .s3_models import S3Action, S3FindingResult, S3Rules, S3StorageMismatchRules, S3WasteType
from .s3_queries import get_all_buckets, get_bucket_request_total, get_latest_object_samples, get_regional_s3_pricing


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

    # --- Handles multiple rule 3 findings for different tags ---
    r3_findings = await _rule3_storage_mismatch(conn, bucket, rules.storage_mismatch)
    for finding in r3_findings:
        if finding.action != S3Action.CLEAN:
            results.append(finding)

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




def _estimate_multi_tier_savings(size_bytes: int, group: dict, rules: S3StorageMismatchRules) -> float:
    """Calculates potential savings by moving 'Standard' data into appropriate tiers."""
    total_gb = size_bytes / (1024 ** 3)
    standard_gb = (group["pct_in_standard"] / 100.0) * total_gb
    
    # Simple weighted calculation:
    # We estimate how much Standard data can be shifted to the cheapest applicable tier
    if group["pct_older_than_180_days"] > 20: # Example logic: focus on Deep Archive if significant
        target_price = rules.deep_archive_price_per_gb
    elif group["pct_older_than_90_days"] > 20:
        target_price = rules.glacier_price_per_gb
    else:
        target_price = rules.ia_price_per_gb

    monthly_savings = standard_gb * (rules.standard_price_per_gb - target_price)

    return round(max(0, monthly_savings), 2)

def _clean(bucket_name: str, waste_type: S3WasteType) -> S3FindingResult:
    return S3FindingResult(
        bucket_name=bucket_name,
        action=S3Action.CLEAN,
        waste_type=waste_type,
        detection_reason="No waste pattern detected for this rule.",
    )


def _generate_lifecycle_policy(bucket_name: str, grouping_key: str = "ALL") -> dict:
    
    # 1. Parse the grouping key into a surgical AWS Filter
    if grouping_key.startswith("tag:"):
        key_val = grouping_key[4:].split("=", 1)
        if len(key_val) == 2:
            filter_dict = {"Tag": {"Key": key_val[0], "Value": key_val[1]}}
        else:
            filter_dict = {"Prefix": ""} 
            
    elif grouping_key.startswith("prefix:"):
        # Example: 'prefix:/logs/'
        filter_dict = {"Prefix": grouping_key[7:]}
    else:
        # Default bucket-level fallback
        filter_dict = {"Prefix": ""}

    # 2. Create a clean ID for the AWS Rule
    safe_id = grouping_key.replace(":", "-").replace("=", "-").replace("/", "-")

    return {
        "Rules": [{
            "ID": f"finops-lifecycle-{safe_id}",
            "Status": "Enabled",
            "Filter": filter_dict,
            "Transitions": [
                {"Days": 30, "StorageClass": "STANDARD_IA"},
                {"Days": 90, "StorageClass": "GLACIER"},
                {"Days": 180, "StorageClass": "DEEP_ARCHIVE"} # NEW
            ],
            "NoncurrentVersionTransitions": [
                {"NoncurrentDays": 30, "StorageClass": "STANDARD_IA"},
                {"NoncurrentDays": 90, "StorageClass": "GLACIER"}
            ]
        }]
    }

async def _rule3_storage_mismatch(
    conn: asyncpg.Connection,
    bucket: dict,
    rules: S3StorageMismatchRules,
) -> list[S3FindingResult]:
    
    groups = await get_latest_object_samples(conn, bucket["resource_id"])
    
    if not groups:
        return [_clean(bucket["bucket_name"], S3WasteType.STORAGE_MISMATCH)]

    # 1. Fetch the exact pricing for THIS bucket's region
    pricing = await get_regional_s3_pricing(conn, bucket["region"])
    findings = []
    
    for group in groups:
        # 2. Check if the group violates ANY of the aging thresholds
        is_wasteful = (
            group["pct_older_than_180_days"] > rules.pct_older_180_days_threshold or
            group["pct_older_than_90_days"] > rules.pct_older_90_days_threshold or
            group["pct_older_than_30_days"] > rules.pct_older_30_days_threshold
        )

        if is_wasteful:
            # 3. Calculate savings using REAL regional pricing and the SPECIFIC group size
            savings = _estimate_dynamic_savings(
                size_bytes=group["group_size_bytes"],
                group=group,
                pricing=pricing,
                rules=rules
            )
            
            policy = _generate_lifecycle_policy(bucket["bucket_name"], group["grouping_key"])

            findings.append(
                S3FindingResult(
                    bucket_name=bucket["bucket_name"],
                    grouping_key=group["grouping_key"],
                    action=S3Action.RECOMMEND_LIFECYCLE,
                    waste_type=S3WasteType.STORAGE_MISMATCH,
                    detection_window=f"{rules.window_days}d",
                    object_count=group["sample_size"],
                    estimated_monthly_savings=savings,
                    recommended_action=f"Apply Tiered Lifecycle for {group['grouping_key']}",
                    lifecycle_policy_json=policy,
                    detection_reason=(
                        f"Target '{group['grouping_key']}' aging breakdown: "
                        f"{group['pct_older_than_30_days']}% >30d, "
                        f"{group['pct_older_than_90_days']}% >90d, "
                        f"{group['pct_older_than_180_days']}% >180d."
                    ),
                )
            )

    if not findings:
        return [_clean(bucket["bucket_name"], S3WasteType.STORAGE_MISMATCH)]
        
    return findings


def _estimate_dynamic_savings(size_bytes: int, group: dict, pricing: dict, rules: S3StorageMismatchRules) -> float:
    """Calculates potential savings by moving 'Standard' data into appropriate tiers based on DB pricing."""
    if size_bytes == 0:
        return 0.0

    total_gb = size_bytes / (1024 ** 3)
    standard_gb = (group["pct_in_standard"] / 100.0) * total_gb
    
    # Extract DB prices (with fallbacks if the dictionary somehow missed a tier)
    std_price = pricing.get("Standard", 0.023)
    
    # Determine the 'deepest' tier this data qualifies for based on the thresholds
    if group["pct_older_than_180_days"] > rules.pct_older_180_days_threshold:
        target_price = pricing.get("Deep Archive", 0.00099)
    elif group["pct_older_than_90_days"] > rules.pct_older_90_days_threshold:
        target_price = pricing.get("Glacier", 0.0036)
    else:
        target_price = pricing.get("Standard-IA", 0.0125)

    # Monthly savings = Gb in standard * (Cost of Standard - Cost of new Tier)
    monthly_savings = standard_gb * (std_price - target_price)
    
    return round(max(0, monthly_savings), 2)