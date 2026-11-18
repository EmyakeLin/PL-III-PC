# 生成源变量与参数

所有几何单位为 SVG 用户单位，在本图中对应 px。坐标均相对当前分组。

| 作用域 | 名称 | 含义 |
|---|---|---|
| ui_primitives 全局 | OUT | 源文件所在输出目录 |
| ui_primitives 全局 | C | 背景 bg、纸面 paper、卡面 white、文字 ink、辅助 muted、边界 line、己方 green、浅绿 pale、敌方 red、浅红 rose、辅助 blue/gold 的颜色映射 |
| ui_primitives 全局 | parts | 顺序积累 SVG 片段的列表 |
| emit / text | s | SVG 片段或转义前的显示内容 |
| 几何函数共用 | x, y | 左上角定位；text 中 y 为基线 |
| box / badge / button | w, h | 外框宽、高；按钮高固定 44 |
| box | fill, stroke, cut | 颜色令牌键与切角深度 |
| box | right, bottom, near, far, topcut, bottomcut | 外框右/下边、切角起止点；由坐标、尺寸和切角深度计算 |
| text / lines / crest | size, color | 字号或徽记边长、颜色令牌键 |
| text | weight | 字重 |
| line | x2, y2, width | 终点坐标及描边宽度 |
| button / badge | label | 控件可见文字 |
| button | kind, fill, color, labelx, labely | 语义变体、推导颜色及文字安全区基线 |
| lines | rows, gap, index, row, baseline | 多行内容、行距、行索引、当前行、计算后的基线 |
| badge | tx, ty | 标签文字位置 |
| icon | kind, shapes | 骰子类型及统一路径映射 |
| frame | index, title, sub, col, row, x, y | 画面索引、名称、状态注释、三列网格位置和画面原点 |
| end | note | 当前画面的入口、结果和返回关系注释 |
| section | title, detail | 区域标题与辅助说明 |
| stat（保留组件） | name, hp, maxhp, light, maxlight, extra, enemy, accent | 角色名、双生命数值、补充说明、敌方标记和推导强调色；本项目未调用旧双生命组件 |
| card | name, owner, cost, dice, selected | 技能名、所属角色、费用、骰子行数据、选择状态 |
| card | index, kind, roll, damage, dy | 骰子序号、类型、公式、效果摘要、行位置 |
| fighter | name, hp, maximum, enemy, used, personal, accent | 名称、当前/最大生命、阵营、已占交锋、剩余个人费、阵营色 |
| generate 场景循环 | index, name, cost, desc, cx | 手牌序号、名称、费值、骰子摘要、卡片水平位置 |
| generate 选人循环 | hp, skills | 角色生命与技能数说明 |
| generate 护盾循环 | label, value | 护盾名称与层数 |

静态生成器中的字面坐标用于图版排版；它不是前端运行时代码。业务数据、费用与骰子结果均是具体示例，不能将其写成产品固定值。

## 第二版新增变量（generate.py）

| 作用域 | 名称 | 含义 |
|---|---|---|
| 全局 | DATA, SKILLS, KINDS, SIZES | 卡包快照、附带所属角色的技能序列、骰子类型中文映射、等级对应面数 |
| anchor | name | 可查找的SVG元素标识 |
| scroll | offset, fraction | 滚动条起点和可见比例；横向按宽、纵向按高计算 |
| tick | on, disabled | 勾选值与不可操作状态 |
| header / board | phase | 当前回合阶段及操作方 |
| player | name, hp, used, personal, enemy, accent | 角色名、生命文本、已占交锋、剩余个人费、敌方标记及强调色 |
| smallcard / skillbody | skill, selected | 卡包技能数据与选择态 |
| board | placed, revealed, empty, paused | 已扣置、已开牌、无手牌、暂停状态 |
| skillbody | i, die, dy, label, effect | 骰子位次、骰子数据、行坐标、类型中文、伤害及词条摘要 |
| 场景循环 | i, j, k, x, y, cx, sy, local, page, char, skill, title, detail, note, label, action, on, before, after, formula, shield, rows, body, score, kind, left, right, result, nextlabel, value, names, name, tab, color | 当前项与索引、布局坐标、分页索引、角色/技能数据、可见文案与状态；几何坐标为px，文本来自对应场景 |
| 覆盖声明 | flows, name, route, nodes, i, target, node, coverage | 流程集合、流程名、画面序列、节点集合、节点序号、画面目标、节点对象及最终覆盖声明 |
