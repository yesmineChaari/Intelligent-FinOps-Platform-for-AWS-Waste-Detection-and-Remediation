"""Safely apply Phase 3 Terraform patch plans to an existing local directory."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

from .patch_schema import PatchPlan


DEFAULT_PATCH_MAX_FILES = 10
_BLOCKED_PATH_PARTS = {".terraform", ".git"}
_TRUE_VALUES = {"1", "true", "yes"}


@dataclass
class LocalPatchResult:
    applied: bool
    repo_dir: str | None
    changed_files: list[str]
    warnings: list[str]
    errors: list[str]


def _env_enabled(name: str) -> bool:
    return os.environ.get(name, "0").strip().lower() in _TRUE_VALUES


def _patch_max_files() -> int:
    value = os.environ.get("PHASE3_PATCH_MAX_FILES", str(DEFAULT_PATCH_MAX_FILES))
    try:
        maximum = int(value)
        if maximum < 0:
            raise ValueError
        return maximum
    except ValueError:
        return DEFAULT_PATCH_MAX_FILES


def _normalize_repo_path(file_path: str) -> str:
    normalized = file_path.strip().replace("\\", "/")
    if not normalized or normalized.endswith("/"):
        raise ValueError(f"Invalid Terraform file path: {file_path}")
    if PurePosixPath(normalized).is_absolute() or PureWindowsPath(file_path).is_absolute():
        raise ValueError(f"Absolute file path is not allowed: {file_path}")

    path = PurePosixPath(normalized)
    if ".." in path.parts:
        raise ValueError(f"Path traversal is not allowed: {file_path}")
    if any(part.lower() in _BLOCKED_PATH_PARTS for part in path.parts):
        raise ValueError(f"Blocked Terraform file path: {file_path}")
    if not path.parts or path.as_posix() == ".":
        raise ValueError(f"Invalid Terraform file path: {file_path}")
    return path.as_posix()


def _validate_patch_plan(
    plan: PatchPlan,
    original_files: dict[str, str],
    *,
    allow_new_files: bool,
) -> list[str]:
    errors: list[str] = []
    if not plan.modified_files:
        return ["No modified files to apply."]

    max_files = _patch_max_files()
    if len(plan.modified_files) > max_files:
        errors.append(f"Too many modified files: {len(plan.modified_files)} > {max_files}")

    normalized_original_files: set[str] = set()
    for original_path in original_files:
        try:
            normalized_original_files.add(_normalize_repo_path(original_path))
        except ValueError:
            continue

    for modified_file in plan.modified_files:
        file_path = modified_file.file_path
        try:
            normalized_path = _normalize_repo_path(file_path)
        except ValueError as exc:
            errors.append(str(exc))
            continue

        lower_path = normalized_path.lower()
        filename = PurePosixPath(lower_path).name
        if (
            filename == "terraform.tfstate"
            or lower_path.endswith(".tfstate")
            or lower_path.endswith(".tfstate.backup")
        ):
            errors.append(f"Terraform state file is not allowed: {file_path}")
            continue
        if not lower_path.endswith(".tf"):
            errors.append(f"Only .tf files may be modified: {file_path}")
            continue
        if not isinstance(modified_file.new_content, str) or not modified_file.new_content.strip():
            errors.append(f"New content is empty for file: {file_path}")
        if not allow_new_files and normalized_path not in normalized_original_files:
            errors.append(f"File not in original Terraform bundle: {file_path}")

    return errors


def validate_patch_plan(plan: PatchPlan, original_files: dict[str, str]) -> list[str]:
    """Validate a patch plan using environment-configured new-file policy."""

    return _validate_patch_plan(
        plan,
        original_files,
        allow_new_files=_env_enabled("PHASE3_ALLOW_NEW_TF_FILES"),
    )


def _resolve_safe_repo_path(repo_dir: Path, file_path: str) -> Path:
    """Resolve a repository-relative file path without permitting escape."""

    normalized_path = _normalize_repo_path(file_path)
    resolved_repo = repo_dir.resolve()
    target = (resolved_repo / Path(*PurePosixPath(normalized_path).parts)).resolve()
    try:
        target.relative_to(resolved_repo)
    except ValueError as exc:
        raise ValueError(f"File path escapes repository directory: {file_path}") from exc
    return target


def apply_patch_plan_to_directory(
    repo_dir: Path,
    plan: PatchPlan,
    original_files: dict[str, str],
    allow_new_files: bool | None = None,
) -> list[str]:
    """Write each patch file only after the full plan passes validation."""

    allow_new = _env_enabled("PHASE3_ALLOW_NEW_TF_FILES") if allow_new_files is None else allow_new_files
    errors = _validate_patch_plan(plan, original_files, allow_new_files=allow_new)
    if errors:
        raise ValueError("\n".join(errors))

    if not repo_dir.is_dir():
        raise FileNotFoundError(f"Repository directory does not exist: {repo_dir}")

    targets: list[tuple[str, Path, str]] = []
    for modified_file in plan.modified_files:
        normalized_path = _normalize_repo_path(modified_file.file_path)
        target = _resolve_safe_repo_path(repo_dir, normalized_path)
        if not target.exists() and not allow_new:
            raise FileNotFoundError(f"Terraform file does not exist in local repository: {normalized_path}")
        targets.append((normalized_path, target, modified_file.new_content))

    changed_files: list[str] = []
    for normalized_path, target, new_content in targets:
        if allow_new:
            target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(new_content.rstrip("\r\n") + "\n", encoding="utf-8")
        changed_files.append(normalized_path)
    return changed_files


def _command_warning(command_name: str, result: subprocess.CompletedProcess[str]) -> str | None:
    if result.returncode == 0:
        return None
    output = (result.stderr or result.stdout or "").strip()
    detail = f": {output}" if output else f" (exit code {result.returncode})"
    return f"{command_name} failed{detail}"


def run_terraform_fmt(repo_dir: Path) -> str | None:
    """Run ``terraform fmt -recursive`` and report failures as warnings."""

    try:
        result = subprocess.run(
            ["terraform", "fmt", "-recursive"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"terraform fmt could not run: {exc}"
    return _command_warning("terraform fmt", result)


def run_terraform_validate(repo_dir: Path) -> str | None:
    """Optionally initialize and validate Terraform without a backend."""

    if not _env_enabled("PHASE3_RUN_TERRAFORM_VALIDATE"):
        return None

    try:
        init_result = subprocess.run(
            ["terraform", "init", "-backend=false"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        warning = _command_warning("terraform init -backend=false", init_result)
        if warning:
            return warning

        validate_result = subprocess.run(
            ["terraform", "validate"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        return _command_warning("terraform validate", validate_result)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"terraform validate could not run: {exc}"


def apply_patch_plan_locally(
    repo_dir: Path,
    plan: PatchPlan,
    original_files: dict[str, str],
) -> LocalPatchResult:
    """Apply patches and perform non-fatal Terraform formatting/validation checks."""

    try:
        changed_files = apply_patch_plan_to_directory(repo_dir, plan, original_files)
    except Exception as exc:
        return LocalPatchResult(
            applied=False,
            repo_dir=str(repo_dir),
            changed_files=[],
            warnings=[],
            errors=[str(exc)],
        )

    warnings = []
    for warning in (run_terraform_fmt(repo_dir), run_terraform_validate(repo_dir)):
        if warning:
            warnings.append(warning)
    return LocalPatchResult(
        applied=True,
        repo_dir=str(repo_dir),
        changed_files=changed_files,
        warnings=warnings,
        errors=[],
    )
