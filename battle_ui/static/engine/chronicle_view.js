/**
 * Interactive Hierarchical Battle Chronicle & Real-Time Math Audit View for 《光点计划 III》.
 *
 * Replaces flat plain-text log walls with a 4-level battle ledger:
 *   Turn -> Block (Phase / Collapsible Duel) -> Round (Die Roll Formula Plaque) -> Causal Ledger Item
 *
 * Capabilities:
 *  - Turn tabs (`全部回合` | `T1` | `T2` ...), Category filters (`全部记录` | `拼点与伤害` | `状态与词条` | `阵亡与摧毁`),
 *    and per-Character focus chips
 *  - Collapsible Duel Cards with matchup summary & net HP swing badges
 *  - Exact arithmetic formula plaques for every die roll and every damage/shield settlement
 *  - Interactive Entity Inspection Pills: hover any referenced `[卡牌]` to preview its full `buildFullCard`,
 *    hover any `[状态]` to inspect its icon & rules, click `[角色]` to jump to their sheet
 *  - One-click Markdown export (`formatChronicleMarkdown`)
 *  - Strictly sunlit warm-paper palette (ZERO black, ZERO blue-purple, ZERO DOM).
 */

import * as PIXI from '../vendor/pixi.min.mjs';
import {
  FONT_UI,
  FONT_NUM,
  INK,
  SIDE_THEME,
  DIE_STYLE,
  OFFICIAL_STATUS_RULES,
  getStatusColor,
  drawUnifiedDieFrame,
  wrapCjkText,
} from './design_system.js';

const CATEGORY_STYLE = {
  combat:  { color: 0xc2641a, bg: 0xfef6ea, label: '拼点' },
  damage:  { color: 0xc8452e, bg: 0xfdf0ed, label: '伤害' },
  passive: { color: 0xb88418, bg: 0xfcf6e3, label: '词条' },
  status:  { color: 0x1a825e, bg: 0xecf7f2, label: '状态' },
  card:    { color: 0x6b6052, bg: 0xf7f3ea, label: '牌序' },
  key:     { color: 0xb02e57, bg: 0xfceef3, label: '重要' },
};

const FILTER_TABS = [
  { id: 'all', label: '全部记录' },
  { id: 'combat_damage', label: '拼点与伤害' },
  { id: 'status_passive', label: '状态与词条' },
  { id: 'key', label: '阵亡与摧毁' },
];

function matchesCategoryFilter(category, filterId) {
  if (!filterId || filterId === 'all') return true;
  if (filterId === 'combat_damage') return category === 'combat' || category === 'damage' || category === 'key';
  if (filterId === 'status_passive') return category === 'status' || category === 'passive';
  if (filterId === 'key') return category === 'key';
  return true;
}

function itemMatchesCharacter(item, charFilterId) {
  if (!charFilterId) return true;
  return (item.entities || []).some(
    (e) => (e.kind === 'char' && e.id === charFilterId) || (e.kind === 'card' && e.character_id === charFilterId),
  );
}

function roundMatchesFilters(rnd, catFilter, charFilter) {
  const rollHit = (!catFilter || catFilter === 'all' || catFilter === 'combat_damage')
    && (!charFilter || (rnd.rolls || []).some((r) => r.character_id === charFilter));
  const matchedItems = (rnd.items || []).filter(
    (it) => matchesCategoryFilter(it.category, catFilter) && itemMatchesCharacter(it, charFilter),
  );
  return { keep: Boolean(rollHit || matchedItems.length > 0), matchedItems };
}

export function buildCatalogLookups(catalog) {
  const skillsById = new Map();
  const skillsByName = new Map();
  const charsById = new Map();
  for (const pl of catalog?.players || []) {
    for (const ch of pl.characters || []) {
      charsById.set(ch.id, { ...ch, side: pl.side });
      for (const sk of ch.skills || []) {
        const enriched = { ...sk, character_id: ch.id, _owner_name: ch.name, _side: pl.side };
        skillsById.set(sk.id, enriched);
        skillsByName.set(`${pl.side}:${sk.name}`, enriched);
        if (!skillsByName.has(sk.name)) skillsByName.set(sk.name, enriched);
        for (const fm of sk.forms || []) {
          if (fm.name) {
            const fmCard = { ...fm, character_id: ch.id, _owner_name: ch.name, _side: pl.side };
            skillsByName.set(`${pl.side}:${fm.name}`, fmCard);
            if (!skillsByName.has(fm.name)) skillsByName.set(fm.name, fmCard);
          }
        }
      }
    }
  }
  return { skillsById, skillsByName, charsById };
}

export function formatChronicleMarkdown(chronicle, { players = [], winnerSide = null, turn = 1, history = [] } = {}) {
  const turns = chronicle?.turns || [];
  const lines = ['# 《光点计划 III》对局战报'];
  if (players.length) {
    const pBits = players.map((p) => `P${p.side} ${p.name || ''}（${(p.characters || []).map((c) => c.name).join('、')}）`);
    lines.push(`- **参战阵容**：${pBits.join('  vs  ')}`);
  }
  if (winnerSide != null) {
    lines.push(`- **对局结果**：${winnerSide ? `P${winnerSide} 获胜` : '双方平局'}（共 ${turn} 回合）`);
  }
  lines.push('');

  if (!turns.length) {
    if (history.length) {
      history.forEach((line, idx) => lines.push(`${idx + 1}. ${line}`));
    } else {
      lines.push('尚无战报记录。');
    }
    return lines.join('\n') + '\n';
  }

  for (const t of turns) {
    const initStr = t.first_player ? ` · ${t.first_player}先手` : '';
    const d1 = t.stats?.damage_by_side?.['1'] ?? 0;
    const d2 = t.stats?.damage_by_side?.['2'] ?? 0;
    lines.push(`## 第 ${t.turn} 回合${initStr}（P1 造伤 ${d1} / P2 造伤 ${d2}）`);
    for (const b of t.blocks || []) {
      if (b.kind === 'duel') {
        const m1 = b.matchup?.['1'];
        const m2 = b.matchup?.['2'];
        const s1 = m1 ? `${m1.character_name}「${m1.card_name}」` : '—';
        const s2 = m2 ? `${m2.character_name}「${m2.card_name}」` : '—';
        const dh1 = b.summary?.hp_delta?.['1'] || 0;
        const dh2 = b.summary?.hp_delta?.['2'] || 0;
        const swing = (dh1 || dh2) ? ` [生命变化 P1:${dh1 > 0 ? '+' + dh1 : dh1} / P2:${dh2 > 0 ? '+' + dh2 : dh2}]` : '';
        lines.push(`### ${b.title}：${s1}  vs  ${s2}${swing}`);
      } else {
        lines.push(`### ${b.title}`);
      }
      for (const rnd of b.rounds || []) {
        const hasRoundHead = Boolean(rnd.label && rnd.round > 0);
        if (hasRoundHead) lines.push(`- **${rnd.label}**`);
        const pad = hasRoundHead ? '  ' : '';
        for (const it of rnd.items || []) {
          lines.push(`${pad}- ${it.text}`);
          if (it.formula) lines.push(`${pad}  - \`算式：${it.formula}\``);
        }
      }
    }
    lines.push('');
  }
  return lines.join('\n').trim() + '\n';
}

function makeMiniPill(label, {
  height = 24,
  padX = 9,
  fontSize = 11,
  accent = INK.secondary,
  active = false,
  bgFill = INK.paper,
  onClick = null,
  onHover = null,
} = {}) {
  const c = new PIXI.Container();
  const txt = new PIXI.Text({
    text: label,
    style: {
      fontFamily: FONT_UI,
      fontSize,
      fontWeight: active ? '900' : '700',
      fill: active ? INK.paper : accent,
    },
  });
  const w = Math.ceil(txt.width) + padX * 2;
  const g = new PIXI.Graphics();
  const draw = (hov = false) => {
    g.clear();
    g.roundRect(0, 0, w, height, 6)
      .fill({ color: active ? accent : hov ? INK.goldBg : bgFill, alpha: 0.96 })
      .stroke({ width: active || hov ? 1.35 : 0.95, color: active || hov ? accent : INK.line });
  };
  draw(false);
  txt.anchor.set(0.5);
  txt.position.set(w / 2, height / 2 + 0.5);
  c.addChild(g, txt);
  c._width = w;
  c._height = height;
  if (onClick || onHover) {
    c.eventMode = 'static';
    c.cursor = 'pointer';
    c.hitArea = new PIXI.Rectangle(0, 0, w, height);
    c.on('pointerover', () => {
      draw(true);
      if (onHover) onHover(true, c);
    });
    c.on('pointerout', () => {
      draw(false);
      if (onHover) onHover(false, c);
    });
    if (onClick) {
      c.on('pointertap', (e) => {
        e.stopPropagation();
        onClick();
      });
    }
  }
  return c;
}

/**
 * Populate an interactive Chronicle Toolbar + Scrollable Viewport inside `host`.
 * Returns `{ toolbarH, buildBody(bodyContainer, contentW) -> totalHeight }`.
 */
export function renderChronicleSection({
  toolbarHost,
  toolbarX,
  toolbarY,
  toolbarW,
  chronicle,
  history = [],
  catalog = null,
  uiState = {},
  makeSealButton,
  onUiChange,
  onCopyMarkdown = null,
  onExportModal = null,
  onHoverCard = null,
  onHoverStatus = null,
  onOpenHero = null,
  viewportCheck = null,
}) {
  const turns = Array.isArray(chronicle?.turns) ? chronicle.turns : [];
  const selectedTurn = uiState.turnFilter ?? 'all';
  const categoryFilter = uiState.categoryFilter || 'all';
  const charFilter = uiState.charFilter || null;
  const collapsedBlocks = uiState.collapsedBlocks instanceof Set ? uiState.collapsedBlocks : new Set();
  const lookups = buildCatalogLookups(catalog);

  // ── Toolbar Row 1: Turn Selector Pills + Collapse/Expand + Copy / Export ──
  let ty = toolbarY;
  let tx = toolbarX;
  const turnPills = [{ id: 'all', label: '全部回合' }, ...turns.map((t) => ({ id: t.turn, label: `T${t.turn}` }))];
  const rightBtnsReserve = (onCopyMarkdown ? 106 : 0) + (onExportModal ? 96 : 0) + 92;
  const maxTurnAreaW = Math.max(160, toolbarW - rightBtnsReserve);

  for (const tp of turnPills) {
    const pill = makeMiniPill(tp.label, {
      height: 25,
      padX: 9,
      fontSize: 11.2,
      accent: 0x1a825e,
      active: selectedTurn === tp.id,
      onClick: () => onUiChange?.({ turnFilter: tp.id, scrollY: 0 }),
    });
    if (tx - toolbarX + pill._width > maxTurnAreaW && tx > toolbarX) break;
    pill.position.set(tx, ty + 2);
    toolbarHost.addChild(pill);
    tx += pill._width + 5;
  }

  let rx = toolbarX + toolbarW;
  if (onExportModal) {
    rx -= 90;
    const expBtn = makeSealButton('全文弹窗', {
      width: 90, height: 27, accent: INK.secondary, fontSize: 11.2, radius: 7, onClick: onExportModal,
    });
    expBtn.position.set(rx, ty + 1);
    toolbarHost.addChild(expBtn);
    rx -= 6;
  }
  if (onCopyMarkdown) {
    rx -= 98;
    const cpBtn = makeSealButton('复制战报', {
      width: 98, height: 27, accent: INK.goldDeep, solid: true, fontSize: 11.4, radius: 7, onClick: onCopyMarkdown,
    });
    cpBtn.position.set(rx, ty + 1);
    toolbarHost.addChild(cpBtn);
    rx -= 6;
  }
  if (turns.length > 0) {
    const allDuelIds = turns.flatMap((t) => (t.blocks || []).filter((b) => b.kind === 'duel').map((b) => b.id));
    const anyExpanded = allDuelIds.some((id) => !collapsedBlocks.has(id));
    rx -= 82;
    const colBtn = makeMiniPill(anyExpanded ? '折叠交锋' : '展开全部', {
      height: 25,
      padX: 8,
      fontSize: 10.8,
      accent: INK.goldDeep,
      onClick: () => {
        const nextSet = new Set();
        if (anyExpanded) {
          for (const id of allDuelIds) nextSet.add(id);
        }
        onUiChange?.({ collapsedBlocks: nextSet, scrollY: 0 });
      },
    });
    colBtn.position.set(rx, ty + 2);
    toolbarHost.addChild(colBtn);
  }
  ty += 32;

  // ── Toolbar Row 2: Category Filter Pills + Participating Character Focus Chips ──
  let fx = toolbarX;
  for (const ft of FILTER_TABS) {
    const pill = makeMiniPill(ft.label, {
      height: 23,
      padX: 8,
      fontSize: 10.6,
      accent: INK.goldDeep,
      active: categoryFilter === ft.id,
      onClick: () => onUiChange?.({ categoryFilter: ft.id, scrollY: 0 }),
    });
    pill.position.set(fx, ty);
    toolbarHost.addChild(pill);
    fx += pill._width + 5;
  }

  fx += 8;
  const allChars = [...lookups.charsById.values()];
  if (allChars.length > 0 && fx + 64 < toolbarX + toolbarW) {
    const allChip = makeMiniPill('全员', {
      height: 23,
      padX: 7,
      fontSize: 10.5,
      accent: INK.secondary,
      active: !charFilter,
      onClick: () => onUiChange?.({ charFilter: null, scrollY: 0 }),
    });
    allChip.position.set(fx, ty);
    toolbarHost.addChild(allChip);
    fx += allChip._width + 4;

    for (const ch of allChars) {
      const sideCol = (SIDE_THEME[ch.side] || SIDE_THEME[1]).accent;
      const chip = makeMiniPill(ch.name, {
        height: 23,
        padX: 7,
        fontSize: 10.5,
        accent: sideCol,
        active: charFilter === ch.id,
        onClick: () => onUiChange?.({ charFilter: charFilter === ch.id ? null : ch.id, scrollY: 0 }),
      });
      if (fx + chip._width > toolbarX + toolbarW) {
        chip.destroy({ children: true });
        break;
      }
      chip.position.set(fx, ty);
      toolbarHost.addChild(chip);
      fx += chip._width + 4;
    }
  }
  ty += 29;

  const toolbarH = ty - toolbarY;

  const buildBody = (body, contentW) => {
    let y = 4;
    const maxChars = Math.max(36, Math.floor(contentW / 6.8));

    // Legacy plain-text fallback when structured chronicle has no turns
    if (!turns.length) {
      if (!history.length) {
        const empty = new PIXI.Text({
          text: '尚无战报记录。',
          style: { fontFamily: FONT_UI, fontSize: 13, fill: INK.muted },
        });
        empty.position.set(8, 12);
        body.addChild(empty);
        return 44;
      }
      history.slice().reverse().forEach((line, i) => {
        const row = new PIXI.Container();
        const txt = new PIXI.Text({
          text: wrapCjkText(`${history.length - i}. ${line}`, maxChars - 3),
          style: {
            fontFamily: FONT_UI, fontSize: 12.4, fontWeight: i === 0 ? '800' : '400',
            fill: i === 0 ? INK.goldDeep : INK.primary, lineHeight: 19,
            wordWrap: true, breakWords: true, wordWrapWidth: contentW - 22,
          },
        });
        const rh = Math.ceil(txt.height) + 12;
        const rg = new PIXI.Graphics();
        rg.roundRect(0, 0, contentW, rh, 5)
          .fill({ color: i === 0 ? INK.goldBg : i % 2 === 0 ? INK.paper : INK.paperSoft, alpha: 0.92 })
          .stroke({ width: 0.75, color: i === 0 ? INK.gold : INK.hairline });
        row.addChild(rg, txt);
        txt.position.set(11, 6);
        row.position.set(0, y);
        row._itemTop = y;
        row._itemBottom = y + rh;
        body.addChild(row);
        y += rh + 6;
      });
      return y;
    }

    const shownTurns = selectedTurn === 'all' ? turns : turns.filter((t) => t.turn === selectedTurn);
    let renderedAny = false;

    for (const t of shownTurns) {
      const turnBlocks = [];
      for (const b of t.blocks || []) {
        const filteredRounds = [];
        for (const rnd of b.rounds || []) {
          const { keep, matchedItems } = roundMatchesFilters(rnd, categoryFilter, charFilter);
          if (keep) filteredRounds.push({ ...rnd, items: matchedItems });
        }
        const matchupCharHit = charFilter && Object.values(b.matchup || {}).some((m) => m?.character_id === charFilter);
        if (filteredRounds.length > 0 || (b.kind === 'duel' && categoryFilter === 'all' && (!charFilter || matchupCharHit))) {
          turnBlocks.push({ ...b, rounds: filteredRounds });
        }
      }
      if (!turnBlocks.length && (categoryFilter !== 'all' || charFilter)) continue;
      renderedAny = true;

      // ── Level 1: Turn Ribbon Header ──
      const turnRow = new PIXI.Container();
      const th = 32;
      const tg = new PIXI.Graphics();
      const firstTheme = t.first_side ? SIDE_THEME[t.first_side] : null;
      tg.roundRect(0, 0, contentW, th, 7)
        .fill({ color: INK.goldBg, alpha: 0.95 })
        .stroke({ width: 1.2, color: INK.gold, alpha: 0.85 });
      tg.roundRect(0, 3, 4, th - 6, 2).fill({ color: firstTheme ? firstTheme.accent : INK.gold });
      turnRow.addChild(tg);

      const initLabel = t.first_player ? `  ·  ${t.first_player}先手` : '';
      const tTitle = new PIXI.Text({
        text: `第 ${t.turn} 回合${initLabel}`,
        style: { fontFamily: FONT_UI, fontSize: 13.5, fontWeight: '900', fill: INK.strong },
      });
      tTitle.anchor.set(0, 0.5);
      tTitle.position.set(14, th / 2);
      turnRow.addChild(tTitle);

      const d1 = t.stats?.damage_by_side?.['1'] ?? 0;
      const d2 = t.stats?.damage_by_side?.['2'] ?? 0;
      const deaths = (t.stats?.deaths || []).map((n) => `${n}阵亡`);
      const collapses = (t.stats?.collapses || []).map((n) => `${n}光点形态群崩塌`);
      const statSummary = [`P1 造伤 ${d1}`, `P2 造伤 ${d2}`, ...collapses, ...deaths].join('  ·  ');
      const tStats = new PIXI.Text({
        text: statSummary,
        style: { fontFamily: FONT_UI, fontSize: 11, fontWeight: '800', fill: INK.secondary },
      });
      tStats.anchor.set(1, 0.5);
      tStats.position.set(contentW - 12, th / 2);
      turnRow.addChild(tStats);

      turnRow.position.set(0, y);
      turnRow._itemTop = y;
      turnRow._itemBottom = y + th;
      body.addChild(turnRow);
      y += th + 7;

      // ── Level 2: Phase / Collapsible Duel Blocks ──
      for (const b of turnBlocks) {
        const isDuel = b.kind === 'duel';
        const isCollapsed = isDuel && collapsedBlocks.has(b.id);

        const blockHead = new PIXI.Container();
        const bh = isDuel ? 34 : 26;
        const bg = new PIXI.Graphics();
        const duelAccent = b.duel_kind === 'pre_reveal' ? 0xbf5224 : b.duel_kind === 'instant' ? 0xc26e1d : 0xc8452e;
        const drawBlockHead = (hov = false) => {
          bg.clear();
          bg.roundRect(4, 0, contentW - 4, bh, 6)
            .fill({ color: isDuel ? (hov ? 0xfdf2ea : 0xfaf4e8) : INK.paperSoft, alpha: 0.96 })
            .stroke({ width: isDuel ? (hov ? 1.4 : 1.05) : 0.85, color: isDuel ? duelAccent : INK.line, alpha: 0.85 });
          bg.roundRect(4, 3, 3.2, bh - 6, 1.5).fill({ color: isDuel ? duelAccent : INK.goldDeep });
        };
        drawBlockHead(false);
        blockHead.addChild(bg);

        let headLabel = b.title;
        if (isDuel) {
          const arrow = isCollapsed ? '▶' : '▼';
          const m1 = b.matchup?.['1'];
          const m2 = b.matchup?.['2'];
          const s1 = m1 ? `${m1.character_name}「${m1.card_name}」${m1.skipped ? '(跳)' : ''}` : '—';
          const s2 = m2 ? `${m2.character_name}「${m2.card_name}」${m2.skipped ? '(跳)' : ''}` : '—';
          headLabel = `${arrow} ${b.title}  ·  ${s1}  vs  ${s2}`;
        } else {
          headLabel = b.title;
        }

        const bhTxt = new PIXI.Text({
          text: headLabel,
          style: {
            fontFamily: FONT_UI,
            fontSize: isDuel ? 12.4 : 11.6,
            fontWeight: '800',
            fill: isDuel ? INK.strong : INK.secondary,
          },
        });
        bhTxt.anchor.set(0, 0.5);
        bhTxt.position.set(15, bh / 2);
        blockHead.addChild(bhTxt);

        if (isDuel) {
          const dh1 = b.summary?.hp_delta?.['1'] || 0;
          const dh2 = b.summary?.hp_delta?.['2'] || 0;
          const metaBits = [];
          if (b.summary?.rounds > 0) metaBits.push(`${b.summary.rounds}轮`);
          if (dh1) metaBits.push(`P1 ${dh1 > 0 ? '+' + dh1 : dh1}HP`);
          if (dh2) metaBits.push(`P2 ${dh2 > 0 ? '+' + dh2 : dh2}HP`);
          for (const hl of (b.summary?.highlights || []).slice(0, 2)) metaBits.push(hl);
          if (metaBits.length) {
            const sumTxt = new PIXI.Text({
              text: metaBits.join(' · '),
              style: { fontFamily: FONT_UI, fontSize: 10.6, fontWeight: '800', fill: duelAccent },
            });
            sumTxt.anchor.set(1, 0.5);
            sumTxt.position.set(contentW - 12, bh / 2);
            if (bhTxt.x + bhTxt.width + 12 > sumTxt.x - sumTxt.width) {
              const avail = Math.max(80, sumTxt.x - sumTxt.width - bhTxt.x - 10);
              bhTxt.scale.x = Math.min(1, avail / Math.max(1, bhTxt.width));
            }
            blockHead.addChild(sumTxt);
          }

          blockHead._interactiveItem = true;
          blockHead.eventMode = 'static';
          blockHead.cursor = 'pointer';
          blockHead.hitArea = new PIXI.Rectangle(4, 0, contentW - 4, bh);
          blockHead.on('pointerover', () => drawBlockHead(true));
          blockHead.on('pointerout', () => drawBlockHead(false));
          blockHead.on('pointertap', (e) => {
            e.stopPropagation();
            const nextSet = new Set(collapsedBlocks);
            if (nextSet.has(b.id)) nextSet.delete(b.id);
            else nextSet.add(b.id);
            onUiChange?.({ collapsedBlocks: nextSet });
          });
        }

        blockHead.position.set(0, y);
        blockHead._itemTop = y;
        blockHead._itemBottom = y + bh;
        body.addChild(blockHead);
        y += bh + 5;

        if (isCollapsed) continue;

        // ── Level 3 & 4: Rounds, Roll Formula Plaques & Causal Ledger Items ──
        for (const rnd of b.rounds || []) {
          // Optional Round Header + Visual Die Roll Formula Plaque
          if (rnd.rolls && rnd.rolls.length > 0 && matchesCategoryFilter('combat', categoryFilter)) {
            const rollCard = new PIXI.Container();
            const rollRowsH = rnd.rolls.length * 24 + 8;
            const rg = new PIXI.Graphics();
            rg.roundRect(14, 0, contentW - 14, rollRowsH, 6)
              .fill({ color: 0xfdf8ee, alpha: 0.98 })
              .stroke({ width: 1.0, color: INK.gold, alpha: 0.72 });
            rollCard.addChild(rg);

            rnd.rolls.forEach((rl, rIdx) => {
              const ry = 4 + rIdx * 24;
              const ds = DIE_STYLE[rl.die_type] || DIE_STYLE.blank;
              const isWin = rl.result === 'win';
              const isLose = rl.result === 'lose';
              drawUnifiedDieFrame(rg, rl.die_type, 29, ry + 11, 5.6, { active: isWin, muted: isLose });

              const resBadge = rl.result === 'win'
                ? (rl.win_branch_skipped ? '〔胜·压制跳分支〕' : '〔拼胜〕')
                : rl.result === 'lose' ? '〔拼负〕'
                  : rl.result === 'draw' ? '〔拼平〕'
                    : rl.result === 'solo' ? `〔单方面 → ${rnd.target_name || '目标'}〕` : '';
              const laneStr = rl.lane === 'rear' ? '后置·' : '';
              const repStr = rl.is_repeat ? '(重投)' : '';
              const lineStr = `[${rnd.label || '用骰'}] P${rl.side} ${rl.character_name}「${rl.card_name}」#${rl.position}${repStr} ${laneStr}${rl.die_label} ${rl.range_label}  ｜  ${rl.formula_text} ${resBadge}`;

              const rTxt = new PIXI.Text({
                text: lineStr,
                style: {
                  fontFamily: FONT_UI,
                  fontSize: 11.2,
                  fontWeight: isWin ? '900' : '700',
                  fill: isWin ? ds.color : isLose ? INK.muted : INK.primary,
                },
              });
              const maxRW = contentW - 52;
              if (rTxt.width > maxRW) rTxt.scale.x = maxRW / rTxt.width;
              rTxt.anchor.set(0, 0.5);
              rTxt.position.set(41, ry + 11);
              rollCard.addChild(rTxt);
            });

            rollCard.position.set(0, y);
            rollCard._itemTop = y;
            rollCard._itemBottom = y + rollRowsH;
            body.addChild(rollCard);
            y += rollRowsH + 4;
          }

          for (const it of rnd.items || []) {
            // Avoid duplicating pure clash_scored summary text if the visual Roll Formula Plaque above already rendered it,
            // UNLESS there are interactive card entities or no rolls array!
            const catStyle = CATEGORY_STYLE[it.category] || CATEGORY_STYLE.card;
            const indent = isDuel ? 18 : 10;
            const rowW = contentW - indent;
            const row = new PIXI.Container();

            const mainTxt = new PIXI.Text({
              text: wrapCjkText(it.text, Math.max(26, Math.floor((rowW - 22) / 6.6))),
              style: {
                fontFamily: FONT_UI,
                fontSize: 12.0,
                fontWeight: it.category === 'key' || it.category === 'damage' ? '800' : '600',
                fill: it.category === 'key' ? catStyle.color : INK.primary,
                lineHeight: 18,
                wordWrap: true,
                breakWords: true,
                wordWrapWidth: rowW - 22,
              },
            });
            mainTxt.position.set(11, 5);
            let curRowY = 5 + Math.ceil(mainTxt.height);

            // Optional Formula Breakdown Audit Line (skip on clash_scored if Roll Plaque already showed it)
            const showFormulaBox = Boolean(it.formula && !(rnd.rolls?.length > 0 && it.text.startsWith('拼点对决：')));
            let formulaNode = null;
            if (showFormulaBox) {
              curRowY += 3;
              formulaNode = new PIXI.Text({
                text: wrapCjkText(`算式：${it.formula}`, Math.max(28, Math.floor((rowW - 28) / 6.2))),
                style: {
                  fontFamily: FONT_NUM,
                  fontSize: 10.8,
                  fontWeight: '700',
                  fill: INK.goldDeep,
                  lineHeight: 16,
                  wordWrap: true,
                  breakWords: true,
                  wordWrapWidth: rowW - 28,
                },
              });
              formulaNode.position.set(15, curRowY + 3);
              curRowY += Math.ceil(formulaNode.height) + 6;
            }

            // Interactive Entity Inspection Chips (`🔍 卡牌` / `✦ 状态` / `👤 角色`)
            const uniqueEntities = [];
            const seenEnt = new Set();
            for (const ent of it.entities || []) {
              if (!ent || !ent.name) continue;
              const ek = `${ent.kind}:${ent.id || ent.name}`;
              if (seenEnt.has(ek)) continue;
              if (ent.kind === 'card') {
                const resolvedCard = lookups.skillsById.get(ent.id)
                  || lookups.skillsByName.get(`${ent.side || 1}:${ent.name}`)
                  || lookups.skillsByName.get(ent.name);
                if (resolvedCard) {
                  seenEnt.add(ek);
                  uniqueEntities.push({ ...ent, resolvedCard });
                }
              } else if (ent.kind === 'status') {
                const hasRule = Boolean(catalog?.statuses?.[ent.name] || OFFICIAL_STATUS_RULES[ent.name]);
                if (hasRule) {
                  seenEnt.add(ek);
                  uniqueEntities.push(ent);
                }
              } else if (ent.kind === 'char' && onOpenHero && lookups.charsById.has(ent.id)) {
                seenEnt.add(ek);
                uniqueEntities.push({ ...ent, resolvedChar: lookups.charsById.get(ent.id) });
              }
            }

            let chipRow = null;
            if (uniqueEntities.length > 0 && (onHoverCard || onHoverStatus || onOpenHero)) {
              curRowY += 4;
              chipRow = new PIXI.Container();
              chipRow.position.set(11, curRowY);
              let cx = 0;
              let cyChip = 0;
              for (const ent of uniqueEntities) {
                if (ent.kind === 'card' && onHoverCard && ent.resolvedCard) {
                  const sk = ent.resolvedCard;
                  const sideCol = (SIDE_THEME[sk._side || ent.side || 1] || SIDE_THEME[1]).accent;
                  const pill = makeMiniPill(`卡牌 · ${ent.name}`, {
                    height: 19,
                    padX: 6,
                    fontSize: 9.8,
                    accent: sideCol,
                    bgFill: INK.paper,
                    onHover: (hov, node) => {
                      if (!hov) {
                        onHoverCard(null);
                        return;
                      }
                      const gp = node.getGlobalPosition();
                      if (viewportCheck && !viewportCheck(gp)) return;
                      onHoverCard(sk, sk._side || ent.side || 1, sk._owner_name || '', gp.x + node._width / 2, gp.y);
                    },
                  });
                  if (cx + pill._width > rowW - 22 && cx > 0) {
                    cx = 0;
                    cyChip += 22;
                  }
                  pill.position.set(cx, cyChip);
                  chipRow.addChild(pill);
                  cx += pill._width + 5;
                } else if (ent.kind === 'status' && onHoverStatus) {
                  const sCol = getStatusColor(ent.name, INK.secondary);
                  const pill = makeMiniPill(`状态 · ${ent.name}`, {
                    height: 19,
                    padX: 6,
                    fontSize: 9.8,
                    accent: sCol,
                    bgFill: INK.paper,
                    onHover: (hov, node) => {
                      if (!hov) {
                        onHoverStatus(null);
                        return;
                      }
                      const gp = node.getGlobalPosition();
                      if (viewportCheck && !viewportCheck(gp)) return;
                      onHoverStatus(ent.name, gp.x + node._width / 2, gp.y);
                    },
                  });
                  if (cx + pill._width > rowW - 22 && cx > 0) {
                    cx = 0;
                    cyChip += 22;
                  }
                  pill.position.set(cx, cyChip);
                  chipRow.addChild(pill);
                  cx += pill._width + 5;
                } else if (ent.kind === 'char' && onOpenHero && ent.resolvedChar) {
                  const ch = ent.resolvedChar;
                  const cCol = (SIDE_THEME[ch.side] || SIDE_THEME[1]).accent;
                  const pill = makeMiniPill(`角色 · ${ch.name}`, {
                    height: 19,
                    padX: 6,
                    fontSize: 9.8,
                    accent: cCol,
                    bgFill: INK.paper,
                    onClick: () => onOpenHero(ch.id, ch.side),
                  });
                  if (cx + pill._width > rowW - 22 && cx > 0) {
                    cx = 0;
                    cyChip += 22;
                  }
                  pill.position.set(cx, cyChip);
                  chipRow.addChild(pill);
                  cx += pill._width + 5;
                }
              }
              if (chipRow.children.length > 0) {
                curRowY += cyChip + 20;
              } else {
                chipRow.destroy();
                chipRow = null;
                curRowY -= 4;
              }
            }

            const rh = curRowY + 5;
            const rg = new PIXI.Graphics();
            rg.roundRect(0, 0, rowW, rh, 5)
              .fill({ color: catStyle.bg, alpha: 0.88 })
              .stroke({ width: 0.8, color: INK.hairline });
            rg.roundRect(0, 2, 3, rh - 4, 1.5).fill({ color: catStyle.color, alpha: 0.92 });
            if (formulaNode) {
              rg.roundRect(11, formulaNode.y - 2, rowW - 18, Math.ceil(formulaNode.height) + 4, 4)
                .fill({ color: INK.paper, alpha: 0.85 })
                .stroke({ width: 0.7, color: INK.gold, alpha: 0.45 });
            }
            row.addChild(rg, mainTxt);
            if (formulaNode) row.addChild(formulaNode);
            if (chipRow) row.addChild(chipRow);

            row.position.set(indent, y);
            row._itemTop = y;
            row._itemBottom = y + rh;
            row._interactiveItem = Boolean(chipRow);
            body.addChild(row);
            y += rh + 4;
          }
        }
        y += 4;
      }
      y += 6;
    }

    if (!renderedAny) {
      const noneTxt = new PIXI.Text({
        text: '当前筛选条件下暂无匹配的战报记录。',
        style: { fontFamily: FONT_UI, fontSize: 12.8, fill: INK.muted },
      });
      noneTxt.position.set(8, 14);
      body.addChild(noneTxt);
      return 48;
    }

    return y;
  };

  return { toolbarH, buildBody };
}
