/**
 * Three.js WebGL 3D & Custom GLSL Shader Engine for 《光点计划 III》.
 * Strictly BRIGHT palette — ZERO black, ZERO blue-purple!
 * Frontal low-FOV pixel-calibrated 3D camera:
 *  - z = 0 aligns 1:1 with CSS/PixiJS pixels (zero board distortion)
 *  - Custom GLSL ShaderMaterial bright light-field surface with real-time impact ripples
 *  - True 3D polyhedral dice (d4, d6, d8, d12, custom d16, d20)
 *  - True 3D double-sided card flips & parabolic arcs (place, pull, reveal, swap, recycle)
 *  - Single-draw-call InstancedMesh 3D clash sparks & shockwave rings
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
  uniform vec4 uRipples[4];      // xy: uv, z: ageSec, w: active(0/1)
  uniform vec3 uRippleColors[4];
  uniform vec3 uPhaseTint;

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

    // Bright sunlit warm-alabaster base field (zero black, zero blue-purple)
    float radial = length(p * vec2(0.85, 1.05));
    vec3 centerCol = vec3(0.976, 0.967, 0.945);
    vec3 edgeCol = vec3(0.922, 0.900, 0.858);
    vec3 col = mix(centerCol, edgeCol, smoothstep(0.05, 0.95, radial));

    // Gentle living sunlit caustic waves
    float w1 = noise(p * 3.2 + vec2(uTime * 0.06, -uTime * 0.04));
    float w2 = noise(p * 6.5 - vec2(uTime * 0.04, uTime * 0.05));
    float caustic = smoothstep(0.38, 0.85, w1 * 0.65 + w2 * 0.35);
    col = mix(col, vec3(1.0, 0.992, 0.968), caustic * 0.38);

    // Subtle warm phase glow around arena center
    col = mix(col, uPhaseTint, (1.0 - smoothstep(0.0, 0.78, radial)) * 0.065);

    // Delicate fine paper grain
    float grain = (hash(gl_FragCoord.xy * 0.5) - 0.5) * 0.014;
    col += grain;

    // Interactive WebGL light ripples on clash / card land / shield break
    for (int i = 0; i < 4; i++) {
      if (uRipples[i].w > 0.5) {
        float age = uRipples[i].z;
        float dist = length((vUv - uRipples[i].xy) * aspect);
        float radius = age * 0.62;
        float ring = exp(-pow((dist - radius) * 24.0, 2.0)) * max(0.0, 1.0 - age / 1.15);
        col = mix(col, uRippleColors[i], ring * 0.32);
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

  // Bright warm-ivory ceramic disc with crisp colored rim (ZERO black!)
  g.beginPath();
  g.arc(128, 128, 76, 0, Math.PI * 2);
  g.fillStyle = 'rgba(255, 252, 245, 0.94)';
  g.fill();
  g.lineWidth = 7;
  g.strokeStyle = accentHex;
  g.stroke();

  g.font = '800 84px "Segoe UI", "Microsoft YaHei", sans-serif';
  g.textAlign = 'center';
  g.textBaseline = 'middle';
  g.fillStyle = '#3b322a';
  g.fillText(String(value), 128, sub ? 115 : 128);

  if (sub) {
    g.font = '700 28px "Segoe UI", "Microsoft YaHei", sans-serif';
    g.fillStyle = accentHex;
    g.fillText(sub, 128, 174);
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
    // Bright geometric light-point emblem
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
    g.globalAlpha = 0.14;
    g.fillRect(0, 0, 256, 94);
    g.globalAlpha = 1;
    g.strokeStyle = accentHex || '#1e8f68';
    g.lineWidth = 8;
    g.strokeRect(6, 6, 244, 344);

    // Cost circle
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
      g.fillRect(22, 118 + i * 64, 212, 48);
    }
  }
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

const MAX_SPARKS = 160;

export class ThreeWorld {
  constructor(canvas) {
    this.canvas = canvas;
    this.width = window.innerWidth;
    this.height = window.innerHeight;
    this.fov = 28; // Low FOV: crisp frontal readability + genuine 3D card/dice depth

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

    // Bright daylight 3-point lighting (warm sun key + soft sand fill)
    const hemi = new THREE.HemisphereLight(0xfffdf7, 0xe8dcc8, 1.45);
    this.scene.add(hemi);

    const sun = new THREE.DirectionalLight(0xfff8e8, 1.35);
    sun.position.set(-220, 340, 820);
    this.scene.add(sun);

    const fill = new THREE.DirectionalLight(0xfdecd2, 0.65);
    fill.position.set(360, -240, 520);
    this.scene.add(fill);

    // Single-draw-call InstancedMesh for 3D sparks (zero per-clash geometry allocation!)
    this._dummy = new THREE.Object3D();
    const sparkGeo = new THREE.OctahedronGeometry(4.5);
    const sparkMat = new THREE.MeshStandardMaterial({
      color: 0xffffff,
      roughness: 0.25,
      metalness: 0.2,
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
    // Hide all unused spark instances cleanly
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

    // Reusable 3D card flip geometry
    this._cardGeo = new THREE.BoxGeometry(1, 1, 3.2);
    this._cardEdgeMat = new THREE.MeshStandardMaterial({ color: 0xe3d8c5, roughness: 0.5 });

    // Subtle floating daylight dust/light motes
    this._motes = this._buildLightMotes();

    this.activeDice = [];
    this.flippingCards = [];
    this.rings = [];
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

  triggerRipple(sx, sy, hex = 0xe8a63c) {
    const idx = this._rippleCursor++ % 4;
    this.ripples[idx].uv.set(sx / Math.max(1, this.width), 1 - sy / Math.max(1, this.height));
    this.ripples[idx].age = 0;
    this.ripples[idx].active = 1;
    this.ripples[idx].color.setHex(hex);
  }

  _buildLightMotes() {
    const count = 36;
    const pos = new Float32Array(count * 3);
    const phases = new Float32Array(count);
    for (let i = 0; i < count; i++) {
      pos[i * 3] = (Math.random() - 0.5) * this.width;
      pos[i * 3 + 1] = (Math.random() - 0.5) * this.height;
      pos[i * 3 + 2] = 20 + Math.random() * 120;
      phases[i] = Math.random() * Math.PI * 2;
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    const mat = new THREE.PointsMaterial({
      color: 0xd9a84e,
      size: 4.5,
      transparent: true,
      opacity: 0.28,
      depthWrite: false,
    });
    const points = new THREE.Points(geo, mat);
    this.scene.add(points);
    return { points, phases, t: 0 };
  }

  /**
   * Launch a crisp bright-ceramic 3D polyhedral die (d4/d6/d8/d12/d16/d20) with warm contact shadow.
   */
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
    radius = 26,
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
    const edgeMat = new THREE.LineBasicMaterial({ color: pal.edge, transparent: true, opacity: 0.65 });
    mesh.add(new THREE.LineSegments(edgeGeo, edgeMat));
    group.add(mesh);

    // Warm soft sand-taupe shadow disc (NEVER black!)
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
    badge.scale.set(radius * 2.4, radius * 2.4, 1);
    this.scene.add(badge);

    this.scene.add(group);
    this.activeDice.push({
      group, mesh, shadow, badge,
      geo, mat, edgeGeo, edgeMat, shadowGeo, shadowMat, badgeTex, badgeMat,
      startX, startY, targetX, targetY,
      physicsBody,
      z: 140, vz: 90,
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

  spawnImpactBurst(sx, sy, colorHex = 0xe89b32, count = 28, heavy = false) {
    this.triggerRipple(sx, sy, colorHex);
    const origin = this.screenToWorld(sx, sy, 36);
    const baseColor = new THREE.Color(colorHex);
    const brightColor = new THREE.Color(0xfff7df);

    for (let i = 0; i < count; i++) {
      const idx = this._sparkCursor++ % MAX_SPARKS;
      const s = this.sparkSlots[idx];
      const a = Math.random() * Math.PI * 2;
      const spd = (heavy ? 240 : 165) + Math.random() * (heavy ? 310 : 210);
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

    // 3D expanding shockwave ring
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

  update(dtSec) {
    // 1. Update background GLSL shader uniforms
    this.bgUniforms.uTime.value += dtSec;
    for (let i = 0; i < 4; i++) {
      const r = this.ripples[i];
      if (r.active) {
        r.age += dtSec;
        if (r.age > 1.2) r.active = 0;
      }
      this.bgUniforms.uRipples.value[i].set(r.uv.x, r.uv.y, r.age, r.active);
      this.bgUniforms.uRippleColors.value[i].copy(r.color);
    }

    // 2. Ambient daylight light-point motes
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

    // 3. Update 3D polyhedral dice (bound 1:1 to Matter.js physicsBody when clashing!)
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
      const badgeIn = Math.max(0, Math.min(1, (d.age - 0.32) / 0.2));
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

    // 4. Update 3D flipping/pulling card arcs
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

    // 5. Update InstancedMesh sparks
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

    // 6. Update 3D shockwave rings
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

    // Render shader field then 3D scene cleanly on single WebGL context
    this.renderer.autoClear = true;
    this.renderer.render(this.bgScene, this.bgCamera);
    this.renderer.autoClear = false;
    this.renderer.clearDepth();
    this.renderer.render(this.scene, this.camera);
  }
}
