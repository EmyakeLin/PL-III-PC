"use strict";

const byId = id => document.getElementById(id);
// Keeping the credential in the fragment preserves reloads and never sends it in a URL.
const token = new URLSearchParams(location.hash.slice(1)).get("token");
const kinds = {
    place: "常规扣牌", pass: "交出置卡权", end: "结束常规置卡",
    attack: "开牌前进攻", intercept: "迎击", let_through: "放行", end_attack: "结束主动进攻",
    special_place: "特殊置卡", special_replace: "替换技能", special_attack: "即时进攻",
    special_intercept: "迎击即时交锋", special_pass_intercept: "放行即时交锋",
    special_custom: "按牌面打出", special_ability: "使用能力", special_choose_card: "依词条选牌",
    special_decline_card: "放弃此次选牌", special_choose_slot: "依词条选择交锋", decline: "让过此次机会"
};
const triggers = {
    decision: "下个席位决策", placement: "取得常规置卡权", pre_reveal: "开牌前声明或迎击",
    roll: "双方刚掷出骰面", scores_ready: "拼点点数就绪、尚未判胜", action: "有人采取行动后", timing: "管线行动时点",
    combat: "交锋结算时", reveal: "统一开牌", turn_end: "回合结束", timer: "等待指定时间"
};
const phaseNames = {setup: "准备阶段", turn_start: "回合开始", draw: "抽牌", placement: "常规置卡",
    pre_reveal: "开牌前交锋", reveal: "统一开牌", combat: "交锋结算", turn_end: "回合结束", finished: "终局"};
const battles = {regular: "常规", pre_reveal: "开牌前", instant: "即时"};
const scores = {lt: "己方点数较低", eq: "双方同点", gt: "己方点数较高"};
const dieNames = {slash: "斩击", pierce: "突刺", blunt: "打击", block: "招架", evade: "闪避", blank: "空白"};
const results = {win: "胜", lose: "负", draw: "平", skip: "跳过"};
const actionFilters = {kind: "action-kind", card_id: "card", target_card_id: "replace-card", ability_id: "ability",
    character_id: "target", duel_number: "target-duel", response_number: "response"};
const eventFilters = {duel_kind: "duel-kind", duel_number: "duel", die_number: "die",
    own_card_id: "using-card", score: "score", pending_number: "pending", turn: "turn",
    action_kind: "observed-kind", actor_side: "actor", timing: "timing"};
const printed = new Map();
let catalog = null;
let catalogRequest = null;
let roster = [];
const records = new Map();
let room = null;
let writing = false;
let disconnected = false;
let clockOffset = Date.now() - performance.now();
let guide = null;
let ruleVersion = 0;

function make(tag, label) {
    const node = document.createElement(tag);
    if (label != null) node.textContent = label;
    return node;
}
function setText(node, label) {
    if (node.textContent !== label) node.textContent = label;
}
function selectItems(id, entries, first) {
    const field = byId(id);
    const saved = field.value;
    const items = first ? [["", first], ...entries] : entries;
    if (field.options.length === items.length && items.every(([value, label], i) =>
        field.options[i].value === value && field.options[i].text === label)) return;
    field.replaceChildren(...items.map(([value, label]) => new Option(label, value)));
    if (items.some(([value]) => value === saved)) field.value = saved;
}
function button(label, invoke) {
    const node = make("button", label);
    node.type = "button";
    node.addEventListener("click", invoke);
    return node;
}
function fillRows(list, items, key, create, update) {
    const remaining = new Map(Array.from(list.children, node => [node.dataset.key, node]));
    items.forEach((item, index) => {
        const identity = String(key(item));
        const node = remaining.get(identity) || create(item);
        remaining.delete(identity);
        node.dataset.key = identity;
        update(node, item);
        if (list.children[index] !== node) list.insertBefore(node, list.children[index] || null);
    });
    remaining.forEach(node => node.remove());
}
const seatName = side => side === 1 ? "席位一" : "席位二";
function titleOf(id) {
    const hand = room?.frame.players.find(p => p.side === room.side)?.hand || [];
    const card = hand.find(c => c.action_key === id);
    return card ? card.name + (card.borrowed ? "（取自对手）" : "") : printed.get(id)?.name || id;
}

async function api(method, body = {}) {
    const headers = {"Content-Type": "application/json"};
    if (token) headers.Authorization = "Bearer " + token;
    const controller = new AbortController();
    const deadline = setTimeout(() => controller.abort(), 18000);
    try {
        const response = await fetch("/api/" + method, {
            method: "POST", headers, body: JSON.stringify(body), cache: "no-store", signal: controller.signal
        });
        const data = await response.json();
        if (!response.ok) {
            const error = new Error(data.error || "房间请求失败。");
            error.status = response.status;
            throw error;
        }
        return data;
    } catch (error) {
        if (controller.signal.aborted) throw new TypeError("房间响应超时。");
        throw error;
    } finally { clearTimeout(deadline); }
}
function notice(message) { setText(byId("notice"), message); }
function connection(message) {
    disconnected = Boolean(message);
    const banner = byId("connection");
    setText(banner, message);
    banner.hidden = !disconnected;
    if (room) updateControls();
}

function updateTeam(node, player) {
    node.dataset.side = player.side;
    const fighter = player.characters[0];
    const origin = [fighter.title, fighter.faction].filter(Boolean).join(" · ");
    const own = player.side === room.side ? " · 我方" : "";
    const seatLabel = seatName(player.side) + own;
    const readiness = room.ready_sides.includes(player.side) ? "已准备" : "待准备";
    setText(node.querySelector(".team-side"), room.lobby ? seatLabel + " · " + readiness : seatLabel);
    setText(node.querySelector(".team-faction"), origin);
    setText(node.querySelector("h3"), fighter.name);
    setText(node.querySelector(".hp"), fighter.hp + " / " + fighter.max_hp);
    const bar = node.querySelector("progress");
    bar.max = fighter.max_hp;
    bar.value = fighter.hp;
    const stats = ["完整度 " + fighter.lightcore_hp + "/" + fighter.max_lightcore_hp,
        "个人费 " + fighter.cost.available, "通用费 " + player.cost.available,
        "手牌 " + player.hand_count, "速度 " + player.speed];
    setText(node.querySelector(".team-stats"), stats.join(" · "));
    const shields = {normal: "护盾", reinforced: "强化护盾", concept: "概念护盾"};
    const statuses = Object.entries(fighter.statuses || {}).map(([name, n]) => name + " " + n);
    for (const [name, count] of Object.entries(fighter.ability_effects || {})) statuses.push(name + " " + count + " 次");
    for (const reserve of fighter.reserved_dice || []) {
        statuses.push("迎击「" + reserve.skill + "」第" + reserve.position + "骰 ×" + reserve.remaining);
    }
    for (const [name, n] of Object.entries(fighter.shields || {})) {
        if (n) statuses.push((shields[name] || name) + " " + n);
    }
    const statusNode = node.querySelector(".statuses");
    setText(statusNode, statuses.join(" · "));
    statusNode.hidden = !statuses.length;
}
function duelRow(node, item) {
    const slot = item.slot;
    const cards = slot.sides.map(seat => {
        const names = seat.cards.map(card => card.hidden ? "扣牌" : card.name);
        return seatName(seat.side) + " " + (names.join("、") || "空位");
    });
    if (slot.target) {
        const target = slot.target.kind === "duel" ? "常规 " + slot.target.number : slot.target.name;
        cards.push("目标 " + target, slot.ready ? "已就绪" : "待迎击");
    }
    setText(node.firstChild, battles[item.kind] + " " + slot.number);
    setText(node.children[1], cards.join(" · "));
    const clock = node.lastChild;
    const timing = item.kind === "pre_reveal" && room.frame.response_times?.find(entry => entry.number === slot.number);
    clock.hidden = !timing;
    if (timing) {
        clock.dataset.from = timing.declared_at_ms;
        clock.dataset.to = timing.answered_at_ms ?? "";
        updateClock(clock);
    }
}
function updateClock(clock) {
    const end = clock.dataset.to ? Number(clock.dataset.to) : clockOffset + performance.now();
    const seconds = Math.max(0, Math.floor((end - Number(clock.dataset.from)) / 1000));
    setText(clock, (clock.dataset.to ? "回应耗时 " : "已等 ") + seconds + " 秒");
}
setInterval(() => document.querySelectorAll("time:not([hidden])").forEach(updateClock), 1000);
function updateBoard(frame) {
    const sets = {regular: frame.duels, pre_reveal: frame.pre_reveal?.duels, instant: frame.special_duels};
    const slots = Object.entries(sets).flatMap(([kind, duels]) => (duels || []).map(slot => ({kind, slot})));
    fillRows(byId("duels"), slots, item => item.kind + item.slot.number, () => {
        const node = make("li"); node.append(make("strong"), make("span"), make("time")); return node;
    }, duelRow);
    byId("empty-board").hidden = !!slots.length;
    const combat = frame.combat;
    const showClash = !!(combat && combat.sides.some(side => side.die?.rolled_value != null));
    byId("clash").hidden = !showClash;
    if (showClash) {
        const dice = combat.sides.map(side => {
            const die = side.die;
            if (!die) return seatName(side.side) + " 空轮";
            const value = die.clash_score ?? "待定";
            if (room.event?.kind === "roll") return seatName(side.side) + " 第" + side.die_number + "骰 · 骰面 " + die.rolled_value;
            const result = results[die.result] || "胜负待定";
            return seatName(side.side) + " 第" + side.die_number + "骰 · 拼点 " + value + "（" + result + "）";
        });
        setText(byId("clash"), battles[combat.kind] + " " + combat.duel_number + "　" + dice.join(" / "));
    }
    const owner = frame.players.find(player => player.side === room.side);
    byId("board-area").hidden = Boolean(room.lobby);
    byId("hand-area").hidden = !owner || Boolean(room.lobby);
    const hand = owner?.hand || [];
    if (owner && catalog) bindHandFilter(hand);
    byId("empty-hand").hidden = !!hand.length;
    fillRows(byId("hand"), hand, card => card.instance_id, card => {
        const node = make("li"); node.append(button("", () => showCard(card.id))); return node;
    }, (node, card) => setText(node.firstChild, card.name + " · " + card.cost + " 费"
        + (card.borrowed ? " · 取自对手" : "") + (card.use_restricted ? " · 当前无法使用" : "")));
}

function describePlan(plan) {
    const match = plan.match || {}, when = plan.when || {};
    const details = [triggers[plan.event], plan.mode === "execute" ? "自动执行" : "留给我决定"];
    if (match.kind) details.push(kinds[match.kind] || match.kind);
    if (match.card_id) details.push(titleOf(match.card_id));
    if (match.ability_id) details.push(catalog?.actions?.[match.ability_id] || match.ability_id);
    if (match.target_card_id) details.push("目标技能 " + titleOf(match.target_card_id));
    if (match.character_id) {
        const actors = room.frame.players.flatMap(player => player.characters);
        details.push("目标 " + (actors.find(actor => actor.id === match.character_id)?.name || match.character_id));
    }
    if (match.duel_number) details.push("目标常规 " + match.duel_number);
    if (match.response_number) details.push("回应 " + match.response_number);
    if (when.duel_kind || when.duel_number) details.push((battles[when.duel_kind] || "交锋") + " " + (when.duel_number || ""));
    if (when.own_card_id) details.push(titleOf(when.own_card_id) + "进行中");
    if (when.die_number) details.push("第 " + when.die_number + " 骰");
    if (when.score) details.push(scores[when.score]);
    if (when.after_ms) details.push(when.after_ms + " 毫秒");
    if (when.pending_number) details.push("编号 " + when.pending_number + " 待迎击");
    if (when.turn) details.push("回合 " + when.turn);
    if (when.actor_side) details.push(seatName(when.actor_side));
    if (when.action_kind) details.push("观察 " + (kinds[when.action_kind] || when.action_kind));
    if (when.timing) details.push(when.timing);
    if (plan.repeat) details.push("每次触发");
    return details.filter(Boolean).join(" · ");
}
function updateLobby(isReady, busy) {
    const lobby = room.lobby;
    const picking = Boolean(lobby && room.side);
    byId("lobby").hidden = !picking;
    if (!picking) return;
    const selector = byId("fighter-pick");
    const opponentPick = lobby.picks[3 - room.side];
    fillRows(selector, lobby.characters, fighter => fighter.id, () => make("option"), (option, fighter) => {
        const taken = fighter.id === opponentPick && !fighter.mirror_allowed;
        option.value = fighter.id;
        option.disabled = taken;
        setText(option, fighter.name + (taken ? "（对方已选）" : ""));
    });
    if (!writing) selector.value = lobby.picks[room.side];
    selector.disabled = busy || isReady;
    byId("lobby-ready").disabled = busy || isReady;
    setText(byId("lobby-ready"), isReady ? "已准备" : "确认角色并准备");
    const note = isReady ? "角色已锁定，等待另一席准备。" :
        "双方各选一名角色，允许镜像的角色可同选。准备会锁定你的角色并预留常规置卡、进攻与迎击，特殊时机可在下方提前声明。";
    setText(byId("lobby-note"), note);
}
function updateControls() {
    const ready = room.ready_sides || [];
    const mine = !!room.side, isReady = ready.includes(room.side);
    const options = room.options || [];
    const busy = writing || disconnected;
    updateLobby(isReady, busy);
    byId("station").hidden = !mine || room.finished;
    document.body.toggleAttribute("data-spectator", !mine || room.finished);
    byId("prepared").textContent = ready.length + " / 2 席准备";
    byId("ready").hidden = isReady || room.started || Boolean(room.lobby);
    byId("ready").disabled = busy;
    setText(byId("prepare-note"), room.started ?
        "声明从登记后的新事件起生效。可以先登记下一次行动，再处理当前选择。" :
        isReady ? "已预留常规置卡、进攻与迎击，正在等对方准备。" :
        "准备时会预留常规置卡、进攻与迎击。特殊操作可在这里单独登记。");
    fillRows(byId("plans"), room.declarations || [], plan => plan.id, plan => {
        const node = make("li");
        node.append(make("span"), button("撤销", () => write("prepare", {declaration: {cancel: plan.id}})));
        return node;
    }, (node, plan) => {
        setText(node.firstChild, describePlan(plan));
        node.lastChild.disabled = busy;
    });
    byId("decision").hidden = !options.length;
    setText(byId("decision-note"), room.event?.timing || "选择本次声明允许的行动。");
    fillRows(byId("options"), options, option => option.id, option =>
        button("", () => write("act", {option_id: option.id})), (node, option) => {
        setText(node, option.label || kinds[option.kind] || option.kind);
        node.disabled = busy;
    });
    byId("plan-form").querySelector("button").disabled = busy || room.finished;
}
function consume(data) {
    for (const event of data.events || []) if (event.text) records.set(event.id, event);
    const current = !room || data.revision >= room.revision;
    if (current) room = data;
    const frame = room.frame;
    if (current && Number.isFinite(data.server_time_ms)) clockOffset = data.server_time_ms - performance.now();
    syncRoster(frame.players);
    document.documentElement.dataset.side = room.side || "";
    const manualDesk = byId("manual-desk");
    if (room.side) manualDesk.href = "/desk" + location.hash;
    manualDesk.hidden = !room.side;
    setText(byId("seat"), room.side ? seatName(room.side) : "公开观战");
    setText(byId("round"), room.started && frame.turn ? "第 " + frame.turn + " 回合" : "对局准备");
    const outcome = room.winner_side ? seatName(room.winner_side) + "获胜" : "平局";
    let phase = room.started ? phaseNames[frame.phase] || "对局进行中" : "等待双方准备";
    if (frame.mode === "placement" && frame.placing_side) phase = seatName(frame.placing_side) + " 常规置卡";
    if (frame.mode === "skill_choice") phase = frame.timing || "等待技能选择";
    if (frame.mode === "pre_reveal") {
        const attack = frame.pre_reveal.attacking_side;
        phase = attack ? seatName(attack) + " 持开牌前进攻权" : "开牌前 · 等待迎击";
    }
    setText(byId("phase"), room.finished ? outcome : phase);
    fillRows(byId("teams"), frame.players, player => player.side,
        () => byId("team-template").content.firstElementChild.cloneNode(true), updateTeam);
    updateBoard(frame);
    updateControls();
    const events = Array.from(records.values()).sort((a,b) => b.id - a.id);
    fillRows(byId("history"), events, event => event.id, () => make("li"), (node, event) => setText(node, event.text));
    byId("empty-history").hidden = !!events.length;
}
async function write(method, fields) {
    if (writing || disconnected || !room?.side) return;
    writing = true;
    updateControls();
    try {
        // getRandomValues is also available over plain HTTP on the LAN.
        const nonce = crypto.getRandomValues(new Uint32Array(4));
        const body = {...fields, revision: room.revision, request_id: Array.from(nonce).join("-")};
        let data;
        while (!data) {
            try { data = await api(method, body); }
            catch (error) {
                if (!(error instanceof TypeError)) throw error;
                notice("连接中断，正在核对刚才的操作。");
                await pause(1500); // Retry the same request until the room acknowledges it.
            }
        }
        consume(data);
        notice(method === "prepare" ? (fields.declaration.cancel ? "已撤销声明。" : "声明已登记。") : "");
    } catch (error) {
        notice(error.message);
        try { consume(await api("observe", {cursor: room.cursor})); } catch { /* Keep the last frame. */ }
    } finally { writing = false; updateControls(); }
}

function fieldsOf(mapping) {
    const fields = {};
    for (const [key, id] of Object.entries(mapping)) {
        const input = byId(id), value = input.value.trim();
        if (value) fields[key] = input.type === "number" || id === "actor" ? Number(value) : value;
    }
    return fields;
}
function syncForm() {
    const execute = byId("mode").value === "execute";
    byId("auto-note").hidden = !execute;
    byId("action-kind").required = execute;
    byId("action-kind").options[0].textContent = execute ? "选择动作" : "任意合法动作";
    const timer = byId("event").value === "timer";
    byId("timer-field").hidden = !timer;
    byId("delay").disabled = !timer;
    byId("pending").required = timer;
    if (timer) byId("filters").open = true;
}
byId("mode").addEventListener("change", syncForm);
byId("event").addEventListener("change", syncForm);
byId("plan-form").addEventListener("submit", event => {
    event.preventDefault();
    const when = fieldsOf(eventFilters);
    const trigger = byId("event").value;
    if (trigger === "timer") when.after_ms = Number(byId("delay").value);
    const declaration = {event: trigger, mode: byId("mode").value, match: fieldsOf(actionFilters), when,
        repeat: Boolean(byId("repeat").value)};
    write("prepare", {declaration});
});
byId("ready").addEventListener("click", () => write("ready", {}));
byId("fighter-pick").addEventListener("change", event => write("select_character", {character_id: event.target.value}));
byId("lobby-ready").addEventListener("click", () => write("ready", {}));
byId("lobby-catalog").addEventListener("click", showCatalog);

function bindCatalog() {
    const mine = catalog.players.find(player => player.side === room?.side);
    const enemy = catalog.players.find(player => player.side !== room?.side);
    const skills = (mine?.characters || []).flatMap(actor => actor.skills);
    const entries = skills.map(skill => [skill.id, skill.name]);
    selectItems("ability", Object.entries(catalog.actions || {}), "任意");
    selectItems("using-card", entries, "任意");
    bindHandFilter(room.frame.players.find(p => p.side === room.side)?.hand || []);
    const targets = (enemy?.characters || []).map(actor => [actor.id, actor.name]);
    selectItems("target", targets, "任意");
}
function bindHandFilter(hand) {
    const own = catalog.players.find(p => p.side === room.side);
    const entries = new Map((own?.characters || []).flatMap(c => c.skills.map(s => [s.id, s.name])));
    for (const card of hand) entries.set(card.action_key, titleOf(card.action_key));
    selectItems("replace-card", [...entries], "任意");
    for (const card of hand) if (card.action_key !== card.id) entries.delete(card.id);
    selectItems("card", [...entries], "任意");
}
function syncRoster(players) {
    const picks = players.map(player => player.characters[0].id);
    if (picks.length === roster.length && picks.every((id, index) => id === roster[index])) return;
    if (room.side) {
        const myIndex = room.side - 1;
        const opponentIndex = 1 - myIndex;
        if (picks[myIndex] !== roster[myIndex]) {
            for (const id of ["card", "replace-card", "using-card"]) selectItems(id, [], "任意");
        }
        if (picks[opponentIndex] !== roster[opponentIndex]) selectItems("target", [], "任意");
    }
    roster = picks;
    catalog = null;
    catalogRequest = null;
    printed.clear();
    const dialog = byId("book");
    if (dialog.open && dialog.dataset.rosterBound === "true") showCatalog();
    else getCatalog().catch(error => notice(error.message));
}
async function getCatalog() {
    if (catalog) return catalog;
    if (!catalogRequest) {
        const requestedRoster = roster;
        const request = api("rules", {topic: "catalog"}).then(data => {
            if (requestedRoster !== roster) return getCatalog();
            catalog = data.catalog;
            for (const player of catalog.players) for (const actor of player.characters) {
                for (const skill of actor.skills) printed.set(skill.id, skill);
            }
            bindCatalog();
            return catalog;
        }).finally(() => {
            if (request === catalogRequest) catalogRequest = null;
        });
        catalogRequest = request;
    }
    return catalogRequest;
}
function showDialog() {
    const book = byId("book");
    if (!book.open) book.showModal();
}
function navigation(items) {
    byId("rule-topics").replaceChildren(...items.map(([label, fn]) => button(label, fn)));
}
function page(title, content) {
    setText(byId("book-title"), title);
    byId("rule-content").replaceChildren(content);
}
function loading(title, rosterBound = false) {
    const version = ++ruleVersion;
    byId("book").dataset.rosterBound = String(rosterBound);
    navigation([]);
    page(title, make("p", "正在读取…"));
    showDialog();
    return version;
}
function ruleError(version, error) {
    if (version !== ruleVersion) return;
    page("读取失败", make("p", error.message));
    navigation([["返回目录", showIndex]]);
}
async function showIndex() {
    const version = loading("规则与卡面");
    try {
        if (!guide) guide = await api("rules");
        if (version !== ruleVersion) return;
        const topics = guide.topics.filter(topic => /^\d+$/.test(topic.id)).map(topic => [topic.title, () => showChapter(topic.id)]);
        navigation([["出战图鉴", showCatalog], ...topics]);
        page("规则与卡面", make("p", "打开章节查阅正式规则，或查看双方角色的印刷技能。"));
    } catch (error) { ruleError(version, error); }
}
async function showChapter(id) {
    const version = loading("正式规则书");
    try {
        const chapter = await api("rules", {topic: id});
        if (version !== ruleVersion) return;
        navigation([["返回目录", showIndex]]);
        page(chapter.title, make("p", chapter.text));
    } catch (error) { ruleError(version, error); }
}
async function showCatalog() {
    const version = loading("出战图鉴", true);
    try {
        const book = await getCatalog();
        if (version !== ruleVersion) return;
        const sections = make("div");
        for (const player of book.players) for (const actor of player.characters) {
            const section = make("section");
            section.append(make("h3", actor.name));
            const passives = [...(actor.faction_passives || []), ...(actor.passives || [])];
            for (const passive of passives) {
                const description = passive.description || passive.entries.join("；");
                section.append(make("p", [passive.name, description].filter(Boolean).join("　")));
            }
            const links = make("div"); links.className = "toolbar";
            for (const skill of actor.skills) links.append(button(skill.name, () => showCard(skill.id)));
            section.append(links); sections.append(section);
        }
        for (const [name, entries] of Object.entries(book.statuses || {})) {
            const detail = make("details");
            detail.append(make("summary", name), make("p", entries.join("；")));
            sections.append(detail);
        }
        navigation([["返回目录", showIndex]]);
        page("出战图鉴", sections);
    } catch (error) { ruleError(version, error); }
}
async function showCard(id) {
    const version = loading("技能卡面", true);
    try {
        await getCatalog();
        if (version !== ruleVersion) return;
        const card = printed.get(id);
        if (!card) throw new Error("图鉴中没有这张技能。");
        const traits = [card.cost + " 费"];
        if (card.range_level) traits.push(["", "普通远程", "强化远程", "极限远程"][card.range_level]);
        if (card.ignore_range) traits.push("无视远程 " + card.ignore_range);
        if (card.pre_reveal) traits.push("可在开牌前打出");
        if (card.anytime_replace) traits.push("可随时替换");
        const ways = {attack: "主动进攻", place: "置入空位", custom: "按牌面执行"};
        if (card.anytime_play?.length) traits.push("可随时" + card.anytime_play.map(way => ways[way]).join("、"));
        if (card.pre_reveal && !card.interceptable) traits.push("开牌前进攻不可拦截");
        if (card.anytime_play?.includes("attack")) traits.push(card.instant_interceptable ? "场内进攻可迎击" : "场内进攻不可拦截");
        const lines = [traits.join(" · "), ...card.entries];
        for (const die of card.dice) lines.push((dieNames[die.type] || die.type) + " 1～" + die.roll_max + "　" + die.entries.join("；"));
        navigation([["出战图鉴", showCatalog], ["规则目录", showIndex]]);
        page(card.name, make("p", lines.join("\n\n")));
    } catch (error) { ruleError(version, error); }
}
byId("rules").addEventListener("click", showIndex);
byId("close").addEventListener("click", () => byId("book").close());
byId("book").addEventListener("close", () => { ++ruleVersion; });
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
async function followRoom() {
    // A write receipt can arrive before the outstanding poll. Only the polling
    // stream has received every event up to this cursor.
    let cursor = 0;
    while (true) {
        try {
            // Players also watch public changes while they have no decision to make.
            // A long wait can finish with just a timeout receipt, without a frame.
            let data = room ? await api("follow", {cursor, timeout: 5}) : await api("observe", {cursor});
            if (data.timeout) data = await api("observe", {cursor});
            consume(data);
            cursor = data.cursor;
            if (disconnected) connection("");
            if (!catalog && !catalogRequest) getCatalog().catch(error => notice(error.message));
            if (room.finished && cursor >= room.cursor) return;
        } catch (error) {
            if (error.status === 401 || error.status === 403) {
                connection("邀请已失效，请打开房主提供的本场链接。");
                return;
            }
            connection("正在重新连接房间。恢复后会同步最新战况，你也可以用原邀请重新加入。");
            await pause(1500);
        }
    }
}
const actionKinds = Object.entries(kinds).filter(([key]) => key !== "decline");
selectItems("event", Object.entries(triggers));
selectItems("action-kind", actionKinds, "任意合法动作");
selectItems("observed-kind", actionKinds, "任意");
syncForm();
followRoom();
