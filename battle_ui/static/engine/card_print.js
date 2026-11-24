/**
 * Pure PixiJS v8 Editorial Card Renderer powered by `design_system.js`.
 *
 * ZERO nested-border clutter, ZERO crude geometric placeholder art boxes, ZERO hover-gated blind text!
 * Every card directly displays 100% verbatim rules on clean sunlit paper with architectural hairlines
 * and surgical semantic color anchors.
 */

import * as PIXI from '../vendor/pixi.min.mjs';
import {
  FONT_UI,
  FONT_NUM,
  INK,
  SIDE_THEME,
  HP_BAR_COLOR,
  DIE_STYLE,
  DAMAGE_GRADE_STYLE,
  SHIELD_STYLE,
  STATUS_COLORS,
  TRAIT_STYLE,
  TRIGGER_STYLE,
  RANK_COLOR,
  LEVEL_MAX,
  RANK_LABEL,
  RANGE_LABELS,
  OFFICIAL_STATUS_RULES,
  parseHexColor,
  hexToCss,
  mixHexColors,
  deriveCardPalette,
  wrapCjkText,
  formatDieRange,
  exactSkillTraits,
  exactSkillTraitSpecs,
  classifyTriggerSeries,
  parseTriggerSegments,
  formatDamagePart,
  resolveDieDamageParts,
  drawDieIcon,
  dieOutcomeColor,
  drawUnifiedDieFrame,
  drawStatusIcon,
  mountStatusIcon,
  setStatusVisuals,
  getStatusColor,
  drawShieldGlyph,
  drawLightStar,
  drawCostCrystal,
  buildRichVerbatimText,
  buildTraitPills,
  buildDamageBadge,
  buildUnifiedDieRow,
  buildUnifiedEntryPlate,
  buildUnifiedSkillRow,
} from './design_system.js';

export {
  FONT_UI,
  FONT_NUM,
  INK,
  SIDE_THEME,
  HP_BAR_COLOR,
  DIE_STYLE,
  DAMAGE_GRADE_STYLE,
  SHIELD_STYLE,
  STATUS_COLORS,
  TRAIT_STYLE,
  TRIGGER_STYLE,
  RANK_COLOR,
  LEVEL_MAX,
  RANK_LABEL,
  RANGE_LABELS,
  OFFICIAL_STATUS_RULES,
  parseHexColor,
  hexToCss,
  mixHexColors,
  deriveCardPalette,
  wrapCjkText,
  formatDieRange,
  exactSkillTraits,
  exactSkillTraitSpecs,
  classifyTriggerSeries,
  parseTriggerSegments,
  formatDamagePart,
  resolveDieDamageParts,
  drawDieIcon,
  drawUnifiedDieFrame,
  drawStatusIcon,
  mountStatusIcon,
  setStatusVisuals,
  getStatusColor,
  drawShieldGlyph,
  drawLightStar,
  drawCostCrystal,
  buildRichVerbatimText,
  buildTraitPills,
  buildDamageBadge,
  buildUnifiedDieRow,
  buildUnifiedEntryPlate,
  buildUnifiedSkillRow,
};

/**
 * Clean Physical Card Back colored in the owning character's signature color,
 * supporting character-configurable heraldry patterns (`card_back` in character JSON):
 *   - string preset: 'star' (default) | 'diamond' | 'rings' | 'lattice' | 'crescent' | 'crest' | 'wave' | 'portal'
 *   - object config: { pattern?: string, color?: number|string, image_url?: string }
 */
function drawCardBackPattern(g, patternName, hw, hh, pal) {
  const r = Math.min(hw * 2, hh * 2) * 0.22;
  const col = pal.accent;
  const soft = pal.border;

  // Corner filigree ticks shared across all patterns
  const ci = 9;
  for (const [sx, sy] of [[-1, -1], [1, -1], [1, 1], [-1, 1]]) {
    const cx = sx * (hw - ci);
    const cy = sy * (hh - ci);
    g.moveTo(cx, cy - sy * 6).lineTo(cx, cy).lineTo(cx - sx * 6, cy)
      .stroke({ width: 1.15, color: col, alpha: 0.55 });
  }

  switch (patternName) {
    case 'diamond': {
      g.poly([0, -hh + 12, hw - 12, 0, 0, hh - 12, -hw + 12, 0])
        .stroke({ width: 1.35, color: col, alpha: 0.62 });
      g.poly([0, -r * 1.35, r * 0.95, 0, 0, r * 1.35, -r * 0.95, 0])
        .fill({ color: col, alpha: 0.18 })
        .stroke({ width: 1.4, color: col, alpha: 0.9 });
      g.poly([0, -r * 0.55, r * 0.42, 0, 0, r * 0.55, -r * 0.42, 0])
        .fill({ color: col, alpha: 0.88 });
      break;
    }
    case 'rings': {
      g.circle(0, 0, r * 1.42).stroke({ width: 1.1, color: soft, alpha: 0.65 });
      g.circle(0, 0, r * 1.05).stroke({ width: 1.5, color: col, alpha: 0.88 });
      g.circle(0, 0, r * 0.58).fill({ color: col, alpha: 0.16 }).stroke({ width: 1.2, color: col, alpha: 0.82 });
      drawLightStar(g, 0, 0, r * 0.48, col, 0.92);
      break;
    }
    case 'lattice': {
      const step = Math.max(12, Math.round(r * 0.72));
      for (let d = -hh + 14; d <= hh - 14; d += step) {
        g.moveTo(-hw + 10, d).lineTo(hw - 10, d).stroke({ width: 0.75, color: soft, alpha: 0.32 });
      }
      g.poly([0, -r * 1.2, r * 0.95, 0, 0, r * 1.2, -r * 0.95, 0])
        .fill({ color: INK.paper, alpha: 0.85 })
        .stroke({ width: 1.4, color: col, alpha: 0.9 });
      drawLightStar(g, 0, 0, r * 0.62, col, 0.92);
      break;
    }
    case 'crescent': {
      g.circle(0, 0, r * 1.22).stroke({ width: 1.0, color: soft, alpha: 0.55 });
      g.circle(-r * 0.12, 0, r * 0.86).fill({ color: col, alpha: 0.88 });
      g.circle(r * 0.24, -r * 0.08, r * 0.72).fill({ color: pal.softBg, alpha: 1.0 });
      drawLightStar(g, r * 0.42, -r * 0.14, r * 0.34, col, 0.95);
      break;
    }
    case 'crest': {
      const sw = r * 1.05;
      const sh = r * 1.28;
      g.poly([0, -sh, sw, -sh * 0.62, sw * 0.86, sh * 0.28, 0, sh, -sw * 0.86, sh * 0.28, -sw, -sh * 0.62])
        .fill({ color: col, alpha: 0.18 })
        .stroke({ width: 1.6, color: col, alpha: 0.92 });
      g.moveTo(0, -sh * 0.78).lineTo(0, sh * 0.78).stroke({ width: 1.2, color: col, alpha: 0.72 });
      g.moveTo(-sw * 0.72, -sh * 0.12).lineTo(sw * 0.72, -sh * 0.12).stroke({ width: 1.2, color: col, alpha: 0.72 });
      break;
    }
    case 'wave': {
      for (let k = -2; k <= 2; k++) {
        const wy = k * (r * 0.52);
        g.moveTo(-hw + 12, wy)
          .bezierCurveTo(-hw * 0.3, wy - 9, hw * 0.3, wy + 9, hw - 12, wy)
          .stroke({ width: k === 0 ? 1.8 : 1.05, color: col, alpha: k === 0 ? 0.9 : 0.45 });
      }
      g.circle(0, 0, r * 0.44).fill({ color: col, alpha: 0.9 });
      break;
    }
    case 'portal': {
      g.ellipse(0, 0, r * 0.78, r * 1.42).stroke({ width: 1.5, color: col, alpha: 0.88 });
      g.ellipse(0, 0, r * 0.46, r * 1.02).fill({ color: col, alpha: 0.2 }).stroke({ width: 1.2, color: col, alpha: 0.78 });
      g.moveTo(0, -r * 1.65).lineTo(0, r * 1.65).stroke({ width: 1.2, color: col, alpha: 0.7 });
      drawLightStar(g, 0, 0, r * 0.42, col, 0.95);
      break;
    }
    case 'star':
    default: {
      g.poly([0, -hh + 13, hw - 13, 0, 0, hh - 13, -hw + 13, 0])
        .stroke({ width: 1.0, color: col, alpha: 0.42 });
      drawLightStar(g, 0, 0, Math.min(hw * 2, hh * 2) * 0.21, col, 0.92);
      break;
    }
  }
}

export function buildCardBack(side = 1, { width = 82, height = 104, accentColor = null, pattern = null } = {}) {
  const cfg = pattern && typeof pattern === 'object' ? pattern : null;
  const patternName = typeof pattern === 'string' ? pattern : (cfg?.pattern || 'star');
  const effectiveColor = cfg?.color ?? accentColor;
  const pal = deriveCardPalette(effectiveColor, side);
  const root = new PIXI.Container();
  const hw = width / 2;
  const hh = height / 2;

  const g = new PIXI.Graphics();
  // Soft layered shadow + 2.5px physical paper-stack bottom edge
  g.roundRect(-hw + 2, -hh + 6, width, height, 7).fill({ color: INK.shadow, alpha: 0.22 });
  g.roundRect(-hw, -hh + 2.5, width, height, 7).fill({ color: 0xe3dac9 });
  g.roundRect(-hw, -hh, width, height, 7)
    .fill({ color: INK.paper })
    .stroke({ width: 1.65, color: pal.accent, alpha: 0.94 });
  g.roundRect(-hw + 5, -hh + 5, width - 10, height - 10, 4)
    .fill({ color: pal.softBg })
    .stroke({ width: 0.95, color: pal.border, alpha: 0.78 });
  drawCardBackPattern(g, patternName, hw, hh, pal);
  root.addChild(g);

  if (cfg?.image_url) {
    const tex = PIXI.Texture.from(cfg.image_url);
    const sp = new PIXI.Sprite(tex);
    sp.anchor.set(0.5);
    sp.width = width - 12;
    sp.height = height - 12;
    const mask = new PIXI.Graphics().roundRect(-hw + 6, -hh + 6, width - 12, height - 12, 4).fill(0xffffff);
    sp.mask = mask;
    root.addChild(mask, sp);
  }

  root._boxWidth = width;
  root._boxHeight = height;
  return root;
}

function dieShowsBlank(die, live, deficit) {
  if (live && (live.type === 'blank' || live.result != null || live.rolled_value != null)) {
    return live.type === 'blank';
  }
  return deficit >= 3 && (die.ignore_range ?? 0) < 3;
}

/**
 * Razor-sharp 1:1 Strictly VERTICAL Portrait Board Mini-Card (W : H = 1 : 1.40, NEVER horizontal!):
 * Shares the exact vertical anatomy & physical card-stock craft of buildFullCard:
 *  - Physical paper-stack bottom bevel + top 3px accent bar + faceted cost crystal + bold name
 *  - Vertically stacked 1:1 crisp die rows (left accent stripe + framed icon + exact range + compact damage + ◆)
 *  - Hovering lifts seamlessly into the full 1:1 vertical buildFullCard!
 */
export function buildBoardCardTag(card, {
  side = 1,
  accentColor = null,
  ownerName = '',
  showOwner = false,
  width = 114,
  height = null,
  playMode = null,
  rangeDeficit = 0,
  activeDieNumber = null,
} = {}) {
  const pal = deriveCardPalette(accentColor, side);
  const W = Math.max(96, Math.round(width));
  const H = height ? Math.max(Math.round(W * 1.34), Math.round(height)) : Math.round(W * 1.40);
  const isBlanked = rangeDeficit >= 3;
  const padX = 6;
  const headerH = 26;

  const root = new PIXI.Container();
  const sheet = new PIXI.Container();

  const bg = new PIXI.Graphics();
  // Physical card-stock shadow + 2.5px warm edge bevel + character-colored rim & header tint!
  bg.roundRect(2, 5, W, H, 7).fill({ color: INK.shadow, alpha: 0.22 });
  bg.roundRect(0, 2.5, W, H, 7).fill({ color: 0xe3dac9 });
  bg.roundRect(0, 0, W, H, 7)
    .fill({ color: isBlanked ? 0xf3efe8 : INK.paper })
    .stroke({ width: 1.45, color: isBlanked ? INK.muted : pal.accent, alpha: isBlanked ? 0.8 : 0.88 });
  if (!isBlanked) {
    bg.roundRect(1, 1, W - 2, headerH - 1, 6).fill({ color: pal.softBg, alpha: 0.72 });
  }
  bg.roundRect(1, 1, W - 2, 3.4, 2).fill({ color: isBlanked ? INK.muted : pal.accent });
  bg.moveTo(padX, headerH).lineTo(W - padX, headerH).stroke({ width: 0.85, color: pal.border, alpha: 0.55 });
  drawCostCrystal(bg, padX + 9, 3 + (headerH - 3) / 2, 8.2, isBlanked ? INK.muted : pal.accent);
  sheet.addChild(bg);

  const cTxt = new PIXI.Text({
    text: String(card.cost ?? 0),
    style: { fontFamily: FONT_NUM, fontSize: 10.5, fontWeight: '900', fill: INK.paper },
  });
  cTxt.anchor.set(0.5);
  cTxt.position.set(padX + 9, 3 + (headerH - 3) / 2 + 0.5);
  sheet.addChild(cTxt);

  const nameSize = (card.name || '').length > 4 ? 10 : 11;
  const nameTxt = new PIXI.Text({
    text: card.name || '',
    style: { fontFamily: FONT_UI, fontSize: nameSize, fontWeight: '800', fill: isBlanked ? INK.muted : INK.strong },
  });
  nameTxt.anchor.set(0, 0.5);
  nameTxt.position.set(padX + 20, 3 + (headerH - 3) / 2);
  sheet.addChild(nameTxt);

  let cursorY = headerH + 3;

  // Optional tiny subline (owner / play mode / range suppression)
  const subBits = [];
  if (rangeDeficit > 0) subBits.push(`压制-${rangeDeficit}`);
  else if (playMode) subBits.push(playMode === 'pulled' ? '被牵制' : playMode === 'passive' ? '迎击' : '主动');
  if (showOwner && ownerName) subBits.push(ownerName);
  if (subBits.length) {
    const subT = new PIXI.Text({
      text: subBits.join(' · '),
      style: { fontFamily: FONT_UI, fontSize: 8.5, fontWeight: '700', fill: rangeDeficit > 0 ? 0xc93e2b : pal.accent },
    });
    subT.position.set(padX, cursorY);
    sheet.addChild(subT);
    cursorY += 12;
  }

  // Strictly vertical dice stack (1 die per row, matching buildFullCard's vertical anatomy!)
  const dice = card.dice || [];
  const traits = exactSkillTraits(card, isBlanked);
  const hasFooter = traits.length > 0 || (!isBlanked && card.entries?.length > 0);
  const footerH = hasFooter ? 16 : 12;
  const maxRows = Math.min(dice.length, 5);
  const availH = Math.max(20, H - footerH - cursorY - 2);
  const rowH = maxRows > 0 ? Math.max(16, Math.min(24, Math.floor(availH / maxRows))) : 20;

  const rowG = new PIXI.Graphics();
  sheet.addChild(rowG);

  for (let i = 0; i < maxRows; i++) {
    const die = dice[i];
    const ry = cursorY + i * rowH;
    const live = card.live_dice?.findLast(d => d?.position === i + 1);
    const blankDie = dieShowsBlank(die, live, rangeDeficit);
    const dType = blankDie ? 'blank' : die.type;
    const ds = DIE_STYLE[dType] || DIE_STYLE.blank;
    const dmgParts = blankDie ? [] : resolveDieDamageParts(die);
    const badge = dmgParts[0] || null;
    const restEntries = blankDie ? (die.no_hit_carrier ? ['无受击载体'] : []) : (die.entries || []).filter(Boolean);

    if (activeDieNumber === i + 1) {
      rowG.roundRect(padX - 2, ry + 1, W - padX * 2 + 4, rowH - 2, 3).fill({ color: INK.goldBg, alpha: 0.95 })
        .stroke({ width: 1.1, color: INK.gold, alpha: 0.9 });
    }
    rowG.roundRect(padX, ry + 2, 2.4, rowH - 4, 1).fill({ color: ds.color, alpha: 0.9 });
    if (i < maxRows - 1) {
      rowG.moveTo(padX + 4, ry + rowH).lineTo(W - padX, ry + rowH).stroke({ width: 0.75, color: INK.hairline });
    }
    drawUnifiedDieFrame(rowG, dType, padX + 11, ry + rowH / 2, Math.min(4.6, rowH * 0.24),
      { result: live?.result, destroyed: live?.destroyed });

    const rngTxt = new PIXI.Text({
      text: formatDieRange(die),
      style: { fontFamily: FONT_NUM, fontSize: W < 108 ? 9.8 : 10.6, fontWeight: '900', fill: dieOutcomeColor(live?.result, ds.color) },
    });
    rngTxt.anchor.set(0, 0.5);
    rngTxt.position.set(padX + 20, ry + rowH / 2);
    sheet.addChild(rngTxt);

    let rx = W - padX;
    if (restEntries.length > 0) {
      rowG.poly([rx - 2.6, ry + rowH / 2 - 2.6, rx, ry + rowH / 2, rx - 2.6, ry + rowH / 2 + 2.6, rx - 5.2, ry + rowH / 2])
        .fill({ color: ds.color, alpha: 0.85 });
      rx -= 7;
    }
    if (badge && rx - (padX + 22 + rngTxt.width) >= 24) {
      const dmgT = new PIXI.Text({
        text: badge.text,
        style: { fontFamily: FONT_UI, fontSize: 8.4, fontWeight: '800', fill: badge.style.color },
      });
      const maxDmgW = Math.max(20, rx - (padX + 22 + rngTxt.width) - 2);
      if (dmgT.width > maxDmgW) dmgT.scale.set(maxDmgW / dmgT.width);
      dmgT.anchor.set(1, 0.5);
      dmgT.position.set(rx, ry + rowH / 2);
      sheet.addChild(dmgT);
    }
  }

  // Footer: trait / entry count or subtle physical pressmark
  const fy = H - 10;
  if (hasFooter) {
    const fBits = [];
    if (traits.length) fBits.push(traits[0].length > 6 ? traits[0].slice(0, 4) : traits[0]);
    if (!isBlanked && card.entries?.length) fBits.push(`◆${card.entries.length}条`);
    const ft = new PIXI.Text({
      text: fBits.join(' · '),
      style: { fontFamily: FONT_UI, fontSize: 8.6, fontWeight: '700', fill: INK.secondary },
    });
    ft.anchor.set(0.5);
    ft.position.set(W / 2, fy);
    sheet.addChild(ft);
  } else {
    const mid = W / 2;
    rowG.moveTo(padX + 10, fy).lineTo(mid - 7, fy).stroke({ width: 0.75, color: INK.hairline });
    rowG.moveTo(mid + 7, fy).lineTo(W - padX - 10, fy).stroke({ width: 0.75, color: INK.hairline });
    rowG.poly([mid, fy - 2.4, mid + 2.6, fy, mid, fy + 2.4, mid - 2.6, fy])
      .stroke({ width: 0.8, color: pal.accent, alpha: 0.72 });
  }

  sheet.position.set(-W / 2, -H / 2);
  root.addChild(sheet);
  root._boxWidth = W;
  root._boxHeight = H;
  return root;
}

/**
 * THE ONE CANONICAL READABLE CARD — used directly across Hand, Public Board, Draw-Select,
 * Pile, Roster Showcase, Combat Showdown, Character Dossier, and Codex!
 *
 * Clean architectural editorial craft:
 *  - Sunlit ivory stock + 3px top accent rule + subtle hairline frame (ZERO nested box clutter!)
 *  - Crisp Header: Cost Crystal + Bold Skill Name + Owner + Status/Play-Mode micro tag
 *  - Hairline Divider
 *  - Exact Trait Strip (only if present)
 *  - 100% Verbatim Skill-Level Entries (only if present)
 *  - Hairline-Separated Unified Die Rows (Framed Icon + Exact Range + Inline Damage Spec + Rich Verbatim Triggers)
 */
export function buildFullCard(card, {
  side = 1,
  accentColor = null,
  ownerName = '',
  showOwner = false,
  width = 264,
  minHeight = 0,
  fixedHeight = 0,
  dense = false,
  compact = false,
  centered = false,
  legal = true,
  selected = false,
  activeDieNumber = null,
  rangeDeficit = 0,
  playMode = null,
} = {}) {
  const pal = deriveCardPalette(accentColor, side);
  const W = width;
  const padX = dense ? 9 : 11;
  const innerW = W - padX * 2;
  const isBlanked = rangeDeficit >= 3;
  const tight = dense || compact;
  const headerH = tight ? 36 : 42;

  const root = new PIXI.Container();
  const sheet = new PIXI.Container();
  const bodyTop = headerH + (tight ? 5 : 7);
  const dice = card.dice || [];

  const layoutBody = (targetInnerW) => {
    const box = new PIXI.Container();
    let y = 0;
    const addDie = (die, idx) => {
      const position = idx + 1;
      const active = activeDieNumber === position;
      const live = card.live_dice?.findLast(d => d?.position === position);
      const destroyed = !active && (card.destroyed_die_positions || []).includes(position);
      const row = buildUnifiedDieRow(die, {width: targetInnerW, active, destroyed,
        spent: destroyed || (activeDieNumber !== null && position < activeDieNumber),
        dense, compact, showDivider: idx < dice.length - 1,
        liveResult: live?.result ?? null, isBlanked: dieShowsBlank(die, live, rangeDeficit)});
      row.position.set(0, y);
      box.addChild(row);
      y += row._height + (idx < dice.length - 1 ? 1 : 0);
    };

    // 1. Exact Skill Trait Strip directly from structured card fields (ONLY if present)
    const traitNode = buildTraitPills(card, targetInnerW, { compact: tight, blanked: isBlanked });
    if (traitNode && traitNode._height > 0) {
      traitNode.position.set(0, y);
      box.addChild(traitNode);
      y += traitNode._height + (tight ? 4 : 6);
    }

    // 2. Skill-Level Entries with data-driven 【触发器】 highlight (ONLY if present)
    if (!isBlanked && card.entries && card.entries.length) {
      const skillPlate = buildUnifiedEntryPlate({
        variant: 'skill',
        entries: card.entries,
        width: targetInnerW,
        accentColor: pal.accent,
        fontSize: dense ? 10.6 : compact ? 11 : 11.8,
        lineHeight: dense ? 14.6 : compact ? 16 : 17.5,
        compact: tight,
      });
      skillPlate.position.set(0, y);
      box.addChild(skillPlate);
      y += skillPlate._height + (tight ? 4 : 7);
    }

    // 3. Hairline-Separated Unified Die Rows (direct from die.type / range / die.damage_parts / die.entries)
    dice.forEach(addDie);

    return { box, bodyH: y };
  };

  let { box: content, bodyH: naturalBodyH } = layoutBody(innerW);
  const H = fixedHeight > 0
    ? Math.round(fixedHeight)
    : Math.max(minHeight || (tight ? 96 : 108), bodyTop + naturalBodyH + (tight ? 7 : 9));

  // Area-preserving editorial re-typeset for fixed-height physical cards:
  // ZERO scrollbars inside cards, ZERO stretching, ZERO wasted side margins!
  let renderedBodyH = naturalBodyH;
  if (fixedHeight > 0) {
    const availBodyH = Math.max(40, H - bodyTop - 7);
    if (naturalBodyH > availBodyH) {
      let fit = Math.max(0.68, Math.min(0.95, Math.sqrt(availBodyH / naturalBodyH) * 0.98));
      content.destroy({ children: true });
      const reLayout = layoutBody(Math.floor(innerW / fit));
      content = reLayout.box;
      if (reLayout.bodyH * fit > availBodyH) {
        fit = Math.max(0.64, availBodyH / reLayout.bodyH);
      }
      content.scale.set(fit);
      renderedBodyH = reLayout.bodyH * fit;
    }
  }
  content.position.set(padX, bodyTop);

  // Physical printed card body — character-colored rim, header tint, cost crystal & pressmark (NO fake gold ultimate rim!)
  const bg = new PIXI.Graphics();
  bg.roundRect(3, 7, W, H, 8).fill({ color: INK.shadow, alpha: selected ? 0.34 : 0.2 });
  bg.roundRect(1, 3, W, H, 8).fill({ color: 0xe3dac9 });
  if (selected && !isBlanked) {
    bg.roundRect(-2.5, -2.5, W + 5, H + 5, 10).stroke({ width: 2.0, color: pal.accent, alpha: 0.42 });
  }
  const borderCol = isBlanked ? INK.muted : legal ? pal.accent : pal.border;
  const topBarCol = isBlanked ? INK.muted : pal.accent;
  bg.roundRect(0, 0, W, H, 8)
    .fill({ color: isBlanked ? 0xf3efe8 : INK.paper, alpha: 0.995 })
    .stroke({ width: selected ? 2.4 : 1.45, color: borderCol, alpha: selected ? 1 : legal ? 0.85 : 0.55 });

  // Soft character-colored header tint band so card identity reads instantaneously on the front face!
  if (!isBlanked) {
    bg.roundRect(1, 1, W - 2, headerH - 1, 7).fill({ color: pal.softBg, alpha: 0.72 });
  }

  // Clean 3.5px top architectural accent bar in character's own color
  bg.roundRect(1, 1, W - 2, 3.6, 2).fill({ color: topBarCol });

  // Hairline header separator
  bg.moveTo(padX, headerH).lineTo(W - padX, headerH)
    .stroke({ width: 0.9, color: pal.border, alpha: 0.65 });

  // Subtle printed bottom pressmark on uniform-height cards with breathing space
  if ((minHeight || fixedHeight) && H - (bodyTop + renderedBodyH) > 18) {
    const py = H - 10;
    const mid = W / 2;
    bg.moveTo(padX + 18, py).lineTo(mid - 9, py).stroke({ width: 0.8, color: pal.border, alpha: 0.55 });
    bg.moveTo(mid + 9, py).lineTo(W - padX - 18, py).stroke({ width: 0.8, color: pal.border, alpha: 0.55 });
    bg.poly([mid, py - 3, mid + 3.2, py, mid, py + 3, mid - 3.2, py])
      .fill({ color: pal.accent, alpha: 0.65 });
  }

  // Cost Crystal (top-left) directly from card.cost
  const cx = padX + 12;
  const cy = 3 + (headerH - 3) / 2;
  drawCostCrystal(bg, cx, cy, tight ? 11.2 : 12.8, isBlanked ? INK.muted : pal.accent);
  sheet.addChild(bg);

  const cTxt = new PIXI.Text({
    text: String(card.cost ?? 0),
    style: { fontFamily: FONT_NUM, fontSize: tight ? 13 : 14.8, fontWeight: '900', fill: INK.paper },
  });
  cTxt.anchor.set(0.5);
  cTxt.position.set(cx, cy + 0.5);
  sheet.addChild(cTxt);

  // Skill Name directly from card.name
  const titleTxt = new PIXI.Text({
    text: card.name || '',
    style: {
      fontFamily: FONT_UI,
      fontSize: dense ? 13.2 : compact ? 13.8 : 15,
      fontWeight: '800',
      fill: isBlanked ? INK.muted : INK.strong,
    },
  });
  titleTxt.anchor.set(0, 0.5);
  titleTxt.position.set(padX + 29, cy);
  sheet.addChild(titleTxt);

  // Subtle right-aligned owner or play-mode / suppression stamp in header
  let rightCursor = W - padX;
  if (playMode || rangeDeficit > 0) {
    const label = rangeDeficit > 0 ? `压制-${rangeDeficit}` : playMode === 'pulled' ? '被牵制' : playMode === 'passive' ? '迎击' : '主动';
    const col = rangeDeficit > 0 ? 0xc93e2b : playMode === 'pulled' ? INK.gold : pal.accent;
    const tagT = new PIXI.Text({
      text: label,
      style: { fontFamily: FONT_UI, fontSize: 9.2, fontWeight: '800', fill: INK.paper },
    });
    const tw = Math.ceil(tagT.width) + 10;
    const tagBg = new PIXI.Graphics();
    tagBg.roundRect(rightCursor - tw, cy - 8, tw, 16, 4).fill({ color: col });
    tagT.anchor.set(0.5);
    tagT.position.set(rightCursor - tw / 2, cy);
    sheet.addChild(tagBg, tagT);
    rightCursor -= tw + 6;
  }

  if ((showOwner || !dense) && ownerName) {
    const owTxt = new PIXI.Text({
      text: ownerName,
      style: { fontFamily: FONT_UI, fontSize: 10.2, fontWeight: '800', fill: pal.accent },
    });
    owTxt.anchor.set(1, 0.5);
    if (rightCursor - owTxt.width > padX + 34 + titleTxt.width) {
      owTxt.position.set(rightCursor, cy);
      sheet.addChild(owTxt);
      rightCursor -= owTxt.width + 6;
    } else {
      owTxt.destroy();
    }
  }
  if (titleTxt.width > Math.max(40, rightCursor - titleTxt.x)) {
    titleTxt.scale.set(Math.max(40, rightCursor - titleTxt.x) / titleTxt.width);
  }

  sheet.addChild(content);

  const isDestroyedCard = Boolean(card.destroyed || card.state === 'negated');
  if (isDestroyedCard) {
    const shatter = new PIXI.Graphics();
    shatter.roundRect(0, 0, W, H, 8)
      .fill({ color: 0x2c2420, alpha: 0.34 })
      .stroke({ width: 2, color: 0xb83a2a, alpha: 0.9 });
    shatter.moveTo(10, 10).lineTo(W - 10, H - 10)
      .moveTo(W - 10, 10).lineTo(10, H - 10)
      .stroke({ width: 2.2, color: 0xb83a2a, alpha: 0.55 });
    const stampW = Math.min(W - 20, 86);
    const stampH = 22;
    shatter.roundRect((W - stampW) / 2, (H - stampH) / 2, stampW, stampH, 5)
      .fill({ color: 0x3b1814, alpha: 0.92 })
      .stroke({ width: 1.4, color: 0xe86b58, alpha: 0.95 });
    sheet.addChild(shatter);
    const stampTxt = new PIXI.Text({
      text: '已摧毁',
      style: { fontFamily: FONT_UI, fontSize: 11.5, fontWeight: '900', fill: 0xffece8, letterSpacing: 1.5 },
    });
    stampTxt.anchor.set(0.5);
    stampTxt.position.set(W / 2, H / 2);
    sheet.addChild(stampTxt);
  } else if (!legal) {
    const wash = new PIXI.Graphics();
    wash.roundRect(0, 0, W, H, 8).fill({ color: 0xf5f1e7, alpha: 0.48 });
    sheet.addChild(wash);
  }

  if (centered) {
    sheet.position.set(-W / 2, -H / 2);
  }
  root.addChild(sheet);
  root._boxWidth = W;
  root._boxHeight = H;
  return root;
}

/**
 * Full verbatim panel alias (top-left origin) used by Dossier, Combat Showdown & Codex.
 */
export function buildVerbatimCardPanel(card, options = {}) {
  return buildFullCard(card, { ...options, centered: false });
}

/**
 * Ultra-compact card token (only used when a board slot has extreme space pressure).
 * Matches the exact same clean sunlit-paper editorial grammar!
 */
export function buildCardFront(card, options = {}) {
  return buildFullCard(card, {
    ...options,
    width: options.width || 248,
    minHeight: options.height || 0,
    dense: true,
    centered: true,
  });
}

/**
 * Strictly Uniform-Size Physical Card (`1 动 0 字 ≡ 30 动 1000 字`):
 *  - Outer W × H is 100% invariant regardless of dice count (1..30+) or entry text length (0..1000+ chars).
 *  - ZERO truncation (no 5-die cap), ZERO unreadable font-shrinking, ZERO web scrollbars.
 *  - Overflowing content smoothly scrolls inside the masked parchment viewport with soft ivory edge fades,
 *    auto-tracks `activeDieNumber`, and exposes `.scrollBy(dy)` / `.scrollToDie(pos)` / `.tick(dt)`.
 */
export function buildUniformCard(card, {
  side = 1,
  accentColor = null,
  ownerName = '',
  showOwner = false,
  width = 224,
  height = 314,
  centered = true,
  selected = false,
  activeCard = false,
  activeDieNumber = null,
  concealActiveScore = false,
  concealActiveOutcome = false,
  rangeDeficit = 0,
  playMode = null,
  statusBadge = null, // 'settled' | 'skipped' | 'dissolved' | null
  initialScrollY = null,
} = {}) {
  const pal = deriveCardPalette(accentColor, side);
  const W = Math.round(width);
  const H = Math.round(height);
  const padX = 9;
  const innerW = W - padX * 2;
  const effectiveDeficit = rangeDeficit || card.range_deficit || 0;
  const isBlanked = effectiveDeficit >= 3;
  const isDestroyedCard = Boolean(card.destroyed || card.state === 'negated');
  const isSettled = Boolean(statusBadge === 'settled' || statusBadge === 'skipped' || statusBadge === 'dissolved' || (card.used && !activeCard));
  const headerH = 36;
  const bodyTop = headerH + 5;
  const bodyBottomPad = 8;
  const viewH = Math.max(40, H - bodyTop - bodyBottomPad);

  const root = new PIXI.Container();
  const sheet = new PIXI.Container();

  // Build lookup of live/settled dice by 1-based position
  const liveByPos = new Map();
  for (const ld of card.live_dice || []) {
    if (ld && ld.position != null) liveByPos.set(ld.position, ld);
  }

  // 1. Physical card-stock body (strictly W × H)
  const bg = new PIXI.Graphics();
  bg.roundRect(3, 7, W, H, 8).fill({ color: INK.shadow, alpha: activeCard ? 0.3 : selected ? 0.34 : 0.2 });
  bg.roundRect(1, 3, W, H, 8).fill({ color: 0xe3dac9 });
  if (activeCard && !isDestroyedCard) {
    bg.roundRect(-2.5, -2.5, W + 5, H + 5, 10)
      .stroke({ width: 2.2, color: INK.gold, alpha: 0.72 });
  } else if (selected && !isBlanked) {
    bg.roundRect(-2.5, -2.5, W + 5, H + 5, 10)
      .stroke({ width: 2.0, color: pal.accent, alpha: 0.45 });
  }
  const borderCol = isBlanked ? INK.muted : activeCard ? INK.goldDeep : isSettled ? pal.border : pal.accent;
  const topBarCol = isBlanked ? INK.muted : pal.accent;
  bg.roundRect(0, 0, W, H, 8)
    .fill({ color: isBlanked ? 0xf3efe8 : isSettled ? 0xf8f4ec : INK.paper, alpha: 0.995 })
    .stroke({ width: activeCard ? 1.85 : 1.45, color: borderCol, alpha: isSettled ? 0.72 : 0.92 });

  if (!isBlanked) {
    bg.roundRect(1, 1, W - 2, headerH - 1, 7)
      .fill({ color: pal.softBg, alpha: isSettled ? 0.45 : 0.76 });
  }
  bg.roundRect(1, 1, W - 2, 3.6, 2).fill({ color: topBarCol, alpha: isSettled ? 0.65 : 1 });
  bg.moveTo(padX, headerH).lineTo(W - padX, headerH)
    .stroke({ width: 0.9, color: pal.border, alpha: 0.65 });

  // Cost Crystal (top-left)
  const cx = padX + 12;
  const cy = 3 + (headerH - 3) / 2;
  drawCostCrystal(bg, cx, cy, 11.2, isBlanked ? INK.muted : pal.accent);
  sheet.addChild(bg);

  const cTxt = new PIXI.Text({
    text: String(card.cost ?? 0),
    style: { fontFamily: FONT_NUM, fontSize: 13, fontWeight: '900', fill: INK.paper },
  });
  cTxt.anchor.set(0.5);
  cTxt.position.set(cx, cy + 0.5);
  sheet.addChild(cTxt);

  const titleTxt = new PIXI.Text({
    text: card.name || '',
    style: {
      fontFamily: FONT_UI,
      fontSize: 13.2,
      fontWeight: '800',
      fill: isBlanked ? INK.muted : isSettled ? INK.secondary : INK.strong,
    },
  });
  titleTxt.anchor.set(0, 0.5);
  titleTxt.position.set(padX + 28, cy);
  sheet.addChild(titleTxt);

  // 2. Full 1:1 readable inner content (NEVER truncated, NEVER squished)
  const content = new PIXI.Container();
  const dice = card.dice || [];
  const dieRowBounds = new Map(); // position -> { y, h }
  let cursorY = 0;

  const traitNode = buildTraitPills(card, innerW, { compact: true, blanked: isBlanked });
  if (traitNode && traitNode._height > 0) {
    traitNode.position.set(0, cursorY);
    content.addChild(traitNode);
    cursorY += traitNode._height + 4;
  }

  if (!isBlanked && card.entries && card.entries.length) {
    const skillPlate = buildUnifiedEntryPlate({
      variant: 'skill',
      entries: card.entries,
      width: innerW,
      accentColor: pal.accent,
      fontSize: 10.6,
      lineHeight: 14.8,
      compact: true,
    });
    skillPlate.position.set(0, cursorY);
    content.addChild(skillPlate);
    cursorY += skillPlate._height + 5;
  }

  dice.forEach((die, idx) => {
    const position = idx + 1;
    const isActiveDie = activeDieNumber === position;
    const liveDie = liveByPos.get(position) || null;
    const isDestroyedDie = Boolean(liveDie?.destroyed) || (!isActiveDie && (card.destroyed_die_positions || []).includes(position));
    const hasSettledResult = Boolean(
      liveDie && !isActiveDie && (liveDie.result != null || liveDie.destroyed || liveDie.landed_hits > 0),
    );
    const isSpent = isDestroyedDie || hasSettledResult || (isSettled && !isActiveDie) || (activeDieNumber !== null && position < activeDieNumber);

    const liveScore = (liveDie && !(isActiveDie && concealActiveScore) && !isDestroyedDie && liveDie.result !== 'skip')
      ? (liveDie.clash_score ?? liveDie.final_score ?? liveDie.rolled_value ?? null)
      : null;
    const liveResult = (liveDie && !(isActiveDie && concealActiveOutcome))
      ? (liveDie.result ?? null)
      : null;

    const row = buildUnifiedDieRow(die, {
      width: innerW,
      active: isActiveDie,
      spent: isSpent,
      destroyed: isDestroyedDie,
      dense: true,
      showDivider: idx < dice.length - 1,
      isBlanked: dieShowsBlank(die, liveDie, effectiveDeficit),
      liveScore,
      liveResult,
    });
    row.position.set(0, cursorY);
    content.addChild(row);
    dieRowBounds.set(position, { y: cursorY, h: row._height });
    cursorY += row._height + (idx < dice.length - 1 ? 1 : 0);
  });

  const naturalBodyH = cursorY;
  const maxScroll = Math.max(0, Math.ceil(naturalBodyH - viewH));

  // Header right tags (status / suppression / die position indicator for overflowing cards)
  let rightCursor = W - padX;
  const addHeaderPill = (label, pillBg, textColor = INK.paper) => {
    const t = new PIXI.Text({
      text: label,
      style: { fontFamily: FONT_UI, fontSize: 9, fontWeight: '800', fill: textColor },
    });
    const tw = Math.ceil(t.width) + 9;
    const g = new PIXI.Graphics();
    g.roundRect(rightCursor - tw, cy - 8, tw, 16, 4).fill({ color: pillBg });
    t.anchor.set(0.5);
    t.position.set(rightCursor - tw / 2, cy);
    sheet.addChild(g, t);
    rightCursor -= tw + 5;
  };

  if (statusBadge === 'dissolved') addHeaderPill('已消散', 0x7b6d61);
  else if (statusBadge === 'skipped') addHeaderPill('已跳过', 0x8b7e70);
  else if (statusBadge === 'settled' || (isSettled && !isDestroyedCard)) addHeaderPill('已结算', 0x7a7065);
  else if (effectiveDeficit > 0) addHeaderPill(`压制-${effectiveDeficit}`, 0xc93e2b);
  else if (playMode) {
    addHeaderPill(
      playMode === 'pulled' ? '被牵制' : playMode === 'passive' ? '迎击' : '主动',
      playMode === 'pulled' ? INK.gold : pal.accent,
    );
  }

  if (maxScroll > 0 && dice.length > 0) {
    const posTag = activeDieNumber ? `${activeDieNumber}/${dice.length}骰` : `${dice.length}骰`;
    addHeaderPill(posTag, INK.goldBg, INK.goldDeep);
  }

  if (showOwner && ownerName) {
    const owTxt = new PIXI.Text({
      text: ownerName,
      style: { fontFamily: FONT_UI, fontSize: 10, fontWeight: '800', fill: pal.accent },
    });
    owTxt.anchor.set(1, 0.5);
    if (rightCursor - owTxt.width > padX + 34 + titleTxt.width) {
      owTxt.position.set(rightCursor, cy);
      sheet.addChild(owTxt);
      rightCursor -= owTxt.width + 5;
    } else {
      owTxt.destroy();
    }
  }
  const maxTitleW = Math.max(36, rightCursor - titleTxt.x - 2);
  if (titleTxt.width > maxTitleW) {
    titleTxt.scale.set(maxTitleW / titleTxt.width);
  }

  // Bottom physical pressmark when card has breathing room (makes 1-die 0-char cards look balanced & complete)
  if (maxScroll === 0 && viewH - naturalBodyH > 20) {
    const py = H - 10;
    const mid = W / 2;
    bg.moveTo(padX + 18, py).lineTo(mid - 9, py).stroke({ width: 0.8, color: pal.border, alpha: 0.55 });
    bg.moveTo(mid + 9, py).lineTo(W - padX - 18, py).stroke({ width: 0.8, color: pal.border, alpha: 0.55 });
    bg.poly([mid, py - 3, mid + 3.2, py, mid, py + 3, mid - 3.2, py])
      .fill({ color: pal.accent, alpha: 0.62 });
  }

  // 3. Masked inner parchment viewport (card face stays 100% pixel-identical to printed hand card!)
  const viewport = new PIXI.Container();
  viewport.position.set(padX, bodyTop);
  const maskG = new PIXI.Graphics();
  maskG.rect(0, 0, innerW, viewH).fill({ color: 0xffffff });
  viewport.addChild(maskG, content);
  content.mask = maskG;
  sheet.addChild(viewport);

  // Soft top/bottom parchment fade edges (ZERO web scrollbar!)
  const topFade = new PIXI.Graphics();
  const botFade = new PIXI.Graphics();
  const fadeBg = isBlanked ? 0xf3efe8 : isSettled ? 0xf8f4ec : INK.paper;
  const fadeSteps = 5;
  const fadeH = 16;
  for (let i = 0; i < fadeSteps; i++) {
    const sh = fadeH / fadeSteps;
    const a = ((fadeSteps - i) / fadeSteps) * 0.88;
    topFade.rect(0, i * sh, innerW, sh + 0.5).fill({ color: fadeBg, alpha: a });
    botFade.rect(0, viewH - (i + 1) * sh, innerW, sh + 0.5).fill({ color: fadeBg, alpha: a });
  }
  // Subtle parchment directional chevrons inside the fade
  const midX = innerW / 2;
  topFade.moveTo(midX - 5, 6).lineTo(midX, 2).lineTo(midX + 5, 6)
    .stroke({ width: 1.3, color: INK.goldDeep, alpha: 0.75 });
  botFade.moveTo(midX - 5, viewH - 6).lineTo(midX, viewH - 2).lineTo(midX + 5, viewH - 6)
    .stroke({ width: 1.3, color: INK.goldDeep, alpha: 0.75 });
  topFade.visible = false;
  botFade.visible = false;
  viewport.addChild(topFade, botFade);

  // Scroll state (smooth damped motion inside fixed card frame)
  let targetScrollY = 0;
  let currentScrollY = 0;

  const clampScroll = (y) => Math.max(0, Math.min(maxScroll, y));
  const applyScroll = (y) => {
    currentScrollY = clampScroll(y);
    content.y = -Math.round(currentScrollY);
    topFade.visible = maxScroll > 0 && currentScrollY > 2;
    botFade.visible = maxScroll > 0 && currentScrollY < maxScroll - 2;
  };

  const computeDieTargetScroll = (pos) => {
    const b = dieRowBounds.get(pos);
    if (!b || maxScroll <= 0) return 0;
    return clampScroll(b.y + b.h / 2 - viewH * 0.48);
  };

  if (initialScrollY != null) {
    targetScrollY = clampScroll(initialScrollY);
    applyScroll(targetScrollY);
  } else if (activeDieNumber != null && maxScroll > 0) {
    targetScrollY = computeDieTargetScroll(activeDieNumber);
    applyScroll(targetScrollY);
  } else {
    applyScroll(0);
  }

  // Destroyed overlay stamp (keeps card on table with clear shatter seal)
  if (isDestroyedCard) {
    const shatter = new PIXI.Graphics();
    shatter.roundRect(0, 0, W, H, 8)
      .fill({ color: 0x2c2420, alpha: 0.28 })
      .stroke({ width: 2, color: 0xb83a2a, alpha: 0.9 });
    shatter.moveTo(10, 10).lineTo(W - 10, H - 10)
      .moveTo(W - 10, 10).lineTo(10, H - 10)
      .stroke({ width: 2.0, color: 0xb83a2a, alpha: 0.5 });
    const stampW = Math.min(W - 20, 86);
    const stampH = 22;
    shatter.roundRect((W - stampW) / 2, (H - stampH) / 2, stampW, stampH, 5)
      .fill({ color: 0x3b1814, alpha: 0.92 })
      .stroke({ width: 1.4, color: 0xe86b58, alpha: 0.95 });
    sheet.addChild(shatter);
    const stampTxt = new PIXI.Text({
      text: '已摧毁',
      style: { fontFamily: FONT_UI, fontSize: 11.5, fontWeight: '900', fill: 0xffece8, letterSpacing: 1.5 },
    });
    stampTxt.anchor.set(0.5);
    stampTxt.position.set(W / 2, H / 2);
    sheet.addChild(stampTxt);
  }

  if (centered) {
    sheet.position.set(-W / 2, -H / 2);
  }
  root.addChild(sheet);

  root._boxWidth = W;
  root._boxHeight = H;
  root.maxScroll = maxScroll;
  root.isOverflowing = maxScroll > 0;
  Object.defineProperty(root, 'scrollY', {
    get: () => targetScrollY,
  });
  root.setScroll = (y, { immediate = false } = {}) => {
    targetScrollY = clampScroll(y);
    if (immediate) applyScroll(targetScrollY);
  };
  root.scrollBy = (dy) => {
    targetScrollY = clampScroll(targetScrollY + dy);
  };
  root.scrollToDie = (pos, { immediate = false } = {}) => {
    targetScrollY = computeDieTargetScroll(pos);
    if (immediate) applyScroll(targetScrollY);
  };
  root.tick = (dtSec) => {
    if (maxScroll <= 0) return;
    if (Math.abs(targetScrollY - currentScrollY) > 0.35) {
      applyScroll(currentScrollY + (targetScrollY - currentScrollY) * Math.min(1, dtSec * 15));
    } else if (currentScrollY !== targetScrollY) {
      applyScroll(targetScrollY);
    }
  };
  return root;
}
