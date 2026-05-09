#!/usr/bin/env python3
"""Evaluate by-harness QA result JSON as a pass/fail gate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HARNESS_DIR_NAME = ".harness"


def parse_args():
    parser = argparse.ArgumentParser(description="Check by-harness QA gate result.")
    parser.add_argument("--target-dir", default=".", help="目标项目目录")
    parser.add_argument("--result-json", default="", help="QA result JSON 路径")
    parser.add_argument("--feature-id", default="", help="feature ID；未提供 result-json 时用于定位任务")
    return parser.parse_args()


def repo_root(target_dir: Path) -> Path:
    current = target_dir.resolve()
    return current.parent if current.name == HARNESS_DIR_NAME else current


def harness_dir(target_dir: Path) -> Path:
    root = repo_root(target_dir)
    candidate = root / HARNESS_DIR_NAME
    return candidate if candidate.exists() else target_dir.resolve()


def resolve_path(target_dir: Path, raw: str) -> Path:
    root = repo_root(target_dir)
    workspace = harness_dir(target_dir)
    text = str(raw or "").strip()
    if not text:
        return root / "__missing_path__"
    path = Path(text)
    if path.is_absolute():
        return path
    candidates = [root / text, workspace / text]
    if text.startswith(f"{HARNESS_DIR_NAME}/"):
        stripped = text[len(HARNESS_DIR_NAME) + 1 :]
        candidates.extend([workspace / stripped, root / stripped])
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def features_from_payload(payload):
    if not isinstance(payload, dict):
        return []
    if isinstance(payload.get("features"), list):
        return [item for item in payload["features"] if isinstance(item, dict)]
    if payload.get("id") or payload.get("description"):
        return [payload]
    return []


def task_files(workspace: Path) -> list[Path]:
    patterns = ["task-harness/tasks/*.json", "task-harness/tasks/**/*.json"]
    paths = []
    seen = set()
    for pattern in patterns:
        for path in sorted(workspace.glob(pattern)):
            key = str(path)
            if path.is_file() and key not in seen:
                seen.add(key)
                paths.append(path)
    for path in (
        workspace / "feature_list.json",
        workspace / "task-harness" / "features" / "backlog-core.json",
    ):
        if path.exists() and str(path) not in seen:
            paths.append(path)
    return paths


def find_feature(workspace: Path, feature_id: str):
    target = str(feature_id or "").strip()
    if not target:
        return None
    for path in task_files(workspace):
        try:
            payload = load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        for feature in features_from_payload(payload):
            if str(feature.get("id", "")).strip() == target:
                return feature
    return None


def result_path_from_feature(target_dir: Path, feature_id: str) -> Path | None:
    workspace = harness_dir(target_dir)
    feature = find_feature(workspace, feature_id)
    if not feature:
        return None
    raw = str(feature.get("qa_report_path", "")).strip()
    if not raw:
        return None
    report_path = resolve_path(target_dir, raw)
    if report_path.suffix:
        return report_path.with_suffix(".result.json")
    return report_path.parent / f"{report_path.name}.result.json"


def check_result(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, f"QA result JSON missing: {path}"
    try:
        result = load_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"QA result JSON invalid: {path}: {exc}"
    gate_status = str(result.get("gate_status", "")).strip().upper()
    summary = result.get("summary", {}) if isinstance(result.get("summary"), dict) else {}
    if gate_status == "PASS":
        return True, (
            "QA gate PASS "
            f"(required {summary.get('required_passed', 0)}/{summary.get('required_total', 0)}, "
            f"manual {summary.get('manual_total', 0)})"
        )
    return False, (
        "QA gate FAIL "
        f"(required {summary.get('required_passed', 0)}/{summary.get('required_total', 0)}, "
        f"required_failed {summary.get('required_failed', 0)}, "
        f"advisory_failed {summary.get('advisory_failed', 0)}): {path}"
    )


def main():
    args = parse_args()
    target_dir = Path(args.target_dir).resolve()
    if args.result_json:
        result_path = resolve_path(target_dir, args.result_json)
    else:
        result_path = result_path_from_feature(target_dir, args.feature_id)
    if not result_path:
        print("QA gate FAIL: provide --result-json or a feature with qa_report_path", file=sys.stderr)
        sys.exit(1)
    ok, message = check_result(result_path)
    stream = sys.stdout if ok else sys.stderr
    print(message, file=stream)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
