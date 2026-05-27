"""Targeted Terraform edits for EC2 instance type recommendations."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Ec2ModuleBlock:
    file_path: str
    module_name: str
    instance_id: str
    instance_type: str | None
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class Ec2InstanceTypeUpdate:
    instance_id: str
    old_type: str
    new_type: str
    file_path: str
    module_name: str


def _normalize_instance_id(value: str) -> str:
    return value.strip().lower().replace("_", "-")


def _module_end(text: str, open_brace_index: int) -> int | None:
    depth = 0
    in_string = False
    escaped = False
    in_line_comment = False

    for index in range(open_brace_index, len(text)):
        char = text[index]
        next_char = text[index + 1] if index + 1 < len(text) else ""

        if in_line_comment:
            if char in "\r\n":
                in_line_comment = False
            continue

        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == "#":
            in_line_comment = True
            continue
        if char == "/" and next_char == "/":
            in_line_comment = True
            continue
        if char == '"':
            in_string = True
            continue
        if char == "{":
            depth += 1
            continue
        if char == "}":
            depth -= 1
            if depth == 0:
                return index + 1

    return None


def find_main_tf_path(tf_file_map: dict[str, str]) -> str | None:
    """Return the most likely main.tf path from a Terraform file map."""

    if "main.tf" in tf_file_map:
        return "main.tf"

    main_tf_paths = []
    for path in tf_file_map:
        normalized = path.replace("\\", "/")
        if normalized.endswith("/main.tf") and "/modules/" not in f"/{normalized}":
            main_tf_paths.append(path)
    main_tf_paths = sorted(main_tf_paths)
    return main_tf_paths[0] if main_tf_paths else None


def extract_ec2_module_blocks(tf_file_map: dict[str, str]) -> list[Ec2ModuleBlock]:
    """Extract module blocks from main.tf that look like EC2 instance modules."""

    main_tf_path = find_main_tf_path(tf_file_map)
    if not main_tf_path:
        return []

    content = tf_file_map.get(main_tf_path, "")
    blocks: list[Ec2ModuleBlock] = []
    for match in re.finditer(r'(?m)^[ \t]*module\s+"([^"]+)"\s*\{', content):
        open_brace_index = content.find("{", match.end() - 1)
        end = _module_end(content, open_brace_index)
        if end is None:
            continue

        block_text = content[match.start() : end]
        source_match = re.search(r'(?m)^[ \t]*source\s*=\s*"([^"]+)"', block_text)
        source = source_match.group(1) if source_match else ""
        if "ec2" not in source.lower():
            continue

        instance_id_match = re.search(r'(?m)^[ \t]*instance_id\s*=\s*"([^"]+)"', block_text)
        if not instance_id_match:
            continue

        instance_type_match = re.search(r'(?m)^[ \t]*instance_type\s*=\s*"([^"]+)"', block_text)
        blocks.append(
            Ec2ModuleBlock(
                file_path=main_tf_path,
                module_name=match.group(1),
                instance_id=instance_id_match.group(1),
                instance_type=instance_type_match.group(1) if instance_type_match else None,
                start=match.start(),
                end=end,
                text=block_text,
            )
        )

    return blocks


def find_ec2_module_for_instance(
    tf_file_map: dict[str, str],
    instance_id: str,
) -> Ec2ModuleBlock | None:
    """Find the EC2 module matching an instance id or normalized module name."""

    wanted = _normalize_instance_id(str(instance_id))
    for block in extract_ec2_module_blocks(tf_file_map):
        if _normalize_instance_id(block.instance_id) == wanted:
            return block
        if _normalize_instance_id(block.module_name) == wanted:
            return block
    return None


def scoped_terraform_for_instance(tf_file_map: dict[str, str], instance_id: str) -> str | None:
    block = find_ec2_module_for_instance(tf_file_map, instance_id)
    if not block:
        return None
    return block.text


def _replace_instance_type(block_text: str, new_type: str) -> str | None:
    pattern = re.compile(r'(?m)^([ \t]*instance_type\s*=\s*)"([^"]+)"')
    return pattern.sub(rf'\1"{new_type}"', block_text, count=1)


def apply_ec2_instance_type_updates(
    tf_file_map: dict[str, str],
    requested_updates: dict[str, str],
) -> tuple[str | None, list[Ec2InstanceTypeUpdate], list[str]]:
    """Patch main.tf by replacing only instance_type for matching EC2 modules."""

    main_tf_path = find_main_tf_path(tf_file_map)
    if not main_tf_path:
        return None, [], ["No main.tf found in Terraform source; cannot patch EC2 instance types."]

    original = tf_file_map.get(main_tf_path, "")
    blocks = extract_ec2_module_blocks(tf_file_map)
    blocks_by_id: dict[str, Ec2ModuleBlock] = {}
    for block in blocks:
        blocks_by_id[_normalize_instance_id(block.instance_id)] = block
        blocks_by_id[_normalize_instance_id(block.module_name)] = block

    warnings: list[str] = []
    changed: list[Ec2InstanceTypeUpdate] = []
    replacements: list[tuple[int, int, str]] = []
    seen_blocks: set[tuple[int, int]] = set()

    for instance_id, new_type in requested_updates.items():
        normalized_id = _normalize_instance_id(str(instance_id))
        new_type = str(new_type).strip()
        if not new_type:
            warnings.append(f"Skipping {instance_id}: recommended instance type is empty.")
            continue

        block = blocks_by_id.get(normalized_id)
        if not block:
            warnings.append(f"Skipping {instance_id}: no matching EC2 module block found in {main_tf_path}.")
            continue
        if not block.instance_type:
            warnings.append(f"Skipping {instance_id}: matching module has no instance_type assignment.")
            continue
        if block.instance_type == new_type:
            warnings.append(f"Skipping {instance_id}: instance_type is already {new_type}.")
            continue
        if (block.start, block.end) in seen_blocks:
            warnings.append(f"Skipping {instance_id}: duplicate update targets module {block.module_name}.")
            continue

        patched_block = _replace_instance_type(block.text, new_type)
        if patched_block is None or patched_block == block.text:
            warnings.append(f"Skipping {instance_id}: failed to replace instance_type.")
            continue

        seen_blocks.add((block.start, block.end))
        replacements.append((block.start, block.end, patched_block))
        changed.append(
            Ec2InstanceTypeUpdate(
                instance_id=block.instance_id,
                old_type=block.instance_type,
                new_type=new_type,
                file_path=main_tf_path,
                module_name=block.module_name,
            )
        )

    if not replacements:
        return original, [], warnings

    patched = original
    for start, end, patched_block in sorted(replacements, key=lambda item: item[0], reverse=True):
        patched = patched[:start] + patched_block + patched[end:]

    return patched, changed, warnings


def parsed_decision_action(parsed: dict[str, Any], instance_id: str) -> str | None:
    """Read the LLM action from either single-instance or multi-instance output."""

    instances = parsed.get("instances")
    if isinstance(instances, dict):
        normalized_id = _normalize_instance_id(str(instance_id))
        for key, item in instances.items():
            if _normalize_instance_id(str(key)) != normalized_id or not isinstance(item, dict):
                continue
            decision = item.get("decision_summary")
            if isinstance(decision, dict):
                action = decision.get("action")
                return str(action) if action else None

    decision = parsed.get("decision_summary")
    if isinstance(decision, dict):
        action = decision.get("action")
        return str(action) if action else None
    return None
