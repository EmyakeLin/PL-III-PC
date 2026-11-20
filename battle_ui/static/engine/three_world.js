/**
 * Three.js WebGL 3D & Custom GLSL Shader Engine for 《光点计划 III》.
 * Strictly BRIGHT palette — ZERO black, ZERO blue-purple!
 * Frontal low-FOV pixel-calibrated 3D camera (z = 0 aligns 1:1 with screen pixels):
 *  - Custom GLSL bright sunlit arena shader with Left(P1)/Right(P2) territory light, dynamic combat spotlight & impact ripples
 *  - True 3D polyhedral dice (d4, d6, d8, d12, d16, d20) bound 1:1 to Matter.js colliding clash bodies
 *  - True 3D double-sided card flips & parabolic arcs (place, pull, reveal, swap, recycle)
 *  - True 3D combat choreography: slash crescents, pierce lances, blunt shock-hammers, block hex-walls, evade wind-streaks, shield dome pulses & parabolic passive/cost energy beams
 *  - Single-draw-call InstancedMesh 3D sparks & shockwave rings
 */

import * as THREE from '../vendor/three.module.js';

const DIE_PALETTES = {
  speed:  { body: 0xf0c75e, edge: 0x8f6618, hex: '#b87d14' },
  slash:  { body: 0xe86b56, edge: 0x8f291c, hex: '#c73a28' },
  pierce: { body: 0xf0a63a, edge: 0x8c550d, hex: '#c77710' },
  blunt:  { body: 0xd95966, edge: 0x7d212b, hex: '#b33442' },
  block:  { body: 0x3eb09b, edge: 0x166355, hex: '#1b8572' },
  evade:  { body: 0x62b84f, edge: 0x26631a, hex: '#3d8f2d' },
  blank:  { body: 0xc9bfb0, edge: 0x73695b, hex: '#7a6f62' },
  breath: { body: 0x45ba9c, edge: 0x176b56, hex: '#238c72' },
};

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

    // Subtle warm phase glow
    col = mix(col, uPhaseTint, (1.0 - smoothstep(0.0, 0.76, radial)) * 0.08);

    // Fine luminous grain
    float grain = (hash(gl_FragCoord.xy * 0.5) - 0.5) * 0.012;
    col += grain;

    // Real-time interactive impact ripples
    for (int i = 0; i < 4; i++) {
      if (uRipples[i].w > 0.5) {
        float age = uRipples[i].z;
        float dist = length((vUv - uRipples[i].xy) * aspect);
        float radius = age * 0.65;
        float ring = exp(-pow((dist - radius) * 22.0, 2.0)) * max(0.0, 1.0 - age / 1.15);
        col = mix(col, uRippleColors[i], ring * 0.36);
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
    this.ripples = Array.from({ length: 4 }, () => ({
      uv: new THREE.Vector2(0.5, 0.5),
      age: 99,
      active: 0,
      color: new THREE.Color(0xe6aa42),
    }));
    this._rippleCursor = 0;
    this.bgUniforms = {
      uTime: { value: 0 },
      uResolution: { value: new THREE.Vector2(this.width, this.height) },
      uRipples: { value: this.ripples.map(() => new THREE.Vector4(0.5, 0.5, 99, 0)) },
      uRippleColors: { value: this.ripples.map((r) => r.color.clone()) },
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
    this.vfxEffects = []; // Kinetic 3D weapon slashes, pierce lances, blunt impacts, block walls, energy beams, shield pulses
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
    this.bgUniforms.uPhaseTint.value.setHex(hex);
  }

  setCombatFocus(active) {
    this.targetCombatFocus = active ? 1 : 0;
  }

  triggerRipple(sx, sy, hex = 0xe8a63c) {
    const idx = this._rippleCursor++ % 4;
    this.ripples[idx].uv.set(sx / Math.max(1, this.width), 1 - sy / Math.max(1, this.height));
    this.ripples[idx].age = 0;
    this.ripples[idx].active = 1;
    this.ripples[idx].color.setHex(hex);
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
   * 3D Sweeping Luminous Slash Crescent cutting across the target!
   */
  spawnSlashArc({ fromX, fromY, toX, toY, colorHex = 0xcf4330 }) {
    const target = this.screenToWorld(toX, toY, 52);
    const origin = this.screenToWorld(fromX, fromY, 52);
    const dir = Math.atan2(target.y - origin.y, target.x - origin.x);

    const group = new THREE.Group();
    group.position.copy(target);

    const outerGeo = new THREE.RingGeometry(42, 74, 28, 1, -Math.PI * 0.45, Math.PI * 0.9);
    const outerMat = new THREE.MeshBasicMaterial({
      color: colorHex,
      transparent: true,
      opacity: 0.92,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    const innerGeo = new THREE.RingGeometry(56, 68, 28, 1, -Math.PI * 0.36, Math.PI * 0.72);
    const innerMat = new THREE.MeshBasicMaterial({
      color: 0xfff8e6,
      transparent: true,
      opacity: 0.95,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    const outerMesh = new THREE.Mesh(outerGeo, outerMat);
    const innerMesh = new THREE.Mesh(innerGeo, innerMat);
    innerMesh.position.z = 4;
    group.add(outerMesh, innerMesh);
    group.rotation.z = dir - 0.9;
    group.rotation.y = (target.x >= origin.x ? 0.25 : -0.25);
    this.scene.add(group);

    this.triggerRipple(toX, toY, colorHex);
    this.spawnImpactBurst(toX, toY, colorHex, 24, true);

    this.vfxEffects.push({
      kind: 'slash',
      group,
      geometries: [outerGeo, innerGeo],
      materials: [outerMat, innerMat],
      baseRotZ: dir - 0.95,
      sweep: target.x >= origin.x ? 1.85 : -1.85,
      age: 0,
      life: 0.44,
    });
  }

  /**
   * 3D High-Velocity Piercing Lance Beam streaking straight from attacker to target!
   */
  spawnPierceLance({ fromX, fromY, toX, toY, colorHex = 0xcc7b14 }) {
    const p0 = this.screenToWorld(fromX, fromY, 54);
    const p1 = this.screenToWorld(toX, toY, 54);
    const delta = p1.clone().sub(p0);
    const dist = Math.max(40, delta.length());
    const angle = Math.atan2(delta.y, delta.x);

    const group = new THREE.Group();
    const beamGeo = new THREE.CylinderGeometry(3.2, 7.5, dist * 0.72, 10);
    const beamMat = new THREE.MeshBasicMaterial({
      color: colorHex,
      transparent: true,
      opacity: 0.9,
      depthWrite: false,
    });
    const coreGeo = new THREE.CylinderGeometry(1.5, 3.2, dist * 0.76, 8);
    const coreMat = new THREE.MeshBasicMaterial({
      color: 0xfff9e8,
      transparent: true,
      opacity: 0.95,
      depthWrite: false,
    });
    const beam = new THREE.Mesh(beamGeo, beamMat);
    const core = new THREE.Mesh(coreGeo, coreMat);
    beam.rotation.z = -Math.PI / 2;
    core.rotation.z = -Math.PI / 2;
    group.add(beam, core);
    group.rotation.z = angle;
    group.position.copy(p0);
    this.scene.add(group);

    this.triggerRipple(toX, toY, colorHex);
    this.spawnImpactBurst(toX, toY, colorHex, 20, false);

    this.vfxEffects.push({
      kind: 'pierce',
      group,
      geometries: [beamGeo, coreGeo],
      materials: [beamMat, coreMat],
      p0, p1,
      age: 0,
      life: 0.4,
    });
  }

  /**
   * 3D Heavy Blunt Shockwave slamming onto target!
   */
  spawnBluntImpact({ toX, toY, colorHex = 0xb33443 }) {
    const center = this.screenToWorld(toX, toY, 44);
    const group = new THREE.Group();
    group.position.copy(center);

    const octGeo = new THREE.RingGeometry(16, 44, 8);
    const octMat = new THREE.MeshBasicMaterial({
      color: colorHex,
      transparent: true,
      opacity: 0.85,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    const coreGeo = new THREE.CircleGeometry(24, 8);
    const coreMat = new THREE.MeshBasicMaterial({
      color: 0xfff5e0,
      transparent: true,
      opacity: 0.8,
      depthWrite: false,
    });
    group.add(new THREE.Mesh(octGeo, octMat), new THREE.Mesh(coreGeo, coreMat));
    this.scene.add(group);

    this.triggerRipple(toX, toY, colorHex);
    this.spawnImpactBurst(toX, toY, colorHex, 30, true);

    this.vfxEffects.push({
      kind: 'blunt',
      group,
      geometries: [octGeo, coreGeo],
      materials: [octMat, coreMat],
      age: 0,
      life: 0.46,
    });
  }

  /**
   * 3D Jade Hexagonal Block Wall flashing at the clash / defender point!
   */
  spawnBlockBarrier({ x, y, colorHex = 0x1a8775 }) {
    const center = this.screenToWorld(x, y, 56);
    const group = new THREE.Group();
    group.position.copy(center);

    const plateGeo = new THREE.CircleGeometry(46, 6);
    const plateMat = new THREE.MeshBasicMaterial({
      color: colorHex,
      transparent: true,
      opacity: 0.34,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    const edgeGeo = new THREE.EdgesGeometry(plateGeo);
    const edgeMat = new THREE.LineBasicMaterial({ color: colorHex, transparent: true, opacity: 0.95 });
    const ringGeo = new THREE.RingGeometry(48, 55, 6);
    const ringMat = new THREE.MeshBasicMaterial({
      color: 0xfffbf0,
      transparent: true,
      opacity: 0.9,
      side: THREE.DoubleSide,
      depthWrite: false,
    });

    group.add(new THREE.Mesh(plateGeo, plateMat), new THREE.LineSegments(edgeGeo, edgeMat), new THREE.Mesh(ringGeo, ringMat));
    this.scene.add(group);
    this.triggerRipple(x, y, colorHex);

    this.vfxEffects.push({
      kind: 'block',
      group,
      geometries: [plateGeo, edgeGeo, ringGeo],
      materials: [plateMat, edgeMat, ringMat],
      age: 0,
      life: 0.56,
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
   * 3D Luminous Parabolic Energy Comet flying from Passive -> Fighter or Cost -> Card!
   */
  spawnEnergyBeam({ fromX, fromY, toX, toY, colorHex = 0xd48e1a, duration = 0.48 }) {
    const p0 = this.screenToWorld(fromX, fromY, 44);
    const p1 = this.screenToWorld(toX, toY, 44);
    const mid = p0.clone().lerp(p1, 0.5);
    mid.y += 42;
    mid.z += 72;

    const group = new THREE.Group();
    const orbGeo = new THREE.OctahedronGeometry(9);
    const orbMat = new THREE.MeshBasicMaterial({ color: colorHex, transparent: true, opacity: 0.95 });
    const haloGeo = new THREE.RingGeometry(11, 16, 16);
    const haloMat = new THREE.MeshBasicMaterial({
      color: 0xfff8df,
      transparent: true,
      opacity: 0.9,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    group.add(new THREE.Mesh(orbGeo, orbMat), new THREE.Mesh(haloGeo, haloMat));
    group.position.copy(p0);
    this.scene.add(group);

    this.vfxEffects.push({
      kind: 'beam',
      group,
      geometries: [orbGeo, haloGeo],
      materials: [orbMat, haloMat],
      p0, mid, p1,
      toX, toY, colorHex,
      age: 0,
      life: duration,
    });
  }

  spawnImpactBurst(sx, sy, colorHex = 0xe89b32, count = 28, heavy = false) {
    this.triggerRipple(sx, sy, colorHex);
    const origin = this.screenToWorld(sx, sy, 36);
    const baseColor = new THREE.Color(colorHex);
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
      color: colorHex,
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

    for (let i = 0; i < 4; i++) {
      const r = this.ripples[i];
      if (r.active) {
        r.age += dtSec;
        if (r.age > 1.2) r.active = 0;
      }
      this.bgUniforms.uRipples.value[i].set(r.uv.x, r.uv.y, r.age, r.active);
      this.bgUniforms.uRippleColors.value[i].copy(r.color);
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

      const fadeOut = d.age > d.lifetime - 0.32 ? Math.max(0, (d.lifetime - d.age) / 0.32) : 1;
      const badgeIn = Math.max(0, Math.min(1, (d.age - 0.3) / 0.18));
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
        this.scene.remove(c.mesh);
        c.frontTex.dispose();
        c.backTex.dispose();
        c.frontMat.dispose();
        c.backMat.dispose();
        this.flippingCards.splice(i, 1);
      }
    }

    // 3D Kinetic Combat & Energy VFX
    for (let i = this.vfxEffects.length - 1; i >= 0; i--) {
      const v = this.vfxEffects[i];
      v.age += dtSec;
      const t = Math.min(1, v.age / v.life);
      if (v.kind === 'slash') {
        const ease = 1 - Math.pow(1 - t, 3);
        v.group.rotation.z = v.baseRotZ + ease * v.sweep;
        v.group.scale.setScalar(0.75 + ease * 0.72);
        const fade = t < 0.2 ? t / 0.2 : 1 - (t - 0.2) / 0.8;
        v.materials[0].opacity = fade * 0.92;
        v.materials[1].opacity = fade * 0.96;
      } else if (v.kind === 'pierce') {
        const ease = 1 - Math.pow(1 - t, 2.5);
        v.group.position.lerpVectors(v.p0, v.p1, ease);
        v.group.scale.set(0.4 + ease * 0.8, 1 - t * 0.45, 1);
        const fade = t < 0.15 ? t / 0.15 : 1 - (t - 0.15) / 0.85;
        v.materials[0].opacity = fade * 0.92;
        v.materials[1].opacity = fade * 0.96;
      } else if (v.kind === 'blunt') {
        const ease = 1 - Math.pow(1 - t, 3);
        v.group.scale.setScalar(0.55 + ease * 1.85);
        v.group.rotation.z += dtSec * 3.5;
        v.materials[0].opacity = (1 - t) * 0.86;
        v.materials[1].opacity = Math.max(0, 1 - t * 1.4) * 0.8;
      } else if (v.kind === 'block') {
        const pop = t < 0.22 ? 0.6 + (t / 0.22) * 0.55 : 1.15 - (t - 0.22) * 0.15;
        v.group.scale.setScalar(pop);
        v.group.rotation.z = Math.sin(t * Math.PI) * 0.14;
        const fade = t < 0.6 ? 1 : 1 - (t - 0.6) / 0.4;
        v.materials[0].opacity = fade * 0.34;
        v.materials[1].opacity = fade * 0.95;
        v.materials[2].opacity = fade * 0.9;
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
        v.group.position.set(x, y, z);
        v.group.rotation.z += dtSec * 11;
        v.group.scale.setScalar(0.7 + Math.sin(t * Math.PI) * 0.55);
        if (t >= 1) {
          this.spawnImpactBurst(v.toX, v.toY, v.colorHex, 12, false);
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
        this.scene.remove(r.mesh);
        r.geo.dispose();
        r.mat.dispose();
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
