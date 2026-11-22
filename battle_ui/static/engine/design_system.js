/**
 * Canonical Editorial Design System for 《光点计划 III》 (Dice / Skills / Rich Verbatim Entries).
 * Single Source of Truth shared by Hand, Board, Combat Showdown, Draw-Select, Roster, Dossier & Codex.
 *
 * CORE PRINCIPLES:
 *  1. 90% Clean Sunlit Paper & Crisp Ink + 10% Surgical Accent Color (ZERO nested-border clutter, ZERO pastel soup)
 *  2. Zero-Hover Direct Readability: necessary card/dice/entry text is directly readable at rest
 *  3. 100% VERBATIM Rule Fidelity: ZERO paraphrasing, ZERO added/removed characters, ZERO "Lv.X", ZERO "无附加词条"
 *  4. Strictly Bright Daylight Palette: ZERO black (max RGB >= 40), ZERO blue-purple
 */

import * as PIXI from '../vendor/pixi.min.mjs';

export const FONT_UI = '"Microsoft YaHei", "PingFang SC", "Segoe UI", system-ui, sans-serif';
export const FONT_NUM = '"Segoe UI", "DIN Alternate", "Consolas", sans-serif';

export const INK = {
  primary: 0x3b322a,
  strong: 0x2c241d,
  secondary: 0x6e6255,
  muted: 0x998d7e,
  line: 0xddd4c5,
  hairline: 0xeae2d4,
  shadow: 0xb5a894,
  paper: 0xfffdf8,
  paperSoft: 0xf8f4ec,
  paperTint: 0xf2ece0,
  gold: 0xc98216,
  goldDeep: 0x9e5e0e,
  goldBg: 0xfdf5e2,
};

export const SIDE_THEME = {
  1: {
    name: '玩家一',
    accent: 0x1a825e,
    accentHex: '#1a825e',
    softBg: 0xeef7f3,
    border: 0x52b08d,
    warmTint: 0xf5faf7,
  },
  2: {
    name: '玩家二',
    accent: 0xc8452e,
    accentHex: '#c8452e',
    softBg: 0xfcf0ed,
    border: 0xe08270,
    warmTint: 0xfef7f5,
  },
};

export const HP_BAR_COLOR = 0xd44638;

export const ATTACK_DIE_COLOR = 0xd1382e;
export const ATTACK_DIE_BG = 0xfdece9;
export const DEFENSE_DIE_COLOR = 0x2478cc;
export const DEFENSE_DIE_BG = 0xeaf4fd;

export function parseHexColor(val, fallback = 0x1a825e) {
  if (typeof val === 'number' && Number.isFinite(val)) return Math.floor(val) & 0xffffff;
  if (typeof val === 'string') {
    const clean = val.trim().replace(/^#|^0x/i, '');
    if (/^[0-9a-f]{6}$/i.test(clean)) return parseInt(clean, 16) & 0xffffff;
  }
  return fallback;
}

export function hexToCss(hex) {
  return `#${(Math.floor(hex) & 0xffffff).toString(16).padStart(6, '0')}`;
}

export function mixHexColors(c1, c2, t) {
  const k = Math.max(0, Math.min(1, t));
  const r1 = (c1 >> 16) & 255;
  const g1 = (c1 >> 8) & 255;
  const b1 = c1 & 255;
  const r2 = (c2 >> 16) & 255;
  const g2 = (c2 >> 8) & 255;
  const b2 = c2 & 255;
  const r = Math.round(r1 + (r2 - r1) * k);
  const g = Math.round(g1 + (g2 - g1) * k);
  const b = Math.round(b1 + (b2 - b1) * k);
  return (r << 16) | (g << 8) | b;
}

export function deriveCardPalette(accentColor = null, fallbackSide = 1) {
  const fallback = SIDE_THEME[fallbackSide] || SIDE_THEME[1];
  if (accentColor === null || accentColor === undefined) {
    return {
      accent: fallback.accent,
      accentHex: fallback.accentHex,
      border: fallback.border,
      softBg: fallback.softBg,
      warmTint: fallback.warmTint,
    };
  }
  const accent = parseHexColor(accentColor, fallback.accent);
  return {
    accent,
    accentHex: hexToCss(accent),
    border: mixHexColors(accent, INK.paper, 0.34),
    softBg: mixHexColors(accent, INK.paper, 0.88),
    warmTint: mixHexColors(accent, INK.paper, 0.93),
  };
}

export const DIE_STYLE = {
  slash:  { label: '斩击', kind: 'attack',  frame: 'hex',    color: ATTACK_DIE_COLOR,  bg: ATTACK_DIE_BG,  hex: '#d1382e' },
  pierce: { label: '突刺', kind: 'attack',  frame: 'hex',    color: ATTACK_DIE_COLOR,  bg: ATTACK_DIE_BG,  hex: '#d1382e' },
  blunt:  { label: '打击', kind: 'attack',  frame: 'hex',    color: ATTACK_DIE_COLOR,  bg: ATTACK_DIE_BG,  hex: '#d1382e' },
  block:  { label: '招架', kind: 'defense', frame: 'square', color: DEFENSE_DIE_COLOR, bg: DEFENSE_DIE_BG, hex: '#2478cc' },
  evade:  { label: '闪避', kind: 'defense', frame: 'square', color: DEFENSE_DIE_COLOR, bg: DEFENSE_DIE_BG, hex: '#2478cc' },
  blank:  { label: '空白', kind: 'blank',   frame: 'square', color: 0x8a7f71,          bg: 0xf6f2ea,       hex: '#8a7f71' },
};

export const DAMAGE_GRADE_STYLE = {
  normal:  { label: '普通伤害', short: '普通', color: 0xc93e2b, bg: 0xfdf0ed, border: 0xe5a296 },
  pierce:  { label: '穿甲伤害', short: '穿甲', color: 0xbf6c0e, bg: 0xfef5e3, border: 0xe0b265 },
  concept: { label: '超穿甲伤害', short: '超穿甲', color: 0xb02e57, bg: 0xfceef3, border: 0xd98aa3 },
};

export const SHIELD_STYLE = {
  normal:     { label: '普通护盾', short: '普通', color: 0x268a6e, bg: 0xebf7f3, hex: '#268a6e' },
  reinforced: { label: '强化护盾', short: '强化', color: 0xc97e12, bg: 0xfef5e2, hex: '#c97e12' },
  concept:    { label: '概念护盾', short: '概念', color: 0xbd3e63, bg: 0xfcedf2, hex: '#bd3e63' },
};

export const STATUS_COLORS = {
  强壮: 0xc96516,
  虚弱: 0x877764,
  迅捷: 0x1a8a68,
  束缚: 0x875f36,
  烧伤: 0xd13f20,
  裂血: 0xba2334,
  呼吸: 0x1f8c73,
  失衡: 0xb58714,
  致命失衡: 0xcc1f36,
  充能: 0x228a5c,
  纯能: 0x4b9930,
  能源: 0x6b911e,
  能源封印: 0x826b58,
  涡流: 0x17856b,
  校准: 0xbd7412,
  置卡机会: 0xb88116,
  换卡机会: 0x22856a,
  骰子等级降低: 0xa65044,
  骰级免疫: 0x2d8c57,
  凝聚: 0x248277,
  余烬: 0xd96226,
};

// Dynamic pack-provided status visuals (`status_visuals` from snapshot):
// name -> { color?: "#...", icon_url?: "/status_icons/...", icon_svg?: "<svg...>", icon_path?: [...], icon_symbol?: "..." }
const CUSTOM_STATUS_VISUALS = new Map();
const STATUS_ICON_TEXTURE_CACHE = new Map();

function _rasterizeStatusSvg(svgMarkup, cacheKey) {
  if (STATUS_ICON_TEXTURE_CACHE.has(cacheKey)) {
    return STATUS_ICON_TEXTURE_CACHE.get(cacheKey);
  }
  const entry = {
    ready: false,
    failed: false,
    texture: null,
    listeners: new Set(),
    onReady(fn) {
      if (this.ready || this.failed) fn(this);
      else this.listeners.add(fn);
    },
  };
  STATUS_ICON_TEXTURE_CACHE.set(cacheKey, entry);

  const notify = () => {
    for (const fn of entry.listeners) {
      try { fn(entry); } catch (_) { /* ignore */ }
    }
    entry.listeners.clear();
  };

  if (typeof Image === 'undefined' || typeof document === 'undefined') {
    entry.failed = true;
    notify();
    return entry;
  }

  const img = new Image();
  img.decoding = 'async';
  img.onload = () => {
    try {
      const sz = 72; // 3x HiDPI crisp status icon
      const canvas = document.createElement('canvas');
      canvas.width = sz;
      canvas.height = sz;
      const ctx = canvas.getContext('2d');
      ctx.imageSmoothingEnabled = true;
      ctx.imageSmoothingQuality = 'high';
      ctx.clearRect(0, 0, sz, sz);
      ctx.drawImage(img, 0, 0, sz, sz);
      const tex = PIXI.Texture.from(canvas);
      if (tex?.source) tex.source.scaleMode = 'linear';
      entry.texture = tex;
      entry.ready = true;
      notify();
    } catch (_) {
      entry.failed = true;
      notify();
    }
  };
  img.onerror = () => {
    entry.failed = true;
    notify();
  };
  img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svgMarkup)}`;
  return entry;
}

function _preloadStatusIconUrl(url) {
  const key = `url:${url}`;
  if (STATUS_ICON_TEXTURE_CACHE.has(key)) {
    return STATUS_ICON_TEXTURE_CACHE.get(key);
  }
  const entry = {
    ready: false,
    failed: false,
    texture: null,
    listeners: new Set(),
    onReady(fn) {
      if (this.ready || this.failed) fn(this);
      else this.listeners.add(fn);
    },
  };
  STATUS_ICON_TEXTURE_CACHE.set(key, entry);

  const notify = () => {
    for (const fn of entry.listeners) {
      try { fn(entry); } catch (_) { /* ignore */ }
    }
    entry.listeners.clear();
  };

  if (typeof fetch !== 'function') {
    entry.failed = true;
    notify();
    return entry;
  }

  fetch(url, { cache: 'no-store' })
    .then((res) => {
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.text();
    })
    .then((svgText) => {
      const compiled = _rasterizeStatusSvg(svgText, `svg_url:${url}`);
      compiled.onReady((done) => {
        entry.ready = done.ready;
        entry.failed = done.failed;
        entry.texture = done.texture;
        notify();
      });
    })
    .catch(() => {
      entry.failed = true;
      notify();
    });

  return entry;
}

export function setStatusVisuals(visualsMap) {
  if (!visualsMap || typeof visualsMap !== 'object') return;
  for (const [name, spec] of Object.entries(visualsMap)) {
    if (!name || !spec || typeof spec !== 'object') continue;
    CUSTOM_STATUS_VISUALS.set(name, spec);
    if (spec.color) {
      STATUS_COLORS[name] = parseHexColor(spec.color, STATUS_COLORS[name] || INK.secondary);
    }
    if (spec.icon_url) {
      _preloadStatusIconUrl(spec.icon_url);
    } else if (spec.icon_svg) {
      _rasterizeStatusSvg(spec.icon_svg, `inline:${name}:${spec.icon_svg.length}`);
    }
  }
}

export function getStatusColor(name, fallback = INK.secondary) {
  const custom = name ? CUSTOM_STATUS_VISUALS.get(name) : null;
  if (custom?.color) return parseHexColor(custom.color, STATUS_COLORS[name] || fallback);
  return STATUS_COLORS[name] || fallback;
}

export const TRAIT_STYLE = {
  range:           { color: 0xb87010, bg: 0xfef6e6, border: 0xe3c386 },
  ignore_range:    { color: 0x61733a, bg: 0xf4f7ec, border: 0xb8c499 },
  pre_reveal:      { color: 0xbf5224, bg: 0xfef2ec, border: 0xe5ad93 },
  anytime:         { color: 0x177d6b, bg: 0xedf8f5, border: 0x8bc9ba },
  uninterceptable: { color: 0xb03547, bg: 0xfdf0f2, border: 0xdfa0aa },
  out_of_combat:   { color: 0x736453, bg: 0xf5f0e8, border: 0xc9beae },
};

export const TIMING_STYLE = {
  skill: { color: 0x167353, wash: 0xe6f5ee, rule: 0x5fb392 },
  clash: { color: 0xad6b10, wash: 0xfdf2dc, rule: 0xd9a64e },
  hit:   { color: 0xbd3728, wash: 0xfdece9, rule: 0xde877c },
  turn:  { color: 0x855518, wash: 0xf8efe0, rule: 0xc49c66 },
};

export const RANK_COLOR = {
  NORMAL: 0x7a6d5e,
  ELITE: 0x1a825e,
  BOSS: 0xc2641a,
  EMPOWERED_BOSS: 0xc93e2b,
};

export const LEVEL_MAX = { 1: 4, 2: 6, 3: 8, 4: 12, 5: 16, 6: 20 };
export const RANK_LABEL = {
  NORMAL: '常人',
  ELITE: '精英',
  BOSS: '首领',
  EMPOWERED_BOSS: '强化首领',
};
export const RANGE_LABELS = ['', '普通远程', '强化远程', '极限远程'];

export const OFFICIAL_STATUS_RULES = {
  强壮: '每层使持有者的非空白骰最终点数 +1。进攻骰、招架和闪避均适用。生效回合结束时清除。',
  虚弱: '每层使持有者的非空白骰最终点数 −1。进攻骰、招架和闪避均适用。生效回合结束时清除。',
  迅捷: '每层使持有角色的速度 +1。先修正各角色速度，再计算阵营速度。生效回合结束时清除。',
  束缚: '每层使持有角色的速度 −1。先修正各角色速度，再计算阵营速度。生效回合结束时清除。',
  烧伤: '回合末持有至少 4 层烧伤时自动结算一次。引燃可立即结算任意正层数的烧伤。按触发时的层数，每满 4 层算一组。承受等于组数的普通伤害（原始伤害至多 3 点），随后减少「组数 + 2」层，最低到 0。减伤或护盾全额抵挡时照常扣层。',
  裂血: '上限 9 层。持有至少 3 层时，每场实际开始结算的交锋开始时承受 1 点穿甲伤害。达到 6 层后进入爆发，直到归零或被解除；爆发期间每被一个伤害部分命中且仍存活，额外承受 1 点穿甲伤害并减少 2 层。',
  呼吸: '上限 6 层。持有者的进攻骰命中时掷 1 枚六面骰，结果不高于层数则触发「暴击时」词条。',
  失衡: '上限 20 层。被「失衡爆发」词条命中时掷 1 枚二十面骰；结果不高于现有层数则获得 1 层致命失衡并减少 5 层失衡，否则增加 2 层失衡。',
  致命失衡: '持有至少 1 层时，所受伤害倍率为 ×2（多层仍为 ×2）。实际受到伤害后减少 1 层，每一轮用骰至多以此减少 1 层。',
  能源: '无通用层数上限。按明确点名「能源」的词条积累或使用，与充能、纯能分别记账。',
  置卡机会: '将持有者的一张手牌置入友方第一个仍可结算的空常规交锋（仍占角色本回合常规交锋额度）。回合结束时清除未使用的次数。',
  换卡机会: '在自身一项技能即将开始使用、尚未付款时，以同一角色的另一张手牌替换它。回合结束时清除未使用的次数。',
  骰子等级降低: '每层使持有者的骰子下降 1 级，仍遵守骰级下限。生效回合结束时清除。',
  骰级免疫: '使有效骰级等于该骰的印刷等级，升级和降级均不能改变它。生效回合结束时清除。',
};

const TIMING_PREFIXES = [
  { phrase: '本技能发动后', group: 'skill' },
  { phrase: '下骰使用时', group: 'skill' },
  { phrase: '使用时', group: 'skill' },
  { phrase: '使用后', group: 'skill' },
  { phrase: '拼点胜利时', group: 'clash' },
  { phrase: '拼点失败时', group: 'clash' },
  { phrase: '拼点平局时', group: 'clash' },
  { phrase: '跳过拼点时', group: 'clash' },
  { phrase: '若首骰命中', group: 'hit' },
  { phrase: '命中目标', group: 'hit' },
  { phrase: '命中前', group: 'hit' },
  { phrase: '命中时', group: 'hit' },
  { phrase: '暴击时', group: 'hit' },
  { phrase: '回合开始前', group: 'turn' },
  { phrase: '回合开始时', group: 'turn' },
  { phrase: '回合结束时', group: 'turn' },
  { phrase: '交锋开始时', group: 'turn' },
  { phrase: '交锋结束时', group: 'turn' },
  { phrase: '开牌前', group: 'turn' },
];

const STATUS_NAMES_SORTED = Object.keys(STATUS_COLORS).sort((a, b) => b.length - a.length);

const INLINE_TOKEN_RE = new RegExp(
  [
    '(「[^」]+」)',
    '(超穿甲伤害|穿甲伤害|普通伤害|物理伤害)',
    '(概念护盾|强化护盾|普通护盾|护盾)',
    '(极限远程|强化远程|普通远程)',
    `(${STATUS_NAMES_SORTED.join('|')})`,
    '((?:[+−\\-×≥≤]\\s*\\d+(?:~\\d+)?)|(?:\\d+~\\d+)|(?:\\d+\\s*(?:层|点|次|张|级)))',
  ].join('|'),
  'g'
);

let _measureCtx = null;
function getMeasureCtx() {
  if (!_measureCtx && typeof document !== 'undefined') {
    const c = document.createElement('canvas');
    _measureCtx = c.getContext('2d');
  }
  return _measureCtx;
}

function measureTextWidth(text, fontSize, bold = false, fontFamily = FONT_UI) {
  const ctx = getMeasureCtx();
  if (ctx) {
    ctx.font = `${bold ? '800' : '400'} ${fontSize}px ${fontFamily}`;
    return ctx.measureText(text).width;
  }
  let w = 0;
  for (const ch of text) {
    w += ch.charCodeAt(0) > 127 ? fontSize : fontSize * 0.56;
  }
  return w;
}

export function wrapCjkText(str, maxHalfWidthChars = 36) {
  if (!str) return '';
  const paragraphs = String(str).split('\n');
  const out = [];
  for (const para of paragraphs) {
    let line = '';
    let width = 0;
    for (const ch of para) {
      const cw = ch.charCodeAt(0) > 127 ? 2 : 1.05;
      if (width + cw > maxHalfWidthChars && line) {
        out.push(line);
        line = ch;
        width = cw;
      } else {
        line += ch;
        width += cw;
      }
    }
    if (line || !para) out.push(line);
  }
  return out.join('\n');
}

export function formatDieRange(die) {
  const maxFace = die.roll_max || LEVEL_MAX[die.level || die.printed_level] || 6;
  let range = `1~${maxFace}`;
  if (die.base_value) {
    range = die.base_value > 0 ? `${die.base_value}+${range}` : `${range}${die.base_value}`;
  }
  if (die.multiplier && die.multiplier !== 1) {
    range = `(${range})×${die.multiplier}`;
  }
  if (die.final_bonus) {
    range += die.final_bonus > 0 ? `+${die.final_bonus}` : `${die.final_bonus}`;
  }
  return range;
}

export function exactSkillTraits(card) {
  return exactSkillTraitSpecs(card).map(({ label }) => label);
}

export function exactSkillTraitSpecs(card) {
  const specs = [];
  if (card.range_level) specs.push({ label: RANGE_LABELS[card.range_level], style: TRAIT_STYLE.range });
  if (card.ignore_range) specs.push({ label: `无视 ${card.ignore_range} 级远程`, style: TRAIT_STYLE.ignore_range });
  const earlyConditions = Object.entries(card.pre_reveal_requires_status || {});
  if (earlyConditions.length) {
    const terms = earlyConditions.map(([name, count]) => `${name}达到${count}层`);
    specs.push({ label: `${terms.join('、')}时可在开牌前进攻`, style: TRAIT_STYLE.pre_reveal });
  } else if (card.pre_reveal) {
    specs.push({ label: '开牌前打出', style: TRAIT_STYLE.pre_reveal });
  }
  if (card.anytime_play && card.anytime_play.length) {
    const modeNames = { attack: '主动进攻', place: '置于空交锋', custom: '依卡面执行' };
    specs.push({
      label: `任意时刻打出（${card.anytime_play.map((m) => modeNames[m] || m).join('、')}）`,
      style: TRAIT_STYLE.anytime,
    });
  }
  if (card.anytime_replace) specs.push({ label: '任意时刻替换', style: TRAIT_STYLE.anytime });
  if (card.interceptable === false) specs.push({ label: '不可拦截', style: TRAIT_STYLE.uninterceptable });
  if (card.starts_out_of_combat) specs.push({ label: '战斗外', style: TRAIT_STYLE.out_of_combat });
  return specs;
}

export function extractDieDamageBadge(entries) {
  const list = (entries || []).filter(Boolean);
  let badge = null;
  const restEntries = [];
  for (const raw of list) {
    const trimmed = String(raw).trim();
    if (!badge) {
      const m = trimmed.match(/^(\d+)\s*点?\s*(普通伤害|穿甲伤害|超穿甲伤害|普通|穿甲|超穿甲|物理)$/);
      if (m) {
        const amount = Number(m[1]);
        const kindRaw = m[2];
        const grade = kindRaw.includes('超穿甲') ? 'concept' : kindRaw.includes('穿甲') ? 'pierce' : 'normal';
        const style = DAMAGE_GRADE_STYLE[grade];
        badge = {
          amount,
          grade,
          exactText: trimmed,
          shortText: `${amount}${style.short}`,
          style,
        };
        continue;
      }
    }
    restEntries.push(trimmed);
  }
  return { badge, restEntries };
}

// ── Clean Architectural Vector Iconography ──

export function drawDieIcon(g, type, cx, cy, r, colorOverride = null) {
  const col = colorOverride ?? (DIE_STYLE[type]?.color || INK.secondary);
  if (type === 'slash') {
    // 斩击：一道凌厉弯曲的刀光（外凸内凹月牙刀弧 + 刃脊高光）
    const outerPts = [
      [cx - r * 0.86, cy + r * 0.72],
      [cx - r * 0.48, cy - r * 0.14],
      [cx + r * 0.14, cy - r * 0.66],
      [cx + r * 0.88, cy - r * 0.80],
      [cx + r * 0.28, cy - r * 0.26],
      [cx - r * 0.20, cy + r * 0.18],
    ];
    const flat = [];
    for (const [px, py] of outerPts) flat.push(px, py);
    g.poly(flat).fill({ color: col });
    // Fine bright gleam along outer cutting edge
    g.moveTo(cx - r * 0.62, cy + r * 0.44)
      .quadraticCurveTo(cx - r * 0.12, cy - r * 0.34, cx + r * 0.72, cy - r * 0.68)
      .stroke({ width: Math.max(0.8, r * 0.14), color: INK.paper, alpha: 0.85, cap: 'round' });
    // Secondary trailing slash light streak
    g.moveTo(cx - r * 0.28, cy + r * 0.72)
      .quadraticCurveTo(cx + r * 0.26, cy + r * 0.26, cx + r * 0.76, cy - r * 0.22)
      .stroke({ width: Math.max(0.9, r * 0.15), color: col, alpha: 0.58, cap: 'round' });
  } else if (type === 'pierce') {
    // 突刺：一柄刺剑突刺破空 + 垂直于剑轴的法向激波环
    // Tapered needle rapier blade thrusting from bottom-left to top-right
    g.poly([
      cx + r * 0.90, cy - r * 0.90,
      cx - r * 0.36, cy + r * 0.14,
      cx - r * 0.14, cy + r * 0.36,
    ]).fill({ color: col });
    // Rapier hilt & cup-crossguard at bottom-left
    g.moveTo(cx - r * 0.68, cy + r * 0.68)
      .lineTo(cx - r * 0.24, cy + r * 0.24)
      .stroke({ width: Math.max(1.2, r * 0.22), color: col, cap: 'round' });
    g.moveTo(cx - r * 0.52, cy + r * 0.08)
      .lineTo(cx - r * 0.08, cy + r * 0.52)
      .stroke({ width: Math.max(1.1, r * 0.20), color: col, cap: 'round' });
    // 法向激波（垂直于 (+1,-1) 突刺轴的双弧激波环，方向 (-1,-1) <-> (+1,+1)）
    const swCx = cx + r * 0.22;
    const swCy = cy - r * 0.22;
    g.moveTo(swCx - r * 0.50, swCy - r * 0.50)
      .quadraticCurveTo(swCx + r * 0.18, swCy - r * 0.18, swCx + r * 0.50, swCy + r * 0.50)
      .stroke({ width: Math.max(1.15, r * 0.20), color: col, alpha: 0.92, cap: 'round' });
    g.moveTo(swCx - r * 0.34, swCy - r * 0.34)
      .quadraticCurveTo(swCx - r * 0.16, swCy + r * 0.16, swCx + r * 0.34, swCy + r * 0.34)
      .stroke({ width: Math.max(0.85, r * 0.14), color: col, alpha: 0.65, cap: 'round' });
    // Outer Mach shock ring trailing slightly behind
    const sw2x = cx - r * 0.02;
    const sw2y = cy + r * 0.02;
    g.moveTo(sw2x - r * 0.34, sw2y - r * 0.34)
      .quadraticCurveTo(sw2x + r * 0.10, sw2y - r * 0.10, sw2x + r * 0.34, sw2y + r * 0.34)
      .stroke({ width: Math.max(0.85, r * 0.14), color: col, alpha: 0.55, cap: 'round' });
  } else if (type === 'blunt') {
    // 打击：从地面而起的冲击波具象（地面基线 + 震源 + 逐层上涌的半圆冲击波与破土气浪）
    const gy = cy + r * 0.64;
    // Ground impact baseline
    g.moveTo(cx - r * 0.84, gy)
      .lineTo(cx + r * 0.84, gy)
      .stroke({ width: Math.max(1.4, r * 0.25), color: col, cap: 'round' });
    // Impact epicenter dome seated on ground
    g.poly([
      cx - r * 0.34, gy,
      cx - r * 0.20, gy - r * 0.30,
      cx, gy - r * 0.42,
      cx + r * 0.20, gy - r * 0.30,
      cx + r * 0.34, gy,
    ]).fill({ color: col });
    // Inner upward shockwave arch rising from ground
    g.moveTo(cx - r * 0.56, gy - r * 0.04)
      .quadraticCurveTo(cx, gy - r * 1.12, cx + r * 0.56, gy - r * 0.04)
      .stroke({ width: Math.max(1.25, r * 0.22), color: col, alpha: 0.92, cap: 'round' });
    // Outer rising shockwave crest
    g.moveTo(cx - r * 0.80, gy - r * 0.10)
      .quadraticCurveTo(cx, gy - r * 1.66, cx + r * 0.80, gy - r * 0.10)
      .stroke({ width: Math.max(1.0, r * 0.17), color: col, alpha: 0.62, cap: 'round' });
    // Upward erupting force spikes from epicenter
    g.moveTo(cx, gy - r * 0.40).lineTo(cx, gy - r * 1.32)
      .stroke({ width: Math.max(1.05, r * 0.18), color: col, cap: 'round' });
    g.moveTo(cx - r * 0.24, gy - r * 0.34).lineTo(cx - r * 0.56, gy - r * 1.06)
      .stroke({ width: Math.max(0.9, r * 0.15), color: col, alpha: 0.85, cap: 'round' });
    g.moveTo(cx + r * 0.24, gy - r * 0.34).lineTo(cx + r * 0.56, gy - r * 1.06)
      .stroke({ width: Math.max(0.9, r * 0.15), color: col, alpha: 0.85, cap: 'round' });
  } else if (type === 'block') {
    // 招架：蓝色硬朗护盾纹章
    g.poly([
      cx, cy - r * 0.78,
      cx + r * 0.68, cy - r * 0.44,
      cx + r * 0.56, cy + r * 0.28,
      cx, cy + r * 0.82,
      cx - r * 0.56, cy + r * 0.28,
      cx - r * 0.68, cy - r * 0.44,
    ]).fill({ color: col, alpha: 0.20 }).stroke({ width: Math.max(1.3, r * 0.24), color: col, join: 'round' });
    g.moveTo(cx, cy - r * 0.52).lineTo(cx, cy + r * 0.54)
      .stroke({ width: Math.max(1.1, r * 0.20), color: col, cap: 'round' });
    g.moveTo(cx - r * 0.36, cy - r * 0.14).lineTo(cx + r * 0.36, cy - r * 0.14)
      .stroke({ width: Math.max(0.9, r * 0.16), color: col, alpha: 0.78, cap: 'round' });
  } else if (type === 'evade') {
    // 闪避：蓝色双层迅捷闪身折锋
    g.moveTo(cx - r * 0.68, cy + r * 0.14)
      .lineTo(cx, cy - r * 0.56)
      .lineTo(cx + r * 0.68, cy + r * 0.14)
      .stroke({ width: Math.max(1.5, r * 0.28), color: col, cap: 'round', join: 'round' });
    g.moveTo(cx - r * 0.48, cy + r * 0.60)
      .lineTo(cx, cy + r * 0.10)
      .lineTo(cx + r * 0.48, cy + r * 0.60)
      .stroke({ width: Math.max(1.15, r * 0.22), color: col, alpha: 0.74, cap: 'round', join: 'round' });
  } else {
    g.roundRect(cx - r * 0.56, cy - r * 0.56, r * 1.12, r * 1.12, 2)
      .stroke({ width: 1.5, color: col, alpha: 0.8 });
    g.moveTo(cx - r * 0.36, cy - r * 0.36)
      .lineTo(cx + r * 0.36, cy + r * 0.36)
      .stroke({ width: 1.2, color: col, alpha: 0.65 });
  }
}

export function drawUnifiedDieFrame(g, type, cx, cy, r, { muted = false, active = false } = {}) {
  const ds = DIE_STYLE[type] || DIE_STYLE.blank;
  const col = muted ? INK.muted : ds.color;
  const fill = muted ? INK.paperSoft : ds.bg;
  const fr = r * 1.32;

  if (ds.frame === 'hex') {
    // 斩击 / 突刺 / 打击：统一红色正六边形框
    const pts = [];
    for (let i = 0; i < 6; i++) {
      const a = -Math.PI / 2 + (i * Math.PI) / 3;
      pts.push(cx + Math.cos(a) * fr, cy + Math.sin(a) * fr);
    }
    if (active && !muted) {
      const halo = [];
      for (let i = 0; i < 6; i++) {
        const a = -Math.PI / 2 + (i * Math.PI) / 3;
        halo.push(cx + Math.cos(a) * (fr + 2.2), cy + Math.sin(a) * (fr + 2.2));
      }
      g.poly(halo).stroke({ width: 1.4, color: col, alpha: 0.35 });
    }
    g.poly(pts)
      .fill({ color: fill })
      .stroke({ width: active ? 1.85 : 1.3, color: col, alpha: muted ? 0.45 : 0.92 });
  } else {
    // 招架 / 闪避（以及空白）：统一正方形框（招架与闪避为统一蓝色）
    const sq = fr * 0.86;
    if (active && !muted) {
      g.roundRect(cx - sq - 2, cy - sq - 2, (sq + 2) * 2, (sq + 2) * 2, 3)
        .stroke({ width: 1.4, color: col, alpha: 0.35 });
    }
    g.roundRect(cx - sq, cy - sq, sq * 2, sq * 2, 1.8)
      .fill({ color: fill })
      .stroke({ width: active ? 1.85 : 1.3, color: col, alpha: muted ? 0.45 : 0.92 });
  }
  drawDieIcon(g, type, cx, cy, r * 0.78, muted ? INK.muted : ds.color);
}

export function drawStatusIcon(g, name, cx, cy, r, col) {
  if (name === '烧伤') {
    g.poly([cx, cy - r * 0.85, cx + r * 0.55, cy + r * 0.15, cx + r * 0.28, cy + r * 0.75, cx - r * 0.28, cy + r * 0.75, cx - r * 0.55, cy + r * 0.15])
      .fill({ color: col });
    g.circle(cx, cy + r * 0.25, r * 0.26).fill({ color: INK.paper });
  } else if (name === '裂血') {
    g.poly([cx, cy - r * 0.85, cx + r * 0.52, cy + r * 0.12, cx, cy + r * 0.78, cx - r * 0.52, cy + r * 0.12])
      .fill({ color: col });
  } else if (name === '涡流') {
    g.circle(cx, cy, r * 0.72).stroke({ width: 1.8, color: col });
    g.circle(cx, cy, r * 0.34).stroke({ width: 1.6, color: col });
    g.moveTo(cx, cy - r * 0.72).lineTo(cx + r * 0.4, cy - r * 0.32).stroke({ width: 1.6, color: col });
    g.moveTo(cx, cy + r * 0.72).lineTo(cx - r * 0.4, cy + r * 0.32).stroke({ width: 1.6, color: col });
  } else if (name === '充能' || name === '纯能' || name === '能源') {
    g.poly([
      cx + r * 0.12, cy - r * 0.85,
      cx - r * 0.45, cy + r * 0.08,
      cx + r * 0.02, cy + r * 0.08,
      cx - r * 0.16, cy + r * 0.85,
      cx + r * 0.48, cy - r * 0.1,
      cx + r * 0.02, cy - r * 0.1,
    ]).fill({ color: col });
  } else if (name === '校准') {
    g.circle(cx, cy, r * 0.58).stroke({ width: 1.6, color: col });
    g.moveTo(cx - r * 0.85, cy).lineTo(cx + r * 0.85, cy).stroke({ width: 1.3, color: col });
    g.moveTo(cx, cy - r * 0.85).lineTo(cx, cy + r * 0.85).stroke({ width: 1.3, color: col });
  } else if (name === '强壮') {
    g.poly([cx, cy - r * 0.8, cx + r * 0.65, cy + r * 0.15, cx + r * 0.25, cy + r * 0.15, cx + r * 0.25, cy + r * 0.78, cx - r * 0.25, cy + r * 0.78, cx - r * 0.25, cy + r * 0.15, cx - r * 0.65, cy + r * 0.15])
      .fill({ color: col });
  } else if (name === '虚弱') {
    g.poly([cx, cy + r * 0.8, cx + r * 0.65, cy - r * 0.15, cx + r * 0.25, cy - r * 0.15, cx + r * 0.25, cy - r * 0.78, cx - r * 0.25, cy - r * 0.78, cx - r * 0.25, cy - r * 0.15, cx - r * 0.65, cy - r * 0.15])
      .fill({ color: col });
  } else if (name === '迅捷') {
    g.moveTo(cx - r * 0.7, cy + r * 0.2).lineTo(cx + r * 0.1, cy - r * 0.55).lineTo(cx + r * 0.7, cy - r * 0.55)
      .stroke({ width: 2, color: col, cap: 'round' });
    g.moveTo(cx - r * 0.55, cy + r * 0.62).lineTo(cx + r * 0.25, cy - r * 0.12).lineTo(cx + r * 0.75, cy - r * 0.12)
      .stroke({ width: 1.8, color: col, cap: 'round' });
  } else if (name === '束缚') {
    g.roundRect(cx - r * 0.68, cy - r * 0.32, r * 0.8, r * 0.64, 3).stroke({ width: 1.8, color: col });
    g.roundRect(cx - r * 0.12, cy - r * 0.32, r * 0.8, r * 0.64, 3).stroke({ width: 1.8, color: col });
  } else if (name === '呼吸') {
    g.circle(cx, cy, r * 0.7).stroke({ width: 1.6, color: col });
    g.circle(cx, cy, r * 0.26).fill({ color: col });
  } else if (name === '失衡' || name === '致命失衡') {
    g.poly([cx, cy - r * 0.8, cx + r * 0.75, cy, cx, cy + r * 0.8, cx - r * 0.75, cy])
      .fill({ color: col, alpha: name === '致命失衡' ? 0.92 : 0.35 })
      .stroke({ width: 1.7, color: col });
    g.moveTo(cx - r * 0.3, cy - r * 0.25).lineTo(cx + r * 0.3, cy + r * 0.25).stroke({ width: 1.6, color: INK.paper });
  } else if (name === '能源封印') {
    g.roundRect(cx - r * 0.52, cy - r * 0.12, r * 1.04, r * 0.82, 2.5).fill({ color: col });
    g.circle(cx, cy - r * 0.28, r * 0.35).stroke({ width: 1.8, color: col });
  } else if (name === '置卡机会') {
    g.roundRect(cx - r * 0.5, cy - r * 0.68, r, r * 1.36, 2.5).stroke({ width: 1.6, color: col });
    g.moveTo(cx - r * 0.28, cy).lineTo(cx + r * 0.28, cy).stroke({ width: 1.8, color: col });
    g.moveTo(cx, cy - r * 0.28).lineTo(cx, cy + r * 0.28).stroke({ width: 1.8, color: col });
  } else if (name === '换卡机会') {
    g.moveTo(cx - r * 0.65, cy - r * 0.22).lineTo(cx + r * 0.55, cy - r * 0.22).stroke({ width: 1.8, color: col });
    g.moveTo(cx + r * 0.25, cy - r * 0.55).lineTo(cx + r * 0.62, cy - r * 0.22).lineTo(cx + r * 0.25, cy + r * 0.1).stroke({ width: 1.6, color: col });
    g.moveTo(cx + r * 0.65, cy + r * 0.25).lineTo(cx - r * 0.55, cy + r * 0.25).stroke({ width: 1.8, color: col });
    g.moveTo(cx - r * 0.25, cy - r * 0.08).lineTo(cx - r * 0.62, cy + r * 0.25).lineTo(cx - r * 0.25, cy + r * 0.58).stroke({ width: 1.6, color: col });
  } else if (name === '骰子等级降低' || name === '骰级免疫') {
    g.roundRect(cx - r * 0.6, cy - r * 0.6, r * 1.2, r * 1.2, 3).stroke({ width: 1.7, color: col });
    if (name === '骰子等级降低') {
      g.moveTo(cx, cy - r * 0.35).lineTo(cx, cy + r * 0.35).stroke({ width: 1.8, color: col });
      g.moveTo(cx - r * 0.3, cy + r * 0.08).lineTo(cx, cy + r * 0.38).lineTo(cx + r * 0.3, cy + r * 0.08).stroke({ width: 1.6, color: col });
    } else {
      g.circle(cx, cy, r * 0.25).fill({ color: col });
    }
  } else {
    g.circle(cx, cy, r * 0.58).fill({ color: col, alpha: 0.25 }).stroke({ width: 1.7, color: col });
  }
}

/**
 * Mount a status icon into `parentContainer`:
 *  - Priority 1: Custom SVG file (`icon_url`), inline SVG (`icon_svg`), or SVG path (`icon_path`)
 *    from `_packs/status_icons/` or `status_rules` (cached at 3x HiDPI as PIXI.Sprite).
 *  - Priority 2: Custom 1-2 char symbol (`icon_symbol`).
 *  - Priority 3: Built-in vector fallback (`drawStatusIcon`).
 */
export function mountStatusIcon(parentContainer, fallbackGraphics, name, cx, cy, r, col) {
  const resolvedCol = col ?? getStatusColor(name);
  const spec = name ? CUSTOM_STATUS_VISUALS.get(name) : null;

  let texEntry = null;
  if (spec?.icon_url) {
    texEntry = _preloadStatusIconUrl(spec.icon_url);
  } else if (spec?.icon_svg) {
    texEntry = _rasterizeStatusSvg(spec.icon_svg, `inline:${name}:${spec.icon_svg.length}`);
  } else if (Array.isArray(spec?.icon_path) && spec.icon_path.length) {
    const cssCol = hexToCss(resolvedCol);
    const paths = spec.icon_path.map((d) => `<path d="${d}" fill="${cssCol}"/>`).join('');
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">${paths}</svg>`;
    texEntry = _rasterizeStatusSvg(svg, `path:${name}:${cssCol}:${spec.icon_path.join('|')}`);
  }

  if (texEntry && parentContainer) {
    const size = r * 2.15;
    if (texEntry.ready && texEntry.texture) {
      const spr = new PIXI.Sprite(texEntry.texture);
      spr.anchor.set(0.5);
      spr.width = size;
      spr.height = size;
      spr.position.set(cx, cy);
      parentContainer.addChild(spr);
      return;
    }
    // Render temporary fallback while 2ms SVG decode finishes, then swap cleanly
    const tempG = new PIXI.Graphics();
    drawStatusIcon(tempG, name, cx, cy, r, resolvedCol);
    parentContainer.addChild(tempG);
    texEntry.onReady((done) => {
      if (parentContainer.destroyed) return;
      if (done.ready && done.texture) {
        if (!tempG.destroyed) tempG.visible = false;
        const spr = new PIXI.Sprite(done.texture);
        spr.anchor.set(0.5);
        spr.width = size;
        spr.height = size;
        spr.position.set(cx, cy);
        parentContainer.addChild(spr);
      }
    });
    return;
  }

  if (spec?.icon_symbol && parentContainer) {
    const t = new PIXI.Text({
      text: spec.icon_symbol,
      style: { fontFamily: FONT_UI, fontSize: Math.max(9, r * 1.45), fontWeight: '900', fill: resolvedCol },
    });
    t.anchor.set(0.5);
    t.position.set(cx, cy);
    parentContainer.addChild(t);
    return;
  }

  if (fallbackGraphics) {
    drawStatusIcon(fallbackGraphics, name, cx, cy, r, resolvedCol);
  }
}

export function drawShieldGlyph(g, kind, cx, cy, r) {
  const st = SHIELD_STYLE[kind] || SHIELD_STYLE.normal;
  const pts = [];
  const sides = kind === 'concept' ? 4 : 6;
  const offset = kind === 'concept' ? -Math.PI / 2 : -Math.PI / 6;
  for (let i = 0; i < sides; i++) {
    const a = offset + (i * Math.PI * 2) / sides;
    pts.push(cx + Math.cos(a) * r, cy + Math.sin(a) * r);
  }
  g.poly(pts).fill({ color: st.bg }).stroke({ width: 1.6, color: st.color });
  if (kind !== 'normal') g.circle(cx, cy, r * 0.3).fill({ color: st.color });
}

export function drawLightStar(g, cx, cy, outerR, color, alpha = 0.9) {
  const pts = [];
  for (let i = 0; i < 8; i++) {
    const a = -Math.PI / 2 + (i * Math.PI) / 4;
    const r = i % 2 === 0 ? outerR : outerR * 0.32;
    pts.push(cx + Math.cos(a) * r, cy + Math.sin(a) * r);
  }
  g.poly(pts).fill({ color, alpha });
  g.circle(cx, cy, outerR * 0.66).stroke({ width: 1.1, color, alpha: alpha * 0.4 });
  g.circle(cx, cy, outerR * 0.16).fill({ color: INK.paper, alpha: 1 });
}

export function drawCostCrystal(g, cx, cy, r, fillCol, rimCol = INK.paper) {
  const pts = [];
  for (let i = 0; i < 6; i++) {
    const a = -Math.PI / 2 + (i * Math.PI * 2) / 6;
    pts.push(cx + Math.cos(a) * r, cy + Math.sin(a) * r);
  }
  g.poly(pts).fill({ color: fillCol }).stroke({ width: 1.3, color: rimCol, alpha: 0.85 });
  g.poly([
    cx, cy - r * 0.82,
    cx + r * 0.62, cy - r * 0.32,
    cx, cy - r * 0.08,
    cx - r * 0.62, cy - r * 0.32,
  ]).fill({ color: INK.paper, alpha: 0.24 });
}

// ── Clean Editorial 100% Verbatim Rich-Text Renderer (ZERO bulky pills!) ──

function classifyInlineMatch(match) {
  if (match[1]) return { color: INK.goldDeep, bold: true, font: FONT_UI };
  if (match[2]) {
    const txt = match[2];
    const st = txt.includes('超穿甲') ? DAMAGE_GRADE_STYLE.concept : txt.includes('穿甲') ? DAMAGE_GRADE_STYLE.pierce : DAMAGE_GRADE_STYLE.normal;
    return { color: st.color, bold: true, font: FONT_UI };
  }
  if (match[3]) {
    const txt = match[3];
    const st = txt.includes('概念') ? SHIELD_STYLE.concept : txt.includes('强化') ? SHIELD_STYLE.reinforced : SHIELD_STYLE.normal;
    return { color: st.color, bold: true, font: FONT_UI };
  }
  if (match[4]) return { color: TRAIT_STYLE.range.color, bold: true, font: FONT_UI };
  if (match[5]) return { color: STATUS_COLORS[match[5]] || INK.primary, bold: true, font: FONT_UI };
  if (match[6]) return { color: INK.strong, bold: true, font: FONT_NUM };
  return { color: INK.primary, bold: false, font: FONT_UI };
}

function tokenizeLine(line, baseColor, muted) {
  const tokens = [];
  let rest = line;

  for (const tp of TIMING_PREFIXES) {
    if (rest.startsWith(tp.phrase)) {
      const ts = TIMING_STYLE[tp.group];
      tokens.push({
        kind: 'timing',
        text: tp.phrase,
        color: muted ? INK.muted : ts.color,
        wash: muted ? INK.paperSoft : ts.wash,
        rule: muted ? INK.line : ts.rule,
        bold: true,
        font: FONT_UI,
      });
      rest = rest.slice(tp.phrase.length);
      break;
    }
  }

  INLINE_TOKEN_RE.lastIndex = 0;
  let lastIdx = 0;
  let m;
  while ((m = INLINE_TOKEN_RE.exec(rest)) !== null) {
    if (m.index > lastIdx) {
      tokens.push({ kind: 'text', text: rest.slice(lastIdx, m.index), color: baseColor, bold: false, font: FONT_UI });
    }
    const cls = classifyInlineMatch(m);
    tokens.push({
      kind: 'text',
      text: m[0],
      color: muted ? INK.muted : cls.color,
      bold: cls.bold,
      font: cls.font,
    });
    lastIdx = m.index + m[0].length;
  }
  if (lastIdx < rest.length) {
    tokens.push({ kind: 'text', text: rest.slice(lastIdx), color: baseColor, bold: false, font: FONT_UI });
  }
  return tokens;
}

/**
 * Editorial 100% Verbatim Rich-Text Renderer:
 *  - Leading timing phrases get a whisper-soft tint wash + crisp 1.5px bottom rule (NO heavy border boxes!)
 *  - Status names, shields, damage grades & numbers render in crisp bold semantic color
 *  - ZERO characters added, deleted, or reworded!
 */
export function buildRichVerbatimText(text, {
  maxWidth = 240,
  fontSize = 11.2,
  lineHeight = 16.5,
  baseColor = INK.primary,
  muted = false,
  paragraphGap = 2.5,
} = {}) {
  const root = new PIXI.Container();
  if (!text) {
    root._width = 0;
    root._height = 0;
    return root;
  }

  const markG = new PIXI.Graphics();
  root.addChild(markG);

  const paragraphs = String(text).split('\n');
  let cursorY = 0;
  let maxLineW = 0;

  for (let pIdx = 0; pIdx < paragraphs.length; pIdx++) {
    const para = paragraphs[pIdx];
    if (!para) {
      cursorY += Math.round(lineHeight * 0.5);
      continue;
    }
    const tokens = tokenizeLine(para, muted ? INK.muted : baseColor, muted);
    let cursorX = 0;

    const flushNewLine = () => {
      maxLineW = Math.max(maxLineW, cursorX);
      cursorX = 0;
      cursorY += lineHeight;
    };

    for (const tok of tokens) {
      if (tok.kind === 'timing') {
        const tw = measureTextWidth(tok.text, fontSize, true, FONT_UI);
        const pw = Math.ceil(tw) + 5;
        const ph = Math.max(13, Math.round(fontSize + 3.5));
        if (cursorX > 0 && cursorX + pw > maxWidth) flushNewLine();
        const py = cursorY + Math.max(0, (lineHeight - ph) / 2);
        // Clean editorial highlight wash + crisp hairline underline (NO cluttered pill border!)
        markG.roundRect(cursorX, py, pw, ph, 2.5).fill({ color: tok.wash, alpha: 0.92 });
        markG.moveTo(cursorX + 1, py + ph - 0.5).lineTo(cursorX + pw - 1, py + ph - 0.5)
          .stroke({ width: 1.4, color: tok.rule, alpha: 0.78 });
        const pt = new PIXI.Text({
          text: tok.text,
          style: { fontFamily: FONT_UI, fontSize, fontWeight: '800', fill: tok.color },
        });
        pt.anchor.set(0, 0.5);
        pt.position.set(cursorX + 2.5, py + ph / 2);
        root.addChild(pt);
        cursorX += pw + 2;
        continue;
      }

      let buf = '';
      let bufW = 0;
      const emitBuf = () => {
        if (!buf) return;
        const t = new PIXI.Text({
          text: buf,
          style: {
            fontFamily: tok.font,
            fontSize,
            fontWeight: tok.bold ? '800' : '400',
            fill: tok.color,
          },
        });
        t.anchor.set(0, 0.5);
        t.position.set(cursorX, cursorY + lineHeight / 2);
        root.addChild(t);
        cursorX += bufW;
        buf = '';
        bufW = 0;
      };

      const wholeW = measureTextWidth(tok.text, fontSize, tok.bold, tok.font);
      if (cursorX + wholeW <= maxWidth) {
        buf = tok.text;
        bufW = wholeW;
        emitBuf();
      } else if (tok.bold && wholeW <= maxWidth && cursorX > 0 && tok.text.length <= 6) {
        flushNewLine();
        buf = tok.text;
        bufW = wholeW;
        emitBuf();
      } else {
        for (const ch of tok.text) {
          const cw = measureTextWidth(ch, fontSize, tok.bold, tok.font);
          if (cursorX + bufW + cw > maxWidth && (cursorX > 0 || buf.length > 0)) {
            emitBuf();
            flushNewLine();
          }
          buf += ch;
          bufW += cw;
        }
        emitBuf();
      }
    }

    maxLineW = Math.max(maxLineW, cursorX);
    cursorY += lineHeight;
    if (pIdx < paragraphs.length - 1) cursorY += paragraphGap;
  }

  root._width = Math.min(maxWidth, Math.ceil(maxLineW));
  root._height = Math.max(lineHeight, Math.ceil(cursorY));
  return root;
}

// ── Clean Editorial Trait Strip, Damage Spec, Die Row, Entry Plate & Skill Row ──

export function buildTraitPills(card, maxWidth, { compact = false } = {}) {
  const specs = exactSkillTraitSpecs(card);
  const root = new PIXI.Container();
  if (!specs.length) {
    root._height = 0;
    return root;
  }
  const bg = new PIXI.Graphics();
  root.addChild(bg);

  const fontSize = compact ? 9.5 : 10.5;
  const pillH = compact ? 16 : 18;
  const gapX = 5;
  const gapY = 4;
  let x = 0;
  let y = 0;

  for (const sp of specs) {
    const t = new PIXI.Text({
      text: sp.label,
      style: { fontFamily: FONT_UI, fontSize, fontWeight: '800', fill: sp.style.color },
    });
    const pw = Math.ceil(t.width) + 10;
    if (x > 0 && x + pw > maxWidth) {
      x = 0;
      y += pillH + gapY;
    }
    bg.roundRect(x, y, pw, pillH, 3)
      .fill({ color: sp.style.bg })
      .stroke({ width: 0.85, color: sp.style.border, alpha: 0.8 });
    t.anchor.set(0, 0.5);
    t.position.set(x + 5, y + pillH / 2);
    root.addChild(t);
    x += pw + gapX;
  }

  root._height = y + pillH;
  return root;
}

/**
 * Clean Editorial Standalone Damage Spec ("2 点普通伤害" / "3 点穿甲伤害" / "3 点超穿甲伤害").
 * Whisper-light wash + crisp geometric grade indicator, NO thick rounded borders!
 */
export function buildDamageBadge(badge, { compact = false, muted = false } = {}) {
  const c = new PIXI.Container();
  const st = badge.style;
  const label = compact ? badge.shortText : badge.exactText;
  const fontSize = compact ? 9.5 : 10.6;
  const pillH = compact ? 15 : 18;

  const txt = new PIXI.Text({
    text: label,
    style: {
      fontFamily: FONT_UI,
      fontSize,
      fontWeight: '800',
      fill: muted ? INK.muted : st.color,
    },
  });
  const iconSpace = compact ? 0 : 10;
  const pw = Math.ceil(txt.width) + (compact ? 6 : 10) + iconSpace;

  const g = new PIXI.Graphics();
  g.roundRect(0, 0, pw, pillH, 3).fill({ color: muted ? INK.paperSoft : st.bg, alpha: 0.95 });
  g.moveTo(1, pillH - 0.5).lineTo(pw - 1, pillH - 0.5)
    .stroke({ width: 1.2, color: muted ? INK.line : st.border, alpha: 0.85 });

  if (!compact) {
    const icx = 6.5;
    const icy = pillH / 2;
    const ic = muted ? INK.muted : st.color;
    if (badge.grade === 'concept') {
      g.poly([icx, icy - 3.6, icx + 3.4, icy, icx, icy + 3.6, icx - 3.4, icy]).fill({ color: ic });
    } else if (badge.grade === 'pierce') {
      g.poly([icx - 3, icy - 2.6, icx + 3.6, icy, icx - 3, icy + 2.6]).fill({ color: ic });
    } else {
      g.circle(icx, icy, 2.6).fill({ color: ic });
    }
  }

  txt.anchor.set(0, 0.5);
  txt.position.set(compact ? 3 : 13, pillH / 2);
  c.addChild(g, txt);
  c._width = pw;
  c._height = pillH;
  return c;
}

/**
 * Clean Editorial Die Row on Pure Paper (ZERO box-inside-box clutter!):
 *  - Pure ivory background (warm gold tint ONLY when actively clashing)
 *  - Crisp 3px left semantic color bar + hairline bottom divider
 *  - Left: Framed Die Emblem + Bold Exact Roll Range
 *  - Right: Inline Damage Spec + Rich Verbatim Trigger Entries
 */
export function buildUnifiedDieRow(die, {
  width = 240,
  active = false,
  spent = false,
  dense = false,
  compact = false,
  showDivider = true,
  isBlanked = false,
} = {}) {
  const root = new PIXI.Container();
  const dType = isBlanked ? 'blank' : die.type;
  const ds = DIE_STYLE[dType] || DIE_STYLE.blank;
  const { badge, restEntries } = isBlanked ? { badge: null, restEntries: [] } : extractDieDamageBadge(die.entries);
  const tight = dense || compact;
  const slim = dense && width < 194;
  const fontSize = slim ? 10.2 : dense ? 10.6 : compact ? 11 : 11.8;
  const lineH = slim ? 14.2 : dense ? 14.8 : compact ? 16 : 17.5;
  const leftColW = slim ? 64 : dense ? 74 : compact ? 80 : 90;
  const rightX = leftColW + 5;
  const rightW = Math.max(76, width - rightX - 3);

  const dmgNode = badge ? buildDamageBadge(badge, { compact: false, muted: spent }) : null;
  const richNode = restEntries.length
    ? buildRichVerbatimText(restEntries.join('\n'), {
        maxWidth: rightW,
        fontSize,
        lineHeight: lineH,
        baseColor: INK.primary,
        muted: spent,
        paragraphGap: 2,
      })
    : null;

  let rightContentH = 0;
  if (dmgNode && richNode) rightContentH = dmgNode._height + 3 + richNode._height;
  else if (dmgNode) rightContentH = dmgNode._height;
  else if (richNode) rightContentH = richNode._height;

  const baseMinH = tight ? 26 : 32;
  const rowH = Math.max(baseMinH, rightContentH + (tight ? 8 : 10));

  const g = new PIXI.Graphics();
  if (active) {
    g.roundRect(0, 0, width, rowH, 4).fill({ color: INK.goldBg, alpha: 0.95 });
  } else if (spent) {
    g.roundRect(0, 0, width, rowH, 4).fill({ color: INK.paperSoft, alpha: 0.55 });
  }
  // Signature crisp 3px left semantic accent bar
  g.roundRect(0, 3, 3, rowH - 6, 1.5)
    .fill({ color: spent ? INK.muted : active ? INK.gold : ds.color, alpha: spent ? 0.45 : 0.92 });

  if (showDivider) {
    g.moveTo(6, rowH).lineTo(width - 2, rowH).stroke({ width: 0.9, color: INK.hairline });
  }

  const leftMidY = rightContentH > baseMinH ? Math.min(rowH / 2, baseMinH / 2 + 2) : rowH / 2;
  drawUnifiedDieFrame(g, dType, slim ? 14 : 16, leftMidY, slim ? 5.6 : tight ? 6.2 : 7.2, { muted: spent, active });

  const rngTxt = new PIXI.Text({
    text: formatDieRange(die),
    style: {
      fontFamily: FONT_NUM,
      fontSize: slim ? 11.2 : tight ? 12.2 : 13.5,
      fontWeight: '900',
      fill: spent ? INK.muted : ds.color,
    },
  });
  rngTxt.anchor.set(0, 0.5);
  rngTxt.position.set(slim ? 24 : 28, leftMidY);
  root.addChild(g, rngTxt);

  let ry = Math.max(4, (rowH - rightContentH) / 2);
  if (dmgNode) {
    dmgNode.position.set(rightX, ry);
    root.addChild(dmgNode);
    ry += dmgNode._height + 3;
  }
  if (richNode) {
    richNode.position.set(rightX, ry);
    root.addChild(richNode);
  }

  root._height = rowH;
  return root;
}

/**
 * Clean Editorial Entry Plate (Passives / Skill-Level Entries / Status Rules):
 * Pure sunlit paper + hairline edge + 3px left semantic accent bar + rich verbatim text.
 */
export function buildUnifiedEntryPlate({
  variant = 'passive',
  title = '',
  tagLabel = '',
  statusName = '',
  statusValue = null,
  statusBurst = false,
  entries = [],
  width = 300,
  accentColor = null,
  fontSize = 11.4,
  lineHeight = 17,
  compact = false,
} = {}) {
  const root = new PIXI.Container();
  const isStatus = variant === 'status';
  const isPassive = variant === 'passive';
  const isSkill = variant === 'skill';
  const accent = accentColor ?? (
    isStatus
      ? getStatusColor(statusName, INK.secondary)
      : isPassive
        ? INK.gold
        : INK.secondary
  );
  const bgCol = isPassive ? INK.paperSoft : isSkill ? INK.paperSoft : INK.paper;

  const padL = isStatus ? 36 : 11;
  const padR = 8;
  const textW = Math.max(76, width - padL - padR);
  const joined = (Array.isArray(entries) ? entries : [entries]).filter(Boolean).join('\n');

  const bodyNode = joined
    ? buildRichVerbatimText(joined, {
        maxWidth: textW,
        fontSize,
        lineHeight,
        baseColor: INK.primary,
        paragraphGap: compact ? 2 : 3,
      })
    : null;

  const hasHeader = Boolean(title || isStatus);
  const headH = hasHeader ? (compact ? 19 : 21) : 0;
  const topPad = hasHeader ? 5 : 5;
  const botPad = 5;
  const totalH = Math.max(isStatus ? 32 : 22, topPad + headH + (bodyNode ? bodyNode._height + (hasHeader ? 2 : 0) : 0) + botPad);

  const g = new PIXI.Graphics();
  g.roundRect(0, 0, width, totalH, 5)
    .fill({ color: bgCol, alpha: isSkill ? 0.72 : 0.96 })
    .stroke({ width: 0.85, color: INK.hairline });
  // Signature 3px left accent rule
  g.roundRect(0, 2, 3, totalH - 4, 1.5).fill({ color: accent, alpha: 0.9 });
  root.addChild(g);

  if (isStatus) {
    mountStatusIcon(root, g, statusName, 19, Math.min(totalH / 2, 17), 9, accent);
    const titleStr = `${statusName}${statusValue !== null ? ' ' + statusValue : ''}${statusBurst ? '（爆发）' : ''}`;
    const hTxt = new PIXI.Text({
      text: titleStr,
      style: { fontFamily: FONT_UI, fontSize: compact ? 11.4 : 12.2, fontWeight: '800', fill: accent },
    });
    hTxt.position.set(padL, topPad);
    root.addChild(hTxt);
  } else if (title) {
    const hTxt = new PIXI.Text({
      text: title,
      style: { fontFamily: FONT_UI, fontSize: compact ? 11.4 : 12.2, fontWeight: '800', fill: isPassive ? INK.goldDeep : accent },
    });
    hTxt.position.set(padL, topPad);
    root.addChild(hTxt);

    if (tagLabel) {
      const tt = new PIXI.Text({
        text: tagLabel,
        style: { fontFamily: FONT_UI, fontSize: 9.2, fontWeight: '800', fill: accent },
      });
      const tw = Math.ceil(tt.width) + 8;
      const tx = Math.min(width - tw - 6, padL + hTxt.width + 6);
      g.roundRect(tx, topPad + 1, tw, 15, 3)
        .fill({ color: INK.paper })
        .stroke({ width: 0.85, color: accent, alpha: 0.6 });
      tt.anchor.set(0.5);
      tt.position.set(tx + tw / 2, topPad + 8.5);
      root.addChild(tt);
    }
  }

  if (bodyNode) {
    bodyNode.position.set(padL, topPad + headH + (hasHeader ? 2 : 0));
    root.addChild(bodyNode);
  }

  root._height = totalH;
  return root;
}

/**
 * Clean Architectural Horizontal Skill Strip (Cost Crystal + Name + Clean Die Range Chips).
 */
export function buildUnifiedSkillRow(skill, {
  width = 460,
  side = 1,
  accentColor = null,
  active = false,
} = {}) {
  const root = new PIXI.Container();
  const pal = deriveCardPalette(accentColor, side);
  const rowH = 38;

  const g = new PIXI.Graphics();
  g.roundRect(0, 0, width, rowH, 6)
    .fill({ color: active ? pal.softBg : INK.paper })
    .stroke({ width: active ? 1.6 : 1.0, color: active ? pal.accent : pal.border });
  g.roundRect(0, 3, 3, rowH - 6, 1.5).fill({ color: pal.accent, alpha: active ? 1 : 0.72 });
  drawCostCrystal(g, 22, rowH / 2, 11.5, pal.accent);
  root.addChild(g);

  const cTxt = new PIXI.Text({
    text: String(skill.cost ?? 0),
    style: { fontFamily: FONT_NUM, fontSize: 13, fontWeight: '900', fill: INK.paper },
  });
  cTxt.anchor.set(0.5);
  cTxt.position.set(22, rowH / 2 + 0.5);
  root.addChild(cTxt);

  const nTxt = new PIXI.Text({
    text: skill.name || '',
    style: { fontFamily: FONT_UI, fontSize: 13, fontWeight: '800', fill: INK.strong },
  });
  nTxt.anchor.set(0, 0.5);
  nTxt.position.set(40, rowH / 2);
  root.addChild(nTxt);

  let dx = width - 8;
  const dice = skill.dice || [];
  for (let i = dice.length - 1; i >= 0; i--) {
    const d = dice[i];
    const ds = DIE_STYLE[d.type] || DIE_STYLE.blank;
    const rt = new PIXI.Text({
      text: formatDieRange(d),
      style: { fontFamily: FONT_NUM, fontSize: 11.2, fontWeight: '800', fill: ds.color },
    });
    const capW = Math.ceil(rt.width) + 22;
    const capX = dx - capW;
    if (capX < 44 + nTxt.width + 8) break;
    drawUnifiedDieFrame(g, d.type, capX + 9, rowH / 2, 5.2);
    rt.anchor.set(0, 0.5);
    rt.position.set(capX + 18, rowH / 2);
    root.addChild(rt);
    dx = capX - 6;
  }

  root._height = rowH;
  return root;
}
