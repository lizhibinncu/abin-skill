#!/usr/bin/env python3
"""
Session close helper for by-harness projects.

Actions:
1) Write session log (per-session shard in file_tasks mode / monthly append in legacy mode)
2) Write a per-session snapshot in file_tasks mode; legacy sharded mode still refreshes latest.txt
3) Print next task recommendation
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import task_store

HARNESS_DIR_NAME = ".harness"
SESSION_MODE_SOFT = "soft_reset"
SESSION_MODE_HARD = "hard_new_session"
VALID_OUTCOMES = ("pass", "fail", "blocked", "in-progress")
OUTCOME_ALIASES = {
    "complete": "pass",
    "completed": "pass",
    "done": "pass",
    "passed": "pass",
    "success": "pass",
    "failed": "fail",
    "failure": "fail",
    "block": "blocked",
    "blocked": "blocked",
    "in_progress": "in-progress",
    "in-progress": "in-progress",
    "progress": "in-progress",
    "wip": "in-progress",
}


class HarnessJsonError(RuntimeError):
    """Raised when harness JSON storage cannot be read or parsed."""


def parse_args():
    parser = argparse.ArgumentParser(description="Close current by-harness session.")
    parser.add_argument("--target-dir", required=True, help="目标项目目录")
    parser.add_argument("--feature-id", default="", help="本次会话处理的 feature ID（可选）")
    parser.add_argument(
        "--outcome",
        default="in-progress",
        help="本次会话结果：pass/fail/blocked/in-progress（completed 兼容映射为 pass）",
    )
    parser.add_argument(
        "--qa-score",
        type=float,
        default=-1,
        help="QA 分数（未知可不填）",
    )
    parser.add_argument(
        "--note",
        action="append",
        default=[],
        help="本次会话说明（可重复）",
    )
    args = parser.parse_args()
    try:
        args.outcome = normalize_outcome(args.outcome)
    except ValueError as exc:
        parser.error(str(exc))
    return args


def normalize_outcome(raw: str) -> str:
    value = str(raw or "").strip().lower()
    outcome = OUTCOME_ALIASES.get(value, value)
    if outcome not in VALID_OUTCOMES:
        allowed = ", ".join(VALID_OUTCOMES)
        raise ValueError(f"argument --outcome: invalid choice: {raw!r} (choose from {allowed})")
    return outcome


def load_json(path: Path):
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HarnessJsonError(f"failed to read JSON: {path}: {exc}") from exc
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise HarnessJsonError(f"invalid JSON: {path}:{exc.lineno}:{exc.colno}: {exc.msg}") from exc


def dump_text(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def dump_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def count_sessions(log_content: str) -> int:
    matches = re.findall(r"会话 #(\d+)\s*-", log_content)
    if not matches:
        return 0
    return max(int(item) for item in matches)


def detect_workspace_dir(target_dir: Path) -> Path:
    harness_dir = target_dir / HARNESS_DIR_NAME
    if harness_dir.exists():
        return harness_dir
    return target_dir


def resolve_store(workspace_dir: Path):
    index_path = workspace_dir / "task-harness" / "index.json"
    if not index_path.exists():
        return {"mode": "legacy", "index": None, "index_path": index_path}
    index = load_json(index_path)
    return {"mode": "sharded", "index": index, "index_path": index_path}


def normalize_session_mode(raw: str) -> str:
    value = str(raw or "").strip().lower()
    if value in {"hard_new_session", "hard", "new_session"}:
        return SESSION_MODE_HARD
    if value in {"soft_reset", "soft", "reset"}:
        return SESSION_MODE_SOFT
    return SESSION_MODE_SOFT


def load_session_control(workspace_dir: Path) -> dict[str, str]:
    control = {"context_mode": SESSION_MODE_SOFT}
    task_path = workspace_dir / "config" / "task.json"
    if not task_path.exists():
        task_path = workspace_dir / "task.json"
    if not task_path.exists():
        return control
    try:
        data = load_json(task_path)
    except (HarnessJsonError, json.JSONDecodeError, OSError, ValueError):
        return control
    harness = data.get("harness", {})
    if not isinstance(harness, dict):
        return control

    session_control = harness.get("session_control", {})
    if isinstance(session_control, dict):
        context_mode = session_control.get("mode", "")
        if context_mode:
            control["context_mode"] = normalize_session_mode(str(context_mode))
    legacy_mode = harness.get("session_mode", "")
    if legacy_mode:
        control["context_mode"] = normalize_session_mode(str(legacy_mode))
    return control


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


def load_all_features(workspace_dir: Path, store):
    if store["mode"] == "legacy":
        for feature_path in (
            workspace_dir / "feature_list.json",
            workspace_dir / "task-harness" / "features" / "backlog-core.json",
        ):
            if not feature_path.exists():
                continue
            data = load_json(feature_path)
            features = data.get("features", [])
            if isinstance(features, list):
                return features
        return []

    all_features = []
    index = store["index"] or {}
    for bucket in index.get("buckets", []):
        rel_path = bucket.get("path", "")
        if not rel_path:
            continue
        feature_path = resolve_bucket_feature_path(workspace_dir, rel_path)
        if feature_path.exists():
            data = load_json(feature_path)
            features = data.get("features", [])
            if isinstance(features, list):
                all_features.extend(features)
    return all_features


def normalize_feature_id(feature_id: str) -> str:
    text = str(feature_id or "").strip().lower()
    match = re.match(r"^([a-z0-9_-]+)-0*(\d+)$", text)
    if match:
        return f"{match.group(1)}-{int(match.group(2))}"
    return text


def find_feature(features, feature_id: str):
    if not feature_id:
        return None
    target_raw = str(feature_id).strip()
    target_norm = normalize_feature_id(target_raw)
    for feat in features:
        if str(feat.get("id", "")).strip() == target_raw:
            return feat
    for feat in features:
        if normalize_feature_id(str(feat.get("id", ""))) == target_norm:
            return feat
    return None


def repo_root_from_workspace(workspace_dir: Path) -> Path:
    return workspace_dir.parent if workspace_dir.name == HARNESS_DIR_NAME else workspace_dir


def resolve_artifact_path(workspace_dir: Path, raw_path: str) -> Path:
    raw = str(raw_path or "").strip()
    root = repo_root_from_workspace(workspace_dir)
    if not raw:
        return root / "__missing_artifact_path__"

    path = Path(raw)
    if path.is_absolute():
        return path

    candidates = [root / raw, workspace_dir / raw]
    if raw.startswith(f"{HARNESS_DIR_NAME}/"):
        stripped = raw[len(HARNESS_DIR_NAME) + 1 :]
        candidates.append(workspace_dir / stripped)
        candidates.append(root / stripped)

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def missing_required_artifacts(workspace_dir: Path, feature) -> list[str]:
    if not feature:
        return []
    errors = []
    for field_name in ("spec_path", "contract_path"):
        raw_path = str(feature.get(field_name, "")).strip()
        artifact_path = resolve_artifact_path(workspace_dir, raw_path)
        if not raw_path or not artifact_path.exists() or not artifact_path.is_file():
            errors.append(f"{field_name} missing -> {raw_path or '(empty)'}")
    return errors


def split_markdown_row(line: str) -> list[str]:
    text = line.strip()
    if not text.startswith("|"):
        return []
    return [cell.strip().lower() for cell in text.strip("|").split("|")]


def is_markdown_separator(cells: list[str]) -> bool:
    return bool(cells) and all(set(cell.replace(":", "")) <= {"-"} for cell in cells if cell)


def contract_has_required_gate(contract_path: Path) -> bool:
    try:
        lines = contract_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    in_matrix = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            in_matrix = "集成测试矩阵" in stripped or "Integration Test Matrix" in stripped
            continue
        if not in_matrix:
            continue
        cells = split_markdown_row(stripped)
        if not cells or is_markdown_separator(cells):
            continue
        if "required" in cells or "阻塞" in cells or "必须" in cells:
            return True
    return False


def qa_result_path_for_feature(workspace_dir: Path, feature) -> Path:
    raw_path = str(feature.get("qa_report_path", "")).strip() if feature else ""
    if raw_path:
        report_path = resolve_artifact_path(workspace_dir, raw_path)
        if report_path.suffix:
            return report_path.with_suffix(".result.json")
        return report_path.parent / f"{report_path.name}.result.json"
    feature_id = str(feature.get("id", "unknown")).strip() if feature else "unknown"
    return workspace_dir / "docs" / "qa" / f"{safe_filename(feature_id)}.result.json"


def load_qa_gate_status(workspace_dir: Path, feature) -> dict:
    result = {
        "required": False,
        "status": "NOT_REQUIRED",
        "result_path": "",
        "summary": {},
        "error": "",
    }
    if not feature:
        return result
    contract_raw = str(feature.get("contract_path", "")).strip()
    contract_path = resolve_artifact_path(workspace_dir, contract_raw)
    if not contract_raw or not contract_path.exists() or not contract_has_required_gate(contract_path):
        return result
    result["required"] = True
    result_path = qa_result_path_for_feature(workspace_dir, feature)
    result["result_path"] = str(result_path)
    if not result_path.exists():
        result["status"] = "MISSING"
        result["error"] = f"QA result JSON missing: {result_path}"
        return result
    try:
        data = load_json(result_path)
    except HarnessJsonError as exc:
        result["status"] = "INVALID"
        result["error"] = str(exc)
        return result
    result["status"] = str(data.get("gate_status", "")).strip().upper() or "UNKNOWN"
    summary = data.get("summary", {})
    if isinstance(summary, dict):
        result["summary"] = summary
    if result["status"] != "PASS":
        result["error"] = f"QA gate status is {result['status']}: {result_path}"
    return result


def sample_feature_ids(features, limit: int = 12):
    ids = []
    for feat in features:
        feat_id = str(feat.get("id", "")).strip()
        label = task_store.display_label(feat)
        if feat_id:
            ids.append(f"{label} ({feat_id})")
    ids = sorted(dict.fromkeys(ids))
    if len(ids) <= limit:
        return ", ".join(ids)
    return ", ".join(ids[:limit]) + f", ... (total {len(ids)})"


def task_summary(feature) -> str:
    if not feature:
        return "n/a"
    label = task_store.display_label(feature)
    desc = str(feature.get("description", "")).strip()
    title = str(feature.get("title", "")).strip()
    compact_desc = re.sub(r"[\s\-:：；，。、！？“”‘’（）【】《》]+", "", desc)
    compact_title = re.sub(r"[\s\-:：；，。、！？“”‘’（）【】《》]+", "", title)
    if not desc or desc == title or (compact_title and compact_desc.startswith(compact_title)):
        return label
    return f"{label} - {desc}"


def to_priority(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 10**9


def next_pending_feature(features, exclude_id: str = ""):
    pending = [f for f in features if not bool(f.get("passes")) and str(f.get("id", "")) != exclude_id]
    if not pending:
        return None
    pending.sort(key=lambda f: (to_priority(f.get("priority")), str(f.get("id", ""))))
    return pending[0]


def build_session_entry(
    session_no: int,
    feature,
    outcome: str,
    qa_score: float,
    notes,
    total: int,
    passed: int,
    next_feature,
    qa_gate_status: dict | None = None,
):
    now = datetime.now()
    feat_id = task_store.display_label(feature) if feature else "n/a"
    feat_desc = str(feature.get("description", "未指定任务")) if feature else "未指定任务"
    qa_text = f"{qa_score:.1f}" if qa_score >= 0 else "n/a"
    note_lines = notes if notes else ["本轮按闭环推进任务，详见提交与 QA 报告。"]
    next_text = (
        task_summary(next_feature)
        if next_feature
        else "无（全部任务已完成）"
    )

    entry = (
        "\n----------------------------------------\n"
        f"会话 #{session_no} - {feat_id}: {feat_desc}\n"
        "----------------------------------------\n"
        f"时间: {now.strftime('%Y-%m-%d %H:%M')}\n\n"
        "结果:\n"
        f"  - outcome: {outcome}\n"
        f"  - qa_score: {qa_text}\n"
    )

    if feature:
        entry += (
            f"  - spec: {feature.get('spec_path', 'n/a')}\n"
            f"  - contract: {feature.get('contract_path', 'n/a')}\n"
            f"  - qa_report: {feature.get('qa_report_path', 'n/a')}\n"
        )
    if qa_gate_status:
        entry += (
            f"  - qa_gate: {qa_gate_status.get('status', 'n/a')}\n"
            f"  - qa_gate_result: {qa_gate_status.get('result_path', 'n/a') or 'n/a'}\n"
        )

    entry += "\n完成工作:\n"
    for line in note_lines:
        entry += f"  - {line}\n"

    entry += (
        "\n进度:\n"
        f"  - 已完成: {passed}/{total}\n"
        f"  - 下一个: {next_text}\n"
        "\n下一会话建议:\n"
        "  1. bash .harness/scripts/init.sh（legacy 项目可用 bash .harness/init.sh）\n"
        "  2. 阅读 AGENTS.md 与 .harness/docs/TASK-HARNESS.md\n"
        f"  3. 优先处理: {next_text}\n"
        "  4. 执行 read task -> plan -> build -> qa gate -> fix -> mark_pass\n"
    )
    return entry


def append_session_log(log_path: Path, entry: str) -> int:
    content = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    session_no = count_sessions(content) + 1
    finalized = entry.replace("会话 #0 -", f"会话 #{session_no} -", 1)
    dump_text(log_path, content + finalized)
    return session_no


def write_file_task_session_log(log_path: Path, entry: str) -> int:
    finalized = entry.replace("会话 #0 -", "会话 #1 -", 1)
    dump_text(log_path, finalized)
    return 1


def build_latest_snapshot(feature, outcome: str, qa_score: float, total: int, passed: int, next_feature, log_path: Path, qa_gate_status: dict | None = None):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    feat_id = task_store.display_label(feature) if feature else "n/a"
    feat_desc = str(feature.get("description", "未指定任务")) if feature else "未指定任务"
    qa_text = f"{qa_score:.1f}" if qa_score >= 0 else "n/a"
    next_text = (
        task_summary(next_feature)
        if next_feature
        else "无（全部任务已完成）"
    )
    return (
        "# LATEST PROGRESS SNAPSHOT\n\n"
        f"- 更新时间: {now}\n"
        f"- 当前任务: {feat_id} - {feat_desc}\n"
        f"- 会话结果: {outcome}\n"
        f"- QA 分数: {qa_text}\n"
        f"- QA Gate: {(qa_gate_status or {}).get('status', 'n/a')}\n"
        f"- 任务进度: {passed}/{total}\n"
        f"- 下一任务建议: {next_text}\n"
        f"- 会话日志文件: {log_path.name}\n\n"
        "下一步:\n"
        "1. 运行 `.harness/scripts/init.sh`\n"
        "2. 阅读 `AGENTS.md` 和 `.harness/docs/TASK-HARNESS.md`\n"
        "3. 继续推进下一任务\n"
    )


def build_session_meta(feature, next_feature, outcome: str, context_mode: str, qa_gate_status: dict | None = None):
    closed_id = str(feature.get("id", "n/a")) if feature else "n/a"
    closed_desc = str(feature.get("description", "未指定任务")) if feature else "未指定任务"
    closed_display = task_store.display_label(feature) if feature else "n/a"
    payload = {
        "context_mode": context_mode,
        "generated_by": "session_close.py",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "closed_feature_id": closed_id,
        "closed_feature_display": closed_display,
        "closed_feature_description": closed_desc,
        "outcome": outcome,
        "qa_gate_status": (qa_gate_status or {}).get("status", ""),
        "qa_gate_result": (qa_gate_status or {}).get("result_path", ""),
    }
    if next_feature:
        payload["next_feature_id"] = str(next_feature.get("id", ""))
        payload["next_feature_display"] = task_store.display_label(next_feature)
        payload["next_feature_description"] = str(next_feature.get("description", ""))
    else:
        payload["next_feature_id"] = ""
        payload["next_feature_display"] = ""
        payload["next_feature_description"] = "无（全部任务已完成）"
    return payload


def safe_filename(value: str, fallback: str = "task") -> str:
    text = re.sub(r"[\\/:*?\"<>|#%{}^~`\[\]\n\r\t：；，。、！？“”‘’（）【】《》]+", "-", str(value or "").strip())
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"-{2,}", "-", text)
    return text.strip("-. _") or fallback


def use_file_task_progress(workspace_dir: Path, entries) -> bool:
    if any(entry.source_kind == "single" for entry in entries):
        return True
    index_path = workspace_dir / "task-harness" / "index.json"
    if not index_path.exists():
        return False
    try:
        index = load_json(index_path)
    except (HarnessJsonError, json.JSONDecodeError, OSError, ValueError):
        return False
    return isinstance(index, dict) and str(index.get("mode", "")).strip() == "file_tasks"


def bump_session_context(workspace_dir: Path, meta: dict, context_mode: str) -> tuple[Path, int]:
    context_path = workspace_dir / "config" / "session-context.json"
    if not context_path.exists():
        legacy = workspace_dir / "session-context.json"
        if legacy.exists():
            context_path = legacy
    epoch = 0
    if context_path.exists():
        try:
            existing = load_json(context_path)
            epoch = int(existing.get("epoch", 0))
        except (json.JSONDecodeError, OSError, ValueError, TypeError):
            epoch = 0

    epoch += 1
    payload = {
        "epoch": epoch,
        "context_mode": context_mode,
        "reset_required": context_mode == SESSION_MODE_SOFT,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "closed_feature_id": meta.get("closed_feature_id", ""),
        "closed_feature_display": meta.get("closed_feature_display", ""),
        "closed_feature_description": meta.get("closed_feature_description", ""),
        "next_feature_id": meta.get("next_feature_id", ""),
        "next_feature_display": meta.get("next_feature_display", ""),
        "next_feature_description": meta.get("next_feature_description", ""),
        "outcome": meta.get("outcome", ""),
        "qa_gate_status": meta.get("qa_gate_status", ""),
        "qa_gate_result": meta.get("qa_gate_result", ""),
    }
    dump_json(context_path, payload)
    return context_path, epoch


def write_hard_boundary(workspace_dir: Path, meta: dict, epoch: int) -> Path:
    boundary_path = workspace_dir / "config" / "session-boundary.json"
    if not boundary_path.exists():
        legacy = workspace_dir / "session-boundary.json"
        if legacy.exists():
            boundary_path = legacy
    payload = dict(meta)
    payload["require_new_session"] = True
    payload["epoch"] = epoch
    dump_json(boundary_path, payload)
    return boundary_path


def main():
    args = parse_args()
    target_dir = Path(args.target_dir).resolve()
    workspace_dir = detect_workspace_dir(target_dir)
    session_control = load_session_control(workspace_dir)
    context_mode = session_control["context_mode"]

    try:
        entries = task_store.load_task_entries(workspace_dir)
    except task_store.HarnessJsonError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    features = [entry.feature for entry in entries]
    if not isinstance(features, list):
        print("Error: feature list storage invalid")
        sys.exit(1)

    entry = task_store.find_entry(workspace_dir, args.feature_id)
    feature = entry.feature if entry else None
    if args.feature_id and feature is None:
        candidates = sample_feature_ids(features)
        print(f"Error: feature id not found: {args.feature_id}")
        if candidates:
            print(f"Available feature ids: {candidates}")
        else:
            print("Available feature ids: none (task storage may be empty or misconfigured)")
        sys.exit(1)
    if args.outcome == "pass" and features and feature is None:
        print("Error: --feature-id is required when --outcome pass, so spec_path and contract_path can be verified.")
        sys.exit(1)
    if args.outcome == "pass" and feature:
        artifact_errors = missing_required_artifacts(workspace_dir, feature)
        if artifact_errors:
            print("Error: cannot close session as pass before required artifacts exist.")
            print(f"Feature: {feature.get('id', 'unknown')}")
            for error in artifact_errors:
                print(f"  - {error}")
            print("Create/update the missing spec and contract, or close with --outcome in-progress/blocked.")
            sys.exit(1)
        qa_gate_status = load_qa_gate_status(workspace_dir, feature)
        if qa_gate_status.get("required") and qa_gate_status.get("status") != "PASS":
            print("Error: cannot close session as pass before required QA Gate passes.")
            print(f"Feature: {feature.get('id', 'unknown')}")
            print(f"  - status: {qa_gate_status.get('status')}")
            print(f"  - result: {qa_gate_status.get('result_path') or 'n/a'}")
            print(f"  - error: {qa_gate_status.get('error') or 'n/a'}")
            print("Run .harness/scripts/qa_runner.py and fix required gate failures, or close with --outcome in-progress/blocked.")
            sys.exit(1)
    else:
        qa_gate_status = load_qa_gate_status(workspace_dir, feature) if feature else {}

    total = len(features)
    passed = sum(1 for feat in features if bool(feat.get("passes")))
    if feature and not bool(feature.get("passes")) and args.outcome in ("in-progress", "blocked"):
        next_feature = feature
    else:
        next_feature = next_pending_feature(
            features,
            exclude_id=str(feature.get("id", "")) if feature else "",
        )

    file_task_progress = use_file_task_progress(workspace_dir, entries)
    if file_task_progress:
        monthly = datetime.now().strftime("%Y-%m")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        feature_token = safe_filename(task_store.display_label(feature) if feature else "session")
        session_log_path = workspace_dir / "task-harness" / "progress" / monthly / f"{stamp}-{feature_token}.md"
    elif (workspace_dir / "task-harness" / "index.json").exists():
        monthly = datetime.now().strftime("%Y-%m")
        session_log_path = workspace_dir / "task-harness" / "progress" / f"{monthly}.md"
    else:
        session_log_path = workspace_dir / "progress.txt"

    entry = build_session_entry(
        session_no=0,
        feature=feature,
        outcome=args.outcome,
        qa_score=args.qa_score,
        notes=args.note,
        total=total,
        passed=passed,
        next_feature=next_feature,
        qa_gate_status=qa_gate_status,
    )
    if file_task_progress:
        session_no = write_file_task_session_log(session_log_path, entry)
    else:
        session_no = append_session_log(session_log_path, entry)

    if file_task_progress:
        snapshot_path = session_log_path.with_suffix(".snapshot.txt")
        snapshot = build_latest_snapshot(
            feature=feature,
            outcome=args.outcome,
            qa_score=args.qa_score,
            total=total,
            passed=passed,
            next_feature=next_feature,
            log_path=session_log_path,
            qa_gate_status=qa_gate_status,
        )
        dump_text(snapshot_path, snapshot)
        print(f"Wrote session snapshot: {snapshot_path}")
    elif (workspace_dir / "task-harness" / "index.json").exists():
        snapshot_path = workspace_dir / "task-harness" / "progress" / "latest.txt"
        snapshot = build_latest_snapshot(
            feature=feature,
            outcome=args.outcome,
            qa_score=args.qa_score,
            total=total,
            passed=passed,
            next_feature=next_feature,
            log_path=session_log_path,
            qa_gate_status=qa_gate_status,
        )
        dump_text(snapshot_path, snapshot)
        print(f"Updated latest snapshot: {snapshot_path}")

    meta = build_session_meta(
        feature=feature,
        next_feature=next_feature,
        outcome=args.outcome,
        context_mode=context_mode,
        qa_gate_status=qa_gate_status,
    )
    context_path, epoch = bump_session_context(
        workspace_dir=workspace_dir,
        meta=meta,
        context_mode=context_mode,
    )

    log_action = "Wrote" if file_task_progress else "Appended"
    print(f"{log_action} session log: {session_log_path} (session #{session_no})")
    print(f"Context mode: {context_mode}")
    print(f"Session context updated: {context_path} (epoch={epoch})")
    print("Auto-continue command: python3 .harness/scripts/task_switch.py continue --target-dir .")
    if context_mode == SESSION_MODE_HARD:
        boundary_path = write_hard_boundary(workspace_dir, meta, epoch)
        print(f"Session boundary marker: {boundary_path}")
        print("Session rotation required: start a NEW session before next feature.")
    else:
        print("Soft reset activated: current session should treat previous feature context as stale.")
    if next_feature:
        print(f"Next recommended task: {task_summary(next_feature)}")
    else:
        print("Next recommended task: none (all tasks are passed)")


if __name__ == "__main__":
    main()
