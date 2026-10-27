/** 试不同的 type / urlPath 组合，找出答案接口的正确参数。 */
import { connect } from "./cdp.mjs";

const PORT = Number(process.argv[2] ?? 9223);
const PATH = process.argv[3] ?? "/cet6/2025-06/01";

const { evaluate, close } = await connect(PORT);

const rows = await evaluate(`(async () => {
  const types = ["0", "1", "2", "3", "4", "5", "answer", "analysis", "ans", "exp"];
  const out = [];
  for (const type of types) {
    const res = await fetch("/api/answerExpansion/textGet", {
      method: "POST",
      cache: "no-cache",
      headers: { "Content-Type": "application/json;charset=UTF-8" },
      body: JSON.stringify({ type, urlPath: ${JSON.stringify(PATH)} }),
    });
    out.push({ type, status: res.status, body: (await res.text()).slice(0, 300) });
  }
  return out;
})()`);

for (const row of rows) console.log(`type=${String(row.type).padEnd(9)} ${row.status}  ${row.body}`);
close();
