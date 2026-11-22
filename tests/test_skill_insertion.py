import io
import random
import unittest
from contextlib import redirect_stdout

from battle_ui.match import BattleMatch
from displayer import Displayer
from entry.entry import Entry, TriggerType
from game import Game
from models.card import Card, CardState
from models.character import Character
from models.dice import describe_die
from models.duel import DuelSlot
from models.special_actions import SkillUse
from player.player import Player


def die(amount, *entries):
    return {"type": "slash", "level": 3, "entries": [str(amount), *entries]}


def choose(selector, code, *, optional=False):
    return {"trigger": "on_dice_hit", "authority": "较高话语权", "operation": {"op": "program", "code": [
        selector, {"literal": {"optional": optional, "then": {"op": "program", "code": code}}}, "CHOOSE_CARD"
    ]}}


class SkillInsertionTests(unittest.TestCase):
    def setUp(self):
        self.log = self.enterContext(redirect_stdout(io.StringIO()))
        self.left, self.right = Player(1, "甲"), Player(2, "乙")
        self.game = Game([self.left, self.right], rng=random.Random(2026))
        self.game.first_player = self.left
        for player in self.game.players:
            actor = Character({"id": player.name, "name": player.name, "rank": "BOSS", "max_hp": 35, "skills": []}, player)
            player.characters.append(actor)
        self.actor, self.foe = self.left.characters[0], self.right.characters[0]
        self.game.start_turn()
        self.game.cards_revealed = True
        self.slot = DuelSlot(self.game)
        self.game.duelspace.append_new_duel(self.slot)

    def card(self, name, dice, *, actor=None, cost=0, entries=(), hand=False):
        actor = actor or self.actor
        card = Card(actor.player, dict(id=name, name=name, cost=cost, dice=dice, entries=entries), actor)
        actor.skills.append(card)
        if hand:
            actor.player.cardspace.hand.add_card(card)
        else:
            self.slot.add_content(actor.player.side, card)
            card.state = CardState.PLACED_FACE_UP
        return card

    def run_to_choice_or_end(self):
        for _ in range(600):
            if self.game.special.decision_owner is not None or not self.game.pipeline.in_duel_phase:
                return
            self.game.next_step()
        self.fail("交锋未结束")

    def test_chosen_skill_pays_discount_runs_before_parent_resumes(self):
        action = choose("$own_hand_skills", [
            "$chosen_card", 2, "SKILL_USE", {"literal": {"at": "after_die"}}, "INSERT_SKILL"
        ], optional=True)
        log = []
        def track(name):
            return {"trigger": name, "operation": lambda ctx: log.append((name, ctx.event["card"].name))}
        entries = [track("on_skill_use"), track("after_skill_use"), track("on_dice_hit")]
        parent = self.card("母牌", [die(1, action), die(2)], cost=2, entries=entries)
        extra = self.card("插牌", [die(3)], cost=3, hand=True, entries=entries)
        self.game.pipeline.start_duel_combat()
        self.run_to_choice_or_end()
        self.assertEqual(self.game.next_step(), "wait_card_choice")
        self.assertEqual(self.game.special.options(self.right), [])
        options = self.game.special.options(self.left)
        self.assertEqual([opt.kind for opt in options], ["choose_card", "decline_card"])
        self.assertTrue(self.game.special.apply(self.left, options[0]))
        self.assertNotIn(extra, self.left.cardspace.hand.content)
        self.run_to_choice_or_end()
        self.assertFalse(self.game.pipeline.in_duel_phase)
        self.assertEqual(log, [("on_skill_use", "母牌"), ("on_dice_hit", "母牌"), ("on_skill_use", "插牌"),
                               ("on_dice_hit", "插牌"), ("after_skill_use", "插牌"),
                               ("on_dice_hit", "母牌"), ("after_skill_use", "母牌")])
        self.assertEqual(self.foe.hp, 29)
        self.assertEqual((self.actor.used_independent_cost, self.left.used_cost), (1, 2))
        self.assertEqual(self.game.used_cards, [parent, extra])
        self.assertEqual(extra.cost, 3)

    def test_chosen_hidden_slot_omits_identity_and_rechecks_zone(self):
        action = choose("$target_board_skills", ["$chosen_card", "DESTROY"])
        self.card("选牌", [die(1, action)])
        hidden = self.card("秘密", [die(1)], actor=self.foe)
        self.slot.remove_card(hidden)
        later = DuelSlot(self.game)
        self.game.duelspace.append_new_duel(later)
        later.add_content(self.right.side, hidden)
        hidden.state = CardState.PLACED_FACE_DOWN
        self.game.pipeline.start_duel_combat()
        self.run_to_choice_or_end()
        options = Displayer(self.game, viewer_side=1).special_actions()
        self.assertEqual(len(options), 1)
        self.assertIn("常规交锋 2", options[0]["label"])
        self.assertNotIn("秘密", str(options))
        self.assertEqual(Displayer(self.game).special_actions(), [])
        later.remove_card(hidden)
        self.right.cardspace.hand.add_card(hidden)
        self.assertIsNone(self.game.special.decision_owner)
        self.assertFalse(hidden.destroyed)

    def test_copied_immediate_attacks_can_nest_and_resume_without_deck_changes(self):
        def attack(name):
            return ["$self", name, "COPY_SKILL", 1, "SKILL_USE",
                    "$target", "immediate_attack", "INSERT_AT", "INSERT_SKILL"]

        def on_hit(code):
            return {"trigger": "on_dice_hit", "operation": {"op": "program", "code": code}}

        parent = self.card("母牌", [die(1, on_hit(attack("甲锤") + attack("乙锤"))), die(2)])
        turn_end = {"trigger": "on_turn_end", "scope": "turn", "operation": {
            "op": "program", "code": ["$self", "余响", 1, "STATUS"]}}
        first = self.card("甲锤", [die(3, on_hit(attack("子锤")))], cost=2, entries=[turn_end], hand=True)
        second = self.card("乙锤", [die(4)], cost=2, hand=True)
        child = self.card("子锤", [die(1)], cost=1, hand=True)
        self.game.pipeline.start_duel_combat()
        self.run_to_choice_or_end()
        self.assertFalse(self.game.pipeline.in_duel_phase)
        self.assertEqual([card.name for card in self.game.used_cards], ["母牌", "甲锤", "子锤", "乙锤"])
        self.assertEqual(self.foe.hp, 35 - 1 - 3 - 1 - 4 - 2)
        self.assertEqual((self.actor.used_independent_cost, self.left.used_cost), (1, 1))
        self.assertEqual(self.left.cardspace.hand.content, [first, second, child])
        copies = self.game.used_cards[1:]
        self.assertTrue(all(card.temporary and card.destroyed for card in copies))
        self.assertTrue(all(not slot.get_content(self.left.side) for slot in self.game.special.duels))
        self.game.finish_turn()
        self.game.context.dispatch_pipeline("on_turn_end")
        self.assertEqual(self.actor.statuses.get("余响"), 1)
        self.assertEqual(self.left.cardspace.draw.content, [parent])
        self.assertEqual(self.left.cardspace.hand.content, [first, second, child])
        self.assertFalse(any(entry.owning_card in copies for entry in self.game.context.entries))

    def test_skill_and_slot_anchors_follow_the_ordinary_use_pipeline(self):
        first = self.card("原牌", [die(1)])
        before, after, tail = [self.card(name, [die(1)], hand=True) for name in ("前", "后", "末")]
        for extra, at in ((before, "before_skill"), (after, "after_skill"), (tail, "slot_tail")):
            target = self.slot if at == "slot_tail" else first
            self.assertTrue(self.game.pipeline.insert_skill(SkillUse(extra), {"at": at, "target": target}, {}))
        self.game.pipeline.start_duel_combat()
        self.run_to_choice_or_end()
        self.assertEqual(self.game.used_cards, [before, first, after, tail])

    def test_explicit_pack_anchor_at_later_before_skill_choice_preserves_paid_prefix(self):
        earlier = self.card("前序牌", [die(1)], cost=1)
        upcoming = self.card("将使用的牌", [die(1)], cost=1)
        extra = self.card("选入的牌", [die(1)], cost=3, hand=True)
        rule = Entry(self.actor, TriggerType.PIPELINE, "test", {"op": "program", "code": [
            "$chosen_card", 2, "SKILL_USE", "$target", "before_skill", "INSERT_AT", "INSERT_SKILL"
        ]})
        game = self.game
        game.pipeline.start_duel_combat()
        for _ in range(200):
            node = game.next_step()
            if node[0] == "before_skill_choice" and self.slot.get_current_card(1) is upcoming:
                break
        else:
            self.fail("未到下一技能使用前")
        self.assertEqual(game.used_cards, [earlier])
        self.assertEqual(self.slot.current_card_index[1], 1)
        with game.context.binding(card=earlier, chosen_card=extra, target=upcoming):
            game.context._invoke(rule)
        self.assertEqual(self.slot.get_current_card(1), extra)
        self.run_to_choice_or_end()
        self.assertEqual(game.used_cards, [earlier, extra, upcoming])
        self.assertEqual((self.actor.used_independent_cost, self.left.used_cost), (1, 2))

    def test_before_die_anchor_preserves_parent_use_and_dice_cursor(self):
        log = []
        hit = {"trigger": "on_dice_hit", "operation": lambda ctx: log.append(ctx.event["card"].name)}
        first = self.card("母", [die(1), die(2)], entries=[hit])
        extra = self.card("子", [die(3)], hand=True, entries=[hit])
        target = first.get_current_die(self.game)
        self.assertTrue(self.game.pipeline.insert_skill(SkillUse(extra), {"at": "before_die", "target": target}, {}))
        self.game.pipeline.start_duel_combat()
        self.run_to_choice_or_end()
        self.assertEqual(log, ["子", "母", "母"])
        self.assertEqual(self.game.used_cards, [first, extra])

    def test_inserted_skill_pairs_against_opponents_next_die(self):
        decisions = choose("$own_hand_skills", [
            "$chosen_card", {"literal": {"at": "after_die"}}, "INSERT_SKILL"
        ], optional=True)
        records = []
        def pair(ctx):
            records.append((ctx.event["card"].name, ctx.event["opponent_die"].position))
        trace = {"trigger": "on_dice_clash", "operation": pair}
        strike = dict(die(1, decisions), base_value=20)
        self.card("母", [strike, die(1)], entries=[trace])
        self.card("子", [die(1), die(1)], hand=True, entries=[trace])
        self.card("对面", [die(1) for _ in range(4)], actor=self.foe)
        self.game.pipeline.start_duel_combat()
        self.run_to_choice_or_end()
        self.game.special.apply(self.left, self.game.special.options(self.left)[0])
        self.run_to_choice_or_end()
        self.assertEqual(records, [("母", 1), ("子", 2), ("子", 3), ("母", 4)])

    def test_decision_controller_keeps_private_hand_hidden_and_can_decline(self):
        table = BattleMatch(seed=2)
        actor = table.game.players[0].characters[0]
        actor.player.draw_card(1)
        candidate = actor.player.cardspace.hand.content[0]
        entry = Entry(actor, TriggerType.PIPELINE, "test", {"op": "program", "code": [
            "$own_hand_skills", {"literal": {"optional": True, "then": {"op": "program", "code": [
                "$chosen_card", "DESTROY"]}}}, "CHOOSE_CARD"
        ]})
        table.game.context._invoke(entry)
        table._advance()
        state = table.snapshot()
        self.assertEqual(state["mode"], "special_handoff")
        self.assertEqual(state["special_options"], [])
        self.assertTrue(all(player["hand"] is None for player in state["frame"]["players"]))
        state = table.act("ready", state["revision"], side=actor.player.side)
        self.assertTrue(state["card_choice"])
        self.assertTrue(any(candidate.name in option["label"] for option in state["special_options"]))
        decline = next(i for i, option in enumerate(state["special_options"]) if option["kind"] == "decline_card")
        state = table.act("use_special", state["revision"], option=decline)
        self.assertFalse(state["card_choice"])
        self.assertFalse(candidate.destroyed)

    def test_lin_qiu_printed_skip_and_range(self):
        from loader import load_characters_from_packs
        lin = next(spec for spec in load_characters_from_packs() if spec["name"] == "林秋")
        actor = Character(lin, self.left)
        self.left.characters.append(actor)
        actor.init_cards()
        catalog = Displayer(self.game).catalog()["players"][0]["characters"][-1]
        skills = {item["name"]: item for item in catalog["skills"]}
        skipped = skills["机动申请"]["dice"][0]
        self.assertEqual((skipped["type"], skipped["roll_max"], skipped["printed_level"]), ("skip", None, None))
        self.assertIn("普通远程", skills["出其不意"]["dice"][-1]["range_traits"])
        self.assertTrue(any("极限远程" in label for label in skills["空断"]["range_traits"]))
        self.assertIn("普通远程", describe_die(lin["skills"][2]["dice"][-1]))
