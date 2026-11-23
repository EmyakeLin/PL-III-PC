// Drives the real GameDirector combat-stage method on a hand-built director (no canvas).
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Container, Text } from './pixi_stub.mjs';

const { GameDirector } = await import(new URL('../../battle_ui/static/engine/game_director.js', import.meta.url));

const card = (id, cid, extra = {}) => ({ id, instance_id: `${id}#1`, name: id, cost: 1, character_id: cid, dice: [{ type: 'attack', min: 1, max: 4, position: 1 }], ...extra });

function director(stateExtra = {}) {
  const d = Object.create(GameDirector.prototype);
  Object.assign(d, {
    w: 1600, h: 900,
    layout: { arenaX: 300, arenaW: 1000, arenaTop: 52, showdownBottom: 876, stageBottom: 730, hasHand: false, w: 1600, h: 900, pad: 16 },
    boardLayer: new Container(), duelPeekLayer: new Container(), clashLayer: new Container(),
    clashMedallionCenters: new Map(), combatCardRects: new Map(), effectMarks: [], mirroredIds: new Set(),
    transport: { isRoom: false }, specialMenuOpen: false, selectedHandCardId: null, activeFieldAbilityKey: null,
    sequencer: { isDieScoreConcealed: () => false, isDieOutcomeConcealed: () => false, pendingCombatRollKeys: new Set() },
    _renderInspection() {},
    rebuilds: 0,
  });
  d._rebuildDynamicBoard = () => { d.rebuilds++; };
  d.state = {
    mode: 'combat', character_colors: {}, special_options: [], catalog: [],
    frame: {
      turn: 1, viewer_side: 1,
      players: [{ side: 1, characters: [{ id: 'x', name: 'X' }] }, { side: 2, characters: [{ id: 'y', name: 'Y' }] }],
      pre_reveal: { duels: [] }, special_duels: [],
      duels: [
        { number: 1, sides: [{ side: 1, cards: [card('c', 'x')] }, { side: 2, cards: [card('d', 'y')] }] },
        { number: 2, sides: [{ side: 1, cards: [card('e', 'x')] }, { side: 2, cards: [card('f', 'y')] }] },
      ],
      combat: { kind: 'regular', duel_number: 1, round_id: 1, sides: [
        { side: 1, die: { position: 1, type: 'attack', base_value: 1, final_score: 3 }, die_number: 1, card_id: 'c', card_instance_id: 'c#1' },
        { side: 2, die: { position: 1, type: 'attack', base_value: 1, final_score: 2 }, die_number: 1, card_id: 'd', card_instance_id: 'd#1' },
      ] },
    },
    ...stateExtra,
  };
  return d;
}

const texts = (n, out = []) => { if (n instanceof Text) out.push(n.text); for (const c of n.children || []) texts(c, out); return out; };

test('plain combat: two stage cards, no peek, no rolling words', () => {
  const d = director();
  d._rebuildCombatShowdownStage();
  assert.deepEqual([...d.combatCardRects.keys()].sort(), [1, 2]);
  assert.equal(d.duelPeekLayer.children.length, 0);
  assert.equal(d.combatPeekKey, null);
  const words = [...texts(d.boardLayer), ...texts(d.clashLayer)].join('|');
  for (const w of ['投掷中', '对撞中', '已完成', '待结算']) assert.ok(!words.includes(w), w);
});

test('board effect choice in another duel: that duel auto-pins and its target is marked', () => {
  const d = director({
    effect_choice: { selection: 'board' },
    special_options: [{ effect_target: { zone: 'board', kind: 'regular', number: 2, side: 2, position: 1, card: { instance_id: 'f#1' } } }],
    active_side: 1,
  });
  d._rebuildCombatShowdownStage();
  assert.equal(d.combatPeekKey, 'regular:2');
  assert.equal(d.duelPeekLayer.children.length, 1);
  assert.equal(d.effectMarks.length, 1, 'exactly the targeted card in the pinned duel is selectable');
  assert.equal(d.effectMarks[0].index, 0);
});
