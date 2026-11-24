// Run from repo root: node --import ./tests/frontend/register.mjs --test tests/frontend/test_data_driven_display.mjs
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Text } from './pixi_stub.mjs';

const ENGINE = new URL('../../battle_ui/static/engine/', import.meta.url);
const {
  INK,
  DIE_STYLE,
  DAMAGE_GRADE_STYLE,
  TRIGGER_STYLE,
  classifyTriggerSeries,
  parseTriggerSegments,
  formatDieRange,
  formatDamagePart,
  resolveDieDamageParts,
  buildRichVerbatimText,
  buildUnifiedDieRow,
  buildUnifiedSkillRow,
  resolveDualForms,
  dualFormBadgeLabel,
} = await import(new URL('design_system.js', ENGINE));
const {
  buildFullCard,
  buildBoardCardTag,
  buildUniformCard,
  buildCompanionFormCard,
  buildDualFormSpread,
} = await import(new URL('card_print.js', ENGINE));
const { CombatTabletop } = await import(new URL('combat_tabletop.js', ENGINE));

const collectTexts = (node, out = []) => {
  if (node instanceof Text) out.push({ text: node.text, fill: node.style?.fill });
  for (const c of node.children || []) collectTexts(c, out);
  return out;
};

test('range pressure changes only the dice reported blank by the combat engine', () => {
  const card = {
    name: '逐骰核对', cost: 0, range_deficit: 3,
    dice: [
      { type: 'slash', roll_max: 6, entries: ['首骰词条'] },
      { type: 'pierce', roll_max: 8, entries: ['次骰词条'] },
      { type: 'block', roll_max: 12, entries: ['末骰词条'] },
    ],
  };
  for (const firstType of [null, 'blank', 'slash']) {
    card.live_dice = firstType ? [{ position: 1, type: firstType }, { position: 2, type: 'pierce' }] : [];
    for (const builder of [buildUniformCard, buildFullCard, buildBoardCardTag]) {
      const texts = collectTexts(builder(card, { width: 240, height: 320, rangeDeficit: 3 }));
      for (const [range, type] of [['1~6', firstType ?? 'slash'], ['1~8', 'pierce'], ['1~12', 'block']]) {
        assert.ok(texts.some(t => t.text === range && t.fill === DIE_STYLE[type].color), range);
      }
      if (builder !== buildBoardCardTag) {
        assert.equal(texts.some(t => t.text === '首骰词条'), firstType !== 'blank');
        assert.ok(texts.some(t => t.text === '次骰词条'));
        assert.ok(texts.some(t => t.text === '末骰词条'));
      }
    }
  }
});

test('settled clash dice retain win/loss colors on the table, in the detail view and in duel history', () => {
  const card = {
    name: '闪回识破', cost: 0, used: true, dissolved: true,
    dice: [
      { type: 'evade', roll_max: 20, no_hit_carrier: true, entries: ['仅非空白骰可见'] },
      { type: 'slash', roll_max: 20, ignore_range: 3, entries: ['施加2裂伤'] },
    ],
    live_dice: [
      { position: 1, type: 'blank', result: 'lose', clash_score: 4 },
      { position: 2, type: 'slash', result: 'win', clash_score: 11 },
    ],
  };
  const slot = { sides: [{ side: 1, cards: [], resolved_cards: [card] }] };
  assert.deepEqual(CombatTabletop.prototype._pickSideCards(slot, 1), [card]);
  for (const builder of [buildUniformCard, buildFullCard, buildBoardCardTag]) {
    const texts = collectTexts(builder(card, { width: 240, height: 320, rangeDeficit: 3 }));
    assert.ok(texts.some(t => t.text.startsWith('1~20') && t.fill === 0xb83a2a));
    assert.ok(texts.some(t => t.text.startsWith('1~20') && t.fill === INK.goldDeep));
    if (builder !== buildBoardCardTag) {
      assert.ok(texts.some(t => t.text === '无受击载体'));
      assert.ok(texts.some(t => t.text === '施加2裂伤'));
      assert.ok(!texts.some(t => t.text === '仅非空白骰可见'));
    }
  }
});

test('trigger series classification covers all 5 canonical color rules', () => {
  // 使用系列 -> 蓝色
  for (const name of ['使用时', '使用前', '使用后', '用骰前', '用骰时', '用骰后']) {
    assert.equal(classifyTriggerSeries(name), 'use', name);
    assert.equal(TRIGGER_STYLE[classifyTriggerSeries(name)].color, TRIGGER_STYLE.use.color);
  }
  // 命中系列 -> 黄绿色
  for (const name of ['命中时', '命中前', '命中后', '暴击时']) {
    assert.equal(classifyTriggerSeries(name), 'hit', name);
    assert.equal(TRIGGER_STYLE[classifyTriggerSeries(name)].color, TRIGGER_STYLE.hit.color);
  }
  // 拼点胜利系列 -> 橙色
  for (const name of ['拼点胜利', '拼点胜利时', '拼赢时']) {
    assert.equal(classifyTriggerSeries(name), 'clash_win', name);
    assert.equal(TRIGGER_STYLE[classifyTriggerSeries(name)].color, TRIGGER_STYLE.clash_win.color);
  }
  // 拼点失败系列 -> 红色
  for (const name of ['拼点失败', '拼点失败时', '拼输时', '拼负时']) {
    assert.equal(classifyTriggerSeries(name), 'clash_lose', name);
    assert.equal(TRIGGER_STYLE[classifyTriggerSeries(name)].color, TRIGGER_STYLE.clash_lose.color);
  }
  // 其他默认 -> 黄绿色
  for (const name of ['回合开始', '回合结束', '战斗开始', '开牌前', '状态变动时', '防摧毁']) {
    assert.equal(classifyTriggerSeries(name), 'default', name);
    assert.equal(TRIGGER_STYLE[classifyTriggerSeries(name)].color, TRIGGER_STYLE.hit.color);
  }
  // Distinct RGB hues across the 4 series
  assert.notEqual(TRIGGER_STYLE.use.color, TRIGGER_STYLE.hit.color);
  assert.notEqual(TRIGGER_STYLE.clash_win.color, TRIGGER_STYLE.clash_lose.color);
  assert.notEqual(TRIGGER_STYLE.clash_win.color, TRIGGER_STYLE.hit.color);
  assert.notEqual(TRIGGER_STYLE.clash_lose.color, TRIGGER_STYLE.use.color);
});

test('parseTriggerSegments replaces 【name】 with [ name ] using pure scanning and handles edge cases', () => {
  const segs = parseTriggerSegments('【使用时】失去1生命；本回合首次【拼点失败】施加2电击。');
  assert.deepEqual(
    segs.map((s) => [s.kind, s.text, s.series || null]),
    [
      ['trigger', '[ 使用时 ]', 'use'],
      ['text', '失去1生命；本回合首次', null],
      ['trigger', '[ 拼点失败 ]', 'clash_lose'],
      ['text', '施加2电击。', null],
    ],
  );
  // Edge cases: plain text without triggers produces zero trigger spans; unclosed/empty brackets stay text
  assert.deepEqual(parseTriggerSegments('本技能不会被任何效果摧毁、无效（最高话语权）').map((s) => [s.kind, s.text]), [
    ['text', '本技能不会被任何效果摧毁、无效（最高话语权）'],
  ]);
  assert.deepEqual(parseTriggerSegments('无闭合【测试').map((s) => [s.kind, s.text]), [['text', '无闭合【测试']]);
  assert.deepEqual(parseTriggerSegments('空【】标记').map((s) => [s.kind, s.text]), [
    ['text', '空'], ['text', '【】'], ['text', '标记'],
  ]);
});

test('buildRichVerbatimText colors each trigger series distinctly and mutes when spent', () => {
  const line = '【使用时】抽1卡；【命中时】施加1烧伤；【拼点胜利】回复1；【拼点失败】驻留；【回合开始】获得1能源。';
  const node = buildRichVerbatimText(line, { maxWidth: 400 });
  const texts = collectTexts(node);
  const byText = new Map(texts.map((t) => [t.text, t.fill]));
  assert.equal(byText.get('[ 使用时 ]'), TRIGGER_STYLE.use.color);
  assert.equal(byText.get('[ 命中时 ]'), TRIGGER_STYLE.hit.color);
  assert.equal(byText.get('[ 拼点胜利 ]'), TRIGGER_STYLE.clash_win.color);
  assert.equal(byText.get('[ 拼点失败 ]'), TRIGGER_STYLE.clash_lose.color);
  assert.equal(byText.get('[ 回合开始 ]'), TRIGGER_STYLE.default.color);

  const muted = buildRichVerbatimText(line, { maxWidth: 400, muted: true });
  for (const t of collectTexts(muted)) {
    assert.equal(t.fill, INK.muted);
  }
});

test('die row reads type, numeric range, and structured damage_parts with normal first and concise labels', () => {
  assert.equal(formatDamagePart({ amount: 1, grade: 'normal' }), '1');
  assert.equal(formatDamagePart({ amount: 1, grade: 'real' }), '1 真实');
  assert.equal(formatDamagePart({ amount: 1, grade: 'normal', aoe: true }), '群体 1');
  assert.equal(formatDamagePart({ amount: 1, grade: 'pierce', aoe: true }), '群体 1 穿甲');
  assert.equal(formatDamagePart({ amount: '(能源值-1)', grade: 'lightcore' }), '(能源值-1) 光点');

  const structuredDie = {
    type: 'pierce',
    printed_level: 4,
    roll_max: 12,
    base_value: 2,
    multiplier: 2,
    final_bonus: 1,
    damage_parts: [
      { amount: 2, grade: 'pierce' },
      { amount: 1, grade: 'normal' },
      { amount: '(能源值-1)', grade: 'lightcore' },
    ],
    entries: ['【命中时】获得1能源。'],
  };
  assert.equal(formatDieRange(structuredDie), '(2+1~12)×2+1');
  assert.equal(formatDieRange({ type: 'skip' }), 'SKIP');
  const resolved = resolveDieDamageParts(structuredDie);
  assert.deepEqual(resolved.map((p) => p.text), ['1', '2 穿甲', '(能源值-1) 光点']);

  // Both narrow (slim hand card) and wide (codex/hover) widths MUST use the same concise labels with normal first
  for (const w of [160, 260]) {
    const row = buildUnifiedDieRow(structuredDie, { width: w, dense: w < 194 });
    const texts = collectTexts(row);
    assert.ok(texts.some((t) => t.text === '(2+1~12)×2+1' && t.fill === DIE_STYLE.pierce.color));
    const normalIdx = texts.findIndex((t) => t.text === '1' && t.fill === DAMAGE_GRADE_STYLE.normal.color);
    const pierceIdx = texts.findIndex((t) => t.text === '2 穿甲' && t.fill === DAMAGE_GRADE_STYLE.pierce.color);
    const lightIdx = texts.findIndex((t) => t.text === '(能源值-1) 光点' && t.fill === DAMAGE_GRADE_STYLE.lightcore.color);
    assert.ok(normalIdx >= 0 && pierceIdx > normalIdx && lightIdx > pierceIdx);
    assert.ok(!texts.some((t) => t.text.includes('点普通伤害') || t.text.includes('点穿甲伤害')));
    assert.ok(texts.some((t) => t.text === '[ 命中时 ]' && t.fill === TRIGGER_STYLE.hit.color));
  }

  // Pairwise contrast: raw "2 穿甲" inside entries with empty damage_parts MUST NOT become a damage badge!
  const textOnlyDie = {
    type: 'slash',
    printed_level: 3,
    roll_max: 8,
    damage_parts: [],
    entries: ['2 穿甲'],
  };
  assert.equal(resolveDieDamageParts(textOnlyDie).length, 0);
  const row2 = buildUnifiedDieRow(textOnlyDie, { width: 260 });
  const texts2 = collectTexts(row2);
  assert.ok(!texts2.some((t) => t.fill === DAMAGE_GRADE_STYLE.pierce.color));
});

test('buildFullCard and buildBoardCardTag read card.name, card.cost, and dice data directly (ignoring legacy printed_text)', () => {
  const card = {
    id: 'test_skill',
    name: '实际技能名',
    cost: 4,
    printed_text: '旧文本标题 99费\n旧文本行',
    entries: ['【使用时】获得2能源。'],
    dice: [
      {
        type: 'block',
        printed_level: 3,
        roll_max: 8,
        printed_line: '旧骰子行',
        damage_parts: [],
        entries: ['【拼点胜利】回复1生命。'],
      },
      {
        type: 'slash',
        printed_level: 2,
        roll_max: 6,
        damage_parts: [{ amount: 3, grade: 'concept', text: '3 超穿甲' }],
        entries: ['【拼点失败】驻留。'],
      },
    ],
  };

  for (const builder of [buildFullCard, buildBoardCardTag]) {
    const node = builder(card, { side: 1, width: 240 });
    const texts = collectTexts(node);
    assert.ok(texts.some((t) => t.text === '实际技能名'));
    assert.ok(texts.some((t) => t.text === '4'));
    assert.ok(texts.some((t) => t.text === '1~8' && t.fill === DIE_STYLE.block.color));
    assert.ok(texts.some((t) => t.text === '1~6' && t.fill === DIE_STYLE.slash.color));
    assert.ok(!texts.some((t) => t.text.includes('旧文本') || t.text.includes('旧骰子')));
  }

  const fullTexts = collectTexts(buildFullCard(card, { side: 1, width: 260 }));
  assert.ok(fullTexts.some((t) => t.text === '[ 使用时 ]' && t.fill === TRIGGER_STYLE.use.color));
  assert.ok(fullTexts.some((t) => t.text === '[ 拼点胜利 ]' && t.fill === TRIGGER_STYLE.clash_win.color));
  assert.ok(fullTexts.some((t) => t.text === '[ 拼点失败 ]' && t.fill === TRIGGER_STYLE.clash_lose.color));
  assert.ok(fullTexts.some((t) => t.text === '3 超穿甲' && t.fill === DAMAGE_GRADE_STYLE.concept.color));
});

test('dual-form skills render side-by-side without vertical scrolling and distinguish base vs transformed badges', () => {
  // 1. Liu Yin ultimate: 战甲塑造 ⇄ 肃清引信
  const liuBase = {
    id: 'liu_armor',
    name: '战甲塑造',
    cost: 5,
    active_form: null,
    active_form_label: '常态',
    entries: ['【使用时】获得3战甲。'],
    dice: [{ type: 'block', printed_level: 5, roll_max: 16, damage_parts: [], entries: [] }],
    dual_forms: [
      {
        id: 'liu_armor',
        name: '战甲塑造',
        cost: 5,
        form_key: null,
        form_label: '常态',
        is_active_form: true,
        entries: ['【使用时】获得3战甲。'],
        dice: [{ type: 'block', printed_level: 5, roll_max: 16, damage_parts: [], entries: [] }],
      },
      {
        id: 'liu_armor',
        name: '肃清引信',
        cost: 5,
        form_key: 'armored',
        form_label: '战甲≥1',
        is_active_form: false,
        entries: [],
        dice: [
          { type: 'skip', damage_parts: [], entries: [] },
          {
            type: 'blunt',
            printed_level: 1,
            roll_max: 4,
            multiplier: 2,
            damage_parts: [{ amount: '目标生命上限1/3（向上取整）', grade: 'concept', text: '目标生命上限1/3（向上取整） 超穿甲' }],
            entries: ['本骰子最终点数+领域洞悉'],
          },
        ],
      },
    ],
  };

  assert.equal(resolveDualForms(liuBase).length, 2);
  assert.equal(dualFormBadgeLabel(liuBase), '⇄肃清引信');

  const liuTransformed = {
    ...liuBase,
    name: '肃清引信',
    active_form: 'armored',
    active_form_label: '战甲≥1',
    dual_forms: [
      { ...liuBase.dual_forms[0], is_active_form: false },
      { ...liuBase.dual_forms[1], is_active_form: true },
    ],
  };
  assert.equal(dualFormBadgeLabel(liuTransformed), '◆战甲≥1');

  // 2. Lan Qing skill: 电叉·回环舞 (常态 ⇄ 活化态)
  const lanDance = {
    id: 'lan_dance_2',
    name: '电叉·回环舞',
    cost: 2,
    active_form: null,
    dual_forms: [
      {
        id: 'lan_dance_2',
        name: '电叉·回环舞',
        cost: 2,
        form_key: null,
        form_label: '常态',
        is_active_form: true,
        entries: [],
        dice: [{ type: 'slash', roll_max: 8, damage_parts: [{ amount: 1, grade: 'normal', text: '1' }], entries: ['【命中时】施加1电击。'] }],
      },
      {
        id: 'lan_dance_2',
        name: '电叉·回环舞',
        cost: 2,
        form_key: 'active',
        form_label: '活化态',
        is_active_form: false,
        entries: ['【使用时】本次使用活化态，消耗同名技能共享的1次活化。'],
        dice: [{ type: 'block', roll_max: 20, damage_parts: [], entries: ['【拼点胜利】施加3电击。'] }],
      },
    ],
  };
  assert.equal(dualFormBadgeLabel(lanDance), '⇄活化态');

  // Resting single-card views & skill row show the dual-form badge
  for (const node of [
    buildFullCard(liuBase, { width: 220 }),
    buildUniformCard(liuBase, { width: 220, height: 308 }),
    buildUnifiedSkillRow(liuBase, { width: 420 }),
  ]) {
    assert.ok(collectTexts(node).some((t) => t.text === '⇄肃清引信'));
  }

  // Side-by-side spread: strictly horizontal (x0 === 0, x1 === 216 + 18, y0 === y1 === 0), ZERO vertical scroll!
  const spread = buildDualFormSpread(liuTransformed, { side: 1, cardWidth: 216, gap: 18, liveContext: true });
  assert.equal(spread._boxWidth, 216 * 2 + 18);
  assert.equal(spread.maxScroll, undefined);
  const cardColumns = spread.children.filter((ch) => ch._boxWidth === 216);
  assert.equal(cardColumns.length, 2);
  assert.equal(cardColumns[0].x, 0);
  assert.equal(cardColumns[1].x, 234);
  assert.equal(cardColumns[0].y, 0);
  assert.equal(cardColumns[1].y, 0);
  assert.equal(cardColumns[0]._boxHeight, cardColumns[1]._boxHeight);

  const spreadTexts = collectTexts(spread).map((t) => t.text);
  assert.ok(spreadTexts.includes('战甲塑造'));
  assert.ok(spreadTexts.includes('肃清引信'));
  assert.ok(spreadTexts.includes('⇄ 另一形态 · 常态'));
  assert.ok(spreadTexts.includes('◆ 当前生效 · 战甲≥1'));
  assert.ok(spreadTexts.includes('⇄'));

  const comp = buildCompanionFormCard(lanDance.dual_forms[1], { width: 208, crestLabel: '⇄ 另一形态 · 活化态' });
  const compTexts = collectTexts(comp).map((t) => t.text);
  assert.ok(compTexts.includes('⇄ 另一形态 · 活化态'));
  assert.ok(compTexts.includes('电叉·回环舞'));
  assert.ok(compTexts.includes('1~20'));
});
