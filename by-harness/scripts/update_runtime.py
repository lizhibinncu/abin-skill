#!/usr/bin/env python3
"""Versioned runtime updater for by-harness projects.

This updater supports:
1) Runtime version tracking via `.harness/config/runtime-version.json`
2) Periodic remote manifest checks
3) Auto-apply based on update policy
4) Incremental migrations by local version chain
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

HARNESS_DIR_NAME = ".harness"
VERSION_FILE_NAME = "config/runtime-version.json"
POLICY_FILE_NAME = "config/update-policy.json"
STATE_FILE_NAME = "config/update-state.json"
TASK_FILE_NAME = "config/task.json"
SESSION_CONTEXT_FILE_NAME = "config/session-context.json"
SESSION_BOUNDARY_FILE_NAME = "config/session-boundary.json"
TASK_CONTRACT_FILE_NAME = "docs/TASK-HARNESS.md"

LEGACY_VERSION_FILE_NAME = "runtime-version.json"
LEGACY_POLICY_FILE_NAME = "update-policy.json"
LEGACY_STATE_FILE_NAME = "update-state.json"
LEGACY_TASK_FILE_NAME = "task.json"
LEGACY_SESSION_CONTEXT_FILE_NAME = "session-context.json"
LEGACY_SESSION_BOUNDARY_FILE_NAME = "session-boundary.json"
LEGACY_TASK_CONTRACT_FILE_NAME = "TASK-HARNESS.md"
LATEST_RUNTIME_VERSION = "2.6.1"
DEFAULT_TASK_GLOBS = ("task-harness/tasks/*.json", "task-harness/tasks/**/*.json")
RUNTIME_SCRIPT_NAMES = (
    "init.sh",
    "quick_fix_classifier.py",
    "session_close.py",
    "ensure_task_branch.py",
    "task_switch.py",
    "task_store.py",
    "update_runtime.py",
    "upgrade_legacy_repo.py",
    "qa_runner.py",
    "qa_report.py",
    "qa_gate.py",
    "testcontainers_doctor.py",
)
RUNTIME_DOC_REL_PATHS = (
    "root/AGENTS.md",
    "root/CLAUDE.md",
    "root/.codex/config.toml",
    "root/.codex/hooks.json",
    "root/.codex/hooks/context-injector.py",
    "root/.codex/hooks/loop-detector.py",
    "root/.codex/hooks/pre-completion-check.py",
    "root/.codex/hooks/convention-check.py",
    "root/.claude/settings.json",
    "root/.claude/hooks/context-injector.py",
    "root/.claude/hooks/loop-detector.py",
    "root/.claude/hooks/pre-completion-check.py",
    "root/.claude/hooks/convention-check.py",
    "root/.claude/agents/planner.md",
    "root/.claude/agents/generator.md",
    "root/.claude/agents/evaluator.md",
    "root/.claude/agents/doc-gardener.md",
    "root/.claude/commands/plan.md",
    "root/.claude/commands/build.md",
    "root/.claude/commands/qa.md",
    "root/.claude/commands/sprint.md",
    TASK_CONTRACT_FILE_NAME,
    "docs/architecture.md",
    "docs/golden-principles.md",
    "docs/sprint-workflow.md",
    "docs/java-dev-conventions.md",
    "docs/java/rules/00-core.md",
    "docs/java/rules/java-ddd.md",
    "docs/java/rules/dubbo-api.md",
    "docs/java/rules/logging-error.md",
    "docs/java/rules/persistence-infra.md",
    "docs/java/rules/testing-security.md",
    "docs/java/rules/distributed-java-gate.md",
    "docs/contracts/TEMPLATE.md",
)
REPO_ROOT_PREFIX = "root/"
MANAGED_BLOCK_BEGIN = "<!-- BEGIN BY-HARNESS MANAGED BLOCK -->"
MANAGED_BLOCK_END = "<!-- END BY-HARNESS MANAGED BLOCK -->"

DEFAULT_MODE = "soft_reset"
SUPPORTED_MODES = ["soft_reset", "hard_new_session"]
MODE_GUIDE = {
    "soft_reset": "默认模式：同一聊天可继续，但每次 feature 收口后自动提升 context epoch，并要求忽略旧 feature 上下文。",
    "hard_new_session": "严格模式：每个 feature 收口后必须新开会话，未新开会话前阻止进入下一个 feature。",
}
TASK_SWITCH_RULE = "继续下个任务可执行：python3 .harness/scripts/task_switch.py continue --target-dir .（仅当前分支）"
RULE_PREFIXES_TO_REMOVE = (
    "连续模式切任务：",
    "多个任务分支在全部完成后自动汇总合并到 rollup_target 分支",
)
LEGACY_CONTROL_KEYS = (
    "flow_mode",
    "dirty_strategy",
    "auto_merge_on_all_done",
    "rollup_target",
    "supported_flow_modes",
    "supported_dirty_strategies",
    "flow_mode_guide",
    "dirty_strategy_guide",
)
SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")

DEFAULT_POLICY = {
    "enabled": False,
    "channel": "stable",
    "manifest_url": "",
    "check_interval_minutes": 360,
    "auto_apply_patch": True,
    "auto_apply_minor": False,
    "auto_apply_major": False,
    "require_checksum": True,
    "request_timeout_seconds": 10,
}

MIGRATIONS: dict[str, tuple[str, str]] = {
    "1.0.0": ("2.0.0", "migrate_remove_branch_switching"),
    "2.0.0": ("2.1.0", "migrate_runtime_versioning"),
    "2.1.0": ("2.2.1", "migrate_runtime_versioning"),
    "2.2.1": ("2.2.2", "migrate_runtime_versioning"),
    "2.2.2": ("2.3.0", "migrate_runtime_versioning"),
    "2.3.0": ("2.3.1", "migrate_runtime_versioning"),
    "2.3.1": ("2.3.2", "migrate_runtime_versioning"),
    "2.3.2": ("2.3.3", "migrate_runtime_versioning"),
    "2.3.3": ("2.3.4", "migrate_runtime_versioning"),
    "2.3.4": ("2.3.5", "migrate_runtime_versioning"),
    "2.3.5": ("2.3.6", "migrate_runtime_versioning"),
    "2.3.6": ("2.3.7", "migrate_runtime_versioning"),
    "2.3.7": ("2.3.8", "migrate_runtime_versioning"),
    "2.3.8": ("2.3.9", "migrate_runtime_versioning"),
    "2.3.9": ("2.3.10", "migrate_runtime_versioning"),
    "2.3.10": ("2.4.0", "migrate_file_tasks_storage"),
    "2.4.0": ("2.5.0", "migrate_file_tasks_storage"),
    "2.5.0": ("2.6.0", "migrate_qa_gate_runtime"),
    "2.6.0": ("2.6.1", "migrate_quick_fix_runtime"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Versioned runtime updater for by-harness projects.")
    parser.add_argument("--target-dir", required=True, help="已初始化仓库目录（或 .harness 目录）")
    parser.add_argument(
        "--check-remote",
        action="store_true",
        help="按 update-policy 执行定时检查并按策略自动应用（用于 init/task_switch 自动触发）",
    )
    parser.add_argument(
        "--force-check",
        action="store_true",
        help="忽略检测间隔，强制检查远程版本",
    )
    parser.add_argument(
        "--manifest-url",
        default="",
        help="覆盖 policy 的 manifest_url（便于测试或临时切换源）",
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印变更计划，不落盘")
    parser.add_argument("--no-backup", action="store_true", help="跳过升级前备份")
    parser.add_argument(
        "--backup-dir",
        default="",
        help="自定义备份目录（默认 .harness/backups/update-YYYYMMDD-HHMMSS）",
    )
    return parser.parse_args()


def detect_harness_dir(target: Path) -> Path:
    if target.name == HARNESS_DIR_NAME and target.exists():
        return target
    harness_dir = target / HARNESS_DIR_NAME
    if harness_dir.exists():
        return harness_dir
    raise RuntimeError(f"未检测到 {HARNESS_DIR_NAME} 目录：{target}")


def resolve_existing_path(harness_dir: Path, primary: str, legacy: str) -> Path | None:
    primary_path = harness_dir / primary
    if primary_path.exists():
        return primary_path
    legacy_path = harness_dir / legacy
    if legacy_path.exists():
        return legacy_path
    return None


def resolve_preferred_path(harness_dir: Path, primary: str, legacy: str) -> Path:
    existing = resolve_existing_path(harness_dir, primary, legacy)
    if existing is not None:
        return existing
    return harness_dir / primary


def task_json_path(harness_dir: Path) -> Path:
    return resolve_preferred_path(harness_dir, TASK_FILE_NAME, LEGACY_TASK_FILE_NAME)


def session_context_path(harness_dir: Path) -> Path:
    return resolve_preferred_path(harness_dir, SESSION_CONTEXT_FILE_NAME, LEGACY_SESSION_CONTEXT_FILE_NAME)


def session_boundary_path(harness_dir: Path) -> Path:
    return resolve_preferred_path(harness_dir, SESSION_BOUNDARY_FILE_NAME, LEGACY_SESSION_BOUNDARY_FILE_NAME)


def parse_semver(value: str) -> tuple[int, int, int] | None:
    text = str(value or "").strip()
    m = SEMVER_RE.match(text)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def semver_lt(a: str, b: str) -> bool:
    pa = parse_semver(a)
    pb = parse_semver(b)
    if pa is None or pb is None:
        return False
    return pa < pb


def semver_gt(a: str, b: str) -> bool:
    pa = parse_semver(a)
    pb = parse_semver(b)
    if pa is None or pb is None:
        return False
    return pa > pb


def classify_bump(current: str, target: str) -> str:
    pc = parse_semver(current)
    pt = parse_semver(target)
    if pc is None or pt is None:
        return "unknown"
    if pt[0] != pc[0]:
        return "major"
    if pt[1] != pc[1]:
        return "minor"
    if pt[2] != pc[2]:
        return "patch"
    return "none"


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def load_project_render_context(harness_dir: Path) -> dict[str, str]:
    task_path = task_json_path(harness_dir)
    project_name = harness_dir.parent.name
    project_type = "General"
    tech_stack = "Not specified"
    if task_path.exists():
        try:
            task = load_json(task_path)
        except (json.JSONDecodeError, OSError, ValueError):
            task = {}
        if isinstance(task, dict):
            project_name = str(task.get("project") or project_name).strip() or project_name
            project_type = str(task.get("project_type") or project_type).strip() or project_type
            tech_stack = str(task.get("tech_stack") or tech_stack).strip() or tech_stack
    return {
        "{{PROJECT_NAME}}": project_name,
        "{{TECH_STACK}}": tech_stack,
        "{{PROJECT_TYPE}}": project_type,
    }


def render_project_context(data: bytes, harness_dir: Path) -> bytes:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError(f"render_project_context requires utf-8 text, got binary data: {exc}") from exc
    context = load_project_render_context(harness_dir)
    for key, value in context.items():
        text = text.replace(key, value)
    return text.encode("utf-8")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_policy(harness_dir: Path) -> dict[str, Any]:
    policy_path = resolve_preferred_path(harness_dir, POLICY_FILE_NAME, LEGACY_POLICY_FILE_NAME)
    if not policy_path.exists():
        return dict(DEFAULT_POLICY)
    try:
        payload = load_json(policy_path)
    except (json.JSONDecodeError, OSError, ValueError):
        return dict(DEFAULT_POLICY)
    if not isinstance(payload, dict):
        return dict(DEFAULT_POLICY)
    policy = dict(DEFAULT_POLICY)
    policy.update(payload)
    return policy


def load_state(harness_dir: Path) -> dict[str, Any]:
    state_path = resolve_preferred_path(harness_dir, STATE_FILE_NAME, LEGACY_STATE_FILE_NAME)
    if not state_path.exists():
        return {}
    try:
        payload = load_json(state_path)
    except (json.JSONDecodeError, OSError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def save_state(harness_dir: Path, state: dict[str, Any], dry_run: bool) -> None:
    path = resolve_preferred_path(harness_dir, STATE_FILE_NAME, LEGACY_STATE_FILE_NAME)
    if dry_run:
        print(f"[dry-run] write state: {path}")
        return
    dump_json(path, state)


def runtime_version_path(harness_dir: Path) -> Path:
    return resolve_preferred_path(harness_dir, VERSION_FILE_NAME, LEGACY_VERSION_FILE_NAME)


def infer_current_version(harness_dir: Path) -> tuple[str, str]:
    version_path = runtime_version_path(harness_dir)
    if version_path.exists():
        try:
            payload = load_json(version_path)
            v = str(payload.get("runtime_version", "")).strip()
            if parse_semver(v):
                return v, str(version_path.relative_to(harness_dir))
        except (json.JSONDecodeError, OSError, ValueError):
            pass

    task_path = task_json_path(harness_dir)
    if not task_path.exists():
        return "1.0.0", "default"
    try:
        task = load_json(task_path)
    except (json.JSONDecodeError, OSError, ValueError):
        return "1.0.0", "task-json-invalid"

    harness = task.get("harness", {})
    sc = harness.get("session_control", {}) if isinstance(harness, dict) else {}
    if not isinstance(sc, dict):
        return "1.0.0", "task-json"
    if any(key in sc for key in LEGACY_CONTROL_KEYS):
        return "1.0.0", "task-json-legacy-keys"
    return "2.0.0", f"{task_path.relative_to(harness_dir)}-modern-no-version-file"


def normalize_mode(raw: Any) -> str:
    text = str(raw or "").strip().lower()
    if text in {"hard_new_session", "hard", "new_session"}:
        return "hard_new_session"
    if text in {"soft_reset", "soft", "reset"}:
        return "soft_reset"
    return DEFAULT_MODE


def migrate_task_json_to_current_branch_mode(task_data: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    changed = False
    payload = dict(task_data) if isinstance(task_data, dict) else {}
    harness = payload.get("harness", {})
    if not isinstance(harness, dict):
        harness = {}
        changed = True

    session_control = harness.get("session_control", {})
    legacy_mode = harness.get("session_mode", "")
    mode = DEFAULT_MODE
    if isinstance(session_control, dict) and session_control.get("mode"):
        mode = normalize_mode(session_control.get("mode"))
    elif legacy_mode:
        mode = normalize_mode(legacy_mode)

    next_control = {
        "mode": mode,
        "supported_modes": SUPPORTED_MODES,
        "mode_guide": MODE_GUIDE,
    }
    if session_control != next_control:
        changed = True
    harness["session_control"] = next_control

    if "session_mode" in harness:
        harness.pop("session_mode", None)
        changed = True

    files = harness.get("files", {})
    if isinstance(files, dict):
        if "feature_list" in files and "legacy_feature_list" not in files:
            files["legacy_feature_list"] = files.pop("feature_list")
            changed = True
        if "legacy_feature_list" not in files:
            files["legacy_feature_list"] = ".harness/feature_list.json"
            changed = True
        if files.get("task_index") != ".harness/task-harness/index.json":
            files["task_index"] = ".harness/task-harness/index.json"
            changed = True
        if files.get("feature_buckets") != ".harness/task-harness/features/":
            files["feature_buckets"] = ".harness/task-harness/features/"
            changed = True
        if files.get("progress_shards") != ".harness/task-harness/progress/":
            files["progress_shards"] = ".harness/task-harness/progress/"
            changed = True
        if files.get("progress_log") != ".harness/task-harness/progress/latest.txt":
            files["progress_log"] = ".harness/task-harness/progress/latest.txt"
            changed = True
        if files.get("runtime_version") != f".harness/{VERSION_FILE_NAME}":
            files["runtime_version"] = f".harness/{VERSION_FILE_NAME}"
            changed = True
        if files.get("update_policy") != f".harness/{POLICY_FILE_NAME}":
            files["update_policy"] = f".harness/{POLICY_FILE_NAME}"
            changed = True
        if files.get("update_state") != f".harness/{STATE_FILE_NAME}":
            files["update_state"] = f".harness/{STATE_FILE_NAME}"
            changed = True
        if files.get("session_context") != f".harness/{SESSION_CONTEXT_FILE_NAME}":
            files["session_context"] = f".harness/{SESSION_CONTEXT_FILE_NAME}"
            changed = True
        if files.get("session_boundary") != f".harness/{SESSION_BOUNDARY_FILE_NAME}":
            files["session_boundary"] = f".harness/{SESSION_BOUNDARY_FILE_NAME}"
            changed = True
        if files.get("init_script") != ".harness/scripts/init.sh":
            files["init_script"] = ".harness/scripts/init.sh"
            changed = True
        if files.get("main_contract") != "AGENTS.md":
            files["main_contract"] = "AGENTS.md"
            changed = True
        if files.get("task_contract") != f".harness/{TASK_CONTRACT_FILE_NAME}":
            files["task_contract"] = f".harness/{TASK_CONTRACT_FILE_NAME}"
            changed = True
        harness["files"] = files

    rules = harness.get("rules", [])
    if isinstance(rules, list):
        normalized: list[str] = []
        for raw in rules:
            text = str(raw)
            if any(text.startswith(prefix) for prefix in RULE_PREFIXES_TO_REMOVE):
                changed = True
                continue
            normalized.append(text)
        if TASK_SWITCH_RULE not in normalized:
            normalized.append(TASK_SWITCH_RULE)
            changed = True
        harness["rules"] = normalized

    payload["harness"] = harness
    updated = datetime.now().strftime("%Y-%m-%d")
    if str(payload.get("updated", "")) != updated:
        payload["updated"] = updated
        changed = True
    return payload, changed


def cleanup_session_context(session_context_path: Path, dry_run: bool) -> bool:
    if not session_context_path.exists():
        return False
    try:
        payload = load_json(session_context_path)
    except (json.JSONDecodeError, OSError, ValueError):
        return False
    if not isinstance(payload, dict):
        return False
    if "review_pending" not in payload:
        return False
    payload.pop("review_pending", None)
    if dry_run:
        print(f"[dry-run] cleanup key review_pending: {session_context_path}")
    else:
        dump_json(session_context_path, payload)
    return True


def remove_file(path: Path, dry_run: bool) -> bool:
    if not path.exists():
        return False
    if dry_run:
        print(f"[dry-run] remove: {path}")
    else:
        path.unlink()
    return True


def relocate_path(harness_dir: Path, target_rel: str, legacy_rel: str, dry_run: bool) -> bool:
    target = harness_dir / target_rel
    legacy = harness_dir / legacy_rel
    if not legacy.exists() or target.exists():
        return False
    if dry_run:
        print(f"[dry-run] relocate: {legacy} -> {target}")
        return True
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(legacy), str(target))
    return True


def migrate_grouped_layout(harness_dir: Path, dry_run: bool) -> dict[str, int]:
    moved = 0
    for target_rel, legacy_rel in (
        (TASK_FILE_NAME, LEGACY_TASK_FILE_NAME),
        (VERSION_FILE_NAME, LEGACY_VERSION_FILE_NAME),
        (POLICY_FILE_NAME, LEGACY_POLICY_FILE_NAME),
        (STATE_FILE_NAME, LEGACY_STATE_FILE_NAME),
        (SESSION_CONTEXT_FILE_NAME, LEGACY_SESSION_CONTEXT_FILE_NAME),
        (SESSION_BOUNDARY_FILE_NAME, LEGACY_SESSION_BOUNDARY_FILE_NAME),
        (TASK_CONTRACT_FILE_NAME, LEGACY_TASK_CONTRACT_FILE_NAME),
        ("scripts/init.sh", "init.sh"),
        ("task-harness/progress/latest.txt", "progress.txt"),
    ):
        if relocate_path(harness_dir, target_rel, legacy_rel, dry_run):
            moved += 1
    return {"layout_moved": moved}


def promote_claude_to_repo_root(harness_dir: Path, dry_run: bool) -> bool:
    src = harness_dir / "CLAUDE.md"
    dst = harness_dir.parent / "CLAUDE.md"
    if not src.exists():
        return False
    if dry_run:
        action = "merge" if dst.exists() else "promote"
        print(f"[dry-run] {action} CLAUDE.md to repo root: {src} -> {dst}")
        return True
    dst.parent.mkdir(parents=True, exist_ok=True)
    template = src.read_text(encoding="utf-8")
    existing = dst.read_text(encoding="utf-8") if dst.exists() else ""
    dst.write_text(merge_markdown_block(existing, template), encoding="utf-8")
    return True


def migrate_remove_branch_switching(harness_dir: Path, dry_run: bool) -> dict[str, int]:
    stats = {"task_json_changed": 0, "context_cleaned": 0, "files_removed": 0, "claude_promoted": 0, "layout_moved": 0}
    task_path = task_json_path(harness_dir)
    task_data = load_json(task_path)
    migrated, changed = migrate_task_json_to_current_branch_mode(task_data)
    if changed:
        if dry_run:
            print(f"[dry-run] migrate task config to current-branch mode: {task_path}")
        else:
            dump_json(task_path, migrated)
        stats["task_json_changed"] += 1
    if cleanup_session_context(session_context_path(harness_dir), dry_run):
        stats["context_cleaned"] += 1
    if remove_file(harness_dir / "branch-rollup.json", dry_run):
        stats["files_removed"] += 1
    if promote_claude_to_repo_root(harness_dir, dry_run):
        stats["claude_promoted"] += 1
    layout = migrate_grouped_layout(harness_dir, dry_run)
    stats["layout_moved"] += layout.get("layout_moved", 0)
    return stats


def migrate_runtime_versioning(harness_dir: Path, dry_run: bool) -> dict[str, int]:
    stats = {"task_json_changed": 0, "context_cleaned": 0, "files_removed": 0, "claude_promoted": 0, "layout_moved": 0}
    task_path = task_json_path(harness_dir)
    task_data = load_json(task_path)
    migrated, changed = migrate_task_json_to_current_branch_mode(task_data)
    if changed:
        if dry_run:
            print(f"[dry-run] migrate runtime-version pointers: {task_path}")
        else:
            dump_json(task_path, migrated)
        stats["task_json_changed"] += 1
    if cleanup_session_context(session_context_path(harness_dir), dry_run):
        stats["context_cleaned"] += 1
    if promote_claude_to_repo_root(harness_dir, dry_run):
        stats["claude_promoted"] += 1
    layout = migrate_grouped_layout(harness_dir, dry_run)
    stats["layout_moved"] += layout.get("layout_moved", 0)
    return stats


def migrate_file_tasks_index(harness_dir: Path, dry_run: bool) -> bool:
    index_path = harness_dir / "task-harness" / "index.json"
    existing: dict[str, Any] = {}
    if index_path.exists():
        try:
            payload = load_json(index_path)
            if isinstance(payload, dict):
                existing = payload
        except (json.JSONDecodeError, OSError, ValueError):
            existing = {}

    legacy_buckets = existing.get("legacy_buckets")
    if not isinstance(legacy_buckets, list):
        legacy_buckets = existing.get("buckets", [])
    if not isinstance(legacy_buckets, list):
        legacy_buckets = []

    task_globs = []
    existing_globs = existing.get("task_globs", [])
    if isinstance(existing_globs, list):
        task_globs = [str(item) for item in existing_globs if str(item).strip()]
    for pattern in DEFAULT_TASK_GLOBS:
        if pattern not in task_globs:
            task_globs.append(pattern)

    next_index = {
        "version": "3",
        "mode": "file_tasks",
        "updated": datetime.now().strftime("%Y-%m-%d"),
        "task_globs": task_globs,
        "legacy_buckets": legacy_buckets,
        "views": {
            "generated_backlog": "task-harness/views/backlog-core.generated.json"
        },
        "notes": [
            "权威任务源是 task_globs 指向的单任务 JSON 文件，默认同时兼容 tasks/*.json 与 tasks/**/*.json。",
            "新拆解任务默认按批次写入 task-harness/tasks/<批次目录>/<任务文件>.json。",
            "legacy_buckets 只用于读取旧 backlog-core/feature_list 任务，不作为新任务写入目标。",
        ],
    }
    if existing == next_index:
        return False
    if dry_run:
        print(f"[dry-run] migrate task index to file_tasks storage: {index_path}")
    else:
        dump_json(index_path, next_index)
    return True


def migrate_file_tasks_storage(harness_dir: Path, dry_run: bool) -> dict[str, int]:
    stats = migrate_runtime_versioning(harness_dir, dry_run)
    stats.setdefault("task_index_changed", 0)
    stats.setdefault("dirs_created", 0)

    for rel in ("task-harness/tasks", "task-harness/views"):
        path = harness_dir / rel
        if not path.exists():
            if dry_run:
                print(f"[dry-run] create dir: {path}")
            else:
                path.mkdir(parents=True, exist_ok=True)
            stats["dirs_created"] += 1

    task_path = task_json_path(harness_dir)
    if task_path.exists():
        try:
            task_data = load_json(task_path)
        except (json.JSONDecodeError, OSError, ValueError):
            task_data = {}
        if isinstance(task_data, dict):
            harness = task_data.setdefault("harness", {})
            if isinstance(harness, dict):
                files = harness.setdefault("files", {})
                if isinstance(files, dict):
                    changed = False
                    desired = {
                        "task_files": ".harness/task-harness/tasks/",
                        "legacy_feature_buckets": ".harness/task-harness/features/",
                        "progress_shards": ".harness/task-harness/progress/",
                    }
                    for key, value in desired.items():
                        if files.get(key) != value:
                            files[key] = value
                            changed = True
                    if files.get("feature_buckets") == ".harness/task-harness/features/":
                        files["feature_buckets"] = ".harness/task-harness/features/ (legacy read-only)"
                        changed = True
                    if changed:
                        if dry_run:
                            print(f"[dry-run] migrate task.json file_tasks pointers: {task_path}")
                        else:
                            dump_json(task_path, task_data)
                        stats["task_json_changed"] = stats.get("task_json_changed", 0) + 1

    if migrate_file_tasks_index(harness_dir, dry_run):
        stats["task_index_changed"] += 1
    return stats


def migrate_qa_gate_runtime(harness_dir: Path, dry_run: bool) -> dict[str, int]:
    """Version marker migration for QA Gate runtime files shipped by manifest."""
    return {"qa_gate_runtime": 0}


def copy_sibling_runtime_script(harness_dir: Path, script_name: str, dry_run: bool) -> bool:
    src = Path(__file__).resolve().parent / script_name
    dst = harness_dir / "scripts" / script_name
    if not src.exists():
        return False
    if src.resolve() == dst.resolve():
        return False
    if dry_run:
        print(f"[dry-run] copy runtime script: {src} -> {dst}")
        return True
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    dst.chmod(dst.stat().st_mode | 0o755)
    return True


def migrate_quick_fix_runtime(harness_dir: Path, dry_run: bool) -> dict[str, int]:
    """Install quick-fix runtime scripts when using local fallback without a manifest."""
    copied = 0
    for script_name in ("quick_fix_classifier.py", "session_close.py", "update_runtime.py"):
        if copy_sibling_runtime_script(harness_dir, script_name, dry_run):
            copied += 1
    return {"quick_fix_runtime": copied}


def run_migration(step_name: str, harness_dir: Path, dry_run: bool) -> dict[str, int]:
    if step_name == "migrate_remove_branch_switching":
        return migrate_remove_branch_switching(harness_dir, dry_run)
    if step_name == "migrate_runtime_versioning":
        return migrate_runtime_versioning(harness_dir, dry_run)
    if step_name == "migrate_file_tasks_storage":
        return migrate_file_tasks_storage(harness_dir, dry_run)
    if step_name == "migrate_qa_gate_runtime":
        return migrate_qa_gate_runtime(harness_dir, dry_run)
    if step_name == "migrate_quick_fix_runtime":
        return migrate_quick_fix_runtime(harness_dir, dry_run)
    raise RuntimeError(f"未知迁移步骤：{step_name}")


def write_runtime_version(harness_dir: Path, version: str, dry_run: bool, updated_by: str) -> bool:
    path = runtime_version_path(harness_dir)
    if path.exists():
        try:
            current = load_json(path)
            if str(current.get("runtime_version", "")).strip() == version:
                return False
        except (json.JSONDecodeError, OSError, ValueError):
            pass

    payload = {
        "skill": "by-harness",
        "runtime_version": version,
        "updated_at": now_iso(),
        "updated_by": updated_by,
    }
    if dry_run:
        print(f"[dry-run] write runtime version: {path} -> {version}")
    else:
        dump_json(path, payload)
    return True


def backup_files(harness_dir: Path, backup_root: Path, paths: list[Path], dry_run: bool) -> int:
    count = 0
    repo_root = harness_dir.parent.resolve()
    harness_root = harness_dir.resolve()
    for src in paths:
        if not src.exists():
            continue
        src_resolved = src.resolve()
        if harness_root in src_resolved.parents or src_resolved == harness_root:
            rel = src_resolved.relative_to(harness_root)
        elif repo_root in src_resolved.parents or src_resolved == repo_root:
            rel = Path("__repo__") / src_resolved.relative_to(repo_root)
        else:
            raise RuntimeError(f"backup path escapes repo: {src}")
        dst = backup_root / rel
        if dry_run:
            print(f"[dry-run] backup: {src} -> {dst}")
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        count += 1
    return count


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch_bytes(url: str, timeout_seconds: int) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "by-harness-updater/1.0"})
    with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
        return resp.read()


def fetch_manifest(manifest_url: str, timeout_seconds: int) -> dict[str, Any]:
    raw = fetch_bytes(manifest_url, timeout_seconds)
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("manifest must be a JSON object")
    return payload


def should_check_remote(policy: dict[str, Any], state: dict[str, Any], force_check: bool) -> tuple[bool, str]:
    if force_check:
        return True, "force-check"
    if not bool(policy.get("enabled", False)):
        return False, "policy-disabled"
    interval_minutes = max(1, to_int(policy.get("check_interval_minutes", 360), 360))
    last_check_ts = to_int(state.get("last_check_unix", 0), 0)
    now_ts = int(datetime.now().timestamp())
    if last_check_ts <= 0:
        return True, "first-check"
    if now_ts - last_check_ts >= interval_minutes * 60:
        return True, "interval-elapsed"
    return False, "interval-not-elapsed"


def update_state_after_check(
    harness_dir: Path,
    state: dict[str, Any],
    *,
    result: str,
    remote_version: str = "",
    error: str = "",
    dry_run: bool,
) -> None:
    now_ts = int(datetime.now().timestamp())
    state["last_check_at"] = now_iso()
    state["last_check_unix"] = now_ts
    state["last_result"] = result
    if remote_version:
        state["last_remote_version"] = remote_version
    if error:
        state["last_error"] = error
    else:
        state.pop("last_error", None)
    save_state(harness_dir, state, dry_run)


def decide_auto_apply(policy: dict[str, Any], current: str, target: str) -> bool:
    bump = classify_bump(current, target)
    if bump == "patch":
        return bool(policy.get("auto_apply_patch", True))
    if bump == "minor":
        return bool(policy.get("auto_apply_minor", False))
    if bump == "major":
        return bool(policy.get("auto_apply_major", False))
    return False


def validate_manifest(manifest: dict[str, Any], current_version: str) -> tuple[str, list[dict[str, Any]]]:
    target_version = str(manifest.get("version", "")).strip()
    if parse_semver(target_version) is None:
        raise RuntimeError("manifest.version is invalid semver")

    min_compatible = str(manifest.get("min_compatible_version", "1.0.0")).strip() or "1.0.0"
    if parse_semver(min_compatible) and semver_lt(current_version, min_compatible):
        raise RuntimeError(
            f"current version {current_version} is lower than min_compatible_version {min_compatible}"
        )

    files = manifest.get("files", [])
    if not isinstance(files, list):
        raise RuntimeError("manifest.files must be an array")
    return target_version, files


def secure_target_path(harness_dir: Path, repo_root: Path, rel_path: str) -> Path:
    raw = str(rel_path or "").strip().replace("\\", "/")
    if not raw or raw.startswith("/") or ".." in raw.split("/"):
        raise RuntimeError(f"invalid manifest file path: {rel_path}")
    if raw.startswith(REPO_ROOT_PREFIX):
        rel = raw[len(REPO_ROOT_PREFIX):].strip("/")
        if not rel:
            raise RuntimeError(f"invalid root path: {rel_path}")
        path = (repo_root / rel).resolve()
        if repo_root.resolve() not in path.parents and path != repo_root.resolve():
            raise RuntimeError(f"path escapes repo root: {rel_path}")
        return path
    path = (harness_dir / raw).resolve()
    if harness_dir.resolve() not in path.parents and path != harness_dir.resolve():
        raise RuntimeError(f"path escapes harness directory: {rel_path}")
    return path


def materialize_manifest_files(
    harness_dir: Path,
    repo_root: Path,
    files: list[dict[str, Any]],
    *,
    timeout_seconds: int,
    require_checksum: bool,
) -> list[tuple[Path, bytes, str]]:
    rendered: list[tuple[Path, bytes, str]] = []
    for item in files:
        if not isinstance(item, dict):
            raise RuntimeError("manifest file item must be an object")
        rel_path = str(item.get("path", "")).strip()
        target = secure_target_path(harness_dir, repo_root, rel_path)
        merge_strategy = str(item.get("merge_strategy", "") or item.get("merge", "")).strip()

        if "content" in item:
            content = item.get("content")
            if isinstance(content, dict) or isinstance(content, list):
                data = (json.dumps(content, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            else:
                data = str(content).encode("utf-8")
        else:
            url = str(item.get("url", "")).strip()
            if not url:
                raise RuntimeError(f"manifest file missing url/content: {rel_path}")
            data = fetch_bytes(url, timeout_seconds)

        expected = str(item.get("sha256", "")).strip().lower()
        if require_checksum:
            if not expected:
                raise RuntimeError(f"checksum required but missing sha256 for {rel_path}")
            actual = sha256_hex(data)
            if actual != expected:
                raise RuntimeError(f"sha256 mismatch for {rel_path}: expected={expected} actual={actual}")

        if bool(item.get("render_project_context", False)):
            data = render_project_context(data, harness_dir)
        rendered.append((target, data, merge_strategy))
    return rendered


def hook_group_signature(group: dict[str, Any]) -> str:
    matcher = group.get("matcher", "")
    hooks = group.get("hooks", [])
    hook_sigs = []
    if isinstance(hooks, list):
        for hook in hooks:
            if isinstance(hook, dict):
                hook_sigs.append(f"{hook.get('type', '')}:{hook.get('command', '')}")
    return f"{matcher}|{'|'.join(hook_sigs)}"


def load_json_object_from_bytes(data: bytes, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{label} must be a JSON object: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{label} must be a JSON object")
    return payload


def load_existing_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot merge invalid JSON file {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"cannot merge non-object JSON file {path}")
    return payload


def build_managed_markdown_block(content: str) -> str:
    body = content.strip()
    return f"{MANAGED_BLOCK_BEGIN}\n{body}\n{MANAGED_BLOCK_END}\n"


def looks_like_legacy_by_harness_doc(content: str) -> bool:
    if MANAGED_BLOCK_BEGIN in content and MANAGED_BLOCK_END in content:
        return False
    return (
        "本项目采用 Harness Engineering 工作流" in content
        and ("Codex 意图路由" in content or "Claude 意图路由" in content)
    )


def merge_markdown_block(existing: str, managed_content: str) -> str:
    block = build_managed_markdown_block(managed_content)
    if MANAGED_BLOCK_BEGIN in existing and MANAGED_BLOCK_END in existing:
        prefix, rest = existing.split(MANAGED_BLOCK_BEGIN, 1)
        _, suffix = rest.split(MANAGED_BLOCK_END, 1)
        return prefix.rstrip() + "\n\n" + block + suffix.lstrip()
    if looks_like_legacy_by_harness_doc(existing):
        return block
    preserved = existing.rstrip()
    if not preserved:
        return block
    return preserved + "\n\n" + block


def merge_hook_groups(existing: dict[str, Any], template: dict[str, Any]) -> None:
    if "hooks" not in existing or not isinstance(existing.get("hooks"), dict):
        existing["hooks"] = {}
    for event_name, groups in template.get("hooks", {}).items():
        if not isinstance(groups, list):
            continue
        if event_name not in existing["hooks"] or not isinstance(existing["hooks"][event_name], list):
            existing["hooks"][event_name] = groups
            continue
        existing_sigs = {
            hook_group_signature(group)
            for group in existing["hooks"][event_name]
            if isinstance(group, dict)
        }
        for group in groups:
            if not isinstance(group, dict):
                continue
            sig = hook_group_signature(group)
            if sig not in existing_sigs:
                existing["hooks"][event_name].append(group)
                existing_sigs.add(sig)


def merge_permissions(existing: dict[str, Any], template: dict[str, Any]) -> None:
    existing_permissions = existing.get("permissions", {})
    template_permissions = template.get("permissions", {})
    if not isinstance(existing_permissions, dict):
        existing_permissions = {}
    if not isinstance(template_permissions, dict):
        template_permissions = {}
    merged_permissions = {}
    for key in ("allow", "deny"):
        values = []
        for source in (existing_permissions.get(key, []), template_permissions.get(key, [])):
            if not isinstance(source, list):
                continue
            for item in source:
                if item not in values:
                    values.append(item)
        if values:
            merged_permissions[key] = values
    if merged_permissions:
        existing["permissions"] = merged_permissions


def render_merge_strategy(target: Path, data: bytes, merge_strategy: str) -> bytes:
    if merge_strategy == "markdown_block":
        template = data.decode("utf-8")
        existing = target.read_text(encoding="utf-8") if target.exists() else ""
        return merge_markdown_block(existing, template).encode("utf-8")

    template = load_json_object_from_bytes(data, str(target))
    existing = load_existing_json_object(target)
    if merge_strategy == "codex_hooks":
        merge_hook_groups(existing, template)
    elif merge_strategy == "claude_settings":
        merge_hook_groups(existing, template)
        merge_permissions(existing, template)
    else:
        raise RuntimeError(f"unsupported merge_strategy for {target}: {merge_strategy}")
    return (json.dumps(existing, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def write_rendered_files(rendered: list[tuple[Path, bytes, str]], dry_run: bool) -> int:
    count = 0
    for target, data, merge_strategy in rendered:
        if dry_run:
            action = "merge file" if merge_strategy else "write file"
            print(f"[dry-run] {action}: {target}")
            count += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if merge_strategy:
            data = render_merge_strategy(target, data, merge_strategy)
        target.write_bytes(data)
        if target.suffix in {".py", ".sh"}:
            target.chmod(target.stat().st_mode | 0o755)
        count += 1
    return count


def run_known_migrations(harness_dir: Path, current_version: str, target_version: str, dry_run: bool) -> dict[str, int]:
    stats = {"task_json_changed": 0, "context_cleaned": 0, "files_removed": 0, "claude_promoted": 0, "layout_moved": 0}
    version = current_version
    while True:
        step = MIGRATIONS.get(version)
        if step is None:
            break
        next_version, step_name = step
        if semver_gt(next_version, target_version):
            break
        print(f"Apply migration: {version} -> {next_version} ({step_name})")
        result = run_migration(step_name, harness_dir, dry_run)
        for k, v in result.items():
            stats[k] = stats.get(k, 0) + int(v)
        version = next_version
    return stats


def apply_remote_update(
    *,
    harness_dir: Path,
    repo_root: Path,
    manifest: dict[str, Any],
    current_version: str,
    target_version: str,
    files: list[dict[str, Any]],
    backup_root: Path,
    no_backup: bool,
    dry_run: bool,
    timeout_seconds: int,
    require_checksum: bool,
) -> tuple[int, dict[str, int]]:
    backup_targets = [task_json_path(harness_dir), runtime_version_path(harness_dir), repo_root / "CLAUDE.md"]
    backup_targets.extend(harness_dir / "scripts" / name for name in RUNTIME_SCRIPT_NAMES)
    backup_targets.extend(secure_target_path(harness_dir, repo_root, rel) for rel in RUNTIME_DOC_REL_PATHS)
    if no_backup:
        print("Backup: skipped (--no-backup)")
        backed_up = 0
    else:
        backed_up = backup_files(harness_dir, backup_root, backup_targets, dry_run)
        print(f"Backup files: {backed_up} -> {backup_root}")

    rendered = materialize_manifest_files(
        harness_dir,
        repo_root,
        files,
        timeout_seconds=timeout_seconds,
        require_checksum=require_checksum,
    )
    updated_files = write_rendered_files(rendered, dry_run)
    print(f"Manifest files applied: {updated_files}")

    stats = run_known_migrations(harness_dir, current_version, target_version, dry_run)
    layout = migrate_grouped_layout(harness_dir, dry_run)
    stats["layout_moved"] = stats.get("layout_moved", 0) + layout.get("layout_moved", 0)
    wrote_version = write_runtime_version(
        harness_dir,
        target_version,
        dry_run,
        updated_by="update_runtime.py(remote)",
    )
    print(f"Runtime version file updated: {'yes' if wrote_version else 'no-change'}")
    return backed_up, stats


def fallback_local_update(
    *,
    harness_dir: Path,
    repo_root: Path,
    current_version: str,
    backup_root: Path,
    no_backup: bool,
    dry_run: bool,
) -> None:
    backup_targets = [task_json_path(harness_dir), runtime_version_path(harness_dir), repo_root / "CLAUDE.md"]
    backup_targets.extend(harness_dir / "scripts" / name for name in RUNTIME_SCRIPT_NAMES)
    backup_targets.extend(secure_target_path(harness_dir, repo_root, rel) for rel in RUNTIME_DOC_REL_PATHS)
    if no_backup:
        print("Backup: skipped (--no-backup)")
    else:
        backed_up = backup_files(harness_dir, backup_root, backup_targets, dry_run)
        print(f"Backup files: {backed_up} -> {backup_root}")

    stats = run_known_migrations(harness_dir, current_version, LATEST_RUNTIME_VERSION, dry_run)
    layout = migrate_grouped_layout(harness_dir, dry_run)
    stats["layout_moved"] = stats.get("layout_moved", 0) + layout.get("layout_moved", 0)
    target_version = LATEST_RUNTIME_VERSION
    if semver_gt(current_version, LATEST_RUNTIME_VERSION):
        # 当前版本已经高于本地内置迁移认知版本，禁止本地 fallback 降级覆盖。
        target_version = current_version
        print(
            "Local fallback keep current runtime version (no downgrade): "
            f"current={current_version} latest_known={LATEST_RUNTIME_VERSION}"
        )
    wrote_version = write_runtime_version(
        harness_dir,
        target_version,
        dry_run,
        updated_by="update_runtime.py(local-fallback)",
    )
    print(f"Runtime version file updated: {'yes' if wrote_version else 'no-change'}")
    print(
        "Migration summary: "
        f"task_json_changed={stats['task_json_changed']}, "
        f"context_cleaned={stats['context_cleaned']}, "
        f"files_removed={stats['files_removed']}, "
        f"layout_moved={stats.get('layout_moved', 0)}"
    )


def resolve_backup_root(args: argparse.Namespace, harness_dir: Path) -> Path:
    if args.backup_dir:
        return Path(args.backup_dir).resolve()
    return harness_dir / "backups" / f"update-{datetime.now().strftime('%Y%m%d-%H%M%S')}"


def main() -> int:
    args = parse_args()
    target_dir = Path(args.target_dir).resolve()
    try:
        harness_dir = detect_harness_dir(target_dir)
    except RuntimeError as exc:
        print(f"Error: {exc}")
        return 1

    pre_layout = migrate_grouped_layout(harness_dir, args.dry_run)
    if pre_layout.get("layout_moved", 0) > 0:
        print(f"Layout migration applied before update: moved={pre_layout.get('layout_moved', 0)}")
    if promote_claude_to_repo_root(harness_dir, args.dry_run):
        print("Layout migration applied before update: promoted .harness/CLAUDE.md -> root/CLAUDE.md")

    task_path = task_json_path(harness_dir)
    if not task_path.exists():
        print(f"Error: task.json 不存在（new/legacy 均未找到）：{task_path}")
        return 1

    policy = load_policy(harness_dir)
    state = load_state(harness_dir)
    repo_root = harness_dir.parent
    current_version, source = infer_current_version(harness_dir)
    if parse_semver(current_version) is None:
        print(f"Error: 无法识别当前版本：{current_version}")
        return 1

    print(f"Update target: {harness_dir}")
    print(f"Current runtime version: {current_version} (source={source})")
    print(f"Updater known latest: {LATEST_RUNTIME_VERSION}")
    if args.dry_run:
        print("Mode: dry-run")

    manifest_url = str(args.manifest_url or policy.get("manifest_url", "")).strip()
    if semver_gt(current_version, LATEST_RUNTIME_VERSION) and not manifest_url:
        print(
            "Warning: 当前项目版本高于本地 updater 的内置迁移版本，且未配置 manifest_url。"
            f" current={current_version} latest_known={LATEST_RUNTIME_VERSION}"
        )
        print("Warning: 仅可执行有限本地迁移；建议尽快配置远程更新源。")
    timeout_seconds = max(1, to_int(policy.get("request_timeout_seconds", 10), 10))
    require_checksum = bool(policy.get("require_checksum", True))
    backup_root = resolve_backup_root(args, harness_dir)

    # Automatic periodic mode: check policy + interval; auto-apply by bump rules.
    if args.check_remote:
        should_check, reason = should_check_remote(policy, state, args.force_check)
        if not should_check:
            print(f"Remote check skipped: {reason}")
            return 0
        print(f"Remote check trigger: {reason}")
        if not manifest_url:
            print("Remote check skipped: manifest_url not configured in .harness/config/update-policy.json")
            update_state_after_check(
                harness_dir,
                state,
                result="skipped-no-manifest-url",
                dry_run=args.dry_run,
            )
            return 0

        try:
            manifest = fetch_manifest(manifest_url, timeout_seconds)
            target_version, files = validate_manifest(manifest, current_version)
        except (RuntimeError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            print(f"Remote check failed: {exc}")
            update_state_after_check(
                harness_dir,
                state,
                result="check-failed",
                error=str(exc),
                dry_run=args.dry_run,
            )
            return 0

        if not semver_gt(target_version, current_version):
            print(f"Remote runtime is up-to-date: {target_version}")
            update_state_after_check(
                harness_dir,
                state,
                result="up-to-date",
                remote_version=target_version,
                dry_run=args.dry_run,
            )
            return 0

        bump = classify_bump(current_version, target_version)
        auto_apply = decide_auto_apply(policy, current_version, target_version)
        print(f"Remote update available: {current_version} -> {target_version} (bump={bump})")
        if not auto_apply:
            print("Auto-apply blocked by policy; update is only recorded.")
            update_state_after_check(
                harness_dir,
                state,
                result="update-available-policy-blocked",
                remote_version=target_version,
                dry_run=args.dry_run,
            )
            return 0

        try:
            apply_remote_update(
                harness_dir=harness_dir,
                repo_root=repo_root,
                manifest=manifest,
                current_version=current_version,
                target_version=target_version,
                files=files,
                backup_root=backup_root,
                no_backup=args.no_backup,
                dry_run=args.dry_run,
                timeout_seconds=timeout_seconds,
                require_checksum=require_checksum,
            )
        except (RuntimeError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            print(f"Remote apply failed: {exc}")
            update_state_after_check(
                harness_dir,
                state,
                result="apply-failed",
                remote_version=target_version,
                error=str(exc),
                dry_run=args.dry_run,
            )
            return 0

        update_state_after_check(
            harness_dir,
            state,
            result="updated",
            remote_version=target_version,
            dry_run=args.dry_run,
        )
        print("Done.")
        return 0

    # Manual mode: if manifest exists -> force check + apply latest; else fallback local migrations.
    if manifest_url:
        print("Manual mode: manifest configured, force check latest remote runtime.")
        try:
            manifest = fetch_manifest(manifest_url, timeout_seconds)
            target_version, files = validate_manifest(manifest, current_version)
        except (RuntimeError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            print(f"Remote fetch failed: {exc}")
            return 1

        if semver_gt(target_version, current_version):
            print(f"Apply remote update: {current_version} -> {target_version}")
            try:
                apply_remote_update(
                    harness_dir=harness_dir,
                    repo_root=repo_root,
                    manifest=manifest,
                    current_version=current_version,
                    target_version=target_version,
                    files=files,
                    backup_root=backup_root,
                    no_backup=args.no_backup,
                    dry_run=args.dry_run,
                    timeout_seconds=timeout_seconds,
                    require_checksum=require_checksum,
                )
            except (RuntimeError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                print(f"Remote apply failed: {exc}")
                return 1
            print("Done.")
            return 0
        if semver_gt(current_version, target_version):
            print(
                "Remote runtime is older than current; skip version overwrite: "
                f"current={current_version} remote={target_version}"
            )
            print("Done.")
            return 0
        print(f"Remote runtime is already latest: {target_version}")
        wrote = write_runtime_version(
            harness_dir,
            target_version,
            args.dry_run,
            updated_by="update_runtime.py(remote-manual-noop)",
        )
        print(f"Runtime version file updated: {'yes' if wrote else 'no-change'}")
        print("Done.")
        return 0

    print("Manual mode: manifest_url not configured, run local migration fallback only.")
    fallback_local_update(
        harness_dir=harness_dir,
        repo_root=repo_root,
        current_version=current_version,
        backup_root=backup_root,
        no_backup=args.no_backup,
        dry_run=args.dry_run,
    )
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
