/**
 * Living Procedural WebGL Character Actors, Animated Status Auras & Concentric Shield Domes
 * for 《光点计划 III》.
 * Strictly bright palette (ZERO black, ZERO blue-purple).
 * Each fighter is a sculpted, breathing, animated kinetic figure facing the opponent across the arena —
 * infinitely extensible across 1v1, 10v10, and unlimited future rosters via `registerActorVisual`
 * and `resolveInfiniteActorSpec`!
 */

import * as PIXI from '../vendor/pixi.min.mjs';
import { INK, SIDE_THEME, SHIELD_STYLE, STATUS_COLORS } from './card_print.js';
import { resolveInfiniteActorSpec } from './formation.js';
import { createSkeletalSvgRig, setCharacterSpriteUrls, getCharacterSpriteUrl } from './svg_rig.js';

export { setCharacterSpriteUrls, getCharacterSpriteUrl };

const VALID_ARCHETYPES = new Set(['blade', 'lance', 'staff', 'shield', 'dual', 'cannon', 'tome']);
const VALID_CRESTS = new Set(['diamond', 'hex', 'star', 'chevron', 'sunburst', 'octagram', 'shield_crest']);
const VALID_AURAS = new Set([
  'wind_ribbons',
  'astrolabe',
  'solar_halo',
  'ember_ring',
  'prism_orbit',
  'banner_crest',
  'harmonic_arcs',
]);
const VALID_MANTLES = new Set(['cloak', 'pauldron', 'coat', 'robe', 'tactical']);

const HANDCRAFTED_PALETTES = {
  plan_b_annolin: {
    primary: 0x1c946b, secondary: 0x52c496, highlight: 0xdef7ec, metal: 0xd49622, trim: 0x3b322a, motif: 'annolin',
  },
  waa_lake: {
    primary: 0xc95a2b, secondary: 0xe69e32, highlight: 0xfef2dc, metal: 0x7a6a58, trim: 0x3b322a, motif: 'lake',
  },
  waa_grolina: {
    primary: 0xc44b3c, secondary: 0xe8a238, highlight: 0xfeefe2, metal: 0x877662, trim: 0x3b322a, motif: 'grolina',
  },
  waa_erkes: {
    primary: 0x5d8f2c, secondary: 0xd4941e, highlight: 0xf4f8e4, metal: 0x6b6052, trim: 0x3b322a, motif: 'erkes',
  },
  mistport_cen_yao: {
    primary: 0x1e8a78, secondary: 0xd48e1a, highlight: 0xe6f7f2, metal: 0x8a7558, trim: 0x3b322a, motif: 'cen_yao',
  },
  ember_wen_sheng: {
    primary: 0xc44558, secondary: 0xd99224, highlight: 0xfdeef0, metal: 0x7d6858, trim: 0x3b322a, motif: 'wen_sheng',
  },
  char_iron_vanguard: {
    primary: 0x6b7c5e, secondary: 0xd49622, highlight: 0xedf2e6, metal: 0x8c7b68, trim: 0x3b322a, motif: 'iron_vanguard',
  },
  char_crimson_duelist: {
    primary: 0xc93b44, secondary: 0xe6a12c, highlight: 0xfdebed, metal: 0x7d6d5b, trim: 0x3b322a, motif: 'crimson_duelist',
  },
  drill_scout: {
    primary: 0x2a8f72, secondary: 0xd49b2c, highlight: 0xe7f5ef, metal: 0x6b6052, trim: 0x3b322a, motif: 'drill_scout',
  },
  drill_medic: {
    primary: 0x3b9c6e, secondary: 0xe08a24, highlight: 0xebf8f0, metal: 0x8a7558, trim: 0x3b322a, motif: 'drill_medic',
  },
  drill_captain: {
    primary: 0xc96b1f, secondary: 0xe6ad2e, highlight: 0xfef4df, metal: 0x7d6d5b, trim: 0x3b322a, motif: 'drill_captain',
  },
  drill_engine: {
    primary: 0x9e5828, secondary: 0xe39e24, highlight: 0xfaeee2, metal: 0x6b6052, trim: 0x3b322a, motif: 'drill_engine',
  },
  plan_b_heck: {
    primary: 0xc94e24, secondary: 0xeb9b28, highlight: 0xfef0df, metal: 0x6e5d4f, trim: 0x3b322a, motif: 'heck',
  },
  plan_b_heris: {
    primary: 0xd1542a, secondary: 0xeaa42e, highlight: 0xfef1e2, metal: 0x7a6856, trim: 0x3b322a, motif: 'heris',
  },
  plan_b_li_ling: {
    primary: 0x208578, secondary: 0xdba228, highlight: 0xe8f6f2, metal: 0x6d685e, trim: 0x3b322a, motif: 'li_ling',
  },
  plan_b_sa: {
    primary: 0xa82e3c, secondary: 0xd9a028, highlight: 0xfbecef, metal: 0x736256, trim: 0x3b322a, motif: 'sa',
  },
  iron_qi_zheng: {
    primary: 0x9c322c, secondary: 0xd99b26, highlight: 0xfbebea, metal: 0x6b6258, trim: 0x3b322a, motif: 'qi_zheng',
  },
  nova_lin_qiu: {
    primary: 0x2b7e82, secondary: 0xe0a832, highlight: 0xedf6f5, metal: 0x8c7c66, trim: 0x3b322a, motif: 'lin_qiu',
  },
  blank_boss: {
    primary: 0xc29838, secondary: 0xe3be5e, highlight: 0xfcf8ec, metal: 0x9e927e, trim: 0x453b31, motif: 'blank_boss',
  },
  bellfounder_que_ming: {
    primary: 0x3d826e, secondary: 0xd4962c, highlight: 0xedf5f0, metal: 0x877250, trim: 0x3b322a, motif: 'que_ming',
  },
  shipbreaker_shen_li: {
    primary: 0x2f7578, secondary: 0xc9682e, highlight: 0xeaf3f2, metal: 0x6b645c, trim: 0x3b322a, motif: 'shen_li',
  },
  emyake_lin_yu: {
    primary: 0x2563eb, secondary: 0x38bdf8, highlight: 0xedf7ff, metal: 0x7c3aed, trim: 0x152242, motif: 'lin_yu',
  },
};

const HANDCRAFTED_MOTIFS = new Set(Object.values(HANDCRAFTED_PALETTES).map((p) => p.motif));
const ACTOR_VISUAL_REGISTRY = new Map();

function clamp01(v) {
  return Math.max(0, Math.min(1, v));
}

function sanitizeWarmBrightHex(hex, fallback) {
  if (typeof hex !== 'number' || !Number.isFinite(hex)) return fallback;
  const clean = Math.floor(hex) & 0xffffff;
  let r = (clean >> 16) & 255;
  let g = (clean >> 8) & 255;
  let b = clean & 255;

  if (b > r + 15 && b > g + 15) {
    b = Math.max(0, Math.min(r, g) + 8);
  }
  const peak = Math.max(r, g, b);
  if (peak < 48) {
    const lift = 48 - peak;
    r = Math.min(255, r + lift + 10);
    g = Math.min(255, g + lift + 6);
    b = Math.min(255, b + lift);
  }
  return (r << 16) | (g << 8) | b;
}

function drawPolygon(g, cx, cy, r, sides, rot = 0) {
  const pts = [];
  for (let i = 0; i < sides; i++) {
    const a = rot + (i * Math.PI * 2) / sides;
    pts.push(cx + Math.cos(a) * r, cy + Math.sin(a) * r);
  }
  return pts;
}

function drawStarPolygon(cx, cy, outerR, innerR, points, rot = -Math.PI / 2) {
  const pts = [];
  const total = points * 2;
  for (let i = 0; i < total; i++) {
    const rad = i % 2 === 0 ? outerR : innerR;
    const a = rot + (i * Math.PI) / points;
    pts.push(cx + Math.cos(a) * rad, cy + Math.sin(a) * rad);
  }
  return pts;
}

/**
 * Register a data-driven actor visual spec for any character ID (future roster, custom boss, or override).
 * Any provided hex colors are strictly sanitized to the warm bright non-blue-purple palette.
 *
 * @param {string} charId
 * @param {object} spec - Optional palette (`primary`, `secondary`, `highlight`, `metal`, `trim`),
 *   procedural traits (`weaponArchetype`, `crestShape`, `auraMotif`, `mantleStyle`, `silhouetteScale`, `crestRings`),
 *   `motif`, and optional custom renderer `draw(g, pal, ch, radius, time)`.
 */
export function registerActorVisual(charId, spec = {}) {
  if (!charId || typeof charId !== 'string' || !spec || typeof spec !== 'object') {
    return null;
  }
  const entry = {};
  if (typeof spec.primary === 'number') entry.primary = sanitizeWarmBrightHex(spec.primary, INK.gold);
  if (typeof spec.secondary === 'number') entry.secondary = sanitizeWarmBrightHex(spec.secondary, INK.gold);
  if (typeof spec.highlight === 'number') entry.highlight = sanitizeWarmBrightHex(spec.highlight, INK.paperSoft);
  if (typeof spec.metal === 'number') entry.metal = sanitizeWarmBrightHex(spec.metal, INK.secondary);
  if (typeof spec.trim === 'number') entry.trim = sanitizeWarmBrightHex(spec.trim, INK.primary);

  if (typeof spec.motif === 'string' && spec.motif) entry.motif = spec.motif;
  if (VALID_ARCHETYPES.has(spec.weaponArchetype)) entry.weaponArchetype = spec.weaponArchetype;
  if (VALID_CRESTS.has(spec.crestShape)) entry.crestShape = spec.crestShape;
  if (VALID_AURAS.has(spec.auraMotif)) entry.auraMotif = spec.auraMotif;
  if (VALID_MANTLES.has(spec.mantleStyle)) entry.mantleStyle = spec.mantleStyle;

  if (typeof spec.silhouetteScale === 'number' && Number.isFinite(spec.silhouetteScale)) {
    entry.silhouetteScale = Math.max(0.85, Math.min(1.22, spec.silhouetteScale));
  }
  if (typeof spec.crestRings === 'number' && Number.isFinite(spec.crestRings)) {
    entry.crestRings = Math.max(1, Math.min(3, Math.round(spec.crestRings)));
  }
  if (typeof spec.draw === 'function') entry.draw = spec.draw;

  ACTOR_VISUAL_REGISTRY.set(charId, entry);
  return entry;
}

/**
 * Character-specific visual palette & silhouette motif (strictly warm bright tones, zero black/blue-purple).
 * Supports:
 *  1. Data-driven overrides registered via `registerActorVisual(charId, spec)`
 *  2. All 12 handcrafted canonical character palettes & silhouettes
 *  3. Deterministic infinite-roster fallback via `resolveInfiniteActorSpec(ch, side)`
 */
export function actorPalette(ch, side = 1) {
  const id = ch?.id || '';
  const handcrafted = HANDCRAFTED_PALETTES[id];
  const registered = id ? ACTOR_VISUAL_REGISTRY.get(id) : null;

  if (handcrafted && !registered) {
    return { ...handcrafted };
  }

  const infiniteSpec = resolveInfiniteActorSpec(ch, side);
  const base = handcrafted
    ? {
        ...infiniteSpec,
        ...handcrafted,
      }
    : {
        ...infiniteSpec,
        procedural: true,
      };

  if (!registered) {
    return base;
  }

  const merged = { ...base, ...registered };
  const overridesArchetype = Boolean(
    registered.weaponArchetype || registered.crestShape || registered.auraMotif || registered.mantleStyle
  );
  if (!registered.motif && overridesArchetype) {
    merged.motif = `${merged.weaponArchetype}_${merged.crestShape}`;
    merged.procedural = true;
  } else if (registered.motif && !HANDCRAFTED_MOTIFS.has(registered.motif)) {
    merged.procedural = true;
  }
  return merged;
}

/**
 * Draw procedural back aura motif behind the fighter (all 7 motifs from `resolveInfiniteActorSpec`).
 */
function drawArchetypeAura(g, auraMotif, primary, secondary, hi, metal, r, time, breathe, flutter, animAmp) {
  if (auraMotif === 'wind_ribbons') {
    g.moveTo(-r * 0.12, -r * 0.24 + breathe)
      .quadraticCurveTo(-r * 0.62, -r * 0.48 + flutter, -r * 0.94, -r * 0.20 - flutter)
      .quadraticCurveTo(-r * 0.54, -r * 0.02 + flutter * 0.5, -r * 0.14, r * 0.06 + breathe)
      .fill({ color: secondary, alpha: 0.68 });
    g.moveTo(-r * 0.08, -r * 0.06 + breathe)
      .quadraticCurveTo(-r * 0.56, r * 0.20 - flutter, -r * 0.86, r * 0.44 + flutter * 0.6)
      .quadraticCurveTo(-r * 0.42, r * 0.44, -r * 0.08, r * 0.20 + breathe)
      .fill({ color: primary, alpha: 0.54 });
    return;
  }

  if (auraMotif === 'astrolabe') {
    const spin = time * 0.65;
    const cy = -r * 0.12 + breathe;
    g.circle(0, cy, r * 0.70).stroke({ width: 1.4, color: secondary, alpha: 0.72 });
    g.arc(0, cy, r * 0.56, spin, spin + Math.PI * 1.15)
      .stroke({ width: 1.2, color: primary, alpha: 0.55, cap: 'round' });
    for (let i = 0; i < 4; i++) {
      const a = spin + (i * Math.PI) / 2;
      g.moveTo(Math.cos(a) * r * 0.56, cy + Math.sin(a) * r * 0.56)
        .lineTo(Math.cos(a) * r * 0.78, cy + Math.sin(a) * r * 0.78)
        .stroke({ width: 1.6, color: secondary, alpha: 0.85 });
    }
    return;
  }

  if (auraMotif === 'solar_halo') {
    const cy = -r * 0.18 + breathe;
    const pulse = 1 + Math.sin(time * 3.4) * 0.05 * animAmp;
    g.poly(drawStarPolygon(0, cy, r * 0.78 * pulse, r * 0.54 * pulse, 8, time * 0.32))
      .fill({ color: secondary, alpha: 0.22 })
      .stroke({ width: 1.3, color: secondary, alpha: 0.62 });
    g.circle(0, cy, r * 0.52).stroke({ width: 1.4, color: primary, alpha: 0.48 });
    return;
  }

  if (auraMotif === 'ember_ring') {
    const count = 5;
    for (let i = 0; i < count; i++) {
      const ph = (time * 0.85 + i * 0.2) % 1;
      const spread = (i - 2) * r * 0.25 + Math.sin(time * 2.6 + i * 1.7) * r * 0.08 * animAmp;
      const ey = r * 0.42 - ph * r * 1.12;
      const sz = (1 - ph * 0.65) * Math.max(2.6, r * 0.13);
      g.poly([spread, ey - sz, spread + sz * 0.68, ey, spread, ey + sz, spread - sz * 0.68, ey])
        .fill({ color: i % 2 === 0 ? secondary : primary, alpha: (1 - ph) * 0.82 });
    }
    return;
  }

  if (auraMotif === 'prism_orbit') {
    const cy = -r * 0.10 + breathe;
    const tilt = -0.34;
    const cosT = Math.cos(tilt);
    const sinT = Math.sin(tilt);
    for (let i = 0; i < 3; i++) {
      const a = time * 1.45 + (i * Math.PI * 2) / 3;
      const lx = Math.cos(a) * r * 0.78;
      const ly = Math.sin(a) * r * 0.34;
      const px = lx * cosT - ly * sinT;
      const py = cy + lx * sinT + ly * cosT;
      const sz = Math.max(3.2, r * 0.14);
      g.poly([px, py - sz, px + sz * 0.72, py, px, py + sz, px - sz * 0.72, py])
        .fill({ color: i === 0 ? secondary : hi, alpha: 0.9 })
        .stroke({ width: 1.2, color: primary, alpha: 0.85 });
    }
    return;
  }

  if (auraMotif === 'banner_crest') {
    g.moveTo(-r * 0.50, -r * 0.78).lineTo(-r * 0.50, r * 0.60)
      .stroke({ width: Math.max(2, r * 0.075), color: metal, cap: 'round' });
    g.circle(-r * 0.50, -r * 0.80, Math.max(2.2, r * 0.08)).fill({ color: secondary });
    g.poly([
      -r * 0.50, -r * 0.74,
      -r * 0.96, -r * 0.56 + flutter * 0.65,
      -r * 0.78, -r * 0.42 + flutter * 0.5,
      -r * 0.94, -r * 0.24 + flutter * 0.55,
      -r * 0.50, -r * 0.32,
    ]).fill({ color: secondary, alpha: 0.86 }).stroke({ width: 1.3, color: primary });
    return;
  }

  // 'harmonic_arcs' (default procedural aura)
  const cy = -r * 0.08 + breathe;
  const a1 = time * 1.15;
  const a2 = -time * 0.95 + Math.PI;
  g.arc(0, cy, r * 0.74, a1, a1 + Math.PI * 0.72)
    .stroke({ width: 1.9, color: primary, alpha: 0.62, cap: 'round' });
  g.arc(0, cy, r * 0.84, a2, a2 + Math.PI * 0.68)
    .stroke({ width: 1.6, color: secondary, alpha: 0.72, cap: 'round' });
  g.circle(Math.cos(a1 + Math.PI * 0.72) * r * 0.74, cy + Math.sin(a1 + Math.PI * 0.72) * r * 0.74, Math.max(2.2, r * 0.075))
    .fill({ color: secondary, alpha: 0.9 });
}

/**
 * Draw procedural mantle / armor torso silhouette (all 5 styles from `resolveInfiniteActorSpec`).
 */
function drawArchetypeMantle(g, mantleStyle, primary, secondary, hi, metal, r, breathe, flutter) {
  if (mantleStyle === 'cloak') {
    g.moveTo(-r * 0.10, -r * 0.28 + breathe)
      .quadraticCurveTo(-r * 0.64, -r * 0.24 + flutter * 0.8, -r * 0.84, r * 0.42 - flutter * 0.5)
      .lineTo(-r * 0.22, r * 0.54)
      .fill({ color: primary, alpha: 0.74 }).stroke({ width: 1.3, color: secondary });
    g.poly([
      0, -r * 0.30 + breathe,
      r * 0.34, r * 0.12 + breathe,
      r * 0.22, r * 0.62,
      -r * 0.26, r * 0.62,
      -r * 0.34, r * 0.10 + breathe,
    ]).fill({ color: primary }).stroke({ width: 1.6, color: INK.paper });
    g.poly([
      0, -r * 0.20 + breathe,
      r * 0.16, r * 0.12 + breathe,
      0, r * 0.32 + breathe,
      -r * 0.14, r * 0.12 + breathe,
    ]).fill({ color: hi });
    return;
  }

  if (mantleStyle === 'pauldron') {
    g.poly([
      -r * 0.38, -r * 0.24 + breathe,
      r * 0.34, -r * 0.24 + breathe,
      r * 0.26, r * 0.62,
      -r * 0.32, r * 0.62,
    ]).fill({ color: primary }).stroke({ width: 1.8, color: INK.paper });
    g.roundRect(-r * 0.48, -r * 0.30 + breathe, r * 0.32, r * 0.22, Math.max(3, r * 0.12))
      .fill({ color: metal }).stroke({ width: 1.5, color: secondary });
    g.roundRect(r * 0.16, -r * 0.28 + breathe, r * 0.28, r * 0.20, Math.max(3, r * 0.12))
      .fill({ color: metal }).stroke({ width: 1.5, color: secondary });
    g.poly(drawPolygon(g, r * 0.02, r * 0.10 + breathe, r * 0.15, 6, 0))
      .fill({ color: secondary }).stroke({ width: 1.2, color: INK.paper });
    return;
  }

  if (mantleStyle === 'coat') {
    g.poly([
      -r * 0.26, -r * 0.28 + breathe,
      r * 0.30, -r * 0.22 + breathe,
      r * 0.36, r * 0.62,
      r * 0.04, r * 0.50,
      -r * 0.34, r * 0.62,
    ]).fill({ color: primary }).stroke({ width: 1.6, color: INK.paper });
    // High collar lapel + diagonal brass sash
    g.poly([
      -r * 0.18, -r * 0.26 + breathe,
      r * 0.20, -r * 0.20 + breathe,
      0, r * 0.08 + breathe,
    ]).fill({ color: hi });
    g.moveTo(-r * 0.22, -r * 0.16 + breathe).lineTo(r * 0.26, r * 0.44)
      .stroke({ width: Math.max(2.2, r * 0.085), color: secondary, cap: 'round' });
    return;
  }

  if (mantleStyle === 'robe') {
    g.poly([
      -r * 0.20, -r * 0.30 + breathe,
      r * 0.24, -r * 0.26 + breathe,
      r * 0.40, r * 0.62,
      -r * 0.40, r * 0.62,
    ]).fill({ color: primary }).stroke({ width: 1.6, color: INK.paper });
    g.poly([
      -r * 0.09, -r * 0.24 + breathe,
      r * 0.11, -r * 0.24 + breathe,
      r * 0.15, r * 0.60,
      -r * 0.13, r * 0.60,
    ]).fill({ color: secondary, alpha: 0.86 });
    g.poly([
      0, -r * 0.18 + breathe,
      r * 0.12, -r * 0.02 + breathe,
      0, r * 0.14 + breathe,
      -r * 0.12, -r * 0.02 + breathe,
    ]).fill({ color: hi });
    return;
  }

  // 'tactical' (default procedural torso)
  g.poly([
    -r * 0.28, -r * 0.24 + breathe,
    r * 0.32, -r * 0.18 + breathe,
    r * 0.26, r * 0.62,
    -r * 0.26, r * 0.62,
  ]).fill({ color: primary }).stroke({ width: 1.6, color: INK.paper });
  g.moveTo(-r * 0.22, -r * 0.16 + breathe).lineTo(r * 0.24, r * 0.40)
    .stroke({ width: Math.max(2.2, r * 0.08), color: secondary });
  g.moveTo(r * 0.24, -r * 0.12 + breathe).lineTo(-r * 0.20, r * 0.36)
    .stroke({ width: Math.max(1.8, r * 0.065), color: metal });
  g.circle(r * 0.02, r * 0.10 + breathe, r * 0.10)
    .fill({ color: INK.paper }).stroke({ width: 1.4, color: secondary });
}

/**
 * Draw sculpted head, crest emblem (all 7 crest shapes), and rank halo rings.
 */
function drawArchetypeHeadAndCrest(
  g, crestShape, primary, secondary, hi, metal, trim, r, breathe, flutter, rankTier, crestRings, time
) {
  const hx = r * 0.02;
  const hy = -r * 0.48 + breathe;

  // Rank halo rings behind/around head for ELITE / BOSS / EMPOWERED_BOSS
  if (rankTier >= 1 || crestRings >= 2) {
    g.poly(drawPolygon(g, hx, hy, r * 0.35, 4, Math.PI / 4 + time * 0.25))
      .stroke({ width: 1.5, color: secondary, alpha: 0.85 });
    if (rankTier >= 2 || crestRings >= 2) {
      g.circle(hx, hy, r * 0.42)
        .stroke({ width: 1.3, color: INK.gold, alpha: 0.72 });
    }
  }

  if (crestShape === 'hex') {
    g.poly(drawPolygon(g, hx, hy, r * 0.22, 6, Math.PI / 6))
      .fill({ color: INK.paper }).stroke({ width: 1.8, color: trim });
    g.poly([
      hx - r * 0.18, hy - r * 0.06,
      hx, hy - r * 0.24,
      hx + r * 0.20, hy - r * 0.06,
    ]).fill({ color: primary });
    g.roundRect(hx - r * 0.04, hy - r * 0.05, r * 0.24, r * 0.10, 2.5)
      .fill({ color: secondary });
    return;
  }

  // Sculpted sunlit head base
  g.circle(hx, hy, r * 0.20)
    .fill({ color: INK.paper }).stroke({ width: 1.75, color: trim });

  if (crestShape === 'diamond') {
    g.poly([
      hx - r * 0.20, hy - r * 0.04,
      hx - r * 0.02, hy - r * 0.30,
      hx + r * 0.20, hy - r * 0.08,
      hx, hy - r * 0.14,
    ]).fill({ color: primary });
    g.poly([
      hx + r * 0.04, hy - r * 0.26,
      hx + r * 0.12, hy - r * 0.16,
      hx + r * 0.04, hy - r * 0.06,
      hx - r * 0.04, hy - r * 0.16,
    ]).fill({ color: secondary }).stroke({ width: 1, color: INK.paper });
  } else if (crestShape === 'star') {
    g.poly(drawStarPolygon(hx, hy - r * 0.24, r * 0.16, r * 0.075, 5, -Math.PI / 2))
      .fill({ color: secondary }).stroke({ width: 1.1, color: primary });
  } else if (crestShape === 'chevron') {
    g.poly([
      hx - r * 0.24, hy - r * 0.24 + flutter * 0.25,
      hx, hy - r * 0.10,
      hx + r * 0.24, hy - r * 0.26 - flutter * 0.2,
      hx + r * 0.16, hy - r * 0.06,
      hx, hy - r * 0.02,
      hx - r * 0.18, hy - r * 0.06,
    ]).fill({ color: primary }).stroke({ width: 1.1, color: secondary });
  } else if (crestShape === 'sunburst') {
    g.poly([
      hx - r * 0.22, hy - r * 0.12,
      hx - r * 0.14, hy - r * 0.34,
      hx - r * 0.04, hy - r * 0.20,
      hx + r * 0.02, hy - r * 0.38,
      hx + r * 0.08, hy - r * 0.20,
      hx + r * 0.18, hy - r * 0.34,
      hx + r * 0.22, hy - r * 0.12,
    ]).fill({ color: secondary }).stroke({ width: 1.1, color: primary });
  } else if (crestShape === 'octagram') {
    g.poly(drawStarPolygon(hx, hy - r * 0.04, r * 0.30, r * 0.22, 8, time * 0.45))
      .stroke({ width: 1.35, color: secondary, alpha: 0.85 });
    g.circle(hx + r * 0.02, hy - r * 0.20, Math.max(2.2, r * 0.075))
      .fill({ color: primary }).stroke({ width: 1, color: hi });
  } else {
    // 'shield_crest'
    g.poly([
      hx - r * 0.20, hy - r * 0.10,
      hx + r * 0.22, hy - r * 0.10,
      hx + r * 0.18, hy - r * 0.24,
      hx - r * 0.18, hy - r * 0.24,
    ]).fill({ color: metal }).stroke({ width: 1.2, color: trim });
    g.poly([
      hx - r * 0.04, hy - r * 0.38,
      hx + r * 0.10, hy - r * 0.26,
      hx + r * 0.02, hy - r * 0.06,
      hx - r * 0.08, hy - r * 0.22,
    ]).fill({ color: secondary });
  }
}

/**
 * Draw distinct animated foreground weapon silhouette for all 7 archetypes:
 * `blade`, `lance`, `staff`, `shield`, `dual`, `cannon`, `tome`.
 */
function drawArchetypeWeapon(g, weaponArchetype, primary, secondary, hi, metal, trim, r, time, breathe, animAmp) {
  if (weaponArchetype === 'blade') {
    const sway = Math.sin(time * 2.8) * r * 0.05 * animAmp;
    // Sweeping sunlit saber / greatsword held forward-high
    g.moveTo(r * 0.20, r * 0.18 + breathe)
      .quadraticCurveTo(r * 0.64, -r * 0.10 + sway, r * 1.02, -r * 0.54 + breathe + sway)
      .quadraticCurveTo(r * 0.78, r * 0.06 + sway * 0.4, r * 0.30, r * 0.28 + breathe)
      .fill({ color: INK.paper }).stroke({ width: 1.8, color: primary });
    g.moveTo(r * 0.26, r * 0.19 + breathe)
      .lineTo(r * 0.92, -r * 0.44 + breathe + sway)
      .stroke({ width: 1.6, color: secondary, cap: 'round' });
    // Sculpted crossguard
    g.moveTo(r * 0.14, r * 0.08 + breathe).lineTo(r * 0.36, r * 0.32 + breathe)
      .stroke({ width: Math.max(2.4, r * 0.085), color: metal, cap: 'round' });
    return;
  }

  if (weaponArchetype === 'lance') {
    const thrust = Math.sin(time * 3.1) * r * 0.06 * animAmp;
    // Balanced shaft + armored vamplate cone + needle lance head
    g.moveTo(-r * 0.18 + thrust, r * 0.20 + breathe)
      .lineTo(r * 0.92 + thrust, -r * 0.22 + breathe)
      .stroke({ width: Math.max(2.4, r * 0.085), color: metal, cap: 'round' });
    g.poly([
      r * 0.24 + thrust, -r * 0.06 + breathe,
      r * 0.46 + thrust, -r * 0.05 + breathe,
      r * 0.30 + thrust, r * 0.16 + breathe,
    ]).fill({ color: secondary }).stroke({ width: 1.2, color: trim });
    g.poly([
      r * 0.56 + thrust, -r * 0.15 + breathe,
      r * 1.12 + thrust, -r * 0.30 + breathe,
      r * 0.62 + thrust, -r * 0.01 + breathe,
    ]).fill({ color: INK.paper }).stroke({ width: 1.7, color: primary });
    // Trailing pennant ribbon under spearhead
    const wave = Math.sin(time * 4.4) * r * 0.05 * animAmp;
    g.moveTo(r * 0.62 + thrust, -r * 0.04 + breathe)
      .quadraticCurveTo(r * 0.50 + thrust, r * 0.12 + wave, r * 0.38 + thrust, r * 0.18 - wave)
      .stroke({ width: 2.0, color: secondary, cap: 'round' });
    return;
  }

  if (weaponArchetype === 'staff') {
    const bob = Math.sin(time * 3.6) * r * 0.045 * animAmp;
    const pulse = 0.86 + Math.sin(time * 4.4) * 0.14 * animAmp;
    const sx = r * 0.48;
    // Tall ornate staff shaft
    g.moveTo(sx, -r * 0.42 + breathe).lineTo(sx, r * 0.62)
      .stroke({ width: Math.max(2.4, r * 0.08), color: metal, cap: 'round' });
    // Crescent cradle finial
    g.arc(sx, -r * 0.52 + breathe, r * 0.18, 0.25, Math.PI - 0.25)
      .stroke({ width: 2.2, color: primary, cap: 'round' });
    // Levitating glowing crystal orb
    g.circle(sx, -r * 0.56 + breathe + bob, r * 0.14 * pulse)
      .fill({ color: secondary, alpha: 0.92 }).stroke({ width: 1.4, color: INK.paper });
    g.circle(sx, -r * 0.56 + breathe + bob, r * 0.22 * pulse)
      .stroke({ width: 1.1, color: secondary, alpha: 0.45 });
    return;
  }

  if (weaponArchetype === 'shield') {
    const brace = Math.sin(time * 2.4) * r * 0.03 * animAmp;
    // Massive sculpted forward tower/kite shield
    g.poly([
      r * 0.22 + brace, -r * 0.38 + breathe,
      r * 0.68 + brace, -r * 0.26 + breathe,
      r * 0.74 + brace, r * 0.28,
      r * 0.44 + brace, r * 0.60,
      r * 0.16 + brace, r * 0.34,
    ]).fill({ color: primary }).stroke({ width: 2.3, color: secondary });
    // Cross reinforcement + central sunlit diamond boss
    g.moveTo(r * 0.45 + brace, -r * 0.26 + breathe).lineTo(r * 0.45 + brace, r * 0.46)
      .stroke({ width: 2.0, color: secondary });
    g.moveTo(r * 0.24 + brace, r * 0.04 + breathe).lineTo(r * 0.66 + brace, r * 0.04 + breathe)
      .stroke({ width: 2.0, color: secondary });
    g.poly([
      r * 0.45 + brace, -r * 0.07 + breathe,
      r * 0.55 + brace, r * 0.04 + breathe,
      r * 0.45 + brace, r * 0.15 + breathe,
      r * 0.35 + brace, r * 0.04 + breathe,
    ]).fill({ color: hi }).stroke({ width: 1.2, color: INK.paper });
    return;
  }

  if (weaponArchetype === 'dual') {
    const swingA = Math.sin(time * 4.5) * r * 0.055 * animAmp;
    const swingB = -swingA;
    // Upper forward curved dagger
    g.poly([
      r * 0.22, -r * 0.02 + breathe,
      r * 0.94, -r * 0.38 + breathe + swingA,
      r * 0.76, -r * 0.10 + breathe + swingA * 0.6,
      r * 0.28, r * 0.08 + breathe,
    ]).fill({ color: INK.paper }).stroke({ width: 1.7, color: primary });
    // Lower agile off-hand short blade
    g.poly([
      r * 0.24, r * 0.24 + breathe,
      r * 0.86, r * 0.06 + breathe + swingB,
      r * 0.74, r * 0.24 + breathe + swingB * 0.6,
      r * 0.28, r * 0.32 + breathe,
    ]).fill({ color: secondary, alpha: 0.92 }).stroke({ width: 1.5, color: trim });
    return;
  }

  if (weaponArchetype === 'cannon') {
    const hum = Math.sin(time * 5.6) * r * 0.025 * animAmp;
    const charge = 0.86 + Math.sin(time * 6.2) * 0.14 * animAmp;
    // Heavy armored cannon barrel + cooling bands + glowing amber muzzle core
    g.roundRect(r * 0.18 - hum, -r * 0.18 + breathe, r * 0.72, r * 0.34, Math.max(4, r * 0.12))
      .fill({ color: metal }).stroke({ width: 1.8, color: trim });
    g.roundRect(r * 0.26 - hum, -r * 0.13 + breathe, r * 0.42, r * 0.24, Math.max(3, r * 0.08))
      .fill({ color: primary }).stroke({ width: 1.3, color: secondary });
    // Twin brass heat-vent ribs
    g.moveTo(r * 0.44 - hum, -r * 0.14 + breathe).lineTo(r * 0.44 - hum, r * 0.12 + breathe)
      .stroke({ width: 2.0, color: secondary });
    g.moveTo(r * 0.58 - hum, -r * 0.14 + breathe).lineTo(r * 0.58 - hum, r * 0.12 + breathe)
      .stroke({ width: 2.0, color: secondary });
    // Flared muzzle collar + pulsing charge core
    g.roundRect(r * 0.82 - hum, -r * 0.22 + breathe, r * 0.14, r * 0.42, 3)
      .fill({ color: secondary }).stroke({ width: 1.4, color: trim });
    g.circle(r * 0.94 - hum, -r * 0.01 + breathe, r * 0.10 * charge)
      .fill({ color: hi }).stroke({ width: 1.4, color: secondary });
    return;
  }

  // 'tome' — hovering open gilded grimoire + levitating rune sigils
  const floatY = Math.sin(time * 3.2) * r * 0.055 * animAmp;
  const bx = r * 0.64;
  const by = -r * 0.02 + breathe + floatY;
  // Open hardcover wings
  g.poly([
    bx - r * 0.24, by - r * 0.16,
    bx, by - r * 0.08,
    bx + r * 0.26, by - r * 0.16,
    bx + r * 0.22, by + r * 0.18,
    bx, by + r * 0.24,
    bx - r * 0.20, by + r * 0.18,
  ]).fill({ color: primary }).stroke({ width: 1.6, color: secondary });
  // Sunlit open paper leaves
  g.poly([
    bx - r * 0.19, by - r * 0.13,
    bx, by - r * 0.06,
    bx + r * 0.21, by - r * 0.13,
    bx + r * 0.18, by + r * 0.13,
    bx, by + r * 0.18,
    bx - r * 0.16, by + r * 0.13,
  ]).fill({ color: INK.paper }).stroke({ width: 1.1, color: trim, alpha: 0.7 });
  g.moveTo(bx, by - r * 0.06).lineTo(bx, by + r * 0.18)
    .stroke({ width: 1.2, color: secondary });
  // Rising floating golden rune sigil & arc above pages
  const runeY = by - r * 0.30 - Math.sin(time * 4.2) * r * 0.04 * animAmp;
  const sz = Math.max(3, r * 0.11);
  g.poly([bx, runeY - sz, bx + sz * 0.72, runeY, bx, runeY + sz, bx - sz * 0.72, runeY])
    .fill({ color: secondary, alpha: 0.92 }).stroke({ width: 1, color: INK.paper });
  g.arc(bx, by - r * 0.14, r * 0.26, -Math.PI * 0.85, -Math.PI * 0.15)
    .stroke({ width: 1.3, color: secondary, alpha: 0.68, cap: 'round' });
}

/**
 * Draw sculpted procedural character figure & weapon silhouette at (0, 0), facing +X (flipped via scale.x).
 */
function drawCharacterBody(g, pal, ch, radius, time, animAmp = 1) {
  const r = radius;
  const alive = ch.alive !== false;
  const primary = alive ? pal.primary : INK.muted;
  const secondary = alive ? pal.secondary : INK.line;
  const hi = alive ? pal.highlight : INK.paperSoft;
  const metal = alive ? (pal.metal ?? INK.secondary) : INK.line;
  const trim = alive ? pal.trim : INK.muted;
  const breathe = alive ? Math.sin(time * 2.8) * (r * 0.045) * animAmp : 0;
  const flutter = alive ? Math.sin(time * 4.4) * (r * 0.09) * animAmp : 0;

  // Back aura emblem halo behind shoulders
  if (alive) {
    g.circle(0, -r * 0.08 + breathe * 0.5, r * 0.66)
      .fill({ color: hi, alpha: 0.72 })
      .stroke({ width: 1.4, color: primary, alpha: 0.36 });
  }

  // Custom registered draw hook (if provided via registerActorVisual)
  if (typeof pal.draw === 'function') {
    pal.draw(g, { ...pal, primary, secondary, highlight: hi, metal, trim }, ch, r, time, animAmp);
  } else if (pal.motif === 'annolin') {
    // Flowing twin emerald wind ribbons streaming behind
    g.moveTo(-r * 0.1, -r * 0.25 + breathe)
      .quadraticCurveTo(-r * 0.62, -r * 0.5 + flutter, -r * 0.94, -r * 0.22 - flutter)
      .quadraticCurveTo(-r * 0.54, -r * 0.04 + flutter * 0.5, -r * 0.14, r * 0.04 + breathe)
      .fill({ color: secondary, alpha: 0.72 });
    g.moveTo(-r * 0.08, -r * 0.08 + breathe)
      .quadraticCurveTo(-r * 0.56, r * 0.18 - flutter, -r * 0.88, r * 0.42 + flutter * 0.6)
      .quadraticCurveTo(-r * 0.44, r * 0.44, -r * 0.06, r * 0.2 + breathe)
      .fill({ color: primary, alpha: 0.58 });

    // Sculpted mantle torso
    g.poly([
      0, -r * 0.32 + breathe,
      r * 0.34, r * 0.14 + breathe,
      r * 0.22, r * 0.62,
      -r * 0.26, r * 0.62,
      -r * 0.34, r * 0.12 + breathe,
    ]).fill({ color: primary }).stroke({ width: 1.6, color: INK.paper });

    // Inner bright jade chevron collar
    g.poly([
      0, -r * 0.22 + breathe,
      r * 0.18, r * 0.12 + breathe,
      0, r * 0.34 + breathe,
      -r * 0.16, r * 0.12 + breathe,
    ]).fill({ color: hi });

    // Sculpted head & hair-crest
    g.circle(r * 0.03, -r * 0.48 + breathe, r * 0.21)
      .fill({ color: INK.paper }).stroke({ width: 1.8, color: trim });
    g.poly([
      -r * 0.18, -r * 0.52 + breathe,
      r * 0.06, -r * 0.76 + breathe,
      r * 0.26, -r * 0.54 + breathe,
      r * 0.04, -r * 0.6 + breathe,
    ]).fill({ color: primary });

    // Sweeping emerald-gold wind blade held forward
    const bladeTilt = Math.sin(time * 2.8) * 0.05 * animAmp;
    g.moveTo(r * 0.18, r * 0.16 + breathe)
      .quadraticCurveTo(r * 0.62, -r * 0.14 + bladeTilt * r, r * 0.96, -r * 0.56 + breathe)
      .quadraticCurveTo(r * 0.74, 0.04 * r, r * 0.28, r * 0.28 + breathe)
      .fill({ color: INK.paper }).stroke({ width: 1.8, color: primary });
    g.moveTo(r * 0.24, r * 0.18 + breathe)
      .lineTo(r * 0.88, -r * 0.46 + breathe)
      .stroke({ width: 1.6, color: metal, cap: 'round' });
  } else if (pal.motif === 'lake' || pal.motif === 'grolina') {
    const isLance = pal.motif === 'grolina';
    // Swept tactical cape / wing fins
    g.poly([
      -r * 0.12, -r * 0.26 + breathe,
      -r * 0.86, isLance ? -r * 0.48 + flutter : -r * 0.1 + flutter * 0.5,
      -r * 0.62, r * 0.44,
      -r * 0.14, r * 0.34,
    ]).fill({ color: secondary, alpha: 0.78 }).stroke({ width: 1.4, color: primary });

    // Angular tactical torso
    g.poly([
      -r * 0.28, -r * 0.24 + breathe,
      r * 0.34, -r * 0.18 + breathe,
      r * 0.26, r * 0.62,
      -r * 0.24, r * 0.62,
    ]).fill({ color: primary }).stroke({ width: 1.6, color: INK.paper });

    // WAA brass tactical cross-strap
    g.moveTo(-r * 0.22, -r * 0.16 + breathe).lineTo(r * 0.24, r * 0.44)
      .stroke({ width: 3.2, color: secondary });
    g.circle(r * 0.04, r * 0.1 + breathe, r * 0.11).fill({ color: INK.paper }).stroke({ width: 1.5, color: secondary });

    // Head with tactical visor crest
    g.circle(r * 0.04, -r * 0.48 + breathe, r * 0.2)
      .fill({ color: INK.paper }).stroke({ width: 1.8, color: trim });
    g.roundRect(-r * 0.02, -r * 0.54 + breathe, r * 0.28, r * 0.11, 3).fill({ color: secondary });

    if (isLance) {
      // Twin needle-lance pointing aggressively forward
      g.poly([
        r * 0.1, -r * 0.02 + breathe,
        r * 1.05, -r * 0.22 + breathe,
        r * 0.14, r * 0.14 + breathe,
      ]).fill({ color: INK.paper }).stroke({ width: 1.8, color: primary });
      g.moveTo(r * 0.14, r * 0.05 + breathe).lineTo(r * 0.96, -r * 0.2 + breathe)
        .stroke({ width: 1.8, color: secondary });
    } else {
      // Forward curved assault saber
      g.poly([
        r * 0.24, r * 0.18 + breathe,
        r * 0.92, -r * 0.38 + breathe,
        r * 0.78, -r * 0.04 + breathe,
        r * 0.3, r * 0.28 + breathe,
      ]).fill({ color: INK.paper }).stroke({ width: 1.8, color: primary });
      g.moveTo(r * 0.28, r * 0.16 + breathe).lineTo(r * 0.84, -r * 0.3 + breathe)
        .stroke({ width: 2, color: secondary });
    }
  } else if (pal.motif === 'erkes') {
    // Heavy armored hexagonal pauldron & reactor torso
    g.poly(drawPolygon(g, 0, r * 0.1 + breathe, r * 0.48, 6, Math.PI / 6))
      .fill({ color: primary }).stroke({ width: 2, color: INK.paper });
    // Glowing pure-energy reactor core in chest
    const corePulse = 0.85 + Math.sin(time * 5.2) * 0.15 * animAmp;
    g.poly(drawPolygon(g, r * 0.04, r * 0.08 + breathe, r * 0.2 * corePulse, 6, 0))
      .fill({ color: secondary }).stroke({ width: 1.5, color: INK.paper });
    // Armored head
    g.poly(drawPolygon(g, 0, -r * 0.46 + breathe, r * 0.22, 6, 0))
      .fill({ color: INK.paper }).stroke({ width: 2, color: trim });
    // Heavy pressurized impact hammer/gauntlet forward
    g.roundRect(r * 0.34, -r * 0.34 + breathe, r * 0.36, r * 0.56, 6)
      .fill({ color: metal }).stroke({ width: 1.8, color: secondary });
    g.roundRect(r * 0.42, -r * 0.24 + breathe, r * 0.2, r * 0.36, 4)
      .fill({ color: secondary, alpha: 0.85 });
  } else if (pal.motif === 'cen_yao') {
    // Rotating brass surveyor astrolabe halo behind Cen Yao
    const spin = time * 0.65;
    g.circle(0, -r * 0.14 + breathe, r * 0.68).stroke({ width: 1.3, color: secondary, alpha: 0.72 });
    for (let i = 0; i < 4; i++) {
      const a = spin + (i * Math.PI) / 2;
      g.moveTo(Math.cos(a) * r * 0.54, -r * 0.14 + breathe + Math.sin(a) * r * 0.54)
        .lineTo(Math.cos(a) * r * 0.74, -r * 0.14 + breathe + Math.sin(a) * r * 0.74)
        .stroke({ width: 1.6, color: secondary });
    }
    // Surveyor cloak torso
    g.poly([
      -r * 0.1, -r * 0.3 + breathe,
      r * 0.28, -r * 0.12 + breathe,
      r * 0.32, r * 0.62,
      -r * 0.36, r * 0.62,
      -r * 0.32, r * 0.02 + breathe,
    ]).fill({ color: primary }).stroke({ width: 1.6, color: INK.paper });
    g.circle(0, -r * 0.48 + breathe, r * 0.2)
      .fill({ color: INK.paper }).stroke({ width: 1.8, color: trim });
    // Long precision sighting rule / rangefinder lance
    g.moveTo(-r * 0.2, r * 0.12 + breathe).lineTo(r * 1.02, -r * 0.24 + breathe)
      .stroke({ width: 3.4, color: secondary, cap: 'round' });
    g.circle(r * 0.78, -r * 0.15 + breathe, r * 0.13)
      .fill({ color: INK.paper, alpha: 0.9 }).stroke({ width: 1.6, color: primary });
  } else if (pal.motif === 'wen_sheng') {
    // Theatrical spotlight prism rays behind
    g.poly([
      0, -r * 0.78 + breathe,
      r * 0.64, r * 0.58,
      -r * 0.64, r * 0.58,
    ]).fill({ color: secondary, alpha: 0.18 });
    // Dramatic pleated cloak
    g.poly([
      0, -r * 0.3 + breathe,
      r * 0.38, r * 0.08 + breathe,
      r * 0.44, r * 0.62,
      -r * 0.42, r * 0.62,
      -r * 0.36, r * 0.04 + breathe,
    ]).fill({ color: primary }).stroke({ width: 1.6, color: INK.paper });
    // Golden curtain sash
    g.poly([
      -r * 0.18, -r * 0.16 + breathe,
      r * 0.22, -r * 0.04 + breathe,
      r * 0.12, r * 0.52,
      -r * 0.22, r * 0.44,
    ]).fill({ color: secondary, alpha: 0.85 });
    // Head + half-theatre mask crest
    g.circle(0, -r * 0.48 + breathe, r * 0.21)
      .fill({ color: INK.paper }).stroke({ width: 1.8, color: trim });
    g.poly([
      0, -r * 0.64 + breathe,
      r * 0.22, -r * 0.54 + breathe,
      r * 0.18, -r * 0.36 + breathe,
      0, -r * 0.42 + breathe,
    ]).fill({ color: secondary });
    // Stage baton / curtain pistol forward
    g.moveTo(r * 0.16, r * 0.08 + breathe).lineTo(r * 0.92, -r * 0.18 + breathe)
      .stroke({ width: 3.2, color: trim, cap: 'round' });
    g.circle(r * 0.92, -r * 0.18 + breathe, r * 0.08).fill({ color: secondary });
  } else if (pal.motif === 'iron_vanguard') {
    // Broad armored torso & twin pauldron plates
    g.poly([
      -r * 0.42, -r * 0.24 + breathe,
      r * 0.26, -r * 0.24 + breathe,
      r * 0.22, r * 0.62,
      -r * 0.36, r * 0.62,
    ]).fill({ color: primary }).stroke({ width: 1.8, color: INK.paper });
    g.roundRect(-r * 0.48, -r * 0.3 + breathe, r * 0.32, r * 0.22, 5)
      .fill({ color: metal }).stroke({ width: 1.5, color: secondary });
    // Visored knight helm
    g.poly(drawPolygon(g, -r * 0.04, -r * 0.48 + breathe, r * 0.22, 6, Math.PI / 6))
      .fill({ color: INK.paper }).stroke({ width: 1.8, color: trim });
    g.moveTo(-r * 0.14, -r * 0.48 + breathe).lineTo(r * 0.14, -r * 0.48 + breathe)
      .stroke({ width: 2.2, color: primary });
    // Massive hexagonal tower shield forward
    g.poly([
      r * 0.22, -r * 0.42 + breathe,
      r * 0.66, -r * 0.28 + breathe,
      r * 0.72, r * 0.32,
      r * 0.42, r * 0.64,
      r * 0.16, r * 0.38,
    ]).fill({ color: primary }).stroke({ width: 2.4, color: secondary });
    g.moveTo(r * 0.44, -r * 0.28 + breathe).lineTo(r * 0.44, r * 0.44)
      .stroke({ width: 2.2, color: secondary });
    g.moveTo(r * 0.26, r * 0.06 + breathe).lineTo(r * 0.62, r * 0.06 + breathe)
      .stroke({ width: 2.2, color: secondary });
  } else if (pal.motif === 'crimson_duelist') {
    // Flowing crimson duelist cape streaming back
    g.moveTo(-r * 0.08, -r * 0.28 + breathe)
      .quadraticCurveTo(-r * 0.66, -r * 0.34 + flutter, -r * 0.92, r * 0.32 - flutter * 0.6)
      .lineTo(-r * 0.24, r * 0.48)
      .fill({ color: primary, alpha: 0.78 }).stroke({ width: 1.4, color: secondary });
    // Slim fencing coat
    g.poly([
      -r * 0.22, -r * 0.28 + breathe,
      r * 0.28, -r * 0.18 + breathe,
      r * 0.2, r * 0.62,
      -r * 0.26, r * 0.62,
    ]).fill({ color: primary }).stroke({ width: 1.6, color: INK.paper });
    g.poly([
      0, -r * 0.22 + breathe,
      r * 0.14, r * 0.12 + breathe,
      0, r * 0.26 + breathe,
      -r * 0.12, r * 0.12 + breathe,
    ]).fill({ color: secondary });
    // Plumed head
    g.circle(r * 0.02, -r * 0.48 + breathe, r * 0.2)
      .fill({ color: INK.paper }).stroke({ width: 1.8, color: trim });
    g.moveTo(-r * 0.1, -r * 0.64 + breathe)
      .quadraticCurveTo(-r * 0.42, -r * 0.84 + flutter * 0.5, -r * 0.58, -r * 0.52 + flutter * 0.4)
      .stroke({ width: 2.8, color: secondary, cap: 'round' });
    // Long gilded fencing rapier thrusting forward
    g.circle(r * 0.32, r * 0.02 + breathe, r * 0.13)
      .fill({ color: hi }).stroke({ width: 1.8, color: secondary });
    g.moveTo(r * 0.36, r * 0.01 + breathe).lineTo(r * 1.08, -r * 0.26 + breathe)
      .stroke({ width: 2.4, color: trim, cap: 'round' });
    g.moveTo(r * 0.4, -r * 0.01 + breathe).lineTo(r * 1.04, -r * 0.24 + breathe)
      .stroke({ width: 1.2, color: secondary, cap: 'round' });
  } else if (pal.motif === 'drill_scout') {
    // Wind-swept scarf
    g.moveTo(-r * 0.1, -r * 0.28 + breathe)
      .quadraticCurveTo(-r * 0.54, -r * 0.2 + flutter, -r * 0.8, r * 0.04 - flutter)
      .stroke({ width: 4.5, color: secondary, cap: 'round' });
    // Agile crouching scout silhouette
    g.poly([
      -r * 0.26, -r * 0.2 + breathe,
      r * 0.3, -r * 0.12 + breathe,
      r * 0.24, r * 0.6,
      -r * 0.28, r * 0.6,
    ]).fill({ color: primary }).stroke({ width: 1.5, color: INK.paper });
    // Peaked hood + head
    g.circle(r * 0.04, -r * 0.44 + breathe, r * 0.19)
      .fill({ color: INK.paper }).stroke({ width: 1.7, color: trim });
    g.poly([
      -r * 0.28, -r * 0.38 + breathe,
      -r * 0.04, -r * 0.72 + breathe,
      r * 0.22, -r * 0.5 + breathe,
      -r * 0.02, -r * 0.54 + breathe,
    ]).fill({ color: primary });
    // Twin forward recon daggers
    g.moveTo(r * 0.24, r * 0.04 + breathe).lineTo(r * 0.84, -r * 0.26 + breathe)
      .stroke({ width: 2.4, color: trim, cap: 'round' });
    g.moveTo(r * 0.26, r * 0.24 + breathe).lineTo(r * 0.76, r * 0.1 + breathe)
      .stroke({ width: 2.2, color: secondary, cap: 'round' });
  } else if (pal.motif === 'drill_medic') {
    // Sunlit medical cross halo behind shoulders
    g.circle(0, -r * 0.12 + breathe, r * 0.52).stroke({ width: 1.4, color: primary, alpha: 0.42 });
    g.roundRect(-r * 0.1, -r * 0.32 + breathe, r * 0.2, r * 0.42, 3).fill({ color: secondary, alpha: 0.26 });
    g.roundRect(-r * 0.21, -r * 0.21 + breathe, r * 0.42, r * 0.2, 3).fill({ color: secondary, alpha: 0.26 });
    // Field coat
    g.poly([
      -r * 0.28, -r * 0.26 + breathe,
      r * 0.28, -r * 0.26 + breathe,
      r * 0.34, r * 0.62,
      -r * 0.34, r * 0.62,
    ]).fill({ color: primary }).stroke({ width: 1.6, color: INK.paper });
    // Crisp white cross badge on chest
    g.roundRect(-r * 0.05, -r * 0.04 + breathe, r * 0.1, r * 0.28, 2).fill({ color: INK.paper });
    g.roundRect(-r * 0.14, r * 0.05 + breathe, r * 0.28, r * 0.1, 2).fill({ color: INK.paper });
    g.circle(0, -r * 0.48 + breathe, r * 0.2)
      .fill({ color: INK.paper }).stroke({ width: 1.8, color: trim });
    // Glowing alchemist lantern staff forward
    g.moveTo(r * 0.46, -r * 0.42 + breathe).lineTo(r * 0.46, r * 0.6)
      .stroke({ width: 2.6, color: metal, cap: 'round' });
    const glow = 0.85 + Math.sin(time * 4.2) * 0.15 * animAmp;
    g.circle(r * 0.46, -r * 0.46 + breathe, r * 0.15 * glow)
      .fill({ color: secondary, alpha: 0.88 }).stroke({ width: 1.4, color: INK.paper });
  } else if (pal.motif === 'drill_captain') {
    // Tall fluttering command banner behind
    g.moveTo(-r * 0.48, -r * 0.78).lineTo(-r * 0.48, r * 0.62)
      .stroke({ width: 2.8, color: metal, cap: 'round' });
    g.poly([
      -r * 0.48, -r * 0.74,
      -r * 0.96, -r * 0.56 + flutter * 0.7,
      -r * 0.82, -r * 0.24 + flutter * 0.5,
      -r * 0.48, -r * 0.34,
    ]).fill({ color: secondary, alpha: 0.88 }).stroke({ width: 1.4, color: primary });
    // Armored commander torso
    g.poly([
      -r * 0.32, -r * 0.28 + breathe,
      r * 0.34, -r * 0.22 + breathe,
      r * 0.28, r * 0.62,
      -r * 0.3, r * 0.62,
    ]).fill({ color: primary }).stroke({ width: 1.8, color: INK.paper });
    g.poly([
      -r * 0.22, -r * 0.2 + breathe,
      r * 0.24, -r * 0.16 + breathe,
      0, r * 0.26 + breathe,
    ]).fill({ color: secondary });
    // Head + golden command crown crest
    g.circle(0, -r * 0.48 + breathe, r * 0.21)
      .fill({ color: INK.paper }).stroke({ width: 1.8, color: trim });
    g.poly([
      -r * 0.22, -r * 0.62 + breathe,
      -r * 0.12, -r * 0.82 + breathe,
      0, -r * 0.68 + breathe,
      r * 0.12, -r * 0.82 + breathe,
      r * 0.22, -r * 0.62 + breathe,
    ]).fill({ color: secondary });
    // Forward halberd
    g.moveTo(r * 0.16, r * 0.38 + breathe).lineTo(r * 0.94, -r * 0.52 + breathe)
      .stroke({ width: 3, color: trim, cap: 'round' });
    g.poly([
      r * 0.72, -r * 0.28 + breathe,
      r * 1.02, -r * 0.62 + breathe,
      r * 0.96, -r * 0.18 + breathe,
    ]).fill({ color: INK.paper }).stroke({ width: 1.8, color: primary });
  } else if (pal.motif === 'drill_engine') {
    // Towering heavy siege mech chassis with twin pulsing furnace pistons
    const piston = Math.sin(time * 5.6) * (r * 0.05) * animAmp;
    // Back steam/piston stacks
    g.roundRect(-r * 0.58, -r * 0.66 - piston, r * 0.22, r * 0.48, 4)
      .fill({ color: metal }).stroke({ width: 1.6, color: secondary });
    g.roundRect(r * 0.36, -r * 0.62 + piston, r * 0.22, r * 0.44, 4)
      .fill({ color: metal }).stroke({ width: 1.6, color: secondary });
    // Massive octagonal armored torso
    g.poly(drawPolygon(g, 0, r * 0.06 + breathe * 0.6, r * 0.58, 8, Math.PI / 8))
      .fill({ color: primary }).stroke({ width: 2.2, color: INK.paper });
    // Inner armored furnace core
    const glow = 0.88 + Math.sin(time * 6.2) * 0.12 * animAmp;
    g.poly(drawPolygon(g, r * 0.04, r * 0.08 + breathe * 0.6, r * 0.24 * glow, 6, 0))
      .fill({ color: secondary }).stroke({ width: 1.6, color: INK.paper });
    // Armored optic turret head
    g.roundRect(-r * 0.26, -r * 0.62 + breathe * 0.6, r * 0.54, r * 0.28, 6)
      .fill({ color: metal }).stroke({ width: 1.8, color: trim });
    g.roundRect(-r * 0.04, -r * 0.54 + breathe * 0.6, r * 0.28, r * 0.12, 3)
      .fill({ color: secondary });
    // Heavy forward battering ram arm
    g.roundRect(r * 0.42, -r * 0.18 + breathe * 0.6, r * 0.48, r * 0.42, 7)
      .fill({ color: primary }).stroke({ width: 2, color: secondary });
    g.roundRect(r * 0.68, -r * 0.1 + breathe * 0.6, r * 0.16, r * 0.26, 3)
      .fill({ color: secondary });
  } else {
    // Rich deterministic archetype-driven silhouette for unlimited future roster!
    const spec = pal.weaponArchetype ? pal : resolveInfiniteActorSpec(ch, pal.side || 1);
    const sr = r * Math.max(0.92, Math.min(1.12, spec.silhouetteScale || 1));
    const sBreathe = alive ? Math.sin(time * 2.8) * (sr * 0.045) * animAmp : 0;
    const sFlutter = alive ? Math.sin(time * 4.4) * (sr * 0.09) * animAmp : 0;
    const rankStr = String(ch.rank || spec.rank || 'NORMAL').toUpperCase();
    const rankTier =
      rankStr === 'EMPOWERED_BOSS' ? 3 :
      rankStr === 'BOSS' ? 2 :
      rankStr === 'ELITE' ? 1 : (spec.rankTier || 0);

    if (alive) {
      drawArchetypeAura(g, spec.auraMotif, primary, secondary, hi, metal, sr, time, sBreathe, sFlutter, animAmp);
    }
    drawArchetypeMantle(g, spec.mantleStyle, primary, secondary, hi, metal, sr, sBreathe, sFlutter);
    drawArchetypeHeadAndCrest(
      g, spec.crestShape, primary, secondary, hi, metal, trim, sr, sBreathe, sFlutter, rankTier, spec.crestRings || 1, time
    );
    drawArchetypeWeapon(g, spec.weaponArchetype, primary, secondary, hi, metal, trim, sr, time, sBreathe, animAmp);
  }

  if (!alive) {
    // Gentle diagonal fracture line for fallen unit (zero black!)
    g.moveTo(-r * 0.55, -r * 0.55).lineTo(r * 0.55, r * 0.55)
      .stroke({ width: 2.2, color: 0xcf4932, alpha: 0.65 });
  }
}

/**
 * Draw living, animated status visuals right around the character figure!
 */
function drawStatusAuras(g, ch, radius, time) {
  if (ch.alive === false) return;
  const statuses = ch.statuses || {};
  const r = radius;

  // 涡流: Swirling emerald cyclone ribbons whose speed & density scale with stacks
  const vortex = statuses['涡流'] || 0;
  if (vortex > 0) {
    const col = STATUS_COLORS['涡流'];
    const rings = Math.min(3, 1 + Math.floor(vortex / 2));
    const speed = 1.8 + vortex * 0.35;
    for (let i = 0; i < rings; i++) {
      const rr = r * (0.76 + i * 0.15);
      const a0 = time * speed * (i % 2 === 0 ? 1 : -0.85) + i * 2.1;
      const a1 = a0 + Math.PI * 0.72;
      g.arc(0, 0, rr, a0, a1).stroke({ width: 2.2 - i * 0.35, color: col, alpha: 0.78 - i * 0.12, cap: 'round' });
      const tx = Math.cos(a1) * rr;
      const ty = Math.sin(a1) * rr;
      g.circle(tx, ty, 3.2).fill({ color: col, alpha: 0.9 });
    }
  }

  // 充能: Orbiting jade-gold energy arcs & crackling diamond nodes
  const charge = statuses['充能'] || 0;
  if (charge > 0) {
    const col = STATUS_COLORS['充能'];
    const nodes = Math.min(6, Math.max(2, Math.ceil(charge / 2)));
    for (let i = 0; i < nodes; i++) {
      const a = time * 2.3 + (i * Math.PI * 2) / nodes;
      const ox = Math.cos(a) * r * 0.9;
      const oy = Math.sin(a) * r * 0.56;
      g.poly([ox, oy - 4.5, ox + 3.5, oy, ox, oy + 4.5, ox - 3.5, oy])
        .fill({ color: col, alpha: 0.88 });
    }
  }

  // 纯能: Orbiting glowing hexagonal prisms (golden-amber flare when >= 3)
  const pure = statuses['纯能'] || 0;
  if (pure > 0) {
    const col = pure >= 3 ? 0xd48e1a : STATUS_COLORS['纯能'];
    const count = Math.min(5, pure);
    for (let i = 0; i < count; i++) {
      const a = -time * 1.9 + (i * Math.PI * 2) / count;
      const ox = Math.cos(a) * r * 0.84;
      const oy = Math.sin(a) * r * 0.72 - r * 0.06;
      g.poly(drawPolygon(g, ox, oy, 5.2, 6, time)).fill({ color: col, alpha: 0.9 }).stroke({ width: 1, color: INK.paper });
    }
  }

  // 校准: Precision rotating golden sighting rings & crosshair ticks
  const calib = statuses['校准'] || 0;
  if (calib > 0) {
    const col = STATUS_COLORS['校准'];
    for (let i = 0; i < Math.min(3, calib); i++) {
      const rr = r * (0.72 + i * 0.14);
      g.circle(0, -r * 0.08, rr).stroke({ width: 1.4, color: col, alpha: 0.65 - i * 0.12 });
    }
    const rot = time * 0.9;
    for (let k = 0; k < 4; k++) {
      const a = rot + (k * Math.PI) / 2;
      g.moveTo(Math.cos(a) * r * 0.64, -r * 0.08 + Math.sin(a) * r * 0.64)
        .lineTo(Math.cos(a) * r * 1.04, -r * 0.08 + Math.sin(a) * r * 1.04)
        .stroke({ width: 1.7, color: col, alpha: 0.85 });
    }
  }

  // 烧伤: Rising vermilion-amber embers
  const burn = statuses['烧伤'] || 0;
  if (burn > 0) {
    const col = STATUS_COLORS['烧伤'];
    const count = Math.min(6, 2 + Math.ceil(burn / 2));
    for (let i = 0; i < count; i++) {
      const phase = (time * 1.3 + i * 0.27) % 1;
      const ex = Math.sin(i * 2.4 + time * 3) * r * 0.56;
      const ey = r * 0.52 - phase * r * 1.25;
      const sz = (1 - phase) * 5.2 + 1.5;
      g.poly([ex, ey - sz, ex + sz * 0.65, ey, ex, ey + sz * 0.7, ex - sz * 0.65, ey])
        .fill({ color: col, alpha: (1 - phase) * 0.88 });
    }
  }

  // 裂血: Pulsing crimson thorns / burst ring
  const bleed = statuses['裂血'] || 0;
  if (bleed > 0) {
    const col = STATUS_COLORS['裂血'];
    const burst = ch.bleed_burst;
    const count = burst ? 8 : Math.min(5, Math.max(2, bleed));
    for (let i = 0; i < count; i++) {
      const a = time * (burst ? 3.2 : 1.2) + (i * Math.PI * 2) / count;
      const rr = r * (burst ? 0.94 + Math.sin(time * 9 + i) * 0.06 : 0.82);
      const bx = Math.cos(a) * rr;
      const by = Math.sin(a) * rr;
      g.poly([bx, by - 4.5, bx + 3, by, bx, by + 4.5, bx - 3, by]).fill({ color: col, alpha: burst ? 0.95 : 0.72 });
    }
  }

  // 呼吸: Expanding soft teal breath mist ring
  const breath = statuses['呼吸'] || 0;
  if (breath > 0) {
    const ph = (time * 0.9) % 1;
    g.circle(0, 0, r * (0.62 + ph * 0.45))
      .stroke({ width: 2, color: STATUS_COLORS['呼吸'], alpha: (1 - ph) * 0.65 });
  }

  // 强壮 / 虚弱
  if ((statuses['强壮'] || 0) > 0) {
    const up = (time * 1.1) % 1;
    const cy = r * 0.2 - up * r * 0.9;
    g.moveTo(-r * 0.26, cy + 6).lineTo(0, cy - 5).lineTo(r * 0.26, cy + 6)
      .stroke({ width: 2.2, color: STATUS_COLORS['强壮'], alpha: (1 - up) * 0.82, cap: 'round' });
  }
  if ((statuses['致命失衡'] || 0) > 0 || (statuses['失衡'] || 0) >= 6) {
    const fatal = (statuses['致命失衡'] || 0) > 0;
    const col = fatal ? STATUS_COLORS['致命失衡'] : STATUS_COLORS['失衡'];
    const jitter = Math.sin(time * 24) * (fatal ? 2.5 : 1.0);
    g.poly(drawPolygon(g, jitter, -r * 0.78, fatal ? 11 : 8, 4, Math.PI / 4))
      .fill({ color: col, alpha: fatal ? 0.82 : 0.35 })
      .stroke({ width: 1.8, color: col });
  }
}

/**
 * Draw warm focus highlight aura & sunlit rising motes when a player hovers this fighter's hand card.
 */
function drawFocusHighlightAura(g, pal, radius, time, focus) {
  const r = radius;
  const pulse = 1 + Math.sin(time * 5.0) * 0.045;
  const cy = -r * 0.06;

  // Radiant double spotlight aura behind focused owner
  g.circle(0, cy, r * (0.92 + focus * 0.14) * pulse)
    .fill({ color: pal.highlight, alpha: focus * 0.44 })
    .stroke({ width: 2.2, color: pal.secondary, alpha: focus * 0.86 });

  const spin = time * 1.25;
  g.arc(0, cy, r * 1.08 * pulse, spin, spin + Math.PI * 0.78)
    .stroke({ width: 2.4, color: pal.primary, alpha: focus * 0.88, cap: 'round' });
  g.arc(0, cy, r * 1.08 * pulse, spin + Math.PI, spin + Math.PI * 1.78)
    .stroke({ width: 2.0, color: INK.gold, alpha: focus * 0.82, cap: 'round' });

  // 4 rising sunlit focus motes
  for (let i = 0; i < 4; i++) {
    const ph = (time * 1.15 + i * 0.25) % 1;
    const mx = Math.cos(i * 1.57 + time * 1.4) * r * 0.72;
    const my = r * 0.50 - ph * r * 1.28;
    const sz = (1 - ph * 0.55) * Math.max(2.6, r * 0.11);
    g.poly([mx, my - sz, mx + sz * 0.7, my, mx, my + sz, mx - sz * 0.7, my])
      .fill({ color: i % 2 === 0 ? pal.secondary : INK.gold, alpha: focus * (1 - ph) * 0.92 });
  }
}

/**
 * Draw real concentric Shield Domes around the fighter ONLY when shield > 0!
 */
function drawShieldDomes(g, ch, radius, time) {
  const sh = ch.shields || {};
  const r = radius;
  const pulse = 1 + Math.sin(time * 3.6) * 0.03;

  if ((sh.normal || 0) > 0) {
    const st = SHIELD_STYLE.normal;
    const pts = drawPolygon(g, 0, -r * 0.04, r * 0.98 * pulse, 6, time * 0.22);
    g.poly(pts).fill({ color: st.color, alpha: 0.11 }).stroke({ width: 2.2, color: st.color, alpha: 0.82 });
  }
  if ((sh.reinforced || 0) > 0) {
    const st = SHIELD_STYLE.reinforced;
    const rr = r * 1.1 * pulse;
    g.arc(0, -r * 0.04, rr, -Math.PI * 0.68, Math.PI * 0.68)
      .stroke({ width: 3.4, color: st.color, alpha: 0.88, cap: 'round' });
    g.arc(0, -r * 0.04, rr, Math.PI * 0.82, Math.PI * 1.18)
      .stroke({ width: 2.4, color: st.color, alpha: 0.58, cap: 'round' });
  }
  if ((sh.concept || 0) > 0) {
    const st = SHIELD_STYLE.concept;
    const pts = drawPolygon(g, 0, -r * 0.04, r * 1.22 * pulse, 4, Math.PI / 4 - time * 0.35);
    g.poly(pts).fill({ color: st.color, alpha: 0.09 }).stroke({ width: 2.4, color: st.color, alpha: 0.9 });
  }
}

/**
 * Create a live animated stage actor container for a fighter.
 */
export function createCharacterActor(ch, side, { radius = 38 } = {}) {
  const root = new PIXI.Container();
  const pal = actorPalette(ch, side);
  const facing = side === 1 ? 1 : -1;
  const useCustomDrawHook = typeof pal.draw === 'function';

  const floorG = new PIXI.Graphics();
  const auraG = new PIXI.Graphics();
  const afterimageG = new PIXI.Graphics();
  const bodyHolder = new PIXI.Container();
  const svgRig = useCustomDrawHook ? null : createSkeletalSvgRig(ch, pal, radius);
  const bodyG = new PIXI.Graphics();
  const shieldG = new PIXI.Graphics();
  const flareG = new PIXI.Graphics();

  if (svgRig) {
    bodyHolder.addChild(svgRig);
  }
  bodyHolder.addChild(bodyG);
  bodyHolder.scale.x = facing;
  afterimageG.scale.x = facing;

  root.addChild(floorG, auraG, afterimageG, bodyHolder, shieldG, flareG);

  root._actorData = { ch, side, pal, radius, facing, svgRig };

  let lastTime = null;
  let focusSmooth = 0;
  let dimSmooth = 0;
  let manualFocus = 0;
  let manualDim = 0;

  root.setFocusState = ({ focusBoost = 0, dimFactor = 0 } = {}) => {
    manualFocus = typeof focusBoost === 'boolean' ? (focusBoost ? 1 : 0) : clamp01(Number(focusBoost) || 0);
    manualDim = typeof dimFactor === 'boolean' ? (dimFactor ? 1 : 0) : clamp01(Number(dimFactor) || 0);
  };

  /**
   * Return the stage-space coordinates of any named bone (`bone_weapon`, `bone_head`, `bone_torso`, etc.)
   * so FX hooks (PR #2) can bind trails, flares, and projectiles directly to skeletal joints.
   */
  root.getBoneWorldPos = (boneId = 'bone_torso') => {
    const local = svgRig ? svgRig.getBoneLocalPos(boneId) : { x: 0, y: -radius * 0.1 };
    const sx = bodyHolder.scale.x || facing;
    const sy = bodyHolder.scale.y || 1;
    return {
      x: root.x + bodyHolder.x + local.x * sx,
      y: root.y + bodyHolder.y + local.y * sy,
    };
  };

  root.tick = (time, motion, liveCh) => {
    const cur = liveCh || ch;
    const m = motion || {};
    const lunge = m.lunge || 0;
    const recoil = m.recoil || 0;
    const evade = m.evade || 0;
    const hitFlash = m.hitFlash || 0;
    const healGlow = m.healGlow || 0;
    const passiveFlare = m.passiveFlare || 0;

    // Optional highlight / dim state for 10v10 card-hover intent focusing
    const rawFocus = m.focusBoost !== undefined ? m.focusBoost : (m.highlight !== undefined ? m.highlight : manualFocus);
    const rawDim = m.dimFactor !== undefined ? m.dimFactor : (m.dim !== undefined ? m.dim : manualDim);
    const targetFocus = typeof rawFocus === 'boolean' ? (rawFocus ? 1 : 0) : clamp01(Number(rawFocus) || 0);
    const targetDimRaw = typeof rawDim === 'boolean' ? (rawDim ? 1 : 0) : clamp01(Number(rawDim) || 0);
    const targetDim = targetDimRaw * (1 - targetFocus);

    if (lastTime === null || time <= lastTime || (time - lastTime) >= 0.5) {
      focusSmooth = targetFocus;
      dimSmooth = targetDim;
    } else {
      const dt = time - lastTime;
      const k = 1 - Math.exp(-dt * 14);
      focusSmooth += (targetFocus - focusSmooth) * k;
      dimSmooth += (targetDim - dimSmooth) * k;
    }
    lastTime = time;

    const r = radius;
    const theme = SIDE_THEME[side] || SIDE_THEME[1];
    const alive = cur.alive !== false;

    // Kinetic offset (lunge toward enemy, recoil backward, evade wind-dash) + subtle focus lift
    const offsetX = facing * (lunge * 34 - recoil * 22 - evade * 26);
    const tilt = facing * (lunge * 0.14 - recoil * 0.18);
    const liftY = alive ? -focusSmooth * Math.min(4.5, r * 0.14) : 0;
    const scaleMag = 1 + (alive ? focusSmooth * 0.065 : 0) - dimSmooth * 0.03;
    const animAmp = 1 - dimSmooth * 0.55;

    bodyHolder.position.set(offsetX, liftY);
    bodyHolder.scale.set(facing * scaleMag, scaleMag);
    bodyHolder.rotation = tilt;
    bodyHolder.alpha = 1 - dimSmooth * 0.42;

    floorG.alpha = 1 - dimSmooth * 0.42;
    auraG.alpha = 1 - dimSmooth * 0.52;
    shieldG.alpha = 1 - dimSmooth * 0.34;

    // 1. Sunlit floor plinth ring (+ luminous intent focus beacon when highlighted)
    floorG.clear();
    if (focusSmooth > 0.01 && alive) {
      const pulse = 1 + Math.sin(time * 5.2) * 0.04;
      const px = offsetX * 0.35;
      const py = r * 0.66;
      floorG.ellipse(px, py, r * (1.16 + focusSmooth * 0.16) * pulse, r * (0.35 + focusSmooth * 0.06) * pulse)
        .fill({ color: pal.highlight, alpha: focusSmooth * 0.72 })
        .stroke({ width: 1.8, color: pal.secondary, alpha: focusSmooth * 0.72 });
      floorG.ellipse(px, py, r * 1.02 * pulse, r * 0.30 * pulse)
        .stroke({ width: 2.4, color: pal.primary, alpha: focusSmooth * 0.94 });
      for (let i = 0; i < 4; i++) {
        const a = time * 1.4 + (i * Math.PI) / 2;
        const rx0 = r * 1.04 * pulse;
        const ry0 = r * 0.30 * pulse;
        const rx1 = r * 1.24 * pulse;
        const ry1 = r * 0.36 * pulse;
        floorG.moveTo(px + Math.cos(a) * rx0, py + Math.sin(a) * ry0)
          .lineTo(px + Math.cos(a) * rx1, py + Math.sin(a) * ry1)
          .stroke({ width: 1.8, color: INK.gold, alpha: focusSmooth * 0.9, cap: 'round' });
      }
    }
    floorG.ellipse(offsetX * 0.4, r * 0.66, r * 0.76, r * 0.22)
      .fill({ color: INK.shadow, alpha: 0.28 });
    floorG.ellipse(0, r * 0.66, r * 0.92, r * 0.27)
      .stroke({
        width: 1.5 + focusSmooth * 0.9,
        color: alive ? (focusSmooth > 0.15 ? pal.primary : theme.accent) : INK.line,
        alpha: Math.min(0.95, 0.55 + focusSmooth * 0.4),
      });

    // 2. Orbiting live status auras (+ bright focus halo when highlighted)
    auraG.clear();
    auraG.position.set(offsetX * 0.5, liftY * 0.5);
    if (focusSmooth > 0.01 && alive) {
      drawFocusHighlightAura(auraG, pal, r, time, focusSmooth);
    }
    drawStatusAuras(auraG, cur, r, time);

    // 3. Evade wind-afterimages (sleek translucent speed silhouettes)
    afterimageG.clear();
    afterimageG.scale.set(facing * scaleMag, scaleMag);
    if (evade > 0.03) {
      for (let k = 1; k <= 2; k++) {
        afterimageG.position.set(offsetX + facing * k * 16, liftY);
        afterimageG.alpha = evade * (0.45 / k);
        afterimageG.ellipse(0, -r * 0.1, r * 0.36, r * 0.62)
          .fill({ color: 0x3b8f6e, alpha: 0.45 })
          .stroke({ width: 1.8, color: 0x7dd4a8, alpha: 0.75 });
      }
    } else {
      afterimageG.alpha = 0;
    }

    // 4. High-Craft 9-Bone SVG Character Rig (O(1) per-frame bone animation; custom draw hook still honored!)
    if (svgRig && svgRig.isReady()) {
      if (bodyG.visible) {
        bodyG.clear();
        bodyG.visible = false;
      }
      svgRig.animate(time, m, alive, animAmp);
    } else if (useCustomDrawHook) {
      bodyG.visible = true;
      bodyG.clear();
      drawCharacterBody(bodyG, pal, cur, r, time, animAmp);
    } else if (svgRig) {
      // Wait for 2ms first-time SVG decode; animate immediately once mounted
      svgRig.animate(time, m, alive, animAmp);
    }

    // 5. Concentric shield domes
    shieldG.clear();
    shieldG.position.set(offsetX * 0.6, liftY * 0.6);
    drawShieldDomes(shieldG, cur, r, time);

    // 6. Transient combat reaction flares (hit flash / heal glow / passive trigger crown!)
    flareG.clear();
    if (hitFlash > 0.02) {
      flareG.circle(offsetX, liftY, r * (0.85 + (1 - hitFlash) * 0.35))
        .fill({ color: 0xfce0d8, alpha: hitFlash * 0.52 })
        .stroke({ width: 2.8, color: 0xcf4330, alpha: hitFlash * 0.85 });
    }
    if (healGlow > 0.02) {
      const t = 1 - healGlow;
      flareG.circle(offsetX, liftY - t * 14, r * (0.7 + t * 0.55))
        .stroke({ width: 2.6, color: 0x269463, alpha: healGlow * 0.85 });
    }
    if (passiveFlare > 0.02) {
      const t = 1 - passiveFlare;
      flareG.poly(drawPolygon(flareG, 0, liftY - r * 0.05, r * (0.85 + t * 0.62), 8, time * 1.4))
        .stroke({ width: 2.6, color: INK.gold, alpha: passiveFlare * 0.9 });
    }
  };

  root.tick(0, null, ch);
  return root;
}
