# santong Skills 技能仓库

这里维护面向 Codex / Claude 等 Agent 的本地技能集合。每个一级目录代表一个独立 skill，真正的执行契约以各目录下的 `SKILL.md` 为准；本 README 只负责说明当前仓库结构、适用场景、常用命令和维护方式。

## 当前内容

```text
santong-skills/
├── by-harness/        # 工程闭环与任务执行 harness
│   ├── SKILL.md
│   ├── scripts/       # scaffold、拆任务、切任务、会话收口、运行时升级
│   ├── templates/     # 初始化时下发到目标仓库的模板
│   └── runtime/       # stable / beta 远程升级 manifest
├── by-tech-plan/      # 技术方案拷问、合成与评审模板
│   └── SKILL.md
└── docs/              # 演示材料与静态 showcase（不属于 skill 运行时依赖）
```

## 使用方式

- 需要某个技能时，让 Agent 直接使用对应 skill 名称，例如 `by-harness` 或 `by-tech-plan`。
- 修改或排查技能行为时，先读对应 `SKILL.md`，再读脚本和模板；不要只按 README 推断执行细节。
- `by-harness` 的脚本可以直接从本仓库运行，也可以由初始化后的目标仓库使用 `.harness/scripts/` 下发副本运行。

## by-harness

`by-harness` 用来给目标仓库安装并运行一套稳定的工程交付闭环：

```text
read task -> plan -> build -> qa -> fix -> mark_pass -> session_close
```

当前运行时版本为 `2.6.0`，版本号在以下位置保持一致：

- `by-harness/scripts/scaffold.py` 的 `HARNESS_RUNTIME_VERSION`
- `by-harness/scripts/update_runtime.py` 的 `LATEST_RUNTIME_VERSION`
- `by-harness/runtime/stable/manifest.json`
- `by-harness/runtime/beta/manifest.json`

### 初始化后布局

默认初始化会在目标仓库生成：

```text
AGENTS.md
CLAUDE.md
.codex/
.claude/
.harness/
├── config/
├── docs/
├── scripts/
└── task-harness/
    ├── index.json
    ├── tasks/
    └── progress/
```

说明：

- `AGENTS.md` 是 Codex 主入口，`CLAUDE.md` 是 Claude 主入口。
- `.harness/config/runtime-version.json` 记录运行时版本，用于后续升级。
- `.harness/config/update-policy.json` 控制 stable / beta manifest 检查、checksum 校验和自动升级策略。
- 新任务默认使用 v3 单任务文件模型，写入 `.harness/task-harness/tasks/<batch>/Txxx-*.json`。
- `.harness/feature_list.json` 只保留 legacy 兼容语义，新项目不要主动依赖它。
- `.harness/task-harness/progress/latest.txt` 是最近一次会话快照，详细历史在 `.harness/task-harness/progress/YYYY-MM/*.md`。

### 核心能力

- `scaffold.py`：向目标仓库安装 by-harness 运行时、入口文档、hooks、任务模板和工程规范。
- `decompose_tasks.py`：把需求拆成可独立闭环的任务文件。
- `ensure_task_branch.py`：定位当前应执行的任务，不负责强制切分支。
- `session_close.py`：写入会话进度、刷新 latest 快照，并给出下一任务建议。
- `task_switch.py`：在当前分支继续下一个任务，并触发运行时检查。
- `update_runtime.py`：做版本化升级、flat-to-grouped 迁移、manifest 拉取与 checksum 校验。
- `qa_runner.py` / `qa_report.py` / `qa_gate.py` / `testcontainers_doctor.py`：执行 QA Gate，解析 Surefire/Failsafe 报告，并将 required 集成测试门禁绑定回 contract。
- Java 规则：下发 Java 总门禁、分片规则和分布式 Java gate，约束 spec、contract、build、qa 全链路。
- Artifact + QA gate：任务标记 `passes=true` 前，必须有真实落盘的 `spec_path` 与 `contract_path`，且 required QA Gate 通过。

### 常用命令

初始化目标仓库：

```bash
python3 by-harness/scripts/scaffold.py \
  --project-name "your-project" \
  --description "一句话描述项目目标" \
  --tech-stack "Java 8 + Spring Boot" \
  --project-type "backend service" \
  --target-dir "/path/to/target-repo"
```

初始化后在目标仓库执行：

```bash
bash .harness/scripts/init.sh
```

持续拆任务：

```bash
python3 by-harness/scripts/decompose_tasks.py \
  --target-dir "/path/to/target-repo" \
  --batch-name "权限与审计" \
  --item "新增用户权限矩阵" \
  --item "增加组织级审计日志"
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

自动续跑下个任务：

```bash
python3 .harness/scripts/task_switch.py continue --target-dir "."
```

执行 QA Gate：

```bash
python3 .harness/scripts/qa_runner.py --target-dir "." --contract ".harness/docs/contracts/<feature>.md"
python3 .harness/scripts/qa_gate.py --target-dir "." --result-json ".harness/docs/qa/<feature>.result.json"
```

手动检查或升级运行时：

```bash
python3 .harness/scripts/update_runtime.py --target-dir "." --check-remote --force-check
```

### 老仓库升级

老仓库优先使用版本化升级，不要重新全量覆盖：

```bash
python3 by-harness/scripts/update_runtime.py --target-dir "/path/to/target-repo"
```

升级策略：

- 默认先读取目标仓库 `.harness/config/runtime-version.json`。
- 有 `manifest_url` 时，从远程 manifest 拉取文件并校验 `sha256`。
- 没有 `manifest_url` 时，只执行本地兼容迁移。
- 本地版本高于当前内置版本时，只告警，不降级覆盖。
- `upgrade_legacy_repo.py` 仍保留兼容入口，但新维护优先使用 `update_runtime.py`。

当前 stable / beta manifest 地址：

```text
https://raw.githubusercontent.com/xmzDesign/santong-skill/main/by-harness/runtime/stable/manifest.json
https://raw.githubusercontent.com/xmzDesign/santong-skill/main/by-harness/runtime/beta/manifest.json
```

## by-tech-plan

`by-tech-plan` 用来把业务需求、PRD、接口约束和代码上下文整理成可评审、可上线、可追责的技术方案。它不是简单套模板，而是先澄清目标、边界、系统影响、数据模型、接口契约、并发一致性、测试、上线、运维和风险。

适用场景：

- 写技术方案、技术设计、方案评审文档。
- 把 PRD 或需求草稿整理成 Markdown 方案。
- 对接口、库表、任务、消息、缓存、发布和回滚做评审前拷问。
- 在 `by-harness` 执行前，把“要做什么、为什么这么做、验收口径是什么”先锁清楚。

工作模式：

- 拷问模式：用户只有粗略想法时，一次只问一个关键问题，并给出推荐答案供确认。
- 合成模式：输入材料足够时，先做信息回放，再产出完整技术方案。

建议输入：

- PRD / 需求说明
- 接口文档
- 代码仓库或相关模块路径
- 数据库表结构或迁移脚本
- 历史方案、ADR、线上问题或运维约束

`docs/examples/by-harness-by-tech-plan-demo.md` 展示了一个完整串联示例：先用 `by-tech-plan` 明确 LeadSpark 百应标签补充方案，再用 `by-harness` 拆成可执行任务。



## 维护校验

修改 `by-harness` 脚本、模板或 manifest 后，至少执行：

```bash
python3 -m py_compile by-harness/scripts/*.py
bash -n by-harness/templates/task/init.sh
python3 -m json.tool by-harness/runtime/stable/manifest.json >/dev/null
python3 -m json.tool by-harness/runtime/beta/manifest.json >/dev/null
```

如果改动了 manifest 中声明的文件，必须重新计算对应 `sha256`，并同步更新 stable / beta 两个 manifest。

修改 README 时同步检查这些高漂移点：

- `by-harness` 当前运行时版本。
- 初始化后的 `.harness/` 目录结构。
- 任务存储模型是否仍是 v3 单任务文件。
- stable / beta manifest 地址和默认更新策略。
- 新增或删除的 skill 目录。
