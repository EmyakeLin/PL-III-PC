import assert from 'node:assert/strict';
import { test } from 'node:test';
import { GameDirector } from '../../battle_ui/static/engine/game_director.js';
import { buildRosterOverlay } from '../../battle_ui/static/engine/table_overlays.js';
import { roomTableState } from '../../battle_ui/static/engine/transport.js';

const catalog = [
  { id: 'c1', name: '林恩', rank: 'NORMAL', max_hp: 6, skills: [] },
  { id: 'c2', name: '赫利斯', rank: 'NORMAL', max_hp: 8, skills: [] },
];

function galleryCard(overlay, characterId) {
  return overlay._actors.find(({ ch, card }) => card && ch.id === characterId).card;
}

function cardEvent(card) {
  const { x, y } = card.getGlobalPosition();
  return { global: { x: x + 12, y: y + 12 }, stopPropagation() {} };
}

test('gallery card and detail button dispatch the same roster action', () => {
  const picks = [];
  const previews = [];
  const overlay = buildRosterOverlay(1280, 800, {
    catalog,
    assignSide: 2,
    hoveredChar: catalog[1],
    roomLobby: { editableSides: [1, 2], sideNames: { 2: '电脑阵容' } },
    onHoverChar: char => previews.push(char.id),
    onInspectChar: char => previews.push(char.id),
    onToggleChar: id => picks.push(id),
  });
  const card = galleryCard(overlay, 'c2');
  const event = cardEvent(card);
  card._handlers.pointerover[0]({ ...event, buttons: 1 });
  assert.deepEqual(previews, []);
  card._handlers.pointerover[0](event);
  assert.deepEqual(previews, ['c2']);
  assert.deepEqual(picks, []);

  card._handlers.pointertap[0]({ ...event, global: { x: 0, y: 0 } });
  assert.deepEqual(picks, []);
  card._handlers.pointertap[0](event);
  assert.deepEqual(picks, ['c2']);
  assert.deepEqual(previews, ['c2']);

  card._handlers.pointertap[0]({ stopPropagation() {} });
  assert.deepEqual(picks, ['c2', 'c2']);

  const detailButton = overlay.children.find(node => node.accessibleTitle === '+ 编入电脑阵容');
  detailButton._handlers.pointertap[0](event);
  assert.deepEqual(picks, ['c2', 'c2', 'c2']);
});

test('room gallery card appends an allowed duplicate to the active team', () => {
  const commands = [];
  const state = roomTableState({
    side: 1,
    bot_side: 2,
    started: false,
    frame: { players: [] },
    lobby_state: {
      picks: { 1: ['c2'], 2: ['c1'] },
      ruleset: { duplicate_policy: 'free_duplicates', pick_mode: 'open', max_chars: null },
    },
  }, { roster_catalog: catalog });
  const director = Object.assign(Object.create(GameDirector.prototype), {
    state,
    lobbyUi: { assignSide: 2, hoveredChar: catalog[1] },
    audio: { coinClink() {} },
    fxDirector: { hasPreviewableFx: () => false },
    _renderInspection() {},
    _rebuildOverlay() {},
    _sendAction: (action, payload) => commands.push({ action, payload }),
  });
  const overlay = director._buildLiveRoomLobbyOverlay(1280, 800);
  const card = galleryCard(overlay, 'c1');
  card._handlers.pointertap[0](cardEvent(card));

  assert.deepEqual(commands, [{ action: 'update_team', payload: { target_side: 2, team: ['c1', 'c1'] } }]);
  assert.equal(director.lobbyUi.hoveredChar.id, 'c1');
  assert.deepEqual(state.lobby_state.picks[2], ['c1']);
});

test('gallery card can still show details when team changes are blocked', () => {
  const blockedRooms = [
    { editableSides: [1], lockedIds: ['c1'] },
    { editableSides: [] },
    { editableSides: [1], ruleset: { duplicate_policy: 'strict_unique', max_chars: null } },
    {
      editableSides: [1],
      isOnline: true,
      draftTurnSide: 2,
      ruleset: { duplicate_policy: 'free_duplicates', pick_mode: 'draft', max_chars: null },
    },
  ];
  for (const roomLobby of blockedRooms) {
    const previews = [];
    const overlay = buildRosterOverlay(1280, 800, {
      catalog,
      team1: roomLobby.draftTurnSide ? ['c1'] : [],
      team2: ['c1'],
      roomLobby,
      onHoverChar: char => previews.push(char.id),
      onToggleChar: id => assert.fail(`Blocked character was selected: ${id}`),
    });
    const card = galleryCard(overlay, 'c1');
    card._handlers.pointertap[0](cardEvent(card));
    assert.deepEqual(previews, ['c1']);
  }
});
