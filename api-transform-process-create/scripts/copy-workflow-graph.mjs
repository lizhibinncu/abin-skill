#!/usr/bin/env node

import fs from "node:fs/promises";
import path from "node:path";

const DEFAULT_URL = "https://sh.planet.byai.com/data-integration/";

function parseArgs(argv) {
  const args = {
    sourceWorkflowId: "",
    targetWorkflowId: "",
    port: "9222",
    screenshot: path.resolve(process.cwd(), "api-transform-process-copy-list.png"),
    preserveReceiverUrl: true,
    saveMode: "auto",
    backToList: true,
  };

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    const next = argv[i + 1];
    if (arg === "--source-workflow-id" || arg === "--source") {
      args.sourceWorkflowId = next || "";
      i += 1;
    } else if (arg === "--target-workflow-id" || arg === "--target") {
      args.targetWorkflowId = next || "";
      i += 1;
    } else if (arg === "--port") {
      args.port = next || "";
      i += 1;
    } else if (arg === "--screenshot") {
      args.screenshot = path.resolve(process.cwd(), next || "");
      i += 1;
    } else if (arg === "--overwrite-receiver-url") {
      args.preserveReceiverUrl = false;
    } else if (arg === "--save-mode") {
      args.saveMode = next || "";
      i += 1;
    } else if (arg === "--no-back") {
      args.backToList = false;
    } else if (arg === "--help" || arg === "-h") {
      usage(0);
    } else {
      throw new Error(`Unknown argument: ${arg}`);
    }
  }

  if (!args.sourceWorkflowId) throw new Error("Missing --source-workflow-id");
  if (!args.targetWorkflowId) throw new Error("Missing --target-workflow-id");
  if (!["auto", "draft", "publish"].includes(args.saveMode)) {
    throw new Error("--save-mode must be one of: auto, draft, publish");
  }
  return args;
}

function usage(code) {
  console.log(`Usage:
  node copy-workflow-graph.mjs --source-workflow-id 23820 --target-workflow-id 27020

Options:
  --source-workflow-id, --source   Workflow to copy graph content from
  --target-workflow-id, --target   Workflow to update
  --overwrite-receiver-url         Also copy the source receiver URL; default preserves target URL
  --save-mode                      auto, draft, or publish; default auto
  --screenshot                     Final list screenshot path
  --port                           Chrome remote debugging port, default 9222
  --no-back                        Skip returning to the list page`);
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

  const target =
    targets.find((item) => item.type === "page" && item.url?.includes("sh.planet.byai.com")) ||
    targets.find((item) => item.type === "page");
  if (!target) throw new Error(`No browser page found on Chrome remote debugging port ${port}`);
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

async function waitFor(client, expression, label, timeoutMs = 10000) {
  const started = Date.now();
  let last;
  while (Date.now() - started < timeoutMs) {
    try {
      last = await evaluate(client, expression);
      if (last) return last;
    } catch (error) {
      last = error.message;
    }
    await delay(150);
  }
  throw new Error(`Timed out waiting for ${label}. Last value: ${JSON.stringify(last)}`);
}

function stable(value) {
  if (Array.isArray(value)) return `[${value.map(stable).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${stable(value[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function receiverNodes(graph) {
  return graph.nodes?.filter((node) => node.nodeType === "API_RECEIVER") || [];
}

function applyTargetReceiverUrls(sourceGraph, targetGraph) {
  const graph = clone(sourceGraph);
  const targetReceivers = receiverNodes(targetGraph);
  const sourceReceivers = receiverNodes(graph);

  sourceReceivers.forEach((sourceNode, index) => {
    const targetNode = targetReceivers[index] || targetReceivers[0];
    if (!targetNode?.extra) return;
    sourceNode.extra = sourceNode.extra || {};
    if (targetNode.extra.uri !== undefined) sourceNode.extra.uri = targetNode.extra.uri;
    if (targetNode.extra.urlPrefix !== undefined) sourceNode.extra.urlPrefix = targetNode.extra.urlPrefix;
  });

  return graph;
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

    const onPlanet = await evaluate(client, "location.origin === 'https://sh.planet.byai.com'");
    if (!onPlanet) {
      await client.send("Page.navigate", { url: DEFAULT_URL });
      await waitFor(client, "location.origin === 'https://sh.planet.byai.com'", "BYAI Planet page");
    }

    const result = await evaluate(
      client,
      `(async () => {
        const args = ${JSON.stringify(args)};
        const req = async (method, url, body) => {
          const response = await fetch(url, {
            method,
            credentials: 'include',
            headers: {
              'Content-Type': 'application/json',
              'Accept': 'application/json, text/plain, */*'
            },
            body: body ? JSON.stringify(body) : undefined
          });
          let parsed;
          try {
            parsed = await response.json();
          } catch {
            parsed = { raw: await response.text() };
          }
          return { status: response.status, body: parsed };
        };
        const source = await req('GET', '/api/transformers/apiworkflow/detail?workflowId=' + args.sourceWorkflowId);
        const target = await req('GET', '/api/transformers/apiworkflow/detail?workflowId=' + args.targetWorkflowId);
        if (!source.body?.success || !target.body?.success) {
          return { ok: false, stage: 'detail', source, target };
        }

        const sourceGraph = source.body.data.graph;
        const targetGraph = target.body.data.graph;
        const receiverNodes = (graph) => (graph.nodes || []).filter((node) => node.nodeType === 'API_RECEIVER');
        const graph = JSON.parse(JSON.stringify(sourceGraph));
        if (args.preserveReceiverUrl) {
          const targetReceivers = receiverNodes(targetGraph);
          receiverNodes(graph).forEach((sourceNode, index) => {
            const targetNode = targetReceivers[index] || targetReceivers[0];
            if (!targetNode?.extra) return;
            sourceNode.extra = sourceNode.extra || {};
            if (targetNode.extra.uri !== undefined) sourceNode.extra.uri = targetNode.extra.uri;
            if (targetNode.extra.urlPrefix !== undefined) sourceNode.extra.urlPrefix = targetNode.extra.urlPrefix;
          });
        }

        const payload = {
          workflowName: target.body.data.workflowName,
          companyId: target.body.data.companyId,
          companyName: target.body.data.companyName,
          workflowId: Number(args.targetWorkflowId),
          graph
        };

        const save = async (mode) => req(
          'POST',
          mode === 'publish' ? '/api/transformers/apiworkflow/update' : '/api/transformers/apiworkflow/draft',
          payload
        );

        let saveResult;
        let saveMode = args.saveMode;
        if (saveMode === 'auto') {
          saveMode = 'draft';
          saveResult = await save('draft');
          const message = saveResult.body?.message || saveResult.body?.msg || '';
          if (!saveResult.body?.success && target.body.data.status === 'PUBLISHED' && String(message).includes('PUBLISHED')) {
            saveMode = 'publish';
            saveResult = await save('publish');
          }
        } else {
          saveResult = await save(saveMode);
        }

        const after = await req('GET', '/api/transformers/apiworkflow/detail?workflowId=' + args.targetWorkflowId);
        return {
          ok: !!saveResult.body?.success,
          saveMode,
          saveResult,
          source: source.body.data,
          targetBefore: target.body.data,
          targetAfter: after.body?.data,
          expectedGraph: graph
        };
      })()`
    );

    if (!result.ok) {
      throw new Error(`Copy save failed: ${JSON.stringify(result.saveResult || result)}`);
    }

    const expectedGraph = args.preserveReceiverUrl
      ? applyTargetReceiverUrls(result.source.graph, result.targetBefore.graph)
      : result.source.graph;
    const graphMatches = stable(result.targetAfter.graph) === stable(expectedGraph);
    if (!graphMatches) {
      throw new Error("Target graph did not match the expected copied graph after save");
    }

    if (args.backToList) {
      await client.send("Page.navigate", { url: DEFAULT_URL });
      await waitFor(
        client,
        `location.href.endsWith('/data-integration/') && document.body.innerText.includes(${JSON.stringify(
          String(args.targetWorkflowId)
        )})`,
        "target workflow row"
      );
      await delay(800);
      const screenshot = await client.send("Page.captureScreenshot", {
        format: "png",
        captureBeyondViewport: false,
      });
      await fs.writeFile(args.screenshot, screenshot.data, "base64");
    }

    const beforeReceiver = receiverNodes(result.targetBefore.graph)[0]?.extra || {};
    const afterReceiver = receiverNodes(result.targetAfter.graph)[0]?.extra || {};
    console.log(`Source workflow ID: ${args.sourceWorkflowId}`);
    console.log(`Target workflow ID: ${args.targetWorkflowId}`);
    console.log(`Save mode: ${result.saveMode}`);
    console.log(`Target workflow name: ${result.targetAfter.workflowName}`);
    console.log(`Target status: ${result.targetAfter.status}`);
    console.log(`Receiver URL preserved: ${args.preserveReceiverUrl}`);
    console.log(`Before receiver uri: ${beforeReceiver.uri || ""}`);
    console.log(`After receiver uri: ${afterReceiver.uri || ""}`);
    if (args.backToList) console.log(`Screenshot: ${args.screenshot}`);
  } finally {
    client.close();
  }
}

main().catch((error) => {
  console.error(error.message);
  process.exit(1);
});
