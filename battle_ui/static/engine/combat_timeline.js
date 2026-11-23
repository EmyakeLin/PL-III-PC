/**
 * Combat duel stage for 《光点计划 III》.
 *
 *  - `buildDuelGemTrack`  — a thread of gems along the top of the arena. One gem per duel:
 *    spent gems sit dim, the live gem glows, queued gems are hollow. Hovering a gem lifts
 *    that duel's cards out as small physical cards; clicking pins them (used for board targets).
 *  - `buildActiveDuelStage` — the live duel only: the clash zone above, and the two duelling
 *    cards standing face to face below it as real card objects (hover for the full printed card).
 *
 * No lists, no scrollbars, no status labels: progress is read from the gems themselves.
 */

import * as PIXI from '../vendor/pixi.min.mjs';
import { FONT_NUM, FONT_UI, INK } from './design_system.js';
import { buildBoardCardTag, buildCardBack, buildUniformCard } from './card_print.js';

const JADE = 0x1f9a78;

export function collectChronicleDuels(frame, combat) {
  const items = [];
  for (const d of frame?.pre_reveal?.duels || []) {
    items.push({ kind: 'pre_reveal', number: d.number, duel: d, key: `pre_reveal:${d.number}` });
  }
  for (const d of frame?.special_duels || []) {
    items.push({ kind: 'instant', number: d.number, duel: d, key: `instant:${d.number}` });
  }
  for (const d of frame?.duels || []) {
    items.push({ kind: 'regular', number: d.number, duel: d, key: `regular:${d.number}` });
  }

  let activeIndex = items.findIndex((it) => it.kind === combat?.kind && it.number === combat?.duel_number);
  if (activeIndex < 0 && items.length) activeIndex = 0;

  return items.map((item, index) => ({
    ...item,
    status: index < activeIndex ? 'completed' : index === activeIndex ? 'active' : 'upcoming',
  }));
}

/** Gem outline per duel kind: pre-reveal = hexagon, instant = tall rhombus, regular = diamond. */
function gemPoints(kind, cx, cy, r) {
  if (kind === 'pre_reveal') {
    const pts = [];
    for (let i = 0; i < 6; i++) {
      const a = Math.PI / 6 + (i * Math.PI) / 3;
      pts.push(cx + Math.cos(a) * r, cy + Math.sin(a) * r);
    }
    return pts;
  }
  if (kind === 'instant') {
    return [cx, cy - r * 1.18, cx + r * 0.62, cy, cx, cy + r * 1.18, cx - r * 0.62, cy];
  }
  return [cx, cy - r, cx + r, cy, cx, cy + r, cx - r, cy];
}

function drawGem(g, item, cx, cy, r, { selectable = false, hovered = false } = {}) {
  const pts = gemPoints(item.kind, cx, cy, r);
  if (item.status === 'active') {
    g.circle(cx, cy, r + 7).fill({ color: INK.gold, alpha: 0.16 });
    g.poly(gemPoints(item.kind, cx, cy + 1.5, r)).fill({ color: INK.shadow, alpha: 0.35 });
    g.poly(pts).fill({ color: INK.gold }).stroke({ width: 1.4, color: INK.goldDeep });
    // facet highlight
    g.poly([pts[0], pts[1], pts[2], pts[3], cx, cy]).fill({ color: 0xffffff, alpha: 0.28 });
  } else if (item.status === 'completed') {
    g.poly(pts).fill({ color: 0x8f8476, alpha: hovered ? 0.95 : 0.7 }).stroke({ width: 1, color: 0x6e6255, alpha: 0.8 });
    g.poly([pts[0], pts[1], pts[2], pts[3], cx, cy]).fill({ color: 0xffffff, alpha: 0.14 });
  } else {
    g.poly(pts).fill({ color: INK.paper, alpha: hovered ? 0.98 : 0.86 })
      .stroke({ width: 1.3, color: hovered ? INK.gold : INK.secondary, alpha: 0.85 });
  }
  if (selectable) {
    g.poly(gemPoints(item.kind, cx, cy, r + 4)).stroke({ width: 1.8, color: JADE, alpha: 0.95 });
  }
}

/**
 * Peek cluster: the duel's cards as small physical cards, P1 on the left, P2 on the right.
 * Returns a container centred on x=0, top at y=0, plus the per-card local rects.
 */
function buildDuelPeek(item, { cardW, charNames, resolveCharColor, onHoverCard }) {
  const root = new PIXI.Container();
  const rects = [];
  const gap = 6;
  const midGap = 22;
  const sideNodes = { 1: [], 2: [] };
  let cardH = Math.round(cardW * 1.4);

  for (const side of [1, 2]) {
    const se = (item.duel?.sides || []).find((s) => s.side === side);
    (se?.cards || []).forEach((card, cIdx) => {
      const accent = resolveCharColor(card.character_id, side);
      const node = card.hidden
        ? buildCardBack(side, { width: cardW, height: cardH, accentColor: accent })
        : buildBoardCardTag(card, { side, accentColor: accent, width: cardW });
      cardH = node._boxHeight || cardH;
      sideNodes[side].push({ node, card, accent, position: cIdx + 1 });
    });
  }

  const widthOf = (n) => (n ? n * cardW + (n - 1) * gap : 0);
  const leftW = widthOf(sideNodes[1].length);
  const rightW = widthOf(sideNodes[2].length);
  const startLeft = -midGap / 2 - leftW;
  const startRight = midGap / 2;

  const place = (side, startX) => {
    sideNodes[side].forEach(({ node, card, accent, position }, i) => {
      const x = startX + i * (cardW + gap);
      node.position.set(x + cardW / 2, cardH / 2);
      node.rotation = 0;
      root.addChild(node);
      rects.push({ side, position, card, x, y: 0, w: cardW, h: cardH });
      if (!card.hidden && onHoverCard) {
        node.eventMode = 'static';
        node.cursor = 'pointer';
        node.on('pointerover', () => {
          const g = node.getGlobalPosition();
          onHoverCard({
            card, side, accentColor: accent,
            ownerName: charNames[card.character_id] || '',
            anchorX: g.x, anchorY: g.y - cardH / 2,
          });
        });
        node.on('pointerout', () => onHoverCard(null));
      }
    });
  };
  place(1, startLeft);
  place(2, startRight);

  // crossed-blades glyph between the two sides
  const x = new PIXI.Graphics();
  const cy = cardH / 2;
  x.moveTo(-6, cy - 6).lineTo(6, cy + 6).moveTo(6, cy - 6).lineTo(-6, cy + 6)
    .stroke({ width: 2, color: INK.gold, alpha: 0.85 });
  root.addChild(x);

  root._rects = rects;
  root._boxHeight = cardH;
  return root;
}

/**
 * Top-of-arena gem thread. `onPeekTargets(host, rects, item)` lets the caller mark selectable cards
 * inside a pinned peek (board effect targets living in a non-active duel).
 */
export function buildDuelGemTrack({
  layer,
  peekLayer,
  frame,
  combat,
  arenaX,
  arenaW,
  y,
  charNames,
  resolveCharColor,
  onHoverCard,
  choiceTargets = new Map(), // duelKey -> Set(choiceIndex)
  pinnedKey = null,
  onPinChange,
  onPeekTargets,
}) {
  const items = collectChronicleDuels(frame, combat);
  const root = new PIXI.Container();
  layer.addChild(root);
  const H = 30;
  const cy = y + H / 2;

  // spacing: shrink to fit, kind groups separated by a wider gap
  const groupBreaks = items.reduce((n, it, i) => n + (i > 0 && it.kind !== items[i - 1].kind ? 1 : 0), 0);
  const avail = Math.max(120, arenaW - 40);
  const step = Math.max(14, Math.min(30, (avail - groupBreaks * 12) / Math.max(1, items.length - 1)));
  const totalW = (items.length - 1) * step + groupBreaks * 12;
  let gx = arenaX + arenaW / 2 - totalW / 2;
  const r = Math.max(5, Math.min(8, step * 0.3));

  const positions = items.map((it, i) => {
    if (i > 0) gx += step + (it.kind !== items[i - 1].kind ? 12 : 0);
    return gx;
  });

  // thread
  const thread = new PIXI.Graphics();
  if (items.length > 1) {
    thread.moveTo(positions[0] - 10, cy).lineTo(positions[positions.length - 1] + 10, cy)
      .stroke({ width: 1, color: INK.line, alpha: 0.9 });
    const ai = items.findIndex((it) => it.status === 'active');
    if (ai > 0) {
      thread.moveTo(positions[0] - 10, cy).lineTo(positions[ai], cy)
        .stroke({ width: 1.8, color: INK.gold, alpha: 0.75 });
    }
  }
  root.addChild(thread);

  const gemRecords = [];
  let peekNode = null;
  let peekKey = null;

  const showPeek = (item, gemX, pinned) => {
    if (peekNode) {
      peekNode.destroy({ children: true });
      peekNode = null;
      peekKey = null;
    }
    if (!item || item.status === 'active') return;
    peekKey = item.key;
    const cardW = Math.max(96, Math.min(112, Math.floor((arenaW - 60) / 6)));
    peekNode = buildDuelPeek(item, { cardW, charNames, resolveCharColor, onHoverCard });
    const clampedX = Math.max(arenaX + 12, Math.min(arenaX + arenaW - 12, gemX));
    peekNode.position.set(clampedX, y + H + 8);
    // keep inside the arena horizontally
    const b = peekNode.getLocalBounds();
    const left = clampedX + b.x;
    const right = clampedX + b.x + b.width;
    if (left < arenaX) peekNode.x += arenaX - left;
    if (right > arenaX + arenaW) peekNode.x -= right - (arenaX + arenaW);
    peekLayer.addChild(peekNode);
    if (pinned && onPeekTargets) onPeekTargets(peekNode, peekNode._rects, item);
  };

  items.forEach((item, i) => {
    const cx = positions[i];
    const selectable = choiceTargets.has(item.key);
    const big = item.status === 'active' ? r + 3 : r;
    const gem = new PIXI.Container();
    const g = new PIXI.Graphics();
    const redraw = (hovered) => {
      g.clear();
      drawGem(g, item, cx, cy, big, { selectable, hovered });
    };
    redraw(false);
    gem.addChild(g);

    if (item.status === 'active' || items.length <= 12) {
      const num = new PIXI.Text({
        text: String(item.number),
        style: {
          fontFamily: FONT_NUM,
          fontSize: item.status === 'active' ? 9.5 : 8,
          fontWeight: '900',
          fill: item.status === 'upcoming' ? INK.secondary : INK.paper,
        },
      });
      num.anchor.set(0.5);
      num.position.set(cx, cy + 0.5);
      gem.addChild(num);
    }

    gem.eventMode = 'static';
    gem.cursor = item.status === 'active' ? 'default' : 'pointer';
    gem.hitArea = new PIXI.Circle(cx, cy, Math.max(big + 5, step / 2));
    gem.on('pointerover', () => {
      redraw(true);
      if (pinnedKey == null) showPeek(item, cx, false);
    });
    gem.on('pointerout', () => {
      redraw(false);
      if (pinnedKey == null && peekKey === item.key) showPeek(null);
    });
    gem.on('pointertap', (e) => {
      e.stopPropagation();
      if (item.status === 'active') return;
      onPinChange?.(pinnedKey === item.key ? null : item.key);
    });
    root.addChild(gem);
    gemRecords.push({ item, gem, g, cx, big, selectable });
  });

  if (pinnedKey) {
    const rec = gemRecords.find((gr) => gr.item.key === pinnedKey);
    if (rec) showPeek(rec.item, rec.cx, true);
  }

  // live gem breathes
  const active = gemRecords.find((gr) => gr.item.status === 'active');
  let t = 0;
  let halo = null;
  if (active) {
    halo = new PIXI.Graphics();
    halo.circle(active.cx, cy, active.big + 6).stroke({ width: 1.4, color: INK.gold, alpha: 0.7 });
    root.addChildAt(halo, 1);
  }
  const tick = (ticker) => {
    if (!halo || halo.destroyed) return;
    t += ticker.deltaMS / 1000;
    const k = (t % 1.6) / 1.6;
    halo.alpha = 0.75 * (1 - k);
    halo.scale.set(1 + k * 0.6);
    halo.pivot.set(active.cx, cy);
    halo.position.set(active.cx, cy);
  };
  PIXI.Ticker.shared.add(tick);
  root.on('destroyed', () => PIXI.Ticker.shared.remove(tick));

  root._boxHeight = H;
  root.highlightChoice = (choiceIndex) => {
    for (const rec of gemRecords) {
      const set = choiceTargets.get(rec.item.key);
      rec.gem.scale.set(1);
      if (set && set.has(choiceIndex)) {
        rec.gem.pivot.set(rec.cx, cy);
        rec.gem.position.set(rec.cx, cy);
        rec.gem.scale.set(1.35);
      } else {
        rec.gem.pivot.set(0, 0);
        rec.gem.position.set(0, 0);
      }
    }
  };
  root.dismissPeek = () => showPeek(null);
  return root;
}

/**
 * Live duel: reserves the clash zone (filled by the director's medallions + 3D dice), and stands
 * the two duelling cards face to face below it.
 */
export function buildActiveDuelStage({
  layer,
  combat,
  arenaX,
  arenaW,
  top,
  bottom,
  activeCardsBySide,
  duelCardsBySide = new Map(),
  concealBySide = new Map(),
  savedScrollByCardKey = new Map(),
  charNames,
  resolveCharColor,
  specialOptions = [],
  pausedLabelFn,
  onMarkEffectTarget,
  onHoverCard,
}) {
  let cursorY = top;

  const paused = combat.suspended || [];
  if (paused.length) {
    const chain = paused.map((play) => pausedLabelFn(play) + (play.source_name ? ` · ${play.source_name}` : ''));
    const context = new PIXI.Text({
      text: chain.join('  ›  '),
      style: {
        fontFamily: FONT_UI, fontSize: 11, fontWeight: '700', fill: INK.secondary,
        align: 'center', wordWrap: true, breakWords: true, wordWrapWidth: arenaW - 40,
      },
    });
    context.alpha = 0.85;
    context.anchor.set(0.5, 0);
    context.position.set(arenaX + arenaW * 0.5, cursorY);
    layer.addChild(context);
    cursorY += context.height + 4;
  }

  const clashH = 148;
  const clashTop = cursorY;
  cursorY += clashH + 10;

  const cardsTop = cursorY;
  const availH = Math.max(160, bottom - cardsTop - 6);
  const cardW = Math.round(Math.max(176, Math.min(256, availH / 1.40, (arenaW - 36) / 2)));
  const cardH = Math.round(Math.min(availH, cardW * 1.40));
  const centerX = arenaX + arenaW / 2;
  const spread = cardW / 2 + Math.max(12, Math.min(34, (arenaW - cardW * 2) * 0.25));
  const combatCardRects = new Map();
  const cardNodes = [];

  for (const side of [1, 2]) {
    const combatSide = (combat.sides || []).find((cs) => cs.side === side);
    const activeCard = activeCardsBySide.get(side) || null;
    const slotCards = duelCardsBySide.get(side) || [];
    const card = activeCard || (slotCards.length ? slotCards[slotCards.length - 1] : null);
    const isSettledFallback = !activeCard && Boolean(card);
    const cx = side === 1 ? centerX - spread : centerX + spread;

    if (!card) {
      // empty seat: a faint upright card silhouette, nothing written
      const ghost = new PIXI.Graphics();
      ghost.roundRect(-cardW / 2, -cardH / 2, cardW, cardH, 8)
        .fill({ color: INK.paperSoft, alpha: 0.35 })
        .stroke({ width: 1.2, color: INK.line, alpha: 0.8 });
      ghost.position.set(cx, cardsTop + cardH / 2);
      ghost.rotation = 0;
      layer.addChild(ghost);
      continue;
    }

    const accent = resolveCharColor(card.character_id, side);
    const conceal = concealBySide.get(side) || {};
    const cardKey = `${side}:${card.instance_id ?? card.id}`;
    const savedScroll = savedScrollByCardKey.has(cardKey) ? savedScrollByCardKey.get(cardKey) : null;
    const node = buildUniformCard(card, {
      side,
      accentColor: accent,
      ownerName: charNames[card.character_id] || '',
      showOwner: true,
      width: cardW,
      height: cardH,
      centered: true,
      activeCard: Boolean(activeCard),
      activeDieNumber: activeCard ? (combatSide?.die?.position ?? combatSide?.die_number ?? null) : null,
      concealActiveScore: Boolean(conceal.score),
      concealActiveOutcome: Boolean(conceal.outcome),
      rangeDeficit: combatSide?.range_deficit || card.range_deficit || 0,
      playMode: combatSide?.play_mode || card.play_mode || null,
      statusBadge: isSettledFallback ? 'settled' : null,
      initialScrollY: savedScroll,
    });
    const h = node._boxHeight;
    node.position.set(cx, cardsTop + h / 2);
    node.rotation = 0;
    layer.addChild(node);

    const x = cx - cardW / 2;
    const rect = {
      x, y: cardsTop, w: cardW, h, cx, cy: cardsTop + h / 2,
      cardId: card.id, instanceId: card.instance_id, cardKey, node,
    };
    combatCardRects.set(side, rect);
    cardNodes.push(rect);

    const option = specialOptions.find(({ effect_target: target }) => target?.zone === 'board'
      && target.card?.instance_id != null && target.card.instance_id === card.instance_id);
    if (option && onMarkEffectTarget) {
      const t = option.effect_target;
      onMarkEffectTarget(layer, t.kind, t.number, side, t.position, x, cardsTop, cardW, h);
    }
  }

  return {
    clashTop,
    clashH,
    choiceSafeTop: clashTop + clashH + 6,
    combatCardRects,
    cardNodes,
  };
}
