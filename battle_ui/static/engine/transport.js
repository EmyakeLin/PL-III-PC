/**
 * Transport abstraction decoupling the WebGL tabletop engine from the host protocol.
 * LocalBattleTransport connects to battle_ui (/api/state, /api/action).
 * RoomSeatTransport renders a fixed seat in battle_mcp's shared room.
 */

export class LocalBattleTransport {
  constructor(baseUrl = '', token = null) {
    this.baseUrl = baseUrl;
    this.headers = token ? { Authorization: `Bearer ${token}` } : {};
    this.revision = 0;
    this.busy = false;
  }

  async fetchState() {
    const res = await fetch(`${this.baseUrl}/api/state`, { headers: this.headers, cache: 'no-store' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || '无法读取当前战局。');
    this.revision = data.revision;
    return data;
  }

  async fetchBattleRecord() {
    const res = await fetch(`${this.baseUrl}/api/battle_record`, { headers: this.headers, cache: 'no-store' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || '无法读取战报。');
    return battleRecordText(data);
  }

  async send(action, payload = {}) {
    if (this.busy) return null;
    this.busy = true;
    try {
      const body = { action, revision: this.revision, ...payload };
      const res = await fetch(`${this.baseUrl}/api/action`, {
        method: 'POST',
        headers: { ...this.headers, 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (res.status === 409 && typeof data.revision === 'number') {
        this.revision = data.revision;
        return data;
      }
      if (!res.ok) throw new Error(data.error || '操作被规则拒绝。');
      this.revision = data.revision;
      return data;
    } finally {
      this.busy = false;
    }
  }
}

export function roomTableState(room, assets) {
  const { frame, options, side } = room;
  const attacks = options.filter(move => move.kind === 'attack');
  const intercepts = options.filter(move => move.kind === 'intercept');
  const placeRears = options.filter(move => move.kind === 'place_rear');
  const pending = options.filter(move => move.kind === 'let_through');
  const specials = options.filter(move => move.kind.startsWith('special_') || move.kind === 'decline');
  const normalizedSpecials = specials.map(move => ({ ...move, kind: move.kind.replace(/^special_/, '') }));
  const canPlace = options.some(move => move.kind === 'end');
  const canEndAttack = options.some(move => move.kind === 'end_attack');
  const canLeaveSpecial = side !== null && room.paused_by === side;
  const specialPending = Boolean(frame.effect_choice) || specials.some(move => move.kind === 'special_pass_intercept');
  const mandatorySpecials = specials.some(move => (
    move.kind === 'decline'
    || move.kind.startsWith('special_choose_')
    || move.kind.startsWith('special_decline_')
  ));
  const regularSpecials = mandatorySpecials && !canPlace && !canEndAttack && !pending.length && !canLeaveSpecial;
  let mode = frame.mode;
  if (!room.started) mode = 'lobby';
  else if (frame.is_over) mode = 'finished';
  else if (frame.mode === 'draw_select') mode = frame.draw_select ? 'draw_select' : 'waiting';
  else if (specialPending || regularSpecials) mode = 'special';
  else if (canPlace) mode = 'placement';
  else if (canEndAttack || pending.length) mode = canEndAttack ? 'pre_attack' : 'intercept';
  else if (['placement', 'pre_reveal', 'skill_choice', 'instant_response', 'advance'].includes(mode)) mode = 'waiting';

  const attackTargets = Object.create(null);
  for (const move of attacks) {
    const target = move.character_id
      ? { kind: 'character', id: move.character_id } : { kind: 'duel', number: move.duel_number };
    (attackTargets[move.card_id] ??= []).push(target);
  }
  const rearTargets = Object.create(null);
  for (const move of placeRears) {
    if (move.duel_number != null) (rearTargets[move.card_id] ??= []).push(move.duel_number);
  }
  const canPick = room.can_rematch || room.can_restart || (room.selectable && !room.ready && side !== null);
  const editableSides = canPick
    ? (room.bot_side && !room.challenge ? [side, room.bot_side] : [side]) : [];
  const tableAssets = { ...assets };
  const copies = frame.players.flatMap(player => player.characters).filter(c => c.printed_id && c.printed_id !== c.id);
  if (copies.length) {
    for (const field of ['character_colors', 'character_sprites', 'character_fx']) {
      const originals = assets[field] || {};
      const aliases = copies.filter(c => originals[c.printed_id] != null).map(c => [c.id, originals[c.printed_id]]);
      tableAssets[field] = { ...originals, ...Object.fromEntries(aliases) };
    }
  }
  const exposeModalSpecials = mode === 'special' || canLeaveSpecial;
  const tableActions = normalizedSpecials.filter(move => move.kind === 'ability');
  return {
    ...tableAssets, ...room, mode, active_side: side, editable_sides: editableSides,
    draw_select: frame.draw_select,
    legal_cards: options.filter(move => move.kind === 'place').map(move => move.card_id),
    legal_rear_cards: [...new Set(placeRears.map(move => move.card_id))],
    rear_targets: rearTargets,
    legal_attack_cards: Object.keys(attackTargets),
    legal_intercept_cards: [...new Set(intercepts.map(move => move.card_id))],
    attack_targets: attackTargets,
    pending_responses: pending.map(move => move.response_number),
    intercepts_by_number: Object.fromEntries(pending.map(({ response_number: number }) =>
      [number, intercepts.filter(move => move.response_number === number).map(move => move.card_id)])),
    can_pass: options.some(move => move.kind === 'pass'), can_end_attack: canEndAttack,
    is_paused_by_me: canLeaveSpecial,
    client_paced: Boolean(room.client_paced),
    can_advance: Boolean(room.can_advance),
    can_restart: Boolean(room.can_restart),
    next_voted: Boolean(room.next_voted),
    beat_duration_ms: room.beat_duration_ms ?? 0,
    beat_remaining_ms: room.beat_remaining_ms ?? 0,
    pause_bank_ms: room.pause_bank_ms ?? 0,
    pause_remaining_ms: room.pause_remaining_ms ?? null,
    declarations: room.declarations || [],
    special_available: Boolean(room.has_special_actions),
    special_pending: specialPending || !canLeaveSpecial,
    special_options: exposeModalSpecials ? normalizedSpecials : [],
    inline_special_options: normalizedSpecials,
    table_actions: tableActions,
    special_timing: frame.timing, effect_choice: frame.effect_choice,
    response_times: frame.response_times,
  };
}

function findRoomMove(state, action, payload) {
  if (action === 'use_special') {
    const list = state.special_options?.length ? state.special_options : (state.inline_special_options || []);
    return list[payload.option];
  }
  if (action === 'trigger_table_action') {
    return (state.table_actions || [])[payload.option];
  }
  return state.options.find(move => {
    if (move.kind !== action || (payload.card_id && move.card_id !== payload.card_id)) return false;
    if (action === 'place_rear') return move.duel_number === payload.duel_number;
    if (action === 'attack') {
      const target = payload.target;
      return target?.kind === 'character' ? move.character_id === target.id : move.duel_number === target?.number;
    }
    if (action === 'intercept' || action === 'let_through') return move.response_number === payload.duel_number;
    return true;
  });
}

function battleRecordText({ bot_side: botSide, challenge, events = [], history, match_number = 1, finished, frame, winner_side: winnerSide }) {
  let matchNumber = match_number;
  let start = 0;
  for (const [index, event] of events.entries()) {
    if (event.kind === 'match_start') {
      matchNumber += 1;
      start = index + 1;
    }
  }

  const sideName = (side) => side === botSide ? (challenge || '电脑对手') : `玩家 ${side}`;
  const teams = frame.players.map(({ side, characters }) => {
    const roster = characters.map(character => character.name).join('、');
    return `${sideName(side)}（${characters.length} 人）　${roster}`;
  });
  const result = winnerSide ? `${sideName(winnerSide)}获胜` : '双方平局';
  const status = finished ? `终局　${result} · 第 ${frame.turn} 回合` : `对局进行中 · 第 ${frame.turn} 回合`;
  const record = history ?? events.slice(start)
    .filter(event => event.kind !== 'ready' && event.kind !== 'select_character')
    .map(event => event.text);
  return [`《光点计划 III》战局记录 · 第 ${matchNumber} 局`, ...teams, status, '',
    ...(record.length ? record : ['尚无战斗事件。'])].join('\n');
}

export class RoomSeatTransport {
  constructor(token, baseUrl = '') {
    this.token = token;
    this.baseUrl = baseUrl;
    this.isRoom = true;
    this.busy = false;
    this.state = null;
    this.assets = null;
  }

  async request(path, body = {}, { publicView = false } = {}) {
    const headers = { 'Content-Type': 'application/json' };
    if (this.token && !publicView) headers.Authorization = `Bearer ${this.token}`;
    const res = await fetch(`${this.baseUrl}/api/${path}`, {
      method: 'POST', headers, body: JSON.stringify(body), cache: 'no-store', signal: AbortSignal.timeout(14000),
    });
    const data = await res.json();
    if (!res.ok) {
      const error = new Error(data.error || '房间请求失败。');
      error.status = res.status;
      throw error;
    }
    return data;
  }

  async fetchBattleRecord() {
    const observation = await this.request('observe', { cursor: 0 }, { publicView: true });
    if (!observation.started) throw new Error('开战后可导出战报。');
    return battleRecordText(observation);
  }

  async fetchState(after) {
    this.assets ??= await this.request('canvas/assets');
    const room = await this.request('canvas/state', after ? { after } : {});
    if (room.timeout || room.position === this.state?.position) return null;
    if (this.state && (room.revision < this.state.revision ||
        (room.revision === this.state.revision && room.engine_revision < this.state.engine_revision))) return null;
    this.state = roomTableState(room, this.assets);
    return this.state;
  }

  async follow(onState, onError) {
    let disconnected = false;
    while (!this.state?.frame.is_over || this.state?.bot_side || this.state?.can_rematch) {
      try {
        const state = await this.fetchState(this.state?.position);
        if (state) onState(state);
        if (disconnected) onError(null);
        disconnected = false;
      } catch (error) {
        if (error.status === 403 || error.status === 404) {
          onError(error);
          return;
        }
        if (!disconnected) onError(error);
        disconnected = true;
        await new Promise(resolve => setTimeout(resolve, 1500));
      }
    }
  }

  async send(action, payload = {}) {
    if (this.busy || !this.state?.side) return null;
    const state = this.state;
    const nonce = crypto.getRandomValues(new Uint32Array(4));
    const args = { revision: state.revision, request_id: Array.from(nonce).join('-') };
    let path;
    if (action === 'new') {
      path = (state.can_rematch || state.can_restart) ? 'canvas/rematch' : 'canvas/ready';
      if (state.bot_side) args.roster = payload.roster;
      else if (state.selectable && !state.can_rematch) args.character_id = payload.roster[state.side - 1][0];
    } else if (action === 'rematch') {
      path = 'canvas/rematch';
    } else if (action === 'next') {
      path = 'canvas/next';
    } else if (action === 'open_special' || action === 'leave_special') {
      path = action === 'open_special' ? 'pause' : 'resume';
    } else if (action === 'draw_bottom') {
      path = 'canvas/draw_bottom';
      args.card_ids = payload.card_ids;
    } else if (action === 'set_default_target') {
      path = 'canvas/target';
      args.character_id = payload.character_id;
    } else if (action === 'prepare') {
      path = 'prepare';
      args.declaration = payload.declaration;
    } else {
      const move = findRoomMove(state, action, payload);
      if (!move) throw new Error('这个动作在当前时点不可用。');
      path = 'act';
      args.option_id = move.id;
    }
    this.busy = true;
    try {
      await this.request(path, args);
      return await this.fetchState();
    } catch (error) {
      if (error.status === 409 || (action === 'next' && error.status === 400)) {
        return await this.fetchState();
      }
      throw error;
    } finally {
      this.busy = false;
    }
  }
}
