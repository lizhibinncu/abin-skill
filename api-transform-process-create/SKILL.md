---
name: api-transform-process-create
description: Create and develop a BYAI API Transformer/data-integration workflow on https://sh.planet.byai.com/data-integration/. Use when the user asks to create a data integration plan, blank plan, workflow, flow, or process, then configure editor nodes such as 接收数据, 数据转换, 发送数据, 数据分流, or 结束 using customer ID, workflow name, receive URL suffix, transform script, request URL, and optional end script.
---

# API Transform Process Create

## Purpose

Create a blank data-integration workflow in BYAI Planet, then optionally develop the workflow in the editor.

Creation inputs:

- Target customer value, usually a company/customer ID such as `10317`
- Workflow name, such as `流程自动化测试`

Do not require the user to provide the displayed customer name. Treat the target customer as a company ID. After typing the target customer value, select only the dropdown option whose text contains `公司ID: <target customer>`.

Development inputs:

- Receive URL suffix for the frontend-accessible callback path
- Transform script for processing incoming data
- Send/request URL for forwarding processed data
- Optional end-node script; default to `return args` when no processing is needed

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

Fast path for a newly created default workflow: use `scripts/create-default-flow.mjs`. It keeps one CDP session, skips editor screenshots, looks up the exact company ID, calls `/api/transformers/apiworkflow/init` to create the blank workflow, calls `/api/transformers/apiworkflow/draft` to write the default graph and move the workflow from `INIT` to `DRAFT`, returns to the list page, and screenshots only the list.

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
4. Configure `结束`.
   - Connect `发送数据 -> 结束`.
   - Open `结束`.
   - Click `发送数据格式` / `编辑脚本`.
   - Enter the end-node script, usually `return args`.
   - Click script `确定`, then click the `结束` drawer `确定`.
5. Verify the canvas shows the chain:
   - `接收数据 -> 数据转换 -> 发送数据 -> 结束`
   - The `检查` indicator should be green when all required configuration is complete.
6. Click `保存草稿` after the flow is configured, unless the user explicitly asks to publish or only inspect.
7. Wait for the toast `保存草稿成功`.
8. Return to `https://sh.planet.byai.com/data-integration/`. Prefer direct navigation for speed after the draft API save; use the editor's top-left `<` only when the user specifically asks to exercise the visible UI back action.
9. Wait for the created row to appear in the list, then capture a screenshot and report the final list URL.

## Node Purposes

- `接收数据`: Exposes the frontend callback/input endpoint. Configure the URL suffix and incoming content type.
- `数据转换`: Runs custom script logic to process incoming `args`.
- `数据分流`: Branches processed data into multiple paths when conditional routing is needed. Skip it for a simple linear flow.
- `发送数据`: Sends processed data to the configured request address.
- `结束`: Processes or wraps the response from `发送数据`. Use `return args` for no extra handling.

## Browser Notes

- This is a live site action. If the user explicitly asked to create the flow, the final `确定` click is part of the requested task.
- Preserve the user's login/session. Prefer an already logged-in Chrome instance, the Browser plugin, or the script's `--port` connection to an existing Chrome debugging session.
- If the script cannot connect to Chrome, ask the user to open Chrome with remote debugging or use the available browser automation tool for the same visible steps.
- If the site returns no exact `公司ID: <target customer>` option after typing the target customer value, clear and retry once. If there is still no exact match, stop and report that no selectable customer appeared.
- If the editor opens successfully, do not keep re-checking list rows; the editor URL and visible workflow name are sufficient confirmation.
- For editor development, rely on visible node drawer labels and the final green `检查` state. If a click opens a script editor, close it with its own `确定` before confirming the node drawer.
- To be fast and stable, prefer the API `init -> draft` flow for default linear workflows. `init` alone creates an `INIT` workflow, and the list page intentionally excludes `INIT`; always call `draft` after `init` before waiting for the row. If API creation fails, retry with `--ui-create` and then write the graph by draft API.
