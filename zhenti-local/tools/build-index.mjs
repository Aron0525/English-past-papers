/**
 * 校验并补全索引：扫描 data/ 里**已经存在**的套卷，把文件大小 + sha256 补进
 * data/papers.json 的对应条目，同时刷新该套自己的 meta.json。
 *
 * 重要：**只补字段，绝不重建或清空 papers.json**。83 套的元数据来自对站点列表页的勘察，
 * 是这套索引的根基；旧版本会把 papers.json 覆盖成单套，那是个数据毁灭级的 bug，已改掉。
 *
 *   node tools/build-index.mjs                 # 处理所有已收录套卷
 *   node tools/build-index.mjs cet6/2025-12/01 # 只处理一套
 */
import { createHash } from "node:crypto";
import { readFileSync, writeFileSync, existsSync, statSync } from "node:fs";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const DATA = join(ROOT, "data");
const INDEX = join(DATA, "papers.json");
const only = process.argv[2] ?? null;

const index = JSON.parse(readFileSync(INDEX, "utf8"));
const sha256 = (path) => createHash("sha256").update(readFileSync(path)).digest("hex");
const stamp = () => new Date().toISOString();

let touched = 0;

for (const paper of index.papers) {
  if (only && paper.id !== only) continue;

  const dir = join(DATA, paper.id);
  const pdf = join(dir, "read.pdf");
  const audio = join(dir, "listen.mp3");
  if (!existsSync(pdf)) continue;

  paper.files = {
    pdf: { name: "read.pdf", bytes: statSync(pdf).size, sha256: sha256(pdf) },
    ...(existsSync(audio) ? { audio: { name: "listen.mp3", bytes: statSync(audio).size, sha256: sha256(audio) } } : {}),
  };
  paper.verifiedAt = stamp();

  // meta.json 是"这一套自己的档案"，同样只补不建
  const metaPath = join(dir, "meta.json");
  const meta = existsSync(metaPath)
    ? JSON.parse(readFileSync(metaPath, "utf8"))
    : { id: paper.id, title: paper.title, source: paper.source };
  meta.files = paper.files;
  meta.verifiedAt = paper.verifiedAt;
  writeFileSync(metaPath, `${JSON.stringify(meta, null, 2)}\n`, "utf8");

  touched += 1;
  const audioPart = paper.files.audio ? ` / ${paper.files.audio.bytes.toLocaleString()} B mp3` : " / （无听力）";
  console.log(`ok   ${paper.id}  ${paper.files.pdf.bytes.toLocaleString()} B pdf${audioPart}`);
}

if (touched === 0) {
  console.log("没有找到可校验的套卷（需要有 read.pdf）");
} else {
  writeFileSync(INDEX, `${JSON.stringify(index, null, 2)}\n`, "utf8");
}

console.log(`\n已更新 ${touched} 套；索引仍是 ${index.papers.length} 条（不会被裁剪）`);
