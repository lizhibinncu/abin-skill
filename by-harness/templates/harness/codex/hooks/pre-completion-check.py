#!/usr/bin/env python3
"""
Pre-Completion Checklist Hook for Harness Engineering Framework.

PostToolUse hook that injects a verification reminder when a task is marked complete.

This implements the "Self-Verify First" golden principle from LangChain's research:
models are biased toward their first plausible solution. Forcing a verification
checklist before marking work done catches issues that would otherwise slip through.

Hook output format:
- {"systemMessage": "..."} to inject context without blocking
- {"decision": "block", "reason": "..."} to block completion when passed features miss required artifacts
"""

import json
import sys
from pathlib import Path

HARNESS_DIR_NAME = ".harness"


CHECKLIST = [
    "1. 代码是否能无错误编译/构建？",
    "2. 既有测试和新增测试是否全部通过？",
    "3. contract 中的验收标准是否已逐条核对？",
    "4. 若本轮映射到 feature，passes=true 前 spec_path 和 contract_path 是否都真实存在？",
    "5. 是否已清理 console.log/TODO/临时代码等调试残留？",
    "6. 行为变化时，相关文档是否已更新？",
    "7. 所有新增/修改函数和方法是否都有清晰中文注释？",
    "8. 若修改 Java，Java 总门禁与触发维度核心门禁是否已逐条核对？",
    "9. 若修改 Java，业务状态、任务类型、动作类型、错误码、配置 key、阈值是否已使用 enum、语义常量或配置项，未散落魔法字符串/魔法数字？",
    "10. 若修改 Java，分布式 Java 门禁是否已声明未触发理由，或已核对触发条款？",
    "11. 若修改 Java/MyBatis/SQL，convention-check.py --changed-only 是否无 FAIL，WARN 是否已修复或解释？",
]

TASK_HARNESS_CHECKLIST = [
    "12. 若本轮映射到 task-harness 任务，passes=true 前单元测试是否已通过？",
    "13. QA 报告是否已记录（非阻塞），进度日志是否已更新？",
]


def emit(payload):
    print(json.dumps(payload, ensure_ascii=False))


def find_workspace(cwd: Path) -> Path:
    for current in (cwd, *cwd.parents):
        if current.name == HARNESS_DIR_NAME:
            return current
        harness = current / HARNESS_DIR_NAME
        if harness.exists():
            return harness
    return cwd


def repo_root(workspace: Path) -> Path:
    return workspace.parent if workspace.name == HARNESS_DIR_NAME else workspace


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def resolve_path(workspace: Path, raw_path: str) -> Path:
    raw = str(raw_path or "").strip()
    root = repo_root(workspace)
    if not raw:
        return root / "__missing_artifact_path__"

    path = Path(raw)
    if path.is_absolute():
        return path

    candidates = [root / raw, workspace / raw]
    if raw.startswith(f"{HARNESS_DIR_NAME}/"):
        stripped = raw[len(HARNESS_DIR_NAME) + 1 :]
        candidates.append(workspace / stripped)
        candidates.append(root / stripped)

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def bucket_paths(workspace: Path) -> list[Path]:
    index_path = workspace / "task-harness" / "index.json"
    index = load_json(index_path)
    paths: list[Path] = []
    if isinstance(index, dict):
        for bucket in index.get("buckets", []):
            if not isinstance(bucket, dict):
                continue
            raw_path = str(bucket.get("path", "")).strip()
            if raw_path:
                paths.append(resolve_path(workspace, raw_path))

    paths.extend(
        [
            workspace / "feature_list.json",
            workspace / "task-harness" / "features" / "backlog-core.json",
        ]
    )
    deduped = []
    seen = set()
    for path in paths:
        key = str(path)
        if key not in seen:
            seen.add(key)
            deduped.append(path)
    return deduped


def task_paths(workspace: Path) -> list[Path]:
    index_path = workspace / "task-harness" / "index.json"
    index = load_json(index_path)
    patterns = ["task-harness/tasks/*.json"]
    if isinstance(index, dict) and isinstance(index.get("task_globs"), list):
        patterns = [str(item) for item in index["task_globs"] if str(item).strip()] or patterns

    paths: list[Path] = []
    seen = set()
    for pattern in patterns:
        base = resolve_path(workspace, pattern)
        if Path(pattern).is_absolute():
            candidates = sorted(base.parent.glob(base.name))
        else:
            candidates = sorted(workspace.glob(pattern))
        for path in candidates:
            key = str(path)
            if path.is_file() and key not in seen:
                seen.add(key)
                paths.append(path)
    return paths


def features_from_payload(data):
    if not isinstance(data, dict):
        return []
    if isinstance(data.get("features"), list):
        return [item for item in data["features"] if isinstance(item, dict)]
    if data.get("id") or data.get("description"):
        return [data]
    return []


def passed_feature_artifact_errors(workspace: Path) -> list[str]:
    errors = []
    seen = set()
    for feature_path in [*task_paths(workspace), *bucket_paths(workspace)]:
        if not feature_path.exists():
            continue
        data = load_json(feature_path)
        for feature in features_from_payload(data):
            if not bool(feature.get("passes")):
                continue
            feature_id = str(feature.get("id", "unknown")).strip() or "unknown"
            dedupe_key = (feature_id, str(feature_path))
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            for field_name in ("spec_path", "contract_path"):
                raw_path = str(feature.get(field_name, "")).strip()
                artifact_path = resolve_path(workspace, raw_path)
                if not raw_path or not artifact_path.exists() or not artifact_path.is_file():
                    errors.append(
                        f"- {feature_id}: {field_name} missing -> {raw_path or '(empty)'} "
                        f"(task source: {feature_path})"
                    )
    return errors


def main():
    # Read hook input from stdin
    try:
        input_data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        emit({})
        return

    # Check if this is a TaskUpdate with status=completed
    tool_name = input_data.get('tool_name', '')
    tool_input = input_data.get('tool_input', {})

    if tool_name != 'TaskUpdate':
        emit({})
        return

    status = tool_input.get('status', '')
    if status != 'completed':
        emit({})
        return

    checklist = list(CHECKLIST)
    cwd = Path.cwd()
    workspace = find_workspace(cwd)
    has_task_harness = (
        (workspace / 'task-harness' / 'index.json').exists()
        or (workspace / 'task-harness' / 'tasks').exists()
        or (workspace / 'feature_list.json').exists()
    )
    if has_task_harness:
        checklist.extend(TASK_HARNESS_CHECKLIST)

    artifact_errors = passed_feature_artifact_errors(workspace) if has_task_harness else []
    if artifact_errors:
        message = (
            "Artifact gate failed: features marked passes=true must have real spec and contract files.\n"
            + "\n".join(artifact_errors[:20])
            + ("\n- ... more missing artifacts omitted." if len(artifact_errors) > 20 else "")
            + "\n\nFix by creating/updating the missing spec/contract files, or set passes=false until they exist."
        )
        emit({"decision": "block", "reason": message})
        return

    # Inject pre-completion checklist
    message = (
        "Pre-completion checklist — verify ALL items before confirming done:\n"
        + "\n".join(checklist)
        + "\n\nIf any item fails, fix it before marking the task complete."
    )

    emit({"systemMessage": message})


if __name__ == '__main__':
    main()
