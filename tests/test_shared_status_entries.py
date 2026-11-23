"""Trace the shared status definitions loaded by the PvE roster."""
import unittest

from displayer import Displayer
from game import Game
from loader import EffectDefinitions, _add_effects, base_effects
from models.card import Card
from models.opcode import OpCode
from player.player import Player
from tests.test_entry_execution_paths import TraceContext, actor_for, resolve_entry


def holder():
    ctx = TraceContext()
    actor = actor_for(ctx, 1)
    ctx.game = actor.game
    defs = base_effects()
    actor.game.status_rules.update(defs.status_rules)
    actor.game.status_entries.update(defs.status_entries)
    return ctx, actor


class TeamRestrictionTests(unittest.TestCase):
    def setUp(self):
        self.left, self.right = Player(1, "甲"), Player(2, "乙")
        self.game = Game([self.left, self.right])
        self.ctx = self.game.context

        def actor(name):
            return dict(id=name, name=name, rank="NORMAL", max_hp=10, skills=[])

        self.game.deploy_rosters([[actor("甲一"), actor("甲二")], [actor("乙一")]])
        self.a, self.b = self.left.characters
        self.enemy, = self.right.characters
        self.game.first_player = self.left

    def in_hand(self, actor, name, cost):
        card = Card(actor.player, dict(id=name, name=name, cost=cost, dice=[]), actor)
        actor.player.cardspace.hand.add_card(card)
        return card

    def test_team_rank_strict_threshold_and_all_lowest_ties(self):
        cards = [self.in_hand(actor, str(i), cost) for i, (actor, cost) in enumerate(
            [(self.a, 4), (self.b, 4), (self.b, 2), (self.a, 1), (self.b, 1)])]
        for n, expected in [(0, []), (1, [0]), (2, [0, 1]), (3, [0, 1, 2]), (5, list(range(5))),
                            (6, [0, 1, 2]), (100, [0, 1, 2])]:
            with self.subTest(n=n):
                self.b.add_status("限制", n - self.left.team_statuses.get("限制", 0))
                for _ in range(2):
                    self.assertEqual([i for i, c in enumerate(cards) if c.character.skill_restricted(c)], expected)
                self.assertEqual(self.a.statuses.get("限制", 0), n)
                self.assertEqual(self.right.team_statuses, {})

    def test_pool_is_declared_by_the_status(self):
        definitions = EffectDefinitions()
        _add_effects(definitions, {"status_rules": {"队伍计数": {"pool": "team"}, "本人计数": {"pool": "character"}}})
        self.game.status_rules.update(definitions.status_rules)
        for name in definitions.status_rules:
            self.a.add_status(name, 2)
            self.b.add_status(name, 1)
        self.assertEqual(self.left.team_statuses, {"队伍计数": 3})
        self.assertEqual((self.a.statuses["本人计数"], self.b.statuses["本人计数"]), (2, 1))
        with self.assertRaisesRegex(ValueError, "层数归属"):
            _add_effects(definitions, {"status_rules": {"样本": {"pool": "other"}}})

    def test_use_spends_one_after_completion_and_failed_use_spends_nothing(self):
        self.game.start_turn()
        expensive = self.in_hand(self.a, "四费", 4)
        cheap = self.in_hand(self.b, "一费", 1)
        self.in_hand(self.a, "同费", 1)
        self.a.add_status("限制", 2)
        self.b.add_status("限制", 2)
        self.enemy.add_status("限制", 7)
        self.assertTrue(self.game.place_in_duel(1, expensive, 0))
        self.assertTrue(self.game.place_in_duel(1, cheap, 1))
        self.assertEqual(self.left.team_statuses["限制"], 4)
        self.assertTrue(self.a.skill_restricted(expensive))
        self.assertFalse(self.b.skill_restricted(cheap))
        with self.ctx.collect_facts() as facts:
            self.game.reveal_cards()
            self.game.pipeline.start_duel_combat()
            for _ in range(400):
                if not self.game.pipeline.in_duel_phase:
                    break
                self.game.next_step()
            self.assertFalse(self.game.pipeline.in_duel_phase)
        self.assertEqual([(k, v.get("card", v.get("amount"))) for k, v in facts
                          if k in ("skill_unpaid", "skill_used", "status_spent")],
                         [("skill_unpaid", expensive.name), ("skill_used", cheap.name), ("status_spent", 1)])
        self.assertEqual(self.left.team_statuses["限制"], 3)
        self.assertEqual(self.right.team_statuses["限制"], 7)
        self.game.finish_turn()
        self.game.prepare_turn()
        self.assertEqual(self.left.team_statuses, {"限制": 3})
        self.assertEqual(self.right.team_statuses, {})

    def test_snapshot_and_original_recipient_death(self):
        self.a.add_status("限制", 2)
        self.b.add_status("限制", 1)
        self.ctx.eval_block([self.a, self.a.hp, OpCode.REAL_DAMAGE])
        self.assertTrue(self.b.is_alive)
        self.assertEqual(self.ctx.eval_block([self.b, "限制", 1, OpCode.SPEND_STATUS]), 1)
        for side in (None, 1, 2):
            team, enemy = Displayer(self.game, viewer_side=side).snapshot()["players"]
            self.assertEqual(team["team_statuses"], {"限制": 2})
            self.assertEqual(enemy["team_statuses"], {})
            self.assertTrue(all("限制" not in c["statuses"] for c in team["characters"]))

    def test_first_turn_and_empty_turn_cleanup_happens_once_after_scheduled_grants(self):
        self.a.add_status("限制", 1)
        self.game.start_turn()
        self.assertEqual(self.left.team_statuses, {"限制": 1})
        discarded = self.in_hand(self.a, "弃牌", 1)
        self.ctx.eval_block([self.left, discarded, OpCode.DISCARD])
        resolve_entry(self.ctx, self.enemy, {"trigger": "fixture", "operation": {"schedule": {
            "event": "on_turn_prepared", "source": "$self", "target": "$event.target",
            "after_turns": 1, "through_turns": 1, "uses": 1, "require_source_alive": False,
            "require_target_alive": True, "then": ["$event.target", "限制", 2, "STATUS"]}}},
            source=self.enemy, target=self.b)
        self.game.finish_turn()
        self.assertEqual(self.left.team_statuses, {"限制": 1})
        with self.ctx.collect_facts() as facts:
            self.game.prepare_turn()
        self.assertEqual([(k, v["total"]) for k, v in facts if v.get("name") == "限制"],
                         [("status_changed", 3), ("status_spent", 0)])
        self.assertTrue(all(v["target"] == self.left.name for _, v in facts if v.get("name") == "限制"))
        self.a.add_status("限制", 1)
        self.game.prepare_turn()
        self.assertEqual(self.left.team_statuses, {"限制": 1})

    def test_play_from_deck_keeps_the_team_active_without_counting_as_hand_play(self):
        self.game.start_turn()
        card = Card(self.left, dict(id="机操", name="机操", cost=0, dice=[]), self.b)
        self.left.cardspace.draw.add_card(card)
        self.a.add_status("限制", 2)
        self.assertTrue(self.game.place_in_duel(1, card, 0))
        self.assertFalse(self.game.turn_history.hand_plays)
        self.game.finish_turn()
        self.game.prepare_turn()
        self.assertEqual(self.left.team_statuses, {"限制": 2})


class SharedStatusTests(unittest.TestCase):

    def test_focus_compares_both_balances_and_shares_one_turn_quota(self):
        ctx, actor = holder()
        actor.add_status("能源", 2)
        actor.add_status("凝聚", 2)
        self.assertEqual(actor.statuses["能源"], 2)
        actor.add_status("凝聚", 2)
        self.assertEqual(actor.statuses["能源"], 3)
        ctx.dispatch_pipeline("on_turn_limits_reset", source=actor)
        self.assertEqual(actor.statuses["能源"], 3)
        ctx.turn_entry_uses.clear()
        ctx.dispatch_pipeline("on_turn_limits_reset", source=actor)
        self.assertEqual(actor.statuses["能源"], 4)

    def test_burn_resolves_damage_then_reduces_stacks_even_if_shielded(self):
        for count in (1, 3, 4, 12, 20):
            for shield in (0, 99):
                with self.subTest(count=count, shield=shield):
                    ctx, actor = holder()
                    actor.add_status("烧伤", count)
                    actor.shield = shield
                    ctx.operations.clear()
                    ctx.dispatch_pipeline("on_character_turn_end", source=actor, target=actor)
                    path = [op for op in ctx.operations if op in (OpCode.ACTIVATE_STATUS, OpCode.DAMAGE, OpCode.STATUS)]
                    expected = [OpCode.ACTIVATE_STATUS, OpCode.DAMAGE, OpCode.STATUS] if count >= 4 else []
                    self.assertEqual(path, expected)
                    damage = min(3, count // 4)
                    self.assertEqual(actor.statuses.get("烧伤", 0), count - (count // 4 + 2) if count >= 4 else count)
                    self.assertEqual(actor.hp, actor.max_hp - max(0, damage - shield))
                    self.assertEqual(ctx.stack, [])

    def test_ignite_reads_and_debits_the_selected_target_even_below_four_stacks(self):
        for count in (1, 3, 4, 20):
            with self.subTest(count=count):
                ctx, target = holder()
                source = actor_for(ctx, 2)
                source.statuses["烧伤"] = 8
                target.add_status("烧伤", count)
                ctx.operations.clear()
                resolve_entry(ctx, source, {"trigger": "on_dice_hit", "operation": {"keyword": "ignite"}},
                              source=source, target=target)
                self.assertEqual(ctx.operations.count(OpCode.ACTIVATE_STATUS), 1)
                self.assertEqual(ctx.operations.count(OpCode.DAMAGE), int(count >= 4))
                self.assertEqual(target.hp, target.max_hp - min(3, count // 4))
                self.assertEqual(target.statuses.get("烧伤", 0), max(0, count - count // 4 - 2))
                self.assertEqual(source.statuses["烧伤"], 8)
                self.assertEqual(ctx.stack, [])

    def test_bleed_compares_its_own_layers_before_duel_damage(self):
        for stacks in (1, 2, 3, 6, 9):
            ctx, actor = holder()
            actor.add_status("裂血", stacks)
            actor.shield = 3
            ctx.operations.clear()
            ctx.dispatch_pipeline("on_character_duel_start", source=actor, target=actor)
            self.assertEqual(ctx.operations.count(OpCode.DAMAGE), int(stacks >= 3))
            self.assertEqual(actor.hp, actor.max_hp - int(stacks >= 3))

    def test_fatal_stagger_charges_only_once_per_round_even_on_full_absorption(self):
        ctx, actor = holder()
        actor.shield = 20
        actor.add_status("致命失衡", 2)
        ctx.operations.clear()
        for amount in (0, 1, 1):
            actor.take_damage(amount)
        self.assertEqual(actor.shield, 16)
        self.assertEqual(actor.hp, actor.max_hp)
        self.assertEqual(actor.statuses["致命失衡"], 1)
        self.assertEqual(ctx.operations.count(OpCode.ROUND_TRIGGER_COUNT), 2)
        self.assertEqual(ctx.operations.count(OpCode.RECORD_ROUND_TRIGGER), 1)
        actor.begin_dice_round()
        actor.take_damage(1)
        self.assertNotIn("致命失衡", actor.statuses)
        self.assertEqual(ctx.operations.count(OpCode.RECORD_ROUND_TRIGGER), 2)
