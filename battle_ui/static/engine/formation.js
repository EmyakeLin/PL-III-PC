/**
 * Infinite-Roster Battlefield Formation Layout, Deterministic Data-Driven Actor Specs
 * & Persistent 60fps Delayed-Trail HP Bar for 《光点计划 III》.
 *
 * Pure PixiJS v8 ES module — ZERO DOM controls, STRICT bright sunlit warm-paper palette
 * (ZERO black max(r,g,b) >= 40, ZERO blue-purple !(b > r + 15 && b > g + 15)).
 *
 * Scales cleanly from 1v1 duels up to 10v10 tactical squads and infinite-roster formations!
 */

import * as PIXI from '../vendor/pixi.min.mjs';
import { INK, SIDE_THEME, FONT_NUM } from './design_system.js';

const WEAPON_ARCHETYPES = ['blade', 'lance', 'staff', 'shield', 'dual', 'cannon', 'tome'];

const CREST_SHAPES = [
  'diamond',
  'hex',
  'star',
  'chevron',
  'sunburst',
  'octagram',
  'shield_crest',
];

const AURA_MOTIFS = [
  'wind_ribbons',
  'astrolabe',
  'solar_halo',
  'ember_ring',
  'prism_orbit',
  'banner_crest',
  'harmonic_arcs',
];

const MANTLE_STYLES = ['cloak', 'pauldron', 'coat', 'robe', 'tactical'];

const RANK_TIER = {
  NORMAL: 0,
  ELITE: 1,
  BOSS: 2,
  EMPOWERED_BOSS: 3,
};

/**
 * Curated 16-swatch warm bright editorial palette (all strictly verified:
 * max(r,g,b) >= 48 and ZERO blue-purple).
 */
const WARM_BRIGHT_SWATCHES = [
  { primary: 0x1c946b, secondary: 0x52c496, highlight: 0xe6f7ef, metal: 0xd49622 },
  { primary: 0xc95a2b, secondary: 0xe69e32, highlight: 0xfef2dc, metal: 0x7a6a58 },
  { primary: 0xc44b3c, secondary: 0xe8a238, highlight: 0xfeefe2, metal: 0x877662 },
  { primary: 0x5d8f2c, secondary: 0xd4941e, highlight: 0xf4f8e4, metal: 0x6b6052 },
  { primary: 0x1e8a78, secondary: 0xd48e1a, highlight: 0xe6f7f2, metal: 0x8a7558 },
  { primary: 0xc44558, secondary: 0xd99224, highlight: 0xfdeef0, metal: 0x7d6858 },
  { primary: 0x6b7c5e, secondary: 0xd49622, highlight: 0xedf2e6, metal: 0x8c7b68 },
  { primary: 0xc93b44, secondary: 0xe6a12c, highlight: 0xfdebed, metal: 0x7d6d5b },
  { primary: 0x2a8f72, secondary: 0xd49b2c, highlight: 0xe7f5ef, metal: 0x6b6052 },
  { primary: 0x3b9c6e, secondary: 0xe08a24, highlight: 0xebf8f0, metal: 0x8a7558 },
  { primary: 0xc96b1f, secondary: 0xe6ad2e, highlight: 0xfef4df, metal: 0x7d6d5b },
  { primary: 0x9e5828, secondary: 0xe39e24, highlight: 0xfaeee2, metal: 0x6b6052 },
  { primary: 0xb87414, secondary: 0xe6b43c, highlight: 0xfef6e0, metal: 0x856e4d },
  { primary: 0xb5445c, secondary: 0xe39836, highlight: 0xfcedf1, metal: 0x826b5c },
  { primary: 0x7c8a2e, secondary: 0xdba328, highlight: 0xf5f7e4, metal: 0x756a52 },
  { primary: 0x288560, secondary: 0xd99626, highlight: 0xe9f6ef, metal: 0x877456 },
];

function clamp(v, lo, hi) {
  return Math.max(lo, Math.min(hi, v));
}

function fnv1a32(str) {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function mixHash(seed, salt) {
  let h = (seed ^ salt) >>> 0;
  h = Math.imul(h ^ (h >>> 16), 2246822507) >>> 0;
  h = Math.imul(h ^ (h >>> 13), 3266489909) >>> 0;
  return (h ^ (h >>> 16)) >>> 0;
}

function sanitizeWarmBrightHex(hex) {
  let r = (hex >> 16) & 255;
  let g = (hex >> 8) & 255;
  let b = hex & 255;

  // Enforce bright warm floor (ZERO black/near-black)
  const peak = Math.max(r, g, b);
  if (peak < 48) {
    const lift = 48 - peak;
    r = Math.min(255, r + lift + 10);
    g = Math.min(255, g + lift + 6);
    b = Math.min(255, b + lift);
  }

  // Enforce ZERO blue-purple: never allow b > r + 15 && b > g + 15
  if (b > r + 15 && b > g + 15) {
    b = Math.max(0, Math.min(r, g) + 8);
  }

  return (r << 16) | (g << 8) | b;
}

function tweakWarmSwatch(hex, shiftSeed) {
  const r0 = (hex >> 16) & 255;
  const g0 = (hex >> 8) & 255;
  const b0 = hex & 255;
  const dr = ((shiftSeed & 31) - 15);
  const dg = (((shiftSeed >> 5) & 31) - 15);
  const db = (((shiftSeed >> 10) & 15) - 7);
  const r = clamp(r0 + dr, 32, 232);
  const g = clamp(g0 + dg, 42, 224);
  const b = clamp(b0 + db, 24, Math.min(210, Math.max(r, g)));
  return sanitizeWarmBrightHex((r << 16) | (g << 8) | b);
}

function toCssHex(hex) {
  return `#${(hex & 0xffffff).toString(16).padStart(6, '0')}`;
}

function lerpColorHex(c1, c2, t) {
  const k = clamp(t, 0, 1);
  const r1 = (c1 >> 16) & 255;
  const g1 = (c1 >> 8) & 255;
  const b1 = c1 & 255;
  const r2 = (c2 >> 16) & 255;
  const g2 = (c2 >> 8) & 255;
  const b2 = c2 & 255;
  const r = Math.round(r1 + (r2 - r1) * k);
  const g = Math.round(g1 + (g2 - g1) * k);
  const b = Math.round(b1 + (b2 - b1) * k);
  return sanitizeWarmBrightHex((r << 16) | (g << 8) | b);
}

/**
 * Compute tactical battlefield formation positions for 1v1, 3v3, 10v10 & infinite rosters.
 *
 * Replaces naive `zoneH / N` vertical squashing:
 *  - 1–3 units: stately single staggered echelon
 *  - 4–10 units: crisp 2-rank diagonal tactical formation (frontline + backline echelons, zero overlap)
 *  - >10 units (11v11, 20v20, infinite): structured multi-rank formation with smooth vertical viewport scrolling
 */
export function computeFormationLayout({
  side = 1,
  count = 1,
  bandX = 0,
  bandW = 240,
  zoneTop = 92,
  zoneBottom = 560,
  scrollY = 0,
} = {}) {
  const safeCount = Math.max(0, Math.floor(count || 0));
  const safeBandW = Math.max(120, bandW || 240);
  const zoneH = Math.max(120, zoneBottom - zoneTop);
  const facing = side === 1 ? 1 : -1;
  const bandCenterX = bandX + safeBandW * 0.5;

  if (safeCount === 0) {
    return {
      side,
      count: 0,
      mode: 'echelon',
      ranks: 1,
      actorR: 36,
      hudScale: 1,
      hudW: Math.min(184, Math.max(140, safeBandW - 36)),
      slotH: zoneH,
      zoneTop,
      zoneBottom,
      zoneH,
      contentHeight: zoneH,
      scrollY: 0,
      maxScroll: 0,
      scrollable: false,
      slots: [],
    };
  }

  // ── Tier 1: 1–3 units — Stately single staggered echelon ──
  if (safeCount <= 3) {
    const slotH = Math.floor(zoneH / safeCount);
    const hudW = Math.min(184, Math.max(152, safeBandW - 34));
    const hudScale = safeCount === 1 ? 1.0 : safeCount === 2 ? 0.96 : 0.92;
    const estHudH = 66 * hudScale;
    const maxR = Math.max(18, Math.floor((slotH - estHudH - 12) / 1.72));
    const actorR = safeCount === 1
      ? clamp(maxR, 34, 54)
      : safeCount === 2
        ? clamp(maxR, 24, 38)
        : clamp(maxR, 18, 28);

    const staggerAmp = Math.min(16, safeBandW * 0.062);
    const slots = [];
    for (let i = 0; i < safeCount; i++) {
      const slotTop = zoneTop + i * slotH;
      const totalUnitH = actorR * 1.66 + estHudH + 4;
      const unitTop = slotTop + Math.max(2, Math.floor((slotH - totalUnitH) / 2));
      const actorCy = unitTop + actorR * 0.92;
      const staggerX = safeCount === 1
        ? 0
        : (i % 2 === 0 ? staggerAmp : -staggerAmp) * facing;
      slots.push({
        index: i,
        rank: 0,
        row: i,
        x: Math.round(bandCenterX + staggerX),
        y: Math.round(actorCy),
        rawY: Math.round(actorCy),
        slotTop: Math.round(slotTop),
        slotH,
        actorR,
        hudScale,
        hudW,
        visible: true,
        visibilityAlpha: 1,
        zIndex: i,
      });
    }

    return {
      side,
      count: safeCount,
      mode: 'echelon',
      ranks: 1,
      actorR,
      hudScale,
      hudW,
      slotH,
      zoneTop,
      zoneBottom,
      zoneH,
      contentHeight: zoneH,
      scrollY: 0,
      maxScroll: 0,
      scrollable: false,
      slots,
    };
  }

  // ── Tier 2: 4–10 units — Crisp 2-rank diagonal tactical formation ──
  if (safeCount <= 10) {
    const ranks = 2;
    const frontCount = Math.ceil(safeCount / 2);
    const backCount = safeCount - frontCount;
    const rows = Math.max(frontCount, backCount);

    const hudScale = safeCount <= 6 ? 0.84 : safeCount <= 8 ? 0.78 : 0.74;
    const colGap = Math.min(safeBandW * 0.245, 64);
    const frontX = bandCenterX + facing * colGap;
    const backX = bandCenterX - facing * colGap;
    const hudW = Math.round(clamp(safeBandW * 0.50, 96, 134));

    const minRowPitch = safeCount <= 6 ? 94 : safeCount <= 8 ? 82 : 74;
    const topPad = 8;
    const botPad = 10;
    const staggerPad = backCount === frontCount ? Math.round(minRowPitch * 0.34) : 0;
    const availH = Math.max(100, zoneH - topPad - botPad - staggerPad);
    const fittedPitch = Math.floor(availH / Math.max(1, rows));
    const rowPitch = Math.max(minRowPitch, Math.min(132, fittedPitch));

    const contentHeight = topPad + rows * rowPitch + staggerPad + botPad;
    const maxScroll = Math.max(0, contentHeight - zoneH);
    const clampedScroll = clamp(scrollY || 0, 0, maxScroll);

    const estHudH = 54 * hudScale;
    const maxR = Math.max(14, Math.floor((rowPitch - estHudH - 6) / 1.65));
    const actorR = safeCount <= 6
      ? clamp(maxR, 17, 25)
      : safeCount <= 8
        ? clamp(maxR, 15, 21)
        : clamp(maxR, 14, 18);

    // Vertically center formation when it fits cleanly inside zoneH
    const freeSpace = maxScroll === 0 ? Math.max(0, Math.floor((zoneH - contentHeight) * 0.5)) : 0;
    const diagOffset = Math.round(rowPitch * (backCount === frontCount ? 0.34 : 0.48));

    const slots = [];
    for (let i = 0; i < safeCount; i++) {
      const rank = i % 2; // 0 = frontline (closer to center), 1 = backline
      const row = Math.floor(i / 2);
      const cx = rank === 0 ? frontX : backX;
      const rankShiftY = rank === 1 ? diagOffset : 0;
      const slotTopRaw = zoneTop + freeSpace + topPad + row * rowPitch + rankShiftY;
      const actorRawY = slotTopRaw + actorR * 0.96 + 4;
      const screenY = actorRawY - clampedScroll;
      const slotTop = slotTopRaw - clampedScroll;

      const unitTop = screenY - actorR - 6;
      const unitBottom = screenY + actorR * 0.78 + estHudH;
      const visible = unitBottom >= zoneTop - 16 && unitTop <= zoneBottom + 16;

      let visibilityAlpha = 1;
      if (maxScroll > 0) {
        const topDist = (screenY - zoneTop) / 28;
        const botDist = (zoneBottom - screenY) / 28;
        visibilityAlpha = visible ? clamp(Math.min(topDist, botDist), 0.15, 1) : 0;
      }

      slots.push({
        index: i,
        rank,
        row,
        x: Math.round(cx),
        y: Math.round(screenY),
        rawY: Math.round(actorRawY),
        slotTop: Math.round(slotTop),
        slotH: rowPitch,
        actorR,
        hudScale,
        hudW,
        visible,
        visibilityAlpha,
        // Frontline draws slightly ahead of backline on same row
        zIndex: row * 4 + (rank === 0 ? 2 : 1),
      });
    }

    return {
      side,
      count: safeCount,
      mode: 'dual_rank',
      ranks,
      actorR,
      hudScale,
      hudW,
      slotH: rowPitch,
      zoneTop,
      zoneBottom,
      zoneH,
      contentHeight,
      scrollY: clampedScroll,
      maxScroll,
      scrollable: maxScroll > 0,
      slots,
    };
  }

  // ── Tier 3: >10 units (11v11, 20v20, infinite!) — Structured multi-rank with smooth scrolling ──
  const ranks = safeBandW >= 296 ? 3 : 2;
  const rows = Math.ceil(safeCount / ranks);
  const hudScale = ranks === 3 ? 0.70 : 0.74;
  const actorR = ranks === 3 ? 15 : 16;
  const hudW = Math.round(clamp(Math.floor(safeBandW / ranks) - 6, 86, 126));
  const rowPitch = 78;
  const topPad = 10;
  const botPad = 14;
  const rankStaggerStep = Math.round(rowPitch / (ranks + 0.6));
  const maxStagger = rankStaggerStep * (ranks - 1);

  const contentHeight = topPad + rows * rowPitch + maxStagger + botPad;
  const maxScroll = Math.max(0, contentHeight - zoneH);
  const clampedScroll = clamp(scrollY || 0, 0, maxScroll);

  // Rank 0 is closest to arena center, rank (ranks-1) is furthest back
  const usableSpanW = Math.max(60, safeBandW - hudW * 0.72);
  const rankXs = [];
  for (let r = 0; r < ranks; r++) {
    const frac = ranks === 1 ? 0 : (r / (ranks - 1)) - 0.5; // -0.5..+0.5
    // rank 0 -> +0.5 * facing (frontline), last rank -> -0.5 * facing (rearline)
    rankXs.push(bandCenterX + facing * (-frac) * usableSpanW);
  }

  const estHudH = 52 * hudScale;
  const slots = [];
  for (let i = 0; i < safeCount; i++) {
    const rank = i % ranks;
    const row = Math.floor(i / ranks);
    const cx = rankXs[rank];
    const slotTopRaw = zoneTop + topPad + row * rowPitch + rank * rankStaggerStep;
    const actorRawY = slotTopRaw + actorR * 0.98 + 4;
    const screenY = actorRawY - clampedScroll;
    const slotTop = slotTopRaw - clampedScroll;

    const unitTop = screenY - actorR - 8;
    const unitBottom = screenY + actorR * 0.78 + estHudH;
    const visible = unitBottom >= zoneTop - 20 && unitTop <= zoneBottom + 20;

    const topFade = (screenY - zoneTop) / 30;
    const botFade = (zoneBottom - screenY) / 30;
    const visibilityAlpha = visible ? clamp(Math.min(topFade, botFade), 0.12, 1) : 0;

    slots.push({
      index: i,
      rank,
      row,
      x: Math.round(cx),
      y: Math.round(screenY),
      rawY: Math.round(actorRawY),
      slotTop: Math.round(slotTop),
      slotH: rowPitch,
      actorR,
      hudScale,
      hudW,
      visible,
      visibilityAlpha,
      zIndex: row * (ranks + 2) + (ranks - rank),
    });
  }

  return {
    side,
    count: safeCount,
    mode: 'multi_rank',
    ranks,
    actorR,
    hudScale,
    hudW,
    slotH: rowPitch,
    zoneTop,
    zoneBottom,
    zoneH,
    contentHeight,
    scrollY: clampedScroll,
    maxScroll,
    scrollable: maxScroll > 0,
    slots,
  };
}

/**
 * Deterministic, data-driven visual descriptor for ANY character ID (including unknown / future infinite roster).
 * Uses FNV-1a hashing over `id`, `faction`, and `rank` — ZERO hardcoded character `if/else` bottlenecks!
 * Strictly guarantees warm bright non-blue-purple palette (`max(r,g,b) >= 48`, `!(b > r+15 && b > g+15)`).
 */
export function resolveInfiniteActorSpec(character, side = 1) {
  const ch = character || {};
  const id = String(ch.id || ch.name || 'unit');
  const faction = String(ch.faction || ch.affiliation || '');
  const rank = String(ch.rank || 'NORMAL').toUpperCase();
  const rankTier = RANK_TIER[rank] ?? 0;

  const baseSeed = fnv1a32(`${id}|${faction}|${rank}`);
  const hPalette = mixHash(baseSeed, 0x9e3779b9);
  const hWeapon = mixHash(baseSeed, 0x85ebca6b);
  const hCrest = mixHash(baseSeed, 0xc2b2ae35);
  const hAura = mixHash(baseSeed, 0x27d4eb2f);
  const hDetail = mixHash(baseSeed, 0x165667b1);

  const sideTheme = SIDE_THEME[side] || SIDE_THEME[1];
  const swatch = WARM_BRIGHT_SWATCHES[hPalette % WARM_BRIGHT_SWATCHES.length];

  // Subtle deterministic tint variation so even 500+ roster units remain visually distinct
  const primary = tweakWarmSwatch(swatch.primary, hPalette >>> 4);
  const secondary = tweakWarmSwatch(swatch.secondary, hDetail);
  const highlight = sanitizeWarmBrightHex(swatch.highlight);
  const metal = sanitizeWarmBrightHex(swatch.metal);
  const trim = INK.primary;

  // Deterministic weapon archetype, crest shape, aura motif & mantle silhouette
  const weaponArchetype = WEAPON_ARCHETYPES[hWeapon % WEAPON_ARCHETYPES.length];
  const crestShape = CREST_SHAPES[(hCrest + rankTier) % CREST_SHAPES.length];
  const auraMotif = AURA_MOTIFS[hAura % AURA_MOTIFS.length];
  const mantleStyle = MANTLE_STYLES[hDetail % MANTLE_STYLES.length];

  const silhouetteScale = rankTier === 3 ? 1.12 : rankTier === 2 ? 1.08 : rankTier === 1 ? 1.03 : 1.0;

  return {
    id,
    faction,
    rank,
    rankTier,
    side,
    seed: baseSeed,
    // Palette tokens (drop-in compatible with actorPalette)
    primary,
    secondary,
    highlight,
    metal,
    trim,
    sideAccent: sideTheme.accent,
    accentHex: toCssHex(primary),
    secondaryHex: toCssHex(secondary),
    // Procedural visual traits
    weaponArchetype,
    crestShape,
    auraMotif,
    mantleStyle,
    motif: `${weaponArchetype}_${crestShape}`,
    crestRings: rankTier >= 2 ? 2 : 1,
    silhouetteScale,
  };
}

/**
 * Persistent 60fps Delayed-Trail HP Bar widget (Limbus Company / Library of Ruina feel):
 *  - Damage: instant drop on main bar + luminous white-to-amber ghost trail that holds briefly then smoothly drains!
 *  - Healing: immediate jade-gold preview trail + smooth main bar fill!
 *  - ZERO destroy/rebuild on updates; returns a PIXI.Container with self-reference `.container` and controller methods.
 */
export function createDelayedHpBar({
  width = 124,
  height = 11,
  accentColor = 0x1a825e,
  maxHp = 100,
  hp = 100,
  showText = false,
  radius = 5,
} = {}) {
  const root = new PIXI.Container();
  root.container = root;

  const trackG = new PIXI.Graphics();
  const trailG = new PIXI.Graphics();
  const fillG = new PIXI.Graphics();
  const notchG = new PIXI.Graphics();
  const flashG = new PIXI.Graphics();
  root.addChild(trackG, trailG, fillG, notchG, flashG);

  let labelText = null;
  if (showText) {
    labelText = new PIXI.Text({
      text: `${Math.round(hp)}/${Math.max(1, Math.round(maxHp))}`,
      style: {
        fontFamily: FONT_NUM,
        fontSize: Math.max(9.5, Math.round(height * 0.92)),
        fontWeight: '900',
        fill: INK.strong,
      },
    });
    labelText.anchor.set(1, 0.5);
    root.addChild(labelText);
  }

  const state = {
    width: Math.max(24, width),
    height: Math.max(6, height),
    radius: Math.min(radius, Math.floor(height * 0.5)),
    accentColor: sanitizeWarmBrightHex(accentColor),
    maxHp: Math.max(1, maxHp),
    targetHp: clamp(hp, 0, Math.max(1, maxHp)),
    currentHp: clamp(hp, 0, Math.max(1, maxHp)),
    trailHp: clamp(hp, 0, Math.max(1, maxHp)),
    holdTimer: 0,
    impactFlash: 0,
    healFlash: 0,
    dirtyTrack: true,
    dirtyBar: true,
  };

  const WARN_CRIMSON = 0xd13f20;
  const TRAIL_WHITE = 0xfffaf0;
  const TRAIL_AMBER = 0xe8a434;
  const HEAL_JADE = 0x3ba874;

  function redrawTrack() {
    const { width: w, height: h, radius: r } = state;
    trackG.clear();
    trackG.roundRect(0, 0, w, h, r)
      .fill({ color: INK.paperTint })
      .stroke({ width: 0.9, color: INK.line });
    // Subtle recessed top inner shadow hairline
    trackG.moveTo(r, 1.2).lineTo(w - r, 1.2)
      .stroke({ width: 1, color: INK.shadow, alpha: 0.22 });

    notchG.clear();
    if (w >= 64) {
      for (const frac of [0.25, 0.5, 0.75]) {
        const nx = Math.round(w * frac);
        notchG.moveTo(nx, 2).lineTo(nx, h - 2)
          .stroke({ width: 0.9, color: INK.paper, alpha: 0.34 });
      }
    }

    if (labelText) {
      labelText.position.set(w - 4, h * 0.5);
    }
    state.dirtyTrack = false;
  }

  function redrawBar() {
    const { width: w, height: h, radius: r, maxHp: mHp } = state;
    const innerW = Math.max(0, w - 2);
    const innerH = Math.max(2, h - 2);
    const innerR = Math.max(1, r - 1);

    const curRatio = clamp(state.currentHp / mHp, 0, 1);
    const trailRatio = clamp(state.trailHp / mHp, 0, 1);

    // 1. Delayed damage or heal ghost trail
    trailG.clear();
    if (trailRatio > curRatio + 0.002) {
      const tw = Math.max(innerR * 2, innerW * trailRatio);
      // White flash immediately on hit -> transitions smoothly into warm glowing amber
      const whiteMix = clamp(state.impactFlash * 1.15, 0, 1);
      const trailCol = lerpColorHex(TRAIL_AMBER, TRAIL_WHITE, whiteMix);
      trailG.roundRect(1, 1, Math.min(innerW, tw), innerH, innerR)
        .fill({ color: trailCol, alpha: 0.95 });
    } else if (state.healFlash > 0.01 && state.targetHp > state.currentHp) {
      const targetRatio = clamp(state.targetHp / mHp, 0, 1);
      const hw = Math.max(innerR * 2, innerW * targetRatio);
      trailG.roundRect(1, 1, Math.min(innerW, hw), innerH, innerR)
        .fill({ color: HEAL_JADE, alpha: 0.52 + state.healFlash * 0.3 });
    }

    // 2. Primary crisp HP fill
    fillG.clear();
    if (curRatio > 0.001) {
      const fw = Math.min(innerW, Math.max(innerH, innerW * curRatio));
      const fillCol = curRatio < 0.34 ? WARN_CRIMSON : state.accentColor;
      fillG.roundRect(1, 1, fw, innerH, innerR)
        .fill({ color: fillCol });
      // Crisp top sunlit specular strip for physical depth
      if (innerH >= 6 && fw > innerR * 2 + 2) {
        fillG.roundRect(1.5, 1.5, fw - 1, Math.max(1.5, innerH * 0.34), Math.max(1, innerR - 0.5))
          .fill({ color: INK.paper, alpha: 0.28 });
      }
    }

    // 3. Brief impact / heal rim flare
    flashG.clear();
    if (state.impactFlash > 0.01) {
      flashG.roundRect(0, 0, w, h, r)
        .stroke({ width: 1.6, color: TRAIL_WHITE, alpha: state.impactFlash * 0.85 });
    } else if (state.healFlash > 0.01) {
      flashG.roundRect(0, 0, w, h, r)
        .stroke({ width: 1.4, color: HEAL_JADE, alpha: state.healFlash * 0.72 });
    }

    if (labelText) {
      labelText.text = `${Math.round(state.currentHp)}/${Math.round(mHp)}`;
    }
    state.dirtyBar = false;
  }

  function setHp(nextHp, nextMaxHp = null, { immediate = false } = {}) {
    if (typeof nextMaxHp === 'number' && Number.isFinite(nextMaxHp) && nextMaxHp > 0) {
      state.maxHp = nextMaxHp;
    }
    const clamped = clamp(Number(nextHp) || 0, 0, state.maxHp);
    const prevTarget = state.targetHp;
    state.targetHp = clamped;

    if (immediate) {
      state.currentHp = clamped;
      state.trailHp = clamped;
      state.holdTimer = 0;
      state.impactFlash = 0;
      state.healFlash = 0;
    } else if (clamped < prevTarget) {
      // Damage taken: snap current HP immediately, keep delayed trail hanging at previous value!
      state.trailHp = Math.max(state.trailHp, state.currentHp, prevTarget);
      state.currentHp = clamped;
      state.holdTimer = 0.28;
      state.impactFlash = 1.0;
      state.healFlash = 0;
    } else if (clamped > prevTarget) {
      // Healing received: trail catches up, currentHp eases up warmly
      state.trailHp = Math.max(state.trailHp, state.currentHp);
      state.healFlash = 0.9;
    }

    state.dirtyBar = true;
  }

  function setMaxHp(nextMaxHp) {
    if (typeof nextMaxHp !== 'number' || !Number.isFinite(nextMaxHp) || nextMaxHp <= 0) return;
    if (state.maxHp !== nextMaxHp) {
      state.maxHp = nextMaxHp;
      state.targetHp = clamp(state.targetHp, 0, state.maxHp);
      state.currentHp = clamp(state.currentHp, 0, state.maxHp);
      state.trailHp = clamp(state.trailHp, 0, state.maxHp);
      state.dirtyBar = true;
    }
  }

  function setAccentColor(colorHex) {
    const safe = sanitizeWarmBrightHex(colorHex);
    if (state.accentColor !== safe) {
      state.accentColor = safe;
      state.dirtyBar = true;
    }
  }

  function setSize(nextW, nextH) {
    const w = Math.max(24, nextW || state.width);
    const h = Math.max(6, nextH || state.height);
    if (w !== state.width || h !== state.height) {
      state.width = w;
      state.height = h;
      state.radius = Math.min(radius, Math.floor(h * 0.5));
      state.dirtyTrack = true;
      state.dirtyBar = true;
    }
  }

  function sync({ hp: nextHp, maxHp: nextMaxHp, accentColor: nextCol, immediate = false } = {}) {
    if (nextCol !== undefined && nextCol !== null) setAccentColor(nextCol);
    if (nextHp !== undefined && nextHp !== null) {
      setHp(nextHp, nextMaxHp ?? state.maxHp, { immediate });
    } else if (nextMaxHp !== undefined && nextMaxHp !== null) {
      setMaxHp(nextMaxHp);
    }
  }

  function tick(dtSec = 1 / 60) {
    const dt = clamp(dtSec || 0, 0, 0.1);
    let changed = false;

    // Smooth healing fill toward targetHp
    if (state.currentHp < state.targetHp) {
      const step = Math.max(state.maxHp * 0.65 * dt, (state.targetHp - state.currentHp) * Math.min(1, dt * 8.5));
      state.currentHp = Math.min(state.targetHp, state.currentHp + step);
      state.trailHp = Math.max(state.trailHp, state.currentHp);
      changed = true;
    } else if (state.currentHp > state.targetHp) {
      state.currentHp = state.targetHp;
      changed = true;
    }

    // Delayed white/amber damage trail drain after brief hold pause
    if (state.trailHp > state.currentHp) {
      if (state.holdTimer > 0) {
        state.holdTimer = Math.max(0, state.holdTimer - dt);
        changed = true;
      } else {
        const diff = state.trailHp - state.currentHp;
        const drain = Math.max(state.maxHp * 0.26 * dt, diff * Math.min(1, dt * 5.6));
        state.trailHp = Math.max(state.currentHp, state.trailHp - drain);
        changed = true;
      }
    } else if (state.trailHp < state.currentHp) {
      state.trailHp = state.currentHp;
      changed = true;
    }

    if (state.impactFlash > 0) {
      state.impactFlash = Math.max(0, state.impactFlash - dt * 3.8);
      changed = true;
    }
    if (state.healFlash > 0) {
      state.healFlash = Math.max(0, state.healFlash - dt * 2.6);
      changed = true;
    }

    if (state.dirtyTrack) redrawTrack();
    if (state.dirtyBar || changed) redrawBar();
  }

  function getState() {
    return {
      hp: state.targetHp,
      maxHp: state.maxHp,
      displayHp: state.currentHp,
      trailHp: state.trailHp,
      ratio: clamp(state.currentHp / state.maxHp, 0, 1),
      trailRatio: clamp(state.trailHp / state.maxHp, 0, 1),
      accentColor: state.accentColor,
    };
  }

  root.setHp = setHp;
  root.setMaxHp = setMaxHp;
  root.setAccentColor = setAccentColor;
  root.setSize = setSize;
  root.sync = sync;
  root.tick = tick;
  root.getState = getState;

  redrawTrack();
  redrawBar();

  return root;
}
