#!/usr/bin/env python3
"""
Run by-harness QA commands and generate gate reports.

This runner is the single entry point intended for local use and future CI jobs.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import qa_report  # noqa: E402
import testcontainers_doctor  # noqa: E402

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_SKIP = "SKIP"


def parse_args():
    parser = argparse.ArgumentParser(description="Run by-harness QA gate.")
    parser.add_argument("--target-dir", default=".", help="目标项目目录")
    parser.add_argument("--contract", default="", help="契约文件路径；为空时选择最新 contract")
    parser.add_argument("--feature-id", default="", help="任务/feature ID")
    parser.add_argument("--output-md", default="", help="输出 Markdown QA 报告路径")
    parser.add_argument("--output-json", default="", help="输出机器可读 QA result JSON 路径")
    parser.add_argument("--skip-convention", action="store_true", help="跳过 convention-check")
    parser.add_argument("--skip-test", action="store_true", help="跳过 mvn test")
    parser.add_argument("--skip-verify", action="store_true", help="跳过 mvn verify")
    parser.add_argument("--no-fail", action="store_true", help="即使 gate FAIL 也返回 0")
    return parser.parse_args()


def repo_root(target_dir: Path) -> Path:
    current = target_dir.resolve()
    return current.parent if current.name == ".harness" else current


def resolve_path(target_dir: Path, raw: str) -> Path:
    return qa_report.resolve_path(target_dir, raw)


def tail(text: str, limit: int = 6000) -> str:
    return (text or "")[-limit:]


def run_command(name: str, command: list[str], cwd: Path, timeout: int | None = None) -> dict[str, object]:
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
        status = STATUS_PASS if completed.returncode == 0 else STATUS_FAIL
        return {
            "name": name,
            "command": command,
            "exit_code": completed.returncode,
            "status": status,
            "summary": command_summary(name, completed.returncode),
            "stdout_tail": tail(completed.stdout),
            "stderr_tail": tail(completed.stderr),
        }
    except FileNotFoundError:
        return {
            "name": name,
            "command": command,
            "exit_code": 127,
            "status": STATUS_FAIL,
            "summary": "command not found",
            "stdout_tail": "",
            "stderr_tail": "command not found",
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "name": name,
            "command": command,
            "exit_code": 124,
            "status": STATUS_FAIL,
            "summary": "command timed out",
            "stdout_tail": tail(exc.stdout if isinstance(exc.stdout, str) else ""),
            "stderr_tail": "command timed out",
        }


def skipped_command(name: str, reason: str, command: list[str] | None = None) -> dict[str, object]:
    return {
        "name": name,
        "command": command or [],
        "exit_code": None,
        "status": STATUS_SKIP,
        "summary": reason,
        "stdout_tail": "",
        "stderr_tail": "",
    }


def command_summary(name: str, exit_code: int) -> str:
    if exit_code == 0:
        return f"{name} passed"
    return f"{name} failed"


def convention_command(root: Path) -> list[str] | None:
    candidates = [
        root / ".codex" / "hooks" / "convention-check.py",
        root / ".claude" / "hooks" / "convention-check.py",
    ]
    for path in candidates:
        if path.exists():
            return [sys.executable, str(path), "--changed-only"]
    return None


def has_pom(root: Path) -> bool:
    return (root / "pom.xml").exists()


def write_commands_json(root: Path, commands: list[dict[str, object]]) -> Path:
    output = root / ".harness" / "docs" / "qa" / "last-commands.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_by": "qa_runner.py",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "commands": commands,
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def has_required_matrix(contract_path: Path | None) -> bool:
    if not contract_path or not contract_path.exists():
        return False
    markdown = contract_path.read_text(encoding="utf-8")
    return any(item.get("gate") == "required" for item in qa_report.parse_integration_matrix(markdown))


def run_doctor(root: Path, required: bool) -> dict[str, object]:
    result = testcontainers_doctor.diagnose(root)
    status = STATUS_PASS if result.get("docker_available") else (STATUS_FAIL if required else STATUS_SKIP)
    return {
        "name": "testcontainers_doctor",
        "command": [sys.executable, str(SCRIPT_DIR / "testcontainers_doctor.py"), "--target-dir", str(root)],
        "exit_code": 0 if result.get("docker_available") else 1,
        "status": status,
        "summary": (
            "Docker available"
            if result.get("docker_available")
            else "Docker unavailable; required integration gate may fail"
        ),
        "stdout_tail": json.dumps(result, ensure_ascii=False)[-6000:],
        "stderr_tail": "",
    }


def build_outputs(target_dir: Path, contract_path: Path | None, args) -> tuple[Path, Path]:
    default_md, default_json = qa_report.default_output_paths(target_dir, contract_path)
    output_md = resolve_path(target_dir, args.output_md) if args.output_md else default_md
    output_json = resolve_path(target_dir, args.output_json) if args.output_json else default_json
    return output_md, output_json


def main():
    args = parse_args()
    target_dir = Path(args.target_dir).resolve()
    root = repo_root(target_dir)
    contract_path = qa_report.resolve_contract(target_dir, args.contract)
    if args.contract and contract_path and not contract_path.exists():
        print(f"Error: contract not found: {contract_path}", file=sys.stderr)
        sys.exit(2)

    required_matrix = has_required_matrix(contract_path)
    commands: list[dict[str, object]] = []
    commands.append(run_doctor(root, required_matrix))

    convention = convention_command(root)
    if args.skip_convention:
        commands.append(skipped_command("convention_check", "skipped by --skip-convention"))
    elif convention:
        commands.append(run_command("convention_check", convention, root))
    else:
        commands.append(skipped_command("convention_check", "convention-check hook not found"))

    if args.skip_test:
        commands.append(skipped_command("maven_test", "skipped by --skip-test", ["mvn", "test"]))
    elif has_pom(root):
        commands.append(run_command("maven_test", ["mvn", "test"], root))
    else:
        commands.append(skipped_command("maven_test", "pom.xml not found", ["mvn", "test"]))

    if args.skip_verify:
        commands.append(skipped_command("maven_verify", "skipped by --skip-verify", ["mvn", "verify"]))
    elif has_pom(root):
        commands.append(run_command("maven_verify", ["mvn", "verify"], root))
    else:
        commands.append(skipped_command("maven_verify", "pom.xml not found", ["mvn", "verify"]))

    commands_json = write_commands_json(root, commands)
    output_md, output_json = build_outputs(target_dir, contract_path, args)
    result = qa_report.build_result(target_dir, contract_path, args.feature_id, commands)
    qa_report.dump_json(output_json, result)
    qa_report.dump_text(output_md, qa_report.render_markdown(result))

    print(f"Commands JSON: {commands_json}")
    print(f"QA result JSON: {output_json}")
    print(f"QA report: {output_md}")
    print(f"QA gate: {result.get('gate_status')}")
    if result.get("gate_status") != STATUS_PASS and not args.no_fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
