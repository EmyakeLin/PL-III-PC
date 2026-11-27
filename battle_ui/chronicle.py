"""Structured, fog-of-war-safe hierarchical Battle Chronicle & Math Ledger for 《光点计划 III》.

Organizes settled kernel facts and seat actions into a 4-level causal tree:
    Turn -> Block (Phase / Duel) -> Round (Setup / Die Clash / Solo Roll) -> Ledger Item

Key guarantees:
  1. Zero truncation across the entire match (Turn 1 through Final Turn always preserved).
  2. Exact formula attribution for every die roll (base, roll, multiplier, card/die/status bonuses, clash score)
     and every direct damage settlement (base, outgoing, multiplier, pre-shield, shield absorb/erode, HP lost).
  3. Strict Fog-of-War during live play: face-down placements and private draw-bottom choices show card names
     only to their owner until `cards_revealed` (for board placements) or `game.is_over` (post-match full replay).
  4. Rich entity references (`char`, `card`, `status`) so the frontend Chronicle Drawer can pop up full card
     faces and official status rules on hover, filter by turn/category/character, and export clean Markdown.
"""

from entry.effects import GRADE_NAMES
from models.dice import TYPE_NAMES, dice_value_range, DiceLevel


SERIES_NAMES = {
    "regular": "常规交锋",
    "pre_reveal": "开牌前交锋",
    "instant": "即时交锋",
}

SHIELD_NAMES = {
    "shield": "普通盾",
    "normal": "普通盾",
    "reinforced_shield": "强化盾",
    "reinforced": "强化盾",
    "concept_shield": "概念盾",
    "concept": "概念盾",
}

RESULT_NAMES = {
    "win": "胜",
    "lose": "负",
    "draw": "平",
    "solo": "单方面",
    "skip": "跳过",
}


def _fmt_num(val):
    if isinstance(val, float) and val.is_integer():
        return str(int(val))
    if isinstance(val, float):
        return f"{val:g}"
    return str(val)


def format_die_formula(detail):
    """Build a crisp, exact arithmetic explanation of a die's rolled -> final -> clash score."""
    dtype = detail.get("die_type", "blank")
    if dtype == "skip":
        return "SKIP（跳过本轮）", "SKIP"
    roll_max = detail.get("roll_max") or 6
    printed_lvl = detail.get("printed_level")
    eff_lvl = detail.get("level")
    printed_max = dice_value_range.get(DiceLevel(printed_lvl), (1, roll_max))[1] if printed_lvl else roll_max
    lvl_note = f"（原1~{printed_max}）" if printed_max != roll_max else ""
    range_label = f"1~{roll_max}{lvl_note}"

    base = detail.get("base_value", 0) or 0
    rolled = detail.get("rolled_value")
    mult = detail.get("multiplier", 1)
    die_f = detail.get("die_final_bonus", 0) or 0
    card_f = detail.get("card_final_bonus", 0) or 0
    status_f = detail.get("status_final_bonus", 0) or 0
    final_score = detail.get("final_score")
    clash_score = detail.get("clash_score")
    formula = detail.get("formula") or "+"

    if rolled is None:
        return "未投掷", range_label

    terms = []
    if base:
        terms.append(f"基础{_fmt_num(base)}")
    terms.append(f"掷{_fmt_num(rolled)}")
    core = " + ".join(terms)
    if formula not in ("+", "-", "(b + v) * m + f"):
        core = f"公式[{formula}](b={_fmt_num(base)},v={_fmt_num(rolled)},m={_fmt_num(mult)},f={_fmt_num(die_f)})"
        die_f = 0
    elif mult != 1:
        core = f"({core})×{_fmt_num(mult)}"

    eff_f = detail.get("final_effect_bonus", 0)
    bonuses = []
    if die_f:
        bonuses.append(f"骰修正{die_f:+d}" if isinstance(die_f, int) else f"骰修正{_fmt_num(die_f)}")
    if card_f:
        bonuses.append(f"牌修正{card_f:+d}" if isinstance(card_f, int) else f"牌修正{_fmt_num(card_f)}")
    if status_f:
        bonuses.append(f"状态{status_f:+d}" if isinstance(status_f, int) else f"状态{_fmt_num(status_f)}")
    if eff_f:
        bonuses.append(f"效果修正{eff_f:+d}" if isinstance(eff_f, int) else f"效果修正{_fmt_num(eff_f)}")

    expr = core + ("".join(f" {b}" for b in bonuses) if bonuses else "")
    if final_score is not None:
        expr += f" = 最终{_fmt_num(final_score)}"
    if clash_score is not None and clash_score != final_score:
        diff = clash_score - (final_score or 0)
        sign = f"+{_fmt_num(diff)}" if diff >= 0 else _fmt_num(diff)
        expr += f" → 拼点{_fmt_num(clash_score)}（拼点修正{sign}）"
    return expr, range_label


GRADE_LABELS = {
    "normal": "普通伤害",
    "pierce": "穿甲伤害",
    "piercing": "穿甲伤害",
    "concept": "超穿甲伤害",
}


def _grade_label(grade):
    if grade in GRADE_LABELS:
        return GRADE_LABELS[grade]
    base = GRADE_NAMES.get(grade, str(grade or "普通"))
    return base if str(base).endswith("伤害") else f"{base}伤害"


def format_damage_formula(*, base_amount=None, outgoing=None, multiplier=1, incoming=0, grade="normal",
                          absorbed=None, eroded=None, borrowed_absorbed=None, hp_lost=0, hp_after=0, max_hp=0):
    """Build a step-by-step damage & shield absorption/erosion audit line."""
    grade_label = _grade_label(grade)
    steps = []
    if base_amount is not None and outgoing is not None and base_amount != outgoing:
        steps.append(f"原始{_fmt_num(base_amount)} → 攻方修正后{_fmt_num(outgoing)}")
    elif outgoing is not None:
        steps.append(f"攻方{_fmt_num(outgoing)}")
    elif base_amount is not None:
        steps.append(f"原始{_fmt_num(base_amount)}")

    if multiplier is not None and multiplier != 1:
        steps.append(f"倍率×{_fmt_num(multiplier)}")
    steps.append(f"入盾前{_fmt_num(incoming)}（{grade_label}）")

    shield_bits = []
    for key, label in (("reinforced_shield", "强化盾"), ("shield", "普通盾"), ("concept_shield", "概念盾"),
                       ("reinforced", "强化盾"), ("normal", "普通盾"), ("concept", "概念盾")):
        val = (absorbed or {}).get(key, 0)
        if val:
            shield_bits.append(f"{label}抵消{_fmt_num(val)}")
    for item in borrowed_absorbed or ():
        b_label = SHIELD_NAMES.get(item.get("field"), "护盾")
        if item.get("blocked"):
            shield_bits.append(f"{item.get('holder', '')}{b_label}代抵{_fmt_num(item['blocked'])}")
    for key, label in (("reinforced_shield", "强化盾"), ("shield", "普通盾"),
                       ("reinforced", "强化盾"), ("normal", "普通盾")):
        val = (eroded or {}).get(key, 0)
        if val:
            shield_bits.append(f"{label}磨损{_fmt_num(val)}")
    if shield_bits:
        steps.append(" / ".join(shield_bits))

    steps.append(f"实扣生命 {_fmt_num(hp_lost)}（剩余 {_fmt_num(hp_after)}/{_fmt_num(max_hp)}）")
    return " → ".join(steps)


class BattleChronicle:
    """Live hierarchical battle ledger subscribed to `game.context.observe_facts()`."""

    def __init__(self, game):
        self._game = game
        self._pending = game.context.observe_facts()
        self._seq = 0
        self._turns = []
        self._turn_by_num = {}
        self._current_turn = None
        self._current_block = None
        self._current_round = None
        self._duel_round_counter = 0
        self._speed_rolls_buf = {}
        self._speed_teams_buf = []
        self._pending_damage_settled = []
        self._pending_health_events = []
        self._pending_shield_balance = None
        self._pending_status_balance = None
        self._last_status_fact = None
        self._turn_revealed = {}
        self._char_index = {}
        self._card_index = {}

    def _refresh_indices(self):
        for p in self._game.players:
            for c in p.characters:
                self._char_index[c.combat_name] = (c.id, c.name, p.side)
                self._char_index[c.name] = (c.id, c.name, p.side)
                self._char_index[c.id] = (c.id, c.name, p.side)
                for sk in c.skill_data:
                    self._card_index[sk["name"]] = (sk["id"], sk["name"], p.side, c.id)
                    self._card_index[sk["id"]] = (sk["id"], sk["name"], p.side, c.id)
                    for fm in (sk.get("forms") or {}).values():
                        if "name" in fm:
                            self._card_index[fm["name"]] = (sk["id"], fm["name"], p.side, c.id)

    def _char_entity(self, name_or_id, fallback_side=None):
        if not name_or_id:
            return None
        if name_or_id not in self._char_index:
            self._refresh_indices()
        info = self._char_index.get(name_or_id)
        if info:
            cid, cname, cside = info
            return {"kind": "char", "id": cid, "name": cname, "side": cside}
        return {"kind": "char", "id": str(name_or_id), "name": str(name_or_id), "side": fallback_side}

    def _card_entity(self, card_name=None, card_id=None, side=None):
        key = card_id or card_name
        if not key:
            return None
        if key not in self._card_index:
            self._refresh_indices()
        info = self._card_index.get(card_id) or self._card_index.get(card_name)
        if info:
            cid, cname, cside, owner_id = info
            return {
                "kind": "card",
                "id": cid,
                "name": card_name or cname,
                "side": side or cside,
                "character_id": owner_id,
            }
        return {"kind": "card", "id": str(card_id or card_name), "name": str(card_name or card_id), "side": side}

    @staticmethod
    def _status_entity(status_name):
        if not status_name:
            return None
        return {"kind": "status", "id": status_name, "name": status_name, "side": None}

    def _ensure_turn(self, turn_num=None):
        num = turn_num if turn_num is not None else max(1, self._game.turn_number or 1)
        if num in self._turn_by_num:
            self._current_turn = self._turn_by_num[num]
            return self._current_turn
        turn_obj = {
            "turn": num,
            "first_side": None,
            "first_player": None,
            "speed_attempts": [],
            "stats": {"damage_by_side": {"1": 0, "2": 0}, "deaths": [], "collapses": []},
            "blocks": [],
        }
        self._turns.append(turn_obj)
        self._turn_by_num[num] = turn_obj
        self._current_turn = turn_obj
        self._current_block = None
        self._current_round = None
        return turn_obj

    def _ensure_phase_block(self, phase, title):
        turn = self._ensure_turn()
        if (
            self._current_block is not None
            and self._current_block["kind"] == "phase"
            and self._current_block["phase"] == phase
        ):
            return self._current_block
        block = {
            "id": f"T{turn['turn']}:phase:{phase}:{len(turn['blocks']) + 1}",
            "kind": "phase",
            "phase": phase,
            "title": title,
            "duel_kind": None,
            "duel_number": None,
            "matchup": {},
            "summary": {"rounds": 0, "hp_delta": {"1": 0, "2": 0}, "highlights": []},
            "rounds": [],
        }
        turn["blocks"].append(block)
        self._current_block = block
        self._current_round = None
        return block

    def _open_duel_block(self, duel_kind, duel_number):
        turn = self._ensure_turn()
        label = f"{SERIES_NAMES.get(duel_kind, '交锋')} {duel_number}"
        block = {
            "id": f"T{turn['turn']}:{duel_kind}:{duel_number}:{len(turn['blocks']) + 1}",
            "kind": "duel",
            "phase": "combat",
            "title": label,
            "duel_kind": duel_kind,
            "duel_number": duel_number,
            "matchup": {},
            "summary": {"rounds": 0, "hp_delta": {"1": 0, "2": 0}, "highlights": []},
            "rounds": [],
        }
        turn["blocks"].append(block)
        self._current_block = block
        self._current_round = None
        self._duel_round_counter = 0
        return block

    def _ensure_round(self, kind="general", label=None):
        block = self._current_block or self._ensure_phase_block("turn_start", "回合开始")
        if self._current_round is not None and kind == "general":
            return self._current_round
        if kind in ("clash", "solo", "skip"):
            self._duel_round_counter += 1
            r_num = self._duel_round_counter
            block["summary"]["rounds"] = max(block["summary"]["rounds"], r_num)
            r_label = label or f"第 {r_num} 轮"
        else:
            r_num = 0
            if block["rounds"] and block["rounds"][-1]["kind"] == kind:
                self._current_round = block["rounds"][-1]
                return self._current_round
            r_label = label or ("用牌与交锋前结算" if block["kind"] == "duel" else "")
        rnd = {
            "round": r_num,
            "kind": kind,
            "label": r_label,
            "rolls": [],
            "target_name": None,
            "items": [],
        }
        block["rounds"].append(rnd)
        self._current_round = rnd
        return rnd

    def _add_item(self, category, text, *, side=None, formula=None, entities=None,
                  private_side=None, reveal_on_cards_revealed=False,
                  redacted_text=None, redacted_entities=None,
                  reveal_text=None, reveal_entities=None,
                  card_id=None, instance_id=None):
        self._seq += 1
        rnd = self._ensure_round("general")
        ents = [e for e in (entities or ()) if e is not None]
        rnd["items"].append({
            "seq": self._seq,
            "category": category,
            "side": side,
            "text": text,
            "formula": formula,
            "entities": ents,
            "private_side": private_side,
            "reveal_on_cards_revealed": bool(reveal_on_cards_revealed),
            "unlocked_at_reveal": False,
            "card_id": card_id,
            "instance_id": instance_id,
            "redacted_text": redacted_text,
            "redacted_entities": [e for e in (redacted_entities or ()) if e is not None] if redacted_entities is not None else [],
            "reveal_text": reveal_text,
            "reveal_entities": [e for e in (reveal_entities or ()) if e is not None] if reveal_entities is not None else None,
        })

    def _mark_hidden_withdrawn(self, side, *, instance_id=None, card_id=None):
        """Prevent a pre-reveal replaced/withdrawn hidden card from unlocking on cards_revealed."""
        turn = self._current_turn
        if not turn:
            return
        for block in reversed(turn["blocks"]):
            for rnd in reversed(block["rounds"]):
                for it in reversed(rnd["items"]):
                    if it.get("private_side") != side or not it.get("reveal_on_cards_revealed"):
                        continue
                    if instance_id is not None and it.get("instance_id") == instance_id:
                        it["reveal_on_cards_revealed"] = False
                        return
                    if instance_id is None and card_id is not None and it.get("card_id") == card_id:
                        it["reveal_on_cards_revealed"] = False
                        return

    def _unlock_revealed_turn_items(self, turn):
        for block in turn["blocks"]:
            for rnd in block["rounds"]:
                for it in rnd["items"]:
                    if it.get("reveal_on_cards_revealed"):
                        it["unlocked_at_reveal"] = True

    def record_action(self, kind, *, side, actor_id=None, actor_name=None, card_id=None, card_name=None,
                      cost=None, duel_number=None, face_up=False, count=None, card_names=None,
                      instance_id=None):
        """Record seat-level actions (e.g. face-down placement, draw-bottom) with fog-of-war metadata."""
        self.flush()
        p_obj = next((p for p in self._game.players if p.side == side), None)
        p_name = p_obj.name if p_obj else f"席位 {side}"
        if kind == "draw_bottom":
            self._ensure_phase_block("turn_start", "回合开始与调度")
            names_str = "、".join(f"「{n}」" for n in (card_names or ()))
            ents = [self._card_entity(card_name=n, side=side) for n in (card_names or ())]
            self._add_item(
                "card",
                f"{p_name} 看顶选底：将 {names_str} 置入牌堆底。",
                side=side,
                entities=ents,
                private_side=side,
                reveal_on_cards_revealed=False,
                redacted_text=f"{p_name} 完成看顶选底（置底 {count or len(card_names or ())} 张）。",
                redacted_entities=[],
            )
        elif kind in ("place", "place_rear"):
            self._ensure_phase_block("placement", "常规置卡与调度")
            lane_str = "后置槽" if kind == "place_rear" else ""
            slot_str = f"常规交锋 {duel_number}{' · ' + lane_str if lane_str else ''}"
            ch_ent = self._char_entity(actor_id or actor_name, fallback_side=side)
            cd_ent = self._card_entity(card_name=card_name, card_id=card_id, side=side)
            cost_str = f"（{cost} 费）" if cost is not None else ""
            if face_up:
                self._add_item(
                    "card",
                    f"{actor_name or p_name} 明置「{card_name}」{cost_str} → {slot_str}。",
                    side=side,
                    entities=[ch_ent, cd_ent],
                )
            else:
                self._add_item(
                    "card",
                    f"{actor_name or p_name} 扣置「{card_name}」{cost_str} → {slot_str}。",
                    side=side,
                    entities=[ch_ent, cd_ent],
                    private_side=side,
                    reveal_on_cards_revealed=True,
                    redacted_text=f"{actor_name or p_name} 在 {slot_str} 扣置了 1 张技能。",
                    redacted_entities=[ch_ent],
                    card_id=card_id,
                    instance_id=instance_id,
                )
        elif kind == "concede":
            self._add_item("key", f"{p_name} 投子认输。", side=side)

    def _flush_pending_shield(self):
        bal = self._pending_shield_balance
        self._pending_shield_balance = None
        if not bal:
            return
        tgt_name = bal.get("character_name") or "目标"
        tgt_side = bal.get("side")
        tgt_ent = self._char_entity(bal.get("character_id") or tgt_name, fallback_side=tgt_side)
        sh_label = SHIELD_NAMES.get(bal.get("field"), bal.get("field", "护盾"))
        self._add_item(
            "status",
            f"{tgt_name} {sh_label} {_fmt_num(bal.get('before', 0))} → {_fmt_num(bal.get('after', 0))}。",
            side=tgt_side,
            entities=[tgt_ent],
        )

    def _flush_pending_status_balance(self):
        bal = self._pending_status_balance
        self._pending_status_balance = None
        if not bal:
            return
        tgt_name = bal.get("character_name") or "目标"
        tgt_side = bal.get("side")
        st_name = bal.get("status")
        old, new = bal.get("before", 0), bal.get("after", 0)
        tgt_ent = self._char_entity(bal.get("character_id") or tgt_name, fallback_side=tgt_side)
        st_ent = self._status_entity(st_name)
        if old and new == 0:
            msg = f"{tgt_name} 清空 {old} 层 {st_name}。"
        else:
            delta = new - old
            sign = f"+{delta}" if delta >= 0 else str(delta)
            msg = f"{tgt_name} {st_name} {sign} → {new} 层。"
        self._add_item("status", msg, side=tgt_side, entities=[tgt_ent, st_ent])

    def _flush_pending_health_events(self):
        while self._pending_health_events:
            ev_kind, bal = self._pending_health_events.pop(0)
            tgt_name = bal.get("character_name") or "目标"
            tgt_side = bal.get("side")
            tgt_ent = self._char_entity(bal.get("character_id") or tgt_name, fallback_side=tgt_side)
            amt = bal.get("amount", 0)
            if ev_kind == "lost":
                if self._current_block and tgt_side in (1, 2):
                    self._current_block["summary"]["hp_delta"][str(tgt_side)] -= amt
                self._add_item(
                    "damage",
                    f"{tgt_name} 失去 {_fmt_num(amt)} 点生命（剩余 {_fmt_num(bal.get('hp', 0))}/{_fmt_num(bal.get('maximum', 0))}）。",
                    side=tgt_side,
                    entities=[tgt_ent],
                )
            else:
                if self._current_block and tgt_side in (1, 2):
                    self._current_block["summary"]["hp_delta"][str(tgt_side)] += amt
                self._add_item(
                    "status",
                    f"{tgt_name} 恢复 {_fmt_num(amt)} 点生命（当前 {_fmt_num(bal.get('hp', 0))}/{_fmt_num(bal.get('maximum', 0))}）。",
                    side=tgt_side,
                    entities=[tgt_ent],
                )

    def _flush_pending_buffers(self):
        self._flush_pending_shield()
        self._flush_pending_status_balance()
        self._flush_all_pending_damage_settled()
        self._flush_pending_health_events()
        self._last_status_fact = None

    def flush(self):
        while self._pending:
            kind, data = self._pending.popleft()
            self._project_fact(kind, data)
        self._flush_pending_buffers()

    def _project_fact(self, kind, data):
        if kind != "shield_changed" and kind != "shield_balance" and self._pending_shield_balance is not None:
            self._flush_pending_shield()
        if kind != "status_cleared" and kind != "status_balance" and self._pending_status_balance is not None:
            self._flush_pending_status_balance()
        if kind != "status_balance":
            self._last_status_fact = None
        if kind in ("turn_opened", "turn_started", "turn_ended", "duel_started",
                    "clash_scored", "solo_attack", "round_skipped", "cards_revealed", "empty_board"):
            self._flush_pending_buffers()
        if kind == "turn_opened":
            self._ensure_turn(data["number"])
            self._ensure_phase_block("turn_start", "回合开始与速度投掷")
            self._speed_rolls_buf.clear()
            self._speed_teams_buf.clear()
            return
        if kind == "turn_started":
            self._ensure_turn(data["turn"])
            self._ensure_phase_block("turn_start", "回合开始与速度投掷")
            return
        if kind == "initiative_die":
            mods = data.get("modifiers") or {}
            self._speed_rolls_buf.setdefault(data["side"], []).append({
                "character_id": data["character_id"],
                "name": data["character_name"],
                "raw": data["raw"],
                "haste": mods.get("迅捷", 0),
                "bind": mods.get("束缚", 0),
                "speed": data["speed"],
            })
            return
        if kind == "team_speed":
            side = data["side"]
            self._speed_teams_buf.append({
                "side": side,
                "team_speed": data["speed"],
                "dropped_id": data.get("dropped"),
                "rolls": self._speed_rolls_buf.pop(side, []),
            })
            return
        if kind in ("initiative", "speed_tied"):
            turn = self._ensure_turn()
            self._ensure_phase_block("turn_start", "回合开始与速度投掷")
            attempt_no = len(turn["speed_attempts"]) + 1
            tied = kind == "speed_tied"
            winner_side = None if tied else data.get("side")
            sides_map = {str(item["side"]): item for item in self._speed_teams_buf}
            self._speed_teams_buf = []
            turn["speed_attempts"].append({
                "attempt": attempt_no,
                "tied": tied,
                "winner_side": winner_side,
                "sides": sides_map,
            })
            parts = []
            for s_key in ("1", "2"):
                s_info = sides_map.get(s_key)
                if not s_info:
                    continue
                r_strs = []
                for r in s_info["rolls"]:
                    mod_bits = []
                    if r["haste"]:
                        mod_bits.append(f"+迅捷{r['haste']}")
                    if r["bind"]:
                        mod_bits.append(f"-束缚{r['bind']}")
                    drop_tag = " [最低舍去]" if s_info.get("dropped_id") == r["character_id"] else ""
                    m_str = f"({'原' + str(r['raw']) + ''.join(mod_bits)})" if mod_bits else ""
                    r_strs.append(f"{r['name']} {r['speed']}{m_str}{drop_tag}")
                p_label = "先手方" if str(winner_side) == s_key else f"P{s_key}"
                parts.append(f"P{s_key} 阵营速 {_fmt_num(s_info['team_speed'])}〔{'、'.join(r_strs)}〕")
            if tied:
                self._add_item("combat", f"速度投掷（第 {attempt_no} 次）平局重掷", formula="  |  ".join(parts))
            else:
                turn["first_side"] = winner_side
                turn["first_player"] = data.get("player")
                self._add_item(
                    "combat",
                    f"速度定先：{data.get('player', f'席位 {winner_side}')} 取得先手",
                    side=winner_side,
                    formula="  |  ".join(parts),
                )
            return

        if kind == "cards_drawn":
            if data.get("count", 0) > 0:
                p = next((pl for pl in self._game.players if pl.side == data["side"]), None)
                p_name = p.name if p else f"P{data['side']}"
                self._add_item("card", f"{p_name} 抽取 {data['count']} 张牌。", side=data["side"])
            return

        if kind == "turn_budget":
            p = next((pl for pl in self._game.players if pl.side == data["side"]), None)
            p_name = p.name if p else f"P{data['side']}"
            pers = "、".join(f"{cid} {amt}" for cid, amt in (data.get("personal") or ()) if amt)
            self._add_item(
                "card",
                f"{p_name} 费用回补：通用费 {data['common']}" + (f"（个人费 {len(data.get('personal') or ())} 人就绪）" if pers else "") + "。",
                side=data["side"],
            )
            return

        if kind == "attack_declared":
            series_key = data["series"]
            s_name = SERIES_NAMES.get(series_key, series_key)
            if series_key == "pre_reveal":
                self._ensure_phase_block("pre_reveal", "开牌前声明与迎击")
            duel_idx = data.get("duel_index")
            tgt = data.get("target") or (f"常规交锋 {duel_idx + 1}" if isinstance(duel_idx, int) else "未知目标")
            p_side = next((pl.side for pl in self._game.players if pl.name == data.get("player")), None)
            cd_ent = self._card_entity(card_name=data.get("card"), side=p_side)
            tgt_ent = self._char_entity(data.get("target")) if data.get("target") else None
            self._add_item(
                "card",
                f"{s_name} {data['number']}：{data['player']} 声明「{data['card']}」→ {tgt}。",
                side=p_side,
                entities=[cd_ent, tgt_ent],
            )
            return

        if kind in ("intercepted", "skill_intercept", "reserved_intercept"):
            if kind == "intercepted":
                s_name = SERIES_NAMES.get(data["series"], data["series"])
                p_side = next((pl.side for pl in self._game.players if pl.name == data.get("player")), None)
                cd_ent = self._card_entity(card_name=data.get("card"), side=p_side)
                self._add_item(
                    "card",
                    f"{data['player']} 以「{data['card']}」迎击 {s_name} {data['number']}。",
                    side=p_side,
                    entities=[cd_ent],
                )
            else:
                tgt_ent = self._char_entity(data.get("target"))
                side = tgt_ent["side"] if tgt_ent else None
                cd_ent = self._card_entity(card_name=data.get("card"), side=side)
                tag = "后备骰" if kind == "reserved_intercept" else "技能"
                pos = data.get("position")
                pos_str = f"第 {pos} 骰" if pos else ""
                self._add_item(
                    "card",
                    f"{data['target']} 以{tag}「{data['card']}」{pos_str}迎击。",
                    side=side,
                    entities=[tgt_ent, cd_ent],
                )
            return

        if kind == "passed_intercept":
            p_side = next((pl.side for pl in self._game.players if pl.name == data.get("player")), None)
            self._add_item("card", f"{data['player']} 放行即时交锋 {data['number']}。", side=p_side)
            return

        if kind in ("cards_revealed", "empty_board"):
            turn = self._ensure_turn()
            self._turn_revealed[turn["turn"]] = True
            self._unlock_revealed_turn_items(turn)
            self._ensure_phase_block("reveal", "统一开牌")
            if kind == "empty_board":
                self._add_item("card", "双方本回合均未置入常规交锋牌。")
            else:
                self._add_item("card", "双方公开全部常规交锋置牌。")
            return

        if kind == "slot_revealed":
            self._ensure_phase_block("reveal", "统一开牌")
            ents = []
            parts = []
            for p_name, cards in data.get("sides", ()):
                p_side = next((pl.side for pl in self._game.players if pl.name == p_name), None)
                for cn in cards:
                    ents.append(self._card_entity(card_name=cn, side=p_side))
                parts.append(f"{p_name}：{'、'.join(f'「{c}」' for c in cards) if cards else '空'}")
            self._add_item("card", f"常规交锋 {data['number']} 开牌 —— {'  |  '.join(parts)}", entities=ents)
            return

        if kind == "duel_started":
            self._open_duel_block(data["series"], data["number"])
            self._ensure_round("setup", "交锋开始与用牌")
            return

        if kind == "duel_skipped":
            if self._current_block and self._current_block["kind"] == "duel":
                self._current_block["summary"]["highlights"].append("交锋跳过")
            self._add_item("combat", "进攻牌或目标已离场，本场交锋跳过。")
            return

        if kind == "card_pulled":
            cd_ent = self._card_entity(card_name=data.get("card"))
            self._add_item(
                "card",
                f"常规交锋 {data['number']} 的「{data['card']}」被牵制入场。",
                entities=[cd_ent],
            )
            return

        if kind == "range_advantage":
            c1 = self._card_entity(card_name=data.get("card"))
            c2 = self._card_entity(card_name=data.get("opposing"))
            self._add_item(
                "combat",
                f"远程优势：「{data['card']}」压制「{data['opposing']}」{data['amount']} 级。",
                entities=[c1, c2],
            )
            return

        if kind == "skill_used":
            ch_ent = self._char_entity(data.get("actor"))
            side = ch_ent["side"] if ch_ent else None
            cd_ent = self._card_entity(card_name=data.get("card"), side=side)
            if self._current_block and self._current_block["kind"] == "duel" and side:
                self._current_block["matchup"][str(side)] = {
                    "character_id": ch_ent["id"] if ch_ent else None,
                    "character_name": data.get("actor"),
                    "card_id": cd_ent["id"] if cd_ent else None,
                    "card_name": data.get("card"),
                    "cost": data.get("cost"),
                    "skipped": False,
                }
            self._add_item(
                "card",
                f"{data['actor']} 发动「{data['card']}」（牌面 {data['cost']} 费）。",
                side=side,
                entities=[ch_ent, cd_ent],
            )
            return

        if kind == "skill_payment":
            side = data.get("side")
            ch_ent = self._char_entity(data.get("character_id"), fallback_side=side)
            if not data.get("paid", True):
                return
            parts = []
            if data.get("personal_paid"):
                parts.append(f"个人费 {data['personal_paid']}")
            if data.get("common_paid"):
                parts.append(f"通用费 {data['common_paid']}")
            if res := data.get("resource_paid"):
                if isinstance(res, dict) and res.get("status"):
                    parts.append(f"{res['status']} {res.get('amount', 0)}")
            if parts:
                self._add_item(
                    "card",
                    f"费用支付：{' + '.join(parts)}。",
                    side=side,
                    entities=[ch_ent],
                )
            elif data.get("prepaid"):
                self._add_item(
                    "card",
                    "费用已预付。",
                    side=side,
                    entities=[ch_ent],
                )
            return

        if kind == "discount_used":
            cd_ent = self._card_entity(card_name=data.get("card"))
            self._add_item(
                "card",
                f"费用减免：「{data['card']}」减免 {data['discount']} 费，实付 {data['paid']} 费。",
                entities=[cd_ent],
            )
            return

        if kind == "skill_unpaid":
            ch_ent = self._char_entity(data.get("actor"))
            side = ch_ent["side"] if ch_ent else None
            cd_ent = self._card_entity(card_name=data.get("card"), side=side)
            if self._current_block and self._current_block["kind"] == "duel" and side:
                self._current_block["matchup"][str(side)] = {
                    "character_id": ch_ent["id"] if ch_ent else None,
                    "character_name": data.get("actor"),
                    "card_id": cd_ent["id"] if cd_ent else None,
                    "card_name": data.get("card"),
                    "cost": None,
                    "skipped": True,
                }
            self._add_item(
                "card",
                f"{data['actor']} 跳过「{data['card']}」（{data.get('reason', '未能支付费用')}）。",
                side=side,
                entities=[ch_ent, cd_ent],
            )
            return

        if kind == "die_unpaid":
            cd_ent = self._card_entity(card_name=data.get("card"))
            self._add_item(
                "combat",
                f"「{data['card']}」第 {data['position']} 骰未付足用骰消耗，略过此骰。",
                entities=[cd_ent],
            )
            return

        if kind == "round_skipped":
            reason_map = {
                "printed": "SKIP 骰跳过本轮。",
                "passive": "双方均为防御骰，本轮跳过拼点。",
                "effect": "受效果影响跳过本轮，双方均不判胜负。",
            }
            rnd = self._ensure_round("skip")
            self._add_item("combat", reason_map.get(data.get("reason"), "本轮跳过。"))
            return

        if kind == "clash_scored":
            rnd = self._ensure_round("clash")
            details = data.get("details")
            ents = []
            summary_parts = []
            if details:
                for d in details:
                    formula_str, range_label = format_die_formula(d)
                    res_label = RESULT_NAMES.get(d.get("result"), "")
                    if d.get("win_branch_skipped"):
                        res_label += "·受压制跳分支"
                    lane_prefix = "后置·" if d.get("lane") == "rear" else ""
                    repeat_suffix = "（重投）" if d.get("is_repeat") else ""
                    rnd["rolls"].append({
                        "side": d["side"],
                        "lane": d["lane"],
                        "character_id": d["character_id"],
                        "character_name": d["character_name"],
                        "card_id": d["card_id"],
                        "card_name": d["card_name"],
                        "position": d["position"],
                        "is_repeat": d["is_repeat"],
                        "die_type": d["die_type"],
                        "die_label": TYPE_NAMES.get(d["die_type"], d["die_type"]),
                        "range_label": range_label,
                        "formula_text": formula_str,
                        "rolled_value": d["rolled_value"],
                        "final_score": d["final_score"],
                        "clash_score": d["clash_score"],
                        "result": d["result"],
                        "win_branch_skipped": d["win_branch_skipped"],
                    })
                    ents.append(self._char_entity(d["character_id"], fallback_side=d["side"]))
                    ents.append(self._card_entity(card_name=d["card_name"], card_id=d["card_id"], side=d["side"]))
                    shown_score = d["clash_score"] if d["clash_score"] is not None else d["final_score"]
                    summary_parts.append(
                        f"{d['character_name']} {lane_prefix}{TYPE_NAMES.get(d['die_type'], d['die_type'])}{repeat_suffix} "
                        f"{_fmt_num(shown_score)}〔{res_label}〕"
                    )
                formula_lines = "  |  ".join(
                    f"P{r['side']} {r['character_name']}({r['die_label']} {r['range_label']})：{r['formula_text']}"
                    for r in rnd["rolls"]
                )
                self._add_item("combat", "拼点对决：" + "  vs  ".join(summary_parts), formula=formula_lines, entities=ents)
            else:
                # Fallback if legacy tuple only
                parts = [
                    f"{name} {TYPE_NAMES.get(dt, dt)} 最终{fin}→拼点{sc}（{RESULT_NAMES.get(res, res)}）"
                    for name, dt, fin, sc, res, _ in data.get("sides", ())
                ]
                self._add_item("combat", "拼点对决：" + "  vs  ".join(parts))
            return

        if kind == "solo_attack":
            rnd = self._ensure_round("solo")
            rnd["target_name"] = data.get("target")
            d = data.get("detail")
            tgt_ent = self._char_entity(data.get("target_id") or data.get("target"), fallback_side=data.get("target_side"))
            if d:
                formula_str, range_label = format_die_formula(d)
                repeat_suffix = "（重投）" if d.get("is_repeat") else ""
                rnd["rolls"].append({
                    "side": d["side"],
                    "lane": d["lane"],
                    "character_id": d["character_id"],
                    "character_name": d["character_name"],
                    "card_id": d["card_id"],
                    "card_name": d["card_name"],
                    "position": d["position"],
                    "is_repeat": d["is_repeat"],
                    "die_type": d["die_type"],
                    "die_label": TYPE_NAMES.get(d["die_type"], d["die_type"]),
                    "range_label": range_label,
                    "formula_text": formula_str,
                    "rolled_value": d["rolled_value"],
                    "final_score": d["final_score"],
                    "clash_score": d["clash_score"],
                    "result": "solo",
                    "win_branch_skipped": False,
                })
                ch_ent = self._char_entity(d["character_id"], fallback_side=d["side"])
                cd_ent = self._card_entity(card_name=d["card_name"], card_id=d["card_id"], side=d["side"])
                self._add_item(
                    "combat",
                    f"单方面进攻：{d['character_name']}「{d['card_name']}」第{d['position']}骰{repeat_suffix} → {data['target']}",
                    side=d["side"],
                    formula=f"{TYPE_NAMES.get(d['die_type'], d['die_type'])} {range_label}：{formula_str}",
                    entities=[ch_ent, cd_ent, tgt_ent],
                )
            else:
                ch_ent = self._char_entity(data.get("actor"))
                self._add_item(
                    "combat",
                    f"单方面进攻：{data['actor']} → {data['target']}（掷 {data.get('rolled')}，最终 {data.get('final_score')}）",
                    side=ch_ent["side"] if ch_ent else None,
                    entities=[ch_ent, tgt_ent],
                )
            return

        if kind in ("unopposed_clash_win", "unopposed_clash_lose", "unopposed_clash_draw"):
            ch_ent = self._char_entity(data.get("actor"))
            res_map = {"win": "胜利", "lose": "落败", "draw": "平局"}
            res_word = res_map[kind.rsplit("_", 1)[-1]]
            self._add_item(
                "combat",
                f"空白轮：对位骰离场，{data['actor']} 判定拼点{res_word}。",
                side=ch_ent["side"] if ch_ent else None,
                entities=[ch_ent],
            )
            return

        if kind == "clash_split":
            self._add_item("combat", "拼点拆分为双方单方面攻击，按点数依次结算命中。")
            return

        if kind == "clash_win_suppressed":
            ch_ent = self._char_entity(data.get("actor"))
            self._add_item("combat", f"{data['actor']} 受远程压制，跳过拼赢分支。", entities=[ch_ent])
            return

        if kind == "hit":
            if data.get("mode") == "full" and data.get("index", 1) <= 1:
                return
            ch_ent = self._char_entity(data.get("source"))
            tgt_ent = self._char_entity(data.get("target"))
            cd_ent = self._card_entity(card_name=data.get("card"), side=ch_ent["side"] if ch_ent else None)
            if data.get("mode") == "full":
                msg = f"追加命中（第 {data['index']} 次）：{data['source']}「{data['card']}」→ {data['target']}。"
            else:
                part = {"effects_only": "仅效果", "damage_only": "仅伤害"}.get(data["mode"], data["mode"])
                msg = f"特殊命中（{part}）：{data['source']}「{data['card']}」→ {data['target']}。"
            self._add_item("combat", msg, side=ch_ent["side"] if ch_ent else None, entities=[ch_ent, cd_ent, tgt_ent])
            return

        if kind == "entry_resolved":
            ch_ent = self._char_entity(data.get("character_id") or data.get("character_name"), fallback_side=data.get("side"))
            group = data.get("group") or "词条"
            st_ent = self._status_entity(group) if group in self._game.status_rules else None
            cd_ent = self._card_entity(card_name=group, side=data.get("side")) if group in self._card_index else None
            self._add_item(
                "passive",
                f"{data.get('character_name', '')} 触发「{group}」。",
                side=data.get("side"),
                entities=[ch_ent, cd_ent, st_ent],
            )
            return

        if kind == "status_activated":
            ch_ent = self._char_entity(data.get("source"))
            tgt_ent = self._char_entity(data.get("target"))
            st_ent = self._status_entity(data.get("effect") or data.get("status"))
            cd_ent = self._card_entity(card_name=data.get("card")) if data.get("card") else None
            origin = data.get("origin")
            init_str = (
                f"「{data['card']}」第{data['position']}骰" if origin == "die"
                else f"「{data['card']}」" if origin == "card"
                else f"的{data['status']}" if data.get("status") else ""
            )
            self._add_item(
                "passive",
                f"{data.get('source') or '效果'}{init_str} 触发 {data['effect']}（{data['target']}，{data['count']} 层）。",
                side=ch_ent["side"] if ch_ent else None,
                entities=[ch_ent, cd_ent, tgt_ent, st_ent],
            )
            return

        if kind == "health_lost":
            self._pending_health_events.append(("lost", data))
            return

        if kind == "health_recovered":
            self._pending_health_events.append(("heal", data))
            return

        if kind == "damage_settled":
            self._pop_matching_health_event(
                "lost",
                char_id=data.get("character_id"),
                name=data.get("character_name"),
                amount=data.get("hp_lost", 0),
                hp=data.get("hp"),
            )
            self._pending_damage_settled.append(data)
            return

        if kind == "direct_damage":
            settled = self._pop_matching_damage_settled(
                char_id=data.get("target_id"),
                name=data.get("target"),
                amount=data.get("amount"),
                hp_lost=data.get("lost"),
                hp=data.get("hp"),
            )
            self._pop_matching_health_event(
                "lost",
                char_id=data.get("target_id"),
                name=data.get("target"),
                amount=data.get("lost", settled.get("hp_lost", 0) if settled else 0),
                hp=data.get("hp"),
            )
            src_name = data.get("source") or "效果"
            tgt_name = data.get("target")
            src_ent = self._char_entity(data.get("source_id") or src_name, fallback_side=data.get("source_side"))
            tgt_ent = self._char_entity(data.get("target_id") or tgt_name, fallback_side=data.get("target_side"))
            cd_ent = self._card_entity(card_name=data.get("card_name"), card_id=data.get("card_id"),
                                       side=src_ent["side"] if src_ent else None)
            hp_lost = data.get("lost", settled.get("hp_lost", 0) if settled else 0)
            tgt_side = data.get("target_side") or (tgt_ent["side"] if tgt_ent else None)
            atk_side = data.get("source_side") or (src_ent["side"] if src_ent else None)
            turn = self._ensure_turn()
            if atk_side in (1, 2):
                turn["stats"]["damage_by_side"][str(atk_side)] += hp_lost
            if self._current_block and tgt_side in (1, 2):
                self._current_block["summary"]["hp_delta"][str(tgt_side)] -= hp_lost

            formula = format_damage_formula(
                base_amount=data.get("base_amount"),
                outgoing=data.get("outgoing_amount"),
                multiplier=data.get("multiplier", settled.get("multiplier", 1) if settled else 1),
                incoming=data.get("amount", 0),
                grade=data.get("grade", "normal"),
                absorbed=settled.get("absorbed") if settled else None,
                eroded=settled.get("eroded") if settled else None,
                borrowed_absorbed=settled.get("borrowed_absorbed") if settled else None,
                hp_lost=hp_lost,
                hp_after=data.get("hp", 0),
                max_hp=data.get("maximum", 0),
            )
            grade_label = _grade_label(data.get("grade", "normal"))
            self._add_item(
                "damage",
                f"{src_name} 对 {tgt_name} 造成 {_fmt_num(data.get('amount', 0))} 点{grade_label}（实扣 {_fmt_num(hp_lost)} 生命）。",
                side=src_ent["side"] if src_ent else None,
                formula=formula,
                entities=[src_ent, cd_ent, tgt_ent],
            )
            return

        if kind == "real_damage":
            src_name = data.get("source") or "效果"
            tgt_ent = self._char_entity(data.get("target_id") or data.get("target"), data.get("target_side"))
            src_ent = self._char_entity(data.get("source_id") or src_name, data.get("source_side"))
            amt = data.get("amount", 0)
            lost = data.get("lost", amt)
            self._pop_matching_health_event("lost", name=data.get("target"), amount=lost, hp=data.get("hp"))
            tgt_side = data.get("target_side") or (tgt_ent["side"] if tgt_ent else None)
            atk_side = data.get("source_side") or (src_ent["side"] if src_ent else None)
            if atk_side in (1, 2):
                self._ensure_turn()["stats"]["damage_by_side"][str(atk_side)] += lost
            if self._current_block and tgt_side in (1, 2):
                self._current_block["summary"]["hp_delta"][str(tgt_side)] -= lost
            self._add_item(
                "damage",
                f"{data['target']} 承受 {_fmt_num(amt)} 点真实伤害（来源：{src_name}，剩余 {data['hp']}/{data['maximum']}）。",
                side=src_ent["side"] if src_ent else None,
                entities=[src_ent, tgt_ent],
            )
            return

        if kind == "hp_lost":
            tgt_ent = self._char_entity(data.get("target"))
            lost = data.get("lost", 0)
            self._pop_matching_health_event("lost", name=data.get("target"), amount=lost, hp=data.get("hp"))
            tgt_side = tgt_ent["side"] if tgt_ent else None
            if self._current_block and tgt_side in (1, 2):
                self._current_block["summary"]["hp_delta"][str(tgt_side)] -= lost
            self._add_item(
                "damage",
                f"{data['target']} 失去 {_fmt_num(lost)} 点生命（剩余 {data['hp']}/{data['maximum']}）。",
                entities=[tgt_ent],
            )
            return

        if kind == "healed":
            tgt_ent = self._char_entity(data.get("target"))
            amt = data.get("amount", 0)
            self._pop_matching_health_event("heal", name=data.get("target"), amount=amt, hp=data.get("hp"))
            tgt_side = tgt_ent["side"] if tgt_ent else None
            if self._current_block and tgt_side in (1, 2):
                self._current_block["summary"]["hp_delta"][str(tgt_side)] += amt
            self._add_item(
                "status",
                f"{data['target']} 恢复 {_fmt_num(amt)} 点生命（当前 {data['hp']}/{data['maximum']}）。",
                side=tgt_side,
                entities=[tgt_ent],
            )
            return

        if kind in ("lightcore_damage", "lightcore_overflow"):
            tgt_name = data.get("character_name") or data.get("target")
            tgt_ent = self._char_entity(data.get("character_id") or tgt_name, fallback_side=data.get("side"))
            if kind == "lightcore_damage":
                src = data.get("source") or "效果"
                src_ent = self._char_entity(src) if src != "效果" else None
                self._add_item(
                    "damage",
                    f"{src} 对 {tgt_name} 造成 {_fmt_num(data.get('amount', 0))} 点光点伤害（完整度 {data.get('hp', 0)}/{data.get('maximum', 0)}）。",
                    entities=[src_ent, tgt_ent],
                )
            else:
                self._add_item(
                    "damage",
                    f"本骰的溢出伤害从 {tgt_name} 的新光点生命条扣除 {_fmt_num(data.get('lost', 0))} 点（完整度 {data.get('hp', 0)}/{data.get('maximum', 0)}）。",
                    entities=[tgt_ent],
                )
            return

        if kind == "lightcore_collapse":
            tgt_name = data.get("character_name") or data.get("target")
            tgt_ent = self._char_entity(data.get("character_id") or tgt_name, fallback_side=data.get("side"))
            turn = self._ensure_turn()
            turn["stats"]["collapses"].append(tgt_name)
            if self._current_block:
                self._current_block["summary"]["highlights"].append(f"{tgt_name}光点形态群崩塌")
            self._add_item("key", f"{tgt_name} 的光点形态群崩塌。", entities=[tgt_ent])
            return

        if kind in ("lightcore_healed", "lightcore_restored", "lightcore_max_changed"):
            tgt_name = data.get("character_name") or data.get("target")
            tgt_ent = self._char_entity(data.get("character_id") or tgt_name, fallback_side=data.get("side"))
            if kind == "lightcore_healed":
                txt = f"{tgt_name} 回复 {_fmt_num(data.get('amount', 0))} 点光点生命（完整度 {data.get('hp', 0)}/{data.get('maximum', 0)}）。"
            elif kind == "lightcore_restored":
                txt = f"{tgt_name} 的光点生命上限降至 {data.get('maximum', 0)}，完整度恢复为 {data.get('hp', 0)}/{data.get('maximum', 0)}。"
            else:
                txt = f"{tgt_name} 的光点生命上限变为 {data.get('maximum', 0)}（完整度 {data.get('hp', 0)}/{data.get('maximum', 0)}）。"
            self._add_item("status", txt, entities=[tgt_ent])
            return

        if kind == "status_changed":
            old, total = data.get("previous", 0), data.get("total", 0)
            delta = total - old
            sign = f"+{delta}" if delta >= 0 else str(delta)
            tgt_ent = self._char_entity(data.get("target"))
            st_ent = self._status_entity(data.get("name"))
            self._last_status_fact = (data.get("target"), data.get("name"), total)
            self._add_item(
                "status",
                f"{data['target']} {data['name']} {sign} → {total} 层。",
                side=tgt_ent["side"] if tgt_ent else None,
                entities=[tgt_ent, st_ent],
            )
            return

        if kind == "status_spent":
            tgt_ent = self._char_entity(data.get("target"))
            st_ent = self._status_entity(data.get("name"))
            self._last_status_fact = (data.get("target"), data.get("name"), data.get("total", 0))
            short = f"（需 {data['cost']}，未付足）" if data.get("amount", 0) < data.get("cost", 0) else ""
            self._add_item(
                "status",
                f"{data['target']} 消耗 {data['amount']} 层 {data['name']}{short} → 剩余 {data['total']} 层。",
                side=tgt_ent["side"] if tgt_ent else None,
                entities=[tgt_ent, st_ent],
            )
            return

        if kind == "status_cleared":
            bal = self._pending_status_balance
            if (bal and bal.get("status") == data.get("name") and bal.get("after", 0) == 0
                    and data.get("target") in (bal.get("character_name"), f"{bal.get('character_name')}（队伍）")):
                self._pending_status_balance = None
            tgt_ent = self._char_entity(data.get("target"))
            st_ent = self._status_entity(data.get("name"))
            self._add_item(
                "status",
                f"{data['target']} 清空 {data['amount']} 层 {data['name']}。",
                side=tgt_ent["side"] if tgt_ent else None,
                entities=[tgt_ent, st_ent],
            )
            return

        if kind == "status_balance":
            last = self._last_status_fact
            self._last_status_fact = None
            if (last and last[1] == data.get("status") and last[2] == data.get("after")
                    and last[0] in (data.get("character_name"), f"{data.get('character_name')}（队伍）")):
                return
            self._flush_pending_status_balance()
            self._pending_status_balance = data
            return

        if kind == "status_blocked":
            tgt_ent = self._char_entity(data.get("target"))
            st_ent = self._status_entity(data.get("name"))
            self._add_item("status", f"{data['target']} 未能获得 {data['name']}。", entities=[tgt_ent, st_ent])
            return

        if kind == "shield_balance":
            self._flush_pending_shield()
            self._pending_shield_balance = data
            return

        if kind == "shield_changed":
            bal = self._pending_shield_balance
            if bal:
                sh_bal_label = SHIELD_NAMES.get(bal.get("field"), bal.get("field"))
                sh_chg_label = SHIELD_NAMES.get(data.get("shield"), data.get("shield"))
                if (data.get("target") in (bal.get("character_name"), f"{bal.get('character_name')}（队伍）")
                        and sh_bal_label == sh_chg_label and bal.get("after") == data.get("total")):
                    self._pending_shield_balance = None
                else:
                    self._flush_pending_shield()
            tgt_ent = self._char_entity(data.get("target"))
            sh_label = SHIELD_NAMES.get(data.get("shield"), data.get("shield", "护盾"))
            self._add_item(
                "status",
                f"{data['target']} {sh_label} → {_fmt_num(data.get('total', 0))}。",
                side=tgt_ent["side"] if tgt_ent else None,
                entities=[tgt_ent],
            )
            return

        if kind in ("ability_spent", "ability_changed"):
            tgt_ent = self._char_entity(data.get("target"))
            tgt_side = tgt_ent["side"] if tgt_ent else None
            if kind == "ability_spent":
                msg = f"{data['target']} 使用 {data['amount']} 次{data['name']} → 剩余 {data['total']} 次。"
            else:
                msg = f"{data['target']} 的{data['name']}变为 {data['total']} 次。"
            self._add_item("status", msg, side=tgt_side, entities=[tgt_ent])
            return

        if kind in ("critical", "stagger_resolved", "random_check"):
            if kind == "critical":
                ch_ent = self._char_entity(data.get("actor"))
                self._add_item("combat", f"{data['actor']} 呼吸判定成功，触发暴击。",
                               side=ch_ent["side"] if ch_ent else None, entities=[ch_ent, self._status_entity("呼吸")])
            elif kind == "stagger_resolved":
                ch_ent = self._char_entity(data.get("character_id") or data.get("character_name"), fallback_side=data.get("side"))
                res = "触发致命失衡。" if data.get("passed") else "未触发致命失衡（失衡+2）。"
                self._add_item("combat", f"失衡爆发检定：{data.get('character_name', '')} {res}",
                               side=data.get("side"), entities=[ch_ent, self._status_entity("失衡")])
            else:
                ch_ent = self._char_entity(data.get("source"))
                self._add_item("combat", f"随机判定：{data.get('source') or '效果'} 投掷 {data['low']}~{data['high']} → 掷出 {data['roll']}。",
                               entities=[ch_ent])
            return

        if kind in ("card_destroyed", "die_destroyed"):
            cd_ent = self._card_entity(card_name=data.get("card"), card_id=data.get("card_id"), side=data.get("side"))
            ch_ent = self._char_entity(data.get("character_id") or data.get("character_name"), fallback_side=data.get("side"))
            if kind == "card_destroyed":
                if self._current_block:
                    self._current_block["summary"]["highlights"].append(f"摧毁「{data.get('card')}」")
                self._add_item("key", f"「{data.get('card')}」被摧毁。", side=data.get("side"), entities=[ch_ent, cd_ent])
            else:
                pos_str = f"第 {data['position']} 骰" if data.get("position") else "一颗骰子"
                card_prefix = f"「{data['card']}」" if data.get("card") else ""
                self._add_item("key", f"{card_prefix}{pos_str}被摧毁。", side=data.get("side"), entities=[ch_ent, cd_ent])
            return

        if kind == "character_died":
            ch_name = data.get("character_name") or "角色"
            ch_ent = self._char_entity(data.get("character_id") or ch_name, fallback_side=data.get("side"))
            turn = self._ensure_turn()
            turn["stats"]["deaths"].append(ch_name)
            if self._current_block:
                self._current_block["summary"]["highlights"].append(f"{ch_name}阵亡")
            self._add_item("key", f"{ch_name} 阵亡。", side=data.get("side"), entities=[ch_ent])
            return

        if kind in ("special_placement", "special_rear_placement", "card_replaced", "hidden_card_replaced",
                    "ability_used", "card_played", "attack_redirected", "rear_card_invalidated",
                    "hand_card_taken", "card_face_changed", "placement_lock"):
            if kind in ("special_placement", "special_rear_placement"):
                p_side = data.get("side")
                slot_lbl = f"常规交锋 {data['number']}" + (" 后置槽" if kind == "special_rear_placement" else "")
                c_name = data.get("card_name")
                a_name = data.get("actor_name") or data["player"]
                if data.get("face_up") and c_name:
                    ch_ent = self._char_entity(data.get("actor_id") or a_name, fallback_side=p_side)
                    cd_ent = self._card_entity(card_name=c_name, card_id=data.get("card_id"), side=p_side)
                    self._add_item("card", f"{a_name} 即时明置「{c_name}」 → {slot_lbl}。",
                                   side=p_side, entities=[ch_ent, cd_ent])
                elif c_name and p_side in (1, 2):
                    ch_ent = self._char_entity(data.get("actor_id") or a_name, fallback_side=p_side)
                    cd_ent = self._card_entity(card_name=c_name, card_id=data.get("card_id"), side=p_side)
                    self._add_item(
                        "card",
                        f"{a_name} 将「{c_name}」即时扣置 → {slot_lbl}。",
                        side=p_side,
                        entities=[ch_ent, cd_ent],
                        private_side=p_side,
                        reveal_on_cards_revealed=True,
                        redacted_text=f"{data['player']} 将手牌即时置入 {slot_lbl}。",
                        redacted_entities=[ch_ent],
                        card_id=data.get("card_id"),
                        instance_id=data.get("instance_id"),
                    )
                else:
                    self._add_item("card", f"{data['player']} 将手牌即时置入 {slot_lbl}。", side=p_side)
            elif kind == "card_replaced":
                ch_ent = self._char_entity(data.get("actor"))
                c1 = self._card_entity(card_name=data.get("card"))
                c2 = self._card_entity(card_name=data.get("replaced"))
                dest = "消散" if data.get("dissolved") else "回手"
                self._add_item("card", f"{data['actor']} 换入「{data['card']}」，原「{data['replaced']}」{dest}。",
                               entities=[ch_ent, c1, c2])
            elif kind == "hidden_card_replaced":
                dest = "消散" if data.get("dissolved") else "回手"
                p_side = data.get("side")
                if p_side in (1, 2):
                    self._mark_hidden_withdrawn(
                        p_side,
                        instance_id=data.get("old_instance_id"),
                        card_id=data.get("old_card_id"),
                    )
                if p_side in (1, 2) and data.get("new_card_name"):
                    ch_ent = self._char_entity(data.get("new_actor_id") or data.get("new_actor_name"), fallback_side=p_side)
                    cd_new = self._card_entity(card_name=data.get("new_card_name"), card_id=data.get("new_card_id"), side=p_side)
                    cd_old = self._card_entity(card_name=data.get("old_card_name"), card_id=data.get("old_card_id"), side=p_side)
                    slot_info = (f"常规交锋 {data['duel_number']}{' · 后置槽' if data.get('lane') == 'rear' else ''}"
                                 if data.get("duel_number") else "扣置槽")
                    self._add_item(
                        "card",
                        f"{data.get('new_actor_name') or data['player']} 调换扣置：换入「{data['new_card_name']}」至 {slot_info}，原「{data.get('old_card_name') or '旧牌'}」{dest}。",
                        side=p_side,
                        entities=[ch_ent, cd_new, cd_old],
                        private_side=p_side,
                        reveal_on_cards_revealed=True,
                        redacted_text=f"{data['player']} 调换了一张扣置技能（原牌{dest}）。",
                        redacted_entities=[],
                        reveal_text=f"{data.get('new_actor_name') or data['player']} 调换扣置：换入「{data['new_card_name']}」至 {slot_info}，原扣置牌{dest}。",
                        reveal_entities=[ch_ent, cd_new],
                        card_id=data.get("new_card_id"),
                        instance_id=data.get("new_instance_id"),
                    )
                else:
                    self._add_item("card", f"{data['player']} 调换了一张扣置技能（原牌{dest}）。", side=p_side)
            elif kind == "ability_used":
                ch_ent = self._char_entity(data.get("actor"))
                self._add_item("passive", f"{data['actor']} 发动主动能力「{data['ability']}」。",
                               side=ch_ent["side"] if ch_ent else None, entities=[ch_ent])
            elif kind == "card_played":
                c1 = self._card_entity(card_name=data.get("card"))
                self._add_item("card", f"{data['player']} 即时打出「{data['card']}」。", entities=[c1])
            elif kind == "attack_redirected":
                ch_ent = self._char_entity(data.get("actor"))
                t_new = self._char_entity(data.get("target"))
                self._add_item("combat", f"{data.get('actor') or '进攻骰'} 攻击目标转移：{data.get('old_target') or '原目标'} → {data.get('target')}。",
                               entities=[ch_ent, t_new])
            elif kind == "rear_card_invalidated":
                p_side = data.get("side")
                cd_ent = self._card_entity(card_name=data.get("card"), card_id=data.get("card_id"), side=p_side)
                self._add_item("card", f"前置锚点失效，后置技能「{data['card']}」作废。", side=p_side, entities=[cd_ent])
            elif kind == "hand_card_taken":
                ch_ent = self._char_entity(data.get("receiver"))
                self._add_item("card", f"{data['receiver']} 接过一张技能牌。",
                               side=ch_ent["side"] if ch_ent else None, entities=[ch_ent])
            elif kind == "card_face_changed":
                label = f"「{data['card']}」" if data.get("card") else "一张扣置牌"
                dir_str = "翻正" if data.get("face") == "up" else "翻面扣置"
                cd_ent = self._card_entity(card_name=data.get("card")) if data.get("card") else None
                self._add_item("card", f"{label}{dir_str}。", entities=[cd_ent])
            elif kind == "placement_lock":
                label = f"「{data['card']}」" if data.get("card") else "一张扣置牌"
                lock_str = "锁定位置" if data.get("locked") else "解除位置锁定"
                cd_ent = self._card_entity(card_name=data.get("card")) if data.get("card") else None
                self._add_item("card", f"{label}{lock_str}。", entities=[cd_ent])
            return

        if kind == "turn_ended":
            self._flush_pending_buffers()
            self._ensure_phase_block("turn_end", "回合收尾与卡牌回收")
            rec = data.get("recycled") or ()
            rec_parts = []
            for idx, item in enumerate(rec, 1):
                if isinstance(item, dict):
                    s = item.get("side", idx)
                    cnt = (item.get("used_count", 0) or 0) + (item.get("board_count", 0) or 0) + (item.get("discard_count", 0) or 0)
                    rec_parts.append(f"P{s} 回收 {cnt} 张")
                else:
                    rec_parts.append(f"P{idx} 回收 {item} 张")
            rec_str = "、".join(rec_parts) if rec_parts else ""
            self._add_item("card", f"第 {data['turn']} 回合结束" + (f"（{rec_str}）" if rec_str else "") + "。")
            return

    def _pop_matching_damage_settled(self, *, char_id=None, name=None, amount=None, hp_lost=None, hp=None):
        for idx in range(len(self._pending_damage_settled) - 1, -1, -1):
            s = self._pending_damage_settled[idx]
            if char_id is not None and s.get("character_id") != char_id:
                continue
            if char_id is None and name is not None and s.get("character_name") != name:
                continue
            if hp is not None and s.get("hp") != hp:
                continue
            return self._pending_damage_settled.pop(idx)
        return self._pending_damage_settled.pop() if self._pending_damage_settled else None

    def _pop_matching_health_event(self, ev_kind, *, char_id=None, name=None, amount=None, hp=None):
        for idx in range(len(self._pending_health_events) - 1, -1, -1):
            k, bal = self._pending_health_events[idx]
            if k != ev_kind:
                continue
            if char_id is not None and bal.get("character_id") != char_id:
                continue
            if char_id is None and name is not None and name not in (bal.get("character_name"),):
                continue
            if amount is not None and bal.get("amount") != amount:
                continue
            if hp is not None and bal.get("hp") != hp:
                continue
            return self._pending_health_events.pop(idx)
        return None

    def _flush_all_pending_damage_settled(self):
        while self._pending_damage_settled:
            settled = self._pending_damage_settled.pop(0)
            self._emit_standalone_damage_settled(settled)

    def _emit_standalone_damage_settled(self, settled):
        if not settled:
            return
        tgt_name = settled.get("character_name") or "目标"
        tgt_side = settled.get("side")
        tgt_ent = self._char_entity(settled.get("character_id") or tgt_name, fallback_side=tgt_side)
        cause = settled.get("cause") or "效果"
        hp_lost = settled.get("hp_lost", 0)
        turn = self._ensure_turn()
        if settled.get("source_side") in (1, 2):
            turn["stats"]["damage_by_side"][str(settled["source_side"])] += hp_lost
        if self._current_block and tgt_side in (1, 2):
            self._current_block["summary"]["hp_delta"][str(tgt_side)] -= hp_lost
        st_ent = self._status_entity(cause) if cause in self._game.status_rules else None
        formula = format_damage_formula(
            incoming=settled.get("incoming", 0),
            multiplier=settled.get("multiplier", 1),
            grade=settled.get("grade", "normal"),
            absorbed=settled.get("absorbed"),
            eroded=settled.get("eroded"),
            borrowed_absorbed=settled.get("borrowed_absorbed"),
            hp_lost=hp_lost,
            hp_after=settled.get("hp", 0),
            max_hp=settled.get("maximum", 0),
        )
        grade_label = _grade_label(settled.get("grade", "normal"))
        self._add_item(
            "damage",
            f"{tgt_name} 承受 {cause} {_fmt_num(settled.get('incoming', 0))} 点{grade_label}（实扣 {_fmt_num(hp_lost)} 生命）。",
            side=tgt_side,
            formula=formula,
            entities=[tgt_ent, st_ent],
        )

    def snapshot(self, viewer_side=None, *, unlock_all=False):
        """Return fog-of-war-filtered hierarchical chronicle for `viewer_side`."""
        self.flush()
        full_unlock = bool(unlock_all or self._game.is_over)
        projected_turns = []
        total_items = 0

        for t in self._turns:
            proj_blocks = []
            for b in t["blocks"]:
                proj_rounds = []
                for rnd in b["rounds"]:
                    proj_items = []
                    for it in rnd["items"]:
                        priv = it["private_side"]
                        is_owner_or_full = full_unlock or (priv is None) or (viewer_side == priv)
                        revealed_now = is_owner_or_full or bool(it.get("unlocked_at_reveal"))
                        if is_owner_or_full:
                            item_text = it["text"]
                            item_formula = it["formula"]
                            item_entities = it["entities"]
                        elif revealed_now:
                            item_text = it.get("reveal_text") or it["text"]
                            item_formula = it["formula"]
                            item_entities = it["reveal_entities"] if it.get("reveal_entities") is not None else it["entities"]
                        else:
                            item_text = it["redacted_text"] or "保密行动。"
                            item_formula = None
                            item_entities = it["redacted_entities"]
                        proj_items.append({
                            "seq": it["seq"],
                            "category": it["category"],
                            "side": it["side"],
                            "text": item_text,
                            "formula": item_formula,
                            "entities": item_entities,
                        })
                        total_items += 1
                    if proj_items or rnd["rolls"]:
                        proj_rounds.append({
                            "round": rnd["round"],
                            "kind": rnd["kind"],
                            "label": rnd["label"],
                            "rolls": list(rnd["rolls"]),
                            "target_name": rnd["target_name"],
                            "items": proj_items,
                        })
                if proj_rounds or b["kind"] == "duel":
                    proj_blocks.append({
                        "id": b["id"],
                        "kind": b["kind"],
                        "phase": b["phase"],
                        "title": b["title"],
                        "duel_kind": b["duel_kind"],
                        "duel_number": b["duel_number"],
                        "matchup": dict(b["matchup"]),
                        "summary": {
                            "rounds": b["summary"]["rounds"],
                            "hp_delta": dict(b["summary"]["hp_delta"]),
                            "highlights": list(b["summary"]["highlights"]),
                        },
                        "rounds": proj_rounds,
                    })
            projected_turns.append({
                "turn": t["turn"],
                "first_side": t["first_side"],
                "first_player": t["first_player"],
                "speed_attempts": list(t["speed_attempts"]),
                "stats": {
                    "damage_by_side": dict(t["stats"]["damage_by_side"]),
                    "deaths": list(t["stats"]["deaths"]),
                    "collapses": list(t["stats"]["collapses"]),
                },
                "blocks": proj_blocks,
            })

        return {
            "unlocked_all": full_unlock,
            "total_events": total_items,
            "turns": projected_turns,
        }

    def to_markdown(self, viewer_side=None, *, unlock_all=False, header_meta=None):
        """Format the chronicle into a clean, copy-ready Markdown report."""
        snap = self.snapshot(viewer_side=viewer_side, unlock_all=unlock_all)
        lines = ["# 《光点计划 III》对局战报"]
        if header_meta:
            if header_meta.get("players"):
                p_bits = []
                for p in header_meta["players"]:
                    roster = "、".join(c["name"] for c in p.get("characters", ()))
                    p_bits.append(f"席位 {p['side']}（{roster}）")
                lines.append(f"- **参战阵容**：{'  vs  '.join(p_bits)}")
            if header_meta.get("result"):
                lines.append(f"- **对局结果**：{header_meta['result']}")
        lines.append("")

        for t in snap["turns"]:
            init_str = f" · {t['first_player']}先手" if t.get("first_player") else ""
            d1 = t["stats"]["damage_by_side"].get("1", 0)
            d2 = t["stats"]["damage_by_side"].get("2", 0)
            lines.append(f"## 第 {t['turn']} 回合{init_str}（P1 造伤 {_fmt_num(d1)} / P2 造伤 {_fmt_num(d2)}）")
            for b in t["blocks"]:
                if b["kind"] == "duel":
                    m1 = b["matchup"].get("1")
                    m2 = b["matchup"].get("2")
                    s1 = f"{m1['character_name']}「{m1['card_name']}」" if m1 else "—"
                    s2 = f"{m2['character_name']}「{m2['card_name']}」" if m2 else "—"
                    dh1 = b["summary"]["hp_delta"].get("1", 0)
                    dh2 = b["summary"]["hp_delta"].get("2", 0)
                    swing = f" [生命变化 P1:{dh1:+g} / P2:{dh2:+g}]" if (dh1 or dh2) else ""
                    lines.append(f"### {b['title']}：{s1}  vs  {s2}{swing}")
                else:
                    lines.append(f"### {b['title']}")
                for rnd in b["rounds"]:
                    if rnd["label"] and rnd["round"] > 0:
                        lines.append(f"- **{rnd['label']}**")
                    indent = "  " if (rnd["label"] and rnd["round"] > 0) else ""
                    for it in rnd["items"]:
                        lines.append(f"{indent}- {it['text']}")
                        if it.get("formula"):
                            lines.append(f"{indent}  - `算式：{it['formula']}`")
            lines.append("")
        return "\n".join(lines).strip() + "\n"
