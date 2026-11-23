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
  TIMING_STYLE,
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
  extractDieDamageBadge,
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
  TIMING_STYLE,
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
  extractDieDamageBadge,
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
 * Clean Physical Card Back colored in the owning character's signature color.
 */
export function buildCardBack(side = 1, { width = 82, height = 104, accentColor = null } = {}) {
  const pal = deriveCardPalette(accentColor, side);
  const root = new PIXI.Container();
  const hw = width / 2;
  const hh = height / 2;

  const g = new PIXI.Graphics();
  // Soft layered shadow + 2.5px physical paper-stack bottom edge
  g.roundRect(-hw + 2, -hh + 6, width, height, 7).fill({ color: INK.shadow, alpha: 0.22 });
  g.roundRect(-hw, -hh + 2.5, width, height, 7).fill({ color: 0xe3dac9 });
  g.roundRect(-hw, -hh, width, height, 7)
    .fill({ color: INK.paper })
    .stroke({ width: 1.55, color: pal.accent, alpha: 0.92 });
  g.roundRect(-hw + 5, -hh + 5, width - 10, height - 10, 4)
    .fill({ color: pal.softBg })
    .stroke({ width: 0.95, color: pal.border, alpha: 0.72 });
  g.poly([0, -hh + 13, hw - 13, 0, 0, hh - 13, -hw + 13, 0])
    .stroke({ width: 1.0, color: pal.accent, alpha: 0.42 });
  drawLightStar(g, 0, 0, Math.min(width, height) * 0.21, pal.accent, 0.92);
  root.addChild(g);
  root._boxWidth = width;
  root._boxHeight = height;
  return root;
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
  if (card.printed_text && !isBlanked) {
    const printW = Math.max(200, W);
    const face = buildFullCard(card, { side, accentColor, width: printW, fixedHeight: H * printW / W,
      dense: true, centered: true, playMode, rangeDeficit, activeDieNumber });
    const root = new PIXI.Container();
    face.scale.set(W / printW);
    root.addChild(face);
    root._boxWidth = W;
    root._boxHeight = H;
    return root;
  }
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
  const traits = isBlanked ? [] : exactSkillTraits(card);
  const hasFooter = !isBlanked && ((card.entries && card.entries.length > 0) || traits.length > 0);
  const footerH = hasFooter ? 16 : 12;
  const maxRows = Math.min(dice.length, 5);
  const availH = Math.max(20, H - footerH - cursorY - 2);
  const rowH = maxRows > 0 ? Math.max(16, Math.min(24, Math.floor(availH / maxRows))) : 20;

  const rowG = new PIXI.Graphics();
  sheet.addChild(rowG);

  for (let i = 0; i < maxRows; i++) {
    const die = dice[i];
    const ry = cursorY + i * rowH;
    const dType = isBlanked ? 'blank' : die.type;
    const ds = DIE_STYLE[dType] || DIE_STYLE.blank;
    const { badge, restEntries } = isBlanked ? { badge: null, restEntries: [] } : extractDieDamageBadge(die.entries);

    if (activeDieNumber === i + 1) {
      rowG.roundRect(padX - 2, ry + 1, W - padX * 2 + 4, rowH - 2, 3).fill({ color: INK.goldBg, alpha: 0.95 })
        .stroke({ width: 1.1, color: INK.gold, alpha: 0.9 });
    }
    rowG.roundRect(padX, ry + 2, 2.4, rowH - 4, 1).fill({ color: ds.color, alpha: 0.9 });
    if (i < maxRows - 1) {
      rowG.moveTo(padX + 4, ry + rowH).lineTo(W - padX, ry + rowH).stroke({ width: 0.75, color: INK.hairline });
    }
    drawUnifiedDieFrame(rowG, dType, padX + 11, ry + rowH / 2, Math.min(4.6, rowH * 0.24));

    const rngTxt = new PIXI.Text({
      text: formatDieRange(die),
      style: { fontFamily: FONT_NUM, fontSize: W < 108 ? 9.8 : 10.6, fontWeight: '900', fill: ds.color },
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
        text: badge.shortText,
        style: { fontFamily: FONT_UI, fontSize: 8.6, fontWeight: '800', fill: badge.style.color },
      });
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
    if (card.entries && card.entries.length) fBits.push(`◆${card.entries.length}条`);
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

  const printedLines = !isBlanked && card.printed_text ? card.printed_text.split('\n') : null;
  const layoutBody = (targetInnerW) => {
    const box = new PIXI.Container();
    let y = 0;
    const addDie = (die, idx) => {
      const position = idx + 1;
      const active = activeDieNumber === position;
      const destroyed = !active && (card.destroyed_die_positions || []).includes(position);
      const row = buildUnifiedDieRow(die, {width: targetInnerW, active, destroyed,
        spent: destroyed || (activeDieNumber !== null && position < activeDieNumber),
        dense, compact, showDivider: idx < dice.length - 1, isBlanked});
      row.position.set(0, y);
      box.addChild(row);
      y += row._height + (idx < dice.length - 1 ? 1 : 0);
    };

    if (printedLines) {
      let idx = 0;
      for (const line of printedLines.slice(1)) {
        if (line === dice[idx]?.printed_line) {
          addDie(dice[idx], idx);
          idx++;
        } else if (line) {
          const text = buildRichVerbatimText(line, {maxWidth: targetInnerW,
            fontSize: dense ? 10.6 : compact ? 11 : 11.8, lineHeight: tight ? 15 : 17.5});
          text.y = y;
          box.addChild(text);
          y += text._height;
        } else {
          y += 7;
        }
      }
      for (; idx < dice.length; idx++) addDie(dice[idx], idx);
      return { box, bodyH: y };
    }

    // 1. Exact Printed Trait Strip (ONLY if present)
    const traitNode = isBlanked ? null : buildTraitPills(card, targetInnerW, { compact: tight });
    if (traitNode && traitNode._height > 0) {
      traitNode.position.set(0, y);
      box.addChild(traitNode);
      y += traitNode._height + (tight ? 4 : 6);
    }

    // 2. 100% Verbatim Skill-Level Entries (ONLY if present)
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

    // 3. Hairline-Separated Unified Die Rows (ZERO nested boxes!)
    dice.forEach(addDie);

    return { box, bodyH: y };
  };

  let { box: content, bodyH: naturalBodyH } = layoutBody(innerW);
  const H = fixedHeight > 0
    ? Math.round(fixedHeight)
    : Math.max(minHeight || (tight ? 96 : 108), bodyTop + naturalBodyH + (tight ? 7 : 9));

  // Area-preserving editorial re-typeset for fixed-height physical cards (like printed MTG/Yu-Gi-Oh cards):
  // ZERO scrollbars inside cards, ZERO stretching, ZERO wasted side margins, 100% verbatim visible!
  let renderedBodyH = naturalBodyH;
  if (fixedHeight > 0) {
    const availBodyH = Math.max(40, H - bodyTop - 7);
    if (naturalBodyH > availBodyH) {
      let fit = Math.max(0.68, Math.min(0.95, Math.sqrt(availBodyH / naturalBodyH) * 0.98));
      content.destroy({ children: true });
      const reLayout = layoutBody(Math.floor(innerW / fit));
      content = reLayout.box;
      if (reLayout.bodyH * fit > availBodyH) {
        fit = printedLines ? availBodyH / reLayout.bodyH : Math.max(0.64, availBodyH / reLayout.bodyH);
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

  // Cost Crystal (top-left) in character's own color (ZERO gold ultimate override!)
  const cx = padX + 12;
  const cy = 3 + (headerH - 3) / 2;
  const showCost = !printedLines || card.cost !== card.printed_cost;
  if (showCost) drawCostCrystal(bg, cx, cy, tight ? 11.2 : 12.8, isBlanked ? INK.muted : pal.accent);
  sheet.addChild(bg);

  if (showCost) {
    const cTxt = new PIXI.Text({
      text: String(card.cost ?? 0),
      style: { fontFamily: FONT_NUM, fontSize: tight ? 13 : 14.8, fontWeight: '900', fill: INK.paper },
    });
    cTxt.anchor.set(0.5);
    cTxt.position.set(cx, cy + 0.5);
    sheet.addChild(cTxt);
  }

  const titleTxt = new PIXI.Text({
    text: printedLines ? printedLines[0] : card.name || '',
    style: {
      fontFamily: FONT_UI,
      fontSize: dense ? 13.2 : compact ? 13.8 : 15,
      fontWeight: '800',
      fill: isBlanked ? INK.muted : INK.strong,
    },
  });
  titleTxt.anchor.set(0, 0.5);
  titleTxt.position.set(padX + (showCost ? 29 : 0), cy);
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

  if (printedLines && titleTxt.width > rightCursor - titleTxt.x) {
    titleTxt.scale.set((rightCursor - titleTxt.x) / titleTxt.width);
  }
  if (!printedLines && (showOwner || !dense) && ownerName) {
    const owTxt = new PIXI.Text({
      text: ownerName,
      style: { fontFamily: FONT_UI, fontSize: 10.2, fontWeight: '800', fill: pal.accent },
    });
    owTxt.anchor.set(1, 0.5);
    if (rightCursor - owTxt.width > padX + 34 + titleTxt.width) {
      owTxt.position.set(rightCursor, cy);
      sheet.addChild(owTxt);
    } else {
      owTxt.destroy();
    }
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
