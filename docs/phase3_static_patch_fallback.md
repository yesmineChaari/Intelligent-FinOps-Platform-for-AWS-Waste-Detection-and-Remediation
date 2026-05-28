# Phase 3 Static Patch Fallback


The trust boundary is around Terraform generation. Phase 3 still extracts the
LLM `PatchPlan` for auditability, but it can ignore LLM-generated Terraform for
PR creation and use a deterministic static `PatchPlan` instead.

## Flow

```text
Phase 1 output
-> Phase 2 output
-> Phase 3 LLM runs normally
-> LLM output is stored
-> LLM PatchPlan is extracted
-> safety envelope is evaluated
-> patch source is selected
-> selected PatchPlan goes to the existing PR flow
```

The PR flow itself is unchanged. It receives whichever `PatchPlan` Phase 3
selected.

## Patch Source Modes

`PHASE3_PATCH_SOURCE=auto`

Default mode. Phase 3 follows
`output["code_generation_safety"]["use_static_patch_fallback"]`. If the safety
envelope requests static fallback, the deterministic static `PatchPlan` is used.
Otherwise the LLM `PatchPlan` is used.

`PHASE3_PATCH_SOURCE=static`

Forces the deterministic static `PatchPlan`, even when the safety envelope would
allow the LLM patch. This is useful for local testing and demos.

`PHASE3_PATCH_SOURCE=llm`

Forces the original LLM `PatchPlan` behavior, even when the safety envelope
would request static fallback. This is useful for comparison.

Invalid values are treated as `auto`.

## Safety Envelope

With `PHASE3_PATCH_SOURCE=auto`, static fallback is requested when any of these
signals is true:

- The maximum prompt token estimate exceeds `PHASE3_LLM_CODEGEN_SAFE_TOKENS`.
- Terraform context is too large, based on a `PHASE3_TERRAFORM_MAX_BYTES`
  warning.
- The context fallback model was used.

`PHASE3_LLM_CODEGEN_SAFE_TOKENS` defaults to `6000`.

The token estimate is intentionally lightweight: approximately 1 token per 4
characters.

## Static Generator Support

### EC2 DOWNSIZE

The static generator can patch EC2 downsizing only when all of these are true:

- Phase 2 approved automatic remediation.
- The action is `DOWNSIZE`.
- A recommended instance type exists.
- Exactly one Terraform `aws_instance` or matching module block is safely
  matched.

Only the `instance_type` line inside the matched block is changed. The generator
does not perform global replacement of `instance_type` values.

### S3 Lifecycle Transition

The static generator can add an S3 lifecycle transition for cold-storage
recommendations.

Supported storage classes:

- `STANDARD_IA`
- `ONEZONE_IA`
- `GLACIER`
- `DEEP_ARCHIVE`
- `INTELLIGENT_TIERING`

If a lifecycle or cold-storage recommendation does not specify a supported
storage class, the generator defaults to `GLACIER` with a 30 day transition.

The generator must match exactly one `aws_s3_bucket` resource by bucket name or a
single safe `bucket_prefix` match. It appends an
`aws_s3_bucket_lifecycle_configuration` block to the same Terraform file as the
matched bucket. It skips the bucket if a lifecycle configuration already exists
for that bucket.

## Unsupported Or Risky Actions

The static generator currently does not:

- Delete resources.
- Terminate EC2 instances.
- Stop EC2 instances.
- Modify IAM policies.
- Modify bucket names.
- Patch ambiguous resources.
- Patch actions that Phase 2 blocked or marked for manual review.

Unsupported or unsafe cases produce warnings and no modified files.

## Output Fields

Inspect `output["code_generation_safety"]` for the safety-envelope decision:

- `safe_codegen_token_limit`
- `max_prompt_token_estimate`
- `context_fallback_was_used`
- `terraform_context_too_large`
- `use_static_patch_fallback`
- `reason`

Inspect `output["patch_generation"]` for the selected patch source:

- `source`
- `patch_source_mode`
- `safety_requested_static`
- `llm_generated_code_ignored`
- `reason`
- `llm_modified_files_count`
- `selected_modified_files_count`
- `selected_warnings`

Example when static is selected:

```json
{
  "patch_generation": {
    "source": "static",
    "llm_generated_code_ignored": true
  }
}
```

Example when the LLM patch is selected:

```json
{
  "patch_generation": {
    "source": "llm",
    "llm_generated_code_ignored": false
  }
}
```

## Environment Examples

Windows PowerShell:

```powershell
$env:PHASE3_PATCH_SOURCE="static"
$env:PHASE3_PATCH_SOURCE="auto"
$env:PHASE3_PATCH_SOURCE="llm"
$env:PHASE3_LLM_CODEGEN_SAFE_TOKENS="6000"
```

## Testing

Lightweight validation commands:

```powershell
python -m py_compile agent2/phase3/llm_phase3.py agent2/phase3/static_patch_generator.py tests/test_static_patch_generator.py
python -m unittest tests.test_static_patch_generator
```

Broader Phase 3 tests may require optional local dependencies such as `asyncpg`
and `PyGithub`.
