/**
 * Bright warm-paper pure-WebGL Canvas overlays & Pinned Character Dossier.
 * ZERO DOM, ZERO black, ZERO blue-purple, ZERO paraphrasing, ZERO filler annotations.
 */

import * as PIXI from '../vendor/pixi.min.mjs';
import {
  FONT_UI,
  FONT_NUM,
  INK,
  SIDE_THEME,
  RANK_LABEL,
  RANK_COLOR,
  DIE_STYLE,
  SHIELD_STYLE,
  STATUS_COLORS,
  OFFICIAL_STATUS_RULES,
  formatDieRange,
  wrapCjkText,
  drawDieIcon,
  drawStatusIcon,
  drawShieldGlyph,
  drawLightStar,
  buildCardFront,
  buildFullCard,
  buildVerbatimCardPanel,
  buildRichVerbatimText,
  buildUnifiedEntryPlate,
  buildUnifiedSkillRow,
} from './card_print.js';
import { createCharacterActor, actorPalette } from './stage_actors.js';

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
  const draw = (hovered) => {
    bg.clear();
    bg.roundRect(2, 4, width, height, radius).fill({ color: INK.shadow, alpha: disabled ? 0.14 : 0.28 });
    const bgCol = disabled ? 0xebe5d9 : solid ? accent : hovered ? 0xfbf6eb : fill;
    bg.roundRect(0, 0, width, height, radius)
      .fill({ color: bgCol, alpha: hovered && solid ? 0.9 : 1 })
      .stroke({ width: hovered && !disabled ? 2.2 : 1.5, color: disabled ? INK.line : accent });
  };
  draw(false);
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
    c.eventMode = 'static';
    c.cursor = 'pointer';
    c.on('pointerover', () => draw(true));
    c.on('pointerout', () => draw(false));
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
  trackG.roundRect(-3, 0, 10, trackH, 5).fill({ color: INK.paper, alpha: 0.001 });
  trackG.roundRect(0, 0, 4, trackH, 2).fill({ color: INK.hairline, alpha: 0.9 });
  track.addChild(trackG);

  const thumbG = new PIXI.Graphics();
  const drawThumb = (active) => {
    thumbG.clear();
    thumbG.roundRect(-1, 0, 6, thumbH, 3).fill({ color: accentColor, alpha: active ? 0.95 : 0.72 });
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

/**
 * Library of Ruina / Limbus Company Side-Docked Physical Hero Inspector:
 *  - Anchored cleanly to that side (P1 Left / P2 Right) BELOW cost/piles and ABOVE hand tray!
 *  - ZERO overlap with the central duel bridge (① ↓ ② ↓ ③), opponent, cost crystals, or hand cards!
 *  - Opens ONLY on explicit click (NEVER surprise hover popups!)
 *  - CONSTANT comfortable reading font (12.5px, NEVER shrinks even for 3,000+ word passives!)
 *  - True O(1) setScroll(y) + draggable scrollbar (zero Pixi rebuilds, buttery 60fps scroll!)
 */
export function buildHeroSidePanel({
  character,
  side,
  catalogChar,
  catalogStatuses,
  teamChars = [],
  x,
  y,
  width,
  height,
  tab = 'passives',
  canSetTarget = false,
  isDefaultTarget = false,
  scrollY = 0,
  onSwitchChar,
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

  // Tactile Tabletop Physical Card Frame (stacked-paper bottom edge bevel + top semantic bar)
  const frame = new PIXI.Graphics();
  frame.roundRect(3, 7, width, height, 12).fill({ color: INK.shadow, alpha: 0.24 });
  frame.roundRect(0, 3, width, height, 11).fill({ color: 0xe3dac9 });
  frame.roundRect(0, 0, width, height, 11)
    .fill({ color: INK.paper, alpha: 0.99 })
    .stroke({ width: 1.6, color: theme.accent });
  frame.roundRect(2, 1.5, width - 4, 4, 2).fill({ color: theme.accent });
  frame.eventMode = 'static';
  frame.on('pointertap', (e) => e.stopPropagation());
  root.addChild(frame);

  let curY = 9;

  // Optional Teammate Switcher Strip (2v2 / 3v3)
  if (teamChars.length > 1) {
    let tx = 12;
    const gap = 5;
    const maxPillW = Math.floor((width - 24 - gap * (teamChars.length - 1)) / teamChars.length);
    for (const tc of teamChars) {
      const isCur = tc.id === character.id;
      const btn = makeSealButton(tc.name, {
        width: maxPillW,
        height: 22,
        accent: theme.accent,
        solid: isCur,
        fontSize: 10.8,
        radius: 6,
        onClick: isCur ? null : () => onSwitchChar && onSwitchChar(tc.id),
      });
      btn.position.set(tx, curY);
      root.addChild(btn);
      tx += maxPillW + gap;
    }
    curY += 27;
  }

  // Compact Hero Identity Header (living 60fps WebGL portrait + Name + Faction/Rank + Live HP/Speed/Duels/Cost)
  const artSize = 54;
  const artX = 12;
  const artY = curY + 2;
  const artG = new PIXI.Graphics();
  artG.roundRect(artX, artY, artSize, artSize, 9)
    .fill({ color: pal.highlight })
    .stroke({ width: 1.1, color: pal.primary, alpha: 0.45 });
  artG.ellipse(artX + artSize / 2, artY + artSize - 9, artSize * 0.32, 4.5)
    .fill({ color: INK.paper, alpha: 0.78 });
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

  const metaParts = [character.faction || '', RANK_LABEL[character.rank] || ''].filter(Boolean).join(' · ');
  if (metaParts) {
    const metaTxt = new PIXI.Text({
      text: metaParts,
      style: { fontFamily: FONT_UI, fontSize: 10.4, fontWeight: '800', fill: theme.accent },
    });
    metaTxt.anchor.set(1, 0);
    metaTxt.position.set(width - 12, curY + 4);
    root.addChild(metaTxt);
  }

  const hpY = curY + 23;
  const hpBarW = Math.max(80, infoW - 48);
  const ratio = Math.max(0, Math.min(1, (character.hp ?? 0) / Math.max(1, character.max_hp || 1)));
  const hpG = new PIXI.Graphics();
  hpG.roundRect(infoX, hpY, hpBarW, 10, 5).fill({ color: INK.paperTint }).stroke({ width: 0.8, color: INK.line });
  if (ratio > 0) {
    hpG.roundRect(infoX + 1, hpY + 1, Math.max(5, (hpBarW - 2) * ratio), 8, 4)
      .fill({ color: ratio < 0.34 ? 0xd13f20 : theme.accent });
  }
  root.addChild(hpG);

  const hpTxt = new PIXI.Text({
    text: `${character.hp}/${character.max_hp}`,
    style: { fontFamily: FONT_NUM, fontSize: 11, fontWeight: '900', fill: INK.strong },
  });
  hpTxt.anchor.set(1, 0.5);
  hpTxt.position.set(width - 12, hpY + 5);
  root.addChild(hpTxt);

  const subStats = new PIXI.Text({
    text: `速度 ${character.speed ?? 0}  ·  交锋 ${character.duels?.used ?? '?'}/${character.duels?.max ?? 1}  ·  个人费 ${character.cost?.available ?? 0}`,
    style: { fontFamily: FONT_UI, fontSize: 10.6, fontWeight: '800', fill: INK.secondary },
  });
  subStats.position.set(infoX, curY + 38);
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
      if (bx + 48 > width - 12) break;
      const col = STATUS_COLORS[sName] || INK.secondary;
      const burst = sName === '裂血' && character.bleed_burst;
      const stTxt = new PIXI.Text({
        text: `${sName}${sVal}`,
        style: { fontFamily: FONT_UI, fontSize: 10.4, fontWeight: '800', fill: col },
      });
      const bw = Math.ceil(stTxt.width) + 10;
      badgeG.roundRect(bx, curY, bw, 19, 4)
        .fill({ color: burst ? 0xfce0e4 : INK.paperSoft })
        .stroke({ width: burst ? 1.5 : 0.9, color: col });
      stTxt.anchor.set(0.5);
      stTxt.position.set(bx + bw / 2, curY + 9.5);
      root.addChild(stTxt);
      bx += bw + 4;
    }
    curY += 24;
  }

  // Tabs & Actions Row: [被动与状态] [技能牌组(N)] ... [集火] [✕]
  const skills = catalogChar?.skills || [];
  const tabH = 25;
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

  // Scrollable Reading Viewport (FIXED 12.5px readable font — NEVER shrinks, O(1) smooth scroll!)
  const vx = 10;
  const vy = curY;
  const vw = width - 20;
  const vh = Math.max(96, height - vy - 10);

  const vpBg = new PIXI.Graphics();
  vpBg.roundRect(vx, vy, vw, vh, 8)
    .fill({ color: INK.paperSoft, alpha: 0.65 })
    .stroke({ width: 0.9, color: INK.hairline });
  root.addChild(vpBg);

  const maskG = new PIXI.Graphics();
  maskG.rect(vx + 2, vy + 2, vw - 4, vh - 4).fill({ color: 0xffffff });
  root.addChild(maskG);

  const content = new PIXI.Container();
  content.mask = maskG;
  root.addChild(content);

  const padIn = 10;
  const innerW = vw - padIn * 2 - 8;
  let cy = padIn;

  if (tab === 'skills') {
    for (const sk of skills) {
      const row = buildUnifiedSkillRow(sk, { width: innerW, side, active: false });
      row.position.set(vx + padIn, vy + cy);
      row.eventMode = 'static';
      row.cursor = 'pointer';
      row.on('pointerover', () => {
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
      const entries = (fp.entries && fp.entries.length) ? fp.entries : (fp.description ? [fp.description] : []);
      const plate = buildUnifiedEntryPlate({
        variant: 'passive',
        title: fp.name || '阵营被动',
        tagLabel: '阵营被动',
        entries,
        width: innerW,
        accentColor: theme.accent,
        fontSize: 12.4,
        lineHeight: 19.2,
      });
      plate.position.set(vx + padIn, vy + cy);
      content.addChild(plate);
      cy += plate._height + 8;
    }

    for (const p of rolePassives) {
      const entries = (p.entries && p.entries.length) ? p.entries : (p.description ? [p.description] : []);
      const plate = buildUnifiedEntryPlate({
        variant: 'passive',
        title: p.name || '角色被动',
        entries,
        width: innerW,
        accentColor: INK.gold,
        fontSize: 12.4,
        lineHeight: 19.2,
      });
      plate.position.set(vx + padIn, vy + cy);
      content.addChild(plate);
      cy += plate._height + 8;
    }

    if (statuses.length) {
      if (cy > padIn) cy += 4;
      const stHead = new PIXI.Text({
        text: '当前状态规则',
        style: { fontFamily: FONT_UI, fontSize: 12, fontWeight: '800', fill: INK.secondary },
      });
      stHead.position.set(vx + padIn, vy + cy);
      content.addChild(stHead);
      cy += 21;

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
          fontSize: 12,
          lineHeight: 18.4,
        });
        plate.position.set(vx + padIn, vy + cy);
        content.addChild(plate);
        cy += plate._height + 7;
      }
    }

    if (!factionPassives.length && !rolePassives.length && !statuses.length) {
      const empty = new PIXI.Text({
        text: '当前角色无被动技能与生效状态。',
        style: { fontFamily: FONT_UI, fontSize: 12.5, fill: INK.muted },
      });
      empty.position.set(vx + padIn, vy + cy + 8);
      content.addChild(empty);
      cy += 34;
    }
  }

  const totalH = cy + padIn;
  const maxScroll = Math.max(0, totalH - vh);
  let curScroll = Math.max(0, Math.min(maxScroll, scrollY));
  content.y = -curScroll;

  let sb = null;
  const setScroll = (nextY) => {
    curScroll = Math.max(0, Math.min(maxScroll, nextY));
    content.y = -curScroll;
    if (sb) sb._updateThumb(curScroll);
    if (onScrollChange) onScrollChange(curScroll);
    return curScroll;
  };

  if (maxScroll > 0) {
    sb = makeSmoothScrollbar({
      x: vx + vw - 7,
      y: vy + 6,
      height: vh - 12,
      totalH,
      viewH: vh,
      scrollY: curScroll,
      accentColor: theme.accent,
      onChange: (val) => setScroll(val),
    });
    root.addChild(sb);
  }

  root._actors = actors;
  root._maxScroll = maxScroll;
  root._rect = { x, y, w: width, h: height };
  root.setScroll = setScroll;
  return root;
}

/**
 * Limbus-style Dual-Side Squad Passive Overview Sheet (Tab / 被动 button):
 *  - Sits cleanly above the hand tray (NO full-screen blackout — hand cards remain visible!)
 *  - Left Column = P1, Right Column = P2 (~560px each), CONSTANT readable font size (12.2px — NEVER shrinks!)
 *  - INDEPENDENT Left & Right scroll viewports + independent draggable scrollbars!
 *    Rolling wheel on the left side scrolls ONLY P1; rolling on the right side scrolls ONLY P2!
 *  - Click any character strip to jump straight into their Side Hero Inspector!
 */
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
}) {
  const root = new PIXI.Container();
  root.position.set(x, y);

  const padX = 16;
  const colGap = 24;
  const colW = Math.floor((width - padX * 2 - colGap) / 2);
  const innerColW = colW - 12; // reserve clean lane for each column's own scrollbar
  const headerH = 38;
  const splitX = x + padX + colW + colGap / 2;

  const builtCols = {};
  let maxColH = 0;

  [1, 2].forEach((side, colIdx) => {
    const player = players.find((p) => p.side === side);
    const theme = SIDE_THEME[side] || SIDE_THEME[1];
    const colX = padX + colIdx * (colW + colGap);
    const colContainer = new PIXI.Container();
    let cy = 4;

    if (player) {
      const sTxt = new PIXI.Text({
        text: `${player.name}  ·  速${Number(player.speed || 0).toFixed(player.speed % 1 ? 1 : 0)}  ·  费${player.cost?.available ?? 0}`,
        style: { fontFamily: FONT_UI, fontSize: 12.5, fontWeight: '900', fill: theme.accent },
      });
      sTxt.position.set(2, cy);
      colContainer.addChild(sTxt);
      cy += 22;

      const chars = player.characters || [];

      // Deduplicated Faction Passives
      const seenFaction = new Set();
      for (const ch of chars) {
        const cat = catalogById.get(ch.id);
        for (const fp of cat?.faction_passives || []) {
          const key = fp.name || (fp.entries || []).join('|');
          if (seenFaction.has(key)) continue;
          seenFaction.add(key);
          const entries = (fp.entries && fp.entries.length) ? fp.entries : (fp.description ? [fp.description] : []);
          const plate = buildUnifiedEntryPlate({
            variant: 'passive',
            title: fp.name || '阵营被动',
            tagLabel: '阵营被动',
            entries,
            width: innerColW,
            accentColor: theme.accent,
            fontSize: 12.2,
            lineHeight: 18.8,
          });
          plate.position.set(0, cy);
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
        const rhH = 27;
        const rhG = new PIXI.Graphics();
        const drawRh = (hov) => {
          rhG.clear();
          rhG.roundRect(0, 0, innerColW, rhH, 6)
            .fill({ color: hov ? theme.warmTint : INK.paperSoft })
            .stroke({ width: hov ? 1.3 : 0.85, color: hov ? theme.accent : INK.hairline });
          rhG.circle(12, rhH / 2, 6).fill({ color: pal.primary });
        };
        drawRh(false);
        rowHead.addChild(rhG);

        const stSummary = Object.entries(ch.statuses || {}).map(([n, v]) => `${n}${v}`).join(' ');
        const chTxt = new PIXI.Text({
          text: `${ch.name}${ch.alive ? '' : ' [亡]'} · 生命 ${ch.hp}/${ch.max_hp}${stSummary ? ' · ' + stSummary : ''}`,
          style: { fontFamily: FONT_UI, fontSize: 12, fontWeight: '800', fill: ch.alive ? INK.strong : INK.muted },
        });
        chTxt.position.set(24, 5);
        rowHead.addChild(chTxt);

        const openLink = new PIXI.Text({
          text: '角色牌面 ↗',
          style: { fontFamily: FONT_UI, fontSize: 10.8, fontWeight: '800', fill: theme.accent },
        });
        openLink.anchor.set(1, 0.5);
        openLink.position.set(innerColW - 10, rhH / 2);
        rowHead.addChild(openLink);

        rowHead.eventMode = 'static';
        rowHead.cursor = 'pointer';
        rowHead.on('pointerover', () => drawRh(true));
        rowHead.on('pointerout', () => drawRh(false));
        rowHead.on('pointertap', (e) => {
          e.stopPropagation();
          if (onOpenHeroSheet) onOpenHeroSheet(ch.id, side);
        });
        colContainer.addChild(rowHead);
        cy += rhH + 6;

        for (const p of rolePassives) {
          const entries = (p.entries && p.entries.length) ? p.entries : (p.description ? [p.description] : []);
          const plate = buildUnifiedEntryPlate({
            variant: 'passive',
            title: p.name || '角色被动',
            entries,
            width: innerColW - 6,
            accentColor: INK.gold,
            fontSize: 12.2,
            lineHeight: 18.8,
          });
          plate.position.set(6, cy);
          colContainer.addChild(plate);
          cy += plate._height + 6;
        }
        cy += 5;
      }
    }

    builtCols[side] = { colContainer, colX, totalH: cy + 8, theme };
    maxColH = Math.max(maxColH, cy);
  });

  const drawerH = Math.min(maxHeight, Math.max(150, headerH + maxColH + 14));
  const vh = drawerH - headerH - 10;

  const frame = new PIXI.Graphics();
  frame.roundRect(4, 8, width, drawerH, 13).fill({ color: INK.shadow, alpha: 0.26 });
  frame.roundRect(0, 0, width, drawerH, 13)
    .fill({ color: INK.paper, alpha: 0.99 })
    .stroke({ width: 1.6, color: INK.gold, alpha: 0.9 });
  frame.roundRect(1.5, 1.5, width - 3, headerH - 1, 11).fill({ color: INK.paperSoft });
  frame.moveTo(12, headerH + 1).lineTo(width - 12, headerH + 1).stroke({ width: 1, color: INK.hairline });
  frame.eventMode = 'static';
  frame.on('pointertap', (e) => e.stopPropagation());
  root.addChild(frame);

  const title = new PIXI.Text({
    text: '双方被动总览',
    style: { fontFamily: FONT_UI, fontSize: 14, fontWeight: '900', fill: INK.strong },
  });
  title.position.set(16, 9);
  root.addChild(title);

  const hint = new PIXI.Text({
    text: '左右栏可独立滚动 · Tab / 点外部 / 右键收起',
    style: { fontFamily: FONT_UI, fontSize: 10.8, fontWeight: '700', fill: INK.muted },
  });
  hint.position.set(16 + title.width + 12, 11);
  root.addChild(hint);

  const closeBtn = makeSealButton('关闭', {
    width: 60, height: 25, accent: INK.secondary, fontSize: 11.2, radius: 12, onClick: onClose,
  });
  closeBtn.position.set(width - 72, 6.5);
  root.addChild(closeBtn);

  const div = new PIXI.Graphics();
  div.moveTo(padX + colW + colGap / 2, headerH + 6).lineTo(padX + colW + colGap / 2, drawerH - 10)
    .stroke({ width: 1, color: INK.hairline });
  root.addChild(div);

  // Mount Left (P1) & Right (P2) as INDEPENDENT masked scroll columns with independent scrollbars!
  const baseY = headerH + 5;
  const colControllers = {};
  const maxScrollBySide = { 1: 0, 2: 0 };

  for (const side of [1, 2]) {
    const info = builtCols[side];
    const maxS = Math.max(0, info.totalH - vh);
    maxScrollBySide[side] = maxS;
    let curS = Math.max(0, Math.min(maxS, side === 1 ? scrollY1 : scrollY2));

    const maskG = new PIXI.Graphics();
    maskG.rect(info.colX - 2, headerH + 3, innerColW + 4, vh).fill({ color: 0xffffff });
    root.addChild(maskG);

    info.colContainer.position.set(info.colX, baseY - curS);
    info.colContainer.mask = maskG;
    root.addChild(info.colContainer);

    let sb = null;
    const setSideScroll = (nextY) => {
      curS = Math.max(0, Math.min(maxS, nextY));
      info.colContainer.y = baseY - curS;
      if (sb) sb._updateThumb(curS);
      if (onScrollChange) onScrollChange(side, curS);
      return curS;
    };

    if (maxS > 0) {
      sb = makeSmoothScrollbar({
        x: info.colX + innerColW + 4,
        y: headerH + 5,
        height: vh - 6,
        totalH: info.totalH,
        viewH: vh,
        scrollY: curS,
        accentColor: info.theme.accent,
        onChange: (val) => setSideScroll(val),
      });
      root.addChild(sb);
    }

    colControllers[side] = { setScroll: setSideScroll, getScroll: () => curS, maxScroll: maxS };
  }

  root._maxScrollBySide = maxScrollBySide;
  root._splitX = splitX;
  root._rect = { x, y, w: width, h: drawerH };
  root.setSideScroll = (side, nextY) => colControllers[side]?.setScroll(nextY);
  return root;
}

export function buildHandoffOverlay(w, h, { activeSide, eligibleSides, onReady }) {
  const root = new PIXI.Container();
  const side = activeSide || (eligibleSides && eligibleSides[0]) || 1;
  const theme = SIDE_THEME[side] || SIDE_THEME[1];

  const veil = new PIXI.Graphics();
  veil.rect(0, 0, w, h).fill({ color: 0xf5f1e7, alpha: 0.96 });
  const cx = w / 2;
  const cy = h / 2;
  veil.circle(cx, cy, 152).stroke({ width: 1.5, color: theme.border, alpha: 0.45 });
  drawLightStar(veil, cx, cy - 66, 28, theme.accent, 0.92);
  veil.eventMode = 'static';
  root.addChild(veil);

  const head = new PIXI.Text({
    text: `${theme.name}`,
    style: { fontFamily: FONT_UI, fontSize: 32, fontWeight: '800', fill: INK.primary, letterSpacing: 3 },
  });
  head.anchor.set(0.5);
  head.position.set(cx, cy - 4);
  root.addChild(head);

  const seats = eligibleSides && eligibleSides.length > 1 ? eligibleSides : [side];
  const btnW = 176;
  const gap = 20;
  const totalW = seats.length * btnW + (seats.length - 1) * gap;
  seats.forEach((s, idx) => {
    const st = SIDE_THEME[s] || SIDE_THEME[1];
    const btn = makeSealButton(`${st.name} 接手`, {
      width: btnW, height: 46, accent: st.accent, solid: true, fontSize: 15,
      onClick: () => onReady(s),
    });
    btn.position.set(cx - totalW / 2 + idx * (btnW + gap), cy + 48);
    root.addChild(btn);
  });

  return root;
}

export function buildDrawSelectOverlay(w, h, { prompt, selectedIds, onToggle, onConfirm }) {
  const root = new PIXI.Container();
  const theme = SIDE_THEME[prompt.side] || SIDE_THEME[1];

  const veil = new PIXI.Graphics();
  veil.rect(0, 0, w, h).fill({ color: 0xf5f1e7, alpha: 0.965 });
  veil.eventMode = 'static';
  root.addChild(veil);

  const cx = w / 2;
  const title = new PIXI.Text({
    text: `${theme.name} · 选 ${prompt.discard_count} 张置底（${selectedIds.size}/${prompt.discard_count}）`,
    style: { fontFamily: FONT_UI, fontSize: 21, fontWeight: '800', fill: theme.accent },
  });
  title.anchor.set(0.5);
  title.position.set(cx, 56);
  root.addChild(title);

  const count = Math.max(1, prompt.candidates.length);
  const gap = 16;
  const cardW = Math.max(192, Math.min(212, Math.floor((w - 64 - gap * (count - 1)) / count)));
  const portraitH = Math.round(cardW * 1.40);
  const totalW = count * cardW + (count - 1) * gap;
  const startX = cx - totalW / 2;

  // Build ALL candidate cards with STRICT fixed vertical physical card proportions (1 : 1.40, NEVER stretches!)
  const built = prompt.candidates.map((card) => {
    const isMarked = selectedIds.has(card.id);
    const spr = buildFullCard(card, {
      side: prompt.side,
      ownerName: card.character_name || '',
      showOwner: true,
      width: cardW,
      fixedHeight: portraitH,
      dense: true,
      centered: false,
      legal: true,
      selected: isMarked,
    });
    return { card, isMarked, spr };
  });

  const maxH = built.reduce((m, b) => Math.max(m, b.spr._boxHeight), 200);
  const baseTop = Math.max(96, Math.min(h - maxH - 122, (h - maxH - 44) / 2));

  built.forEach(({ card, isMarked, spr }, i) => {
    const cardX = startX + i * (cardW + gap);
    const drawY = baseTop + (isMarked ? 16 : 0);
    const holder = new PIXI.Container();
    holder.position.set(cardX, drawY);
    holder.addChild(spr);

    const ch = spr._boxHeight;
    const pill = new PIXI.Graphics();
    pill.roundRect(cardW / 2 - 48, ch + 10, 96, 26, 6)
      .fill({ color: isMarked ? 0xc8452e : 0x1a825e });
    holder.addChild(pill);
    const bTxt = new PIXI.Text({
      text: isMarked ? '置底' : '保留',
      style: { fontFamily: FONT_UI, fontSize: 12, fontWeight: '800', fill: INK.paper },
    });
    bTxt.anchor.set(0.5);
    bTxt.position.set(cardW / 2, ch + 23);
    holder.addChild(bTxt);

    holder.eventMode = 'static';
    holder.cursor = 'pointer';
    holder.on('pointertap', (e) => {
      e.stopPropagation();
      onToggle(card.id);
    });
    root.addChild(holder);
  });

  const ready = selectedIds.size === prompt.discard_count;
  const btn = makeSealButton('确认', {
    width: 176, height: 42, accent: ready ? theme.accent : INK.muted, solid: ready, disabled: !ready, fontSize: 15,
    onClick: () => onConfirm(),
  });
  btn.position.set(cx - 88, h - 64);
  root.addChild(btn);

  return root;
}

export function buildSpecialOverlay(w, h, { side, timing, options, pendingAttack, onPick, onSwitchSide, onLeave }) {
  const root = new PIXI.Container();
  const theme = SIDE_THEME[side] || SIDE_THEME[1];

  const veil = new PIXI.Graphics();
  veil.rect(0, 0, w, h).fill({ color: 0xf4efe4, alpha: 0.86 });
  veil.eventMode = 'static';
  root.addChild(veil);

  const panelW = Math.min(640, w - 80);
  const rowH = 44;
  const maxRows = Math.min(8, Math.max(1, options.length));
  const panelH = Math.min(h - 90, 154 + maxRows * (rowH + 8));
  const px = (w - panelW) / 2;
  const py = (h - panelH) / 2;

  const panel = new PIXI.Graphics();
  panel.roundRect(px + 5, py + 8, panelW, panelH, 14).fill({ color: INK.shadow, alpha: 0.34 });
  panel.roundRect(px, py, panelW, panelH, 14).fill({ color: INK.paper }).stroke({ width: 2, color: theme.accent });
  root.addChild(panel);

  const title = new PIXI.Text({
    text: timing ? `${theme.name} · ${timing}` : `${theme.name} · 特殊行动`,
    style: { fontFamily: FONT_UI, fontSize: 18, fontWeight: '800', fill: theme.accent },
  });
  title.position.set(px + 22, py + 18);
  root.addChild(title);

  if (!options.length) {
    const empty = new PIXI.Text({
      text: '无可发动的特殊行动',
      style: { fontFamily: FONT_UI, fontSize: 14, fill: INK.muted },
    });
    empty.anchor.set(0.5);
    empty.position.set(w / 2, py + panelH / 2);
    root.addChild(empty);
  } else {
    options.slice(0, 8).forEach((opt, idx) => {
      const col = opt.kind === 'replace' ? 0x1a8775 : opt.kind === 'attack' ? 0xcf4932 : opt.kind === 'intercept' ? 0x1c8a64 : INK.gold;
      const btn = makeSealButton(opt.label, {
        width: panelW - 44, height: rowH, accent: col, fill: INK.paperSoft, fontSize: 13,
        onClick: () => onPick(idx),
      });
      btn.position.set(px + 22, py + 58 + idx * (rowH + 8));
      root.addChild(btn);
    });
  }

  const switchBtn = makeSealButton('切换席位', { width: 112, height: 36, accent: INK.secondary, onClick: onSwitchSide });
  switchBtn.position.set(px + 22, py + panelH - 50);
  root.addChild(switchBtn);

  if (!pendingAttack) {
    const closeBtn = makeSealButton('让过', { width: 112, height: 36, accent: theme.accent, solid: true, onClick: onLeave });
    closeBtn.position.set(px + panelW - 134, py + panelH - 50);
    root.addChild(closeBtn);
  }
  return root;
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

/**
 * Visual Confrontational Team Formation & Living Character Showcase (ZERO plain-text tiling!):
 *  - Top: Confrontational VS Stage with 3+3 living animated character pedestals facing each other
 *  - Left: Faction-filtered Living Character Portrait Gallery (breathing silhouettes + visual stat emblems)
 *  - Right: Living Hero Showcase + Structured Verbatim Passive Plates + Real Interactive Skill Cards (hover to magnify!)
 */
export function buildRosterOverlay(w, h, {
  catalog,
  team1,
  team2,
  assignSide,
  hoveredChar,
  factionFilter = null,
  galleryScrollY = 0,
  inspectScrollY = 0,
  onSetAssignSide,
  onSetFaction,
  onToggleChar,
  onRemoveFromSide,
  onHoverChar,
  onHoverCard,
  onStart,
  onCancel,
}) {
  const root = new PIXI.Container();
  const actors = [];

  const veil = new PIXI.Graphics();
  veil.rect(0, 0, w, h).fill({ color: 0xf5f1e7, alpha: 0.985 });
  veil.eventMode = 'static';
  root.addChild(veil);

  const pad = 20;
  const charById = new Map(catalog.map((c) => [c.id, c]));

  // ── 1. TOP CONFRONTATIONAL VS SQUAD FORMATION BAR ──
  const topY = 12;
  const topH = 114;
  const centerW = 196;
  const wingW = Math.floor((w - pad * 2 - centerW - 24) / 2);

  [1, 2].forEach((side) => {
    const t = SIDE_THEME[side];
    const isEditing = assignSide === side;
    const list = side === 1 ? team1 : team2;
    const wx = side === 1 ? pad : w - pad - wingW;

    const wing = new PIXI.Container();
    wing.position.set(wx, topY);
    const wg = new PIXI.Graphics();
    wg.roundRect(2, 4, wingW, topH, 13).fill({ color: INK.shadow, alpha: isEditing ? 0.28 : 0.16 });
    wg.roundRect(0, 0, wingW, topH, 13)
      .fill({ color: isEditing ? t.warmTint : INK.paper })
      .stroke({ width: isEditing ? 2.6 : 1.3, color: isEditing ? t.accent : INK.line });
    wg.roundRect(2, 2, wingW - 4, 24, 11).fill({ color: isEditing ? t.softBg : INK.paperSoft });
    wing.addChild(wg);

    const wTitle = new PIXI.Text({
      text: `${t.name}（${list.length}/3）`,
      style: { fontFamily: FONT_UI, fontSize: 12.5, fontWeight: '800', fill: t.accent },
    });
    wTitle.position.set(side === 1 ? 12 : wingW - 12 - wTitle.width, 5);
    wing.addChild(wTitle);

    if (isEditing) {
      const edTxt = new PIXI.Text({
        text: '● 正在编队',
        style: { fontFamily: FONT_UI, fontSize: 11, fontWeight: '800', fill: INK.gold },
      });
      edTxt.position.set(side === 1 ? wingW - 12 - edTxt.width : 12, 6);
      wing.addChild(edTxt);
    }

    wing.eventMode = 'static';
    wing.cursor = 'pointer';
    wing.on('pointertap', (e) => {
      e.stopPropagation();
      onSetAssignSide(side);
    });

    // 3 visual character pedestal slots per side (P1 left-to-right, P2 mirrored right-to-left facing center!)
    const slotGap = 8;
    const slotW = Math.floor((wingW - 20 - slotGap * 2) / 3);
    const slotH = 78;
    const slotY = 29;
    for (let i = 0; i < 3; i++) {
      const visualIdx = side === 1 ? i : 2 - i;
      const sx = 10 + visualIdx * (slotW + slotGap);
      const cid = list[i];
      const ch = cid ? charById.get(cid) : null;
      const slot = new PIXI.Container();
      slot.position.set(sx, slotY);

      const sg = new PIXI.Graphics();
      if (ch) {
        const pal = actorPalette(ch, side);
        sg.roundRect(0, 0, slotW, slotH, 9)
          .fill({ color: pal.highlight })
          .stroke({ width: 1.7, color: t.accent });
        sg.ellipse(slotW / 2, slotH - 22, slotW * 0.34, 8)
          .fill({ color: INK.paper, alpha: 0.72 })
          .stroke({ width: 1, color: pal.primary, alpha: 0.35 });
        slot.addChild(sg);

        const actor = createCharacterActor(ch, side, { radius: 22 });
        actor.position.set(slotW / 2, 34);
        slot.addChild(actor);
        actors.push({ actor, ch });

        const nm = new PIXI.Text({
          text: ch.name,
          style: { fontFamily: FONT_UI, fontSize: ch.name.length > 4 ? 10.5 : 11.5, fontWeight: '800', fill: INK.primary },
        });
        nm.anchor.set(0.5);
        nm.position.set(slotW / 2, slotH - 11);
        slot.addChild(nm);

        // Compact remove badge
        const rx = side === 1 ? slotW - 12 : 12;
        const rmBg = new PIXI.Graphics();
        rmBg.circle(rx, 11, 7.5).fill({ color: INK.paper, alpha: 0.92 }).stroke({ width: 1.2, color: INK.secondary, alpha: 0.65 });
        rmBg.moveTo(rx - 3, 8).lineTo(rx + 3, 14).stroke({ width: 1.4, color: 0xcf4932 });
        rmBg.moveTo(rx + 3, 8).lineTo(rx - 3, 14).stroke({ width: 1.4, color: 0xcf4932 });
        slot.addChild(rmBg);

        slot.eventMode = 'static';
        slot.cursor = 'pointer';
        slot.on('pointerover', () => onHoverChar(ch));
        slot.on('pointertap', (e) => {
          e.stopPropagation();
          if (onRemoveFromSide) onRemoveFromSide(side, ch.id);
          else onToggleChar(ch.id);
        });
      } else {
        sg.roundRect(0, 0, slotW, slotH, 9)
          .fill({ color: INK.paperSoft, alpha: 0.75 })
          .stroke({ width: 1.2, color: isEditing ? t.border : INK.line, alpha: 0.8 });
        sg.moveTo(slotW / 2 - 7, slotH / 2 - 4).lineTo(slotW / 2 + 7, slotH / 2 - 4)
          .stroke({ width: 1.8, color: INK.muted, alpha: 0.7 });
        sg.moveTo(slotW / 2, slotH / 2 - 11).lineTo(slotW / 2, slotH / 2 + 3)
          .stroke({ width: 1.8, color: INK.muted, alpha: 0.7 });
        slot.addChild(sg);

        const idxTxt = new PIXI.Text({
          text: `${i + 1}号位`,
          style: { fontFamily: FONT_UI, fontSize: 10, fontWeight: '700', fill: INK.muted },
        });
        idxTxt.anchor.set(0.5);
        idxTxt.position.set(slotW / 2, slotH - 12);
        slot.addChild(idxTxt);
      }
      wing.addChild(slot);
    }

    root.addChild(wing);
  });

  // Center VS Crest + Start / Cancel Seals
  const cx = w / 2;
  const vsG = new PIXI.Graphics();
  drawLightStar(vsG, cx, topY + 24, 18, INK.gold, 0.9);
  root.addChild(vsG);
  const vsTxt = new PIXI.Text({
    text: 'VS',
    style: { fontFamily: FONT_NUM, fontSize: 15, fontWeight: '900', fill: INK.primary, letterSpacing: 1 },
  });
  vsTxt.anchor.set(0.5);
  vsTxt.position.set(cx, topY + 24);
  root.addChild(vsTxt);

  const valid = team1.length >= 1 && team2.length >= 1;
  const startBtn = makeSealButton('开始对局', {
    width: 154, height: 36, accent: valid ? 0x1c8a64 : INK.muted, solid: valid, disabled: !valid, fontSize: 14, radius: 18,
    onClick: () => onStart([team1.slice(), team2.slice()]),
  });
  startBtn.position.set(cx - 77, topY + 46);
  root.addChild(startBtn);

  const cancelBtn = makeSealButton('返回', {
    width: 106, height: 26, accent: INK.secondary, fontSize: 11.5, radius: 13, onClick: onCancel,
  });
  cancelBtn.position.set(cx - 53, topY + 88);
  root.addChild(cancelBtn);

  // ── 2. LEFT HALF: FACTION-FILTERED LIVING PORTRAIT GALLERY ──
  const bodyTop = topY + topH + 12;
  const bodyH = h - bodyTop - 16;
  const galleryW = Math.floor((w - pad * 2 - 16) * 0.515);
  const galleryX = pad;

  const galleryBg = new PIXI.Graphics();
  galleryBg.roundRect(galleryX + 2, bodyTop + 4, galleryW, bodyH, 13).fill({ color: INK.shadow, alpha: 0.18 });
  galleryBg.roundRect(galleryX, bodyTop, galleryW, bodyH, 13)
    .fill({ color: INK.paper })
    .stroke({ width: 1.5, color: INK.line });
  root.addChild(galleryBg);

  // Faction Filter Bar
  const factions = [];
  for (const c of catalog) {
    const f = c.faction || '独立';
    if (!factions.includes(f)) factions.push(f);
  }
  const filterItems = [{ id: null, label: `全部 ${catalog.length}` }, ...factions.map((f) => ({ id: f, label: f }))];
  let fx = galleryX + 12;
  const fy = bodyTop + 10;
  for (const item of filterItems) {
    const active = factionFilter === item.id;
    const labelW = Math.max(54, item.label.length * 11 + 18);
    if (fx + labelW > galleryX + galleryW - 10) break;
    const pill = makeSealButton(item.label, {
      width: labelW,
      height: 26,
      accent: active ? SIDE_THEME[assignSide].accent : INK.secondary,
      fill: INK.paperSoft,
      solid: active,
      fontSize: 11,
      radius: 13,
      onClick: () => onSetFaction && onSetFaction(item.id),
    });
    pill.position.set(fx, fy);
    root.addChild(pill);
    fx += labelW + 6;
  }

  const filtered = factionFilter
    ? catalog.filter((c) => (c.faction || '独立') === factionFilter)
    : catalog;

  const gx = galleryX + 12;
  const gy = bodyTop + 44;
  const gw = galleryW - 24;
  const gh = bodyH - 54;

  const gMask = new PIXI.Graphics();
  gMask.rect(gx, gy, gw, gh).fill({ color: 0xffffff });
  root.addChild(gMask);

  const gBody = new PIXI.Container();
  gBody.mask = gMask;
  root.addChild(gBody);

  const cols = gw >= 540 ? 4 : 3;
  const gap = 10;
  const cellW = Math.floor((gw - 8 - gap * (cols - 1)) / cols);
  const cellH = 148;
  const rows = Math.ceil(filtered.length / cols);
  const totalGalleryH = rows * cellH + Math.max(0, rows - 1) * gap + 8;
  root._galleryMaxScroll = Math.max(0, totalGalleryH - gh);
  const clampedGScroll = Math.max(0, Math.min(root._galleryMaxScroll, galleryScrollY));

  const target = hoveredChar || filtered[0] || catalog[0];

  filtered.forEach((char, idx) => {
    const col = idx % cols;
    const row = Math.floor(idx / cols);
    const x = gx + col * (cellW + gap);
    const y = gy + row * (cellH + gap) - clampedGScroll;

    const in1 = team1.indexOf(char.id);
    const in2 = team2.indexOf(char.id);
    const ownerSide = in1 >= 0 ? 1 : in2 >= 0 ? 2 : 0;
    const isSelected = target?.id === char.id;
    const pal = actorPalette(char, ownerSide || assignSide);
    const borderCol = ownerSide ? SIDE_THEME[ownerSide].accent : isSelected ? INK.gold : INK.line;

    const card = new PIXI.Container();
    card.position.set(x, y);
    const bg = new PIXI.Graphics();
    bg.roundRect(2, 4, cellW, cellH, 11).fill({ color: INK.shadow, alpha: isSelected ? 0.3 : 0.18 });
    bg.roundRect(0, 0, cellW, cellH, 11)
      .fill({ color: INK.paper })
      .stroke({ width: ownerSide ? 2.4 : isSelected ? 2.2 : 1.3, color: borderCol });

    // Sculpted portrait art stage (upper 84px)
    const artH = 84;
    bg.roundRect(3, 3, cellW - 6, artH, 8).fill({ color: pal.highlight });
    bg.circle(cellW / 2, artH * 0.54, 30)
      .fill({ color: INK.paper, alpha: 0.68 })
      .stroke({ width: 1.2, color: pal.primary, alpha: 0.35 });
    bg.ellipse(cellW / 2, artH - 9, cellW * 0.3, 6).fill({ color: pal.primary, alpha: 0.14 });
    card.addChild(bg);

    // Living animated character actor right inside the portrait!
    const actor = createCharacterActor(char, ownerSide || 1, { radius: 26 });
    actor.position.set(cellW / 2, artH * 0.56);
    card.addChild(actor);
    actors.push({ actor, ch: char });

    // Rank crest pill (top-left)
    const rankLabel = RANK_LABEL[char.rank] || '';
    if (rankLabel) {
      const rCol = RANK_COLOR[char.rank] || INK.secondary;
      const rw = rankLabel.length * 9 + 10;
      const rg = new PIXI.Graphics();
      rg.roundRect(6, 6, rw, 17, 5).fill({ color: INK.paper, alpha: 0.9 }).stroke({ width: 1.1, color: rCol, alpha: 0.85 });
      card.addChild(rg);
      const rTxt = new PIXI.Text({
        text: rankLabel,
        style: { fontFamily: FONT_UI, fontSize: 9.2, fontWeight: '800', fill: rCol },
      });
      rTxt.anchor.set(0.5);
      rTxt.position.set(6 + rw / 2, 14.5);
      card.addChild(rTxt);
    }

    // Team ownership ribbon (top-right)
    if (ownerSide) {
      const tg = new PIXI.Graphics();
      tg.roundRect(cellW - 48, 6, 42, 18, 5).fill({ color: SIDE_THEME[ownerSide].accent });
      card.addChild(tg);
      const tTxt = new PIXI.Text({
        text: `P${ownerSide}#${(ownerSide === 1 ? in1 : in2) + 1}`,
        style: { fontFamily: FONT_NUM, fontSize: 10.5, fontWeight: '900', fill: INK.paper },
      });
      tTxt.anchor.set(0.5);
      tTxt.position.set(cellW - 27, 15);
      card.addChild(tTxt);
    }

    // Bottom Nameplate + Visual Stat Emblems
    const nm = new PIXI.Text({
      text: char.name,
      style: { fontFamily: FONT_UI, fontSize: char.name.length > 5 ? 12 : 13.5, fontWeight: '800', fill: INK.primary },
    });
    nm.position.set(9, artH + 7);
    card.addChild(nm);

    const fac = new PIXI.Text({
      text: char.faction || '独立',
      style: { fontFamily: FONT_UI, fontSize: 9.8, fontWeight: '700', fill: pal.primary },
    });
    fac.position.set(9, artH + 25);
    card.addChild(fac);

    // Visual HP heart & Duel diamond pips along bottom bar
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
      drawDuelPip(statG, pipStart - d * 11, sy, 4.5, INK.gold);
    }
    card.addChild(statG, hpTxt);

    if (y + cellH > gy && y < gy + gh) {
      card.eventMode = 'static';
      card.cursor = 'pointer';
      card.on('pointerover', () => onHoverChar(char));
      card.on('pointertap', (e) => {
        e.stopPropagation();
        onToggleChar(char.id);
      });
    }
    gBody.addChild(card);
  });

  if (root._galleryMaxScroll > 0) {
    const sbH = Math.max(32, gh * (gh / totalGalleryH));
    const sbY = gy + (clampedGScroll / root._galleryMaxScroll) * (gh - sbH);
    const sb = new PIXI.Graphics();
    sb.roundRect(gx + gw - 4, gy, 4, gh, 2).fill({ color: INK.line, alpha: 0.45 });
    sb.roundRect(gx + gw - 4, sbY, 4, sbH, 2).fill({ color: INK.secondary, alpha: 0.7 });
    root.addChild(sb);
  }

  // ── 3. RIGHT HALF: LIVING HERO SHOWCASE + VERBATIM PASSIVES + REAL SKILL CARDS ──
  const inspX = galleryX + galleryW + 16;
  const inspY = bodyTop;
  const inspW = w - inspX - pad;
  const inspH = bodyH;
  root._gallerySplitX = inspX;

  const inspBg = new PIXI.Graphics();
  inspBg.roundRect(inspX + 2, inspY + 4, inspW, inspH, 13).fill({ color: INK.shadow, alpha: 0.22 });
  inspBg.roundRect(inspX, inspY, inspW, inspH, 13)
    .fill({ color: INK.paper })
    .stroke({ width: 1.6, color: INK.line });
  root.addChild(inspBg);

  if (target) {
    const in1 = team1.indexOf(target.id);
    const in2 = team2.indexOf(target.id);
    const ownerSide = in1 >= 0 ? 1 : in2 >= 0 ? 2 : 0;
    const previewSide = ownerSide || assignSide;
    const pal = actorPalette(target, previewSide);

    // Hero Pedestal Banner (top 118px)
    const bannerH = 118;
    const bG = new PIXI.Graphics();
    bG.roundRect(inspX + 3, inspY + 3, inspW - 6, bannerH, 10).fill({ color: pal.highlight });
    // Sculpted rotating-compass pedestal behind living hero actor
    const acx = inspX + 66;
    const acy = inspY + 62;
    bG.circle(acx, acy, 44).fill({ color: INK.paper, alpha: 0.72 }).stroke({ width: 1.4, color: pal.primary, alpha: 0.4 });
    bG.circle(acx, acy, 34).stroke({ width: 1, color: pal.secondary, alpha: 0.4 });
    bG.ellipse(acx, acy + 30, 34, 8).fill({ color: pal.primary, alpha: 0.16 });
    root.addChild(bG);

    const heroActor = createCharacterActor(target, previewSide, { radius: 38 });
    heroActor.position.set(acx, acy + 4);
    root.addChild(heroActor);
    actors.push({ actor: heroActor, ch: target });

    const infoX = inspX + 124;
    const nameTxt = new PIXI.Text({
      text: target.name,
      style: { fontFamily: FONT_UI, fontSize: 21, fontWeight: '800', fill: INK.primary },
    });
    nameTxt.position.set(infoX, inspY + 14);
    root.addChild(nameTxt);

    if (target.title) {
      const tt = new PIXI.Text({
        text: target.title,
        style: { fontFamily: FONT_UI, fontSize: 12, fontWeight: '700', fill: pal.primary },
      });
      tt.position.set(infoX + nameTxt.width + 10, inspY + 21);
      root.addChild(tt);
    }

    const subTxt = new PIXI.Text({
      text: `${target.faction || '独立'} · ${RANK_LABEL[target.rank] || ''}`,
      style: { fontFamily: FONT_UI, fontSize: 12, fontWeight: '700', fill: INK.secondary },
    });
    subTxt.position.set(infoX, inspY + 44);
    root.addChild(subTxt);

    // Visual Stat Badges Row
    const badgeY = inspY + 72;
    const pills = [
      { label: `生命 ${target.max_hp}`, col: 0xcf4330, bg: 0xfdece9 },
      { label: `交锋 ${target.base_duels || 1}`, col: INK.gold, bg: INK.goldBg },
      { label: `${(target.skills || []).length} 张技能`, col: pal.primary, bg: INK.paper },
    ];
    let px = infoX;
    const pillG = new PIXI.Graphics();
    root.addChild(pillG);
    for (const pl of pills) {
      const pt = new PIXI.Text({
        text: pl.label,
        style: { fontFamily: FONT_UI, fontSize: 11.5, fontWeight: '800', fill: pl.col },
      });
      const pw = pt.width + 16;
      pillG.roundRect(px, badgeY, pw, 24, 7).fill({ color: pl.bg }).stroke({ width: 1.2, color: pl.col, alpha: 0.7 });
      pt.position.set(px + 8, badgeY + 4);
      root.addChild(pt);
      px += pw + 8;
    }

    // Contextual Assign/Remove Action Button on top-right of hero banner
    const activeTheme = SIDE_THEME[assignSide];
    const inActive = (assignSide === 1 ? in1 : in2) >= 0;
    const inOther = (assignSide === 1 ? in2 : in1) >= 0;
    const actLabel = inActive
      ? `移出${activeTheme.name}`
      : inOther
        ? `调入${activeTheme.name}`
        : `+ 编入${activeTheme.name}`;
    const actBtn = makeSealButton(actLabel, {
      width: 118,
      height: 32,
      accent: inActive ? 0xcf4932 : inOther ? INK.gold : activeTheme.accent,
      solid: !inActive,
      fontSize: 12,
      radius: 16,
      onClick: () => onToggleChar(target.id),
    });
    actBtn.position.set(inspX + inspW - 130, inspY + 14);
    root.addChild(actBtn);

    // Scrollable Showcase Body: Structured Passive Plates + Real Interactive Skill Cards!
    const svx = inspX + 14;
    const svy = inspY + bannerH + 12;
    const svw = inspW - 28;
    const svh = inspH - bannerH - 24;

    const sMask = new PIXI.Graphics();
    sMask.rect(svx, svy, svw, svh).fill({ color: 0xffffff });
    root.addChild(sMask);

    const sBody = new PIXI.Container();
    sBody.mask = sMask;
    root.addChild(sBody);

    let cy = 0;
    const innerW = svw - 8;
    const maxChars = Math.max(28, Math.floor((innerW - 22) / 6.4));

    const allPassives = [
      ...(target.faction_passives || []).map((p) => ({ ...p, tag: '阵营被动' })),
      ...(target.passives || []).map((p) => ({ ...p, tag: '角色被动' })),
    ];

    if (allPassives.length) {
      const pHead = new PIXI.Text({
        text: '被动技能',
        style: { fontFamily: FONT_UI, fontSize: 13, fontWeight: '800', fill: INK.secondary },
      });
      pHead.position.set(svx, svy + cy - inspectScrollY);
      sBody.addChild(pHead);
      cy += 22;

      for (const p of allPassives) {
        const entries = (p.entries && p.entries.length) ? p.entries : (p.description ? [p.description] : []);
        const plate = buildUnifiedEntryPlate({
          variant: 'passive',
          title: p.name || p.tag,
          tagLabel: p.tag === '阵营被动' ? '阵营被动' : '',
          entries,
          width: innerW,
          fontSize: 11.6,
          lineHeight: 17.5,
        });
        plate.position.set(svx, svy + cy - inspectScrollY);
        sBody.addChild(plate);
        cy += plate._height + 8;
      }
      cy += 4;
    }

    // Section 2: ZERO-HOVER Full Readable Skill Cards (2-col on wide screens, 1-col on narrow — read EVERY skill directly!)
    const skills = target.skills || [];
    if (skills.length) {
      const skHead = new PIXI.Text({
        text: '技能牌组',
        style: { fontFamily: FONT_UI, fontSize: 13, fontWeight: '800', fill: INK.secondary },
      });
      skHead.position.set(svx, svy + cy - inspectScrollY);
      sBody.addChild(skHead);
      cy += 22;

      const skCols = innerW >= 630 ? 3 : 2;
      const skGapX = 12;
      const skGapY = 12;
      const skW = Math.min(216, Math.floor((innerW - skGapX * (skCols - 1)) / skCols));
      const skMinH = Math.round(skW * 1.38);

      for (let i = 0; i < skills.length; i += skCols) {
        let rowH = 0;
        for (let c = 0; c < skCols && i + c < skills.length; c++) {
          const sk = skills[i + c];
          const cardSpr = buildFullCard(sk, {
            side: previewSide,
            ownerName: target.name,
            showOwner: false,
            width: skW,
            fixedHeight: skMinH,
            dense: true,
            centered: false,
            legal: true,
          });
          cardSpr.position.set(svx + c * (skW + skGapX), svy + cy - inspectScrollY);
          sBody.addChild(cardSpr);
          rowH = Math.max(rowH, cardSpr._boxHeight);
        }
        cy += rowH + skGapY;
      }
      cy += 6;
    }

    root._inspectMaxScroll = Math.max(0, cy - svh + 10);
    if (root._inspectMaxScroll > 0) {
      const clampedS = Math.max(0, Math.min(root._inspectMaxScroll, inspectScrollY));
      const sbH = Math.max(32, svh * (svh / Math.max(svh + 1, cy)));
      const sbY = svy + (clampedS / root._inspectMaxScroll) * (svh - sbH);
      const sb = new PIXI.Graphics();
      sb.roundRect(svx + svw - 4, svy, 4, svh, 2).fill({ color: INK.line, alpha: 0.45 });
      sb.roundRect(svx + svw - 4, sbY, 4, sbH, 2).fill({ color: INK.secondary, alpha: 0.7 });
      root.addChild(sb);
    }
  } else {
    root._inspectMaxScroll = 0;
  }

  root._actors = actors;
  return root;
}

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

export function buildCodexOverlay(w, h, { tab, scrollY, catalog, history, onTab, onClose }) {
  const root = new PIXI.Container();
  const veil = new PIXI.Graphics();
  veil.rect(0, 0, w, h).fill({ color: 0xf4efe4, alpha: 0.86 });
  veil.eventMode = 'static';
  veil.on('pointertap', onClose);
  root.addChild(veil);

  const pw = Math.min(820, w - 80);
  const ph = Math.min(620, h - 80);
  const px = (w - pw) / 2;
  const py = (h - ph) / 2;

  const frame = new PIXI.Graphics();
  frame.roundRect(px + 5, py + 8, pw, ph, 14).fill({ color: INK.shadow, alpha: 0.34 });
  frame.roundRect(px, py, pw, ph, 14).fill({ color: INK.paper }).stroke({ width: 1.8, color: INK.line });
  frame.eventMode = 'static';
  root.addChild(frame);

  const tabs = [
    { id: 'rules', label: '正式规则' },
    { id: 'catalog', label: '本局图鉴' },
    { id: 'history', label: `战报 (${history.length})` },
  ];
  tabs.forEach((t, idx) => {
    const active = tab === t.id;
    const btn = makeSealButton(t.label, {
      width: 140, height: 34, accent: active ? 0x1c8a64 : INK.secondary, solid: active, fontSize: 12.5,
      onClick: () => onTab(t.id),
    });
    btn.position.set(px + 20 + idx * 150, py + 16);
    root.addChild(btn);
  });

  const closeBtn = makeSealButton('关闭', { width: 84, height: 34, accent: 0xcf4932, onClick: onClose });
  closeBtn.position.set(px + pw - 104, py + 16);
  root.addChild(closeBtn);

  const vx = px + 22;
  const vy = py + 66;
  const vw = pw - 44;
  const vh = ph - 86;
  const mask = new PIXI.Graphics();
  mask.rect(vx, vy, vw, vh).fill({ color: 0xffffff });
  root.addChild(mask);

  const body = new PIXI.Container();
  body.mask = mask;
  root.addChild(body);

  let y = 0;
  const maxChars = Math.max(42, Math.floor(vw / 6.7));
  const addLine = (text, { size = 13, color = INK.primary, bold = false, gapAfter = 10, indent = 0 } = {}) => {
    const t = new PIXI.Text({
      text: wrapCjkText(text, maxChars - Math.floor(indent / 6)),
      style: {
        fontFamily: FONT_UI, fontSize: size, fontWeight: bold ? '800' : '400', fill: color, lineHeight: size + 7,
        wordWrap: true, breakWords: true, wordWrapWidth: vw - 12 - indent,
      },
    });
    t.position.set(vx + indent, vy + y - scrollY);
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
          width: vw - 10,
          accentColor: INK.gold,
          fontSize: 12.5,
          lineHeight: 19,
        });
        plate.position.set(vx, vy + y - scrollY);
        body.addChild(plate);
        y += plate._height + 10;
      } else {
        addLine(para, { size: 13, gapAfter: 12 });
      }
    }
  } else if (tab === 'catalog' && catalog) {
    const colGap = 12;
    const cardW = Math.floor((vw - 12 - colGap) / 2);
    for (const pl of catalog.players || []) {
      const theme = SIDE_THEME[pl.side] || SIDE_THEME[1];
      addLine(`── ${theme.name} ──`, { size: 15, color: theme.accent, bold: true, gapAfter: 8 });
      for (const ch of pl.characters || []) {
        addLine(ch.name, { size: 14.5, color: INK.primary, bold: true, gapAfter: 8, indent: 2 });
        for (const p of [...(ch.faction_passives || []).map((x) => ({ ...x, _tag: '阵营被动' })), ...(ch.passives || []).map((x) => ({ ...x, _tag: '' }))]) {
          const plate = buildUnifiedEntryPlate({
            variant: 'passive',
            title: p.name || '被动',
            tagLabel: p._tag,
            entries: p.entries || [],
            width: vw - 14,
            fontSize: 11.8,
            lineHeight: 17.5,
          });
          plate.position.set(vx + 4, vy + y - scrollY);
          body.addChild(plate);
          y += plate._height + 7;
        }
        const skList = ch.skills || [];
        for (let i = 0; i < skList.length; i += 2) {
          const leftCard = buildVerbatimCardPanel(skList[i], { side: pl.side, ownerName: ch.name, width: cardW, compact: true });
          leftCard.position.set(vx + 4, vy + y - scrollY);
          body.addChild(leftCard);
          let rowH = leftCard._boxHeight;
          if (i + 1 < skList.length) {
            const rightCard = buildVerbatimCardPanel(skList[i + 1], { side: pl.side, ownerName: ch.name, width: cardW, compact: true });
            rightCard.position.set(vx + 4 + cardW + colGap, vy + y - scrollY);
            body.addChild(rightCard);
            rowH = Math.max(rowH, rightCard._boxHeight);
          }
          y += rowH + 10;
        }
        y += 6;
      }
    }
    const statuses = Object.entries(catalog.statuses || {});
    if (statuses.length) {
      addLine('── 特殊状态 ──', { size: 15, color: INK.gold, bold: true, gapAfter: 8 });
      for (const [name, list] of statuses) {
        const plate = buildUnifiedEntryPlate({
          variant: 'status',
          statusName: name,
          entries: list,
          width: vw - 14,
          fontSize: 11.8,
          lineHeight: 17.5,
        });
        plate.position.set(vx + 4, vy + y - scrollY);
        body.addChild(plate);
        y += plate._height + 7;
      }
    }
  } else if (tab === 'history') {
    if (!history.length) addLine('尚无战报。', { size: 13, color: INK.muted });
    else {
      history.slice().reverse().forEach((line, i) => {
        addLine(`${history.length - i}. ${line}`, { size: 12.5, color: i === 0 ? INK.gold : INK.primary, gapAfter: 7 });
      });
    }
  }

  root._maxScroll = Math.max(0, y - vh + 24);
  return root;
}

export function buildPileOverlay(w, h, { title, side, cards, charNames, scrollY = 0, onClose }) {
  const root = new PIXI.Container();
  const veil = new PIXI.Graphics();
  veil.rect(0, 0, w, h).fill({ color: 0xf5f1e7, alpha: 0.94 });
  veil.eventMode = 'static';
  veil.on('pointertap', onClose);
  root.addChild(veil);

  const head = new PIXI.Text({
    text: `${title}（${cards.length}）`,
    style: { fontFamily: FONT_UI, fontSize: 19, fontWeight: '800', fill: INK.strong },
  });
  head.anchor.set(0.5);
  head.position.set(w / 2, 46);
  root.addChild(head);

  const closeBtn = makeSealButton('关闭', { width: 80, height: 30, accent: INK.secondary, fontSize: 12, onClick: onClose });
  closeBtn.position.set(w - 108, 31);
  root.addChild(closeBtn);

  const vx = 32;
  const vy = 82;
  const vw = w - 64;
  const vh = h - 106;
  const mask = new PIXI.Graphics();
  mask.rect(vx, vy, vw, vh).fill({ color: 0xffffff });
  root.addChild(mask);

  const body = new PIXI.Container();
  body.mask = mask;
  root.addChild(body);

  let cy = 0;
  if (cards.length) {
    const gap = 16;
    const cols = Math.max(2, Math.min(cards.length, Math.floor((vw + gap) / 218)));
    const cardW = Math.min(210, Math.floor((vw - gap * (cols - 1)) / cols));
    const portraitH = Math.round(cardW * 1.38);
    for (let i = 0; i < cards.length; i += cols) {
      const rowCount = Math.min(cols, cards.length - i);
      const rowW = rowCount * cardW + (rowCount - 1) * gap;
      const startX = vx + (vw - rowW) / 2;
      let rowH = 0;
      for (let c = 0; c < rowCount; c++) {
        const card = cards[i + c];
        const spr = buildFullCard(card, {
          side,
          ownerName: charNames[card.character_id] || '',
          showOwner: true,
          width: cardW,
          fixedHeight: portraitH,
          dense: true,
          centered: false,
          legal: true,
        });
        spr.position.set(startX + c * (cardW + gap), vy + cy - scrollY);
        spr.eventMode = 'static';
        spr.on('pointertap', (e) => e.stopPropagation());
        body.addChild(spr);
        rowH = Math.max(rowH, spr._boxHeight);
      }
      cy += rowH + gap;
    }
  }
  root._maxScroll = Math.max(0, cy - vh + 16);
  return root;
}

export function buildFinishOverlay(w, h, { winnerSide, turn, history, onRematch, onNewRoster }) {
  const root = new PIXI.Container();
  const theme = winnerSide ? SIDE_THEME[winnerSide] : { accent: INK.gold, name: '双方平局' };

  const veil = new PIXI.Graphics();
  veil.rect(0, 0, w, h).fill({ color: 0xf4efe4, alpha: 0.9 });
  veil.eventMode = 'static';
  root.addChild(veil);

  const cx = w / 2;
  const cy = h / 2;
  const pw = 480;
  const ph = 276;
  const plaque = new PIXI.Graphics();
  plaque.roundRect(cx - pw / 2 + 5, cy - ph / 2 + 8, pw, ph, 16).fill({ color: INK.shadow, alpha: 0.34 });
  plaque.roundRect(cx - pw / 2, cy - ph / 2, pw, ph, 16)
    .fill({ color: INK.paper })
    .stroke({ width: 2.4, color: theme.accent });
  drawLightStar(plaque, cx, cy - 78, 26, theme.accent, 0.95);
  root.addChild(plaque);

  const head = new PIXI.Text({
    text: winnerSide ? `${theme.name} 获胜` : '平局',
    style: { fontFamily: FONT_UI, fontSize: 30, fontWeight: '800', fill: INK.primary, letterSpacing: 2 },
  });
  head.anchor.set(0.5);
  head.position.set(cx, cy - 18);
  root.addChild(head);

  const sub = new PIXI.Text({
    text: `第 ${turn} 回合 · ${history[history.length - 1] || ''}`,
    style: { fontFamily: FONT_UI, fontSize: 13, fill: INK.secondary },
  });
  sub.anchor.set(0.5);
  sub.position.set(cx, cy + 18);
  root.addChild(sub);

  const btn1 = makeSealButton('原阵容再战', { width: 160, height: 42, accent: theme.accent, solid: true, onClick: onRematch });
  btn1.position.set(cx - 170, cy + 60);
  root.addChild(btn1);

  const btn2 = makeSealButton('重新选人', { width: 160, height: 42, accent: INK.gold, onClick: onNewRoster });
  btn2.position.set(cx + 10, cy + 60);
  root.addChild(btn2);

  return root;
}
