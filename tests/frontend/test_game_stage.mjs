// Run from repo root: node --import ./tests/frontend/register.mjs --test tests/frontend/test_game_stage.mjs tests/frontend/test_director_stage.mjs
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Container, Text } from './pixi_stub.mjs';

const ENGINE = new URL('../../battle_ui/static/engine/', import.meta.url);
const { buildDuelGemTrack, buildActiveDuelStage, collectChronicleDuels } = await import(new URL('combat_timeline.js', ENGINE));
const { analyzeFieldActions, buildFieldActionLayer, fieldDockActions } = await import(new URL('field_action_workspace.js', ENGINE));

const card = (id, cid, extra = {}) => ({ id, instance_id: `${id}#1`, name: id, cost: 1, character_id: cid, dice: [{ type: 'attack', min: 1, max: 4 }], ...extra });
const frame = {
  pre_reveal: { duels: [{ number: 1, sides: [{ side: 1, cards: [card('a', 'x')] }, { side: 2, cards: [card('b', 'y')] }] }] },
  special_duels: [],
  duels: [
    { number: 1, sides: [{ side: 1, cards: [card('c', 'x')] }, { side: 2, cards: [card('d', 'y')] }] },
    { number: 2, sides: [{ side: 1, cards: [card('e', 'x')] }, { side: 2, cards: [card('f', 'y', { hidden: true })] }] },
  ],
};
const combat = { kind: 'regular', duel_number: 1, round_id: 1, sides: [{ side: 1, die: { position: 1 } }, { side: 2, die: { position: 1 } }] };

const allText = (node, out = []) => { if (node instanceof Text) out.push(node.text); for (const c of node.children || []) allText(c, out); return out; };
const gemsOf = (track) => track.children.filter((c) => c.eventMode === 'static');

function makeTrack(extra = {}) {
  const layer = new Container();
  const peekLayer = new Container();
  const track = buildDuelGemTrack({
    layer, peekLayer, frame, combat, arenaX: 300, arenaW: 700, y: 52,
    charNames: { x: 'X', y: 'Y' }, resolveCharColor: () => 0x123456, onHoverCard: () => {}, ...extra,
  });
  return { layer, peekLayer, track };
}

test('duel order: spent, live, queued', () => {
  const items = collectChronicleDuels(frame, combat);
  assert.deepEqual(items.map((i) => i.status), ['completed', 'active', 'upcoming']);
});

test('hovering a queued gem lifts its cards; hovering the live gem does not', () => {
  const { peekLayer, track } = makeTrack();
  const gems = gemsOf(track);
  assert.equal(gems.length, 3);
  gems[2].emit('pointerover');
  assert.equal(peekLayer.children.length, 1, 'queued duel peek shown');
  gems[2].emit('pointerout');
  assert.equal(peekLayer.children.length, 0, 'peek gone on leave');
  gems[1].emit('pointerover');
  assert.equal(peekLayer.children.length, 0, 'live duel has no peek (it is already on stage)');
});

test('pinned gem keeps its peek and exposes board targets; unpinned does not mark', () => {
  const marked = [];
  const pins = [];
  const { peekLayer, track } = makeTrack({
    pinnedKey: 'regular:2',
    choiceTargets: new Map([['regular:2', new Set([4])]]),
    onPinChange: (k) => pins.push(k),
    onPeekTargets: (host, rects, item) => marked.push(...rects.map((r) => `${item.key}:${r.side}:${r.position}`)),
  });
  assert.equal(peekLayer.children.length, 1);
  assert.deepEqual(marked, ['regular:2:1:1', 'regular:2:2:1']);
  const gems = gemsOf(track);
  gems[2].emit('pointerout');
  assert.equal(peekLayer.children.length, 1, 'pinned peek survives pointer leaving');
  gems[2].emit('pointertap');
  gems[0].emit('pointertap');
  gems[1].emit('pointertap');
  assert.deepEqual(pins, [null, 'pre_reveal:1'], 'tap pinned -> unpin, tap other -> pin, live gem ignored');

  const marked2 = [];
  makeTrack({ onPeekTargets: (h, rects) => marked2.push(...rects) });
  assert.equal(marked2.length, 0);
});

test('no web-status words on the track', () => {
  const { layer, peekLayer, track } = makeTrack();
  gemsOf(track)[0].emit('pointerover');
  const words = [...allText(layer), ...allText(peekLayer)].join('|');
  for (const w of ['已完成', '待结算', '回到当前交锋', '开牌前', '常规']) assert.ok(!words.includes(w), w);
});

test('live stage stands both cards face to face; an empty seat is a silent silhouette', () => {
  const both = new Map([[1, card('c', 'x')], [2, card('d', 'y')]]);
  const args = {
    combat, arenaX: 300, arenaW: 700, top: 90, bottom: 640, charNames: {}, resolveCharColor: () => 0x123456,
    pausedLabelFn: () => '', onHoverCard: () => {},
  };
  const l1 = new Container();
  const s1 = buildActiveDuelStage({ ...args, layer: l1, activeCardsBySide: both });
  assert.deepEqual([...s1.combatCardRects.keys()].sort(), [1, 2]);
  assert.ok(s1.combatCardRects.get(1).cx < s1.combatCardRects.get(2).cx);
  assert.ok(s1.combatCardRects.get(1).y >= s1.clashTop + s1.clashH, 'cards sit below the clash zone');

  const l2 = new Container();
  const s2 = buildActiveDuelStage({ ...args, layer: l2, activeCardsBySide: new Map([[1, card('c', 'x')]]) });
  assert.deepEqual([...s2.combatCardRects.keys()], [1]);
  assert.ok(!allText(l2).some((t) => t.includes('无迎击')));
});

test('selected card: one seal per direct action; several attack targets stay on the battlefield', () => {
  const opts = [
    { kind: 'place', card_id: 'k1', duel_number: 2 },
    { kind: 'custom', card_id: 'k1', label: '按牌面打出' },
    { kind: 'attack', card_id: 'k2', character_id: 'e1', label: '用k2进攻E1' },
    { kind: 'attack', card_id: 'k2', character_id: 'e2', label: '用k2进攻E2' },
    { kind: 'attack', card_id: 'k3', character_id: 'e1', label: '用k3进攻E1' },
  ];
  const analysis = analyzeFieldActions(opts);
  const picks = [];
  const seals = (id) => {
    const root = buildFieldActionLayer({ analysis, selectedCardId: id, selectedCardAnchor: { x: 500, y: 500 },
      characterAnchor: () => null, onPickOption: (i) => picks.push(i), onArmAbility: () => {} });
    return root.children[0].children;
  };
  const k1 = seals('k1');
  assert.equal(k1.length, 2);
  k1[0].emit('pointertap'); k1[1].emit('pointertap');
  assert.deepEqual(picks, [0, 1]);
  assert.equal(seals('k2').length, 0, 'two attack targets: pick on the battlefield');
  const k3 = seals('k3');
  assert.equal(k3.length, 1);
  k3[0].emit('pointertap');
  assert.equal(picks.at(-1), 4);
});

test('ability sigils: self ability fires, targeted ability arms then disarms', () => {
  const opts = [
    { kind: 'ability', character_id: 'h', ability_id: 'a1', label: '自愈' },
    { kind: 'ability', character_id: 'h', ability_id: 'a2', label: '窥探', effect_target: { zone: 'board', kind: 'regular', number: 1, side: 2, position: 1 } },
  ];
  const analysis = analyzeFieldActions(opts);
  const picks = []; const arms = [];
  const build = (activeAbilityKey) => buildFieldActionLayer({ analysis, activeAbilityKey,
    characterAnchor: () => ({ x: 200, y: 300 }), onPickOption: (i) => picks.push(i), onArmAbility: (k) => arms.push(k) }).children[0].children;
  const s = build(null);
  assert.equal(s.length, 2);
  assert.ok(s.every((n) => n.y < 300), 'sigils hang above the owner');
  s[0].emit('pointertap'); s[1].emit('pointertap');
  assert.deepEqual(picks, [0]);
  assert.deepEqual(arms, ['h:a2']);
  build('h:a2')[1].emit('pointertap');
  assert.deepEqual(arms, ['h:a2', null]);
});

test('dock actions: leave only when no attack is pending; long labels are shortened', () => {
  const analysis = analyzeFieldActions([
    { kind: 'pass_intercept', response_number: 2 },
    { kind: 'decline', label: '让过这一次即时进攻并结束回应' },
  ]);
  const base = { onPickOption() {}, onSwitchSide() {}, onLeave() {} };
  const free = fieldDockActions(analysis, base).map((b) => b.label);
  const pending = fieldDockActions(analysis, { ...base, pendingAttack: true }).map((b) => b.label);
  assert.equal(free[0], '返回战场');
  assert.ok(!pending.includes('返回战场'));
  assert.ok(pending.includes('放行即时 2'));
  assert.ok(pending.some((l) => l.endsWith('…') && l.length === 10));
});
