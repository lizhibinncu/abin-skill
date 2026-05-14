#!/usr/bin/env node

import fs from "node:fs/promises";
import path from "node:path";

const DEFAULT_URL = "https://sh.planet.byai.com/data-integration/";

function parseArgs(argv) {
  const args = {
    customer: "",
    flowName: "",
    port: "9222",
    url: DEFAULT_URL,
    screenshot: path.resolve(process.cwd(), "api-transform-process-created.png"),
  };

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    const next = argv[i + 1];
    if (arg === "--customer" || arg === "--target-customer") {
      args.customer = next || "";
      i += 1;
    } else if (arg === "--flow-name" || arg === "--process-name") {
      args.flowName = next || "";
      i += 1;
    } else if (arg === "--port") {
      args.port = next || "";
      i += 1;
    } else if (arg === "--url") {
      args.url = next || "";
      i += 1;
    } else if (arg === "--screenshot") {
      args.screenshot = path.resolve(process.cwd(), next || "");
      i += 1;
    } else if (arg === "--help" || arg === "-h") {
      usage(0);
    } else {
      throw new Error(`Unknown argument: ${arg}`);
    }
  }

  if (!args.customer) throw new Error("Missing --customer");
  if (!args.flowName) throw new Error("Missing --flow-name");
  if (!args.port) throw new Error("Missing --port");
  return args;
}

function usage(code) {
  console.log(`Usage:
  node create-process.mjs --customer "10317" --flow-name "流程自动化测试"

Options:
  --customer, --target-customer   Target customer value/company ID
  --flow-name, --process-name     Workflow/process name
  --screenshot                    Output screenshot path
  --port                          Chrome remote debugging port, default 9222
  --url                           Data integration URL, default ${DEFAULT_URL}`);
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

async function getOrCreateTarget(port, url) {
  const base = `http://127.0.0.1:${port}`;
  let targets;
  try {
    targets = await fetch(`${base}/json/list`).then((response) => response.json());
  } catch {
    throw new Error(
      `Cannot connect to Chrome on port ${port}. Start Chrome with --remote-debugging-port=${port} and an already logged-in profile.`
    );
  }

  const existing =
    targets.find((target) => target.type === "page" && target.url?.includes("sh.planet.byai.com")) ||
    targets.find((target) => target.type === "page");

  if (existing) return existing;
  return fetch(`${base}/json/new?${encodeURIComponent(url)}`, { method: "PUT" }).then((response) =>
    response.json()
  );
}

async function evaluate(client, expression) {
  const result = await client.send("Runtime.evaluate", {
    expression,
    returnByValue: true,
    awaitPromise: true,
  });
  if (result.exceptionDetails) {
    throw new Error(JSON.stringify(result.exceptionDetails));
  }
  return result.result.value;
}

async function waitFor(client, expression, label, timeoutMs = 15000) {
  const started = Date.now();
  let lastValue;
  while (Date.now() - started < timeoutMs) {
    try {
      lastValue = await evaluate(client, expression);
      if (lastValue) return lastValue;
    } catch (error) {
      lastValue = error.message;
    }
    await delay(150);
  }
  throw new Error(`Timed out waiting for ${label}. Last value: ${JSON.stringify(lastValue)}`);
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
  await delay(100);
  await client.send("Input.insertText", { text });
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const target = await getOrCreateTarget(args.port, args.url);
  const client = new CdpClient(target.webSocketDebuggerUrl);
  await client.open();

  try {
    await client.send("Page.enable");
    await client.send("Runtime.enable");
    await client.send("DOM.enable");
    await client.send("Page.bringToFront");
    await client.send("Page.navigate", { url: args.url });

    await waitFor(
      client,
      "document.body && document.body.innerText.includes('新建计划')",
      "data integration list"
    );

    await evaluate(
      client,
      `(() => {
        window.__apiTransformCreate = {
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
              text: (el.innerText || el.textContent || '').trim(),
              tag: el.tagName,
              className: String(el.className || ''),
              placeholder: el.placeholder || '',
              value: el.value || ''
            };
          },
          smallestText(text, selector, root = document) {
            return [...root.querySelectorAll(selector)]
              .filter((el) => this.visible(el) && (el.innerText || el.textContent || '').trim().includes(text))
              .map((el) => ({ ...this.rect(el), area: el.getBoundingClientRect().width * el.getBoundingClientRect().height }))
              .sort((a, b) => a.area - b.area)[0] || null;
          },
          newPlanButton() {
            const button = [...document.querySelectorAll('button')]
              .find((el) => this.visible(el) && (el.innerText || el.textContent || '').includes('新建计划'));
            return button ? this.rect(button) : null;
          },
          blankPlanItem() {
            const item = [...document.querySelectorAll('.by-data-integration-ant-dropdown-menu-item, [role="menuitem"], li')]
              .find((el) => this.visible(el) && (el.innerText || el.textContent || '').includes('空白计划'));
            return item ? this.rect(item) : null;
          },
          modal() {
            return [...document.querySelectorAll('.by-data-integration-ant-modal-content, [role="dialog"]')]
              .find((el) => this.visible(el));
          },
          targetInput() {
            const modal = this.modal();
            if (!modal) return null;
            const input = [...modal.querySelectorAll('input[type="search"]')].find((el) => this.visible(el));
            return input ? this.rect(input) : null;
          },
          flowInput() {
            const modal = this.modal();
            if (!modal) return null;
            const input = [...modal.querySelectorAll('input[placeholder="请输入流程名称"], input[type="text"]')]
              .find((el) => this.visible(el) && el.placeholder !== '');
            return input ? this.rect(input) : null;
          },
          customerOption(customerValue) {
            const expected = '公司ID:' + String(customerValue).trim();
            const dropdowns = [...document.querySelectorAll('.by-data-integration-ant-select-dropdown')]
              .filter((el) => this.visible(el) && !String(el.className).includes('hidden'));
            for (const dropdown of dropdowns) {
              for (const el of dropdown.querySelectorAll('.by-data-integration-ant-select-item-option')) {
                const text = (el.innerText || el.textContent || '').trim();
                if (!this.visible(el) || !text) continue;
                if (text.replace(/\\s/g, '').includes(expected)) return this.rect(el);
              }
            }
            return null;
          },
          confirmButton() {
            const modal = this.modal();
            if (!modal) return null;
            const button = [...modal.querySelectorAll('button')]
              .find((el) => this.visible(el) && (el.innerText || el.textContent || '').replace(/\\s/g, '') === '确定');
            return button ? this.rect(button) : null;
          },
          modalText() {
            const modal = this.modal();
            return modal ? modal.innerText : '';
          }
        };
      })()`
    );

    await clickRect(
      client,
      await waitFor(
        client,
        "window.__apiTransformCreate.newPlanButton()",
        "new plan button"
      )
    );
    await clickRect(
      client,
      await waitFor(
        client,
        "window.__apiTransformCreate.blankPlanItem()",
        "blank plan menu item"
      )
    );

    await waitFor(
      client,
      "window.__apiTransformCreate.modalText().includes('新建流程')",
      "new workflow modal"
    );
    await clickRect(
      client,
      await waitFor(client, "window.__apiTransformCreate.targetInput()", "target customer input")
    );
    await replaceFocusedText(client, args.customer);

    let selectedCustomer;
    try {
      selectedCustomer = await waitFor(
        client,
        `window.__apiTransformCreate.customerOption(${JSON.stringify(args.customer)})`,
        `customer dropdown option matching ${args.customer}`,
        6000
      );
    } catch {
      await clickRect(
        client,
        await waitFor(client, "window.__apiTransformCreate.targetInput()", "target customer input")
      );
      await replaceFocusedText(client, args.customer);
      selectedCustomer = await waitFor(
        client,
        `window.__apiTransformCreate.customerOption(${JSON.stringify(args.customer)})`,
        `customer dropdown option matching ${args.customer}`,
        6000
      );
    }
    await clickRect(client, selectedCustomer);

    await clickRect(
      client,
      await waitFor(client, "window.__apiTransformCreate.flowInput()", "workflow name input")
    );
    await client.send("Input.insertText", { text: args.flowName });

    await clickRect(
      client,
      await waitFor(client, "window.__apiTransformCreate.confirmButton()", "confirm button")
    );

    await waitFor(
      client,
      "!window.__apiTransformCreate.modalText().includes('新建流程') && location.href.includes('/workflow/create/')",
      "workflow editor"
    );
    await delay(1000);

    const finalState = await evaluate(
      client,
      "({ url: location.href, title: document.title, body: document.body.innerText.slice(0, 1000) })"
    );
    const screenshot = await client.send("Page.captureScreenshot", {
      format: "png",
      captureBeyondViewport: false,
    });
    await fs.writeFile(args.screenshot, screenshot.data, "base64");

    console.log(`Selected customer: ${selectedCustomer.text}`);
    console.log(`Final URL: ${finalState.url}`);
    console.log(`Screenshot: ${args.screenshot}`);
  } finally {
    client.close();
  }
}

main().catch((error) => {
  console.error(error.message);
  process.exit(1);
});
