/**
 * Intent-Driven Spring-Physical Cost HUD & Diegetic Tabletop Deck Piles for 《光点计划 III》.
 *
 * Pure PixiJS v8 ES Module — ZERO DOM elements, ZERO `clearContainer` destruction on updates.
 * Strictly bright sunlit warm-paper palette (ZERO black, ZERO blue-purple).
 * Scales smoothly from 1v1 to 10v10+ and arbitrary/infinite rosters.
 */

import * as PIXI from '../vendor/pixi.min.mjs';
import {
  FONT_UI,
  FONT_NUM,
  INK,
  SIDE_THEME,
  drawCostCrystal,
  drawLightStar,
} from './design_system.js';
import { actorPalette } from './stage_actors.js';

export const EXIT_GRACE_DURATION = 0.085;

// Distinct warm sunlit daylight swatches for dynamic/custom rosters (ZERO black, ZERO blue-purple)
const WARM_CHAR_SWATCHES = [
  0x1c946b,
  0xc95a2b,
  0xc98216,
  0xc44558,
  0x5d8f2c,
  0x1e8a78,
  0xc44b3c,
  0xb87414,
  0x3b8c52,
  0xb03a48,
  0x8f6b24,
  0x2d8a64,
];

const UNAFFORDABLE_CRIMSON = 0xc93e2b;
const UNAFFORDABLE_WASH = 0xfdece9;
const CARD_EDGE_LIGHT = 0xe3dac9;
const CARD_EDGE_DEEP = 0xd4c7b0;
const SLOT_RECESSED = 0xefe7d8;
const DISCARD_WASH = 0xfcf2dc;
const OUT_WASH = 0xf4eee4;

function clamp(v, min, max) {
  return Math.max(min, Math.min(max, v));
}

function lerp(a, b, t) {
  return a + (b - a) * t;
}

function expMix(rate, dt) {
  return 1 - Math.exp(-rate * dt);
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
  return (r << 16) | (g << 8) | b;
}

function hashString(str) {
  let h = 2166136261;
  const s = String(str || '');
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function resolveCharacterColor(ch, side, index) {
  if (typeof ch?.color === 'number' && Number.isFinite(ch.color)) {
    return ch.color & 0xffffff;
  }
  const pal = actorPalette(ch, side);
  if (pal && pal.motif && pal.motif !== 'generic') {
    return pal.primary;
  }
  const idx = ch?.id ? hashString(ch.id) % WARM_CHAR_SWATCHES.length : index % WARM_CHAR_SWATCHES.length;
  return WARM_CHAR_SWATCHES[idx];
}

function createScalarSpring(initial, stiffness, damping) {
  return { value: initial, target: initial, vel: 0, stiffness, damping };
}

function stepScalarSpring(sp, dt) {
  const clampedDt = Math.min(dt, 0.05);
  const maxStep = 1 / 120;
  let rem = clampedDt;
  let steps = 0;
  while (rem > 1e-6 && steps < 6) {
    const h = Math.min(rem, maxStep);
    const force = (sp.target - sp.value) * sp.stiffness;
    const damp = -sp.vel * sp.damping;
    sp.vel += (force + damp) * h;
    sp.value += sp.vel * h;
    rem -= h;
    steps++;
  }
}

function calculateSpendBreakdown(sharedCost, personalCost, cardCost) {
  const safeShared = Math.max(0, Number(sharedCost) || 0);
  const safePersonal = Math.max(0, Number(personalCost) || 0);
  const safeCost = Math.max(0, Number(cardCost) || 0);
  const personalUsed = Math.min(safePersonal, safeCost);
  const remaining = Math.max(0, safeCost - personalUsed);
  const sharedUsed = Math.min(safeShared, remaining);
  return {
    personalUsed,
    sharedUsed,
    affordable: personalUsed + sharedUsed >= safeCost,
  };
}

// =============================================================================
// 1. Intent-Driven Spring-Physical Faction Cost HUD
// =============================================================================

const CAPSULE_W = 116;
const CAPSULE_H = 38;
const TAB_W = 46;
const TAB_H = 30;
const TAB_STEP = 28;
const MAX_DIRECT_TABS = 5;
const OVERFLOW_HEAD_COUNT = 4;
const ORB_POOL_SIZE = 24;

export function createFactionCostHud({ side = 1, align = 'left', onShockwave = null } = {}) {
  const theme = SIDE_THEME[side] || SIDE_THEME[1];
  const dir = align === 'right' ? -1 : 1; // +1 extends tabs rightward (P1), -1 leftward (P2)
  const restAccent = INK.gold;

  const root = new PIXI.Container();
  root.container = root;

  const tabsLayer = new PIXI.Container();
  const mainCapsule = new PIXI.Container();
  const fxLayer = new PIXI.Container();
  root.addChild(tabsLayer, mainCapsule, fxLayer);

  // Main Capsule persistent visual primitives (ZERO destruction on update)
  const capAura = new PIXI.Graphics();
  const capShadow = new PIXI.Graphics();
  const capBody = new PIXI.Graphics();
  const capTintMask = new PIXI.Graphics();
  const capTintFill = new PIXI.Graphics();
  capTintFill.mask = capTintMask;
  const capPips = new PIXI.Graphics();
  const capBorder = new PIXI.Graphics();
  const capCrystal = new PIXI.Graphics();

  const costValueText = new PIXI.Text({
    text: '0',
    style: {
      fontFamily: FONT_NUM,
      fontSize: 21,
      fontWeight: '900',
      fill: INK.strong,
    },
  });
  costValueText.anchor.set(0.5, 0.5);

  const costMaxText = new PIXI.Text({
    text: '/5',
    style: {
      fontFamily: FONT_NUM,
      fontSize: 10.5,
      fontWeight: '700',
      fill: INK.muted,
    },
  });
  costMaxText.anchor.set(0, 0.5);

  mainCapsule.addChild(
    capAura,
    capShadow,
    capBody,
    capTintMask,
    capTintFill,
    capPips,
    capBorder,
    capCrystal,
    costValueText,
    costMaxText
  );

  // Overflow "+N" summary tab (persistent, shown only when characters.length > 5)
  const overflowTab = new PIXI.Container();
  const overflowShadow = new PIXI.Graphics();
  const overflowBg = new PIXI.Graphics();
  const overflowText = new PIXI.Text({
    text: '+0',
    style: {
      fontFamily: FONT_NUM,
      fontSize: 12.5,
      fontWeight: '800',
      fill: INK.secondary,
    },
  });
  overflowText.anchor.set(0.5, 0.5);
  overflowTab.addChild(overflowShadow, overflowBg, overflowText);
  overflowTab.visible = false;
  const overflowXSpring = createScalarSpring(0, 240, 21);

  // Persistent local shockwave ring pool (4 slots, never truncates overlapping ripples)
  const ringSlots = Array.from({ length: 4 }, () => {
    const g = new PIXI.Graphics();
    g.visible = false;
    fxLayer.addChild(g);
    return { gfx: g, active: false, age: 1, x: 0, y: 0, color: restAccent };
  });
  let ringCursor = 0;

  // Persistent energy orb pool (ZERO per-hover allocations)
  const orbPool = Array.from({ length: ORB_POOL_SIZE }, () => {
    const g = new PIXI.Graphics();
    g.visible = false;
    fxLayer.addChild(g);
    return {
      gfx: g,
      active: false,
      x: 0,
      y: 0,
      vx: 0,
      vy: 0,
      radius: 3.4,
      color: restAccent,
      age: 0,
      arrived: false,
      burstT: 0,
      maxLife: 1.35,
    };
  });
  let orbCursor = 0;

  // Position & spring states
  let originX = 0;
  let originY = 0;
  const capBaseX = dir * (CAPSULE_W * 0.5);
  const capBaseY = 0;

  const capPosX = createScalarSpring(capBaseX, 290, 22);
  const capPosY = createScalarSpring(capBaseY, 290, 22);
  const capRotSpring = createScalarSpring(0, 260, 18);
  const capSquashSpring = createScalarSpring(0, 320, 20);
  const valuePopSpring = createScalarSpring(1, 380, 19);

  // State model
  let sharedCost = 0;
  let maxShared = 5;
  let characters = []; // normalized [{ id, name, personalCost, color }]
  const tabById = new Map(); // id -> persistent tab entity
  let hasSyncedOnce = false;

  // Intent & 85ms exit-grace hysteresis state
  let activeIntentCharId = null;
  let dockedCharId = null;
  let activeCardCost = 0;
  let pendingExit = false;
  let exitGraceTimer = 0;
  let elapsedTime = 0;
  let unaffordableMix = 0;
  let affordableMix = 0;
  let lastBreakdown = { personalUsed: 0, sharedUsed: 0, affordable: true };

  // Capsule visual animation channels
  const capAnim = {
    hoverMix: 0,
    sweepProgress: 0,
    currentColorHex: restAccent,
    targetColorHex: restAccent,
    displayedCost: 0,
    lastValueFill: INK.strong,
    lastMaxVisible: true,
    dirty: true,
  };

  function getDockX() {
    return capBaseX + dir * (CAPSULE_W * 0.5 - 12);
  }

  function getSlotX(slotIdx) {
    const mainEdge = capBaseX + dir * (CAPSULE_W * 0.5);
    return mainEdge + dir * ((slotIdx + 1) * TAB_STEP - TAB_W * 0.5 + 3);
  }

  function getOverflowSlotX() {
    return getSlotX(OVERFLOW_HEAD_COUNT);
  }

  function createTabEntity(ch, idx) {
    const container = new PIXI.Container();
    const shadowGfx = new PIXI.Graphics();
    const bgGfx = new PIXI.Graphics();
    const valText = new PIXI.Text({
      text: String(ch.personalCost),
      style: {
        fontFamily: FONT_NUM,
        fontSize: 13.5,
        fontWeight: '900',
        fill: INK.paper,
      },
    });
    valText.anchor.set(0.5, 0.5);
    container.addChild(shadowGfx, bgGfx, valText);

    const isOverflow = characters.length > MAX_DIRECT_TABS && idx >= OVERFLOW_HEAD_COUNT;
    const initX = isOverflow ? getOverflowSlotX() : getSlotX(idx);

    return {
      id: ch.id,
      char: ch,
      index: idx,
      isOverflow,
      container,
      shadowGfx,
      bgGfx,
      valText,
      posX: createScalarSpring(initX, 265, 22),
      posY: createScalarSpring(capBaseY, 265, 22),
      slotX: initX,
      slotY: capBaseY,
      phase: 'SLOT', // 'SLOT' | 'MERGING' | 'MERGED' | 'RETURNING'
      dockedTriggered: false,
      dimAlpha: 1,
      visAlpha: isOverflow ? 0 : 1,
      lastDrawnColor: -1,
      lastDrawnAlphaMode: -1,
      lastPersonalText: String(ch.personalCost),
    };
  }

  function emitLocalShockwave(localX, localY, colorHex) {
    const slot = ringSlots[ringCursor];
    ringCursor = (ringCursor + 1) % ringSlots.length;
    slot.active = true;
    slot.age = 0;
    slot.x = localX;
    slot.y = localY;
    slot.color = colorHex;
    slot.gfx.visible = true;
  }

  function spawnEnergyOrbs(fromX, fromY, colorHex) {
    const count = 6;
    for (let k = 0; k < count; k++) {
      const orb = orbPool[orbCursor];
      orbCursor = (orbCursor + 1) % orbPool.length;
      const spreadAngle = -Math.PI * 0.5 + ((k / (count - 1)) - 0.5) * 1.95;
      const speed = 95 + (k % 3) * 34;

      orb.active = true;
      orb.x = fromX;
      orb.y = fromY;
      orb.vx = Math.cos(spreadAngle) * speed + dir * 24;
      orb.vy = Math.sin(spreadAngle) * speed;
      orb.radius = 2.6 + (k % 3) * 0.9;
      orb.color = colorHex;
      orb.age = 0;
      orb.arrived = false;
      orb.burstT = 0;
      orb.maxLife = 1.35;

      orb.gfx.clear();
      orb.gfx.circle(0, 0, orb.radius).fill({ color: colorHex, alpha: 0.92 });
      orb.gfx.circle(0, 0, orb.radius * 0.44).fill({ color: INK.paper, alpha: 0.85 });
      orb.gfx.position.set(fromX, fromY);
      orb.gfx.alpha = 0.01;
      orb.gfx.scale.set(0.75);
      orb.gfx.visible = true;
    }
  }

  function commitDisplayedCost(newCost, pop = true) {
    const val = Math.max(0, Math.round(newCost));
    if (capAnim.displayedCost !== val) {
      capAnim.displayedCost = val;
      costValueText.text = String(val);
      if (pop) {
        valuePopSpring.value = 1.32;
        valuePopSpring.vel = 2.4;
      }
      capAnim.dirty = true;
    }
  }

  function recomputeBreakdown() {
    const activeTab = activeIntentCharId !== null ? tabById.get(activeIntentCharId) : null;
    const pCost = activeTab ? activeTab.char.personalCost : 0;
    const prevAffordable = lastBreakdown.affordable;
    lastBreakdown = calculateSpendBreakdown(sharedCost, pCost, activeCardCost);
    if (activeCardCost > 0 && !lastBreakdown.affordable && prevAffordable) {
      // Tactile micro-tremor when transitioning into unaffordable intent
      capPosX.vel += dir * 90;
      capRotSpring.vel += dir * 1.4;
    }
    capAnim.dirty = true;
  }

  function syncTabAnchors(snapImmediate = false) {
    const hasOverflow = characters.length > MAX_DIRECT_TABS;
    const overflowCount = Math.max(0, characters.length - OVERFLOW_HEAD_COUNT);
    const activeTab = activeIntentCharId !== null ? tabById.get(activeIntentCharId) : null;
    const activeIndex = activeTab ? activeTab.index : -1;
    const activeIsDirect = activeTab && !activeTab.isOverflow;
    const dockX = getDockX();

    const visibleSlotCount = hasOverflow ? OVERFLOW_HEAD_COUNT + 1 : characters.length;
    if (activeIsDirect) {
      // Rack compacts slightly when a visible direct tab leaves its slot
      overflowXSpring.target = getSlotX(OVERFLOW_HEAD_COUNT - 1);
    } else {
      overflowXSpring.target = getOverflowSlotX();
    }

    if (hasOverflow) {
      overflowTab.visible = true;
      overflowText.text = `+${overflowCount}`;
      if (snapImmediate) {
        overflowXSpring.value = overflowXSpring.target;
        overflowXSpring.vel = 0;
      }
    } else {
      overflowTab.visible = false;
    }

    for (let i = 0; i < characters.length; i++) {
      const ch = characters[i];
      const tab = tabById.get(ch.id);
      if (!tab) continue;
      tab.index = i;
      tab.isOverflow = hasOverflow && i >= OVERFLOW_HEAD_COUNT;

      const normalX = tab.isOverflow ? overflowXSpring.target : getSlotX(i);
      tab.slotX = normalX;
      tab.slotY = capBaseY;

      if (tab.phase === 'MERGING' || tab.phase === 'MERGED') {
        tab.posX.target = dockX;
        tab.posY.target = capBaseY;
      } else if (activeIsDirect && !tab.isOverflow) {
        const shiftIdx = i > activeIndex ? i - 1 : i;
        tab.posX.target = getSlotX(shiftIdx);
        tab.posY.target = capBaseY;
      } else {
        tab.posX.target = normalX;
        tab.posY.target = capBaseY;
      }

      if (snapImmediate) {
        tab.posX.value = tab.posX.target;
        tab.posX.vel = 0;
        tab.posY.value = tab.posY.target;
        tab.posY.vel = 0;
      }
    }

    root._boxWidth = CAPSULE_W + visibleSlotCount * TAB_STEP + 10;
    root._boxHeight = CAPSULE_H + 8;
  }

  function rebuildTabZOrder() {
    // Reorder persistent children WITHOUT destroying them:
    // Overflow tab at back, then dynamic overflow tabs, then direct tabs back-to-front (index 0 closest to capsule)
    const desired = [];
    const hasOverflow = characters.length > MAX_DIRECT_TABS;
    if (hasOverflow) {
      desired.push(overflowTab);
    }
    for (let i = characters.length - 1; i >= 0; i--) {
      const tab = tabById.get(characters[i].id);
      if (tab) desired.push(tab.container);
    }
    for (const [id, tab] of tabById.entries()) {
      if (!desired.includes(tab.container)) {
        desired.unshift(tab.container);
      }
      if (id === activeIntentCharId && tab.isOverflow) {
        // Active materialized overflow tab slides smoothly in front of +N tab (still behind mainCapsule)
        const idx = desired.indexOf(tab.container);
        if (idx >= 0) {
          desired.splice(idx, 1);
          desired.push(tab.container);
        }
      }
    }
    for (let i = 0; i < desired.length; i++) {
      const child = desired[i];
      if (child.parent !== tabsLayer) {
        tabsLayer.addChildAt(child, Math.min(i, tabsLayer.children.length));
      } else if (tabsLayer.getChildIndex(child) !== i) {
        tabsLayer.setChildIndex(child, Math.min(i, tabsLayer.children.length - 1));
      }
    }
  }

  function commitIntent(nextCharId, nextCardCost) {
    const normalizedId = nextCharId !== null && nextCharId !== undefined && nextCharId !== '' && tabById.has(nextCharId)
      ? nextCharId
      : null;
    const safeCardCost = Math.max(0, Number(nextCardCost) || 0);

    if (activeIntentCharId === normalizedId) {
      if (activeCardCost !== safeCardCost) {
        activeCardCost = safeCardCost;
        recomputeBreakdown();
      }
      return;
    }

    const prevId = activeIntentCharId;
    activeIntentCharId = normalizedId;
    activeCardCost = safeCardCost;

    if (prevId !== null) {
      const prevTab = tabById.get(prevId);
      if (prevTab && (prevTab.phase === 'MERGING' || prevTab.phase === 'MERGED')) {
        prevTab.phase = 'RETURNING';
        prevTab.dockedTriggered = false;
        prevTab.posX.vel += dir * 185;
      }
    }

    if (normalizedId !== null) {
      const tab = tabById.get(normalizedId);
      if (tab) {
        if (tab.isOverflow && tab.phase === 'SLOT') {
          // Dynamically materialize this character's color tab directly from the "+N" summary tab
          const ovX = overflowXSpring.value || getOverflowSlotX();
          tab.slotX = ovX;
          tab.posX.value = ovX;
          tab.posY.value = capBaseY;
          tab.posX.vel = 0;
          tab.posY.vel = 0;
          tab.visAlpha = 0.05;
        }
        tab.phase = 'MERGING';
        tab.dockedTriggered = false;
        tab.posX.vel -= dir * 235;
        tab.posY.vel -= 32;

        spawnEnergyOrbs(
          tab.posX.value + dir * (TAB_W * 0.15),
          tab.posY.value,
          tab.char.color
        );

        capAnim.sweepProgress = 0;
        capAnim.targetColorHex = tab.char.color;
      }
    } else {
      dockedCharId = null;
      commitDisplayedCost(sharedCost, true);
      capAnim.targetColorHex = restAccent;
      capPosX.vel -= dir * 68;
      capPosY.vel += 26;
    }

    recomputeBreakdown();
    syncTabAnchors(false);
    rebuildTabZOrder();
  }

  function redrawOverflowTab(isActiveOverflow) {
    const hw = TAB_W * 0.5;
    const hh = TAB_H * 0.5;
    const r = hh;

    overflowShadow.clear();
    overflowShadow.roundRect(-hw, -hh + 3.5, TAB_W, TAB_H, r)
      .fill({ color: INK.shadow, alpha: 0.18 });

    overflowBg.clear();
    overflowBg.roundRect(-hw, -hh, TAB_W, TAB_H, r)
      .fill({ color: isActiveOverflow ? INK.goldBg : INK.paperTint, alpha: 0.96 })
      .stroke({ width: isActiveOverflow ? 1.5 : 1.15, color: isActiveOverflow ? INK.gold : INK.line, alpha: 0.92 });

    overflowText.position.set(dir * (hw - TAB_STEP * 0.48), 0);
    overflowText.style.fill = isActiveOverflow ? INK.goldDeep : INK.secondary;
  }

  function redrawTab(tab, anyActive) {
    const hw = TAB_W * 0.5;
    const hh = TAB_H * 0.5;
    const r = hh;
    const col = tab.char.color;
    const isMoving = tab.phase === 'MERGING' || tab.phase === 'MERGED';
    const isZero = (tab.char.personalCost || 0) <= 0;
    const alphaMode = (anyActive && !isMoving ? 1 : 0) + (isZero ? 2 : 0);

    if (tab.lastDrawnColor === col && tab.lastDrawnAlphaMode === alphaMode) {
      return;
    }
    tab.lastDrawnColor = col;
    tab.lastDrawnAlphaMode = alphaMode;

    const fillAlpha = isZero
      ? (anyActive && !isMoving ? 0.34 : 0.48)
      : (anyActive && !isMoving ? 0.62 : 0.94);

    tab.shadowGfx.clear();
    tab.shadowGfx.roundRect(-hw, -hh + 3.5, TAB_W, TAB_H, r)
      .fill({ color: col, alpha: isZero ? 0.10 : 0.18 });

    tab.bgGfx.clear();
    tab.bgGfx.roundRect(-hw, -hh, TAB_W, TAB_H, r)
      .fill({ color: col, alpha: fillAlpha })
      .stroke({ width: 1.4, color: INK.paper, alpha: 0.9 });

    // Subtle sunlit top sheen inside tab
    tab.bgGfx.roundRect(-hw + 5, -hh + 2.5, TAB_W - 10, 4.5, 2.2)
      .fill({ color: INK.paper, alpha: 0.24 });

    tab.valText.position.set(dir * (hw - TAB_STEP * 0.48), 0.5);
  }

  function redrawMainCapsule() {
    const hw = CAPSULE_W * 0.5;
    const hh = CAPSULE_H * 0.5;
    const r = hh;
    const hMix = capAnim.hoverMix;
    const sweep = clamp(capAnim.sweepProgress, 0, 1);
    const activeCol = capAnim.currentColorHex;

    const hasCostCheck = activeCardCost > 0 && (activeIntentCharId !== null || hMix > 0.05);
    const pulse = 0.5 + 0.5 * Math.sin(elapsedTime * 7.4);

    // 1. Affordability outer glow / crimson warning aura (zero verbose text)
    capAura.clear();
    if (unaffordableMix > 0.01) {
      const expand = 3.5 + pulse * 2.8;
      capAura.roundRect(-hw - expand, -hh - expand, CAPSULE_W + expand * 2, CAPSULE_H + expand * 2, r + expand)
        .fill({ color: UNAFFORDABLE_CRIMSON, alpha: unaffordableMix * (0.14 + pulse * 0.10) })
        .stroke({ width: 2.0, color: UNAFFORDABLE_CRIMSON, alpha: unaffordableMix * (0.55 + pulse * 0.35) });
    } else if (affordableMix > 0.01) {
      const expand = 2.8 + pulse * 1.4;
      const glowCol = lerpColorHex(INK.gold, activeCol, hMix * 0.65);
      capAura.roundRect(-hw - expand, -hh - expand, CAPSULE_W + expand * 2, CAPSULE_H + expand * 2, r + expand)
        .fill({ color: glowCol, alpha: affordableMix * (0.10 + pulse * 0.06) })
        .stroke({ width: 1.6, color: glowCol, alpha: affordableMix * (0.45 + pulse * 0.25) });
    }

    // 2. Grounded warm shadow
    capShadow.clear();
    const shadowCol = unaffordableMix > 0.35
      ? lerpColorHex(INK.shadow, UNAFFORDABLE_CRIMSON, unaffordableMix * 0.6)
      : lerpColorHex(INK.shadow, activeCol, hMix * 0.55);
    capShadow.roundRect(-hw, -hh + 4.5, CAPSULE_W, CAPSULE_H, r)
      .fill({ color: shadowCol, alpha: 0.20 + hMix * 0.12 });

    // 3. Sunlit warm ivory body
    capBody.clear();
    const bodyCol = unaffordableMix > 0.02
      ? lerpColorHex(INK.paper, UNAFFORDABLE_WASH, unaffordableMix * 0.72)
      : INK.paper;
    capBody.roundRect(-hw, -hh, CAPSULE_W, CAPSULE_H, r)
      .fill({ color: bodyCol, alpha: 0.985 });

    // 4. Capsule mask + directional color sweep fill
    capTintMask.clear();
    capTintMask.roundRect(-hw, -hh, CAPSULE_W, CAPSULE_H, r)
      .fill({ color: INK.paper });

    capTintFill.clear();
    if (hMix > 0.005) {
      const fillW = CAPSULE_W * sweep;
      const sweepStartX = dir === 1 ? hw - fillW : -hw;
      capTintFill.rect(sweepStartX, -hh, fillW, CAPSULE_H)
        .fill({ color: activeCol, alpha: 0.18 * hMix });

      // Crisp leading edge accent ribbon on outer rim of capsule
      const barW = 5.5 * hMix;
      const barX = dir === 1 ? -hw : hw - barW;
      capTintFill.rect(barX, -hh, barW, CAPSULE_H)
        .fill({ color: activeCol, alpha: 0.88 * hMix });
    }

    // 5. Micro shared-cost pips along bottom rim (diegetic capacity & spend preview)
    capPips.clear();
    const pipCount = clamp(Math.max(maxShared, sharedCost), 1, 8);
    const pipTotalW = Math.min(54, pipCount * 8 - 2);
    const pipW = (pipTotalW - (pipCount - 1) * 2.5) / pipCount;
    const pipStartX = dir === 1 ? -hw + 36 : hw - 36 - pipTotalW;
    const pipY = hh - 6.5;
    for (let i = 0; i < pipCount; i++) {
      const px = dir === 1
        ? pipStartX + i * (pipW + 2.5)
        : pipStartX + (pipCount - 1 - i) * (pipW + 2.5);
      const isFilled = i < sharedCost;
      const isSpentPreview = hasCostCheck && isFilled && i >= Math.max(0, sharedCost - lastBreakdown.sharedUsed);
      let pipCol = isFilled ? INK.gold : INK.line;
      let pipAlpha = isFilled ? 0.9 : 0.6;
      if (isSpentPreview) {
        pipCol = lastBreakdown.affordable ? activeCol : UNAFFORDABLE_CRIMSON;
        pipAlpha = 0.52 + pulse * 0.42;
      }
      capPips.roundRect(px, pipY, pipW, 3.0, 1.5)
        .fill({ color: pipCol, alpha: pipAlpha });
    }

    // 6. Outer border stroke
    capBorder.clear();
    let borderCol = lerpColorHex(theme.border, activeCol, hMix);
    if (unaffordableMix > 0.05) {
      borderCol = lerpColorHex(borderCol, UNAFFORDABLE_CRIMSON, unaffordableMix);
    } else if (affordableMix > 0.05) {
      borderCol = lerpColorHex(borderCol, activeCol, affordableMix * 0.6);
    }
    capBorder.roundRect(-hw, -hh, CAPSULE_W, CAPSULE_H, r)
      .stroke({ width: 1.55 + hMix * 0.75 + unaffordableMix * 0.6, color: borderCol, alpha: 0.78 + hMix * 0.22 });

    // 7. Faceted Cost Crystal emblem on outer side
    capCrystal.clear();
    const crysX = -dir * (hw - 20);
    const crysR = 9.6 + hMix * 1.1;
    const crysCol = unaffordableMix > 0.4
      ? lerpColorHex(activeCol, UNAFFORDABLE_CRIMSON, unaffordableMix)
      : lerpColorHex(INK.gold, activeCol, hMix);
    drawCostCrystal(capCrystal, crysX, 0, crysR, crysCol, INK.paper);

    // 8. Numeric readout positioning & color (balanced for both left and mirrored right alignment)
    const valX = dir === 1 ? 6 : -14;
    costValueText.position.set(valX, -2);
    const targetValFill = unaffordableMix > 0.45
      ? UNAFFORDABLE_CRIMSON
      : lerpColorHex(INK.strong, activeCol, hMix * 0.92);
    if (targetValFill !== capAnim.lastValueFill) {
      capAnim.lastValueFill = targetValFill;
      costValueText.style.fill = targetValFill;
    }

    // Show muted `/maxShared` only at rest; hide cleanly during personal+shared merge pop
    const showMax = hMix < 0.35;
    if (showMax !== capAnim.lastMaxVisible) {
      capAnim.lastMaxVisible = showMax;
      costMaxText.visible = showMax;
    }
    if (showMax) {
      costMaxText.text = `/${maxShared}`;
      costMaxText.alpha = clamp(1 - hMix * 3, 0, 1);
      costMaxText.position.set(valX + Math.max(9, costValueText.width * 0.52) + 1.5, 1.5);
    }
  }

  // Initial draw
  mainCapsule.position.set(capBaseX, capBaseY);
  redrawMainCapsule();

  // Public API
  root.sync = ({ sharedCost: nextShared = 0, maxShared: nextMax = 5, characters: nextChars = [] } = {}) => {
    const prevShared = sharedCost;
    sharedCost = Math.max(0, Math.round(Number(nextShared) || 0));
    maxShared = Math.max(1, Math.round(Number(nextMax) || 5));

    const normalized = (nextChars || []).map((ch, idx) => ({
      id: ch?.id ?? `char_${idx}`,
      name: ch?.name ?? '',
      personalCost: Math.max(0, Math.round(Number(ch?.personalCost ?? ch?.cost?.available ?? 0) || 0)),
      color: resolveCharacterColor(ch, side, idx),
    }));
    characters = normalized;

    const activeIdSet = new Set();
    for (let i = 0; i < characters.length; i++) {
      const ch = characters[i];
      activeIdSet.add(ch.id);
      let tab = tabById.get(ch.id);
      if (!tab) {
        tab = createTabEntity(ch, i);
        tabById.set(ch.id, tab);
      } else {
        tab.char = ch;
        tab.index = i;
        const pStr = String(ch.personalCost);
        if (tab.lastPersonalText !== pStr) {
          tab.lastPersonalText = pStr;
          tab.valText.text = pStr;
        }
        tab.lastDrawnColor = -1;
      }
    }

    // Retire removed characters cleanly (e.g. roster change)
    for (const [id, tab] of tabById.entries()) {
      if (!activeIdSet.has(id)) {
        if (tab.container.parent) tab.container.parent.removeChild(tab.container);
        tab.container.destroy({ children: true });
        tabById.delete(id);
        if (activeIntentCharId === id) {
          activeIntentCharId = null;
          dockedCharId = null;
          capAnim.targetColorHex = restAccent;
        }
      }
    }

    syncTabAnchors(!hasSyncedOnce);
    rebuildTabZOrder();

    if (dockedCharId !== null && tabById.has(dockedCharId)) {
      const docked = tabById.get(dockedCharId);
      commitDisplayedCost(sharedCost + docked.char.personalCost, hasSyncedOnce);
    } else {
      const changed = hasSyncedOnce && prevShared !== sharedCost;
      commitDisplayedCost(sharedCost, changed);
      if (changed) {
        capSquashSpring.vel += prevShared < sharedCost ? 2.4 : -1.8;
      }
    }

    recomputeBreakdown();
    hasSyncedOnce = true;
    capAnim.dirty = true;
  };

  root.setIntent = ({ charId = null, cardCost = 0 } = {}) => {
    const hasTarget = charId !== null && charId !== undefined && charId !== '';
    if (hasTarget) {
      pendingExit = false;
      exitGraceTimer = 0;
      commitIntent(charId, cardCost);
    } else if (activeIntentCharId !== null) {
      // 85ms exit-grace hysteresis so gliding across card gaps never jitters
      pendingExit = true;
    } else {
      activeCardCost = Math.max(0, Number(cardCost) || 0);
      recomputeBreakdown();
    }
  };

  root.setPosition = (x, y) => {
    originX = Number(x) || 0;
    originY = Number(y) || 0;
    root.position.set(originX, originY);
  };

  root.getAnchor = () => ({
    x: originX + capPosX.value,
    y: originY + capPosY.value,
  });

  root.getSpendBreakdown = () => ({
    ...lastBreakdown,
    charId: activeIntentCharId,
    cardCost: activeCardCost,
    sharedCost,
    personalCost: activeIntentCharId && tabById.has(activeIntentCharId)
      ? tabById.get(activeIntentCharId).char.personalCost
      : 0,
  });

  root.tick = (dtSec) => {
    const dt = clamp(Number(dtSec) || 0, 0, 0.05);
    if (dt <= 0) return;
    elapsedTime += dt;

    // 1. 85ms Exit-Grace Hysteresis timer
    if (pendingExit) {
      exitGraceTimer += dt;
      if (exitGraceTimer >= EXIT_GRACE_DURATION) {
        pendingExit = false;
        exitGraceTimer = 0;
        commitIntent(null, 0);
      }
    }

    // 2. Step overflow rack spring
    const hasOverflow = characters.length > MAX_DIRECT_TABS;
    if (hasOverflow) {
      stepScalarSpring(overflowXSpring, dt);
      overflowTab.position.set(overflowXSpring.value, capBaseY);
      const activeTab = activeIntentCharId !== null ? tabById.get(activeIntentCharId) : null;
      redrawOverflowTab(Boolean(activeTab && activeTab.isOverflow));
    }

    // 3. Step personal-cost tab springs & SLOT -> MERGING -> MERGED -> RETURNING state machine
    const dockX = getDockX();
    const isAnyActive = activeIntentCharId !== null;

    for (let i = 0; i < characters.length; i++) {
      const tab = tabById.get(characters[i].id);
      if (!tab) continue;

      if (tab.isOverflow && tab.phase === 'SLOT' && tab.visAlpha < 0.01) {
        tab.container.visible = false;
        continue;
      }

      stepScalarSpring(tab.posX, dt);
      stepScalarSpring(tab.posY, dt);

      const bx = tab.posX.value;
      const by = tab.posY.value;
      tab.container.position.set(bx, by);

      const totalTravel = Math.max(1, Math.abs(tab.slotX - dockX));
      const distFromDock = Math.max(0, (bx - dockX) * dir);
      const travelRatio = clamp(distFromDock / totalTravel, 0, 1);

      if (tab.phase === 'MERGING') {
        if (!tab.dockedTriggered && travelRatio < 0.24) {
          tab.dockedTriggered = true;
          tab.phase = 'MERGED';
          dockedCharId = tab.id;

          commitDisplayedCost(sharedCost + tab.char.personalCost, true);

          // Tactile impact impulse on main capsule
          capPosX.vel -= dir * 135;
          capPosY.vel -= 54;
          capRotSpring.vel -= dir * 2.1;
          capSquashSpring.vel += 3.4;

          emitLocalShockwave(capPosX.value, capPosY.value, tab.char.color);
          if (typeof onShockwave === 'function') {
            onShockwave(originX + capPosX.value, originY + capPosY.value, tab.char.color);
          }
        }
      } else if (tab.phase === 'RETURNING') {
        if (Math.abs(bx - tab.posX.target) < 2.2 && Math.abs(tab.posX.vel) < 22) {
          tab.phase = 'SLOT';
        }
      }

      const emergence = tab.phase === 'SLOT' ? 1.0 : clamp(travelRatio / 0.35, 0, 1);
      const targetDim = isAnyActive && tab.id !== activeIntentCharId ? 0.68 : 1.0;
      tab.dimAlpha = lerp(tab.dimAlpha, targetDim, expMix(10, dt));

      if (tab.isOverflow) {
        const targetVis = tab.phase === 'SLOT' ? 0 : 1;
        tab.visAlpha = lerp(tab.visAlpha, targetVis, expMix(14, dt));
        tab.container.visible = tab.visAlpha > 0.015;
        tab.container.alpha = emergence * tab.dimAlpha * tab.visAlpha;
      } else {
        tab.container.visible = true;
        tab.container.alpha = emergence * tab.dimAlpha;
      }

      const tabScale = lerp(0.78, 1.0, emergence) * (tab.isOverflow ? lerp(0.78, 1.0, tab.visAlpha) : 1.0);
      tab.container.scale.set(tabScale);
      redrawTab(tab, isAnyActive);
    }

    // 4. Step Main Capsule springs & visual channels
    stepScalarSpring(capPosX, dt);
    stepScalarSpring(capPosY, dt);
    stepScalarSpring(capRotSpring, dt);
    stepScalarSpring(capSquashSpring, dt);
    stepScalarSpring(valuePopSpring, dt);

    const targetMix = isAnyActive ? 1 : 0;
    capAnim.hoverMix = lerp(capAnim.hoverMix, targetMix, expMix(10, dt));
    capAnim.sweepProgress = lerp(capAnim.sweepProgress, isAnyActive ? 1 : 0, expMix(9, dt));
    capAnim.currentColorHex = lerpColorHex(capAnim.currentColorHex, capAnim.targetColorHex, expMix(11, dt));

    const hasCostCheck = activeCardCost > 0 && isAnyActive;
    const targetUnaff = hasCostCheck && !lastBreakdown.affordable ? 1 : 0;
    const targetAff = hasCostCheck && lastBreakdown.affordable ? 1 : 0;
    unaffordableMix = lerp(unaffordableMix, targetUnaff, expMix(12, dt));
    affordableMix = lerp(affordableMix, targetAff, expMix(12, dt));

    mainCapsule.position.set(capPosX.value, capPosY.value);
    mainCapsule.rotation = capRotSpring.value * 0.13;
    const baseScale = 1 + capAnim.hoverMix * 0.045;
    const sx = baseScale * (1 + capSquashSpring.value * 0.075);
    const sy = baseScale * (1 - capSquashSpring.value * 0.058);
    mainCapsule.scale.set(sx, sy);
    costValueText.scale.set(valuePopSpring.value);

    redrawMainCapsule();

    // 5. Step homing energy orbs (smooth spring-guided flight into capsule -> arrival flash)
    const orbTargetX = capPosX.value + dir * 10;
    const orbTargetY = capPosY.value;
    const airDrag = Math.exp(-3.4 * dt);

    for (let i = 0; i < orbPool.length; i++) {
      const orb = orbPool[i];
      if (!orb.active) continue;
      orb.age += dt;
      if (orb.arrived) {
        orb.burstT += dt * 7.8;
        orb.gfx.position.set(orbTargetX, orbTargetY);
        orb.gfx.alpha = Math.max(0, 1 - orb.burstT);
        orb.gfx.scale.set(1 + orb.burstT * 0.95);
      } else {
        const dx = orbTargetX - orb.x;
        const dy = orbTargetY - orb.y;
        const dist = Math.hypot(dx, dy);
        if (dist < 13) {
          orb.arrived = true;
        } else {
          const pull = 780 + Math.min(orb.age * 1650, 1800);
          orb.vx = (orb.vx + (dx / dist) * pull * dt) * airDrag;
          orb.vy = (orb.vy + (dy / dist) * pull * dt) * airDrag;
          orb.x += orb.vx * dt;
          orb.y += orb.vy * dt;
          orb.gfx.position.set(orb.x, orb.y);
          const fadeIn = Math.min(1, orb.age * 10);
          orb.gfx.alpha = fadeIn * 0.92;
          orb.gfx.scale.set(0.75 + fadeIn * 0.25);
        }
      }
      if (orb.burstT >= 1 || orb.age >= orb.maxLife) {
        orb.active = false;
        orb.gfx.visible = false;
      }
    }

    // 6. Step local capsule shockwave rings
    for (let i = 0; i < ringSlots.length; i++) {
      const slot = ringSlots[i];
      if (!slot.active) continue;
      slot.age += dt * 2.1;
      if (slot.age >= 1) {
        slot.active = false;
        slot.gfx.visible = false;
        continue;
      }
      const ease = 1 - Math.pow(1 - slot.age, 2);
      const fade = (1 - slot.age) * (1 - slot.age);
      const rx = CAPSULE_W * 0.5 + ease * 36;
      const ry = CAPSULE_H * 0.5 + ease * 26;
      slot.gfx.clear();
      slot.gfx.roundRect(slot.x - rx, slot.y - ry, rx * 2, ry * 2, ry)
        .stroke({ width: 2.2 * (1 - slot.age * 0.55), color: slot.color, alpha: fade * 0.55 });
    }
  };

  const baseDestroy = root.destroy.bind(root);
  root.destroy = (opts = { children: true }) => {
    tabById.clear();
    if (!root.destroyed) baseDestroy(opts);
  };

  return root;
}

// =============================================================================
// 2. Diegetic Tabletop Layered Card Stacks (Draw / Delayed Discard / Out-of-Combat)
// =============================================================================

const PILE_CARD_W = 30;
const PILE_CARD_H = 40;
const PILE_GAP = 10;
const PILE_MAX_STACK_H = 11;

export function createDiegeticDeckPiles({ side = 1, align = 'left', onOpenPile = null } = {}) {
  const theme = SIDE_THEME[side] || SIDE_THEME[1];
  const root = new PIXI.Container();
  root.container = root;

  const pileDefs = align === 'right'
    ? [
        { key: 'out_of_combat', short: '外', full: '战斗外', accent: INK.secondary, wash: OUT_WASH, clickable: true },
        { key: 'delayed_discard', short: '弃', full: '延迟弃牌', accent: INK.goldDeep, wash: DISCARD_WASH, clickable: true },
        { key: 'draw', short: '牌', full: '抽牌堆', accent: theme.accent, wash: theme.softBg, clickable: false },
      ]
    : [
        { key: 'draw', short: '牌', full: '抽牌堆', accent: theme.accent, wash: theme.softBg, clickable: false },
        { key: 'delayed_discard', short: '弃', full: '延迟弃牌', accent: INK.goldDeep, wash: DISCARD_WASH, clickable: true },
        { key: 'out_of_combat', short: '外', full: '战斗外', accent: INK.secondary, wash: OUT_WASH, clickable: true },
      ];

  const totalW = pileDefs.length * PILE_CARD_W + (pileDefs.length - 1) * PILE_GAP;
  const startX = align === 'right' ? -totalW : 0;

  let originX = 0;
  let originY = 0;
  let playerName = theme.name;
  let hasSyncedOnce = false;

  const pileMap = new Map();

  function targetStackHeight(count) {
    if (count <= 0) return 0;
    return clamp(1.8 + Math.pow(count, 0.72) * 1.45, 1.8, PILE_MAX_STACK_H);
  }

  function createPileSlot(def, idx) {
    const cx = startX + idx * (PILE_CARD_W + PILE_GAP) + PILE_CARD_W * 0.5;
    const cy = 0;

    const slot = new PIXI.Container();
    slot.position.set(cx, cy);

    const trayG = new PIXI.Graphics();
    const stackG = new PIXI.Graphics();
    const topCard = new PIXI.Container();
    const topG = new PIXI.Graphics();
    const badgeG = new PIXI.Graphics();

    const countText = new PIXI.Text({
      text: '0',
      style: {
        fontFamily: FONT_NUM,
        fontSize: 10,
        fontWeight: '900',
        fill: INK.muted,
      },
    });
    countText.anchor.set(0.5, 0.5);

    const labelText = new PIXI.Text({
      text: def.short,
      style: {
        fontFamily: FONT_UI,
        fontSize: 9.2,
        fontWeight: '800',
        fill: INK.muted,
      },
    });
    labelText.anchor.set(0.5, 0);
    labelText.position.set(0, PILE_CARD_H * 0.5 + 3.5);

    topCard.addChild(topG);
    slot.addChild(trayG, stackG, topCard, badgeG, countText, labelText);

    const entity = {
      def,
      cx,
      cy,
      slot,
      trayG,
      stackG,
      topCard,
      topG,
      badgeG,
      countText,
      labelText,
      count: 0,
      cards: [],
      hovered: false,
      heightSpring: createScalarSpring(0, 220, 22),
      bounceSpring: createScalarSpring(0, 320, 17),
      squashSpring: createScalarSpring(0, 340, 18),
      hoverSpring: createScalarSpring(0, 260, 20),
      flashAlpha: 0,
      dirty: true,
    };

    slot.eventMode = 'static';
    slot.hitArea = new PIXI.Rectangle(-PILE_CARD_W * 0.5 - 3, -PILE_CARD_H * 0.5 - 12, PILE_CARD_W + 6, PILE_CARD_H + 26);
    slot.on('pointerover', () => {
      entity.hovered = true;
      entity.hoverSpring.target = 1;
      entity.dirty = true;
    });
    slot.on('pointerout', () => {
      entity.hovered = false;
      entity.hoverSpring.target = 0;
      entity.dirty = true;
    });
    slot.on('pointertap', (e) => {
      if (!def.clickable || entity.count <= 0) return;
      if (e && typeof e.stopPropagation === 'function') e.stopPropagation();
      entity.bounceSpring.vel -= 75;
      entity.squashSpring.vel += 1.6;
      entity.flashAlpha = 0.7;
      if (typeof onOpenPile === 'function') {
        onOpenPile({
          key: def.key,
          side,
          title: `${playerName} · ${def.full}`,
          fullLabel: def.full,
          cards: entity.cards,
          count: entity.count,
          playerName,
        });
      }
    });

    root.addChild(slot);
    pileMap.set(def.key, entity);
    drawPile(entity);
  }

  function drawPile(p) {
    const hw = PILE_CARD_W * 0.5;
    const hh = PILE_CARD_H * 0.5;
    const r = 4.2;
    const count = p.count;
    const stackH = Math.max(0, p.heightSpring.value);
    const hover = clamp(p.hoverSpring.value, 0, 1);
    const bounceY = p.bounceSpring.value;
    const sq = p.squashSpring.value;
    const active = count > 0;
    const clickableNow = p.def.clickable && active;

    p.slot.cursor = clickableNow ? 'pointer' : 'default';

    // 1. Recessed tabletop slot outline (always grounds the pile on the sunlit table)
    p.trayG.clear();
    p.trayG.roundRect(-hw, -hh, PILE_CARD_W, PILE_CARD_H, r)
      .fill({ color: SLOT_RECESSED, alpha: active ? 0.55 : 0.72 })
      .stroke({ width: 0.9, color: active ? INK.line : INK.hairline, alpha: 0.9 });
    if (!active) {
      // Quiet empty tabletop pressmark diamond
      p.trayG.poly([0, -4.5, 4.5, 0, 0, 4.5, -4.5, 0])
        .stroke({ width: 0.9, color: INK.line, alpha: 0.85 });
    }

    // 2. Physical 2.5D layered card edges + grounded shadow
    p.stackG.clear();
    p.topG.clear();

    if (active || stackH > 0.35) {
      const shOffset = 2.5 + stackH * 0.25 + hover * 2.2;
      p.stackG.roundRect(-hw + 1.5, -hh + shOffset, PILE_CARD_W, PILE_CARD_H, r)
        .fill({ color: INK.shadow, alpha: 0.20 + Math.min(0.14, stackH * 0.012) });

      // Tactile paper-stack edge layers climbing upward from table surface
      const layers = Math.max(1, Math.min(7, Math.round(stackH / 1.55)));
      for (let i = 0; i < layers; i++) {
        const ly = -i * (stackH / layers);
        const edgeCol = i % 2 === 0 ? CARD_EDGE_DEEP : CARD_EDGE_LIGHT;
        p.stackG.roundRect(-hw, -hh + ly + 1.4, PILE_CARD_W, PILE_CARD_H, r)
          .fill({ color: edgeCol });
      }
      if (stackH > 2) {
        p.stackG.roundRect(-hw, -hh - stackH + 1.4, PILE_CARD_W, PILE_CARD_H + stackH - 1.4, r)
          .stroke({ width: 0.65, color: INK.shadow, alpha: 0.32 });
      }

      // 3. Top tactile card face/back
      const liftY = -stackH - hover * (clickableNow ? 4.2 : 2.0) + bounceY;
      p.topCard.visible = true;
      p.topCard.position.set(0, liftY);
      const baseTilt = p.def.key === 'delayed_discard' ? (align === 'right' ? -0.055 : 0.055) : 0;
      p.topCard.rotation = baseTilt + hover * (align === 'right' ? -0.045 : 0.045);
      const sx = (1 + hover * 0.055) * (1 + sq * 0.075);
      const sy = (1 + hover * 0.055) * (1 - sq * 0.06);
      p.topCard.scale.set(sx, sy);

      const borderCol = hover > 0.1 && clickableNow
        ? lerpColorHex(p.def.accent, INK.gold, hover * 0.55)
        : p.def.accent;

      p.topG.roundRect(-hw, -hh, PILE_CARD_W, PILE_CARD_H, r)
        .fill({ color: INK.paper })
        .stroke({ width: 1.2 + hover * 0.55, color: borderCol, alpha: 0.92 });

      if (p.def.key === 'draw') {
        // Diegetic card back: sunlit inner filigree frame + Light Star emblem
        p.topG.roundRect(-hw + 3, -hh + 3, PILE_CARD_W - 6, PILE_CARD_H - 6, 2.2)
          .fill({ color: p.def.wash })
          .stroke({ width: 0.75, color: theme.border, alpha: 0.6 });
        p.topG.poly([0, -hh + 7, hw - 7, 0, 0, hh - 7, -hw + 7, 0])
          .stroke({ width: 0.75, color: theme.accent, alpha: 0.35 });
        drawLightStar(p.topG, 0, 0, 6.2, theme.accent, 0.88);
      } else if (p.def.key === 'delayed_discard') {
        // Delayed discard stack: warm top gold bar + editorial rules + diamond seal
        p.topG.roundRect(-hw + 1, -hh + 1, PILE_CARD_W - 2, 3.2, 1.6)
          .fill({ color: INK.gold });
        p.topG.roundRect(-hw + 3.2, -hh + 6, PILE_CARD_W - 6.4, PILE_CARD_H - 10, 2)
          .fill({ color: p.def.wash, alpha: 0.75 });
        p.topG.moveTo(-hw + 6, -4).lineTo(hw - 6, -4).stroke({ width: 1.1, color: INK.gold, alpha: 0.65 });
        p.topG.moveTo(-hw + 6, 1.5).lineTo(hw - 8, 1.5).stroke({ width: 1.0, color: INK.line, alpha: 0.85 });
        p.topG.moveTo(-hw + 6, 7).lineTo(hw - 10, 7).stroke({ width: 1.0, color: INK.line, alpha: 0.7 });
        p.topG.poly([0, -11.5, 3.5, -8, 0, -4.5, -3.5, -8])
          .fill({ color: INK.goldDeep, alpha: 0.85 });
      } else {
        // Out-of-combat archive stack: tucked parchment seal
        p.topG.roundRect(-hw + 1, -hh + 1, PILE_CARD_W - 2, 3, 1.5)
          .fill({ color: INK.secondary, alpha: 0.85 });
        p.topG.roundRect(-hw + 3.2, -hh + 6, PILE_CARD_W - 6.4, PILE_CARD_H - 10, 2)
          .fill({ color: p.def.wash, alpha: 0.9 });
        p.topG.circle(0, 1, 5.4)
          .stroke({ width: 1.1, color: INK.secondary, alpha: 0.72 });
        p.topG.circle(0, 1, 2.0)
          .fill({ color: INK.secondary, alpha: 0.72 });
      }

      // Brief warm arrival/departure flash rim
      if (p.flashAlpha > 0.02) {
        p.topG.roundRect(-hw - 1.5, -hh - 1.5, PILE_CARD_W + 3, PILE_CARD_H + 3, r + 1.5)
          .stroke({ width: 1.8, color: INK.gold, alpha: p.flashAlpha * 0.85 });
      }
    } else {
      p.topCard.visible = false;
    }

    // 4. Crisp numeric count badge pinned cleanly on bottom-right corner
    const badgeX = hw - 2;
    const badgeY = hh - 3 - Math.min(stackH * 0.35, 3.5) + bounceY * 0.35;
    const countStr = String(count);
    const bw = count >= 10 ? 19 : 15;
    const bh = 13.5;

    p.badgeG.clear();
    p.badgeG.roundRect(badgeX - bw * 0.5, badgeY - bh * 0.5, bw, bh, 5)
      .fill({ color: active ? p.def.accent : INK.paperSoft })
      .stroke({ width: 1.1, color: active ? INK.paper : INK.line, alpha: 0.95 });

    p.countText.text = countStr;
    p.countText.style.fill = active ? INK.paper : INK.muted;
    p.countText.position.set(badgeX, badgeY + 0.3);

    p.labelText.style.fill = active
      ? (hover > 0.3 && clickableNow ? INK.goldDeep : p.def.accent)
      : INK.muted;
  }

  for (let i = 0; i < pileDefs.length; i++) {
    createPileSlot(pileDefs[i], i);
  }

  root._boxWidth = totalW;
  root._boxHeight = PILE_CARD_H + PILE_MAX_STACK_H + 16;

  root.pulsePile = (key, strength = 1.0) => {
    const p = pileMap.get(key);
    if (!p) return;
    const s = clamp(Number(strength) || 1, 0.25, 1.8);
    p.bounceSpring.vel -= 125 * s;
    p.squashSpring.vel += 2.6 * s;
    p.flashAlpha = Math.min(1, 0.85 * s);
    p.dirty = true;
  };

  root.sync = ({
    drawCount = 0,
    discardCount = 0,
    outCount = 0,
    discardCards = [],
    outCards = [],
    playerName: nextName = '',
  } = {}) => {
    if (nextName) playerName = nextName;
    const updates = [
      { key: 'draw', count: Math.max(0, Math.round(Number(drawCount) || 0)), cards: null },
      { key: 'delayed_discard', count: Math.max(0, Math.round(Number(discardCount) || 0)), cards: Array.isArray(discardCards) ? discardCards : [] },
      { key: 'out_of_combat', count: Math.max(0, Math.round(Number(outCount) || 0)), cards: Array.isArray(outCards) ? outCards : [] },
    ];

    for (const u of updates) {
      const p = pileMap.get(u.key);
      if (!p) continue;
      const changed = hasSyncedOnce && p.count !== u.count;
      p.count = u.count;
      if (u.cards !== null) p.cards = u.cards;
      p.heightSpring.target = targetStackHeight(u.count);
      if (!hasSyncedOnce) {
        p.heightSpring.value = p.heightSpring.target;
        p.heightSpring.vel = 0;
      } else if (changed) {
        root.pulsePile(u.key, 0.65);
      }
      p.dirty = true;
    }

    hasSyncedOnce = true;
    for (const p of pileMap.values()) {
      drawPile(p);
    }
  };

  root.setPosition = (x, y) => {
    originX = Number(x) || 0;
    originY = Number(y) || 0;
    root.position.set(originX, originY);
  };

  root.getPileAnchor = (key) => {
    const p = pileMap.get(key) || pileMap.get('draw');
    if (!p) return { x: originX, y: originY };
    return {
      x: originX + p.cx,
      y: originY + p.cy - Math.max(0, p.heightSpring.value),
    };
  };

  root.tick = (dtSec) => {
    const dt = clamp(Number(dtSec) || 0, 0, 0.05);
    if (dt <= 0) return;

    for (const p of pileMap.values()) {
      const moving =
        p.dirty
        || Math.abs(p.heightSpring.value - p.heightSpring.target) > 0.04
        || Math.abs(p.heightSpring.vel) > 0.05
        || Math.abs(p.bounceSpring.value) > 0.04
        || Math.abs(p.bounceSpring.vel) > 0.05
        || Math.abs(p.squashSpring.value) > 0.004
        || Math.abs(p.squashSpring.vel) > 0.01
        || Math.abs(p.hoverSpring.value - p.hoverSpring.target) > 0.004
        || Math.abs(p.hoverSpring.vel) > 0.01
        || p.flashAlpha > 0.01;

      if (!moving) continue;

      stepScalarSpring(p.heightSpring, dt);
      stepScalarSpring(p.bounceSpring, dt);
      stepScalarSpring(p.squashSpring, dt);
      stepScalarSpring(p.hoverSpring, dt);
      if (p.flashAlpha > 0) {
        p.flashAlpha = Math.max(0, p.flashAlpha - dt * 2.8);
      }

      drawPile(p);
      p.dirty = false;
    }
  };

  const baseDestroy = root.destroy.bind(root);
  root.destroy = (opts = { children: true }) => {
    pileMap.clear();
    if (!root.destroyed) baseDestroy(opts);
  };

  return root;
}
