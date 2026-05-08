#!/usr/bin/env python3
"""
Context Injector Hook for Harness Engineering Framework.

UserPromptSubmit hook that injects project state context at the start of each session.

This implements the "Context Budget" and "Environment Context Injection" principles
from LangChain's research: agents perform better when they know about their environment,
current state, and active tasks.

Hook output format:
- {"systemMessage": "..."} to inject context without blocking
"""

import json
import re
import subprocess
import sys
from pathlib import Path

HARNESS_DIR_NAME = ".harness"
SESSION_MODE_SOFT = "soft_reset"
SESSION_MODE_HARD = "hard_new_session"
SQL_ORM_SPECIFIC_RE = re.compile(r"(mapper|mybatis|sql|dao|repository|分页|更新|查询)", re.IGNORECASE)
CODE_TRIGGER_RE = re.compile(r"(build|implement|code|编码|实现)", re.IGNORECASE)
SQL_ORM_RULE_CARD = "\n".join(
    [
        "本轮 SQL/ORM 门禁：",
        "- Java/Spring/MyBatis 改动前先读取 .harness/docs/java-dev-conventions.md。",
        "- SQL 必须写在 XML Mapper，禁止 @Select/@Update/@Insert/@Delete 注解 SQL。",
        "- 查询列必须显式列出，禁止 select *。",
        "- XML 参数必须使用 #{}，禁止 ${}。",
        "- 必须使用 resultMap，禁止 resultClass。",
        "- 行数统计必须使用 count(*)；sum() 必须用 IFNULL/COALESCE 兜底 NULL。",
        "- 更新记录必须维护 update_time。",
        "- 禁止外键、级联和存储过程承载业务逻辑。",
        "- 声称完成前运行 .claude/hooks/convention-check.py --changed-only。",
    ]
)


def get_git_info():
    """Get current git branch and recent commits."""
    info = {}
    try:
        branch = subprocess.check_output(
            ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
            stderr=subprocess.DEVNULL, timeout=5
        ).decode().strip()
        info['branch'] = branch
    except (subprocess.CalledProcessError, FileNotFoundError):
        info['branch'] = 'unknown (not a git repo)'

    try:
        recent = subprocess.check_output(
            ['git', 'log', '--oneline', '-5'],
            stderr=subprocess.DEVNULL, timeout=5
        ).decode().strip()
        info['recent_commits'] = recent
    except (subprocess.CalledProcessError, FileNotFoundError):
        info['recent_commits'] = ''

    return info


def collect_keyed_strings(obj, target_keys):
    found = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key.lower() in target_keys and isinstance(value, str) and value.strip():
                found.append(value.strip())
            found.extend(collect_keyed_strings(value, target_keys))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(collect_keyed_strings(item, target_keys))
    return found


def extract_prompt_text(hook_input):
    target_keys = {"prompt", "user_prompt", "message", "text", "content", "input"}
    candidates = collect_keyed_strings(hook_input, target_keys)
    if not candidates:
        return ""
    return sorted(candidates, key=len, reverse=True)[0]


def should_inject_sql_orm_rules(prompt_text: str) -> bool:
    cwd = Path.cwd()
    workspace = cwd / HARNESS_DIR_NAME if (cwd / HARNESS_DIR_NAME).exists() else cwd
    is_java_project = (workspace / "docs" / "java-dev-conventions.md").exists() and any(
        candidate.exists()
        for candidate in [
            cwd / "pom.xml",
            cwd / "build.gradle",
            cwd / "src" / "main" / "resources",
        ]
    )
    if SQL_ORM_SPECIFIC_RE.search(prompt_text or ""):
        return True
    return is_java_project and bool(CODE_TRIGGER_RE.search(prompt_text or ""))


def find_branch_script(repo: Path):
    candidates = [
        repo / HARNESS_DIR_NAME / "scripts" / "ensure_task_branch.py",
        repo / "scripts" / "ensure_task_branch.py",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def run_auto_branch(prompt_text):
    repo = Path.cwd()
    script_path = find_branch_script(repo)
    if script_path is None:
        return "Task sync: ensure_task_branch.py not found (skip)."

    cmd = ["python3", str(script_path), "--target-dir", str(repo)]
    if prompt_text:
        cmd.extend(["--prompt", prompt_text])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return "Task sync warning: failed to execute ensure_task_branch.py."

    output = (result.stdout or "").strip()
    if not output:
        output = (result.stderr or "").strip()
    output = output.replace("\r", "")
    if output:
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        output = " | ".join(lines[:4])

    if result.returncode == 0:
        return f"Task sync: {output or 'ok'}"
    return f"Task sync warning: {output or 'failed'}"


def get_project_state():
    """Scan for project state indicators."""
    state = {}
    cwd = Path.cwd()
    workspace = cwd / HARNESS_DIR_NAME if (cwd / HARNESS_DIR_NAME).exists() else cwd

    # Check for active specs
    specs_dir = workspace / 'docs' / 'specs'
    if specs_dir.exists():
        specs = list(specs_dir.glob('*.md'))
        if specs:
            state['active_specs'] = [s.name for s in sorted(specs, key=lambda x: x.stat().st_mtime, reverse=True)[:5]]

    # Check for active contracts
    contracts_dir = workspace / 'docs' / 'contracts'
    if contracts_dir.exists():
        contracts = [c for c in contracts_dir.glob('*.md') if c.name != 'TEMPLATE.md']
        if contracts:
            state['active_contracts'] = [c.name for c in sorted(contracts, key=lambda x: x.stat().st_mtime, reverse=True)[:5]]

    # Check for active plans
    plans_dir = workspace / 'docs' / 'plans'
    if plans_dir.exists():
        plans = list(plans_dir.glob('*.md'))
        if plans:
            state['active_plans'] = [p.name for p in sorted(plans, key=lambda x: x.stat().st_mtime, reverse=True)[:5]]

    return state


def resolve_task_feature_file(workspace: Path):
    legacy = workspace / 'feature_list.json'
    index_path = workspace / 'task-harness' / 'index.json'
    default_path = workspace / 'task-harness' / 'features' / 'backlog-core.json'

    if not index_path.exists():
        if legacy.exists():
            return legacy, 'legacy_feature_list'
        return default_path, 'active_bucket'

    try:
        index = json.loads(index_path.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError, ValueError):
        if legacy.exists():
            return legacy, 'legacy_feature_list'
        return default_path, 'active_bucket'

    buckets = index.get('buckets', [])
    active = str(index.get('active_bucket', '') or '')
    rel_path = ''
    if isinstance(buckets, list):
        for bucket in buckets:
            if str(bucket.get('id', '') or '') == active:
                rel_path = str(bucket.get('path', '') or '')
                break
        if not rel_path and buckets:
            rel_path = str((buckets[0] or {}).get('path', '') or '')
    if not rel_path:
        rel_path = 'task-harness/features/backlog-core.json'

    candidate = workspace / rel_path
    if candidate.exists():
        return candidate, 'active_bucket'
    if rel_path.startswith(f'{HARNESS_DIR_NAME}/'):
        alt = workspace / rel_path[len(HARNESS_DIR_NAME) + 1 :]
        if alt.exists():
            return alt, 'active_bucket'

    if legacy.exists():
        return legacy, 'legacy_feature_list'
    return default_path, 'active_bucket'


def task_source_paths(workspace: Path):
    paths = []
    seen = set()

    index_path = workspace / 'task-harness' / 'index.json'
    index = None
    if index_path.exists():
        try:
            index = json.loads(index_path.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError, ValueError):
            index = None

    default_patterns = ['task-harness/tasks/*.json', 'task-harness/tasks/**/*.json']
    patterns = list(default_patterns)
    if isinstance(index, dict) and isinstance(index.get('task_globs'), list):
        patterns = [str(item) for item in index.get('task_globs', []) if str(item).strip()] or patterns
    for default_pattern in default_patterns:
        if default_pattern not in patterns:
            patterns.append(default_pattern)
    for pattern in patterns:
        pattern_path = Path(pattern)
        if pattern_path.is_absolute():
            candidates = sorted(pattern_path.parent.glob(pattern_path.name))
        else:
            candidates = sorted(workspace.glob(pattern))
        for path in candidates:
            key = str(path)
            if path.is_file() and key not in seen:
                seen.add(key)
                paths.append((path, 'file_tasks'))

    if isinstance(index, dict):
        buckets = index.get('legacy_buckets', index.get('buckets', []))
        if isinstance(buckets, list):
            for bucket in buckets:
                if not isinstance(bucket, dict):
                    continue
                raw_path = str(bucket.get('path', '') or '').strip()
                if not raw_path:
                    continue
                candidate = workspace / raw_path
                if not candidate.exists() and raw_path.startswith(f'{HARNESS_DIR_NAME}/'):
                    candidate = workspace / raw_path[len(HARNESS_DIR_NAME) + 1 :]
                key = str(candidate)
                if key not in seen:
                    seen.add(key)
                    paths.append((candidate, 'legacy_bucket'))

    for path, source in [
        (workspace / 'feature_list.json', 'legacy_feature_list'),
        (workspace / 'task-harness' / 'features' / 'backlog-core.json', 'legacy_bucket'),
    ]:
        key = str(path)
        if key not in seen:
            seen.add(key)
            paths.append((path, source))
    return paths


def features_from_task_payload(data):
    if not isinstance(data, dict):
        return []
    if isinstance(data.get('features'), list):
        return [item for item in data['features'] if isinstance(item, dict)]
    if data.get('id') or data.get('description'):
        return [data]
    return []


def load_all_task_features(workspace: Path):
    features = []
    seen_ids = set()
    source = ''
    for path, source_name in task_source_paths(workspace):
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError, ValueError):
            continue
        for feature in features_from_task_payload(data):
            feature_id = str(feature.get('id', '') or '').strip()
            key = feature_id.lower()
            if key and key in seen_ids:
                continue
            if key:
                seen_ids.add(key)
            features.append(feature)
            source = source or source_name
    return features, source


def to_priority(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 10**9


def has_progress_shards(workspace: Path):
    progress = workspace / 'task-harness' / 'progress'
    if (progress / 'latest.txt').exists() or (workspace / 'progress.txt').exists():
        return True
    if not progress.exists():
        return False
    return any(path.is_file() and path.suffix == '.md' for path in progress.glob('*/*.md'))


def get_task_harness_state():
    """Scan task-harness state from v3 task files plus legacy buckets."""
    state = {}
    cwd = Path.cwd()
    workspace = cwd / HARNESS_DIR_NAME if (cwd / HARNESS_DIR_NAME).exists() else cwd
    workspace_label = f"{HARNESS_DIR_NAME}/" if workspace != cwd else ""

    features, source = load_all_task_features(workspace)
    if not features:
        return state

    total = len(features)
    passed = sum(1 for feat in features if bool(feat.get('passes')))
    pending = [feat for feat in features if not bool(feat.get('passes'))]
    pending_sorted = sorted(
        pending,
        key=lambda feat: (
            to_priority(feat.get('priority')),
            str(feat.get('created_at', '')),
            feat.get('id', ''),
        ),
    )

    state['total_features'] = total
    state['passed_features'] = passed
    state['pending_features'] = max(total - passed, 0)
    state['has_task_contract'] = (workspace / 'docs' / 'TASK-HARNESS.md').exists() or (workspace / 'TASK-HARNESS.md').exists()
    state['has_progress_log'] = has_progress_shards(workspace)
    state['workspace_label'] = workspace_label
    state['task_source'] = source or 'unknown'

    if pending_sorted:
        next_feat = pending_sorted[0]
        display_id = next_feat.get('display_id') or next_feat.get('id', 'unknown')
        title = next_feat.get('title') or next_feat.get('description', '')
        state['next_feature'] = {
            'id': display_id,
            'raw_id': next_feat.get('id', 'unknown'),
            'priority': next_feat.get('priority', '?'),
            'description': title,
        }

    return state


def normalize_session_mode(raw):
    value = str(raw or "").strip().lower()
    if value in {"hard_new_session", "hard", "new_session"}:
        return SESSION_MODE_HARD
    if value in {"soft_reset", "soft", "reset"}:
        return SESSION_MODE_SOFT
    return SESSION_MODE_SOFT


def get_session_mode(workspace: Path):
    task_path = workspace / "config" / "task.json"
    if not task_path.exists():
        task_path = workspace / "task.json"
    if not task_path.exists():
        return SESSION_MODE_SOFT
    try:
        data = json.loads(task_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, ValueError):
        return SESSION_MODE_SOFT
    harness = data.get("harness", {})
    if not isinstance(harness, dict):
        return SESSION_MODE_SOFT
    session_control = harness.get("session_control", {})
    if isinstance(session_control, dict):
        mode = session_control.get("mode", "")
        if mode:
            return normalize_session_mode(mode)
    return normalize_session_mode(harness.get("session_mode", ""))


def get_session_context_notice():
    cwd = Path.cwd()
    workspace = cwd / HARNESS_DIR_NAME if (cwd / HARNESS_DIR_NAME).exists() else cwd
    mode = get_session_mode(workspace)
    context_path = workspace / "config" / "session-context.json"
    if not context_path.exists():
        context_path = workspace / "session-context.json"
    boundary_path = workspace / "config" / "session-boundary.json"
    if not boundary_path.exists():
        boundary_path = workspace / "session-boundary.json"

    if mode == SESSION_MODE_HARD and boundary_path.exists():
        try:
            data = json.loads(boundary_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, ValueError):
            data = {}
        closed_id = str(data.get("closed_feature_display") or data.get("closed_feature_id", "n/a"))
        next_id = str(data.get("next_feature_display") or data.get("next_feature_id", "") or "n/a")
        return (
            "Session mode: hard_new_session. "
            f"Boundary active (closed={closed_id}, next={next_id}). "
            "Do not start next feature in this chat."
        )

    if mode == SESSION_MODE_SOFT and context_path.exists():
        try:
            data = json.loads(context_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, ValueError):
            return "Session mode: soft_reset. Session context file exists but parse failed."
        epoch = data.get("epoch", "n/a")
        reset_required = bool(data.get("reset_required"))
        closed_id = str(data.get("closed_feature_display") or data.get("closed_feature_id", "n/a"))
        next_id = str(data.get("next_feature_display") or data.get("next_feature_id", "") or "n/a")
        if reset_required:
            return (
                "Session mode: soft_reset. "
                f"Context epoch switched to {epoch} after feature {closed_id}. "
                f"Next feature hint: {next_id}. Ignore stale context from older feature turns."
            )
        return f"Session mode: soft_reset. Current context epoch={epoch}."

    return f"Session mode: {mode}."


def main():
    try:
        hook_input = json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, ValueError):
        hook_input = {}
    prompt_text = extract_prompt_text(hook_input)

    parts = []
    parts.append(run_auto_branch(prompt_text))
    parts.append(get_session_context_notice())

    # Git info
    git_info = get_git_info()
    if git_info.get('branch'):
        parts.append(f"Git branch: {git_info['branch']}")
    if git_info.get('recent_commits'):
        parts.append(f"Recent commits:\n{git_info['recent_commits']}")

    # Project state
    state = get_project_state()
    if state.get('active_specs'):
        parts.append(f"Active specs: {', '.join(state['active_specs'])}")
    if state.get('active_contracts'):
        parts.append(f"Active contracts: {', '.join(state['active_contracts'])}")
    if state.get('active_plans'):
        parts.append(f"Active plans: {', '.join(state['active_plans'])}")

    task_state = get_task_harness_state()
    if task_state:
        parts.append(
            "Task harness progress: "
            f"{task_state.get('passed_features', 0)}/{task_state.get('total_features', 0)} passed, "
            f"{task_state.get('pending_features', 0)} pending"
        )
        if task_state.get('next_feature'):
            next_feat = task_state['next_feature']
            parts.append(
                "Next feature: "
                f"[{next_feat.get('id')}] P{next_feat.get('priority')} {next_feat.get('description')}"
            )
        if not task_state.get('has_task_contract'):
            parts.append(
                'Warning: task harness state exists but '
                f"{task_state.get('workspace_label', '')}docs/TASK-HARNESS.md is missing."
            )
        if not task_state.get('has_progress_log'):
            parts.append(
                'Warning: task harness state exists but '
                f"{task_state.get('workspace_label', '')}task-harness/progress/YYYY-MM/*.md is missing."
            )
    if should_inject_sql_orm_rules(prompt_text):
        parts.append(SQL_ORM_RULE_CARD)
    parts.append(
        "Commit policy reminder: commit/push only on explicit user instruction; "
        "develop on current branch by default, and keep commit subject concise."
    )

    if not parts:
        print(json.dumps({}))
        return

    message = (
        "Project context:\n"
        + "\n".join(parts)
        + "\n\nUse this context to understand the current state. "
        + "Read relevant specs/contracts/plans/task files as needed "
        + "(context budget: only read what you need)."
    )

    print(json.dumps({"systemMessage": message}))


if __name__ == '__main__':
    main()
