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
const phaseNames = {setup: "准备阶段", turn_start: "回合开始", draw: "抽牌", placement: "常规置卡",
    pre_reveal: "开牌前交锋", reveal: "统一开牌", combat: "交锋结算", turn_end: "回合结束", finished: "终局"};
const battles = {regular: "常规", pre_reveal: "开牌前", instant: "即时"};
const dieNames = {slash: "斩击", pierce: "突刺", blunt: "砸击", block: "招架", evade: "闪避", blank: "空白骰", skip: "跳过"};
const results = {win: "胜", lose: "负", draw: "平", skip: "跳过"};
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
const seatName = side => side === room?.bot_side ? "电脑对手" : side === 1 ? "席位一" : "席位二";
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
    const showReadiness = room.lobby && !room.bot_side;
    const teamLabel = showReadiness ? seatLabel + " · " + readiness : seatLabel;
    setText(node.querySelector(".team-side"), teamLabel);
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
    const suspended = combat?.suspended || [];
    const hasScores = combat?.sides.some(side => side.die?.rolled_value != null);
    const showClash = hasScores || suspended.length > 0;
    byId("clash").hidden = !showClash;
    if (showClash) {
        const dice = hasScores ? combat.sides.map(side => {
            const die = side.die;
            if (!die) return seatName(side.side) + " 空轮";
            const value = die.clash_score ?? "待定";
            const position = die.position || side.die_number;
            const hit = die.hit_index > 1 ? " · 第 " + die.hit_index + " 次命中" : "";
            const owner = seatName(side.side) + " 第" + position + "骰";
            if (room.event?.kind === "roll") return owner + " · 骰面 " + die.rolled_value;
            const result = results[die.result] || "胜负待定";
            return owner + hit + " · 拼点 " + value + "（" + result + "）";
        }) : [];
        const prior = suspended.at(-1);
        let context = "";
        if (prior) {
            const parent = [battles[prior.kind] || phaseNames[prior.kind], prior.duel_number, prior.card_name,
                prior.die_position ? "第 " + prior.die_position + " 骰" : ""].filter(Boolean).join(" ");
            context = [prior.source_name, "结算后续行 " + parent].filter(Boolean).join(" · ");
        }
        const current = battles[combat.kind] + " " + combat.duel_number;
        setText(byId("clash"), [current, dice.join(" / "), context].filter(Boolean).join("　"));
    }
    const owner = frame.players.find(player => player.side === room.side);
    byId("board-area").hidden = Boolean(room.lobby);
    byId("hand-area").hidden = !owner || Boolean(room.lobby);
    const hand = owner?.hand || [];
    byId("empty-hand").hidden = !!hand.length;
    fillRows(byId("hand"), hand, card => card.instance_id, card => {
        const node = make("li"); node.append(button("", () => showCard(card.id))); return node;
    }, (node, card) => setText(node.firstChild, card.name + " · " + card.cost + " 费"
        + (card.borrowed ? " · 取自对手" : "") + (card.use_restricted ? " · 当前无法使用" : "")));
}

function updateFighterPicker(selector, side, lobby, locked) {
    const opponentSide = 3 - side;
    const opponentPick = lobby.picks[opponentSide];
    fillRows(selector, lobby.characters, fighter => fighter.id, () => make("option"), (option, fighter) => {
        const taken = fighter.id === opponentPick && !fighter.mirror_allowed;
        option.value = fighter.id;
        option.disabled = taken;
        setText(option, fighter.name + (taken ? "（对方已选）" : ""));
    });
    if (!writing) selector.value = lobby.picks[side];
    selector.disabled = locked;
}
function updateLobby(isReady, busy) {
    const lobby = room.lobby;
    const picking = Boolean(lobby && room.side);
    byId("lobby").hidden = !picking;
    if (!picking) return;
    const botSide = room.bot_side;
    const botMatch = Boolean(botSide);
    const locked = busy || isReady;
    updateFighterPicker(byId("fighter-pick"), room.side, lobby, locked);
    byId("bot-pick-field").hidden = !botMatch;
    if (botMatch) updateFighterPicker(byId("bot-pick"), botSide, lobby, locked);
    const title = botMatch ? "选择双方出战角色" : "我的出战角色";
    const startLabel = botMatch ? "开战" : isReady ? "已准备" : "确认角色并准备";
    setText(byId("lobby-title"), title);
    byId("lobby-ready").disabled = locked;
    setText(byId("lobby-ready"), startLabel);
    const note = botMatch ? "允许镜像的角色可同选。" : isReady ? "角色已锁定，等待另一席准备。" :
        "双方各选一名角色，允许镜像的角色可同选。准备后锁定角色。对局中可以随时暂停查看场内行动。";
    setText(byId("lobby-note"), note);
}
function updateControls() {
    const ready = room.ready_sides || [];
    const mine = !!room.side, isReady = ready.includes(room.side);
    const options = room.options || [];
    const busy = writing || disconnected;
    updateLobby(isReady, busy);
    byId("station").hidden = !mine || room.finished || Boolean(room.bot_side && !room.started);
    document.body.toggleAttribute("data-spectator", !mine || room.finished);
    byId("prepared").hidden = Boolean(room.bot_side);
    byId("prepared").textContent = ready.length + " / 2 席准备";
    byId("ready").hidden = isReady || room.started || Boolean(room.lobby);
    byId("ready").disabled = busy;
    const ownPause = room.paused_by === room.side && mine;
    const playback = byId("pause-game");
    playback.hidden = !room.started || (!room.can_pause && !ownPause);
    playback.disabled = busy;
    setText(playback, ownPause ? "继续对局" : "暂停并行动");
    const pausedText = ownPause ? (options.length ? "已暂停，选择行动或继续对局。" : "此时没有可执行的场内行动。")
        : room.paused_by ? seatName(room.paused_by) + " 正在决策。" : "";
    setText(byId("pause-note"), pausedText);
    byId("decision").hidden = !options.length;
    const choice = room.frame.effect_choice;
    const die = choice?.die_position ? " · 第 " + choice.die_position + " 骰" : "";
    setText(byId("decision").querySelector("h2"), choice ? choice.source_name + die : "轮到你决定");
    setText(byId("decision-note"), choice?.description || room.event?.timing || "选择当前行动。");
    fillRows(byId("options"), options, option => option.id, option => {
        const row = make("div");
        row.className = "choice-option";
        row.append(button("", () => write("act", {option_id: option.id})));
        const inspect = button("查看卡面", () => {
            const current = room.options.find(move => move.id === option.id);
            const card = current?.effect_target?.card;
            if (card) showCard(card.id, card, current.use_preview);
        });
        row.append(inspect);
        return row;
    }, (row, option) => {
        const select = row.firstChild, inspect = row.lastChild;
        setText(select, option.label || kinds[option.kind] || option.kind);
        select.disabled = busy;
        const card = option.effect_target?.card;
        inspect.hidden = !card;
        if (card) inspect.setAttribute("aria-label", "查看" + card.name + "卡面");
    });
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
    manualDesk.hidden = !room.side || Boolean(room.bot_side);
    const seatLabel = room.side ? (room.bot_side ? "离线人机对战" : seatName(room.side)) : "公开观战";
    setText(byId("seat"), seatLabel);
    setText(byId("round"), room.started && frame.turn ? "第 " + frame.turn + " 回合" : "对局准备");
    const outcome = room.winner_side ? seatName(room.winner_side) + "获胜" : "平局";
    let phase = room.started ? phaseNames[frame.phase] || "对局进行中" : room.bot_side ? "单角色 1v1" : "等待双方准备";
    if (frame.mode === "placement" && frame.placing_side) phase = seatName(frame.placing_side) + " 常规置卡";
    if (frame.mode === "timing" || frame.mode === "combat") phase = frame.timing || phase;
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
        notice("");
    } catch (error) {
        notice(error.message);
        try { consume(await api("observe", {cursor: room.cursor})); } catch { /* Keep the last frame. */ }
    } finally { writing = false; updateControls(); }
}

byId("pause-game").addEventListener("click", () => write(room.paused_by === room.side ? "resume" : "pause", {}));
byId("ready").addEventListener("click", () => write("player_ready", {}));
byId("fighter-pick").addEventListener("change", event => write("select_character", {character_id: event.target.value}));
byId("bot-pick").addEventListener("change", event => write("select_character", {
    character_id: event.target.value, target_side: room.bot_side
}));
byId("lobby-ready").addEventListener("click", () => write("player_ready", {}));
byId("lobby-catalog").addEventListener("click", showCatalog);

function syncRoster(players) {
    const picks = players.map(player => player.characters[0].id);
    if (picks.length === roster.length && picks.every((id, index) => id === roster[index])) return;
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
                const description = passive.display_lines.join("\n");
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
async function showCard(id, liveCard, preview) {
    const version = loading("技能卡面", true);
    try {
        if (!liveCard) await getCatalog();
        if (version !== ruleVersion) return;
        const card = liveCard || printed.get(id);
        if (!card) throw new Error("图鉴中没有这张技能。");
        const traits = [card.cost + " 费"];
        if (preview) traits.push("本次通常费用预计 " + preview.cost + " 费");
        if (card.resource_cost) {
            const resource = card.resource_cost;
            const available = preview?.resource_cost?.available;
            const balance = available != null ? "（现有 " + available + "）" : "";
            traits.push("另需 " + resource.amount + " " + resource.status + balance);
        }
        traits.push(...card.range_traits);
        const earlyConditions = Object.entries(card.pre_reveal_requires_status || {});
        if (earlyConditions.length) {
            const terms = earlyConditions.map(([name, count]) => name + "达到" + count + "层");
            traits.push(terms.join("、") + "时可在开牌前打出");
        } else if (card.pre_reveal) traits.push("可在开牌前打出");
        if (card.before_duel_attack) traits.push("可在交锋开始前进攻");
        if (card.pre_reveal_target === "occupied_enemy_slot") traits.push("开牌前须指定有敌方置牌的常规交锋");
        for (const [name, amount] of Object.entries(card.requires_status || {})) traits.push("须持有 " + amount + " " + name);
        if (card.anytime_replace) traits.push("可随时替换");
        const ways = {attack: "主动进攻", place: "置入空位", custom: "按牌面执行"};
        if (card.anytime_play?.length) traits.push("可随时" + card.anytime_play.map(way => ways[way]).join("、"));
        if (card.pre_reveal && !card.interceptable) traits.push("开牌前进攻不可拦截");
        if (card.before_duel_attack || card.anytime_play?.includes("attack"))
            traits.push(card.instant_interceptable ? "场内进攻可迎击" : "场内进攻不可拦截");
        const lines = [traits.join(" · "), ...card.entries];
        for (const die of card.dice) {
            const effects = [...die.range_traits, ...die.entries];
            if (die.resource_cost) effects.push("使用本骰须消耗" + die.resource_cost.amount + die.resource_cost.status);
            if (die.base_value) effects.push("基础值 " + die.base_value);
            if (die.multiplier !== 1) effects.push("倍率 " + die.multiplier);
            const range = die.roll_max != null ? " 1～" + die.roll_max : "";
            lines.push((dieNames[die.type] || die.type) + range + "　" + effects.join("；"));
        }
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
followRoom();
