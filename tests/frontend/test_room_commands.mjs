import assert from 'node:assert/strict';
import { test } from 'node:test';
import { GameDirector } from '../../battle_ui/static/engine/game_director.js';
import { RoomSeatTransport } from '../../battle_ui/static/engine/transport.js';

test('rolling replacement sends the selected board instance and waits for acceptance', async () => {
  const sent = [], notices = [];
  const options = [31, 32].map(instance_id => ({
    kind: 'replace', card_id: 'hand', target_card_id: 'board', effect_target: { card: { instance_id } },
  }));
  const director = Object.assign(Object.create(GameDirector.prototype), {
    _getLiveSpecialOptions: () => options, sequencer: { isRollAnimating: true },
    transport: { isRoom: true }, state: { frame: { turn: 1, combat: { kind: 'regular', duel_number: 1, round_id: 1 } } },
    audio: { cardSlide() {} }, _resolveHandCardName: () => '手牌',
    _sendAction: async (action, payload) => { sent.push(payload.declaration); return sent.length === 2; },
    showToast: text => notices.push(text),
  });
  director._pickFieldOption(0);
  director._pickFieldOption(1);
  await Promise.resolve();
  assert.deepEqual(sent.map(d => d.match.target_instance_id), [31, 32]);
  assert.ok(sent.every(d => d.match.target_card_id === 'board' && d.when.timing === 'after_dice_use'));
  assert.equal(notices.length, 1);
});

test('only acknowledgement confirms a command, conflicts and unknown outcomes reject', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  class Socket extends EventTarget {
    static OPEN = 1;
    readyState = Socket.OPEN;
    send(data) { this.last = JSON.parse(data); }
    reply(type, fields = {}) {
      this.dispatchEvent(new MessageEvent('message', { data: JSON.stringify({
        type, request_id: this.last.request_id, ...fields,
      }) }));
    }
  }
  const original = globalThis.WebSocket;
  t.after(() => { globalThis.WebSocket = original; });
  globalThis.WebSocket = Socket;
  const transport = new RoomSeatTransport('test');
  transport._wsUrl = () => 'ws://unused';
  transport.state = { side: 1, revision: 1, match_number: 3 };
  transport.follow(() => {}, () => {});
  const ws = transport.ws;
  const accepted = transport.send('concede');
  assert.equal(ws.last.match_number, 3);
  ws.reply('ack');
  await accepted;
  const conflict = transport.send('next');
  ws.reply('conflict', { error: '局面已更新', status: 409 });
  await assert.rejects(conflict, { status: 409, message: '局面已更新' });
  const late = transport.send('next');
  t.mock.timers.tick(8000);
  await assert.rejects(late, /结果未知/);
  const disconnected = transport.send('next');
  transport._stopped = true;
  ws.dispatchEvent(new Event('close'));
  await assert.rejects(disconnected, /结果未知/);
  assert.equal(transport._pending.size, 0);
});
