#!/usr/bin/env python3
"""Task storage helpers for by-harness.

V3 stores each task in its own JSON file under task-harness/tasks. Older
bucket and feature_list files remain readable for compatibility.
"""

from __future__ import annotations

import glob
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

HARNESS_DIR_NAME = ".harness"
TASK_SCHEMA = "by-harness.task.v3"
DEFAULT_TASK_GLOBS = ("task-harness/tasks/*.json", "task-harness/tasks/**/*.json")


class HarnessJsonError(RuntimeError):
    """Raised when harness JSON storage cannot be read or parsed."""


@dataclass(frozen=True)
class TaskEntry:
    feature: dict[str, Any]
    source_path: Path
    source_kind: str
    array_index: int | None = None


def detect_workspace_dir(target_dir: Path) -> Path:
    harness_dir = target_dir / HARNESS_DIR_NAME
    if harness_dir.exists():
        return harness_dir
    return target_dir


def repo_root_from_workspace(workspace_dir: Path) -> Path:
    return workspace_dir.parent if workspace_dir.name == HARNESS_DIR_NAME else workspace_dir


def load_json(path: Path) -> Any:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HarnessJsonError(f"failed to read JSON: {path}: {exc}") from exc
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise HarnessJsonError(f"invalid JSON: {path}:{exc.lineno}:{exc.colno}: {exc.msg}") from exc


def dump_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def resolve_path(workspace_dir: Path, raw_path: str) -> Path:
    raw = str(raw_path or "").strip()
    root = repo_root_from_workspace(workspace_dir)
    if not raw:
        return root / "__missing_path__"

    path = Path(raw)
    if path.is_absolute():
        return path

    candidates = [workspace_dir / raw, root / raw]
    if raw.startswith(f"{HARNESS_DIR_NAME}/"):
        stripped = raw[len(HARNESS_DIR_NAME) + 1 :]
        candidates.append(workspace_dir / stripped)
        candidates.append(root / stripped)

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def normalize_feature_id(feature_id: str) -> str:
    text = str(feature_id or "").strip().lower()
    match = re.match(r"^([a-z0-9_-]+)-0*(\d+)$", text)
    if match:
        return f"{match.group(1)}-{int(match.group(2))}"
    return text


def normalize_lookup_value(value: str) -> str:
    text = str(value or "").strip().lower().replace("\\", "/")
    if "/" in text:
        text = text.rsplit("/", 1)[-1]
    if text.endswith(".json"):
        text = text[:-5]
    text = text.replace("｜", "-")
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"-{2,}", "-", text)
    return normalize_feature_id(text.strip("-"))


def display_label(feature: dict[str, Any]) -> str:
    display_name = str(feature.get("display_name", "")).strip()
    if display_name:
        return display_name
    display_id = str(feature.get("display_id", "")).strip()
    title = str(feature.get("title", "") or feature.get("description", "")).strip()
    if display_id and title:
        return f"{display_id} - {title}"
    return str(feature.get("id", "unknown")).strip() or "unknown"


def feature_lookup_aliases(feature: dict[str, Any], source_path: Path | None = None) -> set[str]:
    aliases: set[str] = set()
    for key in (
        "id",
        "task_id",
        "display_id",
        "local_display_id",
        "display_name",
        "title",
        "batch_id",
    ):
        value = str(feature.get(key, "") or "").strip()
        if value:
            aliases.add(value)

    task_no = feature.get("task_no")
    try:
        task_no_int = int(task_no)
    except (TypeError, ValueError):
        task_no_int = 0
    if task_no_int > 0:
        aliases.update({str(task_no_int), f"{task_no_int:03d}", f"T{task_no_int}", f"T{task_no_int:03d}"})

    batch_no = feature.get("batch_no")
    try:
        batch_no_int = int(batch_no)
    except (TypeError, ValueError):
        batch_no_int = 0
    if batch_no_int > 0 and task_no_int > 0:
        aliases.update(
            {
                f"B{batch_no_int}-T{task_no_int}",
                f"B{batch_no_int:03d}-T{task_no_int:03d}",
                f"B{batch_no_int:03d}/T{task_no_int:03d}",
                f"{batch_no_int}-{task_no_int}",
                f"{batch_no_int:03d}-{task_no_int:03d}",
            }
        )

    if source_path is not None:
        aliases.update({source_path.name, source_path.stem})
        if source_path.parent.name:
            aliases.add(f"{source_path.parent.name}/{source_path.stem}")
    return {normalize_lookup_value(alias) for alias in aliases if normalize_lookup_value(alias)}


def _task_globs_from_index(workspace_dir: Path) -> list[str]:
    index_path = workspace_dir / "task-harness" / "index.json"
    if not index_path.exists():
        return list(DEFAULT_TASK_GLOBS)
    try:
        index = load_json(index_path)
    except HarnessJsonError:
        return list(DEFAULT_TASK_GLOBS)
    if not isinstance(index, dict):
        return list(DEFAULT_TASK_GLOBS)

    globs: list[str] = []
    raw_globs = index.get("task_globs", [])
    if isinstance(raw_globs, list) and raw_globs:
        globs = [str(item) for item in raw_globs if str(item).strip()]
    for pattern in DEFAULT_TASK_GLOBS:
        if pattern not in globs:
            globs.append(pattern)
    return globs


def task_file_paths(workspace_dir: Path) -> list[Path]:
    paths: list[Path] = []
    seen: set[str] = set()
    for pattern in _task_globs_from_index(workspace_dir):
        raw = str(pattern or "").strip()
        if not raw:
            continue
        base_pattern = str(resolve_path(workspace_dir, raw))
        for match in glob.glob(base_pattern, recursive=True):
            path = Path(match)
            key = str(path.resolve())
            if key not in seen and path.is_file():
                seen.add(key)
                paths.append(path)
    return sorted(paths)


def bucket_file_paths(workspace_dir: Path) -> list[Path]:
    index_path = workspace_dir / "task-harness" / "index.json"
    paths: list[Path] = []
    if index_path.exists():
        index = load_json(index_path)
        if isinstance(index, dict):
            buckets = index.get("legacy_buckets", index.get("buckets", []))
            if isinstance(buckets, list):
                for bucket in buckets:
                    if not isinstance(bucket, dict):
                        continue
                    raw_path = str(bucket.get("path", "")).strip()
                    if raw_path:
                        paths.append(resolve_path(workspace_dir, raw_path))

    paths.extend(
        [
            workspace_dir / "feature_list.json",
            workspace_dir / "task-harness" / "features" / "backlog-core.json",
        ]
    )

    deduped: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        if key not in seen:
            seen.add(key)
            deduped.append(path)
    return deduped


def _entries_from_task_file(path: Path) -> list[TaskEntry]:
    data = load_json(path)
    if not isinstance(data, dict):
        return []
    if isinstance(data.get("features"), list):
        entries: list[TaskEntry] = []
        for idx, feature in enumerate(data["features"]):
            if isinstance(feature, dict):
                entries.append(TaskEntry(dict(feature), path, "bucket", idx))
        return entries
    if data.get("id") or data.get("description"):
        return [TaskEntry(dict(data), path, "single", None)]
    return []


def load_task_entries(workspace_dir: Path) -> list[TaskEntry]:
    entries: list[TaskEntry] = []
    seen_ids: set[str] = set()

    for path in task_file_paths(workspace_dir):
        for entry in _entries_from_task_file(path):
            feature_id = str(entry.feature.get("id", "")).strip()
            key = normalize_feature_id(feature_id)
            if key and key in seen_ids:
                continue
            if key:
                seen_ids.add(key)
            entries.append(entry)

    for path in bucket_file_paths(workspace_dir):
        if not path.exists():
            continue
        for entry in _entries_from_task_file(path):
            feature_id = str(entry.feature.get("id", "")).strip()
            key = normalize_feature_id(feature_id)
            if key and key in seen_ids:
                continue
            if key:
                seen_ids.add(key)
            entries.append(entry)
    return entries


def load_all_features(workspace_dir: Path) -> list[dict[str, Any]]:
    return [entry.feature for entry in load_task_entries(workspace_dir)]


def find_entry(workspace_dir: Path, feature_id: str) -> TaskEntry | None:
    if not feature_id:
        return None
    target_raw = str(feature_id).strip()
    target_norm = normalize_lookup_value(target_raw)
    entries = load_task_entries(workspace_dir)
    for entry in entries:
        if str(entry.feature.get("id", "")).strip() == target_raw:
            return entry
    for entry in entries:
        if target_norm in feature_lookup_aliases(entry.feature, entry.source_path):
            return entry
    return None


def write_feature_update(entry: TaskEntry, mutator: Callable[[dict[str, Any]], bool]) -> bool:
    data = load_json(entry.source_path)
    changed = False
    if entry.source_kind == "single":
        if not isinstance(data, dict):
            return False
        changed = mutator(data)
    else:
        if not isinstance(data, dict) or not isinstance(data.get("features"), list):
            return False
        target_id = str(entry.feature.get("id", ""))
        for feature in data["features"]:
            if not isinstance(feature, dict):
                continue
            if str(feature.get("id", "")) == target_id:
                changed = mutator(feature)
                break
    if changed:
        dump_json(entry.source_path, data)
    return changed
