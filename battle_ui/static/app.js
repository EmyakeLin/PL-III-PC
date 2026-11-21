// The engine owns the match. Only the current selection and dialog belong to the page.
const byId = id => document.getElementById(id);
const typeNames = {slash: "斩击", pierce: "突刺", blunt: "打击", block: "招架", evade: "闪避", blank: "空白", skip: "SKIP"};
const ranks = {NORMAL: "常人", ELITE: "精英", BOSS: "首领", EMPOWERED_BOSS: "强化首领"};
const phases = {placement: "置卡", pre_attack: "开牌前进攻", intercept: "拦截", handoff: "交接", reveal: "开牌", combat: "交锋", turn_end: "回合结束", finished: "对局结束", timing: "行动时点", special: "特殊行动", special_handoff: "特殊行动交接"};
const ranges = ["", "普通远程", "强化远程", "极限远程"];
const outcomes = {win: "胜", lose: "负", draw: "平", skip: "跳过"};

let match = null;
let selection = null;
let busy = false;
let pageGeneration = 0;
let dialogGeneration = 0;
let dialogTrigger = null;
let responseTimer = null;
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
    return currentHand?.find(card => card.action_key === selection);
}

function choosingCard() {
    return ["placement", "pre_attack", "intercept", "special"].includes(match?.mode);
}

function handoffMode(mode) {
    return mode === "handoff" || mode === "special_handoff";
}

function specialDialog() {
    showDialog(match.card_choice ? "选择技能" : match.queued_placement ? "选择交锋" : match.special_pending ? "回应即时进攻" : "选择特殊行动", (body, actions) => {
        const field = element("label", "field", "手牌与目标");
        const select = element("select");
        let chosen = false;
        match.special_options.forEach((move, index) => {
            const option = element("option", "", move.label);
            option.value = index;
            if (!chosen && selection && move.card_id === selection) {
                option.selected = true;
                chosen = true;
            }
            select.append(option);
        });
        field.append(select);
        body.append(field);
        actions.append(button("返回", false, () => closeDialog()), button("确认行动", true, () => {
            send("use_special", {option: Number(select.value)});
        }));
    });
}

function targetText(target) {
    return target.kind === "duel" ? "常规交锋 " + target.number : target.name;
}

function otherSeat() {
    return match.eligible_sides.find(side => side !== match.active_side);
}

function responseDialog() {
    if (!match.pending_responses.length) return;
    showDialog("选择要处理的开牌前交锋", (body, actions) => {
        const duelSelect = element("select");
        const duelField = element("label", "field", "待迎击的进攻");
        for (const slot of match.frame.pre_reveal.duels) {
            if (!match.pending_responses.includes(slot.number)) continue;
            const group = slot.sides.find(part => part.side === slot.attacking_side);
            const attack = group.cards.find(card => card.id === slot.attack_card_id);
            const label = "第 " + slot.number + " 场 · " + (attack?.name || "进攻") + " → " + targetText(slot.target);
            const option = element("option", "", label);
            option.value = slot.number;
            duelSelect.append(option);
        }
        duelField.append(duelSelect);
        const cardSelect = element("select");
        const cardField = element("label", "field", "迎击手牌");
        for (const card of team(match.active_side).hand) {
            if (!match.legal_intercept_cards.includes(card.action_key)) continue;
            const option = element("option", "", card.name + " · " + card.cost + " 费");
            option.value = card.action_key;
            option.selected = card.action_key === selection;
            cardSelect.append(option);
        }
        const hasReplyCard = cardSelect.options.length > 0;
        if (!hasReplyCard) {
            cardSelect.append(element("option", "", "暂无迎击手牌，可稍后回应"));
            cardSelect.disabled = true;
        }
        cardField.append(cardSelect);
        body.append(duelField, cardField);
        const respond = button("打出迎击牌", true, () => {
            send("intercept", {duel_number: Number(duelSelect.value), card_id: cardSelect.value});
        });
        respond.disabled = !hasReplyCard;
        const pass = button("放行所选交锋", false, () => send("let_through", {duel_number: Number(duelSelect.value)}));
        actions.append(button("继续考虑", false, () => closeDialog()), pass, respond);
    });
}

function targetDialog() {
    const card = selectedCard();
    if (!card) return;
    showDialog(card.name + " · 指定目标", (body, actions) => {
        const enemy = match.frame.players.find(player => player.side !== match.active_side);
        const select = element("select");
        const field = element("label", "field", "进攻目标");
        const targets = match.attack_targets[card.action_key].map(target => {
            if (target.kind === "character") {
                return {label: enemy.characters.find(actor => actor.id === target.id).name, target};
            }
            const slot = match.frame.duels[target.number - 1];
            const count = slot.sides.find(side => side.side === enemy.side).cards.length;
            return {label: "常规交锋 " + target.number + " · 对手置牌 " + count + " 张", target};
        });
        for (const item of targets) select.append(element("option", "", item.label));
        field.append(select);
        body.append(field);
        actions.append(button("取消", false, () => closeDialog()), button("声明进攻", true, () => {
            send("attack", {card_id: card.action_key, target: targets[select.selectedIndex].target});
        }));
    });
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
    if (die.type === "skip") {
        row.append(element("span", "die-name", "SKIP · 跳过本轮"));
        return row;
    }
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
        const traits = ["费用 " + card.cost, ...card.range_traits];
        if (card.use_restricted) traits.push("当前无法使用");
        for (const [name, amount] of Object.entries(card.requires_status || {})) {
            traits.push("须持有" + amount + "层" + name);
        }
        const earlyConditions = Object.entries(card.pre_reveal_requires_status || {});
        if (earlyConditions.length) {
            const terms = earlyConditions.map(([name, count]) => name + "达到" + count + "层");
            traits.push(terms.join("、") + "时可在开牌前进攻");
        } else if (card.pre_reveal) traits.push("可在开牌前进攻");
        if (card.before_duel_attack) traits.push("可在交锋开始前进攻");
        if (card.resource_cost) traits.push("使用时须支付" + card.resource_cost.amount + card.resource_cost.status);
        if (card.pre_reveal_target === "occupied_enemy_slot") traits.push("开牌前仅可指定已置敌牌的交锋");
        if (card.anytime_replace) traits.push("可在任意时刻换入");
        const plays = {place: "置入空交锋", attack: "发起进攻", custom: "依牌面打出"};
        for (const mode of card.anytime_play) traits.push("任意时刻可" + plays[mode]);
        const canAttackInField = card.anytime_play.includes("attack");
        if (canAttackInField) {
            traits.push(card.instant_interceptable ? "场内进攻可迎击" : "场内进攻不可迎击");
        }
        if (card.pre_reveal || canAttackInField) {
            traits.push(card.interceptable ? "开牌前进攻可迎击" : "开牌前进攻不可迎击");
        }
        body.append(element("p", "dialog-copy", traits.filter(Boolean).join(" · ")));
        entries(body, card.entries);
        for (const die of card.dice) {
            const section = element("section", "detail-dice");
            section.append(dieRow(die, false));
            const formula = [...die.range_traits];
            if (die.resource_cost) formula.push("使用本骰须消耗" + die.resource_cost.amount + die.resource_cost.status);
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
        for (const form of card.forms || []) {
            body.append(button("查看「" + form.name + "」形态", false, () => cardDetails(form)));
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
        body.append(element("p", "dialog-copy", `光点形态群完整度 ${actor.lightcore_hp}/${actor.max_lightcore_hp}`));
        const lethalHeal = actor.alive && actor.hp >= actor.max_lightcore_hp && actor.hp < actor.max_hp;
        if (lethalHeal) body.append(element("p", "dialog-copy", "当前实际回复生命会立即阵亡。"));
        body.append(element("p", "dialog-copy", `普通盾 ${shields.normal} · 强化盾 ${shields.reinforced} · 概念盾 ${shields.concept}`));
        const statusList = Object.entries(actor.statuses);
        const overflow = Object.entries(actor.status_overflow || {});
        if (statusList.length || overflow.length) {
            heading(body, "当前状态");
            for (const [name, count] of statusList) {
                body.append(element("strong", "", name + " × " + count));
                entries(body, match.catalog.statuses[name]);
            }
            for (const [name, counter] of overflow) {
                body.append(element("p", "dialog-copy", name + "溢出 " + counter.amount + "/" + counter.threshold));
            }
        }
        const abilities = Object.entries(actor.ability_effects || {});
        for (const reserve of actor.reserved_dice || []) {
            body.append(element("p", "dialog-copy", "迎击 · " + reserve.skill + " 第" + reserve.position + "骰，剩余 " + reserve.remaining + " 次"));
        }
        if (abilities.length) {
            heading(body, "能力效果");
            for (const [name, count] of abilities) {
                body.append(element("strong", "", name + " × " + count));
                entries(body, [match.catalog.ability_effects[name]]);
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
            "选择手牌后点击扣置。此后每个置卡窗口最多扣两张，首张扣好后可以提前交权。结束常规置卡后，仍可按机会或技能文字进行特殊置卡。",
            "开牌前由先手方先取得进攻权。每张进攻牌可以指定角色或常规交锋。对手考虑迎击期间，进攻方可以继续出牌。防守方可任选一场待迎击的进攻，用手牌迎击或明确放行。",
            "取得进攻权后仍可处理此前待迎击的牌。双方都结束主动进攻、每场都已就绪后，按进攻编号结算。仍指向常规交锋的进攻会牵走对手的扣牌。随后统一开牌。技能使用时先付个人费，再付通用费。",
            "双方逐骰比拼点点数。攻击骰获胜时命中，攻击骰无对位时单方面攻击。生命归零时判定阵亡，具有免死效果的角色仍可行动。",
            "光点伤害扣除完整度。完整度从正数降到零时触发崩塌，承受原始生命上限一半的真实伤害（向上取整），完整度上限减少 4，再按新上限回满。追加的光点伤害另算一段。",
            "回复前生命已达到当前完整度上限，且此次实际回复了生命，角色立即阵亡。此规则优先于免死。",
            "用置卡机会或牌面许可补入友方空常规交锋，均须有剩余常规交锋额度，置入一张占一次。场内即时进攻默认直接结算，只有牌面明示可迎击时才开放回应。",
            "换卡时换下的牌回手，原费用不退。新牌须自己付费，从第一骰重新使用。",
            "已经对位的骰子在拼点结果产生前消失，会形成空白轮。仅对方取得拼点胜利，消失骰没有拼点结果。",
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
                const label = `${fighter.name} · 生命 ${fighter.max_hp} · 完整度 ${fighter.max_lightcore_hp}`;
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
            const mirrorAllowed = value => match.choices.some(choice => choice.id === value && choice.mirror_allowed);
            start.disabled = duplicate && !mirrorAllowed(selectors[0].value);
            for (const select of selectors) {
                const other = selectors.find(item => item !== select);
                for (const option of select.options) option.disabled = option.value === other.value && !mirrorAllowed(option.value);
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
    setText(field("lightcore"), `完整度 ${actor.lightcore_hp}/${actor.max_lightcore_hp}`);
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
    for (const [name, counter] of Object.entries(actor.status_overflow || {})) {
        statuses.push(name + "溢出 " + counter.amount + "/" + counter.threshold);
    }
    const shieldNames = {normal: "护盾", reinforced: "强化盾", concept: "概念盾"};
    for (const [kind, amount] of Object.entries(actor.shields)) {
        if (amount > 0) statuses.push(shieldNames[kind] + " " + amount);
    }
    const statusesField = field("statuses");
    const abilities = Object.entries(actor.ability_effects || {}).map(([name, count]) =>
        element("span", "status", `能力 · ${name} ${count}次`));
    statusesField.replaceChildren(...statuses.map(label => element("span", "status", label)), ...abilities);
    node.dataset.active = String(choosingCard() && match.active_side === player.side);
    node.disabled = false;
    node.setAttribute("aria-label", "查看" + actor.name + "的角色详情");
}

function currentSlot() {
    const side = match.active_side;
    const duels = match.frame.duels;
    const vacancy = duels.find(slot => slot.sides.some(group => group.side === side && !group.cards.length));
    return vacancy?.number ?? duels.length + 1;
}

function liveDieText(side, number, card, kind) {
    const combat = match.frame.combat;
    if (combat?.duel_number !== number || combat.kind !== kind) return "";
    const active = combat.sides.find(info => info.side === side && info.card_instance_id === card.instance_id);
    const die = active?.die;
    if (!die) return "";
    const parts = ["第 " + active.die_number + " 骰", typeNames[die.type] || die.type];
    if (active.range_deficit) parts.push("远程劣势 " + active.range_deficit);
    if (die.final_score != null) parts.push("最终 " + die.final_score);
    if (die.clash_score != null) parts.push("拼点 " + die.clash_score);
    if (die.result) parts.push(outcomes[die.result] || die.result);
    if (die.win_branch_skipped) parts.push("跳过拼赢分支");
    return parts.join(" · ");
}

function duelSide(side, cards, number, kind, target) {
    const group = element("div", "duel-side " + (side === 1 ? "side-one" : "side-two"));
    if (!cards.length) {
        const waiting = match.mode === "placement" || match.mode === "handoff";
        const label = target || (waiting && kind === "regular" ? "待置卡" : "空位");
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
            const current = liveDieText(side, number, card, kind);
            const label = current || (card.cost + " 费 · " + card.dice.length + " 骰");
            detail.append(element("small", "", label));
            detail.addEventListener("click", () => cardDetails(card));
            group.append(detail);
        }
    }
    return group;
}

function updateWaitText(node, start, end) {
    const seconds = Math.max(0, Math.floor((end - start) / 1000));
    const minutes = Math.floor(seconds / 60);
    const remainder = String(seconds % 60).padStart(2, "0");
    setText(node, minutes + ":" + remainder);
}

function stopResponseTimer() {
    window.clearInterval(responseTimer);
    responseTimer = null;
}

function startResponseTimer() {
    if (document.hidden || !document.querySelector("[data-pending-since]")) return;
    const tick = () => {
        const now = Date.now();
        for (const clock of document.querySelectorAll("[data-pending-since]")) {
            updateWaitText(clock, Number(clock.dataset.pendingSince), now);
        }
    };
    tick();
    responseTimer = window.setInterval(tick, 1000);
}

function renderArena() {
    stopResponseTimer();
    const slots = match.frame.duels.map(slot => ({...slot, kind: "regular"}));
    const placing = match.mode === "placement";
    const pending = placing ? currentSlot() : null;
    if (placing && pending > slots.length) {
        slots.push({number: slots.length + 1, kind: "regular", sides: match.frame.players.map(p => ({side: p.side, cards: []}))});
    }
    for (const slot of [...match.frame.pre_reveal.duels].reverse()) slots.unshift({...slot, kind: "pre_reveal"});
    for (const slot of [...match.frame.special_duels].reverse()) slots.unshift({...slot, kind: "instant"});
    setText(byId("arena-title"), "交锋序列");
    const resolved = match.frame.cards_revealed;
    const note = placing ? "准备第 " + pending + " 交锋" : (resolved ? "常规牌面已公开" : "常规牌面保密");
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
        const early = slot.kind !== "regular";
        const instant = slot.kind === "instant";
        const indexLabel = element("span", "duel-index", (instant ? "即 " : early ? "前 " : "") + String(slot.number).padStart(2, "0"));
        indexLabel.setAttribute("aria-label", (instant ? "即时交锋 " : early ? "开牌前交锋 " : "常规交锋 ") + slot.number);
        if (early) {
            const response = !slot.interceptable ? "直接就绪" : (slot.target.kind === "intercept" ? "已迎击" : "已放行");
            indexLabel.append(element("small", "", slot.ready ? response : "待迎击"));
            const timing = !instant && match.response_times.find(item => item.number === slot.number);
            if (timing) {
                const clock = element("small", "response-time");
                clock.title = "从打出进攻牌到迎击或放行的经过时间";
                if (timing.answered_at_ms == null) clock.dataset.pendingSince = timing.declared_at_ms;
                else updateWaitText(clock, timing.declared_at_ms, timing.answered_at_ms);
                indexLabel.append(clock);
            }
        }
        const target = early ? "目标 · " + targetText(slot.target) : "";
        row.replaceChildren(duelSide(left.side, left.cards, slot.number, slot.kind, left.side !== slot.attacking_side && target), indexLabel,
                            duelSide(right.side, right.cards, slot.number, slot.kind, right.side !== slot.attacking_side && target));
        const combat = match.frame.combat;
        row.dataset.active = String(combat ? combat.kind === slot.kind && slot.number === combat.duel_number
                                           : !early && slot.number === pending);
    }
    while (rail.children.length > slots.length) rail.lastElementChild.remove();
    startResponseTimer();
}

function makeHandCard(card, ownerName) {
    const tile = element("button", "skill-card");
    tile.type = "button";
    tile.dataset.card = card.action_key;
    tile.dataset.form = card.name;
    const head = element("span", "card-head");
    const characteristics = [ownerName, ranges[card.range_level], card.pre_reveal ? "开牌前可出" : ""];
    if (card.borrowed) characteristics.push("取自对手");
    if (card.anytime_play.length) characteristics.push("随时可出");
    if (card.anytime_replace) characteristics.push("随时可换");
    head.append(element("span", "card-owner", characteristics.filter(Boolean).join(" · ")), element("span", "card-cost", card.cost + " 费"));
    const dice = element("span", "card-dice");
    for (const die of card.dice) dice.append(dieRow(die, true));
    tile.append(head, element("strong", "card-name", card.name), dice);
    tile.addEventListener("click", () => {
        if (busy || !choosingCard()) return;
        selection = tile.dataset.card;
        syncSelection();
    });
    return tile;
}

function renderHand(player) {
    const ownHand = player?.hand || [];
    const keepIds = new Set(ownHand.map(card => card.action_key));
    for (const node of [...hand.children]) {
        if (!keepIds.has(node.dataset.card)) node.remove();
    }
    const tiles = new Map([...hand.children].map(node => [node.dataset.card, node]));
    for (const [index, card] of ownHand.entries()) {
        const owner = player.characters.find(actor => actor.id === card.character_id);
        const old = tiles.get(card.action_key);
        const tile = old?.dataset.form === card.name ? old : makeHandCard(card, owner?.name || player.name);
        if (old && tile !== old) old.replaceWith(tile);
        setText(tile.querySelector(".card-name"), card.name + (card.use_restricted ? "（受限）" : ""));
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
    if (match.mode === "special") {
        const available = match.special_options.length > 0;
        byId("primary-btn").disabled = busy || !available;
        const note = available ? "查看可执行的动作并选择目标。" : (match.special_pending ? "当前没有可执行的动作，可交回桌面。" : "当前没有可执行的特殊行动，可返回原阶段。");
        setText(byId("action-note"), note);
        return;
    }
    if (match.mode === "pre_attack" || match.mode === "intercept") {
        const attacking = match.can_end_attack;
        const pending = match.pending_responses.length;
        const legalAttack = match.legal_attack_cards.includes(selection);
        byId("primary-btn").disabled = busy || (attacking ? !legalAttack : !pending);
        const notes = [];
        if (attacking) notes.push(selected && !legalAttack ? "这张手牌不能主动进攻。" : "你持有进攻权。");
        if (pending) notes.push("可处理开牌前交锋 " + match.pending_responses.join("、") + "。");
        setText(byId("action-note"), notes.join(" "));
        return;
    }
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
    const message = match.mode === "timing" ? match.special_timing : lastMessage || note;
    let line = hand.querySelector(".empty-state");
    if (!line || hand.children.length !== 1 || hand.firstElementChild !== line) {
        line = element("p", "empty-state");
        hand.replaceChildren(line);
    }
    setText(line, message);
    setText(byId("action-note"), "");
    const primary = byId("primary-btn");
    const labels = {reveal: "开始交锋", combat: "继续结算", timing: "继续结算", turn_end: "下一回合", finished: "再来一局"};
    setText(primary, labels[match.mode]);
    primary.disabled = busy;
}

function render() {
    const placing = match.mode === "placement";
    const deciding = choosingCard();
    const handoff = handoffMode(match.mode);
    const special = match.mode === "special";
    const specialPanel = special || match.mode === "special_handoff";
    const specialButton = byId("special-btn");
    specialButton.hidden = !match.special_available || (specialPanel && match.special_pending);
    specialButton.disabled = busy;
    setText(specialButton, specialPanel ? "返回原阶段" : "特殊行动");
    const player = team(match.active_side);
    document.documentElement.dataset.viewer = match.frame.viewer_side ?? "public";
    setText(byId("round-number"), String(match.frame.turn).padStart(2, "0"));
    const earlyCombat = match.frame.combat?.kind === "pre_reveal" && match.mode === "combat";
    const declaring = match.mode === "pre_attack" || match.mode === "intercept";
    const phaseName = declaring ? "开牌前置卡" : phases[match.mode];
    setText(byId("phase-name"), earlyCombat ? "开牌前结算" : phaseName);
    for (const p of match.frame.players) updateFighter(p);
    renderArena();
    byId("handoff").hidden = !handoff;
    hand.hidden = handoff;
    byId("actions").hidden = handoff;
    byId("detail-btn").hidden = !deciding;
    byId("pass-btn").hidden = !placing || !match.can_pass;
    byId("end-btn").hidden = !placing && !(declaring && match.can_end_attack);
    const secondSeat = otherSeat();
    byId("handoff-other").hidden = !handoff || secondSeat == null;
    byId("switch-seat").hidden = !(declaring || special) || secondSeat == null;
    byId("switch-seat").disabled = busy;
    const dualRole = declaring && match.can_end_attack && match.pending_responses.length > 0;
    byId("respond-btn").hidden = !dualRole;
    byId("respond-btn").disabled = busy;
    byId("end-btn").disabled = busy;
    byId("pass-btn").disabled = busy;
    byId("new-game").disabled = busy;
    byId("history-toggle").disabled = !match.history.length;
    if (deciding) {
        const primary = special ? "选择特殊行动" : placing ? "扣置所选牌" : (match.can_end_attack ? "指定进攻目标" : "选择待迎击交锋");
        setText(byId("primary-btn"), primary);
        setText(byId("end-btn"), placing ? "结束置卡" : "结束主动进攻");
        if (dualRole) setText(byId("respond-btn"), "处理待迎击（" + match.pending_responses.length + "）");
        renderHand(player);
    } else if (handoff) {
        hand.replaceChildren();
        setText(byId("action-note"), "");
        setText(byId("hand-title"), "交接对局");
        setText(byId("hand-meta"), "");
        const shared = secondSeat != null;
        setText(byId("handoff-title"), match.card_choice ? "请由" + player.name + "选择技能" : match.queued_placement ? "请由" + player.name + "选择交锋" : match.special_pending ? "即时进攻待迎击，由要行动的玩家接手" : shared ? "由要出牌的玩家接手" : "请将屏幕交给" + player.name);
        setText(byId("handoff-action"), "我是" + player.name + "，查看手牌");
        byId("handoff-action").disabled = busy;
        if (shared) {
            setText(byId("handoff-other"), "我是" + team(secondSeat).name + "，查看手牌");
            byId("handoff-other").disabled = busy;
        }
    } else {
        renderPublic();
    }
}

function notice(text) {
    setText(byId("notice"), text);
}

function showState(state, newMatch = false) {
    const previous = match;
    const wasHandoff = handoffMode(previous?.mode);
    const privateSideChanged = previous?.frame.viewer_side !== state.frame.viewer_side;
    if (privateSideChanged || newMatch) {
        hand.replaceChildren();
        closeDialog(true);
    }
    match = state;
    selection = null;
    render();
    if (handoffMode(state.mode)) {
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
    stopResponseTimer();
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
    for (const id of ["detail-btn", "pass-btn", "end-btn", "respond-btn", "switch-seat", "handoff-other", "special-btn"]) byId(id).hidden = true;
    for (const id of ["new-game", "history-toggle", "fighter-1", "fighter-2"]) byId(id).disabled = true;
    setText(byId("primary-btn"), "重新连接");
    byId("primary-btn").disabled = false;
    document.documentElement.dataset.viewer = "public";
}

function lockControls() {
    busy = true;
    document.body.setAttribute("aria-busy", "true");
    for (const id of ["new-game", "primary-btn", "detail-btn", "end-btn", "pass-btn", "handoff-action",
                      "handoff-other", "switch-seat", "respond-btn", "special-btn"]) {
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
    } else if (match.mode === "special") {
        specialDialog();
    } else if (choosingCard()) {
        if (!match.can_end_attack) responseDialog();
        else if (match.legal_attack_cards.includes(selection)) targetDialog();
    } else if (match.mode !== "handoff") {
        send("next");
    }
});
byId("handoff-action").addEventListener("click", event => {
    if (event.detail <= 1 && handoffMode(match?.mode)) send("ready");
});
byId("handoff-other").addEventListener("click", event => {
    if (event.detail <= 1 && handoffMode(match?.mode)) send("ready", {side: otherSeat()});
});
byId("special-btn").addEventListener("click", () => {
    const opened = match.mode === "special" || match.mode === "special_handoff";
    send(opened ? "leave_special" : "open_special");
});
byId("respond-btn").addEventListener("click", responseDialog);
byId("switch-seat").addEventListener("click", () => send("switch_side"));
byId("pass-btn").addEventListener("click", () => send("pass"));
byId("end-btn").addEventListener("click", () => {
    if (match.can_end_attack) { send("end_attack"); return; }
    showDialog("结束本回合置卡？", (body, actions) => {
        body.append(element("p", "dialog-copy", "已扣置的牌保留。你将结束本回合的常规置卡，仍可迎击或按技能执行特殊行动。"));
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
document.addEventListener("visibilitychange", () => {
    stopResponseTimer();
    if (match) startResponseTimer();
});
loadMatch();
