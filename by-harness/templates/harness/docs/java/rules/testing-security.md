# 测试、安全、监控、部署与文档规则

本文件适用于测试、安全敏感代码、认证、授权、监控、指标、部署、CI、配置加固和项目文档。

## 1. 适用场景

- 新增或修改鉴权、权限、输入校验、限流、审计、敏感数据处理。
- 新增或修改单元测试、集成测试、CI、监控指标、告警、日志级别。
- 调整部署配置、灰度、回滚、生产开关、公开文档或运维文档。

## 2. 核心门禁（触发本维度必须满足）

1. **禁止明文秘密**：源码、测试、日志、配置、文档中不得硬编码密码、token、API key、签名密钥、私钥或授权值。
2. **权限来自可信上下文**：受保护操作必须有认证、授权和输入校验，禁止依赖前端传入的身份字段做授权决策。
3. **公共错误安全**：外部错误响应不得包含内部类名、SQL、堆栈、原始系统异常或第三方原始错误。
4. **核心变更有测试**：核心业务逻辑、公共 API、安全边界和异常路径变更必须补充或更新测试。
5. **生产影响可回滚**：生产影响变更必须写明发布验证、灰度、回滚、监控或人工确认方案。

## 3. 安全规则

- 外部调用使用 HTTPS 或批准的安全通道。
- SQL 使用参数化绑定，并在应用边界做输入校验。
- 敏感配置存放在批准的加密配置机制或配置中心。
- 受保护操作使用 RBAC 或项目既有授权机制。
- 敏感、破坏性操作必须有额外审计、回滚和人工确认。
- 日志中禁止输出原始认证数据、密钥、签名、授权头。

## 4. API 安全规则

- 应用边界必须校验输入。
- 外部接口使用 DTO，不暴露 Entity、Domain 内部对象或基础设施类型。
- 公共错误码和错误消息保持稳定、安全、可读。
- 默认保持向后兼容；破坏性变更必须由任务明确要求。
- 对外响应不得包含内部类名、SQL、堆栈或三方原始错误。

## 5. 测试规则

- 核心业务逻辑变更必须新增或更新测试。
- 新增单元测试时遵循项目 JUnit、Mockito 约定。
- 单元测试中 mock 外部依赖、时间、随机数、远程服务和消息组件。
- 关键持久化或跨组件流程可按项目能力补充集成测试。
- 触发真实数据库、Redis、MQ、外部 HTTP/RPC、事务、幂等、补偿或发布停机风险时，必须在 contract 的“集成测试矩阵”中声明是否需要 Testcontainers 集成测试。
- `*Test.java` 默认作为单元测试，`*IT.java` 或项目既有 `*IntegrationTest.java` 作为集成测试入口，由 `mvn verify` / Failsafe 执行。
- required 集成测试必须使用 Testcontainers 或项目批准的等价真实依赖测试设施，不能只用 Mockito 证明数据库、缓存、消息、外部服务或事务边界。
- Testcontainers 镜像版本必须固定，禁止使用 `latest`；测试数据必须自建自清理，不依赖执行顺序。
- Java 8 或老 Spring Boot 项目优先使用 `@DynamicPropertySource`、`ApplicationContextInitializer` 或项目既有测试配置注入容器地址，不强制依赖 Spring Boot 3.1+ `@ServiceConnection`。
- CI 或本地环境没有 Docker 时，required 项必须标记 FAIL 或 blocked，并写明最小复现命令与环境阻塞原因。
- 公共 API 变更覆盖正常路径、参数错误、业务失败、外部依赖失败。
- 无法运行测试时，必须写明最小建议验证命令和阻塞原因。

## 6. 监控规则

- 保持既有 Micrometer 指标命名与标签风格。
- 业务指标命名稳定、含义清晰。
- 指标标签必须控制基数，禁止默认使用 raw ID、订单号、手机号等高基数字段。
- 预期内的业务校验失败不记录为 ERROR，避免误告警。
- 改变运行行为的核心链路应具备延迟、吞吐、错误率可见性。

## 7. 部署与配置规则

- 环境特定值不写入共享默认配置，除非确认安全。
- 不提交生产密钥、生产账号、私有部署细节。
- 保持 dev、test、pre、prod 配置隔离。
- schema 和 API 变更尽量保持回滚兼容。
- 生产影响变更写明上线验证、灰度策略、回滚步骤。
- schema 变更发布前必须有兼容性和回滚演练说明。

## 8. 文档规则

- 公共 API、配置 key、部署步骤、运维行为变化时必须更新文档。
- 文档保持简洁，贴近变更行为。
- 长规范优先链接权威 spec/contract，不重复复制大段内容。
- 代码注释用于解释意图、边界和副作用，不给显而易见的语句加噪音注释。

## 9. 默认验证命令

默认构建验证：

```bash
mvn verify
```

QA Gate 验证：

```bash
python3 .harness/scripts/testcontainers_doctor.py --target-dir .
python3 .harness/scripts/qa_runner.py --target-dir . --contract <contract-file>
python3 .harness/scripts/qa_gate.py --target-dir . --result-json .harness/docs/qa/<feature>.result.json
```

建议扫描：

```bash
rg -n "@Select\\(|@Update\\(|@Insert\\(|@Delete\\(" src/main/java
rg -n "logback|ordinal\\(\\)|select \\*|resultClass|\\$\\{" pom.xml src/main/java src/main/resources
rg -n "password|secret|token|authorization|privateKey|apiKey" src/main/java src/main/resources
```

## 10. 验收与自动检查

- `convention-check` 会拦截疑似硬编码密钥或敏感日志。
- `convention-check` 会拦截 `logback` 依赖链。
- `qa_runner.py` 会解析 contract 集成测试矩阵、运行 `mvn test` / `mvn verify`、读取 Surefire/Failsafe XML，并生成 QA Gate result JSON。
- `qa_gate.py` 会根据 result JSON 阻塞 required 集成测试失败的任务通过。
- 人工验收必须确认输入校验、授权、限流、审计影响已说明。
- 人工验收必须确认测试或最小验证命令已记录。
- 人工验收必须确认生产影响、监控、发布、回滚和文档已进入 contract。
