/**
 * Persistent, 10v10-Scalable Tactical Combat Staging & Sightline Choreography for 《光点计划 III》.
 *
 * Modules exported:
 *  1. renderFocusSightlines(graphics, options)  — 《废墟图书馆》-inspired intelligent combat sightlines
 *  2. createDiegeticTopBar(options)             — Persistent tabletop battle chronicle crest & brass pressmark seals
 *  3. buildScalableDuelRail(options)            — Auto-centering, masked scrollable duel progress rail (1 to 40+ duels)
 *  4. buildHitstopBanner(options)               — Tactile weighted floating callouts with differentiated visual hierarchy
 *
 * STRICT INVARIANTS:
 *  - Pure PixiJS v8 ES module, ZERO DOM controls
 *  - Bright sunlit warm-paper palette: max(r, g, b) >= 40, ZERO blue-purple
 *  - Zero destroy/rebuild on top-bar toggles or duel-rail scrolling
 *  - Zero spiderweb clutter at 10v10; strict duelViewport clipping guards
 */

import * as PIXI from '../vendor/pixi.min.mjs';
import {
  FONT_UI,
  FONT_NUM,
  INK,
  SIDE_THEME,
  TRAIT_STYLE,
  SHIELD_STYLE,
} from './design_system.js';
import {
  drawLightStar,
  drawShieldGlyph,
} from './card_print.js';

const PALETTE = {
  brass: 0xc98216,
  brassDeep: 0x8c530c,
  brassSoft: 0xe6c98e,
  bevel: 0xe3dac9,
  hoverPaper: 0xfbf6eb,
  parchmentTint: 0xf6ead0,
  crimson: 0xc8452e,
  crimsonDeep: 0xa82f24,
  crimsonWash: 0xfdece9,
  jade: 0x1a825e,
  jadeDeep: 0x146649,
  jadeWash: 0xeef7f3,
  maskFill: 0xffffff,
};

function clamp(v, min, max) {
  return Math.max(min, Math.min(max, v));
}

function evalQuadBezier(p0, cp, p1, t) {
  const u = 1 - t;
  const x = u * u * p0.x + 2 * u * t * cp.x + t * t * p1.x;
  const y = u * u * p0.y + 2 * u * t * cp.y + t * t * p1.y;
  const dx = 2 * u * (cp.x - p0.x) + 2 * t * (p1.x - cp.x);
  const dy = 2 * u * (cp.y - p0.y) + 2 * t * (p1.y - cp.y);
  return { x, y, dx, dy };
}

function drawArrowDart(g, x, y, dx, dy, size, color, alpha = 0.92) {
  const len = Math.hypot(dx, dy);
  if (len < 0.001) return;
  const ux = dx / len;
  const uy = dy / len;
  const px = -uy;
  const py = ux;
  const tipX = x + ux * size * 0.45;
  const tipY = y + uy * size * 0.45;
  const baseX = x - ux * size * 0.95;
  const baseY = y - uy * size * 0.95;
  const notchX = x - ux * size * 0.55;
  const notchY = y - uy * size * 0.55;
  g.poly([
    tipX, tipY,
    baseX + px * size * 0.56, baseY + py * size * 0.56,
    notchX, notchY,
    baseX - px * size * 0.56, baseY - py * size * 0.56,
  ]).fill({ color, alpha });
}

function drawDiamondPip(g, cx, cy, r, fillColor, { alpha = 1, strokeColor = null, strokeWidth = 1.1 } = {}) {
  g.poly([cx, cy - r, cx + r, cy, cx, cy + r, cx - r, cy]).fill({ color: fillColor, alpha });
  if (strokeColor !== null) {
    g.poly([cx, cy - r, cx + r, cy, cx, cy + r, cx - r, cy])
      .stroke({ width: strokeWidth, color: strokeColor, alpha: Math.min(1, alpha + 0.1) });
  }
}

function drawTravellingPulses(g, p0, cp, p1, {
  count = 2,
  speed = 0.55,
  time = 0,
  color = INK.gold,
  radius = 3.2,
  alpha = 0.92,
  phaseOffset = 0,
  viewport = null,
} = {}) {
  for (let i = 0; i < count; i++) {
    const t = (((time * speed + phaseOffset + i / count) % 1) + 1) % 1;
    if (t < 0.06 || t > 0.94) continue;
    const pt = evalQuadBezier(p0, cp, p1, t);
    if (viewport) {
      if (pt.y < viewport.top + 3 || pt.y > viewport.bottom - 3) continue;
      if (viewport.left != null && pt.x < viewport.left + 3) continue;
      if (viewport.right != null && pt.x > viewport.right - 3) continue;
    }
    const edgeFade = Math.sin(t * Math.PI);
    const a = alpha * clamp(edgeFade * 1.45, 0, 1);
    g.circle(pt.x, pt.y, radius * 1.9).fill({ color, alpha: a * 0.24 });
    g.circle(pt.x, pt.y, radius).fill({ color, alpha: a });
    g.circle(pt.x, pt.y, radius * 0.45).fill({ color: INK.paper, alpha: a * 0.95 });
  }
}

function isRectInViewport(rect, vp, margin = 6) {
  if (!rect || rect.visible === false) return false;
  if (!vp) return true;
  if (rect.cy < vp.top + margin || rect.cy > vp.bottom - margin) return false;
  if (vp.left != null && rect.cx < vp.left + margin) return false;
  if (vp.right != null && rect.cx > vp.right - margin) return false;
  return true;
}

function clampControlPointToViewport(p0, cp, p1, vp, pad = 6) {
  if (!vp) return cp;
  const minY = Math.min(p0.y, p1.y, vp.top + pad);
  const maxY = Math.max(p0.y, p1.y, vp.bottom - pad);
  let cy = cp.y;
  if (p0.y >= vp.top && p0.y <= vp.bottom && p1.y >= vp.top && p1.y <= vp.bottom) {
    cy = clamp(cy, vp.top + pad, vp.bottom - pad);
  } else {
    cy = clamp(cy, minY - 18, maxY + 18);
  }
  let cx = cp.x;
  if (vp.left != null && vp.right != null) {
    const minX = Math.min(p0.x, p1.x, vp.left + pad);
    const maxX = Math.max(p0.x, p1.x, vp.right - pad);
    cx = clamp(cx, minX, maxX);
  }
  return { x: cx, y: cy };
}

function resolveActorPosition(actorPosFn, charId, fallbackName = null) {
  if (typeof actorPosFn !== 'function') return null;
  if (charId != null) {
    const p = actorPosFn(charId);
    if (p && Number.isFinite(p.x) && Number.isFinite(p.y)) return p;
  }
  if (fallbackName != null && fallbackName !== charId) {
    const p = actorPosFn(fallbackName);
    if (p && Number.isFinite(p.x) && Number.isFinite(p.y)) return p;
  }
  return null;
}

function drawViewportClipCaret(g, x, y, pointsUp, color, alpha = 0.85) {
  const dir = pointsUp ? -1 : 1;
  g.circle(x, y, 7.5).fill({ color: INK.paper, alpha: 0.92 }).stroke({ width: 1.4, color, alpha });
  g.moveTo(x - 3.6, y - dir * 1.4)
    .lineTo(x, y + dir * 2.6)
    .lineTo(x + 3.6, y - dir * 1.4)
    .stroke({ width: 1.7, color, alpha, cap: 'round', join: 'round' });
}

/**
 * 1. 《废墟图书馆》-Style Intelligent Tactical Sightlines (10v10 Anti-Spiderweb Architecture).
 *
 * - Idle (no focus, no drag): draws ONLY whisper-soft anchors on visible regular cards + clean
 *   subdued sightlines for active pre-reveal intercepts/attacks so 10v10 with 15+ cards stays razor-clean.
 * - Focused (`focusCharId`, `focusDuelNumber`, or active drag): vividly illuminates ONLY relevant
 *   owner-to-card tethers, clash bridges, and enemy target/intercept arcs with animated bezier pulse
 *   dots, while gently dimming unrelated threads.
 * - Strictly guards against `duelViewport` so zero lines ever shoot outside the masked duel area.
 */
export function renderFocusSightlines(graphics, {
  duels = [],
  preDuels = [],
  cardOwners = null,
  charColorFn = null,
  regularSlotRects = null,
  preRevealSlotRects = null,
  actorPosFn = null,
  focusCharId = null,
  focusDuelNumber = null,
  dragState = null,
  duelViewport = null,
  time = 0,
  themeMap = SIDE_THEME,
} = {}) {
  if (!graphics || graphics.destroyed) return;
  graphics.clear();

  const themes = themeMap || SIDE_THEME;
  const regMap = regularSlotRects instanceof Map ? regularSlotRects : null;
  const preMap = preRevealSlotRects instanceof Map ? preRevealSlotRects : null;
  const vp = duelViewport || null;

  const isDragging = Boolean(dragState && dragState.moved);
  const dragCharId = isDragging ? (dragState.charId || dragState.card?.character_id || null) : null;
  const effectiveCharId = focusCharId || dragCharId || null;

  let effectiveRegDuel = null;
  let effectivePreDuel = null;
  if (typeof focusDuelNumber === 'number') {
    effectiveRegDuel = focusDuelNumber;
  } else if (focusDuelNumber && typeof focusDuelNumber === 'object') {
    if (focusDuelNumber.kind === 'pre_reveal') effectivePreDuel = focusDuelNumber.number;
    else if (focusDuelNumber.number != null) effectiveRegDuel = focusDuelNumber.number;
  }
  if (isDragging && dragState.targetPreRevealNumber != null) {
    effectivePreDuel = dragState.targetPreRevealNumber;
  }

  const hasFocus = Boolean(
    effectiveCharId != null
    || effectiveRegDuel != null
    || effectivePreDuel != null
    || isDragging
  );

  // Collect visible regular placed cards (strictly clipped against duelViewport!)
  const visibleEntries = [];
  if (regMap && Array.isArray(duels)) {
    for (const duel of duels) {
      if (!duel) continue;
      for (const sEntry of duel.sides || []) {
        const well = regMap.get(`${duel.number}:${sEntry.side}`);
        if (!isRectInViewport(well, vp, 6)) continue;
        const cards = sEntry.cards || [];
        const ownerList = cardOwners?.duels?.[`${duel.number}:${sEntry.side}`] || [];
        for (let ci = 0; ci < cards.length; ci++) {
          const card = cards[ci];
          if (!card) continue;
          const resolvedCharId = card.character_id || ownerList[ci]?.character_id || null;
          if (!resolvedCharId) continue;
          const anchorX = sEntry.side === 1 ? well.x + 5 : well.x + well.w - 5;
          const spreadY = cards.length > 1
            ? ((ci / Math.max(1, cards.length - 1)) - 0.5) * Math.min(26, well.h * 0.34)
            : 0;
          const anchorY = vp
            ? clamp(well.cy + spreadY, vp.top + 8, vp.bottom - 8)
            : well.cy + spreadY;
          const isRelated = Boolean(
            (effectiveCharId != null && resolvedCharId === effectiveCharId)
            || (effectiveRegDuel != null && duel.number === effectiveRegDuel)
          );
          visibleEntries.push({
            duelNumber: duel.number,
            side: sEntry.side,
            card,
            ownerCharId: resolvedCharId,
            well,
            anchorX,
            anchorY,
            isRelated,
          });
        }
      }
    }
  }

  const denseBoard = visibleEntries.length > 4;

  // ── Layer 1: Regular Duel Anchors & Focused Owner-to-Card Tethers ──
  const focusedDuelSides = new Map();
  for (let i = 0; i < visibleEntries.length; i++) {
    const item = visibleEntries[i];
    const theme = themes[item.side] || SIDE_THEME[item.side] || SIDE_THEME[1];
    const col = typeof charColorFn === 'function' ? charColorFn(item.ownerCharId, item.side) : theme.accent;
    const inwardDir = item.side === 1 ? -1 : 1;

    if (item.isRelated) {
      let sideSet = focusedDuelSides.get(item.duelNumber);
      if (!sideSet) {
        sideSet = new Set();
        focusedDuelSides.set(item.duelNumber, sideSet);
      }
      sideSet.add(item.side);
    }

    if (!hasFocus) {
      // Unfocused state: whisper-soft directional anchors (ZERO spiderweb at 10v10!)
      const tickLen = denseBoard ? 11 : 16;
      const tipX = item.anchorX + inwardDir * tickLen;
      graphics.moveTo(item.anchorX, item.anchorY)
        .lineTo(tipX, item.anchorY)
        .stroke({ width: 1.35, color: col, alpha: denseBoard ? 0.24 : 0.32, cap: 'round' });
      drawDiamondPip(graphics, item.anchorX, item.anchorY, 2.7, col, {
        alpha: denseBoard ? 0.36 : 0.46,
        strokeColor: INK.paper,
        strokeWidth: 0.85,
      });
      continue;
    }

    if (!item.isRelated) {
      // Dim unrelated anchors cleanly so focused sightlines own the stage
      drawDiamondPip(graphics, item.anchorX, item.anchorY, 2.2, col, { alpha: 0.14 });
      continue;
    }

    // Focused owner-to-card illuminated bezier tether
    const fp = resolveActorPosition(actorPosFn, item.ownerCharId);
    if (!fp) {
      drawDiamondPip(graphics, item.anchorX, item.anchorY, 4.2, col, {
        alpha: 0.92,
        strokeColor: INK.paper,
        strokeWidth: 1.2,
      });
      continue;
    }

    const p0 = { x: fp.x, y: fp.y };
    const p1 = { x: item.anchorX, y: item.anchorY };
    const dist = Math.hypot(p1.x - p0.x, p1.y - p0.y);
    const archLift = clamp(dist * 0.11, 10, 36);
    const rawCp = {
      x: (p0.x + p1.x) * 0.5,
      y: (p0.y + p1.y) * 0.5 - archLift,
    };
    const cp = clampControlPointToViewport(p0, rawCp, p1, vp, 8);

    // Outer luminous halo + crisp core stroke
    graphics.moveTo(p0.x, p0.y)
      .quadraticCurveTo(cp.x, cp.y, p1.x, p1.y)
      .stroke({ width: 6.2, color: col, alpha: 0.15, cap: 'round' });
    graphics.moveTo(p0.x, p0.y)
      .quadraticCurveTo(cp.x, cp.y, p1.x, p1.y)
      .stroke({ width: 2.25, color: col, alpha: 0.88, cap: 'round' });

    // Origin fighter seal & card-socket pressmark
    const pulseR = 6.2 + Math.sin(time * 5.2 + i) * 1.1;
    graphics.circle(p0.x, p0.y, pulseR)
      .fill({ color: INK.paper, alpha: 0.35 })
      .stroke({ width: 1.6, color: col, alpha: 0.82 });
    graphics.circle(p0.x, p0.y, 2.6).fill({ color: col, alpha: 0.95 });

    drawDiamondPip(graphics, p1.x, p1.y, 4.3, col, {
      alpha: 0.96,
      strokeColor: INK.paper,
      strokeWidth: 1.25,
    });

    // Travelling pulse beads along the bezier curve
    drawTravellingPulses(graphics, p0, cp, p1, {
      count: dist > 260 ? 3 : 2,
      speed: 0.62,
      time,
      color: col,
      radius: 3.1,
      alpha: 0.94,
      phaseOffset: i * 0.23,
    });

    // Subtle highlighted card well frame inside viewport
    if (item.well) {
      const rx = item.well.x - 2;
      const ry = vp ? Math.max(vp.top + 2, item.well.y - 2) : item.well.y - 2;
      const rb = vp ? Math.min(vp.bottom - 2, item.well.y + item.well.h + 2) : item.well.y + item.well.h + 2;
      if (rb - ry > 12) {
        graphics.roundRect(rx, ry, item.well.w + 4, rb - ry, 9)
          .stroke({ width: 1.8, color: col, alpha: 0.48 + Math.sin(time * 6) * 0.16 });
      }
    }
  }

  // Focused Clash Bridge across opposing regular duel cards (when focused duel has both sides visible)
  if (hasFocus && regMap) {
    for (const [duelNum] of focusedDuelSides.entries()) {
      const w1 = regMap.get(`${duelNum}:1`);
      const w2 = regMap.get(`${duelNum}:2`);
      if (!isRectInViewport(w1, vp, 8) || !isRectInViewport(w2, vp, 8)) continue;
      const duelObj = duels.find((d) => d && d.number === duelNum);
      const hasS1 = duelObj?.sides?.some((s) => s.side === 1 && s.cards?.length > 0);
      const hasS2 = duelObj?.sides?.some((s) => s.side === 2 && s.cards?.length > 0);
      if (!hasS1 || !hasS2) continue;

      const b0 = { x: w1.x + w1.w + 2, y: w1.cy };
      const b1 = { x: w2.x - 2, y: w2.cy };
      const midX = (b0.x + b1.x) * 0.5;
      const midY = (b0.y + b1.y) * 0.5;
      const bCp = { x: midX, y: midY };

      graphics.moveTo(b0.x, b0.y).lineTo(b1.x, b1.y)
        .stroke({ width: 5, color: INK.gold, alpha: 0.2, cap: 'round' });
      graphics.moveTo(b0.x, b0.y).lineTo(b1.x, b1.y)
        .stroke({ width: 2, color: INK.gold, alpha: 0.9, cap: 'round' });
      drawTravellingPulses(graphics, b0, bCp, b1, {
        count: 2,
        speed: 0.9,
        time,
        color: INK.gold,
        radius: 2.6,
        alpha: 0.92,
        viewport: vp,
      });
    }
  }

  // ── Layer 2: Pre-Reveal Active Attack & Intercept Sightlines ──
  if (preMap && Array.isArray(preDuels)) {
    for (let idx = 0; idx < preDuels.length; idx++) {
      const slot = preDuels[idx];
      if (!slot) continue;
      const from = preMap.get(slot.number);
      if (!from) continue;

      const slotCharIds = [];
      for (const sEntry of slot.sides || []) {
        for (const c of sEntry.cards || []) {
          if (c && c.character_id) slotCharIds.push({ charId: c.character_id, side: sEntry.side });
        }
      }

      const isFocusedSlot = Boolean(
        (effectivePreDuel != null && slot.number === effectivePreDuel)
        || (effectiveCharId != null && (
          slotCharIds.some((sc) => sc.charId === effectiveCharId)
          || slot.target?.id === effectiveCharId
        ))
        || (effectiveRegDuel != null && slot.target?.kind === 'duel' && slot.target.number === effectiveRegDuel)
      );

      const baseCol = slot.ready ? PALETTE.jade : PALETTE.crimson;

      // Intercepted pre-reveal duel: crisp interlocking golden-emerald shield-clash crest on the slot
      if (slot.target?.kind === 'intercept') {
        const alpha = !hasFocus ? 0.52 : isFocusedSlot ? 0.94 : 0.18;
        const cy = from.cy;
        graphics.roundRect(from.x - 2, from.y - 2, from.w + 4, from.h + 4, 9)
          .stroke({ width: isFocusedSlot ? 2.4 : 1.3, color: PALETTE.jade, alpha });
        drawDiamondPip(graphics, from.cx, cy, isFocusedSlot ? 5.2 : 3.4, INK.gold, {
          alpha,
          strokeColor: INK.paper,
          strokeWidth: 1.1,
        });
        continue;
      }

      // Resolve target endpoint strictly guarding against duelViewport
      let to = null;
      let clippedEdge = null; // 'top' | 'bottom' | null
      if (slot.target?.kind === 'duel' && regMap) {
        const defenderSide = slot.attacking_side ? (3 - slot.attacking_side) : 2;
        const rawTo = regMap.get(`${slot.target.number}:${defenderSide}`);
        if (rawTo) {
          if (vp && rawTo.cy < vp.top + 8) {
            to = { x: rawTo.cx, y: vp.top + 10 };
            clippedEdge = 'top';
          } else if (vp && rawTo.cy > vp.bottom - 8) {
            to = { x: rawTo.cx, y: vp.bottom - 10 };
            clippedEdge = 'bottom';
          } else {
            to = { x: rawTo.cx, y: rawTo.cy };
          }
        }
      } else if (slot.target?.kind === 'character') {
        const fp = resolveActorPosition(actorPosFn, slot.target.id, slot.target.name);
        if (fp) to = { x: fp.x, y: fp.y };
      }

      if (to) {
        const p0 = { x: from.cx, y: from.y + from.h - 4 };
        const dist = Math.hypot(to.x - p0.x, to.y - p0.y);
        const arcBend = clamp(dist * 0.14, 16, 48);
        const rawCp = {
          x: (p0.x + to.x) * 0.5,
          y: Math.min(p0.y, to.y) - arcBend * 0.45 + Math.abs(to.x - p0.x) * 0.04,
        };
        const cp = clampControlPointToViewport(p0, rawCp, to, vp, 8);

        if (!hasFocus) {
          // Idle: ultra-clean, subtle pre-reveal threat arc (readable even with multiple pre-reveals!)
          graphics.moveTo(p0.x, p0.y)
            .quadraticCurveTo(cp.x, cp.y, to.x, to.y)
            .stroke({ width: 1.8, color: baseCol, alpha: 0.46, cap: 'round' });
          const endTangent = evalQuadBezier(p0, cp, to, 0.96);
          if (clippedEdge) {
            drawViewportClipCaret(graphics, to.x, to.y, clippedEdge === 'top', baseCol, 0.68);
          } else {
            drawArrowDart(graphics, to.x, to.y, endTangent.dx, endTangent.dy, 7.5, baseCol, 0.7);
          }
          drawTravellingPulses(graphics, p0, cp, to, {
            count: 1,
            speed: 0.42,
            time,
            color: baseCol,
            radius: 2.5,
            alpha: 0.62,
            phaseOffset: idx * 0.31,
          });
        } else if (isFocusedSlot) {
          // Focused: vivid spotlight arc with warm glow + animated energy beads + precision reticle
          graphics.moveTo(p0.x, p0.y)
            .quadraticCurveTo(cp.x, cp.y, to.x, to.y)
            .stroke({ width: 6.8, color: baseCol, alpha: 0.18, cap: 'round' });
          graphics.moveTo(p0.x, p0.y)
            .quadraticCurveTo(cp.x, cp.y, to.x, to.y)
            .stroke({ width: 2.7, color: baseCol, alpha: 0.94, cap: 'round' });
          const endTangent = evalQuadBezier(p0, cp, to, 0.96);
          if (clippedEdge) {
            drawViewportClipCaret(graphics, to.x, to.y, clippedEdge === 'top', baseCol, 0.95);
          } else {
            graphics.circle(to.x, to.y, 8 + Math.sin(time * 7) * 1.4)
              .stroke({ width: 1.7, color: baseCol, alpha: 0.78 });
            drawArrowDart(graphics, to.x, to.y, endTangent.dx, endTangent.dy, 10, baseCol, 0.96);
          }
          drawTravellingPulses(graphics, p0, cp, to, {
            count: 3,
            speed: 0.72,
            time,
            color: baseCol,
            radius: 3.4,
            alpha: 0.96,
            phaseOffset: idx * 0.19,
          });
        } else {
          // Unrelated pre-reveal while another unit/duel is focused
          graphics.moveTo(p0.x, p0.y)
            .quadraticCurveTo(cp.x, cp.y, to.x, to.y)
            .stroke({ width: 1.2, color: baseCol, alpha: 0.16, cap: 'round' });
        }
      }

      // If this pre-reveal slot is focused, also illuminate owner-to-pre-reveal-card tether
      if (hasFocus && isFocusedSlot) {
        for (const sc of slotCharIds) {
          const fp = resolveActorPosition(actorPosFn, sc.charId);
          if (!fp) continue;
          const col = (themes[sc.side] || SIDE_THEME[sc.side] || SIDE_THEME[1]).accent;
          const anchorX = sc.side === 1 ? from.x + 4 : from.x + from.w - 4;
          const anchorY = from.cy;
          const cp = { x: (fp.x + anchorX) * 0.5, y: Math.min(fp.y, anchorY) - 22 };
          graphics.moveTo(fp.x, fp.y)
            .quadraticCurveTo(cp.x, cp.y, anchorX, anchorY)
            .stroke({ width: 2.1, color: col, alpha: 0.85, cap: 'round' });
          drawTravellingPulses(graphics, fp, cp, { x: anchorX, y: anchorY }, {
            count: 2,
            speed: 0.65,
            time,
            color: col,
            radius: 2.8,
            alpha: 0.9,
          });
        }
      }
    }
  }

  // ── Layer 3: Live Drag Tactical Aiming Choreography ──
  if (isDragging) {
    const { startX, startY, x, y, canAttack, canIntercept, side } = dragState;
    const pulse = 0.72 + Math.sin(time * 9.5) * 0.24;
    const theme = themes[side] || SIDE_THEME[side] || SIDE_THEME[1];

    // Subtle fighter-to-drag-origin tether so player feels who is acting
    if (dragCharId) {
      const fp = resolveActorPosition(actorPosFn, dragCharId);
      if (fp) {
        const cp = { x: (fp.x + x) * 0.5, y: Math.min(fp.y, y) - 28 };
        graphics.moveTo(fp.x, fp.y)
          .quadraticCurveTo(cp.x, cp.y, x, y)
          .stroke({ width: 1.8, color: theme.accent, alpha: 0.42, cap: 'round' });
        graphics.circle(fp.x, fp.y, 6.5).stroke({ width: 1.6, color: theme.accent, alpha: 0.75 });
      }
    }

    if (canAttack || canIntercept) {
      const arcCol = canAttack && !canIntercept ? PALETTE.crimson : INK.gold;
      const p0 = { x: startX, y: startY };
      const p1 = { x, y };
      const cp = {
        x: (startX + x) * 0.5,
        y: Math.min(startY, y) - clamp(Math.hypot(x - startX, y - startY) * 0.22, 26, 76),
      };

      graphics.moveTo(p0.x, p0.y)
        .quadraticCurveTo(cp.x, cp.y, p1.x, p1.y)
        .stroke({ width: 7.5, color: arcCol, alpha: 0.16, cap: 'round' });
      graphics.moveTo(p0.x, p0.y)
        .quadraticCurveTo(cp.x, cp.y, p1.x, p1.y)
        .stroke({ width: 2.8, color: arcCol, alpha: 0.92, cap: 'round' });

      drawTravellingPulses(graphics, p0, cp, p1, {
        count: 3,
        speed: 0.95,
        time,
        color: arcCol,
        radius: 3.6,
        alpha: 0.96,
      });

      // Precision rotating tabletop reticle at pointer
      const rot = time * 1.9;
      const rOuter = 11.5 + Math.sin(time * 8) * 1.2;
      graphics.circle(x, y, rOuter).stroke({ width: 1.8, color: arcCol, alpha: 0.92 });
      graphics.circle(x, y, 3.2).fill({ color: arcCol, alpha: 0.95 });
      for (let k = 0; k < 4; k++) {
        const a = rot + (k * Math.PI) / 2;
        graphics.moveTo(x + Math.cos(a) * (rOuter - 3), y + Math.sin(a) * (rOuter - 3))
          .lineTo(x + Math.cos(a) * (rOuter + 4.5), y + Math.sin(a) * (rOuter + 4.5))
          .stroke({ width: 1.7, color: arcCol, alpha: 0.92, cap: 'round' });
      }
    } else if (dragState.targetDuelNumber != null && regMap) {
      // Placement drop-well corner brackets (strictly inside duelViewport!)
      const well = regMap.get(`${dragState.targetDuelNumber}:${side || 1}`);
      if (well && well.visible !== false && (!vp || (well.y >= vp.top - 4 && well.y + well.h <= vp.bottom + 4))) {
        const bx = well.x - 4;
        const by = well.y - 4;
        const bw = well.w + 8;
        const bh = well.h + 8;
        const arm = 14;
        graphics.roundRect(bx, by, bw, bh, 11)
          .fill({ color: theme.softBg || INK.goldBg, alpha: 0.22 * pulse })
          .stroke({ width: 2.2, color: theme.accent, alpha: pulse });
        const corners = [
          [bx, by + arm, bx, by, bx + arm, by],
          [bx + bw - arm, by, bx + bw, by, bx + bw, by + arm],
          [bx + bw, by + bh - arm, bx + bw, by + bh, bx + bw - arm, by + bh],
          [bx + arm, by + bh, bx, by + bh, bx, by + bh - arm],
        ];
        for (const c of corners) {
          graphics.moveTo(c[0], c[1]).lineTo(c[2], c[3]).lineTo(c[4], c[5])
            .stroke({ width: 3, color: INK.gold, alpha: 0.9, cap: 'round', join: 'round' });
        }
      }
    }
  }
}

// ── Vector Pressmark Glyphs for Diegetic Top Bar Seals ──

function drawSealIcon(g, iconKey, cx, cy, r, color, { active = false, muted = false } = {}) {
  if (iconKey === 'auto') {
    g.poly([
      cx - r * 0.65, cy - r * 0.65,
      cx + r * 0.08, cy,
      cx - r * 0.65, cy + r * 0.65,
    ]).fill({ color, alpha: active ? 0.98 : 0.88 });
    g.poly([
      cx + r * 0.02, cy - r * 0.65,
      cx + r * 0.78, cy,
      cx + r * 0.02, cy + r * 0.65,
    ]).fill({ color, alpha: active ? 0.98 : 0.56 });
  } else if (iconKey === 'audio') {
    g.poly([
      cx - r * 0.72, cy - r * 0.28,
      cx - r * 0.34, cy - r * 0.28,
      cx + r * 0.08, cy - r * 0.68,
      cx + r * 0.08, cy + r * 0.68,
      cx - r * 0.34, cy + r * 0.28,
      cx - r * 0.72, cy + r * 0.28,
    ]).fill({ color, alpha: muted ? 0.58 : 0.9 });
    if (muted) {
      g.moveTo(cx + r * 0.24, cy - r * 0.42).lineTo(cx + r * 0.78, cy + r * 0.42)
        .stroke({ width: 1.6, color, alpha: 0.85, cap: 'round' });
      g.moveTo(cx + r * 0.78, cy - r * 0.42).lineTo(cx + r * 0.24, cy + r * 0.42)
        .stroke({ width: 1.6, color, alpha: 0.85, cap: 'round' });
    } else {
      g.moveTo(cx + r * 0.32, cy - r * 0.36)
        .quadraticCurveTo(cx + r * 0.62, cy, cx + r * 0.32, cy + r * 0.36)
        .stroke({ width: 1.45, color, alpha: 0.9, cap: 'round' });
      g.moveTo(cx + r * 0.54, cy - r * 0.58)
        .quadraticCurveTo(cx + r * 0.92, cy, cx + r * 0.54, cy + r * 0.58)
        .stroke({ width: 1.25, color, alpha: 0.62, cap: 'round' });
    }
  } else if (iconKey === 'passives') {
    drawLightStar(g, cx, cy, r * 0.86, color, 0.95);
  } else if (iconKey === 'codex') {
    g.poly([
      cx - r * 0.8, cy - r * 0.52,
      cx - r * 0.06, cy - r * 0.38,
      cx - r * 0.06, cy + r * 0.58,
      cx - r * 0.8, cy + r * 0.44,
    ]).stroke({ width: 1.4, color, alpha: 0.9, join: 'round' });
    g.poly([
      cx + r * 0.8, cy - r * 0.52,
      cx + r * 0.06, cy - r * 0.38,
      cx + r * 0.06, cy + r * 0.58,
      cx + r * 0.8, cy + r * 0.44,
    ]).stroke({ width: 1.4, color, alpha: 0.9, join: 'round' });
    g.moveTo(cx, cy - r * 0.42).lineTo(cx, cy + r * 0.62)
      .stroke({ width: 1.4, color, alpha: 0.9 });
  } else if (iconKey === 'roster') {
    g.poly([
      cx - r * 0.66, cy - r * 0.64,
      cx - r * 0.06, cy - r * 0.64,
      cx - r * 0.06, cy + r * 0.36,
      cx - r * 0.36, cy + r * 0.68,
      cx - r * 0.66, cy + r * 0.36,
    ]).fill({ color, alpha: 0.22 }).stroke({ width: 1.35, color, alpha: 0.92 });
    g.poly([
      cx + r * 0.06, cy - r * 0.64,
      cx + r * 0.66, cy - r * 0.64,
      cx + r * 0.66, cy + r * 0.36,
      cx + r * 0.36, cy + r * 0.68,
      cx + r * 0.06, cy + r * 0.36,
    ]).fill({ color, alpha: 0.22 }).stroke({ width: 1.35, color, alpha: 0.92 });
  }
}

function drawChamferedPlaque(g, x, y, w, h, cut = 6) {
  const c = Math.min(cut, w * 0.25, h * 0.45);
  return g.poly([
    x + c, y,
    x + w - c, y,
    x + w, y + c,
    x + w, y + h - c,
    x + w - c, y + h,
    x + c, y + h,
    x, y + h - c,
    x, y + c,
  ]);
}

function phaseAccentForLabel(phaseLabel) {
  const s = String(phaseLabel || '');
  if (s.includes('交锋') || s.includes('拼点') || s.includes('结算') || s.includes('战斗')) {
    return { accent: PALETTE.crimson, wash: PALETTE.crimsonWash, border: 0xe08270 };
  }
  if (s.includes('开牌前') || s.includes('攻防') || s.includes('迎击') || s.includes('拦截')) {
    return { accent: TRAIT_STYLE.pre_reveal.color, wash: TRAIT_STYLE.pre_reveal.bg, border: TRAIT_STYLE.pre_reveal.border };
  }
  if (s.includes('扣置') || s.includes('置牌') || s.includes('出牌')) {
    return { accent: PALETTE.jade, wash: PALETTE.jadeWash, border: SIDE_THEME[1].border };
  }
  return { accent: INK.gold, wash: INK.goldBg, border: PALETTE.brassSoft };
}

/**
 * 2. Persistent Tabletop Battle Chronicle Crest & Brass Pressmark Seal Strip.
 *
 * Replaces the "website navbar capsule strip" with an engraved ceremonial Turn & Phase seal
 * on the left and persistent iconographic brass/parchment pressmarks (`自动`, `音效`, `被动`,
 * `典籍`, `编队`) on the right.
 *
 * ZERO destroy/rebuild on toggle or phase change — call `sync(...)` freely!
 */
export function createDiegeticTopBar({
  width = 1280,
  pad = 16,
  onToggleAuto = null,
  onToggleMute = null,
  onTogglePassives = null,
  onOpenCodex = null,
  onOpenRoster = null,
} = {}) {
  const root = new PIXI.Container();
  let curWidth = Math.max(480, width);
  let curPad = pad;
  const barY = 8;
  const barH = 34;

  // ── Left Ceremonial Chronicle Crest (Persistent) ──
  const crestGroup = new PIXI.Container();
  crestGroup.position.set(curPad, barY);

  const crestBg = new PIXI.Graphics();
  const turnText = new PIXI.Text({
    text: '第 1 回合',
    style: { fontFamily: FONT_NUM, fontSize: 12.2, fontWeight: '900', fill: INK.strong },
  });
  turnText.anchor.set(0, 0.5);

  const phaseText = new PIXI.Text({
    text: '',
    style: { fontFamily: FONT_UI, fontSize: 12.2, fontWeight: '800', fill: INK.primary },
  });
  phaseText.anchor.set(0, 0.5);

  const initText = new PIXI.Text({
    text: '',
    style: { fontFamily: FONT_UI, fontSize: 11.2, fontWeight: '800', fill: SIDE_THEME[1].accent },
  });
  initText.anchor.set(0, 0.5);

  crestGroup.addChild(crestBg, turnText, phaseText, initText);
  root.addChild(crestGroup);

  // ── Right Brass/Parchment Pressmark Seal Strip (Persistent) ──
  const trayGroup = new PIXI.Container();
  const trayBg = new PIXI.Graphics();
  trayGroup.addChild(trayBg);
  root.addChild(trayGroup);

  const sealSpecs = [
    { key: 'auto', label: '自动', width: 64, activeAccent: PALETTE.jade, accent: INK.secondary, onClick: onToggleAuto },
    { key: 'audio', label: '音效', width: 62, activeAccent: INK.secondary, accent: INK.secondary, onClick: onToggleMute },
    { key: 'passives', label: '被动', width: 62, activeAccent: INK.gold, accent: INK.goldDeep, onClick: onTogglePassives },
    { key: 'codex', label: '典籍', width: 62, activeAccent: INK.gold, accent: INK.goldDeep, onClick: onOpenCodex },
    { key: 'roster', label: '编队', width: 62, activeAccent: PALETTE.jade, accent: PALETTE.jade, onClick: onOpenRoster },
  ];

  const sealH = 26;
  const sealGap = 5;
  const trayPadX = 6;
  const trayPadY = 4;
  const sealNodes = new Map();

  let cursorX = trayPadX;
  for (const spec of sealSpecs) {
    const btn = new PIXI.Container();
    btn.position.set(cursorX, trayPadY);
    btn.eventMode = 'static';
    btn.cursor = 'pointer';

    const bg = new PIXI.Graphics();
    const labelTxt = new PIXI.Text({
      text: spec.label,
      style: { fontFamily: FONT_UI, fontSize: 11.2, fontWeight: '800', fill: INK.primary },
    });
    labelTxt.anchor.set(0, 0.5);
    labelTxt.position.set(24, sealH / 2 + 0.5);
    btn.addChild(bg, labelTxt);

    const state = {
      hovered: false,
      pressed: false,
      active: false,
      muted: false,
    };

    const redrawBtn = () => {
      bg.clear();
      const w = spec.width;
      const h = sealH;
      const yOff = state.pressed ? 1 : 0;
      const isSolid = state.active;
      const isMuted = state.muted;
      const accent = isSolid ? spec.activeAccent : isMuted ? INK.muted : spec.accent;
      const fillCol = isSolid
        ? spec.activeAccent
        : state.hovered
          ? PALETTE.hoverPaper
          : isMuted
            ? INK.paperSoft
            : INK.paper;
      const strokeCol = isSolid
        ? (spec.key === 'passives' ? PALETTE.brassDeep : PALETTE.jadeDeep)
        : state.hovered
          ? accent
          : INK.line;

      if (!state.pressed) {
        drawChamferedPlaque(bg, 0, 2, w, h, 4.5).fill({ color: isSolid ? INK.shadow : PALETTE.bevel, alpha: isSolid ? 0.36 : 0.9 });
      }
      drawChamferedPlaque(bg, 0, yOff, w, h, 4.5)
        .fill({ color: fillCol, alpha: isSolid ? 0.98 : 0.96 })
        .stroke({ width: state.hovered || isSolid ? 1.35 : 1.0, color: strokeCol, alpha: isMuted ? 0.65 : 0.92 });

      bg.moveTo(5, yOff + 1.5).lineTo(w - 5, yOff + 1.5)
        .stroke({ width: 0.8, color: isSolid ? INK.paper : PALETTE.brassSoft, alpha: isSolid ? 0.32 : 0.55 });

      const iconCol = isSolid ? INK.paper : isMuted ? INK.muted : accent;
      drawSealIcon(bg, spec.key, 13.5, yOff + h / 2, 6.2, iconCol, { active: isSolid, muted: isMuted });

      labelTxt.y = yOff + h / 2 + 0.5;
      labelTxt.style.fill = isSolid ? INK.paper : isMuted ? INK.muted : INK.primary;
    };

    btn.on('pointerover', () => {
      state.hovered = true;
      redrawBtn();
    });
    btn.on('pointerout', () => {
      state.hovered = false;
      state.pressed = false;
      redrawBtn();
    });
    btn.on('pointerdown', (e) => {
      e.stopPropagation();
      state.pressed = true;
      redrawBtn();
    });
    btn.on('pointerup', (e) => {
      e.stopPropagation();
      state.pressed = false;
      redrawBtn();
    });
    btn.on('pointerupoutside', () => {
      state.pressed = false;
      redrawBtn();
    });
    btn.on('pointertap', (e) => {
      e.stopPropagation();
      if (typeof spec.onClick === 'function') spec.onClick();
    });

    redrawBtn();
    trayGroup.addChild(btn);
    sealNodes.set(spec.key, { btn, state, redrawBtn, labelTxt, spec });
    cursorX += spec.width + sealGap;
  }

  const trayW = cursorX - sealGap + trayPadX;
  const trayH = sealH + trayPadY * 2;

  const drawTray = () => {
    trayBg.clear();
    drawChamferedPlaque(trayBg, 2, 3, trayW, trayH, 6).fill({ color: INK.shadow, alpha: 0.18 });
    drawChamferedPlaque(trayBg, 0, 0, trayW, trayH, 6)
      .fill({ color: INK.paperSoft, alpha: 0.94 })
      .stroke({ width: 1.15, color: INK.line });
    drawDiamondPip(trayBg, 3.5, trayH / 2, 1.8, PALETTE.brassSoft, { alpha: 0.9 });
    drawDiamondPip(trayBg, trayW - 3.5, trayH / 2, 1.8, PALETTE.brassSoft, { alpha: 0.9 });
  };
  drawTray();

  const lastSync = {
    turn: 1,
    phaseLabel: '',
    firstSide: null,
    autoPace: false,
    muted: false,
    passivesOpen: false,
  };

  const layoutBar = () => {
    const rightX = Math.max(curPad + 220, curWidth - curPad - trayW);
    trayGroup.position.set(rightX, barY);
    crestGroup.position.set(curPad, barY);

    const maxCrestW = Math.max(180, rightX - curPad - 12);
    const turnVal = lastSync.turn || 1;
    turnText.text = `第 ${turnVal} 回合`;
    const phaseStr = lastSync.phaseLabel ? String(lastSync.phaseLabel) : '';
    phaseText.text = phaseStr;

    const firstTheme = lastSync.firstSide ? (SIDE_THEME[lastSync.firstSide] || null) : null;
    const hasInit = Boolean(firstTheme);
    initText.visible = hasInit;
    if (hasInit) {
      initText.text = `${firstTheme.name}先手`;
      initText.style.fill = firstTheme.accent;
    }

    const phaseStyle = phaseAccentForLabel(phaseStr);
    phaseText.style.fill = phaseStyle.accent;

    const starCx = 18;
    const cy = barH / 2;
    let cx = 32;

    turnText.position.set(cx, cy + 0.5);
    cx += Math.ceil(turnText.width) + 12;

    const div1X = cx;
    if (phaseStr) {
      cx += 14;
      phaseText.position.set(cx, cy + 0.5);
      cx += Math.ceil(phaseText.width) + 12;
    }

    const div2X = cx;
    let showInit = false;
    if (hasInit && cx + 22 + Math.ceil(initText.width) + 14 <= maxCrestW) {
      showInit = true;
      cx += 18;
      initText.position.set(cx, cy + 0.5);
      cx += Math.ceil(initText.width) + 14;
    }
    initText.visible = showInit;

    const crestW = Math.min(maxCrestW, Math.max(140, cx + 6));
    crestBg.clear();

    drawChamferedPlaque(crestBg, 2, 3.5, crestW, barH, 7).fill({ color: INK.shadow, alpha: 0.22 });
    drawChamferedPlaque(crestBg, 0, 1.8, crestW, barH, 7).fill({ color: PALETTE.bevel });
    drawChamferedPlaque(crestBg, 0, 0, crestW, barH, 7)
      .fill({ color: INK.paper, alpha: 0.98 })
      .stroke({ width: 1.35, color: PALETTE.brassSoft });

    drawChamferedPlaque(crestBg, 2.5, 2.5, crestW - 5, barH - 5, 5)
      .stroke({ width: 0.75, color: INK.hairline, alpha: 0.95 });

    crestBg.moveTo(10, 1.4).lineTo(crestW - 10, 1.4)
      .stroke({ width: 2.2, color: phaseStyle.accent, alpha: 0.78, cap: 'round' });

    crestBg.circle(starCx, cy, 10.2)
      .fill({ color: INK.goldBg })
      .stroke({ width: 1.15, color: INK.gold, alpha: 0.85 });
    drawLightStar(crestBg, starCx, cy, 6.8, INK.gold, 0.96);

    if (phaseStr) {
      crestBg.moveTo(div1X, 8).lineTo(div1X, barH - 8)
        .stroke({ width: 1, color: INK.line, alpha: 0.9 });
      drawDiamondPip(crestBg, div1X + 7, cy, 3.0, phaseStyle.accent, { alpha: 0.92 });
      const pw = Math.ceil(phaseText.width) + 8;
      crestBg.roundRect(phaseText.x - 4, 6, pw, barH - 12, 3.5)
        .fill({ color: phaseStyle.wash, alpha: 0.85 });
      crestBg.moveTo(phaseText.x - 2, barH - 6.5).lineTo(phaseText.x + pw - 6, barH - 6.5)
        .stroke({ width: 1.2, color: phaseStyle.border, alpha: 0.82 });
    }

    if (showInit && firstTheme) {
      crestBg.moveTo(div2X, 8).lineTo(div2X, barH - 8)
        .stroke({ width: 1, color: INK.line, alpha: 0.9 });
      const ex = div2X + 10;
      crestBg.poly([
        ex - 3.6, cy - 4.2,
        ex + 4.2, cy,
        ex - 3.6, cy + 4.2,
        ex - 1.4, cy,
      ]).fill({ color: firstTheme.accent, alpha: 0.94 });
    }
  };

  const sync = ({
    turn = lastSync.turn,
    phaseLabel = lastSync.phaseLabel,
    firstSide = lastSync.firstSide,
    autoPace = lastSync.autoPace,
    muted = lastSync.muted,
    passivesOpen = lastSync.passivesOpen,
  } = {}) => {
    lastSync.turn = turn;
    lastSync.phaseLabel = phaseLabel;
    lastSync.firstSide = firstSide;
    lastSync.autoPace = Boolean(autoPace);
    lastSync.muted = Boolean(muted);
    lastSync.passivesOpen = Boolean(passivesOpen);

    const autoNode = sealNodes.get('auto');
    if (autoNode) {
      autoNode.state.active = lastSync.autoPace;
      autoNode.redrawBtn();
    }
    const audioNode = sealNodes.get('audio');
    if (audioNode) {
      audioNode.state.muted = lastSync.muted;
      audioNode.redrawBtn();
    }
    const passivesNode = sealNodes.get('passives');
    if (passivesNode) {
      passivesNode.state.active = lastSync.passivesOpen;
      passivesNode.redrawBtn();
    }

    layoutBar();
  };

  const resize = (nextWidth, nextPad = curPad) => {
    curWidth = Math.max(480, nextWidth || curWidth);
    curPad = nextPad ?? curPad;
    layoutBar();
  };

  root.container = root;
  root.sync = sync;
  root.resize = resize;
  root.setWidth = resize;
  root.getHeight = () => barY + barH;
  root._boxWidth = curWidth;
  root._boxHeight = barY + barH;

  sync(lastSync);
  return root;
}

// ── 3. Auto-Centering, Masked Scrollable Duel Progress Rail (1 to 40+ Duels!) ──

function duelKindStyle(kind) {
  if (kind === 'pre_reveal') {
    return { accent: TRAIT_STYLE.pre_reveal.color, wash: TRAIT_STYLE.pre_reveal.bg, border: TRAIT_STYLE.pre_reveal.border };
  }
  if (kind === 'instant') {
    return { accent: TRAIT_STYLE.anytime.color, wash: TRAIT_STYLE.anytime.bg, border: TRAIT_STYLE.anytime.border };
  }
  return { accent: INK.secondary, wash: INK.paper, border: INK.line };
}

function drawCrossedClashGlyph(g, cx, cy, r, color) {
  g.moveTo(cx - r * 0.72, cy + r * 0.72).lineTo(cx + r * 0.72, cy - r * 0.72)
    .stroke({ width: 1.55, color, cap: 'round' });
  g.moveTo(cx + r * 0.72, cy + r * 0.72).lineTo(cx - r * 0.72, cy - r * 0.72)
    .stroke({ width: 1.55, color, cap: 'round' });
  g.circle(cx, cy, r * 0.28).fill({ color });
}

/**
 * 3. Scalable, Auto-Centering Masked Duel Progress Rail.
 *
 * Cleanly renders 1 to dozens of pre-reveal, instant, and regular duels within `width`,
 * automatically keeping the active duel centered inside a masked viewport with subtle
 * brass left/right overflow chevrons and O(1) horizontal scrolling.
 */
export function buildScalableDuelRail({
  x = 0,
  y = 0,
  width = 640,
  items = [],
  activeKind = null,
  activeNumber = null,
  onSelect = null,
} = {}) {
  const root = new PIXI.Container();
  root.position.set(x, y);

  const W = Math.max(180, Math.round(width));
  const H = 32;
  const chipH = 24;
  const chipY = 3;
  const chipGap = 8;

  const list = Array.isArray(items) ? items : [];
  const activeIndex = list.findIndex((it) => it && it.kind === activeKind && it.number === activeNumber);

  // Subtle inlaid warm-paper brass track bar
  const frameG = new PIXI.Graphics();
  drawChamferedPlaque(frameG, 0, 1, W, H - 2, 6)
    .fill({ color: INK.paperSoft, alpha: 0.78 })
    .stroke({ width: 1, color: INK.hairline });
  root.addChild(frameG);

  // Measure & build chips so multi-digit labels ("常规12", "开牌前15") never clip
  const chipRecords = [];
  let rawCursorX = 0;

  for (let i = 0; i < list.length; i++) {
    const it = list[i];
    const isActive = i === activeIndex;
    const isPast = Boolean(it.done || it.resolved || (activeIndex >= 0 && i < activeIndex));
    const ks = duelKindStyle(it.kind);

    const labelStr = String(it.label || `${it.number ?? i + 1}`);
    const labelTxt = new PIXI.Text({
      text: labelStr,
      style: {
        fontFamily: FONT_UI,
        fontSize: isActive ? 11.2 : 10.6,
        fontWeight: isActive ? '900' : '800',
        fill: isActive ? INK.paper : isPast ? INK.muted : INK.primary,
      },
    });
    const iconSlot = isActive ? 15 : 10;
    const chipW = Math.max(64, Math.ceil(labelTxt.width) + iconSlot + 16);

    const chip = new PIXI.Container();
    chip.position.set(rawCursorX, chipY);

    const g = new PIXI.Graphics();
    if (isActive) {
      drawChamferedPlaque(g, 0, 2, chipW, chipH, 5).fill({ color: INK.shadow, alpha: 0.28 });
      drawChamferedPlaque(g, 0, 0, chipW, chipH, 5)
        .fill({ color: INK.gold })
        .stroke({ width: 1.5, color: PALETTE.brassDeep });
      g.moveTo(6, 1.6).lineTo(chipW - 6, 1.6)
        .stroke({ width: 0.9, color: INK.paper, alpha: 0.4 });
      g.poly([chipW / 2 - 4.5, chipH, chipW / 2 + 4.5, chipH, chipW / 2, chipH + 4.5])
        .fill({ color: INK.gold });
      drawCrossedClashGlyph(g, 12.5, chipH / 2, 4.6, INK.paper);
    } else {
      const fillCol = isPast ? INK.paperTint : ks.wash;
      const strokeCol = isPast ? INK.line : ks.border;
      drawChamferedPlaque(g, 0, 0, chipW, chipH, 5)
        .fill({ color: fillCol, alpha: isPast ? 0.85 : 0.96 })
        .stroke({ width: 1.05, color: strokeCol, alpha: isPast ? 0.72 : 0.92 });
      drawDiamondPip(g, 10, chipH / 2, isPast ? 2.2 : 2.8, isPast ? INK.muted : ks.accent, {
        alpha: isPast ? 0.65 : 0.92,
      });
    }

    labelTxt.anchor.set(0, 0.5);
    labelTxt.position.set(isActive ? 21 : 17, chipH / 2 + 0.5);
    chip.addChild(g, labelTxt);

    if (typeof onSelect === 'function') {
      chip.eventMode = 'static';
      chip.cursor = 'pointer';
      chip.on('pointertap', (e) => {
        e.stopPropagation();
        onSelect(it, i);
      });
    }

    chipRecords.push({
      item: it,
      index: i,
      node: chip,
      x: rawCursorX,
      w: chipW,
      cx: rawCursorX + chipW / 2,
    });
    rawCursorX += chipW + chipGap;
  }

  const totalW = chipRecords.length > 0 ? rawCursorX - chipGap : 0;
  const overflows = totalW > W - 16;
  const chevronZone = overflows ? 32 : 8;
  const viewX = chevronZone;
  const viewW = Math.max(60, W - chevronZone * 2);
  const maxScroll = Math.max(0, totalW - viewW);

  const maskG = new PIXI.Graphics();
  maskG.rect(viewX, 0, viewW, H + 4).fill({ color: PALETTE.maskFill });
  root.addChild(maskG);

  const track = new PIXI.Container();
  track.mask = maskG;
  root.addChild(track);

  if (chipRecords.length > 1) {
    const spineG = new PIXI.Graphics();
    const firstCx = chipRecords[0].cx;
    const lastCx = chipRecords[chipRecords.length - 1].cx;
    spineG.moveTo(firstCx, chipY + chipH / 2)
      .lineTo(lastCx, chipY + chipH / 2)
      .stroke({ width: 1.4, color: INK.line, alpha: 0.85 });
    if (activeIndex > 0) {
      spineG.moveTo(firstCx, chipY + chipH / 2)
        .lineTo(chipRecords[activeIndex].cx, chipY + chipH / 2)
        .stroke({ width: 1.8, color: PALETTE.brassSoft, alpha: 0.95 });
    }
    track.addChild(spineG);
  }

  for (const rec of chipRecords) {
    track.addChild(rec.node);
  }

  const leftCtrl = new PIXI.Container();
  const rightCtrl = new PIXI.Container();
  const leftBg = new PIXI.Graphics();
  const rightBg = new PIXI.Graphics();
  const leftCountTxt = new PIXI.Text({
    text: '',
    style: { fontFamily: FONT_NUM, fontSize: 9.2, fontWeight: '800', fill: INK.goldDeep },
  });
  leftCountTxt.anchor.set(0.5);
  const rightCountTxt = new PIXI.Text({
    text: '',
    style: { fontFamily: FONT_NUM, fontSize: 9.2, fontWeight: '800', fill: INK.goldDeep },
  });
  rightCountTxt.anchor.set(0.5);

  leftCtrl.addChild(leftBg, leftCountTxt);
  rightCtrl.addChild(rightBg, rightCountTxt);

  if (overflows) {
    leftCtrl.eventMode = 'static';
    leftCtrl.cursor = 'pointer';
    rightCtrl.eventMode = 'static';
    rightCtrl.cursor = 'pointer';
    root.addChild(leftCtrl, rightCtrl);
  }

  let scrollX = 0;

  const updateChevronUI = () => {
    if (!overflows) return;
    const canLeft = scrollX > 1;
    const canRight = scrollX < maxScroll - 1;

    let hiddenLeft = 0;
    let hiddenRight = 0;
    for (const rec of chipRecords) {
      if (rec.x + rec.w < scrollX + 4) hiddenLeft++;
      else if (rec.x > scrollX + viewW - 4) hiddenRight++;
    }

    leftBg.clear();
    leftCtrl.visible = canLeft;
    if (canLeft) {
      leftBg.rect(viewX, 2, 12, H - 4).fill({ color: INK.paperSoft, alpha: 0.68 });
      drawChamferedPlaque(leftBg, 3, 4, chevronZone - 6, H - 8, 4)
        .fill({ color: INK.paper, alpha: 0.96 })
        .stroke({ width: 1.1, color: PALETTE.brassSoft });
      const cx = 10;
      const cy = H / 2;
      leftBg.moveTo(cx + 2.5, cy - 4.2).lineTo(cx - 2.2, cy).lineTo(cx + 2.5, cy + 4.2)
        .stroke({ width: 1.7, color: INK.goldDeep, cap: 'round', join: 'round' });
      leftCountTxt.text = hiddenLeft > 0 ? String(hiddenLeft) : '';
      leftCountTxt.position.set(chevronZone - 10, cy + 0.5);
    }

    rightBg.clear();
    rightCtrl.visible = canRight;
    if (canRight) {
      const rx = W - chevronZone;
      rightBg.rect(viewX + viewW - 12, 2, 12, H - 4).fill({ color: INK.paperSoft, alpha: 0.68 });
      drawChamferedPlaque(rightBg, rx + 3, 4, chevronZone - 6, H - 8, 4)
        .fill({ color: INK.paper, alpha: 0.96 })
        .stroke({ width: 1.1, color: PALETTE.brassSoft });
      const cx = W - 10;
      const cy = H / 2;
      rightBg.moveTo(cx - 2.5, cy - 4.2).lineTo(cx + 2.2, cy).lineTo(cx - 2.5, cy + 4.2)
        .stroke({ width: 1.7, color: INK.goldDeep, cap: 'round', join: 'round' });
      rightCountTxt.text = hiddenRight > 0 ? String(hiddenRight) : '';
      rightCountTxt.position.set(rx + 10, cy + 0.5);
    }
  };

  const setScroll = (nextX) => {
    if (!overflows) {
      scrollX = 0;
      track.x = viewX + Math.floor((viewW - totalW) / 2);
    } else {
      scrollX = clamp(nextX, 0, maxScroll);
      track.x = Math.round(viewX - scrollX);
    }
    updateChevronUI();
  };

  const centerOnIndex = (idx) => {
    if (!overflows || idx < 0 || idx >= chipRecords.length) {
      setScroll(0);
      return;
    }
    const targetRec = chipRecords[idx];
    setScroll(targetRec.cx - viewW / 2);
  };

  const centerOn = (kind, number) => {
    const idx = chipRecords.findIndex((r) => r.item.kind === kind && r.item.number === number);
    if (idx >= 0) centerOnIndex(idx);
  };

  if (overflows) {
    const step = Math.max(90, Math.round(viewW * 0.45));
    leftCtrl.on('pointertap', (e) => {
      e.stopPropagation();
      setScroll(scrollX - step);
    });
    rightCtrl.on('pointertap', (e) => {
      e.stopPropagation();
      setScroll(scrollX + step);
    });
  }

  if (activeIndex >= 0) centerOnIndex(activeIndex);
  else setScroll(0);

  root.setScroll = setScroll;
  root.scrollBy = (deltaX) => setScroll(scrollX + deltaX);
  root.centerOn = centerOn;
  root.getMetrics = () => ({
    width: W,
    height: H,
    totalW,
    maxScroll,
    scrollX,
    activeIndex,
    overflows,
  });
  root._boxWidth = W;
  root._boxHeight = H;
  return root;
}

// ── 4. Tactile Weighted Hitstop & Floating Callout Banner Builder ──

function normalizeBannerKind(kind) {
  const k = String(kind || 'clash').toLowerCase();
  if (k === 'status' || k === 'tick' || k === 'quiet') return 'status';
  if (k === 'passive' || k === 'crest') return 'passive';
  if (k === 'shield' || k === 'shield_break' || k === 'break') return 'shield';
  if (k === 'heavy' || k === 'impact' || k === 'crit' || k === 'ko') return 'heavy';
  return 'clash';
}

/**
 * 4. Tactile Weighted Floating Callout / Hitstop Banner Builder.
 *
 * Differentiated visual hierarchy:
 *  - `'status'`  : Quiet status tick (slim sunlit parchment slip, hairline rule, diamond pip)
 *  - `'passive'` : Crisp gold passive crest (chamfered heraldic ribbon with flanking light stars)
 *  - `'shield'`  : Shield break / wear callout (hexagonal bevel banner + fractured shield glyph)
 *  - `'heavy'`   : Bold crimson impact callout (high-weight angular war-seal with flared ink wingtips)
 *  - `'clash'`   : Ceremonial clash banner (warm ivory stock, brass bevel, top crown bar & rivets)
 */
export function buildHitstopBanner({
  text = '',
  accentColor = null,
  kind = 'clash',
  x = 0,
  y = 0,
} = {}) {
  const root = new PIXI.Container();
  root.position.set(x, y);

  const normalized = normalizeBannerKind(kind);
  const label = String(text || '');
  const g = new PIXI.Graphics();
  root.addChild(g);

  let W = 120;
  let H = 28;

  if (normalized === 'status') {
    const col = accentColor ?? INK.secondary;
    const txt = new PIXI.Text({
      text: label,
      style: { fontFamily: FONT_UI, fontSize: 12, fontWeight: '800', fill: col },
    });
    W = Math.ceil(txt.width) + 26;
    H = 22;
    const hw = W / 2;
    const hh = H / 2;

    g.roundRect(-hw + 1, -hh + 2, W, H, 5).fill({ color: INK.shadow, alpha: 0.14 });
    g.roundRect(-hw, -hh, W, H, 5)
      .fill({ color: INK.paperSoft, alpha: 0.94 })
      .stroke({ width: 0.95, color: INK.line });
    g.moveTo(-hw + 6, hh - 0.8).lineTo(hw - 6, hh - 0.8)
      .stroke({ width: 1.4, color: col, alpha: 0.65, cap: 'round' });
    drawDiamondPip(g, -hw + 10, 0, 2.7, col, { alpha: 0.92 });

    txt.anchor.set(0, 0.5);
    txt.position.set(-hw + 17, 0.5);
    root.addChild(txt);
  } else if (normalized === 'passive') {
    const col = accentColor ?? INK.gold;
    const txt = new PIXI.Text({
      text: label,
      style: { fontFamily: FONT_UI, fontSize: 13.4, fontWeight: '900', fill: INK.goldDeep },
    });
    W = Math.ceil(txt.width) + 52;
    H = 30;
    const hw = W / 2;
    const hh = H / 2;

    g.poly([
      -hw - 9, 0,
      -hw + 2, -hh + 5,
      -hw + 2, hh - 5,
    ]).fill({ color: col, alpha: 0.88 });
    g.poly([
      hw + 9, 0,
      hw - 2, -hh + 5,
      hw - 2, hh - 5,
    ]).fill({ color: col, alpha: 0.88 });

    drawChamferedPlaque(g, -hw + 2, -hh + 3.5, W, H, 7).fill({ color: INK.shadow, alpha: 0.24 });
    drawChamferedPlaque(g, -hw, -hh + 1.8, W, H, 7).fill({ color: PALETTE.brassSoft });
    drawChamferedPlaque(g, -hw, -hh, W, H, 7)
      .fill({ color: INK.goldBg, alpha: 0.98 })
      .stroke({ width: 1.55, color: col });
    drawChamferedPlaque(g, -hw + 3, -hh + 3, W - 6, H - 6, 5)
      .stroke({ width: 0.85, color: col, alpha: 0.45 });

    drawLightStar(g, -hw + 14, 0, 6.4, col, 0.96);
    drawLightStar(g, hw - 14, 0, 6.4, col, 0.96);

    txt.anchor.set(0.5);
    txt.position.set(0, 0.5);
    root.addChild(txt);
    W += 18;
  } else if (normalized === 'shield') {
    const col = accentColor ?? SHIELD_STYLE.reinforced.color;
    const txt = new PIXI.Text({
      text: label,
      style: { fontFamily: FONT_UI, fontSize: 13.6, fontWeight: '900', fill: INK.strong },
    });
    W = Math.ceil(txt.width) + 46;
    H = 31;
    const hw = W / 2;
    const hh = H / 2;

    drawChamferedPlaque(g, -hw + 2, -hh + 4, W, H, 8).fill({ color: INK.shadow, alpha: 0.26 });
    drawChamferedPlaque(g, -hw, -hh + 2, W, H, 8).fill({ color: PALETTE.bevel });
    drawChamferedPlaque(g, -hw, -hh, W, H, 8)
      .fill({ color: INK.paper, alpha: 0.98 })
      .stroke({ width: 1.7, color: col });

    const sx = -hw + 17;
    const shieldKind = col === SHIELD_STYLE.concept.color
      ? 'concept'
      : col === SHIELD_STYLE.normal.color
        ? 'normal'
        : 'reinforced';
    drawShieldGlyph(g, shieldKind, sx, 0, 7.6);
    g.moveTo(sx - 4.5, -5.2).lineTo(sx + 0.8, 0.4).lineTo(sx - 1.4, 1.8).lineTo(sx + 4.8, 5.4)
      .stroke({ width: 1.6, color: PALETTE.crimson, cap: 'round', join: 'round' });

    g.moveTo(hw - 9, -6).lineTo(hw - 5, 0).lineTo(hw - 9, 6)
      .stroke({ width: 1.6, color: col, alpha: 0.8, cap: 'round', join: 'round' });

    txt.anchor.set(0, 0.5);
    txt.position.set(-hw + 30, 0.5);
    root.addChild(txt);
  } else if (normalized === 'heavy') {
    const col = accentColor ?? PALETTE.crimson;
    const txt = new PIXI.Text({
      text: label,
      style: {
        fontFamily: FONT_UI,
        fontSize: 15.8,
        fontWeight: '900',
        fill: INK.paper,
        stroke: { color: PALETTE.crimsonDeep, width: 2.2 },
      },
    });
    W = Math.ceil(txt.width) + 54;
    H = 36;
    const hw = W / 2;
    const hh = H / 2;

    g.poly([
      -hw - 16, 0,
      -hw + 4, -hh + 4,
      -hw + 4, hh - 4,
    ]).fill({ color: col, alpha: 0.92 });
    g.poly([
      hw + 16, 0,
      hw - 4, -hh + 4,
      hw - 4, hh - 4,
    ]).fill({ color: col, alpha: 0.92 });

    drawChamferedPlaque(g, -hw + 2.5, -hh + 5, W, H, 9).fill({ color: INK.shadow, alpha: 0.34 });
    drawChamferedPlaque(g, -hw, -hh + 2.4, W, H, 9).fill({ color: PALETTE.crimsonDeep });
    drawChamferedPlaque(g, -hw, -hh, W, H, 9)
      .fill({ color: col, alpha: 0.99 })
      .stroke({ width: 1.9, color: INK.goldBg });

    drawChamferedPlaque(g, -hw + 3.5, -hh + 3.5, W - 7, H - 7, 6.5)
      .stroke({ width: 1.05, color: PALETTE.brassSoft, alpha: 0.85 });

    drawDiamondPip(g, -hw + 14, 0, 3.8, INK.goldBg, { alpha: 0.96 });
    drawDiamondPip(g, hw - 14, 0, 3.8, INK.goldBg, { alpha: 0.96 });

    txt.anchor.set(0.5);
    txt.position.set(0, 0.5);
    root.addChild(txt);
    W += 32;
  } else {
    const col = accentColor ?? INK.gold;
    const txt = new PIXI.Text({
      text: label,
      style: { fontFamily: FONT_UI, fontSize: 14, fontWeight: '900', fill: INK.strong },
    });
    W = Math.ceil(txt.width) + 46;
    H = 32;
    const hw = W / 2;
    const hh = H / 2;

    drawChamferedPlaque(g, -hw + 2, -hh + 4, W, H, 7).fill({ color: INK.shadow, alpha: 0.25 });
    drawChamferedPlaque(g, -hw, -hh + 2, W, H, 7).fill({ color: PALETTE.bevel });
    drawChamferedPlaque(g, -hw, -hh, W, H, 7)
      .fill({ color: INK.paper, alpha: 0.99 })
      .stroke({ width: 1.75, color: col });

    g.moveTo(-hw + 10, -hh + 2.2).lineTo(hw - 10, -hh + 2.2)
      .stroke({ width: 2.4, color: col, alpha: 0.9, cap: 'round' });
    drawDiamondPip(g, -hw + 13, 0, 3.1, col, { alpha: 0.9 });
    drawDiamondPip(g, hw - 13, 0, 3.1, col, { alpha: 0.9 });

    txt.anchor.set(0.5);
    txt.position.set(0, 1);
    root.addChild(txt);
  }

  root.applyHitstopProgress = (t) => {
    const p = clamp(t, 0, 1);
    const punchPeak = normalized === 'heavy' ? 1.14 : normalized === 'status' ? 1.03 : 1.08;
    let scale = 1;
    let alpha = 1;
    if (p < 0.14) {
      const k = p / 0.14;
      scale = 0.76 + (punchPeak - 0.76) * (1 - Math.pow(1 - k, 3));
      alpha = clamp(k * 1.4, 0, 1);
    } else if (p < 0.28) {
      const k = (p - 0.14) / 0.14;
      scale = punchPeak + (1 - punchPeak) * k;
    } else if (p > 0.76) {
      const k = (p - 0.76) / 0.24;
      alpha = Math.max(0, 1 - k * k);
      scale = 1 - k * 0.04;
    }
    root.scale.set(scale);
    root.alpha = alpha;
  };

  root._kind = normalized;
  root._boxWidth = W;
  root._boxHeight = H;
  return root;
}
