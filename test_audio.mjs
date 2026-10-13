import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const source = fs.readFileSync(new URL("./web/audio.js", import.meta.url), "utf8");
const { AudioPlayer, VoiceGate } = await import("data:text/javascript;base64," + Buffer.from(source).toString("base64"));

let starts = 0;
let ends = 0;
let frames = [];
const gate = new VoiceGate(() => { starts += 1; }, (frame) => frames.push(frame), () => { ends += 1; });
const silence = new Float32Array(320);
const voice = new Float32Array(320).fill(0.05);
for (let i = 0; i < 12; i += 1) gate.process(silence, 0.015);
gate.process(voice, 0.015);
gate.process(voice, 0.015);
assert.equal(starts, 0, "Brief noise should not trigger interruption");
gate.process(voice, 0.015);
assert.equal(starts, 1);
assert.equal(frames.length, 12, "Pre-roll must retain the start of speech");
for (let i = 0; i < 35; i += 1) gate.process(silence, 0.015);
assert.equal(ends, 1, "Silence should end the moderator turn");
for (let i = 0; i < 10; i += 1) gate.process(silence, 0.015);
for (let i = 0; i < 1003; i += 1) gate.process(voice, 0.015);
assert.equal(ends, 2, "Long speech must be bounded");
gate.reset();
assert.equal(gate.active, false);

let sources = [];
let decodeResolve;
let delayed = false;
const context = {
  destination: {},
  createGain() { return { gain: { value: 0 }, connect() {} }; },
  async decodeAudioData() {
    if (delayed) await new Promise((resolve) => { decodeResolve = resolve; });
    return { length: 3, sampleRate: 22050, getChannelData() { return new Float32Array([0.1, 0.2, 0.3]); } };
  },
  createBuffer(channels, length) {
    const data = Array.from({ length: channels }, () => new Float32Array(length));
    return { data, copyToChannel(samples, channel) { data[channel].set(samples); } };
  },
  createBufferSource() {
    const source = { connect() {}, disconnect() {}, start() {}, stop() { this.stopped = true; }, onended: null };
    sources.push(source);
    return source;
  },
};
let acks = [];
const player = new AudioPlayer(context, (epoch, turn) => acks.push([epoch, turn]), () => {});
player.begin(1, 1);
await player.enqueue({ epoch: 1, turn: 1, agent: 0, wav: "AAAA" });
assert.deepEqual([...sources[0].buffer.data[1]], [0, 0, 0], "Atlas must be silent in the right channel");
player.end(1, 1);
assert.equal(acks.length, 0, "Do not acknowledge before audio finishes");
sources[0].onended();
assert.deepEqual(acks, [[1, 1]]);
player.end(1, 1);
assert.equal(acks.length, 1, "Acknowledge only once");
player.begin(1, 2);
await player.enqueue({ epoch: 1, turn: 2, agent: 1, wav: "AAAA" });
assert.deepEqual([...sources[1].buffer.data[0]], [0, 0, 0], "Nova must be silent in the left channel");
player.reset(2);
assert.equal(sources[1].stopped, true, "Interruption must stop current playback");
assert.equal(sources[1].onended, null, "Stopped playback cannot acknowledge an old turn");
player.begin(2, 3);
delayed = true;
const decoding = player.enqueue({ epoch: 2, turn: 3, agent: 0, wav: "AAAA" });
await Promise.resolve();
player.reset(3);
decodeResolve();
await decoding;
assert.equal(sources.length, 2, "Audio decoded after interruption must be discarded");

const worklet = fs.readFileSync(new URL("./web/mic-worklet.js", import.meta.url), "utf8");
for (const rate of [44100, 48000]) {
  let processor;
  const outputs = [];
  const sandbox = {
    sampleRate: rate,
    AudioWorkletProcessor: class { constructor() { this.port = { postMessage(buffer) { outputs.push(buffer); } }; } },
    registerProcessor(name, cls) { processor = new cls(); },
    Float32Array,
  };
  vm.runInNewContext(worklet, sandbox);
  for (let offset = 0; offset < rate; offset += 128) {
    processor.process([[new Float32Array(Math.min(128, rate - offset)).fill(0.25)]]);
  }
  const samples = outputs.reduce((total, buffer) => total + buffer.byteLength / 4, 0);
  assert.ok(samples >= 15680 && samples <= 16000, "Resample " + rate + " Hz to 16 kHz within one frame");
  assert.ok(Math.abs(new Float32Array(outputs[0])[0] - 0.25) < 0.0001);
}
console.log("PASS: stereo isolation, playback acknowledgements, stale audio cancellation, voice activity, pre-roll, and 44.1/48 kHz resampling");
