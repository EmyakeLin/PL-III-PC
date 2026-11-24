/**
 * Decoupled Presentation FX Registry for 《光点计划 III》.
 *
 * Maps each settled TableBridge / BattleMatch event kind to its visual & audio
 * execution cleanly outside GameDirector. Adding a new effect visual is adding
 * one self-contained handler entry here.
 */

import {
  DIE_STYLE,
  INK,
  LEVEL_MAX,
  SHIELD_STYLE,
  SIDE_THEME,
  getStatusColor,
} from './design_system.js';

const CIRCLED = ['①', '②', '③', '④', '⑤', '⑥', '⑦', '⑧', '⑨', '⑩', '⑪', '⑫'];
const GRADE_LABEL = { normal: '普通', pierce: '穿甲', concept: '超穿甲', real: '真实' };
const LIGHTCORE_COLOR = 0x2698c8;
const LIGHTCORE_COLLAPSE_COLOR = 0x8b46d4;
const DESTROY_COLOR = 0xb83a2a;

export function createPresentationFx(env) {
  const {
    three,
    physics,
    audio,
    fxDirector,
    getLayout,
    getState,
    actorPos,
    getMotion,
    characterKey,
    resolveCharColor,
    resolveCharColorHex,
    triggerShake,
    spawnFloater,
    showBanner,
    getDeckPile,
    getPileCenter,
    getCostHud,
    getCostAnchor,
    getRegularSlotRect,
    getPreRevealSlotRect,
    getPassivePlate,
    pulsePassive,
    flashLightcore,
  } = env;

  function playSpeedRoll(ev, { silent = false, onReveal = null } = {}) {
    if (!silent) audio.diceRoll();
    const { arenaX, arenaW, arenaTop } = getLayout();
    const cx = arenaX + arenaW * 0.5;
    const cy = arenaTop + 175;
    const launchSpecs = [];
    for (const s of ev.sides || []) {
      const sign = s.side === 1 ? -1 : 1;
      const rolls = (s.rolls || []).slice(0, 3);
      for (const [idx, r] of rolls.entries()) {
        launchSpecs.push({
          sides: 4,
          dieType: 'speed',
          rolledValue: r.speed,
          subLabel: (r.name || '').slice(0, 4),
          startX: cx + sign * 220,
          startY: cy + 50,
          targetX: cx + sign * (78 + idx * 56),
          targetY: cy,
          radius: 23,
          lifetime: 1.35,
          revealDelay: 0.26,
        });
      }
    }
    const finish = () => {
      if (ev.winner_side === null) {
        showBanner(`速度平局（第 ${ev.attempt} 次）· 重掷`, INK.gold, 1.1);
      } else {
        const s1 = ev.sides.find((x) => x.side === 1)?.team_speed ?? 0;
        const s2 = ev.sides.find((x) => x.side === 2)?.team_speed ?? 0;
        showBanner(`速度 ${s1} : ${s2} · ${SIDE_THEME[ev.winner_side].name}先手`, SIDE_THEME[ev.winner_side].accent, 1.4);
      }
      onReveal?.();
    };
    if (!launchSpecs.length) {
      finish();
      return;
    }
    let remaining = launchSpecs.length;
    const onOne = () => {
      remaining -= 1;
      if (remaining === 0) finish();
    };
    for (const spec of launchSpecs) {
      three.launchDie({ ...spec, onReveal: onOne });
    }
  }

  function playDiceRoll(ev, { onNumbersRevealed = null } = {}) {
    audio.diceRoll();
    const { arenaX, arenaW, arenaTop } = getLayout();
    const center = env.getClashCenter ? env.getClashCenter() : { x: arenaX + arenaW * 0.5, y: arenaTop + 132 };
    const cx = center.x;
    const cy = center.y;
    const sidesList = ev.sides || [];
    if (!sidesList.length) {
      onNumbersRevealed?.();
      return;
    }
    let remaining = sidesList.length;
    const onOne = () => {
      remaining -= 1;
      if (remaining === 0) onNumbersRevealed?.();
    };
    const distinctSides = new Set(sidesList.map((s) => s.side));
    const isPaired = distinctSides.size === 2;
    const bySideCount = {
      1: sidesList.filter((s) => s.side === 1).length,
      2: sidesList.filter((s) => s.side === 2).length,
    };
    const seenBySide = { 1: 0, 2: 0 };
    for (const sd of sidesList) {
      const isP1 = sd.side === 1;
      const idxOnSide = seenBySide[sd.side] || 0;
      seenBySide[sd.side] = idxOnSide + 1;
      const multiSide = (bySideCount[sd.side] || 1) > 1;
      const offY = multiSide ? (idxOnSide === 0 ? -28 : 28) : 0;
      const sides = sd.roll_max || LEVEL_MAX[sd.level || sd.printed_level] || 6;
      const displayVal = sd.clash_score ?? sd.final_score ?? sd.rolled_value ?? '—';
      const laneTag = sd.lane === 'rear' ? '后置 ' : '';
      three.launchDie({
        side: sd.side,
        lane: sd.lane || 'front',
        sides,
        dieType: sd.type || 'blank',
        rolledValue: displayVal,
        subLabel: `${laneTag}1~${sides}`,
        startX: cx + (isP1 ? -240 : 240),
        startY: cy + 28 + offY,
        targetX: isPaired ? cx + (isP1 ? -86 : 86) : cx + (isP1 ? 30 : -30),
        targetY: cy + offY,
        radius: multiSide ? 24 : 28,
        lifetime: isPaired ? 2.2 : 1.35,
        willClash: isPaired,
        onReveal: onOne,
      });
    }
  }

  function playClashOutcomeStances(ev) {
    for (const sd of ev.sides || []) {
      if (!sd.character_id) continue;
      if (sd.result === 'win' && sd.type === 'evade') {
        getMotion(sd.character_id, sd.side).evade = 1.0;
        const pos = actorPos(sd.character_id, sd.side);
        three.triggerRipple(pos.x, pos.y, DIE_STYLE.evade.color);
      } else if (sd.result === 'win' && sd.type === 'block') {
        const pos = actorPos(sd.character_id, sd.side);
        three.spawnBlockBarrier({ x: pos.x + (sd.side === 1 ? 36 : -36), y: pos.y, colorHex: DIE_STYLE.block.color });
      } else if (sd.result === 'win') {
        getMotion(sd.character_id, sd.side).lunge = 0.65;
        const winRecipe = fxDirector.resolveClashWinRecipe(sd);
        if (winRecipe) {
          const opp = (ev.sides || []).find((o) => o.side !== sd.side);
          fxDirector.playRecipe(winRecipe, {
            event: ev,
            attackerId: sd.character_id,
            defenderId: opp?.character_id || null,
            attackerSide: sd.side,
            defenderSide: opp?.side || null,
            defaultColor: resolveCharColor(sd.character_id, sd.side),
          });
        }
      }
    }
  }

  function playDiceClash(ev, { needsNumberReveal = true, onNumbersRevealed = null, onOutcomeImpact = null } = {}) {
    if (needsNumberReveal) audio.diceRoll();
    const { arenaX, arenaW, arenaTop } = getLayout();
    const center = env.getClashCenter ? env.getClashCenter() : { x: arenaX + arenaW * 0.5, y: arenaTop + 132 };
    const cx = center.x;
    const cy = center.y;
    const p1List = (ev.sides || []).filter((s) => s.side === 1 && !s.skipped);
    const p2List = (ev.sides || []).filter((s) => s.side === 2 && !s.skipped);

    const alreadyRolled = !needsNumberReveal;
    const revealDelay = needsNumberReveal ? 0.26 : 0;
    if (p1List.length > 0 && p2List.length > 0) {
      const p1Wins = p1List.some((d) => d.result === 'win');
      const p2Wins = p2List.some((d) => d.result === 'win');
      const outcome = p1Wins && !p2Wins ? 'left_win' : p2Wins && !p1Wins ? 'right_win' : 'draw';
      const winDie = [...p1List, ...p2List].find((d) => d.result === 'win') || null;
      const winColor = winDie ? (DIE_STYLE[winDie.type]?.color || INK.gold) : INK.gold;
      // Collision radius = 34 matches outer 1.13x ink silhouette + polyhedron corners -> ZERO clipping (0穿模)!
      const group = physics.createClashDicePair({
        cx,
        cy,
        radius: 34,
        leftCount: p1List.length,
        rightCount: p2List.length,
        outcome,
        winnerColor: winColor,
        lungeDelay: needsNumberReveal ? 0.34 : 0.22,
        alreadyRolled,
        onImpact: () => {
          playClashOutcomeStances(ev);
          onOutcomeImpact?.();
        },
      });
      group.winDieType = winDie?.type || null;

      const pairs = [
        ...p1List.map((sd, i) => [sd, group.leftBodies[i] || group.leftBody]),
        ...p2List.map((sd, i) => [sd, group.rightBodies[i] || group.rightBody]),
      ];
      let remaining = pairs.length;
      const onOneNum = () => {
        remaining -= 1;
        if (remaining === 0) onNumbersRevealed?.();
      };
      for (const [sd, body] of pairs) {
        const sides = sd.roll_max || LEVEL_MAX[sd.level || sd.printed_level] || 6;
        const displayVal = sd.clash_score ?? sd.rolled_value ?? '—';
        const lane = sd.lane || 'front';
        const subLabel = `${lane === 'rear' ? '后置 ' : ''}1~${sides}`;
        if (alreadyRolled && three.attachClashBody?.(sd.side, {
          lane,
          physicsBody: body,
          rolledValue: displayVal,
          subLabel,
          dieType: sd.type || 'blank',
          lifetime: 1.75,
          onReveal: onOneNum,
        })) {
          continue;
        }
        const multiSide = (sd.side === 1 ? p1List.length : p2List.length) > 1;
        three.launchDie({
          side: sd.side,
          lane,
          sides,
          dieType: sd.type || 'blank',
          rolledValue: displayVal,
          subLabel,
          startX: body.position.x,
          startY: body.position.y,
          targetX: cx,
          targetY: cy + (body._offsetY || 0),
          physicsBody: body,
          radius: multiSide ? 24 : 28,
          lifetime: 1.75,
          revealDelay,
          alreadyRolled,
          onReveal: onOneNum,
        });
      }
      return;
    }

    const sidesList = ev.sides || [];
    if (!sidesList.length) {
      onNumbersRevealed?.();
      playClashOutcomeStances(ev);
      onOutcomeImpact?.();
      return;
    }
    let remaining = sidesList.length;
    const onOne = () => {
      remaining -= 1;
      if (remaining === 0) {
        onNumbersRevealed?.();
        playClashOutcomeStances(ev);
        onOutcomeImpact?.();
      }
    };
    for (const sd of sidesList) {
      const lane = sd.lane || 'front';
      // Never spawn a duplicate die on top of an already-rolled live die for this side & lane!
      if (alreadyRolled && three.hasActiveDieForSide?.(sd.side, lane)) {
        onOne();
        continue;
      }
      const isP1 = sd.side === 1;
      const sides = sd.roll_max || LEVEL_MAX[sd.level || sd.printed_level] || 6;
      three.launchDie({
        side: sd.side,
        lane,
        sides,
        dieType: sd.type || 'blank',
        rolledValue: sd.skipped ? '跳过' : (sd.clash_score ?? sd.rolled_value ?? '—'),
        subLabel: sd.skipped ? '跳过' : `${lane === 'rear' ? '后置 ' : ''}1~${sides}`,
        startX: cx + (isP1 ? -240 : 240),
        startY: cy + 32,
        targetX: cx + (isP1 ? -86 : 86),
        targetY: cy,
        radius: 27,
        lifetime: 1.45,
        revealDelay: sd.skipped ? 0.14 : revealDelay,
        onReveal: onOne,
      });
    }
  }

  const HANDLERS = {
    passive_trigger(ev, { silent = false } = {}) {
      const key = `${characterKey(ev.character_id, ev.side)}:${ev.passive_name}`;
      pulsePassive(key, 1.55);
      const pos = actorPos(ev.character_id, ev.side);
      getMotion(ev.character_id, ev.side).passiveFlare = 1.0;

      const customRecipe = fxDirector.resolvePassiveRecipe(ev);
      const playedCustom = customRecipe && fxDirector.playRecipe(customRecipe, {
        event: ev,
        attackerId: ev.character_id,
        defenderId: ev.character_id,
        attackerSide: ev.side || null,
        defenderSide: ev.side || null,
        defaultColor: INK.gold,
      }, { silent });

      if (!playedCustom) {
        if (!silent) audio.passiveChime(1.0, ev.side === 1 ? -0.3 : 0.3);
        three.emitShockwave(pos.x, pos.y, INK.gold);
      }

      const plate = getPassivePlate(key);
      if (plate) {
        three.spawnEnergyBeam({
          fromX: plate.cx, fromY: plate.cy,
          toX: pos.x, toY: pos.y,
          colorHex: INK.gold,
          duration: 0.44,
        });
      }
      spawnFloater(pos.x, pos.y - 50, `${ev.passive_name}`, INK.gold, 14.5, 'passive');
    },

    status_change(ev) {
      const pos = actorPos(ev.character_id, ev.side);
      const col = getStatusColor(ev.status, INK.secondary);
      const sign = ev.delta > 0 ? '+' : '';
      const customRecipe = ev.delta > 0 ? fxDirector.resolveStatusRecipe(ev) : null;
      if (customRecipe) {
        fxDirector.playRecipe(customRecipe, {
          event: ev,
          attackerId: ev.character_id,
          defenderId: ev.character_id,
          attackerSide: ev.side || null,
          defaultColor: col,
        });
      } else if (ev.delta > 0) {
        three.triggerRipple(pos.x, pos.y, col);
      }
      spawnFloater(pos.x, pos.y - 26, `${ev.status} ${sign}${ev.delta}`, col, 13, 'status');
    },

    shield_gain(ev) {
      audio.shieldBlock();
      const pos = actorPos(ev.character_id, ev.side);
      const st = SHIELD_STYLE[ev.shield_kind] || SHIELD_STYLE.normal;
      three.spawnShieldDomePulse({ x: pos.x, y: pos.y, radius: 56, colorHex: st.color });
      spawnFloater(pos.x, pos.y - 36, `+${ev.amount} ${st.label}`, st.color, 14, 'shield');
    },

    combat_strike(ev) {
      const ds = DIE_STYLE[ev.die_type] || DIE_STYLE.slash;
      const customRecipe = fxDirector.resolveStrikeRecipe(ev);
      if (customRecipe) {
        const ran = fxDirector.playRecipe(customRecipe, {
          event: ev,
          attackerId: ev.attacker_id,
          defenderId: ev.target_id,
          attackerSide: ev.attacker_side,
          defenderSide: ev.target_side,
          defaultColor: resolveCharColor(ev.attacker_id, ev.attacker_side),
        });
        if (ran) {
          getMotion(ev.attacker_id, ev.attacker_side).lunge = 1.0;
          return;
        }
      }

      const from = fxDirector.resolveAnchor('attacker.bone_weapon', {
        attackerId: ev.attacker_id,
        defenderId: ev.target_id,
        attackerSide: ev.attacker_side,
        defenderSide: ev.target_side,
      });
      const to = actorPos(ev.target_id, ev.target_side);

      getMotion(ev.attacker_id, ev.attacker_side).lunge = 1.0;
      getMotion(ev.target_id, ev.target_side).recoil = 0.85;
      getMotion(ev.target_id, ev.target_side).hitFlash = 0.9;

      if (ev.die_type === 'slash') {
        audio.clashImpact(true);
        three.spawnSlashArc({ fromX: from.x, fromY: from.y, toX: to.x, toY: to.y, colorHex: ds.color });
      } else if (ev.die_type === 'pierce') {
        audio.clashImpact(false);
        three.spawnPierceLance({ fromX: from.x, fromY: from.y, toX: to.x, toY: to.y, colorHex: ds.color });
      } else {
        audio.clashImpact(true);
        three.spawnBluntImpact({ toX: to.x, toY: to.y, colorHex: ds.color });
        three.emitShockwave(to.x, to.y, ds.color);
        triggerShake(8, 0.24);
      }
    },

    damage(ev) {
      const pos = actorPos(ev.target_id, ev.target_side);
      const tx = pos.x;
      const ty = pos.y;
      const absorbedTotal = (ev.absorbed?.normal || 0) + (ev.absorbed?.reinforced || 0) + (ev.absorbed?.concept || 0);
      const erodedNormal = ev.eroded?.normal || 0;
      const erodedReinf = ev.eroded?.reinforced || 0;

      if (absorbedTotal > 0) {
        audio.shieldBlock();
        const col = ev.absorbed.concept ? SHIELD_STYLE.concept.color
          : ev.absorbed.reinforced ? SHIELD_STYLE.reinforced.color : SHIELD_STYLE.normal.color;
        three.spawnShieldDomePulse({ x: tx, y: ty, radius: 52, colorHex: col });
        physics.spawnShieldShards(tx, ty - 8, col, Math.min(10, 4 + absorbedTotal * 2), false);
        three.spawnImpactBurst(tx, ty - 8, col, 16, false);
        spawnFloater(tx, ty - 42, `护盾抵扣 -${absorbedTotal}`, col, 14.5, 'shield');
      }

      if (erodedNormal > 0 || erodedReinf > 0) {
        audio.shieldErode();
        three.emitShockwave(tx, ty - 6, erodedReinf > 0 ? SHIELD_STYLE.reinforced.color : SHIELD_STYLE.normal.color);
        if (erodedNormal > 0) {
          physics.spawnShieldShards(tx - 14, ty - 6, SHIELD_STYLE.normal.color, 10 + erodedNormal * 2, true);
          spawnFloater(tx - 18, ty - 58, `磨损 -${erodedNormal} 普通护盾`, SHIELD_STYLE.normal.color, 14, 'shield');
        }
        if (erodedReinf > 0) {
          physics.spawnShieldShards(tx + 10, ty - 6, SHIELD_STYLE.reinforced.color, 10 + erodedReinf * 2, true);
          spawnFloater(tx + 14, ty - 58, `磨损 -${erodedReinf} 强化护盾`, SHIELD_STYLE.reinforced.color, 14, 'shield');
        }
      }

      if (ev.hp_lost > 0) {
        const isHeavy = ev.hp_lost >= 3 || (ev.multiplier && ev.multiplier > 1);
        audio.hitDamage(isHeavy);
        getMotion(ev.target_id, ev.target_side).recoil = 1.0;
        getMotion(ev.target_id, ev.target_side).hitFlash = 1.0;
        triggerShake(Math.min(11, 5 + ev.hp_lost * 2), 0.28);
        three.spawnImpactBurst(tx, ty, 0xcf4330, 24, isHeavy);
        if (isHeavy) three.emitShockwave(tx, ty, 0xcf4330);
        const multTag = ev.multiplier > 1 ? ` ×${ev.multiplier}` : '';
        spawnFloater(tx, ty - 18, `-${ev.hp_lost} ${GRADE_LABEL[ev.grade] || ''}${multTag}`.trim(), 0xcf4330, 21, isHeavy ? 'heavy' : 'clash');
      } else if (absorbedTotal === 0) {
        spawnFloater(tx, ty - 14, '0', INK.muted, 13, 'status');
      }
    },

    lightcore_damage(ev) {
      const pos = actorPos(ev.target_id, ev.target_side);
      audio.shieldErode();
      flashLightcore?.(characterKey(ev.target_id, ev.target_side));
      getMotion(ev.target_id, ev.target_side).recoil = 0.72;
      getMotion(ev.target_id, ev.target_side).hitFlash = 0.75;
      three.emitShockwave(pos.x, pos.y, LIGHTCORE_COLOR, 0.48);
      three.spawnImpactBurst(pos.x, pos.y, LIGHTCORE_COLOR, 20, ev.amount >= 4);
      physics.spawnShieldShards(pos.x, pos.y - 6, LIGHTCORE_COLOR, Math.min(12, 4 + (ev.lost || ev.amount || 1)), true);
      const shown = ev.amount ?? ev.lost ?? 0;
      spawnFloater(pos.x, pos.y - 34, `-${shown} 光点`, LIGHTCORE_COLOR, 18.5, shown >= 4 ? 'heavy' : 'clash');
    },

    lightcore_collapse(ev) {
      const pos = actorPos(ev.target_id, ev.target_side);
      audio.clashImpact(true);
      triggerShake(11, 0.42);
      flashLightcore?.(characterKey(ev.target_id, ev.target_side));
      three.emitShockwave(pos.x, pos.y, LIGHTCORE_COLLAPSE_COLOR, 0.72);
      three.spawnImpactBurst(pos.x, pos.y, LIGHTCORE_COLLAPSE_COLOR, 38, true);
      physics.spawnShieldShards(pos.x, pos.y, LIGHTCORE_COLLAPSE_COLOR, 18, true);
      spawnFloater(pos.x, pos.y - 52, '✦ 光点形态群崩塌', LIGHTCORE_COLLAPSE_COLOR, 19.5, 'heavy');
      showBanner(`${ev.target_name || ''} · 光点形态群崩塌`.replace(/^ · /, ''), LIGHTCORE_COLLAPSE_COLOR, 1.8);
    },

    lightcore_restored(ev) {
      const pos = actorPos(ev.target_id, ev.target_side);
      three.triggerRipple(pos.x, pos.y, LIGHTCORE_COLOR);
      spawnFloater(pos.x, pos.y - 24, `完整度上限 → ${ev.max_lightcore ?? 0}`, LIGHTCORE_COLOR, 13.5, 'status');
    },

    card_destroyed(ev) {
      const pan = ev.side === 1 ? -0.28 : ev.side === 2 ? 0.28 : 0;
      audio.cardShatter(pan);
      const { arenaX, arenaW, arenaTop } = getLayout();
      const combatRect = env.getCombatCardRect?.(ev.side);
      const matchCombat = combatRect && (
        (ev.instance_id != null && combatRect.instanceId === ev.instance_id)
        || (ev.card_id && combatRect.cardId === ev.card_id)
      );
      let tx;
      let ty;
      let cardW = 132;
      let cardH = 182;
      if (matchCombat) {
        tx = combatRect.cx;
        ty = combatRect.cy;
        cardW = Math.min(180, Math.max(108, combatRect.w * 0.72));
        cardH = Math.min(230, Math.max(148, combatRect.h * 0.72));
      } else {
        const pos = ev.character_id ? actorPos(ev.character_id, ev.side) : { x: arenaX + arenaW * 0.5, y: arenaTop + 160 };
        tx = (pos.x + (arenaX + arenaW * 0.5)) * 0.5;
        ty = Math.min(pos.y, arenaTop + 210);
      }
      triggerShake(7.5, 0.26);
      three.spawnCardShatter({ x: tx, y: ty, width: cardW, height: cardH, colorHex: DESTROY_COLOR });
      physics.spawnShieldShards(tx, ty, DESTROY_COLOR, 16, true);
      const label = ev.card_name ? `「${ev.card_name}」已摧毁` : '技能已摧毁';
      spawnFloater(tx, ty - 34, label, DESTROY_COLOR, 17.5, 'heavy');
    },

    die_destroyed(ev) {
      const pan = ev.side === 1 ? -0.25 : ev.side === 2 ? 0.25 : 0;
      audio.dieShatter(pan);
      const { arenaX, arenaW, arenaTop } = getLayout();
      const med = env.getClashMedallionCenter?.(ev.side);
      const combatRect = env.getCombatCardRect?.(ev.side);
      const sign = ev.side === 1 ? -1 : ev.side === 2 ? 1 : 0;
      const tx = med ? med.x : combatRect ? combatRect.cx : (arenaX + arenaW * 0.5 + sign * 96);
      const ty = med ? med.y : combatRect ? combatRect.cy : (arenaTop + 132);
      const dieColor = DIE_STYLE[ev.die_type]?.color || DESTROY_COLOR;
      triggerShake(5.5, 0.20);
      three.spawnDieShatter({ x: tx, y: ty, colorHex: DESTROY_COLOR, dieColorHex: dieColor, radius: 28 });
      physics.spawnShieldShards(tx, ty, DESTROY_COLOR, 11, true);
      const posLabel = ev.position ? `第 ${ev.position} 骰已摧毁` : '骰子已摧毁';
      spawnFloater(tx, ty - 34, posLabel, DESTROY_COLOR, 16, 'heavy');
    },

    draw(ev) {
      audio.cardSlide();
      const piles = getDeckPile(ev.side);
      piles?.pulsePile('draw', 1.15);
      const p = piles?.getPileAnchor('draw') || getPileCenter(`${ev.side}:draw`);
      if (p) {
        const { arenaX, arenaW, handY } = getLayout();
        three.spawnCardFlipArc({
          fromX: p.x, fromY: p.y,
          toX: arenaX + arenaW * 0.5, toY: handY,
          width: 84, height: 116, title: '', accentHex: SIDE_THEME[ev.side].accentHex,
          flipFromBack: true, duration: 0.44, peakZ: 88,
        });
      }
    },

    draw_bottom(ev) {
      audio.cardPlace();
      getDeckPile(ev.side)?.pulsePile('draw', 0.9);
      const p = getDeckPile(ev.side)?.getPileAnchor('draw') || getPileCenter(`${ev.side}:draw`);
      if (p) {
        const { arenaX, arenaW, handY } = getLayout();
        three.spawnCardFlipArc({
          fromX: arenaX + arenaW * 0.5, fromY: handY - 60,
          toX: p.x, toY: p.y,
          width: 78, height: 106, title: '', accentHex: SIDE_THEME[ev.side].accentHex,
          flipFromBack: false, duration: 0.42, peakZ: 72,
        });
      }
    },

    cost_refill(ev) {
      audio.coinClink(ev.side === 1 ? 1.04 : 0.96);
      getCostHud(ev.side)?.triggerRefill?.();
      const anchor = getCostAnchor(ev.side);
      if (anchor) three.emitShockwave(anchor.x, anchor.y, INK.gold);
    },

    cost_pay(ev) {
      const hud = getCostHud(ev.side);
      const anchor = getCostAnchor(ev.side);
      if (ev.paid) {
        audio.coinClink(0.92);
        hud?.triggerSpend?.({
          charId: ev.character_id,
          sharedUsed: ev.shared_paid || 0,
          personalUsed: ev.personal_paid || 0,
          color: resolveCharColor(ev.character_id, ev.side),
        });
        if (anchor && (ev.shared_paid || ev.personal_paid)) {
          const total = (ev.shared_paid || 0) + (ev.personal_paid || 0);
          spawnFloater(anchor.x, anchor.y + 18, `-${total} 费`, 0xc95a2b, 13.5, 'status');
        }
      } else {
        audio.shieldErode();
        showBanner(`${ev.card_name} · ${ev.failure_reason || '支付受阻，跳过使用'}`, 0xcf4932, 1.8);
      }
    },

    card_pull(ev) {
      audio.cardFlip();
      const from = getRegularSlotRect(`${ev.from_duel}:${ev.defender_side}`);
      const to = getPreRevealSlotRect(ev.to_pre_reveal);
      const { arenaX, arenaW, arenaTop } = getLayout();
      three.spawnCardFlipArc({
        fromX: from?.cx ?? arenaX + arenaW * 0.5,
        fromY: from?.cy ?? arenaTop + 260,
        toX: to?.cx ?? arenaX + arenaW * 0.5,
        toY: to?.cy ?? arenaTop + 95,
        title: ev.card_name || '',
        accentHex: SIDE_THEME[ev.defender_side]?.accentHex || '#1e8f68',
        flipFromBack: true,
        duration: 0.54,
        peakZ: 145,
      });
      showBanner(`牵制：常规${CIRCLED[ev.from_duel - 1] || ev.from_duel}「${ev.card_name}」→ 开牌前${CIRCLED[ev.to_pre_reveal - 1] || ev.to_pre_reveal}`, INK.gold, 1.8);
    },

    cards_reveal(ev) {
      audio.cardFlip();
      if (typeof env.onCardsReveal === 'function') {
        env.onCardsReveal(ev);
      } else {
        const duels = ev.duels || [];
        duels.forEach((d, idx) => {
          for (const s of d.sides || []) {
            const rect = getRegularSlotRect(`${d.number}:${s.side}`);
            if (rect && s.cards?.length) {
              setTimeout(() => {
                if (!getState()) return;
                three.spawnCardFlipArc({
                  fromX: rect.cx, fromY: rect.cy + 14, toX: rect.cx, toY: rect.cy,
                  width: Math.min(118, rect.w), height: Math.min(158, rect.h),
                  title: s.cards[0].name || '', cost: s.cards[0].cost ?? '',
                  accentHex: resolveCharColorHex(s.cards[0].character_id, s.side),
                  flipFromBack: true, duration: 0.42, peakZ: 108,
                });
              }, idx * 80);
            }
          }
        });
      }
      showBanner('统一开牌', INK.gold, 1.25);
    },

    heal(ev) {
      audio.healChime();
      const pos = actorPos(ev.target_id, ev.target_side);
      getMotion(ev.target_id, ev.target_side).healGlow = 1.0;
      three.spawnImpactBurst(pos.x, pos.y, 0x269463, 14, false);
      spawnFloater(pos.x, pos.y - 36, `+${ev.amount}`, 0x269463, 19, 'clash');
    },

    lose_hp(ev) {
      audio.hitDamage(ev.amount >= 3);
      const pos = actorPos(ev.target_id, ev.target_side);
      getMotion(ev.target_id, ev.target_side).recoil = 0.7;
      getMotion(ev.target_id, ev.target_side).hitFlash = 0.8;
      if (ev.amount >= 3) three.emitShockwave(pos.x, pos.y, 0xc44569);
      spawnFloater(pos.x, pos.y - 34, `失去 ${ev.amount} 生命`, 0xc44569, 16, ev.amount >= 3 ? 'heavy' : 'clash');
    },

    breath_crit(ev) {
      audio.clashImpact(true);
      const pos = actorPos(ev.character_id, ev.side);
      three.emitShockwave(pos.x, pos.y, 0x1a8775);
      spawnFloater(pos.x, pos.y - 46, '✦ 暴击', 0x1a8775, 19, 'heavy');
      three.spawnImpactBurst(pos.x, pos.y, 0x24967c, 26, true);
    },

    stagger_check(ev) {
      const pos = actorPos(ev.target_id, ev.target_side);
      if (ev.triggered) {
        triggerShake(8, 0.3);
        three.emitShockwave(pos.x, pos.y, 0xd4223a);
      }
      spawnFloater(pos.x, pos.y - 42, ev.triggered ? '致命失衡' : '失衡 +2', ev.triggered ? 0xd4223a : 0xbf9119, 17, ev.triggered ? 'heavy' : 'status');
    },

    card_replace(ev) {
      audio.cardFlip();
      const { arenaX, arenaW, arenaTop, arenaH, handY } = getLayout();
      three.spawnCardFlipArc({
        fromX: arenaX + arenaW * 0.5, fromY: arenaTop + arenaH * 0.45,
        toX: arenaX + arenaW * 0.5, toY: handY,
        title: '', accentHex: SIDE_THEME[ev.side]?.accentHex || '#1a8775',
        flipFromBack: false, duration: 0.44, peakZ: 120,
      });
    },

    character_death(ev) {
      audio.clashImpact(true);
      triggerShake(11, 0.45);
      const pos = actorPos(ev.character_id, ev.side);
      three.emitShockwave(pos.x, pos.y, 0xcf4330);
      physics.spawnShieldShards(pos.x, pos.y, 0xcf4330, 18, true);
      three.spawnImpactBurst(pos.x, pos.y, 0xcf4330, 38, true);
      spawnFloater(pos.x, pos.y - 26, `${ev.name} 阵亡`, 0xcf4330, 18, 'heavy');
      showBanner(`${ev.name} 阵亡`, 0xcf4330, 1.8);
    },

    turn_recycle(ev) {
      audio.turnBell();
      const { arenaX, arenaW, arenaTop } = getLayout();
      for (const s of ev.sides || []) {
        const total = (s.used_count || 0) + (s.board_count || 0) + (s.discard_count || 0);
        const piles = getDeckPile(s.side);
        const dp = piles?.getPileAnchor('draw') || getPileCenter(`${s.side}:draw`);
        if (total > 0) {
          piles?.pulsePile('draw', 1.25);
          if (s.discard_count > 0) piles?.pulsePile('delayed_discard', 0.9);
        }
        if (dp && total > 0) {
          three.spawnCardFlipArc({
            fromX: arenaX + arenaW / 2,
            fromY: arenaTop + 210,
            toX: dp.x, toY: dp.y,
            width: 82, height: 112, title: '', accentHex: SIDE_THEME[s.side].accentHex,
            flipFromBack: false, duration: 0.48, peakZ: 88,
          });
        }
      }
    },
  };

  function playFx(ev, opts = {}) {
    if (!ev || !getState()) return;
    const handler = HANDLERS[ev.kind];
    if (handler) handler(ev, opts);
  }

  return {
    playFx,
    playSpeedRoll,
    playDiceRoll,
    playDiceClash,
    HANDLERS,
  };
}
