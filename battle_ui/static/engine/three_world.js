/**
 * Three.js WebGL 3D & Custom GLSL Shader Engine for 《光点计划 III》.
 * Strictly BRIGHT palette — ZERO black, ZERO blue-purple!
 * Frontal low-FOV pixel-calibrated 3D camera (z = 0 aligns 1:1 with screen pixels):
 *  - Custom GLSL bright sunlit arena shader with Left(P1)/Right(P2) territory light,
 *    intent-driven spotlight aura, 4-slot independent shockwave pool & ambient impact ripples
 *  - True 3D polyhedral dice (d4, d6, d8, d12, d16, d20) bound 1:1 to Matter.js colliding clash bodies
 *  - True 3D double-sided card flips & parabolic arcs (place, pull, reveal, swap, recycle)
 *  - Layered tapered 3D combat choreography: razor slash crescents, aerodynamic pierce lances,
 *    fractured blunt shock-hammers, crystalline hex block walls, shield dome pulses & tapered comet energy beams
 *  - Single-draw-call InstancedMesh 3D sparks & shockwave rings
 */

import * as THREE from '../vendor/three.module.js';

const DIE_PALETTES = {
  speed:  { body: 0xf0c75e, edge: 0x8f6618, hex: '#b87d14' },
  slash:  { body: 0xe65c52, edge: 0x94241e, hex: '#d1382e' },
  pierce: { body: 0xe65c52, edge: 0x94241e, hex: '#d1382e' },
  blunt:  { body: 0xe65c52, edge: 0x94241e, hex: '#d1382e' },
  block:  { body: 0x4ca0eb, edge: 0x1a5696, hex: '#2478cc' },
  evade:  { body: 0x4ca0eb, edge: 0x1a5696, hex: '#2478cc' },
  blank:  { body: 0xc9bfb0, edge: 0x73695b, hex: '#7a6f62' },
  breath: { body: 0x45ba9c, edge: 0x176b56, hex: '#238c72' },
};

const SHOCKWAVE_POOL_SIZE = 4;
const SHOCKWAVE_DURATION = 0.72;
const DEFAULT_WARM_GOLD = 0xd99426;

function applySafeColor(target, colorHex, fallback = DEFAULT_WARM_GOLD) {
  if (colorHex instanceof THREE.Color) {
    target.copy(colorHex);
    return target;
  }
  if (Array.isArray(colorHex) && colorHex.length >= 3) {
    target.setRGB(colorHex[0], colorHex[1], colorHex[2]);
    return target;
  }
  if (typeof colorHex === 'number' && Number.isFinite(colorHex)) {
    target.setHex(colorHex);
    return target;
  }
  if (typeof colorHex === 'string' && colorHex.trim()) {
    try {
      target.set(colorHex);
      return target;
    } catch (_) {
      // fall through to fallback
    }
  }
  target.setHex(fallback);
  return target;
}

const BG_VERTEX = /* glsl */ `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = vec4(position.xy, 0.999, 1.0);
  }
`;

const BG_FRAGMENT = /* glsl */ `
  precision highp float;
  varying vec2 vUv;
  uniform float uTime;
  uniform vec2 uResolution;
  uniform vec4 uRipples[4];
  uniform vec3 uRippleColors[4];
  uniform vec4 uShockwaves[4];
  uniform vec3 uShockwaveColors[4];
  uniform vec2 uIntentUv;
  uniform vec3 uIntentColor;
  uniform float uIntentMix;
  uniform vec3 uPhaseTint;
  uniform float uCombatFocus;

  float hash(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123);
  }

  float noise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    float a = hash(i);
    float b = hash(i + vec2(1.0, 0.0));
    float c = hash(i + vec2(0.0, 1.0));
    float d = hash(i + vec2(1.0, 1.0));
    return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
  }

  void main() {
    vec2 aspect = vec2(uResolution.x / max(uResolution.y, 1.0), 1.0);
    vec2 p = (vUv - 0.5) * aspect;
    float radial = length(p * vec2(0.82, 1.02));

    // Bright sunlit warm alabaster base (strictly ZERO black, ZERO blue-purple)
    vec3 centerCol = vec3(0.985, 0.978, 0.956);
    vec3 edgeCol = vec3(0.924, 0.902, 0.860);
    vec3 col = mix(centerCol, edgeCol, smoothstep(0.06, 0.98, radial));

    // Left (P1 sunlit jade mist) vs Right (P2 sunlit coral-sand mist) confrontational light gradient
    float leftBias = smoothstep(0.42, 0.0, vUv.x);
    float rightBias = smoothstep(0.58, 1.0, vUv.x);
    col = mix(col, vec3(0.910, 0.962, 0.935), leftBias * 0.24);
    col = mix(col, vec3(0.982, 0.922, 0.892), rightBias * 0.24);

    // Living sunlit caustics drifting across the battlefield
    float w1 = noise(p * 3.0 + vec2(uTime * 0.055, -uTime * 0.035));
    float w2 = noise(p * 6.2 - vec2(uTime * 0.038, uTime * 0.045));
    float caustic = smoothstep(0.36, 0.86, w1 * 0.62 + w2 * 0.38);
    col = mix(col, vec3(1.0, 0.994, 0.972), caustic * 0.36);

    // Sculptural subtle concentric arena rings in center floor
    float ringDist = length(p * vec2(0.96, 1.18));
    float r1 = exp(-pow((ringDist - 0.32) * 140.0, 2.0));
    float r2 = exp(-pow((ringDist - 0.46) * 160.0, 2.0));
    float axisLine = exp(-pow(abs(p.x) * 260.0, 2.0)) * smoothstep(0.45, 0.05, abs(p.y));
    float arenaInk = (r1 * 0.45 + r2 * 0.28 + axisLine * 0.32) * (0.38 + uCombatFocus * 0.35);
    col = mix(col, vec3(0.84, 0.72, 0.46), arenaInk * 0.35);

    // Combat Showdown warm sunlit spotlight (bright warm sand edge, luminous ivory-gold center!)
    if (uCombatFocus > 0.005) {
      float spot = 1.0 - smoothstep(0.16, 0.78, radial);
      col = mix(col, vec3(1.0, 0.985, 0.935), spot * uCombatFocus * 0.36);
      col = mix(col, vec3(0.91, 0.87, 0.80), (1.0 - spot) * uCombatFocus * 0.22);
    }

    // Subtle intent-driven warm sunlit spotlight aura around hovered card / fighter
    if (uIntentMix > 0.003) {
      float intentDist = length((vUv - uIntentUv) * aspect);
      float intentAura = exp(-intentDist * intentDist * 10.5) * 0.21 * uIntentMix;
      float intentSun = exp(-intentDist * intentDist * 24.0) * 0.14 * uIntentMix;
      float haloR = 0.105 + 0.006 * sin(uTime * 3.1);
      float intentHalo = exp(-pow((intentDist - haloR) * 78.0, 2.0)) * 0.13 * uIntentMix;
      col = mix(col, vec3(1.0, 0.990, 0.954), clamp(intentSun, 0.0, 0.22));
      col = mix(col, uIntentColor, clamp(intentAura + intentHalo, 0.0, 0.32));
    }

    // Subtle warm phase glow
    col = mix(col, uPhaseTint, (1.0 - smoothstep(0.0, 0.76, radial)) * 0.08);

    // Fine luminous grain
    float grain = (hash(gl_FragCoord.xy * 0.5) - 0.5) * 0.012;
    col += grain;

    // Ambient impact ripples (triggerRipple)
    for (int i = 0; i < 4; i++) {
      if (uRipples[i].w > 0.5) {
        float age = uRipples[i].z;
        float dist = length((vUv - uRipples[i].xy) * aspect);
        float radius = age * 0.65;
        float ring = exp(-pow((dist - radius) * 22.0, 2.0)) * max(0.0, 1.0 - age / 1.15);
        col = mix(col, uRippleColors[i], ring * 0.36);
      }
    }

    // 4-slot independent shockwave pool (emitShockwave — never truncates earlier ripples!)
    for (int i = 0; i < 4; i++) {
      vec4 sw = uShockwaves[i];
      if (sw.w > 0.5) {
        float normAge = clamp(sw.z, 0.0, 1.0);
        float dist = length((vUv - sw.xy) * aspect);
        float easeR = 1.0 - pow(1.0 - normAge, 2.2);
        float radius = easeR * 0.54;
        float fade = (1.0 - normAge) * (1.0 - normAge);
        float crest = exp(-pow((dist - radius) * 34.0, 2.0)) * fade * 0.42;
        float innerEcho = exp(-pow((dist - radius * 0.78) * 24.0, 2.0)) * fade * 0.16;
        float sunRim = exp(-pow((dist - radius) * 62.0, 2.0)) * fade * 0.24;
        col = mix(col, uShockwaveColors[i], clamp(crest + innerEcho, 0.0, 0.46));
        col = mix(col, vec3(1.0, 0.988, 0.945), clamp(sunRim, 0.0, 0.28));
      }
    }

    gl_FragColor = vec4(col, 1.0);
  }
`;

function createD16Geometry(radius) {
  const sides = 8;
  const top = [0, radius * 1.16, 0];
  const bot = [0, -radius * 1.16, 0];
  const ring = [];
  for (let i = 0; i < sides; i++) {
    const a = (i / sides) * Math.PI * 2;
    ring.push([Math.cos(a) * radius, 0, Math.sin(a) * radius]);
  }
  const positions = [];
  for (let i = 0; i < sides; i++) {
    const curr = ring[i];
    const next = ring[(i + 1) % sides];
    positions.push(...top, ...next, ...curr);
    positions.push(...bot, ...curr, ...next);
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geo.computeVertexNormals();
  return geo;
}

function makePolyGeo(sides, radius) {
  if (sides <= 4) return new THREE.TetrahedronGeometry(radius * 1.14);
  if (sides <= 6) return new THREE.BoxGeometry(radius * 1.28, radius * 1.28, radius * 1.28);
  if (sides <= 8) return new THREE.OctahedronGeometry(radius * 1.06);
  if (sides <= 12) return new THREE.DodecahedronGeometry(radius * 1.04);
  if (sides <= 16) return createD16Geometry(radius * 1.04);
  return new THREE.IcosahedronGeometry(radius * 1.04);
}

/**
 * Custom razor-tapered crescent blade arc geometry (zero blunt flat ring ends!).
 */
function makeTaperedCrescentGeo(innerR, outerR, arcSpan, segments = 32, leadingBias = 0.64) {
  const positions = [];
  const indices = [];
  const baseThick = (outerR - innerR) * 0.5;
  const baseMid = (innerR + outerR) * 0.5;

  for (let i = 0; i <= segments; i++) {
    const u = i / segments;
    const angle = -arcSpan * 0.5 + u * arcSpan;
    const sinEnv = Math.sin(u * Math.PI);
    const taper = Math.pow(Math.max(0, sinEnv), 0.72);
    // Asymmetric weight toward leading edge of slash
    const skew = 0.62 + 0.54 * Math.exp(-Math.pow((u - leadingBias) / 0.34, 2));
    const halfW = baseThick * taper * skew;
    const midR = baseMid + (1 - taper) * baseThick * 0.32;
    const rIn = Math.max(2, midR - halfW);
    const rOut = midR + halfW;
    const ca = Math.cos(angle);
    const sa = Math.sin(angle);
    positions.push(ca * rIn, sa * rIn, 0);
    positions.push(ca * rOut, sa * rOut, 0);
  }

  for (let i = 0; i < segments; i++) {
    const a = i * 2;
    const b = a + 1;
    const c = a + 2;
    const d = a + 3;
    indices.push(a, b, c, b, d, c);
  }

  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geo.setIndex(indices);
  geo.computeVertexNormals();
  return geo;
}

/**
 * Elongated 4-point tapered diamond flash/spike geometry centered along +X.
 */
function makeDiamondSpikeGeo(length, halfWidth, offsetX = 0) {
  const tipX = offsetX + length;
  const shoulderX = offsetX + length * 0.24;
  const positions = new Float32Array([
    offsetX, 0, 0,
    shoulderX, halfWidth, 0,
    tipX, 0, 0,
    offsetX, 0, 0,
    tipX, 0, 0,
    shoulderX, -halfWidth, 0,
  ]);
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geo.computeVertexNormals();
  return geo;
}

/**
 * Dynamic parabolic comet ribbon trail geometry (updated smoothly per frame).
 */
function makeCometRibbonGeo(segments = 14) {
  const vertCount = (segments + 1) * 2;
  const positions = new Float32Array(vertCount * 3);
  const indices = [];
  for (let i = 0; i < segments; i++) {
    const a = i * 2;
    const b = a + 1;
    const c = a + 2;
    const d = a + 3;
    indices.push(a, b, c, b, d, c);
  }
  const geo = new THREE.BufferGeometry();
  const attr = new THREE.BufferAttribute(positions, 3);
  attr.setUsage(THREE.DynamicDrawUsage);
  geo.setAttribute('position', attr);
  geo.setIndex(indices);
  return geo;
}

function updateCometRibbonGeo(geo, p0, mid, p1, tHead, tailSpan, maxHalfWidth, segments) {
  const attr = geo.getAttribute('position');
  const tStart = Math.max(0, tHead - tailSpan);
  const span = Math.max(0.0001, tHead - tStart);

  for (let i = 0; i <= segments; i++) {
    const frac = i / segments; // 0 = tail tip, 1 = comet head
    const s = tStart + frac * span;
    const u = 1 - s;
    const x = u * u * p0.x + 2 * u * s * mid.x + s * s * p1.x;
    const y = u * u * p0.y + 2 * u * s * mid.y + s * s * p1.y;
    const z = u * u * p0.z + 2 * u * s * mid.z + s * s * p1.z;

    // Curve tangent in XY for perpendicular ribbon expansion
    const tx = 2 * u * (mid.x - p0.x) + 2 * s * (p1.x - mid.x);
    const ty = 2 * u * (mid.y - p0.y) + 2 * s * (p1.y - mid.y);
    const tLen = Math.hypot(tx, ty) || 1;
    const nx = -ty / tLen;
    const ny = tx / tLen;

    // Smooth teardrop taper: razor point at tail -> plump just behind head -> pinches at core
    const widthProfile = Math.pow(frac, 1.35) * (1 - Math.pow(frac, 6) * 0.25);
    const hw = maxHalfWidth * widthProfile;

    attr.setXYZ(i * 2, x + nx * hw, y + ny * hw, z);
    attr.setXYZ(i * 2 + 1, x - nx * hw, y - ny * hw, z);
  }
  attr.needsUpdate = true;
}

function makeDieReadoutTexture(value, sub, accentHex) {
  const c = document.createElement('canvas');
  c.width = 256;
  c.height = 256;
  const g = c.getContext('2d');
  g.clearRect(0, 0, 256, 256);

  g.beginPath();
  g.arc(128, 128, 78, 0, Math.PI * 2);
  g.fillStyle = 'rgba(255, 252, 245, 0.96)';
  g.fill();
  g.lineWidth = 8;
  g.strokeStyle = accentHex;
  g.stroke();

  g.font = '900 88px "Segoe UI", "Microsoft YaHei", sans-serif';
  g.textAlign = 'center';
  g.textBaseline = 'middle';
  g.fillStyle = '#3b322a';
  g.fillText(String(value), 128, sub ? 114 : 128);

  if (sub) {
    g.font = '800 28px "Segoe UI", "Microsoft YaHei", sans-serif';
    g.fillStyle = accentHex;
    g.fillText(sub, 128, 175);
  }

  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

function makeBrightCardTexture({ title, cost, ownerName, accentHex, isBack }) {
  const c = document.createElement('canvas');
  c.width = 256;
  c.height = 356;
  const g = c.getContext('2d');

  if (isBack) {
    g.fillStyle = '#f8f4ea';
    g.fillRect(0, 0, 256, 356);
    g.strokeStyle = accentHex || '#1e8f68';
    g.lineWidth = 10;
    g.strokeRect(10, 10, 236, 336);
    g.lineWidth = 2.5;
    g.strokeRect(24, 24, 208, 308);
    g.save();
    g.translate(128, 178);
    g.fillStyle = accentHex || '#1e8f68';
    g.globalAlpha = 0.14;
    g.beginPath();
    g.arc(0, 0, 68, 0, Math.PI * 2);
    g.fill();
    g.globalAlpha = 0.9;
    g.beginPath();
    for (let i = 0; i < 8; i++) {
      const a = (i * Math.PI) / 4;
      const r = i % 2 === 0 ? 54 : 17;
      if (i === 0) g.moveTo(Math.cos(a) * r, Math.sin(a) * r);
      else g.lineTo(Math.cos(a) * r, Math.sin(a) * r);
    }
    g.closePath();
    g.fill();
    g.restore();
  } else {
    g.fillStyle = '#fffdf8';
    g.fillRect(0, 0, 256, 356);
    g.fillStyle = accentHex || '#1e8f68';
    g.globalAlpha = 0.16;
    g.fillRect(0, 0, 256, 118);
    g.globalAlpha = 1;
    g.strokeStyle = accentHex || '#1e8f68';
    g.lineWidth = 8;
    g.strokeRect(6, 6, 244, 344);

    g.beginPath();
    g.arc(46, 48, 24, 0, Math.PI * 2);
    g.fillStyle = accentHex || '#1e8f68';
    g.fill();
    g.fillStyle = '#fffdf8';
    g.font = '800 30px "Segoe UI", sans-serif';
    g.textAlign = 'center';
    g.textBaseline = 'middle';
    g.fillText(String(cost ?? ''), 46, 49);

    g.fillStyle = '#3b322a';
    g.font = '800 28px "Microsoft YaHei", "PingFang SC", sans-serif';
    g.textAlign = 'left';
    g.fillText(String(title || '').slice(0, 6), 82, 46);
    if (ownerName) {
      g.fillStyle = accentHex || '#1e8f68';
      g.font = '700 19px "Microsoft YaHei", sans-serif';
      g.fillText(ownerName, 82, 76);
    }
    g.fillStyle = '#efeae0';
    for (let i = 0; i < 3; i++) {
      g.fillRect(22, 134 + i * 62, 212, 46);
    }
  }
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

const MAX_SPARKS = 240;

export class ThreeWorld {
  constructor(canvas) {
    this.canvas = canvas;
    this.width = window.innerWidth;
    this.height = window.innerHeight;
    this.fov = 28;
    this.targetCombatFocus = 0;
    this.combatFocus = 0;

    this.renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: true,
      alpha: false,
      powerPreference: 'high-performance',
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.setSize(this.width, this.height, false);
    this.renderer.setClearColor(0xf6f3eb, 1);

    // Background GLSL Shader scene
    this.bgScene = new THREE.Scene();
    this.bgCamera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);

    // Ambient impact ripples (backward-compatible triggerRipple pool)
    this.ripples = Array.from({ length: 4 }, () => ({
      uv: new THREE.Vector2(0.5, 0.5),
      age: 99,
      active: 0,
      color: new THREE.Color(0xe6aa42),
    }));
    this._rippleCursor = 0;

    // 4-slot independent shockwave pool (emitShockwave — rapid bursts never truncate earlier rings!)
    this.shockwaves = Array.from({ length: SHOCKWAVE_POOL_SIZE }, () => ({
      uv: new THREE.Vector2(0.5, 0.5),
      age: 1,
      duration: SHOCKWAVE_DURATION,
      active: 0,
      color: new THREE.Color(DEFAULT_WARM_GOLD),
    }));
    this._shockwaveCursor = 0;

    // Continuous intent-driven sunlit spotlight aura state
    this.intentTarget = {
      active: 0,
      uv: new THREE.Vector2(0.5, 0.5),
      color: new THREE.Color(0xd99a38),
    };
    this.intentState = {
      mix: 0,
      uv: new THREE.Vector2(0.5, 0.5),
      color: new THREE.Color(0xd99a38),
    };

    this.bgUniforms = {
      uTime: { value: 0 },
      uResolution: { value: new THREE.Vector2(this.width, this.height) },
      uRipples: { value: this.ripples.map(() => new THREE.Vector4(0.5, 0.5, 99, 0)) },
      uRippleColors: { value: this.ripples.map((r) => r.color.clone()) },
      uShockwaves: { value: this.shockwaves.map(() => new THREE.Vector4(0.5, 0.5, 1, 0)) },
      uShockwaveColors: { value: this.shockwaves.map((s) => s.color.clone()) },
      uIntentUv: { value: new THREE.Vector2(0.5, 0.5) },
      uIntentColor: { value: new THREE.Color(0xd99a38) },
      uIntentMix: { value: 0 },
      uPhaseTint: { value: new THREE.Color(0xfaecc8) },
      uCombatFocus: { value: 0 },
    };
    const bgMesh = new THREE.Mesh(
      new THREE.PlaneGeometry(2, 2),
      new THREE.ShaderMaterial({
        vertexShader: BG_VERTEX,
        fragmentShader: BG_FRAGMENT,
        uniforms: this.bgUniforms,
        depthWrite: false,
        depthTest: false,
      })
    );
    this.bgScene.add(bgMesh);

    // Main 3D WebGL scene
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(this.fov, this.width / Math.max(1, this.height), 10, 5000);
    this._syncCamera();

    const hemi = new THREE.HemisphereLight(0xfffdf7, 0xe8dcc8, 1.5);
    this.scene.add(hemi);

    const sun = new THREE.DirectionalLight(0xfff8e8, 1.38);
    sun.position.set(-220, 340, 820);
    this.scene.add(sun);

    const fill = new THREE.DirectionalLight(0xfdecd2, 0.68);
    fill.position.set(360, -240, 520);
    this.scene.add(fill);

    // Single-draw-call InstancedMesh for 3D sparks
    this._dummy = new THREE.Object3D();
    const sparkGeo = new THREE.OctahedronGeometry(4.6);
    const sparkMat = new THREE.MeshStandardMaterial({
      color: 0xffffff,
      roughness: 0.24,
      metalness: 0.22,
    });
    this.sparkMesh = new THREE.InstancedMesh(sparkGeo, sparkMat, MAX_SPARKS);
    this.sparkMesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    this.sparkSlots = Array.from({ length: MAX_SPARKS }, () => ({
      active: false,
      x: 0, y: 0, z: 0,
      vx: 0, vy: 0, vz: 0,
      rx: 0, ry: 0,
      age: 0, life: 0.5, scale: 1,
    }));
    for (let i = 0; i < MAX_SPARKS; i++) {
      this._dummy.position.set(0, 0, -9999);
      this._dummy.scale.setScalar(0.0001);
      this._dummy.updateMatrix();
      this.sparkMesh.setMatrixAt(i, this._dummy.matrix);
      this.sparkMesh.setColorAt(i, new THREE.Color(0xe8a63c));
    }
    this.sparkMesh.instanceMatrix.needsUpdate = true;
    this.sparkMesh.instanceColor.needsUpdate = true;
    this.scene.add(this.sparkMesh);
    this._sparkCursor = 0;

    this._cardGeo = new THREE.BoxGeometry(1, 1, 3.2);
    this._cardEdgeMat = new THREE.MeshStandardMaterial({ color: 0xe3d8c5, roughness: 0.5 });

    this._motes = this._buildLightMotes();

    this.activeDice = [];
    this.flippingCards = [];
    this.rings = [];
    this.vfxEffects = [];
  }

  _syncCamera() {
    const camZ = (this.height / 2) / Math.tan((this.fov * Math.PI) / 360);
    this.camera.aspect = this.width / Math.max(1, this.height);
    this.camera.position.set(0, 0, camZ);
    this.camera.lookAt(0, 0, 0);
    this.camera.updateProjectionMatrix();
  }

  resize(w, h) {
    this.width = w;
    this.height = h;
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.setSize(w, h, false);
    this.bgUniforms.uResolution.value.set(w, h);
    this._syncCamera();
  }

  screenToWorld(sx, sy, z = 0) {
    return new THREE.Vector3(sx - this.width / 2, -(sy - this.height / 2), z);
  }

  setPhaseTint(hex) {
    applySafeColor(this.bgUniforms.uPhaseTint.value, hex, 0xfaecc8);
  }

  setCombatFocus(active) {
    this.targetCombatFocus = active ? 1 : 0;
  }

  /**
   * 4-slot independent shockwave pool: rapid cost-merges, card drops & clashes never truncate earlier waves.
   */
  emitShockwave(screenX, screenY, colorHex = DEFAULT_WARM_GOLD, duration = SHOCKWAVE_DURATION) {
    const idx = this._shockwaveCursor;
    this._shockwaveCursor = (this._shockwaveCursor + 1) % SHOCKWAVE_POOL_SIZE;
    const slot = this.shockwaves[idx];
    slot.uv.set(
      Math.max(0, Math.min(1, screenX / Math.max(1, this.width))),
      Math.max(0, Math.min(1, 1 - screenY / Math.max(1, this.height)))
    );
    slot.age = 0;
    slot.duration = Math.max(0.24, duration);
    slot.active = 1;
    applySafeColor(slot.color, colorHex, DEFAULT_WARM_GOLD);
  }

  /**
   * Subtle continuous intent-driven warm spotlight aura around hovered card / fighter.
   */
  setIntentFocus({ active = false, x = null, y = null, colorHex = null } = {}) {
    this.intentTarget.active = active ? 1 : 0;
    if (typeof x === 'number' && typeof y === 'number' && Number.isFinite(x) && Number.isFinite(y)) {
      const uvX = Math.max(0, Math.min(1, x / Math.max(1, this.width)));
      const uvY = Math.max(0, Math.min(1, 1 - y / Math.max(1, this.height)));
      if (this.intentState.mix < 0.02) {
        this.intentState.uv.set(uvX, uvY);
      }
      this.intentTarget.uv.set(uvX, uvY);
    }
    if (colorHex !== null && colorHex !== undefined) {
      applySafeColor(this.intentTarget.color, colorHex, 0xd99a38);
      if (this.intentState.mix < 0.02) {
        this.intentState.color.copy(this.intentTarget.color);
      }
    }
  }

  triggerRipple(sx, sy, hex = 0xe8a63c) {
    const idx = this._rippleCursor++ % 4;
    this.ripples[idx].uv.set(sx / Math.max(1, this.width), 1 - sy / Math.max(1, this.height));
    this.ripples[idx].age = 0;
    this.ripples[idx].active = 1;
    applySafeColor(this.ripples[idx].color, hex, 0xe8a63c);
  }

  _buildLightMotes() {
    const count = 44;
    const pos = new Float32Array(count * 3);
    const phases = new Float32Array(count);
    for (let i = 0; i < count; i++) {
      pos[i * 3] = (Math.random() - 0.5) * this.width;
      pos[i * 3 + 1] = (Math.random() - 0.5) * this.height;
      pos[i * 3 + 2] = 20 + Math.random() * 140;
      phases[i] = Math.random() * Math.PI * 2;
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    const mat = new THREE.PointsMaterial({
      color: 0xd9a84e,
      size: 5,
      transparent: true,
      opacity: 0.3,
      depthWrite: false,
    });
    const points = new THREE.Points(geo, mat);
    this.scene.add(points);
    return { points, phases, t: 0 };
  }

  launchDie({
    sides = 6,
    dieType = 'speed',
    rolledValue = 1,
    subLabel = '',
    startX,
    startY,
    targetX,
    targetY,
    physicsBody = null,
    radius = 28,
    lifetime = 1.9,
    revealDelay = 0.28,
    onReveal = null,
  }) {
    const pal = DIE_PALETTES[dieType] || DIE_PALETTES.speed;
    const group = new THREE.Group();
    const geo = makePolyGeo(sides, radius);
    const mat = new THREE.MeshStandardMaterial({
      color: pal.body,
      roughness: 0.28,
      metalness: 0.14,
      flatShading: true,
    });
    const mesh = new THREE.Mesh(geo, mat);
    const edgeGeo = new THREE.EdgesGeometry(geo);
    const edgeMat = new THREE.LineBasicMaterial({ color: pal.edge, transparent: true, opacity: 0.68 });
    mesh.add(new THREE.LineSegments(edgeGeo, edgeMat));
    group.add(mesh);

    const shadowGeo = new THREE.CircleGeometry(radius * 1.18, 24);
    const shadowMat = new THREE.MeshBasicMaterial({
      color: 0xa89b87,
      transparent: true,
      opacity: 0.32,
      depthWrite: false,
    });
    const shadow = new THREE.Mesh(shadowGeo, shadowMat);
    this.scene.add(shadow);

    const badgeTex = makeDieReadoutTexture(rolledValue, subLabel || `1~${sides}`, pal.hex);
    const badgeMat = new THREE.SpriteMaterial({ map: badgeTex, transparent: true, opacity: 0, depthTest: false });
    const badge = new THREE.Sprite(badgeMat);
    badge.scale.set(radius * 2.45, radius * 2.45, 1);
    this.scene.add(badge);

    this.scene.add(group);
    this.activeDice.push({
      group, mesh, shadow, badge,
      geo, mat, edgeGeo, edgeMat, shadowGeo, shadowMat, badgeTex, badgeMat,
      startX, startY, targetX, targetY,
      physicsBody,
      z: 145, vz: 95,
      rotVel: new THREE.Vector3(10 + Math.random() * 6, 9 + Math.random() * 6, 7 + Math.random() * 5),
      age: 0, lifetime, radius,
      revealDelay: Math.max(0, Number(revealDelay) || 0),
      revealed: false,
      onReveal: typeof onReveal === 'function' ? onReveal : null,
    });
  }

  spawnCardFlipArc({
    fromX, fromY, toX, toY,
    width = 122, height = 168,
    title = '', cost = '', ownerName = '',
    accentHex = '#1e8f68',
    flipFromBack = true,
    duration = 0.52,
    peakZ = 140,
  }) {
    const frontTex = makeBrightCardTexture({ title, cost, ownerName, accentHex, isBack: false });
    const backTex = makeBrightCardTexture({ accentHex, isBack: true });
    const frontMat = new THREE.MeshStandardMaterial({ map: frontTex, roughness: 0.45, metalness: 0.04 });
    const backMat = new THREE.MeshStandardMaterial({ map: backTex, roughness: 0.48, metalness: 0.06 });

    const mesh = new THREE.Mesh(this._cardGeo, [
      this._cardEdgeMat, this._cardEdgeMat, this._cardEdgeMat, this._cardEdgeMat, frontMat, backMat,
    ]);
    mesh.scale.set(width, height, 1);
    mesh.position.copy(this.screenToWorld(fromX, fromY, 10));
    mesh.rotation.y = flipFromBack ? Math.PI : 0;
    this.scene.add(mesh);

    this.flippingCards.push({
      mesh, frontTex, backTex, frontMat, backMat,
      fromX, fromY, toX, toY,
      flipFromBack, duration, peakZ, age: 0,
    });
  }

  /**
   * 3D Tapered Sweeping Razor Slash Crescent with gilded edge glint & cross-cut flash!
   */
  spawnSlashArc({ fromX, fromY, toX, toY, colorHex = 0xcf4330 }) {
    const target = this.screenToWorld(toX, toY, 54);
    const origin = this.screenToWorld(fromX, fromY, 54);
    const dir = Math.atan2(target.y - origin.y, target.x - origin.x);
    const forwardSign = target.x >= origin.x ? 1 : -1;

    const group = new THREE.Group();
    group.position.copy(target);

    // Layer 1: Wide razor-tapered crimson/colored blade sweep
    const outerGeo = makeTaperedCrescentGeo(34, 82, Math.PI * 1.04, 36, 0.66);
    const outerMat = new THREE.MeshBasicMaterial({
      color: colorHex,
      transparent: true,
      opacity: 0.92,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    // Layer 2: Warm gilded metallic rim glint
    const glintGeo = makeTaperedCrescentGeo(54, 78, Math.PI * 0.88, 32, 0.72);
    const glintMat = new THREE.MeshBasicMaterial({
      color: 0xf4c25e,
      transparent: true,
      opacity: 0.88,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    // Layer 3: Blazing ivory inner cutting edge
    const coreGeo = makeTaperedCrescentGeo(62, 74, Math.PI * 0.72, 28, 0.74);
    const coreMat = new THREE.MeshBasicMaterial({
      color: 0xfffaf0,
      transparent: true,
      opacity: 0.98,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    // Layer 4: Sharp impact cross-cut flash streak
    const flashGeo = makeDiamondSpikeGeo(132, 7.5, -66);
    const flashMat = new THREE.MeshBasicMaterial({
      color: 0xfff8e6,
      transparent: true,
      opacity: 0.96,
      side: THREE.DoubleSide,
      depthWrite: false,
    });

    const outerMesh = new THREE.Mesh(outerGeo, outerMat);
    const glintMesh = new THREE.Mesh(glintGeo, glintMat);
    const coreMesh = new THREE.Mesh(coreGeo, coreMat);
    const flashMesh = new THREE.Mesh(flashGeo, flashMat);
    glintMesh.position.z = 2.5;
    coreMesh.position.z = 5.0;
    flashMesh.position.z = 7.0;
    flashMesh.rotation.z = dir + 0.55 * forwardSign;

    const arcPivot = new THREE.Group();
    arcPivot.add(outerMesh, glintMesh, coreMesh);
    arcPivot.rotation.z = dir - 1.05 * forwardSign;
    arcPivot.rotation.y = 0.28 * forwardSign;
    arcPivot.rotation.x = -0.14;

    group.add(arcPivot, flashMesh);
    this.scene.add(group);

    this.emitShockwave(toX, toY, colorHex, 0.58);
    this.spawnImpactBurst(toX, toY, colorHex, 26, true);

    this.vfxEffects.push({
      kind: 'slash',
      group,
      arcPivot,
      flashMesh,
      geometries: [outerGeo, glintGeo, coreGeo, flashGeo],
      materials: [outerMat, glintMat, coreMat, flashMat],
      baseRotZ: dir - 1.05 * forwardSign,
      sweep: 2.08 * forwardSign,
      age: 0,
      life: 0.44,
    });
  }

  /**
   * 3D Aerodynamic Piercing Lance with tapered diamond spearhead, needle wake & sonic rings!
   */
  spawnPierceLance({ fromX, fromY, toX, toY, colorHex = 0xcc7b14 }) {
    const p0 = this.screenToWorld(fromX, fromY, 56);
    const p1 = this.screenToWorld(toX, toY, 56);
    const delta = p1.clone().sub(p0);
    const dist = Math.max(48, delta.length());
    const angle = Math.atan2(delta.y, delta.x);
    const shaftLen = Math.min(dist * 0.74, 320);

    const group = new THREE.Group();

    // Layer 1: Tapered energy shaft (wide at front, razor point at tail)
    const shaftGeo = new THREE.CylinderGeometry(7.2, 0.8, shaftLen, 10);
    const shaftMat = new THREE.MeshBasicMaterial({
      color: colorHex,
      transparent: true,
      opacity: 0.9,
      depthWrite: false,
    });
    const shaft = new THREE.Mesh(shaftGeo, shaftMat);
    shaft.rotation.z = -Math.PI / 2;
    shaft.position.x = -shaftLen * 0.5;

    // Layer 2: Blazing ivory inner lance needle
    const coreGeo = new THREE.CylinderGeometry(3.1, 0.4, shaftLen * 1.06, 8);
    const coreMat = new THREE.MeshBasicMaterial({
      color: 0xfff9e8,
      transparent: true,
      opacity: 0.98,
      depthWrite: false,
    });
    const core = new THREE.Mesh(coreGeo, coreMat);
    core.rotation.z = -Math.PI / 2;
    core.position.x = -shaftLen * 0.48;
    core.position.z = 2;

    // Layer 3: Sharp 4-sided faceted diamond spearhead cone leading the thrust
    const tipGeo = new THREE.ConeGeometry(11.5, 42, 4);
    const tipMat = new THREE.MeshBasicMaterial({
      color: 0xfff7df,
      transparent: true,
      opacity: 0.96,
      depthWrite: false,
    });
    const tip = new THREE.Mesh(tipGeo, tipMat);
    tip.rotation.z = -Math.PI / 2;
    tip.position.x = 18;
    tip.position.z = 3;

    // Layer 4: Twin sonic-boom chevron shock rings sliding back along the lance
    const sonic1Geo = new THREE.RingGeometry(10, 15.5, 16);
    const sonic1Mat = new THREE.MeshBasicMaterial({
      color: colorHex,
      transparent: true,
      opacity: 0.86,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    const sonic1 = new THREE.Mesh(sonic1Geo, sonic1Mat);
    sonic1.rotation.y = Math.PI * 0.44;
    sonic1.position.x = -12;

    const sonic2Geo = new THREE.RingGeometry(14, 18.5, 16);
    const sonic2Mat = new THREE.MeshBasicMaterial({
      color: 0xfff6dc,
      transparent: true,
      opacity: 0.82,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    const sonic2 = new THREE.Mesh(sonic2Geo, sonic2Mat);
    sonic2.rotation.y = Math.PI * 0.44;
    sonic2.position.x = -46;

    group.add(shaft, core, tip, sonic1, sonic2);
    group.rotation.z = angle;
    group.position.copy(p0);
    this.scene.add(group);

    this.emitShockwave(toX, toY, colorHex, 0.56);
    this.spawnImpactBurst(toX, toY, colorHex, 22, false);

    this.vfxEffects.push({
      kind: 'pierce',
      group,
      sonic1,
      sonic2,
      geometries: [shaftGeo, coreGeo, tipGeo, sonic1Geo, sonic2Geo],
      materials: [shaftMat, coreMat, tipMat, sonic1Mat, sonic2Mat],
      p0, p1,
      age: 0,
      life: 0.42,
    });
  }

  /**
   * 3D Heavy Blunt Shock-Hammer Impact with double faceted shock-rings & radial fracture spikes!
   */
  spawnBluntImpact({ toX, toY, colorHex = 0xb33443 }) {
    const center = this.screenToWorld(toX, toY, 46);
    const group = new THREE.Group();
    group.position.copy(center);

    // Layer 1: Primary heavy beveled octagonal shockwave ring
    const octGeo = new THREE.RingGeometry(18, 46, 8);
    const octMat = new THREE.MeshBasicMaterial({
      color: colorHex,
      transparent: true,
      opacity: 0.9,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    const octMesh = new THREE.Mesh(octGeo, octMat);

    // Layer 2: Fast expanding outer hairline pressure ring
    const rimGeo = new THREE.RingGeometry(36, 42, 16);
    const rimMat = new THREE.MeshBasicMaterial({
      color: 0xe6a13a,
      transparent: true,
      opacity: 0.84,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    const rimMesh = new THREE.Mesh(rimGeo, rimMat);

    // Layer 3: Blazing ivory-gold core concussion flash
    const coreGeo = new THREE.CircleGeometry(28, 8);
    const coreMat = new THREE.MeshBasicMaterial({
      color: 0xfff6e0,
      transparent: true,
      opacity: 0.92,
      depthWrite: false,
    });
    const coreMesh = new THREE.Mesh(coreGeo, coreMat);
    coreMesh.position.z = 3;

    // Layer 4: 6 tapered radial impact fracture spikes bursting outward
    const spikeGeo = makeDiamondSpikeGeo(46, 5.2, 14);
    const spikeMat = new THREE.MeshBasicMaterial({
      color: colorHex,
      transparent: true,
      opacity: 0.9,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    const spikesGroup = new THREE.Group();
    spikesGroup.position.z = 2;
    const baseSpin = Math.random() * Math.PI;
    for (let k = 0; k < 6; k++) {
      const sp = new THREE.Mesh(spikeGeo, spikeMat);
      sp.rotation.z = baseSpin + (k * Math.PI * 2) / 6;
      spikesGroup.add(sp);
    }

    group.add(octMesh, rimMesh, coreMesh, spikesGroup);
    this.scene.add(group);

    this.emitShockwave(toX, toY, colorHex, 0.72);
    this.spawnImpactBurst(toX, toY, colorHex, 32, true);

    this.vfxEffects.push({
      kind: 'blunt',
      group,
      octMesh,
      rimMesh,
      coreMesh,
      spikesGroup,
      geometries: [octGeo, rimGeo, coreGeo, spikeGeo],
      materials: [octMat, rimMat, coreMat, spikeMat],
      age: 0,
      life: 0.48,
    });
  }

  /**
   * 3D Crystalline Hexagonal Block Ward with inner lattice & planar snap-in!
   */
  spawnBlockBarrier({ x, y, colorHex = 0x1a8775 }) {
    const center = this.screenToWorld(x, y, 56);
    const group = new THREE.Group();
    group.position.copy(center);

    // Layer 1: Translucent jade/ward hexagonal plate
    const plateGeo = new THREE.CircleGeometry(48, 6);
    const plateMat = new THREE.MeshBasicMaterial({
      color: colorHex,
      transparent: true,
      opacity: 0.30,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    const plateMesh = new THREE.Mesh(plateGeo, plateMat);

    // Layer 2: Crisp outer hex bevel edges
    const edgeGeo = new THREE.EdgesGeometry(plateGeo);
    const edgeMat = new THREE.LineBasicMaterial({ color: colorHex, transparent: true, opacity: 0.96 });
    const edgeLines = new THREE.LineSegments(edgeGeo, edgeMat);
    edgeLines.position.z = 1;

    // Layer 3: Luminous ivory outer chamfer ring
    const ringGeo = new THREE.RingGeometry(49, 56, 6);
    const ringMat = new THREE.MeshBasicMaterial({
      color: 0xfffbf0,
      transparent: true,
      opacity: 0.94,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    const ringMesh = new THREE.Mesh(ringGeo, ringMat);
    ringMesh.position.z = 2;

    // Layer 4: Inner crystalline lattice hex + 3 faceted prism struts
    const innerGeo = new THREE.RingGeometry(24, 28, 6);
    const innerMat = new THREE.MeshBasicMaterial({
      color: 0xfff8e4,
      transparent: true,
      opacity: 0.84,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    const innerMesh = new THREE.Mesh(innerGeo, innerMat);
    innerMesh.rotation.z = Math.PI / 6;
    innerMesh.position.z = 3;

    const strutPts = [];
    for (let i = 0; i < 3; i++) {
      const a = (i * Math.PI) / 3;
      strutPts.push(
        Math.cos(a) * -46, Math.sin(a) * -46, 2.5,
        Math.cos(a) * 46, Math.sin(a) * 46, 2.5
      );
    }
    const strutGeo = new THREE.BufferGeometry();
    strutGeo.setAttribute('position', new THREE.Float32BufferAttribute(strutPts, 3));
    const strutMat = new THREE.LineBasicMaterial({
      color: colorHex,
      transparent: true,
      opacity: 0.56,
    });
    const strutLines = new THREE.LineSegments(strutGeo, strutMat);

    group.add(plateMesh, edgeLines, ringMesh, innerMesh, strutLines);
    this.scene.add(group);
    this.emitShockwave(x, y, colorHex, 0.62);

    this.vfxEffects.push({
      kind: 'block',
      group,
      ringMesh,
      innerMesh,
      geometries: [plateGeo, edgeGeo, ringGeo, innerGeo, strutGeo],
      materials: [plateMat, edgeMat, ringMat, innerMat, strutMat],
      age: 0,
      life: 0.58,
    });
  }

  /**
   * 3D Geodesic Shield Dome Pulse wrapping a fighter when gaining/absorbing shield!
   */
  spawnShieldDomePulse({ x, y, radius = 54, colorHex = 0x2c9477 }) {
    const center = this.screenToWorld(x, y, 36);
    const group = new THREE.Group();
    group.position.copy(center);

    const sphereGeo = new THREE.IcosahedronGeometry(radius, 1);
    const fillMat = new THREE.MeshBasicMaterial({
      color: colorHex,
      transparent: true,
      opacity: 0.18,
      depthWrite: false,
    });
    const wireGeo = new THREE.WireframeGeometry(sphereGeo);
    const wireMat = new THREE.LineBasicMaterial({
      color: colorHex,
      transparent: true,
      opacity: 0.78,
    });
    group.add(new THREE.Mesh(sphereGeo, fillMat), new THREE.LineSegments(wireGeo, wireMat));
    this.scene.add(group);

    this.vfxEffects.push({
      kind: 'dome',
      group,
      geometries: [sphereGeo, wireGeo],
      materials: [fillMat, wireMat],
      age: 0,
      life: 0.65,
    });
  }

  /**
   * 3D Die Destruction VFX: faceted polyhedral die silhouette cleaved by a crimson X-slash,
   * then violently exploding into tumbling 3D tetrahedral shards!
   */
  spawnDieShatter({ x, y, colorHex = 0xc93a2b, dieColorHex = null, radius = 28 }) {
    const center = this.screenToWorld(x, y, 56);
    const group = new THREE.Group();
    group.position.copy(center);

    const geometries = [];
    const materials = [];

    // Phase 1 core die silhouette + wireframe crack glow
    const coreGeo = new THREE.OctahedronGeometry(radius * 0.88, 0);
    const coreMat = new THREE.MeshBasicMaterial({
      color: dieColorHex ?? colorHex,
      transparent: true,
      opacity: 0.88,
      depthWrite: false,
    });
    const coreMesh = new THREE.Mesh(coreGeo, coreMat);
    const wireGeo = new THREE.EdgesGeometry(coreGeo);
    const wireMat = new THREE.LineBasicMaterial({
      color: 0xfff3de,
      transparent: true,
      opacity: 0.96,
    });
    const wireMesh = new THREE.LineSegments(wireGeo, wireMat);
    const coreGroup = new THREE.Group();
    coreGroup.add(coreMesh, wireMesh);
    group.add(coreGroup);
    geometries.push(coreGeo, wireGeo);
    materials.push(coreMat, wireMat);

    // Crossed crimson cleave blades (X fracture across the die)
    const slashGeo = makeDiamondSpikeGeo(radius * 3.1, 4.4, radius * 1.55);
    const slashMat = new THREE.MeshBasicMaterial({
      color: colorHex,
      transparent: true,
      opacity: 0.96,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    const slash1 = new THREE.Mesh(slashGeo, slashMat);
    slash1.position.set(-radius * 1.1, radius * 1.1, 6);
    slash1.rotation.z = -Math.PI * 0.25;
    const slash2 = new THREE.Mesh(slashGeo, slashMat);
    slash2.position.set(-radius * 1.1, -radius * 1.1, 6);
    slash2.rotation.z = Math.PI * 0.25;
    const slashGroup = new THREE.Group();
    slashGroup.add(slash1, slash2);
    group.add(slashGroup);
    geometries.push(slashGeo);
    materials.push(slashMat);

    // Phase 2 tumbling 3D polyhedral shatter shards
    const shardGeo = new THREE.TetrahedronGeometry(radius * 0.34, 0);
    const shardMat = new THREE.MeshBasicMaterial({
      color: colorHex,
      transparent: true,
      opacity: 0.94,
      depthWrite: false,
    });
    const shardRimMat = new THREE.MeshBasicMaterial({
      color: 0xfff0d4,
      transparent: true,
      opacity: 0.88,
      wireframe: true,
      depthWrite: false,
    });
    geometries.push(shardGeo);
    materials.push(shardMat, shardRimMat);

    const shards = [];
    for (let i = 0; i < 12; i++) {
      const ang = (i / 12) * Math.PI * 2 + (Math.random() - 0.5) * 0.35;
      const spd = 150 + Math.random() * 195;
      const mesh = new THREE.Mesh(shardGeo, i % 3 === 0 ? shardRimMat : shardMat);
      mesh.visible = false;
      mesh.scale.setScalar(0.65 + Math.random() * 0.7);
      group.add(mesh);
      shards.push({
        mesh,
        vx: Math.cos(ang) * spd,
        vy: Math.sin(ang) * spd + 48,
        vz: 70 + Math.random() * 140,
        rx: (Math.random() - 0.5) * 16,
        ry: (Math.random() - 0.5) * 16,
        rz: (Math.random() - 0.5) * 14,
      });
    }

    this.scene.add(group);
    this.emitShockwave(x, y, colorHex, 0.48);
    this.spawnImpactBurst(x, y, colorHex, 24, true);

    this.vfxEffects.push({
      kind: 'die_shatter',
      group,
      coreGroup,
      slashGroup,
      shards,
      coreMat,
      wireMat,
      slashMat,
      shardMat,
      shardRimMat,
      geometries,
      materials,
      age: 0,
      life: 0.78,
    });
  }

  /**
   * 3D Skill Card Destruction VFX: card silhouette slashed diagonally with glowing crimson fractures,
   * then tearing apart into 8 tumbling 3D cardstock shards & embers!
   */
  spawnCardShatter({ x, y, width = 128, height = 178, colorHex = 0xc93a2b }) {
    const center = this.screenToWorld(x, y, 52);
    const group = new THREE.Group();
    group.position.copy(center);

    const geometries = [];
    const materials = [];

    // Phase 1 card silhouette & glowing crimson border
    const cardGeo = new THREE.PlaneGeometry(width, height);
    const cardMat = new THREE.MeshBasicMaterial({
      color: 0x3b1b18,
      transparent: true,
      opacity: 0.72,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    const borderGeo = new THREE.EdgesGeometry(cardGeo);
    const borderMat = new THREE.LineBasicMaterial({
      color: colorHex,
      transparent: true,
      opacity: 0.98,
    });
    const frameGroup = new THREE.Group();
    frameGroup.add(new THREE.Mesh(cardGeo, cardMat), new THREE.LineSegments(borderGeo, borderMat));
    group.add(frameGroup);
    geometries.push(cardGeo, borderGeo);
    materials.push(cardMat, borderMat);

    // Diagonal crimson fracture blades across the card face
    const diag = Math.hypot(width, height) * 0.92;
    const crackGeo = makeDiamondSpikeGeo(diag, 5.4, diag * 0.5);
    const crackMat = new THREE.MeshBasicMaterial({
      color: 0xffd7cc,
      transparent: true,
      opacity: 0.98,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    const crackOuterMat = new THREE.MeshBasicMaterial({
      color: colorHex,
      transparent: true,
      opacity: 0.94,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    const crack1 = new THREE.Mesh(crackGeo, crackOuterMat);
    crack1.position.set(-width * 0.45, height * 0.45, 5);
    crack1.rotation.z = -Math.atan2(height, width);
    const crack2 = new THREE.Mesh(crackGeo, crackMat);
    crack2.position.set(-width * 0.45, -height * 0.45, 6);
    crack2.rotation.z = Math.atan2(height, width);
    const crackGroup = new THREE.Group();
    crackGroup.add(crack1, crack2);
    group.add(crackGroup);
    geometries.push(crackGeo);
    materials.push(crackMat, crackOuterMat);

    // Phase 2 torn 3D cardstock shards (2x4 grid flying apart with 3D curl/spin)
    const cols = 2;
    const rows = 4;
    const pieceW = width / cols;
    const pieceH = height / rows;
    const pieceGeo = new THREE.PlaneGeometry(pieceW * 0.92, pieceH * 0.92);
    const pieceMat = new THREE.MeshBasicMaterial({
      color: 0xf7efe0,
      transparent: true,
      opacity: 0.94,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    const pieceEdgeGeo = new THREE.EdgesGeometry(pieceGeo);
    const pieceEdgeMat = new THREE.LineBasicMaterial({
      color: colorHex,
      transparent: true,
      opacity: 0.95,
    });
    geometries.push(pieceGeo, pieceEdgeGeo);
    materials.push(pieceMat, pieceEdgeMat);

    const shards = [];
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const ox = (c - 0.5) * pieceW;
        const oy = (1.5 - r) * pieceH;
        const holder = new THREE.Group();
        holder.position.set(ox, oy, 2);
        holder.add(new THREE.Mesh(pieceGeo, pieceMat), new THREE.LineSegments(pieceEdgeGeo, pieceEdgeMat));
        holder.visible = false;
        group.add(holder);
        const ang = Math.atan2(oy, ox) + (Math.random() - 0.5) * 0.45;
        const spd = 120 + Math.random() * 145;
        shards.push({
          mesh: holder,
          vx: Math.cos(ang) * spd,
          vy: Math.sin(ang) * spd + 35,
          vz: 55 + Math.random() * 110,
          rx: (Math.random() - 0.5) * 11,
          ry: (Math.random() - 0.5) * 11,
          rz: (Math.random() - 0.5) * 8,
        });
      }
    }

    this.scene.add(group);
    this.emitShockwave(x, y, colorHex, 0.56);
    this.spawnImpactBurst(x, y, colorHex, 30, true);

    this.vfxEffects.push({
      kind: 'card_shatter',
      group,
      frameGroup,
      crackGroup,
      shards,
      cardMat,
      borderMat,
      crackMat,
      crackOuterMat,
      pieceMat,
      pieceEdgeMat,
      geometries,
      materials,
      age: 0,
      life: 0.86,
    });
  }

  /**
   * 3D Luminous Parabolic Energy Comet with tapered curved ribbon tail!
   */
  spawnEnergyBeam({ fromX, fromY, toX, toY, colorHex = 0xd48e1a, duration = 0.48 }) {
    const p0 = this.screenToWorld(fromX, fromY, 44);
    const p1 = this.screenToWorld(toX, toY, 44);
    const mid = p0.clone().lerp(p1, 0.5);
    mid.y += 46;
    mid.z += 76;

    const group = new THREE.Group();

    // Comet crystal head
    const headGroup = new THREE.Group();
    const orbGeo = new THREE.OctahedronGeometry(9.2);
    const orbMat = new THREE.MeshBasicMaterial({ color: colorHex, transparent: true, opacity: 0.96 });
    const coreGeo = new THREE.OctahedronGeometry(5.2);
    const coreMat = new THREE.MeshBasicMaterial({ color: 0xfffaf0, transparent: true, opacity: 0.98 });
    const haloGeo = new THREE.RingGeometry(11.5, 16.5, 16);
    const haloMat = new THREE.MeshBasicMaterial({
      color: 0xfff8df,
      transparent: true,
      opacity: 0.9,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    headGroup.add(new THREE.Mesh(orbGeo, orbMat), new THREE.Mesh(coreGeo, coreMat), new THREE.Mesh(haloGeo, haloMat));
    headGroup.position.copy(p0);

    // Tapered curved comet ribbon trail (outer colored + inner ivory core)
    const ribbonSegments = 16;
    const ribbonGeo = makeCometRibbonGeo(ribbonSegments);
    const ribbonMat = new THREE.MeshBasicMaterial({
      color: colorHex,
      transparent: true,
      opacity: 0.72,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    const ribbonCoreGeo = makeCometRibbonGeo(ribbonSegments);
    const ribbonCoreMat = new THREE.MeshBasicMaterial({
      color: 0xfff8e2,
      transparent: true,
      opacity: 0.88,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    const ribbonMesh = new THREE.Mesh(ribbonGeo, ribbonMat);
    const ribbonCoreMesh = new THREE.Mesh(ribbonCoreGeo, ribbonCoreMat);
    ribbonCoreMesh.position.z = 1.5;

    updateCometRibbonGeo(ribbonGeo, p0, mid, p1, 0.01, 0.34, 8.5, ribbonSegments);
    updateCometRibbonGeo(ribbonCoreGeo, p0, mid, p1, 0.01, 0.28, 3.6, ribbonSegments);

    group.add(ribbonMesh, ribbonCoreMesh, headGroup);
    this.scene.add(group);

    this.vfxEffects.push({
      kind: 'beam',
      group,
      headGroup,
      ribbonGeo,
      ribbonCoreGeo,
      ribbonSegments,
      geometries: [orbGeo, coreGeo, haloGeo, ribbonGeo, ribbonCoreGeo],
      materials: [orbMat, coreMat, haloMat, ribbonMat, ribbonCoreMat],
      p0, mid, p1,
      toX, toY, colorHex,
      age: 0,
      life: duration,
    });
  }

  spawnImpactBurst(sx, sy, colorHex = 0xe89b32, count = 28, heavy = false) {
    this.triggerRipple(sx, sy, colorHex);
    const origin = this.screenToWorld(sx, sy, 36);
    const baseColor = applySafeColor(new THREE.Color(), colorHex, 0xe89b32);
    const brightColor = new THREE.Color(0xfff7df);

    for (let i = 0; i < count; i++) {
      const idx = this._sparkCursor++ % MAX_SPARKS;
      const s = this.sparkSlots[idx];
      const a = Math.random() * Math.PI * 2;
      const spd = (heavy ? 245 : 165) + Math.random() * (heavy ? 315 : 210);
      s.active = true;
      s.x = origin.x;
      s.y = origin.y;
      s.z = origin.z;
      s.vx = Math.cos(a) * spd;
      s.vy = Math.sin(a) * spd;
      s.vz = 80 + Math.random() * 190;
      s.rx = Math.random() * 6;
      s.ry = Math.random() * 6;
      s.age = 0;
      s.life = 0.36 + Math.random() * 0.28;
      s.scale = heavy ? 1.25 : 0.9;
      this.sparkMesh.setColorAt(idx, i % 3 === 0 ? brightColor : baseColor);
    }
    this.sparkMesh.instanceColor.needsUpdate = true;

    const rGeo = new THREE.RingGeometry(14, 22, 32);
    const rMat = new THREE.MeshBasicMaterial({
      color: baseColor,
      transparent: true,
      opacity: 0.72,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    const ring = new THREE.Mesh(rGeo, rMat);
    ring.position.copy(origin);
    this.scene.add(ring);
    this.rings.push({ mesh: ring, geo: rGeo, mat: rMat, age: 0, life: 0.42, maxScale: heavy ? 6.5 : 4.2 });
  }

  clearDice() {
    for (const d of this.activeDice) this._disposeDie(d);
    this.activeDice = [];
  }

  clearMatchFx() {
    this.clearDice();
    for (const card of this.flippingCards) this._disposeCardFlip(card);
    for (const effect of this.vfxEffects) this._disposeVfx(effect);
    for (const ring of this.rings) this._disposeRing(ring);
    this.flippingCards.length = this.vfxEffects.length = this.rings.length = 0;
    for (const spark of this.sparkSlots) spark.age = spark.life;
    for (const ripple of this.ripples) ripple.active = 0;
    for (const shockwave of this.shockwaves) shockwave.active = 0;
  }

  _disposeCardFlip(card) {
    this.scene.remove(card.mesh);
    card.frontTex.dispose();
    card.backTex.dispose();
    card.frontMat.dispose();
    card.backMat.dispose();
  }

  _disposeRing(ring) {
    this.scene.remove(ring.mesh);
    ring.geo.dispose();
    ring.mat.dispose();
  }

  _disposeDie(d) {
    this.scene.remove(d.group, d.shadow, d.badge);
    d.geo.dispose();
    d.mat.dispose();
    d.edgeGeo.dispose();
    d.edgeMat.dispose();
    d.shadowGeo.dispose();
    d.shadowMat.dispose();
    d.badgeTex.dispose();
    d.badgeMat.dispose();
  }

  _disposeVfx(v) {
    this.scene.remove(v.group);
    for (const g of v.geometries) g.dispose();
    for (const m of v.materials) m.dispose();
  }

  update(dtSec) {
    this.bgUniforms.uTime.value += dtSec;
    this.combatFocus += (this.targetCombatFocus - this.combatFocus) * Math.min(1, dtSec * 6.5);
    this.bgUniforms.uCombatFocus.value = this.combatFocus;

    // Smoothly interpolate continuous intent spotlight aura
    const mixRate = this.intentTarget.active > 0.5 ? 9.5 : 6.2;
    this.intentState.mix += (this.intentTarget.active - this.intentState.mix) * Math.min(1, dtSec * mixRate);
    this.intentState.uv.lerp(this.intentTarget.uv, Math.min(1, dtSec * 12.5));
    this.intentState.color.lerp(this.intentTarget.color, Math.min(1, dtSec * 9.0));
    this.bgUniforms.uIntentUv.value.copy(this.intentState.uv);
    this.bgUniforms.uIntentColor.value.copy(this.intentState.color);
    this.bgUniforms.uIntentMix.value = this.intentState.mix;

    // Step ambient ripples
    for (let i = 0; i < 4; i++) {
      const r = this.ripples[i];
      if (r.active) {
        r.age += dtSec;
        if (r.age > 1.2) r.active = 0;
      }
      this.bgUniforms.uRipples.value[i].set(r.uv.x, r.uv.y, r.age, r.active);
      this.bgUniforms.uRippleColors.value[i].copy(r.color);
    }

    // Step 4-slot independent shockwave pool
    for (let i = 0; i < SHOCKWAVE_POOL_SIZE; i++) {
      const sw = this.shockwaves[i];
      if (sw.active) {
        sw.age += dtSec / Math.max(0.1, sw.duration);
        if (sw.age >= 1.0) {
          sw.age = 1.0;
          sw.active = 0;
        }
      }
      this.bgUniforms.uShockwaves.value[i].set(sw.uv.x, sw.uv.y, sw.age, sw.active);
      this.bgUniforms.uShockwaveColors.value[i].copy(sw.color);
    }

    this._motes.t += dtSec;
    const pAttr = this._motes.points.geometry.getAttribute('position');
    for (let i = 0; i < this._motes.phases.length; i++) {
      const ph = this._motes.phases[i];
      pAttr.setXYZ(
        i,
        pAttr.getX(i) + Math.cos(this._motes.t * 0.35 + ph) * 0.14,
        pAttr.getY(i) + Math.sin(this._motes.t * 0.45 + ph) * 0.16,
        pAttr.getZ(i)
      );
    }
    pAttr.needsUpdate = true;

    // 3D Polyhedral Dice
    for (let i = this.activeDice.length - 1; i >= 0; i--) {
      const d = this.activeDice[i];
      d.age += dtSec;
      let sx, sy;
      if (d.physicsBody) {
        sx = d.physicsBody.position.x;
        sy = d.physicsBody.position.y;
      } else {
        const moveT = Math.min(1, d.age / 0.42);
        const ease = 1 - Math.pow(1 - moveT, 3);
        sx = d.startX + (d.targetX - d.startX) * ease;
        sy = d.startY + (d.targetY - d.startY) * ease;
      }

      d.vz -= 1220 * dtSec;
      d.z += d.vz * dtSec;
      if (d.z < d.radius) {
        d.z = d.radius;
        d.vz = Math.abs(d.vz) > 45 ? -d.vz * 0.45 : 0;
      }

      const wp = this.screenToWorld(sx, sy, d.z);
      d.group.position.copy(wp);
      d.shadow.position.set(wp.x + 4, wp.y - 6, 1);
      const shScale = Math.max(0.5, 1 - (d.z - d.radius) / 280);
      d.shadow.scale.setScalar(shScale);

      if (d.physicsBody && Math.abs(d.physicsBody.angularVelocity) > 0.05) {
        d.mesh.rotation.z += d.physicsBody.angularVelocity * 1.4;
        d.mesh.rotation.x += d.physicsBody.velocity.y * 0.04;
        d.mesh.rotation.y += d.physicsBody.velocity.x * 0.04;
      } else {
        const damp = d.age > 0.44 ? Math.pow(0.015, dtSec) : Math.pow(0.28, dtSec);
        d.rotVel.multiplyScalar(damp);
        d.mesh.rotation.x += d.rotVel.x * dtSec;
        d.mesh.rotation.y += d.rotVel.y * dtSec;
        d.mesh.rotation.z += d.rotVel.z * dtSec;
      }

      if (!d.revealed && d.age >= d.revealDelay) {
        d.revealed = true;
        if (d.onReveal) {
          const cb = d.onReveal;
          d.onReveal = null;
          cb();
        }
      }
      const fadeOut = d.age > d.lifetime - 0.32 ? Math.max(0, (d.lifetime - d.age) / 0.32) : 1;
      const badgeIn = d.revealed ? Math.max(0, Math.min(1, (d.age - d.revealDelay) / 0.14)) : 0;
      d.badge.position.set(wp.x, wp.y, d.z + d.radius + 14);
      d.badgeMat.opacity = badgeIn * fadeOut;
      d.shadowMat.opacity = 0.3 * shScale * fadeOut;
      if (fadeOut < 1) {
        d.mat.transparent = true;
        d.mat.opacity = fadeOut;
      }

      if (d.age >= d.lifetime) {
        this._disposeDie(d);
        this.activeDice.splice(i, 1);
      }
    }

    // 3D Flipping Cards
    for (let i = this.flippingCards.length - 1; i >= 0; i--) {
      const c = this.flippingCards[i];
      c.age += dtSec;
      const rawT = Math.min(1, c.age / c.duration);
      const t = 1 - Math.pow(1 - rawT, 3);
      const sx = c.fromX + (c.toX - c.fromX) * t;
      const sy = c.fromY + (c.toY - c.fromY) * t;
      const sz = 8 + Math.sin(rawT * Math.PI) * c.peakZ;
      c.mesh.position.copy(this.screenToWorld(sx, sy, sz));
      c.mesh.rotation.y = c.flipFromBack ? Math.PI * (1 - t) : Math.PI * t;
      c.mesh.rotation.x = Math.sin(rawT * Math.PI) * 0.22;

      if (rawT >= 1) {
        this._disposeCardFlip(c);
        this.flippingCards.splice(i, 1);
      }
    }

    // 3D Kinetic Combat & Energy VFX
    for (let i = this.vfxEffects.length - 1; i >= 0; i--) {
      const v = this.vfxEffects[i];
      v.age += dtSec;
      const t = Math.min(1, v.age / v.life);
      if (v.kind === 'slash') {
        const ease = 1 - Math.pow(1 - t, 3.2);
        v.arcPivot.rotation.z = v.baseRotZ + ease * v.sweep;
        v.arcPivot.scale.setScalar(0.72 + ease * 0.78);
        const fade = t < 0.14 ? t / 0.14 : Math.pow(1 - (t - 0.14) / 0.86, 1.35);
        v.materials[0].opacity = fade * 0.92;
        v.materials[1].opacity = fade * 0.88;
        v.materials[2].opacity = fade * 0.98;
        // Crisp cross-cut glint snaps open & closes cleanly
        const flashT = Math.min(1, t / 0.36);
        v.flashMesh.scale.set(0.45 + flashT * 1.15, Math.max(0.05, 1 - flashT * 0.92), 1);
        v.materials[3].opacity = Math.max(0, (1 - flashT) * 0.96);
      } else if (v.kind === 'pierce') {
        const ease = 1 - Math.pow(1 - t, 2.8);
        v.group.position.lerpVectors(v.p0, v.p1, ease);
        const widthTaper = Math.max(0.12, 1 - Math.pow(t, 1.4) * 0.82);
        v.group.scale.set(0.55 + ease * 0.65, widthTaper, 1);
        v.sonic1.position.x = -10 - t * 62;
        v.sonic1.scale.setScalar(0.75 + t * 1.45);
        v.sonic2.position.x = -38 - t * 88;
        v.sonic2.scale.setScalar(0.65 + t * 1.75);
        const fade = t < 0.12 ? t / 0.12 : Math.pow(1 - (t - 0.12) / 0.88, 1.25);
        v.materials[0].opacity = fade * 0.9;
        v.materials[1].opacity = fade * 0.98;
        v.materials[2].opacity = fade * 0.96;
        v.materials[3].opacity = fade * 0.82;
        v.materials[4].opacity = fade * 0.74;
      } else if (v.kind === 'blunt') {
        const ease = 1 - Math.pow(1 - t, 3.0);
        const fastEase = 1 - Math.pow(1 - t, 2.0);
        v.octMesh.scale.setScalar(0.52 + ease * 1.92);
        v.octMesh.rotation.z += dtSec * 2.8;
        v.rimMesh.scale.setScalar(0.6 + fastEase * 2.45);
        const coreFade = Math.max(0, 1 - t * 2.1);
        v.coreMesh.scale.setScalar(0.7 + ease * 0.95);
        v.spikesGroup.scale.setScalar(0.5 + ease * 1.65);
        v.spikesGroup.rotation.z -= dtSec * 0.85;
        v.materials[0].opacity = Math.pow(1 - t, 1.2) * 0.9;
        v.materials[1].opacity = Math.pow(1 - t, 1.6) * 0.82;
        v.materials[2].opacity = coreFade * 0.92;
        v.materials[3].opacity = Math.pow(1 - t, 1.5) * 0.88;
      } else if (v.kind === 'block') {
        const snapT = Math.min(1, t / 0.18);
        const snapEase = 1 - Math.pow(1 - snapT, 3);
        const pop = t < 0.2 ? 0.56 + snapEase * 0.58 : 1.14 - (t - 0.2) * 0.14;
        v.group.scale.setScalar(pop);
        v.group.rotation.y = (1 - snapEase) * 0.52;
        v.innerMesh.rotation.z = Math.PI / 6 + t * 0.55;
        v.ringMesh.scale.setScalar(1 + t * 0.16);
        const fade = t < 0.58 ? 1 : Math.pow(1 - (t - 0.58) / 0.42, 1.2);
        v.materials[0].opacity = fade * 0.30;
        v.materials[1].opacity = fade * 0.96;
        v.materials[2].opacity = fade * 0.92;
        v.materials[3].opacity = fade * 0.84;
        v.materials[4].opacity = fade * 0.56;
      } else if (v.kind === 'dome') {
        const ease = 1 - Math.pow(1 - t, 3);
        v.group.scale.setScalar(0.75 + ease * 0.55);
        v.group.rotation.y += dtSec * 1.8;
        v.group.rotation.x += dtSec * 0.9;
        v.materials[0].opacity = (1 - t) * 0.2;
        v.materials[1].opacity = (1 - t) * 0.82;
      } else if (v.kind === 'beam') {
        const u = 1 - t;
        const x = u * u * v.p0.x + 2 * u * t * v.mid.x + t * t * v.p1.x;
        const y = u * u * v.p0.y + 2 * u * t * v.mid.y + t * t * v.p1.y;
        const z = u * u * v.p0.z + 2 * u * t * v.mid.z + t * t * v.p1.z;
        v.headGroup.position.set(x, y, z);
        v.headGroup.rotation.z += dtSec * 12;
        v.headGroup.rotation.y += dtSec * 7;
        const pulse = 0.72 + Math.sin(t * Math.PI) * 0.52;
        v.headGroup.scale.setScalar(pulse);
        updateCometRibbonGeo(v.ribbonGeo, v.p0, v.mid, v.p1, t, 0.36, 9.2 * pulse, v.ribbonSegments);
        updateCometRibbonGeo(v.ribbonCoreGeo, v.p0, v.mid, v.p1, t, 0.28, 3.8 * pulse, v.ribbonSegments);
        if (t >= 1) {
          this.emitShockwave(v.toX, v.toY, v.colorHex, 0.52);
          this.spawnImpactBurst(v.toX, v.toY, v.colorHex, 14, false);
        }
      } else if (v.kind === 'die_shatter') {
        const splitT = 0.22;
        if (t < splitT) {
          const p = t / splitT;
          v.coreGroup.visible = true;
          v.coreGroup.rotation.x += dtSec * 8;
          v.coreGroup.rotation.y += dtSec * 11;
          v.coreGroup.scale.setScalar(1 + Math.sin(p * Math.PI) * 0.24);
          v.slashGroup.visible = true;
          v.slashGroup.scale.setScalar(0.35 + p * 0.95);
          v.slashMat.opacity = 0.98;
        } else {
          const p = (t - splitT) / (1 - splitT);
          v.coreGroup.visible = false;
          v.slashGroup.visible = p < 0.35;
          v.slashMat.opacity = Math.max(0, 1 - p / 0.35) * 0.92;
          const fade = Math.pow(1 - p, 1.35);
          v.shardMat.opacity = fade * 0.94;
          v.shardRimMat.opacity = fade * 0.88;
          for (const sh of v.shards) {
            sh.mesh.visible = true;
            sh.vz -= 520 * dtSec;
            sh.mesh.position.x += sh.vx * dtSec;
            sh.mesh.position.y += sh.vy * dtSec;
            sh.mesh.position.z = Math.max(2, sh.mesh.position.z + sh.vz * dtSec);
            sh.vx *= Math.pow(0.28, dtSec);
            sh.vy *= Math.pow(0.28, dtSec);
            sh.mesh.rotation.x += sh.rx * dtSec;
            sh.mesh.rotation.y += sh.ry * dtSec;
            sh.mesh.rotation.z += sh.rz * dtSec;
          }
        }
      } else if (v.kind === 'card_shatter') {
        const splitT = 0.24;
        if (t < splitT) {
          const p = t / splitT;
          v.frameGroup.visible = true;
          v.frameGroup.scale.setScalar(1 + Math.sin(p * Math.PI) * 0.08);
          v.crackGroup.visible = true;
          v.crackGroup.scale.setScalar(0.2 + p * 0.96);
          v.cardMat.opacity = 0.72 * (1 - p * 0.3);
          v.borderMat.opacity = 0.98;
        } else {
          const p = (t - splitT) / (1 - splitT);
          v.frameGroup.visible = false;
          v.crackGroup.visible = p < 0.32;
          const crackFade = Math.max(0, 1 - p / 0.32);
          v.crackMat.opacity = crackFade * 0.98;
          v.crackOuterMat.opacity = crackFade * 0.92;
          const fade = Math.pow(1 - p, 1.3);
          v.pieceMat.opacity = fade * 0.94;
          v.pieceEdgeMat.opacity = fade * 0.94;
          for (const sh of v.shards) {
            sh.mesh.visible = true;
            sh.vz -= 420 * dtSec;
            sh.mesh.position.x += sh.vx * dtSec;
            sh.mesh.position.y += sh.vy * dtSec;
            sh.mesh.position.z = Math.max(2, sh.mesh.position.z + sh.vz * dtSec);
            sh.vx *= Math.pow(0.32, dtSec);
            sh.vy *= Math.pow(0.32, dtSec);
            sh.mesh.rotation.x += sh.rx * dtSec;
            sh.mesh.rotation.y += sh.ry * dtSec;
            sh.mesh.rotation.z += sh.rz * dtSec;
          }
        }
      }

      if (t >= 1) {
        this._disposeVfx(v);
        this.vfxEffects.splice(i, 1);
      }
    }

    // InstancedMesh 3D Sparks
    let sparksDirty = false;
    for (let i = 0; i < MAX_SPARKS; i++) {
      const s = this.sparkSlots[i];
      if (!s.active) continue;
      sparksDirty = true;
      s.age += dtSec;
      if (s.age >= s.life) {
        s.active = false;
        this._dummy.position.set(0, 0, -9999);
        this._dummy.scale.setScalar(0.0001);
        this._dummy.updateMatrix();
        this.sparkMesh.setMatrixAt(i, this._dummy.matrix);
        continue;
      }
      s.vz -= 720 * dtSec;
      s.x += s.vx * dtSec;
      s.y += s.vy * dtSec;
      s.z = Math.max(2, s.z + s.vz * dtSec);
      s.vx *= Math.pow(0.18, dtSec);
      s.vy *= Math.pow(0.18, dtSec);
      s.rx += 11 * dtSec;
      s.ry += 9 * dtSec;
      const sc = Math.max(0.05, (1 - s.age / s.life) * s.scale);
      this._dummy.position.set(s.x, s.y, s.z);
      this._dummy.rotation.set(s.rx, s.ry, 0);
      this._dummy.scale.setScalar(sc);
      this._dummy.updateMatrix();
      this.sparkMesh.setMatrixAt(i, this._dummy.matrix);
    }
    if (sparksDirty) this.sparkMesh.instanceMatrix.needsUpdate = true;

    // 3D Shockwave Rings
    for (let i = this.rings.length - 1; i >= 0; i--) {
      const r = this.rings[i];
      r.age += dtSec;
      const t = Math.min(1, r.age / r.life);
      r.mesh.scale.setScalar(1 + t * r.maxScale);
      r.mat.opacity = 0.65 * (1 - t);
      if (t >= 1) {
        this._disposeRing(r);
        this.rings.splice(i, 1);
      }
    }

    this.renderer.autoClear = true;
    this.renderer.render(this.bgScene, this.bgCamera);
    this.renderer.autoClear = false;
    this.renderer.clearDepth();
    this.renderer.render(this.scene, this.camera);
  }
}
