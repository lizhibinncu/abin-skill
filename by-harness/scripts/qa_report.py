#!/usr/bin/env python3
"""
Build by-harness QA reports from contract matrices and test outputs.

The script is intentionally dependency-free so initialized projects can run it in
older Java service repositories without extra Python packages.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree

HARNESS_DIR_NAME = ".harness"
STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_PARTIAL = "PARTIAL"
STATUS_SKIP = "SKIP"
GATE_REQUIRED = "required"
GATE_ADVISORY = "advisory"
GATE_MANUAL = "manual"


def parse_args():
    parser = argparse.ArgumentParser(description="Generate a by-harness QA report.")
    parser.add_argument("--target-dir", default=".", help="目标项目目录")
    parser.add_argument("--contract", default="", help="契约文件路径；为空时选择最新 contract")
    parser.add_argument("--feature-id", default="", help="任务/feature ID（用于报告归档）")
    parser.add_argument("--commands-json", default="", help="qa_runner 写出的命令结果 JSON")
    parser.add_argument("--output-md", default="", help="输出 Markdown QA 报告路径")
    parser.add_argument("--output-json", default="", help="输出机器可读 QA result JSON 路径")
    return parser.parse_args()


def dump_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def dump_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def repo_root(target_dir: Path) -> Path:
    current = target_dir.resolve()
    if current.name == HARNESS_DIR_NAME:
        return current.parent
    return current


def harness_dir(target_dir: Path) -> Path:
    root = repo_root(target_dir)
    candidate = root / HARNESS_DIR_NAME
    if candidate.exists():
        return candidate
    return target_dir.resolve()


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


def latest_contract(target_dir: Path) -> Path | None:
    workspace = harness_dir(target_dir)
    contracts_dir = workspace / "docs" / "contracts"
    if not contracts_dir.exists():
        return None
    contracts = [
        path
        for path in contracts_dir.glob("*.md")
        if path.is_file() and path.name != "TEMPLATE.md"
    ]
    if not contracts:
        return None
    return max(contracts, key=lambda item: item.stat().st_mtime)


def resolve_contract(target_dir: Path, raw_contract: str) -> Path | None:
    if raw_contract:
        path = resolve_path(target_dir, raw_contract)
        return path if path.exists() else path
    return latest_contract(target_dir)


def normalize_gate(value: str) -> str:
    text = str(value or "").strip().lower()
    mapping = {
        "required": GATE_REQUIRED,
        "block": GATE_REQUIRED,
        "blocking": GATE_REQUIRED,
        "阻塞": GATE_REQUIRED,
        "必须": GATE_REQUIRED,
        "是": GATE_REQUIRED,
        "advisory": GATE_ADVISORY,
        "optional": GATE_ADVISORY,
        "report": GATE_ADVISORY,
        "建议": GATE_ADVISORY,
        "非阻塞": GATE_ADVISORY,
        "manual": GATE_MANUAL,
        "人工": GATE_MANUAL,
    }
    return mapping.get(text, text if text in {GATE_REQUIRED, GATE_ADVISORY, GATE_MANUAL} else GATE_ADVISORY)


def clean_cell(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"<br\s*/?>", " / ", text, flags=re.IGNORECASE)
    return text.strip()


def split_markdown_row(line: str) -> list[str]:
    text = line.strip()
    if not text.startswith("|"):
        return []
    parts = [clean_cell(part) for part in text.strip("|").split("|")]
    return parts


def is_separator_row(cells: list[str]) -> bool:
    if not cells:
        return False
    return all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells if cell.strip())


def find_section_lines(markdown: str, heading: str) -> list[str]:
    lines = markdown.splitlines()
    start = -1
    target = heading.strip()
    for index, line in enumerate(lines):
        if line.strip() == target:
            start = index + 1
            break
    if start < 0:
        return []
    collected = []
    for line in lines[start:]:
        if line.startswith("#") and line.strip() != target:
            break
        collected.append(line)
    return collected


def parse_table(section_lines: list[str]) -> list[dict[str, str]]:
    rows = [split_markdown_row(line) for line in section_lines if split_markdown_row(line)]
    rows = [row for row in rows if not is_separator_row(row)]
    if len(rows) < 2:
        return []
    headers = [cell.strip() for cell in rows[0]]
    result = []
    for row in rows[1:]:
        item = {}
        for idx, header in enumerate(headers):
            item[header] = row[idx] if idx < len(row) else ""
        result.append(item)
    return result


def value_by_alias(row: dict[str, str], aliases: tuple[str, ...]) -> str:
    lowered = {key.strip().lower(): value for key, value in row.items()}
    for alias in aliases:
        if alias in row:
            return row[alias]
        lowered_alias = alias.lower()
        if lowered_alias in lowered:
            return lowered[lowered_alias]
    return ""


def parse_acceptance_criteria(markdown: str) -> list[dict[str, str]]:
    rows = parse_table(find_section_lines(markdown, "## 验收标准（Acceptance Criteria）"))
    criteria = []
    for row in rows:
        number = value_by_alias(row, ("#", "ID", "编号")) or str(len(criteria) + 1)
        criterion = value_by_alias(row, ("标准（Criterion）", "标准", "Criterion", "验收项"))
        method = value_by_alias(row, ("验证方法（Verification Method）", "验证方法", "Verification Method"))
        criteria.append(
            {
                "id": number,
                "criterion": criterion,
                "verification_method": method,
                "status": STATUS_SKIP,
            }
        )
    return criteria


def parse_integration_matrix(markdown: str) -> list[dict[str, str]]:
    rows = parse_table(find_section_lines(markdown, "## 集成测试矩阵（Integration Test Matrix）"))
    if not rows:
        rows = parse_table(find_section_lines(markdown, "## 集成测试矩阵"))
    matrix = []
    for index, row in enumerate(rows, start=1):
        item_id = value_by_alias(row, ("ID", "Id", "id")) or f"IT-{index:02d}"
        gate = normalize_gate(value_by_alias(row, ("门禁", "Gate", "gate", "是否阻塞")))
        matrix.append(
            {
                "id": item_id,
                "criterion": value_by_alias(row, ("验收项", "标准", "Criterion")),
                "dependency": value_by_alias(row, ("触发依赖", "依赖", "Dependency")),
                "container": value_by_alias(row, ("Testcontainers", "Testcontainers 类型", "Container")),
                "test_class": value_by_alias(row, ("测试类", "测试入口", "Test Class")),
                "assertion": value_by_alias(row, ("核心断言", "断言", "Assertion")),
                "failure_case": value_by_alias(row, ("异常场景", "Failure Case")),
                "gate": gate,
                "status": STATUS_SKIP,
                "evidence": "",
            }
        )
    return matrix


def parse_junit_report(path: Path) -> dict[str, object] | None:
    try:
        tree = ElementTree.parse(path)
    except (ElementTree.ParseError, OSError):
        return None
    root = tree.getroot()
    suites = []
    if root.tag == "testsuite":
        suites = [root]
    elif root.tag == "testsuites":
        suites = [node for node in root.findall("testsuite")]
    if not suites:
        return None

    total_tests = 0
    total_failures = 0
    total_errors = 0
    total_skipped = 0
    suite_names = []
    testcase_names = []
    for suite in suites:
        suite_names.append(suite.get("name", ""))
        total_tests += int(float(suite.get("tests", "0") or 0))
        total_failures += int(float(suite.get("failures", "0") or 0))
        total_errors += int(float(suite.get("errors", "0") or 0))
        total_skipped += int(float(suite.get("skipped", "0") or 0))
        for testcase in suite.findall("testcase"):
            name = testcase.get("classname") or testcase.get("name") or ""
            if name:
                testcase_names.append(name)
    status = STATUS_PASS
    if total_failures or total_errors:
        status = STATUS_FAIL
    elif total_tests and total_skipped == total_tests:
        status = STATUS_SKIP
    return {
        "file": str(path),
        "name": ", ".join([name for name in suite_names if name]) or path.stem,
        "tests": total_tests,
        "failures": total_failures,
        "errors": total_errors,
        "skipped": total_skipped,
        "status": status,
        "testcases": sorted(set(testcase_names)),
    }


def collect_reports(target_dir: Path, subdir: str) -> list[dict[str, object]]:
    root = repo_root(target_dir)
    report_dir = root / "target" / subdir
    reports = []
    if not report_dir.exists():
        return reports
    for path in sorted(report_dir.glob("TEST-*.xml")):
        parsed = parse_junit_report(path)
        if parsed:
            reports.append(parsed)
    return reports


def simple_name(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = text.split("#", 1)[0].split("::", 1)[0].strip()
    return text.rsplit(".", 1)[-1]


def report_matches_test_class(report: dict[str, object], test_class: str) -> bool:
    expected = simple_name(test_class)
    if not expected:
        return False
    candidates = [
        simple_name(str(report.get("name", ""))),
        simple_name(Path(str(report.get("file", ""))).stem.replace("TEST-", "")),
    ]
    for testcase in report.get("testcases", []) or []:
        candidates.append(simple_name(str(testcase)))
    return expected in candidates


def attach_matrix_evidence(matrix: list[dict[str, str]], reports: list[dict[str, object]]) -> list[dict[str, str]]:
    for item in matrix:
        test_class = item.get("test_class", "")
        gate = item.get("gate", GATE_ADVISORY)
        if gate == GATE_MANUAL:
            item["status"] = STATUS_PARTIAL
            item["evidence"] = "manual gate: requires human confirmation"
            continue
        if not test_class:
            item["status"] = STATUS_FAIL if gate == GATE_REQUIRED else STATUS_PARTIAL
            item["evidence"] = "missing test class in integration matrix"
            continue
        matched = [report for report in reports if report_matches_test_class(report, test_class)]
        if not matched:
            item["status"] = STATUS_FAIL if gate == GATE_REQUIRED else STATUS_PARTIAL
            item["evidence"] = f"no failsafe report matched {test_class}"
            continue
        failed = [report for report in matched if report.get("status") == STATUS_FAIL]
        skipped = [report for report in matched if report.get("status") == STATUS_SKIP]
        if failed:
            item["status"] = STATUS_FAIL
            item["evidence"] = "; ".join(str(report.get("file", "")) for report in failed)
        elif skipped and len(skipped) == len(matched):
            item["status"] = STATUS_FAIL if gate == GATE_REQUIRED else STATUS_PARTIAL
            item["evidence"] = "; ".join(str(report.get("file", "")) for report in skipped)
        else:
            item["status"] = STATUS_PASS
            item["evidence"] = "; ".join(str(report.get("file", "")) for report in matched)
    return matrix


def status_from_exit_code(exit_code) -> str:
    if exit_code is None:
        return STATUS_SKIP
    try:
        return STATUS_PASS if int(exit_code) == 0 else STATUS_FAIL
    except (TypeError, ValueError):
        return STATUS_SKIP


def load_commands(path: Path | None) -> list[dict[str, object]]:
    if not path or not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    commands = data.get("commands", data if isinstance(data, list) else [])
    result = []
    if isinstance(commands, list):
        for item in commands:
            if isinstance(item, dict):
                normalized = dict(item)
                normalized["status"] = normalized.get("status") or status_from_exit_code(normalized.get("exit_code"))
                result.append(normalized)
    return result


def command_status(commands: list[dict[str, object]], name: str) -> str:
    for command in commands:
        if command.get("name") == name:
            return str(command.get("status", STATUS_SKIP))
    return STATUS_SKIP


def compute_gate_status(matrix: list[dict[str, str]], commands: list[dict[str, object]]) -> tuple[str, dict[str, int]]:
    required = [item for item in matrix if item.get("gate") == GATE_REQUIRED]
    advisory = [item for item in matrix if item.get("gate") == GATE_ADVISORY]
    manual = [item for item in matrix if item.get("gate") == GATE_MANUAL]
    summary = {
        "required_total": len(required),
        "required_passed": sum(1 for item in required if item.get("status") == STATUS_PASS),
        "required_failed": sum(1 for item in required if item.get("status") == STATUS_FAIL),
        "advisory_total": len(advisory),
        "advisory_failed": sum(1 for item in advisory if item.get("status") == STATUS_FAIL),
        "manual_total": len(manual),
    }
    blocking_failures = []
    for name in ("convention_check", "maven_test"):
        status = command_status(commands, name)
        if status == STATUS_FAIL:
            blocking_failures.append(name)
    if required:
        if command_status(commands, "maven_verify") == STATUS_FAIL:
            blocking_failures.append("maven_verify")
        if summary["required_failed"] or summary["required_passed"] < summary["required_total"]:
            blocking_failures.append("required_integration_matrix")
    return (STATUS_FAIL if blocking_failures else STATUS_PASS), summary


def compute_score(criteria: list[dict[str, str]], matrix: list[dict[str, str]]) -> float:
    scored = []
    scored.extend(item.get("status", STATUS_SKIP) for item in criteria if item.get("criterion"))
    scored.extend(item.get("status", STATUS_SKIP) for item in matrix if item.get("gate") != GATE_MANUAL)
    if not scored:
        return 0.0
    points = 0.0
    for status in scored:
        if status == STATUS_PASS:
            points += 1.0
        elif status == STATUS_PARTIAL:
            points += 0.5
    return round(points / len(scored) * 100, 1)


def mark_criteria(criteria: list[dict[str, str]], commands: list[dict[str, object]]) -> list[dict[str, str]]:
    build_status = command_status(commands, "maven_test")
    verify_status = command_status(commands, "maven_verify")
    for item in criteria:
        method = str(item.get("verification_method", "")).lower()
        if "integration" in method or "集成" in method:
            item["status"] = verify_status if verify_status in {STATUS_PASS, STATUS_FAIL} else STATUS_PARTIAL
        elif "build" in method or "unit" in method or "单元" in method:
            item["status"] = build_status if build_status in {STATUS_PASS, STATUS_FAIL} else STATUS_PARTIAL
        elif "manual" in method or "人工" in method:
            item["status"] = STATUS_PARTIAL
        else:
            item["status"] = STATUS_PARTIAL
    return criteria


def render_markdown(result: dict[str, object]) -> str:
    lines = [
        f"## QA 报告：{result.get('contract_name', 'unknown')}",
        "",
        f"**日期**：{result.get('generated_at', '')}",
        f"**Feature**：{result.get('feature_id') or 'n/a'}",
        f"**分数**：{result.get('score', 0)}/100",
        f"**Gate**：{result.get('gate_status', STATUS_FAIL)}",
        "",
        "### 命令结果",
        "",
        "| 命令 | 状态 | Exit Code | 说明 |",
        "| --- | --- | --- | --- |",
    ]
    for command in result.get("commands", []) or []:
        lines.append(
            "| {name} | {status} | {exit_code} | {summary} |".format(
                name=command.get("name", ""),
                status=command.get("status", ""),
                exit_code=command.get("exit_code", ""),
                summary=str(command.get("summary", "")).replace("|", "/"),
            )
        )

    lines.extend(["", "### 验收标准结果", "", "| # | 标准 | 验证方法 | 状态 |", "| --- | --- | --- | --- |"])
    for item in result.get("acceptance_criteria", []) or []:
        lines.append(
            "| {id} | {criterion} | {method} | {status} |".format(
                id=item.get("id", ""),
                criterion=str(item.get("criterion", "")).replace("|", "/"),
                method=str(item.get("verification_method", "")).replace("|", "/"),
                status=item.get("status", ""),
            )
        )

    lines.extend(["", "### 集成测试矩阵", "", "| ID | 验收项 | 依赖 | Testcontainers | 测试类 | 门禁 | 状态 | 证据 |", "| --- | --- | --- | --- | --- | --- | --- | --- |"])
    for item in result.get("integration_matrix", []) or []:
        lines.append(
            "| {id} | {criterion} | {dependency} | {container} | {test_class} | {gate} | {status} | {evidence} |".format(
                id=item.get("id", ""),
                criterion=str(item.get("criterion", "")).replace("|", "/"),
                dependency=str(item.get("dependency", "")).replace("|", "/"),
                container=str(item.get("container", "")).replace("|", "/"),
                test_class=str(item.get("test_class", "")).replace("|", "/"),
                gate=item.get("gate", ""),
                status=item.get("status", ""),
                evidence=str(item.get("evidence", "")).replace("|", "/"),
            )
        )

    summary = result.get("summary", {}) or {}
    lines.extend(
        [
            "",
            "### Gate 汇总",
            "",
            f"- required: {summary.get('required_passed', 0)}/{summary.get('required_total', 0)} passed",
            f"- advisory failed: {summary.get('advisory_failed', 0)}/{summary.get('advisory_total', 0)}",
            f"- manual confirmation: {summary.get('manual_total', 0)}",
            "",
            "### 后续动作",
        ]
    )
    if result.get("gate_status") == STATUS_PASS:
        lines.append("- Gate PASS：required 门禁已通过，可进入 mark_pass 前置检查。")
    else:
        lines.append("- Gate FAIL：修复 required 失败项后重新运行 `.harness/scripts/qa_runner.py`。")
    return "\n".join(lines) + "\n"


def default_output_paths(target_dir: Path, contract_path: Path | None) -> tuple[Path, Path]:
    workspace = harness_dir(target_dir)
    stem = contract_path.stem if contract_path else "latest"
    md_path = workspace / "docs" / "qa" / f"{stem}.md"
    json_path = workspace / "docs" / "qa" / f"{stem}.result.json"
    return md_path, json_path


def build_result(
    target_dir: Path,
    contract_path: Path | None,
    feature_id: str,
    commands: list[dict[str, object]],
) -> dict[str, object]:
    markdown = contract_path.read_text(encoding="utf-8") if contract_path and contract_path.exists() else ""
    criteria = parse_acceptance_criteria(markdown)
    matrix = parse_integration_matrix(markdown)
    surefire_reports = collect_reports(target_dir, "surefire-reports")
    failsafe_reports = collect_reports(target_dir, "failsafe-reports")
    criteria = mark_criteria(criteria, commands)
    matrix = attach_matrix_evidence(matrix, failsafe_reports)
    gate_status, summary = compute_gate_status(matrix, commands)
    score = compute_score(criteria, matrix)
    return {
        "schema_version": 1,
        "generated_by": "qa_report.py",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "target_dir": str(repo_root(target_dir)),
        "feature_id": feature_id,
        "contract_path": str(contract_path) if contract_path else "",
        "contract_name": contract_path.stem if contract_path else "unknown",
        "gate_status": gate_status,
        "score": score,
        "summary": summary,
        "commands": commands,
        "acceptance_criteria": criteria,
        "integration_matrix": matrix,
        "reports": {
            "surefire": surefire_reports,
            "failsafe": failsafe_reports,
        },
    }


def main():
    args = parse_args()
    target_dir = Path(args.target_dir).resolve()
    contract_path = resolve_contract(target_dir, args.contract)
    if args.contract and contract_path and not contract_path.exists():
        print(f"Error: contract not found: {contract_path}", file=sys.stderr)
        sys.exit(2)

    commands_path = resolve_path(target_dir, args.commands_json) if args.commands_json else None
    commands = load_commands(commands_path)
    result = build_result(target_dir, contract_path, args.feature_id, commands)
    default_md, default_json = default_output_paths(target_dir, contract_path)
    output_md = resolve_path(target_dir, args.output_md) if args.output_md else default_md
    output_json = resolve_path(target_dir, args.output_json) if args.output_json else default_json
    dump_json(output_json, result)
    dump_text(output_md, render_markdown(result))
    print(f"Wrote QA result JSON: {output_json}")
    print(f"Wrote QA report: {output_md}")
    if result.get("gate_status") != STATUS_PASS:
        sys.exit(1)


if __name__ == "__main__":
    main()
