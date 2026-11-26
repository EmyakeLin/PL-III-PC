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
