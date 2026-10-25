/*
 * Audio-reactive wave ring drawn behind the avatar. It reads the agent's real playback audio through an
 * AnalyserNode, so the waves move exactly with the voice. Bars follow the avatar's rounded-square outline.
 */
(function () {
  const BARS = 96;
  const SHAPE = 5; // superellipse exponent: 2 is a circle, higher is closer to a square; 5 matches the avatar's rounded corners

  window.VoiceViz = class VoiceViz {
    constructor(canvas, avatarSize) {
      this.canvas = canvas;
      this.ctx = canvas.getContext("2d");
      this.avatarSize = avatarSize; // () => avatar width in CSS px
      this.accent = "#075985";
      this.levels = new Float32Array(BARS);
      this.avg = 0;
      this.onFrame = null; // (avgLevel 0..1) => void
      this.analyser = null;
      this.raf = 0;
    }

    attach(audioContext, source) {
      this.analyser = audioContext.createAnalyser();
      this.analyser.fftSize = 256;
      this.analyser.smoothingTimeConstant = 0.55;
      this.data = new Uint8Array(this.analyser.frequencyBinCount);
      source.connect(this.analyser); // extra tap only; playback still goes straight to the speakers
    }

    start() {
      if (this.raf) return;
      const tick = () => {
        this.draw();
        this.raf = requestAnimationFrame(tick);
      };
      this.raf = requestAnimationFrame(tick);
    }

    stop() {
      cancelAnimationFrame(this.raf);
      this.raf = 0;
      this.analyser = null;
      this.levels.fill(0);
      this.avg = 0;
      this.ctx.setTransform(1, 0, 0, 1, 0, 0);
      this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
      this.onFrame?.(0);
    }

    draw() {
      const c = this.canvas;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const css = c.clientWidth;
      if (!css) return;
      const px = Math.round(css * dpr);
      if (c.width !== px) c.width = c.height = px;
      const ctx = this.ctx;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, css, css);

      if (this.analyser) this.analyser.getByteFrequencyData(this.data);
      const side = this.avatarSize();
      const half = side * 0.5 * 1.06; // small gap between avatar and bars
      const maxLen = side * 0.3;
      const mid = css / 2;
      let sum = 0;

      for (let i = 0; i < BARS; i++) {
        const t = i / BARS;
        const sym = t < 0.5 ? t * 2 : (1 - t) * 2; // mirrored left/right: low pitch at the top, high pitch at the bottom
        const raw = this.analyser ? this.data[1 + Math.floor(sym * 40)] / 255 : 0; // voice energy sits in the lowest ~4 kHz
        const target = raw < 0.12 ? 0 : Math.pow(raw, 1.2);
        const cur = this.levels[i];
        this.levels[i] = cur + (target - cur) * (target > cur ? 0.55 : 0.14); // quick attack, slow release
        sum += this.levels[i];
      }
      this.avg = sum / BARS;

      ctx.lineCap = "round";
      ctx.lineWidth = Math.max(3, side * 0.013);
      ctx.strokeStyle = this.accent;
      ctx.shadowColor = this.accent;
      ctx.shadowBlur = 10;
      for (let layer = 0; layer < 2; layer++) { // second layer: shorter, fainter bars between the first ones, for density
        ctx.globalAlpha = layer ? 0.3 : 0.8;
        for (let i = 0; i < BARS; i++) {
          const lvl = this.levels[(i + layer) % BARS] * (layer ? 0.55 : 1);
          if (lvl < 0.02) continue;
          const theta = ((i + layer * 0.5) / BARS) * Math.PI * 2 - Math.PI / 2;
          const cx = Math.cos(theta);
          const sy = Math.sin(theta);
          const x = Math.sign(cx) * Math.pow(Math.abs(cx), 2 / SHAPE) * half;
          const y = Math.sign(sy) * Math.pow(Math.abs(sy), 2 / SHAPE) * half;
          let nx = Math.sign(x) * Math.pow(Math.abs(x) / half, SHAPE - 1); // outline normal
          let ny = Math.sign(y) * Math.pow(Math.abs(y) / half, SHAPE - 1);
          const nl = Math.hypot(nx, ny) || 1;
          nx /= nl;
          ny /= nl;
          const len = side * 0.02 + lvl * maxLen * (1 - 0.55 * Math.max(0, sy)); // shorter at the bottom so it stays clear of the status text
          ctx.beginPath();
          ctx.moveTo(mid + x, mid + y);
          ctx.lineTo(mid + x + nx * len, mid + y + ny * len);
          ctx.stroke();
        }
      }
      ctx.globalAlpha = 1;
      this.onFrame?.(this.avg);
    }
  };
})();
