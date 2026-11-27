# 当前设计与工作记录

## 常规置卡的开牌前交锋声称按钮（2026-11-27）

轮到本席常规置卡时，战斗操作栏始终显示「声称开牌前交锋」或已声称状态。点击通过房间传输发送 `claim_pre_reveal`，允许声称或撤销。可预置的手牌继续决定「预置开牌前」的显示。

前端 38 项测试通过。新增专测从房间状态渲染操作栏，核对有无可预置牌时都能点击，并验证发送的命令。房间实测空手牌也能声称和撤销。帝国第一序列兵持有「破碎」时可先声称，结束置卡后拿到主动出牌选项。Python 回归 362 项通过，9 项旧房间测试因其阵容角色不在当前卡包而报错。

## 合入战斗演出与新版林羽（2026-11-27）

合并演出分支的 `ee99748`。林羽沿该分支的新版牌面加载，`master` 的话语权裁决继续决定实际生效的射程。战报的骰面读取同一次裁决的结果，并保留演出分支的实时点数与骰面。

角色、战报与射程相关的 59 项测试和前端 36 项测试通过。新增投影专测中，同一枚写有无视两级射程的骰子面对相同对手时，较低话语权显示 0，常规话语权显示 2。

## 林秋「空断」的星环（2026-11-27）

房间服务提供星环的 SVG 图片。「空断」变换形态时在使用者身上显示星环，出击时在目标身上显示。专测从两个效果的实际配置取得图片地址，分别核对位置、HTTP 200、图片类型和 SVG 内容。独立副本通过 309 项测试。用编译后的「空断」效果调用前端播放入口，两次绘制分别收到使用者和受击者的坐标。

## 战报的伤害归属和暗牌记录（2026-11-27）

战报按实际伤害来源统计。己方受到自己造成的伤害时，伤害计入己方。开牌时公开留在场上的牌；开牌前被换回手里的暗牌，对手和观战者在对局结束前看不到牌名。导出的战报按当前席位显示。

独立副本通过 299 项战报与词条测试，3 个战报界面模块通过 JavaScript 语法检查。

## 房间开局、热座交接和联机操作（2026-11-27）

本地提交 `e5ae9ea`。房间先验证阵容并建立对局，再登记开战。挑战的固定首领保留指定阵容，玩家编队遵守房间上限。赛前声明保留到开战。公开选人按当前阵容给出牌面，双盲选人时每方只读到己方已选角色。预约换牌记住所选场上牌的实例，即使两张牌同名也能区分。

在临时 Chrome 和本机游戏服务中，从主菜单选安诺琳对纪岚。双方结束置卡后点击“场内行动”，画面要求玩家二接手。交接前双方手牌数据均为 0 张，接手后分别为 0 张和 3 张。另一局从挑战菜单把战力上限设为 3，把个人费加至 10 后再点一次加号，数值保持 10。安诺琳对固定首领结构化载体进入第一回合。

真实 WebSocket 测试在房间生成首帧后换人，客户端在下一帧收到这次变化。两个 MCP 席位经 HTTP 完成准备，轮到抽牌的一方收到私有候选并成功置底，重发相同请求只结算一次。前端专测核对了换牌目标、服务器拒绝、断线、超时和成功回执。旧局的认输请求到达新局会被拒绝。

当前工作区的 363 项 Python 专测和 30 项前端测试通过，包含 294 项词条专测。战报自伤归属在现有未跟踪的战报实现及其测试中修正，分别核对了直接伤害和真实伤害的同侧、异侧来源。暗牌撤回后的保密和星环资源 HTTP 200 已由工作区现有集成测试验证。

单独导出房间修复提交后，330 项 Python 测试通过。该副本的前端测试有两项沿用旧的战桌测试对象，缺少 `tabletop`。在修复前的原始提交 `222ea16` 上也复现了相同的两项失败。另行运行的旧 `tests.test_canvas_room` 四项均在加载归档角色 `ember_wen_sheng` 时退出。

## 全链路真实缺陷排查、战报视角与大厅/战桌交互修复（2026-11-27）

1. **网络路由、静默 404 与未公开信息隔离修复**：
   - `battle_mcp/transport.py`：`do_GET` 静态资源前缀补齐 `"/fx_assets/"` 与 `"/sfx/"`，解决 `/fx_assets/star_knot_ring.svg` 等资源 404；WS `battle_record` 与 HTTP `GET /api/battle_record` 透传 `viewer_side` 与 `hotseat` 视角。
   - `battle_mcp/room.py`：新增只读 `_hotseat_record_side_locked()` 与视角投影版 `battle_record(viewer_side=None, *, hotseat=False)`；`battle_ui/static/engine/transport.js` 的 `fetchBattleRecord()` 移除强制 `publicView: true`，按席位凭据拉取对应视角战报。
   - `battle_mcp/hosting.py`：`Lobby.lineup()` 补充下发 `character_colors`、`character_fx`、`fx_scripts`、`status_visuals`，供 `/lobby/` 选人预览特效使用。
2. **内核统计、投掷算式与战报记录一致性修复**：
   - `displayer.py`：`_effective_card_die_view` 创建预览 `Dice` 时从 `card.player.game` 读取 `game`；角色快照新增 `initial_max_lightcore_hp`，避免 `hp_scale_pct != 100` 时首回合误判露出光点生命栏。
   - `context/context.py` 与 `pipeline/pipeline.py`：`skill_payment` 在多形态技能上附带 `active_form`；`_die_roll_detail` 计算并记录 `final_effect_bonus`（`die.final_score - die.calculate_final_score()`），确保自定义公式与乘区下左右算式严格守恒。
   - `models/special_actions.py` 与 `battle_ui/match.py`：`special_placement`、`special_rear_placement`、`hidden_card_replaced` 补齐角色/技能/位置元数据；`_place_action` 回填真实 `duel_number` 与 `instance_id`；`cards_revealed` 之前被调换回手的原扣置技能通过 `_mark_hidden_withdrawn` 与 `reveal_text`/`reveal_entities` 双层遮罩持续对对手保密（开牌后仅暴露换上场的新牌，完局才全量解锁）。
   - `battle_ui/chronicle.py`：修正 `format_die_formula` 自定义 `formula` 判重顺序与 `final_effect_bonus` 展示；修复 `to_markdown` 交锋标题末尾多余 `$` 与 `turn_ended` 回合回收字典直出；用 `_pending_damage_settled` 与事件边界冲刷替代全局布尔去重，修复 `AFTER APPLY_DAMAGE` 触发时直接伤害漏记与护盾抵消丢失问题；统一句柄化直接 `Character` 状态/生命/护盾变更（去重 Opcode 重复记账）及 `attack_declared(duel_index=None)`、后置失效、接牌、翻正、锁定、次数能力等漏记事件。
3. **大厅与战桌 WebGL / Pixi 实机交互与渲染修复**：
   - `battle_ui/static/lobby.html` & `battle_ui/static/engine/lobby.js`：补齐 `/lobby/` `#three-canvas`，改为使用 `ThreeWorld.update(...)`（修正原 `three.tick` 不存在导致的三维特效不渲染），绑定 `showSkillBanner` 浮层并支持显式屏幕尺寸重排，修正 `wheel` 监听改用全局指针追踪与屏幕坐标换算，解决右侧英雄详情栏滚轮误滚左侧图鉴问题。
   - `battle_ui/static/engine/fx_director.js`：`deferFx` 默认及实例封装改为 `(fn, ms) => setTimeout(fn, ms)`，消除浏览器中 `this.deferFx(...)` 直接绑定 `setTimeout` 引发的 `TypeError: Illegal invocation`。
   - `battle_ui/static/engine/table_overlays.js` & `game_director.js` & `three_world.js` & `presentation_fx.js`：扩展 `slotHost.hitArea` 涵盖技能卡下方 `预览特效` 按钮；修复侧边检查器行点击关闭与按钮/骰区重叠、标题与编入按钮碰撞、剪裁外战报胶囊误悬停及 `topBar` 与速度横幅碰撞；调整 `sidePanelsLayer` 到手牌与按钮层上方；弹窗打开时屏蔽背景槽位悬停浮标并在预览时启用透明背景 `setOverlayPreviewMode(true)`（`zIndex: '4'`）与 `fxTextLayer` 置顶；骰子对撞补充 `resolveDiceStyle` 专属外观与状态光环 `"pulse"` 驱动。
4. **验证范围（全部在末次修改后通过）**：
   - Python：`python -m unittest tests.test_end_to_end_audit tests.test_battle_chronicle tests.test_canvas_battle_engine tests.test_fx_dsl tests.test_displayer tests.test_private_table_and_ws tests.test_room_pacing_and_dice_presentation tests.test_sp_characters tests.test_liu_yin tests.test_carrier_challenge tests.entry_semantics` —— `442` 项全部通过（`OK`；另 `test_canvas_room` / `test_mcp_transport` / `test_match` / `test_special_actions` 中原本指向已退场测试角色的旧用例未在本次改动范围，维持原状）。
   - 前端：`node --check` 全部改动 `.js` 通过；`node --import ./tests/frontend/register.mjs --test tests/frontend/test_game_stage.mjs tests/frontend/test_data_driven_display.mjs tests/frontend/test_sequencer_and_choreography.mjs tests/frontend/test_director_stage.mjs` —— `28/28` 通过。
   - 真实浏览器（Chromium WebGL，端口 `8771`）：大厅选人滚轮、贺敛标题与技能 `预览特效` 三维斩击/粒子与横幅、林秋/澜清进入战斗、速度横幅与面板分层、林秋 `空断` `预览特效`（`/fx_assets/star_knot_ring.svg` HTTP 200）、第一回合置牌与回合末战报全文弹窗全部实测通过，控制台 `0` 报错，网络请求 `0` 失败。

## 私人牌桌、房主全权房间规则与原生 WebSocket 实时架构重构（2026-11-27）

- **已确认语义与私人牌桌规则体系**：
  - **统一房间引擎与 6 位无歧义房间码**：移除本地专属 `BattleSession` 分裂栈，将 `online`（双人联机）、`solo`（单人演练）、`hotseat`（同屏双人）与 `challenge`（首领挑战）全部统一承载于实时 `Room` 引擎；大厅支持一键创建房间并生成 6 位去歧义大写房间码（`23456789ABCDEFGHJKLMNPQRSTUVWXYZ`），通过 `POST /api/rooms/join` 输入房间码加入时，第 1 位加入者自动获得 2 号对战席，第 2 位及以后加入者自动分配只读观战席。
  - **房主全权房间规则设置（默认基线严格对齐《正式规则书》）**：
    - **编队与选人规则**：支持总战力标度上限 `power_cap`（常人 `1`、精英 `2`、首领 `3`、强化首领 `4`、极端战力 `5`；默认 `None` 不设限，支持 `3/5/7/10` 及自定义整数）、每方人数上限 `max_chars`（默认不设限，最少 `1` 人）、同名角色规则 `duplicate_policy`（默认 `team_unique` 队内唯一可镜像，可选 `strict_unique` 全场唯一或 `free_duplicates` 允许同名堆叠，自动按 `@side.pos:id` 区分实例）、选人方式 `pick_mode`（联机默认 `blind` 双盲保密仅向对手展示人数与总战力，可选 `open` 公开选人或 `draft` `1-2-2-1...` 蛇形轮选并支持房主 `pass_first_pick` 让出先手及单方提前准备跳过）以及同屏防窥遮帘开关 `hotseat_curtain`。
    - **对局 `GameRule` 与节奏覆盖**：支持房主按房间独立覆盖每回合留牌数 `draw_count`（默认 `2`，首回合自动 `+1`）、每回合通用费用补充 `max_basic_cost`（默认 `5`）、存活角色独立费用补充 `char_independent_cost`（默认 `1`）、单窗口常规连扣上限 `place_capacity`（默认 `2`）、开局最大生命与最大光核百分比倍率 `hp_scale_pct`（默认 `100%`，浅拷贝缩放不污染全局卡包）与思考暂停限时 `pause_limit_s`（好友房默认 `None` 不限时，可选 `20s / 60s / 120s`）。
    - **好友局流程韧性与断线保护**：支持开战前随时 `unready` 取消准备调整阵容、局中房主或终局任意席位发起 `reopen_lobby` 全员不断线保留原房间码重返选人台、二次确认 `concede` 投子认输结算；联机 WebSocket 断线满 `60s` 自动挂起公共节拍时钟等待重连，满 `120s` 绝不强制判负销毁牌局，仅向在线方开放可选的 `claim_disconnect_win` 提前获胜结算按钮，重连后自动解冻续战。
- **执行路径**：
  - **规则校验、智能单人对手与统一对局内核**（[ruleset.py](battle_mcp/ruleset.py)、[match.py](battle_ui/match.py)、[engine.py](battle_mcp/engine.py)、[bot.py](battle_mcp/bot.py)）：新增 `RoomRuleset` 归一化与单队/双队战力及重名校验、蛇形轮选席位计算、卡包阵营/首领预设自动发现与等战力随机配队 `generate_matched_team`；`BattleMatch` 注入独立 `GameRule` 与生命光核缩放并实现 `forfeit` 终局裁定；`bot.py` 补齐 `place_rear` 置牌与基于本方可见局面的回合内 `choose_inturn_move`（`special_place` / `special_replace` / 无目标 `special_ability`）。
  - **零第三方依赖 RFC 6455 WebSocket 与房间调度**（[ws.py](battle_mcp/ws.py)、[room.py](battle_mcp/room.py)、[hosting.py](battle_mcp/hosting.py)、[transport.py](battle_mcp/transport.py)、[__main__.py](battle_ui/__main__.py)）：纯标准库实现 WebSocket 握手、掩码/分片帧编解码、线程安全推送与心跳；连接首帧通过 `{"type": "auth", "token": ...}` 完成鉴权（URL 零明文凭据），服务端状态变更经 `Condition` 即时广播；删除旧 `battle_ui/session.py` 并将 `python -m battle_ui` 统一挂载至 `Room + ArenaServer`。
  - **纯 WebGL 大厅、实时房间选人台、房间规则设置与牌桌菜单**（[transport.js](battle_ui/static/engine/transport.js)、[app.js](battle_ui/static/app.js)、[lobby.js](battle_ui/static/engine/lobby.js)、[table_overlays.js](battle_ui/static/engine/table_overlays.js)、[game_director.js](battle_ui/static/engine/game_director.js)、[combat_choreography.js](battle_ui/static/engine/combat_choreography.js)）：`RoomSeatTransport` 切换为原生 WebSocket 双工直连与断线指数退避重连；大厅补齐联机建房与 6 位房间码输入/粘贴入房页；选人台实时同步 `lobby_state`、战力标度徽章、双盲保密遮罩、单人等战力随机/预设切换与房主「房间规则设置」面板；顶栏「菜单」整合房间码复制、重返选人台、战报导出与二次确认投子认输。
- **验证结果**：
  - 新增后端与双工协议专测 [test_private_table_and_ws.py](tests/test_private_table_and_ws.py)（9 项，覆盖 6 位房间码双人及第 3 人自动观战、战力上限与重名策略、双盲脱敏与蛇形轮选先手让渡、自定义 `GameRule` 与 `150%` 生命光核倍率、投子认输与不断线重返选人台、`60s/120s` 断线挂起保护与提前结算、同屏遮帘开关、等战力 AI 回合内切入及真实 Socket WebSocket 并发握手推送），并将 [test_battle_session.py](tests/test_battle_session.py)、[test_canvas_battle_engine.py](tests/test_canvas_battle_engine.py)、[test_fx_dsl.py](tests/test_fx_dsl.py)、[test_mode_lobby.py](tests/test_mode_lobby.py) 全部迁移至统一后端。
  - 扩充前端专测 [test_sequencer_and_choreography.mjs](tests/frontend/test_sequencer_and_choreography.mjs)（新增统一房间大厅/同屏遮帘/不限时暂停映射、双盲战力展示、「房间规则设置」与「牌桌菜单」渲染校验）。
  - Python 回归套件 **360/360 通过**；前端专测套件 **23/23 通过**。

## 回合内即时行动、联机零泄密时序、3D 骰子状态机与命中演出重构（2026-11-27）

- **已确认语义与联机公平准则**：
  - **回合内即时切入与换卡**：开牌后及交锋任意结算节拍（含敌方已打出前两骰、轮空空白轮或拼点轮间），手牌扇区对固定视角席位全程常驻，无需切入二级模式即可直接拖入桌面或点击印章执行 `special_place` / `special_place_rear` / `special_replace` / `special_attack` / `special_custom` 及全量角色主动能力（含 `own_hand` 与 `board` 选目标能力）；中途置入或换入的新卡在下一骰轮直接以自身第 1 骰接敌方下一颗未用骰（如敌方第 3 骰）。
  - **真人联机零读秒泄密**：联机房间公共节拍推进时长（`2.6s` / `2.4s` / `2.0s` / `1.75s`）仅由公开场面决定，严禁因单侧私有手牌或鼠标悬停冻结共享时钟；桌面席位在非暂停节拍私密接收 `inline_special_options` 零暂停直出，同窗口内节拍修订号微进仍允许合法提交。
  - **动画期/跨轮预宣言（`/api/prepare`）与思考时间银行**：3D 骰子翻滚期或前序轮次拖放/点击切入与换卡时，联机模式自动挂载按 `(turn, duel_kind, duel_number, round_id, timing="after_dice_use")` 绑定的私密 `prepare` 声明（本地模式进入落骰即刻队列），桌面渲染仅本人可见的半透明预约残影并支持一键撤回；联机手动暂停接入每回合每席 `20s` 思考时间银行（支持暂停中连续多步操作保持暂停，耗尽自动恢复）。
- **执行路径**：
  - **命中因果序与本地桥接**（[table_bridge.py](battle_ui/table_bridge.py)、[match.py](battle_ui/match.py)、[session.py](battle_ui/session.py)）：新增 `TableBridge.mark()` 与保序重排 `emit_at(after_seq, ...)`，在 `before_dice_hit` 记录锚点并将 `combat_strike` 插回 `logic_dice_hit` 伤害/引燃之前、保持在 `cost_pay` / `on_skill_use` 被动之后；单方面技能 `logic_skill_use` 基于纯公开盘面停拍；`BattleSession` 传入 `viewer_side` 并开放免 `open_special` 的内联 `use_special` / `trigger_table_action` 与冗余微时点折叠。
  - **联机房间与声明协议**（[declarations.py](battle_mcp/declarations.py)、[engine.py](battle_mcp/engine.py)、[room.py](battle_mcp/room.py)、[transport.js](battle_ui/static/engine/transport.js)）：补齐 `place_rear` / `special_place_rear` 及 `round_id`、`enemy_die_number` 声明匹配条件；`Room` 暴露 `beat_duration_ms`、`beat_remaining_ms`、`pause_bank_ms`、`pause_remaining_ms` 与席位私有 `declarations`；`roomTableState` 区分强制响应（`decline` / `special_choose_*`）与常驻内联选项，避免劫持 `combat` 模式。
  - **3D 骰子回合状态机与受击同步**（[three_world.js](battle_ui/static/engine/three_world.js)、[physics.js](battle_ui/static/engine/physics.js)、[fx_director.js](battle_ui/static/engine/fx_director.js)、[presentation_fx.js](battle_ui/static/engine/presentation_fx.js)、[timeline_sequencer.js](battle_ui/static/engine/timeline_sequencer.js)）：引入 `roundKey` 与 `throwing -> holding -> clashing -> settled -> retiring` 状态机，新轮次 `0.16s` 快速退场旧骰消除空等，慢节拍下 `holding` 保活至对撞并修复 `attachClashBody` 地板下陷与拉回瞬移；`launchDie` 严格遵守 `revealDelay` 并展现 `掷X→Y` 跳变；`FxDirector` 拆分 `t = 0` 攻击前冲与 `t = impactMs` 受击后仰/震屏/血条光核扣减，补齐 `烧伤`/`爆燃`/`裂血` 伤害归因与飘字防重叠级联。
  - **战桌直拖切入、印章标注与残影交互**（[field_action_workspace.js](battle_ui/static/engine/field_action_workspace.js)、[combat_tabletop.js](battle_ui/static/engine/combat_tabletop.js)、[combat_choreography.js](battle_ui/static/engine/combat_choreography.js)、[game_director.js](battle_ui/static/engine/game_director.js)）：修复 5 段式 `kind:number:side:lane:position` 场上牌键，暴露 `boardCardRects` 支持手牌直拖替换任意友方前后置牌，渲染切入虚线槽（提示「首骰接敌第 N 骰」）、预约残影与顶栏节拍/思考进度条，并为行动印章补齐常驻中文牌匾。
- **验证结果**：
  - 新增后端与联机集成专测 [test_inturn_and_choreography.py](tests/test_inturn_and_choreography.py)（5 项，覆盖因果事件序、人机常驻手牌切入接第 3 骰、联机零暂停同窗直出、联机 `prepare` 跨轮零泄密预约及 `20s` 思考时间银行连招保持与超时恢复）。
  - 新增前端确定性专测 [test_sequencer_and_choreography.mjs](tests/frontend/test_sequencer_and_choreography.mjs)（5 项，覆盖 `normalizeBeatEvents` 前置事件保序、状态机快速退场与换卡退骰、`impactMs` 风压受击分离、`roomTableState` 内联投影与中文标注印章）。
  - `python -m unittest tests.entry_semantics tests.test_displayer tests.test_inturn_and_choreography tests.test_room_pacing_and_dice_presentation tests.test_mode_lobby tests.test_cang_feng tests.test_lan_qing tests.test_liu_yin tests.test_heris tests.test_carrier_challenge` **454/454 通过**；前端专测套件 **21/21 通过**。

## 林羽（Emyake）卡包重做补强、平衡性定稿、旧版归档与裂伤可视化（2026-11-26）

- **已确认文义与归档**：
  - 原版卡包完整归档至 [emyake_lin_yu_legacy.json](_packs_legacy/emyake_lin_yu_legacy.json)；全部改动严格限定于 [emyake_lin_yu.json](_packs/emyake_lin_yu.json)、新增状态图标与专测文件（零内核 Python 代码改动）。
  - **`裂伤` 与 `羽流·延攻` 存储曲线重调**：
    - `裂伤`（上限 25）：受到骰子造成的伤害时，裂伤存伤改为增加 `X/5（向下取整）*10%` 的伤害量（`20~24` 层均为 `+40%`，无需卡死 `24` 层即可吃满基础档位）。
    - `羽流·延攻`（最大 3）：存储裂伤伤害时，存储数额增加改为 `X*50%`（3 层延攻即 `250% × 40% = 100%` 等效翻倍）。
  - **重做并平衡 `刻刃风暴`（4 费，`range_level: 3` 极限远程，非不可摧毁）**：
    - 技能词条：`本技能骰子等级不受外部效果影响`；`【使用时】消耗3铭刻以使本技能骰子等级提升1、最终点数+2`（遵循 `铭刻视界`：`3~12` 铭刻弹出可选 `CHOOSE_OPTION`，`>12` 自动触发，`<3` 静默跳过）。
    - 第一骰 `斩击 1~6×3`：无直伤；【命中时】锁定**下一交锋**的敌方槽位，使该槽位中敌方所有骰子最终点数 `÷4`（向下取整）。
    - 第二骰 `斩击 1~6×3`：【命中时】若本技能消耗了铭刻，造成群体 `2` 超穿甲伤害；锁定**本交锋后第二交锋**的敌方槽位，使该槽位中当前及后续置入的所有敌方技能无效化（`NEGATE_SKILL`），且仅当以此实际使敌方技能无效化时获得 `1` 层 `羽流·终`（单次结算至多触发 `1` 次，中盘润滑折影铭刻回转）。
    - 第三骰 `斩击 1~12×2`：群体 `1` 超穿甲；【命中时】若本技能消耗了铭刻，群体使下次裂伤爆发伤害 `+20%`（可叠加无上限，向上取整前乘算，爆发后一次性清空）。
  - **低费裂伤联动与平衡定稿**：
    - `铭刻闪动`（1 费远程，双斩击骰不变）：技能词条 `目标每持有8层裂伤，本技能骰子最终点数+1（至多+3）`；第二骰 `若目标裂伤不低于16，额外抽1卡`。
    - `刻刃护卫`（1 费）：前两颗斩击骰 `施加1裂伤；若目标裂伤不低于8，获得1护盾`（先叠层后判阈值）；第三颗远程斩击骰 `0穿甲；远程骰子；消耗1铭刻以使伤害+1；目标每持有12层裂伤，伤害+1（至多+2）`。
  - **`裂伤` 存伤展示与状态图标**：
    - 新增日光高对比配色与自定义 SVG 图标 [裂伤.svg](_packs/status_icons/裂伤.svg)、[裂伤拘束.svg](_packs/status_icons/裂伤拘束.svg)，为林羽专属状态补齐显式 `color` / `polarity` / `icon_path`。
    - `status_rules["裂伤"]["display_fields"]` 投影 `已存储伤害`、`下次爆发增幅(%)`（未增幅为 `null` 时自动隐藏）与 `预计爆发伤害`。
- **纯词条执行路径**：
  - 外部骰级免疫由三段最高话语权隐藏词条协同实现：`BEFORE SKILL_LEVEL_ADD` 与 `BEFORE DIE_LEVEL_ADD` 拦截非自身 `刻刃风暴内部改级` 窗口的等级增减，`BEFORE RESOLVE_DIE_LEVEL` 将 `value_ref` 上下界同时锚定为 `printed_level + (1 if 刻刃风暴强化 else 0)`；D2 条件伤害与 D3 条件增幅统一读取 `$event.card.use_state.刻刃风暴强化`。
  - 槽位锁定通过 `1 DUEL_OFFSET`（预约 `before_dice_use` 校验 `$event.observed.side` 写入 `刻刃除四次数`）与 `2 DUEL_OFFSET`（即时清扫 `SLOT_AT_OFFSET` 现存敌方牌 + 预约 `before_skill_start` 校验 `$event.observed.side` 拦截后续入槽敌方牌，并以单次 `风暴锁序号` 去重发放 `羽流·终`）实现。
  - 裂伤存伤按 `damage * (裂伤 // 5) * (10 + 5 * 延攻)`（百分位整数）记录并通过 `DIVIDE` 维护 `裂伤显示存伤`，爆发时按 `(裂伤存伤 * (10 + 裂伤爆发增幅) + 999) // 1000` 在向上取整前乘算并重置增幅与存伤。
- **验证结果**：
  - [林羽词条专测](tests/test_emyake.py) 覆盖 `4/8/10/20/24` 裂伤五层档距与 `3` 层延攻等效翻倍、未强化/强化 `刻刃风暴` 的直伤（`1` vs `3`）与爆发增幅（`0%` vs `20%`）正反对照、外部改级免疫、双槽锁定与中途补牌无效化、`铭刻闪动`/`刻刃护卫` 新阈值及 `Displayer` 面板/图标投影。
  - `python -m unittest tests.entry_semantics tests.test_displayer` **297/297 通过**。

## 主动能力弹窗可取消与未提交不扣次数修复（2026-11-24）

- **已确认语义**：
  - `Context.mutation_serial` 统计非纯查询/选择指令（排除了 `_NON_MUTATING_OPCODES` 中的流程与选择指令）。
  - `SpecialActions._use_ability` 若触发挂起决策（`CHOOSE_OPTION` / `CHOOSE_CHARACTER` / `CHOOSE_CARD` / `CHOOSE_SLOT`），将 `ability_uses[key]`（`per_turn` 次数）与 `ability_used` 事实延迟至真正产生副作用或最深层非放弃选择完成时再提交；若玩家点击「放弃 · Esc」（包括从 `重城·烛芯` 进 `投掷重剑壳 -> CHOOSE_CHARACTER` 后点击 `decline_character`），则清理待提交记录并无损退回原置卡/开牌前窗口，次数不消耗。
  - 为 [重城·烛芯](_packs/waa_cang_feng.json)（外层 `CHOOSE_OPTION` 与内层 `投掷重剑壳` `CHOOSE_CHARACTER`）和 [深秋工作室](_packs/jingzhi_lan_qing.json)（外层 `CHOOSE_OPTION` 与 `已置卡 +1 远程`/`+1 骰级` `CHOOSE_CARD`）开启 `"optional": true`；`BattleMatch._trigger_table_action` 仅在非挂起即时完成时提前记录发动日志，避免放弃选择时误记一次发动。
- **验证结果**：
  - [藏锋事务所专测](tests/test_cang_feng.py) 新增 `test_core_command_cancel_refunds_per_turn_and_returns_to_placement`（覆盖 `BattleMatch` 下点开 `重城·烛芯 -> 放弃`、进 `投掷重剑壳 -> 放弃选人` 均返还次数/费用并回到 `placement`，以及确认执行 `enter_core` 后正常扣除当回合次数）。
  - `python -m unittest tests.entry_semantics` **238/238 通过**，`python -m unittest tests.entry_semantics tests.test_displayer` **251/251 通过**。

## 「藏锋事务所」卡包、系统状态 `爆燃` 与烧伤/致命失衡规则实装（2026-11-24）

- **已确认语义与内核补充**：
  - [系统状态效果包](_packs/effects/system_statuses.json)：
    - 新增体系状态 `爆燃`（`aliases: ["deflagration"]`）：`烧伤` 结算时原始伤害上限为 `3 + 爆燃`；仅当实际触发烧伤伤害（`烧伤 // 4 > 0`）时消耗 `1` 层 `爆燃`，`烧伤 < 4` 被引燃时不消耗 `爆燃`。
    - `致命失衡` 新增 `BEFORE RESOLVE_DAMAGE_STATUS`（`subject: "target"`）抑制条目：当 `damage_cause == "烧伤"` 时（包含回合末烧伤结算与主动/被动 `引燃`），烧伤伤害不触发 `致命失衡` 翻倍，也不消耗 `致命失衡` 层数。
  - [藏锋事务所卡包](_packs/waa_cang_feng.json)：
    - **阵营被动 `藏锋事务所`**：回合开始每名满足「自身手牌技能 ≥ 3」或「持有`偏转力场`」的存活本阵营角色获 `2 护盾`且己方 `+1 费`（每回合最多以此 `+2 费`）；敌方获得`致命失衡`（`actual_delta > 0`）时立即对其触发一次`引燃`。
    - **`偏转力场`（上限 3）**：通过 `ADD_SHIELD_DEFENSE` 仅向通用通道注册规则——多人时友方受直伤可借用持有者强化/普通护盾，孤身时自身每 `2` 点普通护盾抵挡 `1` 点穿甲伤害（`SKIP_SHIELD_EROSION` 配合余数磨损）；敌方进攻骰命中友方（含自身）且未造成实际生命流失（`attack_hp_lost` 为假）时，消耗 `1` 层对攻击者施加 `2 烧伤 + 2 失衡` 并通过带 `"chooser": "target"` 的单次 `CHOOSE_OPTION` 触发【防反】（每轮至多 `1` 次、每次至多 `1` 名友方响应）。
    - **贺敛 / 纪岚 / 季夏**：完整实装所长贺敛（`拔芯` 交锋/速度/过热代价与全局同步清理、`剑壳镇压` 锁鞘与双形态切换、`重城·烛芯` 主动技与 `飞城破阵·踏鞘归火`）、纪岚（`双生炉门` 转烧伤/`炉温`/`爆燃`、`重盾顶退` 借由 `REDIRECT_ATTACK` 转火+`respond_to_die` 迎击、`合炉·焦土锻葬`）、季夏（`红线缠缚` 开牌前被动迎击 `-1 费` 与无视 `1` 级远程、`顺丝叩响` 闪避反击与 `千丝收束·零距礼花`）。
  - **两处纯净内核修复**：
    - `context/context.py` 在 `OpCode.DAMAGE` 与 `OpCode.APPLY_DAMAGE` 事件补充 `damage_source`，确保 `run_program` 将 `$event.source` 重绑为词条持有者后，全局/他方监听者（如`双生炉门`）仍可准确读取原始伤害来源。
    - `models/special_actions.py` 新增 `_decision_owner_alive(choice)`，使 `global_entries`（`owner is None`，如`偏转力场`配合 `"chooser": "target"`）挂起的决策不被误判无主清除。
- **验证结果**：
  - 新增 [藏锋事务所专测](tests/test_cang_feng.py)（7 项，覆盖`爆燃`上限与零段不扣、`烧伤`/`引燃`不触发且不消耗`致命失衡`、阵营回合初加盾与 `+2 费` 上限、`偏转力场` 孤身 2:1 穿甲 / 多人借盾 / 单轮一次【防反】、贺敛 `拔芯`/`剑芯过热`/`剑壳镇压`/`重城·烛芯`/`飞城破阵·踏鞘归火`、纪岚 `REDIRECT_ATTACK` 援护与 `双生炉门`/`合炉·焦土锻葬`、季夏开牌前被动迎击减费无视远程与 `千丝收束·零距礼花` 超穿甲解锁），接入 `tests.entry_semantics`。
  - `python -m unittest tests.entry_semantics` **237/237 通过**，`python -m unittest tests.entry_semantics tests.test_displayer` **250/250 通过**。

## 通用角色选择原语 `CHOOSE_CHARACTER`（2026-11-24）

- **已确认语义**：
  - 新增 `OpCode.CHOOSE_CHARACTER`（操作数 `candidates, specification`）与 `CharacterDecision`（`models/opcode.py`、`models/opcodes.py`、`models/special_actions.py`、`game.py`），沿用与 `CHOOSE_OPTION` / `CHOOSE_CARD` 同一套 `decision_owner` 挂起与续体机制：支持任意词条或 `CHOOSE_OPTION` 分支链式弹出存活角色选择面板，去重并过滤阵亡角色；提交 `choose_character` 后绑定 `$event.chosen_character` 执行 `specification.then`，或通过 `decline_character` 放弃可选点名；当唯一候选角色在等待期间阵亡时决策队列自动清理。
  - 全端桥接同步投影（`displayer.py`、`battle_ui/match.py`、`battle_ui/session.py`、`battle_mcp/engine.py`、`battle_mcp/declarations.py`、`battle_mcp/static/app.js`、`special_actions_cli.py`、`battle_ui/static/engine/table_overlays.js`）：`effect_choice` 投影 `selection = "character"`，选项附上角色名称与实时 `生命/护盾` 描述；Web 2.5D 战桌复用选项卡板渲染角色候选与可选放弃按钮；MCP 房间以 `special_choose_character` / `special_decline_character`（含 `choice_key` 与精简字段匹配）及 CLI 同步接入。
- **验证结果**：
  - 新增 [角色选择专测](tests/test_choose_character.py)（3 项，覆盖 `CHOOSE_OPTION -> CHOOSE_CHARACTER` 链式选择与精准作用对象对照、可选放弃与候选阵亡自动失效、`Displayer`/`BattleMatch`/`ArenaEngine` 桥接投影与提交），接入 `tests.entry_semantics`。
  - `python -m unittest tests.entry_semantics tests.test_displayer` **243/243 通过**，`node --check battle_ui/static/engine/table_overlays.js` 通过。

## 显式转火原语 `REDIRECT_ATTACK` 与攻击目标确认时点（2026-11-24）

- **已确认语义**：
  - 保留 `respond_to_die` 的纯净边界（仅允许当前攻击的受击目标本人发起单方面迎击），不把“改换目标”与“迎击响应”混写在同一分支。
  - 新增显式转火指令 `OpCode.REDIRECT_ATTACK`（操作数 `die, new_target`），用于更新进攻骰的目标指向并发布 `attack_redirected` 事实（保留 `$event.target` 为原目标、`$event.new_target` 为新目标，支持 `None` 目标失落、`preserve_target` 与 `BEFORE REDIRECT_ATTACK` 话语权/防转火取消）。
  - 在 `pipeline/pipeline.py`（`_pair_dice` 与 `_solo`）新增 `before_attack_target` 时点，先解析出初始预定目标，允许通过 `decision_owner` 挂起交互选择，再将最终目标交由 `BEFORE_ONE_SIDED_ATTACK` 与命中结算；友方援护拦截（如转火后由自身 `respond_to_die` 迎击）、嘲讽与隐匿均复用同一条转火路径。
- **验证结果**：
  - 新增 [攻击转火专测](tests/test_attack_redirect.py)（4 项，覆盖友方转火接 `respond_to_die` 迎击正反对照、嘲讽拉走拼点骰且不迎击、隐匿转火队友及单人隐匿脱靶、防转火取消及同阵营/阵亡无效目标拦截），接入 `tests.entry_semantics`。
  - `python -m unittest tests.entry_semantics` **227/227 通过**。

## 通用护盾防卫通道 `ADD_SHIELD_DEFENSE`（2026-11-24）

- **已确认语义**：
  - 在 `OpCode.APPLY_DAMAGE` 阶段暴露 `$event.shield_defenses` 通道，`OpCode.ADD_SHIELD_DEFENSE` 仅接收 `(channel, holder, rule)` 三个操作数，不向内核传入任何比例、等级上限或磨损开关等业务特例。
  - `Character.apply_resolved_damage` 在结算受击者自身默认抵挡之后、默认磨损之前，按注册顺序在独立求值栈上执行各 `(holder, rule)`，暴露 `$event.holder`、`$event.target`、`$event.incoming`、`$event.remaining`、`$event.penetration` 与 `$event.erode_pools`。
  - 新增专用于伤害护盾结算期间的原子操作 `OpCode.SHIELD_ABSORB`（`holder, shield_kind, shield_cost, blocked_damage`）、`OpCode.SHIELD_ERODE`（`holder, shield_kind, amount`）与 `OpCode.SKIP_SHIELD_EROSION`（`shield_kind`），将实际吸收、磨损及跨位借盾明细写入 `damage_settled` 与 `AFTER APPLY_DAMAGE` 事件的 `shield_absorbed` / `shield_eroded` / `shield_lost`。
- **验证结果**：
  - 新增 [护盾防卫通道专测](tests/test_shield_defense.py)（4 项，覆盖 2:1 穿甲抵挡的 `0/1/2/3/5/10^6` 边界与 `SKIP_SHIELD_EROSION` 留存对比、1:3 自定义规则、多友方顺序借盾与已阵亡跳过、非法调用上下文校验），接入 `tests.entry_semantics`。
  - `python -m unittest tests.entry_semantics` **223/223 通过**。

## 双形态技能并排卡面展示与结构化投影（2026-11-24）

- **结构化双形态投影**（`displayer.py`、`battle_ui/match.py`）：
  - 基于 `form_when` 与 `forms` 纯结构化字段（零正则猜文本）生成形态标签 `_form_label`（如流阴 `常态` / `战甲≥1`、澜清 `常态` / `活化态`、赫克 `常态` / `持有全开`、林羽 `常态` / `替换态`）与完整双形态列表 `dual_forms`（保留 `is_active_form` 与实时费用/骰面状态）。
  - 统一覆盖 `_printed_skill(..., include_forms=True)`（图鉴/典籍与选人 `_roster_preview`）、`_visible_card`（手牌、场上已公开牌、弃牌堆、除外区与选牌界面）以及起手调度 `_current_draw_prompt`。
- **横向并排双卡展示（严禁单卡内上下滚动堆叠）**（`design_system.js`、`card_print.js`、`combat_tabletop.js`、`table_overlays.js`、`game_director.js`）：
  - 静息单卡（`buildFullCard`、`buildUniformCard`）与角色侧栏技能条（`buildUnifiedSkillRow`）显示精炼形态角标（常态显示 `⇄肃清引信` / `⇄活化态`，已切换形态高亮显示 `◆战甲≥1` / `◆活化态`）。
  - 新增 `buildDualFormSpread` 与 `buildCompanionFormCard`：选人编队、角色侧栏、起手调度、选牌面板及弃牌堆悬停时直接展开左右等高并排双实体牌（`[形态 I] ⇄ [形态 II]`）；手牌扇区与 2.5D 战场牌悬停时在抬升主牌一侧并排浮现另一形态伴生实体牌；规则典籍双列排版中双形态技能直接横跨左右两列并排展示；选人与弃牌堆网格同时支持点击 `⇄` 角标原地切换形态。
- **验证记录**：
  - `tests.test_displayer`（13/13，新增流阴「战甲塑造 ⇄ 肃清引信」与澜清活化技能变身前后及选人预览双形态对照测试）与 `tests.entry_semantics`（219/219）共 **232/232 通过**。
  - 5 个改动 JS 模块全部通过 `node --check`；Node 前端专测（`test_game_stage.mjs` + `test_data_driven_display.mjs`，新增横向并排坐标、零纵向滚动与形态徽章对照断言）**16/16 通过**。

## 后置交锋（Rear Duel）双轨内核、桥接与 2.5D/3D 牌桌演出（2026-11-24）

### 已确认规则与语义
- **附属关系、权限与容量**：后置交锋附属在己方已有合法前置卡的交锋槽位之后，单边默认容量为 `1`（可通过 `OpCode.REAR_CAPACITY` 读取、`OpCode.SET_REAR_CAPACITY` 改写）。仅具备后置权限的角色/技能（`card.data["rear_duel"]`、`character.data["rear_duel"]`、`character.ability_permission("rear_duel")`、`anytime_play` 含 `"rear_duel"`）或词条显式插入（`INSERT_SKILL` 锚点 `"rear_duel"`）可置入后置交锋。前置技能 `on_skill_use` 动态插入的后置卡（如以 `2 * cost` 能源预付 `{"prepaid": true}`，无需占用置卡机会）自第 1 轮起即与前置首骰同轮参战。
- **统一拼点与目标公式（`1v1 / 1v2 / 2v1 / 2v2` 完全同构）**：设本轮参战的前置骰为 `F`、后置骰为 `R`（缺席或已耗尽记为 `0`）：
  - **任意前置骰 `F`**：拼点阈值对比 **`enemy_F + enemy_R`**，受击目标为 `enemy_F` 所属角色（仅当 `enemy_F` 已自然耗尽时退回 `enemy_R` 所属角色）。
  - **任意后置骰 `R`**：拼点阈值对比 **`enemy_F`**（仅当 `enemy_F` 已自然耗尽时对比 `enemy_R`），受击目标同为 `enemy_F` 所属角色（或 `enemy_R`）。
  - 自然支持三骰/四骰同输（如 `5+6` 对 `8`）、多胜者同轮依次命中（如 `7+6` 对 `5`，或 `2v2` 中 `R1 > F2`）、拼点逆转及某轨骰子提前耗尽后平滑转入 `1v2 / 1v1`。
- **特殊骰子（`skip` / `block` / `evade`）**：印刷 `skip` 骰仅在前置轨触发整轮跳过并结算前置 `on_clash_skip`（参战后置骰同步记为 `skip` 并推位，不触发后置 `on_clash_skip`）；后置轨的印刷 `skip` 骰不触发、不跳过整轮，仅本轮轮空推位。防御/闪避骰的无对位轮空跳过（`on_clash_skip`）与分裂拼点命中仅对前置轨生效；参拼的后置守备骰正常掷点计入 `F + R`。
- **连坐作废 vs 自然耗尽**：当前置卡被摧毁（`DESTROY`）、无效化（`NEGATE_SKILL`）、移走/牵制、持牌人阵亡或因未付清费用而跳过时，`DuelSlot.sync_rear_validity` 立即撤回并作废（`CardState.NEGATED`）同侧后置卡，发布 `on_skill_disabled(reason="rear_anchor_lost")`；已正常付费并自然打完骰子的前置卡保留有效锚点，后置剩余骰子继续交锋。

### 执行路径与前端桥接
- **内核与管线**（`models/opcode.py`、`models/opcodes.py`、`models/duel.py`、`models/character.py`、`models/dice.py`、`models/special_actions.py`、`context/context.py`、`game.py`、`pipeline/combat_steps.py`、`pipeline/pipeline.py`）：
  - 新增 `OpCode.REAR_SLOT_CARDS`、`OpCode.REAR_CAPACITY`、`OpCode.SET_REAR_CAPACITY`；`SLOT_CARDS` 与 `REMAINING_CARDS` 统一涵盖有效后置卡。
  - `CombatFrame` 与 `Pipeline` 支持 `(side, lane)` 双轨 `SidePipeline`，后置轨使用 `REAR_DUEL`（不重复触发 `duel_start` / `duel_end`）；`_play_slot` 先令前置技能入场付费并结算 `on_skill_use`，再接纳后置技能进入第 1 轮配对。`ClashPair.clash_check()` 统一产出 `lane_results`；`_resolve_results` 支持 `0 / 1 / 2+` 名胜者依次结算并完整消费 `CAN_HIT`。
- **顶层桥接与纯画布表现**（`displayer.py`、`battle_ui/match.py`、`battle_ui/session.py`、`card_print.js`、`timeline_sequencer.js`、`physics.js`、`three_world.js`、`presentation_fx.js`、`combat_tabletop.js`、`field_action_workspace.js`、`game_director.js`）：
  - 快照与桥接暴露 `duels[].sides[].rear_cards`、`rear_capacity`、`card_owners.duels_rear`、`legal_rear_cards`、`rear_targets`、`place_rear`、`combat.sides[].rear` 及带 `lane` 标识的 `dice_roll` / `dice_clash` / `combat_strike` 事件。
  - 2.5D 牌桌在前置牌外侧对称渲染平放后置实体牌（左 P1 / 右 P2，`rotation = 0`）与金色「后置」角标、置卡期及场内行动期的 `⊕ 后置交锋` 落点槽、扣置后置牌角色卡背、战斗焦点悬停抬升查阅、双行（`前` + `后` + `合 X`）对撞勋章，以及 Matter.js + Three.js `1v2 / 2v1 / 2v2` 多骰同轮投掷与物理对撞。

### 验证记录
- 新增区分性专测 `tests/test_rear_duel.py`（7 大组场景）并接入 `tests/entry_semantics.py`，逐项核对：置入权限/前置依赖/`SET_REAR_CAPACITY` 容量扩充；`1v2` 三骰皆输、敌前置胜伤严格命中前置角色、双胜连击；`2v2` 非对称拼点与自然耗尽转 `1v1`（且不重复派发 `duel_start/end`）；前后轨 `skip` 与无对位守备骰差异；前置摧毁/欠费/阵亡连坐作废；余晖巨像式 `on_skill_use` 双倍能源预付动态插入首轮参战（不耗置卡额度与团队费）；`BattleMatch` + `Displayer` 顶层置卡、归属与 `lane` 事件流。
- Python：`python -m unittest tests.entry_semantics` **219/219 通过**；现代展示桥接与大厅对战回归套件（`test_displayer`、`test_room_pacing_and_dice_presentation`、`test_lan_qing`、`test_liu_yin`、`test_emyake`、`test_carrier_challenge`、`test_heris`、`test_mode_lobby`、`test_rear_duel`）**178/178 通过**。
- 前端：全部 8 个改动 JS 模块通过 `node --check`；`node --import ./tests/frontend/register.mjs --test tests/frontend/test_game_stage.mjs tests/frontend/test_data_driven_display.mjs` **15/15 通过**。

## 林秋「分界」的摧毁候选（2026-11-24）

测试修正见 `40811eb`。按现行卡面“敌方本回合仍在场的任意一张技能”，候选包含命中目标与其队友仍在场的技能。专测按交锋顺序取得三张候选，排除了已摧毁的牌。第一张候选离场后，提交该选择会被拒绝；随后选择第二个交锋中目标的技能，只有该牌被摧毁。专测通过，完整词条套件 212 项全部通过。

## 极限远程在每枚骰子配对时判定空白（2026-11-24）

三级远程压制对骰子的空白判定发生在该骰实际配对时。提前读取后续骰子只取得实体及其印刷属性。战桌、展开牌面与交锋缩略图按各枚实际用骰的骰种显示，没有用骰记录的位置显示印刷骰面。技能自身词条的远程压制仍在双方技能对阵时结算。

用三枚各需1铭刻的骰子预先取得全部实体。分别以整张极限远程对中骰无视3级、以及仅首末两枚对方骰为极限远程跑完交锋。两例都只有首骰和末骰在各自轮次变为空白，中骰实付1铭刻并命中一次。先变空白再取得无视3级的恢复与显式空白也分别通过原有专测。相关后端128项、前端15项通过。完整词条入口211/212，既有的林秋「分界」候选断言仍失败。

## 林羽的远程压制、无受击载体与迎击骰面（2026-11-24）

「无视3级远程」即时恢复同一枚因远程压制而成为空白的骰子。已配对的斩击在用骰前取得无视后可以拼赢、发动骰面词条并造成2超穿甲；同样的骰子被词条直接改为空白时仍为空白。普通「闪回识破」只在首枚闪避上写有「无受击载体」。这项性质在骰子变为空白时仍有效，第二枚斩击可以受击。「折影交织」换出的「闪回识破」通过本次技能状态取得整技保护。用对方拼胜、命中、伤害、施加状态和自身取得拼胜收益分别核对了作用对象。

「威压烙印」是1级远程。用两张实牌分别重放常规对位、开牌前迎击和开牌前牵制，互换先手，六种情形中「折影交织」均回手并返还3场内费。「闪回识破」的闪避和斩击各与一枚突刺拼点，战桌分别发出两次双方掷骰。临时技能消散后保留只供回看的两枚骰和各自结果，被后续命中摧毁的牌保留已结算的骰面。桌面、展开牌面和缩略牌面依实际胜负着色，战报写出参拼的技能及骰位。玩家当局战报已不可用，以上为同牌重放结果。

当前工作区中，角色、载体、澜清、流阴、远程、迎击与展示专测共156项通过。完整词条入口210/211，林秋「分界」的实体候选断言在改动前也失败。三个前端测试文件合计14/16，原提交上两个战桌测试同样因测试夹具缺少 setLayout 而失败。另在干净的 3f78fe2 上单独应用本补丁核对过，林羽原卡包已引用 CHOOSE_OPTION，但该基线缺少此指令。工作区已有的选项暂停实现是运行林羽专测的依赖。

## 大厅单人和 Boss 挑战使用本机 AI 战桌（2026-11-24）

提交 `34d8657`。作者指定 `python -m battle_ui --ai` 为标准。旧大厅的单人和挑战虽然加载了相同的画布，却由 `RoomSeatTransport` 和 `ArenaEngine` 推进，未提供置卡期的开牌前预置。大厅现通过 `BattleSession(ai_side=2)` 创建这两种玩法，与本机入口共用 `BattleMatch`、`LocalBattleTransport` 和战场界面。独立启动单人或 Boss 挑战也进入这套编队与战桌。挑战的固定阵容、专用卡包、目标优先级和出牌策略在建房和重开时生效。私人邀请支持回到原桌并导出本局完整战报。

- 使用同一阵容和种子，逐步比对大厅单人与直接启动的本机 AI 对战，核对行动席、可用手牌、开牌前目标和扣置卡归属。在林羽对澜清的房间实际提交预置和撤回，验证所选实体牌和目标。分别核对迎击只接受该交锋的候选和待迎击的特殊行动能由 AI 放行。
- 林羽对澜清、林羽对结构化载体都经本机战桌推进到终局并按原阵容再战。战场状态图标专测现从同一个大厅工厂建立新战桌。另在刚启动的本机服务上核对私人邀请指向 `/table/`、对阵双方和 11 条状态目录原文。
- 本次对应的大厅、桌面启动后台、载体、澜清、林羽、展示和悬停回归共 128 项通过。完整词条入口 207/208，林秋「分界」候选集仍是既有失败。另行核对的本机战桌及特殊行动历史套件有 14/16 项在迁移前后同名失败；MCP 传输的历史对局用例仍引用当前卡包中缺少的 `ember_wen_sheng`。

## 林羽对澜清的战场状态浮窗（2026-11-24）

提交 `f9bdc87`。在新建的澜清挑战中，悬停图标会列出该角色的各项状态。「破甲」原先在自身说明下连续显示四份「纯粹之心」末骰全文，分别来自四个状态执行词条。将这四处的描述修正为骰面括号内原文“无视全部护甲且无法持有护盾”。技能上的整句原文保留。

用挑战房间返回的双方状态跑过战场图标的悬停与移出事件。林羽同时持有七项状态，澜清同时持有裂伤、裂伤拘束与破甲；逐项比对浮窗中的标题、实际层数和 Pixi 文本，正文与各自的声明完全相同。施加在技能上的「折影」另在状态目录核对。角色、展示、澜清和悬停专测共 86 项通过。完整词条入口为 207/208，既有的林秋「分界」候选实体断言仍失败。

## 林羽首斩清势与状态说明（2026-11-24）

修复提交 `3dd3466`。原文要求“成功触发上述效果并获取了羽流剑术状态后，消耗全部羽流·势。”2 势使用「折影吞噬」单方面命中时，原实现先执行骰面的回手，随后失去用骰结束回调。5 势「折影交织」的单方面首斩在命中时也仍显示 5 势。

- 匹配费用后，角色 JSON 在用骰时标记第一枚印刷斩击的实体。拼胜、拼负、拼平分别使用其结果节点。单方面攻击在确认进入首次命中流程时取得制衡，先于骰面回手。远程劣势使单方面攻击完全不能命中时，用骰结束仍可结算。各分支以实际取得剑术状态的回执为准，有势时按当时层数向上取半发放附加收益，再用 `SPEND_STATUS all` 清势。
- 2 势「折影吞噬」回手前已获得 1 制衡和 1 护盾。5 势「折影交织」首斩单方面攻击取得 1 制衡、3 护盾，首斩分别拼赢、拼输、打平时各只消耗一次 5 势。4 势使用同一张 5 费牌保留 4 势；首斩取得状态被取消时，后续斩击不会继承首斩奖励。用澜清实际牌面复核，「折影交织」首斩 12 对「残雪·幽蓝流光」16，记录 1 反制并消耗 5 势。
- 状态目录按完整声明保留原字和换行，去除与完整声明或其中一整行相同的执行说明。条目另有的规则仍展示。通过新大厅的澜清挑战对局接口核对了八个状态的返回值，其中「裂伤」从三份相同全文归为一份。
- 角色、状态展示、澜清与其 AI 的 85 项专测全部通过。完整词条入口 207/208，原有林秋「分界」候选集断言仍失败。另对照展示层与画布的 27 项测试，修复前后为相同的 7 项失败或错误。

## Emyake 林羽（2026-11-24）

实现提交为 `24f1c77`。[_packs/emyake_lin_yu.json](_packs/emyake_lin_yu.json) 定义 12 生命、11 张常规技能和仅供触发的 0 费「闪回识破」。以《Emyake 林羽.docx》为印刷文案来源，逐字核对了全部 34 行骰面（含 SKIP）和 48 段被动、状态、技能说明。裂伤拘束使用作者在对话中补充的原文。

- 「流华幻影」的前两枚骰子在确认命中后，通过 `SET_SKILL_STATE` 累加本次使用的命中数。末骰确认命中后，已有的选项暂停接受玩家决定，`SPEND_STATUS` 接收选定额度。伤害与追加裂伤读取本笔实付回执。前骰都落空、末骰落空、只付一层、放弃支付，以及支付被词条减量均有执行器验收。
- 「剑术·羽流」在使用时核对实际持有的势和技能费用，判定第一枚印刷斩击骰。结算奖励时读取当时的势，获得剑术状态后清势。羽流·终每回合可转化 X 铭刻，折影化铭刻最多持有 8。折影额度计入当时可用铭刻，优先支付，回合末清除余额，保留折影化铭刻本体。
- 裂伤以百分之一伤害为单位累积，只在爆发时向上取整。延攻取造成该次骰子伤害的角色。按作者裁定，2 延攻对 8 裂伤造成 5 点骰子伤害，目标存入 1.4 点。裂伤拘束仍在时可连续钳制，每轮最多实付一层。折影交织维持 24 层上限，使用后在 24 层改作超穿甲爆发。
- 「折影吞噬」在开牌前指定实体技能时绑定该牌，指定角色时只接受原目标角色使用的应对牌。折影记录被移出的实体，下一次施加时送回其所属牌堆底。对方对应常规交锋的封印在下回合计算两张技能的射程和费用前生效。
- 单方面攻击的迎击按实际目标发出。被改向的攻击和分开的拼点也走迎击时点。付费迎击和「纯粹之心」额外迎击分别记账。「折影交织」用插入技能时的参数给同一份「闪回识破」施加本次迎击的加强。
- [角色专测](tests/test_emyake.py) 共 22 项，全数通过。完整入口 `python -m unittest tests.entry_semantics` 为 202/203；改动前基线为 180/181。两次均只有林秋「分界」的实体候选集断言失败。另行对照的六组历史模块共 64 项，改动前后失败的 33 个用例相同。三个调整过的桌面对战 JavaScript 模块通过语法检查。
- 本次实现复用了工作区已有的选择暂停。该功能在验收时仍是另一项未提交改动；单独移植林羽提交时需要同时具备这项依赖。

## WAA东部4科三人卡包移植到新版（2026-11-24）

- **已确认文义与迁移范围**：
  - 在不改动任何内核文件的前提下，将 `_packs_legacy/waa_east_four.json` 完整移植至新版 `_packs/waa_east_four.json`（阵营 `WAA东部四科`，含莱克 `waa_lake`、格罗琳娜 `waa_grolina`、厄尔克斯 `waa_erkes`，各 3 张技能），补齐 `充能`、`纯能`、`能源封印` 三项 `status_rules` 与 `polarity`，并统一全部词条 `description` 为 `【触发器】` 及 `{N}点{等级}伤害` 规范格式。
- **执行路径迁移要点**：
  - 阵营被动「WAA东部四科」的 `on_hand_changed` 使用 `$event.previous_count` / `$event.hand_count` 与 `$player.characters` 筛选存活友方施加 `充能`；`能源封印` 的 `BEFORE SPEND_STATUS` 保留 `["POP", 0]` 以维持封印阻止消耗时返回 `0`（而非取消为 `None`）的原有语义。
  - 莱克「突击」与格罗琳娜「推进输出」分别通过 `0 DUEL_OFFSET 1 null LOOKUP 0 EQ` / `0 GT` 与 `$player "lose" -1 DUEL_OFFSET CLASH_COUNT 0 EQ` 精确识别当前交锋序列的首场与上一交锋拼点失败数（开牌前与常规互不混算）；「应变」使用 `CLASH_COUNT` 统计本回合胜场。
  - 格罗琳娜「快速行动」与「阻滞」使用 `$player.speed` 与 `$player OPPONENT {"field":"speed"}` 比较速度；「借机」使用显式 `ADD_DAMAGE_MODIFIER` 与 `SPEND_STATUS` 回执；全部延迟施加（`QUEUE_STATUS` / `NEXT_TEAM_STATUS`）改写为标准 `schedule`（`on_turn_prepared`）。
  - 厄尔克斯「自发增压武器」使用 `$event.damage_status` / `$event.target $self IS` 与 `$pending.amount`；「武器增压迸发」通过卡面隐藏的 `AFTER SPEND_STATUS` 词条累计本技能实际消耗的 `充能` 至 `$owner.use_state["spent_charge"]` 供第二骰读取，并通过 `on_dice_use` 登记 `burst_repeats` 控制末骰至多重复 3 次。
- **验证结果**：
  - 新增专测 `tests/test_waa_east_four.py`（5 项）并接入 `tests/entry_semantics.py`，`tests.test_waa_east_four`（5/5）与 `tests.test_displayer`（12/12）全部通过；`tests.entry_semantics` 180/181 通过（唯一失败项仍为改动前工作区既有的 `test_boundary_declares_candidates_and_revalidates_the_chosen_physical_card`）。

## 统一决策原语 CHOOSE_OPTION 与选角色界面重设计（2026-11-24）

- **统一内核决策原语 `PromptDecision` + `OpCode.CHOOSE_OPTION`**（`models/opcode.py`、`models/opcodes.py`、`models/special_actions.py`、`game.py`）：
  - 新增 `PromptOption`、`PromptDecision` 与 `OpCode.CHOOSE_OPTION`，与 `CHOOSE_CARD` / `CHOOSE_SLOT` 共用同一条 `decision_owner` 挂起与续体执行机制，支持任意词条在任意时点或主动动作中弹出多分支选项，并可在分支 `then` 内继续链式嵌套 `CHOOSE_CARD` / `CHOOSE_OPTION`（无需为单个功能在底层加特例字段）。
  - 顶层桥接（`displayer.py`、`battle_ui/match.py`、`battle_ui/session.py`）将 `option_decision` 统一投影为 `effect_choice.selection = "option"`，并在开放阶段（置卡/开牌前）投影 `table_actions` 供前端在角色旁挂载主动印章，通过 `trigger_table_action` 一键触发。
  - 前端 `table_overlays.js`（`buildEffectChoice`）新增 `selection === "option"` 纯分支选项卡片渲染；`game_director.js` 在角色旁渲染开放窗口的主动能力印章。
- **澜清被动「深秋工作室」**（`_packs/jingzhi_lan_qing.json`）：
  - 以单条声明式主动入口动作 `lan_qing_autumn_studio`（`window: "placement"`, `target: "self"`, `per_turn: 1`）+ `CHOOSE_OPTION` 四选一实现：1. 获得 2 护盾；2. 链式 `CHOOSE_CARD` 为 1 张己方已置卡赋予 `range_bonus +1`；3. 链式 `CHOOSE_CARD` 为 1 张己方已置卡执行 `SKILL_LEVEL_ADD +1`；4. 本回合 `TURN_DUELS_ADD +1` 并 `TURN_COST_ADD +1`。
- **选角色界面精简重设计**（`table_overlays.js`、`game_director.js`）：
  - 移除 `1v1/3v3/5v5/10v10` 规模预设、`1~5 / 批量×N / 编入×1` 批量控件与 10 个空编号占位格，改为按实际已选人数自然排布的顶部编队台。

## 2.5D 活牌桌转正、开牌前交锋重做、扣置卡背与规则修正（2026-11-24）

### 已确认规则与内核修正
- **所有远程技能可在开牌前打出**（`models/card.py`）：`Card.can_open_pre_reveal` 新增 `self.effective_range > 0` 通则，常驻远程（澜清「转势·涌流灌注」、赫克「枪刃迸射」、林秋「空断」）与当前满足条件的条件远程（流阴「洞穿希望」、李凌「机动·贯彻长空」）统一自动获得开牌前权限；仅单颗骰子带远程的近战技能（如「出其不意」）不受影响。
- **骰间插入技能继承当前交锋目标**（`pipeline/pipeline.py`）：子管线加载 `before_die` / `after_die` 插入的技能牌（如林秋「出其不意」插入「空断」）时，若无显式声明目标，则从挂起的父技能 `parent_pipe` 继承当前交锋仍存活的目标角色，避免对方牌已耗尽时误退回全局默认集火目标。
- **林秋「分界」指定摧毁范围**（`_packs/xinxing_lin_qiu.json`）：移除 `$event.item.character == $event.target` 限制，命中后可指定并摧毁敌方本回合仍在场的任意一张未摧毁技能。
- **扣置牌角色卡背与归属公开**（`battle_ui/match.py`、`displayer.py`、`card_print.js`、`combat_tabletop.js`、`game_director.js`、`table_overlays.js`）：
  - 扣置牌卡背严格采用所属角色特征色，并支持角色 JSON 配置 `"card_back"`（内置 `star`/`diamond`/`rings`/`lattice`/`crescent`/`crest`/`wave`/`portal` 纹样或 `{pattern, color, image_url}` 对象）。
  - 鼠标悬停对方扣置牌时不掀牌、不泄露卡面，弹出「归属 · 角色名」徽章并点亮角色归属连线；`effect_choice` 选牌面板中的扣置牌同步展示所属角色名与角色专属卡背。
- **回合结束暂停时机**（`battle_ui/match.py`）：回合结束暂停点提前至 `before_turn_end`（`logic_turn_end` 回收牌之前），使已结算交锋与卡牌保留在牌桌上供复盘，点击「下一回合」后再执行收牌。

### 2.5D 常驻牌桌、开牌前重做与三渲二骰子转正
- **2.5D 活牌桌正式接管主干**（`combat_tabletop.js`、`game_director.js`）：
  - 统一承载置卡、开牌前、开牌、战斗焦点与回合结束平铺，严格左右对称（左 P1 / 右 P2）与平放统一实体牌面；支持 Hermite 手牌飞入、卡片中心物理悬停抬升、2.5D 原地翻牌、P2 视角飞牌方向、`effect_choice` 焦点行徽章/叠牌选点、战中拖拽同步，以及每帧同步平铺静息槽位矩形（修复回合结束连线残留战斗放大坐标的旧 bug）；修复 `_renderClashMedallions` 重复重建导致 `effectMarks` 访问已销毁 `Graphics.clear()` 的报错。
- **开牌前交锋声称与预置解绑重做**（`battle_ui/match.py`、`battle_ui/session.py`、`combat_tabletop.js`、`game_director.js`）：
  - 置卡期新增独立「声称开牌前交锋」开关（不锁常规置卡；未声称且无预置时置卡后自动跳过己方主动进攻，对手攻来仍自动弹出迎击/放行）；声称后解锁独立的「预置开牌前」模式，支持私密预排草稿、费用/目标动态校验、60fps 动态瞄准连线与开牌前一键发出；迎击阶段自动聚焦待响应行并提供醒目的待迎击投放槽与「放行此交锋」按钮。
- **三渲二 3D 骰子与风格化 DCC d16**（`three_world.js`、`physics.js`、`presentation_fx.js`、`timeline_sequencer.js`）：
  - 保留严格队列阻塞（上一批骰子未自然消失不放下一批）、不穿模半径与静息高度、原版爆发式拼点对撞；以 `ENABLE_CLASH_Z_BOUNCE = false` 保留但禁用对撞 3D 纵深落地回弹分支（注释明确记录其为悬空与无限翻滚根源），并修复摧毁/跳过骰子补生成重影与拼后无限翻滚。
  - 按 DCC 严格对跖截球体（8 对平行圆形平面 + 光滑球面腰带）完成粗勾边三渲二风格化与单例缓存实装，替换原双八棱锥 d16。
- **收尾清理**：前置安全存档提交 `6af94a8` 后，删除冗余目录 `battle_ui/static/mock_clash/` 与 `game_director.js` 中旧牌桌死代码（`preDuelPage`、`_combatRail`、`_duelScrollCtl`、`buildBoardCardTag` 等）。本次收口按作者要求未运行自动化测试，均经实机对战与代码路径核对。

## PlanB S级条目·萨（焦黄风暴）卡包移植到新版（2026-11-24）

- **已确认文义与迁移范围**：
  - 将 `_packs_legacy/yellow_storm.json` 完整移植至新版 `_packs/yellow_storm.json`（角色 ID `plan_b_sa`，`PlanB` 阵营，`BOSS` 级，15 生命，7 张常规技能），保留全部 4 项专属状态（`崩析`/`崩裂`/`弥合`/`崩离`）、6 项被动（`S级条目`/`Plan B`/`焦黄风暴`/`弥合裂隙`/`狂暴毁灭`/`崩析灭除`）及 7 张技能牌与《正式规则书》中的反震、追伤、引爆优先级与回收裁定。
  - 所有专属状态补齐 `polarity`（`崩析`/`崩裂`/`崩离` 为 `negative`，`弥合` 为 `positive`）；全部词条 `description` 统一规范为 `【触发器】` 标注与 `{N}点{等级}伤害` 格式；自定义直伤段（「闪进解离」末骰、「黄风漫天」首骰群伤）声明结构化 `damage_part` 以直读投影；纯内部状态/锁层/追伤辅助钩子标记 `hidden: true`。
- **执行路径迁移要点**：
  - 所有旧字段别名（`$original_max_hp`、`$in_turn_end`、`$damage_die_is_attack`、`$is_attack`、`$did_deal_damage`、`$target_alive`、`$printed_level`、`$enemies`、`$next_duel_target`、`$next_duel_enemy_skills`、`$skill_target` 等）全部改写为显式路径与集合指令（`$self.original_max_hp`、`$game.turn_ending`、`$event.die.is_attack`、`SLOT_AT_OFFSET` + `REMAINING_CARDS` + `FILTER` + `FIRST` + `CHARACTER_OF`、`SELECT_SKILL_TARGET` 等）。
  - 旧 `when` 字典改为显式比较列表（含 `BEFORE STATUS` 中使用 `$pending.amount`）；旧 `QUEUE_STATUS` 改为标准 `schedule`（`on_turn_prepared`、`after_turns: 1`、`through_turns: 1`、`uses: 1`、`require_source_alive: false`、`require_target_alive: true`）。
  - 旧 `DIE_STATE`/`SKILL_STATE` 改为 `$event.die.use_state` / `$owner.use_state` / `$event.card.use_state` + `LOOKUP`；旧 `USED_SKILL_THIS_TURN` 与 `FIND_SKILL` 改为 `SKILL_USE_COUNT` 与 `ZONE_CARDS` + `FILTER`（按 `character IS $self` 精确筛选）+ `FIRST`。
  - 旧 `{"op": "damage", ..., "from_die": true}` 改为 `"credit": "die"`；旧 `{"op": "damage_add", "amount": 1}` 改为 `ADD_DAMAGE_MODIFIER`；无返回值调用 `ACTIVATE_STATUS` / `SPEND_STATUS` 直接执行不额外 `POP`，需要返回值时（「分崩离析」末骰）显式使用 `{"call": "ACTIVATE_STATUS", "result": "result", "default": false}`。
- **验证结果**：
  - 新增专测 `tests/test_plan_b_sa.py`（12 项）并接入 `tests/entry_semantics.py`，覆盖全卡包编译、四项状态边界与阈值对照、`S级条目`/`Plan B`/`弥合裂隙` 阈值对、全部 7 张技能牌、「闪进解离」跨交锋/无下一交锋追伤、「分崩离析」末骰引爆优先级与远程压制、以及「黄风漫天」高低崩析分支与组合回收正反对照。
  - `tests.test_plan_b_sa`（12/12）与 `tests.test_displayer`（12/12，含全卡包结构化 `damage_parts` 与 `【触发器】` 全检）全部通过；`tests.entry_semantics` 175/176 通过（唯一失败项 `test_boundary_declares_candidates_and_revalidates_the_chosen_physical_card` 为改动前工作区既有未提交改动所致）。

## 流阴技能组打磨：逆流溯源触发条件与重打覆盖（2026-11-24）

- **已确认文义**：
  - 「逆流溯源」的回退触发条件由原先“环境压制再次减少至使用时的相同层数”改为“**环境压制减少至 0（清空）时**”触发，同步更新 `_packs/guangsheng_liu_yin.json` 与 `_packs/printed/流阴.txt` 卡面文案。
  - **边界**：在生效前再次打出「逆流溯源」时，直接用本次使用时的生命值与个人状态覆盖旧存档，且只保留 1 份待生效回退监听；回退生命仍通过 `SET_HP` 直接回退，不触发回复类被动（如「篡改万物」的全场光点伤害），也不因回退洞悉而触发战甲获能。
- **执行路径**：
  - 使用角色 `rule_state` 的 `逆流溯源生命`、`逆流溯源状态` 保存最新快照，`逆流溯源待生效` 标记是否已挂起单次 `on_status_changed` 预约（`previous_stacks > 0` 且 `current_stacks == 0`）；归零触发时先复位待生效标记，再按正面/生命取 `MAX`、负面取 `MIN`、中性取存档值执行 `RESTORE_STATUS_STACKS` 与 `SET_HP`。
  - 环境压制归零时，`deliver_scheduled` 先于普通监听器执行，先完成逆流溯源回退（环境压制取 `MIN(0, then)=0` 保持归零），随后「行至阴处」正常发放 12 层领域洞悉。
- **溯源标记与通用状态动态描述**：
  - 在 `_packs/guangsheng_liu_yin.json` 新增纯标记状态 `溯源标记`（`cap: 1`、`polarity: "neutral"`、无 `status_entries`），「逆流溯源」使用时挂上 1 层，环境压制归零完成回退后通过 `-1 STATUS` 移除。
  - 在 `displayer.py` 新增通用声明式投影 `_status_details`：按 `status_rules[<状态名>].display_fields` 实时求值并投影为 `character.status_details`（支持 `plain` 与 `status_map` + `exclude` 过滤）。`溯源标记` 声明展示 `已记录生命` 与过滤掉 `环境压制`、`溯源标记` 后的 `已记录状态`。
  - 前端 `game_director.js`（脚下状态悬停浮窗）与 `table_overlays.js`（角色侧栏「当前状态规则」）统一将 `catalog.statuses[name]` 与 `character.status_details?.[name]` 直读拼接展示。
- **天性解放 state 由环境压制统一维护**：
  - 将「行至阴处」的“首次归零获得 12 领域洞悉（仅一次）”拆到独立标记 `已获归零洞悉`，不再与 `天性解放` 混用。
  - 在 `_packs/guangsheng_liu_yin.json` 中由「天性解放」的 `on_status_changed` 统一维护 `rule_state["天性解放"]`：`环境压制` 减少至 0 时置 `true`，`环境压制 > 0` 时直接解除为 `false`；底下 3 条效果词条（减压制转能源、拼点开始 1 光点、拼点失败 1 光点）只检查 `rule_state["天性解放"] == true`，不再各自重复判断 `环境压制 == 0`。
  - 环境压制重新变为正数（如解放后再打「逆流溯源」+6）时，`天性解放` 解除，减少环境压制正常扣减直至再次归零，此时「逆流溯源」触发回退并清除「溯源标记」，`天性解放` 重新置 `true` 且不重复发放 12 领域洞悉。
- **验证结果**：
  - `tests.test_liu_yin`、`tests.entry_semantics`、`tests.test_displayer` 共 209 项全部通过（断言压制 > 0 时 `rule_state["天性解放"]` 确实为 `False`，再次归零时恢复 `True` 且不重复发放 12 洞悉，并验证解放后重打「逆流溯源」全链路）。
  - `node --check` 校验 `game_director.js` 与 `table_overlays.js` 均通过；`test_game_stage.mjs` 与 `test_data_driven_display.mjs` 全部通过（`test_director_stage.mjs` 2 项失败来自工作树既有的 `combatTabletop.setLayout` 未提交改动，与本次修改无关）。

## 数据直读卡面与统一触发器高亮规范（2026-11-24）

### 规范总则
- **能读数据的全部直读数据，前端禁止用正则猜卡面**：
  - 技能名读 `card.name`，费用读 `card.cost`（及 `card.resource_cost`），技能特性读结构化字段。
  - 骰子类型读 `die.type`（含 `skip` 专用样式 `DIE_STYLE.skip`），数值范围由 `formatDieRange(die)` 直接读取 `roll_max`/`level`/`base_value`/`multiplier`/`final_bonus` 拼接（`skip` 显示 `SKIP`）。
  - 伤害部分由后端 `displayer.py` 的 `_split_die_entries` 从引擎固定伤害段直接投影为 `die.damage_parts`（支持 `normal`/`pierce`/`concept`/`lightcore`/`real` 五级，含 `0` 点伤害段）；已投影的固定伤害段不再重复出现在 `die.entries` 中。全界面统一只输出唯一标准格式 `text: "{N}点{等级}伤害"`（彻底移除 `label`/`exact` 与 `shortText`/`exactText` 双格式混用，窄牌与微缩牌也不再退化为 `1普通`/`1光点`）。同步将 `_packs` 正文中所有残留简写（`群1光点`、`群伤2`、`1物理`、`1超穿甲`、`1伤`、`1光点伤害` 等）统一改写为 `{N}点{等级}伤害`。前端 `resolveDieDamageParts(die)` 与 `buildDamageBadge` 直接读取 `die.damage_parts`，彻底删除 `extractDieDamageBadge`。
  - 移除旧的 `printed_sheet` / `printed_text` / `printed_line` / `printed_rules` / `printed_profile` / `printed_heading` 覆盖旁路（清理 `loader.py`、`displayer.py`、`models/card.py`、`models/dice.py`、`battle_ui/match.py`、`terminal_bridge.py`、`battle_mcp/static/app.js`、`card_print.js`、`design_system.js`、`table_overlays.js`），全部 8 位角色（含流阴）走同一条数据直读渲染管线。
- **触发器纯字符串扫描替换与着色（零正则）**：
  - `_packs` 内全部 8 位角色及 3 个共享效果包（共 11 个 JSON 文件、459 条词条）的 `description` 统一改写为以 `【触发器名称】` 标注触发器的标准格式（不重复书写前置时机词）；字符串关键词（如 `"引燃"`）由 `describe_entry` 投影为 `【命中时】引燃。`；为流阴 3 处动态远程字段补齐 `description`，为赫里斯 `heris_crush` 补齐缺失 `description`。
  - 前端 `design_system.js` 提供纯字符串扫描器 `parseTriggerSegments(text)`（仅用 `indexOf('【')`/`indexOf('】')`，无任何 `RegExp`）与分类函数 `classifyTriggerSeries(name)`，将成对 `【触发器名称】` 替换为 `[ 触发器名称 ]` 并按统一规则着色（`TRIGGER_STYLE`）：
    - **“使用”系列**（含“使用”或“用骰”）→ 蓝色（`0x1c6cc4`）
    - **“命中”系列**（含“命中”或“暴击”）→ 黄绿色（`0x5c8a14`）
    - **“拼点胜利”系列**（含“拼点胜利”或“拼赢”）→ 橙色（`0xd96b0b`）
    - **“拼点失败”系列**（含“拼点失败”或“拼输”或“拼负”）→ 红色（`0xc92a2a`）
    - **默认（其余全部触发器）**→ 黄绿色（`0x5c8a14`）
  - 覆盖范围：`buildFullCard`、`buildBoardCardTag`、`buildUnifiedDieRow`、`buildUnifiedEntryPlate`、`buildHeroSidePanel`、`buildPassiveDrawer`、`buildRosterOverlay`、`buildCodexOverlay`。

### 验证记录
- 前置存档提交：`b08c504`（存档：前端演出重构与对战画布去网页化）。
- `_packs` 校验：8 位角色全部通过 `load_characters_from_packs` 载入，11 个 JSON 文件内 0 条非规范词条；`git diff b08c504 -- _packs/` 确认仅改动 `description`、流阴 3 处远程字段说明与移除 `printed_sheet`，零运算/操作码改动。
- 语法与零正则检查：`battle_ui/static/engine/*.js` 全部通过 `node --check`；`design_system.js` 与 `card_print.js` 零文本正则匹配；全库无残留 `printed_text`/`printed_line`/`TIMING_STYLE`/`extractDieDamageBadge`。
- Node 前端专测（`node --import ./tests/frontend/register.mjs --test tests/frontend/test_game_stage.mjs tests/frontend/test_director_stage.mjs tests/frontend/test_data_driven_display.mjs`）：15/15 通过，含成对对照验证（五类触发器系列着色与 muted 灰化；结构化 `damage_parts` 渲染伤害徽章 vs 仅在 `entries` 写 `"2穿甲"` 时绝不正则猜徽章；`card.name`/`card.cost`/`die.type`/数值直读并忽略遗留 `printed_text`/`printed_line`）。
- Python 专测：308/308 通过（`tests.entry_semantics`、`tests.test_displayer` 含全部 8 角色结构化伤害段与 `【触发器】` 全检、`tests.test_liu_yin`、`tests.test_lan_qing`、`tests.test_heris`、`tests.test_carrier_challenge`、`tests.test_entry_execution_paths`、`tests.test_room_pacing_and_dice_presentation`、`tests.test_canvas_battle_engine.CanvasBattleEngineTests.test_liu_yin_renders_structured_data_and_colored_triggers_on_cards_and_in_catalog`）。

## 对战画布去网页化（2026-11-23）

作者评价：整个对战界面被一批网页式部件拖垮；攻击特效与 3D 骰子对撞必须保留。作者点名的五类问题部件全部改为游戏内表现，攻击特效、骰子对撞、`TimelineSequencer` 时序与内核桥接均未改动。

- **交锋进度**：删除可滚动交锋列表、圆角条目、「已完成/待结算」标签、细滚动条、「回到当前交锋」胶囊和顶部文字进度轨（`buildScalableDuelRail` 已移除）。`combat_timeline.js` 改为 `buildDuelGemTrack`：竞技场顶端一条宝石线，一场交锋一颗（开牌前六边形、即时细菱、常规方菱）；已结算暗色实心，当前金色并呼吸光环，待结算空心。悬停宝石把该场的牌以小实体牌浮出，点击钉住。若可选的场上目标位于非当前交锋，宝石带翠绿外环；效果选择仅一场含目标时自动钉住，目标经 `_markEffectTarget` 在浮出的牌上点选。战斗舞台不再滚动。
- **中央卡面**：两张平铺原文大面板改为 `buildActiveDuelStage`，在对撞区下方左右各立一张实体牌（`buildBoardCardTag`，各向内倾斜），悬停看完整原文。`buildBoardCardTag` 新增 `activeDieNumber`，高亮当前骰位。空位只画淡色牌影，不写「无迎击技能」。`combatCardRects` 仍按 side 提供给特效锚点。
- **场内行动**：删除顶部提示栏、胶囊按钮行、「清单(N)」及其全屏清单（`buildSpecialOverlay` 已移除），也删除手牌上方的操作面板。`field_action_workspace.js` 改为两部分。`buildFieldActionLayer` 把角色主动能力做成圆形纹章，悬挂在该角色头顶；无目标能力直接发动，有目标能力先点亮再点目标。选中手牌后，牌上方弹出一弧圆形印章，每个直接动作一枚（置入、按牌面打出、以此牌发动能力、迎击；进攻或替换目标只有一个时也给印章），悬停才显示名称。多个进攻目标仍只在战场上发光点选或拖放。`fieldDockActions` 把「返回战场」「放行即时 N」、让过等无空间对象的选择并入右下指令坞的封蜡按钮。Esc 先放下选中牌或已点亮的能力，再按一次才离开场内行动。
- **字幕与提示字**：删除拍次字幕条（`createBeatCaption` 已移除，`createLightcoreBar` 保留）。掷骰和对撞期间收起推进按钮，落定后再出现，不再显示「掷骰中…/对撞结算中…」。对撞勋章也不再写「投掷中…/对撞中…」。
- **查阅面板**：`table_overlays.js` 的竖向和横向可拖拽滚动条统一换成 `makeScrollCue`。没有轨道和滑块，只在仍可滚动的一端显示黄铜小箭头，点一下翻约一页，滚轮照旧可用；工厂原有的 `onChange` 与 `_updateThumb` 契约不变。被动典录里的「查档 ↗」文字链接换成折页档案图标，整行仍可点开角色档案。

### 验证记录
- `node --check` 覆盖 `battle_ui/static/engine/*.js`，全部通过。在 PIXI 替身下导入 `game_director.js`，ESM 链接成功，没有缺失导出。
- 新增 `tests/frontend/`（PIXI 替身 + 加载钩子），运行 `node --import ./tests/frontend/register.mjs --test tests/frontend/test_game_stage.mjs tests/frontend/test_director_stage.mjs`，10/10 通过。成对对照包括：悬停待结算宝石出现浮牌，悬停当前宝石不出现；钉住的浮牌在指针离开后保留，并只标出该场目标，未钉住时不标；轨道上没有「已完成/待结算/回到当前交锋」等字样；双方均有牌时左右对立，缺一方时只画牌影且无文字。另外三组：一张牌有一个进攻目标时出现印章，有两个时不出现；无目标能力直接发动，有目标能力点亮后再点一次熄灭；有待处理进攻时不提供「返回战场」，无待处理进攻时提供。另用真实 `GameDirector._rebuildCombatShowdownStage` 驱动两种情形：普通战斗时两张舞台牌都在，没有浮牌，也没有滚动提示字；目标位于常规②的效果选择会自动钉住常规②，并只标出 1 个目标。
- Python：`tests.entry_semantics`、`tests.test_room_pacing_and_dice_presentation` 通过。`tests.test_battle_session` 有 3 项失败（「出战角色不在本房间的卡包中」、热座新局模式为 `timing`），属于既有问题：在干净的 HEAD 工作树上同样是这 3 项失败。这次只改了前端 JS，与此无关。
- 未在浏览器里目测；视觉需作者实机确认。

## 画布前端解耦重构与演出时序对齐（2026-11-23）

### 事实与顶层桥接边界
- 内核 `models/opcodes.py` 的 `lightcore_damage`、`lightcore_collapse`、`lightcore_restored`、`card_destroyed`、`die_destroyed` 事实补充 `side`、`character_id`、`character_name`（及卡牌/骰子标识）字段，原有键名与结算顺序不变。
- `battle_ui/table_bridge.py` 顶层桥将上述五类内核事实直接投影为桌面动画事件，不向内核回写任何 UI 状态。
- `battle_ui/session.py` 为热座 `BattleSession` 增加单调递增的 `match_number`，`action == "new"` 时递增，避免热座重开时前端因旧 `lastFxSeq` 漏演或误播回合初速度骰。

### 前端正交拆解与视觉保留
- 新建 `battle_ui/static/engine/timeline_sequencer.js`（无 PIXI 依赖的纯状态机）：统一管理单调 `lastFxSeq`、同轮 `dice_roll + dice_clash` 去重合并、严格 `combat_strike` 先于伤害/光点/摧毁/阵亡排序、跨拍清理残留 3D 骰子与物理对撞组、速度骰平局重掷清场与全程遮蔽直到胜负落定、`pendingCombatRollKeys`（点数先投后显）与 `pendingClashOutcomeKeys`（物理对撞瞬间揭示胜负与姿态）、延迟释放 HP 与光点完整性条、以及完成门控 `isSettled`（`autoPace` 仅在演出落定后倒计时，绝不腰斩动画）。
- 新建 `battle_ui/static/engine/presentation_fx.js`：将所有事件演出注册为独立处理器，完整保留并强化 3D 多面体骰子对撞（`physics.js` 同步 `lungeDelay=0.34s` + `onImpact` 回调）与攻击特效（斩击弧光、突刺光枪、打击震波、护盾碎裂、角色自定义 `FxDirector` 配方与 WebAudio 音效），并新增光点伤害、光点形态群崩塌、光点重建、卡牌摧毁与骰子摧毁专用视觉与飘字。
- 新建 `battle_ui/static/engine/beat_caption.js`：拆分角色脚下晶莹光点完整性条（`createLightcoreBar`）与不遮挡舞台的实时拍次叙事带（`createBeatCaption`，在速度/拼点未揭示前自动隐藏防止剧透）。
- `battle_ui/static/engine/design_system.js` 彻底删除 `INLINE_TOKEN_RE`、`TIMING_PREFIXES`、`STATUS_NAMES_SORTED`、`classifyInlineMatch`、`tokenizeLine` 与正则猜框/猜高亮逻辑，恢复纯 `PIXI.Text` 原文排版；`battle_ui/static/engine/card_print.js` 为 `card.destroyed || card.state === 'negated'` 的牌面增加猩红碎裂交叉与「已摧毁」印章。
- `battle_ui/static/engine/game_director.js` 删去 515 行耦合的内联 FX 调度代码，改为组合 `TimelineSequencer`、`PresentationFx`、`BeatCaption` 与光点完整性条，并补全角色脚下速度文本的开局遮蔽。

### 验证记录
- `node --check` 检查全部 13 个前端模块均通过。
- Node ESM 专测（`scratch/test_frontend_refactor.mjs`）6/6 通过：覆盖同轮去重与打击先于后果、两拍制“先滚骰锁定后端 → 解锁 → 物理对撞”严格阻断门控、速度平局清场重掷全程锁定且不复播、战斗中重连不误播速度骰及新局重置、`collectChronicleDuels` 已完成/当前/待结算分区、以及 `analyzeFieldActions` / `resolveFieldHighlights` 活桌面场内行动空间映射。
- Python 单测全部通过：`tests.test_room_pacing_and_dice_presentation`（10/10，含单方面攻击与拼点均严格先停在掷骰拍、待下一拍才执行命中/拼点结算的断言，以及光点伤害/崩塌/重建、卡牌与骰子摧毁桥接投影、热座 `match_number` 递增专测）、`tests.entry_semantics`（161/161）、`tests.test_displayer`（9/9）、`tests.test_liu_yin`（30/30）。

### 二期细化（2026-11-23）
- **光点血槽零跳变按需显现**：角色脚下血条基座（`hudBoxH`）与护盾/状态行（`row3Y`）保持固定像素坐标；光点完整性条（`createLightcoreBar`）默认隐藏（`alpha = 0`），仅当角色首次受到光点伤害或完整度上限降低时在预留细槽中平滑展开淡入，全过程零布局跳变。
- **掷骰动画期间严格阻断后端**：`battle_ui/match.py` `_combat_stop` 新增 `logic_dice_clash` 与未播报 `before_dice_hit` 断点，使单方面攻击与拼点都在掷出点数后立即暂停于结算之前；`TimelineSequencer.isRollAnimating` 在速度骰、掷骰、物理对撞期间全面阻断 `GameDirector._sendAction` 的推进与出牌请求并将推进钮锁定为「掷骰中… / 对撞结算中…」，待动画完成后才释放并进入结算；PVP 房间同步提高掷骰拍超时兜底并由客户端在动画落定后自动投票推进。
- **骰子与技能摧毁专属 3D 碎裂特效**：`three_world.js` 新增 `spawnDieShatter`（多面体剪影 + 猩红交叉斩裂 + 12 块 3D 四面体碎片炸散）与 `spawnCardShatter`（牌面猩红对角裂痕 + 8 块 3D 翻飞撕裂牌片），`audio.js` 新增 `dieShatter` 与 `cardShatter`，并按真实战场牌位与对撞勋章坐标精准锚定触发。
- **交锋完成缩小上移与滚轮纵览**：新建 `battle_ui/static/engine/combat_timeline.js`，战斗阶段中已完成交锋自动缩小为紧凑历史条并上移至当前对撞舞台上方（默认露出最近一场已完结交锋），待结算交锋列于下方，鼠标滚轮可在中央竞技场内自由上下浏览历史与后续交锋，并附「回到当前交锋」一键回正与悬停看原稿牌面。
- **高自由度活桌面「场内行动」**：新建 `battle_ui/static/engine/field_action_workspace.js`，移除遮屏选择题弹窗，进入场内行动时保持战场角色、场上交锋位与完整扇形手牌全部鲜活可交互；点选/拖拽发光手牌可直接指定敌方角色进攻、点击场上牌替换、置入交锋或按牌面打出，顶部浮条呈现角色主动能力与即时回应，并保留可选「清单(N)」回退视图。

## 流阴卡面原稿（2026-11-23）

作者最后贴出的全文保存在 `_packs/printed/流阴.txt`。从“光生会 执政 流阴”到「形态灭杀」末句按原稿保存，包括全角标点、非断行空格和段间空行。流阴的角色介绍、五个被动、三项专属状态、十一张牌与「领域覆写」从该文件取印刷文字。卡包继续按先前确认的对象和状态结算，例如「领域覆写」选敌方，「战甲塑造」给目标施加环境压制。印刷文字保留本次原稿中的“任意目标”和“领域压制”。

「无形杀」斩击保留“拼点逆转”。实际置入常规交锋，用 3 点对 7、1、3 点分别拼赢、拼输、拼平，命中依次归流阴、对方和无人。骰子变为空白后恢复普通胜负条件。「逆流溯源」从 5 压制起用牌，先到 11，打击命中后到 10，拼输后到 14，平局停在 11。使用后减少 2，持有能源时再减少 1，「行至阴处」首牌另减 1。六组交锋逐笔核对了实际层数变化。

完整词条专测 161 项通过。另两项画布专测通过，覆盖图鉴、选人界面、两种宽度的完整牌面、战场小牌、战甲两种形态以及同调图标切换。房间网页的角色与 12 个技能弹窗、终端输出另与原稿逐字比对。扩跑画布模块和点数模块时，改动前的 `fa84b16` 同样有 1 个断言失败和 8 个错误，涉及旧阵容、存档资源和旧词条测试。

## 流阴与变动点数（2026-11-23）

优势次数与劣势次数在获得时按数量相消。实际拼点时只发生一次用骰和一次 ROLL，分别完成两次变动点数取值，优势取大，劣势取小，随后扣一次。3 与 7 的劣势结果为 3。速度和单方面攻击不使用次数。两种选择由共享能力词条声明，SAMPLE_ROLL_VALUE 走原有变动点数修正。专测更改取值规则使原始随机数的大小顺序反转，并核对取值次数、ROLL 次数和能力余额。完整词条专测通过 116 项。

### 执政·流阴

- 18 生命、28 初始完整度、4 个基础常规交锋，11 张常规技能。「领域覆写」独立于起始牌堆。10、20、30 洞悉各登记一次，跨过多个新档分别预约。在下回合开牌前由玩家任选存活敌方角色，每次生成独立的免费使用，走通常的技能及骰子管线。专测核对两次预约、选中非默认敌人、两张不同的副本和两份零费回执。
- 同调转换符合条件的物理段。3 同调、近战斩击的 1 物理产生单段 4 光点。实际结算的物理段才另行追加等量光点。「肃清引信」取目标当前生命上限的三分之一，向上取整，单独结算超穿甲和追加光点。
- 极限远程压成空白、明确无效化、摧毁都会发布技能失效的事实。反制摧毁具有最高话语权。自毁也触发反制。「形态灭杀」固定使用 1～100；本骰造成的崩塌才额外削完整度上限，条件成立时三次即死分别与免死比较话语权。回手且立即结束当前交锋时，下一编号仍正常结算。
- 「逆流溯源」每次使用各自保存压制基准、生命与个人状态。一次减少后的值恰好等于基准才回退。回退直接设置生命与状态，不产生回复、获得洞悉或战甲能源。正面状态与生命保留较高值，负面状态保留较低值。「强行适应」在 3 生命、10 洞悉时实付 2，变为 1 生命、12 洞悉。
- 「画地为牢」针对目标下回合第一场实际开始的交锋。变动点数为 8 的骰变白，为 9 则保留；下一场的 8 保留。共享能力次数在获得成功时抵消，取消获得保留原有次数。
- `python -m unittest tests.entry_semantics` 通过 139 项，其中流阴及其引入规则的专测 25 项。标准流程对安诺琳，种子 7 由流阴于第 4 回合获胜，种子 31 由安诺琳于第 7 回合获胜。额外核对 `test_lightcore`、`test_cost_opcodes`、`test_range`、`test_ability_effects`，与改动前的 `c4f9c1b` 相同的 3 项断言失败、24 项错误，逐项比对了名称和末行错误。旧模块仍依赖归档角色、旧词条语法或已移除指令。

基线为 `0a9faaf`。本文件保存当前对话中用户的原话、可核对的设计决策、验证记录与接续点。后续涉及引擎行为的提交同时更新本文件。提交历史记录每一步对应的版本。

## 用户原话（按对话顺序）

> 在我未严格监管的时候，AI往我的代码里下毒了。有那么几条，就破坏了我的代码的纯洁性。
> 这些都是“投机编码”——只考虑特定的业务逻辑，对可以复用的内容进行封装，导致执行时不透明，并破坏开发和维护体验。编码应该遵循**语义标准**，语义是怎么样的，就应该怎么写代码。**一切以自然语言描述为基准，在自然语言的基础上开发，为的是使用代码还原自然语言的语义**

> 先列出有依据的问题，我来定修改范围

> 这不是最严重的问题！

> 不允许这么检查！

> 你去读代码。不准去实际跑程序，只分析代码本身。不准grep，要读就他妈给我通读。通读，只能读游戏内核的文件，不准读外部配置。**不准读规则，不准读卡包，不准读战斗日志，不准读测试脚本**。

> 这些根本不是投机编码

> 就这点？

> 数量级不对。

> 你刚才列出的1根本不是投机编码，2是

> 我都说了不是一个数量级的了！就这么几个？

> 这些到底是哪里有问题？

> 我说的是投机编码，不是让你把所有 bug 都列一遍。全部重新查，不准只在这些条里筛选。只留把特定业务塞进通用封装、偷换原本语义的地方。逐条说清自然语言怎么描述、代码实际怎么做、特例藏在哪，符合的一条都别漏。原来的限制照旧，先别改代码。难道投机编码都在内核里？你觉得这些都是投机编码的话那还怎么编游戏？if __name__ == "__main__"都他妈算投机编码？鼠标按下都算投机编码？看敌我双方都算投机编码？？？？

> 什么叫“投机编码”？

> 投机编码在哪里最多？

> 同一条代码，什么时候判它是投机编码，什么时候判它合格？

> 接近了。继续去思考，将这种思路推广

> 给我举代码中的例子，两个即可。讲讲怎么把投机编码解耦

> 目前问题最多的就在于词条这里，因为这里AI最喜欢偷懒。这里是重灾区。但是不意味着其他的游戏内核逻辑就不存在投机编码。你派一个子代理去按照这种标准再查除了词条以外的（也就是dice, player, character之类的）地方的投机编码，然后你自己把有关于词条、OpCode这些的投机编码都列出来，怎么解耦也都列出来，并把相似的或者解耦之后有重合的东西放在靠近的位置。

> 问你一个问题：
> def once_per_round(vm):
>     key = vm.pop()
>     vm.push(key not in actor.round_triggers)
>     actor.round_triggers.add(key)
> 这个算不算投机编码？为什么？如果算的话，怎么改？

> 错！这他妈就是投机编码！不管返回什么都他妈算投机编码！为什么？

> 错！

> 我认为最直接的问题就是把查询和1次绑死，其他的由于我也没读过，我看不出问题（但不代表它没问题）。我说“错”，是因为你没有显式指出“一次”的投机问题

> 理论上，在抹除了投机编码之后，角色的词条长度会普遍增长2~5倍，而负责解析词条、OpCode等代码的代码量将减少至原先的20%左右。同时，builtin_operations会增加不少条目。这些是我的直觉所带来的预言，由于我没看过代码，所以不保证准确，也不是追求的目标。
> 话说现在builtin_operations还有用吗？

> 现在导致出现这种混乱的成果，多半是因为没写builtin_operations导致的。builtin_operations的初衷是提供便捷、高效的写法，如`"DRAW 1"`就直接代表了抽1卡，是利好角色设计的。我不知道是从什么时候开始把它删掉了，我认为删掉它是一种损失。还是我刚才的预言，如果启用builtin_operations的话，角色的词条长度只会膨胀至2~3倍。你读过builtin_operations，不要重复读取。

> 现在的代码已经不能通过小修小补来完善了。而且由于这个游戏在开发时就把cli的print、input等耦合在了后端逻辑，这部分也需要进行真正的解耦。这将会是一场彻彻底底的革命，会血洗之前的所有代码，并以你自己惊世骇俗的代码能力将屎山重构成令人叹为观止的、代码本身具有美学价值的工业级后端代码。
> 有关于前后端解耦：必须写一个桥接器，而桥接器只能出现在顶层拓扑里，不能探入深处。
> 重构后，整个体系将变得极度完备。目前我只能幻想到重构后编写新角色的样子（其他的我现在尚无法幻想到，代表着我对它有极高的期待）：我创建一个角色，可以直接先写一个通用的builtin_operation（如果是新开辟一个体系的话，甚至可以把它丢到通用的文件还里），然后在角色的json里写下一行行的entry，用entry去进行编程——后续可能还会开发出专门用来写entry的代码编辑器（足以见得我对于entry的期望有多高），实现我最终想要达到的角色的玩法。如果当前后端不支持，我就会把我要做的东西先尽可能用已有的东西去拼，留出一个原子化的缺口，然后在后端里把这个小缺口补上，为后续的开发搭桥。然后，就爽玩新角色去了。
>
> 我信任你，是因为你有足够强大的能力。希望你不要辜负我的信任。
> 步步为营，结硬寨打呆仗，每完成一个小步骤就进行一次git提交，每一步都严格去遵循我设下的理念去走。始终维护一个_CurrentMind.md文件，记录我的每一句话以及你的思想，避免上下文压缩导致你的能力下降。

## 决策与接续

- 从设计者的文字可读出数量、主体、条件、顺序和记账时点。查询返回事实，例如实际次数。具体词条比较 `< 1` 或 `< 2`。
- 基础操作提供可组合的简写。抽一张与抽两张共享抽牌动作。代码量与词条长度属于事后观察指标。
- 前端桥接器位于应用的顶层。内核表达动作、结果及待决定的问题；终端输入、网络会话、提示和呈现属于外层。
- 现有工作树里已有未提交的 UI、MCP、资源、测试等修改。只提交本次编辑的内容。
- 已核对 Git 历史。提交 `a3306f0` 将抽牌、用骰、置卡三个内核入口切到直接执行 OpCode，并新增现行词条解释入口。
- 本步建立重构记录。下一步核对现有前端驱动对局的真实入口与内核动作之间的依赖；文件阅读和运行验证依用户给定范围执行。

### 用户补充的阅读与测试范围

> 允许读写相关前端、CLI、角色JSON（只允许读取PlanB、新星组织的角色），必须读取规则（还必须读我自己手写的那份规则），战斗日志不准读，本地测试不准读，并且你要单独开一个文件，在那个文件里写新的测试。测试**应当**聚焦于探索所有边界情况、改变所有可能改变的量，并且测试针对的对象应该是解析器、执行器这类的事物而非整个系统。改变所有可能改变的量的意思是，任意数字，任意枚举值都要能够成功。同时测试也必须追溯“到底是怎么执行的”，避免投机编码让整条线跑通，但是是以不合适的方式跑通的。这些测试要测的不是“能不能行”，而是“跑得漂不漂亮”。

- 正式规则书第 1.5 条分别定义回合、交锋与轮。角色的每轮计数随骰轮重置，插入交锋仍使用管线已保存的外层计数器。查询与记一次各自有独立指令，阈值留在词条内。旧写法按原有求值顺序展开，保留“每次求值都登记”的旧行为。
- 用户随后提供手稿《光点三spec.txt》。已通读全文。手稿明确将“轮”定义为骰子层面的循环；“致命失衡”写的是“每一轮内至多减少1层”。这两处分别对应计数器的生命周期与词条里的上限。
- 新文件 `tests/test_entry_semantics.py` 直接驱动真实 VM，记录指令前后时点与栈快照，覆盖重复查询、独立记账、旧写法的顺序、轮次替换及大整数。

> 可以，只运行新测试

- 设计者可以在 `entry/builtin_operations.py` 或已加载的系统模块中声明指令如何展开。安诺琳的“A级条目”直接按印刷顺序写 `DRAW 1`、`HEAL 2`，展开到原有带前后时点的执行器。
- 已单独执行新文件中的四项测试，全部通过。抽牌还核对了实际栈参数、指令前后时点、牌序和超出牌堆张数时的结果。
- 选角交互已迁入顶层 `TerminalBridge`。共享池、镜像回池、预留名额、提交次序由独立的选角执行器处理。无效阵容在改变牌池前即被拒绝。内核只根据确定的阵容入场。
- 手稿明确先从候选置底，然后把留下的牌收入手中。CLI 和网页现共用 `DrawChoice`，结算一席之后才为下一席读取牌堆。重复、过期、范围外的答复均在移牌前拒绝。新测试穷举小牌堆的查看数、留牌数及所有置底排列，同时检查每次移牌与抽牌的顺序。
- 顶层终端桥负责同屏换手、特殊行动和开牌前声明。常规置卡现在由同一内核入口处理当前行动方、可用手牌、窗口容量、提早交权及结束。网页及回放驱动使用同一入口；管线前进到开牌前的条件是双方均已结束置卡。
- 护盾、资源、伤害等 OpCode 在结算点记录事实，含当时的数值。终端桥拉取并呈现；无观察者时不会积存记录。护盾测试遍历每种合法名称及正、零、负和大整数，同时核对真实指令及产生的事实。
- 回合、交锋、先手、声明、牵制、拼点和用骰的终端输出已迁至顶层。扣牌替换的公开事实只包含玩家和原牌去向，公开的换牌才带卡名。清除开牌前阶段残留的同屏换手调用。
- 手稿要求未指定目标时可临时选择。席位可声明下一次有多个合法候选时自行答复。核心只发布候选并等待该声明的结果，已有对位以及零或单候选直接结算。顶层终端桥在工作线程推进单个命令，在终端线程交互；无需回滚、重跑或向深层注入前端回调。专门测试两次连续选择之间的执行轨迹。
- 命中执行器统一记录命中方式和本骰第几次命中。旧终端会省略首次完整命中的文字，此呈现选择保留在桥外层。覆盖三种命中方式与多个命中序号，并核对随后才进入暴击判定。
- 通读席位房间投影时发现它还从原网页驱动读取常规置卡的窗口大小。已将这个消费者也切换为内核的同一容量字段。
- 每次实际使用技能与每次实际拼点结果分别记账。词条可取某个角色或一方在指定交锋及整个回合的胜、负、平次数，可用任意有符号的交锋偏移量。旧的“用过”“赢过”“上一场输过”由次数比较得出。验证包括同名技能由多人使用、同编号不同序列及同场重复输赢。
- 词条可直接读取 `$self.hp`、`$event.target` 等数据路径，并可对集合筛选、遍历、取长度、比较成员和调整优先顺序。“技能集满”展开为筛去战斗外牌、逐张检查在手、确认常规技能非空；“本回合赢过”展开为胜场数大于零。筛选谓词有独立的操作栈，错误条件无法消费外层参数。
- 条件骰位及状态形态可显式指定比较符与阈值，原布尔标记仍按原义。每次数值变化都重新核对相关形态，仅在形态实际改变时重建骰序。并列状态判定分别结算成功或失败的后果后，再汇总是否暴击或失衡。测试遍历六种比较与两项独立判定的四种成败序列。

- 将词条 JSON 在注册时编译为可检查的指令序列。引用、局部变量、引用代码块与带引号的字面量在指令中分别保留；每次执行和延后选择使用本次的变量与事件。无参数作者指令可组合，递归展开报告整条循环路径。独立测试 21 项通过。

- 角色直接记录本次伤害中每一层盾实际吸收、磨损与生命损失。新增测试在结算回调里补盾，确认这笔补盾不会被误算为负吸收。先攻、回收、支付与翻牌也从实际变更处产生事实，以供顶层取用。22 项新测试通过。

- 网页版现在创建原生 Game、Player 和 Character。顶层 TableBridge 从事实还原网页协议，删除了网页为出动画而重写的先攻、护盾、回收和被动结算。被动提示现在以具名词条完成执行为准。已同步适配工作树原有、尚未提交的房间画布事件和机器人目标选择两处调用；这两处只存在于原有本地改动。24 项新测试通过。

- 原生 OpCode 可按已声明的操作数顺序直接写为一行，作者简写优先。旧 TEAM_STATUS 与 NEXT_TEAM_STATUS 展开为命名参数、正数比较、逐成员存活检查及普通或延迟施加指令。绑定结束后恢复外层同名变量。测试覆盖所有已声明原生指令签名及敌我以外的自定义队员组合、数量、名称和两种生效时点。26 项通过。

- 五份获准角色文件中，38 个可直接按文字顺序书写的旧程序改成作者指令，并迁移了旧回复简写；复杂的计算仍保留其步骤。赫里斯群体能源显式说明数量、存活条件和遍历。新解析测试逐个注册五份文件中的词条，核对林秋先获得隧道、再抽牌、最后给指定目标加星结的完整指令及操作数。27 项通过。

- 复核实际卡包入口时发现，执行器已接受骰位阈值，但 loader 仍拒绝字典形式。现在加载阶段与执行阶段共享比较符。用新测试生成临时卡包，经过真实加载器验证六个比较符、负数、零、大整数及无效条件；隔离共享配置读取。28 项通过。

- 订阅条件在注册时转为两个操作数与一个比较符。字段可来自事件、拥有者、任意键的状态表或 BEFORE 监听当下的待执行操作数；只有待执行操作数的条件推迟至实际轮到该监听时读取。新测试让前一监听改写数值，逐一核对六种比较及原始/改写值反向跨阈值。赫里斯的烧伤条件使用同一语法。30 项通过。

- 旧式 Draw/Heal/Status/Shield 等操作现在在注册时编译，继续使用原来的目标选择与事件归属，复用同一指令执行路径。卡牌朝向、当前置卡的位置锁定、窗口查询可以独立使用；旧 reveal_lock 展开成有明确前提的两次写入。验证全部 CardState、窗口开闭、独立解锁和暗牌名称保护。32 项通过。

- 作者可显式调用一项 OpCode，独立声明执行选项、要读取的回执字段与缺省值。旧的伤害量、实际花费、是否付足等写法统一展开为这项语法。测试遍历所有枚举，区分无结果、False、零、负数和大整数，每次只调用一次。旧拼写的业务定义已移出编译器。33 项通过。

- 旧的“我方/目标/全场技能”“下一场敌方待用技能”“个人速度差”等字段改成可查看的取值与集合表达式。交锋偏移、席位、读取起点、存活条件、归属与结果顺序均独立；取下一场使用偏移 1。参数化测试核对负数、大偏移、不同席号、多队员交错、销毁牌与死亡角色，并断言展开路径。35 项通过。

- 林秋的选牌、是否必须可使用、费用减免及插入技能分别表达。选择保存本次执行的变量和事件，后续用牌读取命名参数；可使单纯选牌允许当前无法打出的牌。网页根据明确的预览字段展示折扣，回合选位、放弃选牌的文字也回到前端。验证同一词条的两次未答复选择不会串用局部值。36 项通过。

- 对照历史字段协议，保留缺失可选事件字段的空值、非角色目标的存活/完整度默认值。未声明且本次事件也未提供的裸字段会指出拼错的名称；显式可选读取可写 $event.name。同一目标的判断按对象身份。37 项通过。

- 实际入口进一步核对：缺席或多席阵容在创建角色前被拒绝；非法置底答复可重试，执行抽牌监听时同一答复已不可重入；终端与网页版复用同一合法扣牌集合。席位主机按发布边界消费事实，纯网络对局也不积攒未读动画事实。39 项通过。

- 新增单独的共享 builtin 算术模块，登记 DIVMOD。赫克、赫里斯、李凌的累计消耗分别写出换算基数 8、保存余数和取得凝聚。编译器和 VM 无须认识角色或资源名。测试对正负除数、零和大整数逐条核对展开，除零恢复原操作栈。保持不重新读取 builtin_operations 的限制，仅追加其导入声明。40 项通过。

- 词条可分别写立即改掷骰值与预约下一次掷骰修正。伤害修正可指定收取修改的列表、增减/倍率/护甲类型、数值与穿甲级别，旧写法仍映射到原时点。全程保留整数精度。测试使用真实 d4 的上下限，核对预约仅在下次掷骰兑现，并对三种等级、三种修改和两条通道检查唯一写入。42 项通过。

- 查找牌与置入交锋已分开。旧 place_skill 按席位选择第一张匹配卡，旧 FIND_SKILL 按角色选择，两者的原有不同语义在展开式内可见。状态键、骰/技能局部键、已花资源和指定交锋的状态损失使用通用映射查询。新测试用同 ID、不同角色的两张牌逐个验证四种牌区和过期交锋。43 项通过。

- 投影边界复核发现：多状态共同触发失衡时，动画应消费整次失衡的结果，零项检定也应有一次结论。现分开记录每次真实掷骰、各自的成败和汇总；暴击公开结果读取 on_critical 结算后的层数。44 项通过。

- 新增拓扑检查逐个解析 37 个内核模块的完整语法树，发现并清除了 Card.print 残留的两次终端输出。网页版部署阵容改用与 CLI 相同的 Game.deploy_rosters。其余新增检查覆盖词条执行中途取消后恢复栈、跳过下一指令，以及所有普通执行指令与操作数签名一一对应。47 项通过。

- 终端桥在主线程直接等待命令结束或席位提交候选，不向内核保存的 Future 注册前端回调。测试核对内核执行与终端提问分别位于不同线程，提问中断会解除等待并恢复上一份席位声明。48 项通过。

- 星结的批量锁定原先在 Game.resolve_status_batches 发布事件后强制清零溢出并压低层数，载入器也强制要求 reduce_to。现可仅累计溢出、仅发出批次、在监听器结束后执行自定词条，或组合使用。林秋 JSON 显式写出 SET_STATUS_OVERFLOW 与 CAP_STATUS；后者只编排取层数、求差、比较及普通 STATUS，保留监听机会。测试覆盖只有事件、只清累计、只降层数、两者一起、旧格式和超大累计值，核对名单冻结与先攻顺序。51 项通过。

- COPY_SKILL 原先把副本归属者、按 ID 查其自身技能、取首张和使用印刷数据绑在一个 Python 词里。其旧拼写现展开为 FILTER、FIRST、读取 printed_data 及 SKILL_COPY。新词可以用任意已经选定的印刷数据与独立指定的角色构造延迟副本。赫里斯的追击触发来源用 OR 表达「技能或骰子」。52 项通过。

- TAKE_HAND_CARD 旧实现隐含敌对席位、随机选取的位置以及新控制者三项选择。旧入口保留，同一份 RANDOM_ITEM 简写按集合长度抽一个索引，在 TRANSFER_HAND_CARD 前完成选取。词条也可指定一张牌交给敌方或本席队友；同席换控制者保留手牌顺序。抽私有手牌使用 SAMPLE_INT，公开判定使用 RANDOM_INT，测试核对前者的索引不会出现在公共事实里。53 项通过。

- 技能和骰子上的 range_level_when、ignore_range_when 也曾把本次技能的状态读取为布尔值。两者现与条件骰位共用相同的比较器与声明校验。测试分别构造真实技能、真实骰子，遍历两类远程属性、四个合法等级、六个比较符，核对缺失键、阈值两侧和大整数。54 项通过。

- 用单个实际管线节点核对历史记账：未付费或已撤回的技能不登记，连续两次实际使用分别在 on_skill_use 监听器内读到 1、2。实际拼点胜、负、平先记入各自角色与交锋，胜利分支被远程压制时仍保留胜场。测试只调用对应节点与结果分发器。56 项通过。

## 按自然语言复核的语义问题

下表使用基线 `0a9faaf` 的旧行为与本次修改后的入口。表中的同组项目共享数据或指令。判定依据是词条作者能否独立表达自然语言中本来可以分别改变的量。

| 自然语言中的要求 | 原来的执行与特例位置 | 拆开后在哪里表达 |
| --- | --- | --- |
| 查询本轮已经触发几次，再决定是否登记这次 | `entry/program.py` 的 `ONCE_PER_ROUND` 查询集合成员并立刻写入。一次、两次及以上都只留下“已有”。 | `ROUND_TRIGGER_COUNT` 读数，`LT` 与词条给出的阈值比较，`RECORD_ROUND_TRIGGER` 独立登记。旧拼写中的常量 1 和登记顺序可在 `entry/legacy_operations.py` 看到。 |
| 查询某角色本回合使用指定技能的次数 | 使用节点原先向集合加入角色及技能 ID，重复使用同一技能会丢失次数。 | `pipeline/pipeline.py` 在实际进入 `on_skill_use` 时记账。`SKILL_USE_COUNT` 读出数字，旧的“用过”展开为大于零。 |
| 查询某角色或阵营在某场交锋里的胜、负、平次数 | `Game.record_clash_result` 分别记角色的胜利标记和阵营的败场集合；读取败场又固定上一场。 | `models/turn_history.py` 按序列、交锋位置、角色和结果计数。`DUEL_OFFSET` 选位置，`CLASH_COUNT` 选主体和结果，再按词条比较。 |
| 数值满足某条件时启用骰位、切换形态或获得远程等级 | `models/card.py` 的骰位及远程条件只认状态真假；`models/character.py` 也只在状态从无到有或有到无时复核形态。 | 状态值、比较符和阈值分别传入。卡牌和骰子读取同一条件，每次相关层数变化都会重新求值。 |
| 某次伤害量或资源量符合条件时响应 | 监听条件的字段名曾将主体、比较方向与取数时点捆在一起。前序监听器还可能修改待执行数量。 | `entry/predicates.py` 分别编译左右操作数和比较符。事件快照和 `$pending.amount` 各有入口，后者在轮到该监听器时读取。 |
| 同一时点的状态各自掷骰、各自结算成败，然后判断是否发生一次暴击或失衡 | `Character._roll_status_check` 在首个成功后提前结束，跳过后续状态的随机判定和效果。 | 每一项都产生真实判定，随后汇总一次结果。角色死亡或战斗结束仍然终止后续结算。 |
| 查找某区、某方、某角色或某交锋的一张牌；集满手牌；查下一场的敌方待用技能 | `entry/program.py` 原有专用字段一次选定自己的牌、所在区、存活条件、第一张、交锋偏移 1 或比较对象。旧 `place_skill` 还同时查找并置入。 | `entry/field_aliases.py` 与 `entry/legacy_operations.py` 公开集合展开。牌区、席位、交锋偏移、遍历起点、筛选、取首项、置入各自是一步。“集满”写明检查全部常规技能且集合非空。 |
| 从某张技能的印刷数据制作给指定角色使用的副本 | `COPY_SKILL` 在副本归属者自己的技能表中按 ID 取第一张，随即用同一角色构造副本。 | 筛选、取首张、读取 `printed_data`、构造 `SKILL_COPY` 分开；可以把选定的印刷数据交给另一名角色。 |
| 选择一张牌；由谁接手；是否必须当前可用；按什么价格插入 | `TAKE_HAND_CARD` 自带敌方判断和随机选取。`SpecialActions.choose_card` 的手牌资格、减费字段、后续使用和界面预览曾共用约定。 | `RANDOM_ITEM` 只选一个元素，`TRANSFER_HAND_CARD` 只转交指定手牌。林秋在 JSON 明写选牌资格、可放弃、减费 2 与插入位置。每次暂停都保留自己的局部值，答复时复核候选资格。 |
| 对所列目标逐个施加状态，或预约到下回合 | `TEAM_STATUS` 和 `NEXT_TEAM_STATUS` 各自内置了谁算队友、只选存活者、只处理正数以及执行时点。 | 在 `entry/legacy_operations.py` 中能逐步看到每项选择。词条也能直接选集合、用 `EACH` 遍历，再调用 `STATUS` 或 `QUEUE_STATUS`。 |
| 读取消耗结果、尝试付足或允许部分支付 | 旧程序词绑定了调用、是否要求付足、读哪个回执字段及无结果时用什么值。 | `entry/compiler.py` 的 `call`、`with`、`result`、`default` 各自声明。单次实际扣款可以返回已付数量或是否付足，零和 False 都能保留。 |
| 卡牌翻正；本置卡窗口锁住该位置 | `entry/effects.py` 的 `reveal_lock` 把窗口判断、牌面朝向、翻正和锁位做成一个效果分支。 | `WINDOW_OPEN`、`SET_CARD_FACE`、`SET_PLACEMENT_LOCK` 分开。旧拼写明确写出只对本窗口中的扣牌执行两次变更。 |
| 修改这次掷骰，或预约下次修正；修改指定通道的某种伤害量 | `roll_add/set` 通过当前时点选择立即或延期，`DAMAGE_ADD` 还隐含目标、修改列表和等级。 | `UPDATE_ROLL`、`QUEUE_ROLL_UPDATE` 及 `ADD_DAMAGE_MODIFIER` 的参数公开这些选择；老词在兼容展开中保留旧触发时点。 |
| 溢出可以单独累计；达到阈值时冻结名单、发布事件，并按牌面处理余额 | `loader.py` 要求每个溢出事件都有 `reduce_to`；`Game.resolve_status_batches` 发布事件后强制清零并截短层数。这是星结的整段后果。 | 可单独设 `track_overflow`，批次事件可以没有后续。林秋的 `then` 逐个清累计，并对仍存活的目标调用 `CAP_STATUS`。封顶量 6 在 JSON 中，一次必要的降层仍通过正常 STATUS 监听链。 |

### 角色作者实际使用的入口

- 安诺琳的“额外抽一张并回复二点生命”写作 `["DRAW 1", "HEAL 2"]`。林秋的“获得一隧道，抽一卡，施加一星结”写作 `["STATUS 隧道 1 $self", "DRAW 1", "STATUS 星结 1 $skill_target"]`。解析器按这三个动作的顺序保存指令，执行器在本次触发的事件中取目标。
- 赫克、赫里斯、李凌的能源换算共用 `DIVMOD $local.total 8`。除数、余数写到哪个键、商兑换什么资源都由角色定义。新增系统可以像 `entry/arithmetic_operations.py` 和 `entry/status_operations.py` 一样登记自己的简写。共享公式本身属于正常复用。
- `entry/commands.py` 接收作者的指令行，`entry/compiler.py` 在注册词条时展开，`entry/program.py` 把同一程序绑定到每次独立的执行。旧卡包拼写保留为兼容入口。

### 界面边界与验证范围

- `terminal_bridge.py` 负责终端问答与呈现，`battle_ui/table_bridge.py` 把内核事实译为桌面动画。选角、抽牌置底、常规置卡、先攻重掷、护盾吸收、资源支付均由共享领域对象处理。选择前后没有重放内核。该项属于架构重构，和上表的业务特例分开记录。
- 网页被动提示改为在有名称的词条完成时显示。即使它最终没有改变数值，仍可能出现提示。隐蔽抽牌的随机索引不会作为公开掷骰显示。
- 正式规则第 4.8 条描述重复使用骰子。对于同一次骰收到两个独立重复请求，手稿与已读条文没有给出独立累加的判据。保持旧有的合并行为，将其列为规则待定项。
- 唯一运行的测试文件为 `tests/test_entry_semantics.py`。56 个测试方法通过，其中包含循环枚举和执行轨迹断言。五份获准的角色 JSON 中带 trigger 的词条经过编译，39 个指定内核文件经过输入输出及依赖方向检查。没有启动游戏，也没有读取原有测试和战斗日志。由此验证的是具体执行器和适配边界；整局体验及其他角色的实战行为未覆盖。
- 基线与本次提交相比，`entry/` 加 `models/opcode.py`、`models/opcodes.py` 增加 1154 行、删除 459 行，净增 695 行，统计包含简写、兼容展开和新增指令。五份已迁移 JSON 的物理行总数净减 64 行。两项统计都不能直接换算为单个词条的长度或执行速度。
- 工作树已有用户进行中的前端、房间、机器人及旧测试改动。房间读取桌面事件和机器人声明目标优先级两处接线依赖这些尚未提交的代码，随其留在工作树。本次提交仅纳入可以独立归属本轮的修改。

## 用户提出的五处遗漏及静态核对

> 状态发动的 activation_multiplier / activation_final_divisor（effects.py 第 142-159 行、context.py 第 359-365 行、opcodes.py 第 656-657 行）：在通用 DAMAGE 里特判 trigger == "activate_status"，并把向上取整除数 (final + divisor - 1) // divisor 硬塞进通用最终伤害结算。
> canonical_status_name 硬编码 if name == "energy": return "能源"（character.py 第 258-268 行，以及注明为快照兼容的 bleed_burst 和 displayer.py 第 451 行）：已有通用 aliases 查表却仍硬写具体状态名。
> restrict_highest_hand_cost（character.py 第 283-293 行、card_space.py 第 82-94 行）：为“限制手牌中费用最高的 N 张技能”这一个具体状态规则，把费用排名记账直接焊进 Hand、Card、Character。
> pre_reveal_target == "occupied_enemy_slot"（pre_reveal.py 第 124-127、194-195 行）：字面只说选“有敌方置牌的交锋”，实际在同一个字符串分支里暗中绑死了 slot.required_card（那张牌离场则跳过整场交锋）。
> ability_options 里的 requires_draw_pile（special_actions.py 第 266 行）：在通用主动能力分发器里，单为“牌堆非空”硬加一个专属布尔开关。
>
> ---
>
> 上述这几个问题是真的吗？

- 赫克的本次引燃翻倍、李凌的重复引燃最终伤害折半向上取整有不同结算时点。Context.execute_op 以触发器名字选取修正，FINALIZE_DAMAGE 在数值边界之后统一读取专用除数。规则应能指定作用范围、阶段和运算。
- `energy` 在查正式名和 aliases 前就固定映射到能源。`bleed_burst` 是按通用 active_statuses 推导的旧输出字段，可在快照生成处保持原协议。裂血的爆发持续至归零，显示时应读取激活状态。
- 正式规则 7.3 明文要求出牌时留存费用顺位、使用时才按层数判定。专用排序与记账散落在 Hand.remove_card、Card.hand_cost_rank 和 Character.skill_restricted，后者还固定对多个同类标志取最大层数。
- `occupied_enemy_slot` 同时过滤可选编号并存下当时的下一张可用牌。放行后这张牌失效时，即使同位置有后继牌也会跳过本场。成功迎击另走迎击牌分支。正式规则 3.5 的通常处理是结算时才查该位置。
- `requires_draw_pile` 把行动方、抽牌堆、张数大于零写在能力候选生成中。提交时会重新生成候选，随后才支付与执行；若改为通用条件，应保留这个先后关系。
- 本轮仅静态核对并补记工作记录。

## 五项修订

> 把这些改掉

- 将 energy 登记为共享数据别名，与各包内的 aliases 汇合，正式名始终优先。快照直接从激活状态投影 bleed_burst。新增测试核对两种注册顺序、正式名冲突和状态层数相同但爆发标记不同的情况。

- 开牌前的 occupied_enemy_slot 只筛选声明时有敌方待用牌的位置，放行后按位置重新牵制。需要锚定原牌的卡可另写 pre_reveal_bind=declared_card。验证两种目标范围、两种绑定与替换／已牵空／成功迎击三条结算路径；查询候选不会推进牌位。58 项通过。

- 主动能力的 when 与词条使用同一套只读比较，可以声明读取的牌区、集合张数、比较符和阈值。旧 requires_draw_pile 在兼容层展开，实际提交仍先复核候选再支付。测试遍历四个牌区、六种比较符、空集合与极端阈值，并核对候选过期时没有支付或增加使用次数。59 项通过。

- 费用顺位已由状态声明候选集合、筛选、稳定排序字段和方向。Hand.remove_card 回归移除语义；置牌、声明、替换及自定义出牌在实际打出时记录，普通移区不记录。使用资格读取当前状态层数。新测试检查同费、队友、状态后取得、换排序字段与方向、普通移区和抽回重置。60 项通过。

- 赫克在 damage_multiplier 阶段执行 [2, MUL]，李凌在 final_damage 阶段执行 [2, CEIL_DIV]。CEIL_DIV 由已有的栈和整数算术指令展开。修正附属于本次词条执行，阶段程序使用独立操作栈；普通词条和状态发动共用相同机制。新增测试核对结算顺序、三种伤害等级、正负与大数整除、初次与追加引燃的骰子归属、独立追击和中途取消。64 项通过。

- 复核延迟弃牌区的回收路径：自定义出牌保留本次快照，重新入手时清除。新增断言覆盖该牌洗回、抽回、再次普通弃牌的完整顺序；普通移区和同区重排仍保持原有通知时点。置牌在修改牌位或占用次数之前完成观察。

## 重构前后实测

> 现在看看，我的预言有没有成真~

对照重构前的 `0a9faaf` 与六项修订提交完成后的 `6f20b68`。只做 Git 快照的静态计量。角色样本限于获准的五名 PlanB 和新星组织角色。按角色、被动或技能、形态、骰位和词条位置配对，209 对的触发器和原文描述均一致。统计角色本体中的 entries，包括 40 条字符串简写，不计角色外的共享状态定义。剔除 description，使用紧凑 JSON 的 Unicode 字符数。

| 范围 | 重构前 | 重构后 | 后／前 |
| --- | ---: | ---: | ---: |
| 全部 209 条完整词条 | 29,055 | 28,036 | 96.5% |
| 53 条改写的完整词条 | 7,548 | 6,529 | 86.5% |
| 全部词条的 operation 或字符串简写 | 19,754 | 18,682 | 94.6% |
| entry 下解析、执行、条件与兼容模块（物理行） | 658 | 1,172 | 178.1% |
| models/opcode.py 和 models/opcodes.py（物理行） | 939 | 1,228 | 130.8% |
| 上述两组加 context/context.py（物理行） | 2,388 | 3,186 | 133.4% |

- 后端口径固定，计空行和注释，剔除 builtin 主文件、算术、集合及状态三个作者指令模块。仅合计 program.py 和新增 compiler.py 也为 328 → 310 行。
- 配对结果为 156 条原样、48 条变短、5 条变长。完整词条的最大倍率为 1.46。只看 operation，赫克「贯彻之刺」的引燃由 30 增至 61 字符，安诺琳「A级条目」的抽牌与回复由 61 减至 19 字符。基线已有 152 条含显式 program，所以多项角色逻辑此前已经写在数据内。
- 新作者注册接口增加 9 个具名简写，主文件注册 DRAW、HEAL、DISCARD、STATUS、SHIELD，分模块注册 DIVMOD、CEIL_DIV、CAP_STATUS、RANDOM_ITEM。按增量核对，旧栈函数及按签名自动开放的原生 OpCode 单独看待。
- 现阶段观测支持作者简写增加。启用 builtin 后的角色词条 2～3 倍和解释执行代码剩约 20% 两项均未出现。本次比较没有提供完整等价且关闭 builtin 的第三个版本，故原先的 2～5 倍情形没有对照。

## 按语义重构角色与词条

> 现在开始改。把那21条兼容层、15条执行器或模型、6条词条本身的问题按根因归在一起改，4条受牵连的追到源头验证。108条合格的保留，2条文义待定的单独问我。该由角色决定的写进entry，builtin只做语义透明的简写，别再换个地方藏，也别凑20%。每完成一小步就用新测试核对实际执行路径，更新_CurrentMind.md，提交一次git。
> 同时，不要留任何兼容，不需要兼容层。既然是完全的大清洗，就应该把角色也都清洗了。
>
> 尽量消耗，只有 1 层也扣掉并激活
>
> 本骰每次命中都减少，包括未激活时
>
> 仍只开放 PlanB 和新星组织

首步处理 #012、#017、#037。末骰直接筛本次实例化骰上的实际 clash_result，压制跳过拼赢效果时仍计胜。同卡读取末骰标志的 #018、#019 沿用同一份标记。贯彻之刺只在首骰实际作为重复骰使用时增加计数，已请求而未使用的骰不计。新测试遍历胜负平与无结果、压制、不同上限和是否重复，追踪 FILTER、SIZE、加骰级、记录和重复请求。专用文件 2 项通过。未读取其他组织或旧测试。

第二步处理 #122、#126、#127、#138 和用户已裁定的 #150、#152。每笔预约命中携带自己的来源；驻留减伤只响应那笔预约。羽流记录实际成功而非首击序号。羽流剑术同时检查首次命中、伤害骰及其技能。新测试覆盖其他来源的仅伤害命中、失败后追加命中的重试、嵌套来源、0/1/足额消耗、未激活及交锋次数耗尽后的星结减少。6 项新测试通过。

第三步处理 #008。赫克的词条明确指定第一骰位、凝聚决定份数、单方面攻击触发、回合结束失效和实际用骰扣次。模型分别截取骰样本及登记迎击机会。专测 7 项通过，包括同一攻击两次观察、付费失败、过期、不同扣次策略、预览不会扣次。

第四步处理 #001、#002、#047、#055、#067、#069、#070、#084、#091、#094、#096、#111、#116、#117、#130、#136、#142、#156。阵营自行筛牌和给定集齐张数；群伤显式按主目标优先并检查命中成功；查场上牌和下一交锋的筛选留在各自条目。字段读取不会选人。需要决定单方面目标的条目显式发 SELECT_SKILL_TARGET，已有目标直接复用，缺目标跳过。新测试 9 项通过，包括每个角色门槛两侧、外部牌、缺目标、选人调用次数及群伤逐人顺序。

第五步处理九处增伤调用与 #004、#062、#066。每条明确传本段或整命中的修正容器。#026 从本次足额支付取回实付数，删除整卡累计消费账；#027 用同笔奖金施烧伤。词条显式指定引燃归属，赫里斯以本笔 STATUS 的直接签发条目对照引燃执行条目。12 项新测试通过，覆盖新增实耗的嵌套支付、嵌套扣烧伤、整命中与分段容器，并验证 #017、#018、#019 从真实胜场到末骰加成和摧毁。

第六步处理 #025、#057。远程数值可由只读表达式计算，赫克在骰面指定凝聚和上限。赫里斯在初始射程比较时明读当前凝聚，使用时先消耗能源、再锁定数值，之后读取这一快照。移除专用每层抵一级的字段以及缺快照自动读实时状态。新射程测试 5 项，和前两份专测合跑共 24 项通过。

第七步处理 #128。星结自行在回合收尾订阅一次，从先手起过滤存活角色与溢出阈值、冻结名单、发布星结事件，监听者完成后清零并按 6 封顶。删除 Game 的溢出逐回合扫描与专用结算器。三个阈值、镜像注册、事件期间改变候选人及重复进入时点的测试均通过。专用文件现有 13 项通过。

第八步处理 #135。DISCARD 结算指定实体手牌，由角色 entry 明确选择目标手牌第一张，从而保持原先弃哪一张的行为。普通弃牌原语不再选牌。空手、外部牌和任意手牌位置均使用同一条移区路径。14 项新测试通过。

迎击样本的冻结边界（#008）。保存骰子时冻结这次用牌的嵌套数值，保留被标记角色等实体的身份；每颗实际生成的迎击骰各自持有一份数值。单元测试经实体卡换持有人、两次建骰与再次消费重现并核对，迎击专测 8 项通过。

核对独立 Git 快照发现先前局部暂存使 PUBLISH 的处理函数、登记和 Context 的监听方法错位，且 Game 初始化须先创建 Context。已恢复正确作用域与顺序。迎击生产预览只检查候选骰是否启用，实际使用再走可拦截的支付。按索引导出这一步的内核、五份获准角色和三份新测试，独立运行 28 项通过，其中覆盖原价不足但减费后付得起，以及最终未付足而转试下一颗骰。

删除 field_aliases、legacy_operations 两份翻译表，五份角色文件统一采用明确的事件字段、局部变量、缺省值、条件、返回字段与公开关键词。#119 直接比较 STATUS 受者的待执行增量；#096 回到 #094，确认只扣使用时记录的那一名角色。新的 DRAW n 原样走 DRAW，覆盖 0、1、2 和大于牌堆的数量。伤害、具名关键词和旧字段的错误用法在新解析器处可区分。本步暂存快照运行 33 项新测试通过。

删除 QUEUE_STATUS、QUEUE_DIE_EFFECT 和对应的原生队列，授权角色在 13 处下回合状态与 3 处下一骰预约上声明事件、起止回合、次数、存活条件、冻结数据和执行体。林秋使目标下骰−4的效果在来源死亡后仍可兑现。核对预约体递归展开、调用方字段隔离、抽牌前及实际用骰入口、无效骰不耗机会，并逐包注册技能、形态和骰面。本步四份新测试独立运行 47 项通过。

继续追 #025、#057 的另一套射程入口：原先 range_level_when 和 ignore_range_when 另在模型里分辨速度差、状态层数、本次技能标记。五份授权卡包中剩余 5 处现也统一为只读取值表达式，卡面明定缺目标、速度差、阈值、结果和说明。测试验证空断的固有一级射程、隧道开启和重复标记相互独立，以及对手刚好比速度差门槛高或低一格。独立暂存快照四份新测试 49 项通过。

卡包载入遇到废弃的 restrict_highest_hand_cost、overflow_batch、requires_draw_pile 时会指出无效字段，避免原来有限制的状态或能力被当成无限制。只在加载边界报错，不转换旧定义。用合成旧配置走失败分支，另用五份获准角色定义走真实的定义注册；暂存快照四份新测试共 50 项通过。

终核 #091、#156：删除曾替调用者选择下一交锋首名敌手及预筛目标场上技能的三个模型方法。新测试从角色 entry 开始，追到实际转火登记及选择后摧毁。覆盖无下一场、已用或失效的牌、同队其他角色、响应时仍在场的那张实体，以及每次技能的次数。四份专测在独立的暂存快照中共 52 项通过。

复核旧审计中的 108 条合格项，按角色、技能或被动、形态、骰位、原文与触发器找到 108/108。49 条完整 JSON 相同，59 条语法或执行来源标注有迁移。#013 因移除前一条旧计数而前移。对新旧指令归一后，剩余差异为五处引燃改用公开关键词，另两处 QUEUE_HIT 标注来源；#126 的来源供 #127 精确扣减。四条连带项已逐条追根：#017、#019 取自实际胜场，#027 取自本笔支付，#096 取自使用时标定的旧目标。此次核对只覆盖授权的五份角色文件及其中的定义。

> 把你改完的东西写到文档里，并确保以后不要再出现投机编码问题。

在 docs/词条与内核开发规范.md 记录五份角色的迁移、两条「空断」裁定、entry/builtin/OpCode 的职责、顶层桥接边界及按反例追执行路径的验收方法。README 的选牌、支付、伤害归属、引燃和事件取值示例同步更新到当前语法。原有联机与人机介绍属于已有工作区改动。

专测直接从作者文档读取「回响」的 JSON，经角色监听、查询、比较、登记和 DRAW 验证空牌堆、他人命中、额度耗尽及换轮。计数原语独立变换角色、键和阈值；CAP_STATUS 与显式结算比较受者、实际扣层与 STATUS 事件数。在暂存快照中分别把查询改成“小于 1”的布尔结果、把登记塞回查询，两种错误均使新测试失败。恢复后同一快照的 55 项专测通过。统一入口为 python -m unittest tests.entry_semantics。

正式规则书 A.2 同步写明「空断」只剩 1 隧道仍激活，以及未激活、减交锋次数用尽时每次命中仍减 2 星结。使用真实骰面与新的执行路径测试单独核对上述边界。

> 继续

根目录 AGENTS.md 将卡面依据、可独立改变的量、查询和记账的分离、透明 builtin、顶层桥接和路径反例纳入持续开发约定。GitHub Actions 对 push 和 pull_request 运行同一个限范围专测入口。已在独立暂存快照用本地 Python 3.12 按工作流命令执行，并用 3.14 复核，各 55 项通过。托管端运行在推送后触发。

> 现在把所有其他卡包都移出_packs目录，放到_packs_legacy里面，然后丢到gitignore里。

按角色加载器枚举的根目录 JSON 归档。_packs 保留 PlanB 的赫克、赫里斯、李凌、安诺琳及新星组织的林秋。其余 10 份角色包原文件移至同级 _packs_legacy，逐一核对名称、大小和 Git 忽略规则；共享效果及美术资源保留原目录。词条专测 55 项通过。

> 推送到远端，并启动服务（pve，自动战斗程序）
>
> 允许迁移启动所需的共享定义

归档提交 6258da6 已推送。首次使用活跃角色启动时，基础状态「限制」因旧字段被加载器拒绝。获准后迁移共享定义：手牌限制明确保存本角色的稳定费用顺位，凝聚直接比较两项余额，烧伤和裂血声明各自的门槛，致命失衡分别查询本轮次数、比较上限 1 和登记。独立关键词引燃按本笔目标结算，回合末发动不读取未请求的返回值。新增路径测试覆盖同费与换序、共用回合额度、低层主动引燃、护盾抵消及每轮扣次；包含五个角色的词条专测合计 61 项通过。本地 PvE 用赫克和安诺琳初始化，可在大厅换人；已核对网页响应和玩家、电脑席位。

> 请你启动一个热座模式web ui

热座入口原来默认使用已归档的莱克。改用安诺琳与赫克，并让默认阵容走显式阵容的同一条校验路径。因 8765 已占用，另起本地回环服务。已核对首页 HTTP 200、状态为 placement、双方角色与五人选角列表，61 项词条专测通过。

### 澜清（幽兰残雪）与单方面掷骰

经值事务所强化首领，18 生命，11 张实体牌，初始 3 交锋、最低 2。「终雪」是第十一张牌。牌面中的「点击」按「电击」处理，「终雪」活化的牌为 5 费「残雪·幽蓝流光」。

- 每个技能名共享至多一次活化。实际用牌锁定本次骰序。同名另一张立即反映剩余额度。大招按三个其他技能名分别计数，满足至少两名且自身未活化时自活化，本次采用活化态；其余情况下仅活化其他常态技能。永久成长由持有者分项记录，骰级、基础值、最终点数与拼点点数各走对应的数值层。
- 经值按上回合从本人手中实际打出的次数回复及增加本回合通用费。致命失衡临结算时核对当前段伤害，低于 2 点不翻倍、不扣层，达到 2 点则应用倍率并转为穿甲。麻痹在真实战斗投掷取两骰之差的绝对值，按骰面范围取值，忽略速度骰与状态判定。电击按命中计数，电流溢出时由持有者在既有选牌桥接中逐张弃牌。

### PVE / 联机房间节奏改造与骰子点数呈现对齐

> 现在PVE的界面的实际游玩体验实在是折磨人啊。请你告诉我为什么我这么说。明明同源的热座模式玩起来那么爽
> 要是这样的话，双人联机+MCP房间的体验也是极度折磨的
> 可以，你去改吧。同时要对齐一点：所有骰子都是在【使用时】触发投掷的，而且呈现依赖于骰子点数出现。其他显示点数的位置也都要有这个约束：必须骰子先骰出数值，才能显示数值。注意：一定要让玩家玩得爽，不要卡来卡去的。

- `battle_mcp/room.py` 与 `battle_mcp/transport.py`：
  - 真人房间跳过无实际可发动特殊行动的空 `timing` / `advance` 节点（仅在 `reveal`、`combat`、`turn_end` 或有真人实际可执行特殊行动的 `scores_ready` / `技能使用前，可换卡` 停顿）；纯双 MCP Agent 房间（`human_seats` 为空）全速遍历与 `prepare()` 声明保持不变。
  - Canvas 单人 PVE（`client_paced`）取消服务端 0.85s 强制节拍，改由前端通过 `/api/canvas/next` 像热座一样控制（支持「下一拍」按钮、空格/回车快进、可切换自动推进、中途换阵重开）。
  - 联机 PVP 与人机 MCP 新增 `/api/canvas/next` 投票快进（人打 MCP 一键即进，双人 PVP 双方均点击立即推进）、合理的动态节拍（战斗 1.15s / 开牌与回合末 0.95s / 可打断窗口 1.8s）、终局再战（PVP 同阵容再战）、以及 `set_default_target` 容忍已更新的 `revision`。
- `battle_ui/match.py`、`three_world.js`、`table_overlays.js`、`transport.js`、`game_director.js`：
  - 单方面攻击骰与提前停在掷骰/拼点点数就绪的骰子统一触发 `dice_roll` 3D 投掷，且 `dice_roll` 严格先于 `combat_strike`；`ThreeWorld.launchDie` 新增 `revealDelay` 与 `onReveal` 回调，3D 骰子落地显数前所有显示点数的界面位置（交锋计分牌的变动/最终/拼点点数与胜负印章、双方翼区速度与先手标志、顶部先手徽标、被动抽屉速度、速度横幅、拼点姿态与后续打击/扣血特效）均保持隐藏或等待，骰子出数后再同步揭示并触发后续表现。
  - 解耦顶部暂停与全屏「场内行动」遮罩；修复 `_hasLiveHand()` 消除手牌在过渡期反复闪现重发；409/过期 `next` 静默同步不弹错。
- 验证：`tests/test_room_pacing_and_dice_presentation.py` 7 项专测全部通过（覆盖 PVE 客户端步进与中途重开、PVP 跳过空时点/投票快进/暂停继续/终局再战、人打 MCP 快进且保留微时点声明、纯双 MCP 声明、单方面攻击先掷骰后打击、拼点不重复掷骰）；完整 PVE 对局模拟 2 回合 31 拍零空时点顺畅终局；全部改动 JS 通过 `node --check` 且前端 `roomTableState` ESM 断言全通过。
- 「幽兰残雪」使独存骰进入正常拼负分支。「风卷残叶」取相邻场第一张技能的骰面投影、制作空白复制品，并按本场受击者对阵。占位毁骰保留一个空骰位。追加命中可以携带具体受者，逐人独立经过命中及受击监听。
- 单方面进攻依次执行战斗投掷、最终点数、命中。原先只解析骰级。专测追踪一次 ROLL、一次 RESOLVE_FINAL_SCORE 和一次 RESOLVE_HIT；已经掷骰并比较后拆成单方面攻击的骰保留原点数。

分别在独立测试进程中屏蔽独存骰结果、指定受者的额外命中、临时对阵复制品这三个动作，对应专测均在实际战斗断言处失败。用五名现役角色做对手，经完整回合驱动跑到终局的固定种子对抗包括 10 局一对一和 5 局二对二。

2 费活化「极锐刺」仅移动余骰。实体牌仍可在原交锋查到并被摧毁。末场登记原牌和本次用牌的骰组，原牌与本次使用仍有效时，继续原骰游标。原牌存活时不重复付费、用牌或占用交锋；中间场按原位置摧毁原牌时，末骰不再投掷或命中。这两个专测曾在移动整张牌的实现上同时失败。完整词条入口通过 83 项，其中本次新增 22 项；另有 6 项既有战斗与置卡回归通过。

### 澜清专用 bot

`python -m bots.lan_qing` 开一间本机单挑房，玩家一默认使用安诺琳，可用 `--opponent` 指定角色，玩家二由澜清策略控制。策略从本席可见局面和合法选项评估最多三张牌的顺序。开牌前迎击先于常规置卡付款，牵走的常规牌从原位移出后只计一次。打出三张手牌的收益、持有者生命、同名活化、连续命中电击目标以及留到下回合的活化均参与取舍。估分中的命中按预期收益处理，实战掷骰和付费仍由游戏结算。

8 项 bot 专测覆盖三组起手牌、5 费与 6 费的终雪连段、共享活化与大招两分支、致死自损、因电击而改变用牌、迎击挤占大招费用、溢出弃牌和真实席位终局。对战赫克时，驻留骰使公共快照抛出 AttributeError。快照现从被捕获的骰子模板读取牌名和骰位，从迎击机会本身读取剩余次数。新增的三视角回归在修复前复现异常。

83 项词条专测、8 项 bot 专测及全部 9 项快照测试通过。既有逐拍快照测试的数值引用已迁移到 `$event.value_ref`。安诺琳、赫里斯、赫克、林秋、李凌各由通用 bot 驱动，种子 0 至 5 的 30 场单挑均达终局，澜清获胜 30 场。独立启动命令后，通过本机 HTTP 的玩家一席位完成准备、出牌、逐拍推进及终局。

### 纸质版机操挑战 · 结构化载体

挑战房间使用本机玩家一的私人邀请，固定对手、专用策略和角色包随再战保留。`--challenge` 默认启用结构化载体，`--challenge lan_qing` 启用澜清策略。结构化载体的 18 生命、八个被动、10 张普通牌及 5 张决战牌见 `_packs/challenges/structured_carrier.json`。

- 普通、决战两堆独立洗牌，取各自堆顶，用后回所属堆底。骰模板前跳过通常回合抽牌，技能免付通常费用。模板 3 的两张普通牌指向最低生命者，初判至少 4 时等对方置完再重骰，重判仍至少 4 才用三张普通牌打最高生命者。反制在单方面远程技能使用前把一张普通实体牌放入本场，成功放入才加一级远程及登记本次次数。
- 正常冻结时，超过 1 点的伤害命中提供 2 层熔毁。初次真实伤害触发休止，原伤被挡，额外承受 3 点真实伤害。优先判定容器发射，发射中及休止中承受真实伤害都按原伤。休止覆盖触发回合和下一回合。回合末先按熔毁层数发奖励，再算自伤并衰减。8 层自伤 2、移除 3。发射开始冷却 6 个无效熔毁，结束前消耗 2 个容器。若在回合末奖励时获得第二个容器，新发射持续到下回合结束前。
- 发射把每段最终伤害转为目标生命上限的相应百分比，按超穿甲穿透等级结算。角色保留十进制生命余数，外部统一读取 `Character.hp` 的非负整数部分。9 血受 3.6 伤害后余 5.4，读作 5。再受 4.8 后余 0.6，判定阵亡。测试另含概念护盾吸收 3.6 后余 0.4，以及治疗后再受伤保留余数。
- 「扭曲障壁」摧毁交锋实体牌，超过两骰才由对手选择弃手牌。「复制复刻」实际转移对位实体牌的牌堆归属，原角色阵亡后仍留在载体普通堆。「弹反防御」重复骰仍能施加威压，1 点伤害每次使用技能只结算一次。被动激活的进攻骰有对位时可拼点，无对位时跳过。「怪物」先施加 4 威压，再按目标威压除 2 向下取整决定用骰数，最多使用五颗印刷骰。「一击穿心」读取上一颗实例骰的拼点结果，拼赢才同时给第二骰加 2 最终点数和 2 伤害。

词条、澜清策略、逐拍与快照回归合计 133 项通过，含 26 项本次载体专测。另有一项本机 HTTP 测试，分别用两种挑战的玩家席位完成编队、整局和再战，同时核对旁观者的隐藏手牌。改动的 7 个 JavaScript 文件通过语法检查。安诺琳、赫里斯组队对结构化载体，固定种子 0～15 的 16 局均在第 2～3 回合结束，均由载体取胜。另跑两个旧开牌前测试模块，15 项中 9 项通过。其余 6 项依赖旧词条语法或旧终端接口，逐项在 PvE 前置提交 `245bbb1` 上复现了相同报错。

### 限制改为全队状态

甲收到 2 层、队友乙再收到 1 层时，两人共用 3 层。受牌角色阵亡，层数仍属于这支队伍。费用顺位、最低费和手牌数量都按全队手牌计算。费用为 1、1、3 的三张手牌在 3 层时全部受限，4 层时两张 1 费牌均可选。版面与战报按队伍显示层数。

出牌时记录手牌张数、该牌费用顺位和更低费牌的数量，结算时读取当前限制。实际完成使用才通过 `after_skill_use` 扣 1 层，扣置、弃牌及支付失败均不减层。回合结束保留限制。整队未打出实体牌时，下回合开场的预约效果先结算，再把全队限制一次清空。其后获得的新层数继续生效。机操按照模板从牌堆直接出牌也计作该队已出牌。

六项队伍限制专测覆盖跨角色叠加与扣层、严格门槛及最低费并列、失败支付、原受者阵亡、公开快照、预约清除顺序和机操出牌。含词条、快照、澜清策略、房间节奏及出牌记录的 140 项回归通过。另有一项 HTTP 测试通过，结构化载体和澜清两种挑战都完成了整局及再战。

### 澜清的基础值增益归入个人被动

「残雪·幽蓝流光」末骰命中时，沿用 `SET_CHARACTER_STATE` 累加澜清的永久基础值。「幽兰残雪」在本回合首次即将拼负时记录回合号，后续每次实际用骰时读取永久加值，回合号相同时再加 2。这一临时加值已从状态和回合末清除名单移出。

新专测从真实出牌开始。末骰命中一次后，澜清下一张牌三颗基础值为 0 的骰子依次以 1、3、3 使用，对方三颗骰子的基础值始终为 50。下回合的首两骰分别为 1、3。旧实现的数值相同，但会向 `BEFORE STATUS` 监听者发送临时基础值的状态操作，专测在此处失败。迁移后该专测通过，完整词条专测与澜清策略回归合计 148 项通过。

### 结构化载体的被动记录与常驻强壮

「容器发射」记录发射窗口，「纳米休止」记录恢复冻结的回合号。「行为剖析」读写当回合的模板判定和修正，「修补堆芯」记录本回合熔毁免伤，「反制」只在实际迎击成功时登记次数。本回合记录保留到回合收尾词条结束，下回合开场清空，再兑现预约。双方的对局快照可查看发射、休止和模板的公开值。普通状态的枚举、回退和获得事件只处理卡面状态。

「乘胜」只向强壮提供常驻层数。存活敌人的总威压达到 12、18、24 时分别提供 2、3、4 层。威压降低、回退或敌人阵亡时重算，并保留其他来源授予的强壮。以模板 3 同时发射为例，此时快照可以同时显示两项被动进度。持有的常驻强壮计入实际强壮，普通个人状态回退只能读到载体容器、堆芯熔毁等普通层数。

词条执行与快照回归共 152 项通过，覆盖状态操作监听、回合末仍可读取及新回合清空变量、独立来源的常驻强壮、模板重判、真实伤害休止、回合末取得容器后跨回合发射。HTTP 挑战回归另有 1 项通过，验证玩家 1 的邀请、选阵、整局和再战。两处客户端改动通过 JavaScript 语法检查。

### 澜清的活化与涌流灌注

四种同名技能活化各自占一项可见状态。「转势·涌流灌注」使用时仍给予一次极锐刺活化，同时给使用者的回合变量「涌流灌注」加 2。澜清在非空白战斗骰结算最终点数时读取该变量；公开快照以被动数值展示累计加值，澜清策略也从这里读取。其他角色借用此牌时，首用为实际使用者预约本回合后续用骰的加值，同回合再用只增加记录。新回合清空加值，未花掉的活化跨回合保留。

旧实现在连续两次实际用牌时多发两笔涌流灌注状态操作。迁移后状态监听只收到两次极锐刺活化，两张牌的首骰最终点数分别为 10 和 12。流阴的回退专测在首次灌注后记录状态，再用一次、消耗活化，回退时恢复一次活化，加值保留为 4。借牌归还、未付费、空白骰、重复求值、公开快照及策略读取都有专测。词条、策略及展示回归共 165 项通过。

### 澜清的「枫落」

「枫落」替换第十一张实体牌「终雪」，沿用实体牌标识 `lan_end`。现为 4 费极限远程，四骰依次为斩击 1～12、斩击 1～12、斩击 1～8、突刺 1～12×4。使用时给 5 费「残雪·幽兰流光」一次公开活化，另按当时敌方总失衡快照为本技能加拼点点数。旧称「残雪·幽蓝流光·活化」仍会归入同一个计数。收势继续活化步枪系的「深秋·风卷残叶」。

首骰按失衡爆发回执决定是否追加 3 失衡；第二骰群体施加 2 电击；第三骰对每个存活敌人分别结算命中、失衡爆发及麻痹。末骰实际命中后先结算 3 穿甲，再摧毁对位实体牌。专测首次在旧牌费用 1 和射程 0 处失败。新牌末骰掷 12 时最终点数为 48，面对 20 普通护盾的目标仍造成 3 生命损失，随后摧毁技能；拦截此次命中，两项均跳过。其他专测覆盖 3 费无法活化、拼点加值门槛与封顶、次要目标拦截、9 费连段和旧状态名兼容。完整词条专测与澜清策略共 158 项通过。

### 战斗界面的八枚状态图标

麻痹、弹药、威压、电击、电流、堆芯熔毁、隧道和星结采用确认的独立 SVG。隧道在左侧菱形内扩大两道切缝，四个尖点沿用原稿。星结采用交扣箭带初稿，两处遮罩保留穿压关系。

对局通过同名文件发现图标，将地址写入快照的 `status_visuals`，战斗界面经静态资源路由读取 SVG。新增专测逐项核对八个状态名对应的文件和媒体类型，接入前八项均报缺，接入后两项图标专测与完整词条专测共 149 项通过。正式文件的图形、变换、配色及星结遮罩均与定稿逐项匹配。

### 澜清的战斗小人和四种活化

澜清沿用安诺琳、李凌的象牙白圆首、五边形棋身与背后淡色光环。侧分的蓝发垂至腰后，双齿电叉的凹槽里露出电弧，肩后悬浮三枚铜枫色方柱，表现「深秋工作室·枫落」的原始形态。「收势·灵器同思」继续活化「深秋·风卷残叶」，该图标沿用方柱。两种电叉活化分别画回旋弧与直刺双齿，「残雪·幽兰流光」用带双尾迹的雪光。

四种公开活化分别通过同名 SVG 接入。浏览器从对局快照取得素材，在 Pixi 中加载了六个骨骼和四枚状态纹理，并核对了角色镜像、突进姿态和约 19 像素的图标。词条、澜清策略和特效模块合跑 165 项，164 项通过。唯一失败的祁铮特效发现断言在更换「枫落」前的版本也可独立复现。

重绘后以同一缩放和落脚线并排核对安诺琳、澜清与李凌，见[战斗形象预览](design-ui/澜清战斗形象.png)。澜清素材发现专测通过，Pixi 已加载新版六层骨骼并验证左右镜像和突进姿态。

电叉工坊X的每枚叉齿由直线段构成。从铜色发射座斜向外，在最宽处形成清晰折角，再斜向内收至尖端。双尖之间留出开口。小人和两种电叉活化图标均以多边形绘制叉齿。

### 全开、载体容器和伤害提升的状态图标

全开和伤害提升按通用状态名显示。全开采用绯红色双臂与中央长芒，伤害提升采用中央镂空加号的朱红爆点。载体容器采用黑色正方体框架，蓝紫色平面折线聚在体心。三枚图标沿用按状态名发现同名 SVG 的路径。

将三个名称加入对局快照专测后，接入前逐项报缺。接入后，三个快照地址都解析到各自的正式 SVG，图形路径、变换、配色与最终设计稿逐项一致。两项图标专测与完整词条专测合计 151 项通过。

### 流阴的状态图标与环境同调层数

领域洞悉、环境压制、战甲和三档环境同调共采用六份定稿 SVG。环境压制用相向的留白挤压流阴的品红光核。同调三档均有三瓣。1 层三瓣均为蓝紫，2 层下瓣露出灰绿切面，3 层右瓣也露出灰绿，光核中央显出静态四芒星。

状态图标清单的 `icons_by_stack` 按实际层数精确匹配。资源加载器把各档 SVG 地址发给前端，状态栏角标与图标使用同一快照值。角色详情与悬浮说明共用选图入口。层数清零时徽章随状态移除，本局图鉴使用清单指定的默认 1 层图。

接入前的挂载专测在 2 层读到了 1 层纹理。接入后，完整词条专测及相关界面和资源回归合计 155 项通过。另在本机 Edge 的实际对局画布中，逐帧核对了 0 → 1 → 2 → 3 → 2 → 0 → 3 的状态栏、详情和悬浮说明纹理，并验证满层时图鉴仍展示 1 层图。

### 澜清的三骰极锐刺与锁级风卷残叶

3 费活化「极锐刺」改为三颗 1～12 突刺，末骰点数乘 3。首骰、末骰各有 1 穿甲，分别在拼赢时触发失衡爆发。第二骰拼赢后，将 +1 记在本次用牌上，交给这张实体牌接下来实际使用的骰子。它若是重复骰，同样取得加值。期间插入的其他技能照常结算。末骰命中时施加 4 电击并摧毁对位技能。

3 费活化「深秋·风卷残叶」采用极限远程，一颗突刺，1～6×10，锁定骰级，命中造成 3 穿甲并毁掉对位技能，使用后回手。沿用现有骰面属性 `fixed_level`。骰级升降与家族永久骰级提升仍对常态牌生效。锁级骰掷出 6、基础值 +1、最终点数 +2 时，实际点数为 72。

第十一张实体牌 `lan_end` 改为 1 费极限远程「终雪」，保留三颗斩击。此次确认的大招全名为「残雪·幽蓝流光」。原活化状态名作为别名，仍归入同一份计数。流阴的回退分类、活化图标与澜清 bot 已同步。bot 按 6 费规划「终雪」接大招，并按新版骰数评估连续命中。

完整词条专测和澜清 bot 专测共 162 项通过。临时解除锁级后，骰级提升与降低两个用例均失败。把增伤固定给印刷第三骰后，第二骰重复的实战用例失败。种子 2、8 下，专用 bot 分别与安诺琳、赫克、流阴交手，六场均完成结算。

「终雪」随后取消极限远程，现按 1 费近战结算。实际对阵近战技能时，它成功活化「残雪·幽蓝流光」；面对成功付费的极限远程技能时，3 级压制使它空白，本次活化为零。旧卡面在后一情形仍获得 1 次活化，专测复现了这个差异。完整词条与澜清 bot 专测共 163 项通过。

### 澜清的 3 费活化「深秋·风卷残叶」锁定全部骰子数值

这颗 1～6×10 突刺的骰级、基础值、变动点数、最终点数和拼点点数均忽略数值修正。骰面用 `fixed_scores` 声明，空白复制品沿用印刷数值性质。每次采样在 `RESOLVE_RAW_ROLL` 处理麻痹的两骰取差，优势与劣势比较各次采样并扣次。澜清 bot 按实际形态判断「涌流灌注」是否能加点。

专测同时施加永久成长、骰级升降、基础值和最终点数修正，以及拼点上下限，掷到 6 仍为 60。麻痹的两组投掷取到 5 和 0，按变动点数下限与优势或劣势分别拼 50、10。伤害另验了 3 穿甲触发致命失衡后变为 6，2 强化护盾吸收后实际掉 4 血。完整词条、澜清 bot 与展示专测共 176 项通过。

### 同一服务进程内的对战大厅

`python -m battle_mcp --lobby` 启动常驻大厅。模式目录与建房共用同一份玩法注册表。常规热座调用热座战桌，常规单人调用通用 bot 房间，挑战从已登记配置取得固定阵容、额外卡包和队伍脚本。界限战斗和砺战合约保留空的玩法表，创建请求返回 HTTP 501。每次建房分配独立的对局、房间地址和凭据。热座的私人邀请可随换手操作双方，人机的邀请只授权玩家 1。关闭一间房会回收其计时器并唤醒该房间的等待者。

通过同一监听端口同时创建了热座、单人、载体挑战和澜清挑战。实际请求核对了换手遮牌、凭据隔离、观战视图、关闭一桌后继续另一桌，以及两种挑战各自开战、终局和再战。以双人固定对手阵容另验了准备和再战时的队伍锁定。大厅、HTTP、地址校验及挑战端到端共 12 项通过，完整词条专测 154 项通过。另有 8 项旧回归在变更前版本 b4d895a 同样失败，其中 7 项引用当前卡包缺失的角色，1 项预期新局首拍为换手而当前先出现结算时点。

### 在游戏主菜单编队与返回战桌

玩家选模式、查看对手或翻阅角色卡时，服务端只返回该玩法的卡包、立绘、印刷技能与固定阵容。主菜单复用游戏画布和战桌的角色图鉴。点击头像后保持该角色的详情，可以滚动阅读被动与牌组。编入和移出有各自的按钮。退回玩法后再进入仍可接着编队。玩家确认开战时才提交双方按出战顺序排列的名单。通过私人邀请进入尚未开战的挑战时，玩家一可以从空阵容开始选择，固定对手继续使用挑战配置。

服务端大厅创建的战桌在游戏视口底部留出返回入口。离桌只返回大厅，继续对局使用该标签页保存的私人邀请，结束对局另行确认。战桌和图鉴的遮罩只占战场高度，换手遮牌时也保留返回入口。

专测区分了只读预览和确认建房，并核对原顺序、重复角色、固定对手、非法阵容以及两个大厅地址提供的画布资源。大厅、挑战与 HTTP 协议专测 11 项通过，完整词条专测 157 项通过。另跑的旧双席对战用例仍在建局时因默认卡包缺少 `ember_wen_sheng` 而中止。8767 的实际服务返回了载体的 15 张技能牌和游戏资源。本次没有操作浏览器，未实测画面的可读性和点击手感。

### Windows 桌面启动大厅

双击项目入口或桌面快捷方式，由通知区域的游戏进程管理本机大厅。同一份项目再次启动时通知原进程打开同一地址。桌面入口在当前浏览器配置中按服务实例保存私人邀请，关闭标签页后可继续对局。结束服务仍会关闭所有房间，托盘退出时先查询房间数，有房间则由玩家确认。

启动专测在 8766 已被占用的条件下验证了备用端口、大厅响应、建房前后的房间数，以及托盘控制管道关闭后服务释放端口。启动、大厅和词条专测合计 169 项通过。Node 专测验证了跨标签页恢复邀请和重新启动后的房间隔离。Windows 托盘冒烟测试拦截浏览器调用，验证了再次启动会通知原实例、菜单退出会回收服务；未手动操作浏览器画面或退出确认框。

### 数据直读展示、忠实原稿与零私造触发器

技能名、费用、骰子类型、骰面范围及固定伤害部分统一直接从结构化数据读取，固定伤害展示格式收口为 `{N}点{等级}伤害`（移除窄/宽双格式混用与旧 `printed_text`/`printed_line` 旁路）。前端触发器高亮仅对 `description` 做纯字符扫描（零正则），将 `【名称】` 替换为着色 `[ 名称 ]`（使用系蓝色、命中系及默认黄绿色、拼点胜利系橙色、拼点失败系红色）；无触发器的常规说明按原文正常显示，不强加触发器前缀。

`displayer.py`、`models/card.py` 与 `terminal_bridge.py` 新增对词条 `"hidden": true` 的过滤，隐藏纯内部记账钩子而不改变运行时执行；多行被动 `description` 按行直接拆分为 `display_lines`。全量清理 `_packs` 中先前私自添加的内部钩子触发器标签，并将流阴的 5 项被动、4 项状态说明与 12 张技能逐字恢复至作者原稿（仅保留真实卡牌/回合触发器，疑似错别字与简略表述留待作者批准）。核对 11 份 `_packs` JSON 除 `description`/`hidden` 外与基线 `46070cf` 完全机械等价。

`tests/test_displayer.py`、`tests/test_liu_yin.py` 与 `tests/frontend/test_data_driven_display.mjs` 均改为结构不变量与对比路径断言，不硬编码触发器白名单或复制原文。Python 专测（含 `tests.entry_semantics`、展示、流阴、澜清、赫里斯、载体、执行路径等）309 项通过，Node 前端专测 15 项通过。未操作浏览器。

### 精简伤害展示格式与流阴原稿核准修订

按作者裁定统一结构化伤害展示规则：普通伤害仅显示裸数字（如 `1`）且始终排在第一位；非普通伤害显示 `{量} {等级}`（如 `1 真实`、`2 穿甲`、`3 超穿甲`、`1 光点`）；群伤加 `群体` 前缀（如 `群体 1`、`群体 1 穿甲`、`群体 3 光点`）；表达式伤害直接写表达式（如 `(能源值-1) 光点`）。`displayer.py` 与 `battle_ui/static/engine/design_system.js` 共用同一格式与稳定排序（普通单伤 → 普通群伤 → 其余等级），支持词条上的结构化 `damage_part` 声明，并在窄卡内自动换行防溢出。

按核准清单修订流阴 3 处原文：「画地为牢」`变得点数` → `变动点数`、「战甲塑造」常规第一骰 `领域压制` → `环境压制`、「肃清引信」强化第二骰补全为 `目标生命上限1/3（向上取整） 超穿甲`；「领域覆写」保留原句，个人设定不作改动。同期将流阴、澜清、安诺琳的群体/动态伤害词条接入结构化 `damage_part`，并回退此前加冗的 `点普通伤害` / `点超穿甲伤害` 文案。核对全部 11 份 `_packs` JSON 除展示字段外与 `46070cf` 完全机械等价；Python 专测 310 项、Node 前端专测 15 项全部通过。未操作浏览器。

### 同级话语权下的保护裁定

正式规则书 §8.5：动作遇到已生效的保护，双方同为常规或同为较高时，保护挡下动作。敌我双方同为最高时，由本回合先手方胜出。以「信子科学的结晶」的防摧毁词条为例，只有摧毁与保护都为最高，交换先后手才会改变同级冲突的结果。

公共取消入口比较本次动作与保护词条的话语权。预约兑现和护盾防卫执行时携带各自的来源，按兑现时的先手裁定。牌面调用参数不能改写话语权或其归属。

专测覆盖三个摧毁等级、三个保护等级及双方轮流先手的 18 种组合，逐一核对目标实体是否被摧毁及摧毁记录次数。改动前仅“双最高、摧毁方先手”一格失败。另验证预约扣层与护盾吸收的双方归属。完整词条专测 242 项通过。

### 流阴与澜清的五个 SP 形态

选角目录增加流阴（秒开）、流阴（？？？）、流阴（真正的执政）、澜清（不演了）和澜清（？？？？）。卡包按原版展开 SP 牌组，变体各自声明血量、基础交锋和被动，使用时持有独立的实体牌、状态和计数。原版与 SP 的「幽蓝残雪」统一正名，流阴的环境压制移除层数上限。

流阴在战斗开始获得的 15 或 30 洞悉，分别预约首回合开牌前的一次或三次免费「领域覆写」。三个 SP 的压制扣层先翻倍，「天性解放」以翻倍后的数量转为能源。「？？？」首回合的 9 层扣除实际扣 18；三次覆写后从 24 洞悉在回合末补回 30。「真正的执政」在首次实际获得压制后登记，可从 30 压制经「逆流溯源」达到 36。其覆写奖励在自身使用后逐次结算。

澜清每次即将拼负时查询当前生命与本回合已触发次数，第三次可在回合中降到 6 或 12 生命时开放。首次触发后的 +2 只对后续用骰生效，重复触发时保持 +2。失衡爆发读取成功回执，对该受者额外施加一层致命失衡。每段直伤在 `RESOLVE_DAMAGE_BASE` 确定基础数值、穿甲等级及百分比标记。命中骰与伤害来源骰一致、最终点数至少 12 时，澜清（？？？？）以每名受者当前生命上限计算原伤害数值 × 10%，向上取整，随后结算致命失衡及护盾。

新增 11 项 SP 专测，经选角、开牌前交锋和常规用骰核对。原伤害 2 打生命上限 30 的目标，最终点数 11 为普通 2，涌流灌注将最终点数推到 12 后为超穿甲 6。群伤对上限 17 与 30 的两名目标分别打 4 与 6。完整词条专测 253 项通过，大厅、展示与澜清 bot 回归另 34 项通过。旧战斗与伤害结果两组共 37 项，9 项通过，28 项失败；与改动前 `2049c58` 逐项比对，失败用例及异常末行一致。

### 真正的执政·流阴的出战位阶

设计者确认流阴（真正的执政）为极端战力，30 生命，沿用原版技能。载入器分别验证角色位阶与继承牌组的印刷位阶。部署后为 30/30 生命、44/44 完整度、5 基础交锋，11 张常规技能与战斗外「领域覆写」。同场原版流阴仍为强化首领、18/18 生命、28/28 完整度。SP 专测 12 项通过。提交 7e33a08 的独立快照运行完整词条专测 254 项通过。

### 光生会“目击残差”与极端战力挑战

“目击残差”的引号属于代号。光生会第三席以 30 生命、44 完整度、8 通用费加 1 个人费、5 基础交锋和 15 张常规技能入场。抽牌时先确定己方保留 4 张，再按存活人数直接抽或选牌置底。两位极端战力 SP 均以 30 生命、44 完整度入场，各自继承 11 张常规技能。

「一体两伤」取每段直伤入盾前的伤害量，对同一存活目标追加两倍光点伤害。3 点物理全被盾吸收时仍追加 6 点。28/30 生命受 5 点治疗，实回 2，只回复 2 完整度，且受当前完整度上限约束。「展形」累计实际能源支出，过两档分两次治疗，供能达到每回合 7 后仍可治疗。

「余形」在技能用完时登记最后实际掷过的原印骰。展用复制原印骰面和骰上词条，保留已被选择的其他骰子对象。「倾身」末骰当次打 5，「全形」展用两次各打 3。「断节」只读当前对阵牌的下一颗可用骰，一级远程优势允许查询并保护受者免于摧毁。「并行」展用防御骰时只加强自己的两颗原印斩击骰。

功能提交 7bd8a12 的独立快照通过 272 项完整词条专测，其中“目击残差”17 项、SP 13 项。另通过 12 项大厅与挑战接口回归，实测两场双 SP 编队及两场单 SP 对局均正常结算。正式 8766 大厅已返回带引号的挑战名、固定对手和立绘。通过大厅新建双 SP 挑战房核实三名角色均以 30/44 入场，验证后关闭该自测房。

### 形态灭杀的连续崩塌与铭刻视界的折影额度

流阴的「形态灭杀」在本骰每次引发崩塌时取目标崩塌前的普通生命和当时生命上限。崩塌的真伤、复活、完整度恢复后，按卡面另减 4 完整度上限，并按快照决定三次即死。耗能和光点伤害按一次命中结算。逐条扣除同段余伤时重新取快照，普通光点伤害默认在该条结束。专测用 18/18 生命、1/28 完整度承受 21 光点，实际记录两次 9 真伤、一次真伤阵亡判定、三次即死。三次满血复活死于末次即死，四次复活存活。所有流阴 SP、奇数上限、跨条余伤归属、完整度归零及战桌事件顺序均已核对。功能提交 a01f074。

林羽直接获得折影化铭刻时立即按实际增加的层数发放本回合额度。「羽流·终」转化已有铭刻时只改变其中的额度归属。所有判定和支付共用含额度的铭刻总数，实际扣层先减额度。1 普通铭刻和 3 剩余额度可选择「闪回识破」，成功迎击实付 4、占一次，放弃保留全部资源及次数。额度耗尽后保留折影化铭刻本体，回合结束清理剩余额度，下回合刷新。专测另核对了总数 12/13 的选择分界、次数用尽、8 层上限及战桌的普通铭刻和剩余额度明细。功能提交 c837856。

上述两项提交的独立快照通过 280 项完整词条专测和光点战桌桥接专测。当前工作区完整词条专测通过 284 项。单独运行旧模块 tests.test_lightcore 时，改动前后均有 11 项在准备阶段因缺少 blank_boss 卡包而停止。按用户决定保留当前对局，本次暂缓重启 8766 大厅。

### 限制的最低费例外与受限手牌（2026-11-27）

设计者确认，限制层数不低于全队手牌数时，可任选一张最低费牌，包括并列最低费。状态定义用同一个比较条件驱动持牌者预览与实际使用。例如 1、1、3 费三张手牌，2 层只开放靠后的 1 费牌，3 层和 4 层均开放两张 1 费牌。仅有一张牌并受 1 层限制时，扣置保留该层，实际用完技能才扣 1 层。规则与专测提交 150e1e4。

战桌手牌按持牌席位取得的实体标记显示「受限 · 当前无法使用」。玩家仍可主动扣置。通用人机和挑战策略逐次排除当前受限的出牌与迎击，弃牌仍可选择受限牌。专测覆盖同名同费实例在同一手牌中的不同顺位、其中一张离手后行动编号的变化，以及最低费例外对默认与挑战策略的影响。功能提交 c68130d。

完整词条专测、澜清 bot 和基础效果包回归合计 301 项通过。额外运行旧大厅与人机适配测试时，有 4 项缺少旧测试角色，1 项预期交接而实际为时点。使用修复前的适配器和相同卡包复测，五项结果一致。已按用户授权重启正式 8766 大厅，在正式房读取到最新「不低于」词条。流阴（真正的执政）与“目击残差”以 30 生命、44 完整度出战并进入交锋，验证房已关闭。

实测“目击残差”持有 24 层裂伤与 3 点存伤后增加到 25 层，结算记录依次为裂伤爆发的 3 穿甲、它自己对自己追加的 6 光点。状态自行爆发归持有者，「一体两伤」识别直伤来源并向同一存活目标追伤。相同的裂伤在林羽身上只扣普通生命。

### “目击残差”的单枚余形与目标侧结算前追伤（2026-11-27）

功能提交 `8c071ed`。设计者确认余形保留一枚，跨回合公开，扩大可展用的技能范围，并让展用骰随累计实耗能源成长。15 张牌有 11 张可选展用。纳流、蜕形各付 1 能源展用 1 次；收束、潜相、透界、探隙、断节各付 1 展用 2 次；贯核付 1 展用 1 次；折返付 2、并行付 3，均展用 3 次；全形付 4 展用 4 次。以累计实耗每满 6 获得的供能加成为档位，最高 4 档。每枚展用骰最终点数增加 8＋6×档位，展用攻骰成功命中目标额外造成独立的 2＋3×档位物理伤害。

每张牌给出费用与次数，余形词条提交可选支付，按足额支付回执向本技能前端插入新骰。原印骰面带着原生词条复制，逐枚获得本次展用的附加词条。先结算支付带来的升档，再用骰。取最后实际掷出的原印骰更新；无原印骰掷出则保留来源回合。「潜相」可还原上一份余形及来源回合。双方和公共快照投影完整骰面，角色 HUD 标明来源，详情页与确认展用时可读原印词条。挑战 bot 按牌面展开次数估算顺序，同时比较立即支付与为后续技能留能。

「一体两伤」在成功的直伤段结束、目标仍存活时读取 `outgoing_amount`，独立追加两倍光点伤害。实测 1 物理被环境压制减至 0 仍追 2，3 物理被致命失衡翻倍至 6 仍追 6。来源自身的倾身加伤与崩析减伤均进入原始量。取消、致死、全盾、群攻与回满时的实回已分别核对。

完整词条专测、快照、澜清 bot 与基础效果包共 318 项通过。两个改动的战桌 JavaScript 模块通过语法检查。本机挑战接口使用种子 3、4 分别跑至第 3、2 回合终局，换回合后的玩家帧仍读到旧余形。第一组比较采用种子 16～31，每个对手换席各打 16 局，使用各自的挑战策略。目击残差对极端澜清 29 胜 3 负，对挑战版结构化载体 23 胜 9 负；64 局均实际展用，47 局在前两回合结束，最高实战供能为 5。供能 7 的上限由定向专测核对。按用户选择，保留 8766 大厅现有对局，暂缓重启。

数值定稿后复测种子 32～47，同样按两个席位各打 16 局。目击残差对极端澜清 26 胜 6 负，对结构化载体 24 胜 8 负。两组共 128 局，分别为 55/64 胜和 47/64 胜。所有对局都实际展用，95 局在前两回合结束，最高实战供能为 6。

### “目击残差”的展用试打版进入正式卡包（2026-11-27）

功能提交 `b23a856`。11 张可展用牌中，8 张支付 1 能源各展用一次。「折返」付 2 展用两次，「并行」付 3 展用三次，「全形」付 4 展用三次。卡面说明与确认支付时显示的能源、次数已逐张核对。

足额支付并结算供能升档后，复制骰取得最终点数加成 8＋6×供能档位。展用攻骰成功命中时，词条读取此次使用技能的 `$event.card.data.cost`。印刷费用至少为 2 时，结算独立的 2＋3×供能档位物理伤害，由「一体两伤」依来源侧原始伤害量再追两倍光点。此前已实耗 5 能源时，「收束」和「透界」分别支付 1 能源展用「贯核」，复制骰都获得 +14 最终点数。前者命中造成 7 光点，后者的同一枚复制骰在无其他修正时依次造成 7 光点、5 物理、10 光点。

角色专测 23 项通过。完整词条专测连同快照、澜清 bot、基础效果包共 320 项通过。通过挑战模式的阵容选择与建房入口，在进程内以真正的执政·流阴对战“目击残差”两局（种子 16、17），均打至第二回合终局，玩家帧均可读取上一回合留存的余形与来源回合。另用正式卡包复测种子 16～31，双方换席各 16 局。通用 bot 操作流阴 0 胜 32 负，其中 7 局在首回合结束，19 局在第二回合结束，6 局进入第三回合。

## 四档话语权与对立效果裁决（2026-11-27）

实现提交 `f8b99b7`。较低、常规、较高、最高依次比较。对同一个动作，先确认适用的保护与双方归属；同级盾优先，双方均最高时敌我按本回合先手。未遇到保护的动作直接执行。取消护盾抵消时，正在抵消的规则是盾；原始伤害段没有话语权。回复致死使用规则指定的最高话语权；对方同为最高的免死由先手裁决，致死一方取回复的实际来源。

技能远程等级先受对方的降级，再抵消、扣除能无视的等级并施加压制。降级、保护远程等级和无视远程分别裁决。三级压制、封印成空白与明确无效化经过同一个 `NEGATE_SKILL` 窗口。牌与骰保留作用于本次使用的无效化来源，查询词条有效性不执行程序、不占用次数。流阴「领域覆写」用同一条防无效化保护覆盖远程。羽流剑反原形态三颗骰对三级压制均为空白，仍以小点取得拼赢、跳过拼赢分支且命中零次。片羽穿空受三级压制后挡下常规摧毁，较高摧毁成功。明确摧毁仍会终止对象的后续响应。

改动前词条专测 290 项通过；改后 `python3.12 -m unittest tests.entry_semantics` 共 300 项通过。摧毁与保护覆盖四档的全部 16 种组合和两种先手。其他专测分别核对本次词条执行被拦前的次数、明确置空后监听的实际触发、强弱无效化连续作用与重新抽牌、护盾消耗和实际失血、双最高回复致死、降级与防降级的有无及无视远程的等级边界。独立运行全量发现测试，比对改动前 `222ea16` 的 876 项与改后的 886 项，均为 35 项断言失败、321 项错误，未通过用例名称完全相同。

## 帝国第一序列兵（2026-11-27）

实现提交 `9ef417d`。在战桌的普通选人入口核对了 18 生命、强化 Boss、4 个基础常规交锋和 11 张技能。威压沿用结构化载体的 12 层定义，移入共享状态包供两者使用。

「阴黑无明」比较已经确定的双方拼点点数。仅重投玩家选中的己方骰，沿用本次拼点，重新计算该骰的最终点数、拼点点数与双方结果。己方原掷 1、0 层崩解使最终点数 +3，对方为 9 时可先重投到 2，再重投到 10，以 13 对 9 拼赢。拒绝保留次数，重投后仍严格低于对方可再选，同点停止，每回合最多三次。拼点逆转仍比较数值是否较低。重投同一枚骰保留对手结果和剩余的优势次数。

崩解以 0 层入场，清除层数后仍持有状态。生命归零可获本回合最高话语权免死。回合末先按自愈前层数判断复活，0 层无法复活，1 层以 1 生命复活。5 层在自愈前发动即死，仅对该动作略过「毁灭生死」。每次复活将当前生命上限向下减半，18 依次降至 9、4、2、1、0，上限归零时阵亡。

「绝望」印刷费用为 2，本回合在敌方每张技能开始时检查对位。原有对位随后耗尽，余骰继续使用。毁灭模式在进入后的回合开始增加 1 崩解，模式内暂停自愈。定值直伤 3 对 17 上限转为 6 点超穿甲，原有 20% 对同一目标为 4 点。百分比段按最高话语权抵抗减伤，仍结算增伤与概念护盾。开牌前「破碎」沿用场上实体牌选择，隐藏牌以交锋位置呈现。「贯彻他的意志」的驻留和永久骰级分别复用追加命中与持续预约。

角色专测 15 项通过，覆盖全部 11 张牌的实际结算、重投取舍、费用与崩解各档、百分比段和减伤话语权、无对位与余骰、回合末复活及模式切换。改动卡包副本中的费用、生命门槛和伤害分母后，执行结果随实参改变。完整词条专测 `python -m unittest tests.entry_semantics` 共 315 项通过。

## 光暗使 安吉尔（2026-11-27）

实现提交 `35615d4`。普通战桌选人可用，15 生命，初始完整度 24，强化 Boss，基础 4 交锋。九张实体技能中，七张常规牌起始参与抽牌，两张决战技起始在战斗外。角色包单独加载也可使用共享的置卡或换卡机会。

光涌与暗涌在全场分别共用硬上限。初始各 3 层，缺额归安吉尔。向已满的全场直接新增会被拦截。转移以目标实际接收的层数为准，转移过程保留总量。光破先比较目标身上的暗涌与光涌，再向目标转光涌。目标有 3 暗、1 光时，印刷 3 光破并成功转入 1 光涌，扣 5 完整度；无法转入则扣 1 物理。暗蚀交换属性。灰界在每次开牌时保留，每满 4 层提升两种涌的共同上限 1，至多 8。共同上限 7、灰界 8 时升至 8，回复 1 生命。暗笼封存的暗涌仍占名额，暗笼耗尽时全部返还。暗笼拦截发生在其他即将命中的被动之前，空效果进攻骰也消耗一层。

黑白共舞在每回合开始、抽牌及速度判定前按 6 灰界重新判断。首次入场将决战技直接入手。6 灰界入场时费用上限 7、交锋数 5；回合末灰界降到 4，下回合退出。与光竞速将常驻一层与每 2 速度差的加层叠加，合计封顶 3。与暗争变由实际控制者在拼点和单方面攻击中选择，普通回合 2 次、共舞 3 次，同骰每次重投另加 1 最终点数。

灰界覆盖使用时选定整张技能的吸收与转移属性。取暗弃光末骰为 2 光破。耀光周身依序将闪避改为 1～20 斩击，移除原倍率，激活相应伤害。暗影凝集的下回合费用及置卡机会独立于吸收。光影乱流对三级远程攻击拼点时最终点数加 3，对骰本次取劣势；遇已有优势次数，消耗一次优势并只掷一次；已有劣势次数保留。冬韵共舞可有七次命中，末骰按四枚实际命中的骰子消耗灰界。烁光幻灭末骰使用时比较光涌，达到 6 层取得最高话语权，随后转出光涌仍按该次资格结算。

光点解构按每名敌人当前形态群的完整度实损累计。生命上限 15、完整度 24 的目标一次失去全部完整度，崩塌前依次承受三段各 1.5 超穿甲；下一条上限 20，实损 5 又触发一段。「光点碎裂」按裁定只在共享状态包保存定义，暂未挂载触发和计数。

复用状态收支、玩家选择、卡牌形态、反击池与跨回合预约。新增的状态转移简写展开为既有状态指令。公共结算补足了单方面攻击出分后的重投、命中前拦截、每条完整度实损回报及显式小数直伤，并让角色声明自身无视远程和特殊常规牌数。26 项安吉尔专测及完整词条专测 341 项均通过，另经普通战桌和独立卡包加载验证。
