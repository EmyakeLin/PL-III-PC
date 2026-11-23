// Minimal PIXI stand-in so the stage builders can run headless in Node.
const chain = () => {
  const p = new Proxy(function () {}, {
    get: (t, k) => (k === 'then' ? undefined : p),
    apply: () => p,
  });
  return p;
};

class Point { constructor(x = 0, y = 0) { this.x = x; this.y = y; } set(x = 0, y = x) { this.x = x; this.y = y; } }

export class Container {
  constructor() {
    this.children = []; this.parent = null; this.position = new Point(); this.scale = new Point(1, 1);
    this.pivot = new Point(); this.anchor = new Point(); this.rotation = 0; this.alpha = 1; this.visible = true;
    this.destroyed = false; this._handlers = {}; this.eventMode = 'auto'; this.mask = null;
  }
  get x() { return this.position.x; } set x(v) { this.position.x = v; }
  get y() { return this.position.y; } set y(v) { this.position.y = v; }
  addChild(...cs) { for (const c of cs) { c.parent = this; this.children.push(c); } return cs[0]; }
  addChildAt(c, i) { c.parent = this; this.children.splice(i, 0, c); return c; }
  removeChildren() { const r = this.children; this.children = []; return r; }
  setChildIndex() {}
  on(ev, fn) { (this._handlers[ev] ||= []).push(fn); return this; }
  emit(ev, arg = { stopPropagation() {} }) { for (const fn of this._handlers[ev] || []) fn(arg); }
  destroy() { if (this.destroyed) return; this.destroyed = true; this.emit('destroyed'); if (this.parent) this.parent.children = this.parent.children.filter((c) => c !== this); }
  getGlobalPosition() { let x = 0, y = 0, n = this; while (n) { x += n.x; y += n.y; n = n.parent; } return { x, y }; }
  getLocalBounds() { return { x: -50, y: 0, width: 100, height: 100 }; }
  toLocal(p) { return p; }
}

export class Graphics extends Container {
  constructor() {
    super();
    return new Proxy(this, {
      get: (t, k) => (k in t ? t[k] : (typeof k === 'string' ? () => chainG(t) : undefined)),
    });
  }
}
function chainG(g) {
  const p = new Proxy(g, { get: (t, k) => (k in t ? t[k] : () => p) });
  return p;
}

export class Text extends Container {
  constructor(opts = {}) { super(); this.text = String(opts.text ?? ''); this.style = opts.style || {}; }
  get width() { return this.text.length * (this.style.fontSize || 12) * 0.9; }
  get height() { return (this.style.fontSize || 12) * 1.3; }
}
export class Sprite extends Container {}
export class Rectangle { constructor(x, y, w, h) { Object.assign(this, { x, y, w, h }); } }
export class Circle { constructor(x, y, r) { Object.assign(this, { x, y, r }); } }
export const Ticker = { shared: { fns: new Set(), add(fn) { this.fns.add(fn); }, remove(fn) { this.fns.delete(fn); } } };
export const Assets = { load: async () => null };
export const Texture = { from: () => ({}) , WHITE: {} };
export default { Container, Graphics, Text, Sprite, Rectangle, Circle, Ticker, Assets, Texture };
export { chain };
