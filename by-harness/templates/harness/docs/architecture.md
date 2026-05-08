# 架构说明（Architecture）

Harness Engineering Framework 的系统设计说明。

---

## 系统图

```
用户
  |
  v
[/sprint <描述>] -----> [Planner 智能体]
                              |
                              v
                    .harness/docs/specs/<name>.md
                              |
                              v
                         [契约协商]
                     /                  \
            [Generator]  <------->  [Evaluator]
                    |                      |
                    v                      v
                 源码               测试结果 + 评分
                    |                      |
                    +-------- fix --------+
                              |
                              v
                [单元测试通过?] --否--> 修复循环（最多 3 轮）
                              |
                            是
                              v
                    [Doc Gardener] --> .harness/docs/ 已更新
                              |
                              v
                           冲刺完成
```

## 智能体关系

```
Planner ---> 产出 spec ---> Generator 读取 spec
Generator --> 提出 contract --> Evaluator 评审
Evaluator --> 给出评分 --> Generator 修复（如需）
Generator --> 完成冲刺 --> Doc Gardener 审计文档
```

## Hook 注入点

```
Claude 运行时：
  UserPromptSubmit --> .claude/hooks/context-injector.py
  PreToolUse(Edit|Write|MultiEdit) --> .claude/hooks/loop-detector.py
  PostToolUse(TaskUpdate) --> .claude/hooks/pre-completion-check.py

Codex 运行时：
  UserPromptSubmit --> .codex/hooks/context-injector.py
  PreToolUse(Edit|Write|MultiEdit) --> .codex/hooks/loop-detector.py
  Stop --> .codex/hooks/pre-completion-check.py
```

## 组件清单

| 组件 | 文件 | 作用 |
|-----------|------|------|
| Codex 指南 | `AGENTS.md` | Codex 入口与工作流规则 |
| 项目地图 | `CLAUDE.md` | Claude 入口与渐进披露导航 |
| Planner 智能体 | `.claude/agents/planner.md` | 将需求扩展为规格 |
| Generator 智能体 | `.claude/agents/generator.md` | 执行功能实现 |
| Evaluator 智能体 | `.claude/agents/evaluator.md` | 测试并评分 |
| Doc Gardener 智能体 | `.claude/agents/doc-gardener.md` | 维护文档新鲜度 |
| /plan 命令 | `.claude/commands/plan.md` | 触发 planner |
| /build 命令 | `.claude/commands/build.md` | 触发 generator + evaluator |
| /qa 命令 | `.claude/commands/qa.md` | 独立执行评估 |
| /sprint 命令 | `.claude/commands/sprint.md` | 执行全流程冲刺 |
| 循环检测 | `.claude/hooks/loop-detector.py` | 阻止无效反复编辑 |
| 完成前检查 | `.claude/hooks/pre-completion-check.py` | 完成前质量门禁 |
| 上下文注入 | `.claude/hooks/context-injector.py` | 注入会话上下文 |
| Codex Hook 配置 | `.codex/hooks.json` | Codex hook 注册 |
| Codex Hook 脚本 | `.codex/hooks/*.py` | Codex 运行时 hook 处理器 |
| Codex Hook 开关 | `.codex/config.toml` | 启用 Codex hooks |
| 黄金原则 | `.harness/docs/golden-principles.md` | 不可妥协规则 |
| 冲刺工作流 | `.harness/docs/sprint-workflow.md` | 流程文档 |
| 契约模板 | `.harness/docs/contracts/TEMPLATE.md` | 冲刺契约结构 |
| 任务清单（默认） | `.harness/task-harness/tasks/*.json` | v3 权威任务状态源，每个任务一个文件，适合多分支合并 |
| 任务清单（legacy 兼容） | `.harness/task-harness/features/*.json` / `.harness/feature_list.json` | 历史项目兼容读取，不作为新任务默认写入目标 |
| 任务层契约（可选） | `.harness/docs/TASK-HARNESS.md` | task-harness 任务追踪规则 |

## MCP 工具映射

| MCP 工具 | 使用方 | 目的 |
|----------|---------|---------|
| JUnit / Maven / Gradle | Evaluator | 单元测试、集成测试、构建验证 |
| convention-check | Evaluator | Java/MyBatis/SQL 机器检查 |
| web_reader | Planner | 获取外部文档资料 |

## Sprint 生命周期

```
状态：IDLE
  |
  [来自 Claude 命令或 Codex 提示的 plan/sprint 意图]
  v
状态：PLANNING（Planner 产出 spec）
  |
  [spec 已批准]
  v
状态：CONTRACTING（Generator + Evaluator 协商）
  |
  [contract 已达成一致]
  v
状态：BUILDING（Generator 实现）
  |
  [自检通过]
  v
状态：VERIFYING（Evaluator 测试）
  |
  [单元测试通过]
  v
状态：COMPLETE（文档更新，冲刺日志记录，必要时更新 passes）
  |
  [单元测试失败 且迭代 < 3]
  v
状态：FIXING（Generator 修复失败项）
  |
  [返回 VERIFYING]
```

## 扩展指南

### 新增智能体（Agent）

1. 在 `.claude/agents/<name>.md` 创建文件并补齐 frontmatter（name、description、tools）
2. 定义该智能体的角色、约束与输出格式
3. 在 `CLAUDE.md` 和/或 `AGENTS.md` 中补充引用
4. 需要时在 `.claude/commands/<name>.md` 增加对应命令

### 新增 Hook

1. 在 `.claude/hooks/<name>.py` 和/或 `.codex/hooks/<name>.py` 创建脚本
2. 在 `.claude/settings.json`（Claude）和/或 `.codex/hooks.json`（Codex）注册
3. 输出协议：
   - Claude：`{}` 放行，`{"decision":"block","reason":"..."}` 阻断，`{"systemMessage":"..."}` 注入
   - Codex：优先使用 `hookSpecificOutput`（如 `permissionDecision` / `additionalContext`）；兼容 legacy 的 `{"decision":"block","reason":"..."}`

### 新增命令（Command）

1. 在 `.claude/commands/<name>.md` 创建文件并补齐 frontmatter（description、argument-hint）
2. 在正文定义执行步骤
3. 通过 Agent tool 引用已有智能体
