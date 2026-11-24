/**
 * Pure Canvas 2.5D Living Tabletop Engine for 《光点计划 III》.
 *
 * ZERO webpage popovers / tooltips / duplicate inspection overlays:
 *  - Hovering ANY card on the tabletop physically lifts THAT EXACT CARD in place via its own
 *    `inspectSpring` (smoothly scaling from its tabletop scale to 1.0× full clarity, rising to
 *    front z-order, clamping cleanly inside screen bounds, and settling back when unhovered).
 *  - Active, genuine state machines on every Duel Row & Card Entity:
 *      DuelRowState:  'spawning' -> 'idle' | 'active' | 'completed'
 *      CardState:     'entering' -> 'idle' | 'active' | 'settled' | 'destroyed' + 'inspecting'
 *      CameraState:   'auto_follow' | 'user_inspecting'
 *    Every state transition is evaluated in `tick()` and directly drives spring targets, z-order,
 *    mask bypass while lifted, and wheel routing.
 *  - Strict Left-Right Symmetry: Left is ALWAYS P1, Right is ALWAYS P2, duel emblem sits dead
 *    center (`x = 0`).
 *  - Strictly flat (rotation = 0), strictly uniform physical card size (1 动 0 字 ≡ 30 动 1000 字).
 */

import * as PIXI from '../vendor/pixi.min.mjs';
import {
  FONT_NUM,
  FONT_UI,
  INK,
  SIDE_THEME,
  deriveCardPalette,
  drawCostCrystal,
} from './design_system.js';
import { buildCardBack, buildUniformCard } from './card_print.js';
import { makeSealButton } from './table_overlays.js';

const CIRCLED = ['①', '②', '③', '④', '⑤', '⑥', '⑦', '⑧', '⑨', '⑩'];
const KIND_LABEL = { pre_reveal: '开', pre_reveal_draft: '预', instant: '即', regular: '常' };

function duelShortMark(duel) {
  const num = CIRCLED[(duel.number || 1) - 1] || String(duel.number || 1);
  if (duel.kind === 'regular') return num;
  return `${KIND_LABEL[duel.kind] || ''}${num}`;
}

function clamp(v, lo, hi) {
  return Math.max(lo, Math.min(hi, v));
}

function smoothstep(edge0, edge1, x) {
  const t = clamp((x - edge0) / Math.max(1e-6, edge1 - edge0), 0, 1);
  return t * t * (3 - 2 * t);
}

function lerp(a, b, t) {
  return a + (b - a) * t;
}

/**
 * Exact analytical critically-damped 1D spring ODE solution:
 *   x(dt) = target + (x0 + (v0 + ω·x0)·dt) · exp(-ω·dt)
 *   v(dt) = (v0 - ω·(v0 + ω·x0)·dt) · exp(-ω·dt)
 * Unconditionally stable, 100% frame-rate independent (60/144/240Hz identical), C∞ smooth, zero overshoot.
 */
class Spring1D {
  constructor(initial = 0, { omega = 13.5, precision = 0.001 } = {}) {
    this.value = initial;
    this.target = initial;
    this.velocity = 0;
    this.omega = omega;
    this.precision = precision;
  }

  snap(v) {
    this.value = v;
    this.target = v;
    this.velocity = 0;
  }

  setTarget(v) {
    this.target = v;
  }

  impulse(dv) {
    this.velocity += dv;
  }

  get settled() {
    return Math.abs(this.value - this.target) < this.precision
      && Math.abs(this.velocity) < this.precision * this.omega;
  }

  step(dtSec) {
    const dt = Math.min(0.05, Math.max(0.0005, dtSec));
    const x0 = this.value - this.target;
    const v0 = this.velocity;
    const w = this.omega;
    const expTerm = Math.exp(-w * dt);
    const c2 = v0 + w * x0;

    this.value = this.target + (x0 + c2 * dt) * expTerm;
    this.velocity = (v0 - w * c2 * dt) * expTerm;

    if (this.settled) {
      const changed = this.value !== this.target || this.velocity !== 0;
      this.value = this.target;
      this.velocity = 0;
      return changed;
    }
    return true;
  }
}

/**
 * Exact analytical underdamped 2nd-order harmonic oscillator (0 < ζ < 1):
 *   ω_d = ω_n · √(1 - ζ²)
 *   x(dt) = target + e^(-ζω_n dt) · [x0·cos(ω_d dt) + ((v0 + ζω_n x0) / ω_d)·sin(ω_d dt)]
 *   v(dt) =          e^(-ζω_n dt) · [v0·cos(ω_d dt) - ((ω_n² x0 + ζω_n v0) / ω_d)·sin(ω_d dt)]
 * Used for tactile touchdown compression/rebound on card impact — frame-rate independent.
 */
class UnderdampedSpring1D {
  constructor(initial = 0, { omega = 32.0, zeta = 0.46, precision = 0.0015 } = {}) {
    this.value = initial;
    this.target = initial;
    this.velocity = 0;
    this.omega = omega;
    this.zeta = clamp(zeta, 0.08, 0.96);
    this.precision = precision;
  }

  snap(v) {
    this.value = v;
    this.target = v;
    this.velocity = 0;
  }

  setTarget(v, { omega = null, zeta = null } = {}) {
    this.target = v;
    if (omega !== null) this.omega = omega;
    if (zeta !== null) this.zeta = clamp(zeta, 0.08, 0.98);
  }

  impulse(dv) {
    this.velocity += dv;
  }

  get settled() {
    return Math.abs(this.value - this.target) < this.precision
      && Math.abs(this.velocity) < this.precision * this.omega;
  }

  step(dtSec) {
    const dt = Math.min(0.05, Math.max(0.0005, dtSec));
    const x0 = this.value - this.target;
    const v0 = this.velocity;
    const wn = this.omega;
    const z = this.zeta;
    const wd = wn * Math.sqrt(1 - z * z);
    const decay = Math.exp(-z * wn * dt);
    const cosT = Math.cos(wd * dt);
    const sinT = Math.sin(wd * dt);

    const A = x0;
    const B = (v0 + z * wn * x0) / wd;
    this.value = this.target + decay * (A * cosT + B * sinT);
    this.velocity = decay * (v0 * cosT - ((wn * wn * x0 + z * wn * v0) / wd) * sinT);

    if (this.settled) {
      const changed = this.value !== this.target || this.velocity !== 0;
      this.value = this.target;
      this.velocity = 0;
      return changed;
    }
    return true;
  }
}

/**
 * Cubic Hermite spline evaluation & analytical first derivative:
 *   P(s)  = h00(s)·p0 + h10(s)·m0 + h01(s)·p1 + h11(s)·m1
 *   P'(s) = h00'(s)·p0 + h10'(s)·m0 + h01'(s)·p1 + h11'(s)·m1
 */
function evalHermite1D(p0, m0, p1, m1, s) {
  const s2 = s * s;
  const s3 = s2 * s;
  const h00 = 2 * s3 - 3 * s2 + 1;
  const h10 = s3 - 2 * s2 + s;
  const h01 = -2 * s3 + 3 * s2;
  const h11 = s3 - s2;
  const val = h00 * p0 + h10 * m0 + h01 * p1 + h11 * m1;
  const dh00 = 6 * s2 - 6 * s;
  const dh10 = 3 * s2 - 4 * s + 1;
  const dh01 = -6 * s2 + 6 * s;
  const dh11 = 3 * s2 - 2 * s;
  const deriv = dh00 * p0 + dh10 * m0 + dh01 * p1 + dh11 * m1;
  return { val, deriv };
}

/**
 * Asymmetric quintic-ease flight time warp s(u) ∈ [0, 1]:
 *   Launch has brisk initial momentum (s'(0) = 0.65), zero arrival velocity (s'(1) = 0),
 *   and negative arrival acceleration (s''(1) < 0) so the card snaps decisively into its slot.
 */
function flightTimeWarp(u) {
  const t = clamp(u, 0, 1);
  const inv = 1 - t;
  const inv2 = inv * inv;
  const inv3 = inv2 * inv;
  // s(t) = 1 - (1 - t)^3 * (1 + 2.35*t - 0.65*t^2)  -> s(0)=0, s(1)=1, s'(0)=0.65, s'(1)=0
  const s = 1 - inv3 * (1 + 2.35 * t - 0.65 * t * t);
  const ds = 3 * inv2 * (1 + 2.35 * t - 0.65 * t * t) - inv3 * (2.35 - 1.30 * t);
  return { s: clamp(s, 0, 1), ds };
}

export class CombatTabletop {
  constructor(parentLayer, {
    resolveCharColor,
    resolveCardOwner,
    resolveCardBack,
    getCharName,
    onCardLand,
    onHoverCard,
    onSlotTap,
    onAttackDuel,
    onInterceptDuel,
    onLetThrough,
    onUnstagePreReveal,
    markEffectTarget,
  } = {}) {
    this.resolveCharColor = resolveCharColor || ((_, side) => SIDE_THEME[side]?.accent || INK.gold);
    this.resolveCardOwner = resolveCardOwner || null;
    this.resolveCardBack = resolveCardBack || null;
    this.getCharName = getCharName || (() => '');
    this.onCardLand = onCardLand || null;
    this.onHoverCard = onHoverCard || null;
    this.onSlotTap = onSlotTap || null;
    this.onAttackDuel = onAttackDuel || null;
    this.onInterceptDuel = onInterceptDuel || null;
    this.onLetThrough = onLetThrough || null;
    this.onUnstagePreReveal = onUnstagePreReveal || null;
    this.markEffectTarget = markEffectTarget || null;

    this.root = new PIXI.Container();
    this.stageClip = new PIXI.Container();
    this.stageMask = new PIXI.Graphics();
    this.depthLayer = new PIXI.Container();
    // Damped mathematical touchdown ripples rendered on the tabletop surface
    this.impactRippleLayer = new PIXI.Graphics();
    // Projected altitude drop-shadow layer beneath airborne cards
    this.flightShadowLayer = new PIXI.Graphics();
    // Unclipped top layer where THE ACTUAL physical card temporarily reparents while airborne or lifted
    this.liftedLayer = new PIXI.Container();

    this.stageClip.addChild(this.stageMask, this.depthLayer, this.impactRippleLayer);
    this.depthLayer.mask = this.stageMask;
    this.impactRippleLayer.mask = this.stageMask;

    this.root.addChild(this.stageClip, this.flightShadowLayer, this.liftedLayer);
    parentLayer.addChild(this.root);

    this.layout = { arenaX: 280, arenaW: 720, stageTop: 206, stageH: 480 };
    this.duels = [];
    this.activeIndex = 0;
    this.combat = null;
    this.concealBySide = new Map();
    this.activeSide = 1;
    this.viewerSide = 1;
    this.cardsRevealed = false;
    this.pendingResponses = new Set();
    this.attackableDuels = new Set();
    this.canClickIntercept = false;
    this.canTapEmptySlot = false;

    // Global Tabletop State Machine
    this.phaseState = 'placement';    // 'placement' | 'reveal' | 'combat'
    this.cameraState = 'auto_follow'; // 'auto_follow' | 'user_inspecting'
    this._lastActiveKey = null;

    // Global Camera & Phase Analytical Springs (natural frequency ω in rad/s)
    this.focusSpring = new Spring1D(0, { omega: 13.5, precision: 0.001 });
    this.combatBlendSpring = new Spring1D(0, { omega: 11.5, precision: 0.0015 });
    this.overviewOriginSpring = new Spring1D(0, { omega: 13.0, precision: 0.2 });
    this._originInitialized = false;

    // Persistent Per-Duel, Per-Card, and Per-Stack-Tab State Machines
    this.duelMotionMap = new Map(); // duelKey -> { state, ySpring, scaleSpring, alphaSpring, markAlphaSpring }
    this.cardMotionMap = new Map(); // cardKey -> { state, hovered, dwellTimer, enterCooldown, anchorX, anchorY, flight, impactSpring, inspectSpring }
    this.tabMotionMap = new Map();  // tabKey  -> { state, hovered, dwellTimer, slideSpring }

    // Pending Hermite flight launches registered from hand release (cardId -> launchKinematics)
    this.pendingLaunches = new Map();
    // Active damped tabletop impact ripples [{ x, y, w, h, color, age, duration }]
    this.impactRipples = [];

    this.cardScrollByKey = new Map();
    this.hoveredStackChoice = new Map();
    this.inspectedCardKey = null;
    this.interactiveCardRects = []; // [{ cardKey, x, y, w, h, node, isInspecting }]
    this.combatCardRects = new Map();
    this.placementSlotRects = new Map();
    this.regularLaneRects = new Map();
    this.preRevealSlotRects = new Map();
    this.depthSlotEntries = [];

    this._lastPointerX = 0;
    this._lastPointerY = 0;
    this._lastPointerTime = 0;
    this._pointerSpeed = 0;
    this._lastInspectEndedAt = 0;
    this._lastStepWheelMs = 0;
    this._hasRenderedInitialPlacement = false;
  }

  /**
   * Register exact physical release kinematics (position, velocity, angle, scale) from a hand card
   * so its airborne Hermite spline starts C¹-continuously from the player's actual release state.
   */
  registerPlacementLaunch(cardId, { fromX, fromY, vx = 0, vy = -380, rot0 = 0, scale0 = 0.86, color = INK.gold } = {}) {
    if (!cardId) return;
    this.pendingLaunches.set(String(cardId), {
      fromX, fromY, vx, vy, rot0, scale0, color, createdAt: performance.now(),
    });
  }

  attachTo(parentLayer) {
    if (this.root.parent !== parentLayer) {
      parentLayer.addChild(this.root);
    }
  }

  resetMatch(combatInit = 0) {
    this.duelMotionMap.clear();
    this.cardMotionMap.clear();
    this.tabMotionMap.clear();
    this.pendingLaunches.clear();
    this.impactRipples = [];
    this.impactRippleLayer.clear();
    this.flightShadowLayer.clear();
    this.cardScrollByKey.clear();
    this.hoveredStackChoice.clear();
    this.inspectedCardKey = null;
    this.focusSpring.snap(0);
    this.combatBlendSpring.snap(combatInit);
    this._originInitialized = false;
    this._hasRenderedInitialPlacement = false;
    this.cameraState = 'auto_follow';
    this._lastActiveKey = null;
  }

  setLayout({ arenaX, arenaW, stageTop, stageH }) {
    this.layout = { arenaX, arenaW, stageTop, stageH };
    this._computeCardMetrics();
    this.stageMask.clear().rect(arenaX - 24, stageTop - 4, arenaW + 48, stageH + 8).fill({ color: 0xffffff });
    this._syncOriginTarget(false);
    this._rebuildDepthPool();
    this._applyStateMachineTargets(false);
    this._layoutDepthFrame(true);
  }

  _computeCardMetrics() {
    const { arenaX, arenaW, stageTop, stageH } = this.layout;
    const pairGap = 28;
    const maxCardWByWidth = Math.floor((arenaW - pairGap - 36) / 2);
    const maxCardWByHeight = Math.floor((stageH * 0.72) / 1.40);
    const cardW = Math.round(clamp(Math.min(maxCardWByWidth, maxCardWByHeight), 184, 248));
    const cardH = Math.round(cardW * 1.40);

    const overviewScale = clamp(Math.min(0.62, (stageH * 0.29) / cardH), 0.44, 0.62);
    const overviewStepY = cardH * overviewScale + 14;

    this.metrics = {
      cardW,
      cardH,
      pairGap,
      overviewScale,
      overviewStepY,
      centerX: arenaX + arenaW * 0.5,
      combatFocusY: stageTop + cardH * 0.5 + 8,
    };
  }

  _syncOriginTarget(snap = false) {
    if (!this.metrics) return;
    const { stageTop, stageH } = this.layout;
    const { cardH, overviewStepY } = this.metrics;
    const n = Math.max(1, this.duels.length);
    // Guarantee the topmost duel row has enough headroom to expand 1.0x around its own center with 0px shift
    const maxOrigin = Math.max(stageTop + overviewStepY * 0.5 + 8, cardH * 0.5 + 10);
    const minOrigin = Math.min(maxOrigin, stageTop + stageH - 12 - (n - 0.5) * overviewStepY);

    const focusVal = clamp(this.focusSpring.target, 0, Math.max(0, n - 1));
    let targetOriginY = this._originInitialized ? clamp(this.overviewOriginSpring.target, minOrigin, maxOrigin) : maxOrigin;

    const focusY = targetOriginY + focusVal * overviewStepY;
    const padTop = stageTop + overviewStepY * 0.5 + 4;
    const padBot = stageTop + stageH - overviewStepY * 0.5 - 8;
    if (focusY > padBot) {
      targetOriginY -= (focusY - padBot);
    } else if (focusY < padTop) {
      targetOriginY += (padTop - focusY);
    }
    targetOriginY = clamp(targetOriginY, minOrigin, maxOrigin);

    if (snap || !this._originInitialized) {
      this.overviewOriginSpring.snap(targetOriginY);
      this._originInitialized = true;
    } else {
      this.overviewOriginSpring.setTarget(targetOriginY);
    }
  }

  snapToActive() {
    this.cameraState = 'auto_follow';
    this.focusSpring.setTarget(this.activeIndex);
    this._syncOriginTarget(false);
  }

  /**
   * Trigger staggered in-place 2.5D horizontal cosine flip on all regular duel cards during `cards_reveal`.
   */
  triggerRevealFlip() {
    let idx = 0;
    for (const entry of this.depthSlotEntries) {
      if (entry.duel.kind !== 'regular') continue;
      for (const side of [1, 2]) {
        const sw = entry.sideWidgets[side];
        if (!sw?.cardMotion || !sw.card || sw.card.hidden) continue;
        sw.cardMotion.revealFlip = {
          delay: idx * 0.055,
          age: 0,
          duration: 0.28,
        };
      }
      idx += 1;
    }
  }

  setState({
    duels = [],
    activeIndex = 0,
    combat = null,
    concealBySide = new Map(),
    isPlacement = false,
    overview = false,
    activeSide = 1,
    viewerSide = 1,
    cardsRevealed = false,
    pendingResponses = null,
    attackableDuels = null,
    canClickIntercept = false,
    interceptableNumbers = null,
    canTapEmptySlot = false,
  }) {
    this.duels = duels;
    this.phaseState = isPlacement ? 'placement' : overview ? 'reveal' : 'combat';
    this.activeIndex = clamp(activeIndex, 0, Math.max(0, duels.length - 1));
    this.combat = combat;
    this.concealBySide = concealBySide;
    this.activeSide = activeSide || 1;
    this.viewerSide = viewerSide ?? null;
    this.cardsRevealed = Boolean(cardsRevealed);
    this.pendingResponses = pendingResponses instanceof Set ? pendingResponses : new Set(pendingResponses || []);
    this.attackableDuels = attackableDuels instanceof Set ? attackableDuels : new Set(attackableDuels || []);
    this.canClickIntercept = Boolean(canClickIntercept);
    this.interceptableNumbers = interceptableNumbers || this.pendingResponses;
    this.canTapEmptySlot = Boolean(canTapEmptySlot);

    this.combatBlendSpring.setTarget(this.phaseState === 'combat' ? 1 : 0);

    const activeDuel = this.duels[this.activeIndex];
    const activeKey = activeDuel ? activeDuel.key : null;
    if (activeKey !== this._lastActiveKey) {
      this._lastActiveKey = activeKey;
      this.cameraState = 'auto_follow';
      this.focusSpring.setTarget(this.activeIndex);
      if (this.duels.length && Math.abs(this.focusSpring.value - this.activeIndex) > this.duels.length) {
        this.focusSpring.snap(this.activeIndex);
      }
    } else if (this.cameraState === 'auto_follow') {
      this.focusSpring.setTarget(this.activeIndex);
    } else {
      this.focusSpring.target = clamp(this.focusSpring.target, 0, Math.max(0, this.duels.length - 1));
    }

    this._computeCardMetrics();
    this._syncOriginTarget(false);
    this._rebuildDepthPool();
    this._applyStateMachineTargets(false);
    this._layoutDepthFrame(true);
  }

  setPointer(x, y) {
    const now = performance.now();
    const dt = (now - this._lastPointerTime) / 1000;
    if (this._lastPointerTime > 0 && dt > 0.002 && dt < 0.12) {
      const dist = Math.hypot(x - this._lastPointerX, y - this._lastPointerY);
      const instSpeed = dist / dt;
      this._pointerSpeed = this._pointerSpeed * 0.5 + instSpeed * 0.5;
    } else if (dt >= 0.12) {
      this._pointerSpeed = 0;
    }
    this._lastPointerX = x;
    this._lastPointerY = y;
    this._lastPointerTime = now;
  }

  handleWheel(deltaY) {
    if (!this.duels.length) return false;
    const x = this._lastPointerX;
    const y = this._lastPointerY;
    const { arenaX, arenaW, stageTop, stageH } = this.layout;
    if (x < arenaX - 24 || x > arenaX + arenaW + 24 || y < stageTop - 160 || y > stageTop + stageH + 16) {
      return false;
    }

    // 1. Overflowing card currently under cursor (lifted OR full-size focused card) takes wheel priority
    for (const item of this.interactiveCardRects) {
      if (
        item.node && !item.node.destroyed && item.node.maxScroll > 0
        && x >= item.x && x <= item.x + item.w
        && y >= item.y && y <= item.y + item.h
      ) {
        item.node.scrollBy(deltaY * 0.65);
        this.cardScrollByKey.set(item.cardKey, item.node.scrollY);
        return true;
      }
    }

    // 2. Smooth spring-driven integer duel stepping along the SINGLE vertical axis
    if (this.duels.length > 1) {
      const now = performance.now();
      if (now - this._lastStepWheelMs < 80) return true;
      this._lastStepWheelMs = now;
      const dir = deltaY > 0 ? 1 : -1;
      const nextIdx = clamp(Math.round(this.focusSpring.target) + dir, 0, this.duels.length - 1);
      if (nextIdx === Math.round(this.focusSpring.target)) {
        this.focusSpring.impulse(dir * 1.4);
      } else {
        this.focusSpring.setTarget(nextIdx);
        this.cameraState = nextIdx === this.activeIndex ? 'auto_follow' : 'user_inspecting';
        this._syncOriginTarget(false);
      }
      this._clearInspection();
      return true;
    }
    return false;
  }

  _clearInspection() {
    if (!this.inspectedCardKey) return;
    const prev = this.cardMotionMap.get(this.inspectedCardKey);
    if (prev) prev.hovered = false;
    this.inspectedCardKey = null;
  }

  /**
   * Unified C∞ Analytical Tabletop Geometry:
   *  - Scale:  s(u) = sInf + (1 - sInf) / (1 + (α·u)²)               [Lorentzian perspective, s'(0) = 0]
   *  - Y(d):   ∫₀ᵈ (H + g)·s(u) du = (H + g)·[sInf·d + ((1 - sInf)/α)·atan(α·d)]
   *            Exact closed-form integral guaranteeing strictly proportional non-overlapping air gaps
   *            and C∞ smooth velocity across d = 0!
   *  - Alpha:  1 / (1 + (β·d)²)                                      [smooth peak at d = 0, zero kink]
   */
  _evalTargetPose(index, d, combatBlend) {
    const { cardH, overviewScale, overviewStepY, combatFocusY } = this.metrics;

    // A. Equal-scale strategic tabletop (placement / reveal)
    const equalY = this.overviewOriginSpring.value + index * overviewStepY;
    const equalScale = overviewScale;
    const distFromStageCenter = Math.abs(equalY - (this.layout.stageTop + this.layout.stageH * 0.5));
    const equalAlpha = clamp(1 - smoothstep(this.layout.stageH * 0.44, this.layout.stageH * 0.62, distFromStageCenter), 0, 1);

    // B. Exact Lorentzian-arctan analytical combat focal geometry
    const sInf = 0.28;
    const alphaK = 1.15;
    const baseGap = 24;
    const combatScale = sInf + (1 - sInf) / (1 + (alphaK * d) * (alphaK * d));
    const combatY = combatFocusY + (cardH + baseGap) * (sInf * d + ((1 - sInf) / alphaK) * Math.atan(alphaK * d));
    const betaK = 0.52;
    const combatAlpha = 1 / (1 + (betaK * d) * (betaK * d));

    const t = clamp(combatBlend, 0, 1);
    const markAlpha = lerp(0.92, 1 - 1 / (1 + (2.4 * d) * (2.4 * d)), t);
    return {
      y: lerp(equalY, combatY, t),
      scale: lerp(equalScale, combatScale, t),
      alpha: lerp(equalAlpha, combatAlpha, t),
      markAlpha,
    };
  }

  _ensureDuelMotion(duelKey, initialPose) {
    let dm = this.duelMotionMap.get(duelKey);
    if (!dm) {
      dm = {
        state: 'spawning',
        ySpring: new Spring1D(initialPose.y, { omega: 14.5, precision: 0.2 }),
        scaleSpring: new Spring1D(initialPose.scale, { omega: 14.5, precision: 0.002 }),
        alphaSpring: new Spring1D(0, { omega: 13.0, precision: 0.004 }),
        markAlphaSpring: new Spring1D(0, { omega: 13.0, precision: 0.004 }),
      };
      this.duelMotionMap.set(duelKey, dm);
    }
    return dm;
  }

  _ensureCardMotion(cardKey, {
    isFreshPlacement = false,
    side = 1,
    card = null,
    targetX = 0,
    targetY = 0,
    targetScale = 0.56,
    accentColor = INK.gold,
  } = {}) {
    let cm = this.cardMotionMap.get(cardKey);
    if (!cm) {
      // Match any explicit hand-release kinematics registered by the player
      let launch = null;
      if (card) {
        const keys = [card.action_key, card.id, card.instance_id != null ? `instance:${card.instance_id}` : null].filter(Boolean);
        for (const k of keys) {
          if (this.pendingLaunches.has(String(k))) {
            launch = this.pendingLaunches.get(String(k));
            this.pendingLaunches.delete(String(k));
            break;
          }
        }
      }

      let flight = null;
      const shouldFly = Boolean(launch) || (isFreshPlacement && this._hasRenderedInitialPlacement);
      if (shouldFly) {
        const { arenaX, arenaW, stageTop, stageH } = this.layout;
        // Properly distinguish viewer's own hand (bottom) vs opponent's side edge (top-left for P1, top-right for P2)!
        const isOpponentCard = this.viewerSide != null && side !== this.viewerSide;
        const oppEdgeX = side === 1 ? (arenaX - 130) : (arenaX + arenaW + 130);
        const fromX = launch ? launch.fromX : (isOpponentCard ? oppEdgeX : arenaX + arenaW * 0.5);
        const fromY = launch ? launch.fromY : (isOpponentCard ? stageTop - 36 : stageTop + stageH + 140);
        const vx = launch ? launch.vx : (isOpponentCard ? (side === 1 ? 420 : -420) : (targetX - fromX) * 0.45);
        const vy = launch ? launch.vy : (isOpponentCard ? 120 : -460);
        const rot0 = launch ? launch.rot0 : (isOpponentCard ? (side === 1 ? -0.14 : 0.14) : -0.08);
        const scale0 = launch ? launch.scale0 : Math.min(0.84, targetScale * 1.18);
        const dx = targetX - fromX;
        const dy = targetY - fromY;
        const dist = Math.hypot(dx, dy);
        const duration = clamp(0.26 + 0.00028 * dist, 0.28, 0.44);
        const peakZ = clamp(54 + 0.14 * dist, 62, 146);

        flight = {
          fromX,
          fromY,
          // Cubic Hermite endpoint tangents scaled by duration (C¹ continuous with release velocity!)
          m0x: clamp(vx * duration, -520, 520),
          m0y: clamp(vy * duration, -560, 420),
          m1x: dx * 0.12,
          m1y: Math.max(85, Math.abs(dy) * 0.34),
          rot0,
          scale0,
          peakZ,
          duration,
          age: 0,
          side,
          accentColor: launch?.color ?? accentColor,
        };
      }

      cm = {
        state: flight ? 'airborne' : 'idle',
        hovered: false,
        dwellTimer: 0,
        enterCooldown: flight ? 0.28 : 0,
        flight,
        impactSpring: new UnderdampedSpring1D(0, { omega: 34.0, zeta: 0.46, precision: 0.0015 }),
        // Dual-regime tactile lift oscillator:
        // Lift-up: underdamped (ω=42, ζ=0.72) + initial impulse -> crisp ~3.8% overshoot, ~100ms settle.
        // Put-down: high-damping fast tuck (ω=52, ζ=0.92) + downward impulse -> ~80ms crisp return.
        inspectSpring: new UnderdampedSpring1D(0, { omega: 42.0, zeta: 0.72, precision: 0.01 }),
      };
      this.cardMotionMap.set(cardKey, cm);
    }
    return cm;
  }

  _ensureTabMotion(tabKey) {
    let tm = this.tabMotionMap.get(tabKey);
    if (!tm) {
      tm = {
        state: 'peeking', // 'peeking' | 'hover_dwell' | 'promoted'
        hovered: false,
        dwellTimer: 0,
        slideSpring: new Spring1D(0, { omega: 18.0, precision: 0.003 }),
      };
      this.tabMotionMap.set(tabKey, tm);
    }
    return tm;
  }

  _pickSideCards(duel, side) {
    const se = (duel.sides || []).find((s) => s.side === side);
    return [...(se?.cards || []), ...(se?.resolved_cards || [])].filter(Boolean);
  }

  _resolveFrontCardIndex(duel, side, cards) {
    if (!cards.length) return -1;
    const stackKey = `${duel.key}:${side}`;
    const hoveredKey = this.hoveredStackChoice.get(stackKey);
    if (hoveredKey) {
      const hi = cards.findIndex((c) => `${duel.key}:${side}:${c.instance_id ?? c.id}` === hoveredKey);
      if (hi >= 0) return hi;
    }
    if (duel.status === 'active' && this.combat) {
      const cs = (this.combat.sides || []).find((s) => s.side === side);
      if (cs?.card_instance_id != null || cs?.card_id) {
        const ai = cards.findIndex((c) => (cs.card_instance_id != null
          ? c.instance_id === cs.card_instance_id
          : c.id === cs.card_id));
        if (ai >= 0) return ai;
      }
      return cards.length - 1;
    }
    if (duel.status === 'completed') return cards.length - 1;
    return 0;
  }

  _cardStatusBadge(duel, side, card, isActiveCard) {
    if (card.dissolved) return 'dissolved';
    if (card.skipped) return 'skipped';
    if (duel.status === 'completed') return 'settled';
    if (duel.status === 'active' && !isActiveCard && card.used) return 'settled';
    return null;
  }

  _rebuildDepthPool() {
    this._clear(this.depthLayer);
    this._clear(this.liftedLayer);
    this.depthSlotEntries = [];
    const { cardW, cardH } = this.metrics;
    const isPlacement = this.phaseState === 'placement';
    const combatBlend = clamp(this.combatBlendSpring.value, 0, 1);

    this.duels.forEach((duel, index) => {
      const d = index - this.focusSpring.value;
      const initPose = this._evalTargetPose(index, d, combatBlend);
      const dm = this._ensureDuelMotion(duel.key, initPose);

      const row = new PIXI.Container();
      const sideWidgets = {};

      const centerEmblem = new PIXI.Container();
      const isLive = duel.status === 'active' && this.phaseState === 'combat';
      const isDone = duel.status === 'completed';
      const isDraft = duel.kind === 'pre_reveal_draft';
      const isPreReveal = duel.kind === 'pre_reveal';
      const isAttackable = duel.kind === 'regular' && this.attackableDuels.has(duel.number);
      const isPendingPreReveal = isPreReveal && this.pendingResponses.has(duel.number);
      const isInterceptable = isPendingPreReveal && this.canClickIntercept && this.interceptableNumbers.has(duel.number) && Boolean(this.onInterceptDuel);
      const emblemG = new PIXI.Graphics();
      const er = (isAttackable || isInterceptable || isPendingPreReveal) ? 14 : 11;
      const emblemFill = (isAttackable || isInterceptable || isPendingPreReveal)
        ? 0xfce6df
        : isDraft ? (duel.draftValid === false || duel.draftAffordable === false ? 0xfde8e4 : 0xfbf3df)
        : isLive ? INK.goldBg : INK.paper;
      const emblemStroke = (isAttackable || isInterceptable || isPendingPreReveal)
        ? 0xcf4932
        : isDraft ? (duel.draftValid === false || duel.draftAffordable === false ? 0xcf4932 : INK.gold)
        : isLive ? INK.gold : isDone ? INK.muted : INK.line;
      emblemG.poly([0, -er, er, 0, 0, er, -er, 0])
        .fill({ color: emblemFill, alpha: 0.96 })
        .stroke({ width: (isAttackable || isInterceptable || isPendingPreReveal || isDraft) ? 1.8 : isLive ? 1.5 : 1.0, color: emblemStroke, alpha: 0.94 });
      const emblemT = new PIXI.Text({
        text: duelShortMark(duel),
        style: {
          fontFamily: FONT_NUM,
          fontSize: 9.5,
          fontWeight: '900',
          fill: (isAttackable || isInterceptable || isPendingPreReveal) ? 0xcf4932 : isDraft ? INK.goldDeep : isLive ? INK.goldDeep : isDone ? INK.muted : INK.secondary,
        },
      });
      emblemT.anchor.set(0.5);
      centerEmblem.addChild(emblemG, emblemT);

      // Clickable attack-target callout on attackable regular duels (both during placement staging & pre_attack)
      if (isAttackable && this.onAttackDuel) {
        const atkPill = new PIXI.Graphics();
        atkPill.roundRect(-64, -er - 24, 128, 20, 6)
          .fill({ color: 0xcf4932, alpha: 0.95 })
          .stroke({ width: 1.2, color: 0xffe4b8, alpha: 0.95 });
        const atkTxt = new PIXI.Text({
          text: `⚔ 牵制常规交锋 ${duel.number}`,
          style: { fontFamily: FONT_UI, fontSize: 10, fontWeight: '900', fill: 0xfffaf0 },
        });
        atkTxt.anchor.set(0.5);
        atkTxt.position.set(0, -er - 14);
        centerEmblem.addChild(atkPill, atkTxt);
        centerEmblem.eventMode = 'static';
        centerEmblem.cursor = 'pointer';
        centerEmblem.on('pointertap', (e) => {
          e.stopPropagation();
          this.onAttackDuel(duel.number);
        });
      } else if (isInterceptable) {
        centerEmblem.eventMode = 'static';
        centerEmblem.cursor = 'pointer';
        centerEmblem.on('pointertap', (e) => {
          e.stopPropagation();
          this.onInterceptDuel(duel.number);
        });
      }

      // Target badge pill on live pre-reveal duels (always visible so player knows who/what is targeted)
      if (isPreReveal && duel.target) {
        let tgtLabel = '';
        let badgeBg = 0xfef0ea;
        let badgeStroke = 0xcf4932;
        let badgeTextFill = 0x9c2c18;
        if (duel.target.kind === 'intercept') {
          tgtLabel = `⚔ 已迎击`;
          badgeBg = 0xe6f5ef;
          badgeStroke = 0x1a825e;
          badgeTextFill = 0x126146;
        } else if (duel.target.kind === 'duel') {
          tgtLabel = `→ 牵制常规 ${CIRCLED[(duel.target.number || 1) - 1] || duel.target.number}`;
        } else if (duel.target.kind === 'character') {
          tgtLabel = `→ 目标 · ${duel.target.name || '敌方角色'}`;
        }
        if (tgtLabel) {
          const pillW = Math.max(88, Math.min(148, tgtLabel.length * 10 + 18));
          const pill = new PIXI.Graphics();
          pill.roundRect(-pillW / 2, -er - 22, pillW, 18, 5)
            .fill({ color: badgeBg, alpha: 0.96 })
            .stroke({ width: 1.1, color: badgeStroke, alpha: 0.9 });
          const pt = new PIXI.Text({
            text: tgtLabel,
            style: { fontFamily: FONT_UI, fontSize: 9.5, fontWeight: '800', fill: badgeTextFill },
          });
          pt.anchor.set(0.5);
          pt.position.set(0, -er - 13);
          centerEmblem.addChild(pill, pt);
        }
      }

      const beforeMarkCount = centerEmblem.children.length;
      this.markEffectTarget?.(centerEmblem, duel.kind, duel.number, null, null, -20, -20, 40, 40);
      const forceEmblemVisible = isAttackable || isPendingPreReveal || isDraft || isPreReveal || centerEmblem.children.length > beforeMarkCount;
      row.addChild(centerEmblem);

      for (const side of [1, 2]) {
        const cards = this._pickSideCards(duel, side);
        const sideContainer = new PIXI.Container();
        row.addChild(sideContainer);

        if (!cards.length) {
          // Case A: Private staged pre-reveal draft target plaque (opposite side of attacker)
          if (isDraft) {
            const invalid = duel.draftValid === false || duel.draftAffordable === false;
            const plaque = new PIXI.Graphics();
            plaque.roundRect(-cardW / 2, -cardH / 2, cardW, cardH, 8)
              .fill({ color: invalid ? 0xfdecea : 0xfcf6e8, alpha: 0.92 })
              .stroke({ width: 1.8, color: invalid ? 0xcf4932 : INK.gold, alpha: 0.92 });
            sideContainer.addChild(plaque);
            const hdr = new PIXI.Text({
              text: invalid ? '⚠ 预排需调整' : '预排 · 开牌前交锋',
              style: { fontFamily: FONT_UI, fontSize: 10.5, fontWeight: '900', fill: invalid ? 0xcf4932 : INK.goldDeep },
            });
            hdr.anchor.set(0.5, 0);
            hdr.position.set(0, -cardH / 2 + 16);
            const tgt = new PIXI.Text({
              text: `→ ${duel.targetLabel || '已选目标'}`,
              style: { fontFamily: FONT_UI, fontSize: 12, fontWeight: '900', fill: INK.primary, wordWrap: true, wordWrapWidth: cardW - 22, align: 'center' },
            });
            tgt.anchor.set(0.5, 0.5);
            tgt.position.set(0, -8);
            sideContainer.addChild(hdr, tgt);
            if (duel.draftReason) {
              const rsn = new PIXI.Text({
                text: duel.draftReason,
                style: { fontFamily: FONT_UI, fontSize: 10, fontWeight: '700', fill: 0xcf4932, wordWrap: true, wordWrapWidth: cardW - 22, align: 'center' },
              });
              rsn.anchor.set(0.5, 0);
              rsn.position.set(0, 14);
              sideContainer.addChild(rsn);
            }
            if (this.onUnstagePreReveal && duel.draftCardId) {
              const rmBtn = makeSealButton('撤销预排', {
                width: 84, height: 26, accent: 0xc8452e, solid: false, fontSize: 10.5, radius: 6,
                onClick: () => this.onUnstagePreReveal(duel.draftCardId),
              });
              rmBtn.position.set(-42, cardH / 2 - 38);
              sideContainer.addChild(rmBtn);
            }
            sideWidgets[side] = { container: sideContainer, homeRow: row, frontNode: null, cardKey: null, card: null, cardMotion: null, screenRect: null };
            continue;
          }

          // Case B: Live pre-reveal duel — Focused Pending Intercept Slot OR Open Target Plaque
          if (isPreReveal && side !== duel.attackingSide) {
            const box = new PIXI.Graphics();
            if (isPendingPreReveal) {
              box.roundRect(-cardW / 2, -cardH / 2, cardW, cardH, 8)
                .fill({ color: isInterceptable ? 0xfce7df : 0xfdf4e7, alpha: 0.94 })
                .stroke({ width: 2.2, color: 0xcf4932, alpha: 0.96 });
              sideContainer.addChild(box);
              const badge = new PIXI.Text({
                text: `⚔ 待迎击 · 开牌前 ${CIRCLED[(duel.number || 1) - 1] || duel.number}`,
                style: { fontFamily: FONT_UI, fontSize: 10.5, fontWeight: '900', fill: 0xcf4932 },
              });
              badge.anchor.set(0.5, 0);
              badge.position.set(0, -cardH / 2 + 16);
              const prompt = new PIXI.Text({
                text: isInterceptable ? '点击此处用选中牌迎击\n或拖入其他手牌' : '点击或拖入手牌迎击',
                style: { fontFamily: FONT_UI, fontSize: 11.5, fontWeight: '800', fill: INK.primary, align: 'center', lineHeight: 16 },
              });
              prompt.anchor.set(0.5, 0.5);
              prompt.position.set(0, -10);
              sideContainer.addChild(badge, prompt);
              if (isInterceptable) {
                box.eventMode = 'static';
                box.cursor = 'pointer';
                box.on('pointertap', (e) => {
                  e.stopPropagation();
                  this.onInterceptDuel(duel.number);
                });
              }
              if (this.onLetThrough) {
                const passBtn = makeSealButton('放行此交锋', {
                  width: 96, height: 28, accent: 0xc8452e, solid: true, fontSize: 11, radius: 6,
                  onClick: () => this.onLetThrough(duel.number),
                });
                passBtn.position.set(-48, cardH / 2 - 42);
                sideContainer.addChild(passBtn);
              }
            } else {
              const targetDesc = duel.target?.kind === 'duel'
                ? `牵制 · 常规交锋 ${CIRCLED[(duel.target.number || 1) - 1] || duel.target.number}`
                : duel.target?.kind === 'character'
                  ? `直击 · ${duel.target.name || '敌方角色'}`
                  : '等待结算';
              const statusDesc = duel.interceptable === false ? '不可拦截' : (duel.ready ? '已放行' : '等待对手响应…');
              box.roundRect(-cardW / 2, -cardH / 2, cardW, cardH, 8)
                .fill({ color: INK.paperSoft, alpha: 0.72 })
                .stroke({ width: 1.3, color: INK.line, alpha: 0.75 });
              sideContainer.addChild(box);
              const hdr = new PIXI.Text({
                text: statusDesc,
                style: { fontFamily: FONT_UI, fontSize: 10, fontWeight: '800', fill: INK.muted },
              });
              hdr.anchor.set(0.5, 0);
              hdr.position.set(0, -cardH / 2 + 22);
              const tgt = new PIXI.Text({
                text: targetDesc,
                style: { fontFamily: FONT_UI, fontSize: 12, fontWeight: '900', fill: INK.primary, wordWrap: true, wordWrapWidth: cardW - 22, align: 'center' },
              });
              tgt.anchor.set(0.5, 0.5);
              tgt.position.set(0, 6);
              sideContainer.addChild(hdr, tgt);
            }
            sideWidgets[side] = { container: sideContainer, homeRow: row, frontNode: null, cardKey: null, card: null, cardMotion: null, screenRect: null };
            continue;
          }

          const isDropTarget = isPlacement && side === this.activeSide;
          const ghost = new PIXI.Graphics();
          ghost.roundRect(-cardW / 2, -cardH / 2, cardW, cardH, 8)
            .fill({ color: isDropTarget ? INK.goldBg : INK.paperSoft, alpha: isDropTarget ? 0.3 : 0.2 })
            .stroke({ width: isDropTarget ? 1.5 : 1, color: isDropTarget ? INK.gold : INK.line, alpha: isDropTarget ? 0.8 : 0.45 });
          if (isDropTarget && this.canTapEmptySlot && this.onSlotTap) {
            ghost.eventMode = 'static';
            ghost.cursor = 'pointer';
            ghost.on('pointertap', (e) => {
              e.stopPropagation();
              this.onSlotTap(duel.number, side);
            });
          }
          sideContainer.addChild(ghost);
          sideWidgets[side] = { container: sideContainer, homeRow: row, frontNode: null, cardKey: null, card: null, cardMotion: null, screenRect: null };
          continue;
        }

        const frontIdx = this._resolveFrontCardIndex(duel, side, cards);
        const frontCard = cards[frontIdx];
        const isFaceDown = Boolean(
          frontCard.hidden
          || (duel.kind === 'regular' && !this.cardsRevealed && frontCard.state === 'placed_face_down' && side !== this.viewerSide),
        );
        const cardKey = isFaceDown
          ? `${duel.key}:${side}:hidden`
          : `${duel.key}:${side}:${frontCard.instance_id ?? frontCard.id}`;
        const spread = (this.metrics.pairGap * 0.5 + cardW * 0.5) * initPose.scale;
        const targetX = this.metrics.centerX + (side === 1 ? -spread : spread);
        const targetY = initPose.y;
        const accentForLaunch = isFaceDown
          ? (SIDE_THEME[side]?.accent || INK.gold)
          : this.resolveCharColor(frontCard.character_id, side);
        const cm = this._ensureCardMotion(cardKey, {
          isFreshPlacement: isPlacement,
          side,
          card: frontCard,
          targetX,
          targetY,
          targetScale: initPose.scale,
          accentColor: accentForLaunch,
        });

        if (isFaceDown) {
          const ownerInfo = this.resolveCardOwner?.(duel.kind, duel.number, side, frontIdx) || null;
          const ownerId = ownerInfo?.characterId || frontCard.character_id || null;
          const ownerName = ownerInfo?.characterName || (ownerId ? this.getCharName(ownerId) : '');
          const ownerColor = ownerInfo?.color != null
            ? ownerInfo.color
            : (ownerId ? this.resolveCharColor(ownerId, side) : SIDE_THEME[side]?.accent);
          const cardBackCfg = ownerInfo?.cardBack ?? (ownerId ? this.resolveCardBack?.(ownerId) : null) ?? null;
          const backNode = buildCardBack(side, {
            width: cardW,
            height: cardH,
            accentColor: ownerColor,
            pattern: cardBackCfg,
          });
          backNode.rotation = 0;
          sideContainer.addChild(backNode);
          this.markEffectTarget?.(sideContainer, duel.kind, duel.number, side, frontIdx + 1, -cardW / 2, -cardH / 2, cardW, cardH);
          sideWidgets[side] = {
            container: sideContainer,
            homeRow: row,
            frontNode: backNode,
            cardKey,
            card: { ...frontCard, hidden: true, character_id: ownerId },
            ownerId,
            ownerName,
            ownerColor,
            cardMotion: cm,
            screenRect: null,
          };
          continue;
        }

        const cs = isLive ? (this.combat?.sides || []).find((s) => s.side === side) : null;
        const isLiveExecuting = Boolean(
          isLive && cs && (cs.card_instance_id != null
            ? cs.card_instance_id === frontCard.instance_id
            : cs.card_id === frontCard.id),
        );

        const others = cards.map((c, ci) => ({ c, ci })).filter(({ ci }) => ci !== frontIdx);
        const tabWidgets = [];
        others.forEach(({ c, ci }, oi) => {
          const dir = side === 1 ? -1 : 1;
          const tabW = 24;
          const baseOffset = dir * (cardW / 2 + 11 + oi * 20);
          const otherKey = `${duel.key}:${side}:${c.instance_id ?? c.id}`;
          const tm = this._ensureTabMotion(otherKey);
          const accent = this.resolveCharColor(c.character_id, side);
          const pal = deriveCardPalette(accent, side);
          const tab = new PIXI.Container();
          const tg = new PIXI.Graphics();
          tg.roundRect(-tabW / 2, -cardH * 0.44, tabW, cardH * 0.88, 6)
            .fill({ color: c.used ? 0xf3eee4 : INK.paper, alpha: 0.96 })
            .stroke({ width: 1.25, color: pal.accent, alpha: 0.82 });
          tg.roundRect(-tabW / 2 + 1, -cardH * 0.44 + 1, tabW - 2, 3.6, 2).fill({ color: pal.accent });
          drawCostCrystal(tg, 0, -cardH * 0.44 + 15, 7, pal.accent);
          const ct = new PIXI.Text({
            text: String(c.cost ?? 0),
            style: { fontFamily: FONT_NUM, fontSize: 9, fontWeight: '900', fill: INK.paper },
          });
          ct.anchor.set(0.5);
          ct.position.set(0, -cardH * 0.44 + 15.5);
          const vertName = (c.name || '').slice(0, 6).split('').join('\n');
          const nt = new PIXI.Text({
            text: vertName,
            style: { fontFamily: FONT_UI, fontSize: 9.5, fontWeight: '800', fill: INK.primary, lineHeight: 12.5, align: 'center' },
          });
          nt.anchor.set(0.5, 0);
          nt.position.set(0, -cardH * 0.44 + 28);
          tab.addChild(tg, ct, nt);
          this.markEffectTarget?.(tab, duel.kind, duel.number, side, ci + 1, -tabW / 2, -cardH * 0.44, tabW, cardH * 0.88);
          tab.position.set(baseOffset, 0);
          tab.eventMode = 'static';
          tab.cursor = 'pointer';
          tab.on('pointerover', () => {
            tm.hovered = true;
            tm.slideSpring.setTarget(1);
          });
          tab.on('pointerout', () => {
            tm.hovered = false;
            tm.dwellTimer = 0;
            tm.state = 'peeking';
            tm.slideSpring.setTarget(0);
          });
          sideContainer.addChild(tab);
          tabWidgets.push({ tab, dir, baseOffset, otherKey, stackKey: `${duel.key}:${side}`, tabMotion: tm });
        });

        const accent = this.resolveCharColor(frontCard.character_id, side);
        const conceal = isLiveExecuting ? (this.concealBySide.get(side) || {}) : {};
        const statusBadge = this._cardStatusBadge(duel, side, frontCard, isLiveExecuting);
        const savedScroll = this.cardScrollByKey.has(cardKey) ? this.cardScrollByKey.get(cardKey) : null;

        const frontNode = buildUniformCard(frontCard, {
          side,
          accentColor: accent,
          ownerName: this.getCharName(frontCard.character_id) || '',
          showOwner: true,
          width: cardW,
          height: cardH,
          centered: true,
          activeCard: isLiveExecuting,
          activeDieNumber: isLiveExecuting ? (cs?.die?.position ?? cs?.die_number ?? null) : null,
          concealActiveScore: Boolean(conceal.score),
          concealActiveOutcome: Boolean(conceal.outcome),
          rangeDeficit: (isLiveExecuting ? cs?.range_deficit : 0) || frontCard.range_deficit || 0,
          playMode: (isLiveExecuting ? cs?.play_mode : null) || frontCard.play_mode || null,
          statusBadge,
          initialScrollY: savedScroll,
        });
        frontNode.rotation = 0;
        frontNode.eventMode = 'none'; // Hit-testing is handled deterministically by screen-space AABB (zero reparent flicker!)

        sideContainer.addChild(frontNode);
        this.markEffectTarget?.(sideContainer, duel.kind, duel.number, side, frontIdx + 1, -cardW / 2, -cardH / 2, cardW, cardH);
        sideWidgets[side] = { container: sideContainer, homeRow: row, frontNode, cardKey, card: frontCard, cardMotion: cm, tabWidgets, screenRect: null };
      }

      this.depthLayer.addChild(row);
      this.depthSlotEntries.push({ duel, index, row, centerEmblem, forceEmblemVisible, sideWidgets, duelMotion: dm });
    });
    if (isPlacement && this.duels.length > 0) {
      this._hasRenderedInitialPlacement = true;
    }
  }

  /**
   * Genuine State Machine Transition & Target Evaluation:
   *  - DuelRowState:  'spawning' -> 'active' | 'completed' | 'idle'
   *  - CardState:     'entering' (0.32s placement cooldown) -> 'idle' | 'active' | 'settled' | 'destroyed'
   *                   -> 'hover_dwell' (0.20s deliberate hover dwell) -> 'inspecting' (cursor-centered lift)
   *                   -> 'returning' -> resting state
   *  - TabState:      'peeking' -> 'hover_dwell' (0.16s) -> 'promoted'
   */
  _applyStateMachineTargets(snap = false, dtSec = 0) {
    const combatBlend = clamp(this.combatBlendSpring.value, 0, 1);
    const focusVal = this.focusSpring.value;
    // Fast, non-punishing intent gate:
    //  - Only genuinely violent cross-screen flicks (>900 px/s) pause dwell (never resets on micro-moves!)
    //  - Chained inspection (switching from one inspected card to another within 0.30s) is 0ms instant!
    const DWELL_THRESHOLD = 0.035;
    const FLICK_SPEED = 900;
    const TAB_DWELL_THRESHOLD = 0.06;
    const nowMs = performance.now();
    const isChainedInspect = (nowMs - this._lastInspectEndedAt) < 300;
    let needsPoolRebuild = false;

    // Deterministic screen-space AABB hit-test (replaces fragile PixiJS pointerover/out across reparenting!):
    // 1. Currently lifted/inspecting card gets top priority (matches unclipped liftedLayer z-order).
    // 2. Otherwise check visible cards inside stage clip, closest to focal index first.
    const px = this._lastPointerX;
    const py = this._lastPointerY;
    const { arenaX, arenaW, stageTop, stageH } = this.layout;
    const inStageClip = px >= arenaX - 24 && px <= arenaX + arenaW + 24 && py >= stageTop - 4 && py <= stageTop + stageH + 4;
    let hitCardKey = null;
    let hitCardMeta = null;

    // Pass 1: check any lifted card first (unclipped)
    for (const entry of this.depthSlotEntries) {
      if (!entry.row.visible) continue;
      for (const side of [1, 2]) {
        const sw = entry.sideWidgets[side];
        const r = sw?.screenRect;
        if (!r || !sw.cardMotion || sw.cardMotion.inspectSpring.value <= 0.01) continue;
        if (px >= r.x && px <= r.x + r.w && py >= r.y && py <= r.y + r.h) {
          hitCardKey = sw.cardKey;
          hitCardMeta = { characterId: sw.card?.character_id || null, side, duelKind: entry.duel.kind, duelNumber: entry.duel.number };
          break;
        }
      }
      if (hitCardKey) break;
    }

    // Pass 2: check non-lifted visible cards inside stage clip (front-to-back by |d|)
    if (!hitCardKey && inStageClip) {
      let bestDist = Infinity;
      for (const entry of this.depthSlotEntries) {
        if (!entry.row.visible) continue;
        const ad = Math.abs(entry.index - focusVal);
        for (const side of [1, 2]) {
          const sw = entry.sideWidgets[side];
          const r = sw?.screenRect;
          if (!r || !sw.card || !sw.cardMotion || sw.cardMotion.state === 'airborne') continue;
          if (px >= r.x && px <= r.x + r.w && py >= r.y && py <= r.y + r.h) {
            if (ad < bestDist) {
              bestDist = ad;
              hitCardKey = sw.cardKey;
              hitCardMeta = {
                hidden: Boolean(sw.card.hidden),
                characterId: sw.ownerId || sw.card?.character_id || null,
                characterName: sw.ownerName || '',
                color: sw.ownerColor ?? null,
                anchorX: r.x + r.w * 0.5,
                anchorY: r.y - 12,
                side,
                duelKind: entry.duel.kind,
                duelNumber: entry.duel.number,
              };
            }
          }
        }
      }
    }

    if (hitCardKey !== this.inspectedCardKey) {
      if (this.inspectedCardKey) {
        for (const [stackKey, chosenKey] of this.hoveredStackChoice.entries()) {
          if (chosenKey === this.inspectedCardKey) {
            this.hoveredStackChoice.delete(stackKey);
            needsPoolRebuild = true;
          }
        }
      }
      this.inspectedCardKey = hitCardKey;
      this.onHoverCard?.(hitCardMeta);
    }

    for (const entry of this.depthSlotEntries) {
      const d = entry.index - focusVal;
      const pose = this._evalTargetPose(entry.index, d, combatBlend);
      const dm = entry.duelMotion;

      if (dm.state === 'spawning' && dm.alphaSpring.value >= pose.alpha * 0.96) {
        dm.state = entry.duel.status === 'active' ? 'active' : entry.duel.status === 'completed' ? 'completed' : 'idle';
      } else if (dm.state !== 'spawning') {
        dm.state = entry.duel.status === 'active' ? 'active' : entry.duel.status === 'completed' ? 'completed' : 'idle';
      }

      if (snap) {
        dm.ySpring.snap(pose.y);
        dm.scaleSpring.snap(pose.scale);
        dm.alphaSpring.snap(pose.alpha);
        dm.markAlphaSpring.snap(pose.markAlpha);
      } else {
        dm.ySpring.setTarget(pose.y);
        dm.scaleSpring.setTarget(pose.scale);
        dm.alphaSpring.setTarget(pose.alpha);
        dm.markAlphaSpring.setTarget(pose.markAlpha);
      }

      for (const side of [1, 2]) {
        const sw = entry.sideWidgets[side];
        const cm = sw?.cardMotion;
        if (!cm || !sw.card) continue;

        // Tick placement cooldown so freshly placed cards NEVER immediately zoom up under the releasing cursor!
        if (cm.enterCooldown > 0) {
          cm.enterCooldown = Math.max(0, cm.enterCooldown - dtSec);
        }

        // Evaluate stacked-card tab state machines
        for (const tw of sw.tabWidgets || []) {
          const tm = tw.tabMotion;
          if (tm.hovered) {
            tm.dwellTimer += dtSec;
            if (tm.dwellTimer >= TAB_DWELL_THRESHOLD && tm.state !== 'promoted') {
              tm.state = 'promoted';
              this.hoveredStackChoice.set(tw.stackKey, tw.otherKey);
              needsPoolRebuild = true;
            } else if (tm.state === 'peeking') {
              tm.state = 'hover_dwell';
            }
          }
        }

        const restingState = sw.card.destroyed ? 'destroyed'
          : (entry.duel.status === 'active' && this.phaseState === 'combat') ? 'active'
            : (sw.card.used || entry.duel.status === 'completed') ? 'settled'
              : 'idle';

        // Sync deterministic hover flag from AABB hit-test
        cm.hovered = Boolean(sw.cardKey && sw.cardKey === hitCardKey);

        // Phase 1: Airborne Hermite ballistic flight (hand/edge -> exact slot)
        if (cm.state === 'airborne' && cm.flight) {
          cm.inspectSpring.setTarget(0);
          cm.flight.age += dtSec;
          if (cm.flight.age >= cm.flight.duration) {
            const { centerX, cardW, cardH, pairGap } = this.metrics;
            const landScale = Math.max(0.2, dm.scaleSpring.value);
            const landSpread = (pairGap * 0.5 + cardW * 0.5) * landScale;
            const landX = centerX + (side === 1 ? -landSpread : landSpread);
            const landY = dm.ySpring.value;
            const accentCol = cm.flight.accentColor;

            cm.flight = null;
            cm.state = 'impact';
            cm.enterCooldown = 0.28;
            // Conservation of vertical touchdown momentum -> underdamped compression impulse
            cm.impactSpring.impulse(-4.4);
            this.impactRipples.push({
              x: landX,
              y: landY,
              w: cardW * landScale,
              h: cardH * landScale,
              color: accentCol,
              age: 0,
              duration: 0.38,
            });
            this.onCardLand?.({ x: landX, y: landY, side, color: accentCol, card: sw.card });
          }
          continue;
        }

        // Phase 2: Underdamped touchdown compression & cooldown (blocks instant hover-zoom on release)
        if (cm.state === 'impact') {
          cm.inspectSpring.setTarget(0);
          if (cm.impactSpring.settled && cm.enterCooldown <= 0) {
            cm.state = restingState;
          }
          continue;
        }

        const eligibleToInspect = !sw.card.hidden && (pose.scale < 0.96 || Math.abs(d) > 0.25);
        if (cm.hovered && eligibleToInspect && cm.enterCooldown <= 0) {
          if (cm.state === 'inspecting') {
            cm.inspectSpring.setTarget(1, { omega: 42.0, zeta: 0.72 });
            this._lastInspectEndedAt = nowMs;
          } else {
            cm.state = 'hover_dwell';
            if (isChainedInspect) {
              cm.dwellTimer = DWELL_THRESHOLD;
            } else if (this._pointerSpeed <= FLICK_SPEED) {
              cm.dwellTimer += dtSec;
            }
            if (cm.dwellTimer >= DWELL_THRESHOLD) {
              cm.state = 'inspecting';
              cm.inspectSpring.setTarget(1, { omega: 42.0, zeta: 0.72 });
              // Crisp physical lift-off impulse so Frame 1 immediately pops off the tabletop!
              if (cm.inspectSpring.value < 0.25) {
                cm.inspectSpring.impulse(6.5);
              }
              this._lastInspectEndedAt = nowMs;
            }
          }
        } else {
          cm.dwellTimer = 0;
          if (cm.state === 'inspecting') {
            this._lastInspectEndedAt = nowMs;
            cm.state = 'returning';
            cm.inspectSpring.setTarget(0, { omega: 52.0, zeta: 0.92 });
            // Crisp downward tuck impulse so put-down snaps cleanly back to the felt
            if (cm.inspectSpring.value > 0.4) {
              cm.inspectSpring.impulse(-4.5);
            }
          } else if (cm.state === 'returning') {
            cm.inspectSpring.setTarget(0, { omega: 52.0, zeta: 0.92 });
            if (cm.inspectSpring.settled) cm.state = restingState;
          } else {
            cm.inspectSpring.setTarget(0, { omega: 52.0, zeta: 0.92 });
            cm.state = restingState;
          }
        }
      }
    }

    if (needsPoolRebuild) {
      this._rebuildDepthPool();
      this._applyStateMachineTargets(false, 0);
      this._layoutDepthFrame(true);
    }
  }

  _layoutDepthFrame(updateRects = false) {
    const { centerX, cardW, cardH, pairGap } = this.metrics;
    const { arenaX, arenaW, stageTop, stageH } = this.layout;
    const combatBlend = clamp(this.combatBlendSpring.value, 0, 1);
    const focusVal = this.focusSpring.value;

    if (updateRects) {
      this.interactiveCardRects = [];
      this.combatCardRects.clear();
      this.placementSlotRects.clear();
      this.regularLaneRects.clear();
      this.preRevealSlotRects.clear();
    }

    this.flightShadowLayer.clear();
    this.impactRippleLayer.clear();

    // Render mathematically damped rounded-card contour ripples on the tabletop surface
    for (const rp of this.impactRipples) {
      const tau = clamp(rp.age / rp.duration, 0, 1);
      const expand = 1 + 0.34 * (1 - Math.exp(-6.0 * tau));
      const alpha = 0.64 * Math.pow(1 - tau, 2) * Math.exp(-2.0 * tau);
      if (alpha > 0.01) {
        const rw = rp.w * expand;
        const rh = rp.h * expand;
        this.impactRippleLayer
          .roundRect(rp.x - rw / 2, rp.y - rh / 2, rw, rh, 9)
          .stroke({ width: 2.2 * (1 - tau * 0.55), color: rp.color, alpha });
      }
    }

    const ordered = this.depthSlotEntries
      .map((entry) => ({ entry, d: entry.index - focusVal }))
      .sort((a, b) => Math.abs(b.d) - Math.abs(a.d));

    for (let z = 0; z < ordered.length; z++) {
      const { entry, d } = ordered[z];
      const ad = Math.abs(d);
      const dm = entry.duelMotion;
      const rowAlpha = clamp(dm.alphaSpring.value, 0, 1);
      const maxVisibleD = lerp(4.5, 3.2, combatBlend);

      if (ad > maxVisibleD || rowAlpha < 0.015) {
        entry.row.visible = false;
        continue;
      }
      entry.row.visible = true;
      if (this.depthLayer.getChildIndex(entry.row) !== z) {
        this.depthLayer.setChildIndex(entry.row, z);
      }

      const rowSettled = dm.ySpring.settled && dm.scaleSpring.settled;
      const rowY = rowSettled ? Math.round(dm.ySpring.value) : dm.ySpring.value;
      const baseScale = Math.max(0.2, dm.scaleSpring.value);
      const baseSpread = (pairGap * 0.5 + cardW * 0.5) * baseScale;

      entry.row.position.set(rowSettled ? Math.round(centerX) : centerX, rowY);
      entry.row.alpha = rowAlpha;

      const ma = entry.forceEmblemVisible ? 1 : clamp(dm.markAlphaSpring.value, 0, 1);
      entry.centerEmblem.visible = ma > 0.02;
      entry.centerEmblem.alpha = ma;
      entry.centerEmblem.position.set(0, 0);
      entry.centerEmblem.scale.set(lerp(0.85, 1.0, baseScale));

      if (updateRects) {
        const laneW = (pairGap + cardW * 2) * baseScale;
        const laneH = cardH * baseScale;
        const laneRect = {
          x: centerX - laneW * 0.5,
          y: rowY - laneH * 0.5,
          w: laneW,
          h: laneH,
          cx: centerX,
          cy: rowY,
          visible: rowY + laneH * 0.5 > stageTop && rowY - laneH * 0.5 < stageTop + stageH,
        };
        if (entry.duel.kind === 'regular') {
          this.regularLaneRects.set(entry.duel.number, laneRect);
        } else if (entry.duel.kind === 'pre_reveal') {
          this.preRevealSlotRects.set(entry.duel.number, laneRect);
        }
      }

      for (const side of [1, 2]) {
        const sw = entry.sideWidgets[side];
        if (!sw) continue;
        const cm = sw.cardMotion;
        const isAirborne = Boolean(cm && cm.state === 'airborne' && cm.flight);
        const impactVal = cm ? cm.impactSpring.value : 0;
        // Allow slight natural underdamped overshoot (>1.0) on inspectT for tactile physical pop!
        const inspectT = cm ? clamp(cm.inspectSpring.value, 0, 1.08) : 0;
        const isLifted = !isAirborne && inspectT > 0.01;

        // Resting world coordinates on the tabletop
        const restX = centerX + (side === 1 ? -baseSpread : baseSpread);
        const restY = rowY;

        // Update stacked-card tab springs cleanly
        for (const tw of sw.tabWidgets || []) {
          const slide = tw.tabMotion.slideSpring.value;
          tw.tab.position.set(tw.baseOffset + tw.dir * slide * 8, 0);
        }

        let curScale;
        let curWorldX;
        let curWorldY;

        if (isAirborne) {
          const fl = cm.flight;
          const u = clamp(fl.age / fl.duration, 0, 1);
          const { s, ds } = flightTimeWarp(u);
          // Dynamically target LIVE (restX, restY) so spline lands with 0.0px error even if tabletop scrolls!
          const hx = evalHermite1D(fl.fromX, fl.m0x, restX, fl.m1x, s);
          const hy = evalHermite1D(fl.fromY, fl.m0y, restY, fl.m1y, s);
          const velX = (hx.deriv * ds) / fl.duration;
          // Asymmetric ballistic altitude: z(u) = peakZ * (27/4) * u * (1 - u)^2 (peaks at u = 1/3, zero at u = 0,1)
          const altitude = fl.peakZ * 6.75 * u * (1 - u) * (1 - u);
          const perspFactor = 1 + altitude / 520;
          curScale = lerp(fl.scale0, baseScale, s) * perspFactor;
          curWorldX = hx.val;
          curWorldY = hy.val - altitude * 0.22;
          // Aerodynamic banking yaw decaying cleanly to exact 0.000 rad at touchdown (u = 1)
          const aeroYaw = fl.rot0 * (1 - s) * (1 - s) + clamp(velX / 3200, -0.15, 0.15) * Math.sin(Math.PI * u);

          // Projected physical altitude drop-shadow on the tabletop beneath the flying card
          const shW = cardW * lerp(fl.scale0, baseScale, s) * (1 + altitude * 0.0005);
          const shH = cardH * lerp(fl.scale0, baseScale, s) * (1 + altitude * 0.0005);
          const shAlpha = 0.28 / (1 + altitude * 0.0055);
          this.flightShadowLayer
            .roundRect(hx.val + altitude * 0.10 - shW / 2, hy.val + altitude * 0.22 - shH / 2, shW, shH, 8)
            .fill({ color: INK.shadow, alpha: shAlpha });

          if (sw.container.parent !== this.liftedLayer) {
            this.liftedLayer.addChild(sw.container);
          }
          sw.container.position.set(curWorldX, curWorldY);
          sw.container.scale.set(curScale);
          sw.container.rotation = aeroYaw;
          sw.container.alpha = 1;
        } else {
          // Uniform card-center physical lift with slight tactile overshoot & projected tabletop shadow
          const clampT = clamp(inspectT, 0, 1);
          const impactScale = 1 + impactVal * 0.038;
          // Allow the ~3.8% underdamped overshoot to express naturally on scale!
          const unimpactedScale = baseScale + (1.0 - baseScale) * inspectT;
          curScale = unimpactedScale * impactScale;

          const viewW = typeof window !== 'undefined' ? window.innerWidth : (arenaX + arenaW + 240);
          const viewH = typeof window !== 'undefined' ? window.innerHeight : (stageTop + stageH + 160);
          // Use constant final 1.0x half-extents so viewport clamping never suddenly "hits a wall" mid-zoom
          const finalHalfW = cardW * 0.5 + 8;
          const finalHalfH = cardH * 0.5 + 8;
          const targetX = clamp(restX, finalHalfW, Math.max(finalHalfW, viewW - finalHalfW));
          const targetY = clamp(restY, finalHalfH, Math.max(finalHalfH, viewH - finalHalfH));
          const rawX = lerp(restX, targetX, clampT);
          const rawY = lerp(restY, targetY, clampT) - clampT * 4;
          // Only pixel-snap when settled so mid-animation motion is silky GPU-filtered with zero 1px staircases!
          const settled = !cm || cm.inspectSpring.settled;
          curWorldX = settled ? Math.round(rawX) : rawX;
          curWorldY = settled ? Math.round(rawY) : rawY;

          // Reparent THE ACTUAL physical card to unclipped `liftedLayer` while lifted, and return it to
          // `homeRow` once settled back — ZERO duplicate popover card!
          if (isLifted) {
            // Projected soft elevation shadow beneath the lifted card -> genuine tabletop lift depth!
            const shW = cardW * curScale * 1.02;
            const shH = cardH * curScale * 1.02;
            const shOffY = 10 * clampT;
            this.flightShadowLayer
              .roundRect(curWorldX - shW / 2, curWorldY + shOffY - shH / 2, shW, shH, 9)
              .fill({ color: INK.shadow, alpha: 0.24 * clampT });

            if (sw.container.parent !== this.liftedLayer) {
              this.liftedLayer.addChild(sw.container);
            }
            sw.container.position.set(curWorldX, curWorldY);
            sw.container.alpha = lerp(rowAlpha, 1.0, clampT);
          } else {
            if (sw.container.parent !== sw.homeRow) {
              sw.homeRow.addChild(sw.container);
            }
            const localX = restX - centerX;
            sw.container.position.set(settled && rowSettled ? Math.round(localX) : localX, 0);
            sw.container.alpha = 1;
          }
          // In-place 2.5D horizontal cosine flip during `cards_reveal`
          let flipScaleX = 1;
          if (cm?.revealFlip) {
            const rf = cm.revealFlip;
            const elapsed = Math.max(0, rf.age - rf.delay);
            const p = clamp(elapsed / rf.duration, 0, 1);
            flipScaleX = Math.max(0.06, Math.abs(Math.cos(Math.PI * p)));
          }
          sw.container.scale.set(curScale * flipScaleX, curScale);
          sw.container.rotation = 0;
        }

        // Always keep live screen-space AABB updated for deterministic hover hit-testing
        const worldW = cardW * curScale;
        const worldH = cardH * curScale;
        sw.screenRect = {
          x: curWorldX - worldW / 2,
          y: curWorldY - worldH / 2,
          w: worldW,
          h: worldH,
        };

        if (updateRects) {
          if (entry.duel.kind === 'regular') {
            this.placementSlotRects.set(`${entry.duel.number}:${side}`, {
              x: restX - (cardW * baseScale) / 2,
              y: restY - (cardH * baseScale) / 2,
              w: cardW * baseScale,
              h: cardH * baseScale,
              cx: restX,
              cy: restY,
              visible: restY + (cardH * baseScale) / 2 > stageTop && restY - (cardH * baseScale) / 2 < stageTop + stageH,
            });
          }
          if (sw.frontNode && !sw.card?.hidden && (isLifted || (combatBlend > 0.7 && ad < 0.35))) {
            // Put lifted cards first so wheel routing prioritizes the card currently lifted by the player
            const rectItem = {
              side,
              cardKey: sw.cardKey,
              x: curWorldX - worldW / 2,
              y: curWorldY - worldH / 2,
              w: worldW,
              h: worldH,
              node: sw.frontNode,
              isInspecting: isLifted,
            };
            if (isLifted) this.interactiveCardRects.unshift(rectItem);
            else this.interactiveCardRects.push(rectItem);
          }
          if (sw.frontNode && entry.index === this.activeIndex) {
            this.combatCardRects.set(side, {
              x: curWorldX - worldW / 2,
              y: curWorldY - worldH / 2,
              w: worldW,
              h: worldH,
              cx: curWorldX,
              cy: curWorldY,
              cardId: sw.card.id,
              instanceId: sw.card.instance_id,
            });
          }
        }
      }
    }
  }

  tick(dtSec) {
    let dirty = false;
    // Fast exponential pointer speed decay so dwell opens within ~2 frames of stopping
    this._pointerSpeed *= Math.exp(-32 * dtSec);
    if (this.focusSpring.step(dtSec)) dirty = true;
    if (this.combatBlendSpring.step(dtSec)) dirty = true;
    if (this.overviewOriginSpring.step(dtSec)) dirty = true;

    this._applyStateMachineTargets(false, dtSec);

    // Advance active damped tabletop impact ripples
    for (let i = this.impactRipples.length - 1; i >= 0; i--) {
      this.impactRipples[i].age += dtSec;
      dirty = true;
      if (this.impactRipples[i].age >= this.impactRipples[i].duration) {
        this.impactRipples.splice(i, 1);
      }
    }

    for (const entry of this.depthSlotEntries) {
      const dm = entry.duelMotion;
      if (dm.ySpring.step(dtSec)) dirty = true;
      if (dm.scaleSpring.step(dtSec)) dirty = true;
      if (dm.alphaSpring.step(dtSec)) dirty = true;
      if (dm.markAlphaSpring.step(dtSec)) dirty = true;
      for (const side of [1, 2]) {
        const sw = entry.sideWidgets[side];
        if (!sw) continue;
        if (sw.cardMotion) {
          if (sw.cardMotion.state === 'airborne') dirty = true;
          if (sw.cardMotion.revealFlip) {
            sw.cardMotion.revealFlip.age += dtSec;
            dirty = true;
            if (sw.cardMotion.revealFlip.age >= sw.cardMotion.revealFlip.delay + sw.cardMotion.revealFlip.duration) {
              sw.cardMotion.revealFlip = null;
            }
          }
          if (sw.cardMotion.impactSpring.step(dtSec)) dirty = true;
          if (sw.cardMotion.inspectSpring.step(dtSec)) dirty = true;
        }
        for (const tw of sw.tabWidgets || []) {
          if (tw.tabMotion.slideSpring.step(dtSec)) dirty = true;
        }
        if (sw.frontNode && !sw.frontNode.destroyed) sw.frontNode.tick?.(dtSec);
      }
    }

    if (dirty) {
      this._layoutDepthFrame(true);
    }
  }

  _clear(c) {
    const removed = c.removeChildren();
    for (const ch of removed) {
      if (ch && !ch.destroyed) ch.destroy({ children: true });
    }
  }
}
