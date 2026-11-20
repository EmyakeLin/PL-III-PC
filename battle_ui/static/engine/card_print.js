/**
 * Pure PixiJS v8 WebGL Card, Status Icon, and 100% Verbatim Card Panel Renderer.
 * STRICT RULES:
 *  - Bright daylight palette: ZERO black, ZERO blue-purple
 *  - 100% VERBATIM rule text: ZERO paraphrasing, ZERO summarizing, ZERO flavor/annotation filler
 *  - Show exact roll ranges (1~4, 1~6, 1~8, 1~12, 1~16, 1~20, 1~10) — NEVER "Lv.2"
 *  - Empty die entries stay blank — NEVER "无附加词条"
 *  - Limbus-style custom vector status icons + stack numbers
 */

import * as PIXI from '../vendor/pixi.min.mjs';

export const FONT_UI = '"Microsoft YaHei", "PingFang SC", "Segoe UI", system-ui, sans-serif';
export const FONT_NUM = '"Segoe UI", "DIN Alternate", "Consolas", sans-serif';

export const INK = {
  primary: 0x3b322a,
  secondary: 0x6b5f53,
  muted: 0x998d7e,
  line: 0xd9cfbe,
  shadow: 0xb0a38f,
  paper: 0xfffdf8,
  paperSoft: 0xf6f1e6,
  paperTint: 0xefe8da,
  gold: 0xd48e1a,
  goldBg: 0xfef3db,
};

export const SIDE_THEME = {
  1: {
    name: '玩家一',
    accent: 0x1c8a64,
    accentHex: '#1c8a64',
    softBg: 0xe6f5ee,
    border: 0x52b38e,
    warmTint: 0xf2faf6,
  },
  2: {
    name: '玩家二',
    accent: 0xcf4932,
    accentHex: '#cf4932',
    softBg: 0xfcebe7,
    border: 0xe38472,
    warmTint: 0xfef5f2,
  },
};

export const DIE_STYLE = {
  slash:  { label: '斩击', color: 0xcf4330, bg: 0xfdece9, hex: '#cf4330' },
  pierce: { label: '突刺', color: 0xcc7b14, bg: 0xfef4df, hex: '#cc7b14' },
  blunt:  { label: '砸击', color: 0xb33443, bg: 0xfbe8eb, hex: '#b33443' },
  block:  { label: '招架', color: 0x1a8775, bg: 0xe4f6f2, hex: '#1a8775' },
  evade:  { label: '闪避', color: 0x459934, bg: 0xebf6e6, hex: '#459934' },
  blank:  { label: '空白', color: 0x8a7f71, bg: 0xf2ede4, hex: '#8a7f71' },
};

export const SHIELD_STYLE = {
  normal:     { label: '普通护盾', short: '普通', color: 0x2c9477, bg: 0xe3f5ef, hex: '#2c9477' },
  reinforced: { label: '强化护盾', short: '强化', color: 0xd48817, bg: 0xfef2da, hex: '#d48817' },
  concept:    { label: '概念护盾', short: '概念', color: 0xc44569, bg: 0xfce7ee, hex: '#c44569' },
};

export const STATUS_COLORS = {
  强壮: 0xd46e1a,
  虚弱: 0x8f7e6a,
  迅捷: 0x1d9470,
  束缚: 0x8f673c,
  烧伤: 0xd94524,
  裂血: 0xc22738,
  呼吸: 0x24967c,
  失衡: 0xbf9119,
  致命失衡: 0xd4223a,
  充能: 0x269463,
  纯能: 0x52a336,
  能源: 0x739c22,
  能源封印: 0x8a7360,
  涡流: 0x1b8f74,
  校准: 0xc77e16,
  置卡机会: 0xc48b1a,
  换卡机会: 0x278f73,
  骰子等级降低: 0xad584c,
  骰级免疫: 0x32965e,
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

/**
 * Format a die's exact numerical range as players actually read it (e.g. "1~12", "2+1~8", "1~10").
 * NEVER outputs "Lv.2"!
 */
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

/**
 * Exact printed traits of a skill (verbatim terminology, zero invented shorthand).
 */
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

export function drawDieIcon(g, type, cx, cy, r, colorOverride = null) {
  const col = colorOverride ?? (DIE_STYLE[type]?.color || INK.secondary);
  if (type === 'slash') {
    g.moveTo(cx - r * 0.7, cy + r * 0.7)
      .lineTo(cx + r * 0.75, cy - r * 0.75)
      .stroke({ width: 2.2, color: col, cap: 'round' });
    g.moveTo(cx - r * 0.25, cy - r * 0.55)
      .quadraticCurveTo(cx + r * 0.55, cy - r * 0.52, cx + r * 0.55, cy + r * 0.32)
      .stroke({ width: 1.6, color: col, alpha: 0.85, cap: 'round' });
  } else if (type === 'pierce') {
    g.moveTo(cx - r * 0.68, cy + r * 0.68)
      .lineTo(cx + r * 0.45, cy - r * 0.45)
      .stroke({ width: 2, color: col, cap: 'round' });
    g.poly([
      cx + r * 0.8, cy - r * 0.8,
      cx + r * 0.08, cy - r * 0.56,
      cx + r * 0.56, cy - r * 0.08,
    ]).fill({ color: col });
  } else if (type === 'blunt') {
    g.moveTo(cx - r * 0.64, cy + r * 0.64)
      .lineTo(cx + r * 0.1, cy - r * 0.1)
      .stroke({ width: 2.1, color: col, cap: 'round' });
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
    ]).fill({ color: col, alpha: 0.2 }).stroke({ width: 1.8, color: col });
    g.moveTo(cx, cy - r * 0.5).lineTo(cx, cy + r * 0.5).stroke({ width: 1.4, color: col });
  } else if (type === 'evade') {
    g.moveTo(cx - r * 0.72, cy + r * 0.18)
      .lineTo(cx, cy - r * 0.54)
      .lineTo(cx + r * 0.72, cy + r * 0.18)
      .stroke({ width: 2.1, color: col, cap: 'round', join: 'round' });
    g.moveTo(cx - r * 0.48, cy + r * 0.6)
      .lineTo(cx, cy + r * 0.12)
      .lineTo(cx + r * 0.48, cy + r * 0.6)
      .stroke({ width: 1.6, color: col, alpha: 0.75, cap: 'round', join: 'round' });
  } else {
    g.roundRect(cx - r * 0.58, cy - r * 0.58, r * 1.16, r * 1.16, 2)
      .stroke({ width: 1.6, color: col, alpha: 0.85 });
    g.moveTo(cx - r * 0.38, cy - r * 0.38)
      .lineTo(cx + r * 0.38, cy + r * 0.38)
      .stroke({ width: 1.3, color: col, alpha: 0.7 });
  }
}

/**
 * Limbus-Company-style unmistakable vector icon per status effect (no truncated 3-char text boxes!).
 */
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
  g.poly(pts).fill({ color: st.bg }).stroke({ width: 1.7, color: st.color });
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
  g.circle(cx, cy, outerR * 0.66).stroke({ width: 1.2, color, alpha: alpha * 0.45 });
  g.circle(cx, cy, outerR * 0.16).fill({ color: INK.paper, alpha: 1 });
}

export function buildCardBack(side = 1, { width = 136, height = 188 } = {}) {
  const theme = SIDE_THEME[side] || SIDE_THEME[1];
  const root = new PIXI.Container();
  const hw = width / 2;
  const hh = height / 2;

  const g = new PIXI.Graphics();
  g.roundRect(-hw + 3, -hh + 5, width, height, 11).fill({ color: INK.shadow, alpha: 0.32 });
  g.roundRect(-hw, -hh, width, height, 10)
    .fill({ color: INK.paper })
    .stroke({ width: 2, color: theme.accent, alpha: 0.9 });
  g.roundRect(-hw + 7, -hh + 7, width - 14, height - 14, 6)
    .fill({ color: theme.softBg })
    .stroke({ width: 1, color: theme.border, alpha: 0.65 });
  drawLightStar(g, 0, 0, Math.min(width, height) * 0.25, theme.accent, 0.88);
  root.addChild(g);
  return root;
}

/**
 * Library-of-Ruina style compact card face for hand & board:
 *  - Shows Cost, Exact Name, Exact Range/Trait markers (only if present)
 *  - Shows each Die as [Die Icon] [Exact Range 1~12] + exact pure-damage line if short + [◆] marker if full text exists
 *  - NEVER paraphrases, NEVER summarizes, NEVER prints "Lv.2", NEVER truncates sentences!
 */
export function buildCardFront(card, {
  side = 1,
  ownerName = '',
  showOwner = false,
  width = 138,
  height = 190,
  legal = true,
  selected = false,
  activeDieNumber = null,
  rangeDeficit = 0,
  playMode = null,
} = {}) {
  const theme = SIDE_THEME[side] || SIDE_THEME[1];
  const root = new PIXI.Container();
  const hw = width / 2;
  const hh = height / 2;
  const isBlanked = rangeDeficit >= 3;

  const g = new PIXI.Graphics();
  g.roundRect(-hw + 3, -hh + 6, width, height, 12).fill({ color: INK.shadow, alpha: selected ? 0.42 : 0.3 });
  if (selected) {
    g.roundRect(-hw - 3, -hh - 3, width + 6, height + 6, 13).stroke({ width: 3, color: INK.gold });
  }
  const borderCol = isBlanked ? INK.muted : selected ? INK.gold : legal ? theme.accent : INK.line;
  g.roundRect(-hw, -hh, width, height, 10)
    .fill({ color: isBlanked ? 0xf2eee6 : INK.paper })
    .stroke({ width: selected ? 2.4 : 1.7, color: borderCol });

  // Clean header crest
  const headerH = showOwner || card.range_level || card.pre_reveal || card.anytime_replace || (card.anytime_play && card.anytime_play.length) ? 44 : 38;
  g.roundRect(-hw + 2, -hh + 2, width - 4, headerH, 8).fill({ color: isBlanked ? 0xe8e2d7 : theme.softBg });
  g.moveTo(-hw + 6, -hh + headerH + 2).lineTo(hw - 6, -hh + headerH + 2).stroke({ width: 1, color: borderCol, alpha: 0.35 });

  // Cost circle
  const cx = -hw + 20;
  const cy = -hh + headerH / 2 + 1;
  g.circle(cx, cy, 13).fill({ color: isBlanked ? INK.muted : theme.accent });
  root.addChild(g);

  const costTxt = new PIXI.Text({
    text: String(card.cost ?? 0),
    style: { fontFamily: FONT_NUM, fontSize: 15, fontWeight: '800', fill: INK.paper },
  });
  costTxt.anchor.set(0.5);
  costTxt.position.set(cx, cy + 0.5);
  root.addChild(costTxt);

  const nameTxt = new PIXI.Text({
    text: card.name || '',
    style: {
      fontFamily: FONT_UI,
      fontSize: card.name && card.name.length > 5 ? 11.5 : 13,
      fontWeight: '800',
      fill: isBlanked ? INK.muted : INK.primary,
    },
  });
  nameTxt.anchor.set(0, 0.5);
  nameTxt.position.set(-hw + 37, headerH > 38 ? -hh + 15 : cy);
  root.addChild(nameTxt);

  if (headerH > 38) {
    const bits = [];
    if (showOwner && ownerName) bits.push(ownerName);
    if (card.range_level) bits.push(RANGE_LABELS[card.range_level]);
    if (card.pre_reveal) bits.push('开牌前');
    if (card.anytime_play && card.anytime_play.length) bits.push('任意打出');
    if (card.anytime_replace) bits.push('任意替换');
    if (card.interceptable === false) bits.push('不可拦截');
    const subTxt = new PIXI.Text({
      text: bits.slice(0, 2).join(' · '),
      style: { fontFamily: FONT_UI, fontSize: 9.5, fontWeight: '700', fill: card.range_level ? INK.gold : theme.accent },
    });
    subTxt.anchor.set(0, 0.5);
    subTxt.position.set(-hw + 37, -hh + 33);
    root.addChild(subTxt);
  }

  // Play mode / suppression badge
  if (playMode || rangeDeficit > 0) {
    const tagG = new PIXI.Graphics();
    const label = rangeDeficit > 0 ? `压制-${rangeDeficit}` : playMode === 'pulled' ? '被牵制' : playMode === 'passive' ? '迎击' : '主动';
    const col = rangeDeficit > 0 ? 0xcf4330 : playMode === 'pulled' ? INK.gold : theme.accent;
    tagG.roundRect(hw - 42, -hh - 8, 40, 16, 6).fill({ color: col });
    root.addChild(tagG);
    const t = new PIXI.Text({
      text: label,
      style: { fontFamily: FONT_UI, fontSize: 9, fontWeight: '700', fill: INK.paper },
    });
    t.anchor.set(0.5);
    t.position.set(hw - 22, -hh);
    root.addChild(t);
  }

  // Clean Library-of-Ruina Dice Column: [Icon] [1~12] + exact pure damage string if present + indicator dot if verbatim text exists
  const dice = card.dice || [];
  const hasSkillEntries = !isBlanked && card.entries && card.entries.length > 0;
  const startY = -hh + headerH + 8;
  const maxRows = Math.min(dice.length, 5);
  const footSpace = hasSkillEntries ? 22 : 8;
  const availH = height - headerH - 10 - footSpace;
  const rowH = maxRows ? Math.min(28, Math.floor(availH / maxRows) - 3) : 24;

  const rowG = new PIXI.Graphics();
  root.addChild(rowG);

  for (let i = 0; i < maxRows; i++) {
    const die = dice[i];
    const ry = startY + i * (rowH + 3);
    const isActive = activeDieNumber === i + 1;
    const isSpent = activeDieNumber !== null && i + 1 < activeDieNumber;
    const dType = isBlanked ? 'blank' : die.type;
    const ds = DIE_STYLE[dType] || DIE_STYLE.blank;

    rowG.roundRect(-hw + 7, ry, width - 14, rowH, 5)
      .fill({ color: isActive ? INK.goldBg : ds.bg, alpha: isSpent ? 0.45 : 1 })
      .stroke({ width: isActive ? 1.8 : 1, color: isActive ? INK.gold : ds.color, alpha: isSpent ? 0.3 : 0.72 });

    drawDieIcon(rowG, dType, -hw + 19, ry + rowH / 2, 7.2, isSpent ? INK.muted : ds.color);

    const rangeText = formatDieRange(die);
    const rngTxt = new PIXI.Text({
      text: rangeText,
      style: { fontFamily: FONT_NUM, fontSize: 12.5, fontWeight: '800', fill: isSpent ? INK.muted : INK.primary },
    });
    rngTxt.anchor.set(0, 0.5);
    rngTxt.position.set(-hw + 32, ry + rowH / 2);
    root.addChild(rngTxt);

    if (!isBlanked && die.entries && die.entries.length) {
      // Only extract literal pure damage entry (e.g. "1 点普通伤害" -> exact damage number + grade), never paraphrase effects!
      const pureDmg = die.entries.find((e) => /^\d+\s*点?(?:普通伤害|穿甲伤害|超穿甲伤害|物理|穿甲|超穿甲)$/.test(e.trim()));
      const hasOtherText = die.entries.some((e) => e !== pureDmg);
      let rx = hw - 10;
      if (hasOtherText) {
        rowG.poly([rx - 4, ry + rowH / 2 - 4, rx, ry + rowH / 2, rx - 4, ry + rowH / 2 + 4, rx - 8, ry + rowH / 2])
          .fill({ color: isSpent ? INK.muted : ds.color, alpha: 0.85 });
        rx -= 12;
      }
      if (pureDmg) {
        const cleanDmg = pureDmg.replace(/\s+/g, '').replace('点普通伤害', '普通').replace('点穿甲伤害', '穿甲').replace('点超穿甲伤害', '超穿甲');
        const dt = new PIXI.Text({
          text: cleanDmg,
          style: { fontFamily: FONT_UI, fontSize: 10, fontWeight: '700', fill: isSpent ? INK.muted : ds.color },
        });
        dt.anchor.set(1, 0.5);
        dt.position.set(rx, ry + rowH / 2);
        root.addChild(dt);
      }
    }
  }

  // Subtle literal marker if skill has card-level verbatim entries (no fake summary!)
  if (hasSkillEntries) {
    const fy = hh - 19;
    rowG.moveTo(-hw + 12, fy - 4).lineTo(hw - 12, fy - 4).stroke({ width: 1, color: INK.line });
    const countTxt = new PIXI.Text({
      text: `◆ ${card.entries.length} 条技能词条`,
      style: { fontFamily: FONT_UI, fontSize: 9.5, fontWeight: '700', fill: INK.secondary },
    });
    countTxt.anchor.set(0.5);
    countTxt.position.set(0, fy + 5);
    root.addChild(countTxt);
  }

  if (!legal) {
    const wash = new PIXI.Graphics();
    wash.roundRect(-hw, -hh, width, height, 10).fill({ color: 0xf4efe4, alpha: 0.5 });
    root.addChild(wash);
  }
  return root;
}

/**
 * Wide, crystal-clear, 100% VERBATIM Card Panel (Library-of-Ruina Combat Page style).
 * ZERO paraphrasing, ZERO "Lv.2", ZERO "无附加词条", ZERO annotation/flavor text!
 */
export function buildVerbatimCardPanel(card, { side = 1, ownerName = '', width = 376 } = {}) {
  const theme = SIDE_THEME[side] || SIDE_THEME[1];
  const W = width;
  const root = new PIXI.Container();
  const content = new PIXI.Container();
  let cursorY = 58;

  // Exact printed traits (ONLY if present)
  const traits = exactSkillTraits(card);
  if (traits.length) {
    const tTxt = new PIXI.Text({
      text: wrapCjkText(traits.join(' · '), Math.floor((W - 32) / 6.5)),
      style: {
        fontFamily: FONT_UI,
        fontSize: 12,
        fontWeight: '700',
        fill: INK.gold,
        lineHeight: 18,
        wordWrap: true,
        breakWords: true,
        wordWrapWidth: W - 32,
      },
    });
    tTxt.position.set(16, cursorY);
    content.addChild(tTxt);
    cursorY += tTxt.height + 10;
  }

  // 100% Verbatim Skill-Level Entries (ONLY if present)
  if (card.entries && card.entries.length) {
    const joined = card.entries.join('\n');
    const txt = new PIXI.Text({
      text: wrapCjkText(joined, Math.floor((W - 44) / 6.8)),
      style: {
        fontFamily: FONT_UI,
        fontSize: 12.5,
        fill: INK.primary,
        lineHeight: 19,
        wordWrap: true,
        breakWords: true,
        wordWrapWidth: W - 44,
      },
    });
    const box = new PIXI.Graphics();
    box.roundRect(14, cursorY, W - 28, txt.height + 14, 7)
      .fill({ color: INK.paperSoft })
      .stroke({ width: 1, color: INK.line });
    txt.position.set(22, cursorY + 7);
    content.addChild(box, txt);
    cursorY += txt.height + 22;
  }

  // 100% Verbatim Dice Stack (Icon + Exact Range on left, Verbatim entries on right — EMPTY if none!)
  const leftColW = 92;
  const textColX = 14 + leftColW + 10;
  const textColW = W - textColX - 20;
  const maxDieChars = Math.max(24, Math.floor(textColW / 6.5));

  for (const die of card.dice || []) {
    const ds = DIE_STYLE[die.type] || DIE_STYLE.blank;
    const entries = (die.entries || []).filter(Boolean);
    let bodyTxt = null;
    if (entries.length) {
      bodyTxt = new PIXI.Text({
        text: wrapCjkText(entries.join('\n'), maxDieChars),
        style: {
          fontFamily: FONT_UI,
          fontSize: 12.5,
          fill: INK.primary,
          lineHeight: 18.5,
          wordWrap: true,
          breakWords: true,
          wordWrapWidth: textColW,
        },
      });
    }
    const rowH = Math.max(36, bodyTxt ? bodyTxt.height + 14 : 36);
    const rowBg = new PIXI.Graphics();
    rowBg.roundRect(14, cursorY, W - 28, rowH, 7)
      .fill({ color: ds.bg })
      .stroke({ width: 1.2, color: ds.color, alpha: 0.72 });

    // Die icon + exact range (e.g. "1~12", NO "Lv.4"!)
    const midY = cursorY + Math.min(rowH / 2, 18);
    drawDieIcon(rowBg, die.type, 29, midY, 8.5, ds.color);
    const rngTxt = new PIXI.Text({
      text: formatDieRange(die),
      style: { fontFamily: FONT_NUM, fontSize: 14, fontWeight: '900', fill: ds.color },
    });
    rngTxt.anchor.set(0, 0.5);
    rngTxt.position.set(44, midY);

    content.addChild(rowBg, rngTxt);
    if (bodyTxt) {
      bodyTxt.position.set(textColX, cursorY + (entries.length === 1 && bodyTxt.height < 22 ? (rowH - bodyTxt.height) / 2 : 7));
      content.addChild(bodyTxt);
    }
    cursorY += rowH + 6;
  }

  const H = Math.max(120, cursorY + 10);
  const bg = new PIXI.Graphics();
  bg.roundRect(4, 7, W, H, 13).fill({ color: INK.shadow, alpha: 0.36 });
  bg.roundRect(0, 0, W, H, 12)
    .fill({ color: INK.paper, alpha: 0.99 })
    .stroke({ width: 2, color: theme.accent });
  bg.roundRect(2, 2, W - 4, 48, 10).fill({ color: theme.softBg });
  bg.circle(26, 26, 15).fill({ color: theme.accent });
  root.addChild(bg);

  const cTxt = new PIXI.Text({
    text: String(card.cost ?? 0),
    style: { fontFamily: FONT_NUM, fontSize: 17, fontWeight: '800', fill: INK.paper },
  });
  cTxt.anchor.set(0.5);
  cTxt.position.set(26, 26);
  root.addChild(cTxt);

  const titleTxt = new PIXI.Text({
    text: card.name || '',
    style: { fontFamily: FONT_UI, fontSize: 16.5, fontWeight: '800', fill: INK.primary },
  });
  titleTxt.anchor.set(0, 0.5);
  titleTxt.position.set(49, 26);
  root.addChild(titleTxt);

  if (ownerName) {
    const owTxt = new PIXI.Text({
      text: ownerName,
      style: { fontFamily: FONT_UI, fontSize: 12, fontWeight: '700', fill: theme.accent },
    });
    owTxt.anchor.set(1, 0.5);
    owTxt.position.set(W - 16, 26);
    root.addChild(owTxt);
  }

  root.addChild(content);
  root._boxWidth = W;
  root._boxHeight = H;
  return root;
}
