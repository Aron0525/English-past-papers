/**
 * 从站点批量取答案。
 *
 * 思路：站点自己的 Worker（read_zhenti_web_worker.js）就带解密能力。
 * 我们不去逆向它的加密算法，而是直接借它干活：
 *   1. 在已登录的页面里同源 fetch 试卷页 HTML；
 *   2. 从 HTML 的 globalConfig 里抠出 newAnswer（密文块）；
 *   3. 把密文块 postMessage 给站点 Worker，拿回明文答案。
 * 这样不碰密钥、不改页面，站点改算法我们也跟着走。
 *
 * 用法：node tools/fetch-answers.mjs 9223 [--only id] [--delay 1500]
 */

import { readFile, writeFile, mkdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { connect, sleep } from "./cdp.mjs";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const PORT = Number(process.argv[2] || 9223);
const arg = (name, fallback) => {
  const i = process.argv.indexOf(`--${name}`);
  return i > -1 ? process.argv[i + 1] : fallback;
};
const ONLY = arg("only", null);
const DELAY = Number(arg("delay", 1500));
const OUT = join(ROOT, "data", "answers.json");

/** 在页面里跑：抓 HTML → 抠 newAnswer → 交给站点 Worker 解密 */
const PAGE_FETCH = (path) => `(async () => {
  const res = await fetch(${JSON.stringify(path)}, { credentials: "include" });
  const html = await res.text();
  if (res.status !== 200) return { error: "http " + res.status };

  // 从 "newAnswer": 后面按括号配平抠出整个对象，避免手写正则踩嵌套
  const start = html.indexOf('"newAnswer"');
  if (start < 0) return { error: "no newAnswer", hasAnswerBtn: html.includes('answer_btn') };
  const braceStart = html.indexOf("{", start);
  let depth = 0, end = -1, inStr = false, esc = false;
  for (let i = braceStart; i < html.length; i++) {
    const c = html[i];
    if (inStr) {
      if (esc) esc = false;
      else if (c === "\\\\") esc = true;
      else if (c === '"') inStr = false;
      continue;
    }
    if (c === '"') { inStr = true; continue; }
    if (c === "{") depth++;
    else if (c === "}") { depth--; if (depth === 0) { end = i + 1; break; } }
  }
  if (end < 0) return { error: "brace mismatch" };
  let payload;
  try { payload = JSON.parse(html.slice(braceStart, end)); }
  catch (e) { return { error: "json " + e.message }; }

  let worker = window.__ansWorker;
  if (!worker) {
    worker = window.__ansWorker = new Worker("/javascripts/read_zhenti_web_worker.js?version=03aad8a1");
  }
  const plain = await new Promise((resolve) => {
    const timer = setTimeout(() => resolve({ __timeout: true }), 10000);
    const onMsg = (e) => {
      const d = e.data;
      if (d && d.type === "decryp_msg_ans_ed") {
        clearTimeout(timer);
        worker.removeEventListener("message", onMsg);
        resolve(d.resData);
      }
    };
    worker.addEventListener("message", onMsg);
    worker.postMessage({ type: "decryp_msg_ans", resData: { data: payload } });
  });
  return {
    ok: true,
    plain,
    hasExp: /"answerExpObj":\\{/.test(html),
    hasListenText: /"hasListeningText":\\s*true/.test(html),
  };
})()`;

const main = async () => {
  const papers = JSON.parse(await readFile(join(ROOT, "data", "papers.json"), "utf8"));
  const list = (Array.isArray(papers) ? papers : papers.papers).map((p) => p.id);
  const todo = ONLY ? list.filter((id) => id === ONLY) : list;

  const store = existsSync(OUT) ? JSON.parse(await readFile(OUT, "utf8")) : {};
  const { evaluate, close } = await connect(PORT);
  const origin = await evaluate("location.origin");

  let ok = 0, empty = 0, fail = 0;
  for (const [i, id] of todo.entries()) {
    const tag = `[${i + 1}/${todo.length}] ${id}`;
    if (store[id]?.answers?.length) {
      console.log(`${tag} 已有 ${store[id].answers.length} 条，跳过`);
      continue;
    }
    let result;
    try {
      result = await evaluate(PAGE_FETCH(`/${id}`));
    } catch (e) {
      console.log(`${tag} 请求失败 ${e.message.slice(0, 80)}`);
      fail++;
      await sleep(DELAY * 2);
      continue;
    }
    if (!result?.ok) {
      if (result?.error === "no newAnswer" && result.hasAnswerBtn) {
        console.log(`${tag} 无答案（老卷，站点也不提供）`);
        store[id] = { answers: [], note: "站点无答案" };
        empty++;
      } else {
        console.log(`${tag} ${JSON.stringify(result).slice(0, 120)}`);
        fail++;
      }
      await sleep(DELAY);
      continue;
    }
    const answers = result.plain?.data ?? result.plain;
    if (!Array.isArray(answers) || !answers.length) {
      console.log(`${tag} 解出空数据 ${JSON.stringify(result.plain).slice(0, 100)}`);
      fail++;
    } else {
      store[id] = {
        answers,
        count: answers.length,
        hasExp: result.hasExp,
        hasListenText: result.hasListenText,
        fetchedAt: new Date().toISOString(),
      };
      ok++;
      console.log(`${tag} ${answers.length} 条  ${answers.slice(0, 5).join(" ")} …`);
    }
    // 每取 10 套落一次盘，断了不白跑
    if ((i + 1) % 10 === 0) await writeFile(OUT, JSON.stringify(store, null, 1));
    await sleep(DELAY);
  }

  await mkdir(join(ROOT, "data"), { recursive: true });
  await writeFile(OUT, JSON.stringify(store, null, 1));
  console.log(`\n完成：成功 ${ok}，无答案 ${empty}，失败 ${fail}，累计 ${Object.keys(store).length} 套`);
  close();
};

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
