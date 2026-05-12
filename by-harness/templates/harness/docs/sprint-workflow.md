# 冲刺工作流（Sprint Workflow）

本文详细说明 `Plan-Build-Verify-Fix-Complete` 的完整闭环。

---

## 概览

每个功能都应经过 6 个阶段的冲刺循环。该流程落实以下黄金原则：先有 spec、标准可测、先自检、契约驱动。

明确、小、可验证的 bug 可以先走 Quick Fix 分流。Quick Fix 是轻量旁路，不是跳过验证：它只省略完整 spec/contract 前置工件，仍必须自动分类、定向验证、post-diff 复核，并写入 quick close 日志。

```bash
python3 .harness/scripts/quick_fix_classifier.py --target-dir . --prompt "<bug 描述>"
```

只有 `confidence=high` 且 `recommended_mode=quick_fix` 时才可直接轻量修复；`medium` 先询问用户，`low` 回到完整冲刺循环。

## 阶段 1：Plan（规划）

**智能体（Agent）**：Planner  
**输入**：用户 1-4 句话描述  
**输出**：`.harness/docs/specs/<feature-name>.md`

Planner 会：
1. 阅读简述需求  
2. 若存在歧义先做澄清  
3. 调研现有代码模式  
4. 产出结构化 spec，至少包含：
   - 问题陈述（Problem statement）
   - 用户故事（User stories）
   - 验收标准（每条均可机器验证）
   - 组件边界（Component boundaries）
   - 数据流（Data flow）
   - 错误处理（Error handling）
   - 边界场景（至少 3 个）
   - 依赖项（Dependencies）

**阶段准入条件**：spec 已写入 `.harness/docs/specs/` 且通过用户评审。

## 阶段 2：契约协商（Contract Negotiation）

**智能体（Agents）**：Generator + Evaluator  
**输出**：`.harness/docs/contracts/<feature-name>.md`

在任何代码编写前，先完成：
1. Generator 提出“要实现什么 + 如何验证成功”  
2. Evaluator 审核，确保：
   - 标准确实可测试（非主观）
   - 范围有边界（非开放式）
   - 每条标准都有验证方法
3. 双方迭代直到达成一致  
4. 用户批准最终契约

**阶段准入条件**：Generator、Evaluator、User 三方对契约达成一致。

## 阶段 3：Build（实现）

**智能体（Agent）**：Generator  
**输入**：Spec + Contract  
**输出**：代码改动 + 冲刺报告

Generator 会：
1. 只读取 spec 与必要相关代码（控制上下文预算）
2. 在契约范围内完成一个 Sprint
3. 实现后执行自检：
   - 复读代码
   - 检查编译/构建
   - 对照验收标准
   - 运行已有测试
4. 输出简短冲刺报告（做了什么、验证了什么、待关注点）

**阶段准入条件**：Generator 提交“已完成 + 自检结果”。

## 阶段 4：Verify（验证）

**智能体（Agent）**：Evaluator  
**输入**：Contract + 源码 + 运行中的应用  
**输出**：评分报告（0-100）

Evaluator 使用 Java 工程验证策略：
1. **单元层**：读源码校验逻辑，并运行可用单元测试
2. **集成层**：读取 contract 集成测试矩阵，运行 Testcontainers / Failsafe 集成测试，覆盖数据库、缓存、消息、RPC、外部 HTTP、事务、幂等和补偿等触发点
3. **契约层**：逐条对照 contract、Java 总门禁和触发维度分片规则
4. **构建层**：检查编译、依赖、打包或项目既有质量门禁

每条验收标准都要给出结果：
- PASS：标准满足，且有证据
- FAIL：标准未满足，附失败细节、复现步骤、修复建议

**评分公式**：`分数 = (通过标准条数 / 标准总条数) * 100`  
**执行门禁**：单元测试通过、`convention-check` 无 fail，且 contract 中 required 集成测试全部通过

**阶段流转条件**：
- required QA Gate 通过：进入阶段 6（Complete）
- 单元测试、convention-check 或 required 集成测试失败：进入阶段 5（Fix）

## 阶段 5：Fix Loop（修复循环）

**智能体（Agent）**：Generator（基于 Evaluator 反馈）  
**最大迭代次数**：3

1. 将 Evaluator 失败报告回传给 Generator  
2. Generator 分析每条失败并定位根因  
3. Generator 实施修复  
4. Generator 对修复结果自检  
5. 回到阶段 4（Verify）

**若 3 轮仍失败**：
- 结束当前 feature 的修复循环
- 保持该 feature 的 `passes=false`
- 向用户汇总全部失败项
- 给出建议：a) 缩小范围 b) 拆分更小冲刺 c) 人工介入
- 继续推进下一个 feature，避免阻塞总体进度

**上下文重置建议**：如果 Generator 工作过久并出现上下文焦虑（提前收尾、重复错误），可考虑：
- 将当前进展写入文件
- 开启全新会话
- 让新会话读取 spec、contract、sprint log 继续工作

## 阶段 6：Complete（完成）

**智能体（Agent）**：Doc Gardener（自动）  
**输出**：更新后的文档

1. Doc Gardener 审计文档新鲜度：
   - 文档引用路径是否仍存在
   - 新代码是否有对应文档
   - 示例是否仍有效
2. 在 contract 文件中记录 sprint log
3. 标记任务完成
4. 产出冲刺总结：
   - 本次构建内容
   - 最终评估分数
   - 迭代次数
   - 剩余问题或技术债

若项目启用了 task-harness（存在 `.harness/task-harness/index.json`）：
- 单元测试通过、required QA Gate 通过，且 `spec_path` / `contract_path` 文件真实存在后，才可更新对应 feature 的 `passes=true`
- 同步在 `.harness/task-harness/progress/YYYY-MM/<timestamp>-<feature-id>.md` 写入该 feature 的闭环记录

## 上下文重置（Context Reset）与压缩（Compaction）的取舍

| 策略 | 适用时机 | 优点 | 缺点 |
|----------|-------------|------|------|
| **Compaction** | 常规、短冲刺 | 连续性好 | 不能彻底消除上下文焦虑 |
| **Context Reset** | 长会话、3 轮以上修复、上下文焦虑 | 干净重启、注意力恢复 | 需要高质量交接材料 |

**交接材料（重置前写入文件）**应包含：
- 当前 sprint contract 状态
- 已实现内容
- 未解决失败项
- 下一步计划
- 关键决策记录

交接材料本质上就是 spec + contract + sprint log 文件，这也是为什么它们必须落盘，而不是只存在于上下文中。
