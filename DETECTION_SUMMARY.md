# Detection Summary and Test Case Guide

This document summarizes what the pipeline detects, how each decision is made, and which cases should be covered by tests. Thresholds come from `rules.yaml`.

## Data Sources

EC2 detection reads:

- `ec2_instances` joined to `resources` for identity, role, status, region, OS, and instance type.
- `ec2_metrics` for CPU, RAM, network, disk, and last metric timestamp.
- `pricing` for instance hourly cost and the same-family sizing ladder.

S3 detection reads:

- `s3_instances` for bucket metadata, object count, size, lifecycle status, region, team, and environment.
- `s3_metrics` for GET + PUT request totals.
- `s3_object_samples` for latest object-age and storage-class samples by `grouping_key`.
- `s3_pricing` for regional Standard, Standard-IA, Glacier, and Deep Archive prices.

Phase 2 reads `resource_relationships` and `resources` to score local relationships around Phase 1 EC2 findings.

## EC2 Phase 1 Detection

### Stopped Zombie

Detected before role-specific logic. If an instance status is `stopped` and its latest EC2 metric is stale by at least `30` days, or no metric exists, it is flagged:

- `action`: `TERMINATE`
- `waste_type`: `zombie`
- `detection_window_days`: `30`
- `waste_per_month`: current hourly price x 24 x 30

Test cases:

- Stopped instance with last metric older than 30 days returns `TERMINATE`.
- Stopped instance with no metrics returns `TERMINATE`.
- Stopped instance with last metric newer than 30 days returns `REVIEW` and `waste_type=stopped`.
- Boundary: exactly 30 stale days is zombie; below 30 is review.

### Running Zombie

Detected for `running` instances before skipped-role and role-specific logic. Metrics are evaluated over `14` days. All conditions must be true:

- `max_cpu < 1.5`
- `max_network_mbps < 5.0`
- `max_disk_mbps < 1.0`

Result:

- `action`: `TERMINATE`
- `waste_type`: `zombie`
- includes max CPU, network, and disk evidence

Test cases:

- All three values below thresholds returns `TERMINATE`.
- Any one value at or above threshold does not return running zombie.
- Running zombie applies even if role would otherwise be skipped.

### Skipped Roles

After zombie checks, roles listed in `detection.skipped_roles` are skipped:

- `backup`
- `dependant_secondary`

Result:

- `action`: `SKIP`
- `waste_type`: `none`

Test cases:

- Non-zombie `backup` returns `SKIP`.
- Non-zombie `dependant_secondary` returns `SKIP`.
- Zombie status still wins before skipped role handling.

### Dependant Primary Idle

For `role=dependant_primary`, metrics are evaluated over `30` days. Both conditions must be true:

- `p95_cpu < 10.0`
- `p95_ram < 20.0`

Result:

- `action`: `DOWNSIZE`
- `waste_type`: `idle`
- sizing recommendation is calculated from the pricing ladder

Test cases:

- Both p95 values below thresholds returns `DOWNSIZE`.
- Either p95 value at or above threshold returns `CLEAN`.
- No metrics returns `CLEAN`.

### Bursty Tag Error

For `role=bursty`, metrics are evaluated over `30` days. If `cv < 0.5`, the workload is treated as incorrectly tagged:

- `action`: `REVIEW`
- `waste_type`: `tag_error`

This check runs before bursty oversized detection.

Test cases:

- `cv < 0.5` returns `REVIEW`.
- Boundary: `cv == 0.5` does not trigger tag error.
- Low `cv` plus low `p99_cpu` still returns tag error because tag error is checked first.

### Bursty Oversized

For `role=bursty`, after passing the CV check, the instance is oversized when:

- `p99_cpu < 30.0`

Result:

- `action`: `DOWNSIZE`
- `waste_type`: `oversized`
- sizing uses `p99_cpu`, `p95_ram`, `p99_network_mbps`, and `p99_disk_mbps`

Test cases:

- `cv >= 0.5` and `p99_cpu < 30.0` returns `DOWNSIZE`.
- Boundary: `p99_cpu == 30.0` returns `CLEAN`.
- No metrics returns `CLEAN`.

### Steady Idle

Default path for roles other than `dependant_primary` and `bursty`. Idle is checked before oversized using a `7` day window. All conditions must be true:

- `p95_cpu < 5.0`
- `p95_ram < 10.0`
- `max_cpu < 20.0`

Result:

- `action`: `STOP`
- `waste_type`: `idle`
- `waste_per_month`: current hourly price x 24 x 30

Test cases:

- All values below thresholds returns `STOP`.
- Any value at or above threshold falls through to oversized detection.
- Idle wins over oversized if both could match.

### Steady Oversized

If steady idle does not match, oversized is checked over `14` days. Both conditions must be true:

- `p95_cpu < 20.0`
- `p95_ram < 40.0`

Result:

- `action`: `DOWNSIZE`
- `waste_type`: `oversized`
- sizing recommendation is calculated

Test cases:

- Both p95 values below thresholds returns `DOWNSIZE`.
- Either p95 value at or above threshold returns `CLEAN`.
- No idle metrics but oversized metrics exist can still return `DOWNSIZE`.
- No metrics for either window returns `CLEAN`.

## EC2 Sizing Recommendation

Downsize candidates are loaded from `pricing` for the same instance family, region, and OS. Candidates below the current ladder rank are checked from nearest smaller type downward.

A candidate is rejected if:

- projected CPU is `>= 70.0`
- projected RAM is `> 80.0`
- projected network exceeds `80%` of candidate network capacity, when capacity exists
- projected disk exceeds `80%` of candidate disk capacity, when capacity exists

The first passing candidate is returned with `recommended_type`, projected CPU/RAM, recommended hourly cost, and monthly waste.

Test cases:

- Candidate with safe CPU/RAM/IO returns a recommendation.
- CPU exactly `70.0` rejects the candidate.
- RAM exactly `80.0` is allowed; above `80.0` rejects.
- Missing pricing ladder returns no recommendation but keeps the detection result.

## S3 Phase 1 Detection

S3 rules are independent. One bucket can produce multiple findings.

### Missing Lifecycle

Detected when:

- `has_lifecycle` is false
- `object_count > 0`

Result:

- `action`: `RECOMMEND_LIFECYCLE`
- `waste_type`: `missing_lifecycle`
- recommends Standard-IA after 30 days, Glacier after 90 days, Deep Archive after 180 days

Test cases:

- Bucket with objects and no lifecycle returns `RECOMMEND_LIFECYCLE`.
- Bucket with lifecycle returns `CLEAN` for this rule.
- Empty bucket returns `CLEAN` for this rule.

### Abandoned Bucket

Detected when:

- `object_count >= 1`
- request metrics exist for the last `30` days
- total requests, computed as `SUM(get_requests + put_requests)`, are `<= 10`

Result:

- `action`: `REVIEW`
- `waste_type`: `abandoned`

Test cases:

- Object count above minimum and total requests `<= 10` returns `REVIEW`.
- Boundary: exactly `10` requests returns `REVIEW`.
- `11` requests returns `CLEAN`.
- No request samples returns `CLEAN`.
- `object_count < 1` returns `CLEAN`.

### Storage Mismatch

Latest object samples are evaluated independently by `grouping_key`. A group is wasteful if any condition is true:

- `pct_older_than_30_days > 50.0`
- `pct_older_than_90_days > 30.0`
- `pct_older_than_180_days > 20.0`

Result:

- `action`: `RECOMMEND_LIFECYCLE`
- `waste_type`: `storage_mismatch`
- `grouping_key`: the tag or prefix group being optimized
- `estimated_monthly_savings`: regional Standard price minus target tier price, multiplied by Standard GB in the group

Target tier is chosen by deepest qualifying threshold:

- `> 180d` threshold: Deep Archive
- else `> 90d` threshold: Glacier
- else `> 30d` threshold: Standard-IA

Test cases:

- Each threshold independently produces a finding.
- Boundary values equal to thresholds do not produce a finding.
- Multiple grouping keys can produce multiple findings for one bucket.
- No object samples returns `CLEAN`.
- Missing regional pricing falls back to default prices.
- `group_size_bytes=0` returns savings `0.0`.

## Phase 2 Guardrails

Phase 2 does not create new waste findings. It changes or blocks EC2 Phase 1 actions using relationship context.

### Bypassed Actions

Phase 1 `CLEAN` and `SKIP` are not graph-scored. They pass through Phase 2 with:

- same `action`
- `skip_write=True`
- `blast_radius=0`

Test cases:

- `CLEAN` remains `CLEAN`.
- `SKIP` remains `SKIP` and includes a `block_reason`.

### Guardrail A: High Availability Relationships

If a flagged resource has any Type-E relationship, action is forced to `SKIP`:

- `replicates_to`
- `failover_for`

Result:

- `action`: `SKIP`
- `skip_write=True`
- `block_reason` explains the Type-E relationship

Test cases:

- Any `replicates_to` relationship forces `SKIP`.
- Any `failover_for` relationship forces `SKIP`.
- Type-E guardrail wins before blast-radius scoring.

### Guardrail B: Blast Radius

Relationships are weighted:

- `backup_of`: 3
- `writes_to`: 2
- `reads_from`: 1
- `sends_logs_to`: 1

The blast radius is the sum of relationship weights. Unknown relationship types count as `0`.

Action downgrades:

- `TERMINATE` becomes `REVIEW` when `blast_radius > 0`.
- `STOP` becomes `DOWNSIZE` when any relationship is `writes_to` or `sends_logs_to`.
- `STOP` becomes `REVIEW` when `blast_radius > 1` and no writes/logs downgrade applied.
- `DOWNSIZE` becomes `REVIEW` when `blast_radius > 3`.
- `REVIEW` remains `REVIEW`.

Test cases:

- `TERMINATE` with no relationships remains `TERMINATE`.
- `TERMINATE` with one `reads_from` becomes `REVIEW`.
- `STOP` with `writes_to` becomes `DOWNSIZE`.
- `STOP` with two low-risk relationships and score above `1` becomes `REVIEW`.
- `DOWNSIZE` with score `3` remains `DOWNSIZE`.
- `DOWNSIZE` with score `4` becomes `REVIEW`.
- Unknown relationship type does not increase `blast_radius`.

## Suggested Test Organization

Use small, focused tests around pure helpers where possible:

- `phase1.sizing.calculate_recommended_type`
- `phase2.guardrails.compute_blast_radius`
- `phase3.converter.build_ec2_scenario`
- `phase3.converter.build_s3_scenario`

For async detection functions, mock the query helpers imported into the module under test, or seed a disposable test database with minimal rows. Prefer one expected behavior per test and include boundary cases for strict `<`, `>`, `<=`, and `>=` behavior.
