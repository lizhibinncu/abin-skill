# {{PROJECT_NAME}} Claude 指南

本项目采用 Harness Engineering 工作流。在 Claude 中，请将此文件视为 `Plan -> Build -> Verify` 的执行契约。

## 快速开始（Claude）

可使用以下任一意图：

1. `/plan <功能描述>`
2. `/build`
3. `/qa`
4. `/sprint <功能描述>`（完整周期）

## Claude 意图路由

当用户请求匹配下列意图时，执行对应流程。

| 意图 | 触发示例 | 必要动作 | 必要输出 |
|---|---|---|---|
| `/plan` | “/plan login flow”, “/plan 设计订单取消流程” | 澄清歧义、检查相关代码、编写 spec | `.harness/docs/specs/<feature>.md` |
| `/build` | “/build”, “按最新 spec 实现” | 读取 spec+contract，按范围实现并自检 | 代码改动 + 冲刺报告 |
| `/qa` | “/qa”, “评估当前实现” | 读取 contract，执行 QA Gate 并逐条评分 | 结构化 QA 报告 + result JSON + 分数 |
| `/sprint` | “/sprint 构建用户权限” | 依次执行 plan+contract+build+qa+fix | spec + contract + 实现 + 报告 |

## 执行契约

### Plan 契约

- 不允许编写实现代码。
- Spec 必须包含：
  - 规范引用（Norm references）：本次读取的 Java/项目局部规范文件、适用原因、未适用原因
  - 问题陈述（Problem statement）
  - 用户故事（User stories）
  - 可机器验证的验收标准
  - 组件边界（Component boundaries）
  - 数据流（Data flow）
  - 错误处理（Error handling）
  - 最小实体与成本评估：如无必要，勿增实体；优先复用既有实体、表、DTO、Service、配置和扩展点
  - 至少 3 个边界场景
  - 依赖项（Dependencies）
- Plan 阶段必须遵守“如无必要，勿增实体”。尤其是历史项目的小改动，默认选择最小成本方案；若方案需要新增实体、表、DTO、Service、配置项或新层级，必须在 spec 中说明必要性、替代方案、兼容性、迁移成本和回滚影响。
- 若需求涉及 Java/Spring Boot/Dubbo/XXL-Job/MyBatis/Redis/金额/分页/配置/日志，Plan 阶段必须先阅读 `.harness/docs/java-dev-conventions.md` 入口，再按触发维度读取 `.harness/docs/java/rules/` 下的分片规则，并在 spec 的规范引用、Java 总门禁、维度核心门禁和分布式 Java 门禁中补充：
  - Java 总门禁 5 条：先契约后实现、先本地后通用、边界不被突破、风险显式落地、验证可追溯
  - 触发维度核心门禁：通用工程、分层与 DDD、Dubbo 与公共 API、日志与异常、持久化与基础设施、测试安全运维、分布式 Java 门禁；每个触发维度按入口文件列出的 5 条核心规则落地
  - 每条触发门禁的实现方式、验收方式、自动检查项和人工确认项
  - 分布式 Java 门禁：所有 Java 改动都必须声明“未触发/触发”；触发外部调用、Dubbo/HTTP/RPC、MQ、异步、线程池、锁、Redis、事务、补偿、发布停机时，必须列出 `.harness/docs/java/rules/distributed-java-gate.md` 对应条款、实现证据、验收方法和人工确认项
- 保存路径：`.harness/docs/specs/<feature-name>.md`

### Build 契约

- 从 `.harness/docs/specs/` 读取目标 spec。
- 从 `.harness/docs/contracts/` 读取目标 contract。
- 若 contract 缺失，先基于 `.harness/docs/contracts/TEMPLATE.md` 创建再实现。
- 若 spec/contract 缺少本次适用的 Java 总门禁、触发维度核心门禁或分布式 Java 门禁，先补齐 contract，再开始实现。
- 只允许实现 contract 范围内内容。
- 若项目技术栈包含 Java/Spring Boot，编码前必须先阅读 `.harness/docs/java-dev-conventions.md` 入口，并按任务触发维度读取 `.harness/docs/java/rules/` 分片规则，完成前置闸门确认。
- 若本次涉及 Java，实现前必须复述 Java 总门禁 5 条，并列出本次触发的维度核心门禁。未触发的维度要写明理由，触发的维度必须按入口文件中的 5 条核心规则逐项落地。
- 若本次涉及 Java，实现前必须声明魔法值治理方式：业务状态、任务类型、动作类型、错误码、配置 key、阈值使用 enum、语义常量或配置项，禁止在分支中散落字符串/数字字面量。
- 若本次涉及 Java，实现前必须确认 contract 已包含触发维度的验收项，至少覆盖分层与 DDD、Dubbo/API、日志异常、持久化基础设施、测试安全运维中的实际触发项。
- 若本次涉及 Java，实现前必须声明分布式 Java 门禁：未触发需说明理由；触发时逐项覆盖外部调用边界、资源隔离、一致性恢复、失败可追踪可降级、发布停机不丢数据。
- 所有新增/修改的函数、方法必须补充中文注释，至少说明：用途、关键参数、返回值与副作用（如状态变更/IO）。
- 交付前必须自检：
  - 构建/编译通过
  - 测试通过（既有 + 新增）
  - 验收标准逐条核对
  - 若涉及 Java：Java 总门禁、触发维度核心门禁、分布式 Java 门禁逐条核对；运行 convention-check；fail 必须修复，warn 必须修复或解释
  - 若涉及 Java：确认业务状态、任务类型、动作类型、错误码、配置 key、阈值没有散落魔法字符串/魔法数字
  - 新增/修改函数与方法的中文注释完整
  - 无调试残留

### QA 契约

- 评分只依据 contract 标准。
- 每条标准状态仅允许：`PASS` / `FAIL` / `PARTIAL`。
- 评分公式：
  - `score = (pass + 0.5 * partial) / total * 100`
- QA 结果按门禁级别生效：`required` 阻塞通过，`advisory` / `manual` 用于质量跟踪与人工确认。
- contract 的集成测试矩阵支持 `required` / `advisory` / `manual`：
  - `required`：失败则禁止 `passes=true`
  - `advisory`：失败进入 QA 报告，不阻塞
  - `manual`：列人工确认项，不计入机器通过率
- 若 contract 含 required 集成测试，必须运行 `python3 .harness/scripts/qa_runner.py --target-dir . --contract <contract-file>`，并确认 QA result JSON 中 `gate_status=PASS`。
- 每个 FAIL 必须包含：
  - 预期行为
  - 实际行为
  - 复现步骤
  - 修复建议

### Sprint 契约

- 顺序必须严格遵守：
  1. Plan
  2. Contract
  3. Build
  4. QA
  5. Fix loop（必要时）
  6. 文档新鲜度检查
- Fix loop 最大迭代：`3`。
- 若 3 轮后单元测试仍失败：
  - 记录失败项与建议
  - 保持当前 feature `passes=false`
  - 继续下一个 feature（不阻塞整体流程）

## 操作规则

- 先 spec 后代码。
- 先 contract 后 build。
- 先 artifact 后 pass：任何 feature 标记 `passes=true` 前，`spec_path` 与 `contract_path` 必须指向真实存在的文件。
- 一次只做一个 sprint。
- 会话切换策略由 `.harness/config/task.json` 的 `harness.session_control.mode` 控制：
  - `soft_reset`（默认）：feature 收口后自动切换 context epoch，继续会话时必须忽略旧 feature 上下文。
  - `hard_new_session`：feature 收口后必须新开会话，未新开会话前不允许进入下一 feature。
- 可用一条命令自动续跑下个任务（当前分支）：
  - `python3 .harness/scripts/task_switch.py continue --target-dir .`
- 禁止隐式扩范围。
- 如无必要，勿增实体；历史项目小改动优先最小成本实施。
- 问题必须显式暴露并附证据。
- 优先可回滚、低风险的朴素方案。
- 不得省略函数/方法中文注释；注释质量不达标视为未完成。

### Java 后端附加规则（适用时强制）

- 若为 Java 项目：必须先读 `.harness/docs/java-dev-conventions.md`，再按触发维度读取 `.harness/docs/java/rules/` 分片。
- 涉及 Java 实现时，必须在 plan/build/qa 中显式处理 Java 总门禁和触发维度核心门禁，不能只写“已阅读规范”。
- 读取 Java 规范时使用按需路由：通用工程看 `00-core.md`，分层与 DDD 看 `java-ddd.md`，Dubbo/API/DTO 看 `dubbo-api.md`，日志/异常看 `logging-error.md`，数据库/MyBatis/Redis/锁/MQ/配置看 `persistence-infra.md`，安全/测试/监控/部署看 `testing-security.md`，分布式影响看 `distributed-java-gate.md`。
- 所有 Java 改动必须显式处理分布式 Java 门禁：未触发需写明理由；触发 `.harness/docs/java/rules/distributed-java-gate.md` 任一条款时必须进入 spec、contract、build 自检和 QA 报告。
- 完成前运行 `.codex/hooks/convention-check.py --changed-only` 或 `.claude/hooks/convention-check.py --changed-only`。

## 与 Task Harness 的集成（可选但推荐）

若项目存在 `.harness/task-harness/index.json` 与 `.harness/docs/TASK-HARNESS.md`，按以下方式形成任务闭环：

1. 从 `.harness/task-harness/tasks/*.json` 与 `.harness/task-harness/tasks/**/*.json` 选择优先级最高且 `passes=false` 的 feature；旧 bucket/feature_list 仅作兼容读取
2. 严格执行 `plan -> contract -> build -> qa -> fix` 主流程
3. 单元测试通过、convention-check 无 fail、required QA Gate 通过，且 `spec_path` / `contract_path` 文件真实存在后，才可将该 feature 的 `passes` 置为 `true`
4. 通过 `.harness/scripts/session_close.py` 写入 `.harness/task-harness/progress/YYYY-MM/<timestamp>-<feature-id>.md`
5. 若达到 3 轮仍失败，保持 `passes=false` 并继续下一个任务

集成约束：
- `AGENTS.md` 负责主闭环，不负责改任务定义
- `.harness/docs/TASK-HARNESS.md` 负责任务追踪，不得覆盖主闭环规则
- QA 结论中的 required gate 是阻塞门禁；advisory/manual 用于质量跟踪和人工确认

## Claude Hook 运行时

- Claude hooks 定义在 `.claude/settings.json`
- hook 脚本位于 `.claude/hooks/`
- 主要目标：
  - PreToolUse 循环检测
  - UserPromptSubmit 上下文注入
  - Stop 阶段完成前检查提醒

## 项目布局

- `AGENTS.md`：Codex 执行入口
- `CLAUDE.md`：Claude 执行入口
- `.claude/agents/`：角色定义
- `.claude/commands/`：标准命令流程
- `.claude/hooks/`：循环/上下文/检查 hook
- `.harness/docs/specs/`：功能规格
- `.harness/docs/contracts/`：冲刺契约
- `.harness/docs/plans/`：计划产物
- `.harness/docs/java-dev-conventions.md`：Java 后端编码规范入口（Java 项目先读）
- `.harness/docs/java/rules/`：Java 分片规则（按任务触发维度读取）
- `.harness/task-harness/tasks/`：v3 权威任务目录，新任务默认按批次写入 `<batch-id>/<display-id>-<中文标题>-<hash>.json`
- `.harness/task-harness/features/`：v2/legacy bucket 目录，仅兼容读取
- `.harness/feature_list.json`：legacy 兼容镜像（仅在历史项目存在时沿用）
- `.harness/config/runtime-version.json`：运行时版本号（用于版本化升级）
- `.harness/config/update-policy.json`：远程更新策略（定时检查与自动应用）
- `.harness/docs/TASK-HARNESS.md`：任务层执行契约（可选）

## 提示词示例（Claude）

- `/plan 增加邮箱魔法链接免密登录`
- `/build`
- `/qa`
- `/sprint 在 dashboard 中增加组织切换器`

## 技术栈

- 项目：`{{PROJECT_NAME}}`
- 类型：`{{PROJECT_TYPE}}`
- 技术栈：`{{TECH_STACK}}`
