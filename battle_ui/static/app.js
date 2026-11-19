// The engine owns the match. Only the current selection and dialog belong to the page.
const byId = id => document.getElementById(id);
const typeNames = {slash: "斩击", pierce: "突刺", blunt: "打击", block: "招架", evade: "闪避", blank: "空白"};
const ranks = {NORMAL: "常人", ELITE: "精英", BOSS: "首领", EMPOWERED_BOSS: "强化首领"};
const phases = {placement: "置卡", handoff: "交接", reveal: "开牌", combat: "交锋", turn_end: "回合结束", finished: "对局结束"};
const outcomes = {win: "胜", lose: "负", draw: "平", skip: "跳过"};

let match = null;
let selection = null;
let busy = false;
let pageGeneration = 0;
let dialogGeneration = 0;
let dialogTrigger = null;
const modal = byId("modal");
const hand = byId("hand");

function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
}

function icon(name) {
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("class", "icon die-icon");
    svg.setAttribute("aria-hidden", "true");
    const use = document.createElementNS(ns, "use");
    use.setAttribute("href", "#i-" + name);
    svg.append(use);
    return svg;
}

function setText(node, text) {
    if (node.textContent !== text) node.textContent = text;
}

function button(label, primary, activate) {
    const variant = primary ? "btn btn-primary" : "btn btn-quiet";
    const node = element("button", variant, label);
    node.type = "button";
    node.addEventListener("click", activate);
    return node;
}

function team(side) {
    return match?.frame.players.find(player => player.side === side);
}

function selectedCard() {
    const currentHand = team(match?.active_side)?.hand;
    return currentHand?.find(card => card.id === selection);
}

function bookFor(side, characterId) {
    const collection = match.catalog.players.find(player => player.side === side);
    return collection?.characters.find(character => character.id === characterId);
}

function heading(body, text) {
    body.append(element("h3", "detail-heading", text));
}

function entries(body, texts) {
    if (!texts?.length) return;
    const list = element("ul", "rule-list");
    for (const text of texts) list.append(element("li", "", text));
    body.append(list);
}

function showDialog(title, build) {
    if (busy) return;
    dialogGeneration++;
    delete modal.dataset.privateReset;
    if (!modal.open) dialogTrigger = document.activeElement;
    setText(byId("modal-title"), title);
    const body = byId("modal-body");
    const actions = byId("modal-actions");
    body.replaceChildren();
    actions.replaceChildren();
    build(body, actions);
    body.scrollTop = 0;
    if (!modal.open) modal.showModal();
    byId("modal-close").focus({preventScroll: true});
}

function closeDialog(privateReset = false) {
    const generation = ++dialogGeneration;
    if (privateReset === true) modal.dataset.privateReset = "true";
    if (modal.open) modal.close();
    const clearContents = () => {
        if (modal.open || generation !== dialogGeneration) return;
        setText(byId("modal-title"), "");
        byId("modal-body").replaceChildren();
        byId("modal-actions").replaceChildren();
    };
    if (privateReset === true) clearContents();
    else Promise.allSettled(modal.getAnimations().map(animation => animation.finished)).then(clearContents);
    if (dialogTrigger?.isConnected) dialogTrigger.focus({preventScroll: true});
    dialogTrigger = null;
}

function dieRow(die, summary) {
    const row = element("span", "die-row");
    const name = typeNames[die.type] || die.type;
    const range = "1–" + die.roll_max;
    row.append(icon(die.type), element("span", "die-name", name), element("span", "die-roll", range));
    if (summary) {
        const damage = die.entries?.find(text => /^\d+\s*点.*伤害$/.test(text));
        if (damage) row.append(element("span", "die-effect", damage));
    }
    return row;
}

function cardDetails(card) {
    showDialog(card.name, body => {
        body.append(element("p", "dialog-copy", "费用 " + card.cost));
        entries(body, card.entries);
        for (const die of card.dice) {
            const section = element("section", "detail-dice");
            section.append(dieRow(die, false));
            const formula = [];
            if (die.base_value) formula.push("基础值 " + die.base_value);
            if (die.multiplier !== 1) formula.push("倍率 " + die.multiplier);
            if (die.final_bonus) formula.push("最终修正 " + die.final_bonus);
            if (die.formula && !["+", "-", "(b + v) * m + f"].includes(die.formula)) {
                formula.push("公式 " + die.formula);
            }
            if (formula.length) section.append(element("p", "dialog-copy", formula.join(" · ")));
            entries(section, die.entries);
            body.append(section);
        }
    });
}

function fighterDetails(side) {
    const player = team(side);
    if (!player) return;
    const actor = player.characters[0];
    const printed = bookFor(side, actor.id);
    showDialog(actor.name, body => {
        const used = actor.duels.used == null ? "未公开" : actor.duels.used;
        const shields = actor.shields;
        body.append(element("p", "dialog-copy", player.name + " · " + (ranks[actor.rank] || actor.rank)));
        body.append(element("p", "dialog-copy", `生命 ${actor.hp}/${actor.max_hp} · 交锋 ${used}/${actor.duels.max} · 个人费 ${actor.cost.available} · 通用费 ${player.cost.available}`));
        body.append(element("p", "dialog-copy", `普通盾 ${shields.normal} · 强化盾 ${shields.reinforced} · 概念盾 ${shields.concept}`));
        const statusList = Object.entries(actor.statuses);
        if (statusList.length) {
            heading(body, "当前状态");
            for (const [name, count] of statusList) {
                body.append(element("strong", "", name + " × " + count));
                entries(body, match.catalog.statuses[name]);
            }
        }
        const passives = [...(printed?.faction_passives || []), ...(printed?.passives || [])];
        if (passives.length) {
            heading(body, "被动技能");
            for (const passive of passives) {
                body.append(element("strong", "", passive.name || "被动"));
                if (passive.description) body.append(element("p", "dialog-copy", passive.description));
                entries(body, passive.entries);
            }
        }
        if (printed?.skills.length) {
            heading(body, "技能组");
            for (const skill of printed.skills) {
                const label = skill.name + " · " + skill.cost + " 费";
                body.append(button(label, false, () => cardDetails(skill)));
            }
        }
    });
}

function rulesDialog() {
    showDialog("对战规则", body => {
        entries(body, [
            "两名玩家各控制一名角色。每回合先抽牌，再比较速度，由先手先扣一张牌。",
            "选择手牌后点击扣置。此后每个置卡窗口最多扣两张，首张扣好后可以提前交权。结束置卡会放弃本回合剩余的置卡机会。",
            "双方结束置卡后统一开牌。技能使用时优先支付个人费，再用通用费补足。费用不足的技能无法发动。",
            "双方逐骰比拼点点数。攻击骰获胜时命中，攻击骰无对位时单方面攻击。角色生命归零即阵亡。",
        ]);
    });
}

function historyDialog() {
    if (!match) return;
    showDialog("对战记录", body => {
        const list = element("ol", "rule-list");
        for (const text of match.history) list.append(element("li", "", text));
        if (list.children.length) body.append(list);
        else body.append(element("p", "dialog-copy", "本局尚无公开结算。"));
    });
}

function newGameDialog() {
    if (!match) return;
    showDialog("新对局", (body, actions) => {
        const selectors = [];
        for (const player of match.frame.players) {
            const field = element("label", "field", player.name);
            const select = element("select");
            for (const fighter of match.choices) {
                const label = `${fighter.name} · ${fighter.max_hp} 生命`;
                const option = element("option", "", label);
                option.value = fighter.id;
                select.append(option);
            }
            select.value = player.characters[0].id;
            field.append(select);
            body.append(field);
            selectors.push(select);
        }
        if (!match.frame.is_over) body.append(element("p", "dialog-copy", "开始新对局后，当前对局将结束。"));
        const start = button("开始新对局", true, () => {
            const roster = selectors.map(select => select.value);
            send("new", {roster});
        });
        const validate = () => {
            const duplicate = selectors[0].value === selectors[1].value;
            start.disabled = duplicate;
            for (const select of selectors) {
                const other = selectors.find(item => item !== select);
                for (const option of select.options) option.disabled = option.value === other.value;
            }
        };
        for (const select of selectors) select.addEventListener("change", validate);
        validate();
        actions.append(button("取消", false, () => closeDialog()), start);
    });
}

function updateFighter(player) {
    const node = byId("fighter-" + player.side);
    const field = name => node.querySelector('[data-field="' + name + '"]');
    const actor = player.characters[0];
    const lead = player.side === match.frame.first_side ? " · 先手" : "";
    const meta = [actor.title || actor.faction, ranks[actor.rank] || actor.rank].filter(Boolean);
    setText(field("side"), player.name + lead);
    setText(field("name"), actor.name);
    setText(field("meta"), meta.join(" · "));
    setText(field("hp"), String(actor.hp));
    setText(field("max-hp"), String(actor.max_hp));
    const bar = field("hp-bar");
    bar.max = actor.max_hp;
    bar.value = actor.hp;
    bar.setAttribute("aria-label", actor.name + "生命");
    const stats = [
        "速度 " + actor.speed,
        "通用费 " + player.cost.available,
        "个人费 " + actor.cost.available,
    ];
    const statsField = field("stats");
    statsField.replaceChildren(...stats.map(label => element("span", "stat", label)));
    const statuses = Object.entries(actor.statuses).map(([name, count]) => name + " " + count);
    const shieldNames = {normal: "护盾", reinforced: "强化盾", concept: "概念盾"};
    for (const [kind, amount] of Object.entries(actor.shields)) {
        if (amount > 0) statuses.push(shieldNames[kind] + " " + amount);
    }
    const statusesField = field("statuses");
    statusesField.replaceChildren(...statuses.map(label => element("span", "status", label)));
    node.dataset.active = String(match.mode === "placement" && match.active_side === player.side);
    node.disabled = false;
    node.setAttribute("aria-label", "查看" + actor.name + "的角色详情");
}

function currentSlot() {
    const side = match.active_side;
    const duels = match.frame.duels;
    const vacancy = duels.find(slot => slot.sides.some(group => group.side === side && !group.cards.length));
    return vacancy?.number ?? duels.length + 1;
}

function liveDieText(side, number, card) {
    const combat = match.frame.combat;
    if (combat?.duel_number !== number) return "";
    const active = combat.sides.find(info => info.side === side && info.card_id === card.id);
    const die = active?.die;
    if (!die) return "";
    const parts = ["第 " + active.die_number + " 骰", typeNames[die.type] || die.type];
    if (die.final_score != null) parts.push("最终 " + die.final_score);
    if (die.clash_score != null) parts.push("拼点 " + die.clash_score);
    if (die.result) parts.push(outcomes[die.result] || die.result);
    return parts.join(" · ");
}

function duelSide(side, cards, number) {
    const group = element("div", "duel-side " + (side === 1 ? "side-one" : "side-two"));
    if (!cards.length) {
        const waiting = match.mode === "placement" || match.mode === "handoff";
        const label = waiting ? "待置卡" : "空位";
        const empty = element("span", "duel-card");
        empty.append(element("strong", "", label));
        group.append(empty);
    }
    for (const card of cards) {
        if (card.hidden) {
            const back = element("span", "duel-card");
            back.append(element("strong", "", "已扣置"), element("small", "", "牌面未公开"));
            group.append(back);
        } else {
            const detail = element("button", "duel-card");
            detail.type = "button";
            detail.append(element("strong", "", card.name));
            const current = liveDieText(side, number, card);
            const label = current || (card.cost + " 费 · " + card.dice.length + " 骰");
            detail.append(element("small", "", label));
            detail.addEventListener("click", () => cardDetails(card));
            group.append(detail);
        }
    }
    return group;
}

function renderArena() {
    const slots = [...match.frame.duels];
    const placing = match.mode === "placement";
    const pending = placing ? currentSlot() : null;
    if (placing && pending > slots.length) {
        slots.push({number: slots.length + 1, sides: match.frame.players.map(p => ({side: p.side, cards: []}))});
    }
    setText(byId("arena-title"), "交锋序列");
    const resolved = match.frame.cards_revealed;
    const note = placing ? "准备第 " + pending + " 交锋" : (resolved ? "牌面已公开" : "双方扣置后统一开牌");
    setText(byId("arena-note"), match.mode === "finished" ? "对局结束" : note);
    const rail = byId("duels");
    if (!slots.length) {
        const emptyMessage = match.mode === "turn_end" ? "交锋槽已回收。" : "当前没有交锋。";
        let empty = rail.querySelector(".empty-state");
        if (!empty) {
            empty = element("p", "empty-state");
            rail.replaceChildren(empty);
        }
        setText(empty, emptyMessage);
        return;
    }
    rail.querySelector(".empty-state")?.remove();
    for (const [index, slot] of slots.entries()) {
        let row = rail.children[index];
        if (!row) {
            row = element("div", "duel-row");
            rail.append(row);
        }
        const [left, right] = slot.sides;
        const indexLabel = element("span", "duel-index", String(slot.number).padStart(2, "0"));
        indexLabel.setAttribute("aria-label", "第 " + slot.number + " 交锋");
        row.replaceChildren(duelSide(left.side, left.cards, slot.number), indexLabel,
                            duelSide(right.side, right.cards, slot.number));
        row.dataset.active = String(slot.number === (match.frame.combat?.duel_number ?? pending));
    }
    while (rail.children.length > slots.length) rail.lastElementChild.remove();
}

function makeHandCard(card, ownerName) {
    const tile = element("button", "skill-card");
    tile.type = "button";
    tile.dataset.card = card.id;
    const head = element("span", "card-head");
    head.append(element("span", "card-owner", ownerName), element("span", "card-cost", card.cost + " 费"));
    const dice = element("span", "card-dice");
    for (const die of card.dice) dice.append(dieRow(die, true));
    tile.append(head, element("strong", "card-name", card.name), dice);
    tile.addEventListener("click", () => {
        if (busy || match?.mode !== "placement") return;
        selection = tile.dataset.card;
        syncSelection();
    });
    return tile;
}

function renderHand(player) {
    const ownHand = player?.hand || [];
    const keepIds = new Set(ownHand.map(card => card.id));
    for (const node of [...hand.children]) {
        if (!keepIds.has(node.dataset.card)) node.remove();
    }
    const tiles = new Map([...hand.children].map(node => [node.dataset.card, node]));
    for (const [index, card] of ownHand.entries()) {
        const owner = player.characters.find(actor => actor.id === card.character_id);
        const tile = tiles.get(card.id) || makeHandCard(card, owner?.name || player.name);
        if (hand.children[index] !== tile) hand.insertBefore(tile, hand.children[index] || null);
    }
    if (!ownHand.length) hand.append(element("p", "empty-state", "手中没有技能牌。"));
    setText(byId("hand-title"), player.name + "的手牌");
    setText(byId("hand-meta"), "手牌 " + player.hand_count + " · 牌堆 " + player.draw_count);
    syncSelection();
}

function syncSelection() {
    const selected = selectedCard();
    const legal = match.legal_cards.includes(selection);
    for (const tile of hand.querySelectorAll(".skill-card")) {
        const chosen = tile.dataset.card === selection;
        tile.dataset.selected = String(chosen);
        tile.setAttribute("aria-pressed", String(chosen));
        tile.disabled = busy;
    }
    byId("detail-btn").disabled = busy || !selected;
    byId("primary-btn").disabled = busy || !legal;
    const actor = team(match.active_side)?.characters[0];
    const remaining = actor && actor.duels.used != null ? actor.duels.max - actor.duels.used : null;
    const note = selected ? (legal ? selected.name + "将扣在第 " + currentSlot() + " 交锋。"
                                     : "这名角色本回合已无可用交锋。")
                          : "选择一张手牌扣置。";
    const quota = remaining == null ? "" : " 剩余交锋 " + remaining + "。";
    setText(byId("action-note"), note + quota);
}

function winnerLabel() {
    const winner = team(match.frame.winner_side);
    return winner ? winner.name + "获胜" : "双方平局";
}

function renderPublic() {
    const finished = match.mode === "finished";
    const title = finished ? winnerLabel() : phases[match.mode];
    setText(byId("hand-title"), title);
    setText(byId("hand-meta"), "");
    const lastMessage = match.history.at(-1);
    const note = match.mode === "reveal" ? "双方的扣牌现已公开。"
               : match.mode === "turn_end" ? "本回合结算完毕。"
               : finished ? "本局结算完毕。" : "查看当前交锋的结算。";
    const message = lastMessage || note;
    let line = hand.querySelector(".empty-state");
    if (!line || hand.children.length !== 1 || hand.firstElementChild !== line) {
        line = element("p", "empty-state");
        hand.replaceChildren(line);
    }
    setText(line, message);
    setText(byId("action-note"), "");
    const primary = byId("primary-btn");
    const labels = {reveal: "开始交锋", combat: "继续结算", turn_end: "下一回合", finished: "再来一局"};
    setText(primary, labels[match.mode]);
    primary.disabled = busy;
}

function render() {
    const placing = match.mode === "placement";
    const handoff = match.mode === "handoff";
    const player = team(match.active_side);
    document.documentElement.dataset.viewer = match.frame.viewer_side ?? "public";
    setText(byId("round-number"), String(match.frame.turn).padStart(2, "0"));
    setText(byId("phase-name"), phases[match.mode]);
    for (const p of match.frame.players) updateFighter(p);
    renderArena();
    byId("handoff").hidden = !handoff;
    hand.hidden = handoff;
    byId("actions").hidden = handoff;
    byId("detail-btn").hidden = !placing;
    byId("pass-btn").hidden = !placing || !match.can_pass;
    byId("end-btn").hidden = !placing;
    byId("end-btn").disabled = busy;
    byId("pass-btn").disabled = busy;
    byId("new-game").disabled = busy;
    byId("history-toggle").disabled = !match.history.length;
    if (placing) {
        setText(byId("primary-btn"), "扣置所选牌");
        renderHand(player);
    } else if (handoff) {
        hand.replaceChildren();
        setText(byId("action-note"), "");
        setText(byId("hand-title"), "交接置卡权");
        setText(byId("hand-meta"), "");
        setText(byId("handoff-title"), "请将屏幕交给" + player.name);
        setText(byId("handoff-action"), "我是" + player.name + "，查看手牌");
        byId("handoff-action").disabled = busy;
    } else {
        renderPublic();
    }
}

function notice(text) {
    setText(byId("notice"), text);
}

function showState(state, newMatch = false) {
    const previous = match;
    const wasHandoff = previous?.mode === "handoff";
    const privateSideChanged = previous?.frame.viewer_side !== state.frame.viewer_side;
    if (privateSideChanged || newMatch) {
        hand.replaceChildren();
        closeDialog(true);
    }
    match = state;
    selection = null;
    render();
    if (state.mode === "handoff") {
        byId("handoff-action").focus({preventScroll: true});
    } else if (wasHandoff) {
        const first = hand.querySelector(".skill-card") || byId("primary-btn");
        first.focus({preventScroll: true});
    } else if (previous && document.activeElement === document.body) {
        const primary = byId("primary-btn");
        const focus = primary.disabled ? hand.querySelector(".skill-card") : primary;
        focus?.focus({preventScroll: true});
    }
}

function hidePrivateData() {
    match = null;
    selection = null;
    closeDialog(true);
    hand.replaceChildren();
    byId("duels").replaceChildren();
    setText(byId("hand-title"), "对局状态");
    setText(byId("hand-meta"), "");
    setText(byId("action-note"), "");
    byId("handoff").hidden = true;
    byId("actions").hidden = false;
    hand.hidden = false;
    for (const id of ["detail-btn", "pass-btn", "end-btn"]) byId(id).hidden = true;
    for (const id of ["new-game", "history-toggle", "fighter-1", "fighter-2"]) byId(id).disabled = true;
    setText(byId("primary-btn"), "重新连接");
    byId("primary-btn").disabled = false;
    document.documentElement.dataset.viewer = "public";
}

function lockControls() {
    busy = true;
    document.body.setAttribute("aria-busy", "true");
    for (const id of ["new-game", "primary-btn", "detail-btn", "end-btn", "pass-btn", "handoff-action"]) {
        byId(id).disabled = true;
    }
    for (const tile of hand.querySelectorAll(".skill-card")) tile.disabled = true;
}

function unlockControls() {
    busy = false;
    document.body.removeAttribute("aria-busy");
}

async function readState() {
    const response = await fetch("/api/state", {cache: "no-store"});
    if (!response.ok) throw new Error("无法读取对局");
    return response.json();
}

async function loadMatch() {
    if (busy) return;
    const generation = pageGeneration;
    lockControls();
    notice("正在读取对局…");
    try {
        const state = await readState();
        if (generation !== pageGeneration) return;
        unlockControls();
        showState(state);
        notice("");
    } catch {
        if (generation !== pageGeneration) return;
        unlockControls();
        hidePrivateData();
        notice("暂时无法读取对局，请重新连接。");
    }
}

async function send(action, fields = {}) {
    if (busy || !match) return;
    closeDialog(true);
    const generation = pageGeneration;
    const request = {action, revision: match.revision, ...fields};
    lockControls();
    notice("正在提交…");
    try {
        const response = await fetch("/api/action", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(request),
            cache: "no-store",
        });
        const payload = await response.json();
        if (generation !== pageGeneration) return;
        if (!response.ok && response.status !== 409) {
            if (response.status >= 500) throw new Error("对局状态待同步");
            unlockControls();
            render();
            notice(payload.error || "这项操作当前不可用。");
            return;
        }
        unlockControls();
        showState(payload, action === "new");
        notice(response.status === 409 ? "对局已更新，请按当前局面操作。" : "");
    } catch {
        if (generation !== pageGeneration) return;
        // The server may have accepted the action even when its reply did not arrive.
        hidePrivateData();
        try {
            const state = await readState();
            if (generation !== pageGeneration) return;
            unlockControls();
            showState(state);
            notice("已重新同步对局。");
        } catch {
            if (generation !== pageGeneration) return;
            unlockControls();
            hidePrivateData();
            notice("连接中断，请重新连接以查看当前对局。");
        }
    }
}

byId("primary-btn").addEventListener("click", event => {
    if (busy || event.detail > 1) return;
    if (!match) { loadMatch(); return; }
    if (match.mode === "finished") { newGameDialog(); return; }
    if (match.mode === "placement") {
        if (match.legal_cards.includes(selection)) send("place", {card_id: selection});
    } else if (match.mode !== "handoff") {
        send("next");
    }
});
byId("handoff-action").addEventListener("click", event => {
    if (event.detail <= 1 && match?.mode === "handoff") send("ready");
});
byId("pass-btn").addEventListener("click", () => send("pass"));
byId("end-btn").addEventListener("click", () => {
    showDialog("结束本回合置卡？", (body, actions) => {
        body.append(element("p", "dialog-copy", "已扣置的牌会保留，本回合剩余的置卡机会将放弃。"));
        actions.append(button("继续置卡", false, () => closeDialog()), button("结束置卡", true, () => send("end")));
    });
});
byId("detail-btn").addEventListener("click", () => {
    const card = selectedCard();
    if (card) cardDetails(card);
});
byId("fighter-1").addEventListener("click", () => fighterDetails(1));
byId("fighter-2").addEventListener("click", () => fighterDetails(2));
byId("new-game").addEventListener("click", newGameDialog);
byId("rules").addEventListener("click", rulesDialog);
byId("history-toggle").addEventListener("click", historyDialog);
byId("modal-close").addEventListener("click", () => closeDialog());
modal.addEventListener("cancel", event => {
    event.preventDefault();
    closeDialog();
});
window.addEventListener("pagehide", () => {
    pageGeneration++;
    unlockControls();
    hidePrivateData();
});
window.addEventListener("pageshow", event => {
    if (event.persisted) loadMatch();
});
loadMatch();
