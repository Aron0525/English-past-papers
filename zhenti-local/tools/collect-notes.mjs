/**
 * 把所有套卷的笔记 / 错题 / 生词汇总成一份复习总纲：data/notes-all.md
 *
 * 直接读文件系统，不需要服务在跑。
 *   node tools/collect-notes.mjs
 */
import { readFileSync, readdirSync, existsSync, writeFileSync, statSync } from "node:fs";
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
const readText = (path) => {
  try {
    return readFileSync(path, "utf8");
  } catch {
    return "";
  }
};

const index = readJson(join(DATA, "papers.json"), { papers: [] });
const wordbook = readJson(join(DATA, "study", "wordbook.json"), []);
const wrongbook = readJson(join(DATA, "study", "wrong.json"), []);

const clock = (seconds) => {
  const total = Math.floor(Number(seconds) || 0);
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
};

const sections = [];
const usedWrong = new Set();
const usedWords = new Set();

for (const paper of index.papers ?? []) {
  const dir = join(DATA, paper.id);
  if (!existsSync(join(dir, "read.pdf"))) continue;

  const notes = readText(join(dir, "notes.md")).trim();
  const progress = readJson(join(dir, "progress.json"), null);
  const sheet = readJson(join(dir, "sheet.json"), null);
  const answers = readJson(join(dir, "answers.json"), null);

  const wrongs = wrongbook.filter((entry) => String(entry.key ?? "").startsWith(`${paper.id}::`));
  const words = wordbook.filter((entry) => String(entry.key ?? "").startsWith(`${paper.id}::`));
  wrongs.forEach((entry) => usedWrong.add(entry.key));
  words.forEach((entry) => usedWords.add(entry.key));

  const answered = sheet?.answers ? Object.values(sheet.answers).filter(Boolean).length : 0;
  const hasKey = answers && Object.keys(answers).some((key) => /^\d+$/.test(key));

  // 判分（有标准答案才算）
  let score = null;
  if (hasKey && sheet?.answers) {
    let right = 0;
    let scored = 0;
    for (const [q, mine] of Object.entries(sheet.answers)) {
      if (!mine || typeof answers[q] !== "string") continue;
      scored += 1;
      if (mine === answers[q].trim().toUpperCase()) right += 1;
    }
    score = { right, scored, rate: scored ? Math.round((right / scored) * 100) : 0 };
  }

  if (!notes && wrongs.length === 0 && words.length === 0 && !progress && answered === 0) continue;

  const meta = [
    `\`${paper.id}\``,
    progress && (progress.page > 1 || progress.audioTime > 5)
      ? `读到第 ${progress.page} 页 · 听力 ${clock(progress.audioTime)}`
      : null,
    answered ? `已答 ${answered}/${sheet.count ?? 55}` : null,
    score ? `得分 ${score.right}/${score.scored}（${score.rate}%）` : null,
  ].filter(Boolean);

  const block = [`## ${paper.title}`, "", meta.join(" · "), ""];

  // 笔记里的标题要降级，否则 H1 会插到 ### 笔记 上面，破坏总纲的层级
  const demote = (text) => text.replace(/^(#{1,6})(\s)/gm, (_, hashes, space) => "#".repeat(Math.min(hashes.length + 3, 6)) + space);

  if (notes) block.push("### 笔记", "", demote(notes), "");
  if (wrongs.length) {
    block.push("### 错题", "");
    for (const entry of wrongs.sort((a, b) => Number(a.q) - Number(b.q))) {
      const detail = [entry.answer ? `我 ${entry.answer}` : null, entry.correct ? `正 ${entry.correct}` : null].filter(Boolean).join(" / ");
      block.push(`- 第 ${entry.q} 题${detail ? ` · ${detail}` : ""}${entry.note ? ` —— ${entry.note}` : ""}`);
    }
    block.push("");
  }
  if (words.length) {
    block.push("### 生词", "");
    for (const entry of words.sort((a, b) => String(a.at).localeCompare(String(b.at)))) {
      block.push(`- ${entry.word}${entry.note ? ` —— ${entry.note}` : ""}`);
    }
    block.push("");
  }
  sections.push(block.join("\n"));
}

// 没挂到任何已收录套卷上的条目（例如之前收过、后来把卷删了）
const orphans = [
  ...wrongbook.filter((entry) => !usedWrong.has(entry.key)).map((entry) => `- 第 ${entry.q} 题 · ${entry.paper ?? entry.key}${entry.correct ? ` · 正 ${entry.correct}` : ""}`),
  ...wordbook.filter((entry) => !usedWords.has(entry.key)).map((entry) => `- ${entry.word} · ${entry.paper ?? entry.key}`),
];
if (orphans.length) {
  sections.push(["## 其他（未挂到已收录套卷）", "", ...orphans, ""].join("\n"));
}

const localCount = (index.papers ?? []).filter((paper) => existsSync(join(DATA, paper.id, "read.pdf"))).length;
const stamp = new Date().toISOString().slice(0, 16).replace("T", " ");
const out = [
  "# 六级复习总纲",
  "",
  `生成时间：${stamp} · 已收录 ${localCount} 套 · 生词 ${wordbook.length} · 错题 ${wrongbook.length}`,
  "",
  "> 由 `node tools/collect-notes.mjs` 自动生成，内容来自各套卷的 `notes.md` 和 `data/study/*.json`。",
  "",
  "---",
  "",
  ...sections,
].join("\n");

writeFileSync(join(DATA, "notes-all.md"), out, "utf8");

console.log("wrote data/notes-all.md");
console.log("papers with content:", sections.length, "| bytes:", statSync(join(DATA, "notes-all.md")).size);
