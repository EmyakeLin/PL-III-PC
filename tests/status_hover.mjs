import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import * as PIXI from '../battle_ui/static/vendor/pixi.min.mjs';
import { GameDirector } from '../battle_ui/static/engine/game_director.js';

const { catalog, fighters, printed } = JSON.parse(readFileSync(0, 'utf8'));
const measure = { measureText: text => ({
  width: text.length * 10, actualBoundingBoxAscent: 10, actualBoundingBoxDescent: 3,
}) };
PIXI.DOMAdapter.set({ ...PIXI.DOMAdapter.get(), getCanvasRenderingContext2D: () => class {},
  createCanvas: () => ({ getContext: () => measure }) });

function texts(node) {
  return node instanceof PIXI.Text ? [node.text] : (node.children || []).flatMap(texts);
}

// Exercise the game's icon handlers and inspect their Pixi text nodes.
const director = Object.assign(Object.create(GameDirector.prototype), {
  state: { mode: 'combat', catalog }, transport: {}, time: 0,
  layout: { w: 1280, h: 800, arenaX: 200, arenaW: 880 },
  actorsLayer: new PIXI.Container(), wingsLayer: new PIXI.Container(), inspectLayer: new PIXI.Container(),
  sequencer: { deferredHpOverrides: new Map(), deferredLightcoreOverrides: new Map() },
  mirroredIds: new Set(), actorMotion: new Map(), lightcoreRevealed: new Set(),
  lightcoreRevealAlpha: new Map(), lightcoreTrailState: new Map(), lightcoreWidgets: new Map(),
  actorNodes: new Map(), charRects: new Map(), _fighterFloorDrawers: new Map(),
  hpWidgets: new Map(), hpTrailState: new Map(), _fighterSpeedRefs: [],
});
const seen = new Set();
for (const [index, fighter] of fighters.entries()) {
  const slot = { x: 180, y: 300, actorR: 38, hudW: 300, visible: true };
  const { statusOverlayHost } = director._buildOpenBattlefieldFighter(fighter, index + 1, slot, 1);
  const statuses = Object.entries(fighter.statuses);
  assert.ok(statusOverlayHost.children.length >= 2);
  for (const icon of statusOverlayHost.children) {
    icon.emit('pointerover');
    const plates = director.inspectLayer.children.at(-1).children;
    assert.equal(plates.length, statuses.length);
    for (const [i, [name, value]] of statuses.entries()) {
      if (!Object.hasOwn(printed, name)) continue;
      seen.add(name);
      assert.deepEqual(texts(plates[i]), [name + ' ' + value, ...printed[name].split('\n'),
        ...(fighter.status_details?.[name] || [])], name);
    }
    icon.emit('pointerout');
    assert.equal(director.inspectLayer.children.length, 0);
  }
}
// 折影 is applied to a skill. Only character statuses have a fighter HUD icon.
assert.deepEqual(seen, new Set(Object.keys(printed).filter(name => name !== '折影')));
