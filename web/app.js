import { AudioPlayer, VoiceGate } from "./audio.js";

const $ = (id) => document.getElementById(id);
const names = ["Aarav", "Meera"];
let socket;
let context;
let player;
let stream;
let micNode;
let micSource;
let micSink;
let started = false;
let roomStarting = false;
let paused = false;
let connected = false;
let cloudMode = true;
let epoch = 0;
let ignoreAudio = false;
let messages = Promise.resolve();
let currentEntry = null;
let records = [];
let generation = 0;
let waveformFrame = 0;
let analyser;
let waveformSamples;
const waveBars = [".wave-left", ".wave-right"].map((selector) => [...document.querySelector(selector).children]);
const waveHistory = waveBars.map((bars) => bars.map(() => 3));

function animateWaveform(agent) {
  cancelAnimationFrame(waveformFrame);
  waveformFrame = 0;
  waveBars.forEach((bars) => bars.forEach((bar) => { bar.style.height = "3px"; }));
  waveHistory.forEach((history) => history.fill(3));
  if (agent === null || !analyser) return;
  let last = 0;
  let smoothed = 3;
  const draw = (time) => {
    if (time - last >= 40) {
      last = time;
      analyser.getFloatTimeDomainData(waveformSamples);
      let energy = 0;
      for (const sample of waveformSamples) energy += sample * sample;
      const height = Math.min(72, Math.max(3, Math.sqrt(energy / waveformSamples.length) * 380));
      smoothed += (height - smoothed) * 0.65;
      const history = waveHistory[agent];
      if (agent === 0) { history.shift(); history.push(smoothed); }
      else { history.pop(); history.unshift(smoothed); }
      waveBars[agent].forEach((bar, index) => {
        const distance = agent === 0 ? (history.length - 1 - index) : index;
        const taper = 1 - 0.65 * distance / Math.max(1, history.length - 1);
        bar.style.height = Math.max(3, history[index] * taper) + "px";
      });
    }
    waveformFrame = requestAnimationFrame(draw);
  };
  waveformFrame = requestAnimationFrame(draw);
}

function send(data) {
  if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(data));
}

function notice(message) {
  $("notice").textContent = message;
  $("notice").hidden = false;
}

function clearNotice() {
  $("notice").hidden = true;
}

function speaking(agent) {
  animateWaveform(agent);
  for (let index = 0; index < 2; index += 1) {
    $("agent-" + index).classList.toggle("speaking", index === agent);
    $("agent-" + index).querySelector(".agent-state").textContent = index === agent ? "Speaking" : "Listening";
  }
  document.querySelector(".wave-left").classList.toggle("active", agent === 0);
  document.querySelector(".wave-right").classList.toggle("active", agent === 1);
  $("speaker-label").textContent = agent === null ? "Listening to the room" : names[agent] + " is speaking";
  $("speaker-detail").textContent = agent === null ? "Jump in whenever you like." : (agent === 0 ? "In your left ear" : "In your right ear");
  if (agent !== null) {
    $("room-status").textContent = names[agent] + " has the floor";
  }
}

function status(value) {
  const labels = {
    paused: "Taking a breather", listening: "The floor is yours",
    thinking: "Finding the next thought", transcribing: "Listening to your take",
  };
  $("room-status").textContent = labels[value] || value.toUpperCase();
  $("speaker-label").textContent = ({ paused: "Conversation paused", listening: "You’re speaking", thinking: "A thought is forming…", transcribing: "Listening to you…" })[value] || "Listening to the room";
  $("speaker-detail").textContent = value === "listening" ? "Both voices are listening." : "Jump in whenever you like.";
  document.querySelector(".agents").dataset.speaker = value === "listening" ? "human" : "";
  paused = value === "paused";
  $("pause").textContent = paused ? "Resume" : "Pause";
}

function addEntry(speaker, text = "") {
  if ($("transcript").querySelector(".empty-state")) $("transcript").replaceChildren();
  const entry = document.createElement("article");
  entry.className = "entry " + (speaker === "You" ? "moderator" : speaker === "Aarav" ? "atlas" : speaker === "Meera" ? "nova" : speaker.toLowerCase());
  const header = document.createElement("div");
  header.className = "entry-header";
  const name = document.createElement("strong");
  name.textContent = speaker;
  const time = document.createElement("small");
  time.textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const body = document.createElement("p");
  body.textContent = text;
  header.append(name, time);
  entry.append(header, body);
  $("transcript").append(entry);
  const record = { speaker, text, timestamp: new Date().toISOString(), interrupted: false };
  records.push(record);
  while ($("transcript").children.length > 120) $("transcript").firstElementChild.remove();
  if (records.length > 1000) records.shift();
  return { entry, body, record };
}

function scrollTranscript() {
  $("transcript").scrollTop = $("transcript").scrollHeight;
}

function markInterrupted() {
  if (currentEntry && !currentEntry.record.interrupted) {
    currentEntry.record.interrupted = true;
    currentEntry.entry.classList.add("interrupted");
    const marker = document.createElement("small");
    marker.className = "cutoff";
    marker.textContent = "interrupted";
    currentEntry.entry.querySelector(".entry-header").append(marker);
  }
  currentEntry = null;
}

async function ensureAudio() {
  if (!context) {
    context = new AudioContext();
    analyser = context.createAnalyser();
    analyser.fftSize = 512;
    waveformSamples = new Float32Array(analyser.fftSize);
    player = new AudioPlayer(context, (e, turn) => { send({ type: "played", epoch: e, turn }); currentEntry = null; }, speaking);
    player.gain.connect(analyser);
  }
  await context.resume();
}

function interrupt() {
  ignoreAudio = true;
  generation += 1;
  player?.reset();
  markInterrupted();
  send({ type: "interrupt" });
  status("listening");
}

const gate = new VoiceGate(
  interrupt,
  (frame) => {
    if (socket?.readyState === WebSocket.OPEN && socket.bufferedAmount < 256000) {
      socket.send(frame.buffer);
    } else {
      disableMic();
      notice("Audio connection is too slow. Microphone stopped; reconnect and retry.");
    }
  },
  () => send({ type: "speech_end" }),
);

async function disableMic() {
  gate.finish();
  stream?.getTracks().forEach((track) => track.stop());
  micNode?.disconnect();
  micSource?.disconnect();
  micSink?.disconnect();
  if (micNode) micNode.port.onmessage = null;
  stream = null;
  micNode = null;
  micSource = null;
  micSink = null;
  $("mic").classList.remove("enabled");
  $("mic").setAttribute("aria-pressed", "false");
  $("mic").setAttribute("aria-label", "Enable microphone");
  $("mic-label").textContent = "MIC OFF";
  $("mic-label").classList.remove("live");
  $("mic-status").textContent = "Enable your mic to jump in. Headphones recommended.";
  $("mic-level").value = 0;
}

async function enableMic() {
  if (stream) return;
  $("mic").disabled = true;
  try {
    await ensureAudio();
    if (!navigator.mediaDevices?.getUserMedia || !context.audioWorklet) {
      throw new Error("Microphone requires a modern browser on localhost. Use Chrome or Edge.");
    }
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: false, channelCount: 1 },
    });
    if (!connected || !started) throw new Error("Room disconnected while enabling microphone.");
    await context.audioWorklet.addModule("/mic-worklet.js");
    micSource = context.createMediaStreamSource(stream);
    micNode = new AudioWorkletNode(context, "mic-processor");
    micSink = context.createGain();
    micSink.gain.value = 0;
    micSource.connect(micNode);
    micNode.connect(micSink);
    micSink.connect(context.destination);
    gate.reset();
    micNode.port.onmessage = (event) => {
      if (!started || !connected || roomStarting) return;
      $("mic-level").value = gate.process(new Float32Array(event.data), Number($("threshold").value));
    };
    stream.getAudioTracks()[0].onended = () => {
      disableMic();
      notice("Microphone disconnected. Enable it again to continue.");
    };
    $("mic").classList.add("enabled");
    $("mic").setAttribute("aria-pressed", "true");
    $("mic").setAttribute("aria-label", "Disable microphone");
    $("mic-label").textContent = "MIC LIVE";
    $("mic-label").classList.add("live");
    $("mic-status").textContent = "Speak naturally. Both agents stop when you jump in.";
    clearNotice();
  } catch (error) {
    await disableMic();
    notice("Microphone unavailable: " + error.message + " You can still type your prompts.");
  } finally {
    $("mic").disabled = !started || !connected;
  }
}

$("mic").addEventListener("click", () => stream ? disableMic() : enableMic());

$("room-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!connected || roomStarting) return;
  roomStarting = true;
  $("start").disabled = true;
  try {
    await ensureAudio();
    gate.reset();
    markInterrupted();
    ignoreAudio = true;
    player.reset();
    records = [];
    $("transcript").replaceChildren();
    clearNotice();
    started = true;
    $("start").textContent = "Restart room ↗";
    $("mic").disabled = false;
    $("pause").disabled = false;
    $("send").disabled = false;
    $("role-0").textContent = $("mode").value === "negotiate" ? "The buyer. Seeking a fair deal." : "Makes the case.";
    $("role-1").textContent = $("mode").value === "negotiate" ? "The seller. Defending the value." : "Questions the assumptions.";
    await enableMic();
    send({ type: "start", topic: $("topic").value, language: $("language").value, mode: $("mode").value });
  } catch (error) {
    notice(error.message);
  } finally {
    roomStarting = false;
    $("start").disabled = !connected;
  }
});

$("pause").addEventListener("click", () => {
  gate.reset();
  if (paused) {
    send({ type: "resume" });
    status("thinking");
  } else {
    ignoreAudio = true;
    generation += 1;
    player.reset();
    markInterrupted();
    send({ type: "pause" });
    status("paused");
  }
});

$("moderator-form").addEventListener("submit", (event) => {
  event.preventDefault();
  if (!started || !connected) return;
  const text = $("moderator-text").value.trim();
  if (!text) return;
  gate.reset();
  ignoreAudio = true;
  generation += 1;
  player.reset();
  markInterrupted();
  send({ type: "moderator", text });
  $("moderator-text").value = "";
});

$("export").addEventListener("click", () => {
  const text = "# Stereo Sabha\n\nTopic: " + $("topic").value + "\n\n" + records.map(
    (record) => "## " + record.speaker + " · " + record.timestamp + (record.interrupted ? " · interrupted" : "") + "\n\n" + record.text,
  ).join("\n\n");
  const url = URL.createObjectURL(new Blob([text], { type: "text/markdown" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "stereo-sabha-" + new Date().toISOString().slice(0, 10) + ".md";
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});

$("test-audio").addEventListener("click", async () => {
  if (started && !paused) {
    notice("Pause the room before the headphone check.");
    return;
  }
  await ensureAudio();
  for (let channel = 0; channel < 2; channel += 1) {
    const buffer = context.createBuffer(2, context.sampleRate * 0.3, context.sampleRate);
    const samples = buffer.getChannelData(channel);
    for (let index = 0; index < samples.length; index += 1) {
      const envelope = Math.min(1, index / 500, (samples.length - index) / 500);
      samples[index] = Math.sin(index * 2 * Math.PI * (channel === 0 ? 440 : 660) / context.sampleRate) * 0.2 * envelope;
    }
    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(context.destination);
    source.start(context.currentTime + channel * 0.65);
  }
  notice("Headphone check: lower beep on the left, then higher beep on the right.");
});

async function handle(message) {
  if (message.epoch !== undefined && message.epoch !== epoch) return;
  if (message.type === "turn") {
    if (ignoreAudio) return;
    player.begin(message.epoch, message.turn);
    currentEntry = addEntry(names[message.agent]);
    $("agent-" + message.agent).querySelector(".agent-state").textContent = "Thinking";
    status("thinking");
  } else if (message.type === "audio") {
    if (ignoreAudio || !currentEntry) return;
    const active = currentEntry;
    const version = generation;
    active.body.textContent += (message.text_is_delta ? "" : (active.body.textContent ? " " : "")) + message.text;
    active.record.text = active.body.textContent;
    if (message.text) $("agent-" + message.agent).querySelector(".utterance").textContent = active.body.textContent;
    if (message.first_audio_ms !== null) $("latency").textContent = (message.first_audio_ms / 1000).toFixed(1) + "s to voice";
    scrollTranscript();
    try {
      if (message.wav) {
        await player.enqueue(message);
        if (cloudMode) $("connection").textContent = "Sarvam voice active";
      }
    } catch (error) {
      if (version !== generation) return;
      ignoreAudio = true;
      player.reset();
      send({ type: "pause" });
      notice("Audio playback failed: " + error.message);
    }
  } else if (message.type === "turn_end") {
    if (!ignoreAudio) player.end(message.epoch, message.turn);
  } else if (message.type === "transcript") {
    addEntry(message.speaker, message.text);
    scrollTranscript();
  } else if (message.type === "status") {
    status(message.status);
    if (message.detail) notice(message.detail);
  } else if (message.type === "error" || message.type === "notice") {
    notice(message.message);
  }
}

function connect() {
  socket = new WebSocket("ws://" + location.host + "/ws");
  socket.onmessage = (event) => {
    let message;
    try {
      message = JSON.parse(event.data);
    } catch {
      notice("Invalid server message.");
      return;
    }
    if (message.type === "ready") {
      connected = true;
      epoch = message.epoch;
      $("connection").textContent = cloudMode ? "Server ready · cloud unverified" : "Local engine connected";
      $("connection-dot").classList.add("online");
      $("start").disabled = false;
    } else if (message.type === "reset") {
      generation += 1;
      epoch = message.epoch;
      player?.reset(epoch);
      ignoreAudio = false;
      status(message.status);
    } else {
      messages = messages.then(() => handle(message)).catch((error) => notice(error.message));
    }
  };
  socket.onclose = () => {
    connected = false;
    started = false;
    generation += 1;
    player?.reset();
    disableMic();
    $("start").disabled = true;
    $("mic").disabled = true;
    $("pause").disabled = true;
    $("send").disabled = true;
    $("connection").textContent = "Disconnected";
    $("connection-dot").classList.remove("online");
    notice("Room disconnected. Check the terminal and refresh this page. Only one room tab can be open.");
  };
  socket.onerror = () => notice("Cannot connect to the local room. Run start.ps1 and refresh.");
}

fetch("/health").then((response) => response.json()).then((health) => {
  cloudMode = !health.local;
  if (!cloudMode) {
    document.querySelector(".local-badge").textContent = "LOCAL MODE";
    $("privacy-title").textContent = "Optional local inference";
    $("privacy-body").textContent = "AI models run on this CPU. No cloud inference.";
  }
  if (!health.ready) notice("Local language model is not ready. Wait for start.ps1 to finish loading it.");
  connect();
}).catch(() => notice("Local server is unavailable. Run start.ps1, then open http://127.0.0.1:8765."));
window.addEventListener("pagehide", () => {
  stream?.getTracks().forEach((track) => track.stop());
  socket?.close();
  context?.close();
});
