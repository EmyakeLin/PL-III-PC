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
  resolveDieDamageParts,
  buildRichVerbatimText,
  buildUnifiedDieRow,
} = await import(new URL('design_system.js', ENGINE));
const { buildFullCard, buildBoardCardTag } = await import(new URL('card_print.js', ENGINE));

const collectTexts = (node, out = []) => {
  if (node instanceof Text) out.push({ text: node.text, fill: node.style?.fill });
  for (const c of node.children || []) collectTexts(c, out);
  return out;
};

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
  // Edge cases: unclosed bracket and empty bracket do not loop or crash
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

test('die row reads type, numeric range, and structured damage_parts only (never regex-guesses text)', () => {
  const structuredDie = {
    type: 'pierce',
    printed_level: 4,
    roll_max: 12,
    base_value: 2,
    multiplier: 2,
    final_bonus: 1,
    damage_parts: [
      { amount: 2, grade: 'pierce', text: '2点穿甲伤害' },
      { amount: 1, grade: 'lightcore', text: '1点光点伤害' },
    ],
    entries: ['【命中时】获得1能源。'],
  };
  assert.equal(formatDieRange(structuredDie), '(2+1~12)×2+1');
  assert.equal(formatDieRange({ type: 'skip' }), 'SKIP');
  assert.equal(resolveDieDamageParts(structuredDie).length, 2);

  // Both narrow (slim hand card) and wide (codex/hover) widths MUST use the single canonical wording, never "2穿甲"/"1光点"
  for (const w of [160, 260]) {
    const row = buildUnifiedDieRow(structuredDie, { width: w, dense: w < 194 });
    const texts = collectTexts(row);
    assert.ok(texts.some((t) => t.text === '(2+1~12)×2+1' && t.fill === DIE_STYLE.pierce.color));
    assert.ok(texts.some((t) => t.text === '2点穿甲伤害' && t.fill === DAMAGE_GRADE_STYLE.pierce.color));
    assert.ok(texts.some((t) => t.text === '1点光点伤害' && t.fill === DAMAGE_GRADE_STYLE.lightcore.color));
    assert.ok(!texts.some((t) => t.text === '2穿甲' || t.text === '1光点'));
    assert.ok(texts.some((t) => t.text === '[ 命中时 ]' && t.fill === TRIGGER_STYLE.hit.color));
  }

  // Pairwise contrast: raw "2穿甲" inside entries with empty damage_parts MUST NOT become a damage badge!
  const textOnlyDie = {
    type: 'slash',
    printed_level: 3,
    roll_max: 8,
    damage_parts: [],
    entries: ['2穿甲'],
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
        damage_parts: [{ amount: 3, grade: 'concept', text: '3点超穿甲伤害' }],
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
  assert.ok(fullTexts.some((t) => t.text === '3点超穿甲伤害' && t.fill === DAMAGE_GRADE_STYLE.concept.color));
});
