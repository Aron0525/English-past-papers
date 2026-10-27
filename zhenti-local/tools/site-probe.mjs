/** 探一探真题站：登录态 + 答案接口要什么参数。只读，不改站点任何数据。 */
import { connect } from "./cdp.mjs";

const PORT = Number(process.argv[2] ?? 9223);
const PAPER = process.argv[3] ?? "cet6/2025-06/01";

const { evaluate, close } = await connect(PORT);

console.log("页面：", await evaluate("document.title"));
console.log("地址：", await evaluate("location.href"));

const state = await evaluate(`(() => {
  const txt = document.body.innerText;
  return {
    hasLoginBtn: /登录|注册/.test(txt) && !/退出|个人中心/.test(txt),
    hasUserArea: /个人中心|我的|退出登录/.test(txt),
    answerBtn: !!document.querySelector('.answer_btn'),
    head: txt.slice(0, 160).replace(/\\s+/g, ' '),
  };
})()`);
console.log("登录态：", JSON.stringify(state));

const probe = await evaluate(`(async () => {
  const url = "/api/answerExpansion/textGet";
  const out = [];
  for (const type of [0, 1, 2, 3]) {
    try {
      const res = await fetch(url, {
        method: "POST",
        cache: "no-cache",
        headers: { "Content-Type": "application/json;charset=UTF-8" },
        body: JSON.stringify({ type, urlPath: ${JSON.stringify(PAPER)} }),
      });
      const text = await res.text();
      out.push({ type, status: res.status, body: text.slice(0, 400) });
    } catch (error) {
      out.push({ type, status: 0, body: "ERR " + error.message });
    }
  }
  return out;
})()`);

for (const row of probe) {
  console.log(`\ntype=${row.type} status=${row.status}\n  ${row.body}`);
}

close();
