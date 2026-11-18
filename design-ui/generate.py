from ui_primitives import *
import json

DATA=json.loads((OUT/'sample_pack.snapshot.json').read_text(encoding='utf-8'))
SKILLS=[dict(skill,owner=character['name']) for character in DATA['characters'] for skill in character['skills']]
KINDS={'slash':'斩击','pierce':'突刺','blunt':'打击','block':'招架','evade':'闪避','guard':'类型待核对'}
SIZES=[0,4,6,8,12,16,20]

def anchor(name): emit(f'<g id="{name}">')
def close(): emit('</g>')
def scroll(x,y,w,h,offset=0.0,fraction=.4):
    box(x,y,w,h,'bg','bg')
    if w>h: box(x+w*offset,y,w*fraction,h,'green','green')
    else: box(x,y+h*offset,w,h*fraction,'green','green')
def tick(x,y,label,on=False,disabled=False):
    box(x,y,22,22,'green' if on else 'white','line')
    if on: text(x+3,y+17,'✓',18,'white',700)
    text(x+34,y+18,label,16,'muted' if disabled else 'ink')
def header(phase):
    text(386,39,phase,18,'ink',600); button(940,10,'记录',90); button(1042,10,'菜单',114)
def player(x,y,name,hp,used,personal,enemy=False):
    accent='red' if enemy else 'green'
    box(x,y,246,187,'white','line',8); text(x+16,y+32,name,23,accent,700)
    text(x+16,y+65,f'生命 {hp}',20); box(x+16,y+82,214,5,accent,accent)
    text(x+16,y+115,f'交锋 {used} / 2    个人费 {personal} / 1',15)
    text(x+16,y+145,'普通盾 0 · 强化盾 0 · 概念盾 0',13,'muted')
    text(x+16,y+173,'查看角色与技能  ↗',14,accent)
def smallcard(x,y,skill,selected=False):
    box(x,y,276,116,'pale' if selected else 'white','green' if selected else 'line',8)
    text(x+14,y+29,skill['name'],21,'ink',700); text(x+216,y+29,f'{skill["cost"]} 费',15,'green')
    text(x+14,y+56,skill['owner'],13,'muted')
    for i,die in enumerate(skill['dice']):
        text(x+14,y+81+i*21,f'{KINDS[die["type"]]}  1～{SIZES[die["level"]]} + {die["base_value"]}',14)
def board(placed=False,revealed=False,empty=False,phase='置卡 · 玩家一操作',paused=False):
    header('第 1 回合 / '+phase)
    player(24,92,'铁壁先锋','15 / 15',1 if placed else 0,0 if placed else 1)
    player(910,92,'绯红决斗者','12 / 12',1,0,True)
    text(24,322,'全局费用 5 / 5',24,'green',700); button(24,352,'牌区 · 抽牌堆 3',246)
    text(910,322,'默认：绯红决斗者',20,'red',700); button(910,352,'更改默认目标',246)
    badge(296,92,'已填 1 / 2' if placed else '本次已填 0 / 2',w=220)
    for i in range(3):
        cx=296+i*198
        text(cx,154,f'交锋 0{i+1}',16,'muted',700)
        box(cx,172,180,118,'rose' if i==0 else 'paper','line',8)
        if i==0:
            if revealed: text(cx+14,215,'弧影穿刺',21,'red',700); text(cx+14,252,'突刺 → 闪避',15)
            else: crest(cx+64,191,54,'red'); text(cx+37,274,'对方已扣置',14,'red')
        else: text(cx+36,233,'对方未置卡',15,'muted')
        box(cx,318,180,126,'pale' if i==0 else 'paper','line',8)
        if i==0 and placed: text(cx+14,358,'全线守备',21,'green',700); text(cx+14,395,'招架 → 招架',15); text(cx+14,424,'已开牌' if revealed else '己方扣置',14,'muted')
        else: text(cx+14,369,'首个空位' if i==0 else '等待顺序置入',16); text(cx+14,410,'从手牌选择' if i==0 else '不可跳过空位',14,'muted')
    scroll(296,469,576,5,fraction=.65)
    text(24,449,'我方速度 2 · 对方速度 4',16,'muted'); button(910,424,'结束置卡',246)
    text(24,533,'手牌 0' if empty else '手牌 1' if placed else '手牌 2',20,'ink',700)
    if empty:
        text(24,585,'没有可用手牌，本方已结束置卡。',22,'muted'); badge(24,622,'等待对方完成',w=246)
    else:
        smallcard(24,553,SKILLS[4])
        if not placed: smallcard(320,553,SKILLS[3])
    if paused: badge(700,495,'已暂停 · 结果已保留',w=400)
def dim(): emit('<rect x="0" y="64" width="1180" height="636" fill="#243D39" opacity=".32"/>')
def modal(title,x=290,y=125,w=600,h=520):
    dim(); box(x,y,w,h,'white','line',8); text(x+28,y+45,title,26,'ink',700); button(x+w-118,y+15,'关闭',90); line(x+28,y+68,x+w-28,y+68)
def skillbody(skill,x,y,w=520,h=242):
    box(x,y,w,h,'white','line',8); text(x+18,y+32,skill['name'],24,'ink',700); text(x+w-80,y+32,f'{skill["cost"]} 费',18,'green',700)
    text(x+18,y+59,skill['owner']+(' · 战斗外' if skill.get('out_of_combat') else ' · 普通技能'),14,'muted')
    text(x+18,y+84,'技能效果：无额外词条',14,'muted')
    for i,die in enumerate(skill['dice']):
        dy=y+101+i*62; label=KINDS[die['type']]
        if die['type']!='guard': icon(x+16,dy,label)
        else: text(x+18,dy+21,'?',24,'red',700)
        text(x+54,dy+19,f'{label}  1～{SIZES[die["level"]]} + {die["base_value"]}',19)
        effect='命中：2 普通伤害' if die['entries']==['2'] else '无伤害部分 · 无额外词条'
        text(x+54,dy+44,effect,14,'red' if die['entries'] else 'muted')
    text(x+18,y+h-13,'类型待核对，暂不可用于对局' if any(d['type']=='guard' for d in skill['dice']) else '骰子按从上到下的顺序使用',13,'red' if any(d['type']=='guard' for d in skill['dice']) else 'muted')
def start(index,title,sub): frame(index-1,title,sub)

emit('<svg xmlns="http://www.w3.org/2000/svg" width="3756" height="8760" viewBox="0 0 3756 8760"><title>PL-III-PC 全界面与交互状态 · 修订稿</title><desc>30 个分区；具体技能、浮层上下文、状态变化与返回关系在同一静态画布展示。标注区分现有行为、前端提案与待定规则。</desc><style>text{font-family:"Microsoft YaHei",sans-serif}</style>')
box(0,0,3756,8760,'bg','bg'); text(48,60,'光点计划 III · 界面与交互状态',38,'ink',700)
text(48,100,'现有：已在源码出现的操作或数据   /   提案：新增前端呈现与防错   /   待定：需要统一的规则或数据',18,'muted')
text(2490,62,'这里没有的，代码里存在，就是非法。',22,'green',600)

start(1,'开始界面与启动状态','提案｜先进入选择角色；加载、失败、无资料均有独立可见结果')
anchor('lobby-ready'); crest(190,112,174); text(72,344,'光点计划 III',43,'ink',700); text(72,393,'双人对战',22,'muted'); button(72,443,'开始对局',430,'primary'); button(72,505,'规则说明',206); button(296,505,'设置',206); close()
for y,title,detail,label in [(100,'正在读取角色资料','保持当前界面，暂时无法开始。','读取中…'),(300,'角色资料读取失败','未能读取卡包，请检查后重试。','重新读取'),(500,'尚无可选角色','至少需要两名角色供双方选择。','重新读取')]:
    box(590,y,566,174,'white','line',8); text(616,y+40,title,23,'ink',700); text(616,y+80,detail,16,'muted'); button(616,y+108,label,250,'disabled' if y==100 else 'normal')
end('开始 → 02；规则 → 19，设置 → 20（返回文字为“返回开始”）；重试 → 读取中 → 成功回到左侧 / 失败保留错误。')

start(2,'玩家一选人 · 未选、选中与取消','现有：共享角色池、至少 1 人、最多 5 人；提案：为玩家二保留一名可选角色')
text(24,110,'玩家一 · 选择出战角色',26,'ink',700)
for i,char in enumerate(DATA['characters']):
    x=24+i*576; box(x,150,552,228,'white','line',8); crest(x+24,176,84,'green' if i==0 else 'red'); text(x+132,199,char['name'],27,'ink',700)
    text(x+132,239,f'精英 · 生命 {char["max_hp"]} · 交锋 2',18); text(x+132,273,'铁契军团 · 5 张普通技能',16,'muted'); button(x+24,311,'查看角色',220); button(x+266,311,'选择',260)
anchor('selection-empty'); box(24,415,552,261,'white','line',8); text(48,458,'已选 0 / 5',23,'ink',700); text(48,504,'至少选择 1 名角色。',18,'muted'); button(48,602,'确认阵容',504,'disabled'); close()
anchor('selection-selected'); box(600,415,556,261,'pale','line',8); text(624,458,'已选 1 / 5',23,'green',700); badge(624,487,'铁壁先锋',w=250); button(894,478,'移除',230); text(624,558,'绯红决斗者保留给玩家二。',17,'muted'); button(624,602,'确认并交给玩家二',500,'primary'); close()
end('查看角色 → 15；选择 → 右侧已选；移除 → 左侧未选；确认 → 03。选择被保留角色时提示“需为玩家二保留角色”。')

start(3,'玩家二选人与双方阵容确认','现有：已选角色离开共享池；提案：锁定后禁止返回修改，避免破坏共享池')
text(24,111,'玩家二 · 选择出战角色',26,'ink',700)
box(24,152,550,241,'bg','line',8); crest(48,183,84); text(160,204,'铁壁先锋',27,'muted',700); text(160,246,'已由玩家一选择',19,'muted'); button(48,325,'不可选择',502,'disabled')
box(606,152,550,241,'pale','green',8); crest(630,183,84,'red'); text(742,204,'绯红决斗者',27,'red',700); text(742,246,'生命 12 · 精英 · 交锋 2',18); button(630,325,'已选 · 点击取消',502,'selected')
box(24,425,1132,251,'white','line',8); text(48,466,'双方阵容',24,'ink',700); text(48,511,'玩家一   铁壁先锋',21,'green',700); text(610,511,'玩家二   绯红决斗者',21,'red',700)
text(48,555,'各有 5 张普通技能入牌堆；尖刺必杀留在玩家二的战斗外区域。',17,'muted'); button(48,603,'查看角色资料',260); button(854,603,'确认并开始',278,'primary')
end('取消选择 → 确认按钮禁用；查看资料 → 15；确认 → 04。角色池不足时使用 22 的明确错误反馈。')

start(4,'速度与单角色抽牌 · 四个相邻状态','现有：双方 d4，打平重投；单角色直接抽 2 张。提案：过程可见，结果一次确认')
for i,(title,score,note,label,kind) in enumerate([('确定速度','… : …','正在投掷双方速度骰。','投掷中…','disabled'),('速度相同','3 : 3','本次打平，自动重新投掷。','重新投掷中…','disabled'),('速度确定','2 : 4','玩家二先手，首次置入 1 张。','继续抽牌','primary'),('已抽取 2 张','全线守备 / 铁誓反击','手牌 0 → 2；抽牌堆 5 → 3。','进入置卡','primary')]):
    x=24+(i%2)*582; y=100+(i//2)*294; box(x,y,550,270,'white','line',8); text(x+24,y+42,title,24,'ink',700); text(x+24,y+102,score,30 if i<3 else 22,'green',700); text(x+24,y+151,note,17,'muted'); button(x+24,y+204,label,500,kind)
end('正常：投掷 → 确定 → 抽牌 → 06；平局循环至确定。多人抽牌分支 → 05；抽牌堆不足/为空 → 17。')

start(5,'多人抽牌 · 选择前、选中、确认后','现有分支｜扩展角色池后的双角色示例；不保留卡在当前代码中进入原牌堆底')
text(24,111,'选择 1 张不保留的牌',27,'ink',700); text(24,144,'保留 2 张进入手牌。点击卡牌选择；再次点击取消。',17,'muted')
for i,k in enumerate([0,3,9]):
    x=24+i*380; skillbody(SKILLS[k],x,174,356,258); tick(x+16,448,'不保留这张牌',i==2)
anchor('draw-unselected'); box(24,500,550,175,'white','line',8); text(48,543,'已选 0 / 1',22); text(48,580,'还需选择 1 张。',17,'muted'); button(310,608,'确认保留',240,'disabled'); close()
anchor('draw-selected'); box(606,500,550,175,'pale','line',8); text(630,543,'已选 1 / 1 · 决意贯穿',22,'green',700); text(630,580,'确认后手牌：试探刺击、全线守备。',17); button(886,608,'确认保留',246,'primary'); close()
end('选满后另点一张则替换选择，不允许超选；取消回到 0/1；确认 → 06 对应两张手牌；详情从卡片名称进入 25～27。')

start(6,'置卡桌面 · 主界面','现有数据与动作；提案：费用展示/支付校验。当前示例敌方先手已扣置 1 张')
anchor('board-main'); board(); close()
end('手牌 → 07；结束 → 09；角色 → 15；牌区 → 16；目标 → 13；记录/菜单 → 18。首个空位与手牌选择联动。')

start(7,'选择手牌 · 详情浮层与支付预览','浮层保持真实战场上下文；取消不消耗资源，确认才扣置。费用支付为提案')
board(); modal('全线守备',282,90,616,600)
skillbody(SKILLS[3],310,178,560,270)
text(310,487,'支付：个人 1 + 全局 0 = 1 费',22,'green',700); text(310,523,'交锋占用 0 / 2 → 1 / 2',17)
button(310,555,'取消选择',166); button(492,555,'扣置并结束',178); button(686,555,'确认扣置',184,'primary')
text(310,650,'全局费用仍为 5；全线守备离开手牌。',16,'muted')
end('取消/关闭 → 06 原样；确认 → 08；扣置并结束 → 09 已结束态。详情可进入角色页，关闭子层返回本层。')

start(8,'确认扣置后 · 跨区域同步更新','牌从手牌进入首个空位，个人费与交锋占用更新，反馈出现在交锋附近')
board(True); badge(296,488,'已扣置全线守备 · 还可填 1 个半交锋',w=576)
end('继续选牌 → 07 携带新技能数据；填满本次名额 → 10 交接；结束 → 09。无自由撤回，避免引入未定义规则。')

start(9,'结束置卡 · 确认、取消与空手牌','上方为遮罩内确认；下方为原位置的结束后局部状态')
board(True); modal('结束本回合置卡？',300,130,580,300)
lines(330,234,['你还有 1 张手牌。','结束后本回合不能再次获得置卡权。'],18)
button(330,346,'继续置卡',240); button(590,346,'确认结束',260,'primary')
box(24,480,550,205,'white','line',8); text(48,524,'玩家一已结束置卡',24,'ink',700); text(48,563,'手牌 1 · 本回合不可再放入交锋',17,'muted'); button(48,610,'等待玩家二',500,'disabled')
box(606,480,550,205,'white','line',8); text(630,524,'手牌 0 · 自动结束',24,'ink',700); text(630,563,'没有可用手牌，已交出置卡权。',17,'muted'); button(630,610,'等待玩家二',500,'disabled')
end('继续/关闭 → 08；确认/空手牌 → 10；双方均结束 → 11。等待期间仅允许查看公开角色、牌区和记录。')

start(10,'交接遮屏 · 双方视角隔离','提案｜遮屏取代整个战场，不能从背景看到私人手牌；没有越过交接的关闭按钮')
box(0,64,1180,636,'ink','ink'); crest(490,128,200,'paper'); text(370,386,'请将设备交给玩家二',34,'white',700)
text(366,440,'玩家一的手牌与扣置详情已隐藏。',21,'paper'); button(360,510,'我是玩家二 · 继续',460)
text(360,598,'轮到玩家一时，对应显示玩家一。',16,'paper')
end('确认 → 06 镜像玩家二视角；单方已结束时，仅另一方继续。选人交接同组件，目标状态为 03，不暴露已选详情。')

start(11,'统一开牌 · 当前交锋与结算中','双方扣置牌一次性翻开；保留每方当前卡与后续骰子的位置')
board(True,True,phase='开牌 · 交锋 01')
box(24,514,1132,172,'white','line',8); text(48,555,'交锋 01 · 第 1 骰',25,'ink',700); text(48,599,'全线守备  招架 1～8 + 2    ↔    弧影穿刺  突刺 1～6 + 2',19)
button(48,625,'正在结算…',260,'disabled'); button(866,625,'暂停展示',260)
end('结算完成 → 12；暂停 → 保留当前画面及结果，按钮改“继续展示”，见 30；每次仅推进一次，不重复投掷。')

start(12,'逐骰结果 · 胜、负、平与无对手','结果区的四种具体表现；在 11 中替换底部结果区域，外框和当前技能不消失')
for i,(title,left,right,result,note,nextlabel) in enumerate([
 ('拼点胜利','5 + 2 = 7','3 + 2 = 5','招架胜利','无伤害部分，双方生命不变。','下一枚骰子'),
 ('拼点失败','1 + 2 = 3','5 + 2 = 7','突刺胜利','弧影穿刺没有伤害部分，生命不变。','下一枚骰子'),
 ('拼点打平','3 + 2 = 5','3 + 2 = 5','双方打平','没有额外打平词条。','下一枚骰子'),
 ('被动骰无对手','招架 1～6 + 1','对方骰子已用尽','不触发','跳过本骰，不产生攻击与伤害。','结束当前技能')]):
    x=24+(i%2)*582; y=100+(i//2)*294; box(x,y,550,270,'white','line',8); text(x+24,y+35,title,22,'ink',700)
    text(x+24,y+80,left,24,'green',700); text(x+292,y+80,right,20,'red',700); text(x+24,y+123,result,26,'ink',700); text(x+24,y+161,note,16,'muted'); button(x+24,y+203,nextlabel,500,'primary')
end('下一骰 → 11 新位次；同交锋有下一张技能则换卡；全部技能用尽 → 下个交锋；没有交锋 → 23。主动骰无对手 → 13。')

start(13,'单方面攻击 · 目标选择与默认值','现有｜选择本次目标或持久默认目标；无对方技能时才请求选择')
board(True,True,phase='交锋 02 · 单方面攻击'); modal('选择受击角色',282,105,616,575)
box(310,206,560,142,'pale','green',8); tick(330,228,'绯红决斗者',True); text(330,294,'生命 12 / 12 · 当前默认目标',20,'red',700)
tick(310,385,'同时设为后续攻击的默认目标',False)
text(310,437,'本次选中：绯红决斗者',20); button(310,488,'取消选择',220); button(550,488,'攻击此目标',320,'primary')
box(310,560,560,87,'pale','line',8); text(330,593,'已设默认目标：绯红决斗者',19,'green',700); text(330,623,'继续当前攻击；主界面的默认目标同步更新。',15)
end('取消 → 返回当前结算，仍等待选目标；关闭同取消。勾选后确认保存默认；仅从主界面进入时按钮为“保存默认目标”。')

start(14,'伤害与护盾 · 真实扣减反馈','独立局面示例｜伤害取自破势重砸首骰词条 2；其第二骰类型待核对')
for i,(title,before,after,formula,shield) in enumerate([
 ('普通伤害 · 无护盾','12 / 12','10 / 12','2 伤害 − 0 抵挡 = 2 生命损失','护盾不变：0'),
 ('普通伤害 · 普通护盾','12 / 12','11 / 12','2 伤害 − 1 抵挡 = 1 生命损失','普通护盾 1 → 0'),
 ('普通伤害 · 强化护盾','12 / 12','12 / 12','2 伤害 − 2 抵挡 = 0 生命损失','强化护盾 2 → 0'),
 ('致命伤害','1 / 12','0 / 12','2 伤害，生命最低为 0','绯红决斗者阵亡')]):
    x=24+(i%2)*582; y=100+(i//2)*294; box(x,y,550,270,'white','line',8); text(x+24,y+39,title,23,'ink',700); text(x+24,y+93,before+'  →  '+after,29,'red',700); lines(x+24,y+140,[formula,shield],17); button(x+24,y+205,'查看终局' if i==3 else '继续结算',500,'primary')
end('存活 → 11；阵亡且对方全灭 → 24，否则回到战场，阵亡角色禁用。穿甲/超穿甲按实际伤害事件显示对应护盾减量。')

start(15,'双方角色详情 · 技能清单可选择','从角色卡打开侧抽屉；背后保留战场。左右两份是不同角色的实际内容')
for i,char in enumerate(DATA['characters']):
    x=24+i*582; box(x,100,550,577,'white','line',8); text(x+24,143,char['name'],27,'red' if i else 'green',700); button(x+424,114,'关闭',100)
    text(x+24,182,f'铁契军团 · 精英 · 生命 {char["max_hp"]}/{char["max_hp"]}',18)
    text(x+24,217,'交锋上限 2 · 个人费上限 1',17); text(x+24,251,'普通盾 0  /  强化盾 0  /  概念盾 0',16)
    text(x+24,285,'被动技能：无',17,'muted')
    for j,skill in enumerate(char['skills']):
        sy=312+j*48; box(x+24,sy,500,42,'pale' if j==0 else 'paper','line'); text(x+38,sy+28,skill['name'],17); text(x+300,sy+28,f'{skill["cost"]} 费',16); text(x+378,sy+28,'战斗外 ↗' if skill.get('out_of_combat') else '查看 ↗',15,'green')
end('点击技能行 → 25～27 对应完整内容；叠层布局见 28。关闭返回原战场，不清空选择。')

start(16,'牌区 · 四个标签的展开内容','同一牌区浮层的局部状态对照；当前标签用底色明确标识')
for i,title in enumerate(['抽牌堆 3','手牌 2','待回收 1','战斗外 1']):
    x=24+(i%2)*582; y=100+(i//2)*294; box(x,y,550,270,'white','line',8)
    for j,tab in enumerate(['抽牌堆','手牌','待回收','战斗外']): button(x+14+j*133,y+15,tab,123,'selected' if i==j else 'normal')
    if i==0: crest(x+24,y+91,100); text(x+154,y+126,'剩余 3 张',26,'ink',700); text(x+154,y+167,'牌序与内容不公开',18,'muted')
    else:
        names=['全线守备','铁誓反击'] if i==1 else ['试探刺击'] if i==2 else ['尖刺必杀']
        for j,name in enumerate(names):
            box(x+24,y+88+j*55,502,45,'paper','line'); text(x+40,y+118+j*55,name,19); text(x+400,y+118+j*55,'查看 ↗',15,'green')
    button(x+24,y+210,'关闭牌区',502)
end('四个标签分别显示对应内容；卡牌行 → 完整详情 25～27（只读）；关闭 → 原战场。手牌详情允许“选择扣置”仅在己方置卡时。')

start(17,'牌区空态与抽牌不足 · 不隐藏结果','四类空内容与实际抽取数量均具体画出；不自动补牌或洗牌')
for i,(title,note,action) in enumerate([('抽牌堆 0','本次未抽到牌，手牌数量保持不变。','继续回合'),('手牌 0','当前没有手牌，已结束本方置卡。','关闭牌区'),('待回收 0','当前没有等待回收的卡牌。','关闭牌区'),('战斗外 0','当前没有战斗外卡牌。','关闭牌区')]):
    x=24+(i%2)*582; y=96+(i//2)*215; box(x,y,550,194,'white','line',8); text(x+24,y+39,title,25,'ink',700); text(x+24,y+86,note,17,'muted'); button(x+24,y+127,action,500)
box(24,548,1132,135,'pale','line',8); text(48,588,'原计划抽 2 张，实际抽到 1 张',25,'green',700); text(48,627,'获得：全线守备  ·  抽牌堆 1 → 0  ·  手牌 0 → 1',19); button(890,608,'进入置卡',240,'primary')
end('关闭回到原战场；继续/进入置卡 → 06。多个角色选弃时若候选不足，不要求玩家选择不存在的卡：按实际候选保留。')

start(18,'菜单、暂停与结算记录 · 有遮罩上下文','保留当前交锋；打开菜单不会重新投骰。记录面板从菜单展开，关闭返回菜单')
board(True,True,phase='交锋 01 · 已暂停'); dim(); box(740,82,416,604,'white','line',8); text(768,125,'对局菜单',27,'ink',700)
button(768,156,'继续对局',360,'primary'); button(768,217,'结算记录',360); button(768,278,'规则说明',360); button(768,339,'设置',360)
box(48,153,650,490,'white','line',8); text(76,199,'结算记录',27,'ink',700); button(560,169,'关闭',108)
for i,(label,detail) in enumerate([('交锋 01 · 第 1 骰','招架 7 > 突刺 5'),('拼点胜利','铁壁先锋获胜；无伤害部分'),('生命变化','铁壁先锋 15/15；绯红决斗者 12/12'),('等待下一骰','招架 1～6+1 对 闪避 1～6+1')]):
    sy=240+i*83; text(76,sy,label,18,'ink',700); text(76,sy+31,detail,17,'muted'); line(76,sy+47,660,sy+47)
scroll(677,238,5,350,fraction=.7)
end('继续 → 11 原位；记录关闭 → 菜单仍在；规则 → 19；设置 → 20；Esc 每次只关闭顶层。局部暂停按钮切为“继续展示”。')

start(19,'规则面板 · 顶部与滚动后的完整内容','前端可读规则，不把实现术语和代码问题放进正文；底部关闭按钮固定')
for i in range(2):
    x=24+i*582; box(x,96,550,582,'white','line',8); text(x+24,137,'对局规则',27,'ink',700); button(x+424,110,'关闭',100)
    rows=[('阵容','每方 1～5 名角色，从共享角色池选择。'),('回合开始','比较速度，平局重投；每回合基础抽 2 张。'),('多人抽牌','角色数大于 1 时，看角色数 + 1 张，保留 2 张。'),('置卡','先手首次填 1 个半交锋，之后每次填 2 个。'),('结束置卡','可提前结束；结束后本回合不能再次置卡。')] if i==0 else [('费用','全局费用 5；每角色个人费 1，个人费优先。'),('拼点与伤害','比较补正后骰点；伤害读取骰子的伤害部分。'),('被动骰子','招架与闪避没有拼点对象时不触发。'),('回合结束','用过的卡先回牌底，待回收卡随后返回。'),('终局','对方无存活角色时获胜；双方全灭为平局。')]
    for j,(title,body) in enumerate(rows):
        sy=191+j*78; text(x+24,sy,title,20,'ink',700); text(x+24,sy+30,body,15,'muted')
    scroll(x+533,171,5,420,offset=.5 if i else 0,fraction=.5); button(x+24,614,'返回菜单',500)
end('左：滚动顶部；右：滚动底部。滚动只移动正文；关闭/返回 → 18。费用规则作为前端目标，底层差异仅写在图外待定标记。')

start(20,'设置 · 开关、焦点和关闭后的结果','提案｜只有减少动效这一项；明确开启/关闭，不引入未设计的音量或分辨率设置')
for i,on in enumerate([False,True]):
    x=24+i*582; box(x,108,550,404,'white','line',8); text(x+24,151,'设置',27,'ink',700); button(x+424,122,'关闭',100)
    text(x+24,223,'减少动效',23,'ink',700); button(x+310,190,'开启' if on else '关闭',214,'selected' if on else 'normal')
    lines(x+24,292,['使用直接切换与文字反馈。' if on else '使用短暂过渡保持操作连续。','骰子结果不因显示方式改变。','设置立即生效，无需保存。'],18)
    button(x+24,433,'返回菜单',500)
box(24,550,1132,130,'pale','line',8); text(48,590,'减少动效已开启',23,'green',700); text(48,628,'返回交锋 01 · 第 1 骰，当前骰点与阅读位置保持不变。',19)
end('点击开关切换左右状态；关闭/返回 → 18，继续 → 11 原位。Tab 聚焦开关，空格切换；设置关闭后保留选择。')

start(21,'操作反馈 · 正常、悬停、聚焦、按下与处理中','共享按钮状态用真实操作文字展示；错误保持在原操作区域，不做无关全屏刷新')
for i,(label,kind) in enumerate([('确认扣置','normal'),('确认扣置','selected'),('确认扣置','primary'),('确认扣置','normal'),('正在扣置…','disabled'),('确认扣置','disabled')]):
    x=24+(i%3)*388; y=108+(i//3)*172; text(x,y,['默认','悬停','按下','键盘焦点','处理中 · 防止重复提交','禁用 · 当前无法支付'][i],19,'ink',700)
    if i==3: box(x-4,y+20,358,52,'white','green',8)
    button(x,y+24,label,350,kind)
box(24,460,550,220,'white','line',8); text(48,502,'未扣置成功',25,'red',700); lines(48,546,['手牌、费用与交锋均保持原值。','请重试，或返回选择其他技能。'],17); button(48,609,'重试扣置',238,'primary'); button(304,609,'返回手牌',246)
box(606,460,550,220,'white','line',8); text(630,502,'已扣置全线守备',25,'green',700); text(630,546,'交锋 01 · 个人费 1 → 0 · 手牌 2 → 1',17); button(630,609,'继续置卡',500,'primary')
end('悬停只改变表面，焦点 2px 外框；按下不移动布局。成功 → 08；失败重试 → 处理中；返回 → 06。反馈同样用于确认选弃。')

start(22,'边界状态 · 就地禁用与可恢复路径','每条错误具有相关对象、原因和下一步；前端提案与源码缺口在图外标明')
for i,(title,detail,action) in enumerate([('费用不足 · 铁誓反击','需要 3 费；个人 0 + 全局 2 = 2。','返回选择其他手牌'),('交锋次数已满 · 铁壁先锋','已占用 2 / 2 次交锋。','结束本方置卡'),('阵容人数已满','已选 5 / 5 名角色，不能继续添加。','返回已选阵容'),('没有可选角色','需为另一位玩家保留至少 1 名角色。','移除最近选择'),('角色资料需要核对','破势重砸含未识别骰子类型，暂不可使用。','返回角色资料'),('没有可攻击目标','对方没有存活角色，停止本次攻击。','查看终局')]):
    x=24+(i%2)*582; y=90+(i//2)*202; box(x,y,550,185,'white','line',8); text(x+24,y+37,title,22,'red',700); text(x+24,y+79,detail,16,'muted'); button(x+24,y+116,action,500)
end('返回手牌 → 06；结束 → 09；阵容 → 02；移除 → 02 未选；资料 → 15/25；终局 → 24。满人数属于扩展卡包边界。')

start(23,'回合完成 · 回收顺序与下一回合','现有｜先回收场上卡，再回收待回收卡；护盾与占用清零，不自动洗牌')
board(True,True,phase='回合完成'); modal('第 1 回合结束',260,92,660,596)
for i,(label,value) in enumerate([('已用卡回牌底','全线守备 → 铁誓反击'),('待回收卡随后返回','试探刺击'),('护盾','普通 2 → 0；强化 1 → 0；概念 0'),('资源与占用','个人费 0 → 1；交锋占用 2 → 0'),('下一回合','重新投速度，再进行抽牌')]):
    sy=211+i*72; text(290,sy,label,18,'ink',700); text(290,sy+29,value,17,'muted')
button(290,610,'开始第 2 回合',600,'primary')
end('开始下一回合 → 04；关闭仅查看已清空战场，主操作仍为“开始第 2 回合”。已经返回牌堆的卡不能再次回收。')

start(24,'阵亡与终局 · 三种结果及只读回看','分别为独立状态，不在游戏中同时并排；终局后禁用所有推进与置卡操作')
for i,(title,body,color) in enumerate([('玩家一胜利','玩家二全部角色阵亡。','green'),('玩家一战败','己方全部角色阵亡。','red'),('平局','双方同时没有存活角色。','ink')]):
    x=24+i*380; box(x,100,356,420,'white','line',8); crest(x+114,130,126,color); text(x+24,304,title,31,color,700); text(x+24,351,body,17,'muted'); button(x+24,390,'查看最后结算',308); button(x+24,451,'返回开始',308,'primary')
box(24,552,1132,129,'rose','line',8); text(48,594,'绯红决斗者 · 阵亡',26,'red',700); text(48,635,'生命 0 / 12 · 场上所属技能移入战斗外 · 该角色不再提供可操作手牌',18)
end('最后结算 → 12/14 只读，底部按钮改“返回终局”；返回开始 → 01。阵亡卡牌全区域处理仍需统一，见图外待定。')

for page in range(3):
    start(25+page,'技能详情全集 · '+str(page+1)+'/3','所有 11 张实际技能逐张绘制；详情内容由卡包快照生成，不用“同上”代替独有骰子')
    for local,skill in enumerate(SKILLS[page*4:page*4+4]):
        x=24+(local%2)*582; y=90+(local//2)*300
        anchor('skill-'+skill['id']); skillbody(skill,x,y,550,280); close()
    if page==2:
        box(606,390,550,280,'paper','line',8); text(630,430,'从牌区打开的只读详情',24,'ink',700); text(630,473,'尖刺必杀位于战斗外，不能直接扣置。',17,'muted'); button(630,521,'选择扣置',500,'disabled'); button(630,593,'关闭详情',500)
    end('详情容器及背景见 07；从角色/牌区打开则隐藏支付栏，底部只显示“关闭详情”；关闭回到来源页并保留滚动位置。')

start(28,'层级展开 · 战场 → 角色抽屉 → 技能详情','保留每层上下文；只关闭顶层。这里实际展示 15 的抽屉位置和完整遮挡关系')
board(True); dim(); box(600,64,580,636,'white','line'); text(626,108,'铁壁先锋',27,'ink',700); button(1042,80,'关闭角色',112)
for i,skill in enumerate(SKILLS[:5]):
    y=168+i*72; box(624,y,528,52,'pale' if i==4 else 'paper','line'); text(644,y+34,skill['name'],20); text(1040,y+34,f'{skill["cost"]} 费',16)
emit('<rect x="600" y="130" width="580" height="570" fill="#243D39" opacity=".2"/>')
box(76,150,690,496,'white','green',8); text(102,195,'铁誓反击 · 技能详情',26,'ink',700); button(638,165,'关闭详情',102)
skillbody(SKILLS[4],102,222,638,280); button(102,558,'返回角色资料',638)
end('关闭详情/返回/Esc → 角色抽屉仍在，铁誓反击行保持选中；再关闭角色 → 08。详情在只读入口不出现扣置按钮。')

start(29,'长手牌与日志 · 滚动前后可见内容','局部状态｜不缩小文字塞满手牌；滚动指示与剩余数量常驻，完整名称不截断')
text(24,110,'手牌 5 · 当前可见第 1～3 张',23,'ink',700)
for i,k in enumerate([0,1,2]): smallcard(24+i*300,142,SKILLS[k])
button(946,180,'向右查看',210); scroll(24,280,1132,6,fraction=.6)
text(24,334,'手牌 5 · 向右滚动后可见第 3～5 张',23,'ink',700)
for i,k in enumerate([2,3,4]): smallcard(24+i*300,366,SKILLS[k])
button(946,405,'向左查看',210); scroll(24,504,1132,6,offset=.4,fraction=.6)
box(24,548,550,137,'white','line',8); text(48,586,'结算记录 · 空',22,'ink',700); text(48,626,'本局尚未产生结算记录。',17,'muted'); button(360,626,'关闭记录',190)
box(606,548,550,137,'white','line',8); text(630,586,'记录底部 · 对局开始',22,'ink',700); text(630,626,'玩家一：铁壁先锋；玩家二：绯红决斗者。',16); scroll(1137,570,5,89,offset=.6,fraction=.4)
end('手牌按钮/滚轮/拖动横条结果如上下两行；卡牌选择 → 07。日志滚动不改变战局；空记录关闭 → 18。')

start(30,'次级分支 · 当前目标、暂停与只读返回','只变化的局部控件集中展示；所有操作都保留原阶段，不另建未说明的页面')
box(24,100,550,268,'white','line',8); text(48,143,'更改默认目标',25,'ink',700); tick(48,184,'绯红决斗者 · 生命 12/12',True); text(48,238,'仅修改默认值，不发动攻击。',17,'muted'); button(48,296,'取消',180); button(246,296,'保存默认目标',304,'primary')
box(606,100,550,268,'pale','line',8); text(630,143,'默认目标已保存',25,'green',700); text(630,194,'绯红决斗者',24,'red',700); button(630,232,'更改默认目标',500); text(630,333,'主界面右侧原位置更新。',17,'muted')
box(24,400,550,279,'white','line',8); text(48,443,'已暂停 · 交锋 01 / 第 1 骰',24,'ink',700); text(48,495,'招架 7 > 突刺 5 · 结果已保留',21); button(48,603,'继续展示',500,'primary')
box(606,400,550,279,'white','line',8); text(630,443,'最后结算 · 只读',24,'ink',700); text(630,495,'绯红决斗者生命 1 → 0 · 玩家一胜利',19); button(630,541,'继续结算',500,'disabled'); button(630,603,'返回终局',500)
end('取消 → 06 保持旧目标；保存 → 右上局部结果；继续展示 → 11；返回终局 → 24。默认目标失效时回退到最高生命存活敌人。')

text(48,8740,'待定：费用支付未接入；guard 类型需统一；多人选弃与阵亡卡牌归属需确认。前端提案不等于现有实现。',17,'red')
emit('</svg>')
(OUT/'PL-III-PC-界面与状态-v2.svg').write_text('\n'.join(parts),encoding='utf-8')
(OUT/'PL-III-PC-界面与状态.svg').write_text('\n'.join(parts),encoding='utf-8')

# Coverage checks anchor existence and path closure; it does not prove visual completeness.
flows=[]
for name,route in [('setup',[1,2,3,4,6]),('placement',[6,7,8,9,10,11]),('combat',[11,12,13,14,23,4]),('inspection',[6,15,25,15,6]),('decks',[6,16,27,16,6]),('settings',[6,18,20,18,6]),('rules',[18,19,18]),('recovery',[7,21,6]),('terminal',[14,24,1])]:
    nodes=[]
    for i,target in enumerate(route):
        node={'id':str(i),'targets':[f'screen-{target:02}']}
        if i==len(route)-1: node['terminal']=True
        else: node['next']=[str(i+1)]
        nodes.append(node)
    flows.append({'id':name,'starts':['0'],'nodes':nodes})
coverage={'requirements':[{'id':f'visible-screen-{i}','targets':[f'screen-{i:02}']} for i in range(1,31)],'flows':flows}
(OUT/'coverage-v2.json').write_text(json.dumps(coverage,ensure_ascii=False,indent=2),encoding='utf-8')
print('v2 generated: 30 screens, 11 skill details')
