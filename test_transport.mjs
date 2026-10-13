import assert from "node:assert/strict";
const base = "http://127.0.0.1:8765";
const health = await fetch(base + "/health").then(r => r.json());
assert.equal(health.ready, true);
assert.equal(health.model, "Sarvam 105B Conversations");
const page = await fetch(base + "/");
assert.equal(page.status, 200);
assert.ok((await page.text()).includes("prompts go to Sarvam"));
await new Promise((resolve, reject) => {
  const socket = new WebSocket("ws://127.0.0.1:8765/ws");
  const timer = setTimeout(() => { socket.close(); reject(Error("WebSocket timed out")); }, 5000);
  socket.onmessage = e => {
    const message = JSON.parse(e.data);
    if (message.type === "ready") socket.send(JSON.stringify({type:"start",topic:"x"}));
    if (message.type === "error") {
      clearTimeout(timer); socket.close();
      try { assert.match(message.message, /between 3 and 500/); resolve(); } catch(error) { reject(error); }
    }
  };
  socket.onerror = () => { clearTimeout(timer); reject(Error("WebSocket failed")); };
});
console.log("PASS: real HTTP health, Sarvam UI disclosure, and WebSocket validation; no provider calls");
