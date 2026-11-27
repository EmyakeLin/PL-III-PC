// Drives the real GameDirector combat-stage method on a hand-built director (no canvas).
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Container, Text } from './pixi_stub.mjs';

const { GameDirector } = await import(new URL('../../battle_ui/static/engine/game_director.js', import.meta.url));
const { CombatTabletop } = await import(new URL('../../battle_ui/static/engine/combat_tabletop.js', import.meta.url));

const card = (id, cid, extra = {}) => ({ id, instance_id: `${id}#1`, name: id, cost: 1, character_id: cid, dice: [{ type: 'slash', level: 1, roll_max: 4, position: 1 }], ...extra });

function director(stateExtra = {}) {
  const d = Object.create(GameDirector.prototype);
  const tabletopLayer = new Container();
  Object.assign(d, {
    w: 1600, h: 900,
    layout: { arenaX: 300, arenaW: 1000, arenaTop: 52, showdownBottom: 876, stageBottom: 730, hasHand: false, w: 1600, h: 900, pad: 16 },
    boardLayer: new Container(), duelPeekLayer: new Container(), clashLayer: new Container(), tabletopLayer,
    clashMedallionCenters: new Map(), combatCardRects: new Map(), regularLaneRects: new Map(), preRevealSlotRects: new Map(),
    effectMarks: [], mirroredIds: new Set(), lastPointerX: 800, lastPointerY: 450,
    transport: { isRoom: false }, specialMenuOpen: false, selectedHandCardId: null, activeFieldAbilityKey: null, dragState: null, localQueuedAction: null,
    sequencer: { isDieScoreConcealed: () => false, isDieOutcomeConcealed: () => false, pendingCombatRollKeys: new Set(), isRollAnimating: false },
    _renderInspection() {},
    rebuilds: 0,
  });
  d.tabletop = new CombatTabletop(tabletopLayer, {
    resolveCharColor: () => 0xc8452e,
    getCharName: (cid) => cid,
    markEffectTarget: (parent, kind, number, side, position, x, y, width, height, lane) =>
      d._markEffectTarget(parent, kind, number, side, position, x, y, width, height, lane),
  });
  d._rebuildDynamicBoard = () => { d.rebuilds++; };
  d.state = {
    mode: 'combat', character_colors: {}, special_options: [], inline_special_options: [], catalog: { players: [] },
    frame: {
      turn: 1, viewer_side: 1, cards_revealed: true,
      players: [{ side: 1, characters: [{ id: 'x', name: 'X' }] }, { side: 2, characters: [{ id: 'y', name: 'Y' }] }],
      pre_reveal: { duels: [] }, special_duels: [],
      duels: [
        { number: 1, sides: [{ side: 1, cards: [card('c', 'x')] }, { side: 2, cards: [card('d', 'y')] }] },
        { number: 2, sides: [{ side: 1, cards: [card('e', 'x')] }, { side: 2, cards: [card('f', 'y')] }] },
      ],
      combat: { kind: 'regular', duel_number: 1, round_id: 1, sides: [
        { side: 1, die: { position: 1, type: 'slash', base_value: 1, final_score: 3 }, die_number: 1, card_id: 'c', card_instance_id: 'c#1' },
        { side: 2, die: { position: 1, type: 'slash', base_value: 1, final_score: 2 }, die_number: 1, card_id: 'd', card_instance_id: 'd#1' },
      ] },
    },
    ...stateExtra,
  };
  return d;
}

const texts = (n, out = []) => { if (n instanceof Text) out.push(n.text); for (const c of n.children || []) texts(c, out); return out; };

test('plain combat: two stage cards on persistent tabletop, no rolling filler words', () => {
  const d = director();
  d._rebuildCombatShowdownStage();
  assert.deepEqual([...d.combatCardRects.keys()].sort(), [1, 2]);
  const words = [...texts(d.tabletopLayer), ...texts(d.clashLayer)].join('|');
  for (const w of ['投掷中', '对撞中', '已完成', '待结算']) assert.ok(!words.includes(w), w);
});

test('board effect choice in another duel: target card in that duel is directly marked on tabletop', () => {
  const d = director({
    effect_choice: { selection: 'board' },
    special_options: [{ effect_target: { zone: 'board', kind: 'regular', number: 2, side: 2, position: 1, card: { instance_id: 'f#1' } } }],
    active_side: 1,
  });
  d._rebuildCombatShowdownStage();
  assert.equal(d.effectMarks.length, 1, 'exactly the targeted card in duel 2 is selectable on tabletop');
  assert.equal(d.effectMarks[0].index, 0);
});
