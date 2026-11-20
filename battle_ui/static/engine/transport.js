/**
 * Transport abstraction decoupling the WebGL tabletop engine from the host protocol.
 * LocalBattleTransport connects to battle_ui (/api/state, /api/action).
 * A future RoomSeatTransport for battle_mcp can implement the exact same interface.
 */

export class LocalBattleTransport {
  constructor(baseUrl = '') {
    this.baseUrl = baseUrl;
    this.revision = 0;
    this.busy = false;
  }

  async fetchState() {
    const res = await fetch(`${this.baseUrl}/api/state`, { cache: 'no-store' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || '无法读取当前战局。');
    this.revision = data.revision;
    return data;
  }

  async send(action, payload = {}) {
    if (this.busy) return null;
    this.busy = true;
    try {
      const body = { action, revision: this.revision, ...payload };
      const res = await fetch(`${this.baseUrl}/api/action`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
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
