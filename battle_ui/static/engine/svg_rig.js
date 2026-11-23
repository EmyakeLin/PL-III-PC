/**
 * Layered Minimalist SVG Character Rig Engine & Compact Figurine Builder
 * for 《光点计划 III》.
 *
 * Art & Engineering Guarantees:
 *  - Standard canvas: `viewBox="0 0 160 160"`, grounded base `data-foot="80,136"`, facing RIGHT (+X).
 *  - Clean `<clipPath>` clipping on both torso & head so visors, straps, split robes, and armor plates
 *    NEVER bleed outside borders or break the crisp warm-white `#FFFDF7` silhouette edge.
 *  - Grounded hierarchical bone animation: torso breathes via subtle squash-and-stretch anchored at
 *    the floor base `(80, 136)` so the miniature NEVER floats or clips below the floor plinth, and
 *    head / cape / weapon inherit torso displacement so parts NEVER drift apart on lunge or recoil.
 *  - Supersamples each `<g id="bone_*">` once (2.5x HiDPI Canvas -> PIXI.Texture) and caches by key.
 */

import * as PIXI from '../vendor/pixi.min.mjs';

export const SVG_VIEW_W = 160;
export const SVG_VIEW_H = 160;
export const SVG_FOOT_X = 80;
export const SVG_FOOT_Y = 136;

export const BONE_ORDER = [
  'bone_back_hair',
  'bone_cape_back',
  'bone_arm_back',
  'bone_torso',
  'bone_head',
  'bone_weapon',
];

export const DEFAULT_BONE_PIVOTS = {
  bone_back_hair: [80, 86],
  bone_cape_back: [70, 82],
  bone_arm_back: [96, 98],
  bone_torso: [80, 136],
  bone_head: [80, 68],
  bone_weapon: [98, 102],
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
      asset.footY = viewH * 0.85;
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
          pivotY: viewH * 0.85,
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
 *  TIER 2: CLIP-PERFECT COMPACT MINIMALIST FIGURINE 160x160 SVG BUILDER
 *  Zero bleed, zero protruding visors, seamless shoulder-tucked capes,
 *  and crisp front-flank weapons for all roster & future characters.
 * ============================================================================ */

const COMPACT_PROFILES = {
  plan_b_annolin: { halo: 'soft', cape: 'wind_ribbons', torso: 'mantle', head: 'crest', weapon: 'wind_blade' },
  plan_b_heck: { halo: 'ember', cape: 'draped_cloak', torso: 'coat_diamond', head: 'flame_visor', weapon: 'flame_sword' },
  plan_b_heris: { halo: 'ember', cape: 'scarf', torso: 'tactical_strap', head: 'goggles', weapon: 'warhammer' },
  plan_b_li_ling: { halo: 'prism', cape: 'flowing_cape', torso: 'mantle', head: 'visor', weapon: 'energy_lance' },
  plan_b_sa: { halo: 'boss_sun', cape: 'royal_cloak', torso: 'boss_robe', head: 'crown_visor', weapon: 'boss_blade' },
  iron_qi_zheng: { halo: 'boss_sun', cape: 'royal_cloak', torso: 'armored', head: 'hex_crown', weapon: 'hook_saber' },
  char_iron_vanguard: { halo: 'soft', cape: 'none', torso: 'armored', head: 'hex_visor', weapon: 'tower_shield' },
  char_crimson_duelist: { halo: 'soft', cape: 'flowing_cape', torso: 'mantle', head: 'plume', weapon: 'rapier' },
  waa_lake: { halo: 'soft', cape: 'draped_cape', torso: 'tactical_strap', head: 'visor', weapon: 'saber' },
  waa_grolina: { halo: 'compass', cape: 'scarf', torso: 'tactical_strap', head: 'visor', weapon: 'needle_lance' },
  waa_erkes: { halo: 'prism', cape: 'none', torso: 'hex_reactor', head: 'hex_visor', weapon: 'cannon_gauntlet' },
  nova_lin_qiu: { halo: 'feather', cape: 'royal_cloak', torso: 'split_robe', head: 'feather_crest', weapon: 'inscribe_sword' },
  mistport_cen_yao: { halo: 'astrolabe', cape: 'draped_cape', torso: 'mantle', head: 'cap', weapon: 'sight_rule' },
  ember_wen_sheng: { halo: 'spotlight', cape: 'none', torso: 'theatre_sash', head: 'half_mask', weapon: 'war_fan' },
  bellfounder_que_ming: { halo: 'bell_rings', cape: 'royal_cloak', torso: 'coat_diamond', head: 'halo_ring', weapon: 'bell_mallet' },
  shipbreaker_shen_li: { halo: 'boss_sun', cape: 'draped_cloak', torso: 'armored', head: 'bandana_visor', weapon: 'cleaver' },
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
  const isBoss = ['BOSS', 'EMPOWERED_BOSS', 'EXTREME'].includes(ch?.rank);
  const halos = ['soft', 'astrolabe', 'ember', 'prism', 'compass'];
  const capes = ['wind_ribbons', 'draped_cape', 'flowing_cape', 'scarf', 'draped_cloak'];
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

function getTorsoPolygonPath(torso) {
  if (torso === 'hex_reactor') {
    return 'M 80 70 L 106 86 L 104 120 L 80 136 L 56 120 L 54 86 Z';
  }
  if (torso === 'armored') {
    return 'M 62 76 L 98 76 L 102 136 L 58 136 Z';
  }
  if (torso === 'tactical_strap' || torso === 'coat_diamond') {
    return 'M 64 76 L 97 78 L 100 136 L 60 136 Z';
  }
  if (torso === 'theatre_sash') {
    return 'M 80 70 L 102 94 L 106 136 L 54 136 L 58 94 Z';
  }
  // mantle / split_robe / boss_robe / kintsugi
  return 'M 80 70 L 101 94 L 98 136 L 62 136 L 59 94 Z';
}

function renderCompactHalo(halo, primary, sec, hi) {
  const base = `<circle cx="80" cy="86" r="42" fill="${hi}" fill-opacity="0.72" stroke="${primary}" stroke-width="1.3" stroke-opacity="0.30"/>`;
  if (halo === 'boss_sun') {
    return `
      <circle cx="80" cy="86" r="44" fill="${hi}" fill-opacity="0.72" stroke="${sec}" stroke-width="1.5" stroke-opacity="0.48"/>
      <polygon points="80,35 84,43 76,43" fill="${sec}" opacity="0.82"/>
      <polygon points="30,86 38,82 38,90" fill="${sec}" opacity="0.82"/>
      <polygon points="130,86 122,82 122,90" fill="${sec}" opacity="0.82"/>
    `;
  }
  if (halo === 'astrolabe' || halo === 'bell_rings') {
    return base + `
      <circle cx="80" cy="86" r="46" fill="none" stroke="${sec}" stroke-width="1.3" opacity="0.60"/>
      <path d="M 80 36 L 80 46 M 80 126 L 80 136 M 30 86 L 40 86 M 120 86 L 130 86" stroke="${sec}" stroke-width="1.5" opacity="0.75"/>
    `;
  }
  if (halo === 'ember') {
    return base + `
      <polygon points="39,72 44,63 47,74 41,79" fill="${sec}" opacity="0.85"/>
      <polygon points="33,102 39,93 42,104 35,109" fill="${primary}" opacity="0.68"/>
    `;
  }
  if (halo === 'spotlight') {
    return base + `<polygon points="80,38 120,132 40,132" fill="${sec}" opacity="0.18"/>`;
  }
  if (halo === 'medic_cross') {
    return base + `
      <rect x="74" y="60" width="12" height="34" rx="2" fill="${sec}" opacity="0.28"/>
      <rect x="63" y="71" width="34" height="12" rx="2" fill="${sec}" opacity="0.28"/>
    `;
  }
  if (halo === 'prism') {
    return base + `<polygon points="80,41 122,86 80,131 38,86" fill="none" stroke="${sec}" stroke-width="1.2" opacity="0.55"/>`;
  }
  return base;
}

function renderCompactCape(cape, primary, priDark, sec) {
  if (cape === 'none') return '';
  if (cape === 'wind_ribbons') {
    return `
      <path d="M 74 82 Q 46 66 20 78 Q 46 90 74 96 Z" fill="${sec}" opacity="0.74"/>
      <path d="M 74 94 Q 48 108 26 122 Q 54 122 76 108 Z" fill="${primary}" opacity="0.54"/>
    `;
  }
  if (cape === 'royal_cloak') {
    return `
      <path d="M 74 80 Q 44 88 28 132 Q 52 134 74 128 Z" fill="${priDark}" opacity="0.82"/>
      <path d="M 35 126 Q 54 127 72 123" fill="none" stroke="${sec}" stroke-width="2.2" stroke-linecap="round"/>
    `;
  }
  if (cape === 'draped_cape' || cape === 'draped_cloak') {
    const col = cape === 'draped_cloak' ? priDark : sec;
    return `
      <path d="M 72 80 Q 46 88 32 126 Q 52 130 72 120 Z" fill="${col}" opacity="0.80"/>
      <path d="M 39 120 Q 54 122 70 115" fill="none" stroke="${cape === 'draped_cloak' ? sec : PAPER}" stroke-width="1.6" stroke-linecap="round" opacity="0.75"/>
    `;
  }
  if (cape === 'flowing_cape') {
    return `
      <path d="M 74 80 Q 44 84 26 124 Q 50 130 74 124 Z" fill="${primary}" opacity="0.76"/>
      <path d="M 33 118 Q 52 122 72 118" fill="none" stroke="${sec}" stroke-width="1.8" stroke-linecap="round"/>
    `;
  }
  // scarf
  return `
    <path d="M 74 80 Q 48 84 28 102" fill="none" stroke="${sec}" stroke-width="5.2" stroke-linecap="round"/>
    <path d="M 72 88 Q 50 98 34 114" fill="none" stroke="${primary}" stroke-width="3.2" stroke-linecap="round" opacity="0.65"/>
  `;
}

function renderCompactTorso(torso, clipId, primary, priDark, sec, hi, metal) {
  const pathD = getTorsoPolygonPath(torso);
  let inner = '';
  if (torso === 'hex_reactor') {
    inner = `<polygon points="81,90 93,97 93,111 81,118 69,111 69,97" fill="${sec}" stroke="${PAPER}" stroke-width="1.5"/>`;
  } else if (torso === 'armored') {
    inner = `
      <polygon points="70,76 92,76 90,110 81,118 72,110" fill="${metal}" stroke="${PAPER}" stroke-width="1.3"/>
      <polygon points="81,84 86,95 81,106 76,95" fill="${sec}"/>
      <line x1="58" y1="126" x2="102" y2="126" stroke="${sec}" stroke-width="2.4"/>
    `;
  } else if (torso === 'tactical_strap') {
    inner = `
      <line x1="60" y1="78" x2="100" y2="124" stroke="${sec}" stroke-width="3.8"/>
      <circle cx="81" cy="100" r="7.2" fill="${PAPER}" stroke="${sec}" stroke-width="2.0"/>
      <circle cx="81" cy="100" r="3.0" fill="${sec}"/>
    `;
  } else if (torso === 'theatre_sash') {
    inner = `<polygon points="64,78 96,90 88,136 60,136" fill="${sec}" opacity="0.88"/>`;
  } else if (torso === 'split_robe' || torso === 'boss_robe') {
    inner = `
      <rect x="80" y="70" width="26" height="68" fill="${torso === 'split_robe' ? PAPER : priDark}" opacity="0.90"/>
      <line x1="58" y1="126" x2="102" y2="126" stroke="${sec}" stroke-width="2.2"/>
      <polygon points="80,94 86,102 80,110 74,102" fill="${sec}"/>
    `;
  } else if (torso === 'coat_diamond') {
    inner = `
      <polygon points="80,78 91,99 80,115 69,99" fill="${hi}" opacity="0.92"/>
      <polygon points="80,88 85,98 80,108 75,98" fill="${sec}"/>
      <line x1="58" y1="125" x2="102" y2="125" stroke="${sec}" stroke-width="2.2"/>
    `;
  } else {
    // mantle
    inner = `
      <polygon points="80,76 92,99 80,116 68,99" fill="${hi}" opacity="0.92"/>
      <polygon points="80,94 85,100 80,106 75,100" fill="${sec}"/>
      <line x1="58" y1="126" x2="102" y2="126" stroke="${sec}" stroke-width="2.2" opacity="0.88"/>
    `;
  }

  const pauldron = torso === 'armored'
    ? `<rect x="54" y="74" width="18" height="12" rx="4.5" fill="${metal}" stroke="${PAPER}" stroke-width="1.5"/>`
    : '';

  // Base fill + strictly clipped inner details + crisp unbroken outer paper border on top!
  return `
    <path d="${pathD}" fill="${primary}"/>
    <g clip-path="url(#${clipId})">${inner}</g>
    <path d="${pathD}" fill="none" stroke="${PAPER}" stroke-width="2.2" stroke-linejoin="round"/>
    ${pauldron}
  `;
}

function renderCompactHead(head, headClipId, primary, sec, metal) {
  const isHex = head === 'hex_visor' || head === 'hex_crown' || head === 'hex_plain';
  const basePath = isHex
    ? 'M 80 42 L 92 49 L 92 63 L 80 70 L 68 63 L 68 49 Z'
    : null;
  const baseFill = isHex
    ? `<path d="${basePath}" fill="${PAPER}"/>`
    : `<circle cx="80" cy="56" r="13.5" fill="${PAPER}"/>`;
  const baseStroke = isHex
    ? `<path d="${basePath}" fill="none" stroke="${TRIM_DARK}" stroke-width="1.8" stroke-linejoin="round"/>`
    : `<circle cx="80" cy="56" r="13.5" fill="none" stroke="${TRIM_DARK}" stroke-width="1.8"/>`;

  // Clipped interior details (NEVER poke outside the head circle/hex!)
  let inside = '';
  if (head === 'visor' || head === 'flame_visor' || head === 'bandana_visor' || head === 'crown_visor' || head === 'hex_visor' || head === 'hex_crown') {
    const vCol = (head === 'crown_visor' || head === 'hex_visor' || head === 'hex_crown' || head === 'bandana_visor') ? primary : sec;
    inside += `<rect x="76" y="52.5" width="20" height="6" rx="2.5" fill="${vCol}"/>`;
    if (head === 'bandana_visor') {
      inside += `<path d="M 65 48 Q 80 44 95 48 L 95 52 Q 80 48 65 52 Z" fill="${sec}"/>`;
    }
  } else if (head === 'half_mask') {
    inside += `<polygon points="80,41 96,46 96,67 80,62" fill="${sec}"/>`;
  } else if (head === 'goggles') {
    inside += `
      <rect x="66" y="50" width="28" height="4" fill="${TRIM_DARK}" opacity="0.75"/>
      <circle cx="79" cy="52" r="4.4" fill="${metal}" stroke="${TRIM_DARK}" stroke-width="1.3"/>
      <circle cx="79" cy="52" r="2.3" fill="${sec}"/>
      <circle cx="89" cy="52" r="4.0" fill="${metal}" stroke="${TRIM_DARK}" stroke-width="1.3"/>
      <circle cx="89" cy="52" r="2.1" fill="${sec}"/>
    `;
  } else if (head === 'halo_mirror') {
    inside += `<circle cx="84" cy="56" r="5.0" fill="none" stroke="${sec}" stroke-width="1.5"/>`;
  }

  // External crown/crest accents seated cleanly on the top arc
  let crown = '';
  if (head === 'crest') {
    crown = `
      <path d="M 67 51 Q 78 36 93 49 Q 81 45 67 51 Z" fill="${primary}"/>
      <polygon points="78,43 82,46.5 78,50 74,46.5" fill="${sec}"/>
    `;
  } else if (head === 'flame_visor') {
    crown = `<path d="M 69 47 L 75 35 L 82 43 L 90 36 L 91 47 Q 80 44 69 47 Z" fill="${primary}"/>`;
  } else if (head === 'plume') {
    crown = `<path d="M 74 44 Q 54 32 45 50" fill="none" stroke="${sec}" stroke-width="3.0" stroke-linecap="round"/>`;
  } else if (head === 'hood') {
    crown = `<path d="M 65 56 L 76 37 L 91 48 Q 78 46 65 56 Z" fill="${primary}"/>`;
  } else if (head === 'cap') {
    crown = `
      <path d="M 67 48 Q 80 37 93 47 Z" fill="${primary}" stroke="${TRIM_DARK}" stroke-width="1.3"/>
      <line x1="84" y1="47" x2="99" y2="50" stroke="${TRIM_DARK}" stroke-width="2.2" stroke-linecap="round"/>
      <circle cx="80" cy="44" r="2.3" fill="${sec}"/>
    `;
  } else if (head === 'crown_visor') {
    crown = `<polygon points="70,45 75,35 80,41 85,35 90,45" fill="${sec}" stroke="${TRIM_DARK}" stroke-width="1.2" stroke-linejoin="round"/>`;
  } else if (head === 'hex_crown') {
    crown = `<polygon points="80,33 85,43 80,48 75,43" fill="${sec}"/>`;
  } else if (head === 'halo_ring' || head === 'halo_mirror') {
    crown = `<ellipse cx="80" cy="36" rx="16" ry="3.6" fill="none" stroke="${sec}" stroke-width="2.0"/>`;
  }

  return `
    ${baseFill}
    ${inside ? `<g clip-path="url(#${headClipId})">${inside}</g>` : ''}
    ${baseStroke}
    ${crown}
  `;
}

function renderCompactWeapon(weapon, primary, sec, metal) {
  // All weapons cleanly positioned on the front flank (x >= 94) so they NEVER slice across the chest crest!
  if (weapon === 'tower_shield') {
    return `
      <polygon points="98,68 124,76 127,114 110,134 95,116" fill="${primary}" stroke="${sec}" stroke-width="2.2" stroke-linejoin="round"/>
      <line x1="111" y1="77" x2="111" y2="122" stroke="${sec}" stroke-width="2.2"/>
      <line x1="100" y1="98" x2="122" y2="98" stroke="${sec}" stroke-width="2.2"/>
    `;
  }
  if (weapon === 'warhammer') {
    return `
      <line x1="96" y1="114" x2="128" y2="74" stroke="${TRIM_DARK}" stroke-width="4.0" stroke-linecap="round"/>
      <rect x="112" y="54" width="30" height="20" rx="4" transform="rotate(-38 127 64)" fill="${metal}" stroke="${primary}" stroke-width="2.0"/>
      <line x1="120" y1="58" x2="135" y2="70" stroke="${sec}" stroke-width="3.2" stroke-linecap="round"/>
    `;
  }
  if (weapon === 'energy_lance' || weapon === 'needle_lance') {
    return `
      <polygon points="95,94 150,74 96,105" fill="${PAPER}" stroke="${primary}" stroke-width="1.9" stroke-linejoin="round"/>
      <line x1="98" y1="99" x2="144" y2="76" stroke="${sec}" stroke-width="2.0" stroke-linecap="round"/>
      ${weapon === 'energy_lance' ? `<circle cx="118" cy="89" r="5.5" fill="none" stroke="${sec}" stroke-width="1.9"/>` : ''}
    `;
  }
  if (weapon === 'rapier') {
    return `
      <circle cx="101" cy="99" r="7.5" fill="${PAPER}" stroke="${sec}" stroke-width="1.9"/>
      <line x1="105" y1="98" x2="149" y2="78" stroke="${TRIM_DARK}" stroke-width="2.4" stroke-linecap="round"/>
      <line x1="107" y1="97" x2="145" y2="80" stroke="${sec}" stroke-width="1.2" stroke-linecap="round"/>
    `;
  }
  if (weapon === 'cannon_gauntlet') {
    return `
      <rect x="102" y="76" width="24" height="36" rx="5" fill="${metal}" stroke="${sec}" stroke-width="1.9"/>
      <rect x="107" y="83" width="14" height="22" rx="3" fill="${sec}" opacity="0.88"/>
    `;
  }
  if (weapon === 'sight_rule') {
    return `
      <line x1="94" y1="104" x2="148" y2="80" stroke="${sec}" stroke-width="3.4" stroke-linecap="round"/>
      <circle cx="132" cy="87" r="7.8" fill="${PAPER}" fill-opacity="0.92" stroke="${primary}" stroke-width="1.8"/>
    `;
  }
  if (weapon === 'war_fan') {
    return `
      <path d="M 97 104 L 118 70 A 35 35 0 0 1 146 98 Z" fill="${primary}" stroke="${sec}" stroke-width="2.0" stroke-linejoin="round"/>
      <path d="M 97 104 L 126 80 M 97 104 L 136 89" stroke="${sec}" stroke-width="1.3"/>
    `;
  }
  if (weapon === 'bell_mallet') {
    return `
      <line x1="96" y1="114" x2="130" y2="72" stroke="${TRIM_DARK}" stroke-width="3.8" stroke-linecap="round"/>
      <rect x="116" y="54" width="20" height="26" rx="6" transform="rotate(-42 126 67)" fill="${metal}" stroke="${sec}" stroke-width="1.9"/>
    `;
  }
  if (weapon === 'hook_saber' || weapon === 'cleaver') {
    return `
      <path d="M 98 104 C 116 86 132 68 144 50 C 151 56 150 68 140 78 L 132 74 L 135 83 C 124 94 112 103 101 110 Z"
            fill="${PAPER}" stroke="${primary}" stroke-width="1.9" stroke-linejoin="round"/>
      <line x1="102" y1="102" x2="139" y2="62" stroke="${sec}" stroke-width="2.1" stroke-linecap="round"/>
    `;
  }
  if (weapon === 'twin_daggers') {
    return `
      <line x1="97" y1="98" x2="138" y2="76" stroke="${TRIM_DARK}" stroke-width="2.6" stroke-linecap="round"/>
      <line x1="99" y1="110" x2="134" y2="101" stroke="${sec}" stroke-width="2.4" stroke-linecap="round"/>
    `;
  }
  if (weapon === 'staff') {
    return `
      <line x1="98" y1="126" x2="132" y2="60" stroke="${TRIM_DARK}" stroke-width="3.4" stroke-linecap="round"/>
      <circle cx="134" cy="56" r="8.8" fill="${PAPER}" stroke="${sec}" stroke-width="2.0"/>
      <circle cx="134" cy="56" r="3.8" fill="${primary}"/>
    `;
  }
  // saber / wind_blade / flame_sword / boss_blade / inscribe_sword / prism_blade
  return `
    <polygon points="97,102 144,58 136,84 102,109" fill="${PAPER}" stroke="${primary}" stroke-width="1.9" stroke-linejoin="round"/>
    <line x1="101" y1="101" x2="138" y2="66" stroke="${sec}" stroke-width="2.1" stroke-linecap="round"/>
  `;
}

/**
 * Generate a clip-perfect, compact 160x160 5-bone SVG figurine for any character & palette.
 */
export function buildParametricCharacterSvg(ch, pal) {
  const profile = resolveCompactProfile(ch, pal);
  const primary = hexNumToCss(pal.primary, '#2A9D8F');
  const sec = hexNumToCss(pal.secondary, '#E6A238');
  const hi = hexNumToCss(pal.highlight, tintHex(primary, 0.78));
  const metal = hexNumToCss(pal.metal, '#7C6E60');
  const priDark = shadeHex(primary, 0.28);

  const safeId = `p_${hashStr(`${ch?.id || 'c'}_${pal.primary}`).toString(36)}`;
  const torsoClip = `${safeId}_tc`;
  const headClip = `${safeId}_hc`;
  const torsoPath = getTorsoPolygonPath(profile.torso);
  const isHex = profile.head === 'hex_visor' || profile.head === 'hex_crown' || profile.head === 'hex_plain';
  const headClipShape = isHex
    ? '<path d="M 80 42 L 92 49 L 92 63 L 80 70 L 68 63 L 68 49 Z"/>'
    : '<circle cx="80" cy="56" r="13.5"/>';

  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${SVG_VIEW_W} ${SVG_VIEW_H}" data-foot="${SVG_FOOT_X},${SVG_FOOT_Y}">
  <defs>
    <clipPath id="${torsoClip}"><path d="${torsoPath}"/></clipPath>
    <clipPath id="${headClip}">${headClipShape}</clipPath>
  </defs>
  <g id="bone_back_hair" data-pivot="80,86">
    ${renderCompactHalo(profile.halo, primary, sec, hi)}
  </g>
  <g id="bone_cape_back" data-pivot="70,82">
    ${renderCompactCape(profile.cape, primary, priDark, sec)}
  </g>
  <g id="bone_torso" data-pivot="80,136">
    ${renderCompactTorso(profile.torso, torsoClip, primary, priDark, sec, hi, metal)}
  </g>
  <g id="bone_head" data-pivot="80,68">
    ${renderCompactHead(profile.head, headClip, primary, sec, metal)}
  </g>
  <g id="bone_weapon" data-pivot="98,102">
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
  const cacheKey = `compact_v7:${charId}:${pal.primary}:${pal.secondary}:${pal.metal}`;
  if (RIG_CACHE.has(cacheKey)) {
    return RIG_CACHE.get(cacheKey);
  }
  const svgText = buildParametricCharacterSvg(ch, pal);
  return compileSvgRig(svgText, cacheKey, 2.5);
}

/**
 * Build a live animated PixiJS layered SVG rig container with grounded hierarchical bone motion.
 */
export function createSkeletalSvgRig(ch, pal, targetRadius = 38) {
  const rigRoot = new PIXI.Container();
  const boneMap = new Map();
  let mounted = false;

  // Compact footprint matching the original stage_actors.js miniature scale
  const desiredHeight = targetRadius * 1.42;
  let svgScale = desiredHeight / 100;

  const placeholderG = new PIXI.Graphics();
  const pri = typeof pal.primary === 'number' ? pal.primary : 0x2a9d8f;
  placeholderG.circle(0, -targetRadius * 0.08, targetRadius * 0.50)
    .fill({ color: pri, alpha: 0.20 });
  rigRoot.addChild(placeholderG);

  const mountBones = (asset) => {
    if (rigRoot.destroyed || mounted || !asset?.ready || !asset.bones?.length) return;
    mounted = true;
    placeholderG.visible = false;

    const footX = asset.footX ?? (asset.viewW * 0.5);
    const footY = asset.footY ?? (asset.viewH * 0.85);
    svgScale = desiredHeight / (asset.viewH * 0.625);
    const groundY = targetRadius * 0.62;

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
      const fallbackKey = `compact_v7:${ch?.id || 'unknown'}:${pal.primary}:${pal.secondary}:${pal.metal}`;
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
      y: targetRadius * 0.62 + (def[1] - SVG_FOOT_Y) * svgScale,
    };
  };

  rigRoot.animate = (time, motion, alive = true, animAmp = 1) => {
    if (!mounted) return;
    const m = motion || {};
    const lunge = m.lunge || 0;
    const recoil = m.recoil || 0;
    const t = time + phaseOffset;
    const amp = alive ? animAmp : 0;

    // Grounded hierarchical kinematics:
    // Torso stays firmly planted at its base (y = 136) and breathes via gentle squash-and-stretch,
    // while head, cape, and weapon rigidly follow the torso's top lean so parts NEVER drift apart!
    const breathWave = Math.sin(t * 2.8) * amp;
    const scaleY = 1 + breathWave * 0.028;
    const scaleX = 1 - breathWave * 0.014;
    const torsoRot = lunge * 0.11 - recoil * 0.14 + (alive ? 0 : -0.18);
    const flutter = Math.sin(t * 4.2) * 0.055 * amp;

    rigRoot.alpha = alive ? 1 : 0.42;

    const torso = boneMap.get('bone_torso');
    const torsoBaseY = torso ? torso.baseY : (targetRadius * 0.62);
    const torsoBaseX = torso ? torso.baseX : 0;

    // Helper: transform any upper-body joint by the torso's grounded base pivot so it stays 100% locked
    const followTorso = (entry) => {
      const dx = (entry.baseX - torsoBaseX) * scaleX;
      const dy = (entry.baseY - torsoBaseY) * scaleY;
      const cosR = Math.cos(torsoRot);
      const sinR = Math.sin(torsoRot);
      return {
        x: torsoBaseX + dx * cosR - dy * sinR,
        y: torsoBaseY + dx * sinR + dy * cosR,
      };
    };

    if (torso) {
      torso.joint.position.set(torsoBaseX, torsoBaseY);
      torso.joint.scale.set(scaleX, scaleY);
      torso.joint.rotation = torsoRot;
    }

    const halo = boneMap.get('bone_back_hair');
    if (halo) {
      halo.joint.position.set(halo.baseX, halo.baseY - breathWave * (targetRadius * 0.025));
      halo.joint.rotation = Math.sin(t * 1.4) * 0.025 * amp;
    }

    const cape = boneMap.get('bone_cape_back');
    if (cape) {
      const p = followTorso(cape);
      cape.joint.position.set(p.x, p.y);
      cape.joint.rotation = torsoRot + flutter - lunge * 0.22 + recoil * 0.14;
    }

    const head = boneMap.get('bone_head');
    if (head) {
      const p = followTorso(head);
      head.joint.position.set(p.x, p.y);
      head.joint.rotation = torsoRot + Math.sin(t * 2.1) * 0.02 * amp + lunge * 0.04 - recoil * 0.10 + (alive ? 0 : 0.16);
    }

    const weapon = boneMap.get('bone_weapon');
    if (weapon) {
      const p = followTorso(weapon);
      weapon.joint.position.set(p.x + lunge * 3.8, p.y - lunge * 2.2);
      weapon.joint.rotation = torsoRot + Math.sin(t * 2.8) * 0.04 * amp + lunge * 0.36 - recoil * 0.14;
    }

    const armBack = boneMap.get('bone_arm_back');
    if (armBack) {
      const p = followTorso(armBack);
      armBack.joint.position.set(p.x, p.y);
      armBack.joint.rotation = torsoRot + lunge * 0.14 - recoil * 0.12;
    }
  };

  return rigRoot;
}
