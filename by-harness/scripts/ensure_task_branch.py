#!/usr/bin/env python3
"""Auto-select next task in current branch (no branch switching)."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from task_store import display_label, feature_lookup_aliases, load_task_entries, normalize_lookup_value, write_feature_update

HARNESS_DIR_NAME = ".harness"
SESSION_MODE_SOFT = "soft_reset"
SESSION_MODE_HARD = "hard_new_session"

STOP_WORDS = {
    "处理",
    "继续",
    "推进",
    "优化",
    "修复",
    "相关",
    "问题",
    "任务",
    "实现",
    "开发",
    "本次",
    "今天",
    "这个",
    "那个",
    "一下",
    "进行",
    "开始",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Auto-select next feature in current branch.")
    parser.add_argument("--target-dir", default=".", help="repository root")
    parser.add_argument("--prompt", default="", help="optional user prompt for task matching")
    parser.add_argument(
        "--sync-state",
        action="store_true",
        help="sync selected feature status back to task files",
    )
    return parser.parse_args()


def run_git_cmd(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def get_current_branch(repo: Path) -> str:
    symbolic = run_git_cmd(repo, "symbolic-ref", "--short", "HEAD")
    if symbolic.returncode == 0:
        text = (symbolic.stdout or "").strip()
        if text:
            return text

    rev_parse = run_git_cmd(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if rev_parse.returncode == 0:
        text = (rev_parse.stdout or "").strip()
        if text and text != "HEAD":
            return text
    return "unknown"


def detect_workspace_dir(repo: Path) -> Path:
    harness_dir = repo / HARNESS_DIR_NAME
    if harness_dir.exists():
        return harness_dir
    return repo


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def resolve_bucket_feature_path(workspace_dir: Path, rel_path: str) -> Path:
    raw = str(rel_path or "").strip()
    if not raw:
        return workspace_dir / "__invalid_bucket_path__"

    candidates = [workspace_dir / raw]
    if raw.startswith(f"{HARNESS_DIR_NAME}/"):
        candidates.append(workspace_dir / raw[len(HARNESS_DIR_NAME) + 1 :])

    if workspace_dir.name == HARNESS_DIR_NAME:
        candidates.append(workspace_dir.parent / raw)
        if raw.startswith(f"{HARNESS_DIR_NAME}/"):
            candidates.append(workspace_dir.parent / raw[len(HARNESS_DIR_NAME) + 1 :])

    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def default_feature_file(workspace_dir: Path) -> Path:
    legacy = workspace_dir / "feature_list.json"
    if legacy.exists():
        return legacy
    return workspace_dir / "task-harness" / "features" / "backlog-core.json"


def resolve_feature_file(workspace_dir: Path) -> tuple[Path, Path, dict[str, Any] | None]:
    index_path = workspace_dir / "task-harness" / "index.json"
    if not index_path.exists():
        feature_file = default_feature_file(workspace_dir)
        return feature_file, workspace_dir / "feature_list.json", None

    index_data = load_json(index_path)
    active_bucket = str(index_data.get("active_bucket", "") or "")
    buckets = index_data.get("buckets", []) or []
    rel_path = ""
    for bucket in buckets:
        if str(bucket.get("id", "")) == active_bucket:
            rel_path = str(bucket.get("path", "") or "")
            break
    if not rel_path and buckets:
        rel_path = str((buckets[0] or {}).get("path", "") or "")
    if not rel_path:
        rel_path = "task-harness/features/backlog-core.json"

    feature_file = resolve_bucket_feature_path(workspace_dir, rel_path)
    legacy_mirror = workspace_dir / "feature_list.json"
    return feature_file, legacy_mirror, index_data


def normalize_session_mode(raw: str) -> str:
    value = str(raw or "").strip().lower()
    if value in {"hard_new_session", "hard", "new_session"}:
        return SESSION_MODE_HARD
    if value in {"soft_reset", "soft", "reset"}:
        return SESSION_MODE_SOFT
    return SESSION_MODE_SOFT


def load_session_mode(workspace_dir: Path) -> str:
    task_path = workspace_dir / "config" / "task.json"
    if not task_path.exists():
        task_path = workspace_dir / "task.json"
    if not task_path.exists():
        return SESSION_MODE_SOFT

    try:
        data = load_json(task_path)
    except (json.JSONDecodeError, OSError, ValueError):
        return SESSION_MODE_SOFT
    harness = data.get("harness", {})
    if not isinstance(harness, dict):
        return SESSION_MODE_SOFT

    session_control = harness.get("session_control", {})
    if isinstance(session_control, dict) and session_control.get("mode"):
        return normalize_session_mode(str(session_control.get("mode")))
    return normalize_session_mode(str(harness.get("session_mode", "")))


def load_session_boundary(workspace_dir: Path) -> dict[str, Any] | None:
    path = workspace_dir / "config" / "session-boundary.json"
    if not path.exists():
        path = workspace_dir / "session-boundary.json"
    if not path.exists():
        return None
    try:
        data = load_json(path)
    except (json.JSONDecodeError, OSError, ValueError):
        return {"invalid": True}
    if not isinstance(data, dict):
        return {"invalid": True}
    return data


def to_priority(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 10**9


def sort_key(feature: dict[str, Any]) -> tuple[int, str]:
    return (to_priority(feature.get("priority")), str(feature.get("id", "")))


def is_feature_done(feature: dict[str, Any]) -> bool:
    if bool(feature.get("passes")):
        return True
    status = str(feature.get("status", "")).strip().lower()
    return status == "done"


def normalize_task_id(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return "-".join(part.upper() for part in text.split("-"))


def build_task_state(features: list[dict[str, Any]]) -> dict[str, bool]:
    state: dict[str, bool] = {}
    for feature in features:
        task_id = normalize_task_id(str(feature.get("task_id", "")))
        if not task_id:
            continue
        state[task_id] = state.get(task_id, False) or is_feature_done(feature)
    return state


def dependency_unmet(feature: dict[str, Any], task_state: dict[str, bool]) -> list[str]:
    deps = feature.get("depends_on", [])
    if not isinstance(deps, list):
        return []
    unmet: list[str] = []
    for dep in deps:
        dep_text = str(dep or "").strip()
        dep_key = normalize_task_id(dep_text)
        if dep_key and not task_state.get(dep_key, False):
            unmet.append(dep_text)
    return unmet


def is_selectable(feature: dict[str, Any], task_state: dict[str, bool]) -> bool:
    if bool(feature.get("passes")):
        return False
    status = str(feature.get("status", "")).strip().lower()
    if status == "doing":
        return True
    return not dependency_unmet(feature, task_state)


def extract_prompt_refs(prompt_text: str) -> tuple[list[str], list[str]]:
    text = (prompt_text or "").strip()
    if not text:
        return [], []

    task_ids: list[str] = []
    feature_ids: list[str] = []
    for match in re.findall(r"\b[a-z]{2,}(?:-[a-z0-9]{1,})+\b", text, flags=re.IGNORECASE):
        normalized = "-".join(part.upper() for part in match.split("-"))
        if normalized not in task_ids:
            task_ids.append(normalized)

    for match in re.findall(r"\bB\d{1,4}[-/]T\d{1,4}\b|\bT\d{1,4}\b|\b\d{3}\b", text, flags=re.IGNORECASE):
        value = match.lower()
        if value not in feature_ids:
            feature_ids.append(value)

    for match in re.findall(r"\b(?:\d{8}T\d{6}Z-)?[a-z]{2,}(?:-[a-z0-9]{1,})+\b", text, flags=re.IGNORECASE):
        value = match.lower()
        if value not in feature_ids:
            feature_ids.append(value)
    return task_ids, feature_ids


def extract_text_tokens(text: str) -> list[str]:
    if not text:
        return []
    lowered = text.lower()
    raw_tokens = re.findall(r"[a-z0-9]{2,}|[\u4e00-\u9fff]{2,}", lowered)
    dedup: list[str] = []
    seen: set[str] = set()
    for token in raw_tokens:
        if token in STOP_WORDS:
            continue
        if token not in seen:
            seen.add(token)
            dedup.append(token)
    return dedup


def semantic_score(prompt_text: str, feature: dict[str, Any]) -> int:
    prompt = (prompt_text or "").lower()
    if not prompt.strip():
        return 0

    score = 0
    tokens = extract_text_tokens(prompt_text)
    feature_text = " ".join(
        [
            str(feature.get("task_id", "")).lower(),
            str(feature.get("id", "")).lower(),
            str(feature.get("display_id", "")).lower(),
            str(feature.get("local_display_id", "")).lower(),
            str(feature.get("title", "")).lower(),
            str(feature.get("display_name", "")).lower(),
            str(feature.get("description", "")).lower(),
        ]
    )
    for token in tokens:
        if token in feature_text:
            score += min(4, max(1, len(token) // 3 + 1))
    return score


def pick_by_prompt(
    features: list[dict[str, Any]],
    task_ids: list[str],
    feature_ids: list[str],
    prompt_text: str,
) -> tuple[dict[str, Any] | None, str]:
    for task_id in task_ids:
        matched = [f for f in features if normalize_task_id(str(f.get("task_id", ""))) == task_id]
        if matched:
            return sorted(matched, key=sort_key)[0], "explicit-task-id"

    for feature_id in feature_ids:
        target = normalize_lookup_value(feature_id)
        matched = [f for f in features if target in feature_lookup_aliases(f)]
        if matched:
            return sorted(matched, key=sort_key)[0], "explicit-feature-id"

    if prompt_text.strip():
        scored: list[tuple[int, dict[str, Any]]] = []
        for feature in features:
            score = semantic_score(prompt_text, feature)
            if score > 0:
                scored.append((score, feature))
        if scored:
            scored.sort(key=lambda item: (-item[0], *sort_key(item[1])))
            return scored[0][1], "semantic-match"

    return None, ""


def sync_feature_status(data: dict[str, Any], feature_id: str, status: str) -> bool:
    features = data.get("features", [])
    if not isinstance(features, list):
        return False

    changed = False
    now = datetime.now().strftime("%Y-%m-%d")
    for feature in features:
        if str(feature.get("id", "")) != feature_id:
            continue
        if status and str(feature.get("status", "")).strip().lower() != status.strip().lower():
            feature["status"] = status
            changed = True
        if str(feature.get("updated_at", "")) != now:
            feature["updated_at"] = now
            changed = True
        break
    return changed


def write_json_if_changed(path: Path, data: dict[str, Any], changed: bool) -> None:
    if changed:
        dump_json(path, data)


def main() -> int:
    args = parse_args()
    repo = Path(args.target_dir).resolve()
    workspace_dir = detect_workspace_dir(repo)

    session_mode = load_session_mode(workspace_dir)
    if session_mode == SESSION_MODE_HARD:
        boundary = load_session_boundary(workspace_dir)
        if boundary:
            closed_id = str(boundary.get("closed_feature_id", "n/a"))
            next_id = str(boundary.get("next_feature_id", "n/a"))
            print(
                "[task] blocked by session boundary: "
                f"mode=hard_new_session closed_feature={closed_id} next_feature={next_id}"
            )
            print("[task] run `bash .harness/scripts/init.sh` in a NEW session before next feature.")
            return 2

    try:
        entries = load_task_entries(workspace_dir)
    except Exception as exc:
        print(f"[task] failed to read task storage: {exc}")
        return 0

    if not entries:
        feature_file, _legacy_mirror, _index_data = resolve_feature_file(workspace_dir)
        print(f"[task] no task files found; checked legacy source: {feature_file}")
        return 0

    features = [entry.feature for entry in entries]

    task_state = build_task_state(features)
    selectable = sorted([f for f in features if is_selectable(f, task_state)], key=sort_key)

    task_ids, feature_ids = extract_prompt_refs(args.prompt)
    selected, source = pick_by_prompt(selectable, task_ids, feature_ids, args.prompt)

    if selected is None:
        doing = sorted(
            [f for f in selectable if str(f.get("status", "")).strip().lower() == "doing"],
            key=sort_key,
        )
        if doing:
            selected = doing[0]
            source = "fallback-doing"
        elif selectable:
            selected = selectable[0]
            source = "fallback-default"

    if selected is None:
        print("[task] no selectable pending feature")
        return 0

    feature_id = str(selected.get("id") or "feat")
    task_id = str(selected.get("task_id") or selected.get("display_id") or "")
    status = str(selected.get("status") or "todo")
    branch = get_current_branch(repo)
    print(f"[task] source={source} feature={display_label(selected)} raw_id={feature_id} task_id={task_id} status={status}")
    print(f"[task] current_branch={branch} (branch switching disabled)")

    unmet = dependency_unmet(selected, task_state)
    if unmet and status.strip().lower() != "doing":
        print(f"[task] selected feature has unmet dependencies: {','.join(unmet)}")
        return 0

    if args.sync_state:
        next_status = status
        if not bool(selected.get("passes")) and status.strip().lower() in ("", "todo"):
            next_status = "doing"
        selected_entry = next(
            (entry for entry in entries if str(entry.feature.get("id", "")) == feature_id),
            None,
        )
        if selected_entry is not None:
            def mutate(feature: dict[str, Any]) -> bool:
                return sync_feature_status({"features": [feature]}, feature_id, next_status)

            write_feature_update(selected_entry, mutate)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
