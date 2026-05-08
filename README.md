# santong Skills 技能仓库

这里是 Skills 技能集合，每个子目录代表一个独立技能。

## 目录结构

```text
santong-skills/
└── by-harness/   # 独立融合版（初始化 + 持续拆任务 + 会话控制 + 自动续跑）
```

## by-harness（独立融合版 Harness）

`by-harness` 用于一键落地 `plan -> build -> qa -> fix` 统一闭环，不依赖其他 skill 目录。

### 核心能力

- 根目录极简：默认只放 `AGENTS.md`（以及隐藏运行目录 `.codex/.claude`）
- 根目录入口文件：`AGENTS.md`（Codex）与 `CLAUDE.md`（Claude）
- 工作文件集中在 `.harness/`：`config/`、`docs/`、`scripts/`、`task-harness/`（`feature_list.json` 不再默认创建，仅 legacy 项目兼容）
- 默认下发工程规范文档：`.harness/docs/java-dev-conventions.md`（后端）与 `.harness/docs/frontend-dev-conventions.md`（前端）
- 默认下发 Java Gate：Service 接口/实现、入口依赖方向、MapStruct、中文注释、金额、分页、Redis、日志、配置密钥，贯穿 plan/build/qa/hook
- 默认下发 Distributed Java Gate：所有 Java 改动都需声明分布式影响；触发外部调用、幂等、重试、锁、事务、缓存、消息、异步、发布停机时，按 `.harness/docs/java-dev-conventions.md` 第 14 章进入 spec/contract/build/qa
- 默认下发前端三层规范：`.harness/docs/frontend/rules.md`（约束层）、`code-design.md`（示范层）、`ui-design.md`（视觉层），用于约束 AI 生成前端页面、组件、样式和交互
- 默认下发 BYAI HTML 参考：`.harness/docs/frontend/references/byai-ds-v/`，包含页面 gallery、12 个页面设计稿、组件 showcase、tokens 与设计说明快照
- 运行时版本文件：`.harness/config/runtime-version.json`（用于版本化升级）
- 远程更新策略：`.harness/config/update-policy.json`（定时检查 + 自动升级策略）
- 自动任务定位：`.harness/scripts/ensure_task_branch.py`（按任务状态/提示词选出当前要做的 feature，不切分支）
- 会话收口：`.harness/scripts/session_close.py`（会话日志 + 快照 + 会话状态）
- 连续切任务：`.harness/scripts/task_switch.py`（当前分支自动续跑下个任务）
- 持续拆任务：新任务默认按批次写入 `.harness/task-harness/tasks/<batch-id>/`，文件名带 `T001` 数字号和中文标题；legacy 项目可继续写旧 bucket
- 每个任务闭环工件字段：`spec_path` / `contract_path` / `qa_report_path`
- 门禁策略：单元测试通过且 spec/contract 已落盘后才可 `passes=true`，QA 默认非阻塞
- Artifact Gate：已标记 `passes=true` 的 feature 必须存在 `spec_path` 与 `contract_path` 对应文件，否则 pre-completion hook 阻断完成
- 注释准则：所有新增/修改函数、方法必须补齐中文注释（用途、参数、返回值、副作用）

### 任务索引与进度快照

- `.harness/task-harness/index.json`：任务路由索引（给脚本读）
- 作用：维护 `active_bucket` 与各 bucket 文件路径映射，帮助 `init.sh`、`ensure_task_branch.py`、`decompose/rebalance` 快速定位“当前任务桶”
- `.harness/task-harness/progress/latest.txt`：最新进度快照（给人读）
- 作用：记录最近一次会话收口后的摘要（当前 feature、完成项、风险与下一步），用于新会话快速接续
- 详细历史仍在：`.harness/task-harness/progress/YYYY-MM/*.md`

### 一体化初始化

```bash
python3 by-harness/scripts/scaffold.py \
  --project-name "your-project" \
  --description "一句话描述项目目标" \
  --tech-stack "React + Node.js" \
  --project-type "web app" \
  --target-dir "."
```

初始化后先执行：

```bash
bash .harness/scripts/init.sh
```

### 常用命令

持续拆任务：

```bash
python3 by-harness/scripts/decompose_tasks.py \
  --target-dir "." \
  --batch-name "权限与审计" \
  --item "新增用户权限矩阵" \
  --item "增加组织级审计日志"
```

任务重平衡：

```bash
python3 by-harness/scripts/rebalance_tasks.py --target-dir "."
```

会话收口：

```bash
python3 .harness/scripts/session_close.py \
  --target-dir "." \
  --feature-id "B001-T001" \
  --outcome "in-progress" \
  --qa-score 72 \
  --note "已完成 plan/build，准备进入 fix"
```

自动续跑下个任务（当前分支）：

```bash
python3 .harness/scripts/task_switch.py continue --target-dir "."
```

远程运行时检查（按策略定时）：

```bash
python3 .harness/scripts/update_runtime.py --target-dir "." --check-remote
```

### 会话控制配置（`.harness/config/task.json`）

```json
{
  "harness": {
    "session_control": {
      "mode": "soft_reset"
    }
  }
}
```

- `mode`
  - `soft_reset`：同一会话可继续，但自动提升 context epoch，要求忽略旧任务上下文
  - `hard_new_session`：任务收口后强制新会话

### 老仓库升级建议

- 可以再次执行 `scaffold.py`，默认不带 `--force` 时已有文件会 `SKIP`，不会直接覆盖任务数据
- 不要在已有项目直接全量 `--force`
- 升级由版本文件 `.harness/config/runtime-version.json` 驱动，脚本会自动同步运行时脚本与迁移 `config/task.json`
- 推荐直接使用版本化升级脚本（自动备份 + 按版本差异迁移）：

```bash
python3 by-harness/scripts/update_runtime.py --target-dir "<你的项目目录>"
```

- 当 `manifest_url` 已配置时，`update_runtime.py` 会从远程拉取脚本并校验 checksum。
- 当 `manifest_url` 未配置时，`update_runtime.py` 仅执行本地兼容迁移。
- 当本地 `runtime_version` 高于内置或远程版本时，脚本只告警并保持当前版本，不会自动降级覆盖。

- 兼容旧命令（已废弃但可用）：

```bash
python3 by-harness/scripts/upgrade_legacy_repo.py --target-dir "<你的项目目录>"
```

### 远程自动更新配置

1) 在远程维护 `manifest.json`（建议 stable / beta 分开）。  
2) 在项目配置 `.harness/config/update-policy.json` 的 `manifest_url`。  
3) `init.sh` 与 `task_switch.py continue` 会自动触发定时检查，发现新版本按策略自动更新。
默认模板里 `enabled=false`，配置 `manifest_url` 后请切换为 `true`。

`update-policy.json` 关键字段示例：

```json
{
  "enabled": true,
  "manifest_url": "https://your-domain/path/by-harness/stable/manifest.json",
  "check_interval_minutes": 360,
  "auto_apply_patch": true,
  "auto_apply_minor": false,
  "auto_apply_major": false,
  "require_checksum": true
}
```

`xmzDesign/santong-skill` 的双通道地址示例：

- stable：`https://raw.githubusercontent.com/xmzDesign/santong-skill/main/by-harness/runtime/stable/manifest.json`
- beta：`https://raw.githubusercontent.com/xmzDesign/santong-skill/main/by-harness/runtime/beta/manifest.json`

切换到 stable：

```json
{
  "enabled": true,
  "channel": "stable",
  "manifest_url": "https://raw.githubusercontent.com/xmzDesign/santong-skill/main/by-harness/runtime/stable/manifest.json"
}
```

切换到 beta：

```json
{
  "enabled": true,
  "channel": "beta",
  "manifest_url": "https://raw.githubusercontent.com/xmzDesign/santong-skill/main/by-harness/runtime/beta/manifest.json"
}
```

配置变更后可强制检查一次：

```bash
python3 .harness/scripts/update_runtime.py --target-dir . --check-remote --force-check
```

远程 `manifest.json` 最小结构示例：

说明：`files` 不仅可下发 `scripts/*`，也可下发 `.harness` 内的规范文档（如 `docs/TASK-HARNESS.md`、`docs/*.md`），用于统一更新团队执行规范。

```json
{
  "skill": "by-harness",
  "channel": "stable",
  "version": "2.2.1",
  "min_compatible_version": "1.0.0",
  "files": [
    {
      "path": "scripts/session_close.py",
      "url": "https://your-domain/path/session_close.py",
      "sha256": "..."
    },
    {
      "path": "scripts/ensure_task_branch.py",
      "url": "https://your-domain/path/ensure_task_branch.py",
      "sha256": "..."
    },
    {
      "path": "scripts/task_switch.py",
      "url": "https://your-domain/path/task_switch.py",
      "sha256": "..."
    },
    {
      "path": "scripts/update_runtime.py",
      "url": "https://your-domain/path/update_runtime.py",
      "sha256": "..."
    }
  ]
}
```
