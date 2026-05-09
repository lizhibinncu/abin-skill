#!/usr/bin/env python3
"""Diagnose Docker/Testcontainers readiness for by-harness integration QA."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(description="Check Testcontainers runtime prerequisites.")
    parser.add_argument("--target-dir", default=".", help="目标项目目录")
    parser.add_argument("--format", choices=("text", "json"), default="text", help="输出格式")
    parser.add_argument("--require-docker", action="store_true", help="Docker 不可用时返回非 0")
    return parser.parse_args()


def run(command: list[str], cwd: Path, timeout: int = 20) -> dict[str, object]:
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
        return {
            "command": command,
            "exit_code": completed.returncode,
            "stdout": completed.stdout[-4000:],
            "stderr": completed.stderr[-4000:],
        }
    except FileNotFoundError:
        return {"command": command, "exit_code": 127, "stdout": "", "stderr": "command not found"}
    except subprocess.TimeoutExpired as exc:
        return {
            "command": command,
            "exit_code": 124,
            "stdout": (exc.stdout or "")[-4000:] if isinstance(exc.stdout, str) else "",
            "stderr": "command timed out",
        }


def pom_contains_testcontainers(root: Path) -> bool:
    pom = root / "pom.xml"
    if not pom.exists():
        return False
    try:
        return "org.testcontainers" in pom.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False


def has_integration_tests(root: Path) -> bool:
    test_root = root / "src" / "test"
    if not test_root.exists():
        return False
    for pattern in ("**/*IT.java", "**/*IntegrationTest.java"):
        if any(test_root.glob(pattern)):
            return True
    return False


def diagnose(root: Path) -> dict[str, object]:
    docker_binary = shutil.which("docker")
    docker_info = run(["docker", "info"], root) if docker_binary else {
        "command": ["docker", "info"],
        "exit_code": 127,
        "stdout": "",
        "stderr": "docker binary not found",
    }
    return {
        "target_dir": str(root),
        "docker_binary": docker_binary or "",
        "docker_available": docker_info.get("exit_code") == 0,
        "docker_info": docker_info,
        "pom_exists": (root / "pom.xml").exists(),
        "pom_has_testcontainers": pom_contains_testcontainers(root),
        "has_integration_tests": has_integration_tests(root),
    }


def render_text(result: dict[str, object]) -> str:
    lines = [
        "Testcontainers doctor:",
        f"- target_dir: {result.get('target_dir')}",
        f"- docker_binary: {result.get('docker_binary') or 'missing'}",
        f"- docker_available: {result.get('docker_available')}",
        f"- pom_exists: {result.get('pom_exists')}",
        f"- pom_has_testcontainers: {result.get('pom_has_testcontainers')}",
        f"- has_integration_tests: {result.get('has_integration_tests')}",
    ]
    docker_info = result.get("docker_info", {}) if isinstance(result.get("docker_info"), dict) else {}
    if docker_info.get("exit_code") != 0:
        lines.append(f"- docker_error: {docker_info.get('stderr', '').strip()}")
    return "\n".join(lines)


def main():
    args = parse_args()
    root = Path(args.target_dir).resolve()
    if root.name == ".harness":
        root = root.parent
    result = diagnose(root)
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(render_text(result))
    if args.require_docker and not result.get("docker_available"):
        sys.exit(1)


if __name__ == "__main__":
    main()
