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
  buildVerbatimCardPanel,
} from './card_print.js';

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

/**
 * Arknights / Library-of-Ruina inspired Pinned Character Dossier:
 * Click ANY character on the field to see ALL passives (100% verbatim),
 * ALL active statuses (icon + stacks + 100% verbatim rule text), and ALL printed skills
 * (click/hover any skill to view its full 100% verbatim card sheet right beside it!).
 */
export function buildCharacterDossier(w, h, {
  character,
  side,
  catalogChar,
  catalogStatuses,
  selectedSkillId,
  canSetTarget,
  isDefaultTarget,
  scrollY = 0,
  onSelectSkill,
  onSetFocusTarget,
  onClose,
}) {
  const root = new PIXI.Container();
  const theme = SIDE_THEME[side] || SIDE_THEME[1];

  const veil = new PIXI.Graphics();
  veil.rect(0, 0, w, h).fill({ color: 0xf4efe4, alpha: 0.78 });
  veil.eventMode = 'static';
  veil.on('pointertap', onClose);
  root.addChild(veil);

  const skills = catalogChar?.skills || [];
  const activeSkill = skills.find((s) => s.id === selectedSkillId) || skills[0] || null;
  const cardW = 382;
  const leftW = Math.min(520, w - cardW - 72);
  const totalW = leftW + (activeSkill ? cardW + 18 : 0);
  const panelH = Math.min(640, h - 72);
  const px = Math.max(24, (w - totalW) / 2);
  const py = (h - panelH) / 2;

  const panel = new PIXI.Graphics();
  panel.roundRect(px + 5, py + 8, leftW, panelH, 14).fill({ color: INK.shadow, alpha: 0.34 });
  panel.roundRect(px, py, leftW, panelH, 14)
    .fill({ color: INK.paper })
    .stroke({ width: 2, color: theme.accent });
  panel.roundRect(px + 2, py + 2, leftW - 4, 62, 12).fill({ color: theme.softBg });
  panel.eventMode = 'static';
  root.addChild(panel);

  // Header: Character Name + Exact Stats
  const nameTxt = new PIXI.Text({
    text: `${character.name}${character.title ? ' · ' + character.title : ''}`,
    style: { fontFamily: FONT_UI, fontSize: 20, fontWeight: '800', fill: INK.primary },
  });
  nameTxt.position.set(px + 20, py + 12);
  root.addChild(nameTxt);

  const statBits = [
    character.faction || '',
    RANK_LABEL[character.rank] || '',
    `生命 ${character.hp}/${character.max_hp}`,
    `速度 ${character.speed ?? 0}`,
    `常规交锋 ${character.duels?.used ?? '?'}/${character.duels?.max ?? 1}`,
    `个人费 ${character.cost?.available ?? 0}`,
  ].filter(Boolean);
  const statTxt = new PIXI.Text({
    text: statBits.join(' · '),
    style: { fontFamily: FONT_UI, fontSize: 12, fontWeight: '700', fill: theme.accent },
  });
  statTxt.position.set(px + 20, py + 40);
  root.addChild(statTxt);

  const closeBtn = makeSealButton('关闭', {
    width: 68, height: 30, accent: INK.secondary, fontSize: 12, onClick: onClose,
  });
  closeBtn.position.set(px + leftW - 84, py + 16);
  root.addChild(closeBtn);

  if (canSetTarget && character.alive) {
    const focusBtn = makeSealButton(isDefaultTarget ? '当前集火目标' : '设为集火目标', {
      width: 110, height: 30, accent: INK.gold, solid: isDefaultTarget, fontSize: 11.5,
      onClick: onSetFocusTarget,
    });
    focusBtn.position.set(px + leftW - 202, py + 16);
    root.addChild(focusBtn);
  }

  // Scrollable content mask
  const vx = px + 18;
  const vy = py + 74;
  const vw = leftW - 36;
  const vh = panelH - 90;
  const mask = new PIXI.Graphics();
  mask.rect(vx, vy, vw, vh).fill({ color: 0xffffff });
  root.addChild(mask);

  const body = new PIXI.Container();
  body.mask = mask;
  root.addChild(body);

  let y = 0;
  const maxChars = Math.max(32, Math.floor((vw - 16) / 6.5));

  // Active Shields (ONLY if any > 0)
  const sh = character.shields || {};
  const activeShields = ['normal', 'reinforced', 'concept'].filter((k) => (sh[k] || 0) > 0);
  if (activeShields.length) {
    const shRow = new PIXI.Graphics();
    let sx = 0;
    for (const kind of activeShields) {
      const st = SHIELD_STYLE[kind];
      shRow.roundRect(vx + sx, vy + y - scrollY, 108, 26, 6).fill({ color: st.bg }).stroke({ width: 1.2, color: st.color });
      drawShieldGlyph(shRow, kind, vx + sx + 14, vy + y - scrollY + 13, 7);
      const t = new PIXI.Text({
        text: `${st.label} ${sh[kind]}`,
        style: { fontFamily: FONT_UI, fontSize: 11.5, fontWeight: '800', fill: st.color },
      });
      t.anchor.set(0, 0.5);
      t.position.set(vx + sx + 26, vy + y - scrollY + 13);
      body.addChild(t);
      sx += 116;
    }
    body.addChildAt(shRow, 0);
    y += 36;
  }

  // Section 1: ALL Active Statuses (Limbus icon + stacks + 100% VERBATIM rule text!)
  const statuses = Object.entries(character.statuses || {});
  if (statuses.length) {
    const sHead = new PIXI.Text({
      text: '状态效果',
      style: { fontFamily: FONT_UI, fontSize: 13, fontWeight: '800', fill: INK.secondary },
    });
    sHead.position.set(vx, vy + y - scrollY);
    body.addChild(sHead);
    y += 22;

    for (const [name, val] of statuses) {
      const col = STATUS_COLORS[name] || INK.secondary;
      const burst = name === '裂血' && character.bleed_burst;
      const ruleList = catalogStatuses?.[name];
      const ruleText = (ruleList && ruleList.length ? ruleList.join('\n') : OFFICIAL_STATUS_RULES[name]) || '';
      const head = new PIXI.Text({
        text: `${name} ${val}${burst ? '（爆发）' : ''}`,
        style: { fontFamily: FONT_UI, fontSize: 12.5, fontWeight: '800', fill: col },
      });
      const desc = ruleText ? new PIXI.Text({
        text: wrapCjkText(ruleText, maxChars - 5),
        style: {
          fontFamily: FONT_UI, fontSize: 11.5, fill: INK.primary, lineHeight: 17,
          wordWrap: true, breakWords: true, wordWrapWidth: vw - 46,
        },
      }) : null;
      const bh = Math.max(36, 24 + (desc ? desc.height + 8 : 8));
      const box = new PIXI.Graphics();
      box.roundRect(vx, vy + y - scrollY, vw, bh, 8)
        .fill({ color: INK.paperSoft })
        .stroke({ width: 1.2, color: col, alpha: 0.7 });
      drawStatusIcon(box, name, vx + 18, vy + y - scrollY + 18, 10, col);
      head.position.set(vx + 36, vy + y - scrollY + 6);
      body.addChild(box, head);
      if (desc) {
        desc.position.set(vx + 36, vy + y - scrollY + 24);
        body.addChild(desc);
      }
      y += bh + 7;
    }
    y += 6;
  }

  // Section 2: ALL Passives (100% VERBATIM!)
  const allPassives = [
    ...(catalogChar?.faction_passives || []).map((p) => ({ ...p, kind: '阵营被动' })),
    ...(catalogChar?.passives || []).map((p) => ({ ...p, kind: '角色被动' })),
  ];
  if (allPassives.length) {
    const pHead = new PIXI.Text({
      text: '被动技能',
      style: { fontFamily: FONT_UI, fontSize: 13, fontWeight: '800', fill: INK.secondary },
    });
    pHead.position.set(vx, vy + y - scrollY);
    body.addChild(pHead);
    y += 22;

    for (const p of allPassives) {
      const text = (p.entries || []).join('\n') || p.description || '';
      const head = new PIXI.Text({
        text: `${p.name || p.kind}${p.kind === '阵营被动' ? '（阵营被动）' : ''}`,
        style: { fontFamily: FONT_UI, fontSize: 12.5, fontWeight: '800', fill: INK.gold },
      });
      const desc = new PIXI.Text({
        text: wrapCjkText(text, maxChars - 2),
        style: {
          fontFamily: FONT_UI, fontSize: 12, fill: INK.primary, lineHeight: 18,
          wordWrap: true, breakWords: true, wordWrapWidth: vw - 22,
        },
      });
      const bh = 28 + desc.height + 10;
      const box = new PIXI.Graphics();
      box.roundRect(vx, vy + y - scrollY, vw, bh, 8)
        .fill({ color: INK.goldBg, alpha: 0.65 })
        .stroke({ width: 1.1, color: INK.gold, alpha: 0.55 });
      head.position.set(vx + 11, vy + y - scrollY + 7);
      desc.position.set(vx + 11, vy + y - scrollY + 27);
      body.addChild(box, head, desc);
      y += bh + 7;
    }
    y += 6;
  }

  // Section 3: ALL Printed Skills (click/hover to view full verbatim card right beside!)
  if (skills.length) {
    const skHead = new PIXI.Text({
      text: '技能牌组',
      style: { fontFamily: FONT_UI, fontSize: 13, fontWeight: '800', fill: INK.secondary },
    });
    skHead.position.set(vx, vy + y - scrollY);
    body.addChild(skHead);
    y += 22;

    for (const sk of skills) {
      const isActive = activeSkill && activeSkill.id === sk.id;
      const row = new PIXI.Container();
      row.position.set(vx, vy + y - scrollY);
      const rg = new PIXI.Graphics();
      rg.roundRect(0, 0, vw, 38, 8)
        .fill({ color: isActive ? theme.softBg : INK.paperSoft })
        .stroke({ width: isActive ? 2 : 1, color: isActive ? theme.accent : INK.line });
      rg.circle(20, 19, 11).fill({ color: theme.accent });
      row.addChild(rg);

      const cTxt = new PIXI.Text({
        text: String(sk.cost),
        style: { fontFamily: FONT_NUM, fontSize: 13, fontWeight: '800', fill: INK.paper },
      });
      cTxt.anchor.set(0.5);
      cTxt.position.set(20, 19);
      const nTxt = new PIXI.Text({
        text: sk.name,
        style: { fontFamily: FONT_UI, fontSize: 13, fontWeight: '800', fill: INK.primary },
      });
      nTxt.anchor.set(0, 0.5);
      nTxt.position.set(38, 19);
      row.addChild(cTxt, nTxt);

      // Right side: die icons + exact roll ranges (NO Lv.X!)
      let dx = vw - 10;
      for (let i = (sk.dice || []).length - 1; i >= 0; i--) {
        const d = sk.dice[i];
        const ds = DIE_STYLE[d.type] || DIE_STYLE.blank;
        const rt = new PIXI.Text({
          text: formatDieRange(d),
          style: { fontFamily: FONT_NUM, fontSize: 11.5, fontWeight: '800', fill: ds.color },
        });
        rt.anchor.set(1, 0.5);
        rt.position.set(dx, 19);
        row.addChild(rt);
        dx -= rt.width + 12;
        drawDieIcon(rg, d.type, dx + 3, 19, 6.5, ds.color);
        dx -= 12;
      }

      row.eventMode = 'static';
      row.cursor = 'pointer';
      row.on('pointerover', () => {
        if (!isActive) onSelectSkill(sk.id);
      });
      row.on('pointertap', (e) => {
        e.stopPropagation();
        onSelectSkill(sk.id);
      });
      body.addChild(row);
      y += 44;
    }
  }

  root._maxScroll = Math.max(0, y - vh + 24);

  // Right Side: Full 100% Verbatim Card Panel for the hovered/selected skill!
  if (activeSkill) {
    const cardPanel = buildVerbatimCardPanel(activeSkill, { side, ownerName: character.name, width: cardW });
    cardPanel.position.set(px + leftW + 18, Math.max(24, py + Math.max(0, (panelH - cardPanel._boxHeight) / 2)));
    cardPanel.eventMode = 'static';
    cardPanel.on('pointertap', (e) => e.stopPropagation());
    root.addChild(cardPanel);
  }

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

export function buildDrawSelectOverlay(w, h, { prompt, selectedIds, onToggle, onConfirm, onHoverCard }) {
  const root = new PIXI.Container();
  const theme = SIDE_THEME[prompt.side] || SIDE_THEME[1];

  const veil = new PIXI.Graphics();
  veil.rect(0, 0, w, h).fill({ color: 0xf4efe4, alpha: 0.95 });
  veil.eventMode = 'static';
  root.addChild(veil);

  const cx = w / 2;
  const title = new PIXI.Text({
    text: `${theme.name} · 选 ${prompt.discard_count} 张置底（${selectedIds.size}/${prompt.discard_count}）`,
    style: { fontFamily: FONT_UI, fontSize: 22, fontWeight: '800', fill: theme.accent },
  });
  title.anchor.set(0.5);
  title.position.set(cx, 74);
  root.addChild(title);

  const count = prompt.candidates.length;
  const cardW = 144;
  const cardH = 198;
  const spacing = Math.min(174, (w - 140) / Math.max(1, count));
  const startX = cx - ((count - 1) * spacing) / 2;
  const cardY = h * 0.46;

  prompt.candidates.forEach((card, i) => {
    const isMarked = selectedIds.has(card.id);
    const holder = new PIXI.Container();
    holder.position.set(startX + i * spacing, isMarked ? cardY + 24 : cardY - 6);
    const spr = buildCardFront(card, {
      side: prompt.side,
      ownerName: card.character_name || '',
      showOwner: true,
      width: cardW,
      height: cardH,
      legal: true,
      selected: isMarked,
    });
    holder.addChild(spr);

    const pill = new PIXI.Graphics();
    pill.roundRect(-42, cardH / 2 + 12, 84, 24, 7).fill({ color: isMarked ? 0xcf4932 : 0x1c8a64 });
    holder.addChild(pill);
    const bTxt = new PIXI.Text({
      text: isMarked ? '置底' : '保留',
      style: { fontFamily: FONT_UI, fontSize: 12, fontWeight: '800', fill: INK.paper },
    });
    bTxt.anchor.set(0.5);
    bTxt.position.set(0, cardH / 2 + 24);
    holder.addChild(bTxt);

    holder.eventMode = 'static';
    holder.cursor = 'pointer';
    holder.on('pointerover', () => onHoverCard && onHoverCard(card, prompt.side, card.character_name || ''));
    holder.on('pointerout', () => onHoverCard && onHoverCard(null));
    holder.on('pointertap', (e) => {
      e.stopPropagation();
      onToggle(card.id);
    });
    root.addChild(holder);
  });

  const ready = selectedIds.size === prompt.discard_count;
  const btn = makeSealButton('确认', {
    width: 176, height: 44, accent: ready ? theme.accent : INK.muted, solid: ready, disabled: !ready, fontSize: 15,
    onClick: () => onConfirm(),
  });
  btn.position.set(cx - 88, h - 94);
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

export function buildRosterOverlay(w, h, {
  catalog,
  team1,
  team2,
  assignSide,
  hoveredChar,
  onSetAssignSide,
  onToggleChar,
  onHoverChar,
  onStart,
  onCancel,
}) {
  const root = new PIXI.Container();
  const veil = new PIXI.Graphics();
  veil.rect(0, 0, w, h).fill({ color: 0xf5f1e7, alpha: 0.98 });
  veil.eventMode = 'static';
  root.addChild(veil);

  const pad = 26;
  const title = new PIXI.Text({
    text: '编队选人（每方 1～3 名）',
    style: { fontFamily: FONT_UI, fontSize: 20, fontWeight: '800', fill: INK.primary },
  });
  title.position.set(pad, 18);
  root.addChild(title);

  [1, 2].forEach((s, idx) => {
    const t = SIDE_THEME[s];
    const active = assignSide === s;
    const list = s === 1 ? team1 : team2;
    const names = list.map((id) => catalog.find((c) => c.id === id)?.name || id).join('、') || '未选';
    const b = makeSealButton(`${t.name}（${list.length}/3）：${names}`, {
      width: 286, height: 36, accent: t.accent, fill: active ? t.softBg : INK.paper, solid: active, fontSize: 12.5,
      onClick: () => onSetAssignSide(s),
    });
    b.position.set(pad + idx * 300, 52);
    root.addChild(b);
  });

  const gridX = pad;
  const gridY = 104;
  const gridW = Math.floor((w - pad * 3) * 0.56);
  const cols = gridW > 620 ? 3 : 2;
  const gap = 11;
  const cellW = Math.floor((gridW - gap * (cols - 1)) / cols);
  const cellH = 74;

  catalog.forEach((char, idx) => {
    const col = idx % cols;
    const row = Math.floor(idx / cols);
    const x = gridX + col * (cellW + gap);
    const y = gridY + row * (cellH + gap);
    if (y + cellH > h - 76) return;

    const in1 = team1.indexOf(char.id);
    const in2 = team2.indexOf(char.id);
    const ownerSide = in1 >= 0 ? 1 : in2 >= 0 ? 2 : 0;
    const borderCol = ownerSide ? SIDE_THEME[ownerSide].accent : hoveredChar?.id === char.id ? INK.gold : INK.line;

    const card = new PIXI.Container();
    card.position.set(x, y);
    const bg = new PIXI.Graphics();
    bg.roundRect(2, 4, cellW, cellH, 10).fill({ color: INK.shadow, alpha: 0.2 });
    bg.roundRect(0, 0, cellW, cellH, 10)
      .fill({ color: ownerSide ? SIDE_THEME[ownerSide].softBg : INK.paper })
      .stroke({ width: ownerSide ? 2.2 : 1.3, color: borderCol });
    card.addChild(bg);

    const nm = new PIXI.Text({
      text: char.name,
      style: { fontFamily: FONT_UI, fontSize: 14, fontWeight: '800', fill: INK.primary },
    });
    nm.position.set(12, 10);
    const meta = new PIXI.Text({
      text: `${char.faction || '独立'} · ${RANK_LABEL[char.rank] || ''} · 生命 ${char.max_hp} · ${char.base_duels}交锋`,
      style: { fontFamily: FONT_UI, fontSize: 11, fill: INK.secondary },
    });
    meta.position.set(12, 36);
    card.addChild(nm, meta);

    if (ownerSide) {
      const tag = new PIXI.Graphics();
      tag.roundRect(cellW - 54, 8, 46, 20, 6).fill({ color: SIDE_THEME[ownerSide].accent });
      card.addChild(tag);
      const tTxt = new PIXI.Text({
        text: `P${ownerSide}#${(ownerSide === 1 ? in1 : in2) + 1}`,
        style: { fontFamily: FONT_NUM, fontSize: 11, fontWeight: '800', fill: INK.paper },
      });
      tTxt.anchor.set(0.5);
      tTxt.position.set(cellW - 31, 18);
      card.addChild(tTxt);
    }

    card.eventMode = 'static';
    card.cursor = 'pointer';
    card.on('pointerover', () => onHoverChar(char));
    card.on('pointertap', (e) => {
      e.stopPropagation();
      onToggleChar(char.id);
    });
    root.addChild(card);
  });

  // Right 42%: 100% Verbatim Character Sheet
  const inspX = gridX + gridW + pad;
  const inspY = 104;
  const inspW = w - inspX - pad;
  const inspH = h - inspY - 78;
  const inspBg = new PIXI.Graphics();
  inspBg.roundRect(inspX + 3, inspY + 5, inspW, inspH, 12).fill({ color: INK.shadow, alpha: 0.24 });
  inspBg.roundRect(inspX, inspY, inspW, inspH, 12).fill({ color: INK.paper }).stroke({ width: 1.5, color: INK.line });
  root.addChild(inspBg);

  const target = hoveredChar || catalog[0];
  if (target) {
    let cy = inspY + 14;
    const maxChars = Math.max(28, Math.floor((inspW - 32) / 6.3));
    const h1 = new PIXI.Text({
      text: `${target.name}${target.title ? ' · ' + target.title : ''}`,
      style: { fontFamily: FONT_UI, fontSize: 17.5, fontWeight: '800', fill: INK.primary },
    });
    h1.position.set(inspX + 16, cy);
    root.addChild(h1);
    cy += 26;

    const h2 = new PIXI.Text({
      text: `${target.faction || '独立'} · ${RANK_LABEL[target.rank] || ''} · 生命 ${target.max_hp} · 基础交锋 ${target.base_duels}`,
      style: { fontFamily: FONT_UI, fontSize: 11.5, fontWeight: '700', fill: INK.gold },
    });
    h2.position.set(inspX + 16, cy);
    root.addChild(h2);
    cy += 22;

    const allPassives = [
      ...(target.faction_passives || []).map((p) => ({ ...p, tag: '阵营被动' })),
      ...(target.passives || []).map((p) => ({ ...p, tag: '角色被动' })),
    ];
    for (const p of allPassives) {
      if (cy > inspY + inspH - 72) break;
      const desc = (p.entries || []).join('；') || p.description || '';
      const pt = new PIXI.Text({
        text: wrapCjkText(`【${p.name || p.tag}】${desc}`, maxChars),
        style: {
          fontFamily: FONT_UI, fontSize: 11.5, fill: INK.primary, lineHeight: 16.5,
          wordWrap: true, breakWords: true, wordWrapWidth: inspW - 32,
        },
      });
      pt.position.set(inspX + 16, cy);
      root.addChild(pt);
      cy += pt.height + 6;
    }

    cy += 6;
    for (const sk of target.skills || []) {
      if (cy > inspY + inspH - 36) break;
      const diceStr = (sk.dice || []).map((d) => `${DIE_STYLE[d.type]?.label || d.type} ${formatDieRange(d)}`).join(' / ');
      const st = new PIXI.Text({
        text: wrapCjkText(`[${sk.cost}费] ${sk.name}：${diceStr}`, maxChars),
        style: {
          fontFamily: FONT_UI, fontSize: 11.5, fontWeight: '800', fill: INK.primary, lineHeight: 16,
          wordWrap: true, breakWords: true, wordWrapWidth: inspW - 32,
        },
      });
      st.position.set(inspX + 16, cy);
      root.addChild(st);
      cy += st.height + 4;
      if (sk.entries && sk.entries.length && cy < inspY + inspH - 22) {
        const se = new PIXI.Text({
          text: wrapCjkText(sk.entries.join('\n'), maxChars - 2),
          style: {
            fontFamily: FONT_UI, fontSize: 11, fill: INK.secondary, lineHeight: 15.5,
            wordWrap: true, breakWords: true, wordWrapWidth: inspW - 38,
          },
        });
        se.position.set(inspX + 22, cy);
        root.addChild(se);
        cy += se.height + 6;
      }
    }
  }

  const valid = team1.length >= 1 && team2.length >= 1;
  const startBtn = makeSealButton('开局', {
    width: 156, height: 42, accent: valid ? 0x1c8a64 : INK.muted, solid: valid, disabled: !valid, fontSize: 15,
    onClick: () => onStart([team1.slice(), team2.slice()]),
  });
  startBtn.position.set(w - pad - 156, h - 58);
  root.addChild(startBtn);

  const cancelBtn = makeSealButton('返回', { width: 116, height: 42, accent: INK.secondary, onClick: onCancel });
  cancelBtn.position.set(w - pad - 156 - 130, h - 58);
  root.addChild(cancelBtn);

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
    for (const para of RULES_VERBATIM) addLine(para, { size: 13, gapAfter: 12 });
  } else if (tab === 'catalog' && catalog) {
    for (const pl of catalog.players || []) {
      const theme = SIDE_THEME[pl.side] || SIDE_THEME[1];
      addLine(`── ${theme.name} ──`, { size: 15, color: theme.accent, bold: true, gapAfter: 8 });
      for (const ch of pl.characters || []) {
        addLine(ch.name, { size: 14.5, color: INK.primary, bold: true, gapAfter: 6, indent: 4 });
        for (const p of [...(ch.faction_passives || []), ...(ch.passives || [])]) {
          addLine(`【${p.name || '被动'}】${(p.entries || []).join('\n')}`, { size: 12, color: INK.gold, gapAfter: 6, indent: 12 });
        }
        for (const sk of ch.skills || []) {
          const head = `[${sk.cost}费] ${sk.name}`;
          const diceLines = (sk.dice || []).map((d) => {
            const ds = DIE_STYLE[d.type]?.label || d.type;
            const ent = (d.entries || []).join('；');
            return `${ds} ${formatDieRange(d)}${ent ? '：' + ent : ''}`;
          });
          const bodyLines = [...(sk.entries || []), ...diceLines].join('\n');
          addLine(`${head}\n${bodyLines}`, { size: 12, color: INK.secondary, gapAfter: 8, indent: 12 });
        }
      }
    }
    const statuses = Object.entries(catalog.statuses || {});
    if (statuses.length) {
      addLine('── 特殊状态 ──', { size: 15, color: INK.gold, bold: true, gapAfter: 8 });
      for (const [name, list] of statuses) addLine(`【${name}】${list.join('\n')}`, { size: 12, color: INK.primary, gapAfter: 6, indent: 10 });
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

export function buildPileOverlay(w, h, { title, side, cards, charNames, onHoverCard, onClose }) {
  const root = new PIXI.Container();
  const veil = new PIXI.Graphics();
  veil.rect(0, 0, w, h).fill({ color: 0xf4efe4, alpha: 0.92 });
  veil.eventMode = 'static';
  veil.on('pointertap', onClose);
  root.addChild(veil);

  const head = new PIXI.Text({
    text: `${title}（${cards.length}）`,
    style: { fontFamily: FONT_UI, fontSize: 19, fontWeight: '800', fill: INK.primary },
  });
  head.anchor.set(0.5);
  head.position.set(w / 2, 74);
  root.addChild(head);

  if (cards.length) {
    const cols = Math.min(cards.length, 6);
    const gapX = 152;
    const gapY = 206;
    const rows = Math.ceil(cards.length / cols);
    const startY = h / 2 - ((rows - 1) * gapY) / 2;
    cards.forEach((card, i) => {
      const r = Math.floor(i / cols);
      const c = i % cols;
      const rowCount = Math.min(cols, cards.length - r * cols);
      const startX = w / 2 - ((rowCount - 1) * gapX) / 2;
      const spr = buildCardFront(card, {
        side, ownerName: charNames[card.character_id] || '', showOwner: true, width: 138, height: 190, legal: true,
      });
      spr.position.set(startX + c * gapX, startY + r * gapY);
      spr.eventMode = 'static';
      spr.cursor = 'pointer';
      spr.on('pointerover', () => onHoverCard && onHoverCard(card, side, charNames[card.character_id] || ''));
      spr.on('pointerout', () => onHoverCard && onHoverCard(null));
      spr.on('pointertap', (e) => e.stopPropagation());
      root.addChild(spr);
    });
  }
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
