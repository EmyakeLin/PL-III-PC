/**
 * Layered Minimalist SVG Character Rig Engine & Compact Figurine Builder
 * for 《光点计划 III》.
 *
 * Art Direction (Compact, Luminous, Iconic Boardgame Figurine):
 *  - Preserves the clean, compact, sunlit geometric elegance of the original stage actors ("小而简洁").
 *  - Standard canvas: `viewBox="0 0 160 160"`, base anchor `data-foot="80,140"`, facing RIGHT (+X).
 *  - Crisp warm-white `#FFFDF7` torso edges, borderless airy watercolor halos/ribbons,
 *    compact chess-figurine mantle seated cleanly on the floor plinth (no cluttered limbs),
 *    ivory sphere/hex head with 1 iconic crest or visor, and crisp signature weapon.
 *  - 5 core semantic `<g id="bone_*">` groups (+ optional `bone_arm_back` for offhand props):
 *      bone_back_hair (halo/emblem), bone_cape_back (ribbons/cloak), bone_arm_back (optional offhand),
 *      bone_torso (figurine body), bone_head (head + crest/visor), bone_weapon (signature weapon).
 *  - Supersamples each bone SVG once (2.5x HiDPI Canvas -> PIXI.Texture) and caches by key,
 *    giving O(1) GPU bone animation at 60fps across 1v1 and 10v10 rosters.
 */

import * as PIXI from '../vendor/pixi.min.mjs';

export const SVG_VIEW_W = 160;
export const SVG_VIEW_H = 160;
export const SVG_FOOT_X = 80;
export const SVG_FOOT_Y = 140;

export const BONE_ORDER = [
  'bone_back_hair',
  'bone_cape_back',
  'bone_arm_back',
  'bone_torso',
  'bone_head',
  'bone_weapon',
];

export const DEFAULT_BONE_PIVOTS = {
  bone_back_hair: [80, 82],
  bone_cape_back: [74, 84],
  bone_arm_back: [96, 98],
  bone_torso: [80, 114],
  bone_head: [80, 66],
  bone_weapon: [94, 102],
};

const PAPER = '#FFFDF7';
const TRIM_DARK = '#3B322A';

const RIG_CACHE = new Map();
const EXTERNAL_SPRITE_URLS = new Map();

export function setCharacterSpriteUrls(spriteMap) {
  if (!spriteMap || typeof spriteMap !== 'object') return;
  for (const [charId, url] of Object.entries(spriteMap)) {
    if (typeof charId === 'string' && typeof url === 'string' && url.endsWith('.svg')) {
      const prev = EXTERNAL_SPRITE_URLS.get(charId);
      if (prev !== url) {
        EXTERNAL_SPRITE_URLS.set(charId, url);
        preloadExternalSvgRig(url);
      }
    }
  }
}

export function getCharacterSpriteUrl(charId) {
  return charId ? (EXTERNAL_SPRITE_URLS.get(charId) || null) : null;
}

function hexNumToCss(n, fallback = '#2A9D8F') {
  if (typeof n === 'string' && n.startsWith('#')) return n;
  if (typeof n !== 'number' || !Number.isFinite(n)) return fallback;
  return `#${(Math.floor(n) & 0xffffff).toString(16).padStart(6, '0')}`;
}

function mixHex(hexA, hexB, t) {
  const a = parseInt(hexNumToCss(hexA).slice(1), 16);
  const b = parseInt(hexNumToCss(hexB).slice(1), 16);
  const r = Math.round(((a >> 16) & 255) * (1 - t) + ((b >> 16) & 255) * t);
  const g = Math.round(((a >> 8) & 255) * (1 - t) + ((b >> 8) & 255) * t);
  const bl = Math.round((a & 255) * (1 - t) + (b & 255) * t);
  return `#${((r << 16) | (g << 8) | bl).toString(16).padStart(6, '0')}`;
}

function shadeHex(hex, amount = 0.24) {
  return mixHex(hex, '#2A221C', amount);
}

function tintHex(hex, amount = 0.36) {
  return mixHex(hex, '#FFFDF7', amount);
}

function parsePivot(el, boneId) {
  const raw = el?.getAttribute?.('data-pivot');
  if (raw) {
    const parts = raw.split(/[\s,]+/).map(Number);
    if (parts.length >= 2 && Number.isFinite(parts[0]) && Number.isFinite(parts[1])) {
      return [parts[0], parts[1]];
    }
  }
  return DEFAULT_BONE_PIVOTS[boneId] || [80, 96];
}

function rasterizeSvgToTexture(svgMarkup, viewW, viewH, supersample = 2.5) {
  return new Promise((resolve, reject) => {
    if (typeof Image === 'undefined' || typeof document === 'undefined') {
      reject(new Error('DOM unavailable'));
      return;
    }
    const img = new Image();
    img.decoding = 'async';
    img.onload = () => {
      try {
        const cw = Math.max(16, Math.round(viewW * supersample));
        const ch = Math.max(16, Math.round(viewH * supersample));
        const canvas = document.createElement('canvas');
        canvas.width = cw;
        canvas.height = ch;
        const ctx = canvas.getContext('2d');
        ctx.imageSmoothingEnabled = true;
        ctx.imageSmoothingQuality = 'high';
        ctx.clearRect(0, 0, cw, ch);
        ctx.drawImage(img, 0, 0, cw, ch);
        const tex = PIXI.Texture.from(canvas);
        if (tex?.source) {
          tex.source.scaleMode = 'linear';
        }
        resolve(tex);
      } catch (err) {
        reject(err);
      }
    };
    img.onerror = (err) => reject(err);
    img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svgMarkup)}`;
  });
}

/**
 * Parse a layered SVG document and compile each `<g id="bone_*">` into a HiDPI cached PIXI.Texture.
 */
export function compileSvgRig(svgText, cacheKey, supersample = 2.5) {
  if (RIG_CACHE.has(cacheKey)) {
    return RIG_CACHE.get(cacheKey);
  }
  const asset = {
    key: cacheKey,
    ready: false,
    failed: false,
    viewW: SVG_VIEW_W,
    viewH: SVG_VIEW_H,
    footX: SVG_FOOT_X,
    footY: SVG_FOOT_Y,
    bones: [],
    listeners: new Set(),
    onReady(fn) {
      if (this.ready || this.failed) {
        fn(this);
      } else {
        this.listeners.add(fn);
      }
    },
  };
  RIG_CACHE.set(cacheKey, asset);

  const notify = () => {
    for (const fn of asset.listeners) {
      try { fn(asset); } catch (_) { /* ignore */ }
    }
    asset.listeners.clear();
  };

  if (typeof DOMParser === 'undefined' || typeof XMLSerializer === 'undefined') {
    asset.failed = true;
    notify();
    return asset;
  }

  try {
    const parser = new DOMParser();
    const doc = parser.parseFromString(svgText, 'image/svg+xml');
    const svgEl = doc.querySelector('svg');
    if (!svgEl || doc.querySelector('parsererror')) {
      asset.failed = true;
      notify();
      return asset;
    }

    const vb = (svgEl.getAttribute('viewBox') || `0 0 ${SVG_VIEW_W} ${SVG_VIEW_H}`)
      .trim().split(/[\s,]+/).map(Number);
    const viewW = vb.length === 4 && vb[2] > 0 ? vb[2] : SVG_VIEW_W;
    const viewH = vb.length === 4 && vb[3] > 0 ? vb[3] : SVG_VIEW_H;
    asset.viewW = viewW;
    asset.viewH = viewH;
    const footAttr = svgEl.getAttribute('data-foot');
    if (footAttr) {
      const fp = footAttr.split(/[\s,]+/).map(Number);
      if (fp.length >= 2 && Number.isFinite(fp[0]) && Number.isFinite(fp[1])) {
        asset.footX = fp[0];
        asset.footY = fp[1];
      }
    } else {
      asset.footX = viewW * 0.5;
      asset.footY = viewH * 0.875;
    }

    const serializer = new XMLSerializer();
    const defsEls = Array.from(svgEl.querySelectorAll('defs'));
    const defsMarkup = defsEls.map((d) => serializer.serializeToString(d)).join('');

    const boneEls = Array.from(svgEl.querySelectorAll('g[id^="bone_"]'));
    const tasks = [];

    if (boneEls.length > 0) {
      for (const gEl of boneEls) {
        const id = gEl.getAttribute('id');
        const [pivotX, pivotY] = parsePivot(gEl, id);
        const groupMarkup = serializer.serializeToString(gEl);
        const frag = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${viewW} ${viewH}" width="${viewW}" height="${viewH}">${defsMarkup}${groupMarkup}</svg>`;
        tasks.push(
          rasterizeSvgToTexture(frag, viewW, viewH, supersample).then((texture) => ({
            id, pivotX, pivotY, texture,
          }))
        );
      }
    } else {
      const whole = serializer.serializeToString(svgEl);
      tasks.push(
        rasterizeSvgToTexture(whole, viewW, viewH, supersample).then((texture) => ({
          id: 'bone_torso',
          pivotX: viewW * 0.5,
          pivotY: viewH * 0.7,
          texture,
        }))
      );
    }

    Promise.all(tasks).then((bones) => {
      asset.bones = bones;
      asset.ready = true;
      notify();
    }).catch(() => {
      asset.failed = true;
      notify();
    });
  } catch (_) {
    asset.failed = true;
    notify();
  }

  return asset;
}

/**
 * Fetch and compile an external `/sprites/<char_id>.svg` file (cached by URL).
 */
export function preloadExternalSvgRig(url) {
  const cacheKey = `url:${url}`;
  if (RIG_CACHE.has(cacheKey)) {
    return RIG_CACHE.get(cacheKey);
  }
  const placeholder = {
    key: cacheKey,
    ready: false,
    failed: false,
    viewW: SVG_VIEW_W,
    viewH: SVG_VIEW_H,
    footX: SVG_FOOT_X,
    footY: SVG_FOOT_Y,
    bones: [],
    listeners: new Set(),
    onReady(fn) {
      if (this.ready || this.failed) {
        fn(this);
      } else {
        this.listeners.add(fn);
      }
    },
  };
  RIG_CACHE.set(cacheKey, placeholder);

  const notify = () => {
    for (const fn of placeholder.listeners) {
      try { fn(placeholder); } catch (_) { /* ignore */ }
    }
    placeholder.listeners.clear();
  };

  if (typeof fetch !== 'function') {
    placeholder.failed = true;
    notify();
    return placeholder;
  }

  fetch(url, { cache: 'no-store' })
    .then((res) => {
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.text();
    })
    .then((svgText) => {
      const compiled = compileSvgRig(svgText, `parsed:${url}`, 2.5);
      compiled.onReady((done) => {
        placeholder.ready = done.ready;
        placeholder.failed = done.failed;
        placeholder.viewW = done.viewW;
        placeholder.viewH = done.viewH;
        placeholder.footX = done.footX;
        placeholder.footY = done.footY;
        placeholder.bones = done.bones;
        notify();
      });
    })
    .catch(() => {
      placeholder.failed = true;
      notify();
    });

  return placeholder;
}

/* ============================================================================
 *  TIER 2: COMPACT MINIMALIST FIGURINE 160x160 SVG BUILDER
 *  Matches the original clean, compact, jewel-like miniature aesthetic!
 * ============================================================================ */

const COMPACT_PROFILES = {
  plan_b_annolin: { halo: 'soft', cape: 'wind_ribbons', torso: 'mantle', head: 'crest', weapon: 'wind_blade' },
  plan_b_heck: { halo: 'ember', cape: 'tattered', torso: 'coat_diamond', head: 'flame_visor', weapon: 'flame_sword' },
  plan_b_heris: { halo: 'ember', cape: 'scarf', torso: 'tactical_strap', head: 'goggles', weapon: 'warhammer' },
  plan_b_li_ling: { halo: 'prism', cape: 'wing_cape', torso: 'mantle', head: 'visor', weapon: 'energy_lance' },
  plan_b_sa: { halo: 'boss_sun', cape: 'royal_cloak', torso: 'boss_robe', head: 'crown_visor', weapon: 'boss_blade' },
  iron_qi_zheng: { halo: 'boss_sun', cape: 'royal_cloak', torso: 'armored', head: 'hex_crown', weapon: 'hook_saber' },
  char_iron_vanguard: { halo: 'soft', cape: 'none', torso: 'armored', head: 'hex_visor', weapon: 'tower_shield' },
  char_crimson_duelist: { halo: 'soft', cape: 'flowing_cape', torso: 'mantle', head: 'plume', weapon: 'rapier' },
  waa_lake: { halo: 'soft', cape: 'tactical_cape', torso: 'tactical_strap', head: 'visor', weapon: 'saber' },
  waa_grolina: { halo: 'compass', cape: 'wing_cape', torso: 'tactical_strap', head: 'visor', weapon: 'needle_lance' },
  waa_erkes: { halo: 'prism', cape: 'none', torso: 'hex_reactor', head: 'hex_plain', weapon: 'cannon_gauntlet' },
  nova_lin_qiu: { halo: 'feather', cape: 'royal_cloak', torso: 'split_robe', head: 'feather_crest', weapon: 'inscribe_sword' },
  mistport_cen_yao: { halo: 'astrolabe', cape: 'none', torso: 'mantle', head: 'cap', weapon: 'sight_rule' },
  ember_wen_sheng: { halo: 'spotlight', cape: 'none', torso: 'theatre_sash', head: 'half_mask', weapon: 'war_fan' },
  bellfounder_que_ming: { halo: 'bell_rings', cape: 'royal_cloak', torso: 'coat_diamond', head: 'halo_ring', weapon: 'bell_mallet' },
  shipbreaker_shen_li: { halo: 'boss_sun', cape: 'tattered', torso: 'armored', head: 'bandana_visor', weapon: 'cleaver' },
  blank_boss: { halo: 'mirror', cape: 'royal_cloak', torso: 'kintsugi', head: 'halo_mirror', weapon: 'prism_blade' },
  drill_scout: { halo: 'soft', cape: 'scarf', torso: 'coat_diamond', head: 'hood', weapon: 'twin_daggers' },
  drill_medic: { halo: 'medic_cross', cape: 'none', torso: 'mantle', head: 'cap', weapon: 'staff' },
  drill_captain: { halo: 'boss_sun', cape: 'flowing_cape', torso: 'armored', head: 'cap', weapon: 'hook_saber' },
  drill_engine: { halo: 'prism', cape: 'none', torso: 'hex_reactor', head: 'hex_visor', weapon: 'warhammer' },
};

function hashStr(str) {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function resolveCompactProfile(ch, pal) {
  const id = ch?.id || '';
  if (COMPACT_PROFILES[id]) return COMPACT_PROFILES[id];
  const h = hashStr(`${id}:${ch?.name || ''}`);
  const isBoss = ch?.rank === 'BOSS' || ch?.rank === 'EMPOWERED_BOSS';
  const halos = ['soft', 'astrolabe', 'ember', 'prism', 'compass'];
  const capes = ['wind_ribbons', 'tactical_cape', 'flowing_cape', 'scarf', 'tattered'];
  const torsos = ['mantle', 'tactical_strap', 'coat_diamond', 'armored', 'split_robe'];
  const heads = ['crest', 'visor', 'plume', 'hood', 'hex_visor'];
  const weaponMap = {
    blade: 'saber',
    lance: 'energy_lance',
    staff: 'staff',
    shield: 'tower_shield',
    dual: 'twin_daggers',
    cannon: 'cannon_gauntlet',
    tome: 'sight_rule',
  };
  return {
    halo: isBoss ? 'boss_sun' : halos[h % halos.length],
    cape: isBoss ? 'royal_cloak' : capes[(h >>> 4) % capes.length],
    torso: isBoss ? 'boss_robe' : torsos[(h >>> 8) % torsos.length],
    head: isBoss ? 'crown_visor' : heads[(h >>> 12) % heads.length],
    weapon: weaponMap[pal.weaponArchetype] || 'saber',
  };
}

function renderCompactHalo(halo, primary, sec, hi) {
  const base = `<circle cx="80" cy="82" r="44" fill="${hi}" fill-opacity="0.72" stroke="${primary}" stroke-width="1.3" stroke-opacity="0.34"/>`;
  if (halo === 'boss_sun') {
    return `
      <circle cx="80" cy="82" r="46" fill="${hi}" fill-opacity="0.74" stroke="${sec}" stroke-width="1.6" stroke-opacity="0.52"/>
      <polygon points="80,30 84,39 76,39" fill="${sec}" opacity="0.86"/>
      <polygon points="28,82 37,78 37,86" fill="${sec}" opacity="0.86"/>
      <polygon points="132,82 123,78 123,86" fill="${sec}" opacity="0.86"/>
    `;
  }
  if (halo === 'astrolabe' || halo === 'bell_rings') {
    return base + `
      <circle cx="80" cy="82" r="48" fill="none" stroke="${sec}" stroke-width="1.4" opacity="0.65"/>
      <path d="M 80 30 L 80 42 M 80 122 L 80 134 M 28 82 L 40 82 M 120 82 L 132 82" stroke="${sec}" stroke-width="1.6"/>
    `;
  }
  if (halo === 'ember') {
    return base + `
      <polygon points="36,68 41,58 44,70 38,75" fill="${sec}" opacity="0.86"/>
      <polygon points="28,98 35,88 38,100 31,105" fill="${primary}" opacity="0.72"/>
    `;
  }
  if (halo === 'spotlight') {
    return base + `<polygon points="80,32 124,132 36,132" fill="${sec}" opacity="0.18"/>`;
  }
  if (halo === 'medic_cross') {
    return base + `
      <rect x="74" y="54" width="12" height="36" rx="2" fill="${sec}" opacity="0.28"/>
      <rect x="62" y="66" width="36" height="12" rx="2" fill="${sec}" opacity="0.28"/>
    `;
  }
  if (halo === 'prism') {
    return base + `<polygon points="80,36 124,82 80,128 36,82" fill="none" stroke="${sec}" stroke-width="1.3" opacity="0.58"/>`;
  }
  return base;
}

function renderCompactCape(cape, primary, priDark, sec) {
  if (cape === 'none') return '';
  if (cape === 'wind_ribbons') {
    return `
      <path d="M 74 70 Q 40 52 16 70 Q 44 82 72 88 Z" fill="${sec}" opacity="0.74"/>
      <path d="M 74 84 Q 44 102 22 118 Q 52 118 76 102 Z" fill="${primary}" opacity="0.56"/>
    `;
  }
  if (cape === 'royal_cloak') {
    return `
      <path d="M 74 72 Q 36 80 20 128 L 66 126 Z" fill="${priDark}" opacity="0.82"/>
      <path d="M 28 120 L 64 120" stroke="${sec}" stroke-width="2.4" stroke-linecap="round"/>
    `;
  }
  if (cape === 'tactical_cape' || cape === 'wing_cape') {
    return `<polygon points="72,70 22,${cape === 'wing_cape' ? 58 : 82} 38,122 70,114" fill="${sec}" opacity="0.80" stroke="${primary}" stroke-width="1.3" stroke-linejoin="round"/>`;
  }
  if (cape === 'flowing_cape') {
    return `<path d="M 74 70 Q 38 68 20 118 L 64 126 Z" fill="${primary}" opacity="0.78" stroke="${sec}" stroke-width="1.4"/>`;
  }
  if (cape === 'tattered') {
    return `<polygon points="74,70 26,86 38,118 52,110 56,124 74,116" fill="${priDark}" opacity="0.78"/>`;
  }
  // scarf
  return `<path d="M 74 70 Q 46 74 26 94" fill="none" stroke="${sec}" stroke-width="5.5" stroke-linecap="round"/>`;
}

function renderCompactTorso(torso, primary, priDark, sec, hi, metal) {
  if (torso === 'hex_reactor') {
    return `
      <polygon points="80,68 112,86 112,122 80,140 48,122 48,86" fill="${primary}" stroke="${PAPER}" stroke-width="2.0" stroke-linejoin="round"/>
      <polygon points="82,86 94,93 94,107 82,114 70,107 70,93" fill="${sec}" stroke="${PAPER}" stroke-width="1.5"/>
    `;
  }
  if (torso === 'armored') {
    return `
      <polygon points="56,72 104,72 100,138 60,138" fill="${primary}" stroke="${PAPER}" stroke-width="2.0" stroke-linejoin="round"/>
      <polygon points="68,74 94,74 91,110 81,118 71,110" fill="${metal}" stroke="${PAPER}" stroke-width="1.4"/>
      <polygon points="81,82 87,94 81,106 75,94" fill="${sec}"/>
      <rect x="46" y="68" width="24" height="16" rx="5" fill="${metal}" stroke="${sec}" stroke-width="1.8"/>
      <path d="M 62 128 L 98 128" stroke="${sec}" stroke-width="2.4" stroke-linecap="round"/>
    `;
  }
  if (torso === 'tactical_strap') {
    return `
      <polygon points="60,72 103,76 98,138 62,138" fill="${primary}" stroke="${PAPER}" stroke-width="2.0" stroke-linejoin="round"/>
      <line x1="64" y1="78" x2="96" y2="122" stroke="${sec}" stroke-width="3.6" stroke-linecap="round"/>
      <circle cx="82" cy="96" r="7.5" fill="${PAPER}" stroke="${sec}" stroke-width="2.0"/>
      <circle cx="82" cy="96" r="3.2" fill="${sec}"/>
    `;
  }
  if (torso === 'theatre_sash') {
    return `
      <polygon points="80,66 106,94 110,138 50,138 54,94" fill="${primary}" stroke="${PAPER}" stroke-width="2.0" stroke-linejoin="round"/>
      <polygon points="66,78 96,88 88,132 62,126" fill="${sec}" opacity="0.88"/>
    `;
  }
  if (torso === 'split_robe' || torso === 'boss_robe') {
    return `
      <polygon points="80,66 104,96 98,138 60,138 56,96" fill="${primary}" stroke="${PAPER}" stroke-width="2.0" stroke-linejoin="round"/>
      <polygon points="80,68 102,96 96,136 80,136" fill="${torso === 'split_robe' ? PAPER : priDark}" opacity="0.92"/>
      <path d="M 62 128 L 96 128" stroke="${sec}" stroke-width="2.4" stroke-linecap="round"/>
      <polygon points="80,92 86,100 80,108 74,100" fill="${sec}"/>
    `;
  }
  if (torso === 'coat_diamond') {
    return `
      <polygon points="58,72 102,74 98,138 62,138" fill="${primary}" stroke="${PAPER}" stroke-width="2.0" stroke-linejoin="round"/>
      <polygon points="80,76 92,98 80,114 69,98" fill="${hi}" opacity="0.92"/>
      <polygon points="80,86 86,96 80,106 74,96" fill="${sec}"/>
      <path d="M 64 126 L 96 126" stroke="${sec}" stroke-width="2.2" stroke-linecap="round"/>
    `;
  }
  // mantle (default classic Anolin-like sculpted pawn)
  return `
    <polygon points="80,66 104,98 96,138 62,138 56,96" fill="${primary}" stroke="${PAPER}" stroke-width="2.0" stroke-linejoin="round"/>
    <polygon points="80,74 93,98 80,116 68,98" fill="${hi}" opacity="0.92"/>
    <path d="M 62 128 L 96 128" stroke="${sec}" stroke-width="2.2" stroke-linecap="round" opacity="0.85"/>
    <polygon points="80,94 85,100 80,106 75,100" fill="${sec}"/>
  `;
}

function renderCompactHead(head, primary, sec, metal) {
  if (head === 'hex_visor' || head === 'hex_crown' || head === 'hex_plain') {
    return `
      <polygon points="82,39 95,46 95,61 82,68 69,61 69,46" fill="${PAPER}" stroke="${TRIM_DARK}" stroke-width="1.9" stroke-linejoin="round"/>
      ${head !== 'hex_plain' ? `<rect x="75" y="51" width="21" height="5.5" rx="2.5" fill="${primary}"/>` : ''}
      ${head === 'hex_crown' ? `<polygon points="82,31 87,42 82,47 77,42" fill="${sec}"/>` : ''}
    `;
  }
  const baseSphere = `<circle cx="82" cy="54" r="14" fill="${PAPER}" stroke="${TRIM_DARK}" stroke-width="1.8"/>`;
  if (head === 'visor' || head === 'flame_visor' || head === 'bandana_visor') {
    return baseSphere + `
      <rect x="78" y="49.5" width="19.5" height="7" rx="3.2" fill="${sec}"/>
      ${head === 'flame_visor' ? `<path d="M 68 48 L 76 32 L 84 42 L 94 34 L 94 46 Z" fill="${primary}"/>` : ''}
      ${head === 'bandana_visor' ? `<path d="M 68 46 Q 82 40 96 46 L 94 50 Q 82 45 70 50 Z" fill="${primary}"/>` : ''}
    `;
  }
  if (head === 'goggles') {
    return baseSphere + `
      <circle cx="81" cy="50" r="5" fill="${metal}" stroke="${TRIM_DARK}" stroke-width="1.4"/>
      <circle cx="81" cy="50" r="2.8" fill="${sec}"/>
      <circle cx="92" cy="50" r="4.6" fill="${metal}" stroke="${TRIM_DARK}" stroke-width="1.4"/>
      <circle cx="92" cy="50" r="2.5" fill="${sec}"/>
    `;
  }
  if (head === 'plume') {
    return baseSphere + `<path d="M 74 42 Q 52 28 42 50" fill="none" stroke="${sec}" stroke-width="3.2" stroke-linecap="round"/>`;
  }
  if (head === 'half_mask') {
    return baseSphere + `<polygon points="82,40 96,48 94,62 82,58" fill="${sec}"/>`;
  }
  if (head === 'hood') {
    return baseSphere + `<polygon points="62,56 78,34 94,48 80,46" fill="${primary}"/>`;
  }
  if (head === 'cap') {
    return baseSphere + `
      <path d="M 66 48 Q 82 34 98 46 Z" fill="${primary}" stroke="${TRIM_DARK}" stroke-width="1.4"/>
      <line x1="86" y1="46" x2="104" y2="50" stroke="${TRIM_DARK}" stroke-width="2.4" stroke-linecap="round"/>
      <circle cx="82" cy="43" r="2.6" fill="${sec}"/>
    `;
  }
  if (head === 'crown_visor') {
    return baseSphere + `
      <rect x="77" y="51" width="19" height="5.5" rx="2.5" fill="${primary}"/>
      <polygon points="70,44 76,34 82,40 88,34 94,44" fill="${sec}" stroke="${TRIM_DARK}" stroke-width="1.2" stroke-linejoin="round"/>
    `;
  }
  if (head === 'halo_ring') {
    return baseSphere + `<ellipse cx="82" cy="34" rx="17" ry="3.8" fill="none" stroke="${sec}" stroke-width="2.0"/>`;
  }
  // crest (classic Annolin emerald crest)
  return baseSphere + `
    <path d="M 67 52 L 83 34 L 98 50 L 82 46 Z" fill="${primary}"/>
    <polygon points="78,42 83,46 78,50 73,46" fill="${sec}"/>
  `;
}

function renderCompactWeapon(weapon, primary, sec, metal) {
  if (weapon === 'tower_shield') {
    return `
      <polygon points="94,58 124,68 128,112 108,136 90,116" fill="${primary}" stroke="${sec}" stroke-width="2.4" stroke-linejoin="round"/>
      <line x1="109" y1="68" x2="109" y2="122" stroke="${sec}" stroke-width="2.4"/>
      <line x1="96" y1="92" x2="122" y2="92" stroke="${sec}" stroke-width="2.4"/>
    `;
  }
  if (weapon === 'warhammer') {
    return `
      <line x1="88" y1="118" x2="128" y2="68" stroke="${TRIM_DARK}" stroke-width="4.2" stroke-linecap="round"/>
      <rect x="112" y="50" width="32" height="22" rx="4" transform="rotate(-38 128 61)" fill="${metal}" stroke="${primary}" stroke-width="2.0"/>
      <line x1="120" y1="54" x2="136" y2="68" stroke="${sec}" stroke-width="3.2" stroke-linecap="round"/>
    `;
  }
  if (weapon === 'energy_lance' || weapon === 'needle_lance') {
    return `
      <polygon points="88,88 152,70 90,100" fill="${PAPER}" stroke="${primary}" stroke-width="2.0" stroke-linejoin="round"/>
      <line x1="92" y1="94" x2="146" y2="72" stroke="${sec}" stroke-width="2.2" stroke-linecap="round"/>
      ${weapon === 'energy_lance' ? `<circle cx="116" cy="84" r="6" fill="none" stroke="${sec}" stroke-width="2.0"/>` : ''}
    `;
  }
  if (weapon === 'rapier') {
    return `
      <circle cx="100" cy="96" r="8.5" fill="${PAPER}" stroke="${sec}" stroke-width="2.0"/>
      <line x1="104" y1="95" x2="152" y2="74" stroke="${TRIM_DARK}" stroke-width="2.6" stroke-linecap="round"/>
      <line x1="106" y1="94" x2="148" y2="76" stroke="${sec}" stroke-width="1.3" stroke-linecap="round"/>
    `;
  }
  if (weapon === 'cannon_gauntlet') {
    return `
      <rect x="102" y="70" width="26" height="40" rx="5" fill="${metal}" stroke="${sec}" stroke-width="2.0"/>
      <rect x="108" y="78" width="14" height="24" rx="3" fill="${sec}" opacity="0.88"/>
    `;
  }
  if (weapon === 'sight_rule') {
    return `
      <line x1="70" y1="102" x2="150" y2="74" stroke="${sec}" stroke-width="3.6" stroke-linecap="round"/>
      <circle cx="134" cy="80" r="8.5" fill="${PAPER}" fill-opacity="0.92" stroke="${primary}" stroke-width="1.8"/>
    `;
  }
  if (weapon === 'war_fan') {
    return `
      <path d="M 94 102 L 116 66 A 38 38 0 0 1 148 96 Z" fill="${primary}" stroke="${sec}" stroke-width="2.2" stroke-linejoin="round"/>
      <path d="M 94 102 L 126 76 M 94 102 L 138 86" stroke="${sec}" stroke-width="1.4"/>
    `;
  }
  if (weapon === 'bell_mallet') {
    return `
      <line x1="88" y1="116" x2="132" y2="66" stroke="${TRIM_DARK}" stroke-width="4.0" stroke-linecap="round"/>
      <rect x="118" y="50" width="22" height="28" rx="6" transform="rotate(-44 129 64)" fill="${metal}" stroke="${sec}" stroke-width="2.0"/>
    `;
  }
  if (weapon === 'hook_saber' || weapon === 'cleaver') {
    return `
      <path d="M 94 102 C 114 82 132 62 146 44 C 154 50 152 64 142 74 L 132 70 L 136 80 C 124 92 110 102 98 110 Z"
            fill="${PAPER}" stroke="${primary}" stroke-width="2.0" stroke-linejoin="round"/>
      <line x1="98" y1="100" x2="140" y2="56" stroke="${sec}" stroke-width="2.2" stroke-linecap="round"/>
    `;
  }
  if (weapon === 'twin_daggers') {
    return `
      <line x1="94" y1="96" x2="138" y2="72" stroke="${TRIM_DARK}" stroke-width="2.8" stroke-linecap="round"/>
      <line x1="96" y1="110" x2="134" y2="100" stroke="${sec}" stroke-width="2.6" stroke-linecap="round"/>
    `;
  }
  if (weapon === 'staff') {
    return `
      <line x1="92" y1="128" x2="134" y2="56" stroke="${TRIM_DARK}" stroke-width="3.6" stroke-linecap="round"/>
      <circle cx="136" cy="52" r="9.5" fill="${PAPER}" stroke="${sec}" stroke-width="2.2"/>
      <circle cx="136" cy="52" r="4.2" fill="${primary}"/>
    `;
  }
  // saber / wind_blade / flame_sword / boss_blade / inscribe_sword / prism_blade
  return `
    <polygon points="94,100 144,54 136,82 99,108" fill="${PAPER}" stroke="${primary}" stroke-width="2.0" stroke-linejoin="round"/>
    <line x1="98" y1="99" x2="138" y2="62" stroke="${sec}" stroke-width="2.2" stroke-linecap="round"/>
  `;
}

/**
 * Generate a clean, compact 160x160 5-bone SVG figurine for any character & palette.
 */
export function buildParametricCharacterSvg(ch, pal) {
  const profile = resolveCompactProfile(ch, pal);
  const primary = hexNumToCss(pal.primary, '#2A9D8F');
  const sec = hexNumToCss(pal.secondary, '#E6A238');
  const hi = hexNumToCss(pal.highlight, tintHex(primary, 0.78));
  const metal = hexNumToCss(pal.metal, '#7C6E60');
  const priDark = shadeHex(primary, 0.28);

  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${SVG_VIEW_W} ${SVG_VIEW_H}" data-foot="${SVG_FOOT_X},${SVG_FOOT_Y}">
  <g id="bone_back_hair" data-pivot="80,82">
    ${renderCompactHalo(profile.halo, primary, sec, hi)}
  </g>
  <g id="bone_cape_back" data-pivot="74,84">
    ${renderCompactCape(profile.cape, primary, priDark, sec)}
  </g>
  <g id="bone_torso" data-pivot="80,114">
    ${renderCompactTorso(profile.torso, primary, priDark, sec, hi, metal)}
  </g>
  <g id="bone_head" data-pivot="80,66">
    ${renderCompactHead(profile.head, primary, sec, metal)}
  </g>
  <g id="bone_weapon" data-pivot="94,102">
    ${renderCompactWeapon(profile.weapon, primary, sec, metal)}
  </g>
</svg>`;
}

/**
 * Resolve the cached RigAsset for a character.
 */
export function resolveCharacterRig(ch, pal) {
  const charId = ch?.id || 'unknown';
  const extUrl = getCharacterSpriteUrl(charId);
  if (extUrl) {
    const ext = preloadExternalSvgRig(extUrl);
    if (!ext.failed) {
      return ext;
    }
  }
  const cacheKey = `compact_v6:${charId}:${pal.primary}:${pal.secondary}:${pal.metal}`;
  if (RIG_CACHE.has(cacheKey)) {
    return RIG_CACHE.get(cacheKey);
  }
  const svgText = buildParametricCharacterSvg(ch, pal);
  return compileSvgRig(svgText, cacheKey, 2.5);
}

/**
 * Build a live animated PixiJS layered SVG rig container from a RigAsset.
 */
export function createSkeletalSvgRig(ch, pal, targetRadius = 38) {
  const rigRoot = new PIXI.Container();
  const boneMap = new Map();
  let mounted = false;

  // Match the original compact stage_actors.js footprint (~1.42 * r visual height from crown to base!)
  const desiredHeight = targetRadius * 1.44;
  let svgScale = desiredHeight / 104;

  const placeholderG = new PIXI.Graphics();
  const pri = typeof pal.primary === 'number' ? pal.primary : 0x2a9d8f;
  placeholderG.circle(0, -targetRadius * 0.08, targetRadius * 0.54)
    .fill({ color: pri, alpha: 0.22 });
  rigRoot.addChild(placeholderG);

  const mountBones = (asset) => {
    if (rigRoot.destroyed || mounted || !asset?.ready || !asset.bones?.length) return;
    mounted = true;
    placeholderG.visible = false;

    const footX = asset.footX ?? (asset.viewW * 0.5);
    const footY = asset.footY ?? (asset.viewH * 0.875);
    svgScale = desiredHeight / (asset.viewH * 0.65);
    const groundY = targetRadius * 0.63;

    for (const b of asset.bones) {
      const joint = new PIXI.Container();
      const baseX = (b.pivotX - footX) * svgScale;
      const baseY = groundY + (b.pivotY - footY) * svgScale;
      joint.position.set(baseX, baseY);

      const spr = new PIXI.Sprite(b.texture);
      spr.width = asset.viewW * svgScale;
      spr.height = asset.viewH * svgScale;
      spr.position.set(-b.pivotX * svgScale, -b.pivotY * svgScale);

      joint.addChild(spr);
      rigRoot.addChild(joint);
      boneMap.set(b.id, { joint, spr, baseX, baseY, pivotX: b.pivotX, pivotY: b.pivotY });
    }
  };

  const primaryAsset = resolveCharacterRig(ch, pal);
  primaryAsset.onReady((res) => {
    if (res.ready) {
      mountBones(res);
    } else if (res.failed && primaryAsset.key.startsWith('url:')) {
      const fallbackKey = `compact_v6:${ch?.id || 'unknown'}:${pal.primary}:${pal.secondary}:${pal.metal}`;
      const fallbackAsset = compileSvgRig(buildParametricCharacterSvg(ch, pal), fallbackKey, 2.5);
      fallbackAsset.onReady(mountBones);
    }
  });

  const phaseOffset = (hashStr(ch?.id || '') % 628) / 100;

  rigRoot.isReady = () => mounted;

  rigRoot.getBoneLocalPos = (boneId) => {
    const entry = boneMap.get(boneId);
    if (entry) {
      return { x: entry.joint.x, y: entry.joint.y };
    }
    const def = DEFAULT_BONE_PIVOTS[boneId] || [SVG_FOOT_X, 96];
    return {
      x: (def[0] - SVG_FOOT_X) * svgScale,
      y: targetRadius * 0.63 + (def[1] - SVG_FOOT_Y) * svgScale,
    };
  };

  rigRoot.animate = (time, motion, alive = true, animAmp = 1) => {
    if (!mounted) return;
    const m = motion || {};
    const lunge = m.lunge || 0;
    const recoil = m.recoil || 0;
    const t = time + phaseOffset;
    const amp = alive ? animAmp : 0;

    const breath = Math.sin(t * 2.8) * (targetRadius * 0.042) * amp;
    const flutter = Math.sin(t * 4.2) * 0.065 * amp;

    rigRoot.alpha = alive ? 1 : 0.42;

    const halo = boneMap.get('bone_back_hair');
    if (halo) {
      halo.joint.y = halo.baseY + breath * 0.5;
      halo.joint.rotation = Math.sin(t * 1.4) * 0.03 * amp;
    }

    const cape = boneMap.get('bone_cape_back');
    if (cape) {
      cape.joint.y = cape.baseY + breath * 0.9;
      cape.joint.rotation = flutter - lunge * 0.24 + recoil * 0.16;
    }

    const torso = boneMap.get('bone_torso');
    if (torso) {
      torso.joint.y = torso.baseY + breath + (alive ? 0 : 4 * svgScale);
      torso.joint.rotation = lunge * 0.11 - recoil * 0.14 + (alive ? 0 : -0.18);
    }

    const head = boneMap.get('bone_head');
    if (head) {
      head.joint.y = head.baseY + breath * 1.1 + (alive ? 0 : 5 * svgScale);
      head.joint.rotation = Math.sin(t * 2.1) * 0.025 * amp + lunge * 0.06 - recoil * 0.16 + (alive ? 0 : 0.2);
    }

    const weapon = boneMap.get('bone_weapon');
    if (weapon) {
      weapon.joint.y = weapon.baseY + breath - lunge * 2.8;
      weapon.joint.x = weapon.baseX + lunge * 4.5;
      weapon.joint.rotation = Math.sin(t * 2.8) * 0.045 * amp + lunge * 0.42 - recoil * 0.18;
    }

    const armBack = boneMap.get('bone_arm_back');
    if (armBack) {
      armBack.joint.y = armBack.baseY + breath * 0.9;
      armBack.joint.rotation = lunge * 0.18 - recoil * 0.14;
    }
  };

  return rigRoot;
}
