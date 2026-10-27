/**
 * 语法自检：所有 JS 都过一遍 `node --check`。
 *
 * 存在的意义：改代码时很容易把两行合成一行（例如去空行时把注释和语句并到一起，
 * 后半句就变成了注释内容）—— 这种错只有运行时才炸，而且可能炸在很久以后的某个接口上。
 * 每次改完跑一下：
 *   node tools/check.mjs
 */
import { execFileSync } from "node:child_process";
import { readdirSync, statSync } from "node:fs";
import { join, resolve, dirname, relative } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");

const walk = (dir, out = []) => {
  for (const name of readdirSync(dir)) {
    if (name === "node_modules" || name === "vendor") continue;
    const full = join(dir, name);
    if (statSync(full).isDirectory()) walk(full, out);
    else if (name.endsWith(".mjs") || name.endsWith(".js")) out.push(relative(ROOT, full));
  }
  return out;
};

const files = walk(ROOT).sort();
let failed = 0;

for (const file of files) {
  try {
    execFileSync(process.execPath, ["--check", join(ROOT, file)], { stdio: "pipe" });
    console.log(`ok   ${file}`);
  } catch (error) {
    failed += 1;
    console.log(`FAIL ${file}`);
    console.log(String(error.stderr ?? error.message).trim());
  }
}

console.log(`\n${files.length - failed}/${files.length} files ok`);
process.exit(failed === 0 ? 0 : 1);
