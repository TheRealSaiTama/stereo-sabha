class MicProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / 16000;
    this.phase = 0;
    this.sum = 0;
    this.count = 0;
    this.frame = new Float32Array(320);
    this.index = 0;
  }

  process(inputs) {
    const samples = inputs[0]?.[0];
    if (!samples) return true;
    for (const value of samples) {
      this.sum += value;
      this.count += 1;
      this.phase += 1;
      if (this.phase >= this.ratio) {
        this.phase -= this.ratio;
        this.frame[this.index++] = this.sum / this.count;
        this.sum = 0;
        this.count = 0;
        if (this.index === 320) {
          this.port.postMessage(this.frame.buffer, [this.frame.buffer]);
          this.frame = new Float32Array(320);
          this.index = 0;
        }
      }
    }
    return true;
  }
}
registerProcessor("mic-processor", MicProcessor);
