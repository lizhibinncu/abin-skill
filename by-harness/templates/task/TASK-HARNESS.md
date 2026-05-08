# {{项目名称}} - TASK-HARNESS 任务层执行规则

本文件是任务层契约，负责“任务拆分与进度追踪”。  
根目录 `AGENTS.md` 由 Harness Engineering 管理，负责 `Plan -> Build -> Verify` 主闭环。两者必须同时遵循。

## 工件定位（技术方案 / 测试计划 / 验证结果）

- 技术方案：`spec_path` 指向的规格文件（通常为 `.harness/docs/specs/<task-id>.md`）
- 测试计划与验收标准：`contract_path` 指向的契约文件（通常为 `.harness/docs/contracts/<task-id>.md`）
- 测试结果与评分：`qa_report_path` 指向的 QA 报告（通常为 `.harness/docs/qa/<task-id>.md`）

## 会话启动（必须按顺序）

1. 运行 `bash .harness/scripts/init.sh`（legacy 项目可用 `bash .harness/init.sh`）
2. 阅读根目录 `AGENTS.md`/`CLAUDE.md`（主工作流约束）
3. 阅读 `.harness/docs/TASK-HARNESS.md`（任务追踪约束）
4. 阅读 `.harness/task-harness/index.json`（定位 `task_globs`）
5. 阅读对应单任务文件（如 `.harness/task-harness/tasks/<batch-id>/<display-id>-<title>-<hash>.json`；旧 `.harness/task-harness/tasks/<task-id>.json`、`.harness/task-harness/features/*.json` 与 `.harness/feature_list.json` 仅作兼容查看）
6. 阅读 `.harness/task-harness/progress/YYYY-MM/*.md`（`latest.txt` 只作 legacy 兼容快照）
7. 选择优先级最高且 `passes=false` 的 1 个功能

## 闭环执行契约（严格遵循 Harness Engineering）

针对选中的单个 feature，必须按以下严格顺序执行（不得跳步）：
1. **读取任务（read task）**：从单任务 JSON 读取该 feature 的 `description/steps/spec_path/contract_path/qa_report_path`
2. **plan**：生成/更新 `spec_path` 对应规格文件（禁止直接写实现）
3. **build**：基于 spec + contract 实现并自检；所有新增/修改函数、方法必须补齐中文注释
4. **qa（非阻塞）**：生成 `qa_report_path`，按 contract 逐条评分（用于质量跟踪，不阻塞流程）
5. **fix**：若单元测试未通过，进入修复循环（最多 3 轮）
6. **mark_pass**：单元测试通过，且 `spec_path` / `contract_path` 文件真实存在后，才可将该 feature `passes=false -> true`

## 任务清单修改规则

- 对应单任务 JSON（例如 `.harness/task-harness/tasks/<batch-id>/<display-id>-<title>-<hash>.json`）中仅允许修改：
  - `status: todo|doing|done`
  - `passes: false -> true`（单元测试通过且 spec/contract 已落盘后）
- 若存在 `.harness/feature_list.json` 或 `.harness/task-harness/features/*.json`，其为 legacy 兼容数据，常规不直接手改
- 禁止修改：
  - `id/category/priority/description/file/spec_path/contract_path/qa_report_path/steps/verification`
- 如需改任务定义，必须先和用户确认，再由用户批准后调整

## 会话结束前必须完成

1. 写入进度日志（`.harness/task-harness/progress/YYYY-MM/<timestamp>-<feature-id>.md`）
2. 若该 feature 单元测试通过且 `spec_path` / `contract_path` 文件存在：更新 `passes=true`
3. 运行会话收口脚本：`python3 .harness/scripts/session_close.py --target-dir . --feature-id <task-id> --outcome pass|fail|blocked|in-progress`
4. 提交 git commit（建议一个 feature 一个 commit）
5. 输出下一步建议（下一个 feature 或阻塞处理方案）
6. 根据 `.harness/config/task.json` 的 `harness.session_control.mode` 自动执行会话切换：
   - `soft_reset`：继续当前会话时，必须按新 epoch 上下文处理下一 feature
   - `hard_new_session`：必须新开会话后再开始下一 feature
7. 自动续跑下一个任务可执行：
   - `python3 .harness/scripts/task_switch.py continue --target-dir .`
   - 该命令会在当前分支自动定位下一个任务并更新状态（不切分支）

## 遇到阻塞时

- 立即停止当前 feature 的继续堆叠开发，先记录阻塞证据
- 若同一 feature 修复 3 轮仍未通过单元测试：保持 `passes=false`，并继续下一个任务
- 在 `.harness/task-harness/progress/YYYY-MM/<timestamp>-<feature-id>.md` 记录：
  - 阻塞现象
  - 已尝试方案
  - 失败原因
  - 建议下一步（缩范围 / 拆子任务 / 人工决策）

## Codex 提示词示例

- `先运行 .harness/scripts/init.sh，然后按 AGENTS.md + .harness/docs/TASK-HARNESS.md 执行下一个 feature`
- `执行 20260508T153012Z-feat-login-rate-limit-a3f9c2：严格按 read task -> plan -> build -> qa(non-blocking) -> fix -> mark_pass`
- `按 harness 工作流修复指定任务 ID，最多 3 轮；若单测仍失败则继续下一个任务`

## 项目信息

- 项目：`{{项目名称}}`
- 描述：`{{项目描述，一句话概括目标和范围}}`
