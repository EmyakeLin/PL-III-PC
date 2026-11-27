/**
 * Procedural Web Audio API Tabletop Foley & Combat Sound Engine for 《光点计划 III》.
 * Pure WebAudio synthesis — ZERO external audio URLs, ZERO DOM controls.
 *
 * Tactile tabletop soundscape:
 *  - Real cardstock paper slide / flick / place / flip (band-pass filtered noise bursts + transient snaps + oak-desk thump)
 *  - Heavy metallic clash impact (layered inharmonic steel partials + low sub-thump + stereo punch)
 *  - Crystalline shield block & brittle multi-grain shatter crackle
 *  - Warm resonant bronze turn bell, delicate harmonic passive chime & cost-merge crystal chime
 *  - Master dynamics limiter bus so rapid multi-event combat never clips
 */

export class TabletopAudio {
  constructor() {
    this.ctx = null;
    this.muted = false;
    this._master = null;
    this._bus = null;
    this._whiteBuf = null;
    this._paperBuf = null;
    this._clipCache = new Map();
  }

  _ensure() {
    if (this.muted) return null;
    if (!this.ctx) {
      const AC = typeof window !== 'undefined' && (window.AudioContext || window.webkitAudioContext);
      if (!AC) return null;
      this.ctx = new AC();
      this._buildMasterBus(this.ctx);
    }
    if (this.ctx.state === 'suspended') {
      this.ctx.resume().catch(() => {});
    }
    return this.ctx;
  }

  _buildMasterBus(ctx) {
    const master = ctx.createGain();
    master.gain.value = 0.88;

    const airLp = ctx.createBiquadFilter();
    airLp.type = 'lowpass';
    airLp.frequency.value = 14500;
    airLp.Q.value = 0.5;

    if (typeof ctx.createDynamicsCompressor === 'function') {
      const comp = ctx.createDynamicsCompressor();
      comp.threshold.value = -10;
      comp.knee.value = 14;
      comp.ratio.value = 6;
      comp.attack.value = 0.003;
      comp.release.value = 0.14;
      master.connect(airLp).connect(comp).connect(ctx.destination);
    } else {
      master.connect(airLp).connect(ctx.destination);
    }

    this._master = master;
    this._bus = master;
  }

  toggleMute() {
    this.muted = !this.muted;
    if (this._master && this.ctx) {
      const now = this.ctx.currentTime;
      this._master.gain.cancelScheduledValues(now);
      this._master.gain.setTargetAtTime(this.muted ? 0.0001 : 0.88, now, 0.015);
    }
    return this.muted;
  }

  _out(ctx, pan = 0) {
    const dest = this._bus || ctx.destination;
    if (pan && Math.abs(pan) > 0.01 && typeof ctx.createStereoPanner === 'function') {
      const panner = ctx.createStereoPanner();
      panner.pan.value = Math.max(-0.85, Math.min(0.85, pan));
      panner.connect(dest);
      return panner;
    }
    return dest;
  }

  _jitter(amount = 0.04) {
    return 1 + (Math.random() - 0.5) * 2 * amount;
  }

  _whiteNoise(ctx) {
    if (this._whiteBuf && this._whiteBuf.sampleRate === ctx.sampleRate) {
      return this._whiteBuf;
    }
    const len = Math.max(1, Math.floor(ctx.sampleRate * 0.6));
    const buf = ctx.createBuffer(1, len, ctx.sampleRate);
    const ch = buf.getChannelData(0);
    for (let i = 0; i < len; i++) {
      ch[i] = Math.random() * 2 - 1;
    }
    this._whiteBuf = buf;
    return buf;
  }

  _paperNoise(ctx) {
    if (this._paperBuf && this._paperBuf.sampleRate === ctx.sampleRate) {
      return this._paperBuf;
    }
    const len = Math.max(1, Math.floor(ctx.sampleRate * 0.5));
    const buf = ctx.createBuffer(1, len, ctx.sampleRate);
    const ch = buf.getChannelData(0);
    // Mild pink-shaped + micro-grain paper fiber noise
    let b0 = 0, b1 = 0, b2 = 0;
    for (let i = 0; i < len; i++) {
      const white = Math.random() * 2 - 1;
      b0 = 0.997 * b0 + white * 0.045;
      b1 = 0.985 * b1 + white * 0.08;
      b2 = 0.94 * b2 + white * 0.16;
      const fiber = Math.random() > 0.985 ? (Math.random() * 2 - 1) * 0.35 : 0;
      ch[i] = Math.max(-1, Math.min(1, (b0 + b1 + b2 + white * 0.42 + fiber) * 0.85));
    }
    this._paperBuf = buf;
    return buf;
  }

  _noiseBuffer(ctx, duration) {
    const len = Math.max(1, Math.floor(ctx.sampleRate * duration));
    const buf = ctx.createBuffer(1, len, ctx.sampleRate);
    const ch = buf.getChannelData(0);
    for (let i = 0; i < len; i++) ch[i] = Math.random() * 2 - 1;
    return buf;
  }

  _noiseBurst(ctx, {
    start = ctx.currentTime,
    duration = 0.08,
    filterType = 'bandpass',
    freqStart = 1800,
    freqEnd = 900,
    q = 1.6,
    peak = 0.12,
    attack = 0.008,
    pan = 0,
    paper = true,
  }) {
    const src = ctx.createBufferSource();
    src.buffer = paper ? this._paperNoise(ctx) : this._whiteNoise(ctx);
    const maxOffset = Math.max(0.01, src.buffer.duration - duration - 0.02);
    const offset = Math.random() * maxOffset;

    const filter = ctx.createBiquadFilter();
    filter.type = filterType;
    filter.frequency.setValueAtTime(Math.max(40, freqStart), start);
    if (freqEnd && freqEnd !== freqStart) {
      filter.frequency.exponentialRampToValueAtTime(Math.max(40, freqEnd), start + duration);
    }
    filter.Q.value = q;

    const gain = ctx.createGain();
    gain.gain.setValueAtTime(0.0005, start);
    gain.gain.linearRampToValueAtTime(peak, start + Math.min(attack, duration * 0.45));
    gain.gain.exponentialRampToValueAtTime(0.0005, start + duration);

    src.connect(filter).connect(gain).connect(this._out(ctx, pan));
    src.start(start, offset, duration + 0.015);
    src.stop(start + duration + 0.012);
  }

  _tone(ctx, {
    start = ctx.currentTime,
    duration = 0.2,
    type = 'sine',
    freqStart = 440,
    freqEnd = null,
    peak = 0.08,
    attack = 0.004,
    pan = 0,
    lpFreq = null,
  }) {
    const osc = ctx.createOscillator();
    osc.type = type;
    osc.frequency.setValueAtTime(Math.max(24, freqStart), start);
    if (freqEnd && freqEnd !== freqStart) {
      osc.frequency.exponentialRampToValueAtTime(Math.max(24, freqEnd), start + duration);
    }

    const gain = ctx.createGain();
    gain.gain.setValueAtTime(0.0005, start);
    gain.gain.linearRampToValueAtTime(peak, start + Math.min(attack, duration * 0.4));
    gain.gain.exponentialRampToValueAtTime(0.0005, start + duration);

    const out = this._out(ctx, pan);
    if (lpFreq) {
      const lp = ctx.createBiquadFilter();
      lp.type = 'lowpass';
      lp.frequency.setValueAtTime(lpFreq, start);
      osc.connect(lp).connect(gain).connect(out);
    } else {
      osc.connect(gain).connect(out);
    }
    osc.start(start);
    osc.stop(start + duration + 0.02);
  }

  /**
   * Real parchment/cardstock slide across linen felt + micro edge snap.
   */
  cardSlide(pan = 0, pitch = 1.0) {
    const ctx = this._ensure();
    if (!ctx) return;
    const now = ctx.currentTime;
    const p = pitch * this._jitter(0.055);

    this._noiseBurst(ctx, {
      start: now,
      duration: 0.082,
      filterType: 'bandpass',
      freqStart: 2350 * p,
      freqEnd: 880 * p,
      q: 2.1,
      peak: 0.13,
      attack: 0.009,
      pan,
      paper: true,
    });
    this._noiseBurst(ctx, {
      start: now + 0.003,
      duration: 0.02,
      filterType: 'highpass',
      freqStart: 3400 * p,
      freqEnd: 2400 * p,
      q: 0.9,
      peak: 0.055,
      attack: 0.002,
      pan,
      paper: false,
    });
  }

  /**
   * Crisp cardstock flick (dealing / snapping a card into hand).
   */
  cardFlick(pan = 0, pitch = 1.0) {
    const ctx = this._ensure();
    if (!ctx) return;
    const now = ctx.currentTime;
    const p = pitch * this._jitter(0.06);

    this._noiseBurst(ctx, {
      start: now,
      duration: 0.026,
      filterType: 'bandpass',
      freqStart: 3200 * p,
      freqEnd: 1650 * p,
      q: 1.8,
      peak: 0.16,
      attack: 0.002,
      pan,
      paper: false,
    });
    this._noiseBurst(ctx, {
      start: now + 0.008,
      duration: 0.055,
      filterType: 'bandpass',
      freqStart: 1900 * p,
      freqEnd: 950 * p,
      q: 1.5,
      peak: 0.09,
      attack: 0.006,
      pan,
      paper: true,
    });
    this._tone(ctx, {
      start: now,
      duration: 0.032,
      type: 'sine',
      freqStart: 420 * p,
      freqEnd: 185 * p,
      peak: 0.045,
      attack: 0.002,
      pan,
    });
  }

  /**
   * Tactile heavy cardstock placement on a warm wood/felt tabletop.
   */
  cardPlace(pan = 0) {
    const ctx = this._ensure();
    if (!ctx) return;
    const now = ctx.currentTime;
    const p = this._jitter(0.04);

    // Warm oak-and-felt sub body thud
    this._tone(ctx, {
      start: now,
      duration: 0.095,
      type: 'sine',
      freqStart: 158 * p,
      freqEnd: 52 * p,
      peak: 0.24,
      attack: 0.003,
      pan,
      lpFreq: 420,
    });
    // Secondary hollow tabletop woody knock
    this._tone(ctx, {
      start: now,
      duration: 0.052,
      type: 'triangle',
      freqStart: 310 * p,
      freqEnd: 112 * p,
      peak: 0.09,
      attack: 0.002,
      pan,
      lpFreq: 780,
    });
    // Crisp paper slap transient
    this._noiseBurst(ctx, {
      start: now,
      duration: 0.024,
      filterType: 'bandpass',
      freqStart: 2100 * p,
      freqEnd: 980 * p,
      q: 1.4,
      peak: 0.16,
      attack: 0.002,
      pan,
      paper: true,
    });
    // Brief settling paper rub right after contact
    this._noiseBurst(ctx, {
      start: now + 0.016,
      duration: 0.065,
      filterType: 'bandpass',
      freqStart: 1500 * p,
      freqEnd: 680 * p,
      q: 2.0,
      peak: 0.075,
      attack: 0.008,
      pan,
      paper: true,
    });
  }

  /**
   * Two-stage crisp tabletop card turn & reveal snap.
   */
  cardFlip(pan = 0) {
    const ctx = this._ensure();
    if (!ctx) return;
    const now = ctx.currentTime;
    const p = this._jitter(0.05);

    // Stage 1: Lift & air whip
    this._noiseBurst(ctx, {
      start: now,
      duration: 0.048,
      filterType: 'bandpass',
      freqStart: 2600 * p,
      freqEnd: 4100 * p,
      q: 1.7,
      peak: 0.12,
      attack: 0.005,
      pan: pan - 0.12,
      paper: true,
    });
    // Stage 2: Crisp face-up snap landing
    const t2 = now + 0.042;
    this._noiseBurst(ctx, {
      start: t2,
      duration: 0.058,
      filterType: 'bandpass',
      freqStart: 2400 * p,
      freqEnd: 820 * p,
      q: 1.5,
      peak: 0.17,
      attack: 0.003,
      pan: pan + 0.1,
      paper: false,
    });
    this._tone(ctx, {
      start: t2,
      duration: 0.055,
      type: 'sine',
      freqStart: 205 * p,
      freqEnd: 78 * p,
      peak: 0.11,
      attack: 0.002,
      pan: pan + 0.1,
    });
  }

  /**
   * Gilded brass token / coin clink with realistic metallic partial beating.
   */
  coinClink(pitch = 1.0) {
    const ctx = this._ensure();
    if (!ctx) return;
    const now = ctx.currentTime;
    const p = pitch * this._jitter(0.03);

    this._noiseBurst(ctx, {
      start: now,
      duration: 0.012,
      filterType: 'bandpass',
      freqStart: 5400 * p,
      freqEnd: 3800 * p,
      q: 2.5,
      peak: 0.07,
      attack: 0.001,
      paper: false,
    });

    const partials = [
      { f: 2140, g: 0.068, d: 0.22, pan: -0.14 },
      { f: 2148, g: 0.036, d: 0.19, pan:  0.14 },
      { f: 3260, g: 0.045, d: 0.17, pan:  0.18 },
      { f: 5090, g: 0.024, d: 0.11, pan: -0.18 },
    ];
    for (const part of partials) {
      this._tone(ctx, {
        start: now,
        duration: part.d,
        type: 'sine',
        freqStart: part.f * p,
        peak: part.g,
        attack: 0.002,
        pan: part.pan,
      });
    }
  }

  /**
   * Crystalline cost-merge chime (when personal cost fuses into shared cost capsule).
   */
  costMerge(pitch = 1.0, pan = 0) {
    const ctx = this._ensure();
    if (!ctx) return;
    const now = ctx.currentTime;
    const p = Math.max(0.55, Math.min(2.0, pitch)) * this._jitter(0.02);

    // Delicate crystal-on-crystal contact glint
    this._noiseBurst(ctx, {
      start: now,
      duration: 0.018,
      filterType: 'bandpass',
      freqStart: 4200 * p,
      freqEnd: 2900 * p,
      q: 3.0,
      peak: 0.055,
      attack: 0.002,
      pan,
      paper: false,
    });

    // Warm harmonic crystal bloom (G4 foundation + G5 + D6 + G6 + B6 shimmer)
    const tones = [
      { dt: 0.000, f: 392.00,  g: 0.045, d: 0.24, pan },
      { dt: 0.000, f: 783.99,  g: 0.072, d: 0.34, pan: pan - 0.18 },
      { dt: 0.000, f: 1174.66, g: 0.048, d: 0.30, pan: pan + 0.18 },
      { dt: 0.024, f: 1567.98, g: 0.044, d: 0.28, pan: pan - 0.12 },
      { dt: 0.036, f: 1975.53, g: 0.026, d: 0.24, pan: pan + 0.22 },
    ];
    for (const t of tones) {
      this._tone(ctx, {
        start: now + t.dt,
        duration: t.d,
        type: 'sine',
        freqStart: t.f * p,
        freqEnd: t.f * p * 1.004,
        peak: t.g,
        attack: 0.006,
        pan: t.pan,
      });
    }
  }

  /**
   * Delicate harmonic celesta/harp passive trigger chime.
   */
  passiveChime(pitch = 1.0, pan = 0) {
    const ctx = this._ensure();
    if (!ctx) return;
    const now = ctx.currentTime;
    const p = Math.max(0.6, Math.min(1.8, pitch)) * this._jitter(0.015);

    const notes = [
      { dt: 0.000, f: 659.25,  g: 0.052, d: 0.42, pan: pan - 0.20 },
      { dt: 0.032, f: 987.77,  g: 0.044, d: 0.38, pan: pan + 0.15 },
      { dt: 0.068, f: 1318.51, g: 0.034, d: 0.36, pan: pan - 0.10 },
      { dt: 0.104, f: 1760.00, g: 0.022, d: 0.32, pan: pan + 0.24 },
    ];
    for (const n of notes) {
      this._tone(ctx, {
        start: now + n.dt,
        duration: n.d,
        type: 'sine',
        freqStart: n.f * p,
        peak: n.g,
        attack: 0.008,
        pan: n.pan,
      });
      this._tone(ctx, {
        start: now + n.dt,
        duration: n.d * 0.55,
        type: 'triangle',
        freqStart: n.f * p * 2.0,
        peak: n.g * 0.22,
        attack: 0.005,
        pan: -n.pan * 0.5,
        lpFreq: 5200,
      });
    }
  }

  /**
   * Tactile resin/bone polyhedral dice clatter with settling bounce cadence.
   */
  diceRoll() {
    const ctx = this._ensure();
    if (!ctx) return;
    const now = ctx.currentTime;
    const offsets = [0, 0.046, 0.102, 0.172, 0.255, 0.348];
    const startPan = (Math.random() - 0.5) * 0.4;

    offsets.forEach((dt, i) => {
      const t = now + dt;
      const energy = Math.pow(0.84, i);
      const pan = Math.max(-0.6, Math.min(0.6, startPan + (i - 2.5) * 0.09));
      const base = (690 + (i % 3) * 165 + Math.random() * 140) * this._jitter(0.04);

      this._noiseBurst(ctx, {
        start: t,
        duration: 0.015,
        filterType: 'bandpass',
        freqStart: 2800 + (i % 3) * 550,
        freqEnd: 1500,
        q: 2.6,
        peak: 0.11 * energy,
        attack: 0.001,
        pan,
        paper: false,
      });
      this._tone(ctx, {
        start: t,
        duration: 0.036,
        type: 'triangle',
        freqStart: base,
        freqEnd: base * 0.42,
        peak: 0.095 * energy,
        attack: 0.0015,
        pan,
        lpFreq: 2400,
      });
      this._tone(ctx, {
        start: t,
        duration: 0.024,
        type: 'sine',
        freqStart: base * 2.18,
        freqEnd: base * 1.45,
        peak: 0.042 * energy,
        attack: 0.001,
        pan,
      });
    });
  }

  /**
   * Heavy metallic clash impact: layered inharmonic steel partials + low sub-thump + stereo punch.
   */
  clashImpact(heavy = false, pan = 0) {
    const ctx = this._ensure();
    if (!ctx) return;
    const now = ctx.currentTime;
    const p = this._jitter(0.035);

    // 1. Chest-weight low sub-thump
    this._tone(ctx, {
      start: now,
      duration: heavy ? 0.21 : 0.14,
      type: 'sine',
      freqStart: (heavy ? 132 : 112) * p,
      freqEnd: (heavy ? 32 : 42) * p,
      peak: heavy ? 0.34 : 0.22,
      attack: 0.002,
      pan: pan * 0.4,
      lpFreq: 320,
    });

    // 2. Crisp steel-edge spark transient burst (stereo punch)
    this._noiseBurst(ctx, {
      start: now,
      duration: heavy ? 0.048 : 0.032,
      filterType: 'bandpass',
      freqStart: 3800 * p,
      freqEnd: 1450 * p,
      q: 1.5,
      peak: heavy ? 0.24 : 0.16,
      attack: 0.0015,
      pan: pan - 0.25,
      paper: false,
    });
    this._noiseBurst(ctx, {
      start: now + 0.003,
      duration: heavy ? 0.038 : 0.024,
      filterType: 'highpass',
      freqStart: 4200 * p,
      freqEnd: 2600 * p,
      q: 1.1,
      peak: heavy ? 0.15 : 0.10,
      attack: 0.001,
      pan: pan + 0.28,
      paper: false,
    });

    // 3. Layered inharmonic blade-ring partials with stereo width
    const root = (heavy ? 430 : 520) * p;
    const ratios = heavy
      ? [
          { r: 1.00, g: 0.125, d: 0.42, pan: -0.32, type: 'triangle' },
          { r: 1.43, g: 0.095, d: 0.38, pan:  0.34, type: 'sine' },
          { r: 2.17, g: 0.072, d: 0.32, pan: -0.46, type: 'sine' },
          { r: 2.94, g: 0.056, d: 0.26, pan:  0.48, type: 'sine' },
          { r: 3.81, g: 0.038, d: 0.20, pan: -0.24, type: 'sine' },
          { r: 4.96, g: 0.025, d: 0.14, pan:  0.26, type: 'sine' },
        ]
      : [
          { r: 1.00, g: 0.090, d: 0.28, pan: -0.26, type: 'triangle' },
          { r: 1.47, g: 0.068, d: 0.25, pan:  0.28, type: 'sine' },
          { r: 2.24, g: 0.048, d: 0.20, pan: -0.38, type: 'sine' },
          { r: 3.12, g: 0.032, d: 0.15, pan:  0.38, type: 'sine' },
        ];

    for (const part of ratios) {
      const freq = root * part.r;
      this._tone(ctx, {
        start: now,
        duration: part.d,
        type: part.type,
        freqStart: freq,
        freqEnd: freq * 0.94,
        peak: part.g,
        attack: 0.002,
        pan: Math.max(-0.85, Math.min(0.85, pan + part.pan)),
        lpFreq: part.type === 'triangle' ? 3200 : null,
      });
    }

    // 4. Heavy clash secondary steel shimmer echo
    if (heavy) {
      this._tone(ctx, {
        start: now + 0.024,
        duration: 0.32,
        type: 'sine',
        freqStart: root * 2.52,
        freqEnd: root * 2.42,
        peak: 0.045,
        attack: 0.004,
        pan: pan + 0.35,
      });
    }
  }

  /**
   * Crystalline shield ward block: crisp jade barrier deflection + glassy harmonic bloom.
   */
  shieldBlock(pan = 0) {
    const ctx = this._ensure();
    if (!ctx) return;
    const now = ctx.currentTime;
    const p = this._jitter(0.03);

    this._tone(ctx, {
      start: now,
      duration: 0.085,
      type: 'sine',
      freqStart: 255 * p,
      freqEnd: 118 * p,
      peak: 0.14,
      attack: 0.002,
      pan,
    });
    this._noiseBurst(ctx, {
      start: now,
      duration: 0.028,
      filterType: 'bandpass',
      freqStart: 4600 * p,
      freqEnd: 2800 * p,
      q: 3.2,
      peak: 0.085,
      attack: 0.002,
      pan,
      paper: false,
    });

    const partials = [
      { f: 659.25,  end: 698.46,  g: 0.075, d: 0.24, pan: pan - 0.22 },
      { f: 987.77,  end: 1046.50, g: 0.056, d: 0.22, pan: pan + 0.22 },
      { f: 1480.00, end: 1510.00, g: 0.038, d: 0.18, pan: pan - 0.32 },
      { f: 2217.46, end: 2245.00, g: 0.024, d: 0.15, pan: pan + 0.32 },
    ];
    for (const part of partials) {
      this._tone(ctx, {
        start: now,
        duration: part.d,
        type: 'sine',
        freqStart: part.f * p,
        freqEnd: part.end * p,
        peak: part.g,
        attack: 0.003,
        pan: part.pan,
      });
    }
  }

  /**
   * Brittle multi-grain crystal/ward shatter & erosion crackle.
   */
  shieldErode(pan = 0) {
    const ctx = this._ensure();
    if (!ctx) return;
    const now = ctx.currentTime;

    this._noiseBurst(ctx, {
      start: now,
      duration: 0.23,
      filterType: 'bandpass',
      freqStart: 1380,
      freqEnd: 310,
      q: 1.5,
      peak: 0.15,
      attack: 0.004,
      pan,
      paper: true,
    });

    const grains = [0.0, 0.018, 0.042, 0.071, 0.104, 0.145, 0.188];
    grains.forEach((dt, idx) => {
      const t = now + dt;
      const decay = 1 - idx * 0.1;
      const gPan = Math.max(-0.75, Math.min(0.75, pan + (idx % 2 === 0 ? -1 : 1) * (0.14 + idx * 0.06)));
      const crackFreq = 2100 + ((idx * 733) % 2700) + Math.random() * 450;

      this._noiseBurst(ctx, {
        start: t,
        duration: 0.018 + (idx % 2) * 0.008,
        filterType: 'bandpass',
        freqStart: crackFreq,
        freqEnd: crackFreq * 0.68,
        q: 3.4,
        peak: 0.11 * decay,
        attack: 0.001,
        pan: gPan,
        paper: false,
      });
      this._tone(ctx, {
        start: t,
        duration: 0.042 + (idx % 3) * 0.016,
        type: 'sine',
        freqStart: crackFreq * 0.78,
        freqEnd: crackFreq * 0.66,
        peak: 0.042 * decay,
        attack: 0.001,
        pan: gPan,
      });
    });
  }

  /**
   * Crystalline polyhedral die fracture & violent shatter.
   */
  dieShatter(pan = 0) {
    const ctx = this._ensure();
    if (!ctx) return;
    const now = ctx.currentTime;
    const p = this._jitter(0.05);

    this._noiseBurst(ctx, {
      start: now,
      duration: 0.036,
      filterType: 'bandpass',
      freqStart: 4200 * p,
      freqEnd: 1400 * p,
      q: 2.2,
      peak: 0.24,
      attack: 0.001,
      pan,
      paper: false,
    });
    this._tone(ctx, {
      start: now,
      duration: 0.14,
      type: 'triangle',
      freqStart: 980 * p,
      freqEnd: 175 * p,
      peak: 0.16,
      attack: 0.001,
      pan,
    });
    [0.03, 0.068, 0.105, 0.148, 0.195].forEach((dt, idx) => {
      const f = (2400 + idx * 540) * p;
      this._tone(ctx, {
        start: now + dt,
        duration: 0.055,
        type: 'sine',
        freqStart: f,
        freqEnd: f * 0.78,
        peak: 0.068 * (1 - idx * 0.14),
        attack: 0.001,
        pan: Math.max(-0.75, Math.min(0.75, pan + (idx % 2 ? 0.18 : -0.18))),
      });
    });
  }

  /**
   * Heavy skill card diagonal cleave, cardstock tear & cinder burst.
   */
  cardShatter(pan = 0) {
    const ctx = this._ensure();
    if (!ctx) return;
    const now = ctx.currentTime;
    const p = this._jitter(0.04);

    // Crisp crimson slash cleave
    this._noiseBurst(ctx, {
      start: now,
      duration: 0.065,
      filterType: 'bandpass',
      freqStart: 3600 * p,
      freqEnd: 880 * p,
      q: 1.6,
      peak: 0.25,
      attack: 0.002,
      pan,
      paper: true,
    });
    // Low shatter body impact
    this._tone(ctx, {
      start: now + 0.02,
      duration: 0.18,
      type: 'sine',
      freqStart: 164 * p,
      freqEnd: 42 * p,
      peak: 0.26,
      attack: 0.002,
      pan,
      lpFreq: 480,
    });
    // Secondary paper rip & ember crackles
    [0.055, 0.105, 0.16, 0.22].forEach((dt, idx) => {
      this._noiseBurst(ctx, {
        start: now + dt,
        duration: 0.032,
        filterType: 'bandpass',
        freqStart: (1850 + idx * 420) * p,
        freqEnd: 740 * p,
        q: 2.0,
        peak: 0.13 * (1 - idx * 0.18),
        attack: 0.002,
        pan: Math.max(-0.75, Math.min(0.75, pan + (idx % 2 ? 0.22 : -0.22))),
        paper: true,
      });
    });
  }

  /**
   * Weighty visceral damage impact: sub-punch + damped armor crunch + impact slap.
   */
  hitDamage(heavy = false, pan = 0) {
    const ctx = this._ensure();
    if (!ctx) return;
    const now = ctx.currentTime;
    const p = this._jitter(0.04);

    this._tone(ctx, {
      start: now,
      duration: heavy ? 0.22 : 0.17,
      type: 'sine',
      freqStart: (heavy ? 148 : 132) * p,
      freqEnd: 34 * p,
      peak: heavy ? 0.32 : 0.24,
      attack: 0.002,
      pan,
      lpFreq: 360,
    });
    this._tone(ctx, {
      start: now,
      duration: 0.12,
      type: 'sawtooth',
      freqStart: 165 * p,
      freqEnd: 46 * p,
      peak: heavy ? 0.11 : 0.08,
      attack: 0.002,
      pan,
      lpFreq: 480,
    });
    this._noiseBurst(ctx, {
      start: now,
      duration: 0.046,
      filterType: 'bandpass',
      freqStart: 1250 * p,
      freqEnd: 380 * p,
      q: 1.2,
      peak: heavy ? 0.20 : 0.14,
      attack: 0.002,
      pan,
      paper: true,
    });
  }

  /**
   * Warm sunlit restorative chord shimmer.
   */
  healChime(pan = 0) {
    const ctx = this._ensure();
    if (!ctx) return;
    const now = ctx.currentTime;
    const notes = [
      { f: 523.25, dt: 0.000, g: 0.062, pan: pan - 0.18 },
      { f: 659.25, dt: 0.042, g: 0.056, pan: pan + 0.12 },
      { f: 783.99, dt: 0.084, g: 0.050, pan: pan - 0.08 },
      { f: 1046.5, dt: 0.130, g: 0.036, pan: pan + 0.20 },
    ];
    for (const n of notes) {
      this._tone(ctx, {
        start: now + n.dt,
        duration: 0.34,
        type: 'sine',
        freqStart: n.f,
        peak: n.g,
        attack: 0.012,
        pan: n.pan,
      });
    }
  }

  /**
   * Warm resonant cast-bronze turn bell with authentic bell partials & soft felt mallet tap.
   */
  turnBell() {
    const ctx = this._ensure();
    if (!ctx) return;
    const now = ctx.currentTime;
    const prime = 392.0; // Warm G4 bronze bell

    this._noiseBurst(ctx, {
      start: now,
      duration: 0.026,
      filterType: 'lowpass',
      freqStart: 1400,
      freqEnd: 420,
      q: 0.9,
      peak: 0.095,
      attack: 0.002,
      paper: true,
    });
    this._tone(ctx, {
      start: now,
      duration: 0.065,
      type: 'sine',
      freqStart: 220,
      freqEnd: 145,
      peak: 0.08,
      attack: 0.002,
    });

    const modes = [
      { r: 0.500, g: 0.060, d: 0.98, pan:  0.00 },
      { r: 1.000, g: 0.082, d: 0.88, pan: -0.14 },
      { r: 1.003, g: 0.038, d: 0.82, pan:  0.14 },
      { r: 1.252, g: 0.044, d: 0.68, pan:  0.18 },
      { r: 1.500, g: 0.036, d: 0.62, pan: -0.18 },
      { r: 2.004, g: 0.030, d: 0.52, pan:  0.10 },
      { r: 2.985, g: 0.016, d: 0.34, pan: -0.10 },
    ];
    for (const m of modes) {
      this._tone(ctx, {
        start: now,
        duration: m.d,
        type: 'sine',
        freqStart: prime * m.r,
        peak: m.g,
        attack: 0.005,
        pan: m.pan,
      });
    }
  }

  async _playAudioUrl(url, gainVal = 0.28, pan = 0) {
    if (!url || typeof url !== 'string' || !url.startsWith('/sfx/')) return false;
    const ctx = this._ensure();
    if (!ctx || typeof fetch !== 'function' || typeof ctx.decodeAudioData !== 'function') return false;
    try {
      let bufPromise = this._clipCache.get(url);
      if (!bufPromise) {
        bufPromise = fetch(url)
          .then((res) => (res.ok ? res.arrayBuffer() : Promise.reject(new Error('sfx_missing'))))
          .then((arr) => ctx.decodeAudioData(arr));
        this._clipCache.set(url, bufPromise);
      }
      const audioBuf = await bufPromise;
      if (this.muted || !audioBuf) return false;
      const src = ctx.createBufferSource();
      src.buffer = audioBuf;
      const gain = ctx.createGain();
      gain.gain.value = Math.max(0.02, Math.min(0.60, Number(gainVal) || 0.28));
      src.connect(gain).connect(this._out(ctx, pan));
      src.start(ctx.currentTime);
      return true;
    } catch (_) {
      this._clipCache.delete(url);
      return false;
    }
  }

  /**
   * Play a declarative FX DSL audio recipe (named preset, `/sfx/` clip, or procedural WebAudio synth params).
   */
  playSynthRecipe(recipe, pan = 0) {
    if (!recipe || typeof recipe !== 'object') return false;
    let played = false;
    if (recipe.url) {
      this._playAudioUrl(recipe.url, recipe.gain, pan);
      played = true;
      if (!recipe.preset && !recipe.waveform) return true;
    }
    const preset = recipe.preset;
    if (preset && !recipe.waveform) {
      if (preset === 'slash' || preset === 'clash_heavy') this.clashImpact(true, pan);
      else if (preset === 'pierce' || preset === 'clash') this.clashImpact(false, pan);
      else if (preset === 'blunt') {
        this.clashImpact(true, pan);
        this.hitDamage(true, pan);
      } else if (preset === 'bell') this.turnBell();
      else if (preset === 'passive') this.passiveChime(1.0, pan);
      else if (preset === 'shield') this.shieldBlock(pan);
      else if (preset === 'shatter') this.shieldErode(pan);
      else if (preset === 'heal') this.healChime(pan);
      else if (preset === 'coin') this.coinClink(1.0, pan);
      else if (preset === 'wind') {
        const ctx = this._ensure();
        if (ctx) {
          this._noiseBurst(ctx, {
            start: ctx.currentTime,
            duration: 0.26,
            filterType: 'bandpass',
            freqStart: 1550,
            freqEnd: 420,
            q: 2.2,
            peak: 0.14,
            attack: 0.015,
            pan,
          });
        }
      }
      return true;
    }

    const ctx = this._ensure();
    if (!ctx) return false;
    const now = ctx.currentTime;
    const durSec = Math.max(0.04, Math.min(1.2, (Number(recipe.duration_ms) || 240) / 1000));
    const f0 = Math.max(45, Math.min(5000, Number(recipe.freq_start) || 440));
    const f1 = Math.max(40, Math.min(5000, Number(recipe.freq_end) || f0));
    const gain = Math.max(0.02, Math.min(0.26, Number(recipe.gain) || 0.13));

    if (recipe.waveform === 'noise') {
      this._noiseBurst(ctx, {
        start: now,
        duration: durSec,
        filterType: 'bandpass',
        freqStart: f0,
        freqEnd: f1,
        q: 2.0,
        peak: gain,
        attack: Math.min(0.02, durSec * 0.15),
        pan,
      });
      return true;
    }

    const type = ['sine', 'triangle', 'sawtooth', 'square'].includes(recipe.waveform) ? recipe.waveform : 'sine';
    const harmonics = Array.isArray(recipe.harmonics) && recipe.harmonics.length ? recipe.harmonics.slice(0, 6) : [1.0];
    const perGain = gain / Math.sqrt(harmonics.length);
    harmonics.forEach((ratio, idx) => {
      const r = Math.max(0.25, Math.min(6.0, Number(ratio) || 1.0));
      this._tone(ctx, {
        start: now + idx * 0.004,
        duration: durSec * (1 - idx * 0.08),
        type,
        freqStart: Math.min(8000, f0 * r),
        freqEnd: Math.min(8000, f1 * r),
        peak: perGain * Math.pow(0.82, idx),
        attack: 0.006,
        pan: Math.max(-0.8, Math.min(0.8, pan + (idx % 2 === 0 ? -0.06 : 0.06))),
      });
    });

    if (recipe.noise_freq) {
      const nf = Math.max(120, Math.min(6000, Number(recipe.noise_freq) || 900));
      this._noiseBurst(ctx, {
        start: now,
        duration: Math.min(0.16, durSec * 0.55),
        filterType: 'bandpass',
        freqStart: nf,
        freqEnd: nf * 0.45,
        q: 1.4,
        peak: gain * 0.55,
        attack: 0.003,
        pan,
      });
    }
    return true;
  }
}

export const SoundEngine = TabletopAudio;
