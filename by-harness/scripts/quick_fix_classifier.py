#!/usr/bin/env python3
"""Classify whether a request can start in by-harness quick-fix mode."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

HARNESS_DIR_NAME = ".harness"

QUICK_TERMS = (
    "bug",
    "fix",
    "quick fix",
    "typo",
    "lint",
    "compile error",
    "test failure",
    "stack trace",
    "null",
    "nil",
    "empty",
    "fallback",
    "guard",
    "log level",
    "error message",
    "404",
    "500",
    "修复",
    "报错",
    "异常",
    "空指针",
    "空值",
    "编译失败",
    "测试失败",
    "日志",
    "错误提示",
)

HIGH_RISK_TERMS = (
    "migration",
    "schema",
    "database",
    "db",
    "sql",
    "auth",
    "permission",
    "security",
    "billing",
    "payment",
    "quota",
    "rate limit",
    "concurrency",
    "lock",
    "transaction",
    "idempotent",
    "redis",
    "cache",
    "mq",
    "kafka",
    "rpc",
    "public api",
    "api contract",
    "dto",
    "breaking",
    "rename",
    "delete",
    "权限",
    "鉴权",
    "安全",
    "计费",
    "扣费",
    "额度",
    "限流",
    "并发",
    "事务",
    "幂等",
    "缓存",
    "表结构",
    "迁移",
    "接口契约",
    "公共接口",
)

HIGH_RISK_PATH_PATTERNS = (
    r"(^|/)(migrations?|schema|sql|db|database)(/|$)",
    r"(^|/)(auth|security|permission|rbac)(/|$)",
    r"(^|/)(billing|payment|quota|rate[-_]?limit)(/|$)",
    r"(^|/)(dto|api|proto|openapi|graphql)(/|$)",
    r"(^|/)(config|configs|setting|settings)(/|$)",
    r"(^|/)(redis|cache|mq|kafka|transaction|lock)(/|$)",
    r"\.(sql|proto)$",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Classify by-harness quick-fix suitability.")
    parser.add_argument("--target-dir", default=".", help="repository or .harness directory")
    parser.add_argument("--prompt", default="", help="user request or bug description")
    parser.add_argument(
        "--phase",
        choices=("initial", "post-diff"),
        default="initial",
        help="initial checks request shape; post-diff also treats large diffs as escalation",
    )
    parser.add_argument(
        "--changed-file",
        action="append",
        default=[],
        help="changed file path; repeat to override/augment git status discovery",
    )
    parser.add_argument("--max-files", type=int, default=3, help="quick-fix changed-file threshold")
    parser.add_argument("--max-lines", type=int, default=100, help="quick-fix changed-line threshold")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON only")
    return parser.parse_args()


def repo_root_from_target(target_dir: Path) -> Path:
    target = target_dir.resolve()
    return target.parent if target.name == HARNESS_DIR_NAME else target


def git_lines(root: Path, args: list[str]) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except OSError:
        return []
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def parse_status_paths(lines: list[str]) -> list[str]:
    paths: list[str] = []
    for line in lines:
        if len(line) < 4:
            continue
        raw = line[3:].strip()
        if " -> " in raw:
            raw = raw.rsplit(" -> ", 1)[-1].strip()
        if raw:
            paths.append(raw.strip('"'))
    return paths


def git_changed_files(root: Path) -> list[str]:
    files = parse_status_paths(git_lines(root, ["status", "--porcelain=v1"]))
    return sorted(dict.fromkeys(files))


def git_numstat(root: Path) -> dict[str, int]:
    additions = 0
    deletions = 0
    for line in git_lines(root, ["diff", "--numstat", "HEAD", "--"]):
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        add_raw, del_raw = parts[0], parts[1]
        additions += int(add_raw) if add_raw.isdigit() else 0
        deletions += int(del_raw) if del_raw.isdigit() else 0
    return {
        "additions": additions,
        "deletions": deletions,
        "total_lines": additions + deletions,
    }


def normalize_text(value: str) -> str:
    return str(value or "").strip().lower()


def term_hits(text: str, terms: tuple[str, ...]) -> list[str]:
    haystack = normalize_text(text)
    return [term for term in terms if term in haystack]


def path_risk_hits(files: list[str]) -> list[str]:
    hits: list[str] = []
    for path in files:
        normalized = path.replace("\\", "/").lower()
        for pattern in HIGH_RISK_PATH_PATTERNS:
            if re.search(pattern, normalized):
                hits.append(f"{path} matches {pattern}")
                break
    return hits


def classify(args: argparse.Namespace) -> dict[str, Any]:
    root = repo_root_from_target(Path(args.target_dir))
    explicit_files = [str(item).strip() for item in args.changed_file if str(item).strip()]
    discovered_files = git_changed_files(root) if args.phase == "post-diff" else []
    changed_files = sorted(dict.fromkeys([*discovered_files, *explicit_files]))
    stats = git_numstat(root) if args.phase == "post-diff" else {
        "additions": 0,
        "deletions": 0,
        "total_lines": 0,
    }
    stats["files"] = len(changed_files)

    quick_hits = term_hits(args.prompt, QUICK_TERMS)
    risk_flags = []
    risk_flags.extend(f"prompt:{term}" for term in term_hits(args.prompt, HIGH_RISK_TERMS))
    risk_flags.extend(f"path:{item}" for item in path_risk_hits(changed_files))

    if len(changed_files) > args.max_files:
        risk_flags.append(f"diff:file_count>{args.max_files}")
    if args.phase == "post-diff" and stats["total_lines"] > args.max_lines:
        risk_flags.append(f"diff:changed_lines>{args.max_lines}")

    signals = []
    if quick_hits:
        signals.extend(f"prompt:{term}" for term in quick_hits)
    if changed_files:
        signals.append("git:changed_files_present")
    if 0 < len(changed_files) <= args.max_files:
        signals.append("diff:file_count_within_threshold")
    if stats["total_lines"] and stats["total_lines"] <= args.max_lines:
        signals.append("diff:changed_lines_within_threshold")

    if risk_flags:
        confidence = "low"
        recommended = "standard_feature"
    elif quick_hits and (not changed_files or len(changed_files) <= args.max_files):
        if args.phase == "post-diff" and stats["total_lines"] > args.max_lines:
            confidence = "low"
            recommended = "standard_feature"
        else:
            confidence = "high"
            recommended = "quick_fix"
    elif changed_files and len(changed_files) <= args.max_files and stats["total_lines"] <= args.max_lines:
        confidence = "medium"
        recommended = "ask_user"
    else:
        confidence = "low"
        recommended = "standard_feature"

    return {
        "schema": "by-harness.quick_fix.classifier.v1",
        "target_dir": str(root),
        "phase": args.phase,
        "confidence": confidence,
        "recommended_mode": recommended,
        "signals": signals,
        "risk_flags": risk_flags,
        "changed_files": changed_files,
        "changed_stats": stats,
        "thresholds": {
            "max_files": args.max_files,
            "max_lines": args.max_lines,
        },
    }


def print_human(result: dict[str, Any]) -> None:
    print("Quick-fix classification")
    print(f"  recommended_mode: {result['recommended_mode']}")
    print(f"  confidence: {result['confidence']}")
    print(f"  phase: {result['phase']}")
    stats = result["changed_stats"]
    print(
        "  changed: "
        f"files={stats.get('files', 0)} "
        f"additions={stats.get('additions', 0)} "
        f"deletions={stats.get('deletions', 0)}"
    )
    if result["signals"]:
        print("  signals:")
        for item in result["signals"]:
            print(f"    - {item}")
    if result["risk_flags"]:
        print("  risk_flags:")
        for item in result["risk_flags"]:
            print(f"    - {item}")
    if result["recommended_mode"] == "quick_fix":
        print("  next: run the targeted fix, verify it, then close with session_close.py --quick-fix")
    elif result["recommended_mode"] == "ask_user":
        print("  next: ask whether to proceed as quick-fix or standard feature")
    else:
        print("  next: use standard by-harness plan/contract/build/qa flow")


def main() -> int:
    args = parse_args()
    result = classify(args)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_human(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
