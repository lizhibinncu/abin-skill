# abin Skills 技能仓库

这里维护面向 Codex / Claude 等 Agent 的本地技能集合。每个一级目录代表一个独立 skill，真正的执行契约以各目录下的 `SKILL.md` 为准；本 README 只负责说明当前仓库结构、适用场景、常用命令和维护方式。

## 当前内容

```text
abin-skill/
└── api-transform-process-create/  # 百应 API Transformer 数据集成流程创建与开发
    ├── SKILL.md
    ├── agents/
    └── scripts/
```

## 使用方式

- 需要创建或开发百应 API Transformer 数据集成流程时，让 Agent 使用 `api-transform-process-create`。
- 修改或排查技能行为时，先读 `api-transform-process-create/SKILL.md`，再读 `scripts/` 下的脚本；不要只按 README 推断执行细节。

## api-transform-process-create

`api-transform-process-create` 用来在百应 Planet 数据集成页面创建 API Transformer 流程，并按默认线性链路完成开发：

```text
接收数据 -> 数据转换 -> 发送数据 -> 结束
```

适用场景：

- 新建数据集成计划、空白计划、流程或 workflow。
- 通过目标客户公司 ID 精确选择客户，例如 `公司ID: 10317`。
- 配置接收 URL 后缀、数据转换脚本、发送请求地址和结束节点脚本。
- 在已有登录态的 Chrome 远程调试端口上，用脚本快速创建并保存草稿。

常用命令：

```bash
node api-transform-process-create/scripts/create-default-flow.mjs \
  --customer "10317" \
  --flow-name "流程自动化测试" \
  --screenshot "./data-integration-list.png"
```

如需只创建空白流程或调试单独开发阶段，分别使用：

```bash
node api-transform-process-create/scripts/create-process.mjs \
  --customer "10317" \
  --flow-name "流程自动化测试"

node api-transform-process-create/scripts/develop-default-flow.mjs \
  --workflow-id "28920" \
  --receive-uri "abinliuchengceshi" \
  --request-url "www.baidu.com"
```

## 维护校验

修改 `api-transform-process-create` 脚本后，至少执行：

```bash
node --check api-transform-process-create/scripts/create-default-flow.mjs
node --check api-transform-process-create/scripts/create-process.mjs
node --check api-transform-process-create/scripts/develop-default-flow.mjs
```
