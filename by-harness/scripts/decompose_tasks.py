#!/usr/bin/env python3
"""
by-harness task decomposition helper.

Append new tasks into task storage with harness-closed-loop defaults.
Supports:
- v3 mode: task-harness/tasks/<task-id>.json (default)
- legacy mode: feature_list.json
- sharded mode: task-harness/index.json + task-harness/features/*.json
"""

import argparse
import hashlib
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from task_store import TASK_SCHEMA, detect_workspace_dir, dump_json, load_json, load_task_entries

HARNESS_DIR_NAME = ".harness"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Append new decomposed tasks into harness task storage."
    )
    parser.add_argument("--target-dir", required=True, help="目标项目目录")
    parser.add_argument(
        "--item",
        action="append",
        dest="items",
        required=True,
        help="新增任务描述（可重复传多次）",
    )
    parser.add_argument("--category", default="feature", help="任务分类，默认 feature")
    parser.add_argument("--id-prefix", default="feat", help="ID 前缀，默认 feat")
    parser.add_argument(
        "--start-priority",
        type=int,
        default=0,
        help="优先级起点（0 表示自动从现有最大值+1）",
    )
    parser.add_argument(
        "--bucket",
        default="",
        help="目标 legacy/v2 任务桶 ID；默认写入 v3 单任务文件以降低多分支合并冲突",
    )
    parser.add_argument(
        "--use-legacy",
        action="store_true",
        help="强制使用 legacy 模式（feature_list.json）",
    )
    return parser.parse_args()


def parse_id_index(feature_id: str, prefix: str) -> int:
    pattern = re.compile(rf"^{re.escape(prefix)}-(\d+)$")
    match = pattern.match(feature_id)
    return int(match.group(1)) if match else 0


def next_start_index(features, prefix: str) -> int:
    max_idx = 0
    for feat in features:
        max_idx = max(max_idx, parse_id_index(str(feat.get("id", "")), prefix))
    return max_idx + 1


def next_priority_start(features, explicit_start: int) -> int:
    if explicit_start > 0:
        return explicit_start
    max_priority = 0
    for feat in features:
        try:
            max_priority = max(max_priority, int(feat.get("priority", 0)))
        except (TypeError, ValueError):
            pass
    return max_priority + 1


def path_prefix_for_artifacts(workspace_dir: Path, target_dir: Path) -> str:
    if workspace_dir == target_dir:
        return ""
    return workspace_dir.relative_to(target_dir).as_posix()


def artifact_paths(feature_id: str, prefix: str):
    base = f"{prefix}/" if prefix else ""
    return {
        "spec_path": f"{base}docs/specs/{feature_id}.md",
        "contract_path": f"{base}docs/contracts/{feature_id}.md",
        "qa_report_path": f"{base}docs/qa/{feature_id}.md",
    }


def ensure_artifact_fields(features, path_prefix: str):
    updated = 0
    for feat in features:
        feature_id = str(feat.get("id", "")).strip()
        if not feature_id:
            continue
        paths = artifact_paths(feature_id, path_prefix)
        for key, value in paths.items():
            if not feat.get(key):
                feat[key] = value
                updated += 1
    return updated


def build_feature(item_desc: str, feature_id: str, category: str, priority: int, path_prefix: str):
    paths = artifact_paths(feature_id, path_prefix)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return {
        "schema": TASK_SCHEMA,
        "id": feature_id,
        "category": category,
        "priority": priority,
        "description": item_desc,
        "file": None,
        "status": "todo",
        "spec_path": paths["spec_path"],
        "contract_path": paths["contract_path"],
        "qa_report_path": paths["qa_report_path"],
        "steps": [
            f"读取任务定义：task-harness/tasks 中 {feature_id} 的目标与约束",
            f"执行 plan：生成 {paths['spec_path']}",
            f"执行 contract：生成 {paths['contract_path']} 并明确验收标准与验证方式",
            "执行 build：按 contract 范围实现并完成自检（构建/单元测试/验收标准）",
            f"执行 qa：生成 {paths['qa_report_path']}，作为非阻塞质量报告",
            "若单元测试未通过，进入 fix 循环（最多 3 轮）",
            "执行 mark_pass：单元测试通过且 spec/contract 文件已落盘后才可将 passes 置为 true；3 轮失败则保持 false 并继续下个任务",
        ],
        "passes": False,
        "verification": "单元测试通过且 spec/contract 文件已落盘后才可判定通过；qa 报告为建议项，不阻塞流程",
        "created_at": now,
        "updated_at": now,
    }


def slug(text: str, fallback: str = "task") -> str:
    raw = (text or fallback).strip().lower()
    raw = re.sub(r"[^a-z0-9]+", "-", raw)
    raw = raw.strip("-")
    return raw[:48].strip("-") or fallback


def generate_file_task_id(item_desc: str, id_prefix: str, offset: int) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    text_slug = slug(item_desc, "task")
    nonce_input = f"{stamp}|{offset}|{item_desc}|{uuid.uuid4().hex}"
    nonce = hashlib.sha1(nonce_input.encode("utf-8")).hexdigest()[:6]
    return f"{stamp}-{slug(id_prefix, 'feat')}-{text_slug}-{nonce}"


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


def resolve_store(workspace_dir: Path, bucket_arg: str, use_legacy: bool):
    if not use_legacy and not bucket_arg:
        return {
            "mode": "file_tasks",
            "tasks_dir": workspace_dir / "task-harness" / "tasks",
            "bucket_id": "file-tasks",
            "index": None,
            "index_path": workspace_dir / "task-harness" / "index.json",
        }

    index_path = workspace_dir / "task-harness" / "index.json"
    if use_legacy or not index_path.exists():
        return {
            "mode": "legacy",
            "feature_path": workspace_dir / "feature_list.json",
            "bucket_id": "legacy",
            "index": None,
            "index_path": index_path,
        }

    index = load_json(index_path)
    buckets = index.get("buckets", [])
    if not isinstance(buckets, list) or not buckets:
        raise RuntimeError("task-harness/index.json 缺少有效 buckets 配置")

    bucket_id = bucket_arg or index.get("active_bucket", "")
    if not bucket_id:
        bucket_id = buckets[0].get("id", "")
    bucket_obj = next((b for b in buckets if b.get("id") == bucket_id), None)
    if bucket_obj is None:
        valid = ", ".join(str(b.get("id", "")) for b in buckets)
        raise RuntimeError(f"bucket 不存在: {bucket_id}，可选: {valid}")

    rel_path = bucket_obj.get("path", "")
    if not rel_path:
        raise RuntimeError(f"bucket {bucket_id} 未配置 path")

    return {
        "mode": "sharded",
        "feature_path": resolve_bucket_feature_path(workspace_dir, rel_path),
        "bucket_id": bucket_id,
        "index": index,
        "index_path": index_path,
    }


def load_or_init_feature_doc(feature_path: Path, workspace_dir: Path):
    if feature_path.exists():
        data = load_json(feature_path)
        if not isinstance(data.get("features"), list):
            data["features"] = []
        return data

    legacy = workspace_dir / "feature_list.json"
    if legacy.exists():
        data = load_json(legacy)
        if not isinstance(data.get("features"), list):
            data["features"] = []
        data["features"] = []
        return data

    return {
        "project": workspace_dir.name,
        "description": "待补充",
        "features": [],
    }


def aggregate_features(workspace_dir: Path, store):
    if store["mode"] == "file_tasks":
        return [entry.feature for entry in load_task_entries(workspace_dir)]

    if store["mode"] == "legacy":
        return load_json(store["feature_path"]).get("features", [])

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


def sync_legacy_view(workspace_dir: Path, data) -> bool:
    legacy_path = workspace_dir / "feature_list.json"
    if not legacy_path.exists():
        return False
    dump_json(legacy_path, data)
    return True


def update_task_summary(workspace_dir: Path, all_features):
    task_json = workspace_dir / "config" / "task.json"
    if not task_json.exists():
        task_json = workspace_dir / "task.json"
    if not task_json.exists():
        return

    data = load_json(task_json)
    summary = data.get("summary", {})
    summary["total_features"] = len(all_features)
    categories = {}
    for feat in all_features:
        category = str(feat.get("category", "unknown"))
        categories[category] = categories.get(category, 0) + 1
    summary["categories"] = categories
    data["summary"] = summary
    data["updated"] = datetime.now().strftime("%Y-%m-%d")
    dump_json(task_json, data)


def append_progress_note(workspace_dir: Path, added_ids, bucket_id: str, mode: str):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    note = (
        "\n----------------------------------------\n"
        "任务拆解更新\n"
        "----------------------------------------\n"
        f"时间: {now}\n"
        f"新增任务: {', '.join(added_ids)}\n"
        f"任务桶: {bucket_id}\n"
        "说明: 新任务已按 harness 闭环模板生成（read task/plan/build/qa(non-blocking)/fix/mark_pass）。\n"
    )

    if mode in ("sharded", "file_tasks"):
        monthly = datetime.now().strftime("%Y-%m")
        if mode == "file_tasks":
            safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", added_ids[0]) if added_ids else "tasks"
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            progress_path = workspace_dir / "task-harness" / "progress" / monthly / f"{stamp}-decompose-{safe_id}.md"
        else:
            progress_path = workspace_dir / "task-harness" / "progress" / f"{monthly}.md"
    else:
        progress_path = workspace_dir / "progress.txt"

    content = progress_path.read_text(encoding="utf-8") if progress_path.exists() else ""
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    progress_path.write_text(content + note, encoding="utf-8")


def main():
    args = parse_args()
    target_dir = Path(args.target_dir).resolve()
    workspace_dir = detect_workspace_dir(target_dir)
    path_prefix = path_prefix_for_artifacts(workspace_dir, target_dir)

    try:
        store = resolve_store(workspace_dir, args.bucket, args.use_legacy)
    except RuntimeError as exc:
        print(f"Error: {exc}")
        sys.exit(1)

    feature_path = store.get("feature_path")
    repaired = 0
    legacy_synced = False
    added = []

    if store["mode"] == "file_tasks":
        existing_for_index = aggregate_features(workspace_dir, store)
        pri_start = next_priority_start(existing_for_index, args.start_priority)
        tasks_dir = store["tasks_dir"]
        tasks_dir.mkdir(parents=True, exist_ok=True)
        for offset, item_desc in enumerate(args.items):
            feature_id = generate_file_task_id(item_desc, args.id_prefix, offset)
            priority = pri_start + offset
            feat = build_feature(item_desc, feature_id, args.category, priority, path_prefix)
            task_path = tasks_dir / f"{feature_id}.json"
            dump_json(task_path, feat)
            added.append(feature_id)
    else:
        data = load_or_init_feature_doc(feature_path, workspace_dir)
        if not isinstance(data.get("features"), list):
            data["features"] = []

        features = data["features"]
        repaired = ensure_artifact_fields(features, path_prefix)

        existing_for_index = aggregate_features(workspace_dir, store)
        if store["mode"] == "legacy":
            existing_for_index = features

        idx_start = next_start_index(existing_for_index, args.id_prefix)
        pri_start = next_priority_start(existing_for_index, args.start_priority)

        for offset, item_desc in enumerate(args.items):
            feature_id = f"{args.id_prefix}-{idx_start + offset:02d}"
            priority = pri_start + offset
            feat = build_feature(item_desc, feature_id, args.category, priority, path_prefix)
            features.append(feat)
            added.append(feature_id)

        data["features"] = features
        dump_json(feature_path, data)

        if store["mode"] == "sharded":
            legacy_synced = sync_legacy_view(workspace_dir, data)

    all_features = aggregate_features(workspace_dir, store)
    update_task_summary(workspace_dir, all_features)
    append_progress_note(workspace_dir, added, store["bucket_id"], store["mode"])

    print("Added tasks:")
    for task_id in added:
        print(f"  - {task_id}")
    if repaired > 0:
        print(f"Backfilled artifact fields on existing tasks: {repaired} fields updated")
    print(f"Target store: {store['mode']} / bucket={store['bucket_id']}")
    if store["mode"] == "file_tasks":
        print(f"Task files created under: {store['tasks_dir']}")
    else:
        print(f"Feature file updated: {feature_path}")
    if legacy_synced:
        print(f"Legacy mirror synced: {workspace_dir / 'feature_list.json'}")
    print("Reminder: pass gate = unit tests; QA report is non-blocking.")


if __name__ == "__main__":
    main()
