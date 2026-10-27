/** 刷新试卷页，把这段时间里所有 /api/ 请求列出来。 */
import { connect, sleep } from "./cdp.mjs";

const PORT = Number(process.argv[2] ?? 9223);
const { send, on, close } = await connect(PORT);

await send("Network.enable");
await send("Page.enable");

const reqs = new Map();
on("Network.requestWillBeSent", (p) => {
  if (p.request.url.includes("/api/")) reqs.set(p.requestId, { url: p.request.url, method: p.request.method, postData: p.request.postData });
});
on("Network.responseReceived", (p) => {
  const item = reqs.get(p.requestId);
  if (item) { item.status = p.response.status; item.mime = p.response.mimeType; }
});

await send("Page.reload", { ignoreCache: false });
await sleep(9000);

for (const [id, item] of reqs) {
  console.log(`${item.status ?? "?"} ${item.method} ${item.url.replace("https://zhenti.burningvocabulary.cn", "")}`);
  if (item.postData) console.log(`    body: ${item.postData.slice(0, 160)}`);
  try {
    const body = await send("Network.getResponseBody", { requestId: id });
    const text = body.base64Encoded ? Buffer.from(body.body, "base64").toString("utf8") : body.body;
    console.log(`    响应: ${text.replace(/\s+/g, " ").slice(0, 260)}`);
  } catch { /* 取不到就算了 */ }
}
console.log("共", reqs.size, "个 /api/ 请求");
close();
