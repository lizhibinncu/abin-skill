#!/usr/bin/env node

import fs from "node:fs/promises";
import path from "node:path";

const DEFAULT_URL = "https://sh.planet.byai.com/data-integration/";

function parseArgs(argv) {
  const args = {
    customer: "",
    companyName: "",
    flowName: "",
    port: "9222",
    receiveUri: "abinliuchengceshi",
    transformScript: "return args",
    requestUrl: "www.baidu.com",
    endScript: "return args",
    screenshot: path.resolve(process.cwd(), "api-transform-process-list.png"),
    uiCreate: false,
  };

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    const next = argv[i + 1];
    if (arg === "--customer" || arg === "--target-customer") {
      args.customer = next || "";
      i += 1;
    } else if (arg === "--company-name") {
      args.companyName = next || "";
      i += 1;
    } else if (arg === "--flow-name" || arg === "--process-name") {
      args.flowName = next || "";
      i += 1;
    } else if (arg === "--port") {
      args.port = next || "";
      i += 1;
    } else if (arg === "--receive-uri") {
      args.receiveUri = next || "";
      i += 1;
    } else if (arg === "--transform-script") {
      args.transformScript = next || "";
      i += 1;
    } else if (arg === "--request-url") {
      args.requestUrl = next || "";
      i += 1;
    } else if (arg === "--end-script") {
      args.endScript = next || "";
      i += 1;
    } else if (arg === "--screenshot") {
      args.screenshot = path.resolve(process.cwd(), next || "");
      i += 1;
    } else if (arg === "--ui-create") {
      args.uiCreate = true;
    } else if (arg === "--api-create") {
      args.uiCreate = false;
    } else if (arg === "--help" || arg === "-h") {
      usage(0);
    } else {
      throw new Error(`Unknown argument: ${arg}`);
    }
  }

  if (!args.customer) throw new Error("Missing --customer");
  if (!args.flowName) throw new Error("Missing --flow-name");
  if (!args.port) throw new Error("Missing --port");
  if (!args.receiveUri) throw new Error("Missing --receive-uri");
  if (!args.transformScript) throw new Error("Missing --transform-script");
  if (!args.requestUrl) throw new Error("Missing --request-url");
  if (!args.endScript) throw new Error("Missing --end-script");
  return args;
}

function usage(code) {
  console.log(`Usage:
  node create-default-flow.mjs --customer "10317" --flow-name "流程自动化测试"

Options:
  --customer, --target-customer   Target customer/company ID
  --company-name                  Optional company name; skips company lookup when provided
  --flow-name, --process-name     Workflow/process name
  --receive-uri                   Receive URL suffix, default abinliuchengceshi
  --transform-script              Data transform script, default "return args"
  --request-url                   Sender request URL, default www.baidu.com
  --end-script                    End node script, default "return args"
  --screenshot                    Final list screenshot path
  --port                          Chrome remote debugging port, default 9222
  --api-create                    Create by API; this is the default fast path
  --ui-create                     Use the visible new-plan modal as a fallback`);
  process.exit(code);
}

class CdpClient {
  constructor(webSocketDebuggerUrl) {
    this.ws = new WebSocket(webSocketDebuggerUrl);
    this.nextId = 0;
    this.pending = new Map();
    this.ws.onmessage = (event) => {
      const message = JSON.parse(event.data);
      if (!message.id || !this.pending.has(message.id)) return;
      const request = this.pending.get(message.id);
      this.pending.delete(message.id);
      if (message.error) request.reject(new Error(`${request.method}: ${JSON.stringify(message.error)}`));
      else request.resolve(message.result);
    };
  }

  async open() {
    if (this.ws.readyState === WebSocket.OPEN) return;
    await new Promise((resolve, reject) => {
      this.ws.onopen = resolve;
      this.ws.onerror = reject;
    });
  }

  send(method, params = {}) {
    return new Promise((resolve, reject) => {
      const id = (this.nextId += 1);
      this.pending.set(id, { resolve, reject, method });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }

  close() {
    this.ws.close();
  }
}

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function getTarget(port) {
  const base = `http://127.0.0.1:${port}`;
  let targets;
  try {
    targets = await fetch(`${base}/json/list`).then((response) => response.json());
  } catch {
    throw new Error(`Cannot connect to Chrome on port ${port}`);
  }

  const existing =
    targets.find((target) => target.type === "page" && target.url?.includes("sh.planet.byai.com")) ||
    targets.find((target) => target.type === "page");
  if (existing) return existing;
  return fetch(`${base}/json/new?${encodeURIComponent(DEFAULT_URL)}`, { method: "PUT" }).then((response) =>
    response.json()
  );
}

async function evaluate(client, expression) {
  const result = await client.send("Runtime.evaluate", {
    expression,
    returnByValue: true,
    awaitPromise: true,
  });
  if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
  return result.result.value;
}

async function waitFor(client, expression, label, timeoutMs = 8000) {
  const started = Date.now();
  let lastValue;
  while (Date.now() - started < timeoutMs) {
    try {
      lastValue = await evaluate(client, expression);
      if (lastValue) return lastValue;
    } catch (error) {
      lastValue = error.message;
    }
    await delay(80);
  }
  throw new Error(`Timed out waiting for ${label}. Last value: ${JSON.stringify(lastValue)}`);
}

async function clickRect(client, rect) {
  const x = rect.x + rect.width / 2;
  const y = rect.y + rect.height / 2;
  await client.send("Input.dispatchMouseEvent", { type: "mouseMoved", x, y });
  await client.send("Input.dispatchMouseEvent", { type: "mousePressed", x, y, button: "left", clickCount: 1 });
  await client.send("Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button: "left", clickCount: 1 });
}

async function replaceFocusedText(client, text) {
  await client.send("Input.dispatchKeyEvent", {
    type: "keyDown",
    key: "a",
    code: "KeyA",
    modifiers: 4,
    windowsVirtualKeyCode: 65,
    nativeVirtualKeyCode: 65,
  });
  await client.send("Input.dispatchKeyEvent", {
    type: "keyUp",
    key: "a",
    code: "KeyA",
    modifiers: 4,
    windowsVirtualKeyCode: 65,
    nativeVirtualKeyCode: 65,
  });
  await client.send("Input.dispatchKeyEvent", {
    type: "keyDown",
    key: "Backspace",
    code: "Backspace",
    windowsVirtualKeyCode: 8,
    nativeVirtualKeyCode: 8,
  });
  await client.send("Input.dispatchKeyEvent", {
    type: "keyUp",
    key: "Backspace",
    code: "Backspace",
    windowsVirtualKeyCode: 8,
    nativeVirtualKeyCode: 8,
  });
  await delay(50);
  await client.send("Input.insertText", { text });
}

function buildDefaultGraph(detail, args) {
  const resultNode =
    detail?.graph?.nodes?.find((node) => node.nodeType === "API_RESULT") || {
      id: "defaultResult01",
      label: "结束",
      nodeType: "API_RESULT",
      frontParams: { branches: ["默认"], position: { x: 19910, y: 20124 } },
    };
  const resultId = resultNode.id;

  return {
    edges: [
      { id: "edge-receive-convert", index: 0, source: "00000000", target: "defaultConvert01" },
      { id: "edge-convert-send", index: 0, source: "defaultConvert01", target: "defaultSender01" },
      { id: "edge-send-result", index: 0, source: "defaultSender01", target: resultId },
    ],
    nodes: [
      {
        id: "00000000",
        index: 0,
        label: "接收数据",
        name: "",
        nodeType: "API_RECEIVER",
        frontParams: { branches: ["默认"], position: { x: 19910, y: 19518 } },
        extra: {
          name: "接收数据-默认",
          urlPrefix: "https://open-tcs.byai.com/api/transformers/",
          uri: args.receiveUri,
          method: "POST",
          mediaType: "application/json",
          paramType: 1,
          paramCheckList: [],
          paramTree: [],
        },
      },
      {
        id: "defaultConvert01",
        index: 0,
        label: "数据转换",
        name: "",
        nodeType: "DATA_CONVERT",
        frontParams: { branches: ["默认"], position: { x: 19910, y: 19720 } },
        extra: { name: "数据转换-默认", convertScript: args.transformScript },
      },
      {
        id: "defaultSender01",
        index: 0,
        label: "发送数据",
        name: "",
        nodeType: "API_SENDER",
        frontParams: { branches: ["默认"], position: { x: 19910, y: 19922 } },
        extra: {
          name: "发送数据-默认",
          rpcProtocol: "http",
          method: "POST",
          path: args.requestUrl,
          mediaType: "application/json",
          paramType: 1,
          timeoutSecond: 5,
          httpHeaderList: [],
          httpHeaderTree: [],
        },
      },
      {
        id: resultId,
        index: 0,
        label: "结束",
        name: "",
        nodeType: "API_RESULT",
        frontParams: resultNode.frontParams || { branches: ["默认"], position: { x: 19910, y: 20124 } },
        extra: { name: "结束-默认", apiResultScript: args.endScript },
      },
    ],
  };
}

function buildInitialGraph() {
  const resultId = `defaultResult${Math.random().toString(36).slice(2, 10)}`;
  return {
    edges: [],
    nodes: [
      {
        id: "00000000",
        index: 0,
        label: "接收数据",
        name: "",
        nodeType: "API_RECEIVER",
        frontParams: { branches: ["默认"], position: { x: 19910, y: 19518 } },
        extra: {},
      },
      {
        id: resultId,
        index: 0,
        label: "结束",
        name: "",
        nodeType: "API_RESULT",
        frontParams: { branches: ["默认"], position: { x: 19910, y: 20018 } },
        extra: {},
      },
    ],
  };
}

async function installPageHelpers(client) {
  await evaluate(
    client,
    `(() => {
      window.__apiTransformFast = {
        visible(el) {
          if (!el) return false;
          const rect = el.getBoundingClientRect();
          const style = getComputedStyle(el);
          return style.display !== 'none' &&
            style.visibility !== 'hidden' &&
            style.opacity !== '0' &&
            rect.width > 0 &&
            rect.height > 0 &&
            rect.bottom > 0 &&
            rect.right > 0;
        },
        rect(el) {
          const rect = el.getBoundingClientRect();
          return {
            x: rect.x,
            y: rect.y,
            width: rect.width,
            height: rect.height,
            text: (el.innerText || el.textContent || '').trim()
          };
        },
        newPlanButton() {
          const el = [...document.querySelectorAll('button')]
            .find((item) => this.visible(item) && (item.innerText || '').includes('新建计划'));
          return el ? this.rect(el) : null;
        },
        blankPlanItem() {
          const el = [...document.querySelectorAll('.by-data-integration-ant-dropdown-menu-item, [role="menuitem"], li')]
            .find((item) => this.visible(item) && (item.innerText || '').includes('空白计划'));
          return el ? this.rect(el) : null;
        },
        modal() {
          return [...document.querySelectorAll('.by-data-integration-ant-modal-content, [role="dialog"]')]
            .find((item) => this.visible(item));
        },
        modalText() {
          const modal = this.modal();
          return modal ? modal.innerText : '';
        },
        targetInput() {
          const modal = this.modal();
          if (!modal) return null;
          const input = [...modal.querySelectorAll('input[type="search"]')].find((item) => this.visible(item));
          return input ? this.rect(input) : null;
        },
        flowInput() {
          const modal = this.modal();
          if (!modal) return null;
          const input = [...modal.querySelectorAll('input[placeholder="请输入流程名称"], input[type="text"]')]
            .find((item) => this.visible(item) && item.placeholder !== '');
          return input ? this.rect(input) : null;
        },
        customerOption(customerValue) {
          const expected = '公司ID:' + String(customerValue).trim();
          const dropdowns = [...document.querySelectorAll('.by-data-integration-ant-select-dropdown')]
            .filter((item) => this.visible(item) && !String(item.className).includes('hidden'));
          for (const dropdown of dropdowns) {
            for (const item of dropdown.querySelectorAll('.by-data-integration-ant-select-item-option')) {
              const text = (item.innerText || item.textContent || '').trim();
              if (this.visible(item) && text.replace(/\\s/g, '').includes(expected)) return this.rect(item);
            }
          }
          return null;
        },
        confirmButton() {
          const modal = this.modal();
          if (!modal) return null;
          const button = [...modal.querySelectorAll('button')]
            .find((item) => this.visible(item) && (item.innerText || '').replace(/\\s/g, '') === '确定');
          return button ? this.rect(button) : null;
        }
      };
    })()`
  );
}

async function createBlankWorkflow(client, args) {
  const onList = await evaluate(
    client,
    "location.href.startsWith('https://sh.planet.byai.com/data-integration/') && !location.href.includes('/workflow/') && document.body?.innerText.includes('新建计划')"
  );
  if (!onList) {
    await client.send("Page.navigate", { url: DEFAULT_URL });
    await waitFor(client, "document.body && document.body.innerText.includes('新建计划')", "data integration list");
  }

  await installPageHelpers(client);
  if (!(await evaluate(client, "window.__apiTransformFast.modalText().includes('新建流程')"))) {
    await clickRect(client, await waitFor(client, "window.__apiTransformFast.newPlanButton()", "new plan button"));
    await clickRect(client, await waitFor(client, "window.__apiTransformFast.blankPlanItem()", "blank plan item"));
  }
  await waitFor(client, "window.__apiTransformFast.modalText().includes('新建流程')", "new workflow modal");

  await clickRect(client, await waitFor(client, "window.__apiTransformFast.targetInput()", "target customer input"));
  await replaceFocusedText(client, args.customer);

  let option;
  try {
    option = await waitFor(
      client,
      `window.__apiTransformFast.customerOption(${JSON.stringify(args.customer)})`,
      `customer ${args.customer}`,
      3000
    );
  } catch {
    await clickRect(client, await waitFor(client, "window.__apiTransformFast.targetInput()", "target customer input"));
    await replaceFocusedText(client, args.customer);
    option = await waitFor(
      client,
      `window.__apiTransformFast.customerOption(${JSON.stringify(args.customer)})`,
      `customer ${args.customer}`,
      3000
    );
  }
  await clickRect(client, option);

  await clickRect(client, await waitFor(client, "window.__apiTransformFast.flowInput()", "workflow name input"));
  await replaceFocusedText(client, args.flowName);
  await clickRect(client, await waitFor(client, "window.__apiTransformFast.confirmButton()", "confirm button"));

  const url = await waitFor(
    client,
    "location.href.includes('/data-integration/workflow/create/') && location.href",
    "workflow create page",
    5000
  );
  const workflowId = (String(url).match(/workflow\/create\/(\d+)/) || [])[1];
  if (!workflowId) throw new Error(`Cannot parse workflow ID from ${url}`);
  return { workflowId, selectedCustomer: option.text };
}

async function saveDefaultDraft(client, workflowId, args) {
  const detailResponse = await evaluate(
    client,
    `(async () => {
      const response = await fetch('/api/transformers/apiworkflow/detail?workflowId=${workflowId}', { credentials: 'include' });
      return response.json();
    })()`
  );
  if (!detailResponse.success) throw new Error(`Cannot load workflow detail: ${JSON.stringify(detailResponse)}`);

  const detail = detailResponse.data;
  const graph = buildDefaultGraph(detail, args);
  const draftResult = await evaluate(
    client,
    `(async () => {
      const payload = ${JSON.stringify({
        workflowName: detail.workflowName,
        companyId: detail.companyId,
        companyName: detail.companyName,
        workflowId: Number(workflowId),
      })};
      payload.graph = ${JSON.stringify(graph)};
      const response = await fetch('/api/transformers/apiworkflow/draft', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json, text/plain, */*' },
        body: JSON.stringify(payload)
      });
      return { status: response.status, body: await response.json() };
    })()`
  );
  if (!draftResult.body?.success) throw new Error(`Draft save failed: ${JSON.stringify(draftResult)}`);
  return detail;
}

async function getCompany(client, args) {
  if (args.companyName) {
    return { companyId: Number(args.customer), companyName: args.companyName };
  }

  const result = await evaluate(
    client,
    `(async () => {
      const response = await fetch('/api/transformers/apisystem/company/page?pageNum=1&pageSize=20&search=${encodeURIComponent(args.customer)}', {
        credentials: 'include',
        headers: { 'Accept': 'application/json, text/plain, */*' }
      });
      return response.json();
    })()`
  );
  if (!result.success) throw new Error(`Company lookup failed: ${JSON.stringify(result)}`);

  const expectedId = Number(args.customer);
  const company = result.data?.list?.find((item) => Number(item.companyId) === expectedId);
  if (!company) throw new Error(`No exact company match for company ID ${args.customer}`);
  return { companyId: company.companyId, companyName: company.companyName };
}

async function createWorkflowByApi(client, args) {
  const company = await getCompany(client, args);
  const graph = buildInitialGraph();
  const result = await evaluate(
    client,
    `(async () => {
      const response = await fetch('/api/transformers/apiworkflow/init', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json, text/plain, */*' },
        body: JSON.stringify(${JSON.stringify({
          workflowName: args.flowName,
          companyId: company.companyId,
          companyName: company.companyName,
          graph,
        })})
      });
      return { status: response.status, body: await response.json() };
    })()`
  );
  if (!result.body?.success) throw new Error(`API create failed: ${JSON.stringify(result)}`);

  const workflowId =
    result.body.data?.workflowId ||
    result.body.data?.id ||
    result.body.data ||
    result.body.workflowId;
  if (!workflowId) throw new Error(`Cannot parse workflow ID from API create response: ${JSON.stringify(result)}`);
  return {
    workflowId: String(workflowId),
    selectedCustomer: `${company.companyName}\n公司ID: ${company.companyId}`,
  };
}

async function returnToListAndScreenshot(client, workflowId, workflowName, screenshot) {
  await client.send("Page.navigate", { url: DEFAULT_URL });
  await waitFor(client, "location.href.endsWith('/data-integration/') && document.body.innerText.includes('新建计划')", "list page");
  await waitFor(
    client,
    `document.body.innerText.includes(${JSON.stringify(String(workflowId))}) && document.body.innerText.includes(${JSON.stringify(workflowName)})`,
    "created row"
  );
  const image = await client.send("Page.captureScreenshot", {
    format: "png",
    captureBeyondViewport: false,
  });
  await fs.writeFile(screenshot, image.data, "base64");
}

async function main() {
  const started = Date.now();
  const args = parseArgs(process.argv.slice(2));
  const target = await getTarget(args.port);
  const client = new CdpClient(target.webSocketDebuggerUrl);
  await client.open();

  try {
    await client.send("Page.enable");
    await client.send("Runtime.enable");
    await client.send("Page.bringToFront");

    let created;
    let detail;
    if (args.uiCreate) {
      created = await createBlankWorkflow(client, args);
      detail = await saveDefaultDraft(client, created.workflowId, args);
    } else {
      const onPlanet = await evaluate(client, "location.origin === 'https://sh.planet.byai.com'");
      if (!onPlanet) {
        await client.send("Page.navigate", { url: DEFAULT_URL });
        await waitFor(client, "document.body && document.body.innerText.includes('新建计划')", "data integration list");
      }
      created = await createWorkflowByApi(client, args);
      detail = await saveDefaultDraft(client, created.workflowId, args);
    }
    await returnToListAndScreenshot(client, created.workflowId, detail.workflowName, args.screenshot);

    console.log(`Workflow ID: ${created.workflowId}`);
    console.log(`Workflow name: ${detail.workflowName}`);
    console.log(`Selected customer: ${created.selectedCustomer}`);
    console.log(`Final URL: ${DEFAULT_URL}`);
    console.log(`Screenshot: ${args.screenshot}`);
    console.log(`Elapsed ms: ${Date.now() - started}`);
  } finally {
    client.close();
  }
}

main().catch((error) => {
  console.error(error.message);
  process.exit(1);
});
