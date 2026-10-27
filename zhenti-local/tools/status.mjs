/**
 * 只读体检：题库 / 已收录套卷 / 学习数据的状态一览。
 *
 * **这个脚本不写任何文件、不删任何东西**（以前的 final-check / reset-demo 会删数据，
 * 已经移除）。直接读文件系统，服务器不开也能跑：
 *   node tools/status.mjs
 */
import { readFileSync, readdirSync, existsSync, statSync } from "node:fs";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const DATA = join(ROOT, "data");

const readJson = (path, fallback) => {
  try {
    return JSON.parse(readFileSync(path, "utf8"));
  } catch {
    return fallback;
  }
};
const text = (path) => {
  try {
    return readFileSync(path, "utf8");
  } catch {
    return "";
  }
};
const human = (bytes) => (bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(2)} MB` : `${(bytes / 1024).toFixed(1)} KB`);
const clock = (seconds) => `${String(Math.floor((seconds ?? 0) / 60)).padStart(2, "0")}:${String(Math.floor((seconds ?? 0) % 60)).padStart(2, "0")}`;

const index = readJson(join(DATA, "papers.json"), { papers: [] });
const wordbook = readJson(join(DATA, "study", "wordbook.json"), []);
const wrongbook = readJson(join(DATA, "study", "wrong.json"), []);

const line = (label, value) => console.log(`${label.padEnd(14)}${value}`);

const AUDIO_FILES = ["listen.mp3", "listen.m4a", "listen.wav"];

/** 本套没有独立音频时，看 meta.audioRef 指向的同考次那套有没有（官方多套卷共用听力素材）。 */
const findAudio = (id) => {
  const dir = join(DATA, id);
  const own = AUDIO_FILES.find((name) => existsSync(join(dir, name)));
  if (own) return { path: join(dir, own), from: null };
  const ref = readJson(join(dir, "meta.json"), null)?.audioRef;
  if (typeof ref === "string" && /^[a-z0-9]+\/\d{4}-\d{2}\/[0-9a-z]+$/i.test(ref)) {
    const shared = AUDIO_FILES.find((name) => existsSync(join(DATA, ref, name)));
    if (shared) return { path: join(DATA, ref, shared), from: ref };
  }
  return { path: null, from: null };
};

console.log("=== 索引 ===");
const groups = new Set((index.papers ?? []).map((paper) => paper.groupLabel ?? paper.period));
line("套卷", `${(index.papers ?? []).length} 套 / ${groups.size} 个半年分组`);
line("范围", `${index.papers?.at(-1)?.period ?? "?"} → ${index.papers?.[0]?.period ?? "?"}`);
line("来源", index.source ?? "(未记录)");

const locals = (index.papers ?? []).filter((paper) => existsSync(join(DATA, paper.id, "read.pdf")));
console.log("\n=== 已收录（本地有正文）===");
if (locals.length === 0) {
  console.log("(还没有任何一套；把 read.pdf 放进 data/<考试>/<年-月>/<套号>/ 即可)");
}
for (const paper of locals) {
  const dir = join(DATA, paper.id);
  const pdf = join(dir, "read.pdf");
  const audio = findAudio(paper.id);
  const notes = text(join(dir, "notes.md")).trim();
  const progress = readJson(join(dir, "progress.json"), null);
  const sheet = readJson(join(dir, "sheet.json"), null);
  const answers = readJson(join(dir, "answers.json"), null);

  console.log(`\n  ${paper.title}  [${paper.id}]`);
  const audioText = audio.path
    ? ` · 听力 ${human(statSync(audio.path).size)}${audio.from ? `（复用 ${audio.from}）` : ""}`
    : " · 无听力";
  const analysis = join(dir, "analysis.pdf");
  console.log(`    正文  ${human(statSync(pdf).size)}${audioText}${existsSync(analysis) ? ` · 解析 ${human(statSync(analysis).size)}` : ""}`);
  console.log(`    笔记  ${notes ? `${notes.split("\n").length} 行 / ${notes.length} 字` : "空"}`);
  console.log(`    进度  ${progress ? `第 ${progress.page ?? 1} 页 · 听力 ${clock(progress.audioTime)} · 缩放 ${progress.scale ?? 1}` : "无（读第 1 页起）"}`);
  const answered = sheet?.answers ? Object.values(sheet.answers).filter(Boolean).length : 0;
  console.log(`    答题卡 ${sheet ? `已答 ${answered} / ${sheet.count ?? 55}` : "无"}`);
  if (answers) {
    const keys = Object.keys(answers).filter((key) => /^\d+$/.test(key));
    let right = 0;
    let scored = 0;
    for (const key of keys) {
      const mine = sheet?.answers?.[key];
      if (!mine) continue;
      scored += 1;
      if (mine === String(answers[key]).trim().toUpperCase()) right += 1;
    }
    console.log(`    答案  ${keys.length} 题${scored ? ` · 已判 ${scored} 题（对 ${right}）` : ""}`);
  } else {
    console.log("    答案  未提供（answers.json 缺失，无法判分）");
  }
}

console.log("\n=== 学习数据（跨套）===");
line("生词本", `${wordbook.length} 条${wordbook.length ? ` · 最近 ${wordbook.at(-1)?.word ?? "?"}` : ""}`);
line("错题本", `${wrongbook.length} 条${wrongbook.length ? ` · 最近第 ${wrongbook.at(-1)?.q ?? "?"} 题` : ""}`);

const digest = join(DATA, "notes-all.md");
line("复习总纲", existsSync(digest) ? `${human(statSync(digest).size)}（node tools/collect-notes.mjs 可刷新）` : "未生成");

const studyDir = join(DATA, "study");
line("study 目录", existsSync(studyDir) ? `${readdirSync(studyDir).join(", ") || "空"}` : "不存在");

console.log("\n（以上为只读统计，未修改任何文件）");
