/**
 * Procedural Web Audio API tabletop Foley synthesizer (zero external audio files).
 * Synthesizes tactile physical sounds: card slide/flick, wood thud, brass coins,
 * polyhedral dice clatter, steel clash ring, shield clang & erosion crumble, and turn gong.
 */

export class TabletopAudio {
  constructor() {
    this.ctx = null;
    this.muted = false;
  }

  _ensure() {
    if (this.muted) return null;
    if (!this.ctx) {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return null;
      this.ctx = new AC();
    }
    if (this.ctx.state === 'suspended') {
      this.ctx.resume().catch(() => {});
    }
    return this.ctx;
  }

  toggleMute() {
    this.muted = !this.muted;
    return this.muted;
  }

  _noiseBuffer(ctx, duration) {
    const len = Math.max(1, Math.floor(ctx.sampleRate * duration));
    const buf = ctx.createBuffer(1, len, ctx.sampleRate);
    const ch = buf.getChannelData(0);
    for (let i = 0; i < len; i++) ch[i] = Math.random() * 2 - 1;
    return buf;
  }

  cardSlide() {
    const ctx = this._ensure();
    if (!ctx) return;
    const now = ctx.currentTime;
    const src = ctx.createBufferSource();
    src.buffer = this._noiseBuffer(ctx, 0.09);
    const filter = ctx.createBiquadFilter();
    filter.type = 'bandpass';
    filter.frequency.setValueAtTime(1600, now);
    filter.frequency.exponentialRampToValueAtTime(650, now + 0.08);
    filter.Q.value = 1.6;
    const gain = ctx.createGain();
    gain.gain.setValueAtTime(0.001, now);
    gain.gain.linearRampToValueAtTime(0.11, now + 0.015);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.085);
    src.connect(filter).connect(gain).connect(ctx.destination);
    src.start(now);
    src.stop(now + 0.09);
  }

  cardPlace() {
    const ctx = this._ensure();
    if (!ctx) return;
    const now = ctx.currentTime;
    const osc = ctx.createOscillator();
    osc.type = 'triangle';
    osc.frequency.setValueAtTime(145, now);
    osc.frequency.exponentialRampToValueAtTime(48, now + 0.085);
    const gain = ctx.createGain();
    gain.gain.setValueAtTime(0.24, now);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.095);
    osc.connect(gain).connect(ctx.destination);
    osc.start(now);
    osc.stop(now + 0.1);
    this.cardSlide();
  }

  cardFlip() {
    const ctx = this._ensure();
    if (!ctx) return;
    const now = ctx.currentTime;
    const src = ctx.createBufferSource();
    src.buffer = this._noiseBuffer(ctx, 0.11);
    const hp = ctx.createBiquadFilter();
    hp.type = 'highpass';
    hp.frequency.setValueAtTime(1800, now);
    const gain = ctx.createGain();
    gain.gain.setValueAtTime(0.001, now);
    gain.gain.linearRampToValueAtTime(0.16, now + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.1);
    src.connect(hp).connect(gain).connect(ctx.destination);
    src.start(now);
    src.stop(now + 0.11);
  }

  coinClink(pitch = 1.0) {
    const ctx = this._ensure();
    if (!ctx) return;
    const now = ctx.currentTime;
    [2200, 3310].forEach((freq, idx) => {
      const osc = ctx.createOscillator();
      osc.type = 'sine';
      osc.frequency.setValueAtTime(freq * pitch, now);
      const gain = ctx.createGain();
      gain.gain.setValueAtTime(idx === 0 ? 0.07 : 0.045, now);
      gain.gain.exponentialRampToValueAtTime(0.0008, now + 0.18);
      osc.connect(gain).connect(ctx.destination);
      osc.start(now);
      osc.stop(now + 0.19);
    });
  }

  diceRoll() {
    const ctx = this._ensure();
    if (!ctx) return;
    const now = ctx.currentTime;
    const offsets = [0, 0.055, 0.125, 0.21, 0.31];
    offsets.forEach((dt, i) => {
      const t = now + dt;
      const osc = ctx.createOscillator();
      osc.type = 'triangle';
      const base = 680 + (i % 3) * 180 + Math.random() * 140;
      osc.frequency.setValueAtTime(base, t);
      osc.frequency.exponentialRampToValueAtTime(180, t + 0.032);
      const gain = ctx.createGain();
      gain.gain.setValueAtTime(0.11 * (1 - i * 0.14), t);
      gain.gain.exponentialRampToValueAtTime(0.001, t + 0.038);
      osc.connect(gain).connect(ctx.destination);
      osc.start(t);
      osc.stop(t + 0.042);
    });
  }

  clashImpact(heavy = false) {
    const ctx = this._ensure();
    if (!ctx) return;
    const now = ctx.currentTime;
    const freqs = heavy ? [420, 890, 1740, 2610] : [520, 1140, 2180];
    freqs.forEach((f, idx) => {
      const osc = ctx.createOscillator();
      osc.type = idx === 0 ? 'sawtooth' : 'sine';
      osc.frequency.setValueAtTime(f, now);
      osc.frequency.exponentialRampToValueAtTime(f * 0.86, now + 0.28);
      const gain = ctx.createGain();
      gain.gain.setValueAtTime((heavy ? 0.12 : 0.08) / (idx + 1), now);
      gain.gain.exponentialRampToValueAtTime(0.0008, now + 0.3);
      osc.connect(gain).connect(ctx.destination);
      osc.start(now);
      osc.stop(now + 0.32);
    });
  }

  shieldBlock() {
    const ctx = this._ensure();
    if (!ctx) return;
    const now = ctx.currentTime;
    const osc = ctx.createOscillator();
    osc.type = 'sine';
    osc.frequency.setValueAtTime(640, now);
    osc.frequency.exponentialRampToValueAtTime(980, now + 0.14);
    const gain = ctx.createGain();
    gain.gain.setValueAtTime(0.11, now);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.16);
    osc.connect(gain).connect(ctx.destination);
    osc.start(now);
    osc.stop(now + 0.17);
  }

  shieldErode() {
    const ctx = this._ensure();
    if (!ctx) return;
    const now = ctx.currentTime;
    const src = ctx.createBufferSource();
    src.buffer = this._noiseBuffer(ctx, 0.22);
    const bp = ctx.createBiquadFilter();
    bp.type = 'bandpass';
    bp.frequency.setValueAtTime(1100, now);
    bp.frequency.exponentialRampToValueAtTime(280, now + 0.21);
    const gain = ctx.createGain();
    gain.gain.setValueAtTime(0.16, now);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.21);
    src.connect(bp).connect(gain).connect(ctx.destination);
    src.start(now);
    src.stop(now + 0.22);
  }

  hitDamage() {
    const ctx = this._ensure();
    if (!ctx) return;
    const now = ctx.currentTime;
    const osc = ctx.createOscillator();
    osc.type = 'sawtooth';
    osc.frequency.setValueAtTime(135, now);
    osc.frequency.exponentialRampToValueAtTime(38, now + 0.16);
    const gain = ctx.createGain();
    gain.gain.setValueAtTime(0.22, now);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.18);
    osc.connect(gain).connect(ctx.destination);
    osc.start(now);
    osc.stop(now + 0.19);
  }

  healChime() {
    const ctx = this._ensure();
    if (!ctx) return;
    const now = ctx.currentTime;
    [523.25, 659.25, 783.99].forEach((f, i) => {
      const t = now + i * 0.045;
      const osc = ctx.createOscillator();
      osc.type = 'sine';
      osc.frequency.setValueAtTime(f, t);
      const gain = ctx.createGain();
      gain.gain.setValueAtTime(0.06, t);
      gain.gain.exponentialRampToValueAtTime(0.001, t + 0.24);
      osc.connect(gain).connect(ctx.destination);
      osc.start(t);
      osc.stop(t + 0.25);
    });
  }

  turnBell() {
    const ctx = this._ensure();
    if (!ctx) return;
    const now = ctx.currentTime;
    [392, 587.33, 783.99].forEach((f, i) => {
      const osc = ctx.createOscillator();
      osc.type = 'sine';
      osc.frequency.setValueAtTime(f, now);
      const gain = ctx.createGain();
      gain.gain.setValueAtTime(0.08 / (i + 1), now);
      gain.gain.exponentialRampToValueAtTime(0.0008, now + 0.55);
      osc.connect(gain).connect(ctx.destination);
      osc.start(now);
      osc.stop(now + 0.58);
    });
  }
}
