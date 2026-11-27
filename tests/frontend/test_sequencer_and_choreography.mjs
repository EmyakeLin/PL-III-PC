// Deterministic tests for TimelineSequencer state machine, causal ordering, and FxDirector impactMs timing.
import assert from 'node:assert/strict';
import { test } from 'node:test';

const ENGINE = new URL('../../battle_ui/static/engine/', import.meta.url);
const { TimelineSequencer, normalizeBeatEvents } = await import(new URL('timeline_sequencer.js', ENGINE));
const { FxDirector } = await import(new URL('fx_director.js', ENGINE));

test('normalizeBeatEvents keeps cost_pay, shield_gain, status_change and passive_trigger strictly before combat_strike', () => {
  const raw = [
    { seq: 1, kind: 'cost_pay', paid: true },
    { seq: 2, kind: 'passive_trigger', passive_name: '拔芯' },
    { seq: 3, kind: 'shield_gain', amount: 2 },
    { seq: 4, kind: 'damage', hp_lost: 3, cause: 'attack' },
    { seq: 5, kind: 'combat_strike', die_type: 'slash' },
    { seq: 6, kind: 'damage', hp_lost: 2, cause: '烧伤' },
  ];
  const out = normalizeBeatEvents(raw);
  assert.deepEqual(
    out.map((e) => e.seq),
    [1, 2, 3, 5, 4, 6],
    'Pre-hit cost/passive/shield stay before combat_strike; only hit damages follow combat_strike!'
  );
});

test('TimelineSequencer retires stale round dice without dead-air freeze, preserves in-flight roll on non-mutating refresh, and retires withdrawn die on blank-round replace', () => {
  const scheduled = [];
  let retiredRounds = [];
  let retiredSides = [];
  let releasedVitalsAt = null;
  let nowMs = 0;

  const seq = new TimelineSequencer({
    schedule: (fn, ms) => {
      const item = { fn, due: nowMs + ms, cancelled: false };
      scheduled.push(item);
      return item;
    },
    cancel: (item) => { item.cancelled = true; },
    retireStaleDice: (rk) => retiredRounds.push(rk),
    retireSideDice: (side, lane) => retiredSides.push(`${side}:${lane}`),
    clearClashGroups: () => {},
    playDiceRoll: (_ev, { onNumbersRevealed }) => {
      scheduled.push({ fn: onNumbersRevealed, due: nowMs + 300, cancelled: false });
    },
    playFx: (ev) => (ev.kind === 'combat_strike' ? { impactMs: 140, durationMs: 280 } : null),
    releaseDeferredVitals: () => { releasedVitalsAt = nowMs; },
  });

  const makeState = (roundId, p1Card, fxEvents, p2Hp = 15) => ({
    frame: {
      turn: 1,
      players: [
        { side: 1, characters: [{ id: 'a', hp: 12, lightcore_hp: 16, max_lightcore_hp: 16 }] },
        { side: 2, characters: [{ id: 'b', hp: p2Hp, lightcore_hp: 16, max_lightcore_hp: 16 }] },
      ],
      combat: {
        kind: 'regular',
        duel_number: 1,
        round_id: roundId,
        sides: [
          { side: 1, card_id: p1Card, card_instance_id: p1Card, die_number: 1, die: { position: 1, rolled_value: 5 } },
          { side: 2, card_id: 'enemy', card_instance_id: 'enemy', die_number: roundId, die: { position: roundId, rolled_value: 3 } },
        ],
      },
    },
    fx_events: fxEvents,
  });

  const s0 = makeState(1, 'cardA', []);
  seq.playBeat(seq.prepareBeat({ prevState: null, nextState: s0, isInitial: true }));

  // Round 1 roll starts -> retires any stale dice immediately
  const rollEv = { seq: 1, turn: 1, kind: 'dice_roll', duel_kind: 'regular', duel_number: 1, round_id: 1, sides: [{ side: 1, die_number: 1, rolled_value: 5 }] };
  const s1 = makeState(1, 'cardA', [rollEv]);
  const plan1 = seq.prepareBeat({ prevState: s0, nextState: s1, characterKeyFn: (id) => id });
  seq.playBeat(plan1);
  assert.equal(seq.isRollAnimating, true);
  assert.deepEqual(retiredRounds, ['1:regular:1:1']);

  // Mid-roll non-mutating state update (e.g. player queues a pre-declaration or pauses!) -> MUST keep in-flight roll & concealment alive!
  const s1Refresh = makeState(1, 'cardA', [rollEv]);
  const planRefresh = seq.prepareBeat({ prevState: s1, nextState: s1Refresh, characterKeyFn: (id) => id });
  assert.equal(planRefresh.keepRunning, true);
  seq.playBeat(planRefresh);
  assert.equal(seq.isRollAnimating, true, 'In-flight roll concealment must NOT be wiped by non-mutating state refresh!');

  // Blank-round card replacement on Side 1 (`cardA` -> `cardB`) in Round 1 -> immediately retires Side 1's 3D die!
  const s1Replaced = makeState(1, 'cardB', [rollEv]);
  seq.prepareBeat({ prevState: s1Refresh, nextState: s1Replaced, characterKeyFn: (id) => id });
  assert.deepEqual(retiredSides, ['1:front']);

  // Strike with custom `impactMs = 140` releases deferred HP bars at exact arrival frame `140ms` (not hardcoded 130ms)!
  const strikeEvents = [
    rollEv,
    { seq: 2, turn: 1, kind: 'combat_strike', die_type: 'pierce', attacker_id: 'a', attacker_side: 1, target_id: 'b', target_side: 2 },
    { seq: 3, turn: 1, kind: 'damage', target_id: 'b', target_side: 2, hp_lost: 4 },
  ];
  const sHit = makeState(2, 'cardB', strikeEvents, 11);
  const hitPlan = seq.prepareBeat({ prevState: s1Replaced, nextState: sHit, characterKeyFn: (id) => id });
  assert.equal(seq.deferredHpOverrides.get('b'), 15, 'Defender HP held at pre-hit 15 until strike impact lands');
  seq.playBeat(hitPlan);
  const impactTimer = scheduled.find((t) => !t.cancelled && t.due === 140);
  assert.ok(impactTimer, 'Expected strike impact timer scheduled at exact impactMs = 140ms');
  nowMs = 140;
  impactTimer.fn();
  assert.equal(releasedVitalsAt, 140);
});

test('FxDirector separates windup attacker lunge at t=0 from defender recoil/shake at impactMs', () => {
  const motions = { a: { lunge: 0, recoil: 0, hitFlash: 0 }, b: { lunge: 0, recoil: 0, hitFlash: 0 } };
  const deferred = [];
  let shookAt = null;
  let now = 0;

  const fx = new FxDirector({
    three: { spawnPierceLance() {}, spawnImpactBurst() {} },
    physics: {},
    audio: { playSynthRecipe() {} },
    getActorNode: () => null,
    getActorPos: () => ({ x: 100, y: 100 }),
    getMotion: (id) => motions[id],
    deferFx: (fn, ms) => deferred.push({ fn, due: now + ms }),
    getClashCenter: () => ({ x: 200, y: 200 }),
    triggerShake: () => { shookAt = now; },
  });

  const res = fx.playRecipe({
    vfx: [{ primitive: 'pierce_lance', from: 'attacker.bone_weapon', to: 'defender.center', color: '#d95724' }],
    motion: { lunge: 1.1, recoil: 0.9, hitFlash: 0.95 },
    camera: { shake: 6, duration_ms: 200 },
  }, { attackerId: 'a', defenderId: 'b', attackerSide: 1, defenderSide: 2 });

  assert.ok(res && res.ran);
  assert.equal(res.impactMs, 135);
  assert.equal(motions.a.lunge, 1.1, 'Attacker lunges immediately at t=0');
  assert.equal(motions.b.recoil, 0, 'Defender does NOT recoil prematurely at t=0 while lance is still mid-flight');
  assert.equal(shookAt, null);

  assert.equal(deferred.length, 1);
  now = deferred[0].due;
  deferred[0].fn();
  assert.equal(now, 135);
  assert.equal(motions.b.recoil, 0.9, 'Defender recoils right at impactMs = 135ms');
  assert.equal(motions.b.hitFlash, 0.95);
  assert.equal(shookAt, 135);
});

test('roomTableState exposes inline_special_options, rear_targets, declarations and timers without hijacking combat mode', async () => {
  const { roomTableState } = await import(new URL('transport.js', ENGINE));
  const baseFrame = {
    turn: 1,
    mode: 'combat',
    phase: 'combat',
    is_over: false,
    timing: '骰子使用后',
    players: [
      { side: 1, characters: [{ id: 'c1', name: '甲' }], hand: [{ id: 'h1', name: '快剑' }] },
      { side: 2, characters: [{ id: 'c2', name: '乙' }], hand: null },
    ],
  };

  // Ambient live special options during online PvP combat MUST stay in `combat` mode (not hijacked to `special`!)
  const liveCombat = roomTableState({
    started: true,
    side: 1,
    paused_by: null,
    has_special_actions: true,
    beat_duration_ms: 2600,
    beat_remaining_ms: 1850,
    pause_bank_ms: 20000,
    pause_remaining_ms: null,
    declarations: [{ id: 'p1', event: 'timing', mode: 'execute', match: { kind: 'special_place', card_id: 'h1' } }],
    frame: baseFrame,
    options: [
      { id: 'm1', kind: 'special_place', card_id: 'h1' },
      { id: 'm2', kind: 'special_replace', card_id: 'h1', effect_target: { zone: 'board', kind: 'regular', number: 1, side: 1, lane: 'front', position: 1 } },
      { id: 'm3', kind: 'special_ability', character_id: 'c1', ability_id: 'ab1', label: '甲 · 凝神', target_card_id: 'h1' },
    ],
  }, {});

  assert.equal(liveCombat.mode, 'combat');
  assert.equal(liveCombat.special_options.length, 0, 'Unpaused ambient specials keep modal special_options empty');
  assert.equal(liveCombat.inline_special_options.length, 3, 'Live specials exposed in inline_special_options');
  assert.equal(liveCombat.inline_special_options[0].kind, 'place');
  assert.equal(liveCombat.table_actions.length, 1);
  assert.equal(liveCombat.declarations.length, 1);
  assert.equal(liveCombat.beat_duration_ms, 2600);
  assert.equal(liveCombat.pause_bank_ms, 20000);

  // Mandatory reservation (`decline`) or `special_pass_intercept` DOES enter `special` mode
  const reserved = roomTableState({
    started: true,
    side: 1,
    paused_by: null,
    has_special_actions: true,
    frame: baseFrame,
    options: [
      { id: 'm1', kind: 'special_place', card_id: 'h1' },
      { id: 'm4', kind: 'decline', label: '让过预留时机' },
    ],
  }, {});
  assert.equal(reserved.mode, 'special');
  assert.equal(reserved.special_options.length, 2);

  // Placement rear targets mapped cleanly
  const placementRear = roomTableState({
    started: true,
    side: 1,
    paused_by: null,
    frame: { ...baseFrame, mode: 'placement', phase: 'placement' },
    options: [
      { id: 'e1', kind: 'end' },
      { id: 'r1', kind: 'place_rear', card_id: 'h1', duel_number: 1 },
      { id: 'r2', kind: 'place_rear', card_id: 'h1', duel_number: 2 },
    ],
  }, {});
  assert.equal(placementRear.mode, 'placement');
  assert.deepEqual(placementRear.legal_rear_cards, ['h1']);
  assert.deepEqual(placementRear.rear_targets.h1, [1, 2]);
});

test('field_action_workspace renders Chinese captions on seals, supports includeAbilities=false, and keys 5-segment board targets', async () => {
  const { Text } = await import('./pixi_stub.mjs');
  const { analyzeFieldActions, resolveFieldHighlights, buildFieldActionLayer } = await import(new URL('field_action_workspace.js', ENGINE));
  const collectTexts = (node, out = []) => {
    if (node instanceof Text) out.push(node.text);
    for (const ch of node.children || []) collectTexts(ch, out);
    return out;
  };

  const analysis = analyzeFieldActions([
    { kind: 'ability', character_id: 'c1', ability_id: 'ab1', label: '澜清 · 深秋工作室' },
    { kind: 'place', card_id: 'h1', duel_number: 1 },
    { kind: 'replace', card_id: 'h1', label: '替换交锋1', effect_target: { zone: 'board', kind: 'regular', number: 1, side: 1, lane: 'rear', position: 1 } },
  ]);

  const inlineArc = buildFieldActionLayer({
    analysis,
    selectedCardId: 'h1',
    selectedCardAnchor: { x: 400, y: 500 },
    includeAbilities: false,
    characterAnchor: () => ({ x: 180, y: 260 }),
    onPickOption: () => {},
    onArmAbility: () => {},
  });
  const seals = inlineArc.children[0].children;
  assert.equal(seals.length, 2, 'includeAbilities=false omits character sigil and renders only the 2 selected-card seals');
  const captions = collectTexts(inlineArc);
  assert.ok(captions.includes('置入1'), `Expected '置入1' caption, got ${captions.join(',')}`);
  assert.ok(captions.includes('换卡'), `Expected '换卡' caption, got ${captions.join(',')}`);

  const hl = resolveFieldHighlights(analysis, { selectedCardId: 'h1' });
  assert.equal(hl.boardCardTargets.get('regular:1:1:rear:1'), 2);
});

test('roomTableState maps unified lobby, hotseat handoff curtain, unlimited pause_bank_ms, and disconnect claim flags', async () => {
  const { roomTableState } = await import(new URL('transport.js', ENGINE));
  const baseFrame = {
    turn: 1,
    mode: 'placement',
    phase: 'placement',
    is_over: false,
    players: [
      { side: 1, characters: [{ id: 'c1', name: '甲' }], hand: [] },
      { side: 2, characters: [{ id: 'c2', name: '乙' }], hand: [] },
    ],
  };

  const lobby = roomTableState({
    started: false,
    side: 1,
    ready: false,
    room_code: 'K7P9M2',
    is_host: true,
    frame: baseFrame,
    options: [],
  }, {});
  assert.equal(lobby.mode, 'lobby');
  assert.deepEqual(lobby.editable_sides, [1]);

  const hotseatHandoff = roomTableState({
    started: true,
    side: 2,
    hotseat: true,
    hotseat_handoff_side: 2,
    eligible_sides: [1, 2],
    pause_bank_ms: null,
    can_reopen_lobby: true,
    can_concede: true,
    can_claim_disconnect_win: false,
    frame: baseFrame,
    options: [],
  }, {});
  assert.equal(hotseatHandoff.mode, 'handoff');
  assert.equal(hotseatHandoff.active_side, 2);
  assert.equal(hotseatHandoff.pause_bank_ms, null);
  assert.equal(hotseatHandoff.can_reopen_lobby, true);
  assert.equal(hotseatHandoff.can_concede, true);
});

test('buildRosterOverlay renders blind-pick masking, power caps, and room rules panel with card-game wording', async () => {
  const { Text } = await import('./pixi_stub.mjs');
  const { buildRosterOverlay, buildMatchMenuOverlay } = await import(new URL('table_overlays.js', ENGINE));
  const collectTexts = (node, out = []) => {
    if (node instanceof Text) out.push(node.text);
    for (const ch of node.children || []) collectTexts(ch, out);
    return out;
  };

  const catalog = [
    { id: 'c1', name: '林恩', rank: 'NORMAL', power: 1, max_hp: 15, base_duels: 1, skills: [], passives: [] },
    { id: 'c2', name: '赫利斯', rank: 'BOSS', power: 3, max_hp: 30, base_duels: 2, skills: [], passives: [] },
  ];
  const ruleset = {
    power_cap: 5,
    max_chars: 3,
    duplicate_policy: 'team_unique',
    pick_mode: 'blind',
    draft_first_side: 1,
    draw_count: 2,
    max_basic_cost: 5,
    char_independent_cost: 1,
    place_capacity: 2,
    hp_scale_pct: 100,
    pause_limit_s: null,
    hotseat_curtain: true,
  };

  const blindOv = buildRosterOverlay(1280, 800, {
    catalog,
    team1: ['c1', 'c2'],
    team2: [],
    assignSide: 1,
    roomLobby: {
      editableSides: [1],
      viewerSide: 1,
      isOnline: true,
      isHost: true,
      isReady: false,
      ruleset,
      roomCode: 'K7P9M2',
      onCopyRoomCode: () => {},
      pickMeta: {
        1: { count: 2, power: 4, masked: false, ready: false },
        2: { count: 2, power: 5, masked: true, ready: true },
      },
      rulesOpen: false,
      onToggleRules: () => {},
      onUpdateRules: () => {},
    },
    onSetAssignSide: () => {},
    onToggleChar: () => {},
    onStart: () => {},
    onCancel: () => {},
  });
  const blindTexts = collectTexts(blindOv).join(' | ');
  assert.ok(blindTexts.includes('战力 4/5'), `Expected P1 power 4/5 in header: ${blindTexts}`);
  assert.ok(blindTexts.includes('双盲保密 · 对手已编入 2 名角色（总战力 5/5）'), `Expected masked opponent summary: ${blindTexts}`);
  assert.ok(blindTexts.includes('房间规则'), 'Expected 房间规则 button');

  let patched = null;
  const rulesOv = buildRosterOverlay(1280, 800, {
    catalog,
    team1: ['c1'],
    team2: [],
    assignSide: 1,
    roomLobby: {
      editableSides: [1],
      viewerSide: 1,
      isOnline: true,
      isHost: true,
      isReady: false,
      ruleset,
      rulesOpen: true,
      onToggleRules: () => {},
      onUpdateRules: (p) => { patched = p; },
    },
    onSetAssignSide: () => {},
    onToggleChar: () => {},
    onStart: () => {},
    onCancel: () => {},
  });
  const rulesTexts = collectTexts(rulesOv).join(' | ');
  assert.ok(rulesTexts.includes('房间规则设置'));
  assert.ok(rulesTexts.includes('恢复标准规则'));
  assert.ok(!rulesTexts.includes('调音' + '台'));
  assert.equal(patched, null);

  let conceded = false;
  const menuOv = buildMatchMenuOverlay(1280, 800, {
    roomCode: 'K7P9M2',
    confirmConcede: true,
    canConcede: true,
    canReopenLobby: true,
    onConfirmConcede: () => { conceded = true; },
    onReopenLobby: () => {},
    onClose: () => {},
  });
  const menuTexts = collectTexts(menuOv).join(' | ');
  assert.ok(menuTexts.includes('重返选人台（保留房间）'));
  assert.ok(menuTexts.includes('确认认输结算'));
  assert.equal(conceded, false);
});

test('TimelineSequencer freezes pre-hit shields, statuses, and alive state until combat_strike contact frame', () => {
  const scheduled = [];
  const releasedCalls = [];
  const seq = new TimelineSequencer({
    schedule: (fn, ms) => {
      const item = { fn, ms, cancelled: false };
      scheduled.push(item);
      return item;
    },
    cancel: (item) => { item.cancelled = true; },
    retireStaleDice: () => {},
    retireSideDice: () => {},
    clearClashGroups: () => {},
    playDiceRoll: (_ev, { onNumbersRevealed }) => onNumbersRevealed?.(),
    playDiceClash: (_ev, { onNumbersRevealed, onOutcomeImpact }) => {
      onNumbersRevealed?.();
      onOutcomeImpact?.();
    },
    playFx: (ev) => (ev.kind === 'combat_strike' ? { impactMs: 120, durationMs: 260 } : null),
    releaseDeferredVitals: (opts) => releasedCalls.push(opts),
  });

  const prevState = {
    started: true,
    match_number: 1,
    fx_events: [],
    frame: {
      players: [
        { side: 1, characters: [{ id: 'atk', hp: 20, max_hp: 20, alive: true, shields: {}, statuses: {} }] },
        { side: 2, characters: [{ id: 'def', hp: 6, max_hp: 20, alive: true, shields: { normal: 4 }, statuses: { 烧伤: 1 }, status_details: {}, bleed_burst: false }] },
      ],
    },
  };
  const nextState = {
    started: true,
    match_number: 1,
    fx_events: [
      { seq: 1, kind: 'combat_strike', attacker_id: 'atk', attacker_side: 1, target_id: 'def', target_side: 2, die_type: 'slash' },
      { seq: 2, kind: 'damage', target_id: 'def', target_side: 2, hp_lost: 6, cause: 'attack' },
      { seq: 3, kind: 'status_change', character_id: 'def', side: 2, status: '烧伤', delta: 2 },
      { seq: 4, kind: 'character_death', character_id: 'def', side: 2, name: '守方' },
    ],
    frame: {
      players: [
        { side: 1, characters: [{ id: 'atk', hp: 20, max_hp: 20, alive: true, shields: {}, statuses: {} }] },
        { side: 2, characters: [{ id: 'def', hp: 0, max_hp: 20, alive: false, shields: { normal: 0 }, statuses: { 烧伤: 3 }, status_details: {}, bleed_burst: false }] },
      ],
    },
  };

  const plan = seq.prepareBeat({ prevState, nextState, characterKeyFn: (id, s) => `${s}:${id}` });
  // Before contact frame: pre-hit alive/shields/statuses are frozen in deferredActorStateOverrides!
  const frozen = seq.deferredActorStateOverrides.get('2:def');
  assert.ok(frozen, 'Expected pre-hit actor state to be frozen before strike contact');
  assert.equal(frozen.alive, true);
  assert.equal(frozen.shields.normal, 4);
  assert.equal(frozen.statuses['烧伤'], 1);

  seq.playBeat(plan);
  assert.equal(seq.deferredActorStateOverrides.has('2:def'), true, 'Still frozen during windup before impactMs');
  const impactTimer = scheduled.find((s) => !s.cancelled && s.ms === 120);
  assert.ok(impactTimer, 'Expected impact timer at 120ms');
  impactTimer.fn();
  assert.equal(seq.deferredActorStateOverrides.size, 0, 'Deferred actor state cleared at contact frame');
  assert.ok(releasedCalls.some((c) => c?.rebuildActors === true), 'Expected rebuildActors: true on vitals release');
});

test('FxDirector dispatches extended hooks, hitstop, zoom_punch, auras, and in-dossier preview', () => {
  const calls = { cross: 0, sprite: 0, hitstop: [], zoom: [], banner: [] };
  const fxd = new FxDirector({
    three: {
      spawnCrossSlash: () => { calls.cross += 1; },
      spawnSpriteVfx: () => { calls.sprite += 1; },
      emitShockwave: () => {},
      spawnImpactBurst: () => {},
    },
    physics: {},
    audio: { playSynthRecipe: () => true },
    getActorNode: () => null,
    getActorPos: () => ({ x: 120, y: 200 }),
    getMotion: () => ({ lunge: 0, recoil: 0, evade: 0, hitFlash: 0, healGlow: 0, passiveFlare: 0 }),
    deferFx: (fn) => fn(),
    getClashCenter: () => ({ x: 300, y: 200 }),
    triggerShake: () => {},
    triggerHitstop: (ms) => calls.hitstop.push(ms),
    triggerZoomPunch: (z) => calls.zoom.push(z),
    showSkillBanner: (spec) => calls.banner.push(spec),
    spawnFloater: () => {},
    showBanner: () => {},
  });

  fxd.sync({
    nova_lin_qiu: {
      status_auras: { 隧道: { color: '#238a9e', style: 'ring', radius: 54 } },
      defaults: {
        on_heavy_hit: { threshold: 7, hitstop_ms: 80, camera: { zoom_punch: 0.025 } },
      },
      skills: {
        空断: {
          on_skill_use: { vfx: [{ primitive: 'skill_banner', text: '空断', color: '#238a9e' }] },
          on_strike: {
            hitstop_ms: 75,
            camera: { zoom_punch: 0.02 },
            vfx: [
              { primitive: 'cross_slash', count: 1, color: '#238a9e' },
              { primitive: 'sprite_vfx', url: '/fx_assets/star_knot_ring.svg', color: '#238a9e', count: 1 },
            ],
          },
        },
      },
    },
  }, {});

  assert.equal(fxd.resolveStatusAuras('nova_lin_qiu', { 隧道: 1, 强壮: 2 }).length, 1);
  assert.equal(fxd.resolveHeavyHitRecipe({ characterId: 'nova_lin_qiu', amount: 6 }), null);
  assert.ok(fxd.resolveHeavyHitRecipe({ characterId: 'nova_lin_qiu', amount: 8 }));
  assert.equal(fxd.hasPreviewableFx('nova_lin_qiu', { cardName: '空断' }), true);

  const previewed = fxd.previewCharacterFx('nova_lin_qiu', {
    side: 1,
    cardName: '空断',
    charName: '林秋',
    originPt: { x: 100, y: 180 },
    targetPt: { x: 320, y: 180 },
  });
  assert.equal(previewed, true);
  assert.equal(calls.cross, 1);
  assert.equal(calls.sprite, 1);
  assert.deepEqual(calls.hitstop, [75]);
  assert.deepEqual(calls.zoom, [0.02]);
  assert.equal(calls.banner[0]?.title, '空断');
});

test('Chronicle view and card print render exact formulas, entity hover pills, and distinct skipped vs destroyed stamps with restrained terms', async () => {
  const PIXI = await import('../../battle_ui/static/vendor/pixi.min.mjs');
  const { formatChronicleMarkdown, renderChronicleSection } = await import(new URL('chronicle_view.js', ENGINE));
  const { buildFullCard } = await import(new URL('card_print.js', ENGINE));
  const { makeSealButton } = await import(new URL('design_system.js', ENGINE));

  function collectTexts(node, out = []) {
    if (!node) return out;
    if (typeof node.text === 'string' && node.text.trim()) out.push(node.text.trim());
    for (const ch of node.children || []) collectTexts(ch, out);
    return out;
  }

  const sampleChronicle = {
    unlocked_all: true,
    total_events: 2,
    turns: [{
      turn: 1,
      first_side: 1,
      first_player: '甲席',
      stats: { damage_by_side: { '1': 7, '2': 0 }, deaths: [], collapses: ['澜清'] },
      blocks: [{
        id: 'T1:regular:1:1',
        kind: 'duel',
        phase: 'combat',
        title: '常规交锋 1',
        duel_kind: 'regular',
        duel_number: 1,
        matchup: {
          '1': { character_id: 'nova_lin_qiu', character_name: '林秋', card_id: 'lin_qiu_void_cut', card_name: '空断' },
          '2': { character_id: 'lan_qing', character_name: '澜清', card_id: 'lan_open', card_name: '起势·蓝电缠身' },
        },
        summary: { rounds: 1, hp_delta: { '1': 0, '2': -7 }, highlights: ['澜清光点形态群崩塌'] },
        rounds: [{
          round: 1,
          kind: 'clash',
          label: '第 1 轮',
          rolls: [{
            side: 1, lane: 'front', character_id: 'nova_lin_qiu', character_name: '林秋',
            card_id: 'lin_qiu_void_cut', card_name: '空断', position: 1, is_repeat: false,
            die_type: 'slash', die_label: '斩击', range_label: '1~8（原1~6）',
            formula_text: '(基础2 + 掷5) = 最终7', rolled_value: 5, final_score: 7, clash_score: 7, result: 'win',
          }],
          items: [{
            seq: 1,
            category: 'damage',
            side: 1,
            text: '林秋 对 澜清 造成 7 点普通伤害（实扣 7 生命）。',
            formula: '攻方7 → 入盾前7（普通伤害） → 实扣生命 7（剩余 23/30）',
            entities: [
              { kind: 'card', id: 'lin_qiu_void_cut', name: '空断', side: 1, character_id: 'nova_lin_qiu' },
              { kind: 'status', id: '隧道', name: '隧道', side: null },
            ],
          }],
        }],
      }],
    }],
  };

  const md = formatChronicleMarkdown(sampleChronicle, { winnerSide: 1, turn: 1 });
  assert.ok(md.includes('# 《光点计划 III》对局战报'));
  assert.ok(md.includes('算式：攻方7 → 入盾前7'));
  assert.ok(!md.includes('光核') && !md.includes('崩解') && !md.includes('结构战报'));

  const toolbar = new PIXI.Container();
  const body = new PIXI.Container();
  const sec = renderChronicleSection({
    toolbarHost: toolbar,
    toolbarX: 0,
    toolbarY: 0,
    toolbarW: 860,
    chronicle: sampleChronicle,
    catalog: {
      players: [{ side: 1, characters: [{ id: 'nova_lin_qiu', name: '林秋', skills: [{ id: 'lin_qiu_void_cut', name: '空断', cost: 2, dice: [] }] }] }],
      statuses: { 隧道: ['隧道规则'] },
    },
    makeSealButton,
    onHoverCard: () => {},
    onHoverStatus: () => {},
  });
  sec.buildBody(body, 820);
  const bodyTexts = collectTexts(body).join(' | ');
  assert.ok(bodyTexts.includes('1~8（原1~6）'), `Expected boosted die range in chronicle: ${bodyTexts}`);
  assert.ok(bodyTexts.includes('卡牌 · 空断'), `Expected interactive card chip: ${bodyTexts}`);
  assert.ok(bodyTexts.includes('状态 · 隧道'), `Expected interactive status chip: ${bodyTexts}`);
  assert.ok(bodyTexts.includes('澜清光点形态群崩塌'), `Expected canonical collapse text: ${bodyTexts}`);

  // Verify skipped vs destroyed card stamp distinction + form_when trait rendering
  const skippedCard = buildFullCard({
    id: 'c_skip',
    name: '电叉·回环舞',
    cost: 2,
    skipped: true,
    destroyed: false,
    form_when: { status: '电叉·回环舞·活化', form: 'active' },
    forms: [{ form_key: 'active', name: '电叉·回环舞·活化态' }],
    dice: [{ type: 'slash', printed_level: 2, level: 3, roll_max: 8 }],
  }, { side: 1 });
  const skipTexts = collectTexts(skippedCard).join(' | ');
  assert.ok(skipTexts.includes('已跳过') && !skipTexts.includes('已摧毁'), `Skipped card must not say 已摧毁: ${skipTexts}`);
  assert.ok(skipTexts.includes('持有电叉·回环舞·活化时使用「电叉·回环舞·活化态」形态'), `Expected form_when badge: ${skipTexts}`);
  assert.ok(skipTexts.includes('1~8'), `Expected boosted runtime roll_max 1~8: ${skipTexts}`);

  const destroyedCard = buildFullCard({
    id: 'c_dest',
    name: '碎裂技能',
    cost: 2,
    skipped: true,
    destroyed: true,
    dice: [{ type: 'slash', level: 2, roll_max: 6 }],
  }, { side: 2 });
  const destTexts = collectTexts(destroyedCard).join(' | ');
  assert.ok(destTexts.includes('已摧毁'), `Destroyed card must show 已摧毁: ${destTexts}`);
});
