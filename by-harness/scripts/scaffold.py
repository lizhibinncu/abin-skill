#!/usr/bin/env python3
"""
by-harness scaffold generator.

Standalone initializer:
- Generate main harness loop skeleton
- Generate task tracking files

No runtime dependency on other skills.
"""

import argparse
import json
import shutil
import sys
from datetime import date
from pathlib import Path

HARNESS_DIR_NAME = ".harness"
HARNESS_RUNTIME_VERSION = "2.6.0"
MANAGED_BLOCK_BEGIN = "<!-- BEGIN BY-HARNESS MANAGED BLOCK -->"
MANAGED_BLOCK_END = "<!-- END BY-HARNESS MANAGED BLOCK -->"
AGENT_DOC_ALIASES = {
    "AGENTS.md": ("AGENTS.md", "AGENT.md", "agents.md", "agent.md"),
    "CLAUDE.md": ("CLAUDE.md", "claude.md"),
}
JAVA_RULE_FILES = (
    "docs/java/rules/00-core.md",
    "docs/java/rules/java-ddd.md",
    "docs/java/rules/dubbo-api.md",
    "docs/java/rules/logging-error.md",
    "docs/java/rules/persistence-infra.md",
    "docs/java/rules/testing-security.md",
    "docs/java/rules/distributed-java-gate.md",
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Initialize by-harness standalone scaffold."
    )
    parser.add_argument("--project-name", required=True, help="项目名称")
    parser.add_argument("--description", required=True, help="项目描述")
    parser.add_argument("--tech-stack", default="", help="技术栈（可选）")
    parser.add_argument("--project-type", default="", help="项目类型（可选）")
    parser.add_argument("--design-guidance", default="无", help="设计约束（可选）")
    parser.add_argument("--target-dir", required=True, help="目标目录")
    parser.add_argument("--force", action="store_true", help="覆盖已存在文件")
    return parser.parse_args()


def get_skill_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def substitute(template: str, args) -> str:
    today = date.today().isoformat()
    replacements = {
        "{{PROJECT_NAME}}": args.project_name,
        "{{TECH_STACK}}": args.tech_stack or "Not specified",
        "{{PROJECT_TYPE}}": args.project_type or "General",
        "{{DATE}}": today,
        "{{项目名称}}": args.project_name,
        "{{项目描述，一句话概括目标和范围}}": args.description,
        "{{一句话描述项目目标和范围}}": args.description,
        "{{项目描述}}": args.description,
        "{{主要技术栈信息}}": args.tech_stack or "待补充",
        "{{设计约束和风格指南}}": args.design_guidance or "无",
        "{{YYYY-MM-DD}}": today,
        "{{里程碑 1 名称}}": "M1-首批功能闭环",
        "{{里程碑描述}}": "完成首批高优先级 feature 的 plan/build/qa 闭环",
        "{{重要发现 1}}": "待首次会话补充",
        "{{重要发现 2}}": "待首次会话补充",
        "{{重要发现 3}}": "待首次会话补充",
        "{{HARNESS_RUNTIME_VERSION}}": HARNESS_RUNTIME_VERSION,
    }

    out = template
    for key, value in replacements.items():
        out = out.replace(key, value)
    return out


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


def find_existing_agent_doc(target_path: Path) -> Path | None:
    aliases = AGENT_DOC_ALIASES.get(target_path.name, (target_path.name,))
    for alias in aliases:
        candidate = target_path.parent / alias
        if candidate.exists():
            return candidate
    lowered = {alias.lower() for alias in aliases}
    if target_path.parent.exists():
        for child in target_path.parent.iterdir():
            if child.is_file() and child.name.lower() in lowered:
                return child
    return None


def generate_agent_doc(template_path: Path, target_path: Path, args) -> bool:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    content = template_path.read_text(encoding="utf-8")
    rendered = substitute(content, args)
    existing_path = find_existing_agent_doc(target_path)
    if existing_path and existing_path.exists():
        existing = existing_path.read_text(encoding="utf-8")
        merged = merge_markdown_block(existing, rendered)
        target_path.write_text(merged, encoding="utf-8")
        if existing_path.resolve() == target_path.resolve():
            print(f"  MERGE: {target_path}")
        else:
            print(f"  MERGE: {existing_path} -> {target_path}")
        return False

    target_path.write_text(build_managed_markdown_block(rendered), encoding="utf-8")
    print(f"  CREATE: {target_path}")
    return True


def generate_file(template_path: Path, target_path: Path, args) -> bool:
    if target_path.name in AGENT_DOC_ALIASES and target_path.parent == Path(args.target_dir).resolve():
        return generate_agent_doc(template_path, target_path, args)

    if target_path.exists() and not args.force:
        print(f"  SKIP (exists): {target_path}")
        return False

    target_path.parent.mkdir(parents=True, exist_ok=True)

    if template_path.suffix in (".md", ".txt", ".json", ".toml", ".sh"):
        content = template_path.read_text(encoding="utf-8")
        rendered = substitute(content, args)
        target_path.write_text(rendered, encoding="utf-8")
    else:
        shutil.copy2(template_path, target_path)

    if target_path.suffix in (".py", ".sh"):
        target_path.chmod(target_path.stat().st_mode | 0o755)

    print(f"  CREATE: {target_path}")
    return True


def _hook_group_signature(group: dict):
    matcher = group.get("matcher", "")
    hooks = group.get("hooks", [])
    hook_sigs = []
    for hook in hooks:
        hook_sigs.append(f"{hook.get('type', '')}:{hook.get('command', '')}")
    return f"{matcher}|{'|'.join(hook_sigs)}"


def merge_settings(target_dir: Path, template_settings_path: Path):
    settings_path = target_dir / ".claude" / "settings.json"
    template_content = json.loads(template_settings_path.read_text(encoding="utf-8"))

    if settings_path.exists():
        existing = json.loads(settings_path.read_text(encoding="utf-8"))
    else:
        existing = {}

    if "hooks" not in existing or not isinstance(existing.get("hooks"), dict):
        existing["hooks"] = {}
    for event_name, groups in template_content.get("hooks", {}).items():
        if event_name not in existing["hooks"] or not isinstance(existing["hooks"][event_name], list):
            existing["hooks"][event_name] = groups
            continue
        existing_sigs = {_hook_group_signature(g) for g in existing["hooks"][event_name]}
        for group in groups:
            sig = _hook_group_signature(group)
            if sig not in existing_sigs:
                existing["hooks"][event_name].append(group)
                existing_sigs.add(sig)

    existing_permissions = existing.get("permissions", {})
    template_permissions = template_content.get("permissions", {})
    merged_permissions = {}
    for key in ("allow", "deny"):
        values = []
        for source in (existing_permissions.get(key, []), template_permissions.get(key, [])):
            for item in source:
                if item not in values:
                    values.append(item)
        if values:
            merged_permissions[key] = values
    if merged_permissions:
        existing["permissions"] = merged_permissions

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  MERGE: {settings_path}")


def merge_codex_hooks(target_dir: Path, template_hooks_path: Path):
    hooks_path = target_dir / ".codex" / "hooks.json"
    template_content = json.loads(template_hooks_path.read_text(encoding="utf-8"))
    template_hooks_map = template_content.get("hooks", {})

    if hooks_path.exists():
        existing = json.loads(hooks_path.read_text(encoding="utf-8"))
    else:
        existing = {}

    if "hooks" not in existing or not isinstance(existing.get("hooks"), dict):
        existing["hooks"] = {}

    for event_name, groups in template_hooks_map.items():
        if event_name not in existing["hooks"] or not isinstance(existing["hooks"][event_name], list):
            existing["hooks"][event_name] = groups
            continue

        existing_sigs = {_hook_group_signature(g) for g in existing["hooks"][event_name]}
        for group in groups:
            sig = _hook_group_signature(group)
            if sig not in existing_sigs:
                existing["hooks"][event_name].append(group)
                existing_sigs.add(sig)

    hooks_path.parent.mkdir(parents=True, exist_ok=True)
    hooks_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  MERGE: {hooks_path}")


def ship_runtime_script(
    skill_dir: Path,
    harness_dir: Path,
    script_name: str,
    args,
) -> bool:
    src = skill_dir / "scripts" / script_name
    dst = harness_dir / "scripts" / script_name
    if not src.exists():
        print(f"  WARN: helper not found: {src}")
        return False
    return generate_file(src, dst, args)


def verify_outputs(target_dir: Path):
    required = [
        "AGENTS.md",
        "CLAUDE.md",
        f"{HARNESS_DIR_NAME}/docs/TASK-HARNESS.md",
        f"{HARNESS_DIR_NAME}/task-harness/index.json",
        f"{HARNESS_DIR_NAME}/task-harness/tasks",
        f"{HARNESS_DIR_NAME}/config/runtime-version.json",
        f"{HARNESS_DIR_NAME}/config/update-policy.json",
        f"{HARNESS_DIR_NAME}/config/task.json",
        f"{HARNESS_DIR_NAME}/task-harness/progress/latest.txt",
        f"{HARNESS_DIR_NAME}/scripts/session_close.py",
        f"{HARNESS_DIR_NAME}/scripts/ensure_task_branch.py",
        f"{HARNESS_DIR_NAME}/scripts/task_switch.py",
        f"{HARNESS_DIR_NAME}/scripts/task_store.py",
        f"{HARNESS_DIR_NAME}/scripts/update_runtime.py",
        f"{HARNESS_DIR_NAME}/scripts/qa_runner.py",
        f"{HARNESS_DIR_NAME}/scripts/qa_report.py",
        f"{HARNESS_DIR_NAME}/scripts/qa_gate.py",
        f"{HARNESS_DIR_NAME}/scripts/testcontainers_doctor.py",
        f"{HARNESS_DIR_NAME}/scripts/init.sh",
        ".codex/config.toml",
        ".codex/hooks.json",
        ".codex/hooks/context-injector.py",
        ".codex/hooks/loop-detector.py",
        ".codex/hooks/pre-completion-check.py",
        ".codex/hooks/convention-check.py",
        ".claude/settings.json",
        f"{HARNESS_DIR_NAME}/docs/contracts/TEMPLATE.md",
        f"{HARNESS_DIR_NAME}/docs/java-dev-conventions.md",
        *[f"{HARNESS_DIR_NAME}/{rel}" for rel in JAVA_RULE_FILES],
        f"{HARNESS_DIR_NAME}/docs/qa",
        f"{HARNESS_DIR_NAME}/task-harness/progress",
    ]
    missing = [rel for rel in required if not (target_dir / rel).exists()]
    if missing:
        raise RuntimeError("Missing files after scaffold:\n- " + "\n- ".join(missing))


def main():
    args = parse_args()
    skill_dir = get_skill_dir()
    templates_harness = skill_dir / "templates" / "harness"
    target_dir = Path(args.target_dir).resolve()

    if not target_dir.exists():
        print(f"Error: target directory does not exist: {target_dir}")
        sys.exit(1)

    harness_dir = target_dir / HARNESS_DIR_NAME
    file_mappings = [
        ("harness/AGENTS.md", "AGENTS.md"),
        ("harness/CLAUDE.md", "CLAUDE.md"),
        ("harness/docs/architecture.md", f"{HARNESS_DIR_NAME}/docs/architecture.md"),
        ("harness/docs/golden-principles.md", f"{HARNESS_DIR_NAME}/docs/golden-principles.md"),
        ("harness/docs/sprint-workflow.md", f"{HARNESS_DIR_NAME}/docs/sprint-workflow.md"),
        ("harness/docs/java-dev-conventions.md", f"{HARNESS_DIR_NAME}/docs/java-dev-conventions.md"),
        *[
            (f"harness/{rel}", f"{HARNESS_DIR_NAME}/{rel}")
            for rel in JAVA_RULE_FILES
        ],
        ("harness/docs/contracts/TEMPLATE.md", f"{HARNESS_DIR_NAME}/docs/contracts/TEMPLATE.md"),
        ("harness/agents/planner.md", ".claude/agents/planner.md"),
        ("harness/agents/generator.md", ".claude/agents/generator.md"),
        ("harness/agents/evaluator.md", ".claude/agents/evaluator.md"),
        ("harness/agents/doc-gardener.md", ".claude/agents/doc-gardener.md"),
        ("harness/commands/plan.md", ".claude/commands/plan.md"),
        ("harness/commands/build.md", ".claude/commands/build.md"),
        ("harness/commands/qa.md", ".claude/commands/qa.md"),
        ("harness/commands/sprint.md", ".claude/commands/sprint.md"),
        ("harness/hooks/loop-detector.py", ".claude/hooks/loop-detector.py"),
        ("harness/hooks/pre-completion-check.py", ".claude/hooks/pre-completion-check.py"),
        ("harness/hooks/context-injector.py", ".claude/hooks/context-injector.py"),
        ("harness/hooks/convention-check.py", ".claude/hooks/convention-check.py"),
        ("harness/codex/config.toml", ".codex/config.toml"),
        ("harness/codex/hooks/context-injector.py", ".codex/hooks/context-injector.py"),
        ("harness/codex/hooks/loop-detector.py", ".codex/hooks/loop-detector.py"),
        ("harness/codex/hooks/pre-completion-check.py", ".codex/hooks/pre-completion-check.py"),
        ("harness/codex/hooks/convention-check.py", ".codex/hooks/convention-check.py"),
        ("task/index.json", f"{HARNESS_DIR_NAME}/task-harness/index.json"),
        ("task/runtime-version.json", f"{HARNESS_DIR_NAME}/config/runtime-version.json"),
        ("task/update-policy.json", f"{HARNESS_DIR_NAME}/config/update-policy.json"),
        ("task/progress.txt", f"{HARNESS_DIR_NAME}/task-harness/progress/latest.txt"),
        ("task/init.sh", f"{HARNESS_DIR_NAME}/scripts/init.sh"),
        ("task/task.json", f"{HARNESS_DIR_NAME}/config/task.json"),
        ("task/TASK-HARNESS.md", f"{HARNESS_DIR_NAME}/docs/TASK-HARNESS.md"),
    ]

    print(f"\nInitializing by-harness in: {target_dir}")
    print(f"Project: {args.project_name}")
    print(f"Description: {args.description}")
    print(f"Tech stack: {args.tech_stack or 'Not specified'}")
    print(f"Project type: {args.project_type or 'General'}")
    print()

    created = 0
    skipped = 0
    for template_rel, target_rel in file_mappings:
        template_path = skill_dir / "templates" / template_rel
        target_path = target_dir / target_rel
        if not template_path.exists():
            print(f"  WARN: template not found: {template_path}")
            continue
        if generate_file(template_path, target_path, args):
            created += 1
        else:
            skipped += 1

    # Ship runtime helpers into initialized project
    for runtime_script in (
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
    ):
        if ship_runtime_script(skill_dir, harness_dir, runtime_script, args):
            created += 1
        else:
            skipped += 1

    (harness_dir / "docs" / "specs").mkdir(parents=True, exist_ok=True)
    (harness_dir / "docs" / "plans").mkdir(parents=True, exist_ok=True)
    (harness_dir / "docs" / "qa").mkdir(parents=True, exist_ok=True)
    (harness_dir / "task-harness" / "progress").mkdir(parents=True, exist_ok=True)
    (harness_dir / "task-harness" / "tasks").mkdir(parents=True, exist_ok=True)

    merge_settings(target_dir, templates_harness / "settings.json")
    merge_codex_hooks(target_dir, templates_harness / "codex" / "hooks.json")

    try:
        verify_outputs(target_dir)
    except RuntimeError as exc:
        print(f"\nError: {exc}")
        sys.exit(1)

    print(f"\nDone. Created {created} files, skipped {skipped} files.")
    print("\nNext steps:")
    print(f"  1. bash {HARNESS_DIR_NAME}/scripts/init.sh")
    print(f"  2. 阅读 AGENTS.md 与 {HARNESS_DIR_NAME}/docs/TASK-HARNESS.md")
    print("  3. 选择 passes=false 的 feature，执行 plan/build/qa 闭环")
    print(f"  4. 单元测试、required QA Gate 通过且 spec/contract 已落盘后，才可更新 passes=true，并写入 {HARNESS_DIR_NAME}/task-harness/progress/YYYY-MM/*.md")
    print(f"  5. 会话结束执行：python3 {HARNESS_DIR_NAME}/scripts/session_close.py --target-dir . --feature-id <task-id> --outcome pass")
    print(f"  6. 自动续跑下个任务（当前分支）：python3 {HARNESS_DIR_NAME}/scripts/task_switch.py continue --target-dir .")
    print(f"  7. 配置并启用远程更新：编辑 {HARNESS_DIR_NAME}/config/update-policy.json")


if __name__ == "__main__":
    main()
