/**
 * 给本机页面拍一张图，用来肉眼确认界面。
 * 用法：node tools/shot.mjs <url> <输出png> [宽] [高]
 */
import { writeFile } from "node:fs/promises";
import { connect, sleep } from "./cdp.mjs";

const [, , url, out, w = "1400", h = "900"] = process.argv;
const port = 9223;

const created = await (await fetch(`http://127.0.0.1:${port}/json/new?${encodeURIComponent(url)}`, { method: "PUT" })).json();
const { send, close } = await connect(port, (t) => t.id === created.id);
await send("Emulation.setDeviceMetricsOverride", {
  width: Number(w),
  height: Number(h),
  deviceScaleFactor: 1,
  mobile: false,
});
await sleep(2500);
const shot = await send("Page.captureScreenshot", { format: "png" });
await writeFile(out, Buffer.from(shot.data, "base64"));
close();
console.log("已保存", out);
