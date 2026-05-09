---
description: 让 evaluator 对当前代码状态执行评估
argument-hint: 可选 - 指定要评估的 contract 或 spec
---

# 质量保障（QA Gate）

对当前实现执行完整评估流程，并将业务逻辑集成验证结果写入 QA Gate。

**目标**：$ARGUMENTS（为空时默认对 `.harness/docs/contracts/` 中的契约进行评估）

## 流程

### 1. 选择目标

- 若传入参数：按指定 contract/spec 评估。
- 若未传参数：列出 `.harness/docs/contracts/` 下全部契约让用户选择，或默认评估最新契约。

### 2. 执行 QA Runner

优先运行：

```bash
python3 .harness/scripts/qa_runner.py --target-dir . --contract "<contract 文件>"
```

未指定 contract 时，使用最近修改的 `.harness/docs/contracts/*.md`。`qa_runner.py` 会：
1. 运行 Testcontainers doctor，检查 Docker 与集成测试环境。
2. 运行 `convention-check`（如果项目已下发 hook）。
3. 运行 `mvn test`。
4. 运行 `mvn verify`，由 Failsafe 执行 `*IT.java` / 项目约定集成测试。
5. 解析 `target/surefire-reports/` 与 `target/failsafe-reports/`。
6. 生成 `.harness/docs/qa/<feature>.md` 和 `.harness/docs/qa/<feature>.result.json`。

### 3. 调用 Evaluator

启动 `evaluator` 智能体复核报告，其会：
1. 读取冲刺契约中的验收标准。
2. 阅读源码并校验逻辑正确性。
3. 若涉及 Java，读取 `.harness/docs/java-dev-conventions.md` 入口和任务触发的 `.harness/docs/java/rules/` 分片规则，按 Java 总门禁与触发维度核心门禁检查实现，并运行 convention-check。
4. 若涉及 Java，检查业务状态、任务类型、动作类型、错误码、配置 key、阈值是否使用 enum、语义常量或配置项，确认没有散落魔法字符串/魔法数字，也没有用 `null` 隐式表达默认业务类型。
5. 若存在 Java 改动，检查 spec/contract 是否包含分布式 Java 门禁；未声明则 FAIL。若触发 `.harness/docs/java/rules/distributed-java-gate.md`，逐项检查外部调用边界、资源隔离、一致性恢复、失败可追踪可降级、发布停机不丢数据。
6. 若 contract 中存在“集成测试矩阵”，逐项核对 required/advisory/manual，确认 required 项有 `*IT.java` 与 Failsafe 报告证据。

### 4. 评分报告

`evaluator` 会输出结构化报告，包含：
- 每条标准的通过/失败状态
- 总分（0-100）
- 具体失败细节、复现步骤和修复建议
- QA Gate 状态：`PASS` / `FAIL`
- required 集成测试通过数、advisory 失败数、manual 人工确认项

### 5. 后续动作

若 QA Gate 失败：
- 提示可执行 `/build` 进入修复循环
- 展示需要处理的具体失败项

若 QA Gate 通过：
- 报告通过
- 可选执行 `doc-gardener` 做文档新鲜度检查

说明：
- `required` 集成测试门禁失败会阻塞 `passes=true`。
- `advisory` 失败不阻塞，但必须进入 QA 报告。
- `manual` 项必须列出人工确认内容。
- 是否标记 `passes=true` 以 spec/contract 落盘、单元测试、convention-check 和 required QA Gate 结果为准。
