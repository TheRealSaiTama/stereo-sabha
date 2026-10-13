import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const code = fs.readFileSync(new URL("./web/app.js", import.meta.url), "utf8").replace(/^import .*;\s*/, "");
async function scenario(deny) {
  const elements = new Map();
  const order = [];
  let requests = 0;
  let animation;
  function element(id) {
    if (!elements.has(id)) elements.set(id, {
      value: id === "topic" ? "खुला स्रोत" : id === "language" ? "hi" : "debate",
      dataset: {}, children: Array.from({ length: 5 }, () => ({ style: {} })),
      classList: { add() {}, remove() {}, toggle() {} },
      addEventListener(type, handler) { this[type] = handler; },
      setAttribute() {}, replaceChildren() {}, querySelector() { return element("nested"); },
    });
    return elements.get(id);
  }
  class Socket {
    static OPEN = 1;
    constructor() {
      this.readyState = 1;
      queueMicrotask(() => this.onmessage({ data: JSON.stringify({ type: "ready", epoch: 0 }) }));
    }
    send(raw) { const data = JSON.parse(raw); if (data.type === "start") order.push("start"); }
  }
  const node = () => ({ connect() {}, disconnect() {}, gain: { value: 1 } });
  class Context {
    constructor() { this.audioWorklet = { async addModule() {} }; this.destination = {}; }
    async resume() {}
    createMediaStreamSource() { return node(); }
    createGain() { return node(); }
    createAnalyser() { return { fftSize: 512, getFloatTimeDomainData(samples) { samples.fill(0.1); } }; }
  }
  const track = { stop() {} };
  const sandbox = {
    document: { getElementById: element, querySelector: () => element("badge"), querySelectorAll: () => [] },
    window: { addEventListener() {} },
    location: { host: "127.0.0.1:8765" },
    fetch: async () => ({ async json() { return { ready: true, local: false }; } }),
    WebSocket: Socket,
    AudioContext: Context,
    AudioWorkletNode: class { constructor() { this.port = {}; } connect() {} disconnect() {} },
    AudioPlayer: class { constructor() { this.gain = node(); } reset() {} },
    VoiceGate: class { reset() {} finish() {} },
    navigator: { mediaDevices: { async getUserMedia() {
      requests += 1; order.push("mic");
      if (deny) throw Error("Permission denied");
      return { getTracks: () => [track], getAudioTracks: () => [track] };
    } } },
    requestAnimationFrame: (callback) => { animation = callback; return 1; }, cancelAnimationFrame() {},
    setTimeout, clearTimeout, queueMicrotask, console,
  };
  vm.runInNewContext(code, sandbox);
  vm.runInNewContext('speaking(0)', sandbox);
  assert.equal(element("speaker-label").textContent, "Aarav is speaking");
  assert.equal(element("speaker-detail").textContent, "In your left ear");
  vm.runInNewContext('speaking(1)', sandbox);
  assert.equal(element("speaker-label").textContent, "Meera is speaking");
  assert.equal(element("speaker-detail").textContent, "In your right ear");
  vm.runInNewContext('status("listening")', sandbox);
  assert.equal(element("speaker-label").textContent, "You’re speaking");
  vm.runInNewContext('status("paused")', sandbox);
  assert.equal(element("speaker-label").textContent, "Conversation paused");
  await new Promise(resolve => setTimeout(resolve, 0));
  await element("room-form").submit({ preventDefault() {} });
  vm.runInNewContext("speaking(0)", sandbox);
  animation(100);
  assert.ok(Math.abs(parseFloat(element("badge").children[4].style.height) - 25.75) < 0.01);
  vm.runInNewContext("speaking(null)", sandbox);
  assert.equal(element("badge").children[4].style.height, "3px");
  assert.equal(requests, 1, "Room start must automatically request the microphone");
  assert.deepEqual(order, ["mic", "start"], "Mic request must precede room startup");
  if (deny) {
    assert.match(element("notice").textContent, /Permission denied/);
  } else {
    assert.equal(element("mic-label").textContent, "MIC LIVE");
    await element("room-form").submit({ preventDefault() {} });
    assert.equal(requests, 1, "Restart must reuse the active microphone");
  }
}
await scenario(false);
await scenario(true);
console.log("PASS: automatic microphone request, startup ordering, restart reuse, and permission-denied text fallback");
