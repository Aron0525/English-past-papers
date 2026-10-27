/**
 * 探听力原文：/api/listening/textGet 拿密文 → 站点 Worker 解密。
 * 用法：node tools/probe-listening.mjs 9223 cet6/2025-06/01
 */
import { connect } from "./cdp.mjs";

const [, , portArg, idArg] = process.argv;
const port = Number(portArg || 9223);
const id = idArg || "cet6/2025-06/01";

const expr = `(async () => {
  const out = {};
  try {
    const res = await fetch("/api/listening/textGet", {
      method: "POST",
      cache: "no-cache",
      headers: { "Content-Type": "application/json;charset=UTF-8" },
      body: JSON.stringify({ filePath: ${JSON.stringify(id)} }),
    });
    const text = await res.text();
    out.status = res.status;
    out.len = text.length;
    out.head = text.slice(0, 200);
    let json = null;
    try { json = JSON.parse(text); } catch (e) { out.parse = String(e).slice(0, 80); }
    if (json) {
      out.code = json.code;
      out.dataKeys = json.data ? Object.keys(json.data) : null;
      if (json.code === "0000") {
        const w = new Worker("/javascripts/read_zhenti_web_worker.js?version=03aad8a1");
        const plain = await new Promise((resolve) => {
          const timer = setTimeout(() => resolve({ __timeout: true }), 15000);
          w.addEventListener("message", (e) => {
            const d = e.data;
            if (d && String(d.type || "").endsWith("_ed")) {
              clearTimeout(timer);
              resolve({ type: d.type, data: d.resData });
            }
          });
          w.postMessage({ type: "decryp_msg_listening", resData: json, extraData: {} });
        });
        w.terminate();
        out.plain = JSON.stringify(plain).slice(0, 600);
        out.plainLen = JSON.stringify(plain).length;
      }
    }
  } catch (e) {
    out.error = String(e);
  }
  return out;
})()`;

const { evaluate, close } = await connect(port);
const result = await evaluate(expr);
console.log(JSON.stringify(result, null, 1));
close();
