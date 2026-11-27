/**
 * Deterministic Beat Choreographer & Timeline Sequencer for 《光点计划 III》.
 *
 * Single source of truth for:
 *  - Deduplicating fx_events by monotonic seq (never re-triggering old speed rolls)
 *  - Strict causal ordering:
 *      1. Pre-roll events (turn_recycle / reveal / draw / cost / pre-roll passives)
 *      2. Speed roll attempts sequentially (clearing previous attempt's 3D dice before re-roll;
 *         keeping speed & initiative concealed until the final winning attempt lands)
 *      3. Combat dice roll -> number reveal (0.26s) -> physical Matter.js clash collision (~0.42s)
 *         -> win/lose stamp + winner stance -> post-clash effects
 *      4. Hit choreography: combat_strike ALWAYS plays BEFORE damage / lightcore_damage / death
 *         and BEFORE HP / Lightcore bars drop
 *  - Clean beat-level cancellation & completion gating (`isSettled`) so auto-pace NEVER cuts off
 *    in-flight animations or stacks stale 3D dice from earlier beats.
 */

export function combatRollKey(turn, kind, duelNumber, roundId, side, dieNumber, lane = 'front') {
  return `${turn || 0}:${kind || ''}:${duelNumber || 0}:${roundId || 0}:${side || 0}:${lane || 'front'}:${dieNumber || 0}`;
}

const LIGHTCORE_KINDS = new Set([
  'lightcore_damage',
  'lightcore_healed',
  'lightcore_collapse',
  'lightcore_restored',
  'lightcore_overflow',
  'lightcore_max_changed',
]);

const IMPACT_CONSEQUENCE_KINDS = new Set([
  'damage',
  'lose_hp',
  ...LIGHTCORE_KINDS,
  'breath_crit',
  'stagger_check',
  'character_death',
  'card_destroyed',
  'die_destroyed',
]);

/**
 * Coalesce redundant same-round dice_roll + dice_clash pairs and reorder any
 * combat_strike strictly before the impact consequences (damage / lightcore / death)
 * produced in the same hit step.
 */
export function normalizeBeatEvents(rawEvents) {
  const events = Array.isArray(rawEvents) ? rawEvents.slice() : [];
  if (!events.length) return [];

  // 1. Coalesce same-round dice_roll + dice_clash into a single dice_clash.
  const clashRounds = new Set();
  for (const ev of events) {
    if (ev.kind === 'dice_clash') {
      clashRounds.add(`${ev.turn || 0}:${ev.duel_kind || ''}:${ev.duel_number || 0}:${ev.round_id || 0}`);
    }
  }
  const coalesced = clashRounds.size
    ? events.filter((ev) => {
        if (ev.kind !== 'dice_roll') return true;
        const rk = `${ev.turn || 0}:${ev.duel_kind || ''}:${ev.duel_number || 0}:${ev.round_id || 0}`;
        return !clashRounds.has(rk);
      })
    : events;

  // 2. Ensure every combat_strike plays BEFORE the direct impact consequences
  //    (damage/lightcore/death) of that same hit, WITHOUT ever pushing pre-hit events
  //    (cost_pay, on_skill_use shield/status/passive, card_pull, cards_reveal) behind combat_strike!
  const out = [];
  let pendingConsequences = [];
  const flushConsequences = () => {
    if (pendingConsequences.length) {
      out.push(...pendingConsequences);
      pendingConsequences = [];
    }
  };
  for (const ev of coalesced) {
    if (ev.kind === 'combat_strike') {
      out.push(ev);
      flushConsequences();
    } else if (IMPACT_CONSEQUENCE_KINDS.has(ev.kind)) {
      pendingConsequences.push(ev);
    } else {
      flushConsequences();
      out.push(ev);
    }
  }
  flushConsequences();
  return out;
}

export class TimelineSequencer {
  constructor(hooks = {}) {
    this.hooks = hooks;
    this.lastFxSeq = 0;
    this.beatGen = 0;
    this.isSettled = true;
    this.activeRollKind = null;
    this.pendingSpeedReveal = false;
    this.revealedRollKeys = new Set();
    this.pendingCombatRollKeys = new Set();
    this.pendingClashOutcomeKeys = new Set();
    this.deferredHpOverrides = new Map();
    this.deferredLightcoreOverrides = new Map();
    this.deferredActorStateOverrides = new Map();
    this._timers = new Set();
    this._scheduleFn = hooks.schedule || ((fn, ms) => setTimeout(fn, ms));
    this._cancelFn = hooks.cancel || ((id) => clearTimeout(id));
  }

  get isRollAnimating() {
    return Boolean(
      this.activeRollKind
      || this.pendingSpeedReveal
      || this.pendingCombatRollKeys.size > 0
      || this.pendingClashOutcomeKeys.size > 0
    );
  }

  _setActiveRollKind(kind) {
    const prev = this.isRollAnimating;
    this.activeRollKind = kind;
    const next = this.isRollAnimating;
    if (prev !== next) {
      this.hooks.onRollLockChanged?.(next, this.activeRollKind);
    }
  }

  _clearTimers() {
    for (const id of this._timers) this._cancelFn(id);
    this._timers.clear();
  }

  _later(gen, delayMs, fn) {
    if (delayMs <= 0) {
      if (this.beatGen === gen) fn();
      return;
    }
    const id = this._scheduleFn(() => {
      this._timers.delete(id);
      if (this.beatGen === gen) fn();
    }, delayMs);
    this._timers.add(id);
  }

  resetMatch() {
    this._clearTimers();
    this.beatGen += 1;
    this.lastFxSeq = 0;
    this.isSettled = true;
    this.activeRollKind = null;
    this.pendingSpeedReveal = false;
    this.revealedRollKeys.clear();
    this.pendingCombatRollKeys.clear();
    this.pendingClashOutcomeKeys.clear();
    this.deferredHpOverrides.clear();
    this.deferredLightcoreOverrides.clear();
    this.deferredActorStateOverrides.clear();
    this.deferredActorStateOverrides.clear();
    this.hooks.clearDice?.();
    this.hooks.clearClashGroups?.();
    this.hooks.onRollLockChanged?.(false, null);
  }

  resetTurn() {
    this.revealedRollKeys.clear();
  }

  isDieScoreConcealed(rollKey, die) {
    if (!die) return false;
    if (this.pendingCombatRollKeys.has(rollKey)) return true;
    return die.rolled_value == null && die.result !== 'skip';
  }

  isDieOutcomeConcealed(rollKey, die) {
    if (!die) return false;
    if (this.pendingCombatRollKeys.has(rollKey)) return true;
    if (this.pendingClashOutcomeKeys.has(rollKey)) return true;
    return false;
  }

  /**
   * Prepare concealment & deferred HP/Lightcore overrides BEFORE the view rebuilds.
   * Returns a beat plan to pass into `playBeat(plan)` right after view rebuild.
   */
  prepareBeat({ prevState, nextState, isInitial = false, matchChanged = false, characterKeyFn }) {
    if (matchChanged) this.resetMatch();

    const prevTurn = prevState?.frame?.turn;
    const nextTurn = nextState?.frame?.turn;
    const prevCombat = prevState?.frame?.combat;
    const nextCombat = nextState?.frame?.combat;
    const isCombat = Boolean(nextCombat);
    const combatRoundChanged = Boolean(
      prevCombat && (!nextCombat
        || prevCombat.kind !== nextCombat.kind
        || prevCombat.duel_number !== nextCombat.duel_number
        || prevCombat.round_id !== nextCombat.round_id)
    );

    // Detect mid-round card withdrawal / blank-round replacement so its 3D die retires immediately!
    const withdrawnLanes = [];
    if (!isInitial && !matchChanged && prevCombat && nextCombat && !combatRoundChanged) {
      for (const sideNum of [1, 2]) {
        const ps = (prevCombat.sides || []).find((s) => s.side === sideNum);
        const ns = (nextCombat.sides || []).find((s) => s.side === sideNum);
        const pFront = ps?.card_instance_id ?? ps?.card_id ?? null;
        const nFront = ns?.card_instance_id ?? ns?.card_id ?? null;
        if (pFront != null && pFront !== nFront) withdrawnLanes.push({ side: sideNum, lane: 'front' });
        const pRear = ps?.rear?.card_instance_id ?? ps?.rear?.card_id ?? null;
        const nRear = ns?.rear?.card_instance_id ?? ns?.rear?.card_id ?? null;
        if (pRear != null && pRear !== nRear) withdrawnLanes.push({ side: sideNum, lane: 'rear' });
      }
    }

    const events = nextState?.fx_events || [];
    let rawFresh = [];
    if (!isInitial) {
      rawFresh = events.filter((e) => e.seq > this.lastFxSeq);
      if (events.length) {
        const tailSeq = events[events.length - 1].seq;
        if (tailSeq > this.lastFxSeq) this.lastFxSeq = tailSeq;
      }
    }
    const fresh = isInitial ? [] : normalizeBeatEvents(rawFresh);

    // Same-round non-withdrawing refresh guard (e.g. pausing, queuing pre-declarations, or setting default target):
    // preserve in-flight roll animations, timers, score concealment, and deferred HP overrides!
    if (!isInitial && !matchChanged && prevTurn === nextTurn && !combatRoundChanged
        && withdrawnLanes.length === 0 && fresh.length === 0 && !this.isSettled) {
      return { gen: this.beatGen, keepRunning: true, isInitial: false, initialSpeed: null, initialPassives: [], fresh: [], nextTurn };
    }

    this._clearTimers();
    this.beatGen += 1;
    const gen = this.beatGen;

    if (isInitial || matchChanged || prevTurn !== nextTurn) {
      this.revealedRollKeys.clear();
    }

    this.pendingSpeedReveal = false;
    this.pendingCombatRollKeys.clear();
    this.pendingClashOutcomeKeys.clear();
    this.deferredHpOverrides.clear();
    this.deferredLightcoreOverrides.clear();
    this.deferredActorStateOverrides.clear();

    let initialSpeed = null;
    let initialPassives = [];

    if (isInitial) {
      if (events.length) {
        this.lastFxSeq = events[events.length - 1].seq;
        const candidateSpeed = [...events].reverse().find((e) => e.kind === 'speed_roll') || null;
        if (candidateSpeed && !isCombat && (nextTurn || 0) <= 1) {
          initialSpeed = candidateSpeed;
          this.pendingSpeedReveal = true;
        }
        if (!isCombat && (nextTurn || 0) <= 1) {
          initialPassives = events.filter((e) => e.kind === 'passive_trigger');
        }
      }
      if (isCombat) {
        const combat = nextState.frame.combat;
        for (const s of combat.sides || []) {
          if (s.die && s.die.rolled_value != null) {
            this.revealedRollKeys.add(combatRollKey(
              nextTurn, combat.kind, combat.duel_number, combat.round_id, s.side, s.die_number ?? s.die.position, 'front'
            ));
          }
          if (s.rear?.die && s.rear.die.rolled_value != null) {
            this.revealedRollKeys.add(combatRollKey(
              nextTurn, combat.kind, combat.duel_number, combat.round_id, s.side, s.rear.die_number ?? s.rear.die.position, 'rear'
            ));
          }
        }
      }
    } else {
      if (withdrawnLanes.length > 0) {
        this.hooks.clearClashGroups?.();
        for (const w of withdrawnLanes) {
          this.hooks.retireSideDice?.(w.side, w.lane);
        }
      } else if (combatRoundChanged || (!isCombat && prevCombat)) {
        this.hooks.clearClashGroups?.();
        const nextRoundKey = nextCombat
          ? `${nextTurn || 0}:${nextCombat.kind || ''}:${nextCombat.duel_number || 0}:${nextCombat.round_id || 0}`
          : null;
        this.hooks.retireStaleDice?.(nextRoundKey);
      }

      if (fresh.some((e) => e.kind === 'speed_roll')) {
        this.pendingSpeedReveal = true;
      }

      for (const ev of fresh) {
        if (ev.kind === 'dice_roll' || ev.kind === 'dice_clash') {
          const nonSkipped = (ev.sides || []).filter((sd) => !sd.skipped);
          const isRealPairClash = ev.kind === 'dice_clash'
            && new Set(nonSkipped.map((sd) => sd.side)).size === 2;
          for (const sd of ev.sides || []) {
            if (sd.skipped || sd.rolled_value == null) continue;
            const k = combatRollKey(
              ev.turn ?? nextTurn, ev.duel_kind, ev.duel_number, ev.round_id, sd.side, sd.die_number ?? sd.position, sd.lane || 'front'
            );
            if (!this.revealedRollKeys.has(k)) {
              this.pendingCombatRollKeys.add(k);
            }
            if (isRealPairClash) {
              this.pendingClashOutcomeKeys.add(k);
            }
          }
        }
      }

      // Defer HP, Lightcore, Shields, Statuses & Alive flags until dice reveal & strike impact!
      const hasDeferredGate = this.pendingCombatRollKeys.size > 0
        || this.pendingClashOutcomeKeys.size > 0
        || fresh.some((e) => e.kind === 'combat_strike');
      if (hasDeferredGate && prevState?.frame?.players && characterKeyFn) {
        const prevChars = new Map();
        for (const p of prevState.frame.players) {
          for (const c of p.characters || []) {
            prevChars.set(characterKeyFn(c.id, p.side), c);
          }
        }
        const deferActorVisualState = (cid, side) => {
          if (!cid || !side) return;
          const ck = characterKeyFn(cid, side);
          if (this.deferredActorStateOverrides.has(ck)) return;
          const prev = prevChars.get(ck);
          if (!prev) return;
          this.deferredActorStateOverrides.set(ck, {
            alive: prev.alive,
            shields: prev.shields ? { ...prev.shields } : {},
            statuses: prev.statuses ? { ...prev.statuses } : {},
            status_details: prev.status_details ? { ...prev.status_details } : {},
            bleed_burst: Boolean(prev.bleed_burst),
          });
        };
        for (const ev of fresh) {
          if (ev.kind === 'damage' || ev.kind === 'lose_hp' || ev.kind === 'heal') {
            const ck = characterKeyFn(ev.target_id, ev.target_side);
            const prev = prevChars.get(ck);
            if (prev) this.deferredHpOverrides.set(ck, prev.hp);
            deferActorVisualState(ev.target_id, ev.target_side);
          } else if (LIGHTCORE_KINDS.has(ev.kind)) {
            const ck = characterKeyFn(ev.target_id, ev.target_side);
            const prev = prevChars.get(ck);
            if (prev) {
              this.deferredLightcoreOverrides.set(ck, {
                hp: prev.lightcore_hp,
                max: prev.max_lightcore_hp,
              });
            }
            deferActorVisualState(ev.target_id, ev.target_side);
          } else if (ev.kind === 'status_change' || ev.kind === 'shield_gain' || ev.kind === 'character_death') {
            deferActorVisualState(ev.character_id, ev.side);
          } else if (ev.kind === 'stagger_check') {
            deferActorVisualState(ev.target_id, ev.target_side);
          }
        }
      }
    }

    const willAnimate = isInitial
      ? Boolean(initialSpeed || initialPassives.length)
      : fresh.length > 0;
    this.isSettled = !willAnimate;

    return { gen, isInitial, initialSpeed, initialPassives, fresh, nextTurn };
  }

  playBeat(plan) {
    if (!plan || plan.keepRunning || this.beatGen !== plan.gen) return;
    const { gen, isInitial, initialSpeed, initialPassives, fresh, nextTurn } = plan;

    if (isInitial) {
      if (initialSpeed) {
        this._setActiveRollKind('speed_roll');
        this.hooks.playSpeedRoll?.(initialSpeed, {
          silent: true,
          onReveal: () => {
            if (this.beatGen !== gen) return;
            this.pendingSpeedReveal = false;
            this._setActiveRollKind(null);
            this.hooks.onSpeedRevealed?.();
            this._finishBeat(gen);
          },
        });
      } else {
        this._finishBeat(gen);
      }
      initialPassives.forEach((ev, idx) => {
        this._later(gen, 160 + idx * 180, () => this.hooks.playFx?.(ev, { silent: true }));
      });
      return;
    }

    if (!fresh.length) {
      this._finishBeat(gen);
      return;
    }

    this._runQueue(gen, fresh, 0, nextTurn);
  }

  _finishBeat(gen) {
    if (this.beatGen !== gen) return;
    this.pendingSpeedReveal = false;
    this.pendingCombatRollKeys.clear();
    this.pendingClashOutcomeKeys.clear();
    this._setActiveRollKind(null);
    if (this.deferredHpOverrides.size || this.deferredLightcoreOverrides.size || this.deferredActorStateOverrides.size) {
      const hadActorState = this.deferredActorStateOverrides.size > 0;
      this.deferredHpOverrides.clear();
      this.deferredLightcoreOverrides.clear();
      this.deferredActorStateOverrides.clear();
      this.hooks.releaseDeferredVitals?.({ rebuildActors: hadActorState });
    }
    this.isSettled = true;
    this.hooks.onBeatSettled?.();
  }

  _runQueue(gen, queue, index, nextTurn) {
    if (this.beatGen !== gen) return;
    if (index >= queue.length) {
      this._finishBeat(gen);
      return;
    }

    const ev = queue[index];

    // 1. Speed roll (strictly block queue until any previous die naturally fades out!)
    if (ev.kind === 'speed_roll') {
      if (this.hooks.hasActiveDice?.()) {
        this._setActiveRollKind('speed_roll');
        this.hooks.waitUntilDiceCleared?.(() => {
          if (this.beatGen === gen) this._runQueue(gen, queue, index, nextTurn);
        });
        return;
      }
      const hasMoreSpeed = queue.slice(index + 1).some((x) => x.kind === 'speed_roll');
      this._setActiveRollKind('speed_roll');
      this.hooks.playSpeedRoll?.(ev, {
        silent: false,
        onReveal: () => {
          if (this.beatGen !== gen) return;
          if (hasMoreSpeed) {
            this._later(gen, 240, () => this._runQueue(gen, queue, index + 1, nextTurn));
            return;
          }
          this.pendingSpeedReveal = false;
          this._setActiveRollKind(null);
          this.hooks.onSpeedRevealed?.();
          this._later(gen, 80, () => this._runQueue(gen, queue, index + 1, nextTurn));
        },
      });
      return;
    }

    // 2. Combat dice clash:
    //    Step A: Launch 3D dice -> 0.26s reveal rolled values on medallions (or 0.04s if already rolled)
    //    Step B: Physical Matter.js collision -> stamp win/lose + trigger winner stance!
    //    Step C: Release deferred vitals & play post-clash consequences!
    if (ev.kind === 'dice_clash') {
      const roundKey = `${ev.turn ?? nextTurn ?? 0}:${ev.duel_kind || ''}:${ev.duel_number || 0}:${ev.round_id || 0}`;
      this.hooks.retireStaleDice?.(roundKey);
      const rollKeys = (ev.sides || [])
        .filter((sd) => !sd.skipped && sd.rolled_value != null)
        .map((sd) => combatRollKey(
          ev.turn ?? nextTurn, ev.duel_kind, ev.duel_number, ev.round_id, sd.side, sd.die_number ?? sd.position, sd.lane || 'front'
        ));
      const needsNumberReveal = rollKeys.some((k) => this.pendingCombatRollKeys.has(k));
      if (needsNumberReveal && !this.hooks.retireStaleDice && this.hooks.hasActiveDice?.()) {
        this._setActiveRollKind('dice_clash');
        this.hooks.waitUntilDiceCleared?.(() => {
          if (this.beatGen === gen) this._runQueue(gen, queue, index, nextTurn);
        });
        return;
      }
      this._setActiveRollKind('dice_clash');
      const revealNumbers = () => {
        if (this.beatGen !== gen) return;
        for (const k of rollKeys) {
          this.revealedRollKeys.add(k);
          this.pendingCombatRollKeys.delete(k);
        }
        this.hooks.onCombatMedallionsChanged?.();
      };
      const revealOutcome = () => {
        if (this.beatGen !== gen) return;
        for (const k of rollKeys) {
          this.revealedRollKeys.add(k);
          this.pendingCombatRollKeys.delete(k);
          this.pendingClashOutcomeKeys.delete(k);
        }
        this._setActiveRollKind(null);
        this.hooks.onCombatMedallionsChanged?.();
        this._later(gen, 90, () => this._runQueue(gen, queue, index + 1, nextTurn));
      };

      this.hooks.clearClashGroups?.();
      this.hooks.playDiceClash?.(ev, {
        needsNumberReveal,
        onNumbersRevealed: revealNumbers,
        onOutcomeImpact: revealOutcome,
      });
      return;
    }

    // 3. Solo / early combat die roll:
    //    Retires any earlier round's lingering dice in 0.16s (ZERO dead-air freeze!) and launches immediately!
    if (ev.kind === 'dice_roll') {
      const roundKey = `${ev.turn ?? nextTurn ?? 0}:${ev.duel_kind || ''}:${ev.duel_number || 0}:${ev.round_id || 0}`;
      this.hooks.retireStaleDice?.(roundKey);
      if (!this.hooks.retireStaleDice && this.hooks.hasActiveDice?.()) {
        this._setActiveRollKind('dice_roll');
        this.hooks.waitUntilDiceCleared?.(() => {
          if (this.beatGen === gen) this._runQueue(gen, queue, index, nextTurn);
        });
        return;
      }
      const rollKeys = (ev.sides || [])
        .filter((sd) => !sd.skipped && sd.rolled_value != null)
        .map((sd) => combatRollKey(
          ev.turn ?? nextTurn, ev.duel_kind, ev.duel_number, ev.round_id, sd.side, sd.die_number ?? sd.position, sd.lane || 'front'
        ));
      this._setActiveRollKind('dice_roll');
      this.hooks.clearClashGroups?.();
      this.hooks.playDiceRoll?.(ev, {
        onNumbersRevealed: () => {
          if (this.beatGen !== gen) return;
          for (const k of rollKeys) {
            this.revealedRollKeys.add(k);
            this.pendingCombatRollKeys.delete(k);
          }
          this._setActiveRollKind(null);
          this.hooks.onCombatMedallionsChanged?.();
          this._runQueue(gen, queue, index + 1, nextTurn);
        },
      });
      return;
    }

    // 4. Attack strike: plays windup trajectory at t = 0, then releases deferred HP/Lightcore bars
    //    and triggers hit consequences at the exact contact arrival frame (`impactMs`)!
    if (ev.kind === 'combat_strike') {
      const fxTiming = this.hooks.playFx?.(ev, { silent: false }) || {};
      const impactMs = Math.max(40, Math.min(650, Number(fxTiming.impactMs) || 95));
      this._later(gen, impactMs, () => {
        if (this.beatGen !== gen) return;
        if (this.deferredHpOverrides.size || this.deferredLightcoreOverrides.size || this.deferredActorStateOverrides.size) {
          const hadActorState = this.deferredActorStateOverrides.size > 0;
          this.deferredHpOverrides.clear();
          this.deferredLightcoreOverrides.clear();
          this.deferredActorStateOverrides.clear();
          this.hooks.releaseDeferredVitals?.({ rebuildActors: hadActorState });
        }
        this._runQueue(gen, queue, index + 1, nextTurn);
      });
      return;
    }

    // 5. All other settled effects (damage, lightcore_damage, lightcore_collapse, card_destroyed,
    //    die_destroyed, heal, status_change, shield_gain, passive_trigger, card_pull, cards_reveal, etc.)
    if (IMPACT_CONSEQUENCE_KINDS.has(ev.kind) && (this.deferredHpOverrides.size || this.deferredLightcoreOverrides.size)) {
      this.deferredHpOverrides.clear();
      this.deferredLightcoreOverrides.clear();
      this.hooks.releaseDeferredVitals?.();
    }
    this.hooks.playFx?.(ev, { silent: false });
    const stepDelay = this._stepDelayMs(ev.kind);
    this._later(gen, stepDelay, () => this._runQueue(gen, queue, index + 1, nextTurn));
  }

  _stepDelayMs(kind) {
    if (kind === 'card_pull') return 260;
    if (kind === 'cards_reveal') return 240;
    if (kind === 'lightcore_collapse') return 260;
    if (kind === 'card_destroyed' || kind === 'die_destroyed') return 180;
    if (kind === 'damage' || kind === 'lightcore_damage') return 130;
    if (kind === 'character_death') return 220;
    if (kind === 'passive_trigger') return 95;
    return 45;
  }
}
