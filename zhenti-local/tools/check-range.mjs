const base = "http://127.0.0.1:8787";
const r = await fetch(`${base}/data/cet6/2025-12/01/listen.mp3`, { headers: { Range: "bytes=100-1099" } });
const bytes = Buffer.from(await r.arrayBuffer());
console.log("status:", r.status);
console.log("content-range:", r.headers.get("content-range"));
console.log("content-type:", r.headers.get("content-type"));
console.log("body bytes:", bytes.length);

const head = await fetch(`${base}/data/cet6/2025-12/01/listen.mp3`, { method: "HEAD" });
console.log("full:", head.status, head.headers.get("content-length"), head.headers.get("accept-ranges"));
