import assert from 'node:assert/strict';
import { test } from 'node:test';
import { GameDirector } from '../../battle_ui/static/engine/game_director.js';
import { Container, Text } from './pixi_stub.mjs';

function battleState(statuses, mode = 'combat') {
  const fighter = { id: 'fighter', name: '林恩', alive: true, hp: 8, max_hp: 8, statuses };
  return {
    mode,
    started: true,
    match_number: 1,
    frame: {
      turn: 1,
      players: [
        { side: 1, name: '玩家一', characters: [fighter] },
        { side: 2, name: '玩家二', characters: [] },
      ],
    },
  };
}

function directorFor(state) {
  const director = Object.create(GameDirector.prototype);
  Object.assign(director, {
    state,
    time: 0,
    layout: { w: 1000, h: 540, pad: 16, arenaTop: 52, stageBottom: 390, leftWingX: 16, rightWingX: 744, wingW: 240 },
    transport: { isRoom: false },
    worldRoot: new Container(), wingsLayer: new Container(), actorsLayer: new Container(),
    inspectLayer: new Container(), statusPreviewLayer: new Container(),
    mirroredIds: new Set(), drawSelected: new Set(),
    charRects: new Map(), actorNodes: new Map(), actorMotion: new Map(),
    hpWidgets: new Map(), hpDisplay: new Map(), hpTrailState: new Map(),
    lightcoreWidgets: new Map(), lightcoreTrailState: new Map(), lightcoreRevealAlpha: new Map(),
    _wingHeadRefs: new Map(), _fighterFloorDrawers: new Map(), passivePlates: new Map(), _fighterSpeedRefs: [],
    costHuds: {}, deckPiles: {}, wingScrollY: { 1: 0, 2: 0 }, wingMaxScroll: {},
    fxDirector: { sync() {} },
    three: { setIntentFocus() {}, setPhaseTint() {}, setCombatFocus() {} },
    sequencer: {
      deferredHpOverrides: new Map(), deferredLightcoreOverrides: new Map(), deferredActorStateOverrides: new Map(),
      prepareBeat: () => ({ fresh: [{ kind: 'combat_strike' }] }), playBeat() {},
    },
    _positionPersistentHud() {}, _computeLayout() {}, _syncTopBar() {},
    _rebuildDynamicBoard() {}, _rebuildSidePanels() {}, _rebuildOverlay() {},
  });
  director.worldRoot.addChild(director.wingsLayer, director.actorsLayer);
  return director;
}

function allTexts(node) {
  const ownText = node instanceof Text ? [node.text] : [];
  return ownText.concat(node.children.flatMap(allTexts));
}

test('fighter badges use a second row at the exact height threshold and place stored dice below it', () => {
  const statuses = { 烧伤: 2, 裂血: 2, 失衡: 2, 充能: 2, 纯能: 2, 能源: 2, 强壮: 2 };
  const state = battleState(statuses);
  const fighter = state.frame.players[0].characters[0];
  fighter.shields = { normal: 3, reinforced: 2 };
  fighter.stored_dice = { 余形: { turn: 1, label: '折返', die: { type: 'slash' } } };
  const slot = { x: 120, y: 132, rawY: 132, actorR: 20, hudW: 134, slotTop: 104, visible: true };

  const shortDirector = directorFor(state);
  const short = shortDirector._buildOpenBattlefieldFighter(fighter, 1, { ...slot, slotH: 145 }, 1);
  assert.equal(new Set(short.statusOverlayHost.children.map(chip => chip.y)).size, 1);
  assert.ok(allTexts(short.statusOverlayHost).includes('+5'));

  const tallDirector = directorFor(state);
  const tall = tallDirector._buildOpenBattlefieldFighter(fighter, 1, { ...slot, slotH: 146 }, 1);
  const badges = tall.statusOverlayHost.children;
  assert.equal(new Set(badges.map(chip => chip.y)).size, 2);
  assert.equal(badges.length, 7);
  assert.ok(badges.every(chip => chip.x + 18 <= 134));
  const hud = tallDirector.wingsLayer.children.at(-1);
  const stored = hud.children.find(node => node instanceof Text && node.text.includes('余形'));
  assert.ok(stored.y > badges.at(-1).y + 18);
  assert.ok(tall.charRect.h > short.charRect.h);
});

test('a narrow fighter bar keeps a preview entry for effects crowded out by shields', () => {
  const state = battleState({ 烧伤: 2, 裂血: 3 });
  const fighter = state.frame.players[0].characters[0];
  fighter.shields = { normal: 3, reinforced: 2, concept: 1 };
  const director = directorFor(state);
  const slot = { x: 120, y: 132, rawY: 132, actorR: 20, hudW: 86, slotTop: 104, slotH: 86, visible: true };
  const { statusOverlayHost: bar } = director._buildOpenBattlefieldFighter(fighter, 1, slot, 1);
  assert.deepEqual(allTexts(bar), ['+3']);
  assert.ok(bar.children[0].x + 18 <= slot.hudW);
  bar._handlers.pointerover[0]({ global: { x: bar.x + 74, y: bar.y + bar.hitArea.y + 8 } });
  const previewTexts = allTexts(director.statusPreview.node);
  assert.ok(previewTexts.includes('烧伤 2'));
  assert.ok(previewTexts.includes('裂血 3'));
  assert.ok(previewTexts.includes('概念护盾 1'));
});

test('status hover and scroll survive rebuilt fighters and follow the visible effects through impact', () => {
  const statuses = Object.fromEntries(Array.from({ length: 18 }, (_, index) => [`状态${index + 1}`, 1]));
  const state = battleState(statuses);
  const director = directorFor(state);
  director._rebuildConfrontationWings();
  const bar = director.actorsLayer.children.find(node => node.hitArea && node.children.length);
  const origin = bar.getGlobalPosition();
  const point = { x: origin.x + 8, y: origin.y + bar.hitArea.y + 8 };
  bar._handlers.pointerover[0]({ global: point });
  director._onPointerMove({ global: point });
  const before = director.statusPreview.node;
  assert.ok(before._maxScroll > 0);
  assert.ok(before.y + before._height <= director.layout.h - director.layout.pad);
  director._onWheel({ deltaY: 110 });
  const scroll = before.getScroll();
  assert.ok(scroll > 0);

  const afterImpact = battleState({ ...statuses, 状态1: 3 });
  director.sequencer.deferredActorStateOverrides.set('fighter', { alive: true, shields: {}, statuses });
  director.applyState(afterImpact);
  assert.equal(director.statusPreview.node, before);
  assert.notEqual(director.statusHover.source.node, bar);
  director.statusHover.source.node.emit('pointerout', { global: point });
  director._renderInspection();
  director._onPointerMove({ global: point });
  assert.equal(director.statusPreview.node, before);

  director.sequencer.deferredActorStateOverrides.clear();
  director._releaseDeferredVitals({ rebuildActors: true });
  const after = director.statusPreview.node;
  assert.ok(allTexts(after).includes('状态1 3'));
  assert.equal(after.getScroll(), scroll);
  director._onPointerMove({ global: { x: after.x + 12, y: after.y + 12 } });
  assert.equal(director.statusPreview.node, after);
  director._onPointerMove({ global: { x: 980, y: 50 } });
  assert.equal(director.statusPreview, null);

  const nextBar = director.actorsLayer.children.find(node => node.hitArea && node.children.length);
  nextBar._handlers.pointerover[0]({ global: point });
  assert.ok(director.statusPreview);
  director.applyState(battleState({}));
  assert.equal(director.statusPreview, null);

  director.applyState(battleState(statuses));
  const restoredBar = director.actorsLayer.children.find(node => node.hitArea && node.children.length);
  restoredBar._handlers.pointerover[0]({ global: point });
  assert.ok(director.statusPreview);
  director.applyState(battleState(statuses, 'handoff'));
  assert.equal(director.statusPreview, null);
});
