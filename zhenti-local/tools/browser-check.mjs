#!/usr/bin/env node
/**
 * 浏览器端自检：用 Chrome 的调试协议真点一遍阅读页，验证"点词查词"和"圈画"。
 *
 * 为什么要这个：这两个功能全靠 DOM 事件和画布，`node --check` 只能保证语法，
 * 真出错（文字层没切开、笔迹没落盘）静态检查看不出来。
 *
 * 用法：
 *   chrome --headless=new --remote-debugging-port=9333 --user-data-dir=<临时目录> about:blank
 *   node tools/browser-check.mjs 9333 [cet6/2024-06/01]
 *
 * 注意：跑之前把那套卷子的 ink.json 清掉，否则计数会带着旧笔迹一起算。
 */
const port = process.argv[2] ?? "9333";
const paperId = process.argv[3] ?? "cet6/2024-06/01";
const base = process.env.ZHENTI_BASE ?? "http://127.0.0.1:8787";

const list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
const target = list.find((item) => item.type === "page");
if (!target) throw new Error("没有可用的 page target，Chrome 起了吗？");

const ws = new WebSocket(target.webSocketDebuggerUrl);
let seq = 0;
const pending = new Map();

ws.addEventListener("message", (event) => {
  const message = JSON.parse(event.data);
  const entry = pending.get(message.id);
  if (!entry) return;
  pending.delete(message.id);
  message.error ? entry.reject(new Error(JSON.stringify(message.error))) : entry.resolve(message.result);
});
await new Promise((resolve) => ws.addEventListener("open", resolve, { once: true }));

const send = (method, params = {}) => new Promise((resolve, reject) => {
  const id = ++seq;
  pending.set(id, { resolve, reject });
  ws.send(JSON.stringify({ id, method, params }));
});

const evaluate = async (expression) => {
  const result = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description ?? result.exceptionDetails.text);
  return result.result.value;
};

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const readInk = async () => (await (await fetch(`${base}/api/ink?id=${paperId}`)).json()).pages?.["1"] ?? [];

const resetInk = () => fetch(`${base}/api/ink`, {
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify({ id: paperId, pages: {} }),
});

const drag = async (from, to, steps = 12) => {
  await send("Input.dispatchMouseEvent", { type: "mousePressed", x: from.x, y: from.y, button: "left", clickCount: 1 });
  for (let step = 1; step <= steps; step += 1) {
    await send("Input.dispatchMouseEvent", {
      type: "mouseMoved",
      x: from.x + ((to.x - from.x) * step) / steps,
      y: from.y + ((to.y - from.y) * step) / steps,
      button: "left",
      buttons: 1,
    });
    await wait(12);
  }
  await send("Input.dispatchMouseEvent", { type: "mouseReleased", x: to.x, y: to.y, button: "left", clickCount: 1 });
  await wait(900);
};

await send("Page.enable");
await send("Runtime.enable");
await resetInk();
await send("Page.navigate", { url: `${base}/read.html?id=${paperId}` });

for (let i = 0; i < 40; i += 1) {
  if (await evaluate("document.querySelectorAll('#textLayer aw').length > 20")) break;
  await wait(400);
}

const words = await evaluate("document.querySelectorAll('#textLayer aw').length");
console.log(`文字层逐词：${words} 个可点词`);
if (words < 20) throw new Error("文字层没切开，查词不会生效（这套可能是扫描件）");

const spot = await evaluate(`(() => {
  const el = [...document.querySelectorAll('#textLayer aw')].find((n) => /^[A-Za-z]{6,}$/.test(n.textContent));
  const r = el.getBoundingClientRect();
  return { word: el.textContent, x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) };
})()`);
for (const type of ["mousePressed", "mouseReleased"]) {
  await send("Input.dispatchMouseEvent", { type, x: spot.x, y: spot.y, button: "left", clickCount: 1 });
}
await wait(800);

const dict = await evaluate(`(() => {
  const pop = document.querySelector('#dictPop');
  return {
    open: !pop.hidden,
    word: document.querySelector('#dictWord').textContent,
    phonetic: document.querySelector('#dictPhonetic').textContent,
    body: document.querySelector('#dictBody').innerText.replace(/\\s+/g, ' ').slice(0, 60),
  };
})()`);
console.log("点词查词：", JSON.stringify(dict));

const box = await evaluate(`(() => { const r = document.querySelector('#pageBox').getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height, vh: window.innerHeight }; })()`);

/* 页面试宽后会比窗口高，按比例算出来的 y 可能落在可视区外面 —— 那种坐标鼠标事件根本到不了画布 */
const inside = (nx, ny) => ({
  x: box.x + box.w * nx,
  y: Math.min(box.y + box.h * ny, box.vh - 60),
});

await evaluate("document.querySelector('.tool[data-tool=\"hl\"]').click()");
await drag(inside(0.18, 0.3), inside(0.7, 0.3));
await wait(1200);
const afterHl = (await readInk()).length;

await evaluate("document.querySelector('.tool[data-tool=\"pen\"]').click()");
await drag(inside(0.2, 0.5), inside(0.55, 0.55));
await wait(1200);
const afterPen = (await readInk()).length;

await evaluate("document.querySelector('#inkUndo').click()");
await wait(1200);
const afterUndo = (await readInk()).length;

console.log(`圈画：荧光笔后 ${afterHl} 笔，画笔后 ${afterPen} 笔，撤销后 ${afterUndo} 笔`);

const verdict = dict.open && words > 20 && afterHl === 1 && afterPen === 2 && afterUndo === 1;
console.log(verdict ? "全部通过" : "有不通过项，往上翻");

await resetInk();
ws.close();
process.exit(verdict ? 0 : 1);
