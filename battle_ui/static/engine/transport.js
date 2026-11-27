/**
 * Real-time WebSocket transport & state adapter for the unified 《光点计划 III》 Room engine.
 */

export function roomTableState(room, assets = {}) {
  const { frame, options = [], side } = room;
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
  let activeSide = side;
  if (!room.started) {
    mode = 'lobby';
  } else if (frame.is_over) {
    mode = 'finished';
  } else if (room.hotseat && room.hotseat_handoff_side != null) {
    mode = 'handoff';
    activeSide = room.hotseat_handoff_side;
  } else if (frame.mode === 'draw_select') {
    mode = frame.draw_select ? 'draw_select' : 'waiting';
  } else if (specialPending || regularSpecials) {
    mode = 'special';
  } else if (canPlace) {
    mode = 'placement';
  } else if (canEndAttack || pending.length) {
    mode = canEndAttack ? 'pre_attack' : 'intercept';
  } else if (['placement', 'pre_reveal', 'skill_choice', 'instant_response', 'advance'].includes(mode)) {
    mode = 'waiting';
  }

  const attackTargets = Object.create(null);
  for (const move of attacks) {
    const target = move.character_id
      ? { kind: 'character', id: move.character_id }
      : { kind: 'duel', number: move.duel_number };
    (attackTargets[move.card_id] ??= []).push(target);
  }
  const rearTargets = Object.create(null);
  for (const move of placeRears) {
    if (move.duel_number != null) (rearTargets[move.card_id] ??= []).push(move.duel_number);
  }

  let editableSides = [];
  if (!room.started || room.can_rematch || room.can_restart) {
    if (room.hotseat) {
      editableSides = [1, 2];
    } else if (room.bot_side) {
      editableSides = room.challenge ? [1] : [1, 2];
    } else if (side !== null && !room.ready) {
      editableSides = [side];
    }
  }

  const tableAssets = { ...assets };
  const copies = (frame.players || [])
    .flatMap(player => player.characters || [])
    .filter(c => c.printed_id && c.printed_id !== c.id);
  if (copies.length) {
    for (const field of ['character_colors', 'character_sprites', 'character_fx', 'character_card_backs']) {
      const originals = assets[field] || {};
      const aliases = copies.filter(c => originals[c.printed_id] != null).map(c => [c.id, originals[c.printed_id]]);
      tableAssets[field] = { ...originals, ...Object.fromEntries(aliases) };
    }
  }

  const exposeModalSpecials = mode === 'special' || canLeaveSpecial;
  const tableActions = normalizedSpecials.filter(move => move.kind === 'ability');
  return {
    ...tableAssets,
    ...room,
    mode,
    active_side: activeSide,
    editable_sides: editableSides,
    draw_select: frame.draw_select,
    legal_cards: options.filter(move => move.kind === 'place').map(move => move.card_id),
    legal_rear_cards: [...new Set(placeRears.map(move => move.card_id))],
    rear_targets: rearTargets,
    legal_attack_cards: Object.keys(attackTargets),
    legal_intercept_cards: [...new Set(intercepts.map(move => move.card_id))],
    attack_targets: attackTargets,
    pending_responses: pending.map(move => move.response_number),
    intercepts_by_number: Object.fromEntries(
      pending.map(({ response_number: number }) => [
        number,
        intercepts.filter(move => move.response_number === number).map(move => move.card_id),
      ])
    ),
    can_pass: options.some(move => move.kind === 'pass'),
    can_end_attack: canEndAttack,
    is_paused_by_me: canLeaveSpecial,
    client_paced: Boolean(room.client_paced),
    can_advance: Boolean(room.can_advance),
    can_restart: Boolean(room.can_restart),
    can_reopen_lobby: Boolean(room.can_reopen_lobby),
    can_concede: Boolean(room.can_concede),
    can_claim_disconnect_win: Boolean(room.can_claim_disconnect_win),
    next_voted: Boolean(room.next_voted),
    beat_duration_ms: room.beat_duration_ms ?? 0,
    beat_remaining_ms: room.beat_remaining_ms ?? 0,
    pause_bank_ms: room.pause_bank_ms ?? null,
    pause_remaining_ms: room.pause_remaining_ms ?? null,
    declarations: room.declarations || [],
    special_available: Boolean(room.has_special_actions),
    special_pending: specialPending || !canLeaveSpecial,
    special_options: exposeModalSpecials ? normalizedSpecials : [],
    inline_special_options: normalizedSpecials,
    table_actions: tableActions,
    special_timing: frame.timing,
    effect_choice: frame.effect_choice,
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
  return (state.options || []).find(move => {
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

function battleRecordText(recordData) {
  if (recordData?.markdown && typeof recordData.markdown === 'string') {
    return recordData.markdown;
  }
  const { bot_side: botSide, challenge, events = [], history, match_number = 1, finished, frame, winner_side: winnerSide } = recordData;
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
    .filter(event => event.kind !== 'ready' && event.kind !== 'unready' && event.kind !== 'select_character')
    .map(event => event.text);
  return [
    `《光点计划 III》战局记录 · 第 ${matchNumber} 局`,
    ...teams,
    status,
    '',
    ...(record.length ? record : ['尚无战斗事件。']),
  ].join('\n');
}

function makeRequestId() {
  const nonce = crypto.getRandomValues(new Uint32Array(4));
  return Array.from(nonce).join('-');
}

export class RoomSeatTransport {
  constructor(token, baseUrl = '') {
    this.token = token || null;
    this.baseUrl = baseUrl;
    this.isRoom = true;
    this.busy = false;
    this.state = null;
    this.assets = null;
    this.ws = null;
    this._pending = new Map();
    this._pingTimer = null;
    this._stopped = false;
    this._onState = null;
    this._onError = null;
  }

  _wsUrl() {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${proto}//${location.host}${this.baseUrl}/ws`;
  }

  async requestHttp(path, body = null, { method = 'POST', publicView = false } = {}) {
    const headers = {};
    if (body !== null) headers['Content-Type'] = 'application/json';
    if (this.token && !publicView) headers.Authorization = `Bearer ${this.token}`;
    const res = await fetch(`${this.baseUrl}/api/${path}`, {
      method,
      headers,
      body: body !== null ? JSON.stringify(body) : undefined,
      cache: 'no-store',
      signal: AbortSignal.timeout(14000),
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
    const record = await this.requestHttp('battle_record', null, { method: 'GET' });
    return battleRecordText(record);
  }

  follow(onState, onError) {
    this._onState = onState;
    this._onError = onError;
    this._stopped = false;
    this._connectLoop();
  }

  close() {
    this._stopped = true;
    this._clearPing();
    if (this.ws) {
      try { this.ws.close(); } catch { /* ignore */ }
      this.ws = null;
    }
  }

  _clearPing() {
    if (this._pingTimer) {
      clearInterval(this._pingTimer);
      this._pingTimer = null;
    }
  }

  _connectLoop() {
    let backoffMs = 600;
    let hadDisconnectToast = false;

    const connectOnce = () => {
      if (this._stopped) return;
      const ws = new WebSocket(this._wsUrl());
      this.ws = ws;
      let fatalStop = false;

      ws.addEventListener('open', () => {
        ws.send(JSON.stringify({ type: 'auth', token: this.token }));
        this._clearPing();
        this._pingTimer = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'ping', ts: Date.now() }));
          }
        }, 15000);
      });

      ws.addEventListener('message', (ev) => {
        let msg;
        try {
          msg = JSON.parse(ev.data);
        } catch {
          return;
        }
        if (msg.type === 'welcome') {
          backoffMs = 600;
          if (hadDisconnectToast) {
            hadDisconnectToast = false;
            this._onError?.(null);
          }
          this.assets = msg.assets || {};
          this.state = roomTableState(msg.state, this.assets);
          this._onState?.(this.state);
          return;
        }
        if (msg.type === 'state') {
          if (!this.assets) return;
          this.state = roomTableState(msg.state, this.assets);
          this._onState?.(this.state);
          return;
        }
        if (msg.type === 'ack') {
          const waiter = this._pending.get(msg.request_id);
          if (waiter) {
            this._pending.delete(msg.request_id);
            waiter.resolve(null);
          }
          return;
        }
        if (msg.type === 'conflict' || msg.type === 'error') {
          const waiter = msg.request_id ? this._pending.get(msg.request_id) : null;
          const err = new Error(msg.error || '操作未通过校验。');
          err.status = msg.status || 400;
          if (waiter) {
            this._pending.delete(msg.request_id);
            waiter.reject(err);
          } else if (!msg.request_id && (err.status === 403 || err.status === 404)) {
            fatalStop = true;
            this._stopped = true;
            this._onError?.(err);
          } else {
            this._onError?.(err);
          }
        }
      });

      ws.addEventListener('close', () => {
        this._clearPing();
        for (const [, waiter] of this._pending) {
          waiter.reject(new Error('连接已断开，操作结果未知。请在重连后核对局面。'));
        }
        this._pending.clear();
        if (this._stopped || fatalStop) return;
        if (!hadDisconnectToast && this.state) {
          hadDisconnectToast = true;
          this._onError?.(new Error('连接中断，正在自动重连…'));
        }
        const wait = backoffMs;
        backoffMs = Math.min(4000, Math.round(backoffMs * 1.6));
        setTimeout(connectOnce, wait);
      });
    };

    connectOnce();
  }

  _buildCommandPayload(action, payload) {
    const state = this.state;
    const reqId = makeRequestId();
    const base = { type: 'cmd', revision: state?.revision ?? 0, request_id: reqId };

    if (action === 'new') {
      const cmd = state?.started ? 'rematch' : 'ready';
      const msg = { ...base, cmd };
      if (state?.bot_side || state?.hotseat) {
        msg.roster = payload.roster;
      } else if (Array.isArray(payload.roster) && state?.side) {
        msg.team = payload.roster[state.side - 1] || [];
      } else if (Array.isArray(payload.team)) {
        msg.team = payload.team;
      }
      return msg;
    }
    if (action === 'unready') return { ...base, cmd: 'unready' };
    if (action === 'update_team') {
      return { ...base, cmd: 'update_team', team: payload.team, target_side: payload.target_side ?? null };
    }
    if (action === 'update_rules') {
      return { ...base, cmd: 'update_rules', ruleset: payload.ruleset };
    }
    if (action === 'pass_first_pick') return { ...base, cmd: 'pass_first_pick' };
    if (action === 'randomize_bot_team') {
      return { ...base, cmd: 'randomize_bot_team', preset_id: payload.preset_id ?? null };
    }
    if (action === 'rematch') return { ...base, cmd: 'rematch', roster: payload.roster };
    if (action === 'reopen_lobby') return { ...base, cmd: 'reopen_lobby' };
    if (action === 'concede') return { ...base, cmd: 'concede', match_number: state.match_number };
    if (action === 'claim_disconnect_win') return { ...base, cmd: 'claim_disconnect_win' };
    if (action === 'ready' && state?.hotseat && state?.started) {
      return { ...base, cmd: 'hotseat_ready', side: payload.side };
    }
    if (action === 'switch_side') return { ...base, cmd: 'switch_side' };
    if (action === 'next') return { ...base, cmd: 'next' };
    if (action === 'open_special') return { ...base, cmd: 'pause' };
    if (action === 'leave_special') return { ...base, cmd: 'resume' };
    if (action === 'draw_bottom') return { ...base, cmd: 'draw_bottom', card_ids: payload.card_ids };
    if (action === 'set_default_target') return { ...base, cmd: 'set_default_target', character_id: payload.character_id };
    if (action === 'prepare') return { ...base, cmd: 'prepare', declaration: payload.declaration };
    if (['claim_pre_reveal', 'stage_pre_reveal', 'unstage_pre_reveal', 'commit_pre_reveal_plan'].includes(action)) {
      return { ...base, cmd: action, card_id: payload.card_id ?? null, target: payload.target ?? null };
    }

    const move = findRoomMove(state, action, payload);
    if (!move) throw new Error('这个动作在当前时点不可用。');
    return { ...base, cmd: 'act', option_id: move.id };
  }

  async send(action, payload = {}) {
    if (!this.state) throw new Error('房间状态尚未就绪。');
    if (!this.state.side && !this.state.hotseat) throw new Error('观战席不能执行对战操作。');
    const msg = this._buildCommandPayload(action, payload);

    // Primary path: full-duplex WebSocket frame (zero extra HTTP round-trip; state arrives via server push!)
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      return new Promise((resolve, reject) => {
        const timer = setTimeout(() => {
          this._pending.delete(msg.request_id);
          reject(new Error('房间未及时确认，操作结果未知。请核对最新局面。'));
        }, 8000);
        this._pending.set(msg.request_id, {
          resolve: (val) => { clearTimeout(timer); resolve(val); },
          reject: (err) => { clearTimeout(timer); reject(err); },
        });
        try {
          this.ws.send(JSON.stringify(msg));
        } catch (err) {
          this._pending.delete(msg.request_id);
          clearTimeout(timer);
          reject(err);
        }
      });
    }

    // Fallback path if clicked during brief reconnect window: single-RTT HTTP `/api/canvas/cmd`
    const room = await this.requestHttp('canvas/cmd', msg);
    if (this.assets) {
      this.state = roomTableState(room, this.assets);
      return this.state;
    }
    return null;
  }
}
