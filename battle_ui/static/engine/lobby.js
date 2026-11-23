import * as PIXI from '../vendor/pixi.min.mjs';
import { INK, SIDE_THEME, FONT_UI, drawLightStar, buildCardBack } from './card_print.js';
import { makeSealButton, buildRosterOverlay } from './table_overlays.js';
import { setCharacterSpriteUrls } from './stage_actors.js';
import { savedRooms, saveRoom, forgetRoom } from './lobby_rooms.js';

const app = new PIXI.Application();
const status = document.querySelector('#menu-status');
const canvas = document.querySelector('#pixi-canvas');
const jade = SIDE_THEME[1].accent;
let modes = [], mode = null, variant = null, lineup = null, draft = null;
const drafts = new Map();
let page = 'modes', pageNumber = 0, closing = null, scene = null;
let pending = false, previewRequest = null, elapsed = 0;

function notice(text = '') {
  status.textContent = text;
  status.hidden = !text;
}

function label(parent, text, x, y, size, color = INK.primary, weight = '700') {
  const node = new PIXI.Text({ text, style: { fontFamily: FONT_UI, fontSize: size, fill: color, fontWeight: weight } });
  node.position.set(x, y);
  parent.addChild(node);
  return node;
}

function button(parent, text, x, y, width, onClick, options = {}) {
  const node = makeSealButton(text, { width, height: 43, fontSize: 16, accent: jade,
    disabled: !onClick, onClick, ...options });
  node.position.set(x, y);
  parent.addChild(node);
}

function go(nextPage) {
  if (previewRequest) {
    previewRequest.abort();
    previewRequest = null;
    pending = false;
  }
  if (pending) return;
  page = nextPage;
  pageNumber = 0;
  notice();
  render();
}

async function request(path, options) {
  const response = await fetch(path, options);
  if (response.status === 204) return null;
  const data = await response.json();
  if (!response.ok) throw Object.assign(new Error(data.error), { status: response.status });
  return data;
}

async function chooseVariant(choice) {
  if (pending) return;
  const controller = new AbortController();
  previewRequest = controller;
  pending = true;
  notice('正在展开角色图鉴…');
  try {
    const key = mode.id + '/' + choice.id;
    let saved = drafts.get(key);
    const params = new URLSearchParams({ mode: mode.id, variant: choice.id });
    if (!saved) {
      const data = await request('/api/lineup?' + params, { signal: controller.signal });
      if (controller.signal.aborted) return;
      const locked = data.fixed_opponents;
      saved = { data, draft: { teams: [[], [...locked]], side: 1,
        hero: data.catalog.find(c => c.id === locked[0]) || data.catalog[0],
        faction: null, gallery: 0, inspect: 0, quantity: 1, quantityInput: null } };
      drafts.set(key, saved);
    }
    variant = choice;
    lineup = saved.data;
    draft = saved.draft;
    setCharacterSpriteUrls(lineup.character_sprites);
    page = 'lineup';
    notice();
    render();
  } catch (error) {
    if (!controller.signal.aborted) notice(error.message);
  } finally {
    if (previewRequest === controller) { previewRequest = null; pending = false; }
  }
}

async function start(teams) {
  if (pending) return;
  pending = true;
  notice('正在开战…');
  try {
    const room = await request('/api/rooms', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode: mode.id, variant: variant.id, roster: teams }) });
    const names = new Map(lineup.catalog.map(c => [c.id, c.name]));
    const teamLabel = team => {
      const first = names.get(team[0]);
      return team.length > 1 ? first + '等' + team.length + '人' : first;
    };
    saveRoom({ ...room, label: variant.name, matchup: teams.map(teamLabel).join(' 对 ') });
    location.assign(room.play_url);
  } catch (error) { pending = false; notice(error.message); }
}

function inspect(ch) {
  if (pending || draft.hero?.id === ch.id) return;
  draft.hero = ch;
  draft.inspect = 0;
  render();
}

function toggle(id) {
  if (pending || lineup.fixed_opponents.includes(id)) return;
  const own = draft.teams[draft.side - 1];
  if (lineup.hotseat) {
    const index = own.indexOf(id);
    const other = draft.teams[2 - draft.side];
    const ch = lineup.catalog.find(c => c.id === id);
    if (index >= 0) own.splice(index, 1);
    else if (own.length >= 3) return notice('热座每方最多出战三人。');
    else {
      if (other.includes(id) && !ch.mirror_allowed) other.splice(other.indexOf(id), 1);
      own.push(id);
    }
  } else {
    try { draft.teams[draft.side - 1] = own.concat(Array(draft.quantity).fill(id)); }
    catch (error) { if (error instanceof RangeError) return notice('当前设备无法加入这么多角色。'); throw error; }
  }
  notice();
  render();
}

function picker(w, h) {
  const d = draft;
  const fixed = lineup.fixed_opponents;
  const editable = fixed.length ? [1] : [1, 2];
  const redraw = fn => (...args) => { if (!pending) { fn(...args); notice(); render(); } };
  return buildRosterOverlay(w, h, {
    catalog: lineup.catalog, team1: d.teams[0], team2: d.teams[1], assignSide: d.side,
    hoveredChar: d.hero, factionFilter: d.faction, galleryScrollY: d.gallery, inspectScrollY: d.inspect,
    maxPerSide: lineup.hotseat ? 3 : Infinity,
    roomLobby: { title: variant.name, editableSides: editable, openTeams: !lineup.hotseat, lockedIds: fixed, returnLabel: '返回玩法',
      quantity: d.quantity, quantityInput: d.quantityInput,
      sideNames: lineup.hotseat ? { 1: '玩家一', 2: '玩家二' } : { 1: '我的阵容', 2: fixed.length ? '固定对手' : '电脑阵容' } },
    onSetAssignSide: redraw(s => { if (editable.includes(s)) d.side = s; }),
    onSetFaction: redraw(f => { d.faction = f; d.gallery = 0; }),
    onClearSide: redraw(s => { if (editable.includes(s)) { d.side = s; d.teams[s - 1] = []; } }),
    onQuantity: redraw(n => { d.quantityInput = n === null ? '' : null; if (n) d.quantity = n; }),
    onRemoveFromSide: redraw((s, id) => {
      const team = d.teams[s - 1], index = team.lastIndexOf(id);
      if (editable.includes(s) && index >= 0) { team.splice(index, 1); d.side = s; }
    }),
    onInspectChar: inspect, onToggleChar: toggle,
    onGalleryScrollChange: y => { d.gallery = y; }, onInspectScrollChange: y => { d.inspect = y; },
    onStart: start, onCancel: () => go('variants'),
  });
}

async function endRoom() {
  if (pending || !closing) return;
  pending = true;
  const room = closing;
  try {
    const token = new URL(room.play_url, location.origin).hash.slice(1);
    await request('/api/rooms/' + room.id, { method: 'DELETE',
      headers: { Authorization: 'Bearer ' + new URLSearchParams(token).get('token') } });
  } catch (error) {
    if (error.status !== 404) { pending = false; return notice(error.message); }
  }
  forgetRoom(room.id);
  pending = false;
  go('rooms');
}

async function resume(room) {
  if (pending) return;
  pending = true;
  notice('正在连接战桌…');
  const invite = new URL(room.play_url, location.origin);
  const headers = { Authorization: 'Bearer ' + new URLSearchParams(invite.hash.slice(1)).get('token'),
    'Content-Type': 'application/json' };
  const path = '/rooms/' + room.id + '/api/';
  try {
    if (invite.pathname.endsWith('/table/')) await request(path + 'state', { headers });
    else await request(path + 'canvas/state', { method: 'POST', headers, body: '{}' });
    location.assign(invite.href);
  } catch (error) {
    if (error.status === 404 || error.status === 403) {
      forgetRoom(room.id);
      pageNumber = 0;
      render();
    }
    pending = false;
    notice(error.message);
  }
}

function menu(w, h) {
  const root = new PIXI.Container();
  const compact = w < 720;
  const pad = compact ? 24 : Math.max(40, (w - 1060) / 2);
  const width = compact ? w - pad * 2 : Math.min(416, w * 0.47);
  const y = Math.max(20, (h - 495) / 2);
  const regular = SIDE_THEME[1], opponent = SIDE_THEME[2];
  const art = new PIXI.Container();
  art.eventMode = 'none';
  art.position.set(compact ? w - 50 : pad + (w - 2 * pad) * 0.77, compact ? y + 35 : h * 0.48);
  const scale = compact ? 0.21 : Math.min(1.25, (w - width - 2 * pad) / 365, h / 560);
  art.scale.set(scale);
  for (const [side, x, dy, rotation] of [[1, -63, -27, -0.24], [2, 66, 32, 0.18]]) {
    const card = buildCardBack(side, { width: 174, height: 244 });
    card.position.set(x, dy);
    card.rotation = rotation;
    art.addChild(card);
  }
  root.addChild(art);
  const emblem = new PIXI.Graphics();
  drawLightStar(emblem, pad + 10, y + 14, 10, INK.gold);
  root.addChild(emblem);
  label(root, page === 'modes' ? '对战大厅' : '光点计划 III', pad + 28, y, 20, INK.goldDeep);
  const title = { modes: '光点计划 III', variants: mode?.name, rooms: '我的对局', close: '结束这场对局？' }[page];
  label(root, title, pad, y + 44, compact ? 34 : 47, INK.strong, '900');
  let rowY = y + 118;
  const row = (text, click, options = {}) => {
    button(root, text, pad, rowY, width, click, options);
    rowY += 53;
  };
  if (page === 'modes') {
    if (savedRooms().length) row('继续对局', () => go('rooms'), { accent: INK.goldDeep });
    for (const item of modes) {
      const accent = item.id === 'challenge' ? opponent.accent : regular.accent;
      row(item.available ? item.name : item.name + '　·　未开放', item.available ? () => {
        mode = item; variant = null; go('variants');
      } : null, { accent, solid: item.available });
    }
  } else if (page === 'variants') {
    const perPage = 3;
    for (const choice of mode.variants.slice(pageNumber * perPage, (pageNumber + 1) * perPage)) {
      const caption = choice.id === 'hotseat' ? '热座　·　同机双人' : choice.id === 'solo' ? '单人　·　对战电脑' : choice.name;
      row(caption, () => chooseVariant(choice), { accent: mode.id === 'challenge' ? opponent.accent : jade });
    }
    if (mode.variants.length > perPage) pages(mode.variants.length, perPage);
    row('返回主菜单', () => go('modes'), { accent: INK.secondary });
  } else if (page === 'rooms') {
    const rooms = savedRooms(), perPage = 3;
    if (!rooms.length) { label(root, '尚无可以继续的对局', pad, rowY, 16, INK.secondary); rowY += 50; }
    for (const room of rooms.slice(pageNumber * perPage, (pageNumber + 1) * perPage)) {
      button(root, room.label, pad, rowY, width - 80, () => resume(room));
      button(root, '结束', pad + width - 72, rowY, 72, () => { closing = room; go('close'); }, { accent: opponent.accent });
      rowY += 48;
      if (room.matchup) { label(root, room.matchup, pad + 4, rowY, 13, INK.secondary); rowY += 18; }
      rowY += 8;
    }
    if (rooms.length > perPage) pages(rooms.length, perPage);
    row('返回主菜单', () => go('modes'), { accent: INK.secondary });
  } else {
    label(root, closing.label, pad, rowY, 19); rowY += 34;
    label(root, '结束后无法继续此局。', pad, rowY, 16, INK.secondary); rowY += 45;
    row('保留对局', () => go('rooms'), { solid: true });
    row('确认结束', endRoom, { accent: opponent.accent });
  }
  function pages(total, size) {
    const half = (width - 10) / 2;
    const flip = delta => () => { if (!pending) { pageNumber += delta; render(); } };
    button(root, '上一页', pad, rowY, half, pageNumber > 0 ? flip(-1) : null);
    button(root, '下一页', pad + half + 10, rowY, half, (pageNumber + 1) * size < total ? flip(1) : null);
    rowY += 53;
  }
  return root;
}

function render() {
  const { width, height } = app.screen;
  const editing = page === 'lineup';
  const scale = editing ? Math.min(1, width / 860, height / 490) : Math.min(1, height / 534);
  const view = editing ? picker(width / scale, height / scale) : menu(width / scale, height / scale);
  view.scale.set(scale);
  app.stage.addChild(view);
  scene?.destroy({ children: true });
  scene = view;
}

async function loadMenu() {
  try { modes = await request('/api/modes'); notice(); render(); }
  catch { notice('无法读取对战模式。'); button(app.stage, '重新连接', 25, 25, 140, () => location.reload()); }
}

try {
  await app.init({ canvas, preference: 'webgl', antialias: true, background: INK.paperSoft,
    resolution: Math.min(devicePixelRatio || 1, 2), autoDensity: true, resizeTo: window });
  app.renderer.on('resize', render);
  app.ticker.add(ticker => {
    elapsed += Math.min(ticker.deltaMS, 100) / 1000;
    for (const { actor, ch } of scene?._actors || []) actor.tick(elapsed, null, ch);
  });
  canvas.addEventListener('wheel', event => {
    if (page !== 'lineup') return;
    event.preventDefault();
    const localX = event.offsetX / scene.scale.x;
    if (localX < scene._gallerySplitX) scene.setGalleryScroll(draft.gallery + event.deltaY);
    else scene.setInspectScroll(draft.inspect + event.deltaY);
  }, { passive: false });
  window.addEventListener('keydown', event => {
    if (event.repeat || (pending && !(previewRequest && event.key === 'Escape'))) return;
    if (page === 'lineup' && draft.quantityInput !== null) {
      if (/^\d$/.test(event.key)) draft.quantityInput += event.key;
      else if (event.key === 'Backspace') draft.quantityInput = draft.quantityInput.slice(0, -1);
      else if (event.key === 'Escape') draft.quantityInput = null;
      else if (event.key === 'Enter') {
        const count = Number(draft.quantityInput);
        if (!Number.isSafeInteger(count) || count < 1) return notice('请输入正整数。');
        draft.quantity = count; draft.quantityInput = null;
      } else return;
      event.preventDefault(); notice(); render(); return;
    }
    if (event.key === 'Escape' && page !== 'modes') {
      go(page === 'lineup' ? 'variants' : page === 'close' ? 'rooms' : 'modes');
    }
  });
  window.addEventListener('pageshow', e => { if (e.persisted) location.reload(); });
  await loadMenu();
} catch { notice('游戏画布未能启动，请检查浏览器的图形加速后刷新。'); }
