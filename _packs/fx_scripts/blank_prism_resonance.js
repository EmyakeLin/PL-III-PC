/**
 * Custom FX Script Plugin example for 《光点计划 III》 — Blank Boss ("空白") Prism Resonance.
 * Loaded dynamically from `/fx_scripts/blank_prism_resonance.js` when referenced via
 * `"script": "blank_prism_resonance#onPrismStrike"` inside `_packs/fx/blank_boss.json`.
 */

export function onPrismStrike(api, ctx) {
  const from = api.resolveAnchor('attacker.bone_weapon');
  const to = api.resolveAnchor('defender.center');
  const midX = (from.x + to.x) * 0.5;
  const midY = (from.y + to.y) * 0.5;

  // Dual refracted gold prism echo beams fanning slightly around the main strike line
  api.defer(() => {
    api.three?.spawnEnergyBeam({
      fromX: from.x,
      fromY: from.y - 18,
      toX: to.x,
      toY: to.y + 10,
      colorHex: 0xead078,
      duration: 0.34,
    });
    api.three?.triggerRipple(midX, midY, 0xd9a838);
  }, 75);

  api.defer(() => {
    api.three?.spawnImpactBurst(to.x, to.y, 0xf2d98c, 18, false);
  }, 140);
}
