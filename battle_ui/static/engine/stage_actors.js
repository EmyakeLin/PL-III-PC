/**
 * Living Procedural WebGL Character Actors, Animated Status Auras & Concentric Shield Domes
 * for 《光点计划 III》.
 * Strictly bright palette (ZERO black, ZERO blue-purple).
 * Each fighter is a sculpted, breathing, animated kinetic figure facing the opponent across the arena —
 * NOT a static white text box!
 */

import * as PIXI from '../vendor/pixi.min.mjs';
import { INK, SIDE_THEME, SHIELD_STYLE, STATUS_COLORS } from './card_print.js';

function drawPolygon(g, cx, cy, r, sides, rot = 0) {
  const pts = [];
  for (let i = 0; i < sides; i++) {
    const a = rot + (i * Math.PI * 2) / sides;
    pts.push(cx + Math.cos(a) * r, cy + Math.sin(a) * r);
  }
  return pts;
}

/**
 * Character-specific visual palette & silhouette motif (strictly warm bright tones, zero black/blue-purple).
 */
export function actorPalette(ch, side = 1) {
  const sideTheme = SIDE_THEME[side] || SIDE_THEME[1];
  const id = ch?.id || '';
  if (id === 'plan_b_annolin') {
    return { primary: 0x1c946b, secondary: 0x52c496, highlight: 0xdef7ec, metal: 0xd49622, trim: 0x3b322a, motif: 'annolin' };
  }
  if (id === 'waa_lake') {
    return { primary: 0xc95a2b, secondary: 0xe69e32, highlight: 0xfef2dc, metal: 0x7a6a58, trim: 0x3b322a, motif: 'lake' };
  }
  if (id === 'waa_grolina') {
    return { primary: 0xc44b3c, secondary: 0xe8a238, highlight: 0xfeefe2, metal: 0x877662, trim: 0x3b322a, motif: 'grolina' };
  }
  if (id === 'waa_erkes') {
    return { primary: 0x5d8f2c, secondary: 0xd4941e, highlight: 0xf4f8e4, metal: 0x6b6052, trim: 0x3b322a, motif: 'erkes' };
  }
  if (id === 'mistport_cen_yao') {
    return { primary: 0x1e8a78, secondary: 0xd48e1a, highlight: 0xe6f7f2, metal: 0x8a7558, trim: 0x3b322a, motif: 'cen_yao' };
  }
  if (id === 'ember_wen_sheng') {
    return { primary: 0xc44558, secondary: 0xd99224, highlight: 0xfdeef0, metal: 0x7d6858, trim: 0x3b322a, motif: 'wen_sheng' };
  }
  if (id === 'char_iron_vanguard') {
    return { primary: 0x6b7c5e, secondary: 0xd49622, highlight: 0xedf2e6, metal: 0x8c7b68, trim: 0x3b322a, motif: 'iron_vanguard' };
  }
  if (id === 'char_crimson_duelist') {
    return { primary: 0xc93b44, secondary: 0xe6a12c, highlight: 0xfdebed, metal: 0x7d6d5b, trim: 0x3b322a, motif: 'crimson_duelist' };
  }
  if (id === 'drill_scout') {
    return { primary: 0x2a8f72, secondary: 0xd49b2c, highlight: 0xe7f5ef, metal: 0x6b6052, trim: 0x3b322a, motif: 'drill_scout' };
  }
  if (id === 'drill_medic') {
    return { primary: 0x3b9c6e, secondary: 0xe08a24, highlight: 0xebf8f0, metal: 0x8a7558, trim: 0x3b322a, motif: 'drill_medic' };
  }
  if (id === 'drill_captain') {
    return { primary: 0xc96b1f, secondary: 0xe6ad2e, highlight: 0xfef4df, metal: 0x7d6d5b, trim: 0x3b322a, motif: 'drill_captain' };
  }
  if (id === 'drill_engine') {
    return { primary: 0x9e5828, secondary: 0xe39e24, highlight: 0xfaeee2, metal: 0x6b6052, trim: 0x3b322a, motif: 'drill_engine' };
  }
  return {
    primary: sideTheme.accent,
    secondary: INK.gold,
    highlight: sideTheme.softBg,
    metal: INK.secondary,
    trim: INK.primary,
    motif: 'generic',
  };
}

/**
 * Draw sculpted procedural character figure & weapon silhouette at (0, 0), facing +X (flipped via scale.x).
 */
function drawCharacterBody(g, pal, ch, radius, time) {
  const r = radius;
  const alive = ch.alive !== false;
  const primary = alive ? pal.primary : INK.muted;
  const secondary = alive ? pal.secondary : INK.line;
  const hi = alive ? pal.highlight : INK.paperSoft;
  const trim = alive ? pal.trim : INK.muted;
  const breathe = alive ? Math.sin(time * 2.8) * (r * 0.045) : 0;
  const flutter = alive ? Math.sin(time * 4.4) * (r * 0.09) : 0;

  // Back aura emblem halo behind shoulders
  if (alive) {
    g.circle(0, -r * 0.08 + breathe * 0.5, r * 0.66)
      .fill({ color: hi, alpha: 0.72 })
      .stroke({ width: 1.4, color: primary, alpha: 0.36 });
  }

  if (pal.motif === 'annolin') {
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
    const bladeTilt = Math.sin(time * 2.8) * 0.05;
    g.moveTo(r * 0.18, r * 0.16 + breathe)
      .quadraticCurveTo(r * 0.62, -r * 0.14 + bladeTilt * r, r * 0.96, -r * 0.56 + breathe)
      .quadraticCurveTo(r * 0.74, 0.04 * r, r * 0.28, r * 0.28 + breathe)
      .fill({ color: INK.paper }).stroke({ width: 1.8, color: primary });
    g.moveTo(r * 0.24, r * 0.18 + breathe)
      .lineTo(r * 0.88, -r * 0.46 + breathe)
      .stroke({ width: 1.6, color: pal.metal, cap: 'round' });
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
    const corePulse = 0.85 + Math.sin(time * 5.2) * 0.15;
    g.poly(drawPolygon(g, r * 0.04, r * 0.08 + breathe, r * 0.2 * corePulse, 6, 0))
      .fill({ color: secondary }).stroke({ width: 1.5, color: INK.paper });
    // Armored head
    g.poly(drawPolygon(g, 0, -r * 0.46 + breathe, r * 0.22, 6, 0))
      .fill({ color: INK.paper }).stroke({ width: 2, color: trim });
    // Heavy pressurized impact hammer/gauntlet forward
    g.roundRect(r * 0.34, -r * 0.34 + breathe, r * 0.36, r * 0.56, 6)
      .fill({ color: pal.metal }).stroke({ width: 1.8, color: secondary });
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
      .fill({ color: pal.metal }).stroke({ width: 1.5, color: secondary });
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
      .stroke({ width: 2.6, color: pal.metal, cap: 'round' });
    const glow = 0.85 + Math.sin(time * 4.2) * 0.15;
    g.circle(r * 0.46, -r * 0.46 + breathe, r * 0.15 * glow)
      .fill({ color: secondary, alpha: 0.88 }).stroke({ width: 1.4, color: INK.paper });
  } else if (pal.motif === 'drill_captain') {
    // Tall fluttering command banner behind
    g.moveTo(-r * 0.48, -r * 0.78).lineTo(-r * 0.48, r * 0.62)
      .stroke({ width: 2.8, color: pal.metal, cap: 'round' });
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
    const piston = Math.sin(time * 5.6) * (r * 0.05);
    // Back steam/piston stacks
    g.roundRect(-r * 0.58, -r * 0.66 - piston, r * 0.22, r * 0.48, 4)
      .fill({ color: pal.metal }).stroke({ width: 1.6, color: secondary });
    g.roundRect(r * 0.36, -r * 0.62 + piston, r * 0.22, r * 0.44, 4)
      .fill({ color: pal.metal }).stroke({ width: 1.6, color: secondary });
    // Massive octagonal armored torso
    g.poly(drawPolygon(g, 0, r * 0.06 + breathe * 0.6, r * 0.58, 8, Math.PI / 8))
      .fill({ color: primary }).stroke({ width: 2.2, color: INK.paper });
    // Inner armored furnace core
    const glow = 0.88 + Math.sin(time * 6.2) * 0.12;
    g.poly(drawPolygon(g, r * 0.04, r * 0.08 + breathe * 0.6, r * 0.24 * glow, 6, 0))
      .fill({ color: secondary }).stroke({ width: 1.6, color: INK.paper });
    // Armored optic turret head
    g.roundRect(-r * 0.26, -r * 0.62 + breathe * 0.6, r * 0.54, r * 0.28, 6)
      .fill({ color: pal.metal }).stroke({ width: 1.8, color: trim });
    g.roundRect(-r * 0.04, -r * 0.54 + breathe * 0.6, r * 0.28, r * 0.12, 3)
      .fill({ color: secondary });
    // Heavy forward battering ram arm
    g.roundRect(r * 0.42, -r * 0.18 + breathe * 0.6, r * 0.48, r * 0.42, 7)
      .fill({ color: primary }).stroke({ width: 2, color: secondary });
    g.roundRect(r * 0.68, -r * 0.1 + breathe * 0.6, r * 0.16, r * 0.26, 3)
      .fill({ color: secondary });
  } else {
    // Sculpted generic tactical figure + rank crest
    g.poly([
      0, -r * 0.32 + breathe,
      r * 0.36, r * 0.1 + breathe,
      r * 0.26, r * 0.62,
      -r * 0.26, r * 0.62,
      -r * 0.36, r * 0.1 + breathe,
    ]).fill({ color: primary }).stroke({ width: 1.6, color: INK.paper });
    g.circle(0, -r * 0.48 + breathe, r * 0.21)
      .fill({ color: INK.paper }).stroke({ width: 1.8, color: trim });
    if (ch.rank === 'BOSS' || ch.rank === 'EMPOWERED_BOSS' || ch.rank === 'ELITE') {
      g.poly(drawPolygon(g, 0, -r * 0.48 + breathe, r * 0.34, 4, Math.PI / 4))
        .stroke({ width: 1.5, color: secondary, alpha: 0.8 });
    }
    g.moveTo(r * 0.2, r * 0.1 + breathe).lineTo(r * 0.86, -r * 0.24 + breathe)
      .stroke({ width: 3, color: secondary, cap: 'round' });
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

  const floorG = new PIXI.Graphics();
  const auraG = new PIXI.Graphics();
  const afterimageG = new PIXI.Graphics();
  const bodyG = new PIXI.Graphics();
  const shieldG = new PIXI.Graphics();
  const flareG = new PIXI.Graphics();

  bodyG.scale.x = facing;
  afterimageG.scale.x = facing;

  root.addChild(floorG, auraG, afterimageG, bodyG, shieldG, flareG);

  root._actorData = { ch, side, pal, radius, facing };

  root.tick = (time, motion, liveCh) => {
    const cur = liveCh || ch;
    const m = motion || { lunge: 0, recoil: 0, evade: 0, hitFlash: 0, healGlow: 0, passiveFlare: 0 };
    const r = radius;
    const theme = SIDE_THEME[side] || SIDE_THEME[1];

    // Kinetic offset (lunge toward enemy, recoil backward, evade wind-dash)
    const offsetX = facing * (m.lunge * 34 - m.recoil * 22 - m.evade * 26);
    const tilt = facing * (m.lunge * 0.14 - m.recoil * 0.18);
    bodyG.position.set(offsetX, 0);
    bodyG.rotation = tilt;

    // 1. Sunlit floor plinth ring
    floorG.clear();
    floorG.ellipse(offsetX * 0.4, r * 0.66, r * 0.76, r * 0.22)
      .fill({ color: INK.shadow, alpha: 0.28 });
    floorG.ellipse(0, r * 0.66, r * 0.92, r * 0.27)
      .stroke({ width: 1.5, color: cur.alive !== false ? theme.accent : INK.line, alpha: 0.55 });

    // 2. Orbiting live status auras
    auraG.clear();
    auraG.position.set(offsetX * 0.5, 0);
    drawStatusAuras(auraG, cur, r, time);

    // 3. Evade wind-afterimages
    afterimageG.clear();
    if (m.evade > 0.03) {
      for (let k = 1; k <= 2; k++) {
        afterimageG.position.set(offsetX + facing * k * 16, 0);
        afterimageG.alpha = m.evade * (0.45 / k);
        drawCharacterBody(afterimageG, { ...pal, primary: 0x459934, secondary: 0x82cf6b }, cur, r, time);
      }
    } else {
      afterimageG.alpha = 0;
    }

    // 4. Sculpted animated fighter body
    bodyG.clear();
    drawCharacterBody(bodyG, pal, cur, r, time);

    // 5. Concentric shield domes
    shieldG.clear();
    shieldG.position.set(offsetX * 0.6, 0);
    drawShieldDomes(shieldG, cur, r, time);

    // 6. Transient combat reaction flares (hit flash / heal glow / passive trigger crown!)
    flareG.clear();
    if (m.hitFlash > 0.02) {
      flareG.circle(offsetX, 0, r * (0.85 + (1 - m.hitFlash) * 0.35))
        .fill({ color: 0xfce0d8, alpha: m.hitFlash * 0.52 })
        .stroke({ width: 2.8, color: 0xcf4330, alpha: m.hitFlash * 0.85 });
    }
    if (m.healGlow > 0.02) {
      const t = 1 - m.healGlow;
      flareG.circle(offsetX, -t * 14, r * (0.7 + t * 0.55))
        .stroke({ width: 2.6, color: 0x269463, alpha: m.healGlow * 0.85 });
    }
    if (m.passiveFlare > 0.02) {
      const t = 1 - m.passiveFlare;
      flareG.poly(drawPolygon(flareG, 0, -r * 0.05, r * (0.85 + t * 0.62), 8, time * 1.4))
        .stroke({ width: 2.6, color: INK.gold, alpha: m.passiveFlare * 0.9 });
    }
  };

  root.tick(0, null, ch);
  return root;
}
