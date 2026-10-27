/**
 * 把 data/answers.json 拆到每套目录下的 answers.json。
 *
 * 站点给的是 ["1-C", "2-B", …]，本地判分读的是 { "1": "C", "2": "B" }。
 * 这里顺手把大小写统一，撞上同一题号重复的以后出现的为准。
 *
 * 用法：node tools/distribute-answers.mjs [--dry]
 */

import { readFile, writeFile, mkdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const DRY = process.argv.includes("--dry");

const parse = (list) => {
  const out = {};
  for (const item of list) {
    const m = String(item).trim().match(/^(\d+)\s*[-–.:]\s*([A-Za-z]+)$/);
    if (!m) continue;
    out[String(Number(m[1]))] = m[2].toUpperCase();
  }
  return out;
};

const main = async () => {
  const all = JSON.parse(await readFile(join(ROOT, "data", "answers.json"), "utf8"));
  let written = 0, skipped = 0, noAns = 0;

  for (const [id, entry] of Object.entries(all)) {
    const list = entry?.answers ?? [];
    if (!list.length) { noAns++; continue; }
    const map = parse(list);
    const count = Object.keys(map).length;
    if (!count) { console.log(`跳过 ${id}：解析不出题号`); skipped++; continue; }

    const dir = join(ROOT, "data", id);
    if (!existsSync(dir)) { console.log(`跳过 ${id}：本地没有这套的目录`); skipped++; continue; }

    const payload = { ...map, source: "zhenti.burningvocabulary.cn", fetchedAt: entry.fetchedAt ?? new Date().toISOString() };
    if (!DRY) await writeFile(join(dir, "answers.json"), JSON.stringify(payload, null, 1) + "\n");
    written++;
  }

  console.log(`${DRY ? "[预演] " : ""}写入 ${written} 套，跳过 ${skipped}，站点无答案 ${noAns}`);
};

main().catch((e) => { console.error(e); process.exit(1); });
