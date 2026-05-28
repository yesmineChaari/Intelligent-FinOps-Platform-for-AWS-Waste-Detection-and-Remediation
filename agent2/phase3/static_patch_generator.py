"""Deterministic Phase 3 Terraform patch generation.

This module intentionally ignores LLM-generated Terraform and only emits
patches for narrow, explicitly supported remediation patterns.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from .patch_schema import ModifiedFile, PatchPlan


_SUPPORTED_EC2_ACTIONS = {"DOWNSIZE", "STOP", "TERMINATE"}
_BLOCKED_STATUSES = {
    "BLOCKED",
    "DENIED",
    "FAILED",
    "MANUAL",
    "MANUAL_REVIEW",
    "PENDING",
    "REJECTED",
    "REQUIRES_APPROVAL",
    "REQUIRES_HUMAN_APPROVAL",
    "REVIEW",
    "SKIP",
}
_ALLOWED_STATUS_FIELDS = (
    "status",
    "decision_status",
    "approval_status",
    "phase2_status",
    "safety_status",
)
_MANUAL_REVIEW_FIELDS = (
    "requires_human_approval",
    "requires_manual_approval",
    "requires_manual_review",
    "manual_review_required",
)
_RECOMMENDED_TYPE_FIELDS = (
    "recommended_instance_type",
    "target_instance_type",
    "recommended_type",
    "new_instance_type",
)
_IDENTITY_FIELDS = (
    "instance_name",
    "resource_name",
    "instance_id",
    "terraform_name",
    "name",
)
_INSTANCE_TYPE_RE = re.compile(
    r'(?m)^([ \t]*instance_type[ \t]*=[ \t]*)"([^"]+)"([^\n\r]*)$'
)
_INSTANCE_TYPE_ASSIGNMENT_RE = re.compile(r'^([ \t]*instance_type[ \t]*=[ \t]*)"([^"\r\n]+)"([^\n\r]*)')
_INSTANCE_TYPE_VALUE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_COUNT_ASSIGNMENT_RE = re.compile(r"^([ \t]*count[ \t]*=[ \t]*)([^\n\r#]+)([^\n\r]*)")
_FOR_EACH_ASSIGNMENT_RE = re.compile(r"^[ \t]*for_each[ \t]*=")
_ENABLE_LIFECYCLE_ASSIGNMENT_RE = re.compile(
    r"^([ \t]*enable_lifecycle[ \t]*=[ \t]*)([^\n\r#]+)([^\n\r]*)"
)
_DESIRED_STATE_ASSIGNMENT_RE = re.compile(
    r"^([ \t]*desired_state[ \t]*=[ \t]*)([^\n\r#]+)([^\n\r]*)"
)
_SOURCE_ASSIGNMENT_RE = re.compile(r'^([ \t]*source[ \t]*=[ \t]*)"([^"\r\n]+)"([^\n\r]*)')
_PREVENT_DESTROY_RE = re.compile(
    r"(?s)\blifecycle\s*\{[^{}]*\bprevent_destroy\s*=\s*true\b[^{}]*\}"
)
_BLOCK_HEADER_RE = re.compile(
    r'(?m)^[ \t]*(resource[ \t]+"aws_instance"[ \t]+"([^"]+)"|module[ \t]+"([^"]+)")[ \t]*\{'
)
_EC2_INSTANCE_STATE_HEADER_RE = re.compile(
    r'(?m)^[ \t]*resource[ \t]+"aws_ec2_instance_state"[ \t]+"([^"]+)"[ \t]*\{'
)
_EC2_INSTANCE_STATE_INSTANCE_ID_RE = re.compile(
    r'(?m)^[ \t]*instance_id[ \t]*=[ \t]*([^\n\r#]+)'
)
_STRING_LITERAL_RE = re.compile(r'"([^"\r\n]+)"')
_S3_BUCKET_HEADER_RE = re.compile(
    r'(?m)^[ \t]*resource[ \t]+"aws_s3_bucket"[ \t]+"([^"]+)"[ \t]*\{'
)
_S3_LIFECYCLE_HEADER_RE = re.compile(
    r'(?m)^[ \t]*resource[ \t]+"aws_s3_bucket_lifecycle_configuration"[ \t]+"([^"]+)"[ \t]*\{'
)
_S3_BUCKET_ASSIGNMENT_RE = re.compile(
    r'(?m)^[ \t]*(bucket|bucket_prefix)[ \t]*=[ \t]*"([^"\r\n]+)"[^\n\r]*$'
)
_S3_MODULE_BUCKET_ASSIGNMENT_RE = re.compile(
    r'(?m)^[ \t]*(instance_id|bucket_name|bucket|name|bucket_prefix)[ \t]*=[ \t]*"([^"\r\n]+)"[^\n\r]*$'
)
_S3_BUCKET_FIELDS = (
    "bucket_name",
    "bucket",
    "resource_name",
    "name",
)
_S3_RECOMMENDATION_FIELDS = (
    "recommendation",
    "recommended_action",
    "action",
    "lifecycle_action",
    "storage_recommendation",
    "recommended_storage_class",
    "target_storage_class",
)
_S3_STORAGE_CLASS_FIELDS = (
    "recommended_storage_class",
    "target_storage_class",
)
_S3_ALLOWED_STORAGE_CLASSES = {
    "STANDARD_IA",
    "ONEZONE_IA",
    "GLACIER",
    "DEEP_ARCHIVE",
    "INTELLIGENT_TIERING",
}
_S3_UNSUPPORTED_STORAGE_CLASS_MARKERS = {
    "EXPRESS_ONEZONE",
    "GLACIER_IR",
    "REDUCED_REDUNDANCY",
    "STANDARD",
}
_S3_LIFECYCLE_KEYWORDS = (
    "LIFECYCLE",
    "GLACIER",
    "TRANSITION",
    "ARCHIVE",
    "ARCHIVAL",
)
_TERRAFORM_REFERENCE_LABEL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class _TerraformBlock:
    file_path: str
    start: int
    end: int
    kind: str
    label: str
    text: str


@dataclass(frozen=True)
class _S3BucketMatch:
    block: _TerraformBlock
    assignment_name: str
    assignment_value: str


@dataclass(frozen=True)
class _S3ModuleMatch:
    block: _TerraformBlock
    assignment_name: str
    assignment_value: str


def _read(obj: Any, field: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(field, default)
    return getattr(obj, field, default)


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _is_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _clean_text(value: Any) -> str | None:
    value = _enum_value(value)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize(value: Any) -> str:
    text = _clean_text(value) or ""
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _get_resource_id(result: Any) -> str | None:
    return _clean_text(_read(result, "resource_id"))


def _index_phase1_ec2(ec2_phase1_results: list[Any]) -> dict[str, Any]:
    indexed: dict[str, Any] = {}
    for result in ec2_phase1_results:
        resource_id = _get_resource_id(result)
        if resource_id is not None:
            indexed[resource_id] = result
    return indexed


def _get_action(result: Any) -> str:
    action = _read(result, "phase2_action")
    if action is None:
        action = _read(result, "action")
    return str(_enum_value(action) or "").strip().upper()


def _phase2_allows_ec2_patch(result: Any) -> tuple[bool, str | None]:
    action = _get_action(result)
    if action not in _SUPPORTED_EC2_ACTIONS:
        return False, f"action {action or 'unknown'} is not supported by static EC2 patching"
    if _is_truthy(_read(result, "skip_write")):
        return False, "Phase 2 set skip_write"
    block_reason = _clean_text(_read(result, "block_reason") or _read(result, "guardrail_reason"))
    if block_reason:
        return False, f"Phase 2 blocked remediation: {block_reason}"
    for field in _MANUAL_REVIEW_FIELDS:
        if _is_truthy(_read(result, field)):
            return False, f"Phase 2 requires manual approval ({field})"
    for field in _ALLOWED_STATUS_FIELDS:
        status = _clean_text(_read(result, field))
        if status and status.upper().replace("-", "_").replace(" ", "_") in _BLOCKED_STATUSES:
            return False, f"Phase 2 status is {status}"
    return True, None


def _get_recommended_instance_type(result: Any) -> str | None:
    for field in _RECOMMENDED_TYPE_FIELDS:
        value = _clean_text(_read(result, field))
        if value:
            if not _INSTANCE_TYPE_VALUE_RE.match(value):
                return None
            return value
    return None


def _identity_values(phase1_result: Any | None, phase2_result: Any) -> list[str]:
    values: list[str] = []
    for source in (phase2_result, phase1_result):
        if source is None:
            continue
        for field in _IDENTITY_FIELDS:
            value = _clean_text(_read(source, field))
            if value:
                values.append(value)
    resource_id = _get_resource_id(phase2_result) or _get_resource_id(phase1_result)
    if resource_id:
        values.append(f"resource_id:{resource_id}")

    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        key = value.lower()
        if key not in seen:
            seen.add(key)
            unique.append(value)
    return unique


def _display_name(phase1_result: Any | None, phase2_result: Any) -> str:
    for source in (phase2_result, phase1_result):
        if source is None:
            continue
        for field in ("instance_name", "resource_name", "instance_id", "resource_id"):
            value = _clean_text(_read(source, field))
            if value:
                return value
    return "unknown resource"


def _find_block_end(content: str, open_brace_index: int) -> int | None:
    depth = 0
    in_string = False
    escape = False
    for index in range(open_brace_index, len(content)):
        char = content[index]
        if escape:
            escape = False
            continue
        if in_string:
            if char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index + 1
    return None


def _terraform_blocks(file_path: str, content: str) -> list[_TerraformBlock]:
    blocks: list[_TerraformBlock] = []
    for match in _BLOCK_HEADER_RE.finditer(content):
        open_brace_index = match.end() - 1
        end = _find_block_end(content, open_brace_index)
        if end is None:
            continue
        kind = "resource" if match.group(2) else "module"
        label = match.group(2) or match.group(3) or ""
        blocks.append(
            _TerraformBlock(
                file_path=file_path,
                start=match.start(),
                end=end,
                kind=kind,
                label=label,
                text=content[match.start() : end],
            )
        )
    return blocks


def _line_has_resource_id(block_text: str, resource_id: str) -> bool:
    pattern = re.compile(
        rf'(?m)^[ \t]*(resource_id|ResourceId|ResourceID)[ \t]*=[ \t]*"?{re.escape(resource_id)}"?[ \t]*(?:#.*)?$'
    )
    return bool(pattern.search(block_text))


def _block_matches_identity(block: _TerraformBlock, identities: list[str]) -> bool:
    normalized_label = _normalize(block.label)
    string_literals = {_normalize(value) for value in _STRING_LITERAL_RE.findall(block.text)}
    for identity in identities:
        if identity.startswith("resource_id:"):
            if _line_has_resource_id(block.text, identity.split(":", 1)[1]):
                return True
            continue
        normalized_identity = _normalize(identity)
        if not normalized_identity:
            continue
        if normalized_label == normalized_identity or normalized_identity in string_literals:
            return True
    return False


def _find_matching_terraform_block(
    tf_file_map: dict[str, str],
    identities: list[str],
) -> tuple[_TerraformBlock | None, str | None]:
    matches: list[_TerraformBlock] = []
    for file_path, content in tf_file_map.items():
        if not isinstance(content, str):
            continue
        for block in _terraform_blocks(file_path, content):
            if _block_matches_identity(block, identities):
                matches.append(block)

    if not matches:
        return None, "no matching Terraform aws_instance/module block found"
    if len(matches) > 1:
        paths = ", ".join(f"{match.file_path}:{match.label}" for match in matches)
        return None, f"ambiguous Terraform match ({paths})"
    return matches[0], None


def _replace_instance_type_in_block(
    block: _TerraformBlock,
    recommended_type: str,
) -> tuple[str | None, str | None]:
    matches = list(_INSTANCE_TYPE_RE.finditer(block.text))
    if not matches:
        return None, "matched Terraform block has no instance_type assignment"
    if len(matches) > 1:
        return None, "matched Terraform block has multiple instance_type assignments"

    match = matches[0]
    current_type = match.group(2)
    if current_type == recommended_type:
        return None, f"instance_type is already {recommended_type}"

    replacement = f'{match.group(1)}"{recommended_type}"{match.group(3)}'
    patched_block = block.text[: match.start()] + replacement + block.text[match.end() :]
    return patched_block, None


def _patch_ec2_downsize(
    *,
    phase1_result: Any | None,
    phase2_result: Any,
    file_contents: dict[str, str],
) -> tuple[ModifiedFile | None, str | None]:
    resource_name = _display_name(phase1_result, phase2_result)
    if _get_action(phase2_result) != "DOWNSIZE":
        return None, f"{resource_name}: action is not DOWNSIZE."
    allowed, reason = _phase2_allows_ec2_patch(phase2_result)
    if not allowed:
        return None, f"{resource_name}: Phase 2 did not approve automatic remediation ({reason})."

    recommended_type = _get_recommended_instance_type(phase2_result)
    if not recommended_type:
        return None, f"{resource_name}: no valid Phase 2 recommended instance type was found."

    identities = _identity_values(phase1_result, phase2_result)
    if not identities:
        return None, f"{resource_name}: no safe resource identity was available for Terraform matching."

    block, match_warning = _find_matching_terraform_block(file_contents, identities)
    if block is None:
        return None, f"{resource_name}: {match_warning}."

    patched_block, replace_warning = _replace_instance_type_in_block(block, recommended_type)
    if patched_block is None:
        return None, f"{resource_name}: {replace_warning}."

    original_content = file_contents[block.file_path]
    new_content = original_content[: block.start] + patched_block + original_content[block.end :]
    return ModifiedFile(file_path=block.file_path, new_content=new_content), None


def _ec2_instance_state_blocks(file_path: str, content: str) -> list[_TerraformBlock]:
    return _terraform_blocks_from_header(
        file_path=file_path,
        content=content,
        header_re=_EC2_INSTANCE_STATE_HEADER_RE,
        kind="aws_ec2_instance_state",
    )


def _terraform_string_expression(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _aws_instance_reference(block: _TerraformBlock) -> str | None:
    if block.kind != "resource":
        return None
    if not _TERRAFORM_REFERENCE_LABEL_RE.match(block.label):
        return None
    return f"aws_instance.{block.label}.id"


def _module_source(block: _TerraformBlock) -> str | None:
    if block.kind != "module":
        return None
    source_matches = _top_level_assignment_matches(block.text, "source")
    if len(source_matches) != 1:
        return None
    return source_matches[0][2].group(2).replace("\\", "/").strip("/")


def _is_module_source(block: _TerraformBlock, module_name: str) -> bool:
    source = _module_source(block)
    if source is None:
        return False
    normalized_module = module_name.strip("/")
    return source == normalized_module or source.endswith(f"/{normalized_module}")


def _is_ec2_module_block(block: _TerraformBlock) -> bool:
    return _is_module_source(block, "ec2")


def _literal_instance_id(phase1_result: Any | None, phase2_result: Any) -> str | None:
    for source in (phase2_result, phase1_result):
        if source is None:
            continue
        value = _clean_text(_read(source, "instance_id"))
        if value:
            return value
    return None


def _state_instance_id_expressions(block: _TerraformBlock) -> list[str]:
    return [match.group(1).strip() for match in _EC2_INSTANCE_STATE_INSTANCE_ID_RE.finditer(block.text)]


def _has_existing_ec2_stop_state(
    file_contents: dict[str, str],
    *,
    instance_id_expression: str,
) -> bool:
    quoted_expression = _terraform_string_expression(instance_id_expression)
    for file_path, content in file_contents.items():
        for block in _ec2_instance_state_blocks(file_path, content):
            expressions = _state_instance_id_expressions(block)
            if instance_id_expression in expressions or quoted_expression in expressions:
                return True
    return False


def _append_ec2_stop_state_block(
    *,
    content: str,
    resource_name: str,
    instance_id_expression: str,
    literal_instance_id: bool,
) -> str:
    state_resource_name = f"finops_stop_{_safe_terraform_name(resource_name)}"
    instance_id_value = (
        _terraform_string_expression(instance_id_expression)
        if literal_instance_id
        else instance_id_expression
    )
    state_block = f'''resource "aws_ec2_instance_state" "{state_resource_name}" {{
  instance_id = {instance_id_value}
  state       = "stopped"
}}
'''
    base = content.rstrip()
    separator = "\n\n" if base else ""
    return f"{base}{separator}{state_block}"


def _set_module_desired_state_stopped(block: _TerraformBlock) -> tuple[str | None, str | None]:
    if not _is_ec2_module_block(block):
        return None, "matched module is not sourced from an EC2 module"

    matches = _top_level_assignment_matches(block.text, "desired_state")
    if len(matches) > 1:
        return None, "matched EC2 module has multiple desired_state assignments"
    if matches:
        start, end, match = matches[0]
        current_value = match.group(2).strip().strip('"').lower()
        if current_value == "stopped":
            return None, "desired_state is already stopped"
        if current_value != "running":
            return None, f"desired_state is dynamic ({match.group(2).strip()})"
        replacement = f'{match.group(1)}"stopped"{match.group(3)}'
        return block.text[:start] + replacement + block.text[end:], None

    instance_type_matches = _top_level_assignment_matches(block.text, "instance_type")
    insert_at = instance_type_matches[0][1] if instance_type_matches else None
    if insert_at is None:
        source_matches = _top_level_assignment_matches(block.text, "source")
        insert_at = source_matches[0][1] if source_matches else None
    if insert_at is not None:
        return (
            block.text[:insert_at]
            + '\n  desired_state = "stopped"'
            + block.text[insert_at:],
            None,
        )

    header_end = block.text.find("{") + 1
    if header_end <= 0:
        return None, "matched EC2 module header could not be parsed"
    insertion = '\n  desired_state = "stopped"'
    if block.text[header_end : header_end + 1] not in {"\n", "\r"}:
        insertion += "\n"
    return block.text[:header_end] + insertion + block.text[header_end:], None


def _top_level_assignment_matches(block_text: str, assignment_name: str) -> list[tuple[int, int, re.Match[str]]]:
    matches: list[tuple[int, int, re.Match[str]]] = []
    depth = 0
    in_string = False
    escape = False
    offset = 0
    assignment_patterns = {
        "count": _COUNT_ASSIGNMENT_RE,
        "for_each": _FOR_EACH_ASSIGNMENT_RE,
        "enable_lifecycle": _ENABLE_LIFECYCLE_ASSIGNMENT_RE,
        "desired_state": _DESIRED_STATE_ASSIGNMENT_RE,
        "instance_type": _INSTANCE_TYPE_ASSIGNMENT_RE,
        "source": _SOURCE_ASSIGNMENT_RE,
    }
    assignment_re = assignment_patterns[assignment_name]

    for line in block_text.splitlines(keepends=True):
        if depth == 1:
            match = assignment_re.match(line)
            if match:
                matches.append((offset + match.start(), offset + match.end(), match))

        for char in line:
            if escape:
                escape = False
                continue
            if in_string:
                if char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
        offset += len(line)
    return matches


def _patch_ec2_stop(
    *,
    phase1_result: Any | None,
    phase2_result: Any,
    file_contents: dict[str, str],
) -> tuple[ModifiedFile | None, str | None]:
    resource_name = _display_name(phase1_result, phase2_result)
    if _get_action(phase2_result) != "STOP":
        return None, f"{resource_name}: action is not STOP."
    allowed, reason = _phase2_allows_ec2_patch(phase2_result)
    if not allowed:
        return None, f"{resource_name}: Phase 2 did not approve automatic remediation ({reason})."

    identities = _identity_values(phase1_result, phase2_result)
    if not identities:
        return None, f"{resource_name}: no safe resource identity was available for Terraform matching."

    block, match_warning = _find_matching_terraform_block(file_contents, identities)
    if block is None:
        return None, f"{resource_name}: {match_warning}."

    if block.kind == "module":
        patched_block, patch_warning = _set_module_desired_state_stopped(block)
        if patched_block is None:
            return None, f"{resource_name}: {patch_warning}."
        original_content = file_contents[block.file_path]
        new_content = original_content[: block.start] + patched_block + original_content[block.end :]
        return ModifiedFile(file_path=block.file_path, new_content=new_content), None

    instance_id_expression = _aws_instance_reference(block)
    literal_instance_id = False
    if instance_id_expression is None:
        literal_id = _literal_instance_id(phase1_result, phase2_result)
        if not literal_id:
            return None, (
                f"{resource_name}: matched Terraform block cannot be safely referenced "
                "and no literal instance_id was available."
            )
        instance_id_expression = literal_id
        literal_instance_id = True

    if _has_existing_ec2_stop_state(
        file_contents,
        instance_id_expression=instance_id_expression,
    ):
        return None, f"{resource_name}: aws_ec2_instance_state already manages this instance."

    original_content = file_contents[block.file_path]
    new_content = _append_ec2_stop_state_block(
        content=original_content,
        resource_name=resource_name,
        instance_id_expression=instance_id_expression,
        literal_instance_id=literal_instance_id,
    )
    return ModifiedFile(file_path=block.file_path, new_content=new_content), None


def _set_count_zero(block: _TerraformBlock) -> tuple[str | None, str | None]:
    if block.kind == "module":
        if not _is_ec2_module_block(block):
            return None, "TERMINATE is only supported for direct aws_instance resources and EC2 modules"
    elif block.kind != "resource":
        return None, "TERMINATE is only supported for direct aws_instance resources and EC2 modules"
    if _top_level_assignment_matches(block.text, "for_each"):
        return None, "matched Terraform block uses for_each"
    if _PREVENT_DESTROY_RE.search(block.text):
        return None, "matched Terraform block has lifecycle.prevent_destroy=true"

    count_matches = _top_level_assignment_matches(block.text, "count")
    if len(count_matches) > 1:
        return None, "matched Terraform block has multiple count assignments"
    if count_matches:
        start, end, match = count_matches[0]
        if match.group(2).strip() == "0":
            return None, "count is already 0"
        replacement = f"{match.group(1)}0{match.group(3)}"
        return block.text[:start] + replacement + block.text[end:], None

    if block.kind == "module":
        source_matches = _top_level_assignment_matches(block.text, "source")
        if source_matches:
            insert_at = source_matches[0][1]
            return block.text[:insert_at] + "\n  count = 0 # FinOps static TERMINATE" + block.text[insert_at:], None

    header_end = block.text.find("{") + 1
    if header_end <= 0:
        return None, "matched Terraform block header could not be parsed"
    insertion = "\n  count = 0 # FinOps static TERMINATE"
    if block.text[header_end : header_end + 1] not in {"\n", "\r"}:
        insertion += "\n"
    return block.text[:header_end] + insertion + block.text[header_end:], None


def _patch_ec2_terminate(
    *,
    phase1_result: Any | None,
    phase2_result: Any,
    file_contents: dict[str, str],
) -> tuple[ModifiedFile | None, str | None]:
    resource_name = _display_name(phase1_result, phase2_result)
    if _get_action(phase2_result) != "TERMINATE":
        return None, f"{resource_name}: action is not TERMINATE."
    allowed, reason = _phase2_allows_ec2_patch(phase2_result)
    if not allowed:
        return None, f"{resource_name}: Phase 2 did not approve automatic remediation ({reason})."

    identities = _identity_values(phase1_result, phase2_result)
    if not identities:
        return None, f"{resource_name}: no safe resource identity was available for Terraform matching."

    block, match_warning = _find_matching_terraform_block(file_contents, identities)
    if block is None:
        return None, f"{resource_name}: {match_warning}."

    patched_block, patch_warning = _set_count_zero(block)
    if patched_block is None:
        return None, f"{resource_name}: {patch_warning}."

    original_content = file_contents[block.file_path]
    new_content = original_content[: block.start] + patched_block + original_content[block.end :]
    return ModifiedFile(file_path=block.file_path, new_content=new_content), None


def _patch_ec2_result(
    *,
    phase1_result: Any | None,
    phase2_result: Any,
    file_contents: dict[str, str],
) -> tuple[ModifiedFile | None, str | None]:
    action = _get_action(phase2_result)
    if action == "DOWNSIZE":
        return _patch_ec2_downsize(
            phase1_result=phase1_result,
            phase2_result=phase2_result,
            file_contents=file_contents,
        )
    if action == "STOP":
        return _patch_ec2_stop(
            phase1_result=phase1_result,
            phase2_result=phase2_result,
            file_contents=file_contents,
        )
    if action == "TERMINATE":
        return _patch_ec2_terminate(
            phase1_result=phase1_result,
            phase2_result=phase2_result,
            file_contents=file_contents,
        )

    resource_name = _display_name(phase1_result, phase2_result)
    return None, f"{resource_name}: action {action or 'unknown'} is not supported by static EC2 patching."


def _terraform_blocks_from_header(
    *,
    file_path: str,
    content: str,
    header_re: re.Pattern[str],
    kind: str,
) -> list[_TerraformBlock]:
    blocks: list[_TerraformBlock] = []
    for match in header_re.finditer(content):
        open_brace_index = match.end() - 1
        end = _find_block_end(content, open_brace_index)
        if end is None:
            continue
        blocks.append(
            _TerraformBlock(
                file_path=file_path,
                start=match.start(),
                end=end,
                kind=kind,
                label=match.group(1),
                text=content[match.start() : end],
            )
        )
    return blocks


def _s3_bucket_blocks(file_path: str, content: str) -> list[_TerraformBlock]:
    return _terraform_blocks_from_header(
        file_path=file_path,
        content=content,
        header_re=_S3_BUCKET_HEADER_RE,
        kind="aws_s3_bucket",
    )


def _s3_lifecycle_blocks(file_path: str, content: str) -> list[_TerraformBlock]:
    return _terraform_blocks_from_header(
        file_path=file_path,
        content=content,
        header_re=_S3_LIFECYCLE_HEADER_RE,
        kind="aws_s3_bucket_lifecycle_configuration",
    )


def _get_s3_bucket_name(result: Any) -> str | None:
    for field in _S3_BUCKET_FIELDS:
        value = _clean_text(_read(result, field))
        if not value:
            continue
        if value.startswith("arn:aws:s3:::"):
            value = value.split(":::", 1)[1].split("/", 1)[0].strip()
        if value:
            return value
    return None


def _storage_class_token(value: Any) -> str:
    text = _clean_text(value) or ""
    return re.sub(r"[^A-Z0-9]+", "_", text.upper()).strip("_")


def _storage_class_from_text(value: Any) -> str | None:
    token = _storage_class_token(value)
    if not token:
        return None
    padded = f"_{token}_"
    for storage_class in sorted(_S3_ALLOWED_STORAGE_CLASSES, key=len, reverse=True):
        if token == storage_class or f"_{storage_class}_" in padded:
            return storage_class
    return None


def _unsupported_storage_class_from_text(value: Any) -> str | None:
    token = _storage_class_token(value)
    if not token:
        return None
    padded = f"_{token}_"
    for storage_class in sorted(_S3_UNSUPPORTED_STORAGE_CLASS_MARKERS, key=len, reverse=True):
        if token == storage_class or f"_{storage_class}_" in padded:
            return storage_class
    return None


def _get_s3_recommended_storage_class(result: Any) -> tuple[str | None, str | None]:
    for field in _S3_STORAGE_CLASS_FIELDS:
        value = _clean_text(_read(result, field))
        if not value:
            continue
        token = _storage_class_token(value)
        if token in _S3_ALLOWED_STORAGE_CLASSES:
            return token, None
        parsed = _storage_class_from_text(value)
        if parsed:
            return parsed, None
        return None, f"unsupported S3 storage class {value}"

    for field in _S3_RECOMMENDATION_FIELDS:
        value = _read(result, field)
        parsed = _storage_class_from_text(value)
        if parsed:
            return parsed, None
        unsupported = _unsupported_storage_class_from_text(value)
        if unsupported:
            return None, f"unsupported S3 storage class {unsupported}"
    return None, None


def _s3_requires_lifecycle_patch(result: Any) -> bool:
    if _get_s3_recommended_storage_class(result)[0]:
        return True
    for field in _S3_RECOMMENDATION_FIELDS:
        token = _storage_class_token(_read(result, field))
        if any(keyword in token for keyword in _S3_LIFECYCLE_KEYWORDS):
            return True
    return False


def _s3_bucket_assignments(block: _TerraformBlock) -> list[tuple[str, str]]:
    return [
        (match.group(1), match.group(2).strip())
        for match in _S3_BUCKET_ASSIGNMENT_RE.finditer(block.text)
        if match.group(2).strip()
    ]


def _s3_module_assignments(block: _TerraformBlock) -> list[tuple[str, str]]:
    return [
        (match.group(1), match.group(2).strip())
        for match in _S3_MODULE_BUCKET_ASSIGNMENT_RE.finditer(block.text)
        if match.group(2).strip()
    ]


def _is_s3_module_block(block: _TerraformBlock) -> bool:
    return _is_module_source(block, "s3")


def _format_s3_matches(matches: list[_S3BucketMatch]) -> str:
    return ", ".join(
        f"{match.block.file_path}:{match.block.label} ({match.assignment_name}={match.assignment_value})"
        for match in matches
    )


def _format_s3_module_matches(matches: list[_S3ModuleMatch]) -> str:
    return ", ".join(
        f"{match.block.file_path}:{match.block.label} ({match.assignment_name}={match.assignment_value})"
        for match in matches
    )


def _find_matching_s3_bucket_block(
    file_contents: dict[str, str],
    bucket_name: str,
) -> tuple[_S3BucketMatch | None, str | None]:
    exact_matches: list[_S3BucketMatch] = []
    prefix_matches: list[_S3BucketMatch] = []

    for file_path, content in file_contents.items():
        for block in _s3_bucket_blocks(file_path, content):
            for assignment_name, assignment_value in _s3_bucket_assignments(block):
                match = _S3BucketMatch(
                    block=block,
                    assignment_name=assignment_name,
                    assignment_value=assignment_value,
                )
                if assignment_name == "bucket" and assignment_value == bucket_name:
                    exact_matches.append(match)
                elif assignment_name == "bucket_prefix" and bucket_name.startswith(assignment_value):
                    prefix_matches.append(match)

    if len(exact_matches) == 1:
        return exact_matches[0], None
    if len(exact_matches) > 1:
        return None, f"ambiguous Terraform S3 bucket match ({_format_s3_matches(exact_matches)})"
    if len(prefix_matches) == 1:
        return prefix_matches[0], None
    if len(prefix_matches) > 1:
        return None, f"ambiguous Terraform S3 bucket_prefix match ({_format_s3_matches(prefix_matches)})"
    return None, "no matching Terraform aws_s3_bucket block found"


def _find_matching_s3_module_block(
    file_contents: dict[str, str],
    bucket_name: str,
) -> tuple[_S3ModuleMatch | None, str | None]:
    exact_matches: list[_S3ModuleMatch] = []
    prefix_matches: list[_S3ModuleMatch] = []

    for file_path, content in file_contents.items():
        for block in _terraform_blocks(file_path, content):
            if not _is_s3_module_block(block):
                continue
            for assignment_name, assignment_value in _s3_module_assignments(block):
                match = _S3ModuleMatch(
                    block=block,
                    assignment_name=assignment_name,
                    assignment_value=assignment_value,
                )
                if assignment_name != "bucket_prefix" and assignment_value == bucket_name:
                    exact_matches.append(match)
                elif assignment_name == "bucket_prefix" and bucket_name.startswith(assignment_value):
                    prefix_matches.append(match)

    if len(exact_matches) == 1:
        return exact_matches[0], None
    if len(exact_matches) > 1:
        return None, f"ambiguous Terraform S3 module match ({_format_s3_module_matches(exact_matches)})"
    if len(prefix_matches) == 1:
        return prefix_matches[0], None
    if len(prefix_matches) > 1:
        return None, f"ambiguous Terraform S3 module bucket_prefix match ({_format_s3_module_matches(prefix_matches)})"
    return None, "no matching Terraform S3 module block found"


def _has_existing_s3_lifecycle(
    file_contents: dict[str, str],
    *,
    bucket_name: str,
    terraform_resource_name: str,
) -> bool:
    resource_ref_re = re.compile(
        rf"\baws_s3_bucket\.{re.escape(terraform_resource_name)}\.id\b"
    )
    literal_bucket_re = re.compile(
        rf'(?m)^[ \t]*bucket[ \t]*=[ \t]*"{re.escape(bucket_name)}"[^\n\r]*$'
    )

    for file_path, content in file_contents.items():
        for block in _s3_lifecycle_blocks(file_path, content):
            if resource_ref_re.search(block.text) or literal_bucket_re.search(block.text):
                return True
    return False


def _safe_terraform_name(value: str) -> str:
    name = re.sub(r"[^a-z0-9]+", "_", value.lower())
    name = re.sub(r"_+", "_", name).strip("_")
    return name or "s3_bucket"


def _append_s3_lifecycle_block(
    *,
    content: str,
    bucket_match: _S3BucketMatch,
    bucket_name: str,
    storage_class: str,
) -> str:
    lifecycle_resource_name = f"finops_{_safe_terraform_name(bucket_name)}_lifecycle"
    lifecycle_block = f'''resource "aws_s3_bucket_lifecycle_configuration" "{lifecycle_resource_name}" {{
  bucket = aws_s3_bucket.{bucket_match.block.label}.id

  rule {{
    id     = "finops-transition-cold-objects"
    status = "Enabled"

    transition {{
      days          = 30
      storage_class = "{storage_class}"
    }}
  }}
}}
'''
    base = content.rstrip()
    separator = "\n\n" if base else ""
    return f"{base}{separator}{lifecycle_block}"


def _enable_s3_module_lifecycle(block: _TerraformBlock) -> tuple[str | None, str | None]:
    matches = _top_level_assignment_matches(block.text, "enable_lifecycle")
    if len(matches) > 1:
        return None, "matched Terraform S3 module has multiple enable_lifecycle assignments"
    if matches:
        start, end, match = matches[0]
        current_value = match.group(2).strip().lower()
        if current_value == "true":
            return None, "lifecycle is already enabled in the matched Terraform S3 module"
        if current_value != "false":
            return None, f"enable_lifecycle is dynamic ({match.group(2).strip()})"
        replacement = f"{match.group(1)}true{match.group(3)}"
        return block.text[:start] + replacement + block.text[end:], None

    source_matches = _top_level_assignment_matches(block.text, "source")
    if source_matches:
        insert_at = source_matches[0][1]
        return (
            block.text[:insert_at]
            + "\n  enable_lifecycle = true"
            + block.text[insert_at:],
            None,
        )

    header_end = block.text.find("{") + 1
    if header_end <= 0:
        return None, "matched Terraform S3 module header could not be parsed"
    insertion = "\n  enable_lifecycle = true"
    if block.text[header_end : header_end + 1] not in {"\n", "\r"}:
        insertion += "\n"
    return block.text[:header_end] + insertion + block.text[header_end:], None


def _patch_s3_module_lifecycle(
    *,
    bucket_name: str,
    file_contents: dict[str, str],
) -> tuple[ModifiedFile | None, str | None]:
    module_match, match_warning = _find_matching_s3_module_block(file_contents, bucket_name)
    if module_match is None:
        return None, f"{bucket_name}: {match_warning}."

    patched_block, patch_warning = _enable_s3_module_lifecycle(module_match.block)
    if patched_block is None:
        return None, f"{bucket_name}: {patch_warning}."

    original_content = file_contents[module_match.block.file_path]
    new_content = (
        original_content[: module_match.block.start]
        + patched_block
        + original_content[module_match.block.end :]
    )
    return ModifiedFile(file_path=module_match.block.file_path, new_content=new_content), None


def _patch_s3_lifecycle(
    *,
    s3_result: Any,
    file_contents: dict[str, str],
) -> tuple[ModifiedFile | None, str | None]:
    bucket_name = _get_s3_bucket_name(s3_result)
    if not bucket_name:
        return None, "unknown S3 bucket: missing bucket name for static lifecycle patch."

    display_name = bucket_name
    storage_class, storage_warning = _get_s3_recommended_storage_class(s3_result)
    if storage_warning:
        return None, f"{display_name}: {storage_warning}."
    if not _s3_requires_lifecycle_patch(s3_result):
        return None, f"{display_name}: S3 finding does not request a lifecycle/cold-storage transition."
    if storage_class is None:
        storage_class = "GLACIER"

    bucket_match, match_warning = _find_matching_s3_bucket_block(file_contents, bucket_name)
    if bucket_match is None:
        if match_warning == "no matching Terraform aws_s3_bucket block found":
            module_patch, module_warning = _patch_s3_module_lifecycle(
                bucket_name=bucket_name,
                file_contents=file_contents,
            )
            if module_patch is not None or module_warning is not None:
                return module_patch, module_warning
        return None, f"{display_name}: {match_warning}."
    terraform_resource_name = bucket_match.block.label
    if not _TERRAFORM_REFERENCE_LABEL_RE.match(terraform_resource_name):
        return None, (
            f"{display_name}: matched Terraform bucket resource name "
            f"{terraform_resource_name!r} cannot be safely referenced."
        )
    if _has_existing_s3_lifecycle(
        file_contents,
        bucket_name=bucket_name,
        terraform_resource_name=terraform_resource_name,
    ):
        return None, f"{display_name}: lifecycle configuration already exists; skipped S3 lifecycle patch."

    original_content = file_contents[bucket_match.block.file_path]
    new_content = _append_s3_lifecycle_block(
        content=original_content,
        bucket_match=bucket_match,
        bucket_name=bucket_name,
        storage_class=storage_class,
    )
    return ModifiedFile(file_path=bucket_match.block.file_path, new_content=new_content), None


def build_static_patch_plan(
    ec2_phase1_results: list[Any],
    ec2_phase2_results: list[Any],
    s3_phase1_results: list[Any],
    tf_file_map: dict[str, str],
) -> PatchPlan:
    """Build deterministic Terraform patches from Phase 1/2 decisions.

    EC2 DOWNSIZE, STOP, TERMINATE, and S3 lifecycle transitions are
    supported. Ambiguous Terraform mapping is intentionally skipped.
    """

    warnings: list[str] = []
    modified_by_path: dict[str, ModifiedFile] = {}
    file_contents = {path: content for path, content in tf_file_map.items() if isinstance(content, str)}
    phase1_by_resource_id = _index_phase1_ec2(ec2_phase1_results)

    for phase2_result in ec2_phase2_results:
        resource_id = _get_resource_id(phase2_result)
        phase1_result = phase1_by_resource_id.get(resource_id or "")
        patch, warning = _patch_ec2_result(
            phase1_result=phase1_result,
            phase2_result=phase2_result,
            file_contents=file_contents,
        )
        if warning:
            warnings.append(warning)
            continue
        if patch is None:
            continue
        file_contents[patch.file_path] = patch.new_content
        modified_by_path[patch.file_path] = patch

    for s3_result in s3_phase1_results:
        patch, warning = _patch_s3_lifecycle(
            s3_result=s3_result,
            file_contents=file_contents,
        )
        if warning:
            warnings.append(warning)
            continue
        if patch is None:
            continue
        file_contents[patch.file_path] = patch.new_content
        modified_by_path[patch.file_path] = patch

    return PatchPlan(
        modified_files=list(modified_by_path.values()),
        pr_title="Apply deterministic FinOps Terraform optimization",
        pr_description=(
            "This patch was generated from Phase 1 and Phase 2 outputs. "
            "LLM-generated Terraform is not used as the source of truth for "
            "this static patch."
        ),
        warnings=warnings,
    )
