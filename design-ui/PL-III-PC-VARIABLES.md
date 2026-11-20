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

## 浏览器对战 · 数据与操作

浏览器通过 `GET /api/state` 取得当前桌面，通过 `POST /api/action` 提交带版本号的操作。

| 返回字段或请求参数 | 含义与来源 |
|---|---|
| `mode` | 桌面暂停的位置。可取 `placement` 置卡、`handoff` 交接、`reveal` 开牌、`combat` 交锋、`turn_end` 回合末和 `finished` 终局。 |
| `frame`, `catalog` | `Displayer` 的当前局面与公开的印刷规则。置卡时使用当事方视角，其余阶段使用公开视角。 |
| `active_side`, `choices` | 当前置卡者或即将接手者的阵营号，公开结算时为空。选人项带有卡包中的 `id`、`name`、`title`、`rank`、`max_hp` 和 `faction`。 |
| `legal_cards`, `can_pass`, `window_remaining` | 当前可扣置的手牌 ID、能否提前交权、本窗口尚可扣置的张数，由角色存活情况、可用交锋和本窗口已扣张数推得。 |
| `history` | 最近 100 条公开事件，按发生顺序排列，供结算提示和战报查看。 |
| `action`, `card_id`, `roster` | 请求的操作名。`place` 携带所选技能 ID，`new` 携带两位玩家依次选定的不同角色 ID。`pass` 交权，`end` 结束本回合置卡，`ready` 确认接手，`next` 推进公开结算。 |
| `revision` | 客户端复制最近收到的桌面版本。服务端接受操作后递增，收到过期请求时返回最新局面。 |

### 对局适配器（battle_ui/match.py）

| 作用域 | 变量 | 含义 |
|---|---|---|
| `BattleMatch.__init__` | `roster`, `seed`, `initial_handoff` | 两位玩家的出战角色 ID 顺序、引擎随机种子、首个置卡窗口是否先遮牌交接。 |
| 建局与装配 | `pool`, `spec`, `key`, `choices` | 按角色 ID 索引的卡包定义、遍历到的角色条目、角色或字段的索引及供重开使用的选人清单。 |
| 建局与装配 | `players`, `player`, `character`, `game`, `side`, `_views` | 两位玩家、当前装配对象及其角色、真实游戏、阵营号，以及按阵营号和公开视角保存的只读适配器。 |
| 单局状态 | `mode`, `revision`, `_history`, `_window_size`, `_require_handoff` | 当前操作阶段、单局已接受操作序号、公开记录队列、本窗口容量（张）及下一窗口必须先交接的标志。 |
| `_TableGame.run_placement` | `placing`, `first_player`, `placed_this_window` | 持有置卡权的玩家、本回合先手及本窗口已扣张数。 |
| `snapshot`, `_legal_cards` | `placing`, `side`, `private`, `player`, `card`, `c` | 当前置卡者、行动方号、是否可展示该方私有区，以及读取手牌、筛选可置牌和复制选人项的循环对象。 |
| `act`, `_place_action`, `_open_window` | `action`, `revision`, `card_id`, `game`, `player`, `card`, `c`, `previous`, `switching` | 命令、预期单局版本、所选牌 ID、局面、操作者、匹配的手牌、候选牌、上一窗口操作者及本次是否换人。 |
| `_advance` | `game`, `node`, `count`, `message` | 正在推进的对局、刚完成的主节点或双阵营节点、揭开的交锋槽数及本次开牌记录。 |
| `_combat_stop` | `nodes`, `checkpoints`, `node`, `game`, `combat`, `side`, `player` | 本次推进两侧实际执行的节点、需要读取的节点名、当前节点、引擎、公开交锋快照、该侧管线的可见字段与对应玩家。 |
| `_combat_stop` | `character`, `die`, `pipe`, `verb`, `result`, `enemy`, `p`, `attack` | 出骰角色、实战骰快照、结算费用的管线、技能使用或支付失败用词、胜负字样、对手角色、选取对手时遍历的玩家及进攻类型文字。 |
| `_combat_stop`, `_finish` | `actions`, `scores`, `pause`, `winner`, `fallen` | 本节点的公开事件片段、拼点数及胜负、是否应停留展示、胜方及阵亡角色名。 |

### 本地 HTTP 会话（battle_ui/__main__.py）

| 作用域 | 变量 | 含义 |
|---|---|---|
| 启动入口 | `ASSETS`, `STATIC_DIR`, `parser`, `args`, `server` | 公开 URL 对应的文件名和媒体类型、静态资源目录、参数解析器、含 `port` 与 `seed` 的启动选项及监听回环地址的服务器。 |
| `BattleSession` | `seed`, `match`, `revision`, `lock` | 重开时沿用的随机种子、当前对局、跨重开的桌面版本及保护读取和提交的互斥锁。 |
| `command` | `request`, `action`, `roster`, `item`, `frame` | 浏览器发送的 JSON、操作名、重开的出战组合、待校验的角色 ID 及提交后返回的整份桌面数据。 |
| `_send`, `_json` | `status`, `body`, `content_type`, `data` | HTTP 状态码、已编码的响应字节、响应媒体类型及待编码的 JSON 数据。 |
| `_local_request`, `do_GET` | `port`, `hosts`, `host`, `origin`, `path`, `name`, `content_type` | 实际监听端口、允许的本机主机名集合、请求主机及来源、去掉查询串的路径、对应文件名和类型。 |
| `do_POST` | `size`, `request`, `status`, `frame`, `exc` | 请求体长度（字节）、解码后的动作、处理结果状态、返回桌面及面向玩家的校验错误。 |

### 战场样式（battle_ui/static/style.css）

| 作用域 | 参数 | 含义 |
|---|---|---|
| 页面与组件表面 | `--paper`, `--surface`, `--inset`, `--ink`, `--muted`, `--line`, `--line-strong` | 依次用于桌面底色、纸牌表面、内凹槽位、主要文字、辅助文字、细分隔线和高对比边界。 |
| 阵营与阶段 | `--green`, `--green-wash`, `--red`, `--red-wash`, `--gold` | 双方各自的文字和战旗色、对应的浅色衬底，以及居中阶段指示的颜色。 |
| 私有视角与角色 | `--acting`, `--acting-wash`, `--side-color`, `--side-wash` | 前两项随当前玩家改变选牌和操作的强调色，后两项在各角色栏内绑定该方颜色与底色。 |
| 字体 | `--sans`, `--serif`, `--digits` | 操作及正文、角色和卡名、回合数及生命数值的字体栈。 |
| 布局 | `--gutter`, `--board-width`, `--section-gap`, `--control-height`, `--hand-column` | 页面两侧留白、棋盘最大宽度、区块垂直间距、按钮目标高度和四列手牌的单列宽度。尺寸以 px 或随视口按 vw 计算，手牌列同时扣除三个列间距。 |
| 内部间距 | `--space-1`, `--space-2`, `--space-3`, `--space-4`, `--space-5`, `--space-6` | 从 4、8、12、16、24 到 32 px 的六级间距，供标签、骰子行、按钮组与面板使用。 |
| 形态与反馈 | `--corner`, `--far-corner`, `--button-cut`, `--fast`, `--shift`, `--ease` | 主按钮切角深度（px）、从远端扣除该深度的位置、由二者得到的轮廓、按钮反馈时间和布局变化时间（ms）、二者共用的缓动。 |

### 战场交互（battle_ui/static/app.js）

| 作用域 | 参数 | 含义 |
|---|---|---|
| 页面状态 | `match`, `selection`, `busy`, `pageGeneration`, `dialogGeneration`, `dialogTrigger`, `modal`, `hand` | 当前服务端快照、已选卡 ID、正在提交、页面和浮层各自的生命周期计数、打开详情的焦点来源、浮层根节点和手牌容器。计数用于丢弃过时的响应与退出动画。 |
| 中文文案与 DOM | `typeNames`, `ranks`, `phases`, `outcomes`, `byId`, `id` | 骰型、位阶、对局阶段、拼点结果的显示名称，以及用稳定 ID 定位已有控件的入口与参数。 |
| 元素和按钮模板 | `tag`, `className`, `text`, `node`, `label`, `primary`, `variant`, `activate`, `name`, `ns`, `svg`, `use` | 元素标签、样式类、显示文字、当前 DOM 节点、按钮文案及主次方案、激活回调，以及图形符号名称、命名空间、图标容器与符号引用。 |
| 读快照与图鉴 | `side`, `player`, `characterId`, `character`, `actor`, `collection`, `currentHand`, `card`, `printed` | 阵营、玩家、要查找的角色 ID、角色项、当前出战者、该方图鉴、当前私有手牌、具体技能与印刷规则。 |
| 浮层、战报、规则 | `title`, `build`, `body`, `actions`, `privateReset`, `generation`, `clearContents`, `animation`, `texts`, `list` | 标题、内容构建函数、正文与操作区、切私人视角时立即清空的标记、本次清理代次及函数、退出动画、待列出的词条与列表节点。 |
| 技能与角色详情 | `die`, `summary`, `row`, `range`, `damage`, `section`, `formula`, `used`, `shields`, `statusList`, `count`, `passives`, `passive`, `skill` | 当前印刷骰、是否为手牌摘要、骰子行、变动点数范围、印刷伤害片段、单骰详情、公式说明、已占交锋、各型护盾、状态与层数、被动清单及条目、正在查看的技能。 |
| 新对局 | `selectors`, `field`, `select`, `fighter`, `option`, `start`, `roster`, `validate`, `duplicate`, `other`, `item` | 两侧选择框及其标签、出战候选与选项、开局按钮、选定的两人、重复选择校验、是否重名及校验时比对的另一选择框。 |
| 双方角色栏 | `lead`, `meta`, `bar`, `stats`, `statsField`, `statuses`, `shieldNames`, `kind`, `amount`, `statusesField` | 先手标记、头衔与位阶、生命条、速度及费用文字和容器、状态摘要、盾名称映射、当前盾型与数值、状态容器。 |
| 槽位与拼点 | `duels`, `slots`, `vacancy`, `slot`, `group`, `cards`, `number`, `combat`, `active`, `info`, `parts` | 已有槽与用于绘制的槽序列、当前方可填入的空槽、具体槽、阵营牌组、可见牌、本槽号码、战斗帧、与该牌相符的活动方数据及其点数文字片段。 |
| 交锋序列组件 | `placing`, `pending`, `resolved`, `note`, `rail`, `index`, `left`, `right`, `indexLabel`, `waiting`, `emptyMessage`, `empty`, `back`, `detail`, `current` | 是否置卡、预备槽号、是否开牌、阶段提示、槽列表、序号、左右两侧、槽号标签、等待状态、空区文案和节点、牌背、明牌按钮与当前骰结果。 |
| 手牌与主操作 | `ownerName`, `tile`, `head`, `dice`, `ownHand`, `keepIds`, `tiles`, `owner`, `selected`, `legal`, `chosen`, `remaining`, `quota` | 持牌人名称、卡片按钮、牌头与骰序、己方手牌、应保留的 ID 和已有节点、持牌角色、当前选择、是否可置、此卡是否选中、剩余交锋与额度提示。 |
| 阶段切换与焦点 | `handoff`, `winner`, `finished`, `lastMessage`, `message`, `line`, `labels`, `state`, `previous`, `newMatch`, `wasHandoff`, `privateSideChanged`, `first`, `focus`, `p` | 交接状态、胜方、是否终局、最近的公开事件和最终文案及节点、主操作名称、服务端新旧快照、重开或离开交接标志、视角变化、交接后的首个操作和回退焦点，以及遍历中的玩家。 |
| 请求和事件 | `action`, `fields`, `request`, `response`, `payload`, `generation`, `event` | 动作名、附加参数、带版本的提交内容、HTTP 响应、服务端回包、请求发出时的页面代次，以及触发点击、取消或离开页面的事件。 |
| 开牌前交锋 | `deciding`, `early`, `earlyCombat`, `kind`, `target`, `targets`, `enemy`, `count`, `item` | 是否从手牌作决定、是否为开牌前槽、是否正在结算开牌前交锋、交锋类别、当前目标、可选目标（角色或常规槽）、敌方、目标槽的公开扣牌数及选择项。 |
| 远程和操作标签 | `ranges`, `traits`, `characteristics`, `primary`, `secondary` | 各远程等级对应的牌面名称、详情词条、手牌摘要，以及各阶段的主、次操作标签。 |
| 同屏接手与迎击 | `secondSeat`, `shared`, `dualRole`, `declaring`, `phaseName`, `attacking`, `pending`, `legalAttack`, `notes` | 可接手的另一方、双方皆可接手标记、兼有进攻和回应权标记、声明阶段及名称、自己的主动权、待回应场数、所选牌可否进攻和当前操作说明。 |
| 迎击选择框 | `duelSelect`, `duelField`, `cardSelect`, `cardField`, `group`, `attack`, `respond`, `pass` | 待迎击编号与标签、己方手牌与标签、进攻方已公开的牌组与本场进攻牌，以及对所选编号迎击或放行的操作。 |
| 空手回应 | `hasReplyCard` | 当前是否有可用于迎击的手牌，控制打出迎击牌按钮；空手时仍可明确放行。 |
| 公开等待时间 | `responseTimer`, `timing`, `clock`, `start`, `end`, `now`, `seconds`, `minutes`, `remainder`, `tick` | 页面刷新计时文字的任务、该场的公开时间记录与显示元素、声明与结束或观察时的毫秒时间、当前毫秒时间、经过的整秒与分秒显示，以及更新待回应场次文字的回调。 |
| 特殊行动入口 | `special_available`, `special_pending`, `special_timing`, `special`, `specialPanel`, `specialButton`, `opened` | 公开规则是否允许接手、即时进攻是否待迎击、当前时点文字、是否处于私有选牌或其公开交接、入口按钮及本次点击的打开状态。 |
| 特殊行动选择 | `special_options`, `move`, `index`, `select`, `option`, `chosen`, `available` | 当前接手方可执行的动作及其目标、本次遍历的动作和下标、选择框和各项、所选手牌是否已有默认项、是否至少有一项可执行。下标与本次快照版本共同提交。 |
| 迎击许可 | `canAttackInField`, `card.interceptable`, `card.instant_interceptable`, `slot.interceptable` | 技能是否允许场内主动进攻、牌面在开牌前及独立场内进攻时的迎击许可、本场声明时已确定的许可。牌面说明分别列出两个场合，交锋列表依声明时的许可区分直接就绪和放行。 |
| 即时交锋与牌面 | `special_duels`, `instant`, `anytime_play`, `anytime_replace`, `plays` | 已公开的即时交锋、该行是否为即时交锋、手牌可随时打出的方式、是否可随时换入、各打出方式的显示名称。 |

## 复制对战台

搬运者为每个模型保留一份独立回复草稿。席位更新只替换状态文字。剪贴板由整个页面共享，当前复制结束后另一席才可开始复制。两席可以各自提交回复。

| 文件与作用域 | 变量 | 含义与依赖 |
|---|---|---|
| desk.css | `--pane-gap`, `--row-gap`, `--seat-ink` | 适应屏宽的两席面板间距（px）、同一份提示内的操作间距（px）、由席位决定的强调色。字号、纸色、边框和按钮高度复用房间样式。 |
| desk.js 房间 | `token`, `stations`, `pollInterval`, `refreshNumber`, `requestNumber`, `clipboardOwner` | 链接片段中的邀请、席位编号到常驻面板的表、公开状态拉取间隔（ms）、最后发起的状态查询及本次查询序号、当前正在获取并写入系统剪贴板的席位。 |
| 视图绑定 | `byId`, `id`, `part`, `selector`, `side`, `seat`, `station`, `room`, `root`, `fighter`, `state`, `intro`, `turn`, `packetTools`, `recopy`, `show`, `note`, `reply`, `submit`, `receipt` | 选择器与节点查找、席位及房间状态、常驻面板、角色名与状态、两种导出入口、复印与备用文本控件、复制反馈、该席模型回复及提交回执。 |
| 传递状态 | `busy`, `copyPromise`, `copyDisabled`, `cursor`, `revision`, `finished`, `packet`, `packetMessage`, `packetError`, `expired`, `warning` | 该席是否在提交、尚未结束的复制请求、复制入口能否操作、上次成功复制的事件游标、已知最新席位版本、终局标记、最近一份待送模型的提示及其反馈，局面版本变化时的提示。 |
| 操作及网络 | `method`, `body`, `headers`, `response`, `detail`, `data`, `error`, `event`, `args`, `kind`, `turnLabel`, `result`, `message`, `keepNewerPacket`, `hint`, `denied`, `node` | 房间操作名、参数、凭据头、HTTP 回执、失败原因、表单或复制事件、导出种类及文案、提交成功消息、重复提交时是否保留更新的一份提示、重试说明、权限失效及反馈节点。 |
| 备用复制 | `copyDialog`, `dialogStation`, `dialogPacket`, `field`, `allSelected` | 用户主动打开的对话框、目标席位、当前选中提示、只读文本域和是否完整选中；关闭时清除文本域。 |
| 公开状态 | `single`, `deciding`, `preparing`, `phase`, `label`, `guide`, `playerLink`, `manualDesk`, `pending`, `list`, `kept`, `duel`, `item`, `number`, `hasTime`, `elapsed`, `waiting`, `summary` | 邀请可访问席数、当前决定与准备信息、回合状态、操作说明、单席战场与搬运台链接、待迎击编号及对应的已渲染行；由声明时间推得的等待秒数及文案。 |

## 本地对战房间

`battle_mcp/static` 的席位由私人链接决定。匿名链接共用同一块交锋区。下面的变量作用于独立房间页面。

| 文件与作用域 | 变量 | 用途 |
|---|---|---|
| style.css 纸面与文字 | `--paper`, `--sheet`, `--ink`, `--muted`, `--line`, `--green`, `--red`, `--accent`, `--wash`, `--stripe` | 页面、卡面、主次文字、分隔线、两席颜色、操作强调色及浅底。队伍条纹由该队席位决定。 |
| style.css 排版 | `--serif`, `--sans`, `--gutter`, `--pad`, `--gap`, `--tap`, `--fast` | 标题与正文字体；自适应横向页边距和卡内边距、区块间距、控件最小高度（px）、按钮状态过渡时长（ms）。 |
| app.js 席位状态 | `token`, `room`, `writing`, `records`, `current`, `reconnecting`, `ready`, `mine`, `isReady`, `options` | 当前链接片段中的私席凭据、最新投影、写入锁、按游标合并的本席事件、快照新旧判断、断线重连标记、已就绪席位、参赛身份、己方准备状态及已预留的合法动作。 |
| 标签与控件 | `kinds`, `triggers`, `phaseNames`, `battles`, `scores`, `dieNames`, `results`, `actionFilters`, `eventFilters`, `actionKinds` | 动作、触发、阶段、交锋类别、比较关系、骰种、结果的显示名；动作和事件字段到表单的对应及可登记的动作列表。 |
| 提前声明 | `plan`, `match`, `when`, `execute`, `trigger`, `timer`, `declaration`, `details`, `actors`, `fields`, `mapping`, `key`, `id`, `input`, `value` | 一条事前准备及其动作范围、时点条件、执行方式、触发种类、计时标记，提交负载、供确认的条件说明和候选角色。表单映射负责提取值，席位与编号按整数提交。 |
| 队伍、交锋与手牌 | `side`, `player`, `fighter`, `origin`, `own`, `bar`, `stats`, `shields`, `statuses`, `statusNode`, `n`, `frame`, `sets`, `duels`, `slots`, `slot`, `cards`, `names`, `target`, `kind`, `combat`, `showClash`, `dice`, `die`, `result`, `owner`, `hand`, `outcome`, `phase` | 席位与角色公开字段、头衔、己方标识、生命条、费用与资源等；按交锋类型组织槽、牌与目标；当前掷骰或拼点结果、该席可见手牌与回合结论。 |
| 公开回应计时 | `timing`, `clock`, `end`, `seconds`, `from`, `to` | 声明计时记录、对应 time 元素、服务器给出的起止毫秒（未回应时按当前时间）、累计的整秒。 |
| 列表与节点 | `tag`, `label`, `node`, `list`, `items`, `item`, `index`, `identity`, `remaining`, `create`, `update`, `invoke`, `first`, `saved`, `field`, `option`, `events`, `a`, `b` | 元素标签、内容和节点；带键列表保留同一实例及焦点；创建、更新、点击回调；下拉首项及选中值、可选动作和按 ID 排序的记录。 |
| 网络与只读规则 | `method`, `headers`, `body`, `response`, `data`, `error`, `message`, `ms`, `resolve`, `topic`, `guide`, `topics`, `catalog`, `catalogRequest`, `printed`, `ruleVersion`, `version`, `book`, `chapter`, `title`, `content` | 请求方法、席位请求头、含幂等键的操作、响应及重试；重连延迟毫秒及回调；章节索引、印刷图鉴、共享的加载请求、按牌 ID 检索的印刷牌面和浮层代次。 |
| 图鉴内容 | `enemy`, `targets`, `entries`, `actor`, `skills`, `skill`, `card`, `sections`, `section`, `passives`, `passive`, `description`, `links`, `name`, `detail`, `traits`, `ways`, `way`, `lines`, `fn`, `event` | 候选目标与本席技能、角色与技能原文、被动、状态、导航、卡面费用与许可、骰子行及各控件的动作或提交事件。 |
