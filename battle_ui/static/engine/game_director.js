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
  drawUnifiedDieFrame,
  drawStatusIcon,
  drawShieldGlyph,
  drawLightStar,
  drawCostCrystal,
  buildCardBack,
  buildCardFront,
  buildBoardCardTag,
  buildFullCard,
  buildVerbatimCardPanel,
  buildRichVerbatimText,
  buildUnifiedEntryPlate,
} from './card_print.js';
import { createCharacterActor, actorPalette } from './stage_actors.js';
import {
  createFactionCostHud,
  createDiegeticDeckPiles,
} from './cost_hud.js';
import {
  computeFormationLayout,
  resolveInfiniteActorSpec,
  createDelayedHpBar,
} from './formation.js';
import {
  renderFocusSightlines,
  createDiegeticTopBar,
  buildScalableDuelRail,
  buildHitstopBanner,
} from './combat_choreography.js';
import {
  makeSealButton,
  buildHeroSidePanel,
  buildPassiveDrawer,
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
    this.hpTrailState = new Map();   // charId -> { hp, trailHp, lastTargetHp } persisted across rebuilds
    this.hpWidgets = new Map();      // charId -> { bar, hpTxt, maxHp }
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
    this.focusedCharId = null;
    this.focusedDuelNumber = null;

    // Single-Focus Side Hero Inspector + Independent Dual-Scroll Passive Drawer
    this.activeHeroPanel = null; // { charId, side, tab, scrollY, maxScroll, rect, node }
    this.passiveDrawer = null;   // { scrollY1, scrollY2, maxScrollBySide, splitX, rect, node }
    this.sidePanelActors = [];
    this._duelScrollCtl = null;
    this._combatRail = null;
    this._activeOverlayNode = null;
    this._lastHandHoverSfxMs = 0;
    this.rosterModal = null;
    this.rosterActors = [];
    this.codexModal = null;
    this.pileModal = null;
    this.drawSelected = new Set();
    this.drawSelectScrollX = 0;
    this.specialScrollY = 0;
    this.finishScrollY = 0;
    this.lastPointerX = this.w * 0.5;
    this.lastPointerY = this.h * 0.5;
    this.duelScrollY = 0;
    this.duelMaxScroll = 0;
    this._duelSlotCountPrev = 0;
    this.wingScrollY = { 1: 0, 2: 0 };
    this.wingMaxScroll = { 1: 0, 2: 0 };
    this.wingViewports = {};
    this._wingScrollCtl = {};

    // Spatial hit-test geometry maps
    this.layout = {};
    this.charRects = new Map();
    this.regularSlotRects = new Map();
    this.regularLaneRects = new Map();
    this.preRevealSlotRects = new Map();
    this.pileCenters = new Map();
    this.handCardViews = new Map();
    this.preTimerTexts = [];

    // Matter.js real dice collision callback -> exact contact audio + Three.js sparks + shockwave + defense barrier
    this.physics.onClashImpact = ({ x, y, group }) => {
      const heavy = group.outcome !== 'draw';
      this.audio.clashImpact(heavy);
      this.three.spawnImpactBurst(x, y, group.winnerColor || 0xe89b32, heavy ? 36 : 22, heavy);
      this.physics.applyGentleImpulse(x, y, 290, heavy ? 0.036 : 0.02);
      if (heavy) {
        this.three.emitShockwave(x, y, group.winnerColor || 0xe89b32);
        this._triggerShake(7.5, 0.22);
      }
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
    this.persistentHudLayer = new PIXI.Container();
    this.tetherLayer = new PIXI.Graphics();
    this.sidePanelsLayer = new PIXI.Container();
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
      this.persistentHudLayer,
      this.tetherLayer,
      this.sidePanelsLayer,
      this.handLayer,
      this.controlsLayer,
      this.cornerHudLayer,
      this.fxTextLayer
    );
    app.stage.addChild(this.overlayLayer, this.inspectLayer, this.toastLayer);

    // Persistent Diegetic Tabletop Top Bar (ZERO destroy/rebuild on updates or toggles!)
    this.topBar = createDiegeticTopBar({
      width: this.w,
      pad: 16,
      onToggleAuto: () => {
        this.autoPace = !this.autoPace;
        this.autoTimer = 0.35;
        this._syncTopBar();
      },
      onToggleMute: () => {
        this.audio.toggleMute();
        this._syncTopBar();
      },
      onTogglePassives: () => this._togglePassiveDrawer(),
      onOpenCodex: () => {
        this.activeHeroPanel = null;
        this.passiveDrawer = null;
        this.codexModal = { tab: 'rules', scrollY: 0, maxScroll: 0, node: null };
        this._syncTopBar();
        this._rebuildSidePanels();
        this._rebuildOverlay();
      },
      onOpenRoster: () => this._openRosterModal(),
    });
    this.cornerHudLayer.addChild(this.topBar);

    // Persistent Spring-Physical Faction Cost HUDs & 2.5D Diegetic Deck Piles (NEVER destroyed on rebuild!)
    this.costHuds = {
      1: createFactionCostHud({
        side: 1,
        align: 'left',
        onShockwave: (sx, sy, colorHex) => {
          this.three.emitShockwave(sx, sy, colorHex);
          this.audio.costMerge(1.0, -0.35);
        },
      }),
      2: createFactionCostHud({
        side: 2,
        align: 'right',
        onShockwave: (sx, sy, colorHex) => {
          this.three.emitShockwave(sx, sy, colorHex);
          this.audio.costMerge(0.96, 0.35);
        },
      }),
    };
    this.deckPiles = {
      1: createDiegeticDeckPiles({
        side: 1,
        align: 'left',
        onOpenPile: ({ title, side, cards }) => {
          this.pileModal = { title, side, cards, scrollY: 0, maxScroll: 0, node: null };
          this._rebuildOverlay();
        },
      }),
      2: createDiegeticDeckPiles({
        side: 2,
        align: 'right',
        onOpenPile: ({ title, side, cards }) => {
          this.pileModal = { title, side, cards, scrollY: 0, maxScroll: 0, node: null };
          this._rebuildOverlay();
        },
      }),
    };
    this.persistentHudLayer.addChild(
      this.costHuds[1],
      this.costHuds[2],
      this.deckPiles[1],
      this.deckPiles[2]
    );

    app.stage.eventMode = 'static';
    app.stage.hitArea = app.screen;
    app.stage.on('pointermove', (e) => this._onPointerMove(e));
    app.stage.on('pointerup', (e) => this._onPointerUp(e));
    app.stage.on('pointerupoutside', (e) => this._onPointerUp(e));
    app.stage.on('pointertap', () => {
      if ((this.activeHeroPanel || this.passiveDrawer) && !this.dragState) {
        this._closeStageSheets();
      }
      if (this.selectedHandCardId && !this.dragState) {
        this.selectedHandCardId = null;
        this._rebuildDynamicBoard();
      }
    });

    window.addEventListener('wheel', (e) => this._onWheel(e), { passive: true });
    window.addEventListener('keydown', (e) => this._onKeyDown(e));
    window.addEventListener('contextmenu', (e) => {
      if (this.activeHeroPanel || this.passiveDrawer || this.codexModal || this.pileModal) {
        e.preventDefault();
        this.codexModal = null;
        this.pileModal = null;
        this._closeStageSheets();
        this._rebuildOverlay();
      }
    });

    this._computeLayout();
    this._positionPersistentHud();
    this.topBar.resize(this.w, this.layout.pad);
  }

  resize(w, h) {
    this.w = w;
    this.h = h;
    this.app.stage.hitArea = this.app.screen;
    this._computeLayout();
    this._syncTopBar();
    this._positionPersistentHud();
    if (this.state) this._rebuildAll();
  }

  _positionPersistentHud() {
    const { leftWingX, rightWingX, wingW, stageBottom, h } = this.layout;
    if (leftWingX === undefined) return;
    const costY = 82;
    const pileScale = h < 780 ? 0.84 : 0.96;
    const pileY = stageBottom - Math.round(28 * pileScale);

    this.costHuds[1].setPosition(leftWingX, costY);
    this.costHuds[2].setPosition(rightWingX + wingW, costY);

    this.deckPiles[1].scale.set(pileScale);
    this.deckPiles[2].scale.set(pileScale);
    this.deckPiles[1].setPosition(leftWingX + 4, pileY);
    this.deckPiles[2].setPosition(rightWingX + wingW - 4, pileY);

    for (const side of [1, 2]) {
      this.costAnchors.set(side, this.costHuds[side].getAnchor());
      for (const k of ['draw', 'delayed_discard', 'out_of_combat']) {
        this.pileCenters.set(`${side}:${k}`, this.deckPiles[side].getPileAnchor(k));
      }
    }
  }

  _resolveCharColor(charId, side) {
    const pl = (this.state?.frame?.players || []).find((p) => p.side === side);
    const ch = pl?.characters?.find((c) => c.id === charId);
    if (ch) {
      const pal = actorPalette(ch, side);
      if (pal && pal.motif && pal.motif !== 'generic') return pal.primary;
      return resolveInfiniteActorSpec(ch, side).primary;
    }
    return (SIDE_THEME[side] || SIDE_THEME[1]).accent;
  }

  _setCardIntent(side, card) {
    if (!side || !card || !card.character_id) {
      this._clearCardIntent(side);
      return;
    }
    const charId = card.character_id;
    const cardCost = Math.max(0, Number(card.cost) || 0);
    this.focusedCharId = charId;
    const hud = this.costHuds[side];
    if (hud) hud.setIntent({ charId, cardCost });
    const pos = this._actorPos(charId);
    const colorHex = this._resolveCharColor(charId, side);
    this.three.setIntentFocus({ active: true, x: pos.x, y: pos.y, colorHex });
  }

  _clearCardIntent(side = null) {
    this.focusedCharId = null;
    if (side && this.costHuds[side]) {
      this.costHuds[side].setIntent({ charId: null, cardCost: 0 });
    } else {
      this.costHuds[1]?.setIntent({ charId: null, cardCost: 0 });
      this.costHuds[2]?.setIntent({ charId: null, cardCost: 0 });
    }
    this.three.setIntentFocus({ active: false });
  }

  _hasLiveHand() {
    const frame = this.state?.frame;
    if (!frame) return true;
    const mode = this.state.mode;
    if (frame.combat || mode === 'draw_select' || mode === 'reveal' || mode === 'turn_end' || mode === 'finished') {
      return false;
    }
    const viewerSide = frame.viewer_side;
    const player = viewerSide ? (frame.players || []).find((p) => p.side === viewerSide) : null;
    return Boolean(player && Array.isArray(player.hand) && player.hand.length > 0);
  }

  _computeLayout() {
    const w = this.w;
    const h = this.h;
    const pad = 16;
    const hasHand = this._hasLiveHand();
    // Full-width Open Sunlit Battlefield (NO narrow 210px passive sidebars eating 34% of the screen!)
    const battleX = pad;
    const battleW = Math.max(760, w - pad * 2);
    // Generous left & right fighter bands (standing WebGL actors + underfoot HUD + character-anchored passive chips)
    const fighterBandW = Math.round(Math.max(216, Math.min(280, battleW * 0.235)));
    const wingW = fighterBandW;
    const leftFighterX = battleX + Math.round(fighterBandW * 0.50);
    const rightFighterX = battleX + battleW - Math.round(fighterBandW * 0.50);
    // Expansive central confrontational arena for upright vertical duel cards & combat showdown!
    const arenaX = battleX + fighterBandW + 14;
    const arenaW = Math.max(440, battleW - fighterBandW * 2 - 28);

    // FIXED world vertical stage coordinates across ALL phases (placement -> pre_reveal -> reveal -> combat -> turn_end)!
    // Hiding the hand tray NEVER shifts fighters or duel slots downward (ZERO layout jump on reveal!).
    const baseHandStripH = Math.max(264, Math.min(314, Math.round(h * 0.375)));
    const handStripH = hasHand ? baseHandStripH : 0;
    const handTop = h - baseHandStripH + 4;
    const rightDockW = 152;
    const arenaTop = 52;
    const stageBottom = handTop - 12;
    const arenaH = Math.max(210, stageBottom - arenaTop);
    const handY = handTop + Math.round((baseHandStripH - 8) / 2);

    this.layout = {
      w, h, pad, wingW, hasHand, rightDockW,
      leftWingX: pad,
      rightWingX: w - pad - wingW,
      battleX, battleW, fighterBandW, leftFighterX, rightFighterX,
      arenaX, arenaW, arenaTop, arenaH, stageBottom,
      actionStripY: handTop - 22,
      showdownBottom: h - 24,
      handStripH, handTop, handY,
      cardW: 198,
      cardH: 278,
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
    this.focusedDuelNumber = null;
    this._clearCardIntent();
    if (nextState.mode === 'handoff' || nextState.mode === 'special_handoff') {
      this.activeHeroPanel = null;
      this.passiveDrawer = null;
    }
    this._renderInspection();

    const prevMode = this.state?.mode;
    const prevTurn = this.state?.frame?.turn;
    const nextTurn = nextState.frame?.turn;
    const prevRosterSig = (this.state?.frame?.players || [])
      .map((p) => (p.characters || []).map((c) => c.id).join(',')).join('|');
    const nextRosterSig = (nextState.frame?.players || [])
      .map((p) => (p.characters || []).map((c) => c.id).join(',')).join('|');
    if (isInitial || prevTurn !== nextTurn || prevRosterSig !== nextRosterSig) {
      this.duelScrollY = 0;
      this._duelSlotCountPrev = 0;
    }
    if (isInitial || prevRosterSig !== nextRosterSig) {
      this.activeHeroPanel = null;
      this.passiveDrawer = null;
      this.hpTrailState.clear();
      this.wingScrollY = { 1: 0, 2: 0 };
    }
    if (prevMode !== nextState.mode) {
      this.drawSelectScrollX = 0;
      this.specialScrollY = 0;
      this.finishScrollY = 0;
    }

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

  _resolveActorPosForSightline(idOrName) {
    if (!idOrName) return null;
    const node = this.actorNodes.get(idOrName);
    if (node) return { x: node.cx, y: node.cy };
    const r = this.charRects.get(idOrName);
    if (r) return { x: r.x + r.w / 2, y: r.y + r.h / 2 };
    for (const p of this.state?.frame?.players || []) {
      const ch = (p.characters || []).find((c) => c.name === idOrName);
      if (ch) {
        const n = this.actorNodes.get(ch.id);
        if (n) return { x: n.cx, y: n.cy };
        const cr = this.charRects.get(ch.id);
        if (cr) return { x: cr.x + cr.w / 2, y: cr.y + cr.h / 2 };
      }
    }
    return null;
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
      const pan = ev.side === 1 ? -0.32 : 0.32;
      this.audio.cardFlick(pan);
      this.deckPiles[ev.side]?.pulsePile('draw', 1.15);
      const dp = this.deckPiles[ev.side]?.getPileAnchor('draw') || this.pileCenters.get(`${ev.side}:draw`);
      if (dp) {
        this.three.spawnCardFlipArc({
          fromX: dp.x, fromY: dp.y,
          toX: this.layout.arenaX + this.layout.arenaW / 2,
          toY: this.layout.handY,
          width: 72, height: 100,
          accentHex: SIDE_THEME[ev.side]?.accentHex || '#1c8a64',
          flipFromBack: true, duration: 0.4, peakZ: 90,
        });
        this._spawnFloater(dp.x, dp.y - 36, `+${ev.count} 抽牌`, SIDE_THEME[ev.side].accent, 13, 'status');
      }
    } else if (ev.kind === 'draw_bottom') {
      this.audio.cardPlace(ev.side === 1 ? -0.25 : 0.25);
      this.deckPiles[ev.side]?.pulsePile('draw', 0.85);
      const dp = this.deckPiles[ev.side]?.getPileAnchor('draw') || this.pileCenters.get(`${ev.side}:draw`);
      if (dp) this._spawnFloater(dp.x, dp.y - 32, `置底 ${ev.count}`, INK.gold, 13, 'status');
    } else if (ev.kind === 'cost_refill') {
      this.audio.coinClink(1.08);
      const ca = this.costHuds[ev.side]?.getAnchor() || this.costAnchors.get(ev.side);
      if (ca) this.three.emitShockwave(ca.x, ca.y, INK.gold);
    } else if (ev.kind === 'cost_pay') {
      if (ev.paid) {
        this.audio.coinClink(0.95);
        const ca = this.costHuds[ev.side]?.getAnchor() || this.costAnchors.get(ev.side);
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
          this._spawnFloater(pos.x, pos.y - 44, `-${ev.cost} 费`, INK.gold, 13, 'status');
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
              this.audio.cardFlip(s === 1 ? -0.2 : 0.2);
              this.three.emitShockwave(rect.cx, rect.cy, SIDE_THEME[s].accent);
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
      this._spawnFloater(pos.x, pos.y - 36, `+${ev.amount}`, 0x269463, 19, 'clash');
    } else if (ev.kind === 'lose_hp') {
      this.audio.hitDamage(ev.amount >= 3);
      const pos = this._actorPos(ev.target_id);
      this._getMotion(ev.target_id).recoil = 0.7;
      this._getMotion(ev.target_id).hitFlash = 0.8;
      if (ev.amount >= 3) this.three.emitShockwave(pos.x, pos.y, 0xc44569);
      this._spawnFloater(pos.x, pos.y - 34, `失去 ${ev.amount} 生命`, 0xc44569, 16, ev.amount >= 3 ? 'heavy' : 'clash');
    } else if (ev.kind === 'breath_crit') {
      this.audio.clashImpact(true);
      const pos = this._actorPos(ev.character_id);
      this.three.emitShockwave(pos.x, pos.y, 0x1a8775);
      this._spawnFloater(pos.x, pos.y - 46, '✦ 暴击', 0x1a8775, 19, 'heavy');
      this.three.spawnImpactBurst(pos.x, pos.y, 0x24967c, 26, true);
    } else if (ev.kind === 'stagger_check') {
      const pos = this._actorPos(ev.target_id);
      if (ev.triggered) {
        this._triggerShake(8, 0.3);
        this.three.emitShockwave(pos.x, pos.y, 0xd4223a);
      }
      this._spawnFloater(pos.x, pos.y - 42, ev.triggered ? '致命失衡' : '失衡 +2', ev.triggered ? 0xd4223a : 0xbf9119, 17, ev.triggered ? 'heavy' : 'status');
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
      this.three.emitShockwave(pos.x, pos.y, 0xcf4330);
      this.physics.spawnShieldShards(pos.x, pos.y, 0xcf4330, 18, true);
      this.three.spawnImpactBurst(pos.x, pos.y, 0xcf4330, 38, true);
      this._spawnFloater(pos.x, pos.y - 26, `${ev.name} 阵亡`, 0xcf4330, 18, 'heavy');
      this._showBanner(`${ev.name} 阵亡`, 0xcf4330, 2.0);
    } else if (ev.kind === 'turn_recycle') {
      this.audio.turnBell();
      for (const s of ev.sides || []) {
        const total = (s.used_count || 0) + (s.board_count || 0) + (s.discard_count || 0);
        const dp = this.deckPiles[s.side]?.getPileAnchor('draw') || this.pileCenters.get(`${s.side}:draw`);
        if (total > 0) {
          this.deckPiles[s.side]?.pulsePile('draw', 1.25);
          if (s.discard_count > 0) this.deckPiles[s.side]?.pulsePile('delayed_discard', 0.9);
        }
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
    const node = this.actorNodes.get(ev.character_id);
    const pan = node ? (node.side === 1 ? -0.3 : 0.3) : 0;
    if (!silent) this.audio.passiveChime(1.0, pan);
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
    }
    this.three.emitShockwave(pos.x, pos.y, INK.gold);
    this._spawnFloater(pos.x, pos.y - 50, `${ev.passive_name}`, INK.gold, 14.5, 'passive');
  }

  _playStatusChangeFx(ev) {
    const pos = this._actorPos(ev.character_id);
    const col = STATUS_COLORS[ev.status] || INK.secondary;
    const sign = ev.delta > 0 ? '+' : '';
    if (ev.delta > 0) {
      this.three.triggerRipple(pos.x, pos.y, col);
    }
    this._spawnFloater(pos.x, pos.y - 26, `${ev.status} ${sign}${ev.delta}`, col, 13, 'status');
  }

  _playShieldGainFx(ev) {
    this.audio.shieldBlock();
    const pos = this._actorPos(ev.character_id);
    const st = SHIELD_STYLE[ev.shield_kind] || SHIELD_STYLE.normal;
    this.three.spawnShieldDomePulse({ x: pos.x, y: pos.y, radius: 56, colorHex: st.color });
    this._spawnFloater(pos.x, pos.y - 36, `+${ev.amount} ${st.label}`, st.color, 14, 'shield');
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
      this.three.emitShockwave(to.x, to.y, ds.color);
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
      this._spawnFloater(tx, ty - 42, `护盾抵扣 -${absorbedTotal}`, col, 14.5, 'shield');
    }

    if (erodedNormal > 0 || erodedReinf > 0) {
      this.audio.shieldErode();
      this.three.emitShockwave(tx, ty - 6, erodedReinf > 0 ? SHIELD_STYLE.reinforced.color : SHIELD_STYLE.normal.color);
      if (erodedNormal > 0) {
        this.physics.spawnShieldShards(tx - 14, ty - 6, SHIELD_STYLE.normal.color, 10 + erodedNormal * 2, true);
        this._spawnFloater(tx - 18, ty - 58, `磨损 -${erodedNormal} 普通护盾`, SHIELD_STYLE.normal.color, 14, 'shield');
      }
      if (erodedReinf > 0) {
        this.physics.spawnShieldShards(tx + 10, ty - 6, SHIELD_STYLE.reinforced.color, 10 + erodedReinf * 2, true);
        this._spawnFloater(tx + 14, ty - 58, `磨损 -${erodedReinf} 强化护盾`, SHIELD_STYLE.reinforced.color, 14, 'shield');
      }
    }

    if (ev.hp_lost > 0) {
      const isHeavy = ev.hp_lost >= 3 || (ev.multiplier && ev.multiplier > 1);
      this.audio.hitDamage(isHeavy);
      this._getMotion(ev.target_id).recoil = 1.0;
      this._getMotion(ev.target_id).hitFlash = 1.0;
      this._triggerShake(Math.min(11, 5 + ev.hp_lost * 2), 0.28);
      this.three.spawnImpactBurst(tx, ty, 0xcf4330, 24, isHeavy);
      if (isHeavy) this.three.emitShockwave(tx, ty, 0xcf4330);
      const multTag = ev.multiplier > 1 ? ` ×${ev.multiplier}` : '';
      this._spawnFloater(tx, ty - 18, `-${ev.hp_lost} ${GRADE_LABEL[ev.grade] || ''}${multTag}`.trim(), 0xcf4330, 21, isHeavy ? 'heavy' : 'clash');
    } else if (absorbedTotal === 0) {
      this._spawnFloater(tx, ty - 14, '0', INK.muted, 13, 'status');
    }
  }

  _triggerShake(power, duration) {
    this.shakePower = Math.max(this.shakePower, power);
    this.shakeTime = Math.max(this.shakeTime, duration);
  }

  _spawnFloater(x, y, text, color = INK.primary, fontSize = 15.5, kind = 'clash') {
    const resolvedKind = kind || (fontSize >= 18 ? 'heavy' : fontSize <= 13.5 ? 'status' : 'clash');
    const banner = buildHitstopBanner({ text, accentColor: color, kind: resolvedKind, x, y });
    const halfW = (banner._boxWidth || 120) / 2 + 12;
    banner.x = Math.max(halfW, Math.min(this.w - halfW, x));
    banner.y = Math.max(54, y);
    banner.applyHitstopProgress(0);
    this.fxTextLayer.addChild(banner);
    const life = resolvedKind === 'heavy' ? 1.65 : resolvedKind === 'passive' ? 1.55 : resolvedKind === 'status' ? 1.25 : 1.45;
    this.floaters.push({
      obj: banner,
      vx: (Math.random() - 0.5) * 18,
      vy: resolvedKind === 'heavy' ? -42 : -52,
      age: 0,
      life,
      hasHitstop: true,
    });
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
    this._computeLayout();
    this._syncTopBar();
    this._rebuildConfrontationWings();
    this._rebuildDynamicBoard();
    this._rebuildSidePanels();
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

  _syncTopBar() {
    if (!this.topBar || this.topBar.destroyed) return;
    const frame = this.state?.frame;
    this.topBar.resize(this.layout.w || this.w, this.layout.pad ?? 16);
    this.topBar.sync({
      turn: frame?.turn || 1,
      phaseLabel: frame ? (PHASE_NAMES[frame.phase] || frame.phase || '') : '',
      firstSide: frame?.first_side ?? null,
      autoPace: this.autoPace,
      muted: this.audio.muted,
      passivesOpen: Boolean(this.passiveDrawer),
    });
  }

  _rebuildCornerHud() {
    this._syncTopBar();
  }

  /**
   * Confrontational Left (P1) & Right (P2) Fighter Wings:
   *  - Persistent Spring-Physical Faction Cost HUD & 2.5D Diegetic Deck Piles (synced without destruction!)
   *  - 10v10+ Multi-Rank Tactical Formation via `computeFormationLayout` with O(1) independent wing scrolling
   *  - Persistent 60fps Delayed White-Trail HP Bars via `createDelayedHpBar`
   */
  _rebuildConfrontationWings() {
    // Persist live HP & delayed trail state across wing rebuilds so damage trails never vanish!
    for (const [cid, hw] of this.hpWidgets.entries()) {
      if (hw.bar && !hw.bar.destroyed && typeof hw.bar.getState === 'function') {
        const st = hw.bar.getState();
        this.hpTrailState.set(cid, {
          hp: st.displayHp,
          trailHp: st.trailHp,
          lastTargetHp: st.hp,
        });
      }
    }

    clearContainer(this.wingsLayer);
    clearContainer(this.actorsLayer);
    this.charRects.clear();
    this.actorNodes.clear();
    this.hpWidgets.clear();
    this.passivePlates.clear();
    this.wingViewports = {};
    this._wingScrollCtl = {};

    this._positionPersistentHud();

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
    const chars = player.characters || [];

    // 1. Wing Header: Faction Name + Initiative + Speed + Hand Count
    const headY = 46;
    const isFirst = frame.first_side === side;
    const speedVal = Number(player.speed || 0).toFixed(player.speed % 1 ? 1 : 0);
    const headTxt = new PIXI.Text({
      text: `${player.name}${isFirst ? ' ★先手' : ''} · 速${speedVal} · 手牌${player.hand_count}`,
      style: { fontFamily: FONT_UI, fontSize: 12, fontWeight: '800', fill: theme.accent },
    });
    headTxt.anchor.set(isLeft ? 0 : 1, 0);
    headTxt.position.set(isLeft ? wx + 2 : wx + wingW - 2, headY);
    this.wingsLayer.addChild(headTxt);

    // 2. Sync Persistent Spring-Physical Cost HUD & 2.5D Diegetic Deck Piles (ZERO destroy/rebuild!)
    const costHud = this.costHuds[side];
    if (costHud) {
      costHud.sync({
        sharedCost: player.cost?.available ?? 0,
        maxShared: Math.max(1, player.cost?.refill || 5),
        characters: chars.map((ch) => ({
          id: ch.id,
          name: ch.name,
          personalCost: ch.cost?.available ?? 0,
          color: this._resolveCharColor(ch.id, side),
        })),
      });
      this.costAnchors.set(side, costHud.getAnchor());
    }

    const piles = this.deckPiles[side];
    if (piles) {
      piles.sync({
        drawCount: player.draw_count ?? 0,
        discardCount: player.delayed_discard_count ?? 0,
        outCount: player.out_of_combat_count ?? 0,
        discardCards: player.delayed_discard || [],
        outCards: player.out_of_combat || [],
        playerName: player.name,
      });
      for (const k of ['draw', 'delayed_discard', 'out_of_combat']) {
        this.pileCenters.set(`${side}:${k}`, piles.getPileAnchor(k));
      }
    }

    // 3. 10v10+ Multi-Rank Battlefield Formation Layout (`computeFormationLayout`)
    const pileScale = h < 780 ? 0.84 : 0.96;
    const zoneTop = 106;
    const zoneBottom = Math.max(zoneTop + 140, this.layout.stageBottom - Math.round(58 * pileScale));

    const formation = computeFormationLayout({
      side,
      count: chars.length,
      bandX: wx,
      bandW: wingW,
      zoneTop,
      zoneBottom,
      scrollY: this.wingScrollY[side] || 0,
    });
    this.wingScrollY[side] = formation.scrollY;
    this.wingMaxScroll[side] = formation.maxScroll;
    this.wingViewports[side] = { x: wx, y: zoneTop, w: wingW, h: zoneBottom - zoneTop, top: zoneTop, bottom: zoneBottom };

    let floorHost = this.wingsLayer;
    let actorHost = this.actorsLayer;
    let thumbG = null;
    let thumbTravel = 0;
    const trackTop = zoneTop + 2;

    if (formation.scrollable) {
      const maskX = wx - 12;
      const maskY = zoneTop - 8;
      const maskW = wingW + 24;
      const maskH = zoneBottom - zoneTop + 16;

      const floorMask = new PIXI.Graphics();
      floorMask.rect(maskX, maskY, maskW, maskH).fill({ color: 0xffffff });
      this.wingsLayer.addChild(floorMask);

      floorHost = new PIXI.Container();
      floorHost.y = -formation.scrollY;
      floorHost.mask = floorMask;
      this.wingsLayer.addChild(floorHost);

      const actorMask = new PIXI.Graphics();
      actorMask.rect(maskX, maskY, maskW, maskH).fill({ color: 0xffffff });
      this.actorsLayer.addChild(actorMask);

      actorHost = new PIXI.Container();
      actorHost.y = -formation.scrollY;
      actorHost.mask = actorMask;
      this.actorsLayer.addChild(actorHost);

      // Subtle outer-edge scrollbar thumb for 10v10+ scrollable wings
      const sbX = isLeft ? Math.max(4, wx - 7) : Math.min(this.w - 8, wx + wingW + 3);
      const trackH = Math.max(32, zoneBottom - zoneTop - 4);
      const thumbH = Math.max(28, Math.round(trackH * (formation.zoneH / Math.max(formation.zoneH + 1, formation.contentHeight))));
      thumbTravel = Math.max(1, trackH - thumbH);

      const trackG = new PIXI.Graphics();
      trackG.roundRect(sbX, trackTop, 3.5, trackH, 1.8).fill({ color: INK.hairline, alpha: 0.9 });
      this.wingsLayer.addChild(trackG);

      thumbG = new PIXI.Graphics();
      thumbG.roundRect(sbX, 0, 3.5, thumbH, 1.8).fill({ color: theme.accent, alpha: 0.72 });
      thumbG.y = trackTop + (formation.maxScroll > 0 ? (formation.scrollY / formation.maxScroll) * thumbTravel : 0);
      this.wingsLayer.addChild(thumbG);
    }

    const scrollRefs = [];
    const orderedSlots = [...formation.slots].sort((a, b) => a.zIndex - b.zIndex);
    for (const slot of orderedSlots) {
      const ch = chars[slot.index];
      if (!ch) continue;
      const ref = this._buildOpenBattlefieldFighter(ch, side, slot, chars.length, {
        floorHost,
        actorHost,
        scrollable: formation.scrollable,
        scrollY: formation.scrollY,
        zoneTop,
        zoneBottom,
      });
      if (ref) scrollRefs.push(ref);
    }

    if (formation.scrollable) {
      this._wingScrollCtl[side] = {
        setScroll: (nextY) => {
          const clamped = Math.max(0, Math.min(formation.maxScroll, nextY));
          this.wingScrollY[side] = clamped;
          floorHost.y = -clamped;
          actorHost.y = -clamped;
          for (const ref of scrollRefs) {
            const screenY = ref.baseCy - clamped;
            const screenRectY = ref.baseRectY - clamped;
            if (ref.actorNode) ref.actorNode.cy = screenY;
            if (ref.charRect) ref.charRect.y = screenRectY;
            const vis = (screenY + ref.actorR + 58) >= zoneTop - 16 && (screenY - ref.actorR - 8) <= zoneBottom + 16;
            ref.hitZone.eventMode = vis ? 'static' : 'none';
          }
          if (thumbG && formation.maxScroll > 0) {
            thumbG.y = trackTop + (clamped / formation.maxScroll) * thumbTravel;
          }
        },
      };
    }
  }

  _closeStageSheets() {
    if (!this.activeHeroPanel && !this.passiveDrawer) return;
    this.activeHeroPanel = null;
    this.passiveDrawer = null;
    this.hoveredCard = null;
    this.hoveredInfo = null;
    this._renderInspection();
    this._rebuildCornerHud();
    this._rebuildSidePanels();
  }

  _openHeroSheet(charId, side) {
    this.passiveDrawer = null;
    this.codexModal = null;
    this.pileModal = null;
    // Strictly ONE character info panel open at a time (clicking another character switches cleanly!)
    if (this.activeHeroPanel && this.activeHeroPanel.charId === charId) {
      this.activeHeroPanel = null;
    } else {
      this.activeHeroPanel = { charId, side, tab: 'passives', scrollY: 0, maxScroll: 0, rect: null, node: null };
    }
    this.hoveredCard = null;
    this.hoveredInfo = null;
    this._renderInspection();
    this._rebuildCornerHud();
    this._rebuildSidePanels();
    this._rebuildOverlay();
  }

  _togglePassiveDrawer() {
    if (this.passiveDrawer) {
      this.passiveDrawer = null;
    } else {
      this.activeHeroPanel = null;
      this.codexModal = null;
      this.pileModal = null;
      this.passiveDrawer = { scrollY1: 0, scrollY2: 0, maxScrollBySide: { 1: 0, 2: 0 }, splitX: this.w * 0.5, rect: null, node: null };
    }
    this.hoveredCard = null;
    this.hoveredInfo = null;
    this._renderInspection();
    this._rebuildCornerHud();
    this._rebuildSidePanels();
    this._rebuildOverlay();
  }

  _rebuildSidePanels() {
    clearContainer(this.sidePanelsLayer);
    this.sidePanelActors = [];
    if (!this.state) return;
    const mode = this.state.mode;
    if (mode === 'handoff' || mode === 'special_handoff' || mode === 'draw_select' || mode === 'finished') {
      return;
    }

    const { w, pad, stageBottom } = this.layout;
    const players = this.state.frame?.players || [];
    const activeSide = this.state.active_side;

    // 1. Dual-Side Squad Passive Overview (Tab / 被动) with INDEPENDENT Left/Right scrolling!
    if (this.passiveDrawer) {
      const catById = new Map();
      for (const pl of this.state.catalog?.players || []) {
        for (const c of pl.characters || []) catById.set(c.id, c);
      }
      const sheetW = Math.min(1180, w - pad * 2);
      const sheetX = Math.round((w - sheetW) / 2);
      const maxH = Math.max(220, stageBottom - 48);
      const drawer = buildPassiveDrawer({
        x: sheetX,
        y: 44,
        width: sheetW,
        maxHeight: maxH,
        players,
        catalogById: catById,
        scrollY1: this.passiveDrawer.scrollY1 || 0,
        scrollY2: this.passiveDrawer.scrollY2 || 0,
        onOpenHeroSheet: (cid, s) => this._openHeroSheet(cid, s),
        onScrollChange: (s, val) => {
          if (!this.passiveDrawer) return;
          if (s === 1) this.passiveDrawer.scrollY1 = val;
          else this.passiveDrawer.scrollY2 = val;
        },
        onClose: () => this._closeStageSheets(),
      });
      this.passiveDrawer.maxScrollBySide = drawer._maxScrollBySide || { 1: 0, 2: 0 };
      this.passiveDrawer.splitX = drawer._splitX || (w * 0.5);
      this.passiveDrawer.rect = drawer._rect;
      this.passiveDrawer.node = drawer;
      this.sidePanelsLayer.addChild(drawer);
      return;
    }

    // 2. Single Active Side-Docked Hero Inspector (strictly ONE open at a time!)
    if (this.activeHeroPanel) {
      const m = this.activeHeroPanel;
      const side = m.side;
      const pl = players.find((p) => p.side === side);
      const ch = pl?.characters?.find((c) => c.id === m.charId);
      if (!ch) {
        this.activeHeroPanel = null;
        return;
      }
      const panelTop = 104;
      const panelW = Math.min(412, Math.max(326, Math.floor(w * 0.315)));
      const panelH = Math.max(220, Math.min(520, stageBottom - panelTop - 2));
      const panelX = side === 1 ? pad : w - pad - panelW;
      const canSetTarget = Boolean(activeSide && activeSide !== side && ch.alive);
      const isDefault = canSetTarget && this.state.default_targets?.[String(activeSide)] === ch.id;

      const panel = buildHeroSidePanel({
        character: ch,
        side,
        catalogChar: this._catalogChar(ch.id),
        catalogStatuses: this.state.catalog?.statuses || {},
        teamChars: pl.characters || [],
        x: panelX,
        y: panelTop,
        width: panelW,
        height: panelH,
        tab: m.tab || 'passives',
        canSetTarget,
        isDefaultTarget: isDefault,
        scrollY: m.scrollY || 0,
        onSwitchChar: (cid) => {
          m.charId = cid;
          m.scrollY = 0;
          this.hoveredCard = null;
          this._renderInspection();
          this._rebuildSidePanels();
        },
        onTab: (tab) => {
          m.tab = tab;
          m.scrollY = 0;
          this.hoveredCard = null;
          this._renderInspection();
          this._rebuildSidePanels();
        },
        onHoverSkill: (sk, ax, ay) => {
          this.hoveredCard = sk
            ? { card: sk, side, ownerName: ch.name, anchorX: ax, anchorY: ay, cardH: 310, source: 'hero_panel', sourceSprite: null }
            : null;
          this._renderInspection();
        },
        onSetFocusTarget: () => this._sendAction('set_default_target', { side: activeSide, character_id: ch.id }),
        onScrollChange: (val) => { m.scrollY = val; },
        onClose: () => this._closeStageSheets(),
      });
      m.maxScroll = panel._maxScroll || 0;
      m.rect = panel._rect;
      m.node = panel;
      if (panel._actors?.length) {
        this.sidePanelActors.push(...panel._actors);
      }
      this.sidePanelsLayer.addChild(panel);
    }
  }

  /**
   * Free-Standing Living Fighter on the Open Sunlit Arena Floor (1v1 to 10v10+ Multi-Rank!):
   *  - Hover fighter -> subtle floor ring highlight + Ruina-style focus sightlines (NEVER pops a blocking card!)
   *  - Click fighter -> opens their Side-Docked Inspector Panel (or targets them when a pre-attack card is selected!)
   */
  _buildOpenBattlefieldFighter(ch, side, slot, teamCount, {
    floorHost = this.wingsLayer,
    actorHost = this.actorsLayer,
    scrollable = false,
    scrollY = 0,
    zoneTop = 106,
    zoneBottom = 560,
  } = {}) {
    const theme = SIDE_THEME[side];
    const activeSide = this.state.active_side;
    const defaultTarget = activeSide && activeSide !== side && this.state.default_targets?.[String(activeSide)] === ch.id;
    const catChar = this._catalogChar(ch.id);
    const passiveCount = (catChar?.faction_passives?.length || 0) + (catChar?.passives?.length || 0);
    const hasRow3 = Object.values(ch.shields || {}).some((v) => v > 0) || Object.keys(ch.statuses || {}).length > 0 || passiveCount > 0;

    const cx = slot.x;
    const actorR = slot.actorR;
    const hudW = slot.hudW;
    const compactHud = hudW < 142;
    const hudBoxH = compactHud ? 32 : 38;
    const hudCoreH = hasRow3 ? (compactHud ? 50 : 65) : (hudBoxH + 3);
    const localActorY = scrollable ? slot.rawY : slot.y;
    const screenActorY = scrollable ? (slot.rawY - scrollY) : slot.y;
    const localUnitTop = Math.round(localActorY - actorR * 0.92);

    // Highlight valid enemy attack target when player selected a pre-attack card by click
    const isAttackTargetSelected = Boolean(
      this.selectedHandCardId
      && (this.state.mode === 'pre_attack' || this.state.mode === 'intercept')
      && activeSide && side !== activeSide && ch.alive
      && (this.state.legal_attack_cards || []).includes(this.selectedHandCardId)
    );

    const floorMark = new PIXI.Graphics();
    const drawFloor = (hovered) => {
      floorMark.clear();
      if (hovered || isAttackTargetSelected) {
        floorMark.ellipse(cx, localActorY + actorR * 0.66, actorR * 1.24, actorR * 0.37)
          .fill({ color: isAttackTargetSelected ? 0xfce6df : theme.warmTint, alpha: 0.6 })
          .stroke({ width: 1.8, color: isAttackTargetSelected ? 0xcf4932 : theme.accent, alpha: 0.85 });
      }
      if (defaultTarget) {
        floorMark.ellipse(cx, localActorY + actorR * 0.66, actorR * 1.18, actorR * 0.34)
          .stroke({ width: 2.2, color: INK.gold, alpha: 0.9 });
        floorMark.ellipse(cx, localActorY + actorR * 0.66, actorR * 1.32, actorR * 0.4)
          .stroke({ width: 1.1, color: INK.gold, alpha: 0.45 });
      }
    };
    drawFloor(false);
    floorHost.addChild(floorMark);

    // Living Animated Character Actor standing free on the open battlefield!
    const actor = createCharacterActor(ch, side, { radius: actorR });
    actor.position.set(cx, localActorY);
    actor.tick(this.time, this._getMotion(ch.id), ch);
    actorHost.addChild(actor);
    const actorNode = { actor, liveCh: ch, cx, cy: screenActorY, side };
    this.actorNodes.set(ch.id, actorNode);

    // Hit target rectangle covering the standing figure + underfoot HUD
    const hudX = Math.round(cx - hudW / 2);
    const localHudY = Math.round(localActorY + actorR * 0.78);
    const screenHudY = scrollable ? (localHudY - scrollY) : localHudY;
    const rectH = (localHudY + hudCoreH) - localUnitTop;
    const baseRectY = localUnitTop;
    const rect = { x: hudX - 6, y: scrollable ? (baseRectY - scrollY) : baseRectY, w: hudW + 12, h: rectH, side };
    this.charRects.set(ch.id, rect);

    const hitZone = new PIXI.Container();
    const hitG = new PIXI.Graphics();
    hitG.rect(hudX - 6, localUnitTop, hudW + 12, rectH).fill({ color: INK.paper, alpha: 0.001 });
    hitZone.addChild(hitG);
    hitZone.eventMode = (!scrollable || slot.visible) ? 'static' : 'none';
    hitZone.cursor = 'pointer';
    hitZone.on('pointerover', () => {
      if (this.dragState) return;
      drawFloor(true);
      this.focusedCharId = ch.id;
      this.three.setIntentFocus({
        active: true,
        x: actorNode.cx,
        y: actorNode.cy,
        colorHex: this._resolveCharColor(ch.id, side),
      });
    });
    hitZone.on('pointerout', () => {
      drawFloor(false);
      if (!this.dragState && this.focusedCharId === ch.id) {
        this.focusedCharId = null;
        this.three.setIntentFocus({ active: false });
      }
    });
    hitZone.on('pointertap', (e) => {
      if (this.dragState) return;
      if (scrollable) {
        const py = e.global.y;
        if (py < zoneTop - 8 || py > zoneBottom + 8) return;
      }
      e.stopPropagation();
      if (isAttackTargetSelected) {
        const cid = this.selectedHandCardId;
        this.selectedHandCardId = null;
        this.audio.cardPlace();
        this._sendAction('attack', { card_id: cid, target: { kind: 'character', id: ch.id } });
        return;
      }
      this._openHeroSheet(ch.id, side);
    });
    floorHost.addChild(hitZone);

    // Floating Underfoot Battlefield HUD (slim, translucent warm paper plinth — zero heavy card clutter!)
    const hud = new PIXI.Container();
    hud.position.set(hudX, localHudY);
    const bg = new PIXI.Graphics();
    bg.roundRect(0, 0, hudW, hudBoxH, 6)
      .fill({ color: ch.alive ? INK.paper : 0xede8de, alpha: 0.92 })
      .stroke({ width: defaultTarget ? 1.6 : 0.9, color: defaultTarget ? INK.gold : ch.alive ? INK.line : INK.muted });
    bg.roundRect(0, 2, 3, hudBoxH - 4, 1.5).fill({ color: ch.alive ? theme.accent : INK.muted });
    hud.addChild(bg);

    // Row 1: Name + Duel Quota pips + Speed + Personal Cost crystal
    const rawName = compactHud && ch.name.length > 4 ? `${ch.name.slice(0, 4)}` : ch.name;
    const nameTxt = new PIXI.Text({
      text: `${rawName}${ch.alive ? '' : ' [亡]'}`,
      style: {
        fontFamily: FONT_UI,
        fontSize: compactHud ? 10.2 : teamCount === 3 ? 11.5 : 12.5,
        fontWeight: '800',
        fill: ch.alive ? INK.strong : INK.muted,
      },
    });
    nameTxt.position.set(compactHud ? 6 : 8, compactHud ? 2.5 : 4);
    hud.addChild(nameTxt);

    const pCost = ch.cost?.available ?? 0;
    const pcX = hudW - (compactHud ? 9.5 : 11);
    const pcY = compactHud ? 9.5 : 11;
    drawCostCrystal(bg, pcX, pcY, compactHud ? 6.4 : 7.8, pCost > 0 ? INK.gold : INK.paperTint, pCost > 0 ? 0x9e5e0e : INK.line);
    const pcTxt = new PIXI.Text({
      text: String(pCost),
      style: { fontFamily: FONT_NUM, fontSize: compactHud ? 8.6 : 9.8, fontWeight: '900', fill: pCost > 0 ? INK.paper : INK.muted },
    });
    pcTxt.anchor.set(0.5);
    pcTxt.position.set(pcX, pcY + 0.5);
    hud.addChild(pcTxt);

    if (!compactHud || hudW >= 114) {
      const spTxt = new PIXI.Text({
        text: `速${ch.speed ?? 0}`,
        style: { fontFamily: FONT_NUM, fontSize: compactHud ? 8.8 : 9.8, fontWeight: '800', fill: INK.secondary },
      });
      spTxt.anchor.set(1, 0.5);
      spTxt.position.set(pcX - (compactHud ? 9.5 : 12), pcY);
      hud.addChild(spTxt);
    }

    if (!compactHud) {
      const maxD = ch.duels?.max ?? 1;
      const usedD = ch.duels?.used;
      const pipStartX = 8 + nameTxt.width + 7;
      for (let i = 0; i < maxD; i++) {
        const px = pipStartX + i * 8.5;
        if (px > pcX - 36) break;
        const used = usedD !== null && i < usedD;
        bg.circle(px, pcY, 3)
          .fill({ color: usedD === null ? INK.line : used ? INK.paperTint : theme.accent })
          .stroke({ width: 1, color: usedD === null ? INK.muted : theme.accent });
      }
    }

    // Row 2: Persistent 60fps Delayed White-Trail HP Bar (`createDelayedHpBar`) + Exact Numeral!
    const hpY = compactHud ? 19 : 22;
    const barH = compactHud ? 9 : 11;
    const infoX = compactHud ? 6 : 8;
    const numReserve = compactHud ? 40 : 52;
    const barW = Math.max(36, hudW - numReserve);

    const prevTrail = this.hpTrailState.get(ch.id);
    const initHp = !prevTrail
      ? ch.hp
      : ch.hp < prevTrail.trailHp
        ? prevTrail.trailHp
        : ch.hp > prevTrail.hp
          ? prevTrail.hp
          : ch.hp;
    const hpBar = createDelayedHpBar({
      width: barW,
      height: barH,
      accentColor: theme.accent,
      maxHp: ch.max_hp,
      hp: initHp,
      radius: compactHud ? 4 : 5,
    });
    if (prevTrail && ch.hp !== initHp) {
      hpBar.setHp(ch.hp, ch.max_hp, { immediate: false });
    }
    hpBar.position.set(infoX, hpY);

    const barState = hpBar.getState();
    const hpTxt = new PIXI.Text({
      text: `${Math.round(barState.displayHp)}/${ch.max_hp}`,
      style: { fontFamily: FONT_NUM, fontSize: compactHud ? 9.6 : 11.5, fontWeight: '900', fill: INK.strong },
    });
    hpTxt.anchor.set(1, 0.5);
    hpTxt.position.set(hudW - (compactHud ? 4.5 : 6), hpY + barH / 2);
    hud.addChild(hpBar, hpTxt);
    this.hpWidgets.set(ch.id, { bar: hpBar, hpTxt, maxHp: ch.max_hp });
    this.hpTrailState.set(ch.id, { hp: barState.displayHp, trailHp: barState.trailHp, lastTargetHp: barState.hp });

    // Row 3: Floating Active Shields (ONLY if > 0) + Limbus Status Icons cleanly below HP bar!
    const row3Y = hudBoxH + 3;
    const iconH = compactHud ? 17 : 21;
    let sx = 0;
    const shields = ch.shields || {};
    const shG = new PIXI.Graphics();
    hud.addChild(shG);
    for (const kind of ['normal', 'reinforced', 'concept']) {
      const val = shields[kind] || 0;
      if (val <= 0) continue;
      const shW = compactHud ? 30 : 36;
      if (sx + shW > hudW + 4) break;
      const st = SHIELD_STYLE[kind];
      shG.roundRect(sx, row3Y, shW, iconH, 5).fill({ color: st.bg }).stroke({ width: 1.2, color: st.color });
      drawShieldGlyph(shG, kind, sx + (compactHud ? 8 : 10), row3Y + iconH / 2, compactHud ? 4.8 : 5.8);
      const stNum = new PIXI.Text({
        text: String(val),
        style: { fontFamily: FONT_NUM, fontSize: compactHud ? 9.5 : 11, fontWeight: '900', fill: st.color },
      });
      stNum.anchor.set(0, 0.5);
      stNum.position.set(sx + (compactHud ? 15 : 19), row3Y + iconH / 2);
      hud.addChild(stNum);
      sx += shW + 3;
    }

    const statuses = Object.entries(ch.statuses || {});
    const stBoxSize = compactHud ? 18 : 22;
    for (const [name, val] of statuses) {
      if (sx + stBoxSize + 1 > hudW + 6) break;
      const col = STATUS_COLORS[name] || INK.secondary;
      const burst = name === '裂血' && ch.bleed_burst;
      const iconBox = new PIXI.Container();
      iconBox.position.set(sx, row3Y);
      const ig = new PIXI.Graphics();
      ig.roundRect(0, 0, stBoxSize, stBoxSize, 4.5)
        .fill({ color: burst ? 0xfce0e4 : INK.paper })
        .stroke({ width: burst ? 1.6 : 1.1, color: col });
      drawStatusIcon(ig, name, stBoxSize / 2, stBoxSize * 0.45, compactHud ? 5.8 : 7.2, col);
      ig.roundRect(stBoxSize * 0.45, stBoxSize * 0.52, stBoxSize * 0.6, stBoxSize * 0.5, 3).fill({ color: col });
      iconBox.addChild(ig);

      const valTxt = new PIXI.Text({
        text: String(val),
        style: { fontFamily: FONT_NUM, fontSize: compactHud ? 7.8 : 9, fontWeight: '900', fill: INK.paper },
      });
      valTxt.anchor.set(0.5);
      valTxt.position.set(stBoxSize * 0.75, stBoxSize * 0.77);
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
          y: Math.max(52, screenHudY - 24),
        };
        this._renderInspection();
      });
      iconBox.on('pointerout', () => {
        this.hoveredInfo = null;
        this._renderInspection();
      });
      hud.addChild(iconBox);
      sx += stBoxSize + 3;
    }

    // Subtle passive-count affordance badge on right side of Row 3
    if (passiveCount > 0) {
      const pBadgeW = compactHud ? 30 : 38;
      const pBadgeH = compactHud ? 16 : 19;
      const pbx = Math.max(sx + 2, hudW - pBadgeW);
      if (pbx + pBadgeW <= hudW + 4) {
        const pb = new PIXI.Graphics();
        pb.roundRect(pbx, row3Y + 1, pBadgeW, pBadgeH, 4.5)
          .fill({ color: INK.goldBg, alpha: 0.92 })
          .stroke({ width: 0.9, color: INK.gold, alpha: 0.85 });
        hud.addChild(pb);
        const pt = new PIXI.Text({
          text: `◆${passiveCount}`,
          style: { fontFamily: FONT_UI, fontSize: compactHud ? 8.8 : 10.2, fontWeight: '800', fill: INK.goldDeep },
        });
        pt.anchor.set(0.5);
        pt.position.set(pbx + pBadgeW / 2, row3Y + 1 + pBadgeH / 2);
        hud.addChild(pt);
      }
    }

    if (defaultTarget) {
      const ft = new PIXI.Text({
        text: '◎ 集火',
        style: { fontFamily: FONT_UI, fontSize: compactHud ? 8.8 : 9.8, fontWeight: '800', fill: INK.goldDeep },
      });
      ft.anchor.set(0.5, 1);
      ft.position.set(hudW / 2, -actorR * 1.56);
      hud.addChild(ft);
    }

    floorHost.addChild(hud);
    return { charId: ch.id, baseCy: slot.rawY, baseRectY, actorR, actorNode, charRect: rect, hitZone };
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
    this._duelScrollCtl = null;
    this._combatRail = null;

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

    // 1. Pre-Reveal / Instant Arch (ONLY visible when active — renders FULL readable cards directly!)
    if (showPreLane) {
      const preH = allTopDuels.length > 0
        ? Math.min(206, Math.max(146, Math.round(arenaH * 0.48)))
        : Math.min(82, Math.round(arenaH * 0.22));
      regTop = arenaTop + preH + 10;
      regH = Math.max(120, arenaH - preH - 10);

      const pendingNumbers = new Set(this.state.pending_responses || []);
      const archG = new PIXI.Graphics();
      archG.roundRect(arenaX, arenaTop, arenaW, preH, 10)
        .fill({ color: 0xfbf7ee, alpha: 0.9 })
        .stroke({ width: 1.2, color: INK.gold, alpha: 0.55 });
      this.boardLayer.addChild(archG);

      if (!allTopDuels.length) {
        const cue = new PIXI.Text({
          text: '开牌前交锋',
          style: { fontFamily: FONT_UI, fontSize: 13, fontWeight: '800', fill: INK.goldDeep },
        });
        cue.anchor.set(0.5);
        cue.position.set(arenaX + arenaW / 2, arenaTop + preH / 2);
        this.boardLayer.addChild(cue);
      } else {
        const count = allTopDuels.length;
        const slotGap = 10;
        const slotW = Math.floor((arenaW - 16 - (count - 1) * slotGap) / count);
        const slotH = preH - 14;
        const startX = arenaX + 8;

        allTopDuels.forEach((slot, idx) => {
          const sx = startX + idx * (slotW + slotGap);
          const sy = arenaTop + 7;
          const isPendingForMe = slot._kind === 'pre_reveal' && !slot.ready && pendingNumbers.has(slot.number);
          if (slot._kind === 'pre_reveal') {
            this.preRevealSlotRects.set(slot.number, { x: sx, y: sy, w: slotW, h: slotH, cx: sx + slotW / 2, cy: sy + slotH / 2 });
          }

          const canClickIntercept = Boolean(
            isPendingForMe && this.selectedHandCardId
            && (this.state.legal_intercept_cards || []).includes(this.selectedHandCardId)
          );
          const sg = new PIXI.Graphics();
          sg.roundRect(sx, sy, slotW, slotH, 8)
            .fill({ color: canClickIntercept ? 0xfceee8 : INK.paper })
            .stroke({ width: canClickIntercept ? 2.4 : isPendingForMe ? 1.8 : 1.1, color: isPendingForMe ? 0xc8452e : slot.ready ? 0x1a825e : INK.line });
          if (canClickIntercept) {
            sg.eventMode = 'static';
            sg.cursor = 'pointer';
            sg.on('pointertap', (e) => {
              e.stopPropagation();
              const cid = this.selectedHandCardId;
              this.selectedHandCardId = null;
              this.audio.cardPlace();
              this._sendAction('intercept', { card_id: cid, duel_number: slot.number });
            });
          }
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
            text: `${baseHeader}${elapsed}  ${targetTxt}`,
            style: { fontFamily: FONT_UI, fontSize: 10.5, fontWeight: '800', fill: isPendingForMe ? 0xc8452e : INK.primary },
          });
          head.position.set(sx + 8, sy + 5);
          this.boardLayer.addChild(head);
          if (timingRec?.declared_at_ms && !timingRec.answered_at_ms) {
            this.preTimerTexts.push({ txt: head, baseHeader, declaredAt: timingRec.declared_at_ms });
          }

          const cards = [];
          for (const sEntry of slot.sides || []) {
            for (const c of sEntry.cards || []) cards.push({ card: c, side: sEntry.side });
          }
          const availCardW = Math.max(160, Math.floor((slotW - 14 - (cards.length - 1) * 6) / Math.max(1, cards.length)));
          const availCardH = slotH - 28;
          cards.forEach(({ card, side }, cIdx) => {
            // Try 1:1 full card first; if space is tighter, use razor-sharp 1:1 buildBoardCardTag (ZERO blurry scaling!)
            let spr = null;
            let isTag = false;
            if (availCardW >= 210 && availCardH >= 120) {
              const fullTry = buildFullCard(card, {
                side,
                ownerName: charNames[card.character_id] || '',
                showOwner: multiChar,
                width: Math.min(254, availCardW),
                dense: true,
                centered: true,
                legal: true,
                playMode: card.play_mode,
              });
              if (fullTry._boxHeight <= availCardH + 6) {
                spr = fullTry;
              } else {
                fullTry.destroy({ children: true });
              }
            }
            if (!spr) {
              isTag = true;
              const tagW = Math.max(96, Math.min(132, availCardW - 4, Math.floor((availCardH - 4) / 1.40)));
              spr = buildBoardCardTag(card, {
                side,
                ownerName: charNames[card.character_id] || '',
                showOwner: multiChar,
                width: tagW,
                playMode: card.play_mode,
              });
            }
            const drawW = spr._boxWidth;
            const drawH = spr._boxHeight;
            const cxCard = sx + 7 + drawW / 2 + cIdx * (drawW + 6);
            const cyCard = sy + 23 + availCardH / 2;
            spr.position.set(cxCard, cyCard);
            if (isTag) {
              spr.eventMode = 'static';
              spr.cursor = 'pointer';
              spr.on('pointerover', () => {
                this.hoveredCard = {
                  card, side, ownerName: charNames[card.character_id] || '',
                  anchorX: cxCard, anchorY: cyCard, cardH: drawH, source: 'board', sourceSprite: spr,
                };
                this.focusedCharId = card.character_id || null;
                this.focusedDuelNumber = slot._kind === 'pre_reveal' ? { kind: 'pre_reveal', number: slot.number } : null;
                this._renderInspection();
              });
              spr.on('pointerout', () => {
                this.hoveredCard = null;
                this.focusedCharId = null;
                this.focusedDuelNumber = null;
                this._renderInspection();
              });
            } else if (!card.hidden) {
              spr.eventMode = 'static';
              spr.on('pointerover', () => {
                this.focusedCharId = card.character_id || null;
                this.focusedDuelNumber = slot._kind === 'pre_reveal' ? { kind: 'pre_reveal', number: slot.number } : null;
              });
              spr.on('pointerout', () => {
                this.focusedCharId = null;
                this.focusedDuelNumber = null;
              });
            }
            this.boardLayer.addChild(spr);
          });

          if (isPendingForMe) {
            const passBtn = makeSealButton('放行', {
              width: 52, height: 22, accent: 0xc8452e, solid: true, fontSize: 10.5, radius: 5,
              onClick: () => this._sendAction('let_through', { duel_number: slot.number }),
            });
            passBtn.position.set(sx + slotW - 58, sy + 3);
            this.boardLayer.addChild(passBtn);
          }
        });
      }
    }

    // 2. Scrollable Left (P1) vs Right (P2) Confrontational Duel Bridge in Strict 1D Top-to-Bottom Sequence (① ↓ ② ↓ ③):
    //    - Tight face-to-face horizontal opposition centered around midX ± 24 (zero overlap with 400px Side Inspectors!)
    //    - Vertical axis = Strict 1D sequence ① → ② → ③ with TRUE O(1) wheel scrolling (NEVER rebuilds hand cards!)
    const duels = frame.duels || [];
    const activeSide = this.state.active_side;
    const nextEmptyNum = this._findFirstEmptyRegularDuel(activeSide);
    const slotCount = Math.max(1, duels.length, this.state.mode === 'placement' ? nextEmptyNum : 0);

    const laneW = arenaW - 8;
    const midX = arenaX + laneW / 2;
    const wellPadX = 8;
    const maxAvailHalf = Math.floor(laneW / 2 - 24 - wellPadX);
    // Keep duel card dimensions 100% invariant between placement and reveal (cards flip face-up IN PLACE, zero jump!)
    const wellW = Math.min(152, maxAvailHalf);
    const effectiveCardW = Math.max(106, Math.min(130, wellW - 10, slotCount === 1 ? 132 : 122));
    const wantsFullReveal = false;
    const laneH = Math.round(effectiveCardW * 1.40) + 12;
    const laneGap = 10;
    const stepY = laneH + laneGap;
    const totalH = slotCount * laneH + Math.max(0, slotCount - 1) * laneGap;

    this.duelMaxScroll = Math.max(0, totalH - regH + 6);
    if (slotCount > this._duelSlotCountPrev && this.state.mode === 'placement' && this.duelMaxScroll > 0) {
      this.duelScrollY = this.duelMaxScroll;
    }
    this._duelSlotCountPrev = slotCount;
    this.duelScrollY = Math.max(0, Math.min(this.duelMaxScroll, this.duelScrollY));

    const baseStartY = this.duelMaxScroll > 0
      ? regTop + 2
      : regTop + Math.max(0, Math.floor((regH - totalH) / 2));

    this.duelViewport = { top: regTop, bottom: regTop + regH };
    const duelMask = new PIXI.Graphics();
    duelMask.rect(arenaX - 4, regTop, arenaW + 8, regH).fill({ color: 0xffffff });
    this.boardLayer.addChild(duelMask);

    const duelContent = new PIXI.Container();
    duelContent.y = -this.duelScrollY;
    duelContent.mask = duelMask;
    this.boardLayer.addChild(duelContent);

    if (slotCount > 1) {
      const spineG = new PIXI.Graphics();
      spineG.moveTo(midX, baseStartY + laneH / 2)
        .lineTo(midX, baseStartY + (slotCount - 1) * stepY + laneH / 2)
        .stroke({ width: 1.4, color: INK.line, alpha: 0.8 });
      duelContent.addChild(spineG);
    }

    const leftWellX = Math.round(midX - 24 - wellW);
    const rightWellX = Math.round(midX + 24);
    const bridgeSpanX = leftWellX - 6;
    const bridgeSpanW = (rightWellX + wellW + 6) - bridgeSpanX;
    const isPreAttackSelected = Boolean(
      this.selectedHandCardId
      && (this.state.mode === 'pre_attack' || this.state.mode === 'intercept')
      && (this.state.legal_attack_cards || []).includes(this.selectedHandCardId)
    );

    const laneMeta = [];
    for (let i = 0; i < slotCount; i++) {
      const number = i + 1;
      const baseLy = baseStartY + i * stepY;
      const baseMidY = baseLy + laneH / 2;
      const ly = baseLy - this.duelScrollY;
      const isVisible = ly + laneH > regTop && ly < regTop + regH;
      const slotData = duels[i] || { number, sides: [{ side: 1, cards: [] }, { side: 2, cards: [] }] };
      const isNextDropSlot = this.state.mode === 'placement' && number === nextEmptyNum;

      const laneRect = { x: bridgeSpanX, y: ly, w: bridgeSpanW, h: laneH, cx: midX, cy: ly + laneH / 2, visible: isVisible };
      this.regularLaneRects.set(number, laneRect);

      const bridgeG = new PIXI.Graphics();
      if (isPreAttackSelected && i < duels.length) {
        bridgeG.roundRect(bridgeSpanX, baseLy + 1, bridgeSpanW, laneH - 2, 10)
          .fill({ color: 0xfce6df, alpha: 0.35 })
          .stroke({ width: 1.6, color: 0xcf4932, alpha: 0.8 });
        bridgeG.eventMode = 'static';
        bridgeG.cursor = 'pointer';
        bridgeG.on('pointertap', (e) => {
          e.stopPropagation();
          const cid = this.selectedHandCardId;
          this.selectedHandCardId = null;
          this.audio.cardPlace();
          this._sendAction('attack', { card_id: cid, target: { kind: 'duel', number } });
        });
      }
      bridgeG.moveTo(leftWellX + wellW, baseMidY).lineTo(midX - 15, baseMidY)
        .stroke({ width: 1.2, color: SIDE_THEME[1].border, alpha: 0.65 });
      bridgeG.moveTo(midX + 15, baseMidY).lineTo(rightWellX, baseMidY)
        .stroke({ width: 1.2, color: SIDE_THEME[2].border, alpha: 0.65 });
      bridgeG.poly([midX - 20, baseMidY - 3.5, midX - 14, baseMidY, midX - 20, baseMidY + 3.5]).fill({ color: SIDE_THEME[1].accent, alpha: 0.78 });
      bridgeG.poly([midX + 20, baseMidY - 3.5, midX + 14, baseMidY, midX + 20, baseMidY + 3.5]).fill({ color: SIDE_THEME[2].accent, alpha: 0.78 });
      bridgeG.circle(midX, baseMidY, 13.5)
        .fill({ color: isNextDropSlot ? INK.goldBg : INK.paper })
        .stroke({ width: 1.6, color: isNextDropSlot ? INK.gold : INK.line });
      duelContent.addChild(bridgeG);

      const numTxt = new PIXI.Text({
        text: CIRCLED[i] || String(number),
        style: { fontFamily: FONT_UI, fontSize: 13, fontWeight: '900', fill: isNextDropSlot ? INK.goldDeep : INK.secondary },
      });
      numTxt.anchor.set(0.5);
      numTxt.position.set(midX, baseMidY);
      duelContent.addChild(numTxt);

      const wellH = laneH - 8;
      const slotRefs = [];
      for (const s of [1, 2]) {
        const wx = s === 1 ? leftWellX : rightWellX;
        const baseWy = baseLy + 4;
        const wy = baseWy - this.duelScrollY;
        const wellRect = { x: wx, y: wy, w: wellW, h: wellH, cx: wx + wellW / 2, cy: wy + wellH / 2, visible: isVisible };
        this.regularSlotRects.set(`${number}:${s}`, wellRect);
        slotRefs.push({ wellRect, baseWy });

        const sideEntry = (slotData.sides || []).find((x) => x.side === s);
        const cards = sideEntry ? sideEntry.cards : [];
        const isTargetWell = isNextDropSlot && s === activeSide;

        if (!cards.length || isTargetWell) {
          const slotCardW = Math.min(effectiveCardW, wellW - 4);
          const slotCardH = Math.min(wellH, Math.round(slotCardW * 1.40));
          const sx0 = (wx + wellW / 2) - slotCardW / 2;
          const sy0 = (baseWy + wellH / 2) - slotCardH / 2;
          const wellG = new PIXI.Graphics();
          wellG.roundRect(sx0, sy0, slotCardW, slotCardH, 8)
            .fill({ color: isTargetWell ? SIDE_THEME[s].warmTint : INK.paperSoft, alpha: isTargetWell ? 0.92 : 0.42 })
            .stroke({
              width: isTargetWell ? 1.8 : 0.9,
              color: isTargetWell ? SIDE_THEME[s].accent : SIDE_THEME[s].border,
              alpha: isTargetWell ? 0.95 : 0.42,
            });
          duelContent.addChild(wellG);

          if (isTargetWell) {
            wellG.eventMode = 'static';
            wellG.cursor = 'pointer';
            wellG.on('pointertap', (e) => {
              if (!wellRect.visible) return;
              if (this.selectedHandCardId) {
                e.stopPropagation();
                this._placeCard(this.selectedHandCardId);
              }
            });
          }
        }

        cards.forEach((card, cIdx) => {
          const ox = (cIdx - (cards.length - 1) / 2) * 18;
          const isFaceDown = card.hidden || (!frame.cards_revealed && card.state === 'placed_face_down');
          let spr = null;
          let needsHoverFull = false;

          if (isFaceDown) {
            const bw = Math.min(effectiveCardW, wellW - 6);
            const bh = Math.round(bw * 1.40);
            spr = buildCardBack(s, { width: bw, height: bh });
          } else if (wantsFullReveal && effectiveCardW >= 164) {
            spr = buildFullCard(card, {
              side: s,
              ownerName: charNames[card.character_id] || '',
              showOwner: multiChar,
              width: effectiveCardW,
              fixedHeight: Math.round(effectiveCardW * 1.40),
              dense: true,
              centered: true,
              legal: true,
            });
          } else {
            needsHoverFull = true;
            spr = buildBoardCardTag(card, {
              side: s,
              ownerName: charNames[card.character_id] || '',
              showOwner: multiChar,
              width: Math.min(effectiveCardW, wellW - 6),
            });
          }

          spr.position.set(wx + wellW / 2 + ox, baseWy + wellH / 2);
          if (!card.hidden && needsHoverFull) {
            spr.eventMode = 'static';
            spr.cursor = 'pointer';
            spr.on('pointerover', () => {
              const gp = spr.getGlobalPosition();
              if (gp.y < regTop - 20 || gp.y > regTop + regH + 20) return;
              this.hoveredCard = {
                card, side: s, ownerName: charNames[card.character_id] || '',
                anchorX: gp.x, anchorY: gp.y, cardH: spr._boxHeight, source: 'board', sourceSprite: spr,
              };
              this.focusedCharId = card.character_id || null;
              this.focusedDuelNumber = number;
              this._renderInspection();
            });
            spr.on('pointerout', () => {
              this.hoveredCard = null;
              this.focusedCharId = null;
              this.focusedDuelNumber = null;
              this._renderInspection();
            });
          }
          duelContent.addChild(spr);
        });
      }
      laneMeta.push({ laneRect, baseLy, slotRefs });
    }

    // Subtle scrollbar thumb + true O(1) scroll controller (NEVER rebuilds hand cards on wheel!)
    let thumbG = null;
    let thumbTravel = 0;
    const trackTop = regTop + 2;
    if (this.duelMaxScroll > 0) {
      const sbX = rightWellX + wellW + 10;
      const trackH = regH - 4;
      const thumbH = Math.max(28, Math.round(trackH * (regH / Math.max(regH + 1, totalH))));
      thumbTravel = Math.max(1, trackH - thumbH);
      const trackG = new PIXI.Graphics();
      trackG.roundRect(sbX, trackTop, 3.5, trackH, 1.8).fill({ color: INK.hairline, alpha: 0.9 });
      this.boardLayer.addChild(trackG);

      thumbG = new PIXI.Graphics();
      thumbG.roundRect(sbX, 0, 3.5, thumbH, 1.8).fill({ color: INK.secondary, alpha: 0.65 });
      thumbG.y = trackTop + (this.duelScrollY / this.duelMaxScroll) * thumbTravel;
      this.boardLayer.addChild(thumbG);
    }

    this._duelScrollCtl = {
      setScroll: (nextY) => {
        this.duelScrollY = Math.max(0, Math.min(this.duelMaxScroll, nextY));
        duelContent.y = -this.duelScrollY;
        for (const lm of laneMeta) {
          const ly = lm.baseLy - this.duelScrollY;
          const vis = ly + laneH > regTop && ly < regTop + regH;
          lm.laneRect.y = ly;
          lm.laneRect.cy = ly + laneH / 2;
          lm.laneRect.visible = vis;
          for (const sr of lm.slotRefs) {
            sr.wellRect.y = sr.baseWy - this.duelScrollY;
            sr.wellRect.cy = sr.wellRect.y + sr.wellRect.h / 2;
            sr.wellRect.visible = vis;
          }
        }
        if (thumbG && this.duelMaxScroll > 0) {
          thumbG.y = trackTop + (this.duelScrollY / this.duelMaxScroll) * thumbTravel;
        }
      },
    };
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

    // 1. Auto-Centering Masked Scalable Duel Progress Rail (1 to 40+ Duels!)
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

    const railY = arenaTop;
    const rail = buildScalableDuelRail({
      x: arenaX,
      y: railY,
      width: arenaW,
      items: railItems,
      activeKind: combat.kind,
      activeNumber: combat.duel_number,
    });
    this.boardLayer.addChild(rail);
    this._combatRail = rail;

    // 2. Sculpted 3D Dice Clash Arena & Score Medallions
    const clashTop = railY + (rail._boxHeight || 32) + 8;
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
    const medW = Math.min(226, Math.max(156, Math.floor(arenaW / 2 - 42)));
    for (const s of combat.sides || []) {
      const isLeft = s.side === 1;
      const mx = isLeft ? arenaX + 10 : arenaX + arenaW - medW - 10;
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
      mg.roundRect(mx + 2, my + 4, 4, mh - 8, 2).fill({ color: win ? INK.gold : ds.color });
      drawUnifiedDieFrame(mg, die.type, mx + 25, my + 24, 9.2, { active: win, muted: lose });
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
    const cardsTop = clashTop + clashH + 12;
    const cardsAvailH = Math.max(180, showdownBottom - cardsTop);
    const colGap = 12;
    const colW = Math.min(344, Math.floor((arenaW - colGap) / 2));
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
        minHeight: Math.min(cardsAvailH - 4, Math.round(colW * 1.34)),
        activeDieNumber: combatSide?.die_number || null,
        dense: colW < 290,
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

  /**
   * Full-Width Zero-Hover Hand Tray:
   * Every card in your hand renders directly at full verbatim readable width (228~272px) side-by-side
   * across the entire bottom of the screen — compare ALL 3~5 cards simultaneously with ZERO hovering!
   * Hovering simply glides THAT exact Matter.js card smoothly upward & to front if tall or overlapped.
   */
  _rebuildHandFan() {
    clearContainer(this.handLayer);
    this.handCardViews.clear();

    const frame = this.state.frame;
    const viewerSide = frame.viewer_side;
    const player = viewerSide ? frame.players.find((p) => p.side === viewerSide) : null;
    const hand = player && Array.isArray(player.hand) ? player.hand : [];
    const { w, h, pad, handTop, handStripH, hasHand } = this.layout;
    const cx = w / 2;

    if (!player || !hasHand || !hand.length) {
      this.physics.pruneHandCards(new Set());
      return;
    }

    // Clean architectural divider separating the upper duel stage from the full-width hand tray
    const trayG = new PIXI.Graphics();
    trayG.rect(0, handTop - 6, w, h - handTop + 6).fill({ color: 0xf7f3ea, alpha: 0.72 });
    trayG.moveTo(pad, handTop - 6).lineTo(w - pad, handTop - 6).stroke({ width: 1, color: INK.line, alpha: 0.85 });
    this.handLayer.addChild(trayG);

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
    const rightReserve = (this.layout.rightDockW || 152) + 16;
    const availW = w - pad * 2 - rightReserve;
    const handZoneCx = pad + availW / 2;
    const gap = 14;
    // True Portrait Physical Card Proportions (Width : Height ≈ 1 : 1.40, NEVER landscape tiles!)
    const maxFitH = Math.max(244, handStripH - 18);
    const targetWFromH = Math.round(maxFitH / 1.41);
    const handCardW = Math.max(182, Math.min(208, targetWFromH, Math.floor((availW - Math.max(0, count - 1) * gap) / Math.max(1, count))));
    const portraitTargetH = Math.round(handCardW * 1.40);
    const deckOrigin = this.pileCenters.get(`${viewerSide}:draw`) || { x: handZoneCx, y: h - 60 };
    const validKeys = new Set();

    // Strictly FIXED vertical physical card dimensions (W : H = 1 : 1.40 — NEVER stretched taller by long text!)
    // Scales smoothly from 1-5 cards up to 6-12+ cards in 10v10 battles without overflowing the viewport!
    const uniformH = Math.min(maxFitH, portraitTargetH);
    const step = count > 1
      ? Math.min(handCardW + gap, Math.max(58, (availW - handCardW) / (count - 1)))
      : 0;
    const totalFanW = handCardW + Math.max(0, count - 1) * step;
    const rightLimit = w - pad - rightReserve;
    const fanCenterX = totalFanW >= availW
      ? pad + availW / 2
      : Math.max(pad + totalFanW / 2, Math.min(cx, rightLimit - totalFanW / 2));

    hand.forEach((card, i) => {
      const cardKey = `hand_${viewerSide}_${card.id}`;
      validKeys.add(cardKey);
      const isLegal = legalSet.has(card.id);
      const isSelected = this.selectedHandCardId === card.id;

      const spr = buildFullCard(card, {
        side: viewerSide,
        ownerName: charNames[card.character_id] || '',
        showOwner: multiChar,
        width: handCardW,
        fixedHeight: uniformH,
        dense: true,
        centered: true,
        legal: isLegal,
        selected: isSelected,
      });
      const cardH = spr._boxHeight;
      const norm = count > 1 ? (i / (count - 1)) * 2 - 1 : 0;
      const baseX = fanCenterX + (i - (count - 1) / 2) * step;
      // Subtle physical hand-fan arc (scales gently for 6-12+ cards, straightens cleanly on hover!)
      const angleAmp = count >= 7 ? Math.min(0.045, 0.024 + (count - 5) * 0.003) : 0.024;
      const baseAngle = count >= 3 ? norm * angleAmp : 0;
      const arcDrop = count >= 3 ? Math.round(norm * norm * (count >= 7 ? 10 : 5)) : 0;
      const baseY = h - 10 - cardH / 2 + arcDrop;
      const liftY = Math.max(cardH / 2 + 48, h - 10 - cardH / 2 - 14);

      const bodyEntry = this.physics.ensureHandCard(cardKey, deckOrigin.x, deckOrigin.y, handCardW, cardH);
      bodyEntry.targetX = baseX;
      bodyEntry.targetY = isSelected ? liftY - 8 : baseY;
      bodyEntry.targetAngle = isSelected ? 0 : baseAngle;
      bodyEntry.targetScale = isSelected ? 1.03 : 1.0;

      spr.position.set(bodyEntry.body.position.x, bodyEntry.body.position.y);
      spr.rotation = bodyEntry.body.angle;
      spr.scale.set(bodyEntry.scale);
      spr.eventMode = 'static';
      // Extend hitArea slightly downward so lifting 14px on hover NEVER leaves the cursor (ZERO hover-bounce loop!)
      spr.hitArea = new PIXI.Rectangle(-handCardW / 2, -cardH / 2, handCardW, cardH + 26);
      spr.cursor = isLegal ? 'grab' : 'default';

      spr.on('pointerover', () => {
        if (this.dragState) return;
        const now = performance.now();
        if (now - this._lastHandHoverSfxMs > 120) {
          this._lastHandHoverSfxMs = now;
          this.audio.cardSlide();
        }
        bodyEntry.targetY = liftY;
        bodyEntry.targetAngle = 0;
        bodyEntry.targetScale = 1.025;
        this.handLayer.setChildIndex(spr, this.handLayer.children.length - 1);
        this._setCardIntent(viewerSide, card);
      });

      spr.on('pointerout', () => {
        if (this.dragState?.cardKey === cardKey) return;
        bodyEntry.targetY = this.selectedHandCardId === card.id ? liftY - 8 : baseY;
        bodyEntry.targetAngle = this.selectedHandCardId === card.id ? 0 : baseAngle;
        bodyEntry.targetScale = this.selectedHandCardId === card.id ? 1.03 : 1.0;
        this._clearCardIntent(viewerSide);
      });

      // Prevent stage.pointertap from instantly deselecting a hand card on the same click!
      spr.on('pointertap', (e) => {
        e.stopPropagation();
      });

      spr.on('pointerdown', (e) => {
        if (!isLegal) {
          this.showToast('该牌当前无法打出。', 0xc8452e, 1.8);
          return;
        }
        e.stopPropagation();
        // Close overlapping top passive drawer when grabbing a card; keep non-overlapping side panels open!
        if (this.passiveDrawer) {
          this.passiveDrawer = null;
          this._rebuildCornerHud();
          this._rebuildSidePanels();
        }
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
          prevX: e.global.x,
          x: e.global.x, y: e.global.y,
          moved: false,
        };
        bodyEntry.dragging = true;
        bodyEntry.targetScale = 1.035;
        this.handLayer.setChildIndex(spr, this.handLayer.children.length - 1);
        this._setCardIntent(viewerSide, card);
        this.audio.cardSlide();
      });

      this.handLayer.addChild(spr);
      this.handCardViews.set(cardKey, { container: spr, card, side: viewerSide, legal: isLegal, baseX, baseY, baseAngle, bodyEntry });
    });

    this.physics.pruneHandCards(validKeys);
  }

  /**
   * Bottom-Right Command Dock (Slay-the-Spire / MTG-Arena muscle memory):
   * Keeps the center hand-to-battlefield drag corridor 100% unobstructed and eliminates misclicks!
   */
  _rebuildActionControls() {
    clearContainer(this.controlsLayer);
    const { w, h, pad, rightDockW = 152 } = this.layout;
    const mode = this.state.mode;
    const buttons = [];

    // Order bottom-to-top so the primary phase-end/advance action always anchors cleanly at the bottom-right corner!
    if (mode === 'placement') {
      buttons.push({
        label: `结束置卡（余${this.state.window_remaining}）`,
        h: 40,
        accent: 0xc8452e,
        solid: false,
        fn: () => this._sendAction('end'),
      });
      if (this.state.can_pass) {
        buttons.push({ label: '交权', h: 36, accent: INK.gold, solid: true, fn: () => this._sendAction('pass') });
      }
      if (this.selectedHandCardId) {
        buttons.push({ label: '扣置选中牌', h: 36, accent: 0x1a825e, solid: true, fn: () => this._placeCard(this.selectedHandCardId) });
      }
    } else if (mode === 'pre_attack' || mode === 'intercept') {
      if (this.state.can_end_attack) {
        buttons.push({ label: '结束主动进攻', h: 40, accent: INK.gold, solid: true, fn: () => this._sendAction('end_attack') });
      }
      if ((this.state.eligible_sides || []).length > 1) {
        buttons.push({ label: '切换席位', h: 34, accent: 0x177d6b, solid: false, fn: () => this._sendAction('switch_side') });
      }
    } else if (mode === 'reveal' || mode === 'combat' || mode === 'turn_end' || mode === 'timing') {
      const labelMap = {
        reveal: '进入常规交锋',
        combat: '下一拍',
        timing: '继续',
        turn_end: '下一回合',
      };
      buttons.push({ label: labelMap[mode], h: 42, accent: 0x1a825e, solid: true, fn: () => this._sendAction('next') });
    }

    if (this.state.special_available && mode !== 'finished' && mode !== 'draw_select' && mode !== 'special' && mode !== 'special_handoff') {
      buttons.push({ label: '特殊行动', h: 34, accent: 0x177d6b, solid: true, fn: () => this._sendAction('open_special') });
    }

    if (!buttons.length) return;
    const dockX = w - pad - rightDockW;
    const gap = 8;
    let cursorBottom = h - 16;

    for (const b of buttons) {
      const by = cursorBottom - b.h;
      const btn = makeSealButton(b.label, {
        width: rightDockW,
        height: b.h,
        accent: b.accent,
        solid: !!b.solid,
        fontSize: b.h >= 40 ? 13 : 12.5,
        radius: 8,
        onClick: b.fn,
      });
      btn.position.set(dockX, by);
      this.controlsLayer.addChild(btn);
      cursorBottom = by - gap;
    }
  }

  _rebuildOverlay() {
    clearContainer(this.overlayLayer);
    this.rosterActors = [];
    this._activeOverlayNode = null;
    if (!this.state) return;
    const { w, h } = this.layout;

    if (this.rosterModal) {
      const m = this.rosterModal;
      const cap = m.maxPerSide ?? 10;
      const ov = buildRosterOverlay(w, h, {
        catalog: this.state.roster_catalog || [],
        team1: m.team1,
        team2: m.team2,
        assignSide: m.assignSide,
        hoveredChar: m.hoveredChar,
        factionFilter: m.factionFilter || null,
        maxPerSide: cap,
        galleryScrollY: m.galleryScrollY || 0,
        inspectScrollY: m.inspectScrollY || 0,
        onSetAssignSide: (s) => { m.assignSide = s; this._rebuildOverlay(); },
        onSetMaxPerSide: (nextCap) => {
          m.maxPerSide = nextCap;
          if (typeof nextCap === 'number' && Number.isFinite(nextCap) && nextCap >= 1) {
            if (m.team1.length > nextCap) m.team1.splice(nextCap);
            if (m.team2.length > nextCap) m.team2.splice(nextCap);
          }
          this.audio.coinClink(1.06);
          this._rebuildOverlay();
        },
        onSetFaction: (fac) => {
          m.factionFilter = fac;
          m.galleryScrollY = 0;
          this.hoveredCard = null;
          this._renderInspection();
          this._rebuildOverlay();
        },
        onToggleChar: (cid) => {
          const own = m.assignSide === 1 ? m.team1 : m.team2;
          const other = m.assignSide === 1 ? m.team2 : m.team1;
          const limit = m.maxPerSide ?? 10;
          const idx = own.indexOf(cid);
          if (idx >= 0) own.splice(idx, 1);
          else {
            const oIdx = other.indexOf(cid);
            if (oIdx >= 0) other.splice(oIdx, 1);
            if (limit <= 0 || !Number.isFinite(limit) || own.length < limit) own.push(cid);
            else this.showToast(`每方最多选 ${limit} 名角色。`, INK.gold, 1.8);
          }
          const picked = (this.state.roster_catalog || []).find((c) => c.id === cid);
          if (picked && m.hoveredChar?.id !== picked.id) {
            m.hoveredChar = picked;
            m.inspectScrollY = 0;
          }
          this.hoveredCard = null;
          this._renderInspection();
          this.audio.coinClink(1.1);
          this._rebuildOverlay();
        },
        onRemoveFromSide: (side, cid) => {
          const list = side === 1 ? m.team1 : m.team2;
          const idx = list.indexOf(cid);
          if (idx >= 0) list.splice(idx, 1);
          m.assignSide = side;
          this.hoveredCard = null;
          this._renderInspection();
          this.audio.coinClink(0.95);
          this._rebuildOverlay();
        },
        onHoverChar: (ch) => {
          if (m.hoveredChar?.id !== ch.id) {
            m.hoveredChar = ch;
            m.inspectScrollY = 0;
            this.hoveredCard = null;
            this._renderInspection();
            this._rebuildOverlay();
          }
        },
        onHoverCard: (card, side, ownerName, cardX, cardY, cardH, spr) => {
          this.hoveredCard = card
            ? { card, side, ownerName, anchorX: cardX, anchorY: cardY, cardH: cardH || 172, source: 'roster', sourceSprite: spr }
            : null;
          this._renderInspection();
        },
        onGalleryScrollChange: (val) => { m.galleryScrollY = val; },
        onInspectScrollChange: (val) => { m.inspectScrollY = val; },
        onStart: async (teams) => {
          this.rosterModal = null;
          this.hoveredCard = null;
          this._renderInspection();
          this.three.clearDice();
          this.physics.clearClashGroups();
          await this._sendAction('new', { roster: teams });
        },
        onCancel: () => {
          this.rosterModal = null;
          this.hoveredCard = null;
          this._renderInspection();
          this._rebuildOverlay();
        },
      });
      this.rosterActors = ov._actors || [];
      m.galleryMaxScroll = ov._galleryMaxScroll || 0;
      m.inspectMaxScroll = ov._inspectMaxScroll || 0;
      m.gallerySplitX = ov._gallerySplitX || w * 0.5;
      m.node = ov;
      this.overlayLayer.addChild(ov);
      return;
    }

    if (this.codexModal) {
      const m = this.codexModal;
      const ov = buildCodexOverlay(w, h, {
        tab: m.tab,
        scrollY: m.scrollY,
        catalog: this.state.catalog,
        history: this.state.history || [],
        onTab: (tab) => { m.tab = tab; m.scrollY = 0; this._rebuildOverlay(); },
        onScrollChange: (val) => { m.scrollY = val; },
        onClose: () => { this.codexModal = null; this._rebuildOverlay(); },
      });
      m.maxScroll = ov._maxScroll || 0;
      m.node = ov;
      this.overlayLayer.addChild(ov);
      return;
    }

    if (this.pileModal) {
      const m = this.pileModal;
      const ov = buildPileOverlay(w, h, {
        title: m.title,
        side: m.side,
        cards: m.cards,
        charNames: this._charNameMap(),
        scrollY: m.scrollY || 0,
        onScrollChange: (val) => { m.scrollY = val; },
        onClose: () => { this.pileModal = null; this._rebuildOverlay(); },
      });
      m.maxScroll = ov._maxScroll || 0;
      m.node = ov;
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
        prompt,
        selectedIds: this.drawSelected,
        scrollX: this.drawSelectScrollX || 0,
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
        onScrollChange: (val) => { this.drawSelectScrollX = val; },
      });
      this._activeOverlayNode = { kind: 'draw_select', node: ov };
      this.overlayLayer.addChild(ov);
    } else if (mode === 'special') {
      const ov = buildSpecialOverlay(w, h, {
        side: this.state.active_side,
        timing: this.state.special_timing,
        options: this.state.special_options || [],
        pendingAttack: this.state.special_pending,
        scrollY: this.specialScrollY || 0,
        onPick: (idx) => this._sendAction('use_special', { option: idx }),
        onSwitchSide: () => this._sendAction('switch_side'),
        onLeave: () => this._sendAction('leave_special'),
        onScrollChange: (val) => { this.specialScrollY = val; },
      });
      this._activeOverlayNode = { kind: 'special', node: ov };
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
      this._activeOverlayNode = { kind: 'finished', node: ov };
      this.overlayLayer.addChild(ov);
    }
  }

  _openRosterModal() {
    const players = this.state?.frame?.players || [];
    const t1 = players[0]?.characters?.map((c) => c.id) || ['plan_b_annolin'];
    const t2 = players[1]?.characters?.map((c) => c.id) || ['waa_lake'];
    const catalog = this.state?.roster_catalog || [];
    this.activeHeroPanel = null;
    this.passiveDrawer = null;
    this.hoveredCard = null;
    this.hoveredInfo = null;
    this._renderInspection();
    this._rebuildCornerHud();
    this._rebuildSidePanels();
    this.rosterModal = {
      team1: t1.slice(),
      team2: t2.slice(),
      assignSide: 1,
      hoveredChar: catalog.find((c) => c.id === t1[0]) || catalog[0] || null,
      factionFilter: null,
      maxPerSide: Math.max(10, t1.length, t2.length),
      galleryScrollY: 0,
      inspectScrollY: 0,
      galleryMaxScroll: 0,
      inspectMaxScroll: 0,
      gallerySplitX: this.w * 0.5,
      node: null,
    };
    this._rebuildOverlay();
  }

  /**
   * True In-Place Physical Card Magnification (ZERO separate jumping detail popup & ZERO height collapse!):
   * The hovered card ITSELF hides its resting miniature (keeping hit area intact) and smoothly magnifies
   * into a full, upright 100% verbatim physical card strictly LARGER in both width and height than resting!
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
      const { card, side, ownerName, anchorX, anchorY, sourceSprite = null } = this.hoveredCard;
      const W = 224;
      const fixedH = Math.min(h - 72, Math.round(W * 1.40));
      const panel = buildFullCard(card, {
        side,
        ownerName,
        showOwner: Boolean(ownerName),
        width: W,
        fixedHeight: fixedH,
        dense: true,
        centered: false,
      });
      const H = panel._boxHeight;

      if (sourceSprite && !sourceSprite.destroyed) {
        sourceSprite.alpha = 0;
        this._hiddenHoverSprite = sourceSprite;
      }

      const targetX = anchorX ?? w * 0.5;
      const targetY = anchorY ?? h * 0.45;
      const px = Math.max(16, Math.min(w - W - 16, targetX - W / 2));
      const maxPy = this.hoveredCard.source === 'board' && this.layout.hasHand
        ? Math.max(48, this.layout.stageBottom - H - 4)
        : h - H - 16;
      const py = Math.max(24, Math.min(maxPy, targetY - H / 2));
      const pivotX = Math.max(px + 24, Math.min(px + W - 24, targetX));
      const pivotY = Math.max(py + 24, Math.min(py + H - 24, targetY));

      const wrap = new PIXI.Container();
      wrap.eventMode = 'none';
      panel.position.set(px, py);
      wrap.addChild(panel);

      wrap.pivot.set(pivotX, pivotY);
      wrap.position.set(pivotX, pivotY);
      wrap.scale.set(0.84);
      wrap.alpha = 0.72;
      this.inspectLayer.addChild(wrap);
      this._inspectAnim = { node: wrap, age: 0, duration: 0.1, startScale: 0.84 };
    }

    if (this.hoveredInfo) {
      const info = this.hoveredInfo;
      const W = 404;
      const body = new PIXI.Container();
      let cy = 38;

      for (const item of info.items || []) {
        const isStatus = info.kind === 'statuses';
        const plate = buildUnifiedEntryPlate({
          variant: isStatus ? 'status' : 'passive',
          title: isStatus ? '' : item.name,
          tagLabel: isStatus ? '' : (item.tagLabel || ''),
          statusName: isStatus ? item.name : '',
          statusValue: isStatus ? item.value : null,
          statusBurst: Boolean(item.burst),
          entries: item.text ? [item.text] : [],
          width: W - 24,
          accentColor: item.color || (isStatus ? undefined : INK.gold),
          fontSize: 12,
          lineHeight: 17.8,
        });
        plate.position.set(12, cy);
        body.addChild(plate);
        cy += plate._height + 6;
      }

      const H = cy + 8;
      // Directly adjacent to the battlefield fighter without covering them
      const tx = info.side === 2
        ? Math.max(16, this.layout.arenaX + this.layout.arenaW - W - 6)
        : Math.min(w - W - 16, this.layout.arenaX + 6);
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
    if (this.banner) {
      const b = buildHitstopBanner({
        text: this.banner.text,
        accentColor: this.banner.color,
        kind: 'clash',
        x: this.w / 2,
        y: 26,
      });
      this.toastLayer.addChild(b);
    }
    if (this.toast) {
      const item = { ...this.toast, y: Math.max(66, this.layout.actionStripY - 26), size: 12.5 };
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
    this.lastPointerX = e.global.x;
    this.lastPointerY = e.global.y;
    if (!this.dragState) return;
    const x = e.global.x;
    const y = e.global.y;
    if (Math.hypot(x - this.dragState.startX, y - this.dragState.startY) > 10) {
      this.dragState.moved = true;
    }
    const dx = x - (this.dragState.prevX ?? x);
    this.dragState.prevX = x;
    this.dragState.x = x;
    this.dragState.y = y;
    const view = this.handCardViews.get(this.dragState.cardKey);
    if (view) {
      view.bodyEntry.targetX = x;
      view.bodyEntry.targetY = y;
      view.bodyEntry.targetAngle = Math.max(-0.14, Math.min(0.14, dx * 0.012));
    }
  }

  _onPointerUp(e) {
    if (!this.dragState) return;
    const d = this.dragState;
    this.dragState = null;
    this._clearCardIntent(d.side);
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

    if (!d.moved && (this.state.mode === 'pre_attack' || this.state.mode === 'intercept')) {
      this.selectedHandCardId = this.selectedHandCardId === d.card.id ? null : d.card.id;
      this._rebuildConfrontationWings();
      this._rebuildDynamicBoard();
      return;
    }

    if (this.state.mode === 'placement') {
      const { battleX, battleW, arenaTop, stageBottom } = this.layout;
      if (x >= battleX - 16 && x <= battleX + battleW + 16 && y >= arenaTop - 24 && y <= stageBottom + 16) {
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
        const vp = this.duelViewport;
        const inDuelVp = !vp || (y >= vp.top - 6 && y <= vp.bottom + 6);
        if (inDuelVp) {
          for (let i = 1; i <= duels.length; i++) {
            const lane = this.regularLaneRects.get(i);
            if (lane && lane.visible !== false && x >= lane.x - 8 && x <= lane.x + lane.w + 8 && y >= lane.y - 8 && y <= lane.y + lane.h + 8) {
              this.audio.cardPlace();
              this._sendAction('attack', { card_id: d.card.id, target: { kind: 'duel', number: i } });
              return;
            }
          }
        }
      }
    }
  }

  _onWheel(e) {
    // 1. O(1) Wheel Scroll for Roster Modal (ZERO rebuild on wheel!)
    if (this.rosterModal) {
      const m = this.rosterModal;
      const inGallery = this.lastPointerX < (m.gallerySplitX || this.w * 0.5);
      if (inGallery && m.galleryMaxScroll > 0) {
        const nextY = Math.max(0, Math.min(m.galleryMaxScroll, (m.galleryScrollY || 0) + e.deltaY * 0.65));
        if (m.node && typeof m.node.setGalleryScroll === 'function') {
          m.galleryScrollY = m.node.setGalleryScroll(nextY);
        } else {
          m.galleryScrollY = nextY;
          this._rebuildOverlay();
        }
        if (this.hoveredCard) {
          this.hoveredCard = null;
          this._renderInspection();
        }
      } else if (!inGallery && m.inspectMaxScroll > 0) {
        const nextY = Math.max(0, Math.min(m.inspectMaxScroll, (m.inspectScrollY || 0) + e.deltaY * 0.65));
        if (m.node && typeof m.node.setInspectScroll === 'function') {
          m.inspectScrollY = m.node.setInspectScroll(nextY);
        } else {
          m.inspectScrollY = nextY;
          this._rebuildOverlay();
        }
        if (this.hoveredCard) {
          this.hoveredCard = null;
          this._renderInspection();
        }
      }
      return;
    }

    // 2. O(1) Wheel Scroll for Pile Modal
    if (this.pileModal) {
      if (this.pileModal.maxScroll > 0) {
        const nextY = Math.max(0, Math.min(this.pileModal.maxScroll, (this.pileModal.scrollY || 0) + e.deltaY * 0.65));
        if (this.pileModal.node && typeof this.pileModal.node.setScroll === 'function') {
          this.pileModal.scrollY = this.pileModal.node.setScroll(nextY);
        } else {
          this.pileModal.scrollY = nextY;
          this._rebuildOverlay();
        }
      }
      return;
    }

    // 3. O(1) Wheel Scroll for Codex Modal
    if (this.codexModal) {
      if (this.codexModal.maxScroll > 0) {
        const nextY = Math.max(0, Math.min(this.codexModal.maxScroll, (this.codexModal.scrollY || 0) + e.deltaY * 0.65));
        if (this.codexModal.node && typeof this.codexModal.node.setScroll === 'function') {
          this.codexModal.scrollY = this.codexModal.node.setScroll(nextY);
        } else {
          this.codexModal.scrollY = nextY;
          this._rebuildOverlay();
        }
      }
      return;
    }

    if (!this.state || this.state.mode === 'handoff' || this.state.mode === 'special_handoff') {
      return;
    }

    // 4. O(1) Wheel Scroll for Active Mode Overlays (draw_select / special / finished)
    if (this._activeOverlayNode?.node) {
      const { kind, node } = this._activeOverlayNode;
      if (kind === 'draw_select' && this.state.mode === 'draw_select') {
        if (typeof node.setScrollX === 'function' && (node._maxScrollX || 0) > 0) {
          const delta = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY;
          this.drawSelectScrollX = node.setScrollX((this.drawSelectScrollX || 0) + delta * 0.75);
          if (this.hoveredCard) {
            this.hoveredCard = null;
            this._renderInspection();
          }
        }
        return;
      }
      if (kind === 'special' && this.state.mode === 'special') {
        if (typeof node.setScroll === 'function' && (node._maxScroll || 0) > 0) {
          this.specialScrollY = node.setScroll((this.specialScrollY || 0) + e.deltaY * 0.65);
        }
        return;
      }
      if (kind === 'finished' && this.state.mode === 'finished') {
        if (typeof node.setScroll === 'function' && (node._maxScroll || 0) > 0) {
          this.finishScrollY = node.setScroll((this.finishScrollY || 0) + e.deltaY * 0.65);
        }
        return;
      }
    }

    if (this.state.mode === 'draw_select') {
      return;
    }

    // 5. O(1) Independent Left/Right Scroll for Top Passive Drawer (P1 left vs P2 right scroll independently!)
    if (this.passiveDrawer && this.passiveDrawer.node) {
      const side = this.lastPointerX < (this.passiveDrawer.splitX || this.w * 0.5) ? 1 : 2;
      const maxS = this.passiveDrawer.maxScrollBySide?.[side] || 0;
      if (maxS > 0) {
        const cur = side === 1 ? (this.passiveDrawer.scrollY1 || 0) : (this.passiveDrawer.scrollY2 || 0);
        this.passiveDrawer.node.setSideScroll(side, cur + e.deltaY * 0.65);
      }
      return;
    }

    // 6. O(1) Smooth Scroll for Active Side-Docked Hero Inspector (when pointer is inside panel!)
    if (this.activeHeroPanel && this.activeHeroPanel.node && this.activeHeroPanel.rect) {
      const m = this.activeHeroPanel;
      const r = m.rect;
      if (this.lastPointerX >= r.x && this.lastPointerX <= r.x + r.w && this.lastPointerY >= r.y && this.lastPointerY <= r.y + r.h) {
        if (m.maxScroll > 0) {
          m.node.setScroll((m.scrollY || 0) + e.deltaY * 0.65);
          if (this.hoveredCard?.source === 'hero_panel') {
            this.hoveredCard = null;
            this._renderInspection();
          }
        }
        return;
      }
    }

    // 7. O(1) Smooth Scroll for 10v10+ Scrollable Fighter Wings (independent Left P1 & Right P2!)
    for (const side of [1, 2]) {
      const vp = this.wingViewports[side];
      const ctl = this._wingScrollCtl[side];
      if (
        vp && ctl && (this.wingMaxScroll[side] || 0) > 0
        && this.lastPointerX >= vp.x - 12 && this.lastPointerX <= vp.x + vp.w + 12
        && this.lastPointerY >= vp.y - 8 && this.lastPointerY <= vp.y + vp.h + 8
      ) {
        ctl.setScroll((this.wingScrollY[side] || 0) + e.deltaY * 0.65);
        return;
      }
    }

    // 8. O(1) Horizontal Scroll for Combat Duel Progress Rail
    const { arenaX, arenaW, arenaTop, stageBottom } = this.layout;
    if (
      this.state.frame?.combat && this._combatRail
      && this.lastPointerX >= arenaX && this.lastPointerX <= arenaX + arenaW
      && this.lastPointerY >= arenaTop - 4 && this.lastPointerY <= arenaTop + 40
    ) {
      const delta = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY;
      this._combatRail.scrollBy(delta * 0.75);
      return;
    }

    // 9. O(1) Smooth Scroll for Center Duel Bridge (① ↓ ② ↓ ③ — NEVER rebuilds hand cards!)
    if (this.lastPointerY > stageBottom + 12) return;
    if (this._duelScrollCtl && this.duelMaxScroll > 0 && !this.state.frame?.combat) {
      this._duelScrollCtl.setScroll(this.duelScrollY + e.deltaY * 0.6);
      if (this.hoveredCard?.source === 'board') {
        this.hoveredCard = null;
        this._renderInspection();
      }
    }
  }

  _onKeyDown(e) {
    if (e.key === 'Tab') {
      if (this.state && this.state.mode !== 'handoff' && this.state.mode !== 'special_handoff' && !this.rosterModal) {
        e.preventDefault();
        this._togglePassiveDrawer();
      }
      return;
    }
    if (e.key === 'Escape') {
      if (this.rosterModal || this.codexModal || this.pileModal) {
        this.rosterModal = null;
        this.codexModal = null;
        this.pileModal = null;
        this.hoveredCard = null;
        this.hoveredInfo = null;
        this._renderInspection();
        this._rebuildOverlay();
        return;
      }
      if (this.activeHeroPanel || this.passiveDrawer) {
        this._closeStageSheets();
      }
      return;
    }
    if (e.key === 'm' || e.key === 'M') {
      this.audio.toggleMute();
      this._rebuildCornerHud();
      return;
    }
    if (e.key === 'r' || e.key === 'R') {
      this.activeHeroPanel = null;
      this.passiveDrawer = null;
      this.codexModal = this.codexModal ? null : { tab: 'rules', scrollY: 0, maxScroll: 0, node: null };
      this._rebuildCornerHud();
      this._rebuildSidePanels();
      this._rebuildOverlay();
      return;
    }
    if ((e.key === ' ' || e.key === 'Enter') && !this.passiveDrawer && !this.rosterModal && !this.codexModal && !this.pileModal) {
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
      const vp = this.duelViewport;
      const clampedY = vp ? Math.max(vp.top + 24, Math.min(vp.bottom - 24, dest.cy)) : dest.cy;
      this.three.emitShockwave(dest.cx, clampedY, SIDE_THEME[side].accent);
      this.three.spawnCardFlipArc({
        fromX: view.bodyEntry.body.position.x,
        fromY: view.bodyEntry.body.position.y,
        toX: dest.cx,
        toY: clampedY,
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

    // 1b. Tick Persistent Spring-Physical Cost HUDs & 2.5D Diegetic Deck Piles at 60fps!
    this.costHuds[1]?.tick(dtSec);
    this.costHuds[2]?.tick(dtSec);
    this.deckPiles[1]?.tick(dtSec);
    this.deckPiles[2]?.tick(dtSec);

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
    const activeFocusId = this.focusedCharId || (this.dragState?.card?.character_id ?? null);
    for (const [charId, node] of this.actorNodes.entries()) {
      if (node.actor && !node.actor.destroyed) {
        if (typeof node.actor.setFocusState === 'function') {
          const isFocused = Boolean(activeFocusId && activeFocusId === charId);
          const isDimmed = Boolean(activeFocusId && activeFocusId !== charId);
          node.actor.setFocusState({ focusBoost: isFocused ? 1 : 0, dimFactor: isDimmed ? 0.45 : 0 });
        }
        node.actor.tick(this.time, this._getMotion(charId), node.liveCh);
      }
    }
    if (this.rosterActors.length) {
      for (const item of this.rosterActors) {
        if (item.actor && !item.actor.destroyed) {
          item.actor.tick(this.time, null, item.ch);
        }
      }
    }
    if (this.sidePanelActors.length) {
      for (const item of this.sidePanelActors) {
        if (item.actor && !item.actor.destroyed) {
          item.actor.tick(this.time, null, item.ch);
        }
      }
    }
    // Gently dim side panels ONLY while dragging a pre-attack card so target fighters underneath shine clearly!
    const dimForAttackDrag = Boolean(this.dragState && this.dragState.moved && this.dragState.canAttack);
    const targetSideAlpha = dimForAttackDrag ? 0.25 : 1;
    if (Math.abs(this.sidePanelsLayer.alpha - targetSideAlpha) > 0.01) {
      this.sidePanelsLayer.alpha += (targetSideAlpha - this.sidePanelsLayer.alpha) * Math.min(1, dtSec * 14);
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
        plate.glowG.roundRect(-2, -2, plate.w + 4, plate.h + 4, 6)
          .fill({ color: INK.goldBg, alpha: t * 0.34 })
          .stroke({ width: 2.2, color: INK.gold, alpha: Math.min(1, t * 1.4 * pulse) });
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

    // 7. Ruina-Style Intelligent Focus Sightlines & Live Drag Choreography (`renderFocusSightlines`)
    const isCombat = Boolean(this.state?.frame?.combat);
    let dragPayload = null;
    if (this.dragState && this.dragState.moved) {
      dragPayload = {
        ...this.dragState,
        charId: this.dragState.card?.character_id || null,
        targetDuelNumber: this.state?.mode === 'placement'
          ? this._findFirstEmptyRegularDuel(this.dragState.side)
          : null,
        targetPreRevealNumber: null,
      };
      if (this.dragState.canIntercept) {
        const pending = new Set(this.state?.pending_responses || []);
        for (const [num, r] of this.preRevealSlotRects.entries()) {
          if (pending.has(num) && this.dragState.x >= r.x - 12 && this.dragState.x <= r.x + r.w + 12 && this.dragState.y >= r.y - 12 && this.dragState.y <= r.y + r.h + 12) {
            dragPayload.targetPreRevealNumber = num;
            break;
          }
        }
      }
    }
    renderFocusSightlines(this.tetherLayer, {
      duels: isCombat ? [] : (this.state?.frame?.duels || []),
      preDuels: isCombat ? [] : (this.state?.frame?.pre_reveal?.duels || []),
      regularSlotRects: this.regularSlotRects,
      preRevealSlotRects: this.preRevealSlotRects,
      actorPosFn: (idOrName) => this._resolveActorPosForSightline(idOrName),
      focusCharId: this.focusedCharId,
      focusDuelNumber: this.focusedDuelNumber,
      dragState: dragPayload,
      duelViewport: this.duelViewport,
      time: this.time,
      themeMap: SIDE_THEME,
    });

    // 8. 60fps Delayed White-Trail HP Bar ticking (`createDelayedHpBar`)
    for (const [charId, hw] of this.hpWidgets.entries()) {
      if (!hw.bar || hw.bar.destroyed) continue;
      hw.bar.tick(dtSec);
      const st = hw.bar.getState();
      this.hpDisplay.set(charId, st.displayHp);
      this.hpTrailState.set(charId, {
        hp: st.displayHp,
        trailHp: st.trailHp,
        lastTargetHp: st.hp,
      });
      if (hw.hpTxt && !hw.hpTxt.destroyed) {
        const label = `${Math.round(st.displayHp)}/${hw.maxHp}`;
        if (hw.hpTxt.text !== label) hw.hpTxt.text = label;
      }
    }

    // 9. Tactile Weighted Hitstop Floating Callouts (`buildHitstopBanner`)
    for (let i = this.floaters.length - 1; i >= 0; i--) {
      const f = this.floaters[i];
      f.age += dtSec;
      f.obj.x += f.vx * dtSec;
      f.obj.y += f.vy * dtSec;
      f.vy *= Math.pow(0.18, dtSec);
      const p = Math.min(1, f.age / f.life);
      if (f.hasHitstop && typeof f.obj.applyHitstopProgress === 'function') {
        f.obj.applyHitstopProgress(p);
      } else {
        f.obj.alpha = Math.max(0, 1 - p * p);
      }
      if (f.age >= f.life) {
        this.fxTextLayer.removeChild(f.obj);
        f.obj.destroy({ children: true });
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
    if (this.autoPace && !this.transport.busy && !this.passiveDrawer && !this.rosterModal && !this.codexModal && !this.pileModal) {
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
