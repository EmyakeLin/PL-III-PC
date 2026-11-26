import * as PIXI from '../vendor/pixi.min.mjs';
import { INK, SIDE_THEME, FONT_UI, buildCardBack, drawLightStar } from './card_print.js';
import { FONT_NUM } from './design_system.js';
import { makeSealButton, buildRosterOverlay } from './table_overlays.js';
import { setCharacterSpriteUrls } from './stage_actors.js';
import { savedRooms, saveRoom, forgetRoom } from './lobby_rooms.js';

const app = new PIXI.Application();
const status = document.querySelector('#menu-status');
const canvas = document.querySelector('#pixi-canvas');
const jade = SIDE_THEME[1].accent;

let modes = [];
let mode = null;
let variant = null;
let lineup = null;
let draft = null;
const drafts = new Map();
let page = 'modes';
let pageNumber = 0;
let closing = null;
let scene = null;
let joinCode = '';
let pending = false;
let previewRequest = null;
let elapsed = 0;

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
  if (!response.ok) throw Object.assign(new Error(data.error || '请求失败'), { status: response.status });
  return data;
}

async function createOnlineRoom() {
  if (pending) return;
  pending = true;
  notice('正在创建联机房间…');
  try {
    const room = await request('/api/rooms', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode: 'regular', variant: 'online' }),
    });
    saveRoom({
      ...room,
      label: `联机房间 · ${room.code}`,
      matchup: '房主席位',
    });
    location.assign(room.play_url);
  } catch (error) {
    pending = false;
    notice(error.message);
  }
}

async function submitJoinCode() {
  const cleaned = joinCode.trim().toUpperCase();
  if (cleaned.length < 4 || pending) {
    if (cleaned.length < 4) notice('请输入完整的 6 位房间码。');
    return;
  }
  pending = true;
  notice(`正在加入房间 ${cleaned}…`);
  try {
    const joined = await request('/api/rooms/join', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code: cleaned }),
    });
    if (joined.role === 'player') {
      saveRoom({
        id: joined.id,
        code: joined.code,
        play_url: joined.play_url,
        label: `联机房间 · ${joined.code}`,
        matchup: `席位 ${joined.side}`,
      });
    }
    location.assign(joined.play_url);
  } catch (error) {
    pending = false;
    notice(error.message);
  }
}

function generateEqualPowerTeam(catalog, targetPower, ruleset, excludeIds = []) {
  const cap = ruleset?.power_cap ?? null;
  const maxC = ruleset?.max_chars ?? 4;
  const strict = ruleset?.duplicate_policy === 'strict_unique';
  const allowDup = ruleset?.duplicate_policy === 'free_duplicates';
  const pool = catalog.filter(c => !(strict && excludeIds.includes(c.id) && !c.mirror_allowed));
  if (!pool.length) return catalog[0] ? [catalog[0].id] : [];
  const goal = Math.min(cap || 999, Math.max(1, targetPower || 3));
  let best = null;
  let bestDiff = 9999;
  for (let attempt = 0; attempt < 32; attempt++) {
    const avail = pool.slice().sort(() => Math.random() - 0.5);
    const picked = [];
    let pwr = 0;
    while (avail.length && picked.length < maxC) {
      const ch = avail.pop();
      const cp = ch.power || 1;
      if (cap != null && pwr + cp > cap) continue;
      if (picked.length && pwr + cp > goal + 1) continue;
      picked.push(ch.id);
      pwr += cp;
      if (allowDup) avail.push(ch);
      if (pwr >= goal) break;
    }
    if (!picked.length) {
      const fit = pool.filter(c => cap == null || (c.power || 1) <= cap);
      if (fit.length) {
        fit.sort((a, b) => Math.abs((a.power || 1) - goal) - Math.abs((b.power || 1) - goal));
        picked.push(fit[0].id);
        pwr = fit[0].power || 1;
      }
    }
    if (picked.length) {
      const diff = Math.abs(pwr - goal);
      if (diff < bestDiff) {
        bestDiff = diff;
        best = picked;
        if (diff === 0) break;
      }
    }
  }
  return best || [pool[0].id];
}

async function chooseVariant(choice) {
  if (choice.id === 'online') {
    await createOnlineRoom();
    return;
  }
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
      const locked = data.fixed_opponents || [];
      const ruleset = { ...(data.default_ruleset || {}) };
      const initialOpp = locked.length
        ? [...locked]
        : (choice.id === 'solo' ? generateEqualPowerTeam(data.catalog, 3, ruleset) : []);
      saved = {
        data,
        draft: {
          teams: [[], initialOpp],
          side: 1,
          hero: data.catalog.find(c => c.id === locked[0]) || data.catalog[0],
          faction: null,
          gallery: 0,
          inspect: 0,
          rulesOpen: false,
          ruleset,
          presetIndex: 0,
        },
      };
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
    const room = await request('/api/rooms', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode: mode.id, variant: variant.id, roster: teams, ruleset: draft.ruleset }),
    });
    const names = new Map(lineup.catalog.map(c => [c.id, c.name]));
    const teamLabel = (team) => {
      const first = names.get(team[0]) || team[0];
      return team.length > 1 ? `${first}等${team.length}人` : first;
    };
    saveRoom({ ...room, label: variant.name, matchup: teams.map(teamLabel).join(' 对 ') });
    location.assign(room.play_url);
  } catch (error) {
    pending = false;
    notice(error.message);
  }
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
  const other = draft.teams[2 - draft.side];
  const ch = lineup.catalog.find(c => c.id === id);
  if (!ch) return;

  const rules = draft.ruleset || {};
  const allowDup = rules.duplicate_policy === 'free_duplicates';
  const strictUnique = rules.duplicate_policy === 'strict_unique';
  const index = own.indexOf(id);

  if (!allowDup && index >= 0) {
    own.splice(index, 1);
    notice();
    render();
    return;
  }
  if (rules.max_chars != null && own.length >= rules.max_chars) {
    return notice(`当前房间规则限制每方最多出战 ${rules.max_chars} 人。`);
  }
  const byId = new Map(lineup.catalog.map(c => [c.id, c]));
  const curPower = own.reduce((s, cid) => s + (byId.get(cid)?.power || 1), 0);
  const addPower = ch.power || 1;
  if (rules.power_cap != null && curPower + addPower > rules.power_cap) {
    return notice(`加入「${ch.name}」（战力 ${addPower}）将超出总战力上限 ${rules.power_cap}。`);
  }
  if (strictUnique && other.includes(id) && !ch.mirror_allowed) {
    other.splice(other.indexOf(id), 1);
  }
  own.push(id);
  notice();
  render();
}

function picker(w, h) {
  const d = draft;
  const fixed = lineup.fixed_opponents;
  const editable = fixed.length ? [1] : [1, 2];
  const redraw = (fn) => (...args) => { if (!pending) { fn(...args); notice(); render(); } };
  const presets = lineup.opponent_presets || [];
  const byId = new Map(lineup.catalog.map(c => [c.id, c]));
  const p1Power = d.teams[0].reduce((s, cid) => s + (byId.get(cid)?.power || 1), 0);

  return buildRosterOverlay(w, h, {
    catalog: lineup.catalog,
    team1: d.teams[0],
    team2: d.teams[1],
    assignSide: d.side,
    hoveredChar: d.hero,
    factionFilter: d.faction,
    galleryScrollY: d.gallery,
    inspectScrollY: d.inspect,
    maxPerSide: d.ruleset?.max_chars ?? Infinity,
    roomLobby: {
      title: variant.name,
      editableSides: editable,
      openTeams: d.ruleset?.duplicate_policy === 'free_duplicates',
      lockedIds: fixed,
      returnLabel: '返回玩法',
      isHost: true,
      ruleset: d.ruleset,
      ruleBounds: lineup.rule_bounds,
      rulesOpen: Boolean(d.rulesOpen),
      isHotseat: Boolean(lineup.hotseat),
      isChallenge: fixed.length > 0,
      opponentPresets: presets,
      onToggleRules: redraw(() => { d.rulesOpen = !d.rulesOpen; }),
      onUpdateRules: redraw((patch) => {
        if (patch === 'reset') {
          d.ruleset = { ...(lineup.default_ruleset || {}) };
        } else {
          d.ruleset = { ...d.ruleset, ...patch };
        }
      }),
      onRandomizeOpponent: !fixed.length && variant.id === 'solo' ? redraw(() => {
        d.teams[1] = generateEqualPowerTeam(lineup.catalog, p1Power || 3, d.ruleset, d.teams[0]);
      }) : null,
      onCyclePresetOpponent: !fixed.length && presets.length > 0 ? redraw(() => {
        const p = presets[d.presetIndex % presets.length];
        d.presetIndex = (d.presetIndex + 1) % presets.length;
        d.teams[1] = p.characters.slice();
        notice(`已切换电脑阵容：${p.name}`);
      }) : null,
      sideNames: lineup.hotseat
        ? { 1: '玩家一', 2: '玩家二' }
        : { 1: '我的阵容', 2: fixed.length ? '固定首领' : '电脑阵容' },
    },
    onSetAssignSide: redraw((s) => { if (editable.includes(s)) d.side = s; }),
    onSetFaction: redraw((f) => { d.faction = f; d.gallery = 0; }),
    onClearSide: redraw((s) => { if (editable.includes(s)) { d.side = s; d.teams[s - 1] = []; } }),
    onRemoveFromSide: redraw((s, id) => {
      const team = d.teams[s - 1];
      const index = team.lastIndexOf(id);
      if (editable.includes(s) && index >= 0) { team.splice(index, 1); d.side = s; }
    }),
    onInspectChar: inspect,
    onHoverChar: inspect,
    onToggleChar: toggle,
    onGalleryScrollChange: (y) => { d.gallery = y; },
    onInspectScrollChange: (y) => { d.inspect = y; },
    onStart: start,
    onCancel: () => go('variants'),
  });
}

async function endRoom() {
  if (pending || !closing) return;
  pending = true;
  const room = closing;
  try {
    const token = new URL(room.play_url, location.origin).hash.slice(1);
    await request('/api/rooms/' + room.id, {
      method: 'DELETE',
      headers: { Authorization: 'Bearer ' + new URLSearchParams(token).get('token') },
    });
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
  const tok = new URLSearchParams(invite.hash.slice(1)).get('token');
  const headers = { 'Content-Type': 'application/json' };
  if (tok) headers.Authorization = 'Bearer ' + tok;
  const path = '/rooms/' + room.id + '/api/';
  try {
    await request(path + 'canvas/state', { method: 'POST', headers, body: '{}' });
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

function renderJoinView(root, pad, y, width) {
  label(root, '输入朋友分享的 6 位房间码（若双方席位已满将自动进入观战席）：', pad, y + 108, 15, INK.secondary);

  const boxY = y + 144;
  const slotW = 52;
  const slotGap = 10;
  const slotsG = new PIXI.Graphics();
  root.addChild(slotsG);

  for (let i = 0; i < 6; i++) {
    const sx = pad + i * (slotW + slotGap);
    const ch = joinCode[i] || '';
    const active = i === joinCode.length;
    slotsG.roundRect(sx, boxY, slotW, 62, 10)
      .fill({ color: INK.paper })
      .stroke({ width: active ? 2.4 : 1.5, color: active ? jade : INK.line });
    if (ch) {
      const t = new PIXI.Text({
        text: ch,
        style: { fontFamily: FONT_NUM, fontSize: 28, fontWeight: '900', fill: INK.strong },
      });
      t.anchor.set(0.5);
      t.position.set(sx + slotW / 2, boxY + 31);
      root.addChild(t);
    }
  }

  const rowY = boxY + 84;
  const half = Math.floor((width - 12) / 2);
  button(root, '加入房间', pad, rowY, half, joinCode.length >= 4 ? submitJoinCode : null, { solid: joinCode.length >= 4 });
  button(root, '粘贴房间码', pad + half + 12, rowY, half, async () => {
    try {
      const txt = await navigator.clipboard.readText();
      const cleaned = (txt || '').toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 6);
      if (cleaned) {
        joinCode = cleaned;
        notice();
        render();
      } else {
        notice('剪贴板中没有找到有效的房间码。');
      }
    } catch {
      notice('请直接用键盘输入或按 Ctrl+V 粘贴房间码。');
    }
  }, { accent: INK.goldDeep });

  button(root, '清空输入', pad, rowY + 54, half, joinCode.length ? () => { joinCode = ''; notice(); render(); } : null, { accent: INK.secondary });
  button(root, '返回主菜单', pad + half + 12, rowY + 54, half, () => go('modes'), { accent: INK.secondary });
}

function menu(w, h) {
  const root = new PIXI.Container();
  const compact = w < 720;
  const pad = compact ? 24 : Math.max(40, (w - 1060) / 2);
  const width = compact ? w - pad * 2 : Math.min(424, w * 0.47);
  const y = Math.max(20, (h - 520) / 2);
  const regular = SIDE_THEME[1];
  const opponent = SIDE_THEME[2];

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

  const title = {
    modes: '光点计划 III',
    variants: mode?.name,
    join: '房间码加入',
    rooms: '我的对局',
    close: '结束这场对局？',
  }[page];
  label(root, title, pad, y + 42, compact ? 34 : 46, INK.strong, '900');

  if (page === 'join') {
    renderJoinView(root, pad, y, width);
    return root;
  }

  let rowY = y + 112;
  const row = (text, click, options = {}) => {
    button(root, text, pad, rowY, width, click, options);
    rowY += 52;
  };

  if (page === 'modes') {
    if (savedRooms().length) row('继续对局', () => go('rooms'), { accent: INK.goldDeep });
    row('创建联机房间', createOnlineRoom, { accent: regular.accent, solid: true });
    row('输入房间码加入', () => { joinCode = ''; go('join'); }, { accent: INK.gold, solid: false });
    for (const item of modes) {
      const accent = item.id === 'challenge' ? opponent.accent : regular.accent;
      const caption = item.id === 'regular' ? '单人与同屏对战' : item.name;
      row(item.available ? caption : item.name + '　·　未开放', item.available ? () => {
        mode = item;
        variant = null;
        go('variants');
      } : null, { accent, solid: item.available && item.id !== 'regular' });
    }
  } else if (page === 'variants') {
    const visibleVariants = mode.id === 'regular'
      ? mode.variants.filter(v => v.id !== 'online')
      : mode.variants;
    const perPage = 4;
    for (const choice of visibleVariants.slice(pageNumber * perPage, (pageNumber + 1) * perPage)) {
      const caption = choice.id === 'hotseat' ? '同屏双人　·　本地对决'
        : choice.id === 'solo' ? '单人演练　·　智能电脑'
        : choice.name;
      row(caption, () => chooseVariant(choice), { accent: mode.id === 'challenge' ? opponent.accent : jade, solid: true });
    }
    if (visibleVariants.length > perPage) pages(visibleVariants.length, perPage);
    row('返回主菜单', () => go('modes'), { accent: INK.secondary });
  } else if (page === 'rooms') {
    const rooms = savedRooms();
    const perPage = 3;
    if (!rooms.length) {
      label(root, '尚无可以继续的对局', pad, rowY, 16, INK.secondary);
      rowY += 50;
    }
    for (const room of rooms.slice(pageNumber * perPage, (pageNumber + 1) * perPage)) {
      button(root, room.label, pad, rowY, width - 80, () => resume(room));
      button(root, '结束', pad + width - 72, rowY, 72, () => { closing = room; go('close'); }, { accent: opponent.accent });
      rowY += 48;
      if (room.matchup) {
        label(root, room.matchup, pad + 4, rowY, 13, INK.secondary);
        rowY += 18;
      }
      rowY += 8;
    }
    if (rooms.length > perPage) pages(rooms.length, perPage);
    row('返回主菜单', () => go('modes'), { accent: INK.secondary });
  } else {
    label(root, closing.label, pad, rowY, 19);
    rowY += 34;
    label(root, '结束后无法继续此局。', pad, rowY, 16, INK.secondary);
    rowY += 45;
    row('保留对局', () => go('rooms'), { solid: true });
    row('确认结束', endRoom, { accent: opponent.accent });
  }

  function pages(total, size) {
    const half = (width - 10) / 2;
    const flip = (delta) => () => { if (!pending) { pageNumber += delta; render(); } };
    button(root, '上一页', pad, rowY, half, pageNumber > 0 ? flip(-1) : null);
    button(root, '下一页', pad + half + 10, rowY, half, (pageNumber + 1) * size < total ? flip(1) : null);
    rowY += 52;
  }
  return root;
}

function render() {
  const { width, height } = app.screen;
  const editing = page === 'lineup';
  const scale = editing ? Math.min(1, width / 860, height / 490) : Math.min(1, height / 550);
  const view = editing ? picker(width / scale, height / scale) : menu(width / scale, height / scale);
  view.scale.set(scale);
  app.stage.addChild(view);
  scene?.destroy({ children: true });
  scene = view;
}

window.addEventListener('keydown', (e) => {
  if (page !== 'join' || pending) return;
  if (e.key === 'Escape') {
    go('modes');
    return;
  }
  if (e.key === 'Backspace') {
    e.preventDefault();
    joinCode = joinCode.slice(0, -1);
    notice();
    render();
    return;
  }
  if (e.key === 'Enter') {
    e.preventDefault();
    submitJoinCode();
    return;
  }
  if (/^[a-zA-Z0-9]$/.test(e.key) && !e.ctrlKey && !e.metaKey && !e.altKey) {
    if (joinCode.length < 6) {
      joinCode += e.key.toUpperCase();
      notice();
      render();
    }
  }
});

window.addEventListener('paste', (e) => {
  if (page !== 'join' || pending) return;
  const txt = e.clipboardData?.getData('text') || '';
  const cleaned = txt.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 6);
  if (cleaned) {
    e.preventDefault();
    joinCode = cleaned;
    notice();
    render();
  }
});

async function loadMenu() {
  try {
    modes = await request('/api/modes');
    const params = new URLSearchParams(location.search);
    const joinParam = params.get('join');
    if (joinParam) {
      joinCode = joinParam.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 6);
      page = 'join';
      notice();
      render();
      return;
    }
    mode = modes.find(item => item.id === params.get('mode')) || null;
    const choice = mode?.variants.find(item => item.id === params.get('variant'));
    notice();
    render();
    if (choice) await chooseVariant(choice);
  } catch {
    notice('无法读取对战模式。');
    button(app.stage, '重新连接', 25, 25, 140, () => location.reload());
  }
}

try {
  await app.init({
    canvas,
    preference: 'webgl',
    antialias: true,
    background: INK.paperSoft,
    resolution: Math.min(devicePixelRatio || 1, 2),
    autoDensity: true,
    resizeTo: window,
  });
  app.renderer.on('resize', render);
  app.ticker.add(({ deltaMS }) => {
    elapsed += deltaMS / 1000;
    for (const item of scene?._actors || []) item.actor?.tick(elapsed, null, item.ch);
    if (page === 'lineup') return;
    const cards = scene?.children[0]?.children;
    if (cards?.length === 2) {
      cards[0].y = -27 + Math.sin(elapsed * 1.4) * 4;
      cards[1].y = 32 - Math.sin(elapsed * 1.4) * 4;
    }
  });
  canvas.addEventListener('wheel', (event) => {
    if (page !== 'lineup' || !scene || draft?.rulesOpen) return;
    event.preventDefault();
    if (event.offsetX < scene._gallerySplitX * scene.scale.x) scene.setGalleryScroll(draft.gallery + event.deltaY * 0.65);
    else scene.setInspectScroll(draft.inspect + event.deltaY * 0.65);
  }, { passive: false });
  await loadMenu();
} catch (error) {
  notice('主菜单需要支持 WebGL 的现代浏览器。' + (error?.message ? ' ' + error.message : ''));
}
