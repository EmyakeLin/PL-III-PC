/**
 * Lightweight HUD widgets extracted from GameDirector:
 *  1. `createLightcoreBar` — Crystalline Lightcore Integrity bar paired cleanly beneath a fighter's HP bar
 */

import * as PIXI from '../vendor/pixi.min.mjs';

const LIGHTCORE_FILL = 0x2698c8;
const LIGHTCORE_TRAIL = 0xb9e9fb;
const LIGHTCORE_TRACK = 0xe3edf2;
const LIGHTCORE_BORDER = 0x7ab9d4;

export function createLightcoreBar({
  width = 100,
  height = 5,
  maxLightcore = 12,
  lightcore = 12,
  radius = 2.5,
  revealed = true,
  initialRevealAlpha = null,
} = {}) {
  const root = new PIXI.Container();
  const trackG = new PIXI.Graphics();
  const fillG = new PIXI.Graphics();
  root.addChild(trackG, fillG);

  let maxVal = Math.max(0, Number(maxLightcore) || 0);
  let targetVal = Math.max(0, Math.min(maxVal, Number(lightcore) || 0));
  let displayVal = targetVal;
  let trailVal = targetVal;
  let flashTime = 0;
  let revealTarget = revealed ? 1 : 0;
  let revealAlpha = initialRevealAlpha != null ? Math.max(0, Math.min(1, initialRevealAlpha)) : revealTarget;

  const applyReveal = () => {
    root.alpha = revealAlpha;
    root.scale.y = 0.25 + 0.75 * revealAlpha;
    root.visible = revealAlpha > 0.01;
  };

  const draw = () => {
    trackG.clear();
    fillG.clear();
    trackG.roundRect(0, 0, width, height, radius)
      .fill({ color: LIGHTCORE_TRACK, alpha: 0.94 })
      .stroke({ width: 0.8, color: flashTime > 0 ? 0x8b46d4 : LIGHTCORE_BORDER, alpha: 0.9 });

    if (maxVal <= 0) return;
    const trailFrac = Math.max(0, Math.min(1, trailVal / maxVal));
    const fillFrac = Math.max(0, Math.min(1, displayVal / maxVal));
    if (trailFrac > fillFrac) {
      fillG.roundRect(0.5, 0.5, Math.max(2, (width - 1) * trailFrac), height - 1, Math.max(1, radius - 0.5))
        .fill({ color: LIGHTCORE_TRAIL, alpha: 0.95 });
    }
    if (fillFrac > 0) {
      const col = flashTime > 0 ? 0x62c2ee : LIGHTCORE_FILL;
      fillG.roundRect(0.5, 0.5, Math.max(2, (width - 1) * fillFrac), height - 1, Math.max(1, radius - 0.5))
        .fill({ color: col, alpha: 0.96 });
    }
  };

  draw();
  applyReveal();

  root.setRevealed = (flag, { immediate = false } = {}) => {
    revealTarget = flag ? 1 : 0;
    if (immediate) {
      revealAlpha = revealTarget;
      applyReveal();
    }
  };

  root.setLightcore = (nextVal, nextMax = maxVal, { immediate = false } = {}) => {
    maxVal = Math.max(0, Number(nextMax) || 0);
    targetVal = Math.max(0, Math.min(maxVal, Number(nextVal) || 0));
    if (immediate) {
      displayVal = targetVal;
      trailVal = targetVal;
    } else if (targetVal < displayVal) {
      flashTime = 0.35;
    }
    draw();
  };

  root.flash = () => {
    flashTime = 0.42;
    draw();
  };

  root.tick = (dtSec) => {
    let dirty = false;
    if (Math.abs(revealAlpha - revealTarget) > 0.008) {
      revealAlpha += (revealTarget - revealAlpha) * Math.min(1, dtSec * 7.5);
      if (Math.abs(revealAlpha - revealTarget) <= 0.008) revealAlpha = revealTarget;
      applyReveal();
    }
    if (flashTime > 0) {
      flashTime = Math.max(0, flashTime - dtSec);
      dirty = true;
    }
    if (Math.abs(displayVal - targetVal) > 0.02) {
      displayVal += (targetVal - displayVal) * Math.min(1, dtSec * 14);
      if (Math.abs(displayVal - targetVal) <= 0.02) displayVal = targetVal;
      dirty = true;
    }
    if (Math.abs(trailVal - targetVal) > 0.02) {
      const speed = trailVal > targetVal ? 4.5 : 14;
      trailVal += (targetVal - trailVal) * Math.min(1, dtSec * speed);
      if (Math.abs(trailVal - targetVal) <= 0.02) trailVal = targetVal;
      dirty = true;
    }
    if (dirty) draw();
  };

  root.getState = () => ({ lightcore: targetVal, maxLightcore: maxVal, displayVal, trailVal, revealAlpha });
  return root;
}
