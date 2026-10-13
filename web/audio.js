export class AudioPlayer {
  constructor(context, onPlayed, onSpeaking) {
    this.context = context;
    this.onPlayed = onPlayed;
    this.onSpeaking = onSpeaking;
    this.gain = context.createGain();
    this.gain.gain.value = 0.8;
    this.gain.connect(context.destination);
    this.generation = 0;
    this.queue = [];
    this.current = null;
    this.endReceived = false;
    this.pending = 0;
    this.epoch = 0;
    this.turn = 0;
    this.acknowledged = false;
  }

  reset(epoch = this.epoch) {
    this.generation += 1;
    this.epoch = epoch;
    this.queue = [];
    this.pending = 0;
    this.endReceived = false;
    this.acknowledged = false;
    if (this.current) {
      this.current.onended = null;
      this.current.stop();
      this.current.disconnect();
      this.current = null;
    }
    this.onSpeaking(null);
  }

  begin(epoch, turn) {
    this.reset(epoch);
    this.turn = turn;
  }

  async enqueue(message) {
    if (message.epoch !== this.epoch || message.turn !== this.turn) return;
    const generation = this.generation;
    this.pending += 1;
    try {
      const bytes = Uint8Array.from(atob(message.wav), (character) => character.charCodeAt(0));
      const decoded = await this.context.decodeAudioData(bytes.buffer);
      if (generation !== this.generation) return;
      const stereo = this.context.createBuffer(2, decoded.length, decoded.sampleRate);
      stereo.copyToChannel(decoded.getChannelData(0), message.agent);
      this.queue.push({ buffer: stereo, agent: message.agent });
    } finally {
      if (generation === this.generation) {
        this.pending -= 1;
        this.playNext();
      }
    }
  }

  playNext() {
    if (this.current) return;
    if (this.queue.length) {
      const item = this.queue.shift();
      const source = this.context.createBufferSource();
      const generation = this.generation;
      source.buffer = item.buffer;
      source.connect(this.gain);
      this.current = source;
      this.onSpeaking(item.agent);
      source.onended = () => {
        source.disconnect();
        if (generation !== this.generation) return;
        this.current = null;
        this.playNext();
      };
      source.start();
    } else {
      this.onSpeaking(null);
      if (this.endReceived && this.pending === 0 && !this.acknowledged) {
        this.acknowledged = true;
        this.onPlayed(this.epoch, this.turn);
      }
    }
  }

  end(epoch, turn) {
    if (epoch !== this.epoch || turn !== this.turn) return;
    this.endReceived = true;
    this.playNext();
  }
}

export class VoiceGate {
  constructor(onStart, onFrame, onEnd) {
    this.onStart = onStart;
    this.onFrame = onFrame;
    this.onEnd = onEnd;
    this.reset();
  }

  reset() {
    this.preroll = [];
    this.voiced = 0;
    this.silent = 0;
    this.frames = 0;
    this.active = false;
    this.cooldown = 0;
  }

  process(frame, threshold) {
    let sum = 0;
    for (const sample of frame) sum += sample * sample;
    const rms = Math.sqrt(sum / frame.length);
    if (this.cooldown > 0) {
      this.cooldown -= 1;
      return rms;
    }
    const voiced = rms > threshold;
    if (!this.active) {
      this.preroll.push(frame);
      if (this.preroll.length > 12) this.preroll.shift();
      this.voiced = voiced ? this.voiced + 1 : 0;
      if (this.voiced >= 3) {
        this.active = true;
        this.frames = this.preroll.length;
        this.silent = 0;
        this.onStart();
        for (const saved of this.preroll) this.onFrame(saved);
        this.preroll = [];
      }
    } else {
      this.onFrame(frame);
      this.frames += 1;
      this.silent = voiced ? 0 : this.silent + 1;
      if (this.silent >= 35 || this.frames >= 1000) {
        this.active = false;
        this.voiced = 0;
        this.preroll = [];
        this.cooldown = 10;
        this.onEnd();
      }
    }
    return rms;
  }

  finish() {
    if (this.active) this.onEnd();
    this.reset();
  }
}
