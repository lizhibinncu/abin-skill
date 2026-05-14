#!/usr/bin/env node

import fs from "node:fs/promises";
import path from "node:path";

function parseArgs(argv) {
  const args = {
    workflowId: "",
    port: "9222",
    receiveUri: "abinliuchengceshi",
    transformScript: "return args",
    requestUrl: "www.baidu.com",
    endScript: "return args",
    screenshot: path.resolve(process.cwd(), "api-transform-process-list.png"),
    backToList: true,
    clickSave: true,
  };

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    const next = argv[i + 1];
    if (arg === "--workflow-id") {
      args.workflowId = next || "";
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
    } else if (arg === "--no-back") {
      args.backToList = false;
    } else if (arg === "--no-click-save") {
      args.clickSave = false;
    } else if (arg === "--help" || arg === "-h") {
      usage(0);
    } else {
      throw new Error(`Unknown argument: ${arg}`);
    }
  }

  if (!args.port) throw new Error("Missing --port");
  if (!args.receiveUri) throw new Error("Missing --receive-uri");
  if (!args.transformScript) throw new Error("Missing --transform-script");
  if (!args.requestUrl) throw new Error("Missing --request-url");
  if (!args.endScript) throw new Error("Missing --end-script");
  return args;
}

function usage(code) {
  console.log(`Usage:
  node develop-default-flow.mjs --workflow-id 28920

Options:
  --workflow-id        Workflow id; defaults to id parsed from the current editor URL
  --receive-uri        Receive URL suffix, default abinliuchengceshi
  --transform-script   Data transform script, default "return args"
  --request-url        Sender request URL, default www.baidu.com
  --end-script         End node script, default "return args"
  --screenshot         Output screenshot path
  --port               Chrome remote debugging port, default 9222
  --no-click-save      Skip UI save click after draft API save
  --no-back            Stay on editor page instead of returning to list`);
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
      if (message.error) {
        request.reject(new Error(`${request.method}: ${JSON.stringify(message.error)}`));
      } else {
        request.resolve(message.result);
      }
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
  const targets = await fetch(`http://127.0.0.1:${port}/json/list`).then((response) =>
    response.json()
  );
  const target = targets.find((item) => item.type === "page" && item.url?.includes("sh.planet.byai.com"));
  if (!target) {
    throw new Error(`No BYAI Planet tab found on Chrome remote debugging port ${port}`);
  }
  return target;
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

async function waitFor(client, expression, label, timeoutMs = 15000) {
  const started = Date.now();
  let last;
  while (Date.now() - started < timeoutMs) {
    try {
      last = await evaluate(client, expression);
      if (last) return last;
    } catch (error) {
      last = error.message;
    }
    await delay(250);
  }
  throw new Error(`Timed out waiting for ${label}. Last value: ${JSON.stringify(last)}`);
}

async function waitForOptional(client, expression, timeoutMs = 5000) {
  try {
    return await waitFor(client, expression, "optional condition", timeoutMs);
  } catch {
    return null;
  }
}

async function clickRect(client, rect) {
  const x = rect.x + rect.width / 2;
  const y = rect.y + rect.height / 2;
  await client.send("Input.dispatchMouseEvent", { type: "mouseMoved", x, y });
  await client.send("Input.dispatchMouseEvent", {
    type: "mousePressed",
    x,
    y,
    button: "left",
    clickCount: 1,
  });
  await client.send("Input.dispatchMouseEvent", {
    type: "mouseReleased",
    x,
    y,
    button: "left",
    clickCount: 1,
  });
}

function buildDefaultGraph(detail, args) {
  const resultNode =
    detail.graph?.nodes?.find((node) => node.nodeType === "API_RESULT") || {
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

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const target = await getTarget(args.port);
  const client = new CdpClient(target.webSocketDebuggerUrl);
  await client.open();

  try {
    await client.send("Page.enable");
    await client.send("Runtime.enable");
    await client.send("Page.bringToFront");

    const workflowId =
      args.workflowId ||
      (await evaluate(
        client,
        "((location.pathname.match(/workflow\\/(?:create|edit)\\/(\\d+)/) || [])[1] || '')"
      ));
    if (!workflowId) throw new Error("Missing --workflow-id and current tab is not a workflow editor");

    const detailResponse = await evaluate(
      client,
      `(async () => {
        const response = await fetch('/bygw/api/transformers/apiworkflow/detail?workflowId=${workflowId}', { credentials: 'include' });
        return response.json();
      })()`
    );
    if (!detailResponse.success) {
      throw new Error(`Cannot load workflow detail: ${JSON.stringify(detailResponse)}`);
    }
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
        const response = await fetch('/bygw/api/transformers/apiworkflow/draft', {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json', 'Accept': 'application/json, text/plain, */*' },
          body: JSON.stringify(payload)
        });
        return { status: response.status, body: await response.json() };
      })()`
    );
    if (!draftResult.body?.success) {
      throw new Error(`Draft save failed: ${JSON.stringify(draftResult)}`);
    }

    await client.send("Page.navigate", {
      url: `https://sh.planet.byai.com/data-integration/workflow/edit/${workflowId}`,
    });
    await waitFor(
      client,
      "document.body.innerText.includes('defaultConvert01') && document.body.innerText.includes('defaultSender01')",
      "default flow visible"
    );

    if (args.clickSave) {
      const saveButton = await waitFor(
        client,
        `(() => {
          const el = [...document.querySelectorAll('button,span')]
            .find((item) => getComputedStyle(item).display !== 'none' && (item.innerText || '').includes('保存草稿'));
          if (!el) return null;
          const button = el.closest('button') || el;
          const rect = button.getBoundingClientRect();
          return { x: rect.x, y: rect.y, width: rect.width, height: rect.height };
        })()`,
        "save draft button"
      );
      await clickRect(client, saveButton);
      const saveToast = await waitForOptional(
        client,
        "document.body.innerText.includes('保存草稿成功')",
        8000
      );
      if (!saveToast) {
        console.warn("Save toast was not captured; draft API save already succeeded, continuing.");
      }
    }

    if (args.backToList) {
      const backButton = await waitFor(
        client,
        `(() => {
          const el = document.querySelector('.by-data-integration-ant-drawer-close');
          if (!el) return null;
          const rect = el.getBoundingClientRect();
          return { x: rect.x, y: rect.y, width: rect.width, height: rect.height };
        })()`,
        "editor back button"
      );
      await clickRect(client, backButton);
      const returnedToList = await waitForOptional(
        client,
        "location.href.endsWith('/data-integration/')",
        8000
      );
      if (!returnedToList) {
        await client.send("Page.navigate", {
          url: "https://sh.planet.byai.com/data-integration/",
        });
      }
      await waitFor(client, "location.href.endsWith('/data-integration/')", "data integration list");
      await waitFor(
        client,
        `document.body.innerText.includes(${JSON.stringify(String(workflowId))}) && document.body.innerText.includes(${JSON.stringify(detail.workflowName)})`,
        "workflow row visible"
      );
    }

    await delay(1000);
    const screenshot = await client.send("Page.captureScreenshot", {
      format: "png",
      captureBeyondViewport: false,
    });
    await fs.writeFile(args.screenshot, screenshot.data, "base64");
    console.log(`Workflow ID: ${workflowId}`);
    console.log(`Workflow name: ${detail.workflowName}`);
    console.log(`Screenshot: ${args.screenshot}`);
  } finally {
    client.close();
  }
}

main().catch((error) => {
  console.error(error.message);
  process.exit(1);
});
