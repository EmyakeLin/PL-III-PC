/**
 * Bright, clean, pure-WebGL Game Director for 《光点计划 III》.
 * Commercial-grade information clarity:
 *  - Library of Ruina style cards: clean [Icon] [1~max] face + instant 376px 100% VERBATIM Card Panel on hover
 *  - Arknights style characters: bold HP, shields shown ONLY when > 0, click ANY character to pin full Character Dossier (all verbatim passives + statuses + skills!)
 *  - Limbus Company style statuses: crisp 26x26 custom vector icons + stack numerals, hover for 100% verbatim rule text
 *  - ZERO paraphrasing, ZERO "Lv.X", ZERO "无附加词条", ZERO flavor/annotation text
 *  - ZERO black, ZERO blue-purple, ZERO DOM controls
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
  buildCardBack,
  buildCardFront,
  buildVerbatimCardPanel,
} from './card_print.js';
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

    this.hpDisplay = new Map();
    this.floaters = [];
    this.banner = null;
    this.toast = null;
    this.shakeTime = 0;
    this.shakePower = 0;
    this.time = 0;
    this.autoPace = false;
    this.autoTimer = 0;

    // Inspection & interactive state
    this.hoveredCard = null;    // { card, side, ownerName, anchorX }
    this.hoveredInfo = null;    // { kind: 'status'|'passives', items, x, y }
    this.dragState = null;
    this.selectedHandCardId = null;

    // Modals / Pinned Sheets
    this.dossierModal = null;   // { charId, side, selectedSkillId, scrollY, maxScroll }
    this.rosterModal = null;
    this.codexModal = null;
    this.pileModal = null;
    this.drawSelected = new Set();

    this.layout = {};
    this.charRects = new Map();
    this.regularSlotRects = new Map();
    this.preRevealSlotRects = new Map();
    this.pileCenters = new Map();
    this.handCardViews = new Map();
    this.preTimerTexts = [];

    // Matter.js real dice collision callback -> exact contact audio + Three.js sparks + ripple
    this.physics.onClashImpact = ({ x, y, group }) => {
      const heavy = group.outcome !== 'draw';
      this.audio.clashImpact(heavy);
      this.three.spawnImpactBurst(x, y, group.winnerColor || 0xe89b32, heavy ? 34 : 20, heavy);
      this.physics.applyGentleImpulse(x, y, 280, heavy ? 0.036 : 0.02);
      if (heavy) this._triggerShake(7, 0.22);
    };

    this.worldRoot = new PIXI.Container();
    app.stage.addChild(this.worldRoot);

    this.zonesLayer = new PIXI.Container();
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
      this.zonesLayer,
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
    const pad = 18;
    const leftW = Math.round(Math.max(256, Math.min(296, w * 0.21)));
    const rightW = Math.round(Math.max(176, Math.min(206, w * 0.145)));
    const arenaX = pad + leftW + 22;
    const arenaW = Math.max(440, w - leftW - rightW - pad * 2 - 44);
    const cardW = 138;
    const cardH = 190;
    const handY = h - cardH / 2 - 20;
    const arenaTop = 56;
    const arenaBottom = handY - cardH / 2 - 18;
    const arenaH = Math.max(260, arenaBottom - arenaTop);

    this.layout = {
      w, h, pad, leftW, rightW,
      rightX: w - rightW - pad,
      arenaX, arenaW, arenaTop, arenaH,
      handY, cardW, cardH,
    };
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

    const phaseTint = PHASE_TINTS[nextState.frame?.phase] || 0xfaecc8;
    this.three.setPhaseTint(phaseTint);

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
        this.lastFxSeq = events[events.length - 1].seq;
        if (lastSpeed) this._playSpeedRollFx(lastSpeed, true);
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
      else if (ev.kind === 'dice_clash') delay += 260;
      else if (ev.kind === 'damage') delay += 180;
      else delay += 55;
    }
  }

  _triggerSingleFx(ev) {
    if (!this.state) return;
    if (ev.kind === 'speed_roll') {
      this._playSpeedRollFx(ev, false);
    } else if (ev.kind === 'draw') {
      this.audio.cardSlide();
      const dp = this.pileCenters.get(`${ev.side}:draw`);
      if (dp) this._spawnFloater(dp.x, dp.y - 34, `+${ev.count}`, SIDE_THEME[ev.side].accent);
    } else if (ev.kind === 'draw_bottom') {
      this.audio.cardPlace();
      const dp = this.pileCenters.get(`${ev.side}:draw`);
      if (dp) this._spawnFloater(dp.x, dp.y + 34, `置底 ${ev.count}`, INK.gold);
    } else if (ev.kind === 'cost_refill') {
      this.audio.coinClink(1.08);
    } else if (ev.kind === 'cost_pay') {
      if (ev.paid) {
        this.audio.coinClink(0.95);
        const r = this.charRects.get(ev.character_id);
        if (r && ev.cost > 0) this._spawnFloater(r.x + r.w - 28, r.y + 8, `-${ev.cost}费`, INK.gold);
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
        toY: to ? to.cy : this.h * 0.24,
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
                width: 108, height: 148, title: '', accentHex: SIDE_THEME[s].accentHex,
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
      const r = this.charRects.get(ev.target_id);
      if (r) this._spawnFloater(r.x + r.w * 0.6, r.y + 14, `+${ev.amount}`, 0x269463, 18);
    } else if (ev.kind === 'lose_hp') {
      this.audio.hitDamage();
      const r = this.charRects.get(ev.target_id);
      if (r) this._spawnFloater(r.x + r.w * 0.6, r.y + 14, `失去 ${ev.amount} 生命`, 0xc44569);
    } else if (ev.kind === 'breath_crit') {
      this.audio.clashImpact(true);
      const r = this.charRects.get(ev.character_id);
      if (r) {
        this._spawnFloater(r.x + r.w * 0.5, r.y - 6, '暴击', 0x1a8775, 17);
        this.three.spawnImpactBurst(r.x + r.w * 0.5, r.y + 16, 0x24967c, 22, true);
      }
    } else if (ev.kind === 'stagger_check') {
      const r = this.charRects.get(ev.target_id);
      if (r) {
        this._spawnFloater(r.x + r.w * 0.5, r.y + 4, ev.triggered ? '致命失衡' : '失衡 +2', ev.triggered ? 0xd4223a : 0xbf9119);
      }
    } else if (ev.kind === 'card_replace') {
      this.audio.cardFlip();
      const { arenaX, arenaW, arenaTop, arenaH, handY } = this.layout;
      this.three.spawnCardFlipArc({
        fromX: arenaX + arenaW * 0.5, fromY: arenaTop + arenaH * 0.5,
        toX: arenaX + arenaW * 0.5, toY: handY,
        title: '', accentHex: SIDE_THEME[ev.side]?.accentHex || '#1a8775',
        flipFromBack: false, duration: 0.44, peakZ: 120,
      });
    } else if (ev.kind === 'character_death') {
      this.audio.clashImpact(true);
      this._triggerShake(10, 0.4);
      const r = this.charRects.get(ev.character_id);
      if (r) {
        this.physics.spawnShieldShards(r.x + r.w / 2, r.y + r.h / 2, 0xcf4330, 16, true);
        this.three.spawnImpactBurst(r.x + r.w / 2, r.y + r.h / 2, 0xcf4330, 36, true);
      }
      this._showBanner(`${ev.name} 阵亡`, 0xcf4330, 2.0);
    } else if (ev.kind === 'turn_recycle') {
      this.audio.turnBell();
      for (const s of ev.sides || []) {
        const total = (s.used_count || 0) + (s.board_count || 0) + (s.discard_count || 0);
        const dp = this.pileCenters.get(`${s.side}:draw`);
        if (dp && total > 0) {
          this.three.spawnCardFlipArc({
            fromX: this.layout.arenaX + this.layout.arenaW / 2,
            fromY: this.layout.arenaTop + this.layout.arenaH / 2,
            toX: dp.x, toY: dp.y,
            width: 88, height: 120, title: '', accentHex: SIDE_THEME[s.side].accentHex,
            flipFromBack: false, duration: 0.5, peakZ: 88,
          });
        }
      }
    }
  }

  _playSpeedRollFx(ev, silent) {
    if (!silent) this.audio.diceRoll();
    const { arenaX, arenaW, arenaTop, arenaH } = this.layout;
    const cx = arenaX + arenaW * 0.5;
    const cy = arenaTop + arenaH * 0.46;
    let idx = 0;
    for (const s of ev.sides || []) {
      const sign = s.side === 1 ? -1 : 1;
      for (const r of s.rolls || []) {
        this.three.launchDie({
          sides: 4,
          dieType: 'speed',
          rolledValue: r.speed,
          subLabel: r.name.slice(0, 4),
          startX: cx + sign * 210,
          startY: cy + (s.side === 1 ? 80 : -80),
          targetX: cx + sign * (78 + (idx % 3) * 58),
          targetY: cy + (s.side === 1 ? 30 : -30),
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
    const { arenaX, arenaW, arenaTop, arenaH } = this.layout;
    const cx = arenaX + arenaW * 0.5;
    const cy = arenaTop + arenaH * 0.4;

    const p1 = (ev.sides || []).find((s) => s.side === 1);
    const p2 = (ev.sides || []).find((s) => s.side === 2);

    if (p1 && p2 && !p1.skipped && !p2.skipped) {
      const outcome = p1.result === 'win' ? 'left_win' : p2.result === 'win' ? 'right_win' : 'draw';
      const winDie = p1.result === 'win' ? p1 : p2.result === 'win' ? p2 : null;
      const winColor = winDie ? (DIE_STYLE[winDie.type]?.color || INK.gold) : INK.gold;
      const group = this.physics.createClashDicePair({ cx, cy, radius: 27, outcome, winnerColor: winColor });

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
          radius: 27,
          lifetime: 2.3,
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
          startX: cx + (isP1 ? -220 : 220),
          startY: cy,
          targetX: cx + (isP1 ? -76 : 76),
          targetY: cy,
          radius: 26,
          lifetime: 1.85,
        });
      }
    }
  }

  _playDamageFx(ev) {
    const r = this.charRects.get(ev.target_id);
    const tx = r ? r.x + r.w * 0.55 : this.w * 0.25;
    const ty = r ? r.y + r.h * 0.45 : this.h * 0.5;

    const absorbedTotal = (ev.absorbed?.normal || 0) + (ev.absorbed?.reinforced || 0) + (ev.absorbed?.concept || 0);
    const erodedNormal = ev.eroded?.normal || 0;
    const erodedReinf = ev.eroded?.reinforced || 0;

    if (absorbedTotal > 0) {
      this.audio.shieldBlock();
      const col = ev.absorbed.concept ? SHIELD_STYLE.concept.color
        : ev.absorbed.reinforced ? SHIELD_STYLE.reinforced.color : SHIELD_STYLE.normal.color;
      this.physics.spawnShieldShards(tx, ty - 12, col, Math.min(10, 4 + absorbedTotal * 2), false);
      this.three.spawnImpactBurst(tx, ty - 12, col, 16, false);
      this._spawnFloater(tx + 18, ty - 26, `护盾 -${absorbedTotal}`, col);
    }

    if (erodedNormal > 0 || erodedReinf > 0) {
      this.audio.shieldErode();
      if (erodedNormal > 0) {
        this.physics.spawnShieldShards(tx - 16, ty - 10, SHIELD_STYLE.normal.color, 9 + erodedNormal * 2, true);
        this._spawnFloater(tx - 20, ty - 42, `磨损 -${erodedNormal} 普通护盾`, INK.secondary);
      }
      if (erodedReinf > 0) {
        this.physics.spawnShieldShards(tx + 8, ty - 10, SHIELD_STYLE.reinforced.color, 9 + erodedReinf * 2, true);
        this._spawnFloater(tx + 12, ty - 42, `磨损 -${erodedReinf} 强化护盾`, INK.gold);
      }
    }

    if (ev.hp_lost > 0) {
      this.audio.hitDamage();
      this._triggerShake(Math.min(11, 5 + ev.hp_lost * 2), 0.26);
      this.three.spawnImpactBurst(tx, ty, 0xcf4330, 22, ev.hp_lost >= 3);
      const multTag = ev.multiplier > 1 ? ` ×${ev.multiplier}` : '';
      this._spawnFloater(tx, ty - 6, `-${ev.hp_lost} ${GRADE_LABEL[ev.grade] || ''}${multTag}`, 0xcf4330, 19);
    } else if (absorbedTotal === 0) {
      this._spawnFloater(tx, ty - 6, '0', INK.muted, 15);
    }
  }

  _triggerShake(power, duration) {
    this.shakePower = Math.max(this.shakePower, power);
    this.shakeTime = Math.max(this.shakeTime, duration);
  }

  _spawnFloater(x, y, text, color = INK.primary, fontSize = 15) {
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
    this.floaters.push({ obj: t, vx: (Math.random() - 0.5) * 24, vy: -52, age: 0, life: 1.4 });
  }

  _showBanner(text, color = INK.gold, duration = 1.6) {
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
    this._rebuildCharactersAndStacks();
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
    const pillW = metaTxt.width + 42;
    const pillG = new PIXI.Graphics();
    pillG.roundRect(pad + 2, 14, pillW, 30, 15).fill({ color: INK.shadow, alpha: 0.2 });
    pillG.roundRect(pad, 12, pillW, 30, 15)
      .fill({ color: INK.paper, alpha: 0.96 })
      .stroke({ width: 1.4, color: INK.line });
    drawLightStar(pillG, pad + 17, 27, 8, INK.gold, 0.95);
    metaTxt.anchor.set(0, 0.5);
    metaTxt.position.set(pad + 30, 27);
    this.cornerHudLayer.addChild(pillG, metaTxt);

    const tools = [
      {
        label: this.autoPace ? '自动·开' : '自动',
        w: 66,
        accent: this.autoPace ? 0x1c8a64 : INK.secondary,
        solid: this.autoPace,
        fn: () => { this.autoPace = !this.autoPace; this.autoTimer = 0.35; this._rebuildCornerHud(); },
      },
      {
        label: this.audio.muted ? '静音' : '音效',
        w: 56,
        accent: this.audio.muted ? INK.muted : INK.secondary,
        fn: () => { this.audio.toggleMute(); this._rebuildCornerHud(); },
      },
      {
        label: '规则',
        w: 56,
        accent: INK.gold,
        fn: () => { this.codexModal = { tab: 'rules', scrollY: 0, maxScroll: 0 }; this._rebuildOverlay(); },
      },
      {
        label: '选人',
        w: 56,
        accent: 0x1c8a64,
        fn: () => this._openRosterModal(),
      },
    ];
    let rx = w - pad;
    for (let i = tools.length - 1; i >= 0; i--) {
      const t = tools[i];
      rx -= t.w;
      const btn = makeSealButton(t.label, {
        width: t.w, height: 28, accent: t.accent, solid: !!t.solid, fontSize: 11.5, radius: 14, onClick: t.fn,
      });
      btn.position.set(rx, 13);
      this.cornerHudLayer.addChild(btn);
      rx -= 7;
    }
  }

  _rebuildCharactersAndStacks() {
    clearContainer(this.zonesLayer);
    this.charRects.clear();
    this.pileCenters.clear();

    const { pad, leftW, rightW, rightX, h } = this.layout;
    const frame = this.state.frame;

    const sideConfigs = [
      { side: 2, anchorTop: 56 },
      { side: 1, anchorBottom: h - 18 },
    ];

    for (const cfg of sideConfigs) {
      const player = frame.players.find((p) => p.side === cfg.side);
      if (!player) continue;
      const theme = SIDE_THEME[cfg.side];
      const chars = player.characters || [];
      const plateH = chars.length === 1 ? 132 : chars.length === 2 ? 114 : 94;
      const gap = 8;
      const stackH = 24 + chars.length * plateH + (chars.length - 1) * gap;
      const baseY = cfg.anchorTop !== undefined ? cfg.anchorTop : Math.max(h * 0.5 + 6, cfg.anchorBottom - stackH);

      const isFirst = frame.first_side === cfg.side;
      const tagTxt = new PIXI.Text({
        text: `${player.name}${isFirst ? ' ★先手' : ''} · 速${Number(player.speed || 0).toFixed(player.speed % 1 ? 1 : 0)} · 手牌 ${player.hand_count}`,
        style: { fontFamily: FONT_UI, fontSize: 11.5, fontWeight: '800', fill: theme.accent },
      });
      tagTxt.position.set(pad + 4, baseY + 2);
      this.zonesLayer.addChild(tagTxt);

      chars.forEach((ch, idx) => {
        const py = baseY + 22 + idx * (plateH + gap);
        const rect = { x: pad, y: py, w: leftW, h: plateH, side: cfg.side };
        this.charRects.set(ch.id, rect);
        this._drawCharacterUnit(ch, rect, cfg.side);
      });

      const rightY = cfg.side === 2 ? 56 : Math.max(h * 0.46, h - 296);
      this._drawRightZones(player, rightX, rightY, rightW);
    }
  }

  /**
   * Arknights + Limbus Company inspired Character Unit:
   *  - Bold clear HP bar & numeral
   *  - Shields ONLY displayed when > 0 (zero "普0 强0 概0" noise!)
   *  - Limbus-style 26x26 vector Status Icons with stack counts (hover for full verbatim text)
   *  - Click character plate anytime to pin full Verbatim Character Dossier (passives + statuses + skills!)
   */
  _drawCharacterUnit(ch, rect, side) {
    const { x, y, w, h } = rect;
    const theme = SIDE_THEME[side];
    const plate = new PIXI.Container();
    plate.position.set(x, y);

    const activeSide = this.state.active_side;
    const defaultTarget = activeSide && activeSide !== side && this.state.default_targets?.[String(activeSide)] === ch.id;
    const catChar = this._catalogChar(ch.id);
    const allPassives = [
      ...(catChar?.faction_passives || []).map((p) => ({ ...p, kind: '阵营被动' })),
      ...(catChar?.passives || []).map((p) => ({ ...p, kind: '角色被动' })),
    ];

    const bg = new PIXI.Graphics();
    bg.roundRect(2, 5, w, h, 12).fill({ color: INK.shadow, alpha: 0.24 });
    bg.roundRect(0, 0, w, h, 12)
      .fill({ color: ch.alive ? INK.paper : 0xede8de, alpha: ch.alive ? 0.98 : 0.78 })
      .stroke({ width: defaultTarget ? 2.2 : 1.5, color: ch.alive ? theme.border : INK.line });
    bg.roundRect(0, 0, 6, h, 3).fill({ color: ch.alive ? theme.accent : INK.muted });
    plate.addChild(bg);

    // Click entire character plate -> open Pinned Character Dossier (passives + statuses + skills!)
    plate.eventMode = 'static';
    plate.cursor = 'pointer';
    plate.on('pointertap', (e) => {
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

    // Row 1: Character Name + Duel Quota Pips + Speed + Personal Cost
    const nameTxt = new PIXI.Text({
      text: `${ch.name}${ch.alive ? '' : ' [阵亡]'}`,
      style: { fontFamily: FONT_UI, fontSize: 15.5, fontWeight: '800', fill: ch.alive ? INK.primary : INK.muted },
    });
    nameTxt.position.set(14, 8);
    plate.addChild(nameTxt);

    // Personal Cost pebble
    const pCost = ch.cost?.available ?? 0;
    bg.circle(w - 20, 18, 10)
      .fill({ color: pCost > 0 ? INK.gold : INK.paperTint })
      .stroke({ width: 1.4, color: pCost > 0 ? 0xa86b0d : INK.line });
    const pcTxt = new PIXI.Text({
      text: String(pCost),
      style: { fontFamily: FONT_NUM, fontSize: 11.5, fontWeight: '800', fill: pCost > 0 ? INK.paper : INK.muted },
    });
    pcTxt.anchor.set(0.5);
    pcTxt.position.set(w - 20, 18);
    plate.addChild(pcTxt);

    // Speed chip
    bg.roundRect(w - 72, 9, 36, 18, 6).fill({ color: INK.paperSoft }).stroke({ width: 1, color: INK.line });
    const spTxt = new PIXI.Text({
      text: `速${ch.speed ?? 0}`,
      style: { fontFamily: FONT_NUM, fontSize: 10.5, fontWeight: '800', fill: INK.secondary },
    });
    spTxt.anchor.set(0.5);
    spTxt.position.set(w - 54, 18);
    plate.addChild(spTxt);

    // Duel Quota Pips
    const maxD = ch.duels?.max ?? 1;
    const usedD = ch.duels?.used;
    const pipRight = w - 80;
    for (let i = 0; i < maxD; i++) {
      const px = pipRight - (maxD - 1 - i) * 11;
      const used = usedD !== null && i < usedD;
      bg.circle(px, 18, 3.8)
        .fill({ color: usedD === null ? INK.line : used ? INK.paperTint : theme.accent })
        .stroke({ width: 1.2, color: usedD === null ? INK.muted : theme.accent });
    }

    // Row 2: Arknights-style Bold HP Bar + Clear Numeral + Active Shields ONLY if > 0
    const hpY = 34;
    const barW = w - 76;
    const barH = 14;
    const displayHp = this.hpDisplay.get(ch.id) ?? ch.hp;
    const ratio = Math.max(0, Math.min(1, displayHp / Math.max(1, ch.max_hp)));

    bg.roundRect(14, hpY, barW, barH, 7).fill({ color: INK.paperTint }).stroke({ width: 1, color: INK.line });
    if (ratio > 0) {
      bg.roundRect(15, hpY + 1, Math.max(7, (barW - 2) * ratio), barH - 2, 6)
        .fill({ color: ratio < 0.34 ? 0xd94524 : theme.accent });
    }
    const hpTxt = new PIXI.Text({
      text: `${Math.round(displayHp)}/${ch.max_hp}`,
      style: { fontFamily: FONT_NUM, fontSize: 14, fontWeight: '900', fill: INK.primary },
    });
    hpTxt.anchor.set(1, 0.5);
    hpTxt.position.set(w - 10, hpY + barH / 2);
    plate.addChild(hpTxt);

    // Row 3: Active Shields (ONLY if > 0) + Limbus-Company-style Status Icons!
    const row3Y = 56;
    let cx = 14;

    const shields = ch.shields || {};
    for (const kind of ['normal', 'reinforced', 'concept']) {
      const val = shields[kind] || 0;
      if (val <= 0) continue;
      const st = SHIELD_STYLE[kind];
      bg.roundRect(cx, row3Y, 44, 26, 6).fill({ color: st.bg }).stroke({ width: 1.4, color: st.color });
      drawShieldGlyph(bg, kind, cx + 12, row3Y + 13, 7);
      const stNum = new PIXI.Text({
        text: String(val),
        style: { fontFamily: FONT_NUM, fontSize: 13, fontWeight: '900', fill: st.color },
      });
      stNum.anchor.set(0, 0.5);
      stNum.position.set(cx + 23, row3Y + 13);
      plate.addChild(stNum);
      cx += 49;
    }

    // Limbus-style 26x26 Status Icons + crisp corner stack count
    const statuses = Object.entries(ch.statuses || {});
    for (const [name, val] of statuses) {
      if (cx + 28 > w - 10) break;
      const col = STATUS_COLORS[name] || INK.secondary;
      const burst = name === '裂血' && ch.bleed_burst;
      const iconBox = new PIXI.Container();
      iconBox.position.set(cx, row3Y);
      const ig = new PIXI.Graphics();
      ig.roundRect(0, 0, 26, 26, 6)
        .fill({ color: burst ? 0xfce0e4 : INK.paperSoft })
        .stroke({ width: burst ? 2 : 1.4, color: col });
      drawStatusIcon(ig, name, 13, 12, 8.5, col);
      // Stack number corner badge
      ig.roundRect(13, 14, 15, 13, 4).fill({ color: col });
      iconBox.addChild(ig);

      const valTxt = new PIXI.Text({
        text: String(val),
        style: { fontFamily: FONT_NUM, fontSize: 10, fontWeight: '900', fill: INK.paper },
      });
      valTxt.anchor.set(0.5);
      valTxt.position.set(20.5, 20.5);
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
          x: x + w + 12,
          y: y + 8,
        };
        this._renderInspection();
      });
      iconBox.on('pointerout', () => {
        this.hoveredInfo = null;
        this._renderInspection();
      });
      plate.addChild(iconBox);
      cx += 31;
    }

    // Bottom clean strip: Passive hover trigger + Dossier affordance (NO truncated 3-char pills!)
    if (h >= 106) {
      const footY = h - 26;
      if (allPassives.length) {
        const pBtn = new PIXI.Container();
        pBtn.position.set(14, footY);
        const pg = new PIXI.Graphics();
        const label = `被动 (${allPassives.length})`;
        const pw = 66;
        pg.roundRect(0, 0, pw, 20, 5).fill({ color: INK.goldBg }).stroke({ width: 1, color: INK.gold, alpha: 0.7 });
        pBtn.addChild(pg);
        const pt = new PIXI.Text({
          text: label,
          style: { fontFamily: FONT_UI, fontSize: 10.5, fontWeight: '800', fill: 0x99620d },
        });
        pt.anchor.set(0.5);
        pt.position.set(pw / 2, 10);
        pBtn.addChild(pt);
        pBtn.eventMode = 'static';
        pBtn.cursor = 'help';
        pBtn.on('pointerover', () => {
          this.hoveredInfo = {
            kind: 'passives',
            title: `${ch.name} · 被动技能`,
            items: allPassives.map((p) => ({
              name: p.name || p.kind,
              color: INK.gold,
              text: (p.entries || []).join('\n') || p.description || '',
            })),
            x: x + w + 12,
            y: y + 8,
          };
          this._renderInspection();
        });
        pBtn.on('pointerout', () => {
          this.hoveredInfo = null;
          this._renderInspection();
        });
        plate.addChild(pBtn);
      }

      const detailHint = new PIXI.Text({
        text: defaultTarget ? '◎ 集火 · 档案' : '档案 ›',
        style: { fontFamily: FONT_UI, fontSize: 10.5, fontWeight: '700', fill: defaultTarget ? INK.gold : INK.muted },
      });
      detailHint.anchor.set(1, 0.5);
      detailHint.position.set(w - 12, footY + 10);
      plate.addChild(detailHint);
    }

    this.zonesLayer.addChild(plate);
  }

  _drawRightZones(player, x, y, w) {
    const side = player.side;
    const theme = SIDE_THEME[side];

    const avail = player.cost?.available ?? 0;
    const spent = player.cost?.spent ?? 0;
    const total = Math.min(8, Math.max(avail + spent, player.cost?.refill || 5));

    const lbl = new PIXI.Text({
      text: `${player.name} 通用费 ${avail}`,
      style: { fontFamily: FONT_UI, fontSize: 11.5, fontWeight: '800', fill: INK.secondary },
    });
    lbl.position.set(x, y);
    this.zonesLayer.addChild(lbl);

    const gemG = new PIXI.Graphics();
    for (let i = 0; i < total; i++) {
      const isAvail = i < avail;
      const gx = x + 10 + i * 21;
      const gy = y + 27;
      gemG.circle(gx + 1, gy + 2, 8).fill({ color: INK.shadow, alpha: 0.24 });
      gemG.circle(gx, gy, 8)
        .fill({ color: isAvail ? INK.gold : INK.paperSoft })
        .stroke({ width: 1.5, color: isAvail ? 0xa3680c : INK.line });
      if (isAvail) gemG.circle(gx - 2.2, gy - 2.2, 2.4).fill({ color: INK.paper, alpha: 0.7 });
    }
    this.zonesLayer.addChild(gemG);

    const stackY = y + 48;
    const stacks = [
      { key: 'draw', label: '牌堆', count: player.draw_count, cards: null, col: theme.accent, bg: theme.softBg },
      { key: 'delayed_discard', label: '弃牌', count: player.delayed_discard_count, cards: player.delayed_discard, col: 0xcc7b14, bg: 0xfef4df },
      { key: 'out_of_combat', label: '战外', count: player.out_of_combat_count, cards: player.out_of_combat, col: INK.muted, bg: INK.paperSoft },
    ];
    const cardW = 50;
    const cardH = 68;
    const gap = 12;

    stacks.forEach((st, idx) => {
      const sx = x + idx * (cardW + gap);
      this.pileCenters.set(`${side}:${st.key}`, { x: sx + cardW / 2, y: stackY + cardH / 2 });
      const box = new PIXI.Container();
      box.position.set(sx, stackY);
      const g = new PIXI.Graphics();

      if (st.count === 0) {
        g.roundRect(0, 0, cardW, cardH, 7).fill({ color: INK.paperSoft, alpha: 0.5 }).stroke({ width: 1.2, color: INK.line });
      } else {
        const layers = Math.min(6, st.count);
        for (let l = layers; l >= 1; l--) {
          g.roundRect(l * 1.4, -l * 1.6, cardW, cardH, 7).fill({ color: INK.paper }).stroke({ width: 1, color: st.col, alpha: 0.45 });
        }
        g.roundRect(0, 0, cardW, cardH, 7).fill({ color: st.bg }).stroke({ width: 1.6, color: st.col });
        if (st.key === 'draw') drawLightStar(g, cardW / 2, cardH / 2 - 6, 11, st.col, 0.55);
      }
      box.addChild(g);

      const num = new PIXI.Text({
        text: String(st.count),
        style: { fontFamily: FONT_NUM, fontSize: 16, fontWeight: '900', fill: st.count > 0 ? st.col : INK.muted },
      });
      num.anchor.set(0.5);
      num.position.set(cardW / 2, st.key === 'draw' && st.count > 0 ? cardH - 16 : cardH / 2 - 4);
      const cap = new PIXI.Text({
        text: st.label,
        style: { fontFamily: FONT_UI, fontSize: 10, fontWeight: '700', fill: INK.secondary },
      });
      cap.anchor.set(0.5, 0);
      cap.position.set(cardW / 2, cardH + 5);
      box.addChild(num, cap);

      if (st.cards !== null) {
        box.eventMode = 'static';
        box.cursor = 'pointer';
        box.on('pointertap', (e) => {
          e.stopPropagation();
          this.pileModal = { title: `${player.name} · ${st.label}`, side, cards: st.cards };
          this._rebuildOverlay();
        });
      }
      this.zonesLayer.addChild(box);
    });
  }

  _rebuildDynamicBoard() {
    clearContainer(this.boardLayer);
    clearContainer(this.clashLayer);
    clearContainer(this.controlsLayer);
    this.regularSlotRects.clear();
    this.preRevealSlotRects.clear();
    this.preTimerTexts = [];

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

    // 1. Pre-Reveal / Instant Lane (only shown when active)
    if (showPreLane) {
      const preH = Math.round(arenaH * 0.34);
      regTop = arenaTop + preH + 14;
      regH = arenaH - preH - 14;

      const pendingNumbers = new Set(this.state.pending_responses || []);
      const laneG = new PIXI.Graphics();
      laneG.roundRect(arenaX, arenaTop, arenaW, preH, 12)
        .fill({ color: 0xfbf5e8, alpha: 0.78 })
        .stroke({ width: 1.4, color: INK.gold, alpha: 0.55 });
      this.boardLayer.addChild(laneG);

      if (!allTopDuels.length) {
        const cue = new PIXI.Text({
          text: '开牌前交锋',
          style: { fontFamily: FONT_UI, fontSize: 12, fontWeight: '800', fill: INK.gold },
        });
        cue.anchor.set(0.5);
        cue.position.set(arenaX + arenaW / 2, arenaTop + preH / 2);
        this.boardLayer.addChild(cue);
      } else {
        const count = allTopDuels.length;
        const slotW = Math.min(210, Math.floor((arenaW - 24 - (count - 1) * 10) / count));
        const slotH = preH - 18;
        const totalW = count * slotW + (count - 1) * 10;
        const startX = arenaX + (arenaW - totalW) / 2;

        allTopDuels.forEach((slot, idx) => {
          const sx = startX + idx * (slotW + 10);
          const sy = arenaTop + 9;
          const isPendingForMe = slot._kind === 'pre_reveal' && !slot.ready && pendingNumbers.has(slot.number);
          const isCombatHere = frame.combat && frame.combat.kind === slot._kind && frame.combat.duel_number === slot.number;
          if (slot._kind === 'pre_reveal') {
            this.preRevealSlotRects.set(slot.number, { x: sx, y: sy, w: slotW, h: slotH, cx: sx + slotW / 2, cy: sy + slotH / 2 });
          }

          const sg = new PIXI.Graphics();
          sg.roundRect(sx + 2, sy + 4, slotW, slotH, 10).fill({ color: INK.shadow, alpha: 0.22 });
          sg.roundRect(sx, sy, slotW, slotH, 10)
            .fill({ color: isCombatHere ? INK.goldBg : INK.paper })
            .stroke({
              width: isCombatHere || isPendingForMe ? 2.2 : 1.3,
              color: isCombatHere ? INK.gold : isPendingForMe ? 0xcf4932 : slot.ready ? 0x1c8a64 : INK.line,
            });
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
          head.position.set(sx + 8, sy + 6);
          this.boardLayer.addChild(head);
          if (timingRec?.declared_at_ms && !timingRec.answered_at_ms) {
            this.preTimerTexts.push({ txt: head, baseHeader, declaredAt: timingRec.declared_at_ms });
          }

          const sub = new PIXI.Text({
            text: targetTxt,
            style: { fontFamily: FONT_UI, fontSize: 10, fontWeight: '700', fill: INK.secondary },
          });
          sub.position.set(sx + 8, sy + 21);
          this.boardLayer.addChild(sub);

          const cards = [];
          for (const sEntry of slot.sides || []) {
            for (const c of sEntry.cards || []) cards.push({ card: c, side: sEntry.side });
          }
          cards.forEach(({ card, side }, cIdx) => {
            const miniW = Math.min(86, (slotW - 18) / Math.max(1, cards.length) - 4);
            const scale = Math.min(miniW / 138, (slotH - 42) / 190);
            const cxCard = sx + 10 + (138 * scale) / 2 + cIdx * (138 * scale + 6);
            const spr = buildCardFront(card, {
              side, ownerName: charNames[card.character_id] || '', showOwner: multiChar,
              width: 138, height: 190, legal: true, playMode: card.play_mode,
            });
            spr.scale.set(scale);
            spr.position.set(cxCard, sy + 38 + (190 * scale) / 2);
            spr.eventMode = 'static';
            spr.cursor = 'pointer';
            spr.on('pointerover', () => {
              this.hoveredCard = { card, side, ownerName: charNames[card.character_id] || '', anchorX: cxCard };
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
              width: 54, height: 24, accent: 0xcf4932, solid: true, fontSize: 11, radius: 6,
              onClick: () => this._sendAction('let_through', { duel_number: slot.number }),
            });
            passBtn.position.set(sx + slotW - 60, sy + slotH - 30);
            this.boardLayer.addChild(passBtn);
          }
        });
      }
    }

    // 2. Center Regular Duel Lanes (① ② ③ ④)
    const duels = frame.duels || [];
    const activeSide = this.state.active_side;
    const nextEmptyNum = this._findFirstEmptyRegularDuel(activeSide);
    const slotCount = Math.max(3, duels.length + (this.state.mode === 'placement' && nextEmptyNum > duels.length ? 1 : 0));
    const slotGap = 20;
    const slotW = Math.min(176, Math.floor((arenaW - (slotCount - 1) * slotGap) / slotCount));
    const totalRegW = slotCount * slotW + (slotCount - 1) * slotGap;
    const startRegX = arenaX + (arenaW - totalRegW) / 2;

    for (let i = 0; i < slotCount; i++) {
      const number = i + 1;
      const sx = startRegX + i * (slotW + slotGap);
      const sy = regTop + 6;
      const sh = regH - 12;
      const midY = sy + sh / 2;
      const slotData = duels[i] || { number, sides: [{ side: 1, cards: [] }, { side: 2, cards: [] }] };
      const isCombatHere = frame.combat && frame.combat.kind === 'regular' && frame.combat.duel_number === number;
      const isNextDropSlot = this.state.mode === 'placement' && number === nextEmptyNum;

      const laneG = new PIXI.Graphics();
      laneG.moveTo(sx + 10, midY).lineTo(sx + slotW - 10, midY)
        .stroke({ width: 1.2, color: isCombatHere ? INK.gold : INK.line });
      laneG.circle(sx + slotW / 2, midY, 13)
        .fill({ color: isCombatHere ? INK.gold : INK.paper })
        .stroke({ width: 1.5, color: isCombatHere ? INK.gold : INK.line });
      this.boardLayer.addChild(laneG);

      const numTxt = new PIXI.Text({
        text: CIRCLED[i] || String(number),
        style: { fontFamily: FONT_UI, fontSize: 13.5, fontWeight: '800', fill: isCombatHere ? INK.paper : INK.secondary },
      });
      numTxt.anchor.set(0.5);
      numTxt.position.set(sx + slotW / 2, midY);
      this.boardLayer.addChild(numTxt);

      for (const s of [2, 1]) {
        const halfY = s === 2 ? sy : midY + 18;
        const halfH = sh / 2 - 18;
        const wellRect = { x: sx + 4, y: halfY, w: slotW - 8, h: halfH, cx: sx + slotW / 2, cy: halfY + halfH / 2 };
        this.regularSlotRects.set(`${number}:${s}`, wellRect);

        const isTargetWell = isNextDropSlot && s === activeSide;
        const wellG = new PIXI.Graphics();
        wellG.roundRect(wellRect.x, wellRect.y, wellRect.w, wellRect.h, 12)
          .fill({ color: isTargetWell ? SIDE_THEME[s].warmTint : INK.paperSoft, alpha: isTargetWell ? 0.92 : 0.56 })
          .stroke({
            width: isTargetWell ? 2 : 1.1,
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
          const fitScale = Math.min((wellRect.w - 8) / 138, (wellRect.h - 6) / 190, 0.94);
          const ox = (cIdx - (cards.length - 1) / 2) * 18;
          const isFaceDown = card.hidden || (!frame.cards_revealed && card.state === 'placed_face_down');
          const combatSide = isCombatHere
            ? (frame.combat.sides || []).find((cs) => cs.side === s && cs.card_id === card.id) : null;
          const spr = isFaceDown
            ? buildCardBack(s, { width: 138, height: 190 })
            : buildCardFront(card, {
                side: s,
                ownerName: charNames[card.character_id] || '',
                showOwner: multiChar,
                width: 138, height: 190,
                legal: true,
                activeDieNumber: combatSide?.die_number || null,
                rangeDeficit: combatSide?.range_deficit || 0,
              });
          spr.scale.set(fitScale);
          spr.position.set(wellRect.cx + ox, wellRect.cy);
          if (!card.hidden) {
            spr.eventMode = 'static';
            spr.cursor = 'pointer';
            spr.on('pointerover', () => {
              this.hoveredCard = { card, side: s, ownerName: charNames[card.character_id] || '', anchorX: wellRect.cx };
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

    this._rebuildClashHud();
    this._rebuildHandFan();
    this._rebuildActionControls();
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

  _rebuildClashHud() {
    clearContainer(this.clashLayer);
    const combat = this.state?.frame?.combat;
    if (!combat) return;

    const { arenaX, arenaW, arenaTop, arenaH } = this.layout;
    const barW = Math.min(580, arenaW - 12);
    const barH = 90;
    const bx = arenaX + (arenaW - barW) / 2;
    const by = arenaTop + arenaH - barH - 4;

    const g = new PIXI.Graphics();
    g.roundRect(bx + 3, by + 5, barW, barH, 12).fill({ color: INK.shadow, alpha: 0.3 });
    g.roundRect(bx, by, barW, barH, 12).fill({ color: INK.paper, alpha: 0.97 }).stroke({ width: 1.8, color: INK.gold });
    this.clashLayer.addChild(g);

    const kindName = { pre_reveal: '开牌前', regular: '常规', instant: '即时' }[combat.kind] || '交锋';
    const title = new PIXI.Text({
      text: `${kindName}${CIRCLED[(combat.duel_number || 1) - 1] || combat.duel_number} · 第 ${combat.round_id || 1} 轮`,
      style: { fontFamily: FONT_UI, fontSize: 11, fontWeight: '800', fill: INK.gold },
    });
    title.anchor.set(0.5, 0);
    title.position.set(bx + barW / 2, by + 6);
    this.clashLayer.addChild(title);

    for (const s of combat.sides || []) {
      const isLeft = s.side === 1;
      const sx = isLeft ? bx + 12 : bx + barW / 2 + 16;
      const sw = barW / 2 - 28;
      const die = s.die;
      const theme = SIDE_THEME[s.side];
      if (!die) {
        const empty = new PIXI.Text({
          text: `${theme.name} · 无对位`,
          style: { fontFamily: FONT_UI, fontSize: 12, fill: INK.muted },
        });
        empty.position.set(sx, by + 42);
        this.clashLayer.addChild(empty);
        continue;
      }
      const ds = DIE_STYLE[die.type] || DIE_STYLE.blank;
      const rg = new PIXI.Graphics();
      rg.roundRect(sx, by + 23, sw, 58, 8)
        .fill({ color: ds.bg })
        .stroke({ width: die.result === 'win' ? 2.2 : 1.2, color: die.result === 'win' ? INK.gold : ds.color });
      drawDieIcon(rg, die.type, sx + 18, by + 43, 8.5, ds.color);
      this.clashLayer.addChild(rg);

      // Exact live range (NO Lv.X!)
      const rangeStr = formatDieRange(die);
      const resLabel = die.result === 'win'
        ? (die.win_branch_skipped ? '胜（跳过拼赢）' : '胜')
        : die.result === 'lose' ? '负' : die.result === 'draw' ? '平' : '';
      const head = new PIXI.Text({
        text: `${theme.name} · ${ds.label} ${rangeStr}${s.range_deficit ? ` [压制${s.range_deficit}]` : ''}`,
        style: { fontFamily: FONT_UI, fontSize: 11.5, fontWeight: '800', fill: INK.primary },
      });
      head.position.set(sx + 32, by + 29);
      this.clashLayer.addChild(head);

      const sub = new PIXI.Text({
        text: `基础${die.base_value ?? 0}  变动${die.rolled_value ?? '—'}  最终${die.final_score ?? '—'}${resLabel ? '  ' + resLabel : ''}`,
        style: { fontFamily: FONT_UI, fontSize: 10.5, fontWeight: '600', fill: INK.secondary },
      });
      sub.position.set(sx + 32, by + 53);
      this.clashLayer.addChild(sub);

      const score = new PIXI.Text({
        text: die.clash_score !== null && die.clash_score !== undefined ? String(die.clash_score) : '—',
        style: {
          fontFamily: FONT_NUM, fontSize: 27, fontWeight: '900',
          fill: die.result === 'win' ? ds.color : die.result === 'lose' ? INK.muted : INK.primary,
        },
      });
      score.anchor.set(1, 0.5);
      score.position.set(sx + sw - 10, by + 52);
      this.clashLayer.addChild(score);
    }

    const vs = new PIXI.Text({
      text: 'VS',
      style: { fontFamily: FONT_NUM, fontSize: 13, fontWeight: '900', fill: INK.gold },
    });
    vs.anchor.set(0.5);
    vs.position.set(bx + barW / 2, by + 52);
    this.clashLayer.addChild(vs);
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
    const maxSpread = Math.min(arenaW - cardW - 18, Math.max(220, count * 126));
    const step = count > 1 ? Math.min(144, maxSpread / (count - 1)) : 0;
    const deckOrigin = this.pileCenters.get(`${viewerSide}:draw`) || { x: cx + 260, y: handY };
    const validKeys = new Set();

    hand.forEach((card, i) => {
      const cardKey = `hand_${viewerSide}_${card.id}`;
      validKeys.add(cardKey);
      const norm = count > 1 ? (i / (count - 1)) * 2 - 1 : 0;
      const baseX = cx + (i - (count - 1) / 2) * step;
      const baseY = handY + norm * norm * 10 - 6;
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
        this.hoveredCard = { card, side: viewerSide, ownerName: charNames[card.character_id] || '', anchorX: baseX };
        bodyEntry.targetY = baseY - 30;
        bodyEntry.targetAngle = 0;
        bodyEntry.targetScale = 1.08;
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

  _rebuildActionControls() {
    clearContainer(this.controlsLayer);
    const { rightX, rightW, h } = this.layout;
    const mode = this.state.mode;
    const buttons = [];

    if (mode === 'placement') {
      if (this.selectedHandCardId) {
        buttons.push({ label: '扣置', accent: 0x1c8a64, solid: true, fn: () => this._placeCard(this.selectedHandCardId) });
      }
      if (this.state.can_pass) {
        buttons.push({ label: '交权', accent: INK.gold, fn: () => this._sendAction('pass') });
      }
      buttons.push({
        label: `结束置卡（余${this.state.window_remaining}）`,
        accent: 0xcf4932,
        fn: () => this._sendAction('end'),
      });
    } else if (mode === 'pre_attack' || mode === 'intercept') {
      if (this.state.can_end_attack) {
        buttons.push({ label: '结束主动进攻', accent: INK.gold, solid: true, fn: () => this._sendAction('end_attack') });
      }
      if ((this.state.eligible_sides || []).length > 1) {
        buttons.push({ label: '切换席位', accent: 0x1a8775, fn: () => this._sendAction('switch_side') });
      }
    } else if (mode === 'reveal' || mode === 'combat' || mode === 'turn_end' || mode === 'timing') {
      const labelMap = {
        reveal: '常规交锋',
        combat: '下一拍',
        timing: '继续',
        turn_end: '下回合',
      };
      buttons.push({ label: labelMap[mode], accent: 0x1c8a64, solid: true, fn: () => this._sendAction('next') });
    }

    if (this.state.special_available && mode !== 'finished' && mode !== 'draw_select' && mode !== 'special' && mode !== 'special_handoff') {
      buttons.push({ label: '特殊行动', accent: 0x1a8775, solid: true, fn: () => this._sendAction('open_special') });
    }

    const btnW = rightW;
    const btnH = 38;
    let by = h - 22 - btnH;
    for (let i = buttons.length - 1; i >= 0; i--) {
      const b = buttons[i];
      const btn = makeSealButton(b.label, {
        width: btnW, height: btnH, accent: b.accent, solid: !!b.solid, fontSize: 13, radius: 10, onClick: b.fn,
      });
      btn.position.set(rightX, by);
      this.controlsLayer.addChild(btn);
      by -= btnH + 8;
    }
  }

  _rebuildOverlay() {
    clearContainer(this.overlayLayer);
    if (!this.state) return;
    const { w, h } = this.layout;

    // Pinned Character Dossier (Arknights / Library of Ruina style)
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
        onHoverCard: (card, side, ownerName) => {
          this.hoveredCard = card ? { card, side, ownerName, anchorX: w * 0.4 } : null;
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
        onHoverCard: (card, side, ownerName) => {
          this.hoveredCard = card ? { card, side, ownerName, anchorX: w * 0.4 } : null;
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
   * Renders the wide 100% Verbatim Card Panel OR the Verbatim Status/Passive List cleanly on screen.
   */
  _renderInspection() {
    clearContainer(this.inspectLayer);
    if (this.state?.mode === 'handoff' || this.state?.mode === 'special_handoff') return;

    const { w, h, pad, leftW } = this.layout;

    if (this.hoveredCard) {
      const { card, side, ownerName, anchorX } = this.hoveredCard;
      const panel = buildVerbatimCardPanel(card, { side, ownerName, width: 376 });
      // Smart side placement so panel never hides the card you're reading
      const placeLeft = anchorX > w * 0.56;
      const px = placeLeft ? Math.max(pad + leftW + 14, 24) : Math.min(w - panel._boxWidth - 18, w - 394);
      const py = Math.max(52, Math.min(h - panel._boxHeight - 18, (h - panel._boxHeight) / 2));
      panel.position.set(px, py);
      this.inspectLayer.addChild(panel);
    }

    if (this.hoveredInfo) {
      const info = this.hoveredInfo;
      const W = 356;
      const body = new PIXI.Container();
      let cy = 38;
      const maxChars = 42;

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
      const tx = Math.min(w - W - 16, Math.max(pad + leftW + 10, info.x));
      const ty = Math.min(h - H - 16, Math.max(52, info.y));

      const frame = new PIXI.Graphics();
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
    if (this.banner) items.push({ ...this.banner, y: 27, size: 13.5 });
    if (this.toast) items.push({ ...this.toast, y: this.layout.handY - this.layout.cardH / 2 - 26, size: 12.5 });
    for (const item of items) {
      const t = new PIXI.Text({
        text: item.text,
        style: { fontFamily: FONT_UI, fontSize: item.size, fontWeight: '800', fill: INK.primary },
      });
      const bw = t.width + 32;
      const bh = 30;
      const bx = this.w / 2 - bw / 2;
      const by = item.y - bh / 2;
      const bg = new PIXI.Graphics();
      bg.roundRect(bx + 2, by + 4, bw, bh, 15).fill({ color: INK.shadow, alpha: 0.26 });
      bg.roundRect(bx, by, bw, bh, 15).fill({ color: INK.paper, alpha: 0.98 }).stroke({ width: 1.8, color: item.color });
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
          const r1 = this.regularSlotRects.get(`${i}:1`);
          const r2 = this.regularSlotRects.get(`${i}:2`);
          if (!r1 || !r2) continue;
          const minX = Math.min(r1.x, r2.x) - 10;
          const maxX = Math.max(r1.x + r1.w, r2.x + r2.w) + 10;
          const minY = Math.min(r1.y, r2.y) - 10;
          const maxY = Math.max(r1.y + r1.h, r2.y + r2.h) + 10;
          if (x >= minX && x <= maxX && y >= minY && y <= maxY) {
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
        width: 108,
        height: 148,
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

    if (this.shakeTime > 0) {
      this.shakeTime = Math.max(0, this.shakeTime - dtSec);
      const decay = this.shakeTime > 0 ? this.shakePower * (this.shakeTime / 0.32) : 0;
      this.worldRoot.position.set((Math.random() - 0.5) * decay, (Math.random() - 0.5) * decay);
    } else {
      this.worldRoot.position.set(0, 0);
    }

    for (const view of this.handCardViews.values()) {
      const b = view.bodyEntry.body;
      view.container.position.set(b.position.x, b.position.y);
      view.container.rotation = b.angle;
      view.container.scale.set(view.bodyEntry.scale);
    }

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

    if (this.preTimerTexts.length) {
      const nowMs = Date.now();
      for (const item of this.preTimerTexts) {
        if (!item.txt.destroyed) {
          item.txt.text = `${item.baseHeader} ${((nowMs - item.declaredAt) / 1000).toFixed(1)}s`;
        }
      }
    }

    this.tetherLayer.clear();
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
          const r = this.charRects.get(ch.id);
          if (r) to = { cx: r.x + r.w, cy: r.y + r.h / 2 };
        }
      }
      if (to) {
        const col = slot.ready ? 0x1c8a64 : 0xcf4932;
        this.tetherLayer.moveTo(from.cx, from.cy + from.h * 0.35)
          .quadraticCurveTo((from.cx + to.cx) / 2, Math.min(from.cy, to.cy) - 22, to.cx, to.cy)
          .stroke({ width: 2.2, color: col, alpha: 0.65 });
        this.tetherLayer.circle(to.cx, to.cy, 5).fill({ color: col, alpha: 0.9 });
      }
    }

    if (this.dragState && this.dragState.moved) {
      const { startX, startY, x, y, canAttack, canIntercept, side } = this.dragState;
      const pulse = 0.72 + Math.sin(this.time * 10) * 0.28;
      if (this.state?.mode === 'placement') {
        const nextNum = this._findFirstEmptyRegularDuel(side);
        const well = this.regularSlotRects.get(`${nextNum}:${side}`);
        if (well) {
          this.tetherLayer.roundRect(well.x - 3, well.y - 3, well.w + 6, well.h + 6, 13)
            .stroke({ width: 3, color: SIDE_THEME[side].accent, alpha: pulse });
        }
      } else if (canAttack || canIntercept) {
        this.tetherLayer.moveTo(startX, startY)
          .quadraticCurveTo((startX + x) / 2, Math.min(startY, y) - 50, x, y)
          .stroke({ width: 3, color: INK.gold, alpha: 0.9 });
        this.tetherLayer.circle(x, y, 8).stroke({ width: 2.2, color: INK.gold, alpha: 0.95 });
      }
    }

    let hpDirty = false;
    for (const p of this.state?.frame?.players || []) {
      for (const ch of p.characters || []) {
        const cur = this.hpDisplay.get(ch.id);
        if (cur !== undefined && Math.abs(cur - ch.hp) > 0.04) {
          this.hpDisplay.set(ch.id, cur + (ch.hp - cur) * Math.min(1, dtSec * 8));
          hpDirty = true;
        } else if (cur !== ch.hp) {
          this.hpDisplay.set(ch.id, ch.hp);
          hpDirty = true;
        }
      }
    }
    if (hpDirty) this._rebuildCharactersAndStacks();

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
