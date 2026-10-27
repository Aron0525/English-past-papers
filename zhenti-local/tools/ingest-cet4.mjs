#!/usr/bin/env node
/**
 * 把本地收集的四级真题（E:\workbuddy\仓库\rea\cet4\CET4_近十年）灌进工作台。
 *
 * 源结构：
 *   CET4_近十年/<YYYY-MM>/第N套/{试卷,答案解析,听力}/*.pdf|*.m4a|*.mp3
 * 目标结构（与六级完全一致，阅读器不用改）：
 *   data/cet4/<YYYY-MM>/<NN>/{read.pdf, analysis.pdf, listen.m4a|mp3, meta.json}
 *
 * 只复制 / 硬链接，不动源目录里的任何文件。
 * papers.json 只做增量：补 exam 条目、补/覆盖本套记录，不动六级。
 *
 * 用法
 *   node tools/ingest-cet4.mjs --dry
 *   node tools/ingest-cet4.mjs
 */
import { mkdir, readFile, readdir, rename, stat, writeFile, link, copyFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(here, "..");
const DATA_DIR = join(ROOT, "data");
const SRC_ROOT = resolve(ROOT, "../cet4/CET4_近十年");

const argv = process.argv.slice(2);
const DRY = argv.includes("--dry");

const EXAM = {
  id: "cet4",
  name: "大学英语四级",
  short: "四级",
  source: "E:\\workbuddy\\仓库\\rea\\cet4\\CET4_近十年",
};

const CN_SET = { 一: 1, 二: 2, 三: 3, 四: 4 };

const pad2 = (n) => String(n).padStart(2, "0");

/** 「第1套」「第一套」→ 1 */
const setNumberOf = (name) => {
  const m = name.match(/第\s*([一二三四1-9])\s*套/);
  if (!m) return null;
  return CN_NUM(m[1]) ?? Number(m[1]);
};
const CN_NUM = (ch) => CN_SET[ch] ?? null;

/** 考次月份 → 上下半年标签。非 6/12 的（2020-07 / 2020-09 / 2022-09 / 2023-03）是延期加考。 */
const groupLabelOf = (period) => {
  const [year, month] = period.split("-");
  const m = Number(month);
  if (m === 6) return `${year}年 - 上半年`;
  if (m === 12) return `${year}年 - 下半年`;
  return `${year}年 - 加考（${m}月）`;
};

const titleOf = (period, set) => {
  const [year, month] = period.split("-");
  return `${year}年${Number(month)}月英语四级真题(第${Number(set)}套)`;
};

const human = (bytes) => {
  if (!bytes) return "?";
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${bytes} B`;
};

/** 同一分区优先硬链接（省一半磁盘），失败退回真复制。 */
const place = async (src, dest) => {
  if (existsSync(dest)) {
    const s = await stat(dest);
    const o = await stat(src);
    if (s.size === o.size) return { skipped: true, bytes: s.size, mode: "existing" };
  }
  await mkdir(dirname(dest), { recursive: true });
  try {
    await link(src, dest);
    return { bytes: (await stat(dest)).size, mode: "link" };
  } catch {
    await copyFile(src, dest);
    return { bytes: (await stat(dest)).size, mode: "copy" };
  }
};

/** 目录里按扩展名挑文件；pick 用来在多个候选里选一个（默认取体积最大的）。 */
const pickFile = async (dir, exts, prefer = null) => {
  if (!existsSync(dir)) return null;
  const names = (await readdir(dir)).filter((name) => exts.includes(name.split(".").pop().toLowerCase()));
  if (!names.length) return null;
  if (prefer) {
    const hit = names.find((n) => prefer.test(n));
    if (hit) return join(dir, hit);
  }
  const sized = await Promise.all(names.map(async (name) => ({ name, size: (await stat(join(dir, name))).size })));
  sized.sort((a, b) => b.size - a.size);
  return join(dir, sized[0].name);
};

/* ---------------- 扫描源目录 ---------------- */

if (!existsSync(SRC_ROOT)) {
  console.error(`找不到四级源目录：${SRC_ROOT}`);
  process.exit(1);
}

const periods = (await readdir(SRC_ROOT, { withFileTypes: true }))
  .filter((d) => d.isDirectory() && /^\d{4}-\d{2}$/.test(d.name))
  .map((d) => d.name)
  .sort();

const tasks = [];
for (const period of periods) {
  const sets = (await readdir(join(SRC_ROOT, period), { withFileTypes: true }))
    .filter((d) => d.isDirectory() && /^第\s*[一二三四1-9]\s*套$/.test(d.name));
  for (const setDir of sets) {
    const set = setNumberOf(setDir.name);
    if (!set) continue;
    const base = join(SRC_ROOT, period, setDir.name);
    const paper = await pickFile(join(base, "试卷"), ["pdf"]);
    const analysis = await pickFile(join(base, "答案解析"), ["pdf"]);
    const audio = (await pickFile(join(base, "听力"), ["m4a"]))
      ?? (await pickFile(join(base, "听力"), ["mp3"]));
    const script = await pickFile(join(base, "听力"), ["pdf"], /原文/);
    tasks.push({ period, set: pad2(set), base, paper, analysis, audio, script });
  }
}
tasks.sort((a, b) => (a.period === b.period ? a.set.localeCompare(b.set) : b.period.localeCompare(a.period)));

const missingPaper = tasks.filter((t) => !t.paper).length;
console.log(`源目录 ${SRC_ROOT}`);
console.log(`扫到 ${tasks.length} 套（缺试卷 ${missingPaper} 套）\n`);

let bytes = 0;
for (const t of tasks) {
  const flags = [
    t.paper ? "试卷✓" : "试卷✗",
    t.analysis ? "解析✓" : "解析✗",
    t.audio ? (t.audio.endsWith(".m4a") ? "听力✓m4a" : "听力✓mp3") : "听力✗",
    t.script ? "原文✓" : "原文✗",
  ].join(" ");
  console.log(`  cet4/${t.period}/${t.set}  ${flags}`);
}
console.log("");

if (DRY) {
  console.log("--dry 只扫描，未写入");
  process.exit(0);
}

/* ---------------- 落盘 ---------------- */

const index = JSON.parse(await readFile(join(DATA_DIR, "papers.json"), "utf8"));
index.exams = index.exams ?? [];
if (!index.exams.some((e) => e.id === EXAM.id)) {
  index.exams.push({ id: EXAM.id, name: EXAM.name, short: EXAM.short, source: EXAM.source });
}
if (!index.groupOrder) {
  index.groupOrder = ["cet6", "cet4", "tem4", "tem8"];
}
const byId = new Map((index.papers ?? []).map((p) => [p.id, p]));
index.papers = index.papers ?? [];

const latestPeriod = periods.filter((p) => tasks.some((t) => t.period === p)).sort().pop();

let imported = 0;
const skipped = [];
for (const t of tasks) {
  const id = `${EXAM.id}/${t.period}/${t.set}`;
  if (!t.paper) {
    skipped.push(`${id} 缺试卷`);
    continue;
  }
  const dir = join(DATA_DIR, EXAM.id, t.period, t.set);
  const files = {};

  const jobs = [
    ["pdf", t.paper, "read.pdf", "pdf"],
    ["analysis", t.analysis, "analysis.pdf", "pdf"],
    ["audio", t.audio, t.audio ? `listen.${t.audio.split(".").pop().toLowerCase()}` : null, "audio"],
    ["script", t.script, "listen-script.pdf", "pdf"],
  ];
  for (const [kind, src, name, group] of jobs) {
    if (!src || !name) continue;
    const result = await place(src, join(dir, name));
    files[kind] = {
      name,
      bytes: result.bytes,
      format: name.split(".").pop().toLowerCase(),
      origin: src,
      originalName: basename(src),
      linkMode: result.mode,
    };
    bytes += result.bytes;
    console.log(`  ${result.skipped ? "已有" : result.mode === "link" ? "链接" : "复制"} ${id}/${name} ${human(result.bytes)}`);
  }

  const metaPath = join(dir, "meta.json");
  const oldMeta = existsSync(metaPath) ? JSON.parse(await readFile(metaPath, "utf8")) : {};
  const meta = {
    ...oldMeta,
    id,
    exam: EXAM.id,
    period: t.period,
    set: t.set,
    title: titleOf(t.period, t.set),
    source: t.base,
    files,
    capabilities: {
      answers: existsSync(join(dir, "answers.json")),
      analysis: Boolean(files.analysis),
      audio: Boolean(files.audio),
      listeningText: Boolean(files.script),
      sentenceTranslation: false,
      ...(oldMeta.capabilities ?? {}),
    },
    ingestedFrom: "cet4/CET4_近十年（本地收集）",
    ingestedAt: new Date().toISOString(),
  };
  await writeFile(`${metaPath}.tmp`, `${JSON.stringify(meta, null, 2)}\n`, "utf8");
  await rename(`${metaPath}.tmp`, metaPath);

  const record = {
    id,
    exam: EXAM.id,
    period: t.period,
    set: t.set,
    title: meta.title,
    group: `${t.period.split("-")[0]}年${Number(t.period.split("-")[1])}月`,
    groupLabel: groupLabelOf(t.period),
    latest: t.period === latestPeriod,
    source: t.base,
    files: {
      ...(files.pdf ? { pdf: { name: "read.pdf", bytes: files.pdf.bytes } } : {}),
      ...(files.analysis ? { analysis: { name: "analysis.pdf", bytes: files.analysis.bytes } } : {}),
      ...(files.audio ? { audio: { name: files.audio.name, bytes: files.audio.bytes } } : {}),
    },
    localOrigin: true,
  };
  const old = byId.get(id);
  if (old) Object.assign(old, record);
  else index.papers.push(record);
  imported += 1;
}

// 新 → 旧，同级按套号
index.papers.sort((a, b) => {
  const order = index.groupOrder ?? [];
  const ea = order.indexOf(a.exam);
  const eb = order.indexOf(b.exam);
  if (ea !== eb && ea >= 0 && eb >= 0) return ea - eb;
  if (a.period !== b.period) return String(b.period).localeCompare(String(a.period));
  return String(a.set).localeCompare(String(b.set));
});

const indexPath = join(DATA_DIR, "papers.json");
await writeFile(`${indexPath}.tmp`, `${JSON.stringify(index, null, 2)}\n`, "utf8");
await rename(`${indexPath}.tmp`, indexPath);

const cet4Count = index.papers.filter((p) => p.exam === "cet4").length;
console.log(`\n导入 ${imported} 套，共 ${human(bytes)}；papers.json 现有 ${index.papers.length} 套（四级 ${cet4Count}）`);
if (skipped.length) {
  console.log("\n跳过");
  for (const line of skipped) console.log(`  ${line}`);
}
