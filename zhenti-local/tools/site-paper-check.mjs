/** 打开一套试卷，看看答案按钮在不在（设备绑定是否被认）。 */
import { connect, sleep } from "./cdp.mjs";

const PORT = Number(process.argv[2] ?? 9223);
const PAPER = process.argv[3] ?? "cet6/2025-06/01";

const { evaluate, navigate, waitFor, close } = await connect(PORT);

await navigate(`https://zhenti.burningvocabulary.cn/${PAPER}`, {
  expect: "!!document.querySelector('#textLayer, .textLayer, canvas')",
  timeout: 40000,
});
await sleep(2500);

const info = await evaluate(`(() => {
  const txt = document.body.innerText || "";
  const buttons = [...document.querySelectorAll('button, a, div')]
    .filter((el) => /答案|解析|查答案/.test(el.textContent || "") && (el.textContent || "").length < 20)
    .slice(0, 8)
    .map((el) => ({ tag: el.tagName, cls: String(el.className).slice(0, 60), text: el.textContent.trim() }));
  return {
    title: document.title,
    hasAnswerBtn: !!document.querySelector('.answer_btn'),
    looksLoggedIn: /退出|个人中心|我的|会员/.test(txt),
    loginHint: /登\\s*录/.test(txt),
    candidates: buttons,
    preview: txt.replace(/\\s+/g, " ").slice(0, 200),
  };
})()`);

console.log(JSON.stringify(info, null, 1));
close();
