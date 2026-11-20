"use strict";

const byId = id => document.getElementById(id);
const token = new URLSearchParams(location.hash.slice(1)).get("token");
const stations = new Map();
const pollInterval = 1500;
const copyDialog = byId("manual-copy");
let dialogStation = null;
let dialogPacket = null;
let refreshNumber = 0;
let clipboardOwner = null;

function seatName(side) { return side === 1 ? "席位一" : "席位二"; }
function setText(node, message) {
    if (node.textContent !== message) node.textContent = message;
}
function feedback(node, message, error = false) {
    setText(node, message);
    node.dataset.error = String(error);
}
async function deskRequest(method, body) {
    const headers = {"Content-Type": "application/json", Authorization: "Bearer " + token};
    const response = await fetch("/api/desk/" + method, {
        method: "POST", headers, body: JSON.stringify(body), cache: "no-store"
    });
    if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        const error = new Error(detail.error || "房间请求失败。");
        error.status = response.status;
        throw error;
    }
    return response.json();
}

class Station {
    constructor(seat, room) {
        this.side = seat.side;
        this.root = byId("station-template").content.firstElementChild.cloneNode(true);
        this.root.dataset.side = String(this.side);
        const part = selector => this.root.querySelector(selector);
        this.fighter = part(".fighter");
        this.fighter.id = "fighter-" + this.side;
        this.root.setAttribute("aria-labelledby", this.fighter.id);
        this.state = part(".seat-state");
        this.intro = part(".copy-intro");
        this.turn = part(".copy-turn");
        this.packetTools = part(".packet-tools");
        this.recopy = part(".recopy");
        this.show = part(".show-packet");
        this.note = part(".export-note");
        this.reply = part(".reply");
        this.submit = part(".submit");
        this.receipt = part(".receipt");
        this.busy = false;
        this.copyPromise = null;
        this.packet = null;
        this.cursor = null;
        this.packetMessage = "";
        this.packetError = false;
        this.finished = false;
        part(".seat-label").textContent = seatName(this.side);
        this.intro.addEventListener("click", () => this.transfer("intro"));
        this.turn.addEventListener("click", () => this.transfer("turn"));
        this.recopy.addEventListener("click", () => this.transfer());
        this.show.addEventListener("click", () => showPacket(this));
        this.reply.addEventListener("input", () => this.controls());
        part("form").addEventListener("submit", event => { event.preventDefault(); this.sendReply(); });
        this.update(seat, room);
    }

    update(seat, room) {
        // Polls update the status strip; the private text, reply draft and focus stay put.
        this.revision = seat.revision;
        this.finished = room.finished;
        const deciding = seat.has_decision;
        const preparing = !room.started;
        let label = deciding ? "待模型决定" : "等待战场推进";
        if (preparing) label = seat.ready ? "已准备，等待另一席" : "尚未准备";
        if (room.finished) label = "对局已结束";
        this.root.dataset.deciding = String(deciding);
        setText(this.state, label);
        setText(this.fighter, seat.name || seatName(this.side));
        setText(this.turn, room.finished ? "复制终局" : "复制当前局面");
        this.intro.classList.toggle("primary", preparing && !seat.ready);
        this.turn.classList.toggle("primary", !preparing || seat.ready);
        this.controls();
        this.showNote();
    }

    controls() {
        const copyDisabled = this.busy || clipboardOwner !== null;
        this.intro.disabled = copyDisabled || this.finished;
        this.turn.disabled = copyDisabled;
        this.recopy.disabled = copyDisabled;
        this.show.disabled = copyDisabled;
        this.reply.readOnly = this.busy;
        this.submit.disabled = this.busy || !this.reply.value.trim();
        this.packetTools.hidden = !this.packet;
        this.root.setAttribute("aria-busy", String(this.busy || clipboardOwner === this));
    }

    showNote() {
        const expired = this.packet && this.revision > this.packet.revision;
        const warning = expired ? " 此份局面已有更新，行动前请重新复制当前局面。" : "";
        feedback(this.note, this.packetMessage + warning, this.packetError);
    }

    copied(packet) {
        // Opening the fallback never advances the journal; only a successful copy does.
        this.cursor = packet.cursor;
        this.packetMessage = "已复制" + packet.label + "，请发给" + seatName(this.side) + "的模型。";
        this.packetError = false;
        this.showNote();
    }

    async copy(packet) {
        try {
            await navigator.clipboard.writeText(packet.text);
            this.copied(packet);
        } catch {
            this.packetMessage = "浏览器未完成复制。可重试，或选择“显示文本以手动复制”。";
            this.packetError = true;
            this.showNote();
        }
    }

    transfer(kind) {
        if (this.busy || clipboardOwner || (!kind && !this.packet)) return;
        clipboardOwner = this;
        for (const station of stations.values()) station.controls();
        this.copyPromise = this.obtainAndCopy(kind).finally(() => {
            clipboardOwner = null;
            this.copyPromise = null;
            for (const station of stations.values()) station.controls();
        });
    }

    async obtainAndCopy(kind) {
        if (!kind) return this.copy(this.packet);
        feedback(this.note, "正在获取本席提示…");
        try {
            const args = {side: this.side, kind};
            if (this.cursor !== null) args.cursor = this.cursor;
            const packet = await deskRequest("export", args);
            const turnLabel = packet.finished ? "终局" : "当前局面";
            packet.label = kind === "intro" ? "赛前提示" : turnLabel;
            this.packet = packet;
            setText(this.recopy, "重新复制");
            await this.copy(packet);
        } catch (error) {
            this.packetMessage = error.message;
            this.packetError = true;
            this.showNote();
        }
    }

    async sendReply() {
        const reply = this.reply.value.trim();
        if (this.busy || !reply) return;
        this.busy = true;
        this.controls();
        feedback(this.receipt, "正在核对回复…");
        try {
            // Let this seat's own export finish before replacing its saved packet.
            if (this.copyPromise) await this.copyPromise;
            const result = await deskRequest("submit", {side: this.side, reply});
            this.reply.value = "";
            const message = result.duplicate ? "这份回复已处理。" : result.message || "回复已执行。";
            feedback(this.receipt, message);
            const keepNewerPacket = result.duplicate && this.packet && this.packet.reply_to !== result.reply_to;
            // An old receipt shouldn't replace the next prompt that's already been copied.
            if (keepNewerPacket) return;
            if (result.text) {
                this.packet = {...result, label: "规则答复与最新局面"};
                this.packetMessage = "模型请求的规则已备好，请复制给当前模型。";
                this.packetError = false;
                setText(this.recopy, "复制规则答复");
            } else {
                this.packet = null;
                this.packetMessage = "";
                this.packetError = false;
                setText(this.recopy, "重新复制");
            }
            this.showNote();
        } catch (error) {
            const hint = error.status === 409 ? " 请复制最新局面，让该模型重新作答。" : "";
            feedback(this.receipt, error.message + hint, true);
        } finally {
            this.busy = false;
            this.controls();
            refresh();
        }
    }
}

function selectPacketText() {
    const field = byId("packet-text");
    field.focus();
    field.select();
}
function showPacket(station) {
    if (!station.packet) return;
    dialogStation = station;
    dialogPacket = station.packet;
    setText(byId("copy-title"), seatName(station.side) + " · " + dialogPacket.label);
    byId("packet-text").value = dialogPacket.text;
    copyDialog.showModal();
    selectPacketText();
}
byId("select-all").addEventListener("click", selectPacketText);
byId("close-copy").addEventListener("click", () => copyDialog.close());
byId("packet-text").addEventListener("copy", event => {
    const field = event.target;
    const allSelected = field.selectionStart === 0 && field.selectionEnd === field.value.length;
    if (allSelected && dialogPacket) dialogStation.copied(dialogPacket);
});
copyDialog.addEventListener("close", () => {
    byId("packet-text").value = "";
    dialogPacket = null;
    dialogStation = null;
});

function updatePending(pending) {
    const list = byId("pending");
    const kept = new Map(Array.from(list.children, item => [item.dataset.number, item]));
    for (const duel of pending) {
        const number = String(duel.number);
        const item = kept.get(number) || document.createElement("li");
        kept.delete(number);
        const hasTime = Number.isFinite(duel.declared_at_ms);
        const elapsed = Math.max(0, Math.floor((Date.now() - duel.declared_at_ms) / 1000));
        const waiting = hasTime ? "已待迎击 " + elapsed + " 秒" : "待迎击";
        const summary = "开牌前交锋 " + number + " · " + seatName(duel.attacking_side) + "进攻，" + waiting;
        setText(item, summary);
        item.dataset.number = number;
        if (!item.isConnected) list.append(item);
    }
    for (const item of kept.values()) item.remove();
}

function display(room) {
    let phase = room.started ? "第 " + room.turn + " 回合" : "赛前准备";
    if (room.finished) phase = room.winner_side ? seatName(room.winner_side) + "获胜" : "双方平局";
    setText(byId("phase"), phase);
    document.querySelector(".table-clock").hidden = room.finished;
    const single = room.seats.length === 1;
    const guide = single ? "真人玩家用自己的席位链接操作。此页只搬运当前席位。"
        : "你对 AI 时，用自己的席位链接操作，只搬运对方。两名 AI 对战时，分别处理两席的回复。";
    setText(byId("arrangement"), guide);
    const playerLink = byId("player-link");
    if (single) playerLink.href = "/" + location.hash;
    playerLink.hidden = !single;
    for (const seat of room.seats) {
        let station = stations.get(seat.side);
        if (station) station.update(seat, room);
        else {
            station = new Station(seat, room);
            stations.set(seat.side, station);
            byId("stations").append(station.root);
        }
    }
    updatePending(room.pending || []);
}

async function refresh() {
    // A late poll must not replace the status retrieved after a submission.
    const requestNumber = ++refreshNumber;
    try {
        const room = await deskRequest("status", {});
        if (requestNumber !== refreshNumber) return true;
        setText(byId("connection"), "");
        display(room);
        return !room.finished;
    } catch (error) {
        if (requestNumber !== refreshNumber) return true;
        const denied = error.status === 401 || error.status === 403;
        setText(byId("connection"), denied ? "请打开终端给出的搬运台邀请或本席位的搬运台链接。" : "正在重新连接房间。 " + error.message);
        return !denied;
    }
}
async function followRoom() {
    if (await refresh()) setTimeout(followRoom, pollInterval);
}
if (token) followRoom();
else {
    setText(byId("phase"), "需要邀请");
    setText(byId("connection"), "请使用终端给出的搬运台邀请，或从自己的私人席位进入。");
}
