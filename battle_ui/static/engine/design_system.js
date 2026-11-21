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

export const DIE_STYLE = {
  slash:  { label: '斩击', kind: 'attack',  frame: 'diamond', color: 0xc93e2b, bg: 0xfdf4f2, hex: '#c93e2b' },
  pierce: { label: '突刺', kind: 'attack',  frame: 'diamond', color: 0xc27110, bg: 0xfef8ec, hex: '#c27110' },
  blunt:  { label: '砸击', kind: 'attack',  frame: 'diamond', color: 0xa82f3e, bg: 0xfcf2f4, hex: '#a82f3e' },
  block:  { label: '招架', kind: 'defense', frame: 'hex',     color: 0x177d6b, bg: 0xf0f9f7, hex: '#177d6b' },
  evade:  { label: '闪避', kind: 'defense', frame: 'circle',  color: 0x3b8c2c, bg: 0xf3faf0, hex: '#3b8c2c' },
  blank:  { label: '空白', kind: 'blank',   frame: 'square',  color: 0x8a7f71, bg: 0xf6f2ea, hex: '#8a7f71' },
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
};

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
  烧伤: '回合结束时，将层数除以 4 向下取整记作 N，承受 min(N, 3) 点普通伤害。若实际受到伤害，烧伤减少 N + 2 层；若全被护盾吸收，则保留全部层数。',
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
  const traits = [];
  if (card.range_level) traits.push(RANGE_LABELS[card.range_level]);
  if (card.ignore_range) traits.push(`无视 ${card.ignore_range} 级远程`);
  if (card.pre_reveal) traits.push('开牌前打出');
  if (card.anytime_play && card.anytime_play.length) {
    const modeNames = { attack: '主动进攻', place: '置于空交锋', custom: '依卡面执行' };
    traits.push(`任意时刻打出（${card.anytime_play.map((m) => modeNames[m] || m).join('、')}）`);
  }
  if (card.anytime_replace) traits.push('任意时刻替换');
  if (card.interceptable === false) traits.push('不可拦截');
  if (card.starts_out_of_combat) traits.push('战斗外');
  return traits;
}

export function exactSkillTraitSpecs(card) {
  const specs = [];
  if (card.range_level) specs.push({ label: RANGE_LABELS[card.range_level], style: TRAIT_STYLE.range });
  if (card.ignore_range) specs.push({ label: `无视 ${card.ignore_range} 级远程`, style: TRAIT_STYLE.ignore_range });
  if (card.pre_reveal) specs.push({ label: '开牌前打出', style: TRAIT_STYLE.pre_reveal });
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
    g.moveTo(cx - r * 0.7, cy + r * 0.7)
      .lineTo(cx + r * 0.75, cy - r * 0.75)
      .stroke({ width: 2.0, color: col, cap: 'round' });
    g.moveTo(cx - r * 0.25, cy - r * 0.55)
      .quadraticCurveTo(cx + r * 0.55, cy - r * 0.52, cx + r * 0.55, cy + r * 0.32)
      .stroke({ width: 1.4, color: col, alpha: 0.82, cap: 'round' });
  } else if (type === 'pierce') {
    g.moveTo(cx - r * 0.68, cy + r * 0.68)
      .lineTo(cx + r * 0.45, cy - r * 0.45)
      .stroke({ width: 1.9, color: col, cap: 'round' });
    g.poly([
      cx + r * 0.8, cy - r * 0.8,
      cx + r * 0.08, cy - r * 0.56,
      cx + r * 0.56, cy - r * 0.08,
    ]).fill({ color: col });
  } else if (type === 'blunt') {
    g.moveTo(cx - r * 0.64, cy + r * 0.64)
      .lineTo(cx + r * 0.1, cy - r * 0.1)
      .stroke({ width: 2.0, color: col, cap: 'round' });
    g.poly([
      cx - r * 0.14, cy - r * 0.72,
      cx + r * 0.72, cy + r * 0.14,
      cx + r * 0.36, cy + r * 0.48,
      cx - r * 0.48, cy - r * 0.36,
    ]).fill({ color: col });
  } else if (type === 'block') {
    g.poly([
      cx, cy - r * 0.8,
      cx + r * 0.7, cy - r * 0.44,
      cx + r * 0.56, cy + r * 0.3,
      cx, cy + r * 0.84,
      cx - r * 0.56, cy + r * 0.3,
      cx - r * 0.7, cy - r * 0.44,
    ]).fill({ color: col, alpha: 0.16 }).stroke({ width: 1.6, color: col });
    g.moveTo(cx, cy - r * 0.48).lineTo(cx, cy + r * 0.48).stroke({ width: 1.3, color: col });
  } else if (type === 'evade') {
    g.moveTo(cx - r * 0.7, cy + r * 0.16)
      .lineTo(cx, cy - r * 0.54)
      .lineTo(cx + r * 0.7, cy + r * 0.16)
      .stroke({ width: 1.9, color: col, cap: 'round', join: 'round' });
    g.moveTo(cx - r * 0.46, cy + r * 0.58)
      .lineTo(cx, cy + r * 0.12)
      .lineTo(cx + r * 0.46, cy + r * 0.58)
      .stroke({ width: 1.5, color: col, alpha: 0.72, cap: 'round', join: 'round' });
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
  const col = muted ? INK.muted : active ? INK.gold : ds.color;
  const fill = muted ? INK.paperSoft : active ? INK.goldBg : ds.bg;
  const fr = r * 1.32;

  if (ds.frame === 'diamond') {
    g.poly([cx, cy - fr, cx + fr, cy, cx, cy + fr, cx - fr, cy])
      .fill({ color: fill })
      .stroke({ width: active ? 1.6 : 1.2, color: col, alpha: muted ? 0.45 : 0.82 });
  } else if (ds.frame === 'hex') {
    const pts = [];
    for (let i = 0; i < 6; i++) {
      const a = -Math.PI / 6 + (i * Math.PI) / 3;
      pts.push(cx + Math.cos(a) * fr, cy + Math.sin(a) * fr);
    }
    g.poly(pts)
      .fill({ color: fill })
      .stroke({ width: active ? 1.6 : 1.2, color: col, alpha: muted ? 0.45 : 0.82 });
  } else if (ds.frame === 'circle') {
    g.circle(cx, cy, fr * 0.9)
      .fill({ color: fill })
      .stroke({ width: active ? 1.6 : 1.2, color: col, alpha: muted ? 0.45 : 0.82 });
  } else {
    g.roundRect(cx - fr * 0.8, cy - fr * 0.8, fr * 1.6, fr * 1.6, 2.5)
      .fill({ color: fill })
      .stroke({ width: 1.1, color: col, alpha: 0.55 });
  }
  drawDieIcon(g, type, cx, cy, r * 0.72, muted ? INK.muted : ds.color);
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
      ? (STATUS_COLORS[statusName] || INK.secondary)
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
    drawStatusIcon(g, statusName, 19, Math.min(totalH / 2, 17), 9, accent);
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
  active = false,
} = {}) {
  const root = new PIXI.Container();
  const theme = SIDE_THEME[side] || SIDE_THEME[1];
  const highCost = (skill.cost ?? 0) >= 4;
  const rowH = 38;

  const g = new PIXI.Graphics();
  g.roundRect(0, 0, width, rowH, 6)
    .fill({ color: active ? theme.softBg : INK.paper })
    .stroke({ width: active ? 1.6 : 0.9, color: active ? theme.accent : INK.line });
  if (active) g.roundRect(0, 3, 3, rowH - 6, 1.5).fill({ color: theme.accent });
  drawCostCrystal(g, 22, rowH / 2, 11.5, highCost ? INK.gold : theme.accent);
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
