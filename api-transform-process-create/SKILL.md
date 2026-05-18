---
name: api-transform-process-create
description: Create and develop a BYAI API Transformer/data-integration workflow on https://sh.planet.byai.com/data-integration/. Use when the user asks to create a data integration plan, blank plan, workflow, flow, or process, then configure editor nodes such as 接收数据, 数据转换, 数据映射, 发送数据, 数据分流, 分支, or 结束 using customer ID, workflow name, receive URL suffix, transform script, HTTP/Dubbo request config, DBUtil scripts, branch conditions, request URL, and optional end script.
---

# API Transform Process Create

## Purpose

Create a blank data-integration workflow in BYAI Planet, then optionally develop the workflow in the editor.

Also use this skill when modifying an existing workflow to match another workflow's content. In that copy-update case, preserve the target workflow identity and callback URL by default: keep the target `workflowId`, `workflowName`, `companyId`, `companyName`, and the target `API_RECEIVER.extra.uri` / `urlPrefix` unless the user explicitly asks to overwrite the receiver URL.

Creation inputs:

- Target customer value, usually a company/customer ID such as `10317`
- Workflow name, such as `流程自动化测试`

Do not require the user to provide the displayed customer name. Treat the target customer as a company ID. After typing the target customer value, select only the dropdown option whose text contains `公司ID: <target customer>`.

Development inputs:

- Receive URL suffix for the frontend-accessible callback path
- Transform script for processing incoming data
- Send/request URL for forwarding processed data, or Dubbo service config
- Optional data mapping config for named request objects such as Dubbo `req`
- Optional data dispatch config: dispatch script, branch conditions, and branch-specific node chain
- Optional end-node script; default to `return args` when no processing is needed

For workflows that include `数据分流`, `数据映射`, Dubbo sender, database queries/writes, non-default receiver params, custom HTTP headers, retry, or exception result scripts, read `references/node-patterns.md` before editing the graph.

Publishing rule: when creating a new workflow or a new default graph, save as draft unless the user explicitly asks to publish. For existing published workflows that the user explicitly asks to modify in place, the draft API may reject with `流程当前状态[PUBLISHED]不允许保存草稿`; in that case use the publish/update API only for the requested in-place update.

## Architecture Mental Model

Build workflows around the platform's three runtime pipelines:

- `接收数据` is the HTTP server pipeline entry. Use it for receiving the request, loading the interface config, authentication/signature checks, parameter decrypt, parameter validation, and storing request context for later nodes.
- `数据转换` is the business transform stage. Use it for constants, variable extraction, script-based normalization, DB/Redis lookups or writes, and reshaping data between nodes. Keep it focused on data logic rather than transport concerns.
- `发送数据` is the outbound webhook/RPC pipeline. Use it for loading sender config, optional pre-send data transformation that belongs to the request, adding authentication information, parameter encryption, timeout, retry, rate-limit-related settings, and then sending HTTP/Dubbo requests.
- `结束` is the final response stage. Use it to unwrap sender responses, map platform errors to customer-facing responses, or pass through `args`.

Node execution is ordered by graph edges. Preserve context intentionally with `$global` or returned maps, keep each node's output shaped for the next node, and avoid hiding cross-node dependencies in unrelated scripts.

## Quick Start

Prefer the bundled scripts when Chrome is already running with a remote debugging port and the user is logged in.

Fastest full default flow, with only the final list screenshot:

```bash
node ~/.codex/skills/api-transform-process-create/scripts/create-default-flow.mjs \
  --customer "10317" \
  --flow-name "流程自动化测试" \
  --screenshot "./data-integration-list.png"
```

For default workflows, prefer `create-default-flow.mjs` over running separate create/develop scripts. Its default fast path creates a blank workflow by API, immediately writes the default graph by the draft API so the workflow becomes visible as `DRAFT`, returns directly to `https://sh.planet.byai.com/data-integration/`, and captures only the final list screenshot. It prints `Elapsed ms`; keep the happy path around 5 seconds when the list page and login session are already warm. Use `--ui-create` only as a fallback when API creation fails or the user specifically wants the visible `新建计划 -> 空白计划` path exercised.

The editor's `自动布局` toolbar button is a frontend-only action (`#auto-layout`) and does not call a backend layout API. For default linear workflows, the bundled scripts write auto-layout-style node coordinates directly into the draft graph so the saved canvas is readable without opening the editor just to click the layout button.

If a workflow contains `DATA_DISPATCH` or `DISPATCH_BRANCH`, do not click `自动布局`. It can make branch edges cross or curve awkwardly. Use manual branch-lane coordinates from `references/node-patterns.md`: keep the main spine centered, put branch nodes in one horizontal row, put each branch's child nodes under that branch, and put `结束` below the deepest branch.

Create a blank workflow:

```bash
node ~/.codex/skills/api-transform-process-create/scripts/create-process.mjs \
  --customer "10317" \
  --flow-name "流程自动化测试"
```

Develop the current editor page into a complete default workflow, save draft, return to the list, and screenshot:

```bash
node ~/.codex/skills/api-transform-process-create/scripts/develop-default-flow.mjs \
  --workflow-id "28920" \
  --receive-uri "abinliuchengceshi" \
  --request-url "www.baidu.com" \
  --screenshot "./data-integration-list.png"
```

Copy one existing workflow's graph into another existing workflow while preserving the target receiver URL:

```bash
node ~/.codex/skills/api-transform-process-create/scripts/copy-workflow-graph.mjs \
  --source-workflow-id "23820" \
  --target-workflow-id "27020" \
  --screenshot "./data-integration-list.png"
```

For a full default flow, use `create-default-flow.mjs`. Use the separate `create-process.mjs` and `develop-default-flow.mjs` scripts only when debugging a single stage or when the user explicitly wants to stop on the editor page.

## Create Workflow

1. Confirm the user has provided `目标客户` and `流程名称`; ask only for missing values.
2. Navigate to `https://sh.planet.byai.com/data-integration/`.
3. Click `新建计划`, then click `空白计划`.
4. In `新建流程`, type the target customer value into `目标客户`.
5. Select the visible dropdown option whose company ID exactly matches the target customer value, such as `公司ID: 10317`. Do not select a different company ID just because it is the first visible option.
6. Type the workflow name into `流程名称`.
7. Click `确定`.
8. Wait until the modal closes and the editor page opens, usually a URL like `/data-integration/workflow/create/<id>`.
9. For blank-only creation, capture a screenshot if requested. For full default creation, do not screenshot the editor page.

## Develop Workflow

After the editor page opens, treat this as the real development stage.

Fast path for a newly created default workflow: use `scripts/create-default-flow.mjs`. It keeps one CDP session, skips editor screenshots, looks up the exact company ID, calls `/api/transformers/apiworkflow/init` to create the blank workflow, calls `/api/transformers/apiworkflow/draft` to write the default graph and move the workflow from `INIT` to `DRAFT`, returns to the list page, and screenshots only the list. This is the default behavior for new workflows unless the user explicitly asks to publish.

The draft graph positions should keep the simple chain visually separated, matching the editor's `自动布局` result:

- `接收数据`: `{ x: 19910, y: 19518 }`
- `数据转换`: `{ x: 19910, y: 19754 }`
- `发送数据`: `{ x: 19910, y: 19936 }`
- `结束`: `{ x: 19910, y: 20172 }`

Fast path for an already open editor: use `scripts/develop-default-flow.mjs` for simple linear workflows. It writes the graph through `/bygw/api/transformers/apiworkflow/draft`, then verifies in the editor UI:

- `接收数据 -> 数据转换 -> 发送数据 -> 结束`
- green `检查`
- `保存草稿成功`
- returned list row visible

Ask only for missing non-default values:

- `前端访问后缀 URL`: required for `接收数据`.
- `数据转换脚本`: required unless the user says no transformation; then use `return args`.
- `请求地址`: required for `发送数据`.
- `结束节点脚本`: optional; default to `return args`.

Use these defaults without asking:

- `接收参数类型`: `application/json`
- `发送参数类型`: `application/json`
- `发送数据` timeout: `5秒`
- `结束` node pass-through script: `return args`

Complex development rules:

- For a simple third-party HTTP callback, use `接收数据 -> 数据转换 -> 发送数据(HTTP) -> 结束`.
- For a database lookup response, use `接收数据 -> 数据转换(DBUtil.selectObj/selectOne) -> 结束`.
- For a database write side effect, usually put `DBUtil.insert/update` in a `数据转换` node after the relevant sender or branch.
- Put receive-side auth/signature validation, decrypt, and required-field checks in `接收数据` when the platform fields/scripts can express them. Use `数据转换` for these only when the receive node cannot represent the required logic cleanly.
- Put sender-side auth headers/signatures, request encryption, timeout, retry, and rate-limit-related settings in `发送数据`. Use the upstream `数据转换` only to prepare the business payload or URI/header variables that the sender consumes.
- For Dubbo calls, set `发送数据.extra.rpcProtocol` to `dubbo`, configure `dubboRegistry`, `serviceName`, `serviceInterface`, `serviceMethod`, and `serviceParameterTypes`; use `数据映射` before the sender when the Dubbo method expects a named object such as `req`.
- For HTTP sender calls, set `rpcProtocol: "http"`, `path`, `method`, `mediaType`, `paramType`, `timeoutSecond`, `httpHeaderList`, and `httpHeaderTree`; use `autoRetry` and `retryNum` only when explicitly needed.
- For `数据分流`, `dispatchParamScript` must return a map whose values used by branch rules are strings, such as `return ["send": args.send + ""]`. Create one `DISPATCH_BRANCH` node per rule and keep each branch node's `conditions` in sync with `DATA_DISPATCH.extra.dispatchJudgeList`.
- For receiver typed params, keep `paramCheckList` and `paramTree` aligned. Param check scripts may set `$global` values for later nodes.

Editor sequence:

1. Configure `接收数据`.
   - Open the `接收数据` node.
   - Fill the frontend-accessible suffix URL into the request URL suffix/input.
   - Keep `接收参数类型` as `application/json`.
   - Click `确定` to exit the node drawer.
2. Add and configure `数据转换`.
   - Add the `数据转换` node from the left `基础节点` list if it is not already on the canvas.
   - Connect `接收数据 -> 数据转换`.
   - Open `数据转换`, click `转换方法` / `编辑脚本`.
   - In `编辑脚本`, enter the transform script for processing incoming data.
   - Click script `确定`, then click the `数据转换` drawer `确定`.
3. Add and configure `发送数据`.
   - Add the `发送数据` node if it is not already on the canvas.
   - Connect `数据转换 -> 发送数据`.
   - Open `发送数据`.
   - Fill `请求地址`.
   - Keep protocol `HTTP`, method `POST` unless the user specifies otherwise.
   - Keep `发送参数类型` as `application/json`.
   - Set timeout to `5秒`.
   - Click `确定`.
4. Add and configure optional complex nodes when requested.
   - `数据映射`: set `mappingType: MANUAL`, `systemType: CUSTOM`, and `fieldMappingList` entries from source paths to target paths.
   - `数据分流`: configure `dispatchParamScript`, branch rules, and one visible `DISPATCH_BRANCH` per rule.
   - Dubbo `发送数据`: choose `Dubbo`, then fill registry, application/service name, interface, method, parameter names/types, and timeout.
   - DB logic: put `DBUtil` read/write code in a `数据转换` or result/exception script as appropriate.
5. Configure `结束`.
   - Connect `发送数据 -> 结束`.
   - Open `结束`.
   - Click `发送数据格式` / `编辑脚本`.
   - Enter the end-node script, usually `return args`.
   - Click script `确定`, then click the `结束` drawer `确定`.
6. Verify the canvas shows the expected chain:
   - Simple chain: `接收数据 -> 数据转换 -> 发送数据 -> 结束`
   - Dispatch graph: main spine plus horizontal branch row and branch lanes; do not click `自动布局`.
   - The `检查` indicator should be green when all required configuration is complete.
7. Click `保存草稿` after the flow is configured, unless the user explicitly asks to publish or only inspect.
8. Wait for the toast `保存草稿成功`.
9. Return to `https://sh.planet.byai.com/data-integration/`. Prefer direct navigation for speed after the draft API save; use the editor's top-left `<` only when the user specifically asks to exercise the visible UI back action.
10. Wait for the created row to appear in the list, then capture a screenshot and report the final list URL.

## Copy Or Update From Existing Workflow

When the user asks to make workflow `<target>` the same as workflow `<source>`, prefer `scripts/copy-workflow-graph.mjs`.

Default copy behavior:

- Load both workflow details from `/api/transformers/apiworkflow/detail`.
- Build the update payload with the target workflow's `workflowName`, `companyId`, `companyName`, and `workflowId`.
- Copy the source `graph` into the target.
- Preserve the target receiver URL by default. For each `API_RECEIVER` node, keep the target node's `extra.uri` and `extra.urlPrefix`; do not copy the source callback suffix unless the user explicitly asks for that and accepts URL uniqueness risk.
- Save with `/api/transformers/apiworkflow/draft` first for draft/created targets.
- If the target is already `PUBLISHED` and the draft API rejects because published workflows cannot save drafts, use `/api/transformers/apiworkflow/update` for the requested in-place update.
- Verify the target detail after saving. The target graph should equal the source graph after applying the expected receiver URL preservation.

If the update API rejects with a duplicate receiver URL message, re-check that the target receiver URL was preserved. The platform requires receiver callback paths to be unique across workflows.

## Node Purposes

- `接收数据`: Exposes the frontend callback/input endpoint. Configure the URL suffix, incoming content type, receive-side authentication, decrypt, parameter validation, and context capture.
- `数据转换`: Runs business data logic on incoming `args`: constants, variable extraction, script transforms, DB/Redis reads/writes, and payload reshaping.
- `数据映射`: Maps input paths into structured output paths, commonly before Dubbo senders.
- `数据分流`: Branches processed data into multiple paths when conditional routing is needed. Skip it for a simple linear flow.
- `数据分流分支`: Represents one visible branch condition under `数据分流`; connect branch nodes to branch-specific child nodes or directly to `结束`.
- `发送数据`: Runs the outbound request pipeline for HTTP or Dubbo: sender config, auth/header additions, encryption, timeout/retry/limit settings, and actual request dispatch.
- `结束`: Processes or wraps the response from `发送数据`. Use `return args` for no extra handling.

## Bundled References

- `references/node-patterns.md`: graph JSON structures and examples for receiver params, transform scripts, DBUtil, data mapping, HTTP sender, Dubbo sender, data dispatch, branch nodes, result scripts, and manual branch layout.

## Browser Notes

- This is a live site action. If the user explicitly asked to create the flow, the final `确定` click is part of the requested task.
- Preserve the user's login/session. Prefer an already logged-in Chrome instance, the Browser plugin, or the script's `--port` connection to an existing Chrome debugging session.
- If the script cannot connect to Chrome, ask the user to open Chrome with remote debugging or use the available browser automation tool for the same visible steps.
- If the site returns no exact `公司ID: <target customer>` option after typing the target customer value, clear and retry once. If there is still no exact match, stop and report that no selectable customer appeared.
- If the editor opens successfully, do not keep re-checking list rows; the editor URL and visible workflow name are sufficient confirmation.
- For editor development, rely on visible node drawer labels and the final green `检查` state. If a click opens a script editor, close it with its own `确定` before confirming the node drawer.
- To be fast and stable, prefer the API `init -> draft` flow for default linear workflows. `init` alone creates an `INIT` workflow, and the list page intentionally excludes `INIT`; always call `draft` after `init` before waiting for the row. If API creation fails, retry with `--ui-create` and then write the graph by draft API.
