#!/usr/bin/env node
/**
 * 把 cet6 采集到的真题直链灌进本地题库。
 *
 * 数据源是 cet6/sources/CET6-MASTER.md（已验证直链清单），本脚本只做三件事
 *   1. 每个套次挑一条最优直链（试题 / 解析 / 听力），不重复下载同源副本
 *   2. 落到 data/cet6/<年-月>/<套号>/ 下，命名成工作台认的名字
 *   3. 给 data/papers.json 对应条目补 files 字段
 *
 * 它从不重建索引、从不删除任何文件。已存在的文件默认跳过。
 *
 * 坑（真踩过）：URL 写着 .mp3 不代表内容真是 mp3 —— cettong 的 listening.mp3
 * 文件头是 `ftyp`，实际是 M4A。所以挑选前先 Range 抓前 16 字节嗅探真实格式，
 * 落盘文件名也按真实格式来，不然浏览器按 audio/mpeg 声明去解 AAC 容器会播不了。
 *
 * 用法
 *   node tools/ingest.mjs                 # 灌全部考次
 *   node tools/ingest.mjs --year 2025     # 只灌 2025 年
 *   node tools/ingest.mjs --only 2019.06  # 只灌某个考次
 *   node tools/ingest.mjs --audio m4a     # 听力优先挑体积小的 m4a（默认优先真 mp3）
 *   node tools/ingest.mjs --dry           # 只探测并打印计划，不下载
 */

import { mkdir, readFile, rename, writeFile, stat } from "node:fs/promises";
import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(here, "..");
const DATA_DIR = join(ROOT, "data");
const CET6_DIR = join(DATA_DIR, "cet6");

const argv = process.argv.slice(2);
const flag = (name) => argv.includes(name);
const option = (name, fallback) => {
  const i = argv.indexOf(name);
  return i >= 0 && argv[i + 1] ? argv[i + 1] : fallback;
};

const DRY = flag("--dry");
const YEAR = option("--year", null);
const ONLY = option("--only", null);
const PREFER_AUDIO = option("--audio", "mp3") === "m4a" ? "m4a" : "mp3";
const MASTER_PATH = resolve(option("--master", resolve(ROOT, "../cet6/sources/CET6-MASTER.md")));
const CONCURRENCY = Math.min(Math.max(Number(option("--jobs", "3")), 1), 8);

const CN_NUM = { 一: 1, 二: 2, 三: 3, 1: 1, 2: 2, 3: 3 };
const AUDIO_EXTENSIONS = ["mp3", "m4a", "wav"];

/* ---------------- 解析总清单 ---------------- */

const parseMaster = (text) => {
  const rows = [];
  let sess = null;
  let cat = null;
  for (const line of text.split(/\r?\n/)) {
    let m = line.match(/^## CET6 (\S+)/);
    if (m) { sess = m[1]; cat = null; continue; }
    m = line.match(/^\*\*(.+?)\*\*/);
    if (m && sess) { cat = m[1]; continue; }
    m = line.match(/^- `(\S+)`\s+(.+?)\s+\[(\d+)/);
    if (m && sess && cat) rows.push({ sess, cat, url: m[1], name: m[2], status: Number(m[3]) });
  }
  return rows;
};

/** URL 里写的扩展名（总清单里 cettong 那批条目的 name 被截断成「第1套」，只有 URL 可信）。 */
const declaredExt = (row) => (row.url.split("?")[0].match(/\.([A-Za-z0-9]+)$/)?.[1] ?? "").toLowerCase();

const srcOf = (url) => {
  if (url.includes("1e5e11")) return "A";
  if (url.includes("cettong.cn")) return "B";
  if (url.includes("0609x")) return "C";
  if (url.includes("lazynote")) return "D";
  if (url.includes("hxen")) return "E";
  if (url.includes("DieDiDi")) return "G";
  if (url.includes("NEUQNPEE")) return "H";
  if (url.includes("jianmou23")) return "I";
  if (url.includes("zhiyuanstudent")) return "J";
  if (url.includes("Drhm1224")) return "M";
  return "Z";
};

/**
 * 认出这条直链属于第几套。返回数组，因为存在合订本
 * （`cet6_2022_09_2-3.pdf` 一份文件同时是第 2 套和第 3 套）。
 * 认不出来返回空数组 —— 宁可漏一条，也不要把合订本错配成某一套。
 */
const setsOf = (row) => {
  const decoded = (() => {
    try { return decodeURIComponent(row.url); } catch { return row.url; }
  })();
  const hay = `${row.name} ${decoded}`;

  let m = decoded.match(/\/cet6\/(\d{4})_(\d{2})_(\d)(?![0-9])/);
  if (m) return [Number(m[3])];

  m = decoded.match(/cet6_(\d{4})_(\d{2})_(\d)(?:-(\d))?(?=[_.\-])/);
  if (m) {
    const from = Number(m[3]);
    const to = m[4] ? Number(m[4]) : from;
    const out = [];
    for (let i = from; i <= to && i <= 9; i += 1) out.push(i);
    return out;
  }

  m = hay.match(/第\s*([1-3一二三])\s*套/);
  if (m) return [CN_NUM[m[1]]].filter(Boolean);

  // 「全 1 套」是官方只发一套的考次（2020.07），可以当第 1 套；
  // 「全 3 套」是三套合订本，不映射到任何单独一套。
  m = hay.match(/全\s*([1-9一二三])\s*套/);
  if (m) {
    const n = CN_NUM[m[1]];
    return n === 1 ? [1] : [];
  }
  return [];
};

/* ---------------- 格式嗅探 ---------------- */

/** 抓前 16 字节看真实格式，顺便拿到 content-length。 */
const sniff = async (url) => {
  try {
    const res = await fetch(url, { headers: { Range: "bytes=0-15" }, signal: AbortSignal.timeout(60_000) });
    if (!res.ok && res.status !== 206) return null;
    const buf = Buffer.from(await res.arrayBuffer());
    const total = Number(res.headers.get("content-range")?.split("/")[1] ?? res.headers.get("content-length") ?? 0);
    return { magic: buf, bytes: total };
  } catch {
    return null;
  }
};

const formatOf = (buf) => {
  if (buf.length < 8) return "unknown";
  if (buf.subarray(0, 4).toString("latin1") === "%PDF") return "pdf";
  if (buf.subarray(4, 8).toString("latin1") === "ftyp") return "m4a";
  if (buf.subarray(0, 3).toString("latin1") === "ID3") return "mp3";
  if (buf[0] === 0xff && (buf[1] & 0xe0) === 0xe0) return "mp3";
  if (buf.subarray(0, 4).toString("latin1") === "RIFF") return "wav";
  if (buf.subarray(0, 2).toString("latin1") === "PK") return "zip";
  return "unknown";
};

/* ---------------- 挑选规则 ---------------- */

// A=1e5e11（最全，含音频）C=0609x B=cettong（三件套规整但音频名不实）其余兜底
const SRC_ORDER = ["A", "C", "B", "D", "E", "G", "H", "I", "J", "M", "Z"];
const rank = (row) => SRC_ORDER.indexOf(srcOf(row.url));

/** 先嗅探再挑：真实格式对得上才入选，同格式内按源序。 */
const pickByFormat = async (rows, wanted) => {
  const probed = await Promise.all(rows.map(async (row) => {
    const hit = await sniff(row.url);
    return { row, format: hit ? formatOf(hit.magic) : "unknown", bytes: hit?.bytes ?? 0 };
  }));
  const score = (entry) => wanted.indexOf(entry.format);
  const usable = probed.filter((e) => score(e) >= 0);
  const pool = usable.length ? usable : probed.filter((e) => e.format !== "unknown");
  if (!pool.length) return null;
  pool.sort((a, b) => {
    const sa = score(a);
    const sb = score(b);
    if (sa !== sb) return (sa < 0 ? 99 : sa) - (sb < 0 ? 99 : sb);
    return rank(a.row) - rank(b.row);
  });
  return pool[0];
};

const pickAudio = (rows) => {
  const wanted = PREFER_AUDIO === "m4a" ? ["mp3", "m4a", "wav"] : ["mp3", "m4a", "wav"];
  return pickByFormat(rows, wanted);
};

/* ---------------- 下载 ---------------- */

const sha256 = (buf) => createHash("sha256").update(buf).digest("hex");

const download = async (url, dest) => {
  if (existsSync(dest)) {
    // 已存在也顺手算一遍校验和，否则索引里会留着「未重算」这种占位值
    const buf = await readFile(dest);
    return { skipped: true, bytes: buf.length, sha256: sha256(buf), format: formatOf(buf.subarray(0, 16)) };
  }
  let lastError;
  // raw.githubusercontent 对并发很敏感，大文件经常被重置（表现为 terminated）。
  // 多给几次机会，并且逐次退避，别一上来就把连接打满。
  for (let attempt = 0; attempt < 5; attempt += 1) {
    if (attempt) await new Promise((done) => setTimeout(done, 1500 * attempt));
    try {
      const res = await fetch(url, { signal: AbortSignal.timeout(300_000) });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const buf = Buffer.from(await res.arrayBuffer());
      if (!buf.length) throw new Error("空文件");
      await mkdir(dirname(dest), { recursive: true });
      await writeFile(`${dest}.part`, buf);
      await rename(`${dest}.part`, dest);
      return { bytes: buf.length, sha256: sha256(buf), format: formatOf(buf.subarray(0, 16)) };
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError;
};

const human = (bytes) => {
  if (!bytes) return "?";
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${bytes} B`;
};

/* ---------------- 主流程 ---------------- */

const index = JSON.parse(await readFile(join(DATA_DIR, "papers.json"), "utf8"));
const papers = index.papers ?? [];
const byId = new Map(papers.map((p) => [p.id, p]));

const rows = parseMaster(await readFile(MASTER_PATH, "utf8"));

const grouped = new Map();
for (const row of rows) {
  if (row.status !== 200 && row.status !== 206) continue;
  for (const set of setsOf(row)) {
    const key = `${row.sess}#${set}`;
    if (!grouped.has(key)) grouped.set(key, { sess: row.sess, set, 试题: [], 解析: [], 听力: [] });
    grouped.get(key)[row.cat]?.push(row);
  }
}

const candidates = [];
for (const group of grouped.values()) {
  const period = group.sess.replace(".", "-");
  if (YEAR && !period.startsWith(YEAR)) continue;
  if (ONLY && group.sess !== ONLY) continue;
  const setId = String(group.set).padStart(2, "0");
  const id = `cet6/${period}/${setId}`;
  const paper = byId.get(id);
  if (!paper) continue; // 只灌索引里真实存在的套卷，不凭空造目录
  candidates.push({ id, period, set: setId, title: paper.title, paper, group });
}
candidates.sort((a, b) => a.id.localeCompare(b.id));

console.log(`候选 ${candidates.length} 套，正在嗅探真实格式…（数据源 ${MASTER_PATH}）\n`);

// 嗅探要联网，小并发跑
const targets = [];
const probeQueue = [...candidates];
const probeWorkers = Array.from({ length: Math.min(CONCURRENCY, 4) }, async () => {
  for (;;) {
    const item = probeQueue.shift();
    if (!item) return;
    const [pdf, analysis, audio] = await Promise.all([
      item.group.试题.length ? pickByFormat(item.group.试题, ["pdf"]) : null,
      item.group.解析.length ? pickByFormat(item.group.解析, ["pdf"]) : null,
      item.group.听力.length ? pickAudio(item.group.听力) : null,
    ]);
    targets.push({ ...item, pdf, analysis, audio });
  }
});
await Promise.all(probeWorkers);
targets.sort((a, b) => a.id.localeCompare(b.id));

let plannedBytes = 0;
for (const t of targets) {
  const cell = (entry, label) => (entry ? `${label}✓${entry.format}${entry.bytes ? `(${human(entry.bytes)})` : ""}` : `${label}✗`);
  plannedBytes += (t.pdf?.bytes ?? 0) + (t.analysis?.bytes ?? 0) + (t.audio?.bytes ?? 0);
  console.log(`  ${t.id}  ${cell(t.pdf, "试题")}  ${cell(t.analysis, "解析")}  ${cell(t.audio, "听力")}`);
}
console.log(`\n预计下载 ${human(plannedBytes)}`);

if (DRY) {
  console.log("--dry 只探测，未下载");
  process.exit(0);
}

let ok = 0;
let failed = 0;
const errors = [];

const runOne = async (t) => {
  const dir = join(CET6_DIR, t.period, t.set);
  await mkdir(dir, { recursive: true });
  const files = {};

  // 文件名按真实格式命名：URL 写 .mp3 实际是 m4a 的情况真的存在
  const jobs = [
    ["pdf", t.pdf, "read.pdf"],
    ["analysis", t.analysis, "analysis.pdf"],
    ["audio", t.audio, t.audio ? `listen.${t.audio.format === "wav" ? "wav" : t.audio.format}` : null],
  ];
  for (const [kind, entry, filename] of jobs) {
    if (!entry || !filename) continue;
    if (entry.format === "unknown") { errors.push(`${t.id}/${filename} 格式不明，跳过`); continue; }
    const dest = join(dir, filename);
    try {
      const result = await download(entry.row.url, dest);
      const finalFormat = result.format ?? entry.format;
      files[kind] = {
        name: filename,
        bytes: result.bytes,
        sha256: result.sha256 ?? "(已有文件，未重算)",
        format: finalFormat,
        declaredExt: declaredExt(entry.row),
        source: srcOf(entry.row.url),
        url: entry.row.url,
        originalName: entry.row.name,
      };
      console.log(`  ${result.skipped ? "跳过" : "下载"} ${t.id}/${filename} ${human(result.bytes)} [${finalFormat}]`);
    } catch (error) {
      failed += 1;
      errors.push(`${t.id}/${filename} 失败 ${error.message}`);
      console.log(`  失败 ${t.id}/${filename} ${error.message}`);
    }
  }

  // meta.json：已存在就合并，绝不整体覆盖
  const metaPath = join(dir, "meta.json");
  const oldMeta = existsSync(metaPath) ? JSON.parse(await readFile(metaPath, "utf8")) : {};
  const meta = {
    ...oldMeta,
    id: t.id,
    exam: "cet6",
    period: t.period,
    set: t.set,
    title: t.title,
    source: t.paper.source,
    files,
    assets: {
      ...(oldMeta.assets ?? {}),
      pdfUrl: files.pdf?.url ?? oldMeta.assets?.pdfUrl,
      analysisUrl: files.analysis?.url ?? oldMeta.assets?.analysisUrl,
      audioUrl: files.audio?.url ?? oldMeta.assets?.audioUrl,
    },
    capabilities: {
      answers: existsSync(join(dir, "answers.json")),
      listeningText: false,
      sentenceTranslation: false,
    },
    ingestedFrom: "cet6/sources/CET6-MASTER.md",
    ingestedAt: new Date().toISOString(),
  };
  await writeFile(`${metaPath}.tmp`, `${JSON.stringify(meta, null, 2)}\n`, "utf8");
  await rename(`${metaPath}.tmp`, metaPath);

  // papers.json 只补 files 字段，其它字段一律不动
  if (files.pdf || files.audio || files.analysis) {
    t.paper.files = {
      ...(t.paper.files ?? {}),
      ...(files.pdf ? { pdf: { name: files.pdf.name, bytes: files.pdf.bytes, sha256: files.pdf.sha256 } } : {}),
      ...(files.audio ? { audio: { name: files.audio.name, bytes: files.audio.bytes, sha256: files.audio.sha256 } } : {}),
      ...(files.analysis ? { analysis: { name: files.analysis.name, bytes: files.analysis.bytes, sha256: files.analysis.sha256 } } : {}),
    };
    t.paper.verifiedAt = new Date().toISOString();
  }
  ok += 1;
};

const queue = [...targets];
const workers = Array.from({ length: CONCURRENCY }, async () => {
  for (;;) {
    const next = queue.shift();
    if (!next) return;
    await runOne(next);
  }
});
await Promise.all(workers);

/**
 * 官方多套卷共用同一份听力素材，采集源里第 2、3 套经常没有独立音频。
 * 收尾时给这些套卷写 audioRef，指到同考次里真有音频的那一套，服务端会顺着它找文件。
 */
const hasOwnAudio = (t) =>
  AUDIO_EXTENSIONS.some((ext) => existsSync(join(CET6_DIR, t.period, t.set, `listen.${ext}`)));

let sharedCount = 0;
for (const t of targets) {
  if (hasOwnAudio(t)) continue;
  const donor = targets.find((o) => o !== t && o.period === t.period && hasOwnAudio(o));
  if (!donor) continue;
  const metaPath = join(CET6_DIR, t.period, t.set, "meta.json");
  const meta = existsSync(metaPath) ? JSON.parse(await readFile(metaPath, "utf8")) : {};
  if (meta.audioRef === donor.id) continue;
  meta.audioRef = donor.id;
  meta.audioRefNote = "本套没有独立可下载音频，复用同考次听力素材";
  await writeFile(`${metaPath}.tmp`, `${JSON.stringify(meta, null, 2)}\n`, "utf8");
  await rename(`${metaPath}.tmp`, metaPath);
  sharedCount += 1;
  console.log(`  复用听力 ${t.id} ← ${donor.id}`);
}
if (sharedCount) console.log(`\n${sharedCount} 套没有独立音频，已指向同考次的音频`);

// 原子写回索引
const indexPath = join(DATA_DIR, "papers.json");
await writeFile(`${indexPath}.tmp`, `${JSON.stringify(index, null, 2)}\n`, "utf8");
await rename(`${indexPath}.tmp`, indexPath);

console.log(`\n完成 ${ok} 套，失败 ${failed} 项，索引仍是 ${papers.length} 套`);
if (errors.length) {
  console.log("\n失败明细");
  for (const line of errors) console.log(`  ${line}`);
}
