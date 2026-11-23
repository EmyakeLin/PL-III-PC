/**
 * Pure Standalone Random-Event-Driven Full-UI Mock for 《光点计划 III》.
 *
 *  - Runs the 100% REAL `GameDirector` UI (full fighter wings, underfoot HP/Lightcore/Shield/Status
 *    plinths, passive chips, diegetic top bar, cost crystals, 2.5D deck piles, hero dossier,
 *    passive drawer, codex, TimelineSequencer, PresentationFx, 3D dice, Matter.js physics, WebAudio).
 *  - ZERO backend calls, ZERO fetch(), ZERO core-code backdoors, ZERO hardcoded UI scenes.
 *  - 100% procedurally/randomly generated characters, passives, skills, dice (1..30), entries
 *    (0..1000+ chars), duels (4..40), multi-card stacks, temporary skills, rolls, clashes, and fx_events.
 */

import * as PIXI from '../vendor/pixi.min.mjs';
import { ThreeWorld } from '../engine/three_world.js';
import { TabletopPhysics } from '../engine/physics.js';
import { TabletopAudio } from '../engine/audio.js';
import { GameDirector } from '../engine/game_director.js';
import { combatRollKey } from '../engine/timeline_sequencer.js';
import { LEVEL_MAX } from '../engine/design_system.js';

// ── Pure Procedural Random Generators ────────────────────────────────────────
const pick = (arr) => arr[Math.floor(Math.random() * arr.length)];
const randInt = (lo, hi) => lo + Math.floor(Math.random() * (hi - lo + 1));
const chance = (p) => Math.random() < p;

const CHAR_POOL = [
  { id: 'plan_b_annolin', name: '安诺琳', title: '战术指挥', faction: 'PlanB', rank: 'A' },
  { id: 'plan_b_heck', name: '赫克', title: '爆破先锋', faction: 'PlanB', rank: 'A' },
  { id: 'plan_b_heris', name: '赫里斯', title: '炽焰突击', faction: 'PlanB', rank: 'A' },
  { id: 'plan_b_li_ling', name: '李凌', title: '残影刺客', faction: 'PlanB', rank: 'A' },
  { id: 'nova_lin_qiu', name: '林秋', title: '星轨织者', faction: '新星组织', rank: 'S' },
  { id: 'lan_qing', name: '澜清', title: '幽兰残雪', faction: '经值事务所', rank: 'S' },
  { id: 'guangsheng_liu_yin', name: '流阴', title: '光生执政', faction: '光生会', rank: 'S' },
];

const SKILL_PREFIX = ['断光', '逆流', '幽蓝', '穿星', '裂穹', '残雪', '引燃', '折锋', '空断', '极锐', '同调', '肃清', '贯刺', '回环', '沉锋', '苍焰', '无形', '溯源'];
const SKILL_SUFFIX = ['斩', '突刺', '压制', '覆写', '流光', '强袭', '反制', '连段', '崩解', '穿心', '回响', '障壁', '残叶', '涌流', '灭杀', '剑术', '重击', '护幕'];
const PASSIVE_NAMES = ['光点共鸣', '战术直觉', '残雪凝锋', '领域压迫', '电弧追击', '炽热残响', '星轨校准', '破甲专注'];
const DIE_TYPES = ['slash', 'pierce', 'blunt', 'block', 'evade'];
const DAMAGE_GRADES = ['normal', 'pierce', 'concept', 'lightcore', 'real'];
const GRADE_NAME = { normal: '普通', pierce: '穿甲', concept: '超穿甲', lightcore: '光点', real: '真实' };
const STATUS_POOL = ['烧伤', '裂血', '电击', '星结', '威压', '隧道', '凝聚', '麻痹', '环境压制', '领域洞悉'];
const TRIGGERS = ['【使用时】', '【用骰前】', '【命中时】', '【暴击时】', '【拼点胜利】', '【拼点失败】', '【拼点平局】', '【交锋开始】'];
const CLAUSES = [
  '对目标施加2层烧伤并抽取1张技能牌。',
  '本骰最终点数+2，若目标持有状态则追加1点穿甲伤害。',
  '回复自身2点生命并获得2层普通护盾。',
  '使自身下一颗战斗骰的变动点数上限提升一级。',
  '若本回合已拼点胜利至少1次，则对目标施加3层电击。',
  '本场交锋结束前，敌方后续骰子最终点数减少1点。',
  '摧毁对位技能的下一颗未结算骰子并获得1点通用费用。',
  '记录当前压制基准，若本轮未受生命损失则额外触发一次回响。',
  '将目标的护盾削减2点，并使本技能后续进攻骰获得暴击倾向。',
  '若本次命中造成完整度损失，则追加1层领域洞悉与1层环境同调。',
];

let nextInstanceId = 1;

function randomEntryText(minChars = 0) {
  let out = '';
  do {
    out += pick(TRIGGERS) + pick(CLAUSES);
    if (minChars > 0 && out.length < minChars) out += '\n';
  } while (out.length < minChars);
  return out;
}

function randomDieSpec(position, { allowRich = true, forceEmpty = false } = {}) {
  const isSkip = !forceEmpty && chance(0.05);
  const type = isSkip ? 'skip' : pick(DIE_TYPES);
  const level = isSkip ? 1 : randInt(1, 6);
  const rollMax = LEVEL_MAX[level] || 6;
  const baseValue = chance(0.22) ? randInt(1, 3) : 0;
  const multiplier = chance(0.1) ? 2 : 1;
  const finalBonus = chance(0.18) ? randInt(-1, 3) : 0;
  const isAttack = ['slash', 'pierce', 'blunt'].includes(type);
  const damageParts = [];
  if (isAttack) {
    const g = pick(DAMAGE_GRADES);
    const amt = randInt(1, 4);
    damageParts.push({ grade: g, amount: amt, text: `${amt}点${GRADE_NAME[g]}伤害` });
    if (chance(0.22)) {
      const g2 = pick(DAMAGE_GRADES);
      const amt2 = randInt(1, 2);
      damageParts.push({ grade: g2, amount: amt2, text: `${amt2}点${GRADE_NAME[g2]}伤害` });
    }
  }
  const entries = [];
  if (!forceEmpty && allowRich && !isSkip && chance(0.6)) {
    entries.push(randomEntryText(0));
  }
  return {
    position,
    type,
    level,
    printed_level: level,
    roll_max: rollMax,
    base_value: baseValue,
    multiplier,
    final_bonus: finalBonus,
    damage_parts: damageParts,
    entries,
    range_traits: [],
  };
}

function randomCard(character, { mode = 'normal' } = {}) {
  const id = `mock_card_${nextInstanceId}`;
  const instanceId = nextInstanceId++;
  const name = pick(SKILL_PREFIX) + pick(SKILL_SUFFIX);
  const cost = randInt(0, 5);
  let dieCount;
  let skillEntries = [];
  let forceEmptyDice = false;

  if (mode === 'minimal') {
    dieCount = 1;
    forceEmptyDice = true;
  } else if (mode === 'thirty_dice') {
    dieCount = 30;
    if (chance(0.6)) skillEntries = [randomEntryText(0)];
  } else if (mode === 'thousand_chars') {
    dieCount = randInt(2, 5);
    skillEntries = [randomEntryText(1020)];
  } else {
    dieCount = randInt(1, 5);
    if (chance(0.48)) skillEntries = [randomEntryText(0)];
  }

  const dice = [];
  for (let i = 1; i <= dieCount; i++) {
    dice.push(randomDieSpec(i, { allowRich: mode !== 'minimal', forceEmpty: forceEmptyDice }));
  }

  return {
    id,
    instance_id: instanceId,
    name,
    cost,
    character_id: character.id,
    borrowed: false,
    dice,
    entries: skillEntries,
    live_dice: [],
    destroyed_die_positions: [],
    destroyed: false,
    used: false,
    skipped: false,
    dissolved: false,
    temporary: mode === 'normal' && chance(0.14),
    pre_reveal: chance(0.2),
    range_level: chance(0.25) ? randInt(1, 3) : 0,
    range_deficit: chance(0.1) ? randInt(1, 2) : 0,
    play_mode: null,
    state: 'placed_face_up',
  };
}

function randomPassives() {
  const count = randInt(2, 4);
  const pool = PASSIVE_NAMES.slice().sort(() => Math.random() - 0.5);
  return pool.slice(0, count).map((name) => {
    const desc = randomEntryText(0);
    return { name, description: desc, entries: [desc], display_lines: [desc] };
  });
}

// ── Pure Client-Side Random Transport (ZERO backend, feeds real GameDirector) ─
class PureRandomMockTransport {
  constructor() {
    this.isRoom = false;
    this.busy = false;
    this.matchNumber = 0;
    this.revision = 0;
    this.fxSeq = 0;
    this.preset = 'normal';
    this.state = null;
    this._resetMatch('normal');
  }

  _emitFx(kind, payload = {}) {
    this.fxSeq += 1;
    this._pendingFx.push({ seq: this.fxSeq, turn: this.turn, kind, ...payload });
  }

  _resetMatch(preset = 'normal') {
    this.preset = preset;
    this.matchNumber += 1;
    this.revision += 1;
    this.turn = 1;
    this.fxSeq = 0;
    this._pendingFx = [];
    this._history = [];

    const shuffled = CHAR_POOL.slice().sort(() => Math.random() - 0.5);
    const makePlayer = (side, name, specs) => {
      const chars = specs.map((c) => ({
        id: c.id,
        printed_id: c.id,
        name: c.name,
        title: c.title,
        faction: c.faction,
        rank: c.rank,
        alive: true,
        hp: randInt(14, 24),
        max_hp: 24,
        speed: randInt(2, 6),
        lightcore_hp: randInt(20, 28),
        max_lightcore_hp: 28,
        shields: { normal: randInt(0, 4), reinforced: randInt(0, 2), concept: randInt(0, 2) },
        statuses: { [pick(STATUS_POOL)]: randInt(1, 5), [pick(STATUS_POOL)]: randInt(1, 3) },
        passive_values: {},
        bleed_burst: false,
        ability_effects: {},
        reserved_dice: [],
        status_overflow: {},
        cost: { available: 0, refill: 0, spent: 0 },
        duels: { max: 4, used: 4 },
        _passives: randomPassives(),
      }));
      const totalSpeed = chars.reduce((acc, c) => acc + c.speed, 0);
      let hand;
      if (side === 1 && preset === 'extreme_cards') {
        hand = [
          randomCard(pick(chars), { mode: 'minimal' }),
          randomCard(pick(chars), { mode: 'thirty_dice' }),
          randomCard(pick(chars), { mode: 'thousand_chars' }),
          randomCard(pick(chars), { mode: 'normal' }),
          randomCard(pick(chars), { mode: 'normal' }),
        ];
      } else {
        hand = Array.from({ length: randInt(5, 7) }, () => randomCard(pick(chars)));
      }
      hand.forEach((c) => { c.action_key = `instance:${c.instance_id}`; c.state = 'in_hand'; });
      const discard = Array.from({ length: randInt(1, 3) }, () => randomCard(pick(chars)));
      return {
        side,
        name,
        speed: totalSpeed,
        team_statuses: chance(0.35) ? { 限制: randInt(1, 3) } : {},
        cost: { available: randInt(5, 8), refill: 8, spent: 0 },
        placement_ended: false,
        characters: chars,
        draw_count: randInt(4, 12),
        hand_count: hand.length,
        decisive_count: null,
        delayed_discard_count: discard.length,
        out_of_combat_count: 0,
        hand,
        delayed_discard: discard,
        out_of_combat: [],
      };
    };

    const p1Count = chance(0.45) ? 2 : 1;
    const p2Count = chance(0.45) ? 2 : 1;
    this.players = [
      makePlayer(1, '玩家一', shuffled.slice(0, p1Count)),
      makePlayer(2, '玩家二', shuffled.slice(p1Count, p1Count + p2Count)),
    ];

    this.preRevealDuels = [];
    this.specialDuels = [];
    this.regularDuels = [];
    this.duelOrder = [];

    // Preset 'forty' jumps straight into 40-duel combat stress test;
    // 'normal' and 'extreme_cards' start in live PLACEMENT with fanned hand so the player can place cards!
    if (preset === 'forty') {
      this.mode = 'combat';
      this.cardsRevealed = true;
      this.players[0].placement_ended = true;
      this.players[1].placement_ended = true;
      for (let i = 0; i < 40; i++) {
        let kind = 'regular';
        if (i < 2 && chance(0.3)) kind = 'pre_reveal';
        else if (i >= 2 && i < 4 && chance(0.22)) kind = 'instant';
        const bucket = kind === 'pre_reveal' ? this.preRevealDuels : kind === 'instant' ? this.specialDuels : this.regularDuels;
        const number = bucket.length + 1;
        const sides = [1, 2].map((side) => {
          const roster = this.players[side - 1].characters;
          const count = chance(0.1) ? 0 : chance(0.22) ? 2 : 1;
          const cards = Array.from({ length: count }, () => {
            const card = randomCard(pick(roster));
            if (kind !== 'regular') card.play_mode = side === 1 ? 'active' : 'passive';
            return card;
          });
          return { side, cards };
        });
        if (sides[0].cards.length === 0 && sides[1].cards.length === 0) {
          sides[0].cards.push(randomCard(pick(this.players[0].characters)));
        }
        const slot = {
          number,
          sides,
          ...(kind !== 'regular' ? { ready: true, interceptable: false, attacking_side: 1, target: { kind: 'character', name: this.players[1].characters[0].name } } : {}),
        };
        bucket.push(slot);
        this.duelOrder.push({ kind, number, slot, key: `${kind}:${number}` });
      }
    } else {
      this.mode = 'placement';
      this.cardsRevealed = false;
      this.liveCombat = null;
      // Seed 1 initial opponent face-down card in Duel 1 so the confrontation bridge is immediately alive
      const oppChar = pick(this.players[1].characters);
      const oppCard = preset === 'extreme_cards'
        ? randomCard(oppChar, { mode: 'thirty_dice' })
        : randomCard(oppChar);
      oppCard.state = 'placed_face_down';
      this.regularDuels.push({
        number: 1,
        sides: [
          { side: 1, cards: [] },
          { side: 2, cards: [oppCard] },
        ],
      });
    }

    this.catalog = {
      players: this.players.map((p) => ({
        side: p.side,
        characters: p.characters.map((c) => ({
          id: c.id,
          name: c.name,
          passives: c._passives,
          faction_passives: [],
          skills: [...p.hand, ...p.delayed_discard].filter((s) => s.character_id === c.id),
        })),
      })),
      statuses: Object.fromEntries(STATUS_POOL.map((s) => [s, [`【状态】${s}的随机规则说明。`]])),
      actions: {},
      ability_effects: {},
    };

    this.activeDuelIdx = 0;
    this.roundId = 1;
    this.cardCursor = { 1: 0, 2: 0 };
    this.dieCursor = { 1: 0, 2: 0 };
    if (this.mode === 'combat') {
      this.liveCombat = this._buildEmptyCombat();
      this._stepRound();
    }
  }

  _placeFromHand(cardKey) {
    if (this.mode !== 'placement') return;
    const p1 = this.players[0];
    const idx = p1.hand.findIndex((c) => (c.action_key || c.id) === cardKey || c.id === cardKey);
    if (idx < 0) return;
    const [card] = p1.hand.splice(idx, 1);
    p1.hand_count = p1.hand.length;
    card.state = 'placed_face_down';

    // Find first regular duel slot where P1 has no card yet, or append a new duel slot
    let slot = this.regularDuels.find((d) => d.sides[0].cards.length === 0);
    if (!slot) {
      slot = {
        number: this.regularDuels.length + 1,
        sides: [{ side: 1, cards: [] }, { side: 2, cards: [] }],
      };
      this.regularDuels.push(slot);
    }
    slot.sides[0].cards.push(card);
    this._emitFx('card_place', { side: 1, duel_number: slot.number, card_id: card.id });

    // Opponent responds by placing a face-down card into its next empty slot (up to 4 duels)
    const p2 = this.players[1];
    if (p2.hand.length > 0 && this.regularDuels.filter((d) => d.sides[1].cards.length > 0).length < Math.max(4, this.regularDuels.length)) {
      let oppSlot = this.regularDuels.find((d) => d.sides[1].cards.length === 0);
      if (!oppSlot) {
        oppSlot = {
          number: this.regularDuels.length + 1,
          sides: [{ side: 1, cards: [] }, { side: 2, cards: [] }],
        };
        this.regularDuels.push(oppSlot);
      }
      const oppCard = p2.hand.shift();
      p2.hand_count = p2.hand.length;
      if (oppCard) {
        oppCard.state = 'placed_face_down';
        oppSlot.sides[1].cards.push(oppCard);
      }
    }
  }

  _endPlacement() {
    if (this.mode !== 'placement') return;
    // Remove trailing empty slots
    this.regularDuels = this.regularDuels.filter((d) => d.sides[0].cards.length > 0 || d.sides[1].cards.length > 0);
    if (!this.regularDuels.length) {
      // If player ended without placing any card, auto-place 1 random card so reveal/combat has a duel
      const c1 = this.players[0].hand.shift() || randomCard(pick(this.players[0].characters));
      const c2 = this.players[1].hand.shift() || randomCard(pick(this.players[1].characters));
      this.players[0].hand_count = this.players[0].hand.length;
      this.players[1].hand_count = this.players[1].hand.length;
      this.regularDuels.push({
        number: 1,
        sides: [{ side: 1, cards: [c1] }, { side: 2, cards: [c2] }],
      });
    }
    this.regularDuels.forEach((d, i) => {
      d.number = i + 1;
      for (const se of d.sides) {
        for (const c of se.cards) c.state = 'placed_face_up';
      }
    });
    this.players[0].placement_ended = true;
    this.players[1].placement_ended = true;
    this.cardsRevealed = true;
    this.mode = 'reveal';
    this.duelOrder = this.regularDuels.map((slot) => ({
      kind: 'regular',
      number: slot.number,
      slot,
      key: `regular:${slot.number}`,
    }));
  }

  _startCombatFromReveal() {
    if (this.mode !== 'reveal') return;
    this.mode = 'combat';
    this.activeDuelIdx = 0;
    this.roundId = 1;
    this.cardCursor = { 1: 0, 2: 0 };
    this.dieCursor = { 1: 0, 2: 0 };
    this.liveCombat = this._buildEmptyCombat();
    this._stepRound();
  }

  _currentEntry() {
    return this.duelOrder[this.activeDuelIdx] || null;
  }

  _buildEmptyCombat() {
    const entry = this._currentEntry();
    if (!entry) return null;
    return {
      kind: entry.kind,
      duel_number: entry.number,
      round_id: this.roundId,
      sides: [1, 2].map((side) => ({
        side, node: null, waiting_at: null, card_id: null, card_instance_id: null,
        play_mode: null, range_deficit: 0, character_id: null, target_id: null, die_number: null, die: null,
      })),
      suspended: [],
    };
  }

  _getSideCardAndDie(side) {
    const entry = this._currentEntry();
    if (!entry) return { card: null, die: null, diePos: null };
    const se = entry.slot.sides.find((s) => s.side === side);
    const cards = se?.cards || [];
    while (this.cardCursor[side] < cards.length) {
      const card = cards[this.cardCursor[side]];
      if (card.destroyed || card.skipped || this.dieCursor[side] >= card.dice.length) {
        card.used = true;
        this.cardCursor[side] += 1;
        this.dieCursor[side] = 0;
        continue;
      }
      return { card, die: card.dice[this.dieCursor[side]], diePos: this.dieCursor[side] + 1 };
    }
    return { card: null, die: null, diePos: null };
  }

  _finishCurrentDuel() {
    const entry = this._currentEntry();
    if (entry) {
      for (const se of entry.slot.sides) {
        for (const c of se.cards) {
          c.used = true;
          if (c.temporary) c.dissolved = true;
        }
      }
    }
    this.activeDuelIdx += 1;
    if (this.activeDuelIdx >= this.duelOrder.length) {
      this._resetMatch(this.preset);
      return;
    }
    this.roundId = 1;
    this.cardCursor = { 1: 0, 2: 0 };
    this.dieCursor = { 1: 0, 2: 0 };
    this._stepRound();
  }

  _stepRound() {
    const entry = this._currentEntry();
    if (!entry) return;
    const s1 = this._getSideCardAndDie(1);
    const s2 = this._getSideCardAndDie(2);
    if (!s1.card && !s2.card) {
      this._finishCurrentDuel();
      return;
    }

    const isAttackDie = (die) => Boolean(die && ['slash', 'pierce', 'blunt'].includes(die.type));
    const isPassiveDie = (die) => Boolean(die && ['block', 'evade'].includes(die.type));

    // Advance past any already-destroyed die positions
    const skipDestroyed = (side, pair) => {
      while (pair.card && pair.die && (pair.card.destroyed_die_positions || []).includes(pair.diePos)) {
        this.dieCursor[side] += 1;
        pair = this._getSideCardAndDie(side);
      }
      return pair;
    };
    const p1Pair = skipDestroyed(1, s1);
    const p2Pair = skipDestroyed(2, s2);
    if (!p1Pair.card && !p2Pair.card) {
      this._finishCurrentDuel();
      return;
    }

    const hasBothOpposing = Boolean(
      p1Pair.die && p2Pair.die && p1Pair.die.type !== 'skip' && p2Pair.die.type !== 'skip',
    );

    const findChar = (side, cid) => this.players[side - 1].characters.find((c) => c.id === cid) || this.players[side - 1].characters[0];
    const combatSides = [];

    for (const [side, pair] of [[1, p1Pair], [2, p2Pair]]) {
      const oppRoster = this.players[side === 1 ? 1 : 0].characters;
      const target = pick(oppRoster);
      if (!pair.card || !pair.die) {
        combatSides.push({
          side, node: null, waiting_at: null, card_id: null, card_instance_id: null,
          play_mode: null, range_deficit: 0, character_id: null, target_id: null, die_number: null, die: null,
        });
        continue;
      }
      const spec = pair.die;
      // Passive dice (block / evade) CANNOT attack alone when unopposed -> skip!
      const isSkip = spec.type === 'skip' || (!hasBothOpposing && isPassiveDie(spec));
      const rolled = isSkip ? null : randInt(1, spec.roll_max || 6);
      const finalScore = isSkip ? null : Math.max(1, (spec.base_value || 0) + rolled * (spec.multiplier || 1) + (spec.final_bonus || 0));
      const liveDie = {
        position: pair.diePos,
        type: spec.type,
        printed_level: spec.printed_level,
        level: spec.level,
        roll_max: spec.roll_max,
        base_value: spec.base_value,
        rolled_value: rolled,
        final_score: finalScore,
        clash_score: finalScore,
        result: isSkip ? 'skip' : null,
        win_branch_skipped: false,
        critical: !isSkip && isAttackDie(spec) && rolled === spec.roll_max && chance(0.45),
        destroyed: false,
        hit_index: 0,
        landed_hits: 0,
      };
      pair.card.live_dice = pair.card.live_dice.filter((d) => d.position !== pair.diePos);
      pair.card.live_dice.push(liveDie);

      const charObj = findChar(side, pair.card.character_id);
      combatSides.push({
        side,
        node: 'logic_dice_clash',
        waiting_at: null,
        card_id: pair.card.id,
        card_instance_id: pair.card.instance_id,
        play_mode: pair.card.play_mode,
        range_deficit: pair.card.range_deficit || 0,
        character_id: charObj.id,
        target_id: target.id,
        die_number: pair.diePos,
        die: liveDie,
      });
    }

    this.liveCombat = {
      kind: entry.kind,
      duel_number: entry.number,
      round_id: this.roundId,
      sides: combatSides,
      suspended: [],
    };

    const cs1 = combatSides.find((s) => s.side === 1);
    const cs2 = combatSides.find((s) => s.side === 2);
    const d1 = cs1?.die;
    const d2 = cs2?.die;

    // One seamless continuous roll → reveal → physical clash motion (NO separate pause & replay!)
    if (d1 && d2 && d1.result !== 'skip' && d2.result !== 'skip') {
      if (d1.clash_score > d2.clash_score) { d1.result = 'win'; d2.result = 'lose'; }
      else if (d2.clash_score > d1.clash_score) { d2.result = 'win'; d1.result = 'lose'; }
      else { d1.result = 'draw'; d2.result = 'draw'; }

      const c1 = findChar(1, cs1.character_id);
      const c2 = findChar(2, cs2.character_id);
      this._emitFx('dice_clash', {
        duel_kind: entry.kind,
        duel_number: entry.number,
        round_id: this.roundId,
        blank_round: false,
        already_rolled: false,
        sides: [
          { side: 1, character_id: c1.id, character_name: c1.name, card_id: cs1.card_id, die_number: cs1.die_number, range_deficit: cs1.range_deficit, ...d1 },
          { side: 2, character_id: c2.id, character_name: c2.name, card_id: cs2.card_id, die_number: cs2.die_number, range_deficit: cs2.range_deficit, ...d2 },
        ],
      });
    } else {
      const activeSides = [];
      for (const [side, cs, die] of [[1, cs1, d1], [2, cs2, d2]]) {
        if (!die || die.result === 'skip') continue;
        const ch = findChar(side, cs.character_id);
        activeSides.push({
          side, character_id: ch.id, character_name: ch.name,
          card_id: cs.card_id, die_number: cs.die_number, range_deficit: cs.range_deficit, ...die,
        });
      }
      if (activeSides.length) {
        this._emitFx('dice_roll', {
          duel_kind: entry.kind,
          duel_number: entry.number,
          round_id: this.roundId,
          sides: activeSides,
        });
      }
    }

    const emitStrike = (attSide, defSide, cs, die) => {
      const att = findChar(attSide, cs.character_id);
      const def = findChar(defSide, cs.target_id);
      const oneSided = die.result === null;
      if (oneSided) die.landed_hits = 1;
      this._emitFx('combat_strike', {
        attacker_side: attSide, attacker_id: att.id, attacker_name: att.name,
        target_side: defSide, target_id: def.id, target_name: def.name,
        die_type: die.type, die_number: cs.die_number, one_sided: oneSided,
        card_id: cs.card_id,
      });
      const dmg = randInt(1, 4) + (die.critical ? 2 : 0);
      if (chance(0.28)) {
        def.lightcore_hp = Math.max(0, def.lightcore_hp - dmg);
        this._emitFx('lightcore_damage', {
          target_side: defSide, target_id: def.id, target_name: def.name,
          side: defSide, character_id: def.id, character_name: def.name,
          amount: dmg, lost: dmg, remaining: def.lightcore_hp, max: def.max_lightcore_hp,
        });
      } else {
        def.hp = Math.max(1, def.hp - dmg);
        this._emitFx('damage', {
          target_side: defSide, target_id: def.id, target_name: def.name,
          side: defSide, character_id: def.id, character_name: def.name,
          amount: dmg, hp_lost: dmg, grade: pick(['normal', 'pierce', 'concept']),
          critical: Boolean(die.critical),
          absorbed: { normal: 0, reinforced: 0, concept: 0 },
          eroded: { normal: 0, reinforced: 0 },
        });
      }
      if (chance(0.22)) {
        const st = pick(STATUS_POOL);
        const delta = randInt(1, 2);
        def.statuses[st] = (def.statuses[st] || 0) + delta;
        this._emitFx('status_change', {
          side: defSide, character_id: def.id, character_name: def.name,
          status: st, delta, total: def.statuses[st],
        });
      }
    };

    // Only ATTACK dice (slash / pierce / blunt) perform strikes! Passive dice (block / evade)
    // only trigger their defensive stance (block barrier / evade ripple) via dice_clash.
    if (d1 && d1.result === 'win' && isAttackDie(d1)) emitStrike(1, 2, cs1, d1);
    else if (d2 && d2.result === 'win' && isAttackDie(d2)) emitStrike(2, 1, cs2, d2);
    else if (d1 && !d2 && isAttackDie(d1) && d1.result !== 'skip') emitStrike(1, 2, cs1, d1);
    else if (d2 && !d1 && isAttackDie(d2) && d2.result !== 'skip') emitStrike(2, 1, cs2, d2);

    // Random die_destroyed / card_destroyed events so shatter 3D FX, card shatter panel, and
    // destroyed die icon state are visibly exercised in the mock
    const maybeDestroyOpponent = (loserSide, loserPair) => {
      if (!loserPair?.card || loserPair.card.destroyed) return;
      const nextPos = (this.dieCursor[loserSide] || 0) + 2;
      if (nextPos <= loserPair.card.dice.length && chance(0.22)) {
        if (!loserPair.card.destroyed_die_positions.includes(nextPos)) {
          loserPair.card.destroyed_die_positions.push(nextPos);
        }
        const targetDie = loserPair.card.dice[nextPos - 1];
        this._emitFx('die_destroyed', {
          side: loserSide,
          character_id: loserPair.card.character_id,
          card_id: loserPair.card.id,
          instance_id: loserPair.card.instance_id,
          position: nextPos,
          die_type: targetDie?.type || 'slash',
        });
      } else if (chance(0.1)) {
        loserPair.card.destroyed = true;
        this._emitFx('card_destroyed', {
          side: loserSide,
          character_id: loserPair.card.character_id,
          card_id: loserPair.card.id,
          instance_id: loserPair.card.instance_id,
          card_name: loserPair.card.name,
        });
      }
    };
    if (d1 && d1.result === 'win') maybeDestroyOpponent(2, p2Pair);
    else if (d2 && d2.result === 'win') maybeDestroyOpponent(1, p1Pair);

    if (d1) this.dieCursor[1] += 1;
    if (d2) this.dieCursor[2] += 1;
    this.roundId += 1;
  }

  _triggerDemoDestroy() {
    const entry = this._currentEntry();
    if (!entry) return;
    const targetSide = chance(0.5) ? 2 : 1;
    const se = entry.slot.sides.find((s) => s.side === targetSide);
    const card = se?.cards?.[this.cardCursor[targetSide]] || se?.cards?.[0];
    if (!card) return;
    const nextPos = Math.min(card.dice.length, (this.dieCursor[targetSide] || 0) + 1);
    if (!card.destroyed && nextPos <= card.dice.length && !card.destroyed_die_positions.includes(nextPos)) {
      card.destroyed_die_positions.push(nextPos);
      this._emitFx('die_destroyed', {
        side: targetSide,
        character_id: card.character_id,
        card_id: card.id,
        instance_id: card.instance_id,
        position: nextPos,
        die_type: card.dice[nextPos - 1]?.type || 'slash',
      });
    } else {
      card.destroyed = true;
      this._emitFx('card_destroyed', {
        side: targetSide,
        character_id: card.character_id,
        card_id: card.id,
        instance_id: card.instance_id,
        card_name: card.name,
      });
    }
  }

  snapshot() {
    this.revision += 1;
    const fx = this._pendingFx.splice(0);
    const p1 = this.players[0];
    const isPlacement = this.mode === 'placement';
    const legalCards = isPlacement ? p1.hand.map((c) => c.action_key || c.id) : [];
    const serializeBoardCard = (c, side) => {
      if (!this.cardsRevealed && side === 2 && c.state === 'placed_face_down') {
        return { hidden: true };
      }
      return c;
    };
    const serializedDuels = this.regularDuels.map((d) => ({
      number: d.number,
      sides: d.sides.map((se) => ({
        side: se.side,
        cards: se.cards.map((c) => serializeBoardCard(c, se.side)),
      })),
    }));
    const cardOwners = {};
    this.regularDuels.forEach((d) => {
      d.sides.forEach((se) => {
        se.cards.forEach((c, idx) => {
          cardOwners[`regular:${d.number}:${se.side}:${idx + 1}`] = {
            character_id: c.character_id,
            side: se.side,
          };
        });
      });
    });

    return {
      revision: this.revision,
      match_number: this.matchNumber,
      mode: this.mode,
      active_side: 1,
      viewer_side: 1,
      can_advance: this.mode !== 'placement',
      can_pass: false,
      legal_cards: legalCards,
      card_owners: cardOwners,
      client_paced: true,
      catalog: this.catalog,
      history: this._history,
      fx_events: fx,
      special_options: [],
      effect_choice: null,
      roster_specs: [],
      status_visuals: {},
      character_sprites: {},
      frame: {
        turn: this.turn,
        phase: this.mode,
        node: this.mode === 'combat' ? 'logic_dice_clash' : this.mode === 'reveal' ? 'logic_reveal' : 'logic_place',
        viewer_side: 1,
        first_side: 1,
        placing_side: isPlacement ? 1 : null,
        cards_revealed: this.cardsRevealed,
        is_over: false,
        winner_side: null,
        players: this.players.map((p) => ({
          ...p,
          hand: p.side === 1 ? p.hand : null,
          characters: p.characters.map(({ _passives, ...rest }) => ({ ...rest, shields: { ...rest.shields }, statuses: { ...rest.statuses } })),
        })),
        duels: serializedDuels,
        pre_reveal: { phase: 'done', duels: this.preRevealDuels, eligible_sides: [], actor_side: null, attacking_side: null },
        special_duels: this.specialDuels,
        combat: this.mode === 'combat' ? this.liveCombat : null,
      },
    };
  }

  async fetchState() {
    return this.snapshot();
  }

  async send(action, payload = {}) {
    if (action === 'new') {
      this._resetMatch(payload.preset || this.preset);
      return this.snapshot();
    }
    if (action === 'place') {
      this._placeFromHand(payload.card_id);
      return this.snapshot();
    }
    if (action === 'end' || action === 'pass') {
      this._endPlacement();
      return this.snapshot();
    }
    if (action === 'demo_destroy') {
      this._triggerDemoDestroy();
      return this.snapshot();
    }
    if (action === 'next') {
      if (this.mode === 'reveal') this._startCombatFromReveal();
      else if (this.mode === 'combat') this._stepRound();
      return this.snapshot();
    }
    return this.snapshot();
  }
}

// ── Boot Complete Real GameDirector UI with 2.5D CombatTabletop ──────────────
async function bootFullMock() {
  const threeCanvas = document.getElementById('three-canvas');
  const pixiCanvas = document.getElementById('pixi-canvas');
  if (!threeCanvas || !pixiCanvas) throw new Error('缺少 WebGL 画布节点');

  if (!window.Matter) {
    await new Promise((resolve) => {
      const check = () => (window.Matter ? resolve() : setTimeout(check, 16));
      check();
    });
  }

  const threeWorld = new ThreeWorld(threeCanvas);
  const physics = new TabletopPhysics(window.innerWidth, window.innerHeight);
  const audio = new TabletopAudio();

  const app = new PIXI.Application();
  await app.init({
    canvas: pixiCanvas,
    preference: 'webgl',
    antialias: true,
    backgroundAlpha: 0,
    resolution: Math.min(window.devicePixelRatio || 1, 2),
    autoDensity: true,
    resizeTo: window,
  });

  const transport = new PureRandomMockTransport();
  const director = new GameDirector(app, physics, threeWorld, audio, transport);

  const resetTabletopSprings = (combatInit = 0) => {
    director.tabletop?.resetMatch(combatInit);
  };

  // Preset switching shortcuts (R: normal random, 4: 40 duels, 3: extreme 1-die/30-die/1000-char, H: snap to active)
  window.addEventListener('keydown', async (e) => {
    if (e.key === 'r' || e.key === 'R') {
      resetTabletopSprings(0);
      director.applyState(await transport.send('new', { preset: 'normal' }), { isInitial: false });
    } else if (e.key === '4') {
      resetTabletopSprings(1);
      director.applyState(await transport.send('new', { preset: 'forty' }), { isInitial: false });
    } else if (e.key === '3') {
      resetTabletopSprings(0);
      director.applyState(await transport.send('new', { preset: 'extreme_cards' }), { isInitial: false });
    } else if (e.key === 'd' || e.key === 'D') {
      director.applyState(await transport.send('demo_destroy'), { isInitial: false });
    } else if (e.key === 'h' || e.key === 'H' || e.key === 'Home') {
      director.tabletop?.snapToActive();
    }
  });

  window.addEventListener('resize', () => {
    const w = window.innerWidth;
    const h = window.innerHeight;
    threeWorld.resize(w, h);
    physics.resize(w, h);
    app.renderer.resize(w, h);
    director.resize(w, h);
  });

  const initial = await transport.fetchState();
  director.applyState(initial, { isInitial: true });

  let lastTime = performance.now();
  const tick = (now) => {
    const dtSec = Math.min(0.05, Math.max(0.001, (now - lastTime) / 1000));
    lastTime = now;
    physics.step(dtSec);
    director.update(dtSec);
    threeWorld.update(dtSec);
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

bootFullMock().catch((err) => {
  console.error('[Full Mock Boot Error]', err);
});
