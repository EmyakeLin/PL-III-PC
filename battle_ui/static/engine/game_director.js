/**
 * Living Confrontational Pure-WebGL Game Director for 《光点计划 III》.
 *  - Confrontational Left(P1) vs Right(P2) Stage: living animated character figures facing each other across the sunlit arena
 *  - Expanded Character Passives directly on stage beside each fighter (NEVER collapsed into a "被动(4)" button!), igniting with 3D energy beams whenever triggered
 *  - Living Visual Choreography: animated status auras, concentric shield domes, 3D slash/pierce/blunt/block/evade VFX, actor lunge/recoil/dash, Matter.js colliding 3D dice & shield erosion shards
 *  - Phase-Driven Dynamic Staging: horizontal face-to-face duel bridge during placement/pre-reveal -> dramatic focused Center-Stage Showdown during combat with live verbatim clash panels
 *  - 100% Verbatim Rule Fidelity: ZERO paraphrasing, ZERO "Lv.X", ZERO "无附加词条", ZERO flavor/annotation filler
 *  - Strictly Bright Palette: ZERO black, ZERO blue-purple, ZERO DOM controls
 */

import * as PIXI from '../vendor/pixi.min.mjs';
import {
  FONT_UI,
  FONT_NUM,
  INK,
  SIDE_THEME,
  DIE_STYLE,
  SHIELD_STYLE,
  STATUS_COLORS,
  LEVEL_MAX,
  OFFICIAL_STATUS_RULES,
  formatDieRange,
  wrapCjkText,
  drawDieIcon,
  drawStatusIcon,
  drawShieldGlyph,
  drawLightStar,
  drawCostCrystal,
  buildCardBack,
  buildCardFront,
  buildVerbatimCardPanel,
} from './card_print.js';
import { createCharacterActor } from './stage_actors.js';
import {
  makeSealButton,
  buildCharacterDossier,
  buildHandoffOverlay,
  buildDrawSelectOverlay,
  buildSpecialOverlay,
  buildRosterOverlay,
  buildCodexOverlay,
  buildPileOverlay,
  buildFinishOverlay,
} from './table_overlays.js';

const PHASE_NAMES = {
  setup: '准备',
  turn_start: '回合开始',
  draw_select: '看顶选底',
  placement: '常规置卡',
  pre_reveal: '开牌前',
  reveal: '统一开牌',
  combat: '交锋结算',
  turn_end: '回合结束',
  finished: '终局',
};

const PHASE_TINTS = {
  placement: 0xfaecc8,
  pre_reveal: 0xfde2bf,
  reveal: 0xfef0c4,
  combat: 0xfce0d4,
  turn_end: 0xe6f2e8,
  finished: 0xfef0c4,
};

const GRADE_LABEL = {
  normal: '普通',
  pierce: '穿甲',
  concept: '超穿甲',
};

const CIRCLED = ['①', '②', '③', '④', '⑤', '⑥', '⑦', '⑧'];

function clearContainer(c) {
  const removed = c.removeChildren();
  for (const child of removed) {
    if (child && !child.destroyed) child.destroy({ children: true });
  }
}

export class GameDirector {
  constructor(app, physics, threeWorld, audio, transport) {
    this.app = app;
    this.physics = physics;
    this.three = threeWorld;
    this.audio = audio;
    this.transport = transport;

    this.w = app.screen.width;
    this.h = app.screen.height;
    this.state = null;
    this.lastFxSeq = 0;

    // Live kinetic state ticked at 60fps
    this.hpDisplay = new Map();
    this.hpWidgets = new Map();      // charId -> { barG, hpTxt, barX, barY, barW, barH, maxHp, accent }
    this.actorNodes = new Map();     // charId -> { actor, liveCh, cx, cy, side }
    this.actorMotion = new Map();    // charId -> { lunge, recoil, evade, hitFlash, healGlow, passiveFlare }
    this.passivePlates = new Map();  // `${charId}:${passiveName}` -> { x, y, w, h, cx, cy, glowG, pulse }
    this.passivePulses = new Map();  // `${charId}:${passiveName}` -> remaining sec (0..1.6)
    this.costAnchors = new Map();    // side -> { x, y }
    this.floaters = [];
    this.banner = null;
    this.toast = null;
    this.shakeTime = 0;
    this.shakePower = 0;
    this.time = 0;
    this.autoPace = false;
    this.autoTimer = 0;

    // Inspection & interactive state
    this.hoveredCard = null;
    this.hoveredInfo = null;
    this._hiddenHoverSprite = null;
    this._inspectAnim = null;
    this.dragState = null;
    this.selectedHandCardId = null;

    // Modals / Pinned Sheets
    this.dossierModal = null;
    this.rosterModal = null;
    this.codexModal = null;
    this.pileModal = null;
    this.drawSelected = new Set();

    // Spatial hit-test geometry maps
    this.layout = {};
    this.charRects = new Map();
    this.regularSlotRects = new Map();
    this.regularLaneRects = new Map();
    this.preRevealSlotRects = new Map();
    this.pileCenters = new Map();
    this.handCardViews = new Map();
    this.preTimerTexts = [];

    // Matter.js real dice collision callback -> exact contact audio + Three.js sparks + ripple + defense barrier
    this.physics.onClashImpact = ({ x, y, group }) => {
      const heavy = group.outcome !== 'draw';
      this.audio.clashImpact(heavy);
      this.three.spawnImpactBurst(x, y, group.winnerColor || 0xe89b32, heavy ? 36 : 22, heavy);
      this.physics.applyGentleImpulse(x, y, 290, heavy ? 0.036 : 0.02);
      if (heavy) this._triggerShake(7.5, 0.22);
      if (group.winDieType === 'block') {
        this.three.spawnBlockBarrier({ x, y, colorHex: DIE_STYLE.block.color });
      }
    };

    this.worldRoot = new PIXI.Container();
    app.stage.addChild(this.worldRoot);

    this.wingsLayer = new PIXI.Container();
    this.actorsLayer = new PIXI.Container();
    this.boardLayer = new PIXI.Container();
    this.shardGraphic = new PIXI.Graphics();
    this.clashLayer = new PIXI.Container();
    this.tetherLayer = new PIXI.Graphics();
    this.handLayer = new PIXI.Container();
    this.controlsLayer = new PIXI.Container();
    this.cornerHudLayer = new PIXI.Container();
    this.fxTextLayer = new PIXI.Container();
    this.overlayLayer = new PIXI.Container();
    this.inspectLayer = new PIXI.Container();
    this.toastLayer = new PIXI.Container();

    this.worldRoot.addChild(
      this.wingsLayer,
      this.actorsLayer,
      this.boardLayer,
      this.shardGraphic,
      this.clashLayer,
      this.tetherLayer,
      this.handLayer,
      this.controlsLayer,
      this.cornerHudLayer,
      this.fxTextLayer
    );
    app.stage.addChild(this.overlayLayer, this.inspectLayer, this.toastLayer);

    app.stage.eventMode = 'static';
    app.stage.hitArea = app.screen;
    app.stage.on('pointermove', (e) => this._onPointerMove(e));
    app.stage.on('pointerup', (e) => this._onPointerUp(e));
    app.stage.on('pointerupoutside', (e) => this._onPointerUp(e));
    app.stage.on('pointertap', () => {
      if (this.selectedHandCardId && !this.dragState) {
        this.selectedHandCardId = null;
        this._rebuildDynamicBoard();
      }
    });

    window.addEventListener('wheel', (e) => this._onWheel(e), { passive: true });
    window.addEventListener('keydown', (e) => this._onKeyDown(e));

    this._computeLayout();
  }

  resize(w, h) {
    this.w = w;
    this.h = h;
    this.app.stage.hitArea = this.app.screen;
    this._computeLayout();
    if (this.state) this._rebuildAll();
  }

  _computeLayout() {
    const w = this.w;
    const h = this.h;
    const pad = 16;
    const wingW = Math.round(Math.max(274, Math.min(342, w * 0.242)));
    const arenaGap = 16;
    const arenaX = pad + wingW + arenaGap;
    const arenaW = Math.max(460, w - (pad + wingW + arenaGap) * 2);
    const cardW = 136;
    const cardH = 186;
    const handY = h - cardH / 2 - 12;
    const actionStripY = handY - cardH / 2 - 42;
    const arenaTop = 50;
    const arenaBottom = actionStripY - 8;
    const arenaH = Math.max(240, arenaBottom - arenaTop);

    this.layout = {
      w, h, pad, wingW,
      leftWingX: pad,
      rightWingX: w - pad - wingW,
      arenaX, arenaW, arenaTop, arenaH,
      actionStripY,
      showdownBottom: h - 64,
      handY, cardW, cardH,
    };
  }

  _getMotion(charId) {
    let m = this.actorMotion.get(charId);
    if (!m) {
      m = { lunge: 0, recoil: 0, evade: 0, hitFlash: 0, healGlow: 0, passiveFlare: 0 };
      this.actorMotion.set(charId, m);
    }
    return m;
  }

  applyState(nextState, { isInitial = false } = {}) {
    // STRICT PRIVACY CLEAR on every state update
    this.hoveredCard = null;
    this.hoveredInfo = null;
    this.dragState = null;
    this.selectedHandCardId = null;
    if (nextState.mode === 'handoff' || nextState.mode === 'special_handoff') {
      this.dossierModal = null;
    }
    this._renderInspection();

    this.state = nextState;
    this.drawSelected.clear();

    const isCombat = Boolean(nextState.frame?.combat);
    const phaseTint = PHASE_TINTS[nextState.frame?.phase] || 0xfaecc8;
    this.three.setPhaseTint(phaseTint);
    this.three.setCombatFocus(isCombat);

    for (const p of nextState.frame?.players || []) {
      for (const c of p.characters || []) {
        if (!this.hpDisplay.has(c.id) || isInitial) {
          this.hpDisplay.set(c.id, c.hp);
        }
      }
    }

    this._rebuildAll();

    const events = nextState.fx_events || [];
    if (isInitial) {
      if (events.length) {
        const lastSpeed = [...events].reverse().find((e) => e.kind === 'speed_roll');
        const initialPassives = events.filter((e) => e.kind === 'passive_trigger');
        this.lastFxSeq = events[events.length - 1].seq;
        if (lastSpeed) this._playSpeedRollFx(lastSpeed, true);
        initialPassives.forEach((ev, idx) => {
          setTimeout(() => this._playPassiveTriggerFx(ev, true), 180 + idx * 240);
        });
      }
    } else {
      const fresh = events.filter((e) => e.seq > this.lastFxSeq);
      if (fresh.length) {
        this.lastFxSeq = fresh[fresh.length - 1].seq;
        this._consumeFxEvents(fresh);
      }
    }
  }

  _consumeFxEvents(events) {
    let delay = 0;
    for (const ev of events) {
      const run = () => this._triggerSingleFx(ev);
      if (delay <= 0) run();
      else setTimeout(run, delay);
      if (ev.kind === 'speed_roll') delay += 460;
      else if (ev.kind === 'card_pull') delay += 360;
      else if (ev.kind === 'cards_reveal') delay += 320;
      else if (ev.kind === 'dice_clash') delay += 280;
      else if (ev.kind === 'combat_strike') delay += 220;
      else if (ev.kind === 'damage') delay += 170;
      else if (ev.kind === 'passive_trigger') delay += 140;
      else delay += 55;
    }
  }

  _actorPos(charId) {
    const node = this.actorNodes.get(charId);
    if (node) return { x: node.cx, y: node.cy };
    const r = this.charRects.get(charId);
    if (r) return { x: r.x + r.w / 2, y: r.y + r.h / 2 };
    return { x: this.w * 0.5, y: this.h * 0.45 };
  }

  _triggerSingleFx(ev) {
    if (!this.state) return;
    if (ev.kind === 'speed_roll') {
      this._playSpeedRollFx(ev, false);
    } else if (ev.kind === 'passive_trigger') {
      this._playPassiveTriggerFx(ev, false);
    } else if (ev.kind === 'status_change') {
      this._playStatusChangeFx(ev);
    } else if (ev.kind === 'shield_gain') {
      this._playShieldGainFx(ev);
    } else if (ev.kind === 'combat_strike') {
      this._playCombatStrikeFx(ev);
    } else if (ev.kind === 'draw') {
      this.audio.cardSlide();
      const dp = this.pileCenters.get(`${ev.side}:draw`);
      if (dp) {
        this.three.spawnCardFlipArc({
          fromX: dp.x, fromY: dp.y,
          toX: this.layout.arenaX + this.layout.arenaW / 2,
          toY: this.layout.handY,
          width: 72, height: 100,
          accentHex: SIDE_THEME[ev.side]?.accentHex || '#1c8a64',
          flipFromBack: true, duration: 0.4, peakZ: 90,
        });
        this._spawnFloater(dp.x, dp.y - 36, `+${ev.count} 抽牌`, SIDE_THEME[ev.side].accent);
      }
    } else if (ev.kind === 'draw_bottom') {
      this.audio.cardPlace();
      const dp = this.pileCenters.get(`${ev.side}:draw`);
      if (dp) this._spawnFloater(dp.x, dp.y - 32, `置底 ${ev.count}`, INK.gold);
    } else if (ev.kind === 'cost_refill') {
      this.audio.coinClink(1.08);
      const ca = this.costAnchors.get(ev.side);
      if (ca) this.three.triggerRipple(ca.x, ca.y, INK.gold);
    } else if (ev.kind === 'cost_pay') {
      if (ev.paid) {
        this.audio.coinClink(0.95);
        const ca = this.costAnchors.get(ev.side);
        const pos = this._actorPos(ev.character_id);
        if (ev.cost > 0) {
          if (ca) {
            this.three.spawnEnergyBeam({
              fromX: ca.x, fromY: ca.y,
              toX: this.layout.arenaX + this.layout.arenaW * (ev.side === 1 ? 0.28 : 0.72),
              toY: this.layout.arenaTop + 180,
              colorHex: INK.gold,
              duration: 0.42,
            });
          }
          this._spawnFloater(pos.x, pos.y - 44, `-${ev.cost} 费`, INK.gold, 14);
        }
      } else {
        this.audio.shieldErode();
        this._showBanner(`费用不足 · 跳过「${ev.card_name}」`, 0xcf4932, 1.5);
      }
    } else if (ev.kind === 'card_pull') {
      this.audio.cardFlip();
      const from = this.regularSlotRects.get(`${ev.from_duel}:${ev.defender_side}`);
      const to = this.preRevealSlotRects.get(ev.to_pre_reveal);
      this.three.spawnCardFlipArc({
        fromX: from ? from.cx : this.w * 0.5,
        fromY: from ? from.cy : this.h * 0.52,
        toX: to ? to.cx : this.w * 0.5,
        toY: to ? to.cy : this.h * 0.2,
        title: ev.card_name,
        accentHex: SIDE_THEME[ev.defender_side]?.accentHex || '#1c8a64',
        flipFromBack: true,
        duration: 0.6,
        peakZ: 165,
      });
      this._showBanner(`牵制：常规${CIRCLED[ev.from_duel - 1] || ev.from_duel}「${ev.card_name}」→ 开牌前${CIRCLED[ev.to_pre_reveal - 1] || ev.to_pre_reveal}`, INK.gold, 2.0);
    } else if (ev.kind === 'cards_reveal') {
      this.audio.cardFlip();
      (ev.duels || []).forEach((d, idx) => {
        for (const sideStr of Object.keys(d.sides || {})) {
          const s = Number(sideStr);
          if (!(d.sides[sideStr] || []).length) continue;
          const rect = this.regularSlotRects.get(`${d.number}:${s}`);
          if (rect) {
            setTimeout(() => {
              this.audio.cardFlip();
              this.three.triggerRipple(rect.cx, rect.cy, SIDE_THEME[s].accent);
              this.three.spawnCardFlipArc({
                fromX: rect.cx, fromY: rect.cy, toX: rect.cx, toY: rect.cy,
                width: 96, height: 132, title: '', accentHex: SIDE_THEME[s].accentHex,
                flipFromBack: true, duration: 0.46, peakZ: 115,
              });
            }, idx * 100);
          }
        }
      });
      this._showBanner('统一开牌', INK.gold, 1.4);
    } else if (ev.kind === 'dice_clash') {
      this._playDiceClashFx(ev);
    } else if (ev.kind === 'damage') {
      this._playDamageFx(ev);
    } else if (ev.kind === 'heal') {
      this.audio.healChime();
      const pos = this._actorPos(ev.target_id);
      this._getMotion(ev.target_id).healGlow = 1.0;
      this.three.spawnImpactBurst(pos.x, pos.y, 0x269463, 14, false);
      this._spawnFloater(pos.x, pos.y - 36, `+${ev.amount}`, 0x269463, 19);
    } else if (ev.kind === 'lose_hp') {
      this.audio.hitDamage();
      const pos = this._actorPos(ev.target_id);
      this._getMotion(ev.target_id).recoil = 0.7;
      this._getMotion(ev.target_id).hitFlash = 0.8;
      this._spawnFloater(pos.x, pos.y - 34, `失去 ${ev.amount} 生命`, 0xc44569, 16);
    } else if (ev.kind === 'breath_crit') {
      this.audio.clashImpact(true);
      const pos = this._actorPos(ev.character_id);
      this._spawnFloater(pos.x, pos.y - 46, '✦ 暴击', 0x1a8775, 19);
      this.three.spawnImpactBurst(pos.x, pos.y, 0x24967c, 26, true);
    } else if (ev.kind === 'stagger_check') {
      const pos = this._actorPos(ev.target_id);
      if (ev.triggered) this._triggerShake(8, 0.3);
      this._spawnFloater(pos.x, pos.y - 42, ev.triggered ? '致命失衡' : '失衡 +2', ev.triggered ? 0xd4223a : 0xbf9119, 17);
    } else if (ev.kind === 'card_replace') {
      this.audio.cardFlip();
      const { arenaX, arenaW, arenaTop, arenaH, handY } = this.layout;
      this.three.spawnCardFlipArc({
        fromX: arenaX + arenaW * 0.5, fromY: arenaTop + arenaH * 0.45,
        toX: arenaX + arenaW * 0.5, toY: handY,
        title: '', accentHex: SIDE_THEME[ev.side]?.accentHex || '#1a8775',
        flipFromBack: false, duration: 0.44, peakZ: 120,
      });
    } else if (ev.kind === 'character_death') {
      this.audio.clashImpact(true);
      this._triggerShake(11, 0.45);
      const pos = this._actorPos(ev.character_id);
      this.physics.spawnShieldShards(pos.x, pos.y, 0xcf4330, 18, true);
      this.three.spawnImpactBurst(pos.x, pos.y, 0xcf4330, 38, true);
      this._showBanner(`${ev.name} 阵亡`, 0xcf4330, 2.0);
    } else if (ev.kind === 'turn_recycle') {
      this.audio.turnBell();
      for (const s of ev.sides || []) {
        const total = (s.used_count || 0) + (s.board_count || 0) + (s.discard_count || 0);
        const dp = this.pileCenters.get(`${s.side}:draw`);
        if (dp && total > 0) {
          this.three.spawnCardFlipArc({
            fromX: this.layout.arenaX + this.layout.arenaW / 2,
            fromY: this.layout.arenaTop + 210,
            toX: dp.x, toY: dp.y,
            width: 82, height: 112, title: '', accentHex: SIDE_THEME[s.side].accentHex,
            flipFromBack: false, duration: 0.5, peakZ: 88,
          });
        }
      }
    }
  }

  _playPassiveTriggerFx(ev, silent) {
    if (!silent) this.audio.coinClink(1.22);
    const key = `${ev.character_id}:${ev.passive_name}`;
    this.passivePulses.set(key, 1.65);

    const pos = this._actorPos(ev.character_id);
    this._getMotion(ev.character_id).passiveFlare = 1.0;

    const plate = this.passivePlates.get(key);
    if (plate) {
      this.three.spawnEnergyBeam({
        fromX: plate.cx, fromY: plate.cy,
        toX: pos.x, toY: pos.y,
        colorHex: INK.gold,
        duration: 0.46,
      });
    } else {
      this.three.triggerRipple(pos.x, pos.y, INK.gold);
    }
    this._spawnFloater(pos.x, pos.y - 50, `✦ ${ev.passive_name}`, INK.gold, 14.5);
  }

  _playStatusChangeFx(ev) {
    const pos = this._actorPos(ev.character_id);
    const col = STATUS_COLORS[ev.status] || INK.secondary;
    const sign = ev.delta > 0 ? '+' : '';
    if (ev.delta > 0) {
      this.three.triggerRipple(pos.x, pos.y, col);
    }
    this._spawnFloater(pos.x, pos.y - 26, `${ev.status} ${sign}${ev.delta}`, col, 14);
  }

  _playShieldGainFx(ev) {
    this.audio.shieldBlock();
    const pos = this._actorPos(ev.character_id);
    const st = SHIELD_STYLE[ev.shield_kind] || SHIELD_STYLE.normal;
    this.three.spawnShieldDomePulse({ x: pos.x, y: pos.y, radius: 56, colorHex: st.color });
    this._spawnFloater(pos.x, pos.y - 36, `+${ev.amount} ${st.label}`, st.color, 14.5);
  }

  _playCombatStrikeFx(ev) {
    const from = this._actorPos(ev.attacker_id);
    const to = this._actorPos(ev.target_id);
    const ds = DIE_STYLE[ev.die_type] || DIE_STYLE.slash;

    // Physical actor lunge & target recoil!
    this._getMotion(ev.attacker_id).lunge = 1.0;
    this._getMotion(ev.target_id).recoil = 0.85;
    this._getMotion(ev.target_id).hitFlash = 0.9;

    if (ev.die_type === 'slash') {
      this.audio.clashImpact(true);
      this.three.spawnSlashArc({ fromX: from.x, fromY: from.y, toX: to.x, toY: to.y, colorHex: ds.color });
    } else if (ev.die_type === 'pierce') {
      this.audio.clashImpact(false);
      this.three.spawnPierceLance({ fromX: from.x, fromY: from.y, toX: to.x, toY: to.y, colorHex: ds.color });
    } else {
      this.audio.clashImpact(true);
      this.three.spawnBluntImpact({ toX: to.x, toY: to.y, colorHex: ds.color });
      this._triggerShake(8, 0.24);
    }
  }

  _playSpeedRollFx(ev, silent) {
    if (!silent) this.audio.diceRoll();
    const { arenaX, arenaW, arenaTop } = this.layout;
    const cx = arenaX + arenaW * 0.5;
    const cy = arenaTop + 175;
    let idx = 0;
    for (const s of ev.sides || []) {
      const sign = s.side === 1 ? -1 : 1;
      for (const r of s.rolls || []) {
        this.three.launchDie({
          sides: 4,
          dieType: 'speed',
          rolledValue: r.speed,
          subLabel: r.name.slice(0, 4),
          startX: cx + sign * 220,
          startY: cy + 50,
          targetX: cx + sign * (78 + (idx % 3) * 56),
          targetY: cy,
          radius: 23,
          lifetime: 1.65,
        });
        idx++;
      }
    }
    if (ev.winner_side === null) {
      this._showBanner(`速度平局（第 ${ev.attempt} 次）· 重掷`, INK.gold, 1.3);
    } else {
      const s1 = ev.sides.find((x) => x.side === 1)?.team_speed ?? 0;
      const s2 = ev.sides.find((x) => x.side === 2)?.team_speed ?? 0;
      this._showBanner(`速度 ${s1} : ${s2} · ${SIDE_THEME[ev.winner_side].name}先手`, SIDE_THEME[ev.winner_side].accent, 1.6);
    }
  }

  _playDiceClashFx(ev) {
    this.audio.diceRoll();
    const { arenaX, arenaW, arenaTop } = this.layout;
    const cx = arenaX + arenaW * 0.5;
    const cy = arenaTop + 132;

    const p1 = (ev.sides || []).find((s) => s.side === 1);
    const p2 = (ev.sides || []).find((s) => s.side === 2);

    // Trigger kinetic actor stances (evade wind-dash / attack lunge / block stance)
    for (const sd of ev.sides || []) {
      if (sd.character_id) {
        if (sd.result === 'win' && sd.type === 'evade') {
          this._getMotion(sd.character_id).evade = 1.0;
          const pos = this._actorPos(sd.character_id);
          this.three.triggerRipple(pos.x, pos.y, DIE_STYLE.evade.color);
        } else if (sd.result === 'win' && sd.type === 'block') {
          const pos = this._actorPos(sd.character_id);
          this.three.spawnBlockBarrier({ x: pos.x + (sd.side === 1 ? 36 : -36), y: pos.y, colorHex: DIE_STYLE.block.color });
        } else if (sd.result === 'win') {
          this._getMotion(sd.character_id).lunge = 0.65;
        }
      }
    }

    if (p1 && p2 && !p1.skipped && !p2.skipped) {
      const outcome = p1.result === 'win' ? 'left_win' : p2.result === 'win' ? 'right_win' : 'draw';
      const winDie = p1.result === 'win' ? p1 : p2.result === 'win' ? p2 : null;
      const winColor = winDie ? (DIE_STYLE[winDie.type]?.color || INK.gold) : INK.gold;
      const group = this.physics.createClashDicePair({ cx, cy, radius: 28, outcome, winnerColor: winColor });
      group.winDieType = winDie?.type || null;

      for (const [sd, body] of [[p1, group.leftBody], [p2, group.rightBody]]) {
        const sides = sd.roll_max || LEVEL_MAX[sd.level || sd.printed_level] || 6;
        this.three.launchDie({
          sides,
          dieType: sd.type || 'blank',
          rolledValue: sd.clash_score ?? sd.rolled_value ?? '—',
          subLabel: `1~${sides}`,
          startX: body.position.x,
          startY: body.position.y,
          targetX: cx,
          targetY: cy,
          physicsBody: body,
          radius: 28,
          lifetime: 2.35,
        });
      }
    } else {
      for (const sd of ev.sides || []) {
        const isP1 = sd.side === 1;
        const sides = sd.roll_max || LEVEL_MAX[sd.level || sd.printed_level] || 6;
        this.three.launchDie({
          sides,
          dieType: sd.type || 'blank',
          rolledValue: sd.clash_score ?? sd.rolled_value ?? '—',
          subLabel: sd.skipped ? '跳过' : `1~${sides}`,
          startX: cx + (isP1 ? -210 : 210),
          startY: cy,
          targetX: cx + (isP1 ? -78 : 78),
          targetY: cy,
          radius: 27,
          lifetime: 1.9,
        });
      }
    }
  }

  _playDamageFx(ev) {
    const pos = this._actorPos(ev.target_id);
    const tx = pos.x;
    const ty = pos.y;

    const absorbedTotal = (ev.absorbed?.normal || 0) + (ev.absorbed?.reinforced || 0) + (ev.absorbed?.concept || 0);
    const erodedNormal = ev.eroded?.normal || 0;
    const erodedReinf = ev.eroded?.reinforced || 0;

    if (absorbedTotal > 0) {
      this.audio.shieldBlock();
      const col = ev.absorbed.concept ? SHIELD_STYLE.concept.color
        : ev.absorbed.reinforced ? SHIELD_STYLE.reinforced.color : SHIELD_STYLE.normal.color;
      this.three.spawnShieldDomePulse({ x: tx, y: ty, radius: 52, colorHex: col });
      this.physics.spawnShieldShards(tx, ty - 8, col, Math.min(10, 4 + absorbedTotal * 2), false);
      this.three.spawnImpactBurst(tx, ty - 8, col, 16, false);
      this._spawnFloater(tx, ty - 42, `护盾抵扣 -${absorbedTotal}`, col, 15);
    }

    if (erodedNormal > 0 || erodedReinf > 0) {
      this.audio.shieldErode();
      if (erodedNormal > 0) {
        this.physics.spawnShieldShards(tx - 14, ty - 6, SHIELD_STYLE.normal.color, 10 + erodedNormal * 2, true);
        this._spawnFloater(tx - 18, ty - 58, `磨损 -${erodedNormal} 普通护盾`, INK.secondary, 14);
      }
      if (erodedReinf > 0) {
        this.physics.spawnShieldShards(tx + 10, ty - 6, SHIELD_STYLE.reinforced.color, 10 + erodedReinf * 2, true);
        this._spawnFloater(tx + 14, ty - 58, `磨损 -${erodedReinf} 强化护盾`, INK.gold, 14);
      }
    }

    if (ev.hp_lost > 0) {
      this.audio.hitDamage();
      this._getMotion(ev.target_id).recoil = 1.0;
      this._getMotion(ev.target_id).hitFlash = 1.0;
      this._triggerShake(Math.min(11, 5 + ev.hp_lost * 2), 0.28);
      this.three.spawnImpactBurst(tx, ty, 0xcf4330, 24, ev.hp_lost >= 3);
      const multTag = ev.multiplier > 1 ? ` ×${ev.multiplier}` : '';
      this._spawnFloater(tx, ty - 18, `-${ev.hp_lost} ${GRADE_LABEL[ev.grade] || ''}${multTag}`, 0xcf4330, 21);
    } else if (absorbedTotal === 0) {
      this._spawnFloater(tx, ty - 14, '0', INK.muted, 15);
    }
  }

  _triggerShake(power, duration) {
    this.shakePower = Math.max(this.shakePower, power);
    this.shakeTime = Math.max(this.shakeTime, duration);
  }

  _spawnFloater(x, y, text, color = INK.primary, fontSize = 15.5) {
    const t = new PIXI.Text({
      text,
      style: {
        fontFamily: FONT_UI, fontSize, fontWeight: '800', fill: color,
        stroke: { color: INK.paper, width: 4 },
      },
    });
    t.anchor.set(0.5);
    t.position.set(x, y);
    this.fxTextLayer.addChild(t);
    this.floaters.push({ obj: t, vx: (Math.random() - 0.5) * 26, vy: -56, age: 0, life: 1.45 });
  }

  _showBanner(text, color = INK.gold, duration = 1.65) {
    this.banner = { text, color, age: 0, duration };
    this._renderToast();
  }

  showToast(text, color = 0xcf4932, duration = 2.4) {
    this.toast = { text, color, age: 0, duration };
    this._renderToast();
  }

  _rebuildAll() {
    if (!this.state) return;
    this._rebuildCornerHud();
    this._rebuildConfrontationWings();
    this._rebuildDynamicBoard();
    this._rebuildOverlay();
  }

  _charNameMap() {
    const map = {};
    for (const p of this.state?.frame?.players || []) {
      for (const c of p.characters || []) map[c.id] = c.name;
    }
    return map;
  }

  _catalogChar(charId) {
    for (const p of this.state?.catalog?.players || []) {
      for (const c of p.characters || []) {
        if (c.id === charId) return c;
      }
    }
    return null;
  }

  _rebuildCornerHud() {
    clearContainer(this.cornerHudLayer);
    const { w, pad } = this.layout;
    const frame = this.state.frame;

    const firstStr = frame.first_side ? ` · ${SIDE_THEME[frame.first_side].name}先手` : '';
    const turnStr = `第 ${frame.turn || 1} 回合 · ${PHASE_NAMES[frame.phase] || frame.phase}${firstStr}`;
    const metaTxt = new PIXI.Text({
      text: turnStr,
      style: { fontFamily: FONT_UI, fontSize: 12.5, fontWeight: '800', fill: INK.primary },
    });
    const pillW = metaTxt.width + 40;
    const pillG = new PIXI.Graphics();
    pillG.roundRect(pad + 2, 12, pillW, 28, 14).fill({ color: INK.shadow, alpha: 0.2 });
    pillG.roundRect(pad, 10, pillW, 28, 14)
      .fill({ color: INK.paper, alpha: 0.96 })
      .stroke({ width: 1.4, color: INK.line });
    drawLightStar(pillG, pad + 16, 24, 7.5, INK.gold, 0.95);
    metaTxt.anchor.set(0, 0.5);
    metaTxt.position.set(pad + 29, 24);
    this.cornerHudLayer.addChild(pillG, metaTxt);

    const tools = [
      {
        label: this.autoPace ? '自动·开' : '自动',
        w: 64,
        accent: this.autoPace ? 0x1c8a64 : INK.secondary,
        solid: this.autoPace,
        fn: () => { this.autoPace = !this.autoPace; this.autoTimer = 0.35; this._rebuildCornerHud(); },
      },
      {
        label: this.audio.muted ? '静音' : '音效',
        w: 54,
        accent: this.audio.muted ? INK.muted : INK.secondary,
        fn: () => { this.audio.toggleMute(); this._rebuildCornerHud(); },
      },
      {
        label: '规则',
        w: 54,
        accent: INK.gold,
        fn: () => { this.codexModal = { tab: 'rules', scrollY: 0, maxScroll: 0 }; this._rebuildOverlay(); },
      },
      {
        label: '选人',
        w: 54,
        accent: 0x1c8a64,
        fn: () => this._openRosterModal(),
      },
    ];
    let rx = w - pad;
    for (let i = tools.length - 1; i >= 0; i--) {
      const t = tools[i];
      rx -= t.w;
      const btn = makeSealButton(t.label, {
        width: t.w, height: 27, accent: t.accent, solid: !!t.solid, fontSize: 11.5, radius: 13, onClick: t.fn,
      });
      btn.position.set(rx, 11);
      this.cornerHudLayer.addChild(btn);
      rx -= 7;
    }
  }

  /**
   * Confrontational Left (P1) & Right (P2) Fighter Wings:
   *  - Top: Faction header + floating golden General Cost crystals (inline, no dead right sidebar!)
   *  - Mid: Sculpted LIVING animated character figure standing on the arena-facing edge + bold HP + active shields + Limbus status icons
   *  - Below each fighter: DIRECTLY EXPANDED VERBATIM PASSIVES (NEVER collapsed behind "被动(4)"!) with live trigger pulse glow!
   *  - Bottom corner: Compact physical 3D card stacks (牌堆 / 弃牌 / 战外)
   */
  _rebuildConfrontationWings() {
    clearContainer(this.wingsLayer);
    clearContainer(this.actorsLayer);
    this.charRects.clear();
    this.actorNodes.clear();
    this.hpWidgets.clear();
    this.passivePlates.clear();
    this.pileCenters.clear();
    this.costAnchors.clear();

    const { leftWingX, rightWingX, wingW, h } = this.layout;
    const frame = this.state.frame;

    for (const side of [1, 2]) {
      const player = (frame.players || []).find((p) => p.side === side);
      if (!player) continue;
      const wx = side === 1 ? leftWingX : rightWingX;
      this._buildPlayerWing(player, wx, wingW, h);
    }
  }

  _buildPlayerWing(player, wx, wingW, h) {
    const side = player.side;
    const theme = SIDE_THEME[side];
    const frame = this.state.frame;
    const isLeft = side === 1;

    // 1. Wing Header: Faction Name + Initiative + Speed + Hand Count + General Cost Crystals!
    const headY = 48;
    const isFirst = frame.first_side === side;
    const speedVal = Number(player.speed || 0).toFixed(player.speed % 1 ? 1 : 0);
    const headTxt = new PIXI.Text({
      text: `${player.name}${isFirst ? ' ★先手' : ''} · 速${speedVal} · 手牌${player.hand_count}`,
      style: { fontFamily: FONT_UI, fontSize: 12, fontWeight: '800', fill: theme.accent },
    });
    headTxt.anchor.set(isLeft ? 0 : 1, 0);
    headTxt.position.set(isLeft ? wx + 2 : wx + wingW - 2, headY);
    this.wingsLayer.addChild(headTxt);

    // Inline General Cost Crystals
    const costY = headY + 26;
    const avail = player.cost?.available ?? 0;
    const spent = player.cost?.spent ?? 0;
    const total = Math.min(8, Math.max(avail + spent, player.cost?.refill || 5));
    const costG = new PIXI.Graphics();
    const costLabel = new PIXI.Text({
      text: `通用费 ${avail}`,
      style: { fontFamily: FONT_UI, fontSize: 11, fontWeight: '800', fill: INK.secondary },
    });
    if (isLeft) {
      costLabel.position.set(wx + 2, costY - 7);
      const startX = wx + costLabel.width + 14;
      for (let i = 0; i < total; i++) {
        const isAv = i < avail;
        drawCostCrystal(costG, startX + i * 19, costY, 7.5, isAv ? INK.gold : INK.paperTint, isAv ? 0x99610b : INK.line);
      }
      this.costAnchors.set(side, { x: startX + Math.max(0, avail - 1) * 19, y: costY });
    } else {
      costLabel.anchor.set(1, 0);
      costLabel.position.set(wx + wingW - 2, costY - 7);
      const endX = wx + wingW - costLabel.width - 14;
      for (let i = 0; i < total; i++) {
        const isAv = i < avail;
        drawCostCrystal(costG, endX - i * 19, costY, 7.5, isAv ? INK.gold : INK.paperTint, isAv ? 0x99610b : INK.line);
      }
      this.costAnchors.set(side, { x: endX - Math.max(0, avail - 1) * 19, y: costY });
    }
    this.wingsLayer.addChild(costG, costLabel);

    // 2. Bottom Corner Physical Card Stacks (compact 3D stacks, zero sidebar bloat!)
    const stackH = 60;
    const stackY = h - stackH - 22;
    this._drawCornerStacks(player, wx, stackY, wingW, stackH);

    // 3. Fighters + Directly Expanded Verbatim Passives
    const chars = player.characters || [];
    const zoneTop = costY + 18;
    const zoneBottom = stackY - 12;
    const zoneH = Math.max(220, zoneBottom - zoneTop);
    const gap = 10;
    const perCharH = Math.floor((zoneH - gap * (chars.length - 1)) / Math.max(1, chars.length));

    chars.forEach((ch, idx) => {
      const cy = zoneTop + idx * (perCharH + gap);
      this._buildFighterAndPassives(ch, side, wx, cy, wingW, perCharH, chars.length);
    });
  }

  _buildFighterAndPassives(ch, side, x, y, w, availH, teamCount) {
    const theme = SIDE_THEME[side];
    const isLeft = side === 1;
    const activeSide = this.state.active_side;
    const defaultTarget = activeSide && activeSide !== side && this.state.default_targets?.[String(activeSide)] === ch.id;
    const catChar = this._catalogChar(ch.id);
    const allPassives = [
      ...(catChar?.faction_passives || []).map((p) => ({ ...p, kind: '阵营被动' })),
      ...(catChar?.passives || []).map((p) => ({ ...p, kind: '角色被动' })),
    ];

    // Fighter Stage Pedestal height
    const stageH = teamCount === 1 ? 124 : teamCount === 2 ? 102 : 84;
    const rect = { x, y, w, h: stageH, side };
    this.charRects.set(ch.id, rect);

    const card = new PIXI.Container();
    card.position.set(x, y);

    const bg = new PIXI.Graphics();
    bg.roundRect(2, 5, w, stageH, 13).fill({ color: INK.shadow, alpha: 0.22 });
    bg.roundRect(0, 0, w, stageH, 13)
      .fill({ color: ch.alive ? INK.paper : 0xede8de, alpha: ch.alive ? 0.94 : 0.76 })
      .stroke({ width: defaultTarget ? 2.4 : 1.5, color: defaultTarget ? INK.gold : ch.alive ? theme.border : INK.line });
    // Arena-facing accent ribbon edge
    bg.roundRect(isLeft ? w - 6 : 0, 0, 6, stageH, 3).fill({ color: ch.alive ? theme.accent : INK.muted });
    card.addChild(bg);

    // Click fighter -> open Pinned Character Dossier (full passives + statuses + skills + focus target!)
    card.eventMode = 'static';
    card.cursor = 'pointer';
    card.on('pointertap', (e) => {
      if (this.dragState) return;
      e.stopPropagation();
      this.dossierModal = {
        charId: ch.id,
        side,
        selectedSkillId: catChar?.skills?.[0]?.id || null,
        scrollY: 0,
        maxScroll: 0,
      };
      this.hoveredCard = null;
      this.hoveredInfo = null;
      this._renderInspection();
      this._rebuildOverlay();
    });

    // Living Animated Character Actor positioned on the INNER arena-facing edge!
    const actorR = teamCount === 1 ? 37 : teamCount === 2 ? 31 : 25;
    const actorLocalX = isLeft ? w - actorR - 14 : actorR + 14;
    const actorLocalY = stageH * 0.54;
    const actor = createCharacterActor(ch, side, { radius: actorR });
    actor.position.set(x + actorLocalX, y + actorLocalY);
    actor.tick(this.time, this._getMotion(ch.id), ch);
    this.actorsLayer.addChild(actor);
    this.actorNodes.set(ch.id, { actor, liveCh: ch, cx: x + actorLocalX, cy: y + actorLocalY, side });

    // Info column sits beside the living figure (outer half of the pedestal)
    const infoPad = 12;
    const actorReserve = actorR * 2 + 26;
    const infoX = isLeft ? infoPad : actorReserve;
    const infoW = w - actorReserve - infoPad;

    // Row 1: Character Name + Speed + Personal Cost crystal
    const nameTxt = new PIXI.Text({
      text: `${ch.name}${ch.alive ? '' : ' [阵亡]'}`,
      style: { fontFamily: FONT_UI, fontSize: teamCount === 1 ? 16 : 14.5, fontWeight: '800', fill: ch.alive ? INK.primary : INK.muted },
    });
    nameTxt.position.set(infoX, 9);
    card.addChild(nameTxt);

    const pCost = ch.cost?.available ?? 0;
    const pcX = infoX + infoW - 11;
    const pcY = 18;
    drawCostCrystal(bg, pcX, pcY, 9.5, pCost > 0 ? INK.gold : INK.paperTint, pCost > 0 ? 0xa3680c : INK.line);
    const pcTxt = new PIXI.Text({
      text: String(pCost),
      style: { fontFamily: FONT_NUM, fontSize: 11, fontWeight: '900', fill: pCost > 0 ? INK.paper : INK.muted },
    });
    pcTxt.anchor.set(0.5);
    pcTxt.position.set(pcX, pcY);
    card.addChild(pcTxt);

    // Speed + Duel Quota pips
    const spTxt = new PIXI.Text({
      text: `速${ch.speed ?? 0}`,
      style: { fontFamily: FONT_NUM, fontSize: 10.5, fontWeight: '800', fill: INK.secondary },
    });
    spTxt.anchor.set(1, 0.5);
    spTxt.position.set(pcX - 15, pcY);
    card.addChild(spTxt);

    const maxD = ch.duels?.max ?? 1;
    const usedD = ch.duels?.used;
    const pipStartX = infoX + nameTxt.width + 10;
    for (let i = 0; i < maxD; i++) {
      const px = pipStartX + i * 10;
      if (px > pcX - 42) break;
      const used = usedD !== null && i < usedD;
      bg.circle(px, pcY, 3.6)
        .fill({ color: usedD === null ? INK.line : used ? INK.paperTint : theme.accent })
        .stroke({ width: 1.2, color: usedD === null ? INK.muted : theme.accent });
    }

    // Row 2: Bold HP Bar + Exact Numeral (live-animated without rebuilding containers!)
    const hpY = teamCount === 3 ? 31 : 35;
    const barH = teamCount === 3 ? 12 : 14;
    const barW = infoW - 50;
    const displayHp = this.hpDisplay.get(ch.id) ?? ch.hp;
    const ratio = Math.max(0, Math.min(1, displayHp / Math.max(1, ch.max_hp)));

    bg.roundRect(infoX, hpY, barW, barH, 7).fill({ color: INK.paperTint }).stroke({ width: 1, color: INK.line });
    const hpBarG = new PIXI.Graphics();
    if (ratio > 0) {
      hpBarG.roundRect(infoX + 1, hpY + 1, Math.max(7, (barW - 2) * ratio), barH - 2, 6)
        .fill({ color: ratio < 0.34 ? 0xd94524 : theme.accent });
    }
    const hpTxt = new PIXI.Text({
      text: `${Math.round(displayHp)}/${ch.max_hp}`,
      style: { fontFamily: FONT_NUM, fontSize: teamCount === 3 ? 12.5 : 14, fontWeight: '900', fill: INK.primary },
    });
    hpTxt.anchor.set(1, 0.5);
    hpTxt.position.set(infoX + infoW, hpY + barH / 2);
    card.addChild(hpBarG, hpTxt);
    this.hpWidgets.set(ch.id, { hpBarG, hpTxt, infoX, hpY, barW, barH, maxHp: ch.max_hp, accent: theme.accent });

    // Row 3: Active Shields (ONLY if > 0) + Limbus-style 26x26 Status Icons (hover for full verbatim text!)
    const row3Y = hpY + barH + 8;
    let cx = infoX;
    const shields = ch.shields || {};
    for (const kind of ['normal', 'reinforced', 'concept']) {
      const val = shields[kind] || 0;
      if (val <= 0) continue;
      const st = SHIELD_STYLE[kind];
      bg.roundRect(cx, row3Y, 42, 24, 6).fill({ color: st.bg }).stroke({ width: 1.4, color: st.color });
      drawShieldGlyph(bg, kind, cx + 11, row3Y + 12, 6.5);
      const stNum = new PIXI.Text({
        text: String(val),
        style: { fontFamily: FONT_NUM, fontSize: 12.5, fontWeight: '900', fill: st.color },
      });
      stNum.anchor.set(0, 0.5);
      stNum.position.set(cx + 22, row3Y + 12);
      card.addChild(stNum);
      cx += 46;
    }

    const statuses = Object.entries(ch.statuses || {});
    for (const [name, val] of statuses) {
      if (cx + 25 > infoX + infoW + 4) break;
      const col = STATUS_COLORS[name] || INK.secondary;
      const burst = name === '裂血' && ch.bleed_burst;
      const iconBox = new PIXI.Container();
      iconBox.position.set(cx, row3Y);
      const ig = new PIXI.Graphics();
      ig.roundRect(0, 0, 25, 25, 6)
        .fill({ color: burst ? 0xfce0e4 : INK.paperSoft })
        .stroke({ width: burst ? 2 : 1.4, color: col });
      drawStatusIcon(ig, name, 12.5, 11.5, 8, col);
      ig.roundRect(12, 13, 14, 12.5, 3.5).fill({ color: col });
      iconBox.addChild(ig);

      const valTxt = new PIXI.Text({
        text: String(val),
        style: { fontFamily: FONT_NUM, fontSize: 9.5, fontWeight: '900', fill: INK.paper },
      });
      valTxt.anchor.set(0.5);
      valTxt.position.set(19, 19);
      iconBox.addChild(valTxt);

      iconBox.eventMode = 'static';
      iconBox.cursor = 'help';
      iconBox.on('pointerover', () => {
        this.hoveredInfo = {
          kind: 'statuses',
          title: `${ch.name} · 状态效果`,
          items: statuses.map(([n, v]) => {
            const rl = this.state?.catalog?.statuses?.[n];
            return {
              name: n,
              value: v,
              burst: n === '裂血' && ch.bleed_burst,
              color: STATUS_COLORS[n] || INK.secondary,
              text: (rl && rl.length ? rl.join('\n') : OFFICIAL_STATUS_RULES[n]) || '',
            };
          }),
          side,
          y: y + 8,
        };
        this._renderInspection();
      });
      iconBox.on('pointerout', () => {
        this.hoveredInfo = null;
        this._renderInspection();
      });
      card.addChild(iconBox);
      cx += 29;
    }

    if (defaultTarget) {
      const ft = new PIXI.Text({
        text: '◎ 集火目标',
        style: { fontFamily: FONT_UI, fontSize: 10, fontWeight: '800', fill: INK.gold },
      });
      ft.position.set(infoX, stageH - 18);
      card.addChild(ft);
    }

    this.wingsLayer.addChild(card);

    // 4. DIRECTLY EXPANDED CHARACTER PASSIVES right below the fighter! (NEVER hidden behind a "被动(4)" button!)
    const passivesTop = y + stageH + 7;
    const passivesAvailH = Math.max(0, y + availH - passivesTop);
    if (allPassives.length && passivesAvailH >= 36) {
      this._drawExpandedPassives(ch, side, allPassives, x, passivesTop, w, passivesAvailH);
    }
  }

  /**
   * Renders ALL character passives directly expanded on screen with 100% verbatim rule text
   * and live golden-jade trigger glow overlays!
   */
  _drawExpandedPassives(ch, side, passives, x, y, w, availH) {
    const theme = SIDE_THEME[side];
    const gap = 6;
    const dense = passives.length >= 4 && availH < 340;
    const veryDense = availH < 110;
    const titleSize = veryDense ? 10.5 : dense ? 11 : 11.8;
    const bodySize = veryDense ? 10 : dense ? 10.4 : 11.2;
    const lineH = veryDense ? 13.5 : dense ? 14.5 : 15.8;
    const maxChars = Math.max(22, Math.floor((w - 28) / (bodySize * 0.56)));

    // Pre-measure to fit all verbatim passives cleanly without truncating a single word!
    const prepared = passives.map((p) => {
      const fullText = (p.entries || []).join('\n') || p.description || '';
      const head = new PIXI.Text({
        text: p.name || p.kind,
        style: { fontFamily: FONT_UI, fontSize: titleSize, fontWeight: '800', fill: p.kind === '阵营被动' ? theme.accent : 0xa3680c },
      });
      const body = fullText ? new PIXI.Text({
        text: wrapCjkText(fullText, maxChars),
        style: {
          fontFamily: FONT_UI,
          fontSize: bodySize,
          fill: INK.primary,
          lineHeight: lineH,
          wordWrap: true,
          breakWords: true,
          wordWrapWidth: w - 26,
        },
      }) : null;
      const boxH = 22 + (body ? body.height + 7 : 4);
      return { p, fullText, head, body, boxH };
    });

    const totalNeeded = prepared.reduce((acc, it) => acc + it.boxH, 0) + gap * Math.max(0, prepared.length - 1);
    const fitsAllVerbatim = totalNeeded <= availH + 6;

    let curY = y;
    for (const item of prepared) {
      const { p, fullText, head, body, boxH } = item;
      const key = `${ch.id}:${p.name || p.kind}`;
      const remainingH = y + availH - curY;
      if (remainingH < 24) {
        head.destroy();
        if (body) body.destroy();
        break;
      }

      const drawH = fitsAllVerbatim ? boxH : Math.min(boxH, Math.max(28, Math.floor((availH - gap * (prepared.length - 1)) / prepared.length)));
      const showBodyInPlace = fitsAllVerbatim || drawH >= boxH - 2;

      const plate = new PIXI.Container();
      plate.position.set(x, curY);
      const bg = new PIXI.Graphics();
      bg.roundRect(1, 3, w, drawH, 9).fill({ color: INK.shadow, alpha: 0.16 });
      bg.roundRect(0, 0, w, drawH, 9)
        .fill({ color: p.kind === '阵营被动' ? theme.warmTint : INK.paper, alpha: 0.96 })
        .stroke({ width: 1.2, color: p.kind === '阵营被动' ? theme.border : INK.line });
      // Sculpted passive emblem diamond on left
      drawLightStar(bg, 12, 12, 5.2, p.kind === '阵营被动' ? theme.accent : INK.gold, 0.9);
      plate.addChild(bg);

      head.position.set(22, 4);
      plate.addChild(head);

      if (showBodyInPlace && body) {
        body.position.set(12, 22);
        plate.addChild(body);
      } else {
        if (body) body.destroy();
        // Compact 3v3 fallback: show full passive name + hover reveals full 100% verbatim text!
        const tag = new PIXI.Text({
          text: p.kind === '阵营被动' ? '阵营' : '被动',
          style: { fontFamily: FONT_UI, fontSize: 9.5, fontWeight: '700', fill: INK.muted },
        });
        tag.anchor.set(1, 0.5);
        tag.position.set(w - 10, drawH / 2);
        plate.addChild(tag);
      }

      // Live trigger glow layer ticked every frame when this passive fires!
      const glowG = new PIXI.Graphics();
      plate.addChild(glowG);

      plate.eventMode = 'static';
      plate.cursor = 'pointer';
      plate.on('pointerover', () => {
        if (!showBodyInPlace && fullText) {
          this.hoveredInfo = {
            kind: 'passives',
            title: `${ch.name} · ${p.name || p.kind}`,
            items: [{ name: p.name || p.kind, color: INK.gold, text: fullText }],
            side,
            y: curY,
          };
          this._renderInspection();
        }
      });
      plate.on('pointerout', () => {
        if (!showBodyInPlace) {
          this.hoveredInfo = null;
          this._renderInspection();
        }
      });

      this.wingsLayer.addChild(plate);
      this.passivePlates.set(key, {
        x, y: curY, w, h: drawH,
        cx: x + w / 2, cy: curY + drawH / 2,
        glowG,
      });
      curY += drawH + gap;
    }
  }

  _drawCornerStacks(player, wx, y, wingW, stackH) {
    const side = player.side;
    const theme = SIDE_THEME[side];
    const stacks = [
      { key: 'draw', label: '牌堆', count: player.draw_count, cards: null, col: theme.accent, bg: theme.softBg },
      { key: 'delayed_discard', label: '弃牌', count: player.delayed_discard_count, cards: player.delayed_discard, col: 0xcc7b14, bg: 0xfef4df },
      { key: 'out_of_combat', label: '战外', count: player.out_of_combat_count, cards: player.out_of_combat, col: INK.muted, bg: INK.paperSoft },
    ];
    const cardW = 52;
    const gap = 12;
    const totalW = stacks.length * cardW + (stacks.length - 1) * gap;
    const startX = side === 1 ? wx : wx + wingW - totalW;

    stacks.forEach((st, idx) => {
      const sx = startX + idx * (cardW + gap);
      this.pileCenters.set(`${side}:${st.key}`, { x: sx + cardW / 2, y: y + stackH / 2 });
      const box = new PIXI.Container();
      box.position.set(sx, y);
      const g = new PIXI.Graphics();

      if (st.count === 0) {
        g.roundRect(0, 0, cardW, stackH, 7)
          .fill({ color: INK.paperSoft, alpha: 0.42 })
          .stroke({ width: 1, color: INK.line, alpha: 0.7 });
      } else {
        const layers = Math.min(5, st.count);
        for (let l = layers; l >= 1; l--) {
          g.roundRect(l * 1.4, -l * 1.5, cardW, stackH, 7)
            .fill({ color: INK.paper })
            .stroke({ width: 1, color: st.col, alpha: 0.45 });
        }
        g.roundRect(0, 0, cardW, stackH, 7).fill({ color: st.bg }).stroke({ width: 1.6, color: st.col });
        if (st.key === 'draw') drawLightStar(g, cardW / 2, stackH / 2 - 6, 10, st.col, 0.55);
      }
      box.addChild(g);

      const num = new PIXI.Text({
        text: String(st.count),
        style: { fontFamily: FONT_NUM, fontSize: 15, fontWeight: '900', fill: st.count > 0 ? st.col : INK.muted },
      });
      num.anchor.set(0.5);
      num.position.set(cardW / 2, st.key === 'draw' && st.count > 0 ? stackH - 14 : stackH / 2 - 2);
      const cap = new PIXI.Text({
        text: st.label,
        style: { fontFamily: FONT_UI, fontSize: 9.5, fontWeight: '700', fill: INK.secondary },
      });
      cap.anchor.set(0.5, 0);
      cap.position.set(cardW / 2, stackH + 3);
      box.addChild(num, cap);

      if (st.cards !== null && st.count > 0) {
        box.eventMode = 'static';
        box.cursor = 'pointer';
        box.on('pointertap', (e) => {
          e.stopPropagation();
          this.pileModal = { title: `${player.name} · ${st.label}`, side, cards: st.cards };
          this._rebuildOverlay();
        });
      }
      this.wingsLayer.addChild(box);
    });
  }

  /**
   * Phase-Driven Dynamic Center Stage:
   *  - During Combat -> switches cleanly into Focused Center-Stage Showdown!
   *  - During Placement / Pre-Reveal / Reveal -> Wide Confrontational Horizontal Duel Bridge (Left P1 ⚔ Right P2)!
   */
  _rebuildDynamicBoard() {
    clearContainer(this.boardLayer);
    clearContainer(this.clashLayer);
    clearContainer(this.controlsLayer);
    this.regularSlotRects.clear();
    this.regularLaneRects.clear();
    this.preRevealSlotRects.clear();
    this.preTimerTexts = [];

    const frame = this.state.frame;
    if (frame.combat) {
      this._rebuildCombatShowdownStage();
      this.physics.pruneHandCards(new Set());
      clearContainer(this.handLayer);
      this.handCardViews.clear();
      this._rebuildActionControls();
      return;
    }

    this._rebuildConfrontationBridge();
    this._rebuildHandFan();
    this._rebuildActionControls();
  }

  /**
   * MODE A: Confrontational Horizontal Duel Bridge (Left P1 card faces Right P2 card directly!)
   */
  _rebuildConfrontationBridge() {
    const { arenaX, arenaW, arenaTop, arenaH } = this.layout;
    const frame = this.state.frame;
    const charNames = this._charNameMap();
    const multiChar = (frame.players || []).some((p) => (p.characters || []).length > 1);

    const preDuels = frame.pre_reveal?.duels || [];
    const instantDuels = frame.special_duels || [];
    const allTopDuels = [
      ...preDuels.map((d) => ({ ...d, _kind: 'pre_reveal' })),
      ...instantDuels.map((d) => ({ ...d, _kind: 'instant' })),
    ];
    const showPreLane = allTopDuels.length > 0 || this.state.mode === 'pre_attack' || this.state.mode === 'intercept';

    let regTop = arenaTop;
    let regH = arenaH;

    // 1. Pre-Reveal / Instant Arch (ONLY visible when active!)
    if (showPreLane) {
      const preH = Math.min(138, Math.round(arenaH * 0.31));
      regTop = arenaTop + preH + 12;
      regH = arenaH - preH - 12;

      const pendingNumbers = new Set(this.state.pending_responses || []);
      const archG = new PIXI.Graphics();
      archG.roundRect(arenaX, arenaTop, arenaW, preH, 13)
        .fill({ color: 0xfbf5e8, alpha: 0.82 })
        .stroke({ width: 1.5, color: INK.gold, alpha: 0.65 });
      this.boardLayer.addChild(archG);

      if (!allTopDuels.length) {
        const cue = new PIXI.Text({
          text: '开牌前交锋',
          style: { fontFamily: FONT_UI, fontSize: 13, fontWeight: '800', fill: INK.gold },
        });
        cue.anchor.set(0.5);
        cue.position.set(arenaX + arenaW / 2, arenaTop + preH / 2);
        this.boardLayer.addChild(cue);
      } else {
        const count = allTopDuels.length;
        const slotW = Math.min(208, Math.floor((arenaW - 22 - (count - 1) * 10) / count));
        const slotH = preH - 16;
        const totalW = count * slotW + (count - 1) * 10;
        const startX = arenaX + (arenaW - totalW) / 2;

        allTopDuels.forEach((slot, idx) => {
          const sx = startX + idx * (slotW + 10);
          const sy = arenaTop + 8;
          const isPendingForMe = slot._kind === 'pre_reveal' && !slot.ready && pendingNumbers.has(slot.number);
          if (slot._kind === 'pre_reveal') {
            this.preRevealSlotRects.set(slot.number, { x: sx, y: sy, w: slotW, h: slotH, cx: sx + slotW / 2, cy: sy + slotH / 2 });
          }

          const sg = new PIXI.Graphics();
          sg.roundRect(sx + 2, sy + 4, slotW, slotH, 10).fill({ color: INK.shadow, alpha: 0.2 });
          sg.roundRect(sx, sy, slotW, slotH, 10)
            .fill({ color: INK.paper })
            .stroke({ width: isPendingForMe ? 2.2 : 1.3, color: isPendingForMe ? 0xcf4932 : slot.ready ? 0x1c8a64 : INK.line });
          this.boardLayer.addChild(sg);

          const prefix = slot._kind === 'instant' ? '即时' : '开牌前';
          const mark = CIRCLED[slot.number - 1] || String(slot.number);
          const targetTxt = slot.target?.kind === 'duel'
            ? `→ 常规${CIRCLED[slot.target.number - 1] || slot.target.number}`
            : slot.target?.kind === 'intercept' ? `⇄ ${slot.target.name}` : `→ ${slot.target?.name || ''}`;
          const timingRec = slot._kind === 'pre_reveal'
            ? (this.state.response_times || []).find((t) => t.number === slot.number) : null;
          let elapsed = '';
          if (timingRec?.declared_at_ms) {
            elapsed = ` ${(((timingRec.answered_at_ms || Date.now()) - timingRec.declared_at_ms) / 1000).toFixed(1)}s`;
          }
          const baseHeader = `${prefix}${mark} ${slot.ready ? '就绪' : '待迎击'}`;
          const head = new PIXI.Text({
            text: `${baseHeader}${elapsed}`,
            style: { fontFamily: FONT_UI, fontSize: 10.5, fontWeight: '800', fill: isPendingForMe ? 0xcf4932 : INK.primary },
          });
          head.position.set(sx + 8, sy + 5);
          this.boardLayer.addChild(head);
          if (timingRec?.declared_at_ms && !timingRec.answered_at_ms) {
            this.preTimerTexts.push({ txt: head, baseHeader, declaredAt: timingRec.declared_at_ms });
          }

          const sub = new PIXI.Text({
            text: targetTxt,
            style: { fontFamily: FONT_UI, fontSize: 9.8, fontWeight: '700', fill: INK.secondary },
          });
          sub.position.set(sx + 8, sy + 19);
          this.boardLayer.addChild(sub);

          const cards = [];
          for (const sEntry of slot.sides || []) {
            for (const c of sEntry.cards || []) cards.push({ card: c, side: sEntry.side });
          }
          cards.forEach(({ card, side }, cIdx) => {
            const miniW = Math.min(82, (slotW - 18) / Math.max(1, cards.length) - 4);
            const scale = Math.min(miniW / 138, (slotH - 36) / 190);
            const cxCard = sx + 10 + (138 * scale) / 2 + cIdx * (138 * scale + 6);
            const spr = buildCardFront(card, {
              side, ownerName: charNames[card.character_id] || '', showOwner: multiChar,
              width: 138, height: 190, legal: true, playMode: card.play_mode,
            });
            spr.scale.set(scale);
            const cyCard = sy + 33 + (190 * scale) / 2;
            spr.position.set(cxCard, cyCard);
            spr.eventMode = 'static';
            spr.cursor = 'pointer';
            spr.on('pointerover', () => {
              this.hoveredCard = {
                card, side, ownerName: charNames[card.character_id] || '',
                anchorX: cxCard, anchorY: cyCard, cardH: 190 * scale, source: 'board', sourceSprite: spr,
              };
              this._renderInspection();
            });
            spr.on('pointerout', () => {
              this.hoveredCard = null;
              this._renderInspection();
            });
            this.boardLayer.addChild(spr);
          });

          if (isPendingForMe) {
            const passBtn = makeSealButton('放行', {
              width: 52, height: 24, accent: 0xcf4932, solid: true, fontSize: 11, radius: 6,
              onClick: () => this._sendAction('let_through', { duel_number: slot.number }),
            });
            passBtn.position.set(sx + slotW - 58, sy + slotH - 29);
            this.boardLayer.addChild(passBtn);
          }
        });
      }
    }

    // 2. Horizontal Face-to-Face Regular Duel Lanes (Left P1 ⚔ Right P2)
    const duels = frame.duels || [];
    const activeSide = this.state.active_side;
    const nextEmptyNum = this._findFirstEmptyRegularDuel(activeSide);
    const slotCount = Math.max(3, duels.length + (this.state.mode === 'placement' && nextEmptyNum > duels.length ? 1 : 0));

    const useTwoCols = slotCount >= 4 && arenaW >= 540;
    const cols = useTwoCols ? 2 : 1;
    const rows = Math.ceil(slotCount / cols);
    const colGap = 14;
    const rowGap = 10;
    const laneW = Math.floor((arenaW - colGap * (cols - 1)) / cols);
    const laneH = Math.min(156, Math.floor((regH - rowGap * (rows - 1)) / rows));
    const totalH = rows * laneH + (rows - 1) * rowGap;
    const startY = regTop + Math.max(0, Math.floor((regH - totalH) / 2));

    for (let i = 0; i < slotCount; i++) {
      const number = i + 1;
      const col = i % cols;
      const row = Math.floor(i / cols);
      const lx = arenaX + col * (laneW + colGap);
      const ly = startY + row * (laneH + rowGap);
      const midX = lx + laneW / 2;
      const midY = ly + laneH / 2;
      const slotData = duels[i] || { number, sides: [{ side: 1, cards: [] }, { side: 2, cards: [] }] };
      const isNextDropSlot = this.state.mode === 'placement' && number === nextEmptyNum;

      this.regularLaneRects.set(number, { x: lx, y: ly, w: laneW, h: laneH, cx: midX, cy: midY });

      // Confrontational bridge backdrop + opposing directional arrows meeting at the clash emblem!
      const bridgeG = new PIXI.Graphics();
      bridgeG.roundRect(lx, ly, laneW, laneH, 14)
        .fill({ color: INK.paper, alpha: 0.44 })
        .stroke({ width: 1.1, color: INK.line, alpha: 0.72 });
      bridgeG.moveTo(lx + 18, midY).lineTo(lx + laneW - 18, midY)
        .stroke({ width: 1.4, color: INK.line, alpha: 0.85 });
      // Opposing arrows
      bridgeG.poly([midX - 24, midY - 4, midX - 16, midY, midX - 24, midY + 4]).fill({ color: SIDE_THEME[1].accent, alpha: 0.7 });
      bridgeG.poly([midX + 24, midY - 4, midX + 16, midY, midX + 24, midY + 4]).fill({ color: SIDE_THEME[2].accent, alpha: 0.7 });
      // Central Duel Seal ① ② ③
      bridgeG.circle(midX, midY, 15)
        .fill({ color: INK.paper })
        .stroke({ width: 1.8, color: isNextDropSlot ? INK.gold : INK.line });
      this.boardLayer.addChild(bridgeG);

      const numTxt = new PIXI.Text({
        text: CIRCLED[i] || String(number),
        style: { fontFamily: FONT_UI, fontSize: 14, fontWeight: '900', fill: isNextDropSlot ? INK.gold : INK.secondary },
      });
      numTxt.anchor.set(0.5);
      numTxt.position.set(midX, midY);
      this.boardLayer.addChild(numTxt);

      // Left Half = Side 1 well, Right Half = Side 2 well!
      const wellPadX = 12;
      const wellW = Math.floor(laneW / 2 - 28 - wellPadX);
      const wellH = laneH - 12;

      for (const s of [1, 2]) {
        const wx = s === 1 ? lx + wellPadX : midX + 28;
        const wy = ly + 6;
        const wellRect = { x: wx, y: wy, w: wellW, h: wellH, cx: wx + wellW / 2, cy: wy + wellH / 2 };
        this.regularSlotRects.set(`${number}:${s}`, wellRect);

        const isTargetWell = isNextDropSlot && s === activeSide;
        const wellG = new PIXI.Graphics();
        wellG.roundRect(wellRect.x, wellRect.y, wellRect.w, wellRect.h, 11)
          .fill({ color: isTargetWell ? SIDE_THEME[s].warmTint : INK.paperSoft, alpha: isTargetWell ? 0.94 : 0.52 })
          .stroke({
            width: isTargetWell ? 2.2 : 1.1,
            color: isTargetWell ? SIDE_THEME[s].accent : SIDE_THEME[s].border,
            alpha: isTargetWell ? 0.95 : 0.36,
          });
        this.boardLayer.addChild(wellG);

        if (isTargetWell) {
          wellG.eventMode = 'static';
          wellG.cursor = 'pointer';
          wellG.on('pointertap', (e) => {
            if (this.selectedHandCardId) {
              e.stopPropagation();
              this._placeCard(this.selectedHandCardId);
            }
          });
        }

        const sideEntry = (slotData.sides || []).find((x) => x.side === s);
        const cards = sideEntry ? sideEntry.cards : [];
        cards.forEach((card, cIdx) => {
          const fitScale = Math.min((wellRect.w - 8) / 138, (wellRect.h - 6) / 190, 0.88);
          const ox = (cIdx - (cards.length - 1) / 2) * 20;
          const isFaceDown = card.hidden || (!frame.cards_revealed && card.state === 'placed_face_down');
          const spr = isFaceDown
            ? buildCardBack(s, { width: 138, height: 190 })
            : buildCardFront(card, {
                side: s,
                ownerName: charNames[card.character_id] || '',
                showOwner: multiChar,
                width: 138, height: 190,
                legal: true,
              });
          spr.scale.set(fitScale);
          spr.position.set(wellRect.cx + ox, wellRect.cy);
          if (!card.hidden) {
            spr.eventMode = 'static';
            spr.cursor = 'pointer';
            spr.on('pointerover', () => {
              this.hoveredCard = {
                card, side: s, ownerName: charNames[card.character_id] || '',
                anchorX: wellRect.cx + ox, anchorY: wellRect.cy, cardH: 190 * fitScale, source: 'board', sourceSprite: spr,
              };
              this._renderInspection();
            });
            spr.on('pointerout', () => {
              this.hoveredCard = null;
              this._renderInspection();
            });
          }
          this.boardLayer.addChild(spr);
        });
      }
    }
  }

  /**
   * MODE B: Focused Center-Stage Combat Showdown!
   *  - Top compact Duel Progress Rail (all pre-reveal & regular duels at a glance)
   *  - Center 3D Dice Clash Arena + Sculpted 4-Layer Score Medallions (基础 → 变动 → 最终 → 拼点)
   *  - Directly below: BOTH active clashing skills rendered side-by-side with full 100% VERBATIM text & active die glow!
   */
  _rebuildCombatShowdownStage() {
    const { arenaX, arenaW, arenaTop, showdownBottom } = this.layout;
    const frame = this.state.frame;
    const combat = frame.combat;
    const charNames = this._charNameMap();

    // 1. Compact Top Duel Progress Rail (y = 48..78)
    const railItems = [];
    for (const d of frame.pre_reveal?.duels || []) {
      railItems.push({ kind: 'pre_reveal', number: d.number, label: `开牌前${CIRCLED[d.number - 1] || d.number}` });
    }
    for (const d of frame.special_duels || []) {
      railItems.push({ kind: 'instant', number: d.number, label: `即时${CIRCLED[d.number - 1] || d.number}` });
    }
    for (const d of frame.duels || []) {
      railItems.push({ kind: 'regular', number: d.number, label: `常规${CIRCLED[d.number - 1] || d.number}` });
    }

    const chipH = 26;
    const chipGap = 8;
    const chipWidths = railItems.map((it) => (it.kind === 'regular' ? 70 : 84));
    const totalRailW = chipWidths.reduce((a, b) => a + b, 0) + chipGap * Math.max(0, railItems.length - 1);
    let rx = arenaX + Math.max(0, (arenaW - totalRailW) / 2);
    const railY = arenaTop;

    railItems.forEach((it, idx) => {
      const cw = chipWidths[idx];
      const active = combat.kind === it.kind && combat.duel_number === it.number;
      const g = new PIXI.Graphics();
      g.roundRect(rx, railY, cw, chipH, 13)
        .fill({ color: active ? INK.gold : INK.paper, alpha: active ? 1 : 0.9 })
        .stroke({ width: active ? 2 : 1.2, color: active ? 0xa3680c : INK.line });
      this.boardLayer.addChild(g);
      const t = new PIXI.Text({
        text: active ? `⚔ ${it.label}` : it.label,
        style: { fontFamily: FONT_UI, fontSize: 11, fontWeight: '800', fill: active ? INK.paper : INK.secondary },
      });
      t.anchor.set(0.5);
      t.position.set(rx + cw / 2, railY + chipH / 2);
      this.boardLayer.addChild(t);
      rx += cw + chipGap;
    });

    // 2. Sculpted 3D Dice Clash Arena & Score Medallions (y = 86..234)
    const clashTop = railY + chipH + 10;
    const clashH = 148;
    const cx = arenaX + arenaW / 2;

    const arenaG = new PIXI.Graphics();
    arenaG.roundRect(arenaX, clashTop, arenaW, clashH, 16)
      .fill({ color: INK.paper, alpha: 0.72 })
      .stroke({ width: 1.6, color: INK.gold, alpha: 0.72 });
    // Center confrontation axis & luminous clash ring (where the Matter.js 3D dice physically smash!)
    arenaG.moveTo(arenaX + 18, clashTop + clashH / 2).lineTo(arenaX + arenaW - 18, clashTop + clashH / 2)
      .stroke({ width: 1.2, color: INK.line, alpha: 0.65 });
    arenaG.circle(cx, clashTop + clashH / 2, 42)
      .fill({ color: INK.goldBg, alpha: 0.55 })
      .stroke({ width: 1.8, color: INK.gold, alpha: 0.75 });
    this.clashLayer.addChild(arenaG);

    const kindName = { pre_reveal: '开牌前', regular: '常规', instant: '即时' }[combat.kind] || '交锋';
    const roundBadge = new PIXI.Text({
      text: `${kindName}${CIRCLED[(combat.duel_number || 1) - 1] || combat.duel_number} · 第 ${combat.round_id || 1} 轮`,
      style: { fontFamily: FONT_UI, fontSize: 11.5, fontWeight: '800', fill: INK.gold },
    });
    roundBadge.anchor.set(0.5, 0);
    roundBadge.position.set(cx, clashTop + 6);
    this.clashLayer.addChild(roundBadge);

    const vsTxt = new PIXI.Text({
      text: 'VS',
      style: { fontFamily: FONT_NUM, fontSize: 16, fontWeight: '900', fill: INK.gold },
    });
    vsTxt.anchor.set(0.5);
    vsTxt.position.set(cx, clashTop + clashH / 2);
    this.clashLayer.addChild(vsTxt);

    // Draw Left (P1) & Right (P2) Sculpted Live Die Score Medallions
    const medW = Math.min(226, Math.floor(arenaW / 2 - 58));
    for (const s of combat.sides || []) {
      const isLeft = s.side === 1;
      const mx = isLeft ? arenaX + 14 : arenaX + arenaW - medW - 14;
      const my = clashTop + 26;
      const mh = clashH - 36;
      const die = s.die;
      const theme = SIDE_THEME[s.side];

      if (!die) {
        const empty = new PIXI.Text({
          text: `${theme.name} · 无对位`,
          style: { fontFamily: FONT_UI, fontSize: 12.5, fontWeight: '700', fill: INK.muted },
        });
        empty.anchor.set(0.5);
        empty.position.set(mx + medW / 2, my + mh / 2);
        this.clashLayer.addChild(empty);
        continue;
      }

      const ds = DIE_STYLE[die.type] || DIE_STYLE.blank;
      const win = die.result === 'win';
      const lose = die.result === 'lose';
      const mg = new PIXI.Graphics();
      mg.roundRect(mx, my, medW, mh, 12)
        .fill({ color: win ? INK.goldBg : ds.bg, alpha: lose ? 0.65 : 0.96 })
        .stroke({ width: win ? 2.5 : 1.4, color: win ? INK.gold : ds.color });
      drawDieIcon(mg, die.type, mx + 22, my + 24, 10, ds.color);
      this.clashLayer.addChild(mg);

      const rangeStr = formatDieRange(die);
      const resLabel = win
        ? (die.win_branch_skipped ? '胜（跳过拼赢）' : '胜')
        : lose ? '负' : die.result === 'draw' ? '平' : '';

      const head = new PIXI.Text({
        text: `${ds.label} ${rangeStr}${s.range_deficit ? ` 压制-${s.range_deficit}` : ''}`,
        style: { fontFamily: FONT_UI, fontSize: 12.5, fontWeight: '800', fill: INK.primary },
      });
      head.position.set(mx + 38, my + 12);
      this.clashLayer.addChild(head);

      // 4-Layer Score Breakdown Cascade
      const layers = [
        `基础 ${die.base_value ?? 0}`,
        `变动 ${die.rolled_value ?? '—'}`,
        `最终 ${die.final_score ?? '—'}`,
      ].join('  ·  ');
      const lTxt = new PIXI.Text({
        text: layers,
        style: { fontFamily: FONT_UI, fontSize: 10.5, fontWeight: '700', fill: INK.secondary },
      });
      lTxt.position.set(mx + 14, my + mh - 24);
      this.clashLayer.addChild(lTxt);

      // Big Clash Score Numeral + Win/Lose Stamp
      const scoreVal = die.clash_score !== null && die.clash_score !== undefined ? String(die.clash_score) : '—';
      const scTxt = new PIXI.Text({
        text: scoreVal,
        style: {
          fontFamily: FONT_NUM, fontSize: 34, fontWeight: '900',
          fill: win ? ds.color : lose ? INK.muted : INK.primary,
        },
      });
      scTxt.anchor.set(1, 0.5);
      scTxt.position.set(mx + medW - 14, my + 42);
      this.clashLayer.addChild(scTxt);

      if (resLabel) {
        const rt = new PIXI.Text({
          text: resLabel,
          style: { fontFamily: FONT_UI, fontSize: 11.5, fontWeight: '900', fill: win ? INK.gold : lose ? INK.muted : INK.secondary },
        });
        rt.position.set(mx + 38, my + 34);
        this.clashLayer.addChild(rt);
      }
    }

    // 3. Face-to-Face Active Skill Cards with FULL 100% VERBATIM RULE TEXT directly on the Showdown Stage!
    const cardsTop = clashTop + clashH + 14;
    const cardsAvailH = Math.max(180, showdownBottom - cardsTop);
    const colGap = 16;
    const colW = Math.min(360, Math.floor((arenaW - colGap) / 2));
    const pairStartX = arenaX + Math.floor((arenaW - (colW * 2 + colGap)) / 2);

    const activeCardsBySide = this._findActiveCombatCards();
    for (const side of [1, 2]) {
      const combatSide = (combat.sides || []).find((cs) => cs.side === side);
      const card = activeCardsBySide.get(side);
      const px = side === 1 ? pairStartX : pairStartX + colW + colGap;

      if (!card) {
        const emptyG = new PIXI.Graphics();
        emptyG.roundRect(px, cardsTop, colW, Math.min(180, cardsAvailH), 12)
          .fill({ color: INK.paperSoft, alpha: 0.55 })
          .stroke({ width: 1.2, color: INK.line });
        this.boardLayer.addChild(emptyG);
        const et = new PIXI.Text({
          text: `${SIDE_THEME[side].name} · 无迎击技能`,
          style: { fontFamily: FONT_UI, fontSize: 13, fontWeight: '700', fill: INK.muted },
        });
        et.anchor.set(0.5);
        et.position.set(px + colW / 2, cardsTop + Math.min(180, cardsAvailH) / 2);
        this.boardLayer.addChild(et);
        continue;
      }

      const panel = buildVerbatimCardPanel(card, {
        side,
        ownerName: charNames[card.character_id] || '',
        width: colW,
        activeDieNumber: combatSide?.die_number || null,
        compact: colW < 330 || cardsAvailH < 340,
      });
      if (panel._boxHeight > cardsAvailH) {
        const fit = Math.max(0.76, cardsAvailH / panel._boxHeight);
        panel.scale.set(fit);
        panel.position.set(px + (colW * (1 - fit)) / 2, cardsTop);
      } else {
        panel.position.set(px, cardsTop);
      }
      this.boardLayer.addChild(panel);
    }
  }

  _findActiveCombatCards() {
    const out = new Map();
    const frame = this.state?.frame;
    const combat = frame?.combat;
    if (!combat) return out;

    const pools = [];
    if (combat.kind === 'regular') {
      const slot = (frame.duels || []).find((d) => d.number === combat.duel_number);
      if (slot) pools.push(...(slot.sides || []));
    } else if (combat.kind === 'pre_reveal') {
      const slot = (frame.pre_reveal?.duels || []).find((d) => d.number === combat.duel_number);
      if (slot) pools.push(...(slot.sides || []));
    } else if (combat.kind === 'instant') {
      const slot = (frame.special_duels || []).find((d) => d.number === combat.duel_number);
      if (slot) pools.push(...(slot.sides || []));
    }

    for (const cs of combat.sides || []) {
      if (!cs.card_id) continue;
      const sidePool = pools.find((p) => p.side === cs.side);
      const found = sidePool?.cards?.find((c) => c.id === cs.card_id);
      if (found) out.set(cs.side, found);
    }
    return out;
  }

  _findFirstEmptyRegularDuel(side) {
    if (!side || !this.state?.frame) return 1;
    const duels = this.state.frame.duels || [];
    for (const d of duels) {
      const s = (d.sides || []).find((x) => x.side === side);
      if (!s || !s.cards.length) return d.number;
    }
    return duels.length + 1;
  }

  _rebuildHandFan() {
    clearContainer(this.handLayer);
    this.handCardViews.clear();

    const frame = this.state.frame;
    const viewerSide = frame.viewer_side;
    const player = viewerSide ? frame.players.find((p) => p.side === viewerSide) : null;
    const hand = player && Array.isArray(player.hand) ? player.hand : [];
    const { arenaX, arenaW, handY, cardW, cardH } = this.layout;
    const cx = arenaX + arenaW / 2;

    if (!player || this.state.mode === 'draw_select') {
      this.physics.pruneHandCards(new Set());
      return;
    }

    const legalSet = new Set(
      this.state.mode === 'placement'
        ? this.state.legal_cards
        : [...(this.state.legal_attack_cards || []), ...(this.state.legal_intercept_cards || [])]
    );
    const attackSet = new Set(this.state.legal_attack_cards || []);
    const interceptSet = new Set(this.state.legal_intercept_cards || []);
    const charNames = this._charNameMap();
    const multiChar = (player.characters || []).length > 1;

    const count = hand.length;
    const maxSpread = Math.min(arenaW - cardW + 40, Math.max(200, count * 124));
    const step = count > 1 ? Math.min(142, maxSpread / (count - 1)) : 0;
    const deckOrigin = this.pileCenters.get(`${viewerSide}:draw`) || { x: cx, y: handY + 40 };
    const validKeys = new Set();

    hand.forEach((card, i) => {
      const cardKey = `hand_${viewerSide}_${card.id}`;
      validKeys.add(cardKey);
      const norm = count > 1 ? (i / (count - 1)) * 2 - 1 : 0;
      const baseX = cx + (i - (count - 1) / 2) * step;
      const baseY = handY + norm * norm * 10 - 4;
      const baseAngle = norm * 0.055;
      const isLegal = legalSet.has(card.id);
      const isSelected = this.selectedHandCardId === card.id;

      const bodyEntry = this.physics.ensureHandCard(cardKey, deckOrigin.x, deckOrigin.y, cardW, cardH);
      bodyEntry.targetX = baseX;
      bodyEntry.targetY = isSelected ? baseY - 26 : baseY;
      bodyEntry.targetAngle = isSelected ? 0 : baseAngle;
      bodyEntry.targetScale = isSelected ? 1.09 : 1.0;

      const spr = buildCardFront(card, {
        side: viewerSide,
        ownerName: charNames[card.character_id] || '',
        showOwner: multiChar,
        width: cardW,
        height: cardH,
        legal: isLegal,
        selected: isSelected,
      });
      spr.position.set(bodyEntry.body.position.x, bodyEntry.body.position.y);
      spr.rotation = bodyEntry.body.angle;
      spr.scale.set(bodyEntry.scale);
      spr.eventMode = 'static';
      spr.cursor = isLegal ? 'grab' : 'default';

      spr.on('pointerover', () => {
        if (this.dragState) return;
        this.audio.cardSlide();
        this.hoveredCard = {
          card, side: viewerSide, ownerName: charNames[card.character_id] || '',
          anchorX: baseX, anchorY: baseY, cardH, source: 'hand', sourceSprite: spr,
        };
        bodyEntry.targetY = baseY - 12;
        bodyEntry.targetAngle = 0;
        bodyEntry.targetScale = 1.04;
        this.handLayer.setChildIndex(spr, this.handLayer.children.length - 1);
        this._renderInspection();
      });

      spr.on('pointerout', () => {
        if (this.dragState?.cardKey === cardKey) return;
        this.hoveredCard = null;
        bodyEntry.targetY = this.selectedHandCardId === card.id ? baseY - 26 : baseY;
        bodyEntry.targetAngle = this.selectedHandCardId === card.id ? 0 : baseAngle;
        bodyEntry.targetScale = this.selectedHandCardId === card.id ? 1.09 : 1.0;
        this._renderInspection();
      });

      spr.on('pointerdown', (e) => {
        if (!isLegal) {
          this.showToast('该牌当前无法打出。', 0xcf4932, 1.8);
          return;
        }
        e.stopPropagation();
        this.hoveredCard = null;
        this._renderInspection();
        let kind = 'place';
        if (this.state.mode === 'pre_attack' || this.state.mode === 'intercept') {
          if (this.state.mode === 'intercept' && interceptSet.has(card.id) && !attackSet.has(card.id)) kind = 'intercept';
          else if (attackSet.has(card.id)) kind = 'attack';
          else if (interceptSet.has(card.id)) kind = 'intercept';
        }
        this.dragState = {
          card, cardKey, side: viewerSide, kind,
          canAttack: attackSet.has(card.id),
          canIntercept: interceptSet.has(card.id),
          startX: e.global.x, startY: e.global.y,
          x: e.global.x, y: e.global.y,
          moved: false,
        };
        bodyEntry.dragging = true;
        bodyEntry.targetScale = 1.06;
        this.handLayer.setChildIndex(spr, this.handLayer.children.length - 1);
        this.audio.cardSlide();
      });

      this.handLayer.addChild(spr);
      this.handCardViews.set(cardKey, { container: spr, card, side: viewerSide, legal: isLegal, baseX, baseY, baseAngle, bodyEntry });
    });

    this.physics.pruneHandCards(validKeys);
  }

  /**
   * Floating Foreground Action Seals docked cleanly at the arena bottom — ZERO dead sidebar!
   */
  _rebuildActionControls() {
    clearContainer(this.controlsLayer);
    const { arenaX, arenaW, handY, cardH, h } = this.layout;
    const mode = this.state.mode;
    const isCombat = Boolean(this.state.frame?.combat);
    const buttons = [];

    if (mode === 'placement') {
      if (this.selectedHandCardId) {
        buttons.push({ label: '扣置', w: 92, accent: 0x1c8a64, solid: true, fn: () => this._placeCard(this.selectedHandCardId) });
      }
      if (this.state.can_pass) {
        buttons.push({ label: '交权', w: 92, accent: INK.gold, solid: true, fn: () => this._sendAction('pass') });
      }
      buttons.push({
        label: `结束置卡（余${this.state.window_remaining}）`,
        w: 146,
        accent: 0xcf4932,
        fn: () => this._sendAction('end'),
      });
    } else if (mode === 'pre_attack' || mode === 'intercept') {
      if (this.state.can_end_attack) {
        buttons.push({ label: '结束主动进攻', w: 136, accent: INK.gold, solid: true, fn: () => this._sendAction('end_attack') });
      }
      if ((this.state.eligible_sides || []).length > 1) {
        buttons.push({ label: '切换席位', w: 102, accent: 0x1a8775, fn: () => this._sendAction('switch_side') });
      }
    } else if (mode === 'reveal' || mode === 'combat' || mode === 'turn_end' || mode === 'timing') {
      const labelMap = {
        reveal: '进入常规交锋',
        combat: '下一拍',
        timing: '继续',
        turn_end: '下一回合',
      };
      buttons.push({ label: labelMap[mode], w: 144, accent: 0x1c8a64, solid: true, fn: () => this._sendAction('next') });
    }

    if (this.state.special_available && mode !== 'finished' && mode !== 'draw_select' && mode !== 'special' && mode !== 'special_handoff') {
      buttons.push({ label: '特殊行动', w: 112, accent: 0x1a8775, solid: true, fn: () => this._sendAction('open_special') });
    }

    if (!buttons.length) return;
    const gap = 10;
    const totalW = buttons.reduce((acc, b) => acc + b.w, 0) + gap * (buttons.length - 1);
    let bx = arenaX + (arenaW - totalW) / 2;
    const btnH = 34;
    // In combat/reveal/turn_end -> center bottom; in hand phases -> dedicated action strip cleanly above hand!
    const by = isCombat || mode === 'reveal' || mode === 'turn_end'
      ? h - btnH - 16
      : this.layout.actionStripY;

    for (const b of buttons) {
      const btn = makeSealButton(b.label, {
        width: b.w, height: btnH, accent: b.accent, solid: !!b.solid, fontSize: 13, radius: 17, onClick: b.fn,
      });
      btn.position.set(bx, by);
      this.controlsLayer.addChild(btn);
      bx += b.w + gap;
    }
  }

  _rebuildOverlay() {
    clearContainer(this.overlayLayer);
    if (!this.state) return;
    const { w, h } = this.layout;

    if (this.dossierModal) {
      const m = this.dossierModal;
      const pl = (this.state.frame.players || []).find((p) => p.side === m.side);
      const ch = pl?.characters?.find((c) => c.id === m.charId);
      if (!ch) {
        this.dossierModal = null;
      } else {
        const activeSide = this.state.active_side;
        const canSetTarget = Boolean(activeSide && activeSide !== m.side && ch.alive);
        const isDefault = canSetTarget && this.state.default_targets?.[String(activeSide)] === ch.id;
        const ov = buildCharacterDossier(w, h, {
          character: ch,
          side: m.side,
          catalogChar: this._catalogChar(ch.id),
          catalogStatuses: this.state.catalog?.statuses || {},
          selectedSkillId: m.selectedSkillId,
          canSetTarget,
          isDefaultTarget: isDefault,
          scrollY: m.scrollY,
          onSelectSkill: (sid) => { m.selectedSkillId = sid; this._rebuildOverlay(); },
          onSetFocusTarget: () => this._sendAction('set_default_target', { side: activeSide, character_id: ch.id }),
          onClose: () => { this.dossierModal = null; this._rebuildOverlay(); },
        });
        m.maxScroll = ov._maxScroll || 0;
        this.overlayLayer.addChild(ov);
        return;
      }
    }

    if (this.rosterModal) {
      const m = this.rosterModal;
      const ov = buildRosterOverlay(w, h, {
        catalog: this.state.roster_catalog || [],
        team1: m.team1, team2: m.team2, assignSide: m.assignSide, hoveredChar: m.hoveredChar,
        onSetAssignSide: (s) => { m.assignSide = s; this._rebuildOverlay(); },
        onToggleChar: (cid) => {
          const own = m.assignSide === 1 ? m.team1 : m.team2;
          const other = m.assignSide === 1 ? m.team2 : m.team1;
          const idx = own.indexOf(cid);
          if (idx >= 0) own.splice(idx, 1);
          else {
            const oIdx = other.indexOf(cid);
            if (oIdx >= 0) other.splice(oIdx, 1);
            if (own.length < 3) own.push(cid);
            else this.showToast('每方最多选 3 名角色。', INK.gold, 1.8);
          }
          this.audio.coinClink(1.1);
          this._rebuildOverlay();
        },
        onHoverChar: (ch) => { if (m.hoveredChar?.id !== ch.id) { m.hoveredChar = ch; this._rebuildOverlay(); } },
        onStart: async (teams) => {
          this.rosterModal = null;
          this.three.clearDice();
          this.physics.clearClashGroups();
          await this._sendAction('new', { roster: teams });
        },
        onCancel: () => { this.rosterModal = null; this._rebuildOverlay(); },
      });
      this.overlayLayer.addChild(ov);
      return;
    }

    if (this.codexModal) {
      const m = this.codexModal;
      const ov = buildCodexOverlay(w, h, {
        tab: m.tab, scrollY: m.scrollY, catalog: this.state.catalog, history: this.state.history || [],
        onTab: (tab) => { m.tab = tab; m.scrollY = 0; this._rebuildOverlay(); },
        onClose: () => { this.codexModal = null; this._rebuildOverlay(); },
      });
      m.maxScroll = ov._maxScroll || 0;
      this.overlayLayer.addChild(ov);
      return;
    }

    if (this.pileModal) {
      const m = this.pileModal;
      const ov = buildPileOverlay(w, h, {
        title: m.title, side: m.side, cards: m.cards, charNames: this._charNameMap(),
        onHoverCard: (card, side, ownerName, cardX, cardY, cardH, spr) => {
          this.hoveredCard = card
            ? { card, side, ownerName, anchorX: cardX, anchorY: cardY, cardH: cardH || 190, source: 'board', sourceSprite: spr }
            : null;
          this._renderInspection();
        },
        onClose: () => { this.pileModal = null; this.hoveredCard = null; this._renderInspection(); this._rebuildOverlay(); },
      });
      this.overlayLayer.addChild(ov);
      return;
    }

    const mode = this.state.mode;
    if (mode === 'handoff' || mode === 'special_handoff') {
      const ov = buildHandoffOverlay(w, h, {
        activeSide: this.state.active_side,
        eligibleSides: this.state.eligible_sides,
        onReady: (side) => this._sendAction('ready', { side }),
      });
      this.overlayLayer.addChild(ov);
    } else if (mode === 'draw_select' && this.state.draw_select) {
      const prompt = this.state.draw_select;
      const ov = buildDrawSelectOverlay(w, h, {
        prompt, selectedIds: this.drawSelected,
        onToggle: (cid) => {
          if (this.drawSelected.has(cid)) this.drawSelected.delete(cid);
          else if (this.drawSelected.size < prompt.discard_count) this.drawSelected.add(cid);
          else {
            const first = this.drawSelected.values().next().value;
            this.drawSelected.delete(first);
            this.drawSelected.add(cid);
          }
          this.audio.cardSlide();
          this._rebuildOverlay();
        },
        onConfirm: () => this._sendAction('draw_bottom', { card_ids: Array.from(this.drawSelected) }),
        onHoverCard: (card, side, ownerName, cardX, cardY, cardH, spr) => {
          this.hoveredCard = card
            ? { card, side, ownerName, anchorX: cardX, anchorY: cardY, cardH: cardH || 198, source: 'draw', sourceSprite: spr }
            : null;
          this._renderInspection();
        },
      });
      this.overlayLayer.addChild(ov);
    } else if (mode === 'special') {
      const ov = buildSpecialOverlay(w, h, {
        side: this.state.active_side,
        timing: this.state.special_timing,
        options: this.state.special_options || [],
        pendingAttack: this.state.special_pending,
        onPick: (idx) => this._sendAction('use_special', { option: idx }),
        onSwitchSide: () => this._sendAction('switch_side'),
        onLeave: () => this._sendAction('leave_special'),
      });
      this.overlayLayer.addChild(ov);
    } else if (mode === 'finished') {
      const ov = buildFinishOverlay(w, h, {
        winnerSide: this.state.frame.winner_side,
        turn: this.state.frame.turn,
        history: this.state.history || [],
        onRematch: () => {
          const teams = (this.state.frame.players || []).map((p) => p.characters.map((c) => c.id));
          this.three.clearDice();
          this.physics.clearClashGroups();
          this._sendAction('new', { roster: teams });
        },
        onNewRoster: () => this._openRosterModal(),
      });
      this.overlayLayer.addChild(ov);
    }
  }

  _openRosterModal() {
    const players = this.state?.frame?.players || [];
    const t1 = players[0]?.characters?.map((c) => c.id) || ['plan_b_annolin'];
    const t2 = players[1]?.characters?.map((c) => c.id) || ['waa_lake'];
    const catalog = this.state?.roster_catalog || [];
    this.rosterModal = {
      team1: t1.slice(), team2: t2.slice(), assignSide: 1,
      hoveredChar: catalog.find((c) => c.id === t1[0]) || catalog[0] || null,
    };
    this._rebuildOverlay();
  }

  /**
   * True In-Place Card Expansion (ZERO separate "detail popup" and ZERO left/right jumping!):
   * The hovered card ITSELF hides its resting miniature (keeping hit area intact) and seamlessly
   * grows right in-place into its full 100% verbatim readable face where your eyes already are.
   */
  _renderInspection() {
    clearContainer(this.inspectLayer);
    this._inspectAnim = null;
    if (this._hiddenHoverSprite && !this._hiddenHoverSprite.destroyed) {
      this._hiddenHoverSprite.alpha = 1;
    }
    this._hiddenHoverSprite = null;
    if (this.state?.mode === 'handoff' || this.state?.mode === 'special_handoff') return;

    const { w, h } = this.layout;

    if (this.hoveredCard) {
      const { card, side, ownerName, anchorX, anchorY, cardH = 186, source = 'hand', sourceSprite = null } = this.hoveredCard;
      const W = 348;
      const panel = buildVerbatimCardPanel(card, { side, ownerName, width: W, compact: h < 740 });
      const H = panel._boxHeight;

      // Hide the resting miniature so there is ONLY ONE card — the card itself grew in-place!
      if (sourceSprite && !sourceSprite.destroyed) {
        sourceSprite.alpha = 0;
        this._hiddenHoverSprite = sourceSprite;
      }

      const targetX = anchorX ?? w * 0.5;
      const targetY = anchorY ?? h - 100;
      const px = Math.max(16, Math.min(w - W - 16, targetX - W / 2));
      let py;
      let pivotY;
      if (source === 'hand') {
        // Rises smoothly from the bottom edge directly out of its own hand slot!
        py = Math.max(46, h - H - 10);
        pivotY = py + H;
      } else if (source === 'draw') {
        // Expands upward from the card's own bottom edge so the "保留/置底" pill right underneath stays visible!
        const cardBottom = targetY + cardH / 2;
        py = Math.max(46, Math.min(h - H - 56, cardBottom - H));
        pivotY = cardBottom;
      } else {
        // Board / Pile card expands right around its own exact center!
        py = Math.max(46, Math.min(h - H - 14, targetY - H / 2));
        pivotY = targetY;
      }

      const wrap = new PIXI.Container();
      wrap.eventMode = 'none';
      panel.position.set(px, py);
      wrap.addChild(panel);

      const pivotX = Math.max(px + 24, Math.min(px + W - 24, targetX));
      wrap.pivot.set(pivotX, pivotY);
      wrap.position.set(pivotX, pivotY);
      const startScale = source === 'hand' ? 0.72 : 0.68;
      wrap.scale.set(startScale);
      wrap.alpha = 0.55;
      this.inspectLayer.addChild(wrap);
      this._inspectAnim = { node: wrap, age: 0, duration: 0.11, startScale };
    }

    if (this.hoveredInfo) {
      const info = this.hoveredInfo;
      const W = 352;
      const body = new PIXI.Container();
      let cy = 38;
      const maxChars = 41;

      for (const item of info.items || []) {
        const isStatus = info.kind === 'statuses';
        const titleStr = isStatus ? `${item.name} ${item.value}${item.burst ? '（爆发）' : ''}` : item.name;
        const hTxt = new PIXI.Text({
          text: titleStr,
          style: { fontFamily: FONT_UI, fontSize: 12.5, fontWeight: '800', fill: item.color || INK.gold },
        });
        const dTxt = item.text ? new PIXI.Text({
          text: wrapCjkText(item.text, isStatus ? maxChars - 5 : maxChars),
          style: {
            fontFamily: FONT_UI, fontSize: 12, fill: INK.primary, lineHeight: 17.5,
            wordWrap: true, breakWords: true, wordWrapWidth: W - (isStatus ? 56 : 30),
          },
        }) : null;
        const rowH = Math.max(32, 24 + (dTxt ? dTxt.height + 8 : 6));
        const bgRow = new PIXI.Graphics();
        bgRow.roundRect(12, cy, W - 24, rowH, 7)
          .fill({ color: INK.paperSoft })
          .stroke({ width: 1.1, color: item.color || INK.line, alpha: 0.7 });
        if (isStatus) {
          drawStatusIcon(bgRow, item.name, 28, cy + 16, 9, item.color || INK.secondary);
          hTxt.position.set(44, cy + 5);
          if (dTxt) dTxt.position.set(44, cy + 23);
        } else {
          hTxt.position.set(20, cy + 5);
          if (dTxt) dTxt.position.set(20, cy + 23);
        }
        body.addChild(bgRow, hTxt);
        if (dTxt) body.addChild(dTxt);
        cy += rowH + 6;
      }

      const H = cy + 8;
      // Directly adjacent to the exact fighter wing that you hovered
      const tx = info.side === 2
        ? Math.max(16, this.layout.rightWingX - W - 12)
        : Math.min(w - W - 16, this.layout.arenaX + 4);
      const ty = Math.min(h - H - 16, Math.max(52, info.y || 80));

      const frame = new PIXI.Graphics();
      frame.eventMode = 'none';
      frame.roundRect(tx + 4, ty + 6, W, H, 12).fill({ color: INK.shadow, alpha: 0.34 });
      frame.roundRect(tx, ty, W, H, 12).fill({ color: INK.paper, alpha: 0.99 }).stroke({ width: 1.6, color: INK.line });
      const head = new PIXI.Text({
        text: info.title,
        style: { fontFamily: FONT_UI, fontSize: 13, fontWeight: '800', fill: INK.primary },
      });
      head.position.set(tx + 14, ty + 10);
      body.position.set(tx, ty);
      this.inspectLayer.addChild(frame, head, body);
    }
  }

  _renderToast() {
    clearContainer(this.toastLayer);
    const items = [];
    if (this.banner) items.push({ ...this.banner, y: 24, size: 13.5 });
    if (this.toast) items.push({ ...this.toast, y: this.layout.handY - this.layout.cardH / 2 - 58, size: 12.5 });
    for (const item of items) {
      const t = new PIXI.Text({
        text: item.text,
        style: { fontFamily: FONT_UI, fontSize: item.size, fontWeight: '800', fill: INK.primary },
      });
      const bw = t.width + 32;
      const bh = 28;
      const bx = this.w / 2 - bw / 2;
      const by = item.y - bh / 2;
      const bg = new PIXI.Graphics();
      bg.roundRect(bx + 2, by + 4, bw, bh, 14).fill({ color: INK.shadow, alpha: 0.26 });
      bg.roundRect(bx, by, bw, bh, 14).fill({ color: INK.paper, alpha: 0.98 }).stroke({ width: 1.8, color: item.color });
      t.anchor.set(0.5);
      t.position.set(this.w / 2, item.y);
      this.toastLayer.addChild(bg, t);
    }
  }

  _onPointerMove(e) {
    if (!this.dragState) return;
    const x = e.global.x;
    const y = e.global.y;
    if (Math.hypot(x - this.dragState.startX, y - this.dragState.startY) > 10) {
      this.dragState.moved = true;
    }
    this.dragState.x = x;
    this.dragState.y = y;
    const view = this.handCardViews.get(this.dragState.cardKey);
    if (view) {
      view.bodyEntry.targetX = x;
      view.bodyEntry.targetY = y;
    }
  }

  _onPointerUp(e) {
    if (!this.dragState) return;
    const d = this.dragState;
    this.dragState = null;
    const view = this.handCardViews.get(d.cardKey);
    if (view) {
      view.bodyEntry.dragging = false;
      view.bodyEntry.targetX = view.baseX;
      view.bodyEntry.targetY = view.baseY;
      view.bodyEntry.targetAngle = view.baseAngle;
      view.bodyEntry.targetScale = 1.0;
    }

    const x = e.global.x;
    const y = e.global.y;

    if (!d.moved && this.state.mode === 'placement') {
      if (this.selectedHandCardId === d.card.id) this._placeCard(d.card.id);
      else {
        this.selectedHandCardId = d.card.id;
        this._rebuildDynamicBoard();
      }
      return;
    }

    if (this.state.mode === 'placement') {
      const { arenaX, arenaW, arenaTop, arenaH } = this.layout;
      if (x >= arenaX - 24 && x <= arenaX + arenaW + 24 && y >= arenaTop - 24 && y <= arenaTop + arenaH + 24) {
        this._placeCard(d.card.id);
        return;
      }
    } else if (this.state.mode === 'pre_attack' || this.state.mode === 'intercept') {
      if (d.canIntercept) {
        const pending = new Set(this.state.pending_responses || []);
        for (const [num, r] of this.preRevealSlotRects.entries()) {
          if (pending.has(num) && x >= r.x - 12 && x <= r.x + r.w + 12 && y >= r.y - 12 && y <= r.y + r.h + 12) {
            this.audio.cardPlace();
            this._sendAction('intercept', { card_id: d.card.id, duel_number: num });
            return;
          }
        }
      }
      if (d.canAttack) {
        for (const [charId, r] of this.charRects.entries()) {
          if (r.side !== d.side && x >= r.x && x <= r.x + r.w && y >= r.y && y <= r.y + r.h) {
            this.audio.cardPlace();
            this._sendAction('attack', { card_id: d.card.id, target: { kind: 'character', id: charId } });
            return;
          }
        }
        const duels = this.state.frame.duels || [];
        for (let i = 1; i <= duels.length; i++) {
          const lane = this.regularLaneRects.get(i);
          if (lane && x >= lane.x - 8 && x <= lane.x + lane.w + 8 && y >= lane.y - 8 && y <= lane.y + lane.h + 8) {
            this.audio.cardPlace();
            this._sendAction('attack', { card_id: d.card.id, target: { kind: 'duel', number: i } });
            return;
          }
        }
      }
    }
  }

  _onWheel(e) {
    if (this.dossierModal) {
      this.dossierModal.scrollY = Math.max(0, Math.min(this.dossierModal.maxScroll, this.dossierModal.scrollY + e.deltaY * 0.65));
      this._rebuildOverlay();
      return;
    }
    if (this.codexModal) {
      this.codexModal.scrollY = Math.max(0, Math.min(this.codexModal.maxScroll, this.codexModal.scrollY + e.deltaY * 0.65));
      this._rebuildOverlay();
    }
  }

  _onKeyDown(e) {
    if (e.key === 'Escape') {
      if (this.dossierModal || this.rosterModal || this.codexModal || this.pileModal) {
        this.dossierModal = null;
        this.rosterModal = null;
        this.codexModal = null;
        this.pileModal = null;
        this.hoveredCard = null;
        this.hoveredInfo = null;
        this._renderInspection();
        this._rebuildOverlay();
      }
      return;
    }
    if (e.key === 'm' || e.key === 'M') {
      this.audio.toggleMute();
      this._rebuildCornerHud();
      return;
    }
    if (e.key === 'r' || e.key === 'R') {
      this.codexModal = this.codexModal ? null : { tab: 'rules', scrollY: 0, maxScroll: 0 };
      this._rebuildOverlay();
      return;
    }
    if ((e.key === ' ' || e.key === 'Enter') && !this.dossierModal && !this.rosterModal && !this.codexModal && !this.pileModal) {
      e.preventDefault();
      const mode = this.state?.mode;
      if (mode === 'handoff' || mode === 'special_handoff') {
        this._sendAction('ready', { side: this.state.active_side || (this.state.eligible_sides || [])[0] });
      } else if (mode === 'reveal' || mode === 'combat' || mode === 'turn_end' || mode === 'timing') {
        this._sendAction('next');
      }
    }
  }

  async _placeCard(cardId) {
    const side = this.state?.active_side;
    const nextNum = this._findFirstEmptyRegularDuel(side);
    const dest = this.regularSlotRects.get(`${nextNum}:${side}`);
    const view = this.handCardViews.get(`hand_${side}_${cardId}`);
    this.audio.cardPlace();
    if (dest && view) {
      this.three.triggerRipple(dest.cx, dest.cy, SIDE_THEME[side].accent);
      this.three.spawnCardFlipArc({
        fromX: view.bodyEntry.body.position.x,
        fromY: view.bodyEntry.body.position.y,
        toX: dest.cx,
        toY: dest.cy,
        width: 96,
        height: 132,
        title: view.card.name,
        cost: view.card.cost,
        accentHex: SIDE_THEME[side].accentHex,
        flipFromBack: false,
        duration: 0.42,
        peakZ: 115,
      });
    }
    this.selectedHandCardId = null;
    await this._sendAction('place', { card_id: cardId });
  }

  async _sendAction(action, payload = {}) {
    try {
      const next = await this.transport.send(action, payload);
      if (next) this.applyState(next);
    } catch (err) {
      this.audio.shieldErode();
      this.showToast(err.message || String(err), 0xcf4932, 2.4);
    }
  }

  update(dtSec) {
    this.time += dtSec;

    // 1. Camera shake decay
    if (this.shakeTime > 0) {
      this.shakeTime = Math.max(0, this.shakeTime - dtSec);
      const decay = this.shakeTime > 0 ? this.shakePower * (this.shakeTime / 0.32) : 0;
      this.worldRoot.position.set((Math.random() - 0.5) * decay, (Math.random() - 0.5) * decay);
    } else {
      this.worldRoot.position.set(0, 0);
    }

    // 2. Tick all Living Character Actors + Status Auras + Shield Domes + Combat Motions at 60fps!
    const decayRate = Math.pow(0.012, dtSec);
    for (const [charId, m] of this.actorMotion.entries()) {
      m.lunge *= decayRate;
      m.recoil *= decayRate;
      m.evade *= Math.pow(0.025, dtSec);
      m.hitFlash *= Math.pow(0.01, dtSec);
      m.healGlow *= Math.pow(0.04, dtSec);
      m.passiveFlare *= Math.pow(0.05, dtSec);
      if (m.lunge < 0.004) m.lunge = 0;
      if (m.recoil < 0.004) m.recoil = 0;
      if (m.evade < 0.004) m.evade = 0;
      if (m.hitFlash < 0.004) m.hitFlash = 0;
      if (m.healGlow < 0.004) m.healGlow = 0;
      if (m.passiveFlare < 0.004) m.passiveFlare = 0;
    }
    for (const [charId, node] of this.actorNodes.entries()) {
      if (node.actor && !node.actor.destroyed) {
        node.actor.tick(this.time, this._getMotion(charId), node.liveCh);
      }
    }

    // 3. Tick Expanded Passive Trigger Pulses!
    for (const [key, plate] of this.passivePlates.entries()) {
      if (!plate.glowG || plate.glowG.destroyed) continue;
      const rem = this.passivePulses.get(key) || 0;
      plate.glowG.clear();
      if (rem > 0) {
        const nextRem = Math.max(0, rem - dtSec);
        this.passivePulses.set(key, nextRem);
        const t = nextRem / 1.65;
        const pulse = 0.55 + Math.sin(this.time * 14) * 0.25;
        plate.glowG.roundRect(-2, -2, plate.w + 4, plate.h + 4, 10)
          .fill({ color: INK.goldBg, alpha: t * 0.28 })
          .stroke({ width: 2.6, color: INK.gold, alpha: Math.min(1, t * 1.4 * pulse) });
      }
    }

    // 4. Sync Matter.js hand cards & smooth in-place card expansion
    if (this._inspectAnim && !this._inspectAnim.node.destroyed) {
      this._inspectAnim.age += dtSec;
      const t = Math.min(1, this._inspectAnim.age / this._inspectAnim.duration);
      const ease = 1 - Math.pow(1 - t, 3);
      const s0 = this._inspectAnim.startScale ?? 0.72;
      this._inspectAnim.node.scale.set(s0 + (1 - s0) * ease);
      this._inspectAnim.node.alpha = 0.55 + 0.45 * ease;
      if (t >= 1) this._inspectAnim = null;
    }

    for (const view of this.handCardViews.values()) {
      const b = view.bodyEntry.body;
      view.container.position.set(b.position.x, b.position.y);
      view.container.rotation = b.angle;
      view.container.scale.set(view.bodyEntry.scale);
    }

    // 5. Render Matter.js tumbling Shield Wear / Shatter Shards
    const sg = this.shardGraphic;
    sg.clear();
    if (this.physics.shards.length) {
      for (const s of this.physics.shards) {
        const pts = [];
        for (const v of s.body.vertices) pts.push(v.x, v.y);
        const alpha = Math.max(0, 1 - s.age / s.life);
        sg.poly(pts)
          .fill({ color: s.eroded ? 0xb8afa0 : s.color, alpha: alpha * 0.85 })
          .stroke({ width: 1.2, color: s.eroded ? INK.secondary : INK.paper, alpha: alpha * 0.9 });
      }
    }

    // 6. Live Pre-Reveal elapsed timers
    if (this.preTimerTexts.length) {
      const nowMs = Date.now();
      for (const item of this.preTimerTexts) {
        if (!item.txt.destroyed) {
          item.txt.text = `${item.baseHeader} ${((nowMs - item.declaredAt) / 1000).toFixed(1)}s`;
        }
      }
    }

    // 7. Animated Aiming Arcs & Fighter-to-Card Tethers
    this.tetherLayer.clear();
    if (!this.state?.frame?.combat) {
      // Subtle luminous energy threads connecting each placed visible card back to its living fighter figure!
      for (const duel of this.state?.frame?.duels || []) {
        for (const sEntry of duel.sides || []) {
          const well = this.regularSlotRects.get(`${duel.number}:${sEntry.side}`);
          if (!well) continue;
          for (const card of sEntry.cards || []) {
            if (card.hidden || !card.character_id) continue;
            const fp = this._actorPos(card.character_id);
            const col = SIDE_THEME[sEntry.side]?.accent || INK.gold;
            const anchorX = sEntry.side === 1 ? well.x + 6 : well.x + well.w - 6;
            const ctrlX = (fp.x + anchorX) * 0.5;
            const ctrlY = (fp.y + well.cy) * 0.5 - 12;
            this.tetherLayer.moveTo(fp.x, fp.y)
              .quadraticCurveTo(ctrlX, ctrlY, anchorX, well.cy)
              .stroke({ width: 1.5, color: col, alpha: 0.24 });
          }
        }
      }
    }

    const preDuels = this.state?.frame?.pre_reveal?.duels || [];
    for (const slot of preDuels) {
      const from = this.preRevealSlotRects.get(slot.number);
      if (!from || slot.target?.kind === 'intercept') continue;
      let to = null;
      if (slot.target?.kind === 'duel') {
        to = this.regularSlotRects.get(`${slot.target.number}:${3 - slot.attacking_side}`);
      } else if (slot.target?.kind === 'character') {
        const enemy = this.state.frame.players.find((p) => p.side !== slot.attacking_side);
        const ch = enemy?.characters?.find((c) => c.name === slot.target.name);
        if (ch) {
          const p = this._actorPos(ch.id);
          to = { cx: p.x, cy: p.y };
        }
      }
      if (to) {
        const col = slot.ready ? 0x1c8a64 : 0xcf4932;
        this.tetherLayer.moveTo(from.cx, from.cy + from.h * 0.35)
          .quadraticCurveTo((from.cx + to.cx) / 2, Math.min(from.cy, to.cy) - 24, to.cx, to.cy)
          .stroke({ width: 2.4, color: col, alpha: 0.72 });
        this.tetherLayer.circle(to.cx, to.cy, 6).fill({ color: col, alpha: 0.92 });
      }
    }

    // Live drag aiming arc
    if (this.dragState && this.dragState.moved) {
      const { startX, startY, x, y, canAttack, canIntercept, side } = this.dragState;
      const pulse = 0.72 + Math.sin(this.time * 10) * 0.28;
      if (this.state?.mode === 'placement') {
        const nextNum = this._findFirstEmptyRegularDuel(side);
        const well = this.regularSlotRects.get(`${nextNum}:${side}`);
        if (well) {
          this.tetherLayer.roundRect(well.x - 3, well.y - 3, well.w + 6, well.h + 6, 12)
            .stroke({ width: 3, color: SIDE_THEME[side].accent, alpha: pulse });
        }
      } else if (canAttack || canIntercept) {
        this.tetherLayer.moveTo(startX, startY)
          .quadraticCurveTo((startX + x) / 2, Math.min(startY, y) - 52, x, y)
          .stroke({ width: 3, color: INK.gold, alpha: 0.9 });
        this.tetherLayer.circle(x, y, 9).stroke({ width: 2.2, color: INK.gold, alpha: 0.95 });
      }
    }

    // 8. Smooth zero-rebuild HP bar interpolation at 60fps
    for (const p of this.state?.frame?.players || []) {
      for (const ch of p.characters || []) {
        const cur = this.hpDisplay.get(ch.id);
        let nextVal = cur;
        if (cur !== undefined && Math.abs(cur - ch.hp) > 0.04) {
          nextVal = cur + (ch.hp - cur) * Math.min(1, dtSec * 8);
          this.hpDisplay.set(ch.id, nextVal);
        } else if (cur !== ch.hp) {
          nextVal = ch.hp;
          this.hpDisplay.set(ch.id, nextVal);
        } else {
          continue;
        }
        const hw = this.hpWidgets.get(ch.id);
        if (hw && !hw.hpBarG.destroyed && !hw.hpTxt.destroyed) {
          const ratio = Math.max(0, Math.min(1, nextVal / Math.max(1, hw.maxHp)));
          hw.hpBarG.clear();
          if (ratio > 0) {
            hw.hpBarG.roundRect(hw.infoX + 1, hw.hpY + 1, Math.max(7, (hw.barW - 2) * ratio), hw.barH - 2, 6)
              .fill({ color: ratio < 0.34 ? 0xd94524 : hw.accent });
          }
          hw.hpTxt.text = `${Math.round(nextVal)}/${hw.maxHp}`;
        }
      }
    }

    // 9. Kinetic Floating Numbers & Passive Callouts
    for (let i = this.floaters.length - 1; i >= 0; i--) {
      const f = this.floaters[i];
      f.age += dtSec;
      f.obj.x += f.vx * dtSec;
      f.obj.y += f.vy * dtSec;
      f.vy *= Math.pow(0.18, dtSec);
      f.obj.alpha = Math.max(0, 1 - Math.pow(f.age / f.life, 2));
      if (f.age >= f.life) {
        this.fxTextLayer.removeChild(f.obj);
        f.obj.destroy();
        this.floaters.splice(i, 1);
      }
    }

    let toastCleared = false;
    if (this.banner) {
      this.banner.age += dtSec;
      if (this.banner.age >= this.banner.duration) { this.banner = null; toastCleared = true; }
    }
    if (this.toast) {
      this.toast.age += dtSec;
      if (this.toast.age >= this.toast.duration) { this.toast = null; toastCleared = true; }
    }
    if (toastCleared) this._renderToast();

    // 10. Optional Auto-Pace during resolution
    if (this.autoPace && !this.transport.busy && !this.dossierModal && !this.rosterModal && !this.codexModal && !this.pileModal) {
      const m = this.state?.mode;
      if (m === 'combat' || m === 'reveal' || m === 'timing') {
        this.autoTimer -= dtSec;
        if (this.autoTimer <= 0) {
          this.autoTimer = m === 'combat' ? 1.25 : 0.85;
          this._sendAction('next');
        }
      }
    }
  }
}
