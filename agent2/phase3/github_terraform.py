"""Fetch safe Terraform source context from a GitHub repository.

This module is intentionally standalone. Phase 3 integration is handled in a
later change; callers can resolve a redacted, size-bounded Terraform bundle.
"""

from __future__ import annotations

import base64
import os
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlparse

import requests


DEFAULT_MAX_BYTES = 500_000
GITHUB_API_BASE = "https://api.github.com"
_EXCLUDED_DIRS = {".terraform", ".git", "node_modules", "__pycache__"}
_SECRET_ASSIGNMENT = re.compile(
    r'^(?P<prefix>\s*"?(?:access_key|secret_key|token|password|client_secret|private_key)"?\s*=\s*)(?P<value>.*)$',
    re.IGNORECASE,
)
_HEREDOC_START = re.compile(r'^<<-?\s*"?([A-Za-z_][A-Za-z0-9_]*)"?')


@dataclass(frozen=True)
class TerraformSource:
    repo_url: str
    ref: str = "main"
    subdir: str = ""


@dataclass
class TerraformBundle:
    source: TerraformSource
    owner: str
    repo: str
    files: dict[str, str]
    prompt_bundle: str
    total_bytes: int
    warnings: list[str]


def parse_github_repo_url(repo_url: str) -> tuple[str, str]:
    """Return ``(owner, repo)`` for supported GitHub HTTPS and SSH URLs."""

    value = repo_url.strip()
    if value.startswith("git@github.com:"):
        repo_path = value.removeprefix("git@github.com:")
    else:
        parsed = urlparse(value)
        if parsed.scheme != "https" or parsed.netloc.lower() != "github.com":
            raise ValueError(f"Unsupported GitHub repository URL: {repo_url}")
        repo_path = parsed.path.lstrip("/")

    repo_path = repo_path.rstrip("/")
    if repo_path.endswith(".git"):
        repo_path = repo_path[:-4]
    parts = repo_path.split("/")
    if len(parts) != 2 or not all(parts):
        raise ValueError(f"Invalid GitHub repository URL: {repo_url}")
    return parts[0], parts[1]


def should_include_tf_path(path: str, subdir: str = "") -> bool:
    """Return whether a repository path is safe Terraform source input."""

    normalized_path = path.replace("\\", "/").strip("/")
    parts = [part for part in normalized_path.split("/") if part]
    if not parts or any(part in {".", ".."} for part in parts):
        return False
    if any(part in _EXCLUDED_DIRS for part in parts):
        return False

    filename = parts[-1]
    if filename == "terraform.tfstate" or filename.endswith(".tfstate") or filename.endswith(".tfstate.backup"):
        return False
    if not filename.endswith(".tf"):
        return False

    normalized_subdir = subdir.replace("\\", "/").strip("/")
    if not normalized_subdir:
        return True
    subdir_parts = [part for part in normalized_subdir.split("/") if part]
    if any(part in {".", ".."} for part in subdir_parts):
        return False
    return parts[: len(subdir_parts)] == subdir_parts and len(parts) > len(subdir_parts)


def redact_terraform_secrets(content: str) -> str:
    """Redact direct Terraform assignments for common credential names."""

    redacted_lines: list[str] = []
    heredoc_delimiter: str | None = None
    for line in content.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        newline = line[len(body) :]
        if heredoc_delimiter is not None:
            if body.strip() == heredoc_delimiter:
                heredoc_delimiter = None
            continue

        match = _SECRET_ASSIGNMENT.match(body)
        if not match:
            redacted_lines.append(line)
            continue

        value = match.group("value")
        heredoc_match = _HEREDOC_START.match(value.strip())
        if heredoc_match:
            heredoc_delimiter = heredoc_match.group(1)
        suffix = ""
        inline_comment = None if heredoc_match else re.search(r"\s+(?://|#).*$", value)
        if inline_comment:
            suffix = inline_comment.group(0)
        redacted_lines.append(f'{match.group("prefix")}"***REDACTED***"{suffix}{newline}')
    return "".join(redacted_lines)


def _github_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _get_json(url: str, *, params: dict[str, str] | None = None) -> Any:
    try:
        response = requests.get(url, headers=_github_headers(), params=params, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        raise RuntimeError(f"GitHub API request failed: {exc}") from exc
    except ValueError as exc:
        raise RuntimeError("GitHub API returned an invalid JSON response.") from exc


def list_repo_files(owner: str, repo: str, ref: str) -> list[dict[str, Any]]:
    """Retrieve the repository tree recursively from GitHub."""

    encoded_ref = quote(ref, safe="")
    payload = _get_json(
        f"{GITHUB_API_BASE}/repos/{quote(owner, safe='')}/{quote(repo, safe='')}/git/trees/{encoded_ref}",
        params={"recursive": "1"},
    )
    if not isinstance(payload, dict) or not isinstance(payload.get("tree"), list):
        raise RuntimeError("GitHub tree response did not contain a file tree.")
    if payload.get("truncated"):
        raise RuntimeError("GitHub tree response was truncated; Terraform source cannot be resolved safely.")
    return payload["tree"]


def fetch_file_content(owner: str, repo: str, path: str, ref: str) -> str:
    """Download and decode one UTF-8 file from the GitHub Contents API."""

    encoded_path = quote(path, safe="/")
    payload = _get_json(
        f"{GITHUB_API_BASE}/repos/{quote(owner, safe='')}/{quote(repo, safe='')}/contents/{encoded_path}",
        params={"ref": ref},
    )
    if not isinstance(payload, dict) or payload.get("encoding") != "base64" or not isinstance(payload.get("content"), str):
        raise RuntimeError(f"GitHub content response for '{path}' is not a base64 file.")
    try:
        decoded = base64.b64decode(payload["content"], validate=False)
        return decoded.decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise RuntimeError(f"Terraform file '{path}' could not be decoded as UTF-8.") from exc


def build_prompt_bundle(files: dict[str, str]) -> str:
    """Format Terraform files for injection into a future LLM prompt."""

    sections = []
    for path in sorted(files):
        content = files[path].rstrip("\r\n")
        sections.append(f"### FILE: {path}\n```hcl\n{content}\n```")
    return "\n\n".join(sections)


def _max_bundle_bytes(warnings: list[str]) -> int:
    configured = os.environ.get("PHASE3_TERRAFORM_MAX_BYTES", str(DEFAULT_MAX_BYTES))
    try:
        maximum = int(configured)
        if maximum < 0:
            raise ValueError
        return maximum
    except ValueError:
        warnings.append(
            f"Invalid PHASE3_TERRAFORM_MAX_BYTES value; using default limit of {DEFAULT_MAX_BYTES} bytes."
        )
        return DEFAULT_MAX_BYTES


def resolve_terraform_bundle(source: TerraformSource) -> TerraformBundle:
    """Fetch, redact, and bundle eligible Terraform files from ``source``."""

    owner, repo = parse_github_repo_url(source.repo_url)
    warnings: list[str] = []
    max_bytes = _max_bundle_bytes(warnings)
    files: dict[str, str] = {}

    entries = sorted(
        list_repo_files(owner, repo, source.ref),
        key=lambda item: str(item.get("path", "")) if isinstance(item, dict) else "",
    )
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        path = entry.get("path")
        if entry.get("type") != "blob" or not isinstance(path, str):
            continue
        if not should_include_tf_path(path, source.subdir):
            continue
        try:
            redacted_content = redact_terraform_secrets(fetch_file_content(owner, repo, path, source.ref))
        except RuntimeError as exc:
            warnings.append(f"Unable to fetch Terraform file '{path}': {exc}")
            continue

        candidate_files = {**files, path: redacted_content}
        candidate_bundle = build_prompt_bundle(candidate_files)
        if len(candidate_bundle.encode("utf-8")) > max_bytes:
            warnings.append(
                f"Terraform prompt bundle exceeded PHASE3_TERRAFORM_MAX_BYTES={max_bytes}; "
                "remaining files were not included."
            )
            break
        files[path] = redacted_content

    prompt_bundle = build_prompt_bundle(files)
    return TerraformBundle(
        source=source,
        owner=owner,
        repo=repo,
        files=files,
        prompt_bundle=prompt_bundle,
        total_bytes=len(prompt_bundle.encode("utf-8")),
        warnings=warnings,
    )
