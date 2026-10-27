/**
 * 极简 Chrome DevTools Protocol 客户端。
 * 只做三件事：连上一个标签页、执行表达式、抓网络响应。
 * 不引第三方依赖，Node 22 自带 WebSocket 就够。
 */

export const connect = async (port, matcher = () => true) => {
  const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  const pages = targets.filter((t) => t.type === "page");
  const target = pages.find(matcher) ?? pages[0];
  if (!target) throw new Error(`端口 ${port} 上没有可用的标签页`);

  const ws = new WebSocket(target.webSocketDebuggerUrl);
  const pending = new Map();
  const listeners = new Map();
  let seq = 0;

  ws.addEventListener("message", (event) => {
    const msg = JSON.parse(event.data);
    if (msg.id && pending.has(msg.id)) {
      const entry = pending.get(msg.id);
      pending.delete(msg.id);
      if (msg.error) entry.reject(new Error(JSON.stringify(msg.error)));
      else entry.resolve(msg.result);
      return;
    }
    const handler = listeners.get(msg.method);
    if (handler) handler(msg.params);
  });

  await new Promise((resolve, reject) => {
    ws.addEventListener("open", resolve, { once: true });
    ws.addEventListener("error", () => reject(new Error("CDP 连接失败")), { once: true });
  });

  const send = (method, params = {}) =>
    new Promise((resolve, reject) => {
      const id = ++seq;
      pending.set(id, { resolve, reject });
      ws.send(JSON.stringify({ id, method, params }));
    });

  const on = (method, handler) => listeners.set(method, handler);

  const evaluate = async (expression) => {
    const result = await send("Runtime.evaluate", {
      expression,
      awaitPromise: true,
      returnByValue: true,
      userGesture: true,
    });
    if (result.exceptionDetails) {
      throw new Error(result.exceptionDetails.exception?.description ?? "页面执行出错");
    }
    return result.result.value;
  };

  const waitFor = async (expression, { timeout = 20000, interval = 300 } = {}) => {
    const deadline = Date.now() + timeout;
    for (;;) {
      try {
        if (await evaluate(expression)) return true;
      } catch {
        /* 页面还在导航，忽略 */
      }
      if (Date.now() > deadline) return false;
      await new Promise((r) => setTimeout(r, interval));
    }
  };

  const navigate = async (url, { expect = null, timeout = 30000 } = {}) => {
    await send("Page.navigate", { url });
    if (expect) await waitFor(expect, { timeout });
    return true;
  };

  return { ws, send, on, evaluate, waitFor, navigate, target, close: () => ws.close() };
};

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
