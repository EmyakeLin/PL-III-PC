/**
 * Bright warm-paper pure-WebGL Canvas tabletop overlays & Illuminated Folio Dossiers.
 * Craft language: Slay the Spire / Library of Ruina / Limbus Company tactile parchment & brass seals.
 * ZERO DOM, ZERO black, ZERO blue-purple, ZERO paraphrasing, ZERO tutorial filler.
 * Scales smoothly to 10v10+ squads, infinite rosters, and 3,000+ char verbatim passives.
 */

import * as PIXI from '../vendor/pixi.min.mjs';
import {
  FONT_UI,
  FONT_NUM,
  INK,
  SIDE_THEME,
  HP_BAR_COLOR,
  RANK_LABEL,
  RANK_COLOR,
  SHIELD_STYLE,
  STATUS_COLORS,
  getStatusColor,
  mountStatusIcon,
  OFFICIAL_STATUS_RULES,
  parseHexColor,
  wrapCjkText,
  drawShieldGlyph,
  drawLightStar,
  buildCardBack,
  buildFullCard,
  buildVerbatimCardPanel,
  buildUnifiedEntryPlate,
  buildUnifiedSkillRow,
} from './card_print.js';
import { createCharacterActor, actorPalette } from './stage_actors.js';

// ── SHARED ILLUMINATED FOLIO & HERALDIC PRESSWORK HELPERS ──

function drawCornerDiamonds(g, x, y, w, h, inset, r, color, alpha = 0.72) {
  const pts = [
    [x + inset, y + inset],
    [x + w - inset, y + inset],
    [x + inset, y + h - inset],
    [x + w - inset, y + h - inset],
  ];
  for (const [cx, cy] of pts) {
    g.poly([cx, cy - r, cx + r, cy, cx, cy + r, cx - r, cy]).fill({ color, alpha });
  }
}

function drawDiamondDivider(g, x1, x2, y, color = INK.line, diamondColor = INK.gold) {
  const mid = (x1 + x2) / 2;
  g.moveTo(x1, y).lineTo(mid - 8, y).stroke({ width: 1, color, alpha: 0.85 });
  g.moveTo(mid + 8, y).lineTo(x2, y).stroke({ width: 1, color, alpha: 0.85 });
  g.poly([mid, y - 3.6, mid + 4.4, y, mid, y + 3.6, mid - 4.4, y]).fill({ color: diamondColor, alpha: 0.88 });
}

function drawFolioFrame(g, x, y, w, h, {
  accent = INK.gold,
  bg = INK.paper,
  radius = 12,
  edgeDepth = 4,
  shadowAlpha = 0.26,
  topRibbonH = 0,
  ribbonFill = INK.paperSoft,
  cornerDiamonds = true,
  diamondColor = null,
} = {}) {
  // Soft physical tabletop drop shadow
  g.roundRect(x + 3, y + edgeDepth + 4, w, h, radius + 1).fill({ color: INK.shadow, alpha: shadowAlpha });
  // Stacked thick parchment deck-edge bevel
  if (edgeDepth > 0) {
    g.roundRect(x, y + edgeDepth, w, h, radius).fill({ color: 0xe3dac9 });
  }
  // Sunlit warm parchment sheet + crisp engraved outer border
  g.roundRect(x, y, w, h, radius)
    .fill({ color: bg, alpha: 0.995 })
    .stroke({ width: 1.7, color: accent, alpha: 0.92 });

  // Optional engraved top ceremonial header ribbon
  if (topRibbonH > 0) {
    g.roundRect(x + 1.5, y + 1.5, w - 3, topRibbonH, Math.max(4, radius - 2))
      .fill({ color: ribbonFill, alpha: 0.96 });
    g.moveTo(x + 10, y + topRibbonH + 1).lineTo(x + w - 10, y + topRibbonH + 1)
      .stroke({ width: 1, color: INK.line, alpha: 0.9 });
  }

  // Engraved inner hairline rule (double-hairline parchment folio craft)
  const inset = 4.5;
  if (w > 40 && h > 40) {
    g.roundRect(x + inset, y + inset, w - inset * 2, h - inset * 2, Math.max(4, radius - 4))
      .stroke({ width: 0.85, color: accent, alpha: 0.28 });
  }

  // Subtle corner diamond pressmarks
  if (cornerDiamonds && w > 64 && h > 64) {
    drawCornerDiamonds(g, x, y, w, h, 9.5, 2.7, diamondColor ?? accent, 0.72);
  }
}

function drawHeraldicCompass(g, cx, cy, r, accent = INK.gold, accentSoft = INK.line) {
  // Concentric engraved astrolabe / compass rings
  g.circle(cx, cy, r).stroke({ width: 1.2, color: accentSoft, alpha: 0.6 });
  g.circle(cx, cy, r * 0.84).stroke({ width: 0.85, color: accent, alpha: 0.34 });
  g.circle(cx, cy, r * 0.56).stroke({ width: 0.9, color: INK.gold, alpha: 0.32 });

  // Rotated architectural diamond + inscribed square
  const d = r * 0.82;
  g.poly([cx, cy - d, cx + d, cy, cx, cy + d, cx - d, cy])
    .stroke({ width: 0.9, color: accent, alpha: 0.28 });
  const sq = r * 0.57;
  g.rect(cx - sq, cy - sq, sq * 2, sq * 2)
    .stroke({ width: 0.8, color: INK.gold, alpha: 0.22 });

  // Cardinal and intercardinal compass ticks
  for (let i = 0; i < 8; i++) {
    const a = (i * Math.PI) / 4;
    const isCard = i % 2 === 0;
    const r0 = r * (isCard ? 0.84 : 0.9);
    const r1 = r * (isCard ? 1.07 : 1.01);
    g.moveTo(cx + Math.cos(a) * r0, cy + Math.sin(a) * r0)
      .lineTo(cx + Math.cos(a) * r1, cy + Math.sin(a) * r1)
      .stroke({ width: isCard ? 1.4 : 0.9, color: isCard ? accent : INK.gold, alpha: isCard ? 0.55 : 0.38 });
  }
}

function drawWaxSealBadge(g, cx, cy, r, color, innerColor = INK.paper) {
  // Scalloped octagonal wax seal
  const pts = [];
  const sides = 12;
  for (let i = 0; i < sides; i++) {
    const a = (i * Math.PI * 2) / sides;
    const rr = i % 2 === 0 ? r : r * 0.89;
    pts.push(cx + Math.cos(a) * rr, cy + Math.sin(a) * rr);
  }
  g.poly(pts).fill({ color, alpha: 0.96 }).stroke({ width: 1.1, color: INK.paper, alpha: 0.5 });
  g.circle(cx, cy, r * 0.68).stroke({ width: 0.9, color: innerColor, alpha: 0.55 });
}

function drawActionEmblem(g, kind, cx, cy, r, color) {
  if (kind === 'replace') {
    // Double swap chevron diamond
    g.poly([cx, cy - r, cx + r, cy, cx, cy + r, cx - r, cy])
      .fill({ color: INK.paper }).stroke({ width: 1.4, color });
    g.moveTo(cx - r * 0.42, cy - r * 0.16).lineTo(cx + r * 0.42, cy - r * 0.16).stroke({ width: 1.5, color });
    g.moveTo(cx - r * 0.42, cy + r * 0.18).lineTo(cx + r * 0.42, cy + r * 0.18).stroke({ width: 1.5, color });
  } else if (kind === 'attack') {
    // Sharp spearhead / crossed strike blade
    g.poly([cx, cy - r, cx + r * 0.72, cy, cx, cy + r, cx - r * 0.72, cy])
      .fill({ color });
    g.poly([cx, cy - r * 0.45, cx + r * 0.3, cy, cx, cy + r * 0.45, cx - r * 0.3, cy])
      .fill({ color: INK.paper });
  } else if (kind === 'intercept') {
    // Hexagonal guard / intercept crest
    const pts = [];
    for (let i = 0; i < 6; i++) {
      const a = -Math.PI / 2 + (i * Math.PI) / 3;
      pts.push(cx + Math.cos(a) * r, cy + Math.sin(a) * r);
    }
    g.poly(pts).fill({ color: INK.paper }).stroke({ width: 1.6, color });
    g.circle(cx, cy, r * 0.34).fill({ color });
  } else {
    drawLightStar(g, cx, cy, r, color, 0.95);
  }
}

function drawHeartIcon(g, cx, cy, r, col) {
  g.poly([
    cx, cy + r * 0.85,
    cx - r * 0.82, cy - r * 0.05,
    cx - r * 0.45, cy - r * 0.72,
    cx, cy - r * 0.25,
    cx + r * 0.45, cy - r * 0.72,
    cx + r * 0.82, cy - r * 0.05,
  ]).fill({ color: col });
}

function drawDuelPip(g, cx, cy, r, col) {
  g.poly([cx, cy - r, cx + r * 0.75, cy, cx, cy + r, cx - r * 0.75, cy]).fill({ color: col });
}

function pointerInsideLocalRect(container, globalPt, rx, ry, rw, rh) {
  const local = container.toLocal(globalPt);
  return local.x >= rx && local.x <= rx + rw && local.y >= ry && local.y <= ry + rh;
}

function cullVerticalItems(container, scrollY, viewH, buffer = 160) {
  const lo = scrollY - buffer;
  const hi = scrollY + viewH + buffer;
  for (const child of container.children) {
    if (typeof child._itemTop !== 'number') continue;
    const vis = child._itemBottom >= lo && child._itemTop <= hi;
    if (child.visible !== vis) child.visible = vis;
    if (child._interactiveItem) {
      child.eventMode = vis ? 'static' : 'none';
    }
  }
}

function cullHorizontalItems(container, scrollX, viewW, buffer = 220) {
  const lo = scrollX - buffer;
  const hi = scrollX + viewW + buffer;
  for (const child of container.children) {
    if (typeof child._itemLeft !== 'number') continue;
    const vis = child._itemRight >= lo && child._itemLeft <= hi;
    if (child.visible !== vis) child.visible = vis;
    if (child._interactiveItem) {
      child.eventMode = vis ? 'static' : 'none';
    }
  }
}

// ── 0. TACTILE TABLETOP SEAL BUTTON & DRAGGABLE SCROLLBARS ──

export function makeSealButton(label, {
  width = 138,
  height = 38,
  accent = 0x1c8a64,
  fill = INK.paper,
  textColor = INK.primary,
  solid = false,
  disabled = false,
  fontSize = 13,
  radius = 9,
  onClick = null,
} = {}) {
  const c = new PIXI.Container();
  const bg = new PIXI.Graphics();
  const ceremonial = width >= 112 && height >= 32;

  const draw = (hovered, pressed = false) => {
    bg.clear();
    const dy = pressed ? 1 : 0;
    bg.roundRect(1.5, pressed ? 2.5 : 4, width, height, radius)
      .fill({ color: INK.shadow, alpha: disabled ? 0.12 : hovered ? 0.34 : 0.24 });
    if (!disabled && !pressed && height >= 26) {
      bg.roundRect(0, 2, width, height, radius).fill({ color: solid ? 0xd9c9ad : 0xe3dac9, alpha: 0.72 });
    }
    const bgCol = disabled ? 0xebe5d9 : solid ? accent : hovered ? 0xfbf6eb : fill;
    bg.roundRect(0, dy, width, height, radius)
      .fill({ color: bgCol, alpha: hovered && solid ? 0.92 : 1 })
      .stroke({ width: hovered && !disabled ? 2.1 : 1.45, color: disabled ? INK.line : accent });

    // Inner hairline highlight for tactile wax/brass craft
    if (!disabled && width >= 44 && height >= 24) {
      bg.roundRect(2.5, dy + 2.5, width - 5, height - 5, Math.max(3, radius - 2.5))
        .stroke({ width: 0.75, color: solid ? INK.paper : accent, alpha: solid ? 0.34 : hovered ? 0.3 : 0.16 });
    }
    if (ceremonial && !disabled) {
      const pipCol = solid ? INK.paper : accent;
      const midY = dy + height / 2;
      bg.poly([10, midY - 2.4, 12.6, midY, 10, midY + 2.4, 7.4, midY]).fill({ color: pipCol, alpha: 0.65 });
      bg.poly([width - 10, midY - 2.4, width - 7.4, midY, width - 10, midY + 2.4, width - 12.6, midY]).fill({ color: pipCol, alpha: 0.65 });
    }
  };
  draw(false, false);
  c.addChild(bg);

  const txt = new PIXI.Text({
    text: label,
    style: {
      fontFamily: FONT_UI,
      fontSize,
      fontWeight: '800',
      fill: disabled ? INK.muted : solid ? INK.paper : textColor,
    },
  });
  txt.anchor.set(0.5);
  txt.position.set(width / 2, height / 2);
  c.addChild(txt);

  if (!disabled && onClick) {
    c.accessible = true;
    c.accessibleTitle = label;
    c.eventMode = 'static';
    c.cursor = 'pointer';
    c.on('pointerover', () => draw(true, false));
    c.on('pointerout', () => {
      txt.y = height / 2;
      draw(false, false);
    });
    c.on('pointerdown', (e) => {
      e.stopPropagation();
      txt.y = height / 2 + 1;
      draw(true, true);
    });
    c.on('pointerup', () => {
      txt.y = height / 2;
      draw(true, false);
    });
    c.on('pointerupoutside', () => {
      txt.y = height / 2;
      draw(false, false);
    });
    c.on('pointertap', (e) => {
      e.stopPropagation();
      onClick();
    });
  }
  return c;
}

function makeSmoothScrollbar({ x, y, height, totalH, viewH, scrollY = 0, accentColor = INK.secondary, onChange }) {
  const maxScroll = Math.max(0, totalH - viewH);
  const track = new PIXI.Container();
  track.position.set(x, y);
  const trackH = Math.max(24, height);
  const thumbH = Math.max(28, Math.round(trackH * (viewH / Math.max(viewH + 1, totalH))));
  const travel = Math.max(1, trackH - thumbH);

  const trackG = new PIXI.Graphics();
  trackG.roundRect(-5, 0, 14, trackH, 6).fill({ color: INK.paper, alpha: 0.001 });
  trackG.roundRect(0, 0, 4.5, trackH, 2.2).fill({ color: INK.hairline, alpha: 0.95 })
    .stroke({ width: 0.6, color: INK.line, alpha: 0.6 });
  track.addChild(trackG);

  const thumbG = new PIXI.Graphics();
  const drawThumb = (active) => {
    thumbG.clear();
    thumbG.roundRect(-1.2, 0, 7, thumbH, 3.5)
      .fill({ color: accentColor, alpha: active ? 0.96 : 0.74 })
      .stroke({ width: 0.75, color: INK.paper, alpha: 0.5 });
    const mid = thumbH / 2;
    thumbG.moveTo(0.8, mid - 3).lineTo(3.8, mid - 3).stroke({ width: 0.9, color: INK.paper, alpha: 0.65 });
    thumbG.moveTo(0.8, mid + 3).lineTo(3.8, mid + 3).stroke({ width: 0.9, color: INK.paper, alpha: 0.65 });
  };
  drawThumb(false);
  track.addChild(thumbG);

  const updateThumb = (sy) => {
    const c = Math.max(0, Math.min(maxScroll, sy));
    thumbG.y = maxScroll > 0 ? (c / maxScroll) * travel : 0;
  };
  updateThumb(scrollY);

  let dragging = false;
  const applyLocalY = (localY) => {
    const ratio = Math.max(0, Math.min(1, (localY - thumbH / 2) / travel));
    const next = ratio * maxScroll;
    updateThumb(next);
    if (onChange) onChange(next);
  };

  track.eventMode = 'static';
  track.cursor = 'pointer';
  track.on('pointerover', () => drawThumb(true));
  track.on('pointerout', () => { if (!dragging) drawThumb(false); });
  track.on('pointerdown', (e) => {
    e.stopPropagation();
    dragging = true;
    drawThumb(true);
    const local = track.toLocal(e.global);
    applyLocalY(local.y);
  });
  track.on('globalpointermove', (e) => {
    if (!dragging) return;
    const local = track.toLocal(e.global);
    applyLocalY(local.y);
  });
  const endDrag = () => {
    if (!dragging) return;
    dragging = false;
    drawThumb(false);
  };
  track.on('pointerup', endDrag);
  track.on('pointerupoutside', endDrag);

  track._updateThumb = updateThumb;
  return track;
}

function makeHorizontalScrollbar({ x, y, width, totalW, viewW, scrollX = 0, accentColor = INK.secondary, onChange }) {
  const maxScroll = Math.max(0, totalW - viewW);
  const track = new PIXI.Container();
  track.position.set(x, y);
  const trackW = Math.max(36, width);
  const thumbW = Math.max(32, Math.round(trackW * (viewW / Math.max(viewW + 1, totalW))));
  const travel = Math.max(1, trackW - thumbW);

  const trackG = new PIXI.Graphics();
  trackG.roundRect(0, -5, trackW, 14, 6).fill({ color: INK.paper, alpha: 0.001 });
  trackG.roundRect(0, 0, trackW, 4.5, 2.2).fill({ color: INK.hairline, alpha: 0.95 })
    .stroke({ width: 0.6, color: INK.line, alpha: 0.6 });
  track.addChild(trackG);

  const thumbG = new PIXI.Graphics();
  const drawThumb = (active) => {
    thumbG.clear();
    thumbG.roundRect(0, -1.2, thumbW, 7, 3.5)
      .fill({ color: accentColor, alpha: active ? 0.96 : 0.74 })
      .stroke({ width: 0.75, color: INK.paper, alpha: 0.5 });
    const mid = thumbW / 2;
    thumbG.moveTo(mid - 3, 0.8).lineTo(mid - 3, 3.8).stroke({ width: 0.9, color: INK.paper, alpha: 0.65 });
    thumbG.moveTo(mid + 3, 0.8).lineTo(mid + 3, 3.8).stroke({ width: 0.9, color: INK.paper, alpha: 0.65 });
  };
  drawThumb(false);
  track.addChild(thumbG);

  const updateThumb = (sx) => {
    const c = Math.max(0, Math.min(maxScroll, sx));
    thumbG.x = maxScroll > 0 ? (c / maxScroll) * travel : 0;
  };
  updateThumb(scrollX);

  let dragging = false;
  const applyLocalX = (localX) => {
    const ratio = Math.max(0, Math.min(1, (localX - thumbW / 2) / travel));
    const next = ratio * maxScroll;
    updateThumb(next);
    if (onChange) onChange(next);
  };

  track.eventMode = 'static';
  track.cursor = 'pointer';
  track.on('pointerover', () => drawThumb(true));
  track.on('pointerout', () => { if (!dragging) drawThumb(false); });
  track.on('pointerdown', (e) => {
    e.stopPropagation();
    dragging = true;
    drawThumb(true);
    const local = track.toLocal(e.global);
    applyLocalX(local.x);
  });
  track.on('globalpointermove', (e) => {
    if (!dragging) return;
    const local = track.toLocal(e.global);
    applyLocalX(local.x);
  });
  const endDrag = () => {
    if (!dragging) return;
    dragging = false;
    drawThumb(false);
  };
  track.on('pointerup', endDrag);
  track.on('pointerupoutside', endDrag);

  track._updateThumb = updateThumb;
  return track;
}

// ── 1. DIEGETIC ILLUMINATED FOLIO HERO SIDE PANEL (10v10+ SCALABLE) ──

export function buildHeroSidePanel({
  character,
  side,
  charColor = null,
  catalogChar,
  catalogStatuses,
  x,
  y,
  width,
  height,
  tab = 'passives',
  canSetTarget = false,
  isDefaultTarget = false,
  scrollY = 0,
  onTab,
  onHoverSkill,
  onSetFocusTarget,
  onScrollChange,
  onClose,
}) {
  const root = new PIXI.Container();
  root.position.set(x, y);
  const actors = [];
  const theme = SIDE_THEME[side] || SIDE_THEME[1];
  const pal = actorPalette(character, side);
  const charAccent = parseHexColor(charColor, pal.primary);

  // Illuminated Parchment Folio Frame (engraved double-hairline + corner diamonds + top faction ribbon seal)
  const frame = new PIXI.Graphics();
  drawFolioFrame(frame, 0, 0, width, height, {
    accent: theme.accent,
    radius: 11,
    edgeDepth: 3.5,
    shadowAlpha: 0.25,
    cornerDiamonds: true,
    diamondColor: INK.gold,
  });
  // Engraved top faction ribbon bar
  frame.roundRect(14, 1.5, width - 28, 4, 2).fill({ color: theme.accent, alpha: 0.94 });
  frame.eventMode = 'static';
  frame.on('pointerdown', (e) => e.stopPropagation());
  frame.on('pointertap', (e) => e.stopPropagation());
  root.addChild(frame);

  let curY = 12;

  // Strictly Single-Character Folio: displays ONLY the clicked character (zero switcher for other characters!)
  // Hero Identity Medallion Header (compass-etched portrait + Name + Faction Ribbon + Live HP/Speed/Duels/Cost)
  const artSize = 56;
  const artX = 12;
  const artY = curY + 1;
  const artG = new PIXI.Graphics();
  artG.roundRect(artX, artY, artSize, artSize, 10)
    .fill({ color: pal.highlight })
    .stroke({ width: 1.3, color: pal.primary, alpha: 0.55 });
  artG.circle(artX + artSize / 2, artY + artSize / 2, 22)
    .stroke({ width: 0.85, color: INK.gold, alpha: 0.38 });
  artG.ellipse(artX + artSize / 2, artY + artSize - 9, artSize * 0.32, 4.5)
    .fill({ color: INK.paper, alpha: 0.82 });
  root.addChild(artG);

  const actor = createCharacterActor(character, side, { radius: 21 });
  actor.position.set(artX + artSize / 2, artY + artSize * 0.52);
  root.addChild(actor);
  actors.push({ actor, ch: character });

  const infoX = artX + artSize + 10;
  const infoW = width - infoX - 12;

  const nameTxt = new PIXI.Text({
    text: `${character.name}${character.alive ? '' : ' [亡]'}`,
    style: { fontFamily: FONT_UI, fontSize: 16.5, fontWeight: '900', fill: character.alive ? INK.strong : INK.muted },
  });
  nameTxt.position.set(infoX, curY);
  root.addChild(nameTxt);

  // Engraved Faction/Rank Ribbon Seal (top-right)
  const metaParts = [character.faction || '', RANK_LABEL[character.rank] || ''].filter(Boolean).join(' · ');
  if (metaParts) {
    const metaTxt = new PIXI.Text({
      text: metaParts,
      style: { fontFamily: FONT_UI, fontSize: 10.2, fontWeight: '800', fill: theme.accent },
    });
    const mw = Math.ceil(metaTxt.width) + 12;
    const mx = width - 12 - mw;
    const mG = new PIXI.Graphics();
    mG.roundRect(mx, curY + 2, mw, 17, 4)
      .fill({ color: theme.softBg })
      .stroke({ width: 0.9, color: theme.accent, alpha: 0.5 });
    root.addChild(mG);
    metaTxt.anchor.set(0.5);
    metaTxt.position.set(mx + mw / 2, curY + 10.5);
    root.addChild(metaTxt);
  }

  const hpY = curY + 24;
  const hpBarW = Math.max(80, infoW - 52);
  const ratio = Math.max(0, Math.min(1, (character.hp ?? 0) / Math.max(1, character.max_hp || 1)));
  const hpG = new PIXI.Graphics();
  hpG.roundRect(infoX, hpY, hpBarW, 10, 5).fill({ color: INK.paperTint }).stroke({ width: 0.85, color: INK.line });
  if (ratio > 0) {
    hpG.roundRect(infoX + 1, hpY + 1, Math.max(5, (hpBarW - 2) * ratio), 8, 4)
      .fill({ color: HP_BAR_COLOR });
  }
  root.addChild(hpG);

  const hpTxt = new PIXI.Text({
    text: `${character.hp}/${character.max_hp}`,
    style: { fontFamily: FONT_NUM, fontSize: 11.2, fontWeight: '900', fill: INK.strong },
  });
  hpTxt.anchor.set(1, 0.5);
  hpTxt.position.set(width - 12, hpY + 5);
  root.addChild(hpTxt);

  const subStats = new PIXI.Text({
    text: `速度 ${character.speed ?? 0}  ·  交锋 ${character.duels?.used ?? '?'}/${character.duels?.max ?? 1}  ·  个人费 ${character.cost?.available ?? 0}`,
    style: { fontFamily: FONT_UI, fontSize: 10.6, fontWeight: '800', fill: INK.secondary },
  });
  subStats.position.set(infoX, curY + 40);
  root.addChild(subStats);

  curY += artSize + 8;

  // Compact Active Shields / Status Chips Row (only if present)
  const sh = character.shields || {};
  const activeShields = ['normal', 'reinforced', 'concept'].filter((k) => (sh[k] || 0) > 0);
  const statuses = Object.entries(character.statuses || {});
  if (activeShields.length || statuses.length) {
    let bx = 12;
    const badgeG = new PIXI.Graphics();
    root.addChild(badgeG);
    for (const kind of activeShields) {
      const st = SHIELD_STYLE[kind];
      badgeG.roundRect(bx, curY, 44, 19, 4).fill({ color: st.bg }).stroke({ width: 1, color: st.color });
      drawShieldGlyph(badgeG, kind, bx + 9, curY + 9.5, 4.8);
      const t = new PIXI.Text({
        text: String(sh[kind]),
        style: { fontFamily: FONT_NUM, fontSize: 10.2, fontWeight: '900', fill: st.color },
      });
      t.anchor.set(0, 0.5);
      t.position.set(bx + 18, curY + 9.5);
      root.addChild(t);
      bx += 48;
    }
    for (const [sName, sVal] of statuses) {
      if (bx + 56 > width - 12) break;
      const col = getStatusColor(sName, INK.secondary);
      const burst = sName === '裂血' && character.bleed_burst;
      const stTxt = new PIXI.Text({
        text: `${sName}${sVal}`,
        style: { fontFamily: FONT_UI, fontSize: 10.4, fontWeight: '800', fill: col },
      });
      const bw = Math.ceil(stTxt.width) + 22;
      badgeG.roundRect(bx, curY, bw, 19, 4)
        .fill({ color: burst ? 0xfce0e4 : INK.paperSoft })
        .stroke({ width: burst ? 1.5 : 0.9, color: col });
      mountStatusIcon(root, badgeG, sName, bx + 9.5, curY + 9.5, 5.6, col, sVal);
      stTxt.anchor.set(0, 0.5);
      stTxt.position.set(bx + 17, curY + 9.5);
      root.addChild(stTxt);
      bx += bw + 4;
    }
    curY += 24;
  }

  // Engraved divider above tabs
  const divG = new PIXI.Graphics();
  drawDiamondDivider(divG, 14, width - 14, curY, INK.hairline, INK.gold);
  root.addChild(divG);
  curY += 7;

  // Tabs & Actions Row: [被动与状态] [技能牌组(N)] ... [集火] [✕]
  const skills = catalogChar?.skills || [];
  const tabH = 26;
  const t1 = makeSealButton('被动与状态', {
    width: 92, height: tabH, accent: theme.accent, solid: tab === 'passives', fontSize: 11.2, radius: 6,
    onClick: () => onTab && onTab('passives'),
  });
  t1.position.set(12, curY);
  root.addChild(t1);

  const t2 = makeSealButton(`技能牌组(${skills.length})`, {
    width: 96, height: tabH, accent: theme.accent, solid: tab === 'skills', fontSize: 11.2, radius: 6,
    onClick: () => onTab && onTab('skills'),
  });
  t2.position.set(110, curY);
  root.addChild(t2);

  let rx = width - 12;
  const closeBtn = makeSealButton('✕', {
    width: 28, height: tabH, accent: INK.secondary, fontSize: 11.5, radius: 6,
    onClick: onClose,
  });
  rx -= 28;
  closeBtn.position.set(rx, curY);
  root.addChild(closeBtn);

  if (canSetTarget && character.alive && onSetFocusTarget) {
    rx -= 68;
    const focusBtn = makeSealButton(isDefaultTarget ? '◎集火' : '设为集火', {
      width: 62, height: tabH, accent: INK.gold, solid: isDefaultTarget, fontSize: 10.4, radius: 6,
      onClick: onSetFocusTarget,
    });
    focusBtn.position.set(rx, curY);
    root.addChild(focusBtn);
  }
  curY += tabH + 8;

  // Scrollable Illuminated Vellum Reading Viewport (CONSTANT 12.4px font — NEVER shrinks, O(1) smooth scroll!)
  const vx = 11;
  const vy = curY;
  const vw = width - 22;
  const vh = Math.max(96, height - vy - 11);

  const vpBg = new PIXI.Graphics();
  vpBg.roundRect(vx, vy, vw, vh, 8)
    .fill({ color: INK.paperSoft, alpha: 0.72 })
    .stroke({ width: 0.9, color: INK.hairline });
  root.addChild(vpBg);

  const maskG = new PIXI.Graphics();
  maskG.rect(vx + 2, vy + 2, vw - 4, vh - 4).fill({ color: 0xffffff });
  root.addChild(maskG);

  const content = new PIXI.Container();
  content.position.set(vx, vy);
  content.mask = maskG;
  root.addChild(content);

  const padIn = 10;
  const innerW = vw - padIn * 2 - 9;
  let cy = padIn;

  if (tab === 'skills') {
    for (const sk of skills) {
      const row = buildUnifiedSkillRow(sk, { width: innerW, side, accentColor: charAccent, active: false });
      row.position.set(padIn, cy);
      row._itemTop = cy;
      row._itemBottom = cy + row._height;
      row._interactiveItem = true;
      row.eventMode = 'static';
      row.cursor = 'pointer';
      row.on('pointerover', (e) => {
        if (!pointerInsideLocalRect(root, e.global, vx, vy, vw, vh)) return;
        if (onHoverSkill) {
          const gp = row.getGlobalPosition();
          const anchorX = side === 1 ? x + width + 122 : x - 122;
          onHoverSkill(sk, anchorX, gp.y + row._height / 2);
        }
      });
      row.on('pointerout', () => {
        if (onHoverSkill) onHoverSkill(null);
      });
      content.addChild(row);
      cy += row._height + 7;
    }
  } else {
    const factionPassives = catalogChar?.faction_passives || [];
    const rolePassives = catalogChar?.passives || [];

    for (const fp of factionPassives) {
      const plate = buildUnifiedEntryPlate({
        variant: 'passive',
        title: fp.name || '阵营被动',
        tagLabel: '阵营被动',
        entries: fp.display_lines,
        width: innerW,
        accentColor: theme.accent,
        fontSize: 12.4,
        lineHeight: 19.2,
      });
      plate.position.set(padIn, cy);
      plate._itemTop = cy;
      plate._itemBottom = cy + plate._height;
      content.addChild(plate);
      cy += plate._height + 8;
    }

    for (const p of rolePassives) {
      const plate = buildUnifiedEntryPlate({
        variant: 'passive',
        title: p.name || '角色被动',
        tagLabel: String(character.passive_values?.[p.name] ?? ''),
        entries: p.display_lines,
        width: innerW,
        accentColor: INK.gold,
        fontSize: 12.4,
        lineHeight: 19.2,
      });
      plate.position.set(padIn, cy);
      plate._itemTop = cy;
      plate._itemBottom = cy + plate._height;
      content.addChild(plate);
      cy += plate._height + 8;
    }

    if (statuses.length) {
      if (cy > padIn) cy += 4;
      const stHead = new PIXI.Text({
        text: '当前状态规则',
        style: { fontFamily: FONT_UI, fontSize: 12.2, fontWeight: '800', fill: INK.secondary },
      });
      stHead.position.set(padIn, cy);
      stHead._itemTop = cy;
      stHead._itemBottom = cy + 20;
      content.addChild(stHead);
      cy += 22;

      for (const [sName, sVal] of statuses) {
        const burst = sName === '裂血' && character.bleed_burst;
        const ruleList = catalogStatuses?.[sName];
        const ruleText = (ruleList && ruleList.length ? ruleList.join('\n') : OFFICIAL_STATUS_RULES[sName]) || '';
        const plate = buildUnifiedEntryPlate({
          variant: 'status',
          statusName: sName,
          statusValue: sVal,
          statusBurst: burst,
          entries: ruleText ? [ruleText] : [],
          width: innerW,
          fontSize: 12.2,
          lineHeight: 18.8,
        });
        plate.position.set(padIn, cy);
        plate._itemTop = cy;
        plate._itemBottom = cy + plate._height;
        content.addChild(plate);
        cy += plate._height + 7;
      }
    }

    if (!factionPassives.length && !rolePassives.length && !statuses.length) {
      const empty = new PIXI.Text({
        text: '当前角色无被动技能与生效状态。',
        style: { fontFamily: FONT_UI, fontSize: 12.5, fill: INK.muted },
      });
      empty.position.set(padIn, cy + 8);
      content.addChild(empty);
      cy += 34;
    }
  }

  const totalH = cy + padIn;
  const maxScroll = Math.max(0, totalH - vh);
  let curScroll = Math.max(0, Math.min(maxScroll, scrollY));

  let sb = null;
  const applyScroll = (nextY, emit = true) => {
    curScroll = Math.max(0, Math.min(maxScroll, nextY));
    content.y = vy - curScroll;
    cullVerticalItems(content, curScroll, vh);
    if (sb) sb._updateThumb(curScroll);
    if (emit && onScrollChange) onScrollChange(curScroll);
    return curScroll;
  };
  applyScroll(curScroll, false);

  if (maxScroll > 0) {
    sb = makeSmoothScrollbar({
      x: vx + vw - 8,
      y: vy + 6,
      height: vh - 12,
      totalH,
      viewH: vh,
      scrollY: curScroll,
      accentColor: theme.accent,
      onChange: (val) => applyScroll(val, true),
    });
    root.addChild(sb);
  }

  root._actors = actors;
  root._maxScroll = maxScroll;
  root._rect = { x, y, w: width, h: height };
  root.setScroll = (nextY) => applyScroll(nextY, true);
  return root;
}

// ── 2. ILLUMINATED DUAL-FOLIO PASSIVE DRAWER (INDEPENDENT P1/P2 O(1) SCROLL, 10v10+ READY) ──

export function buildPassiveDrawer({
  x,
  y,
  width,
  maxHeight,
  players = [],
  catalogById = new Map(),
  scrollY1 = 0,
  scrollY2 = 0,
  onOpenHeroSheet,
  onScrollChange,
  onClose,
  hideSpeed = false,
}) {
  const root = new PIXI.Container();
  root.position.set(x, y);

  const padX = 18;
  const colGap = 28;
  const colW = Math.floor((width - padX * 2 - colGap) / 2);
  const innerColW = colW - 13;
  const headerH = 42;
  const splitX = x + padX + colW + colGap / 2;

  const builtCols = {};
  let maxColH = 0;

  [1, 2].forEach((side, colIdx) => {
    const player = players.find((p) => p.side === side);
    const theme = SIDE_THEME[side] || SIDE_THEME[1];
    const colX = padX + colIdx * (colW + colGap);
    const colContainer = new PIXI.Container();
    let cy = 6;

    if (player) {
      const chars = player.characters || [];
      const aliveCount = chars.filter((c) => c.alive).length;

      // Illuminated Faction Column Header Ribbon
      const headPlate = new PIXI.Container();
      headPlate.position.set(0, cy);
      const hpG = new PIXI.Graphics();
      hpG.roundRect(0, 0, innerColW, 28, 6)
        .fill({ color: theme.softBg })
        .stroke({ width: 1, color: theme.accent, alpha: 0.55 });
      hpG.roundRect(0, 3, 4, 22, 2).fill({ color: theme.accent });
      headPlate.addChild(hpG);

      const speedText = hideSpeed ? '—' : Number(player.speed || 0).toFixed(player.speed % 1 ? 1 : 0);
      const sTxt = new PIXI.Text({
        text: `${player.name}  ·  ${aliveCount}/${chars.length}人  ·  速 ${speedText}  ·  费 ${player.cost?.available ?? 0}`,
        style: { fontFamily: FONT_UI, fontSize: 12.2, fontWeight: '900', fill: theme.accent },
      });
      sTxt.anchor.set(0, 0.5);
      sTxt.position.set(12, 14);
      headPlate.addChild(sTxt);
      headPlate._itemTop = cy;
      headPlate._itemBottom = cy + 28;
      colContainer.addChild(headPlate);
      cy += 34;

      // Deduplicated Faction Passives across unlimited squad sizes (10v10+ safe)
      const seenFaction = new Set();
      for (const ch of chars) {
        const cat = catalogById.get(ch.id);
        for (const fp of cat?.faction_passives || []) {
          const key = fp.name || fp.display_lines.join('|');
          if (seenFaction.has(key)) continue;
          seenFaction.add(key);
          const plate = buildUnifiedEntryPlate({
            variant: 'passive',
            title: fp.name || '阵营被动',
            tagLabel: '阵营被动',
            entries: fp.display_lines,
            width: innerColW,
            accentColor: theme.accent,
            fontSize: 12.2,
            lineHeight: 18.8,
          });
          plate.position.set(0, cy);
          plate._itemTop = cy;
          plate._itemBottom = cy + plate._height;
          colContainer.addChild(plate);
          cy += plate._height + 7;
        }
      }

      // Per-Character Block
      for (const ch of chars) {
        const cat = catalogById.get(ch.id);
        const pal = actorPalette(ch, side);
        const rolePassives = cat?.passives || [];

        const rowHead = new PIXI.Container();
        rowHead.position.set(0, cy);
        const rhH = 28;
        const rhG = new PIXI.Graphics();
        const drawRh = (hov) => {
          rhG.clear();
          rhG.roundRect(0, 0, innerColW, rhH, 6)
            .fill({ color: hov ? theme.warmTint : INK.paperSoft })
            .stroke({ width: hov ? 1.4 : 0.9, color: hov ? theme.accent : INK.hairline });
          // Diamond crest dot in character palette
          rhG.poly([13, rhH / 2 - 5.5, 18.5, rhH / 2, 13, rhH / 2 + 5.5, 7.5, rhH / 2]).fill({ color: pal.primary });
        };
        drawRh(false);
        rowHead.addChild(rhG);

        const stSummary = Object.entries(ch.statuses || {}).map(([n, v]) => `${n}${v}`).join(' ');
        const chTxt = new PIXI.Text({
          text: `${ch.name}${ch.alive ? '' : ' [亡]'} · 生命 ${ch.hp}/${ch.max_hp}${stSummary ? ' · ' + stSummary : ''}`,
          style: { fontFamily: FONT_UI, fontSize: 12.2, fontWeight: '800', fill: ch.alive ? INK.strong : INK.muted },
        });
        chTxt.anchor.set(0, 0.5);
        chTxt.position.set(25, rhH / 2);
        rowHead.addChild(chTxt);

        const openLink = new PIXI.Text({
          text: '查档 ↗',
          style: { fontFamily: FONT_UI, fontSize: 10.8, fontWeight: '800', fill: theme.accent },
        });
        openLink.anchor.set(1, 0.5);
        openLink.position.set(innerColW - 10, rhH / 2);
        rowHead.addChild(openLink);

        rowHead._itemTop = cy;
        rowHead._itemBottom = cy + rhH;
        rowHead._interactiveItem = true;
        rowHead.eventMode = 'static';
        rowHead.hitArea = new PIXI.Rectangle(0, 0, innerColW, rhH);
        rowHead.cursor = 'pointer';
        rowHead.on('pointerover', () => drawRh(true));
        rowHead.on('pointerout', () => drawRh(false));
        rowHead.on('pointerdown', (e) => e.stopPropagation());
        rowHead.on('pointertap', (e) => {
          e.stopPropagation();
          if (onOpenHeroSheet) onOpenHeroSheet(ch.id, side);
        });
        colContainer.addChild(rowHead);
        cy += rhH + 6;

        for (const p of rolePassives) {
          const plate = buildUnifiedEntryPlate({
            variant: 'passive',
            title: p.name || '角色被动',
            tagLabel: String(ch.passive_values?.[p.name] ?? ''),
            entries: p.display_lines,
            width: innerColW - 6,
            accentColor: INK.gold,
            fontSize: 12.2,
            lineHeight: 18.8,
          });
          plate.position.set(6, cy);
          plate._itemTop = cy;
          plate._itemBottom = cy + plate._height;
          colContainer.addChild(plate);
          cy += plate._height + 6;
        }
        cy += 6;
      }
    }

    builtCols[side] = { colContainer, colX, totalH: cy + 8, theme };
    maxColH = Math.max(maxColH, cy);
  });

  const drawerH = Math.min(maxHeight, Math.max(170, headerH + maxColH + 16));
  const vh = drawerH - headerH - 12;

  const frame = new PIXI.Graphics();
  drawFolioFrame(frame, 0, 0, width, drawerH, {
    accent: INK.gold,
    radius: 13,
    edgeDepth: 4,
    shadowAlpha: 0.28,
    topRibbonH: headerH - 2,
    ribbonFill: INK.paperSoft,
    cornerDiamonds: true,
    diamondColor: INK.gold,
  });
  frame.eventMode = 'static';
  frame.on('pointerdown', (e) => e.stopPropagation());
  frame.on('pointertap', (e) => e.stopPropagation());
  root.addChild(frame);

  // Ceremonial Folio Crest Title (ZERO web-tutorial hint filler!)
  const crestG = new PIXI.Graphics();
  drawLightStar(crestG, 26, headerH / 2, 7.5, INK.gold, 0.92);
  root.addChild(crestG);

  const title = new PIXI.Text({
    text: '双方被动典录',
    style: { fontFamily: FONT_UI, fontSize: 14.5, fontWeight: '900', fill: INK.strong, letterSpacing: 1 },
  });
  title.anchor.set(0, 0.5);
  title.position.set(40, headerH / 2);
  root.addChild(title);

  const closeBtn = makeSealButton('✕', {
    width: 30, height: 26, accent: INK.secondary, fontSize: 12, radius: 7, onClick: onClose,
  });
  closeBtn.position.set(width - 44, (headerH - 26) / 2);
  root.addChild(closeBtn);

  // Center Book-Spine Divider with Engraved Diamonds
  const spineX = padX + colW + colGap / 2;
  const div = new PIXI.Graphics();
  div.rect(spineX - 5, headerH + 4, 10, drawerH - headerH - 12).fill({ color: INK.paperTint, alpha: 0.55 });
  div.moveTo(spineX, headerH + 8).lineTo(spineX, drawerH - 12).stroke({ width: 1.1, color: INK.line });
  div.poly([spineX, headerH + 12, spineX + 3.2, headerH + 16, spineX, headerH + 20, spineX - 3.2, headerH + 16])
    .fill({ color: INK.gold, alpha: 0.85 });
  div.poly([spineX, drawerH - 22, spineX + 3.2, drawerH - 18, spineX, drawerH - 14, spineX - 3.2, drawerH - 18])
    .fill({ color: INK.gold, alpha: 0.85 });
  root.addChild(div);

  // Independent Left (P1) & Right (P2) Masked Scroll Columns + Draggable Scrollbars
  const baseY = headerH + 6;
  const colControllers = {};
  const maxScrollBySide = { 1: 0, 2: 0 };

  for (const side of [1, 2]) {
    const info = builtCols[side];
    const maxS = Math.max(0, info.totalH - vh);
    maxScrollBySide[side] = maxS;
    let curS = Math.max(0, Math.min(maxS, side === 1 ? scrollY1 : scrollY2));

    const maskG = new PIXI.Graphics();
    maskG.rect(info.colX - 2, headerH + 4, innerColW + 4, vh).fill({ color: 0xffffff });
    root.addChild(maskG);

    info.colContainer.position.set(info.colX, baseY - curS);
    info.colContainer.mask = maskG;
    root.addChild(info.colContainer);

    let sb = null;
    const setSideScroll = (nextY, emit = true) => {
      curS = Math.max(0, Math.min(maxS, nextY));
      info.colContainer.y = baseY - curS;
      cullVerticalItems(info.colContainer, curS, vh);
      if (sb) sb._updateThumb(curS);
      if (emit && onScrollChange) onScrollChange(side, curS);
      return curS;
    };
    setSideScroll(curS, false);

    if (maxS > 0) {
      sb = makeSmoothScrollbar({
        x: info.colX + innerColW + 4,
        y: headerH + 6,
        height: vh - 6,
        totalH: info.totalH,
        viewH: vh,
        scrollY: curS,
        accentColor: info.theme.accent,
        onChange: (val) => setSideScroll(val, true),
      });
      root.addChild(sb);
    }

    colControllers[side] = { setScroll: (val) => setSideScroll(val, true), getScroll: () => curS, maxScroll: maxS };
  }

  root._maxScrollBySide = maxScrollBySide;
  root._splitX = splitX;
  root._rect = { x, y, w: width, h: drawerH };
  root.setSideScroll = (side, nextY) => colControllers[side]?.setScroll(nextY);
  return root;
}

// ── 3. CEREMONIAL TABLETOP SEAT-PASS CURTAIN (HANDOFF OVERLAY) ──

export function buildHandoffOverlay(w, h, { activeSide, eligibleSides, onReady }) {
  const root = new PIXI.Container();
  const side = activeSide || (eligibleSides && eligibleSides[0]) || 1;
  const theme = SIDE_THEME[side] || SIDE_THEME[1];
  const seats = eligibleSides && eligibleSides.length > 1 ? eligibleSides : [side];
  const cx = w / 2;
  const cy = h / 2;

  // Layered warm-linen ceremonial curtain + subtle inset parchment border
  const veil = new PIXI.Graphics();
  veil.rect(0, 0, w, h).fill({ color: 0xf4efe4, alpha: 0.965 });
  // Outer ceremonial linen mat frame
  const matPad = Math.min(28, Math.floor(Math.min(w, h) * 0.035));
  veil.roundRect(matPad, matPad, w - matPad * 2, h - matPad * 2, 16)
    .stroke({ width: 1.4, color: INK.line, alpha: 0.85 });
  veil.roundRect(matPad + 6, matPad + 6, w - (matPad + 6) * 2, h - (matPad + 6) * 2, 12)
    .stroke({ width: 0.85, color: theme.border, alpha: 0.4 });
  drawCornerDiamonds(veil, matPad, matPad, w - matPad * 2, h - matPad * 2, 14, 4, INK.gold, 0.65);

  // Subtle horizontal heraldic tapestry sash behind banner
  veil.rect(matPad + 8, cy - 38, w - (matPad + 8) * 2, 76).fill({ color: theme.warmTint, alpha: 0.72 });
  veil.moveTo(matPad + 16, cy - 38).lineTo(w - matPad - 16, cy - 38).stroke({ width: 1, color: theme.border, alpha: 0.45 });
  veil.moveTo(matPad + 16, cy + 38).lineTo(w - matPad - 16, cy + 38).stroke({ width: 1, color: theme.border, alpha: 0.45 });
  veil.eventMode = 'static';
  root.addChild(veil);

  // Central Heraldic Banner Plaque
  const plaqueW = Math.min(w - 84, Math.max(430, seats.length * 196 + 88));
  const plaqueH = 314;
  const px = cx - plaqueW / 2;
  const py = cy - plaqueH / 2;

  const plaque = new PIXI.Graphics();
  // Top & bottom heraldic pennant tabs
  plaque.poly([cx - 72, py, cx + 72, py, cx + 56, py - 14, cx - 56, py - 14])
    .fill({ color: theme.accent, alpha: 0.9 });
  plaque.poly([cx - 56, py + plaqueH + 4, cx + 56, py + plaqueH + 4, cx + 40, py + plaqueH + 16, cx - 40, py + plaqueH + 16])
    .fill({ color: INK.gold, alpha: 0.82 });

  drawFolioFrame(plaque, px, py, plaqueW, plaqueH, {
    accent: theme.accent,
    bg: INK.paper,
    radius: 15,
    edgeDepth: 5,
    shadowAlpha: 0.3,
    cornerDiamonds: true,
    diamondColor: INK.gold,
  });

  // Geometric Compass Emblem + Faction Seal Crest
  const crestY = py + 84;
  drawHeraldicCompass(plaque, cx, crestY, 54, theme.accent, INK.line);
  drawWaxSealBadge(plaque, cx, crestY, 27, theme.softBg, theme.accent);
  drawLightStar(plaque, cx, crestY, 21, theme.accent, 0.95);

  // Engraved diamond rules flanking seat title
  drawDiamondDivider(plaque, px + 36, px + plaqueW - 36, py + 150, INK.hairline, INK.gold);
  root.addChild(plaque);

  const head = new PIXI.Text({
    text: seats.length > 1 ? '席位交接' : theme.name,
    style: { fontFamily: FONT_UI, fontSize: 30, fontWeight: '900', fill: INK.strong, letterSpacing: 4 },
  });
  head.anchor.set(0.5);
  head.position.set(cx, py + 184);
  root.addChild(head);

  // Bold Wax-Seal Entry Button(s)
  const btnW = 184;
  const gap = 22;
  const totalW = seats.length * btnW + (seats.length - 1) * gap;
  seats.forEach((s, idx) => {
    const st = SIDE_THEME[s] || SIDE_THEME[1];
    const btn = makeSealButton(`${st.name} 接手`, {
      width: btnW,
      height: 48,
      accent: st.accent,
      solid: true,
      fontSize: 15.5,
      radius: 12,
      onClick: () => onReady(s),
    });
    btn.position.set(cx - totalW / 2 + idx * (btnW + gap), py + 232);
    root.addChild(btn);
  });

  return root;
}

// ── 4. SCALABLE TABLETOP OPENING DEAL (3 TO 12+ CANDIDATE CARDS) ──

export function buildDrawSelectOverlay(w, h, {
  prompt,
  chooseKeep = false,
  selectedIds,
  characterColors = {},
  scrollX = 0,
  onToggle,
  onConfirm,
  onHoverCard = null,
  onScrollChange = null,
}) {
  const root = new PIXI.Container();
  const theme = SIDE_THEME[prompt.side] || SIDE_THEME[1];
  const cx = w / 2;

  // Warm sunlit tabletop backdrop + subtle engraved border
  const veil = new PIXI.Graphics();
  veil.rect(0, 0, w, h).fill({ color: 0xf5f1e7, alpha: 0.97 });
  veil.roundRect(16, 16, w - 32, h - 32, 14).stroke({ width: 1.1, color: INK.line, alpha: 0.7 });
  drawCornerDiamonds(veil, 16, 16, w - 32, h - 32, 12, 3.5, INK.gold, 0.65);
  veil.eventMode = 'static';
  root.addChild(veil);

  // Heraldic Deal Header Ribbon + Selection Progress Pips
  const selectionCount = chooseKeep ? prompt.keep : prompt.discard_count;
  const pickedCount = selectedIds.size;
  const ribbonW = Math.min(520, w - 72);
  const ribbonH = 54;
  const ribbonX = cx - ribbonW / 2;
  const ribbonY = 24;

  const headG = new PIXI.Graphics();
  drawFolioFrame(headG, ribbonX, ribbonY, ribbonW, ribbonH, {
    accent: theme.accent,
    bg: INK.paper,
    radius: 11,
    edgeDepth: 3,
    shadowAlpha: 0.2,
    cornerDiamonds: true,
    diamondColor: INK.gold,
  });
  root.addChild(headG);

  const title = new PIXI.Text({
    text: `${theme.name} · 选 ${selectionCount} 张${chooseKeep ? '保留' : '置底'}`,
    style: { fontFamily: FONT_UI, fontSize: 18, fontWeight: '900', fill: theme.accent, letterSpacing: 1 },
  });
  title.anchor.set(0.5);
  title.position.set(cx, ribbonY + 20);
  root.addChild(title);

  // Visual Wax-Pip Progress Counter
  const pipCount = Math.min(12, Math.max(1, selectionCount));
  const pipG = new PIXI.Graphics();
  const pipGap = 15;
  const pipsTotalW = (pipCount - 1) * pipGap;
  for (let i = 0; i < pipCount; i++) {
    const filled = i < pickedCount;
    const px = cx - pipsTotalW / 2 + i * pipGap;
    const py = ribbonY + 41;
    pipG.poly([px, py - 4.5, px + 4.5, py, px, py + 4.5, px - 4.5, py])
      .fill({ color: filled ? 0xc8452e : INK.paperTint })
      .stroke({ width: 1.1, color: filled ? 0xc8452e : INK.muted });
  }
  root.addChild(pipG);

  const countTxt = new PIXI.Text({
    text: `${pickedCount}/${selectionCount}`,
    style: { fontFamily: FONT_NUM, fontSize: 11.5, fontWeight: '900', fill: pickedCount === selectionCount ? 0x1a825e : INK.secondary },
  });
  countTxt.anchor.set(0, 0.5);
  countTxt.position.set(cx + pipsTotalW / 2 + 14, ribbonY + 41);
  root.addChild(countTxt);

  // Card Deck Layout Engine:
  // Strict portrait 1 : 1.40 cards.
  // - <=5 cards: centered tabletop row
  // - 6..10 cards: 2 centered rows if viewport height comfortably fits; else O(1) horizontal smooth-scroll deal rail!
  // - >10 cards: O(1) horizontal smooth-scroll deal rail with draggable scrollbar & step arrows!
  const candidates = prompt.candidates || [];
  const count = Math.max(1, candidates.length);
  const topArea = ribbonY + ribbonH + 18;
  const footArea = 82;
  const availH = Math.max(260, h - topArea - footArea);
  const availW = Math.max(320, w - 72);

  const buildCandidateHolder = (card, cardW, portraitH) => {
    const isMarked = selectedIds.has(card.action_key || card.id);
    const isKept = chooseKeep ? isMarked : !isMarked;
    const spr = buildFullCard(card, {
      side: prompt.side,
      accentColor: characterColors[card.character_id] || null,
      ownerName: card.character_name || '',
      showOwner: true,
      width: cardW,
      fixedHeight: portraitH,
      dense: true,
      centered: false,
      legal: true,
      selected: isMarked,
    });
    const holder = new PIXI.Container();
    holder.addChild(spr);

    const ch = spr._boxHeight;
    // Bold Tactile Wax-Seal 置底 / 保留 Stamp
    const stampG = new PIXI.Graphics();
    const stampW = 104;
    const stampH = 28;
    const sx = cardW / 2 - stampW / 2;
    const sy = ch + 9;
    const stampCol = isKept ? 0x1a825e : 0xc8452e;
    stampG.roundRect(sx + 1, sy + 2.5, stampW, stampH, 14).fill({ color: INK.shadow, alpha: 0.25 });
    stampG.roundRect(sx, sy, stampW, stampH, 14)
      .fill({ color: isMarked ? stampCol : INK.paper })
      .stroke({ width: 1.6, color: stampCol });
    drawWaxSealBadge(stampG, sx + 15, sy + stampH / 2, 8.5, stampCol, INK.paper);
    holder.addChild(stampG);

    const bTxt = new PIXI.Text({
      text: isKept ? '保留' : '置底',
      style: { fontFamily: FONT_UI, fontSize: 12.2, fontWeight: '900', fill: isMarked ? INK.paper : stampCol, letterSpacing: 1 },
    });
    bTxt.anchor.set(0.5);
    bTxt.position.set(cardW / 2 + 8, sy + stampH / 2);
    holder.addChild(bTxt);

    // Subtle red seal watermark on card corner when marked 置底
    if (isMarked) {
      const markG = new PIXI.Graphics();
      drawWaxSealBadge(markG, cardW - 18, 18, 12, stampCol, INK.paper);
      holder.addChild(markG);
      const mTxt = new PIXI.Text({
        text: isKept ? '留' : '底',
        style: { fontFamily: FONT_UI, fontSize: 10.5, fontWeight: '900', fill: INK.paper },
      });
      mTxt.anchor.set(0.5);
      mTxt.position.set(cardW - 18, 18);
      holder.addChild(mTxt);
    }

    holder._totalH = ch + stampH + 14;
    holder._isMarked = isMarked;
    holder._card = card;
    holder._spr = spr;
    return holder;
  };

  let maxScrollX = 0;
  let setScrollX = () => 0;

  // Decide between single centered row (<=5), 2 centered rows (6..10 when height allows), or horizontal scroll rail
  const twoRowCardW = Math.max(176, Math.min(204, Math.floor((availW - 14 * (Math.ceil(count / 2) - 1)) / Math.ceil(count / 2))));
  const twoRowPortraitH = Math.round(twoRowCardW * 1.40);
  const canFitTwoRows = count > 5 && count <= 10 && (twoRowPortraitH + 48) * 2 + 14 <= availH;

  if (count <= 5 && availW >= count * 188 + (count - 1) * 18) {
    const gap = 18;
    const cardW = Math.max(188, Math.min(214, Math.floor((availW - gap * (count - 1)) / count)));
    const portraitH = Math.round(cardW * 1.40);
    const holders = candidates.map((card) => buildCandidateHolder(card, cardW, portraitH));
    const maxH = holders.reduce((m, item) => Math.max(m, item._totalH), portraitH + 40);
    const totalW = count * cardW + (count - 1) * gap;
    const startX = cx - totalW / 2;
    const baseTop = topArea + Math.max(0, (availH - maxH) / 2);

    holders.forEach((holder, i) => {
      holder.position.set(startX + i * (cardW + gap), baseTop + (holder._isMarked ? 12 : 0));
      holder.eventMode = 'static';
      holder.cursor = 'pointer';
      holder.on('pointertap', (e) => {
        e.stopPropagation();
        onToggle(holder._card.action_key || holder._card.id);
      });
      if (onHoverCard) {
        holder.on('pointerover', () => {
          const gp = holder.getGlobalPosition();
          onHoverCard(holder._card, prompt.side, holder._card.character_name || '', gp.x + cardW / 2, gp.y + portraitH / 2, portraitH, holder._spr);
        });
        holder.on('pointerout', () => onHoverCard(null));
      }
      root.addChild(holder);
    });
  } else if (canFitTwoRows) {
    const gapX = 14;
    const gapY = 14;
    const topCount = Math.ceil(count / 2);
    const cardW = twoRowCardW;
    const portraitH = twoRowPortraitH;
    const holders = candidates.map((card) => buildCandidateHolder(card, cardW, portraitH));
    const row1 = holders.slice(0, topCount);
    const row2 = holders.slice(topCount);
    const r1H = row1.reduce((m, item) => Math.max(m, item._totalH), portraitH + 40);
    const r2H = row2.reduce((m, item) => Math.max(m, item._totalH), portraitH + 40);
    const blockH = r1H + gapY + r2H;
    const startY = topArea + Math.max(0, (availH - blockH) / 2);

    [row1, row2].forEach((rowItems, rIdx) => {
      const rowW = rowItems.length * cardW + Math.max(0, rowItems.length - 1) * gapX;
      const startX = cx - rowW / 2;
      const rowY = rIdx === 0 ? startY : startY + r1H + gapY;
      rowItems.forEach((holder, i) => {
        holder.position.set(startX + i * (cardW + gapX), rowY + (holder._isMarked ? 8 : 0));
        holder.eventMode = 'static';
        holder.cursor = 'pointer';
        holder.on('pointertap', (e) => {
          e.stopPropagation();
          onToggle(holder._card.action_key || holder._card.id);
        });
        if (onHoverCard) {
          holder.on('pointerover', () => {
            const gp = holder.getGlobalPosition();
            onHoverCard(holder._card, prompt.side, holder._card.character_name || '', gp.x + cardW / 2, gp.y + portraitH / 2, portraitH, holder._spr);
          });
          holder.on('pointerout', () => onHoverCard(null));
        }
        root.addChild(holder);
      });
    });
  } else {
    // True O(1) Horizontal Smooth Scroll Rail for 6..12+ cards on any viewport!
    const navW = 36;
    const railX = 28 + navW + 10;
    const railW = Math.max(240, w - (28 + navW + 10) * 2);
    const gap = 16;
    const cardW = Math.max(182, Math.min(204, Math.floor((availH - 72) / 1.40)));
    const portraitH = Math.round(cardW * 1.40);
    const railH = Math.min(availH - 22, portraitH + 64);
    const railY = topArea + Math.max(0, (availH - 22 - railH) / 2);

    const railBg = new PIXI.Graphics();
    railBg.roundRect(railX - 6, railY - 6, railW + 12, railH + 12, 12)
      .fill({ color: INK.paperSoft, alpha: 0.6 })
      .stroke({ width: 1, color: INK.hairline });
    root.addChild(railBg);

    const maskG = new PIXI.Graphics();
    maskG.rect(railX, railY - 4, railW, railH + 8).fill({ color: 0xffffff });
    root.addChild(maskG);

    const strip = new PIXI.Container();
    strip.mask = maskG;
    root.addChild(strip);

    const stepWidth = cardW + gap;
    const mounted = new Map();
    const mount = (index) => {
      const holder = buildCandidateHolder(candidates[index], cardW, portraitH);
      const cxPos = 6 + index * stepWidth;
      holder.position.set(cxPos, railY + 4 + (holder._isMarked ? 12 : 0));
      holder._itemLeft = cxPos;
      holder._itemRight = cxPos + cardW;
      holder._interactiveItem = true;
      holder.eventMode = 'static';
      holder.cursor = 'pointer';
      holder.on('pointertap', (e) => {
        if (!pointerInsideLocalRect(root, e.global, railX, railY - 4, railW, railH + 8)) return;
        e.stopPropagation();
        onToggle(holder._card.action_key || holder._card.id);
      });
      if (onHoverCard) {
        holder.on('pointerover', (e) => {
          if (!pointerInsideLocalRect(root, e.global, railX, railY - 4, railW, railH + 8)) return;
          const gp = holder.getGlobalPosition();
          onHoverCard(holder._card, prompt.side, holder._card.character_name || '', gp.x + cardW / 2, gp.y + portraitH / 2, portraitH, holder._spr);
        });
        holder.on('pointerout', () => onHoverCard(null));
      }
      strip.addChild(holder);
      mounted.set(index, holder);
    };

    const totalW = Math.max(0, candidates.length * stepWidth - gap + 12);
    maxScrollX = Math.max(0, totalW - railW);
    let curScrollX = Math.max(0, Math.min(maxScrollX, scrollX));
    let hSb = null;

    const applyX = (nextX, emit = true) => {
      curScrollX = Math.max(0, Math.min(maxScrollX, nextX));
      strip.x = railX - curScrollX;
      const first = Math.max(0, Math.floor(curScrollX / stepWidth) - 1);
      const end = Math.min(candidates.length, Math.ceil((curScrollX + railW) / stepWidth) + 1);
      for (const [index, holder] of mounted) {
        if (index >= first && index < end) continue;
        strip.removeChild(holder);
        holder.destroy({ children: true });
        mounted.delete(index);
      }
      for (let index = first; index < end; index++) if (!mounted.has(index)) mount(index);
      if (hSb) hSb._updateThumb(curScrollX);
      if (emit && onScrollChange) onScrollChange(curScrollX);
      return curScrollX;
    };
    setScrollX = (nextX) => applyX(nextX, true);
    applyX(curScrollX, false);

    if (maxScrollX > 0) {
      hSb = makeHorizontalScrollbar({
        x: railX,
        y: railY + railH + 14,
        width: railW,
        totalW,
        viewW: railW,
        scrollX: curScrollX,
        accentColor: theme.accent,
        onChange: (val) => applyX(val, true),
      });
      root.addChild(hSb);

      const step = Math.max(cardW + gap, Math.floor(railW * 0.65));
      const leftBtn = makeSealButton('‹', {
        width: navW, height: 64, accent: theme.accent, fontSize: 22, radius: 10,
        onClick: () => applyX(curScrollX - step, true),
      });
      leftBtn.position.set(28, railY + railH / 2 - 32);

      const rightBtn = makeSealButton('›', {
        width: navW, height: 64, accent: theme.accent, fontSize: 22, radius: 10,
        onClick: () => applyX(curScrollX + step, true),
      });
      rightBtn.position.set(w - 28 - navW, railY + railH / 2 - 32);
      root.addChild(leftBtn, rightBtn);
    }
  }

  const ready = pickedCount === selectionCount;
  const btn = makeSealButton(chooseKeep ? '确认保留' : '确认置底', {
    width: 184, height: 44, accent: ready ? theme.accent : INK.muted, solid: ready, disabled: !ready, fontSize: 15, radius: 11,
    onClick: () => onConfirm(),
  });
  btn.position.set(cx - 92, h - 62);
  root.addChild(btn);

  root._maxScrollX = maxScrollX;
  root.setScrollX = setScrollX;
  root.setScroll = setScrollX;
  return root;
}

// ── 5. TACTICAL INTERRUPT SEAL PANEL (SPECIAL OVERLAY) ──

const SPECIAL_KIND_STYLE = {
  replace:   { label: '换卡', color: 0x1a8775, wash: 0xedf8f5 },
  attack:    { label: '进攻', color: 0xcf4932, wash: 0xfdf1ee },
  intercept: { label: '迎击', color: 0x1c8a64, wash: 0xeef7f3 },
  pass_intercept: { label: '放行', color: INK.secondary, wash: INK.paperSoft },
  place:     { label: '置卡', color: 0x1a8775, wash: 0xedf8f5 },
  ability:   { label: '能力', color: INK.gold, wash: INK.goldBg },
  custom:    { label: '打出', color: INK.gold, wash: INK.goldBg },
  special:   { label: '特殊', color: INK.gold, wash: INK.goldBg },
};

const DUEL_LABEL = { regular: '常规交锋', pre_reveal: '开牌前交锋', instant: '即时交锋' };

function choiceText(value, size, color, width, bold = false) {
  return new PIXI.Text({
    text: value,
    style: {
      fontFamily: FONT_UI, fontSize: size, fill: color, fontWeight: bold ? '800' : '500',
      wordWrap: true, breakWords: true, wordWrapWidth: Math.max(40, width), lineHeight: size + 4,
    },
  });
}

// A public handoff has no options. Once the seat takes control, board targets
// and the tray use the same option index and the same confirmation button.
export function buildEffectChoice(w, h, {
  side, choice, options, hand = [], colors = {}, owners = {}, safeTop = 64, onReady, onPick, onInspect, onSelectionChange,
}) {
  const root = new PIXI.Container();
  const chooseOnBoard = !onReady && choice.selection !== 'hand';
  root.eventMode = chooseOnBoard ? 'passive' : 'static';
  if (!chooseOnBoard) root.hitArea = new PIXI.Rectangle(0, 0, w, h);
  root.on('pointertap', (event) => event.stopPropagation());
  const theme = SIDE_THEME[side];
  const isSlot = choice.selection === 'slot';
  const task = isSlot ? '选择交锋' : choice.selection === 'hand' ? '选择手牌' : '选择技能';
  const candidates = options.map((option, index) => ({ option, index })).filter(({ option }) => option.kind !== 'decline_card');
  const decline = options.findIndex((option) => option.kind === 'decline_card');
  const gap = 12;
  const panelW = Math.min(w - 24, 1060);
  const innerW = panelW - 32;
  const title = [choice.source_name, choice.die_position && `第 ${choice.die_position} 骰`, task].filter(Boolean).join(' · ');
  const heading = choiceText(title, 16, theme.accent, innerW, true);
  const description = choiceText(choice.description || '', 13, INK.primary, innerW);
  const headerH = 19 + heading.height + (choice.description ? description.height + 4 : 0);
  const cardW = isSlot ? 164 : Math.min(202, Math.max(144, Math.floor(w * 0.19)));
  const perPage = Math.max(1, Math.floor((innerW + gap) / (cardW + gap)));
  const pages = Math.max(1, Math.ceil(candidates.length / perPage));
  const footerH = w < 520 && pages > 1 ? 86 : 48;
  const roomForCard = h - safeTop - headerH - footerH - 22;
  const compact = roomForCard < 188;
  const captionH = onReady || isSlot || compact ? 0 : 44;
  const faceH = onReady ? 0 : isSlot ? 46
    : Math.max(48, Math.min(compact ? 78 : 244, roomForCard - captionH));
  const panelH = headerH + faceH + captionH + footerH + 12;
  const panelX = (w - panelW) / 2;
  const panelY = Math.max(4, h - panelH - 10);
  const panel = new PIXI.Container();
  panel.eventMode = 'static';
  panel.hitArea = new PIXI.Rectangle(0, 0, panelW, panelH);
  panel.position.set(panelX, panelY);
  const paper = new PIXI.Graphics();
  drawFolioFrame(paper, 0, 0, panelW, panelH, { accent: theme.accent, radius: 9, edgeDepth: 2, shadowAlpha: 0.2 });
  panel.addChild(paper, heading);
  heading.position.set(16, 9);
  if (choice.description) {
    description.position.set(16, 13 + heading.height);
    panel.addChild(description);
  } else description.destroy();
  root.addChild(panel);

  if (onReady) {
    const ready = makeSealButton(`${theme.name}接手`, { width: 134, height: 34, accent: theme.accent, solid: true, onClick: onReady });
    ready.position.set(panelW - 150, headerH + 6);
    panel.addChild(ready);
    return root;
  }

  const body = new PIXI.Container();
  const footer = new PIXI.Container();
  panel.addChild(body, footer);
  let page = 0;
  let selected = -1;
  const markers = new Map();
  const reset = (container) => {
    for (const child of container.removeChildren()) child.destroy({ children: true });
  };
  const confirm = () => {
    if (selected >= 0) onPick(selected);
  };
  const select = (index) => {
    const ordinal = candidates.findIndex((candidate) => candidate.index === index);
    if (ordinal < 0) return;
    const targetPage = Math.floor(ordinal / perPage);
    if (targetPage !== page) showPage(targetPage);
    selected = index;
    onSelectionChange(index);
    for (const [candidateIndex, mark] of markers) mark.visible = candidateIndex === index;
    refreshFooter();
  };
  const refreshFooter = () => {
    reset(footer);
    const actionY = panelH - 47;
    const confirmButton = makeSealButton(isSlot ? '确认交锋' : '确认选择', {
      width: 108, height: 34, accent: theme.accent, solid: true, disabled: selected < 0, onClick: confirm,
    });
    confirmButton.position.set(panelW - 124, actionY);
    footer.addChild(confirmButton);
    if (decline >= 0) {
      const skip = makeSealButton('放弃 · Esc', { width: 106, height: 34, onClick: () => onPick(decline) });
      skip.position.set(panelW - 240, actionY);
      footer.addChild(skip);
    }
    if (pages > 1) {
      const navY = w < 520 ? actionY - 38 : actionY;
      const prev = makeSealButton('‹', { width: 34, height: 32, disabled: page === 0, onClick: () => showPage(page - 1) });
      const count = choiceText(`${page + 1} / ${pages}`, 13, INK.primary, 72);
      const next = makeSealButton('›', { width: 34, height: 32, disabled: page + 1 === pages, onClick: () => showPage(page + 1) });
      prev.position.set(16, navY);
      count.position.set(59, navY + 7);
      next.position.set(68 + count.width, navY);
      footer.addChild(prev, count, next);
    }
  };
  const showPage = (nextPage) => {
    onInspect(null);
    reset(body);
    page = Math.max(0, Math.min(pages - 1, nextPage));
    selected = -1;
    onSelectionChange(-1);
    const visible = candidates.slice(page * perPage, (page + 1) * perPage);
    const rowW = visible.length * (cardW + gap) - gap;
    markers.clear();
    visible.forEach(({ option, index }, col) => {
      const target = option.effect_target || {};
      const targetSide = target.side || side;
      const fromHand = target.zone === 'hand' && targetSide === side;
      const card = target.card || (fromHand && hand.find((item) => (item.action_key || item.id) === option.target_card_id));
      const item = new PIXI.Container();
      item.position.set(Math.max(16, (panelW - rowW) / 2) + col * (cardW + gap), headerH + 3);
      item.eventMode = 'static';
      item.cursor = 'pointer';
      item.hitArea = new PIXI.Rectangle(0, 0, cardW, faceH + captionH);
      body.addChild(item);
      const known = card && !card.hidden;
      if (isSlot) {
        const targetLabel = choiceText(option.label, 13, theme.accent, cardW - 14, true);
        const slot = new PIXI.Graphics().roundRect(0, 0, cardW, faceH, 6)
          .fill(INK.paperSoft).stroke({ width: 1, color: theme.border });
        targetLabel.anchor.set(0.5);
        targetLabel.position.set(cardW / 2, faceH / 2);
        item.addChild(slot, targetLabel);
      } else {
        const label = target.zone === 'board'
          ? `${targetSide === side ? '己方' : '对方'} · ${DUEL_LABEL[target.kind]} ${target.number} · 第 ${target.position} 张`
          : known ? owners[card.character_id] || '' : option.label;
        const price = option.use_preview;
        const cost = price ? [`预计 ${price.cost} 费`] : [];
        const extra = price?.resource_cost;
        if (extra) cost.push(`需 ${extra.amount} ${extra.status}（现有 ${extra.available}）`);
        const priceLines = cost.length ? cost : [label];
        if (compact) {
          const surface = new PIXI.Graphics().roundRect(0, 0, cardW, faceH, 6)
            .fill(INK.paperSoft).stroke({ width: 1, color: theme.border });
          const title = known ? card.name : '扣置技能';
          const caption = choiceText([title, ...priceLines].join('\n'), 12, INK.strong, cardW - 12, true);
          caption.anchor.set(0.5);
          caption.position.set(cardW / 2, faceH / 2);
          item.addChild(surface, caption);
        } else {
          const art = known
            ? buildFullCard(card, {
                side: targetSide, width: cardW, fixedHeight: faceH, dense: true, centered: true,
                accentColor: colors[card.character_id],
              })
            : buildCardBack(targetSide, { width: Math.min(cardW, faceH / 1.40), height: faceH });
          art.position.set(cardW / 2, faceH / 2);
          item.addChild(art);
          const clip = new PIXI.Graphics().rect(-2, -2, cardW + 6, faceH + 5).fill(0xffffff);
          item.addChild(clip);
          art.mask = clip;
          const caption = choiceText(priceLines.join('\n'), 12, INK.primary, cardW, true);
          caption.anchor.set(0.5, 0);
          caption.position.set(cardW / 2, faceH + 5);
          item.addChild(caption);
        }
        if (known) {
          item.on('pointerover', () => {
            const point = item.getGlobalPosition();
            onInspect(card, targetSide, point.x + cardW / 2, panelY - 4);
          });
          item.on('pointerout', () => onInspect(null));
        }
      }
      const marker = new PIXI.Graphics();
      marker.roundRect(-2, -3, cardW + 4, faceH + captionH + 3, 7).stroke({ width: 2.5, color: theme.accent });
      marker.visible = false;
      markers.set(index, marker);
      item.addChild(marker);
      item.on('pointertap', (event) => {
        event.stopPropagation();
        select(index);
      });
    });
    refreshFooter();
  };
  showPage(0);
  root.selectOption = select;
  root.trayTop = panelY;
  root.confirmSelection = confirm;
  root.cancelSelection = () => {
    if (selected >= 0) showPage(page);
    else if (decline >= 0) onPick(decline);
  };
  root.moveSelection = (direction) => {
    const ordinal = candidates.findIndex((candidate) => candidate.index === selected);
    const nextOrdinal = ordinal < 0 ? page * perPage
      : Math.max(0, Math.min(candidates.length - 1, ordinal + direction));
    if (candidates[nextOrdinal]) select(candidates[nextOrdinal].index);
  };
  root.getSelection = () => selected;
  root.stepPage = (direction) => {
    const nextPage = page + direction;
    if (nextPage >= 0 && nextPage < pages) showPage(nextPage);
  };
  return root;
}

export function buildSpecialOverlay(w, h, {
  side,
  timing,
  options = [],
  duels = [],
  pendingAttack,
  scrollY = 0,
  onPick,
  onSwitchSide,
  onLeave,
  onScrollChange = null,
}) {
  const root = new PIXI.Container();
  const theme = SIDE_THEME[side] || SIDE_THEME[1];

  const veil = new PIXI.Graphics();
  veil.rect(0, 0, w, h).fill({ color: 0xf4efe4, alpha: 0.18 });
  veil.eventMode = 'static';
  root.addChild(veil);

  const panelW = Math.min(720, w - 24);
  const headerH = 48;
  const footerH = 50;
  const maxBodyH = Math.min(Math.max(84, Math.floor(h * 0.44) - headerH), 322);

  // Pre-build semantic action seal cards to measure exact scrollable height
  const bodyInnerW = panelW - 52;
  const builtCards = [];
  let cy = 6;
  const cardGap = 9;

  options.forEach((opt, idx) => {
    const ks = SPECIAL_KIND_STYLE[opt.kind] || SPECIAL_KIND_STYLE.special;
    const textW = Math.max(76, bodyInnerW - 104);
    const target = opt.effect_target;
    let targetLine = '';
    if (target?.zone === 'board' && (opt.kind === 'replace' || (opt.kind === 'ability' && !opt.duel_number))) {
      targetLine = `${DUEL_LABEL[target.kind]} ${target.number} · 第 ${target.position} 张`;
    } else if (opt.response_number) {
      const duel = duels.find((slot) => slot.number === opt.response_number);
      const attack = duel?.sides.find((entry) => entry.side === duel.attacking_side)?.cards.find((card) => card.play_mode === 'active');
      if (attack) {
        const destination = duel.target?.kind === 'duel' ? `常规交锋 ${duel.target.number}` : duel.target?.name;
        targetLine = [attack.name, destination].filter(Boolean).join(' → ');
      }
    }
    const lbl = new PIXI.Text({
      text: [opt.label, targetLine].filter(Boolean).join('\n'),
      style: {
        fontFamily: FONT_UI,
        fontSize: 12.8,
        fontWeight: '800',
        fill: INK.strong,
        lineHeight: 19,
        wordWrap: true,
        breakWords: true,
        wordWrapWidth: textW,
      },
    });
    const cardH = Math.max(46, Math.ceil(lbl.height) + 18);

    const card = new PIXI.Container();
    const bg = new PIXI.Graphics();
    const drawCard = (hov, pressed = false) => {
      bg.clear();
      const dy = pressed ? 1 : 0;
      bg.roundRect(1.5, pressed ? 2 : 3.5, bodyInnerW, cardH, 8).fill({ color: INK.shadow, alpha: hov ? 0.28 : 0.16 });
      bg.roundRect(0, dy, bodyInnerW, cardH, 8)
        .fill({ color: hov ? ks.wash : INK.paper })
        .stroke({ width: hov ? 1.8 : 1.15, color: hov ? ks.color : INK.line });
      // Semantic 4px left stripe
      bg.roundRect(0, dy + 2, 4.5, cardH - 4, 2).fill({ color: ks.color });
      // Action type emblem medallion
      bg.circle(26, dy + cardH / 2, 13)
        .fill({ color: ks.wash })
        .stroke({ width: 1.1, color: ks.color, alpha: 0.7 });
      drawActionEmblem(bg, opt.kind, 26, dy + cardH / 2, 7.2, ks.color);
      // Kind tag capsule on right
      const tagW = 42;
      bg.roundRect(bodyInnerW - tagW - 10, dy + cardH / 2 - 10, tagW, 20, 5)
        .fill({ color: ks.wash })
        .stroke({ width: 0.9, color: ks.color, alpha: 0.6 });
    };
    drawCard(false, false);
    card.addChild(bg);

    lbl.anchor.set(0, 0.5);
    lbl.position.set(48, cardH / 2);
    card.addChild(lbl);

    const kTxt = new PIXI.Text({
      text: ks.label,
      style: { fontFamily: FONT_UI, fontSize: 10.6, fontWeight: '900', fill: ks.color },
    });
    kTxt.anchor.set(0.5);
    kTxt.position.set(bodyInnerW - 31, cardH / 2);
    card.addChild(kTxt);

    card.position.set(0, cy);
    card._itemTop = cy;
    card._itemBottom = cy + cardH;
    card._interactiveItem = true;
    card._idx = idx;
    card._drawCard = drawCard;
    builtCards.push(card);
    cy += cardH + cardGap;
  });

  const contentH = options.length ? cy + 4 : 72;
  const viewH = Math.max(84, Math.min(maxBodyH, contentH));
  const panelH = headerH + viewH + footerH + 18;
  const px = (w - panelW) / 2;
  const py = Math.max(4, h - panelH - 12);

  // Illuminated Interrupt Folio Frame
  const panel = new PIXI.Graphics();
  drawFolioFrame(panel, px, py, panelW, panelH, {
    accent: theme.accent,
    bg: INK.paper,
    radius: 14,
    edgeDepth: 4.5,
    shadowAlpha: 0.34,
    topRibbonH: headerH - 2,
    ribbonFill: theme.warmTint,
    cornerDiamonds: true,
    diamondColor: INK.gold,
  });
  // Top urgency seal accent bar
  panel.roundRect(px + 20, py + 1.5, panelW - 40, 4, 2).fill({ color: theme.accent });
  drawLightStar(panel, px + 30, py + headerH / 2, 10, theme.accent, 0.94);
  drawDiamondDivider(panel, px + 22, px + panelW - 22, py + panelH - footerH, INK.hairline, INK.gold);
  panel.eventMode = 'static';
  panel.on('pointertap', (e) => e.stopPropagation());
  root.addChild(panel);

  const title = new PIXI.Text({
    text: timing ? `${theme.name} · ${timing}` : `${theme.name} · 特殊行动`,
    style: { fontFamily: FONT_UI, fontSize: 17.5, fontWeight: '900', fill: theme.accent, letterSpacing: 1 },
  });
  title.anchor.set(0, 0.5);
  title.position.set(px + 48, py + headerH / 2);
  root.addChild(title);

  // Scrollable Viewport for Action Seal Cards
  const vx = px + 20;
  const vy = py + headerH + 8;
  const vw = panelW - 40;

  const maskG = new PIXI.Graphics();
  maskG.rect(vx - 2, vy, vw + 4, viewH).fill({ color: 0xffffff });
  root.addChild(maskG);

  const body = new PIXI.Container();
  body.position.set(vx, vy);
  body.mask = maskG;
  root.addChild(body);

  if (!options.length) {
    const empty = new PIXI.Text({
      text: '当前时点无可发动的特殊行动',
      style: { fontFamily: FONT_UI, fontSize: 13.5, fontWeight: '700', fill: INK.muted },
    });
    empty.anchor.set(0.5);
    empty.position.set(vw / 2, viewH / 2);
    body.addChild(empty);
  } else {
    for (const card of builtCards) {
      card.eventMode = 'static';
      card.cursor = 'pointer';
      card.on('pointerover', (e) => {
        if (!pointerInsideLocalRect(root, e.global, vx, vy, vw, viewH)) return;
        card._drawCard(true, false);
      });
      card.on('pointerout', () => card._drawCard(false, false));
      card.on('pointerdown', (e) => {
        if (!pointerInsideLocalRect(root, e.global, vx, vy, vw, viewH)) return;
        e.stopPropagation();
        card._drawCard(true, true);
      });
      card.on('pointerup', () => card._drawCard(true, false));
      card.on('pointertap', (e) => {
        if (!pointerInsideLocalRect(root, e.global, vx, vy, vw, viewH)) return;
        e.stopPropagation();
        onPick(card._idx);
      });
      body.addChild(card);
    }
  }

  const maxScroll = Math.max(0, contentH - viewH);
  let curScroll = Math.max(0, Math.min(maxScroll, scrollY));
  let sb = null;
  const applyScroll = (nextY, emit = true) => {
    curScroll = Math.max(0, Math.min(maxScroll, nextY));
    body.y = vy - curScroll;
    cullVerticalItems(body, curScroll, viewH);
    if (sb) sb._updateThumb(curScroll);
    if (emit && onScrollChange) onScrollChange(curScroll);
    return curScroll;
  };
  applyScroll(curScroll, false);

  if (maxScroll > 0) {
    sb = makeSmoothScrollbar({
      x: vx + vw - 6,
      y: vy + 4,
      height: viewH - 8,
      totalH: contentH,
      viewH,
      scrollY: curScroll,
      accentColor: theme.accent,
      onChange: (val) => applyScroll(val, true),
    });
    root.addChild(sb);
  }

  const footY = py + panelH - footerH + 11;
  if (onSwitchSide) {
    const switchBtn = makeSealButton('切换席位', {
      width: 120, height: 36, accent: INK.secondary, fontSize: 12.5, radius: 9, onClick: onSwitchSide,
    });
    switchBtn.position.set(px + 20, footY);
    root.addChild(switchBtn);
  }

  if (!pendingAttack) {
    const closeBtn = makeSealButton('返回战场', {
      width: 120, height: 36, accent: theme.accent, solid: true, fontSize: 13, radius: 9, onClick: onLeave,
    });
    closeBtn.position.set(px + panelW - 140, footY);
    root.addChild(closeBtn);
  }

  root._maxScroll = maxScroll;
  root._rect = { x: px, y: py, w: panelW, h: panelH };
  root.setScroll = (nextY) => applyScroll(nextY, true);
  return root;
}

// ── 6. INFINITE-SCALE 10v10+ SQUAD FORMATION STAGE (ROSTER OVERLAY) ──

const ROSTER_PRESETS = [1, 3, 5, 10];

export function buildRosterOverlay(w, h, {
  catalog = [],
  team1 = [],
  team2 = [],
  assignSide = 1,
  hoveredChar = null,
  factionFilter = null,
  maxPerSide = 10,
  roomLobby = null,
  galleryScrollY = 0,
  inspectScrollY = 0,
  factionScrollX = 0,
  onSetAssignSide,
  onSetFaction,
  onSetMaxPerSide = null,
  onQuantity = null,
  onClearSide = null,
  onToggleChar,
  onInspectChar = null,
  onRemoveFromSide,
  onHoverChar,
  onHoverCard = null,
  onGalleryScrollChange = null,
  onInspectScrollChange = null,
  onStart,
  onCancel,
}) {
  const root = new PIXI.Container();
  const rootActors = [];
  const galleryActorEntries = [];
  let heroBannerActorEntry = null;
  const wingActors = [];

  const syncLiveActors = () => {
    rootActors.length = 0;
    for (const a of wingActors) rootActors.push(a);
    if (heroBannerActorEntry) rootActors.push(heroBannerActorEntry);
    for (const a of galleryActorEntries) {
      if (!a.card || a.card.visible) rootActors.push(a);
    }
  };

  const veil = new PIXI.Graphics();
  veil.rect(0, 0, w, h).fill({ color: 0xf5f1e7, alpha: 0.985 });
  veil.eventMode = 'static';
  root.addChild(veil);

  const pad = 18;
  const charById = new Map(catalog.map((c) => [c.id, c]));
  const openTeams = Boolean(roomLobby?.openTeams);
  const teamCounts = [team1, team2].map(team => {
    const counts = new Map();
    for (const id of team) counts.set(id, (counts.get(id) || 0) + 1);
    return counts;
  });

  const isUnlimited = maxPerSide === Infinity || maxPerSide === null || maxPerSide <= 0;
  let activeCap = isUnlimited
    ? Math.max(10, team1.length, team2.length)
    : Math.max(1, maxPerSide, team1.length, team2.length);

  // ── 1. TOP CONFRONTATIONAL VS SQUAD FORMATION STAGE (1v1 / 3v3 / 5v5 / 10v10+ SCALABLE!) ──
  const topY = 12;
  const topH = 132;
  const centerW = 208;
  const wingW = Math.floor((w - pad * 2 - centerW - 22) / 2);

  const wingsHost = new PIXI.Container();
  root.addChild(wingsHost);
  const presetHost = new PIXI.Container();
  root.addChild(presetHost);

  function bindOccupiedSlot(slot, removeIcon, iconX, iconY, side, ch, editable) {
    const remove = () => onRemoveFromSide ? onRemoveFromSide(side, ch.id) : onToggleChar(ch.id);
    slot.eventMode = 'static';
    slot.cursor = 'pointer';
    slot.on('pointerover', () => onHoverChar?.(ch));
    slot.on('pointertap', event => {
      event.stopPropagation();
      if (onInspectChar) onInspectChar(ch);
      else if (editable) remove();
    });
    if (!editable) { removeIcon.destroy(); return; }
    slot.addChild(removeIcon);
    if (onInspectChar) {
      removeIcon.eventMode = 'static';
      removeIcon.cursor = 'pointer';
      removeIcon.accessible = true;
      removeIcon.accessibleTitle = '移出' + ch.name;
      removeIcon.hitArea = new PIXI.Circle(iconX, iconY, 11);
      removeIcon.on('pointertap', event => { event.stopPropagation(); remove(); });
    }
  }

  const renderWingRacks = () => {
    const oldWings = wingsHost.removeChildren();
    for (const child of oldWings) child.destroy({ children: true });
    wingActors.length = 0;

    [1, 2].forEach((side) => {
      const t = SIDE_THEME[side];
      const isEditing = assignSide === side;
      const editable = !roomLobby || roomLobby.editableSides.includes(side);
      const sideName = roomLobby?.sideNames?.[side] || t.name;
      const list = side === 1 ? team1 : team2;
      const counts = teamCounts[side - 1];
      const displayed = openTeams && list.length > 5 ? Array.from(counts.keys()) : list;
      const grouped = displayed !== list;
      const wx = side === 1 ? pad : w - pad - wingW;

      const wing = new PIXI.Container();
      wing.position.set(wx, topY);
      const wg = new PIXI.Graphics();
      drawFolioFrame(wg, 0, 0, wingW, topH, {
        accent: isEditing ? t.accent : INK.line,
        bg: isEditing ? t.warmTint : INK.paper,
        radius: 12,
        edgeDepth: 3,
        shadowAlpha: isEditing ? 0.28 : 0.16,
        topRibbonH: 25,
        ribbonFill: isEditing ? t.softBg : INK.paperSoft,
        cornerDiamonds: true,
        diamondColor: isEditing ? t.accent : INK.muted,
      });
      wing.addChild(wg);

      const capLabel = isUnlimited ? `${list.length}人` : `${list.length}/${activeCap}`;
      const wTitle = new PIXI.Text({
        text: `${sideName} · ${capLabel}`,
        style: { fontFamily: FONT_UI, fontSize: 12.2, fontWeight: '900', fill: t.accent },
      });
      wTitle.position.set(side === 1 ? 14 : wingW - 14 - wTitle.width, 5);
      wing.addChild(wTitle);

      if (openTeams && editable && list.length) {
        const clearButton = makeSealButton('清空', {
          width: 42, height: 20, fontSize: 10, radius: 5, accent: t.accent,
          onClick: () => onClearSide(side),
        });
        clearButton.position.set(side === 1 ? wingW - 57 : 14, 3);
        wing.addChild(clearButton);
      } else if (isEditing && editable) {
        const edTxt = new PIXI.Text({
          text: '◆ 当前编队',
          style: { fontFamily: FONT_UI, fontSize: 10.6, fontWeight: '800', fill: INK.goldDeep },
        });
        edTxt.position.set(side === 1 ? wingW - 14 - edTxt.width : 14, 6);
        wing.addChild(edTxt);
      }

      if (editable) {
        wing.eventMode = 'static';
        wing.cursor = 'pointer';
        wing.on('pointertap', (e) => {
          e.stopPropagation();
          onSetAssignSide(side);
        });
      }

      // Dynamic Formation Rack Geometry:
      // - displayCount <= 5: single lush row of living pedestals
      // - 6 <= displayCount <= 10: 2-row x 5-col compact tactical formation (ALL 10 visible at once!)
      // - displayCount > 10: 2-row horizontal scrollable formation rack with draggable scrollbar!
      const displayCount = openTeams ? Math.max(1, displayed.length) : Math.max(list.length, activeCap);
      const rackX = 10;
      const rackY = 30;
      const rackW = wingW - 20;
      const rackH = topH - 36;

      if (displayCount <= 5) {
        const slotGap = 7;
        const slotW = Math.floor((rackW - slotGap * (displayCount - 1)) / displayCount);
        const slotH = rackH - 2;
        for (let i = 0; i < displayCount; i++) {
          const visualIdx = side === 1 ? i : displayCount - 1 - i;
          const sx = rackX + visualIdx * (slotW + slotGap);
          const cid = displayed[i];
          const ch = cid ? charById.get(cid) : null;
          const slot = new PIXI.Container();
          slot.position.set(sx, rackY);

          const sg = new PIXI.Graphics();
          if (ch) {
            const pal = actorPalette(ch, side);
            sg.roundRect(0, 0, slotW, slotH, 9)
              .fill({ color: pal.highlight })
              .stroke({ width: 1.6, color: t.accent });
            sg.ellipse(slotW / 2, slotH - 22, Math.min(36, slotW * 0.34), 7)
              .fill({ color: INK.paper, alpha: 0.78 })
              .stroke({ width: 0.9, color: pal.primary, alpha: 0.35 });
            slot.addChild(sg);

            const rad = Math.min(22, Math.max(15, Math.floor(slotW * 0.22)));
            const actor = createCharacterActor(ch, side, { radius: rad });
            actor.position.set(slotW / 2, Math.round(slotH * 0.42));
            slot.addChild(actor);
            wingActors.push({ actor, ch });

            const nm = new PIXI.Text({
              text: grouped ? `${ch.name} ×${counts.get(cid)}` : ch.name,
              style: { fontFamily: FONT_UI, fontSize: slotW < 92 || ch.name.length > 4 ? 10.2 : 11.5, fontWeight: '800', fill: INK.strong },
            });
            nm.anchor.set(0.5);
            nm.position.set(slotW / 2, slotH - 11);
            slot.addChild(nm);

            const rx = side === 1 ? slotW - 11 : 11;
            const rmBg = new PIXI.Graphics();
            rmBg.circle(rx, 11, 7).fill({ color: INK.paper, alpha: 0.94 }).stroke({ width: 1.1, color: INK.secondary, alpha: 0.65 });
            rmBg.moveTo(rx - 2.8, 8.2).lineTo(rx + 2.8, 13.8).stroke({ width: 1.4, color: 0xcf4932 });
            rmBg.moveTo(rx + 2.8, 8.2).lineTo(rx - 2.8, 13.8).stroke({ width: 1.4, color: 0xcf4932 });
            bindOccupiedSlot(slot, rmBg, rx, 11, side, ch, editable);
          } else {
            sg.roundRect(0, 0, slotW, slotH, 9)
              .fill({ color: INK.paperSoft, alpha: 0.78 })
              .stroke({ width: 1.1, color: isEditing ? t.border : INK.line, alpha: 0.8 });
            sg.moveTo(slotW / 2 - 6, slotH / 2 - 4).lineTo(slotW / 2 + 6, slotH / 2 - 4)
              .stroke({ width: 1.6, color: INK.muted, alpha: 0.65 });
            sg.moveTo(slotW / 2, slotH / 2 - 10).lineTo(slotW / 2, slotH / 2 + 2)
              .stroke({ width: 1.6, color: INK.muted, alpha: 0.65 });
            slot.addChild(sg);

            const idxTxt = new PIXI.Text({
              text: roomLobby?.title && !list.length && i === 0 ? '选角色后点编入' : `${i + 1}号位`,
              style: { fontFamily: FONT_UI, fontSize: 10, fontWeight: '700', fill: INK.muted },
            });
            idxTxt.anchor.set(0.5);
            idxTxt.position.set(slotW / 2, slotH - 12);
            slot.addChild(idxTxt);
          }
          wing.addChild(slot);
        }
      } else {
        // 6..10+ Compact 2-Row Tactical Formation Rack (with horizontal scroll if >10!)
        const rows = 2;
        const colsPerView = 5;
        const totalCols = Math.ceil(displayCount / rows);
        const needScroll = totalCols > colsPerView;
        const gapX = 5;
        const gapY = 5;
        const scrollBarReserve = needScroll ? 10 : 0;
        const cellW = Math.floor((rackW - gapX * (colsPerView - 1)) / colsPerView);
        const cellH = Math.floor((rackH - scrollBarReserve - gapY) / rows);

        const rackMask = new PIXI.Graphics();
        rackMask.rect(rackX, rackY, rackW, rackH - scrollBarReserve).fill({ color: 0xffffff });
        wing.addChild(rackMask);

        const rackBody = new PIXI.Container();
        rackBody.position.set(rackX, rackY);
        rackBody.mask = rackMask;
        wing.addChild(rackBody);

        for (let i = 0; i < displayCount; i++) {
          const r = Math.floor(i / totalCols);
          const rawC = i % totalCols;
          const c = (!needScroll && side === 2) ? (totalCols - 1 - rawC) : rawC;
          const sx = c * (cellW + gapX);
          const sy = r * (cellH + gapY);
          const cid = displayed[i];
          const ch = cid ? charById.get(cid) : null;

          const slot = new PIXI.Container();
          slot.position.set(sx, sy);
          const sg = new PIXI.Graphics();
          if (ch) {
            const pal = actorPalette(ch, side);
            sg.roundRect(0, 0, cellW, cellH, 7)
              .fill({ color: pal.highlight })
              .stroke({ width: 1.4, color: t.accent });
            sg.circle(17, cellH / 2, 12).fill({ color: INK.paper, alpha: 0.85 })
              .stroke({ width: 1, color: pal.primary, alpha: 0.5 });
            slot.addChild(sg);

            const miniActor = createCharacterActor(ch, side, { radius: 11 });
            miniActor.position.set(17, cellH / 2 + 1);
            slot.addChild(miniActor);
            wingActors.push({ actor: miniActor, ch });

            const shortName = ch.name.length > 4 ? `${ch.name.slice(0, 4)}` : ch.name;
            const nm = new PIXI.Text({
              text: shortName,
              style: { fontFamily: FONT_UI, fontSize: 10.6, fontWeight: '800', fill: INK.strong },
            });
            nm.anchor.set(0, 0.5);
            nm.position.set(32, cellH / 2 - 5);
            slot.addChild(nm);

            const idxTag = new PIXI.Text({
              text: grouped ? `×${counts.get(cid)}` : `#${i + 1}`,
              style: { fontFamily: FONT_NUM, fontSize: 9.2, fontWeight: '800', fill: t.accent },
            });
            idxTag.anchor.set(0, 0.5);
            idxTag.position.set(32, cellH / 2 + 8);
            slot.addChild(idxTag);

            const rmBg = new PIXI.Graphics();
            rmBg.circle(cellW - 9, 9, 5.5).fill({ color: INK.paper, alpha: 0.92 }).stroke({ width: 0.9, color: INK.secondary, alpha: 0.6 });
            rmBg.moveTo(cellW - 11.2, 6.8).lineTo(cellW - 6.8, 11.2).stroke({ width: 1.2, color: 0xcf4932 });
            rmBg.moveTo(cellW - 6.8, 6.8).lineTo(cellW - 11.2, 11.2).stroke({ width: 1.2, color: 0xcf4932 });
            bindOccupiedSlot(slot, rmBg, cellW - 9, 9, side, ch, editable);
          } else {
            sg.roundRect(0, 0, cellW, cellH, 7)
              .fill({ color: INK.paperSoft, alpha: 0.72 })
              .stroke({ width: 0.95, color: isEditing ? t.border : INK.line, alpha: 0.72 });
            slot.addChild(sg);

            const idxTxt = new PIXI.Text({
              text: `+ ${i + 1}`,
              style: { fontFamily: FONT_NUM, fontSize: 10.2, fontWeight: '800', fill: INK.muted },
            });
            idxTxt.anchor.set(0.5);
            idxTxt.position.set(cellW / 2, cellH / 2);
            slot.addChild(idxTxt);
          }
          rackBody.addChild(slot);
        }

        if (needScroll) {
          const totalRackW = totalCols * (cellW + gapX) - gapX;
          const hsb = makeHorizontalScrollbar({
            x: rackX,
            y: rackY + rackH - 6,
            width: rackW,
            totalW: totalRackW,
            viewW: rackW,
            scrollX: 0,
            accentColor: t.accent,
            onChange: (sx) => { rackBody.x = rackX - sx; },
          });
          wing.addChild(hsb);
        }
      }

      wingsHost.addChild(wing);
    });

    root._maxPerSide = activeCap;
    syncLiveActors();
  };

  // Center VS Crest + Preset Scale Pills (1v1 / 3v3 / 5v5 / 10v10) + Start / Cancel Seals
  const cx = w / 2;
  const vsG = new PIXI.Graphics();
  if (!roomLobby?.title) {
    drawHeraldicCompass(vsG, cx, topY + 20, 20, INK.gold, INK.line);
    drawLightStar(vsG, cx, topY + 20, 15, INK.gold, 0.92);
  }
  root.addChild(vsG);
  const vsTxt = new PIXI.Text({
    text: roomLobby?.title || 'VS',
    style: { fontFamily: roomLobby?.title ? FONT_UI : FONT_NUM, fontSize: roomLobby?.title ? 18 : 13.5,
      fontWeight: '900', fill: INK.strong, letterSpacing: 1 },
  });
  vsTxt.anchor.set(0.5);
  vsTxt.position.set(cx, topY + 20);
  root.addChild(vsTxt);

  const renderPresets = () => {
    const oldPresets = presetHost.removeChildren();
    for (const child of oldPresets) child.destroy({ children: true });
    if (openTeams) {
      const quickCounts = [1, 2, 3, 4, 5];
      const startX = cx - 102;
      for (const count of quickCounts) {
        const selected = roomLobby.quantity === count && roomLobby.quantityInput == null;
        const button = makeSealButton(String(count), {
          width: 22, height: 22, fontSize: 10.2, radius: 5, accent: INK.gold, solid: selected,
          onClick: () => onQuantity(count),
        });
        button.position.set(startX + (count - 1) * 25, topY + 42);
        presetHost.addChild(button);
      }
      const editing = roomLobby.quantityInput != null;
      const batchText = editing ? `${roomLobby.quantityInput.slice(-9) || '数量'}▏` : `批量 ×${roomLobby.quantity}`;
      const batchButton = makeSealButton(batchText, {
        width: 80, height: 22, fontSize: 10.2, radius: 5, accent: INK.gold, solid: editing,
        onClick: () => onQuantity(null),
      });
      batchButton.position.set(startX + 125, topY + 42);
      presetHost.addChild(batchButton);
      return;
    }
    if (roomLobby) return;
    const pillGap = 4;
    const pillW = 46;
    const totalPW = ROSTER_PRESETS.length * pillW + (ROSTER_PRESETS.length - 1) * pillGap;
    const startPX = cx - totalPW / 2;
    ROSTER_PRESETS.forEach((n, idx) => {
      const isAct = activeCap === n;
      const pBtn = makeSealButton(`${n}v${n}`, {
        width: pillW,
        height: 22,
        accent: isAct ? INK.gold : INK.secondary,
        fill: INK.paperSoft,
        solid: isAct,
        fontSize: 10.2,
        radius: 6,
        onClick: () => {
          activeCap = Math.max(n, team1.length, team2.length);
          if (onSetMaxPerSide) {
            onSetMaxPerSide(n);
          } else {
            renderPresets();
            renderWingRacks();
          }
        },
      });
      pBtn.position.set(startPX + idx * (pillW + pillGap), topY + 41);
      presetHost.addChild(pBtn);
    });
  };

  renderPresets();
  renderWingRacks();

  const valid = team1.length >= 1 && team2.length >= 1;
  const startLabel = roomLobby?.sideNames ? '开战' : roomLobby ? '准备' : '开始对局';
  const startBtn = makeSealButton(startLabel, {
    width: 164, height: 36, accent: valid ? 0x1c8a64 : INK.muted, solid: valid, disabled: !valid, fontSize: 14, radius: 18,
    onClick: () => onStart([team1.slice(), team2.slice()]),
  });
  startBtn.position.set(cx - 82, topY + 69);
  root.addChild(startBtn);

  const cancelBtn = makeSealButton(roomLobby?.returnLabel || '返回', {
    width: 106, height: 24, accent: INK.secondary, fontSize: 11.2, radius: 12, onClick: onCancel,
  });
  cancelBtn.position.set(cx - 53, topY + 109);
  root.addChild(cancelBtn);

  // ── 2. LEFT HALF: INFINITE-ROSTER FACTION RIBBON + O(1) SMOOTH PORTRAIT GALLERY ──
  const bodyTop = topY + topH + 10;
  const bodyH = h - bodyTop - 16;
  const galleryW = Math.floor((w - pad * 2 - 16) * 0.515);
  const galleryX = pad;

  const galleryBg = new PIXI.Graphics();
  drawFolioFrame(galleryBg, galleryX, bodyTop, galleryW, bodyH, {
    accent: INK.line,
    bg: INK.paper,
    radius: 13,
    edgeDepth: 3.5,
    shadowAlpha: 0.2,
    topRibbonH: 42,
    ribbonFill: INK.paperSoft,
    cornerDiamonds: true,
    diamondColor: INK.gold,
  });
  root.addChild(galleryBg);

  // Horizontally Scrollable Faction Filter Ribbon (supports 50+ factions cleanly!)
  const factions = [];
  for (const c of catalog) {
    const f = c.faction || '独立';
    if (!factions.includes(f)) factions.push(f);
  }
  const filterItems = [{ id: null, label: `全部 ${catalog.length}` }, ...factions.map((f) => ({ id: f, label: f }))];
  const fy = bodyTop + 9;
  const fRibbonX = galleryX + 12;
  const fRibbonW = galleryW - 24;

  const fMeasureW = filterItems.reduce((acc, item) => acc + Math.max(56, item.label.length * 11 + 18) + 6, -6);
  const fOverflow = fMeasureW > fRibbonW;
  const fNavW = fOverflow ? 22 : 0;
  const fViewX = fRibbonX + (fOverflow ? fNavW + 4 : 0);
  const fViewW = fRibbonW - (fOverflow ? (fNavW + 4) * 2 : 0);

  const fMask = new PIXI.Graphics();
  fMask.rect(fViewX, fy - 1, fViewW, 30).fill({ color: 0xffffff });
  root.addChild(fMask);

  const fStrip = new PIXI.Container();
  fStrip.mask = fMask;
  root.addChild(fStrip);

  let fx = 0;
  let activeFactionCenter = 0;
  for (const item of filterItems) {
    const active = factionFilter === item.id;
    const labelW = Math.max(56, item.label.length * 11 + 18);
    const pill = makeSealButton(item.label, {
      width: labelW,
      height: 25,
      accent: active ? SIDE_THEME[assignSide].accent : INK.secondary,
      fill: INK.paper,
      solid: active,
      fontSize: 11,
      radius: 12,
      onClick: () => onSetFaction && onSetFaction(item.id),
    });
    pill.position.set(fx, fy);
    fStrip.addChild(pill);
    if (active) activeFactionCenter = fx + labelW / 2;
    fx += labelW + 6;
  }
  const fMaxScroll = Math.max(0, fx - 6 - fViewW);
  let curFScroll = Math.max(0, Math.min(fMaxScroll, factionScrollX || (fOverflow ? activeFactionCenter - fViewW / 2 : 0)));
  const applyFScroll = (nx) => {
    curFScroll = Math.max(0, Math.min(fMaxScroll, nx));
    fStrip.x = fViewX - curFScroll;
  };
  applyFScroll(curFScroll);

  if (fOverflow) {
    const fPrev = makeSealButton('‹', {
      width: fNavW, height: 25, accent: INK.secondary, fontSize: 13, radius: 6,
      onClick: () => applyFScroll(curFScroll - Math.max(120, fViewW * 0.55)),
    });
    fPrev.position.set(fRibbonX, fy);
    const fNext = makeSealButton('›', {
      width: fNavW, height: 25, accent: INK.secondary, fontSize: 13, radius: 6,
      onClick: () => applyFScroll(curFScroll + Math.max(120, fViewW * 0.55)),
    });
    fNext.position.set(fRibbonX + fRibbonW - fNavW, fy);
    root.addChild(fPrev, fNext);
  }

  const filtered = factionFilter
    ? catalog.filter((c) => (c.faction || '独立') === factionFilter)
    : catalog;

  const gx = galleryX + 12;
  const gy = bodyTop + 48;
  const gw = galleryW - 24;
  const gh = bodyH - 58;

  const gMask = new PIXI.Graphics();
  gMask.rect(gx, gy, gw, gh).fill({ color: 0xffffff });
  root.addChild(gMask);

  const gBody = new PIXI.Container();
  gBody.position.set(gx, gy);
  gBody.mask = gMask;
  root.addChild(gBody);

  const cols = gw >= 540 ? 4 : 3;
  const gap = 10;
  const cellW = Math.floor((gw - 12 - gap * (cols - 1)) / cols);
  const cellH = 148;
  const rows = Math.ceil(filtered.length / cols);
  const totalGalleryH = rows * cellH + Math.max(0, rows - 1) * gap + 10;
  const galleryMaxScroll = Math.max(0, totalGalleryH - gh);
  let curGalleryScroll = Math.max(0, Math.min(galleryMaxScroll, galleryScrollY));

  const target = hoveredChar || filtered[0] || catalog[0];

  filtered.forEach((char, idx) => {
    const col = idx % cols;
    const row = Math.floor(idx / cols);
    const cxPos = col * (cellW + gap);
    const cyPos = row * (cellH + gap);

    const in1 = team1.indexOf(char.id);
    const in2 = team2.indexOf(char.id);
    const ownerSide = in1 >= 0 ? 1 : in2 >= 0 ? 2 : 0;
    const isSelected = target?.id === char.id;
    const pal = actorPalette(char, ownerSide || assignSide);
    const borderCol = ownerSide ? SIDE_THEME[ownerSide].accent : isSelected ? INK.gold : INK.line;

    const card = new PIXI.Container();
    card.position.set(cxPos, cyPos);
    const bg = new PIXI.Graphics();
    bg.roundRect(2, 4, cellW, cellH, 10).fill({ color: INK.shadow, alpha: isSelected ? 0.3 : 0.18 });
    bg.roundRect(0, 0, cellW, cellH, 10)
      .fill({ color: INK.paper })
      .stroke({ width: ownerSide ? 2.4 : isSelected ? 2.2 : 1.25, color: borderCol });

    // Sculpted portrait art stage (upper 84px)
    const artH = 84;
    bg.roundRect(3, 3, cellW - 6, artH, 7).fill({ color: pal.highlight });
    bg.circle(cellW / 2, artH * 0.54, 30)
      .fill({ color: INK.paper, alpha: 0.72 })
      .stroke({ width: 1.1, color: pal.primary, alpha: 0.35 });
    bg.ellipse(cellW / 2, artH - 9, cellW * 0.3, 6).fill({ color: pal.primary, alpha: 0.14 });
    card.addChild(bg);

    const actor = createCharacterActor(char, ownerSide || 1, { radius: 26 });
    actor.position.set(cellW / 2, artH * 0.56);
    card.addChild(actor);
    galleryActorEntries.push({ actor, ch: char, card });

    // Rank crest pill (top-left)
    const rankLabel = RANK_LABEL[char.rank] || '';
    if (rankLabel) {
      const rCol = RANK_COLOR[char.rank] || INK.secondary;
      const rw = rankLabel.length * 9 + 10;
      const rg = new PIXI.Graphics();
      rg.roundRect(6, 6, rw, 17, 5).fill({ color: INK.paper, alpha: 0.92 }).stroke({ width: 1.05, color: rCol, alpha: 0.85 });
      card.addChild(rg);
      const rTxt = new PIXI.Text({
        text: rankLabel,
        style: { fontFamily: FONT_UI, fontSize: 9.2, fontWeight: '800', fill: rCol },
      });
      rTxt.anchor.set(0.5);
      rTxt.position.set(6 + rw / 2, 14.5);
      card.addChild(rTxt);
    }

    // Team ownership wax ribbon (top-right, scales to #10, #12, etc.)
    if (ownerSide) {
      const slotNum = (ownerSide === 1 ? in1 : in2) + 1;
      const badgeLabel = openTeams
        ? `P${ownerSide}×${teamCounts[ownerSide - 1].get(char.id)}` : `P${ownerSide}#${slotNum}`;
      const bw = Math.max(42, badgeLabel.length * 7.5 + 12);
      const tg = new PIXI.Graphics();
      tg.roundRect(cellW - bw - 5, 6, bw, 18, 5).fill({ color: SIDE_THEME[ownerSide].accent });
      card.addChild(tg);
      const tTxt = new PIXI.Text({
        text: badgeLabel,
        style: { fontFamily: FONT_NUM, fontSize: 10.2, fontWeight: '900', fill: INK.paper },
      });
      tTxt.anchor.set(0.5);
      tTxt.position.set(cellW - bw / 2 - 5, 15);
      card.addChild(tTxt);
    }

    // Bottom Nameplate + Visual Stat Emblems
    const nm = new PIXI.Text({
      text: char.name,
      style: { fontFamily: FONT_UI, fontSize: char.name.length > 5 ? 12 : 13.5, fontWeight: '800', fill: INK.strong },
    });
    nm.position.set(9, artH + 7);
    card.addChild(nm);

    const fac = new PIXI.Text({
      text: char.faction || '独立',
      style: { fontFamily: FONT_UI, fontSize: 9.8, fontWeight: '700', fill: pal.primary },
    });
    fac.position.set(9, artH + 25);
    card.addChild(fac);

    const statG = new PIXI.Graphics();
    const sy = cellH - 14;
    drawHeartIcon(statG, 15, sy, 5.5, 0xcf4330);
    const hpTxt = new PIXI.Text({
      text: String(char.max_hp),
      style: { fontFamily: FONT_NUM, fontSize: 11, fontWeight: '800', fill: INK.primary },
    });
    hpTxt.anchor.set(0, 0.5);
    hpTxt.position.set(24, sy);

    const duelCount = char.base_duels || 1;
    const pipStart = cellW - 10;
    for (let d = 0; d < Math.min(4, duelCount); d++) {
      const duelPipCol = parseHexColor(char.color, pal.primary);
      drawDuelPip(statG, pipStart - d * 11, sy, 4.5, duelPipCol);
    }
    card.addChild(statG, hpTxt);

    card._itemTop = cyPos;
    card._itemBottom = cyPos + cellH;
    card._interactiveItem = true;
    card.eventMode = 'static';
    card.cursor = 'pointer';
    card.on('pointerover', (e) => {
      if (!pointerInsideLocalRect(root, e.global, gx, gy, gw, gh)) return;
      onHoverChar && onHoverChar(char);
    });
    card.on('pointertap', (e) => {
      if (!pointerInsideLocalRect(root, e.global, gx, gy, gw, gh)) return;
      e.stopPropagation();
      if (onInspectChar) onInspectChar(char);
      else onToggleChar(char.id);
    });
    if (onInspectChar) {
      card.accessible = true;
      card.accessibleTitle = '查看' + char.name;
    }
    gBody.addChild(card);
  });

  let gSb = null;
  const setGalleryScroll = (nextY, emit = true) => {
    curGalleryScroll = Math.max(0, Math.min(galleryMaxScroll, nextY));
    gBody.y = gy - curGalleryScroll;
    cullVerticalItems(gBody, curGalleryScroll, gh, cellH + 30);
    syncLiveActors();
    if (gSb) gSb._updateThumb(curGalleryScroll);
    if (emit && onGalleryScrollChange) onGalleryScrollChange(curGalleryScroll);
    return curGalleryScroll;
  };
  setGalleryScroll(curGalleryScroll, false);

  if (galleryMaxScroll > 0) {
    gSb = makeSmoothScrollbar({
      x: gx + gw - 6,
      y: gy + 2,
      height: gh - 4,
      totalH: totalGalleryH,
      viewH: gh,
      scrollY: curGalleryScroll,
      accentColor: SIDE_THEME[assignSide].accent,
      onChange: (val) => setGalleryScroll(val, true),
    });
    root.addChild(gSb);
  }

  // ── 3. RIGHT HALF: ILLUMINATED HERO SHOWCASE + CONSTANT 12.4px VERBATIM PASSIVES + 1:1.40 SKILL CARDS ──
  const inspX = galleryX + galleryW + 16;
  const inspY = bodyTop;
  const inspW = w - inspX - pad;
  const inspH = bodyH;

  const inspBg = new PIXI.Graphics();
  drawFolioFrame(inspBg, inspX, inspY, inspW, inspH, {
    accent: INK.gold,
    bg: INK.paper,
    radius: 13,
    edgeDepth: 3.5,
    shadowAlpha: 0.22,
    cornerDiamonds: true,
    diamondColor: INK.gold,
  });
  root.addChild(inspBg);

  let inspectMaxScroll = 0;
  let setInspectScroll = () => 0;

  if (target) {
    const in1 = team1.indexOf(target.id);
    const in2 = team2.indexOf(target.id);
    const ownerSide = in1 >= 0 ? 1 : in2 >= 0 ? 2 : 0;
    const previewSide = ownerSide || assignSide;
    const pal = actorPalette(target, previewSide);

    // Hero Pedestal Banner (top 118px) with Compass Watermark
    const bannerH = 118;
    const bG = new PIXI.Graphics();
    bG.roundRect(inspX + 5, inspY + 5, inspW - 10, bannerH, 9).fill({ color: pal.highlight });
    const acx = inspX + 66;
    const acy = inspY + 64;
    drawHeraldicCompass(bG, acx, acy, 44, pal.primary, INK.line);
    bG.circle(acx, acy, 35).fill({ color: INK.paper, alpha: 0.78 }).stroke({ width: 1.2, color: pal.primary, alpha: 0.45 });
    bG.ellipse(acx, acy + 28, 30, 7).fill({ color: pal.primary, alpha: 0.16 });
    root.addChild(bG);

    const heroActor = createCharacterActor(target, previewSide, { radius: 36 });
    heroActor.position.set(acx, acy + 3);
    root.addChild(heroActor);
    heroBannerActorEntry = { actor: heroActor, ch: target };

    const infoX = inspX + 124;
    const nameTxt = new PIXI.Text({
      text: target.name,
      style: { fontFamily: FONT_UI, fontSize: 21, fontWeight: '900', fill: INK.strong },
    });
    nameTxt.position.set(infoX, inspY + 15);
    root.addChild(nameTxt);

    if (target.title) {
      const tt = new PIXI.Text({
        text: target.title,
        style: { fontFamily: FONT_UI, fontSize: 12, fontWeight: '700', fill: pal.primary },
      });
      tt.position.set(infoX + nameTxt.width + 10, inspY + 22);
      root.addChild(tt);
    }

    const subTxt = new PIXI.Text({
      text: `${target.faction || '独立'} · ${RANK_LABEL[target.rank] || ''}`,
      style: { fontFamily: FONT_UI, fontSize: 12, fontWeight: '700', fill: INK.secondary },
    });
    subTxt.position.set(infoX, inspY + 45);
    root.addChild(subTxt);

    // Visual Stat Badges Row
    const badgeY = inspY + 73;
    const pills = [
      { label: `生命 ${target.max_hp}`, col: 0xcf4330, bg: 0xfdece9 },
      { label: `交锋 ${target.base_duels || 1}`, col: INK.gold, bg: INK.goldBg },
      { label: `${(target.skills || []).length} 张技能`, col: pal.primary, bg: INK.paper },
    ];
    let bpx = infoX;
    const pillG = new PIXI.Graphics();
    root.addChild(pillG);
    for (const pl of pills) {
      const pt = new PIXI.Text({
        text: pl.label,
        style: { fontFamily: FONT_UI, fontSize: 11.5, fontWeight: '800', fill: pl.col },
      });
      const pw = pt.width + 16;
      pillG.roundRect(bpx, badgeY, pw, 24, 7).fill({ color: pl.bg }).stroke({ width: 1.15, color: pl.col, alpha: 0.7 });
      pt.position.set(bpx + 8, badgeY + 4);
      root.addChild(pt);
      bpx += pw + 8;
    }

    // Contextual Assign/Remove Wax-Seal Button
    const activeTheme = SIDE_THEME[assignSide];
    const activeName = roomLobby?.sideNames?.[assignSide] || activeTheme.name;
    const inActive = (assignSide === 1 ? in1 : in2) >= 0;
    const inOther = (assignSide === 1 ? in2 : in1) >= 0;
    const actLabel = openTeams ? `编入 ×${roomLobby.quantity}` : inActive
      ? `移出${activeName}`
      : inOther && !(onInspectChar && target.mirror_allowed)
        ? `调入${activeName}`
        : `+ 编入${activeName}`;
    if ((!roomLobby || roomLobby.editableSides.includes(assignSide)) && !roomLobby?.lockedIds?.includes(target.id)) {
      const actBtn = makeSealButton(actLabel, {
        width: 118,
        height: 32,
        accent: openTeams ? activeTheme.accent : inActive ? 0xcf4932 : inOther ? INK.gold : activeTheme.accent,
        solid: openTeams || !inActive,
        fontSize: 12,
        radius: 16,
        onClick: () => onToggleChar(target.id),
      });
      actBtn.position.set(inspX + inspW - 132, inspY + 15);
      root.addChild(actBtn);
    }

    // O(1) Scrollable Showcase Body: Constant 12.4px Verbatim Passives + Vertical 1:1.40 Skill Cards
    const svx = inspX + 14;
    const svy = inspY + bannerH + 14;
    const svw = inspW - 28;
    const svh = inspH - bannerH - 26;

    const sMask = new PIXI.Graphics();
    sMask.rect(svx, svy, svw, svh).fill({ color: 0xffffff });
    root.addChild(sMask);

    const sBody = new PIXI.Container();
    sBody.position.set(svx, svy);
    sBody.mask = sMask;
    root.addChild(sBody);

    let cy = 0;
    const innerW = svw - 12;

    const allPassives = [
      ...(target.faction_passives || []).map((p) => ({ ...p, tag: '阵营被动' })),
      ...(target.passives || []).map((p) => ({ ...p, tag: '角色被动' })),
    ];

    if (allPassives.length) {
      const pHead = new PIXI.Text({
        text: '被动技能',
        style: { fontFamily: FONT_UI, fontSize: 13, fontWeight: '900', fill: INK.secondary },
      });
      pHead.position.set(0, cy);
      pHead._itemTop = cy;
      pHead._itemBottom = cy + 20;
      sBody.addChild(pHead);
      cy += 23;

      for (const p of allPassives) {
        const plate = buildUnifiedEntryPlate({
          variant: 'passive',
          title: p.name || p.tag,
          tagLabel: p.tag === '阵营被动' ? '阵营被动' : '',
          entries: p.display_lines,
          width: innerW,
          accentColor: p.tag === '阵营被动' ? SIDE_THEME[previewSide].accent : INK.gold,
          fontSize: 12.4,
          lineHeight: 19.2,
        });
        plate.position.set(0, cy);
        plate._itemTop = cy;
        plate._itemBottom = cy + plate._height;
        sBody.addChild(plate);
        cy += plate._height + 8;
      }
      cy += 6;
    }

    // Zero-Hover Vertical 1 : 1.40 Skill Cards
    const skills = target.skills || [];
    if (skills.length) {
      const skHead = new PIXI.Text({
        text: '技能牌组',
        style: { fontFamily: FONT_UI, fontSize: 13, fontWeight: '900', fill: INK.secondary },
      });
      skHead.position.set(0, cy);
      skHead._itemTop = cy;
      skHead._itemBottom = cy + 20;
      sBody.addChild(skHead);
      cy += 23;

      const skCols = innerW >= 630 ? 3 : 2;
      const skGapX = 12;
      const skGapY = 12;
      const skW = Math.min(216, Math.floor((innerW - skGapX * (skCols - 1)) / skCols));
      const skMinH = Math.round(skW * 1.40);

      for (let i = 0; i < skills.length; i += skCols) {
        let rowH = 0;
        for (let c = 0; c < skCols && i + c < skills.length; c++) {
          const sk = skills[i + c];
          const cardSpr = buildFullCard(sk, {
            side: previewSide,
            accentColor: parseHexColor(target.color, pal.primary),
            ownerName: target.name,
            showOwner: false,
            width: skW,
            fixedHeight: skMinH,
            dense: true,
            centered: false,
            legal: true,
          });
          cardSpr.position.set(c * (skW + skGapX), cy);
          cardSpr._itemTop = cy;
          cardSpr._itemBottom = cy + cardSpr._boxHeight;
          if (onHoverCard) {
            cardSpr._interactiveItem = true;
            cardSpr.eventMode = 'static';
            cardSpr.cursor = 'pointer';
            cardSpr.on('pointerover', (e) => {
              if (!pointerInsideLocalRect(root, e.global, svx, svy, svw, svh)) return;
              const gp = cardSpr.getGlobalPosition();
              onHoverCard(sk, previewSide, target.name, gp.x + skW / 2, gp.y + cardSpr._boxHeight / 2, cardSpr._boxHeight, cardSpr);
            });
            cardSpr.on('pointerout', () => onHoverCard(null));
          }
          sBody.addChild(cardSpr);
          rowH = Math.max(rowH, cardSpr._boxHeight);
        }
        cy += rowH + skGapY;
      }
      cy += 8;
    }

    const totalInspectH = cy + 6;
    inspectMaxScroll = Math.max(0, totalInspectH - svh);
    let curInspectScroll = Math.max(0, Math.min(inspectMaxScroll, inspectScrollY));
    let sSb = null;

    const applyInspect = (nextY, emit = true) => {
      curInspectScroll = Math.max(0, Math.min(inspectMaxScroll, nextY));
      sBody.y = svy - curInspectScroll;
      cullVerticalItems(sBody, curInspectScroll, svh, 240);
      if (sSb) sSb._updateThumb(curInspectScroll);
      if (emit && onInspectScrollChange) onInspectScrollChange(curInspectScroll);
      return curInspectScroll;
    };
    setInspectScroll = (nextY) => applyInspect(nextY, true);
    applyInspect(curInspectScroll, false);

    if (inspectMaxScroll > 0) {
      sSb = makeSmoothScrollbar({
        x: svx + svw - 6,
        y: svy + 2,
        height: svh - 4,
        totalH: totalInspectH,
        viewH: svh,
        scrollY: curInspectScroll,
        accentColor: pal.primary,
        onChange: (val) => applyInspect(val, true),
      });
      root.addChild(sSb);
    }
  }

  syncLiveActors();
  root._actors = rootActors;
  root._galleryMaxScroll = galleryMaxScroll;
  root._inspectMaxScroll = inspectMaxScroll;
  root._gallerySplitX = inspX;
  root._maxPerSide = activeCap;
  root.setGalleryScroll = (nextY) => setGalleryScroll(nextY, true);
  root.setInspectScroll = setInspectScroll;
  return root;
}

// ── 7. ILLUMINATED CODEX OVERLAY (TRUE O(1) SMOOTH SCROLL + DRAGGABLE SCROLLBAR) ──

const RULES_VERBATIM = [
  '【回合顺序】1. 进入新回合，刷新每回合限次，处理【回合开始前】，到期预约效果转入本回合；2. 回合抽牌，再分别投 1～4 速度骰定先手（多人去一名最低速取平均，同速全员重投）；3. 回补至 5 通用费与每人 1 个人费，再结算「回合开始时」；4. 常规置卡；5. 开牌前交锋声明与结算；6. 统一开牌，按常规交锋编号结算；7. 回合结束与卡牌回收。',
  '【常规置卡】先手方首次置卡权至多扣 1 张，此后双方轮流至多连扣 2 张。沿编号从小到大放入己方第一个空位，占该角色 1 个常规交锋额度，置卡不预扣费用。',
  '【开牌前交锋与牵制】先手方先取得进攻权，每方只有一次主动进攻窗口。公开打出允许开牌前打出的手牌，新开开牌前①②③并指定存活敌方角色或已置常规交锋编号。对手可暂缓、被动打出任意合规手牌迎击转火、或明确放行。双方均结束主动进攻且全部编号就绪后按号结算；结算时才从目标常规槽取走下一张可用敌牌并公开，原常规槽留空不补位。',
  '【费用】技能在实际使用时支付：本角色个人费优先，不足从己方通用费补齐；两处合计仍不够则跳过本次技能，保留两处原有费用。',
  '【四层点数】基础值 → 变动点数（1～上限）→ 最终点数 =（基础值 + 变动点数）× 倍率 + 最终修正（强壮/虚弱作用于所有非空白骰）→ 拼点点数（涡流提供拼点点数下限，至多计入 10）。拼点点差本身不增加伤害。',
  '【远程优势】普通 1 / 强化 2 / 极限 3，高减低再扣劣势方无视远程。余 1 级：不能对优势方产生影响、不能命中；余 2 级：继承 1 级，拼赢也跳过整个拼赢分支，单方面进攻骰变空白；余 3 级：成为空白技能、所有骰变空白（仍需付费）。',
  '【伤害与护盾抵扣】普通伤害：先强化盾，再普通盾（保留概念盾）。穿甲伤害：强化盾抵扣，普通盾按入盾前整段伤害磨损（不抵扣），保留概念盾。超穿甲伤害：概念盾抵扣，普通盾与强化盾各自按整段伤害磨损。回合末结算烧伤后清空全部护盾。',
  '【特殊换卡与空白轮】换下原牌回手，已付费用不退；换入牌重新付费并从第一骰开始。已形成拼点对位且尚未取得拼点结果时一方骰消失，该方为空白轮，判仍在场的对方骰拼点胜利。',
  '【卡牌回收】不洗牌，依次置入抽牌堆底：1. 存活角色已使用且仍在场上的技能（先使用的放前面）；2. 场上其余存活角色牌（常规 → 开牌前 → 即时，按编号与存放先后）；3. 延迟弃牌区（按弃置先后）。未打出手牌保留。',
];

export function buildCodexOverlay(w, h, {
  tab = 'rules',
  scrollY = 0,
  catalog,
  characterColors = {},
  history = [],
  onExport,
  onTab,
  onScrollChange = null,
  onClose,
}) {
  const root = new PIXI.Container();
  const veil = new PIXI.Graphics();
  veil.rect(0, 0, w, h).fill({ color: 0xf4efe4, alpha: 0.87 });
  veil.eventMode = 'static';
  veil.on('pointertap', onClose);
  root.addChild(veil);

  const pw = Math.min(860, w - 72);
  const ph = Math.min(640, h - 72);
  const px = (w - pw) / 2;
  const py = (h - ph) / 2;
  const headerH = 58;

  const frame = new PIXI.Graphics();
  drawFolioFrame(frame, px, py, pw, ph, {
    accent: INK.gold,
    bg: INK.paper,
    radius: 14,
    edgeDepth: 4.5,
    shadowAlpha: 0.34,
    topRibbonH: headerH - 2,
    ribbonFill: INK.paperSoft,
    cornerDiamonds: true,
    diamondColor: INK.gold,
  });
  frame.eventMode = 'static';
  frame.on('pointertap', (e) => e.stopPropagation());
  root.addChild(frame);

  const closeWidth = pw < 600 ? 52 : 84;
  const tabGap = pw < 600 ? 6 : 10;
  const tabWidth = Math.min(144, Math.floor((pw - 44 - closeWidth - 3 * tabGap) / 3));
  const tabs = [
    { id: 'rules', label: '正式规则' },
    { id: 'catalog', label: '本局图鉴' },
    { id: 'history', label: tabWidth < 94 ? '战报' : `战报 (${history.length})` },
  ];
  tabs.forEach((t, idx) => {
    const active = tab === t.id;
    const btn = makeSealButton(t.label, {
      width: tabWidth, height: 34, accent: active ? 0x1c8a64 : INK.secondary, solid: active,
      fontSize: tabWidth < 56 ? 11 : 12.6, radius: 9,
      onClick: () => onTab(t.id),
    });
    btn.position.set(px + 22 + idx * (tabWidth + tabGap), py + 12);
    root.addChild(btn);
  });

  const closeBtn = makeSealButton('关闭', {
    width: closeWidth, height: 34, accent: 0xcf4932, fontSize: 12.5, radius: 9, onClick: onClose,
  });
  closeBtn.position.set(px + pw - closeWidth - 22, py + 12);
  root.addChild(closeBtn);

  const showExport = tab === 'history' && onExport;
  const historyToolsH = showExport ? 40 : 0;
  if (showExport) {
    const exportBtn = makeSealButton('导出战报', {
      width: 110, height: 32, accent: INK.goldDeep, fontSize: 12.5, radius: 9, onClick: onExport,
    });
    exportBtn.position.set(px + pw - 132, py + headerH + 2);
    root.addChild(exportBtn);
  }

  const vx = px + 22;
  const vy = py + headerH + 10 + historyToolsH;
  const vw = pw - 44;
  const vh = ph - headerH - 24 - historyToolsH;
  const contentW = vw - 14;

  const vpBg = new PIXI.Graphics();
  vpBg.roundRect(vx - 4, vy - 4, vw + 8, vh + 8, 9)
    .fill({ color: INK.paperSoft, alpha: 0.55 })
    .stroke({ width: 0.9, color: INK.hairline });
  root.addChild(vpBg);

  const mask = new PIXI.Graphics();
  mask.rect(vx, vy, vw, vh).fill({ color: 0xffffff });
  root.addChild(mask);

  const body = new PIXI.Container();
  body.position.set(vx, vy);
  body.mask = mask;
  root.addChild(body);

  let y = 4;
  const maxChars = Math.max(40, Math.floor(contentW / 6.8));
  const addLine = (text, { size = 12.6, color = INK.primary, bold = false, gapAfter = 10, indent = 0 } = {}) => {
    const t = new PIXI.Text({
      text: wrapCjkText(text, maxChars - Math.floor(indent / 6)),
      style: {
        fontFamily: FONT_UI, fontSize: size, fontWeight: bold ? '800' : '400', fill: color, lineHeight: size + 7,
        wordWrap: true, breakWords: true, wordWrapWidth: contentW - 10 - indent,
      },
    });
    t.position.set(indent, y);
    t._itemTop = y;
    t._itemBottom = y + t.height;
    body.addChild(t);
    y += t.height + gapAfter;
  };

  if (tab === 'rules') {
    for (const para of RULES_VERBATIM) {
      const m = para.match(/^【([^】]+)】(.*)$/s);
      if (m) {
        const plate = buildUnifiedEntryPlate({
          variant: 'skill',
          title: m[1],
          entries: [m[2]],
          width: contentW,
          accentColor: INK.gold,
          fontSize: 12.5,
          lineHeight: 19.2,
        });
        plate.position.set(0, y);
        plate._itemTop = y;
        plate._itemBottom = y + plate._height;
        body.addChild(plate);
        y += plate._height + 10;
      } else {
        addLine(para, { size: 12.6, gapAfter: 12 });
      }
    }
  } else if (tab === 'catalog' && catalog) {
    const colGap = 12;
    const cardW = Math.floor((contentW - 8 - colGap) / 2);
    for (const pl of catalog.players || []) {
      const theme = SIDE_THEME[pl.side] || SIDE_THEME[1];
      addLine(`◆ ${theme.name}`, { size: 15, color: theme.accent, bold: true, gapAfter: 8 });
      for (const ch of pl.characters || []) {
        addLine(ch.name, { size: 14.5, color: INK.strong, bold: true, gapAfter: 8, indent: 2 });
        for (const p of [...(ch.faction_passives || []).map((x) => ({ ...x, _tag: '阵营被动' })), ...(ch.passives || []).map((x) => ({ ...x, _tag: '' }))]) {
          const plate = buildUnifiedEntryPlate({
            variant: 'passive',
            title: p.name || '被动',
            tagLabel: p._tag,
            entries: p.display_lines,
            width: contentW - 6,
            accentColor: p._tag ? theme.accent : INK.gold,
            fontSize: 12.4,
            lineHeight: 19,
          });
          plate.position.set(4, y);
          plate._itemTop = y;
          plate._itemBottom = y + plate._height;
          body.addChild(plate);
          y += plate._height + 7;
        }
        const chAccent = characterColors[ch.id] || null;
        const skList = ch.skills || [];
        for (let i = 0; i < skList.length; i += 2) {
          const leftCard = buildVerbatimCardPanel(skList[i], { side: pl.side, accentColor: chAccent, ownerName: ch.name, width: cardW, compact: true });
          leftCard.position.set(4, y);
          leftCard._itemTop = y;
          leftCard._itemBottom = y + leftCard._boxHeight;
          body.addChild(leftCard);
          let rowH = leftCard._boxHeight;
          if (i + 1 < skList.length) {
            const rightCard = buildVerbatimCardPanel(skList[i + 1], { side: pl.side, accentColor: chAccent, ownerName: ch.name, width: cardW, compact: true });
            rightCard.position.set(4 + cardW + colGap, y);
            rightCard._itemTop = y;
            rightCard._itemBottom = y + rightCard._boxHeight;
            body.addChild(rightCard);
            rowH = Math.max(rowH, rightCard._boxHeight);
          }
          y += rowH + 10;
        }
        y += 8;
      }
    }
    const statuses = Object.entries(catalog.statuses || {});
    if (statuses.length) {
      addLine('◆ 特殊状态', { size: 15, color: INK.gold, bold: true, gapAfter: 8 });
      for (const [name, list] of statuses) {
        const plate = buildUnifiedEntryPlate({
          variant: 'status',
          statusName: name,
          entries: list,
          width: contentW - 6,
          fontSize: 12.4,
          lineHeight: 19,
        });
        plate.position.set(4, y);
        plate._itemTop = y;
        plate._itemBottom = y + plate._height;
        body.addChild(plate);
        y += plate._height + 7;
      }
    }
  } else if (tab === 'history') {
    if (!history.length) {
      addLine('尚无战报。', { size: 12.8, color: INK.muted });
    } else {
      history.slice().reverse().forEach((line, i) => {
        const row = new PIXI.Container();
        const txt = new PIXI.Text({
          text: wrapCjkText(`${history.length - i}. ${line}`, maxChars - 3),
          style: {
            fontFamily: FONT_UI,
            fontSize: 12.5,
            fontWeight: i === 0 ? '800' : '400',
            fill: i === 0 ? INK.goldDeep : INK.primary,
            lineHeight: 19.5,
            wordWrap: true,
            breakWords: true,
            wordWrapWidth: contentW - 22,
          },
        });
        const rh = Math.ceil(txt.height) + 12;
        const rg = new PIXI.Graphics();
        rg.roundRect(0, 0, contentW, rh, 5)
          .fill({ color: i === 0 ? INK.goldBg : i % 2 === 0 ? INK.paper : INK.paperSoft, alpha: 0.92 })
          .stroke({ width: 0.75, color: i === 0 ? INK.gold : INK.hairline, alpha: 0.75 });
        rg.roundRect(0, 2, 3, rh - 4, 1.5).fill({ color: i === 0 ? INK.gold : INK.line });
        row.addChild(rg);
        txt.position.set(11, 6);
        row.addChild(txt);
        row.position.set(0, y);
        row._itemTop = y;
        row._itemBottom = y + rh;
        body.addChild(row);
        y += rh + 6;
      });
    }
  }

  const totalH = y + 12;
  const maxScroll = Math.max(0, totalH - vh);
  let curScroll = Math.max(0, Math.min(maxScroll, scrollY));
  let sb = null;

  const applyScroll = (nextY, emit = true) => {
    curScroll = Math.max(0, Math.min(maxScroll, nextY));
    body.y = vy - curScroll;
    cullVerticalItems(body, curScroll, vh, 240);
    if (sb) sb._updateThumb(curScroll);
    if (emit && onScrollChange) onScrollChange(curScroll);
    return curScroll;
  };
  applyScroll(curScroll, false);

  if (maxScroll > 0) {
    sb = makeSmoothScrollbar({
      x: vx + vw - 6,
      y: vy + 2,
      height: vh - 4,
      totalH,
      viewH: vh,
      scrollY: curScroll,
      accentColor: INK.gold,
      onChange: (val) => applyScroll(val, true),
    });
    root.addChild(sb);
  }

  root._maxScroll = maxScroll;
  root._rect = { x: px, y: py, w: pw, h: ph };
  root.setScroll = (nextY) => applyScroll(nextY, true);
  return root;
}

// ── 8. ILLUMINATED PILE INSPECTION FOLIO (TRUE O(1) SMOOTH SCROLL + DRAGGABLE SCROLLBAR) ──

export function buildPileOverlay(w, h, {
  title,
  side,
  cards = [],
  charNames = {},
  characterColors = {},
  scrollY = 0,
  onScrollChange = null,
  onClose,
}) {
  const root = new PIXI.Container();
  const theme = SIDE_THEME[side] || SIDE_THEME[1];

  const veil = new PIXI.Graphics();
  veil.rect(0, 0, w, h).fill({ color: 0xf4efe4, alpha: 0.9 });
  veil.eventMode = 'static';
  veil.on('pointertap', onClose);
  root.addChild(veil);

  const pw = Math.min(1080, w - 56);
  const ph = Math.min(680, h - 56);
  const px = (w - pw) / 2;
  const py = (h - ph) / 2;
  const headerH = 54;

  const frame = new PIXI.Graphics();
  drawFolioFrame(frame, px, py, pw, ph, {
    accent: theme.accent,
    bg: INK.paper,
    radius: 14,
    edgeDepth: 4.5,
    shadowAlpha: 0.32,
    topRibbonH: headerH - 2,
    ribbonFill: theme.warmTint,
    cornerDiamonds: true,
    diamondColor: INK.gold,
  });
  drawLightStar(frame, px + 30, py + headerH / 2, 9, theme.accent, 0.92);
  frame.eventMode = 'static';
  frame.on('pointertap', (e) => e.stopPropagation());
  root.addChild(frame);

  const head = new PIXI.Text({
    text: `${title} · ${cards.length} 张`,
    style: { fontFamily: FONT_UI, fontSize: 18, fontWeight: '900', fill: theme.accent, letterSpacing: 1 },
  });
  head.anchor.set(0, 0.5);
  head.position.set(px + 48, py + headerH / 2);
  root.addChild(head);

  const closeBtn = makeSealButton('关闭', {
    width: 82, height: 32, accent: INK.secondary, fontSize: 12.2, radius: 9, onClick: onClose,
  });
  closeBtn.position.set(px + pw - 102, py + (headerH - 32) / 2);
  root.addChild(closeBtn);

  const vx = px + 20;
  const vy = py + headerH + 10;
  const vw = pw - 40;
  const vh = ph - headerH - 24;
  const innerW = vw - 14;

  const vpBg = new PIXI.Graphics();
  vpBg.roundRect(vx - 4, vy - 4, vw + 8, vh + 8, 9)
    .fill({ color: INK.paperSoft, alpha: 0.55 })
    .stroke({ width: 0.9, color: INK.hairline });
  root.addChild(vpBg);

  const mask = new PIXI.Graphics();
  mask.rect(vx, vy, vw, vh).fill({ color: 0xffffff });
  root.addChild(mask);

  const body = new PIXI.Container();
  body.position.set(vx, vy);
  body.mask = mask;
  root.addChild(body);

  let cy = 6;
  if (!cards.length) {
    const empty = new PIXI.Text({
      text: '当前牌区暂无卡牌',
      style: { fontFamily: FONT_UI, fontSize: 14, fontWeight: '700', fill: INK.muted },
    });
    empty.anchor.set(0.5);
    empty.position.set(innerW / 2, vh / 2);
    body.addChild(empty);
  } else {
    const gap = 16;
    const cols = Math.max(2, Math.min(cards.length, Math.floor((innerW + gap) / 214)));
    const cardW = Math.min(208, Math.floor((innerW - gap * (cols - 1)) / cols));
    const portraitH = Math.round(cardW * 1.40);
    for (let i = 0; i < cards.length; i += cols) {
      const rowCount = Math.min(cols, cards.length - i);
      const rowW = rowCount * cardW + (rowCount - 1) * gap;
      const startX = (innerW - rowW) / 2;
      let rowH = 0;
      for (let c = 0; c < rowCount; c++) {
        const card = cards[i + c];
        const spr = buildFullCard(card, {
          side,
          accentColor: characterColors[card.character_id] || null,
          ownerName: charNames[card.character_id] || '',
          showOwner: true,
          width: cardW,
          fixedHeight: portraitH,
          dense: true,
          centered: false,
          legal: true,
        });
        spr.position.set(startX + c * (cardW + gap), cy);
        spr._itemTop = cy;
        spr._itemBottom = cy + spr._boxHeight;
        spr._interactiveItem = true;
        spr.eventMode = 'static';
        spr.on('pointertap', (e) => e.stopPropagation());
        body.addChild(spr);
        rowH = Math.max(rowH, spr._boxHeight);
      }
      cy += rowH + gap;
    }
  }

  const totalH = cy + 8;
  const maxScroll = Math.max(0, totalH - vh);
  let curScroll = Math.max(0, Math.min(maxScroll, scrollY));
  let sb = null;

  const applyScroll = (nextY, emit = true) => {
    curScroll = Math.max(0, Math.min(maxScroll, nextY));
    body.y = vy - curScroll;
    cullVerticalItems(body, curScroll, vh, 280);
    if (sb) sb._updateThumb(curScroll);
    if (emit && onScrollChange) onScrollChange(curScroll);
    return curScroll;
  };
  applyScroll(curScroll, false);

  if (maxScroll > 0) {
    sb = makeSmoothScrollbar({
      x: vx + vw - 6,
      y: vy + 2,
      height: vh - 4,
      totalH,
      viewH: vh,
      scrollY: curScroll,
      accentColor: theme.accent,
      onChange: (val) => applyScroll(val, true),
    });
    root.addChild(sb);
  }

  root._maxScroll = maxScroll;
  root._rect = { x: px, y: py, w: pw, h: ph };
  root.setScroll = (nextY) => applyScroll(nextY, true);
  return root;
}

// ── 9. CEREMONIAL VICTORY/DEFEAT CREST & MATCH LEDGER (FINISH OVERLAY) ──

export function buildFinishOverlay(w, h, { winnerSide, winnerName, turn = 1, history = [], onRematch, onNewRoster, onExport }) {
  const root = new PIXI.Container();
  const theme = winnerSide ? SIDE_THEME[winnerSide] : { accent: INK.gold, border: INK.gold, softBg: INK.goldBg, warmTint: INK.paperSoft, name: '双方平局' };
  const cx = w / 2;
  const cy = h / 2;

  const veil = new PIXI.Graphics();
  veil.rect(0, 0, w, h).fill({ color: 0xf4efe4, alpha: 0.91 });
  const matPad = Math.min(26, Math.floor(Math.min(w, h) * 0.03));
  veil.roundRect(matPad, matPad, w - matPad * 2, h - matPad * 2, 16)
    .stroke({ width: 1.2, color: INK.line, alpha: 0.8 });
  drawCornerDiamonds(veil, matPad, matPad, w - matPad * 2, h - matPad * 2, 12, 3.6, INK.gold, 0.6);
  veil.eventMode = 'static';
  root.addChild(veil);

  const pw = Math.min(580, w - 64);
  const ph = Math.min(454, h - 64);
  const px = cx - pw / 2;
  const py = cy - ph / 2;

  const plaque = new PIXI.Graphics();
  // Ceremonial top pennant & bottom ribbon tail
  plaque.poly([cx - 88, py, cx + 88, py, cx + 70, py - 15, cx - 70, py - 15])
    .fill({ color: theme.accent, alpha: 0.92 });
  plaque.poly([cx - 64, py + ph + 5, cx + 64, py + ph + 5, cx + 46, py + ph + 17, cx - 46, py + ph + 17])
    .fill({ color: INK.gold, alpha: 0.84 });

  drawFolioFrame(plaque, px, py, pw, ph, {
    accent: theme.accent,
    bg: INK.paper,
    radius: 16,
    edgeDepth: 5,
    shadowAlpha: 0.34,
    cornerDiamonds: true,
    diamondColor: INK.gold,
  });

  // Victory Crest Compass + Layered Star Medallion
  const crestY = py + 66;
  drawHeraldicCompass(plaque, cx, crestY, 44, theme.accent, INK.line);
  drawWaxSealBadge(plaque, cx, crestY, 24, theme.softBg || INK.goldBg, theme.accent);
  drawLightStar(plaque, cx, crestY, 19, theme.accent, 0.96);

  drawDiamondDivider(plaque, px + 34, px + pw - 34, py + 150, INK.hairline, INK.gold);
  root.addChild(plaque);

  const head = new PIXI.Text({
    text: winnerSide ? `${winnerName || theme.name} 获胜` : '双方平局',
    style: { fontFamily: FONT_UI, fontSize: 30, fontWeight: '900', fill: INK.strong, letterSpacing: 3 },
  });
  head.anchor.set(0.5);
  head.position.set(cx, py + 128);
  root.addChild(head);

  // Match Summary Stat Pills (Turn Count + Chronicle Count)
  const badges = [
    { label: `历经 ${turn} 回合`, col: theme.accent, bg: theme.softBg || INK.goldBg },
    { label: `战报 ${history.length} 条`, col: INK.goldDeep, bg: INK.goldBg },
  ];
  const badgeG = new PIXI.Graphics();
  root.addChild(badgeG);
  const badgeNodes = badges.map((b) => {
    const t = new PIXI.Text({
      text: b.label,
      style: { fontFamily: FONT_UI, fontSize: 11.8, fontWeight: '800', fill: b.col },
    });
    return { ...b, t, w: Math.ceil(t.width) + 20 };
  });
  const totalBadgeW = badgeNodes.reduce((s, b) => s + b.w, 0) + (badgeNodes.length - 1) * 12;
  let bx = cx - totalBadgeW / 2;
  const by = py + 162;
  for (const b of badgeNodes) {
    badgeG.roundRect(bx, by, b.w, 25, 12.5).fill({ color: b.bg }).stroke({ width: 1.1, color: b.col, alpha: 0.7 });
    b.t.anchor.set(0.5);
    b.t.position.set(bx + b.w / 2, by + 12.5);
    root.addChild(b.t);
    bx += b.w + 12;
  }

  // Battle Recap Ledger (Inset Vellum Scroll Box with Recent Verbatim Highlights)
  const lx = px + 26;
  const ly = py + 198;
  const lw = pw - 52;
  const lh = Math.max(42, ph - 274);

  const ledgerG = new PIXI.Graphics();
  ledgerG.roundRect(lx, ly, lw, lh, 9)
    .fill({ color: INK.paperSoft, alpha: 0.9 })
    .stroke({ width: 1, color: INK.line });
  root.addChild(ledgerG);

  const lMask = new PIXI.Graphics();
  lMask.rect(lx + 4, ly + 4, lw - 8, lh - 8).fill({ color: 0xffffff });
  root.addChild(lMask);

  const lBody = new PIXI.Container();
  lBody.position.set(lx + 10, ly + 8);
  lBody.mask = lMask;
  root.addChild(lBody);

  const highlights = history.slice(-12).reverse();
  const lInnerW = lw - 30;
  let lcy = 0;

  if (!highlights.length) {
    const empty = new PIXI.Text({
      text: '对局已终结。',
      style: { fontFamily: FONT_UI, fontSize: 12.5, fill: INK.muted },
    });
    empty.anchor.set(0.5);
    empty.position.set(lInnerW / 2, (lh - 16) / 2);
    lBody.addChild(empty);
  } else {
    highlights.forEach((line, i) => {
      const isLatest = i === 0;
      const row = new PIXI.Container();
      const idxNo = history.length - i;
      const txt = new PIXI.Text({
        text: wrapCjkText(`${idxNo}. ${line}`, Math.max(24, Math.floor(lInnerW / 12.4))),
        style: {
          fontFamily: FONT_UI,
          fontSize: 12.3,
          fontWeight: isLatest ? '800' : '400',
          fill: isLatest ? theme.accent : INK.primary,
          lineHeight: 18.5,
          wordWrap: true,
          breakWords: true,
          wordWrapWidth: lInnerW - 14,
        },
      });
      const rh = Math.ceil(txt.height) + 8;
      const rg = new PIXI.Graphics();
      if (isLatest) {
        rg.roundRect(0, 0, lInnerW, rh, 5).fill({ color: theme.softBg || INK.goldBg });
      }
      rg.poly([5, rh / 2 - 2.6, 7.6, rh / 2, 5, rh / 2 + 2.6, 2.4, rh / 2])
        .fill({ color: isLatest ? theme.accent : INK.gold, alpha: isLatest ? 0.95 : 0.65 });
      row.addChild(rg);
      txt.position.set(13, 4);
      row.addChild(txt);
      row.position.set(0, lcy);
      lBody.addChild(row);
      lcy += rh + 4;
    });
  }

  const lViewH = lh - 14;
  const lTotalH = lcy + 4;
  const lMaxScroll = Math.max(0, lTotalH - lViewH);
  let lCurScroll = 0;
  let lSb = null;
  const setLedgerScroll = (nextY) => {
    lCurScroll = Math.max(0, Math.min(lMaxScroll, nextY));
    lBody.y = ly + 8 - lCurScroll;
    if (lSb) lSb._updateThumb(lCurScroll);
    return lCurScroll;
  };
  if (lMaxScroll > 0) {
    lSb = makeSmoothScrollbar({
      x: lx + lw - 10,
      y: ly + 6,
      height: lh - 12,
      totalH: lTotalH,
      viewH: lViewH,
      scrollY: 0,
      accentColor: theme.accent,
      onChange: (val) => setLedgerScroll(val),
    });
    root.addChild(lSb);
  }

  const actions = [
    { label: '原阵容再战', onClick: onRematch, accent: theme.accent, solid: true },
    { label: '重新选人', onClick: onNewRoster, accent: INK.gold },
    { label: '导出战报', onClick: onExport, accent: INK.goldDeep },
  ].filter(action => action.onClick);
  const btnY = py + ph - 60;
  const btnGap = pw < 420 ? 8 : 20;
  const gapsW = Math.max(0, actions.length - 1) * btnGap;
  const btnW = Math.min(172, Math.floor((pw - 32 - gapsW) / Math.max(1, actions.length)));
  const actionX = cx - (actions.length * btnW + gapsW) / 2;
  for (const [index, { label, onClick, accent, solid }] of actions.entries()) {
    const button = makeSealButton(label, {
      width: btnW, height: 42, accent, solid, fontSize: btnW < 90 ? 12 : 14, radius: 11, onClick,
    });
    button.position.set(actionX + index * (btnW + btnGap), btnY);
    root.addChild(button);
  }

  root._maxScroll = lMaxScroll;
  root.setScroll = setLedgerScroll;
  return root;
}
