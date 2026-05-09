# 冲刺契约：{{FEATURE_NAME}}

## 元信息（Meta）

- **规格文件（Spec）**：`.harness/docs/specs/{{FEATURE_NAME}}.md`
- **创建时间（Created）**：{{DATE}}
- **状态（Status）**：draft
- **最大迭代次数（Max Iterations）**：3
- **执行门禁（Execution Gate）**：单元测试通过、`convention-check` 无 fail，且 required 集成测试门禁通过

## 规范引用（Norm References）

本节必须从 spec 派生，不能只写“已阅读”。

| 规范文件 | 是否适用 | 适用/不适用原因 | 派生验收项 |
|---|---|---|---|
| `.harness/docs/java-dev-conventions.md` | 是/否 | Java 入口索引 | |
| `.harness/docs/java/rules/00-core.md` | 是/否 | | |
| `.harness/docs/java/rules/java-ddd.md` | 是/否 | | |
| `.harness/docs/java/rules/dubbo-api.md` | 是/否 | | |
| `.harness/docs/java/rules/logging-error.md` | 是/否 | | |
| `.harness/docs/java/rules/persistence-infra.md` | 是/否 | | |
| `.harness/docs/java/rules/testing-security.md` | 是/否 | | |
| `.harness/docs/java/rules/distributed-java-gate.md` | 未触发/触发 | | |

## 范围（Scope）

### 范围内（In Scope）

-

### 范围外（Out of Scope）

-

### 最小实体与成本门禁

- [ ] 已优先复用既有实体、表、DTO、Service、配置、扩展点和兼容入口
- [ ] 如无必要，未新增实体、表、DTO、Service、配置项、新层级或框架胶水
- [ ] 若确需新增实体/表/DTO/Service/配置项，已说明必要性、被否决的复用方案和兼容性
- [ ] 历史项目小改动已按最小成本实施，无无关重构、扩表、迁移或跨模块改造
- [ ] 新增成本、迁移成本、回滚影响和人工确认项已进入验收标准

## 验收标准（Acceptance Criteria）

每条标准都必须可验证；涉及真实数据库、缓存、消息、外部 HTTP/RPC、事务、幂等、补偿或发布停机风险时，必须在“集成测试矩阵”中补充 Testcontainers 验证证据。

| # | 标准（Criterion） | 验证方法（Verification Method） | 状态（Status） |
|---|-----------|-------------------|--------|
| 1 | | | [ ] |
| 2 | | | [ ] |
| 3 | | | [ ] |
| 4 | | | [ ] |
| 5 | | | [ ] |

### 验证方法说明（Verification Methods）

- **unit**：阅读代码并验证逻辑
- **build**：编译/构建成功
- **integration**：通过 Testcontainers 或项目既有集成测试运行真实依赖链路
- **manual**：需要用户手动验证

## 集成测试矩阵（Integration Test Matrix）

仅在验收项触发真实依赖时填写。没有触发时保留表格并写“无”。门禁取值：

- `required`：失败则禁止 `passes=true`
- `advisory`：失败进入 QA 报告，但不阻塞任务通过
- `manual`：机器无法完整验证，必须在 QA 报告中列人工确认项

| ID | 验收项 | 触发依赖 | Testcontainers | 测试类 | 核心断言 | 异常场景 | 门禁 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| IT-01 | 无 | 无 | 无 | 无 | 无 | 无 | advisory |

### Java 总门禁（若适用，每次 Java 修改必须满足）

- [ ] 先契约后实现：spec/contract 已包含 Java 入口、触发分片、门禁清单和验收方式
- [ ] 先本地后通用：已查看同层既有实现，并优先复用已有工具、异常、响应包装、转换器、配置、常量、枚举和命名
- [ ] 边界不被突破：入口、Application、Domain、Infrastructure 的依赖方向正确
- [ ] 风险显式落地：公共 API、SQL、缓存、消息、事务、配置、安全、发布、回滚影响已进入验收项
- [ ] 验证可追溯：已运行可用测试和 `convention-check`，fail 已修复，warn 已修复或解释

### Java 维度核心门禁（按触发维度勾选）

#### 通用工程（每次 Java 修改）

- [ ] 最小安全变更，不无依据扩范围
- [ ] 公共契约保持兼容；破坏性变更由任务明确要求
- [ ] 不重复造工具类、异常类、转换器、响应包装或框架胶水；业务状态、任务类型、动作类型、错误码、配置 key、阈值不散落魔法值
- [ ] 新增/修改方法有中文注释，说明用途、参数、返回值和副作用
- [ ] 交付摘要记录读取分片、验证命令和剩余风险

#### 分层与 DDD

- [ ] Controller / Provider / Job 只依赖应用服务接口，不注入 `Impl`
- [ ] `XxxAppService` 是接口，`XxxAppServiceImpl` 实现对应接口
- [ ] Domain 不依赖 Spring、MyBatis、Redis、MQ、HTTP Client 或数据库 Entity
- [ ] Application 不直接操作 Mapper，通过 Repository/Adapter 抽象访问
- [ ] MapStruct 配置 `unmappedTargetPolicy = ReportingPolicy.ERROR`

#### Dubbo 与公共 API

- [ ] 公共 client/api service 方法统一返回 `ApiResponse<T>`
- [ ] Public DTO 实现 `Serializable` 并声明 `serialVersionUID`
- [ ] 公共枚举使用 `name()` 或稳定 code，未使用 `ordinal()`
- [ ] 公共 API 未暴露 Domain、Entity、DO、Mapper、Infrastructure 内部类型
- [ ] 非幂等核心写接口明确 `retries = 0` 或记录既有重试与幂等策略

#### 日志与异常

- [ ] Web/Dubbo/MQ/异步入口生成或传递 TraceId，并在结束时清理 MDC
- [ ] 日志敏感字段已脱敏，无 token、密码、密钥、签名、授权头等敏感值
- [ ] ERROR 日志包含异常堆栈和业务上下文
- [ ] 外部错误响应未暴露系统异常、SQL、堆栈或第三方原始错误
- [ ] 业务异常使用项目统一异常和错误码

#### 持久化与基础设施

- [ ] MyBatis SQL 写在 XML Mapper，未使用注解内联 SQL
- [ ] SQL 未使用 `select *`、`${}`、`resultClass`；统计行数使用 `count(*)`
- [ ] 金额为 Java `BigDecimal` 和数据库 `DECIMAL(18,3)`，更新维护 `update_time`
- [ ] 分页有稳定排序；count 为 0 时不继续查明细
- [ ] Redis key 有命名空间，业务缓存有 TTL；锁有超时和持有者校验释放

#### 测试安全运维

- [ ] 无硬编码密码、token、API key、私钥、签名密钥或授权值
- [ ] 受保护操作有鉴权、输入校验和必要的限流/审计
- [ ] 核心业务逻辑和公共 API 变更覆盖正常/异常路径测试
- [ ] 触发真实依赖的验收项已进入集成测试矩阵，并明确 required/advisory/manual
- [ ] 监控指标标签基数受控，不使用 raw ID 作为高基数 label
- [ ] 生产影响变更写明发布验证、灰度、回滚或人工确认方案

#### 分布式 Java 门禁（所有 Java 改动必须声明）

- [ ] 已声明未触发并说明理由，或声明触发并列出触发条款、证据和人工确认项
- [ ] 外部调用有超时、重试上限、退避策略和幂等前提
- [ ] 线程池、队列、锁有业务命名、容量/超时限制和拒绝/失败策略
- [ ] 跨服务一致性有事务边界、补偿路径、终止条件和人工接管方案
- [ ] MQ/异步/缓存/停机可观测、可重放或可降级，并能处理在途任务

## 冲刺日志（Sprint Log）

| 迭代轮次 | Generator 输出 | Evaluator 评分 | 问题 |
|-----------|-----------------|-----------------|--------|
| | | | |

## 签署确认（Sign-off）

- **Generator**：[ ] 同意标准与范围
- **Evaluator**：[ ] 同意验证方式
- **User**：[ ] 批准范围与标准
