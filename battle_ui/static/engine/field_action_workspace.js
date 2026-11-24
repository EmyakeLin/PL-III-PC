/**
 * Field action ("场内行动") for 《光点计划 III》, played directly on the live table.
 *  - `analyzeFieldActions` groups the flat `special_options` by hand card, ability, board target and response.
 *  - `resolveFieldHighlights` says which table objects glow for the current selection.
 *  - `buildFieldActionLayer` hangs ability sigils over their owners and an arc of action seals over the
 *    selected card; `fieldDockActions` turns pass / decline / leave into command-dock buttons.
 */

import * as PIXI from '../vendor/pixi.min.mjs';
import { FONT_UI, INK } from './design_system.js';

const ACTION_COLOR = {
  place: 0x1a825e,
  place_rear: 0x9c6e18,
  attack: 0xc8452e,
  replace: 0x1b6ea8,
  custom: 0xb67b14,
  intercept: 0xc26e1d,
  pass_intercept: 0x6b6458,
  ability: 0x7b42b8,
  decline: 0x6b6458,
};

/**
 * Pure, PIXI-free analyzer grouping flat `special_options` into direct spatial tabletop intents.
 */
export function analyzeFieldActions(options = []) {
  const byCardId = new Map();         // handKey -> Array<{ idx, opt, kind }>
  const selfAbilities = [];           // Array<{ idx, opt, characterId, abilityId }>
  const handAbilities = new Map();    // abilityKey -> { key, characterId, abilityId, label, options: [...] }
  const boardAbilities = new Map();   // abilityKey -> { key, characterId, abilityId, label, options: [...] }
  const pendingResponses = new Map(); // responseNumber -> { responseNumber, passIdx, interceptOptions: [...] }
  const declineOptions = [];
  const otherOptions = [];

  const pushCard = (cardId, entry) => {
    if (!cardId) return;
    if (!byCardId.has(cardId)) byCardId.set(cardId, []);
    byCardId.get(cardId).push(entry);
  };

  options.forEach((opt, idx) => {
    const kind = opt.kind;
    if (kind === 'place' || kind === 'place_rear' || kind === 'attack' || kind === 'replace' || kind === 'custom' || kind === 'intercept') {
      pushCard(opt.card_id, { idx, opt, kind });
      if (kind === 'intercept' && opt.response_number != null) {
        const num = opt.response_number;
        if (!pendingResponses.has(num)) pendingResponses.set(num, { responseNumber: num, passIdx: null, interceptOptions: [] });
        pendingResponses.get(num).interceptOptions.push({ idx, opt });
      }
      return;
    }
    if (kind === 'pass_intercept') {
      const num = opt.response_number ?? 1;
      if (!pendingResponses.has(num)) pendingResponses.set(num, { responseNumber: num, passIdx: null, interceptOptions: [] });
      pendingResponses.get(num).passIdx = idx;
      return;
    }
    if (kind === 'ability') {
      const aKey = `${opt.character_id || ''}:${opt.ability_id || opt.label}`;
      const baseLabel = String(opt.label || '主动能力').split(' · ').slice(0, 2).join(' · ');
      if (opt.effect_target?.zone === 'board') {
        if (!boardAbilities.has(aKey)) {
          boardAbilities.set(aKey, { key: aKey, characterId: opt.character_id, abilityId: opt.ability_id, label: baseLabel, options: [] });
        }
        boardAbilities.get(aKey).options.push({ idx, opt, target: opt.effect_target });
      } else if (opt.target_card_id) {
        if (!handAbilities.has(aKey)) {
          handAbilities.set(aKey, { key: aKey, characterId: opt.character_id, abilityId: opt.ability_id, label: baseLabel, options: [] });
        }
        handAbilities.get(aKey).options.push({ idx, opt, targetCardId: opt.target_card_id });
        pushCard(opt.target_card_id, { idx, opt, kind: 'ability', abilityKey: aKey, abilityLabel: baseLabel });
      } else {
        selfAbilities.push({ idx, opt, characterId: opt.character_id, abilityId: opt.ability_id, label: baseLabel });
      }
      return;
    }
    if (kind === 'decline') {
      declineOptions.push({ idx, opt });
      return;
    }
    otherOptions.push({ idx, opt });
  });

  return {
    total: options.length,
    byCardId,
    selfAbilities,
    handAbilities,
    boardAbilities,
    pendingResponses: Array.from(pendingResponses.values()),
    declineOptions,
    otherOptions,
  };
}

/**
 * Given the currently selected hand card or active ability key, computes which live tabletop
 * entities should glow & accept clicks directly on the battlefield.
 */
export function resolveFieldHighlights(analysis, { selectedCardId = null, activeAbilityKey = null } = {}) {
  const handCardKeys = new Set();
  const enemyCharTargets = new Map();  // charId -> optionIndex
  const regularDuelTargets = new Map(); // duelNumber -> optionIndex
  const rearDuelTargets = new Map();   // duelNumber -> optionIndex
  const boardCardTargets = new Map();  // `${kind}:${number}:${side}:${lane}:${position}` -> optionIndex
  const instantDuelTargets = new Map();// responseNumber -> optionIndex

  // 1. If a board-targeted or hand-targeted ability is armed
  if (activeAbilityKey && analysis.boardAbilities.has(activeAbilityKey)) {
    const ab = analysis.boardAbilities.get(activeAbilityKey);
    for (const entry of ab.options) {
      const t = entry.target;
      if (t?.zone === 'board') {
        boardCardTargets.set(`${t.kind}:${t.number}:${t.side}:${t.lane || 'front'}:${t.position}`, entry.idx);
      }
    }
    return { handCardKeys, enemyCharTargets, regularDuelTargets, rearDuelTargets, boardCardTargets, instantDuelTargets };
  }
  if (activeAbilityKey && analysis.handAbilities.has(activeAbilityKey)) {
    const ab = analysis.handAbilities.get(activeAbilityKey);
    for (const entry of ab.options) {
      if (entry.targetCardId) handCardKeys.add(entry.targetCardId);
    }
    return { handCardKeys, enemyCharTargets, regularDuelTargets, rearDuelTargets, boardCardTargets, instantDuelTargets };
  }

  // 2. All actionable hand cards glow when nothing specific is armed
  for (const cardId of analysis.byCardId.keys()) {
    handCardKeys.add(cardId);
  }

  // 3. If a hand card is selected, light up all of its direct spatial targets on the battlefield!
  if (selectedCardId && analysis.byCardId.has(selectedCardId)) {
    const entries = analysis.byCardId.get(selectedCardId);
    for (const entry of entries) {
      const { idx, opt, kind } = entry;
      if (kind === 'attack') {
        if (opt.character_id) enemyCharTargets.set(opt.character_id, idx);
        else if (opt.duel_number != null) regularDuelTargets.set(opt.duel_number, idx);
      } else if (kind === 'place_rear' && opt.duel_number != null) {
        rearDuelTargets.set(opt.duel_number, idx);
      } else if (kind === 'replace' && opt.effect_target?.zone === 'board') {
        const t = opt.effect_target;
        boardCardTargets.set(`${t.kind}:${t.number}:${t.side}:${t.lane || 'front'}:${t.position}`, idx);
      } else if (kind === 'intercept' && opt.response_number != null) {
        instantDuelTargets.set(opt.response_number, idx);
      }
    }
  }

  return { handCardKeys, enemyCharTargets, regularDuelTargets, rearDuelTargets, boardCardTargets, instantDuelTargets };
}

const GLYPH_TIPS = {
  place: '置入常规交锋',
  place_rear: '置入后置交锋',
  custom: '按牌面打出',
  ability: '以此牌发动能力',
  intercept: '迎击即时进攻',
  attack: '进攻',
  replace: '替换场上牌',
};

/** Small hand-drawn glyphs for the round action seals. Drawn around (0,0) within radius r. */
function drawActionGlyph(g, kind, r, color) {
  const s = r * 0.5;
  const line = { width: Math.max(1.6, r * 0.13), color, cap: 'round', join: 'round' };
  if (kind === 'place') {
    g.moveTo(0, -s).lineTo(0, s * 0.35).stroke(line);
    g.moveTo(-s * 0.5, -s * 0.1).lineTo(0, s * 0.4).lineTo(s * 0.5, -s * 0.1).stroke(line);
    g.moveTo(-s, s * 0.85).lineTo(s, s * 0.85).stroke(line);
  } else if (kind === 'place_rear') {
    g.moveTo(-s * 0.72, -s * 0.85).lineTo(-s * 0.72, s * 0.85).stroke(line);
    g.moveTo(s * 0.85, 0).lineTo(-s * 0.25, 0).stroke(line);
    g.moveTo(s * 0.22, -s * 0.52).lineTo(-s * 0.28, 0).lineTo(s * 0.22, s * 0.52).stroke(line);
  } else if (kind === 'custom') {
    g.poly([0, -s, s * 0.28, -s * 0.28, s, 0, s * 0.28, s * 0.28, 0, s, -s * 0.28, s * 0.28, -s, 0, -s * 0.28, -s * 0.28])
      .fill({ color });
  } else if (kind === 'ability') {
    g.poly([0, -s, s * 0.8, 0, 0, s, -s * 0.8, 0]).stroke(line);
    g.circle(0, 0, s * 0.28).fill({ color });
  } else if (kind === 'intercept') {
    g.poly([0, -s, s * 0.85, -s * 0.6, s * 0.7, s * 0.35, 0, s, -s * 0.7, s * 0.35, -s * 0.85, -s * 0.6]).stroke(line);
  } else if (kind === 'attack') {
    g.moveTo(-s, -s).lineTo(s, s).moveTo(s, -s).lineTo(-s, s).stroke(line);
    g.moveTo(-s * 0.95, s * 0.35).lineTo(-s * 0.35, s * 0.95).moveTo(s * 0.95, s * 0.35).lineTo(s * 0.35, s * 0.95).stroke(line);
  } else if (kind === 'replace') {
    g.moveTo(-s, -s * 0.35).lineTo(s, -s * 0.35).stroke(line);
    g.moveTo(s * 0.5, -s * 0.8).lineTo(s, -s * 0.35).lineTo(s * 0.5, s * 0.1).stroke(line);
    g.moveTo(s, s * 0.45).lineTo(-s, s * 0.45).stroke(line);
    g.moveTo(-s * 0.5, 0).lineTo(-s, s * 0.45).lineTo(-s * 0.5, s * 0.9).stroke(line);
  }
}

/** Hover tooltip: a small ink plate that appears beside a seal; nothing is shown until hovered. */
function attachTip(node, text, tipLayer, { above = true } = {}) {
  let tip = null;
  node.on('pointerover', () => {
    if (tip || !text) return;
    tip = new PIXI.Container();
    const t = new PIXI.Text({
      text,
      style: { fontFamily: FONT_UI, fontSize: 12, fontWeight: '800', fill: INK.paper },
    });
    const pw = Math.ceil(t.width) + 16;
    const ph = 22;
    const bg = new PIXI.Graphics();
    bg.poly([-pw / 2, -ph / 2, pw / 2, -ph / 2, pw / 2, ph / 2, 5, ph / 2, 0, ph / 2 + 5, -5, ph / 2, -pw / 2, ph / 2])
      .fill({ color: 0x2c241d, alpha: 0.92 });
    if (!above) bg.scale.y = -1;
    t.anchor.set(0.5);
    tip.addChild(bg, t);
    const g = node.getGlobalPosition();
    const r = node._radius || 16;
    tip.position.set(g.x, above ? g.y - r - 18 : g.y + r + 18);
    tipLayer.addChild(tip);
  });
  const clear = () => {
    if (tip) {
      tip.destroy({ children: true });
      tip = null;
    }
  };
  node.on('pointerout', clear);
  node.on('destroyed', clear);
}

/** A round brass-rimmed seal with a glyph. */
function makeSeal(kind, { radius = 17, accent, armed = false, onClick }) {
  const c = new PIXI.Container();
  const g = new PIXI.Graphics();
  const draw = (hov) => {
    g.clear();
    g.circle(1, 3, radius).fill({ color: INK.shadow, alpha: 0.35 });
    if (armed) g.circle(0, 0, radius + 6).fill({ color: accent, alpha: 0.22 });
    g.circle(0, 0, radius).fill({ color: hov || armed ? accent : INK.paper })
      .stroke({ width: 2, color: accent });
    g.circle(0, 0, radius - 3.5).stroke({ width: 0.9, color: hov || armed ? INK.paper : accent, alpha: 0.45 });
    drawActionGlyph(g, kind, radius, hov || armed ? INK.paper : accent);
  };
  draw(false);
  c.addChild(g);
  c.eventMode = 'static';
  c.cursor = 'pointer';
  c.hitArea = new PIXI.Circle(0, 0, radius + 2);
  c.on('pointerover', () => draw(true));
  c.on('pointerout', () => draw(false));
  c.on('pointertap', (e) => {
    e.stopPropagation();
    onClick?.();
  });
  c._radius = radius;
  return c;
}

/**
 * Field action (“场内行动”) on the live table — no bars, no lists:
 *  - Each character's active abilities hang as sigils above that character on the battlefield.
 *  - A selected hand card opens an arc of round seals above it, one per thing it can do right now.
 *    Attack / replace / intercept targets also glow on the battlefield and can be clicked or dropped on.
 * Pass / decline / leave live in the command dock as regular seal buttons (see `fieldDockActions`).
 */
export function buildFieldActionLayer({
  analysis,
  selectedCardId = null,
  selectedCardAnchor = null, // { x, y } top-centre of the lifted card
  activeAbilityKey = null,
  characterAnchor,           // (characterId) => { x, y } top-centre above the actor, or null
  onPickOption,
  onArmAbility,
}) {
  const root = new PIXI.Container();
  const sealLayer = new PIXI.Container();
  const tipLayer = new PIXI.Container();
  root.addChild(sealLayer, tipLayer);

  // 1. Ability sigils above their owners
  const byChar = new Map();
  const pushAbility = (characterId, entry) => {
    const k = characterId || '';
    if (!byChar.has(k)) byChar.set(k, []);
    byChar.get(k).push(entry);
  };
  for (const ab of analysis.selfAbilities) {
    pushAbility(ab.characterId, { label: ab.label, armed: false, onClick: () => onPickOption(ab.idx) });
  }
  for (const ab of [...analysis.boardAbilities.values(), ...analysis.handAbilities.values()]) {
    const armed = activeAbilityKey === ab.key;
    pushAbility(ab.characterId, { label: ab.label, armed, onClick: () => onArmAbility(armed ? null : ab.key) });
  }
  let fallbackX = 0;
  for (const [charId, list] of byChar) {
    const anchor = characterAnchor?.(charId) || null;
    const r = 15;
    const gap = 8;
    const total = list.length * r * 2 + (list.length - 1) * gap;
    const baseX = anchor ? anchor.x - total / 2 + r : 80 + (fallbackX += total + 20);
    const y = anchor ? anchor.y - r - 6 : 120;
    list.forEach((entry, i) => {
      const seal = makeSeal('ability', { radius: r, accent: ACTION_COLOR.ability, armed: entry.armed, onClick: entry.onClick });
      seal.position.set(baseX + i * (r * 2 + gap), y);
      attachTip(seal, entry.label, tipLayer);
      sealLayer.addChild(seal);
    });
  }

  // 2. Arc of seals above the selected card
  if (selectedCardId && selectedCardAnchor && analysis.byCardId.has(selectedCardId)) {
    const entries = analysis.byCardId.get(selectedCardId);
    const seals = [];
    for (const entry of entries) {
      const o = entry.opt;
      if (entry.kind === 'place') {
        seals.push({ kind: 'place', tip: `${GLYPH_TIPS.place}${o.duel_number != null ? ` ${o.duel_number}` : ''}`, idx: entry.idx });
      } else if (entry.kind === 'place_rear') {
        seals.push({ kind: 'place_rear', tip: `${GLYPH_TIPS.place_rear}${o.duel_number != null ? ` ${o.duel_number}` : ''}`, idx: entry.idx });
      } else if (entry.kind === 'custom') {
        seals.push({ kind: 'custom', tip: o.label || GLYPH_TIPS.custom, idx: entry.idx });
      } else if (entry.kind === 'ability') {
        seals.push({ kind: 'ability', tip: entry.abilityLabel || GLYPH_TIPS.ability, idx: entry.idx });
      } else if (entry.kind === 'intercept') {
        seals.push({ kind: 'intercept', tip: o.label || GLYPH_TIPS.intercept, idx: entry.idx });
      }
    }
    // A lone attack / replace target gets a seal too; several targets are picked on the battlefield itself.
    const attacks = entries.filter((e) => e.kind === 'attack');
    if (attacks.length === 1) seals.push({ kind: 'attack', tip: attacks[0].opt.label || GLYPH_TIPS.attack, idx: attacks[0].idx });
    const replaces = entries.filter((e) => e.kind === 'replace');
    if (replaces.length === 1) seals.push({ kind: 'replace', tip: replaces[0].opt.label || GLYPH_TIPS.replace, idx: replaces[0].idx });

    const r = 19;
    const n = seals.length;
    const spreadAngle = Math.min(Math.PI * 0.75, 0.42 * Math.max(0, n - 1));
    const arcR = 64 + Math.max(0, n - 3) * 10;
    const cx = selectedCardAnchor.x;
    const cy = selectedCardAnchor.y + arcR - 18;
    seals.forEach((s, i) => {
      const a = -Math.PI / 2 + (n > 1 ? -spreadAngle / 2 + (spreadAngle * i) / (n - 1) : 0);
      const seal = makeSeal(s.kind, { radius: r, accent: ACTION_COLOR[s.kind] || INK.gold, onClick: () => onPickOption(s.idx) });
      seal.position.set(cx + Math.cos(a) * arcR, cy + Math.sin(a) * arcR);
      attachTip(seal, s.tip, tipLayer);
      sealLayer.addChild(seal);
    });
  }

  return root;
}

/**
 * Non-spatial field choices (pass on an instant attack, decline, other one-off options) become
 * ordinary command-dock seal buttons, bottom-to-top.
 */
export function fieldDockActions(analysis, { pendingAttack = false, canSwitchSide = false, onPickOption, onSwitchSide, onLeave }) {
  const short = (s) => (s.length > 10 ? s.slice(0, 9) + '…' : s);
  const buttons = [];
  if (!pendingAttack) buttons.push({ label: '返回战场', h: 40, accent: 0x177d6b, solid: true, fn: onLeave });
  for (const resp of analysis.pendingResponses) {
    if (resp.passIdx != null) {
      buttons.push({ label: `放行即时 ${resp.responseNumber}`, h: 36, accent: ACTION_COLOR.pass_intercept, solid: false, fn: () => onPickOption(resp.passIdx) });
    }
  }
  for (const dec of analysis.declineOptions) {
    buttons.push({ label: short(dec.opt.label || '让过'), h: 36, accent: ACTION_COLOR.decline, solid: false, fn: () => onPickOption(dec.idx) });
  }
  for (const oth of analysis.otherOptions) {
    buttons.push({ label: short(oth.opt.label || '执行'), h: 36, accent: INK.gold, solid: false, fn: () => onPickOption(oth.idx) });
  }
  if (canSwitchSide) buttons.push({ label: '切换席位', h: 34, accent: 0x177d6b, solid: false, fn: onSwitchSide });
  return buttons;
}
