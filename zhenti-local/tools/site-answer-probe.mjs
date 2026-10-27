/** 用真实鼠标事件点「查答案」，抓所有 XHR 的请求体与响应。 */
import { connect, sleep } from "./cdp.mjs";

const PORT = Number(process.argv[2] ?? 9223);
const { send, on, evaluate, close } = await connect(PORT);

await send("Network.enable");
const captured = new Map();
on("Network.requestWillBeSent", (p) => {
  if (p.request.url.includes("/api/")) captured.set(p.requestId, { url: p.request.url, method: p.request.method, postData: p.request.postData });
});
on("Network.responseReceived", (p) => {
  if (p.response.url.includes("/api/")) {
    const item = captured.get(p.requestId) ?? { url: p.response.url };
    item.status = p.response.status;
    captured.set(p.requestId, item);
  }
});

const rect = await evaluate(`(() => {
  const b = document.querySelector('.answer_btn');
  if (!b) return null;
  b.scrollIntoView({ block: 'center', inline: 'center' });
  const r = b.getBoundingClientRect();
  const inView = r.x >= 0 && r.y >= 0 && r.right <= innerWidth && r.bottom <= innerHeight;
  return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2), inView, vw: innerWidth, vh: innerHeight, cls: b.className };
})()`);
console.log("按钮：", JSON.stringify(rect));

if (rect) {
  for (const type of ["mouseMoved", "mousePressed", "mouseReleased"]) {
    await send("Input.dispatchMouseEvent", {
      type,
      x: rect.x,
      y: rect.y,
      button: type === "mouseMoved" ? "none" : "left",
      clickCount: type === "mouseMoved" ? 0 : 1,
    });
    await sleep(80);
  }
}
await sleep(5000);

for (const [id, item] of captured) {
  console.log(`\n=== ${item.method} ${item.status ?? "?"} ${item.url.slice(0, 120)}`);
  if (item.postData) console.log("  请求体：", item.postData.slice(0, 200));
  try {
    const body = await send("Network.getResponseBody", { requestId: id });
    const text = body.base64Encoded ? Buffer.from(body.body, "base64").toString("utf8") : body.body;
    console.log("  响应：", text.slice(0, 500));
  } catch (error) {
    console.log("  响应取不到：", error.message);
  }
}

const panel = await evaluate(`(() => {
  const box = document.querySelector('.answer_exp_box');
  if (!box) return null;
  return { cls: box.className, text: (box.innerText || '').replace(/\\s+/g, ' ').slice(0, 400) };
})()`);
console.log("\n答案面板：", JSON.stringify(panel));

close();
