"""Execution-path and boundary regression tests for the modernized WAA East Four pack."""

import io
import random
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from entry.compiler import compile_program
from game import Game
from loader import load_characters_from_packs
from models.card import Card
from models.character import Character
from models.opcode import OpCode
from player.player import Player


class WaaEastFourTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.roster = {spec["name"]: spec for spec in load_characters_from_packs()
                      if spec.get("faction") == "WAA东部四科"}

    def setUp(self):
        self.log = self.enterContext(redirect_stdout(io.StringIO()))
        self.left, self.right = Player(1, "WAA"), Player(2, "陪练方")
        self.game = Game([self.left, self.right], rng=random.Random(17))
        self.game.first_player = self.left
        self.enemy = self.recruit(self.right, dict(id="dummy", name="陪练", rank="NORMAL", max_hp=60, skills=[]))

    @staticmethod
    def recruit(player, data):
        actor = Character(data, player)
        player.characters.append(actor)
        actor.init_cards()
        actor.setup_deck()
        return actor

    def team(self, *names):
        actors = [self.recruit(self.left, self.roster[name]) for name in names]
        self.game.start_turn()
        return actors

    def use(self, actor, skill_name, *, opposing_dice=0, slot=0):
        card = next(card for card in actor.skills if card.name == skill_name)
        self.assertTrue(self.game.place_in_duel(actor.player.side, card, slot))
        if opposing_dice:
            dice = [dict(type="slash", level=1, base_value=-10, entries=[]) for _ in range(opposing_dice)]
            opponent = Card(self.right, dict(id=f"opp_{slot}", name="对练", cost=0, dice=dice), self.enemy)
            self.enemy.skills.append(opponent)
            self.assertTrue(self.game.place_in_duel(self.right.side, opponent, slot))
        self.game.reveal_cards()
        self.game.pipeline.start_duel_combat()
        with patch.object(self.game.rng, "randint", return_value=1):
            for _ in range(800):
                if self.game.is_over or not self.game.pipeline.in_duel_phase:
                    break
                self.game.next_step()
        self.assertFalse(self.game.pipeline.in_duel_phase)
        self.assertIn(card, self.game.used_cards)
        return card

    def next_turn(self):
        self.game.finish_turn()
        self.game.context.dispatch_pipeline("on_turn_end")
        self.game.start_turn()

    def test_pack_loads_and_compiles_all_three_characters_without_legacy_syntax(self):
        self.assertEqual(set(self.roster), {"莱克", "格罗琳娜", "厄尔克斯"})
        for name, spec in self.roster.items():
            self.assertEqual(spec["faction"], "WAA东部四科")
            self.assertEqual(spec["rank"], "NORMAL")
            self.assertEqual(len(spec["skills"]), 3, name)
            for status_name in ("充能", "纯能", "能源封印"):
                self.assertIn(status_name, spec["status_rules"])
            for entries in spec["status_entries"].values():
                for entry in entries:
                    op = entry.get("operation")
                    if isinstance(op, dict) and op.get("op") == "program":
                        compile_program(op["code"])

    def test_faction_passive_triggers_once_per_upward_crossing_of_three_cards(self):
        lake, grolina, erkes = self.team("莱克", "格罗琳娜", "厄尔克斯")
        self.left.draw_card(2)
        self.assertEqual([c.statuses.get("充能", 0) for c in (lake, grolina, erkes)], [0, 0, 0])
        self.left.draw_card(1)
        self.left.draw_card(1)
        # Crossing from 2 -> 3 triggers once for all three allies; 3 -> 4 does not re-trigger.
        self.assertEqual([c.statuses.get("充能") for c in (lake, grolina, erkes)], [1, 1, 1])

        # Drop below 3 and cross again -> triggers a second time.
        for _ in range(2):
            self.game.context.eval_block([self.left, self.left.cardspace.hand.content[0], OpCode.DISCARD])
        self.assertEqual(len(self.left.cardspace.hand.content), 2)
        self.left.draw_card(1)
        self.assertEqual([c.statuses.get("充能") for c in (lake, grolina, erkes)], [2, 2, 2])
        self.assertNotIn("充能", self.enemy.statuses)

    def test_lake_assault_contract_finisher_and_adaptability_duel_bonus(self):
        # 突击攻击 at full HP: slot 0 (+2 final from 突击), wins clash on evade -> draws 1 & +1 next_turn_duels, plus 1 from 应变 (no win? Wait: evade win counts as clash win).
        lake, = self.team("莱克")
        card = self.use(lake, "突击攻击", opposing_dice=2, slot=0)
        self.assertEqual(card.final_bonus, 2)
        self.assertEqual(lake.statuses, {"充能": 2, "强壮": 2})
        self.assertEqual(len(self.left.cardspace.hand.content), 1)
        self.next_turn()
        self.assertEqual(lake.max_duels, 2)
        self.assertNotIn("强壮", lake.statuses)

        # 突击攻击 when injured: heals 1 instead of drawing / +1 duel.
        self.setUp()
        lake, = self.team("莱克")
        lake.hp -= 2
        self.use(lake, "突击攻击", opposing_dice=2, slot=0)
        self.assertEqual(lake.hp, 5)
        self.assertEqual(len(self.left.cardspace.hand.content), 0)
        self.next_turn()
        self.assertEqual(lake.max_duels, 1)

        # 执行委托: d10 block, spends 1 charge for +1 damage on die 4.
        self.setUp()
        lake, = self.team("莱克")
        card = self.use(lake, "执行委托", opposing_dice=1, slot=0)
        self.assertEqual(card.instantiated_dice[0].roll_max, 10)
        self.assertEqual((lake.statuses.get("充能"), self.enemy.hp), (1, 57))

        # 猛烈斩杀: 16 charge -> +5 final (capped) + 2 from slot 0 = 7; +2 level (capped); unopposed -> 应变 grants +1 duel.
        self.setUp()
        lake, ally = self.team("莱克", "格罗琳娜")
        lake.add_status("充能", 16)
        card = self.use(lake, "猛烈斩杀", slot=0)
        self.assertEqual((card.final_bonus, card.level_bonus), (7, 2))
        self.assertEqual((lake.statuses.get("充能"), self.enemy.hp), (1, 57))
        self.next_turn()
        self.assertEqual((lake.statuses.get("充能"), ally.statuses.get("充能")), (3, 2))
        self.assertEqual(self.enemy.statuses.get("虚弱"), 1)
        self.assertEqual(lake.max_duels, 2)

    def test_grolina_speed_advance_delay_quick_and_opportunity(self):
        # 快速行动 & 阻滞: faster player -> +1 skill final, +2 level on evade die.
        grolina, = self.team("格罗琳娜")
        self.left.speed, self.right.speed = 3.5, 3
        grolina.add_status("充能", 3)
        card = self.use(grolina, "阻滞", opposing_dice=1, slot=0)
        self.assertEqual(card.final_bonus, 1)
        self.assertEqual([die.final_bonus for die in card.instantiated_dice], [0, 1])
        self.assertEqual(card.instantiated_dice[0].roll_max, 12)
        self.assertEqual(grolina.statuses.get("充能"), 6)
        self.next_turn()
        self.assertEqual((self.enemy.statuses.get("束缚"), self.enemy.statuses.get("虚弱")), (1, 1))

        # 推进输出: slot 1 with no loss in slot 0 -> +1 level & +1 charge; with a loss in slot 0 -> neither.
        self.setUp()
        grolina, = self.team("格罗琳娜")
        card = self.use(grolina, "快进", slot=1)
        self.assertEqual(card.level_bonus, 1)
        self.assertEqual(grolina.statuses.get("充能"), 1)
        self.next_turn()
        self.assertEqual(grolina.statuses.get("迅捷"), 1)
        self.game.record_clash_result(grolina, "lose")
        card = self.use(grolina, "快进", slot=1)
        self.assertEqual(card.level_bonus, 0)
        self.assertEqual(grolina.statuses.get("充能"), 1)

        # 借机: 16 charge -> +3 final, spend 4 on die 3 (+2 dmg), then dump remaining 12 -> +3 team charge.
        self.setUp()
        grolina, ally = self.team("格罗琳娜", "厄尔克斯")
        grolina.add_status("充能", 16)
        card = self.use(grolina, "借机", slot=0)
        self.assertEqual(card.final_bonus, 3)
        self.assertEqual(self.enemy.hp, 56)
        self.assertEqual(len(self.left.cardspace.hand.content), 1)
        self.assertEqual((grolina.statuses.get("充能"), ally.statuses.get("充能")), (3, 3))
        self.next_turn()
        self.assertEqual(self.left.max_cost, 6)

        # 借机 with 能源封印: spend on die 3 is blocked (0 spent), +2 damage still applies? Wait: in legacy test, 16 charge with seal still added +2 because POP 0 returned 0 without cancelling.
        self.setUp()
        grolina, = self.team("格罗琳娜")
        grolina.add_status("充能", 16)
        grolina.add_status("能源封印", 1)
        card = self.use(grolina, "借机", slot=0)
        self.assertEqual(self.enemy.hp, 56)
        self.assertEqual(grolina.statuses.get("充能"), 16)
        self.assertEqual(card.use_state.get("spent_statuses", {}), {})

    def test_erkes_pure_battery_diffusion_surcharge_seal_and_burst(self):
        # 能源逸散: 3 pure energy -> surcharge +1 on 充能 spend (4 -> 5), pure drops 3->2 on after_skill_use so diffusion grants self +1 充能!
        erkes, ally = self.team("厄尔克斯", "莱克")
        erkes.hp -= 1
        erkes.add_status("充能", 8)
        erkes.add_status("纯能", 3)
        card = self.use(erkes, "能源逸散", opposing_dice=1, slot=0)
        self.assertEqual(card.final_bonus, 2)
        self.assertEqual((erkes.hp, self.enemy.hp, self.enemy.statuses.get("虚弱")), (9, 57, 2))
        self.assertEqual(erkes.statuses, {"充能": 8, "纯能": 1})
        self.assertEqual(ally.statuses.get("充能"), 2)

        # 武器增压迸发 with 8 charge & 5 pure: +4 final, die 2 +2 level, die 3 repeats 3 times (4 hits total).
        self.setUp()
        erkes, ally = self.team("厄尔克斯", "格罗琳娜")
        self.left.max_cost = 10
        self.left.cost = 10
        erkes.add_status("充能", 8)
        erkes.add_status("纯能", 9)
        self.assertEqual(erkes.statuses.get("纯能"), 5)
        card = self.use(erkes, "武器增压迸发", slot=0)
        self.assertEqual(card.final_bonus, 4)
        self.assertEqual([die.position for die in card.instantiated_dice], [1, 2, 3, 3, 3, 3])
        self.assertEqual(card.instantiated_dice[1].roll_max, 12)
        self.assertEqual(card.use_state["spent_charge"], 8)
        # Pure drops 5 -> 4 -> 3 -> 2; 3rd repeat drops 3 -> 2 so Erkes receives 1 charge from that diffusion!
        self.assertEqual((self.enemy.hp, ally.statuses.get("充能")), (49, 3))
        self.assertEqual(erkes.statuses, {"纯能": 2, "充能": 1})

        # 武器增压迸发 with 7 charge & 2 pure: gains 1 pure (to 3), drains 7 charge, applies 能源封印 before die 1.
        self.setUp()
        erkes, = self.team("厄尔克斯")
        self.left.max_cost = 10
        self.left.cost = 10
        erkes.add_status("充能", 7)
        erkes.add_status("纯能", 2)
        first_die = []
        self.game.context.register_entries(erkes, [{
            "trigger": "before_dice_use",
            "operation": lambda ctx: first_die.append((dict(erkes.statuses), ctx.event["card"].use_state.get("spent_charge", 0), ctx.event["card"].final_bonus))
            if ctx.event["die"].position == 1 else None,
        }])
        card = self.use(erkes, "武器增压迸发", slot=0)
        self.assertEqual(first_die, [({"纯能": 3, "能源封印": 1}, 7, 2)])
        self.assertEqual([die.position for die in card.instantiated_dice], [1, 2, 3])
        self.assertEqual(self.enemy.hp, 54)
        # Unlock 能源封印 when charge reaches 8.
        erkes.add_status("纯能", -3)
        erkes.add_status("充能", 8)
        self.assertNotIn("能源封印", erkes.statuses)


if __name__ == "__main__":
    unittest.main()
