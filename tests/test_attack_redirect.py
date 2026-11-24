"""Semantic tests for explicit attack redirection (REDIRECT_ATTACK & before_attack_target)."""
import io
import random
import unittest
from contextlib import redirect_stdout

from game import Game
from models.card import Card
from models.character import Character
from models.opcode import OpCode
from models.special_actions import SpecialAction
from player.player import Player
from tests.test_entry_execution_paths import TraceContext


class FixedRng:
    def __init__(self, value=3):
        self.value = value

    def randint(self, low, high):
        return max(low, min(high, self.value))


class AttackRedirectTests(unittest.TestCase):
    def _setup_game(self, *, left_chars, right_chars, rng_val=3):
        self.enterContext(redirect_stdout(io.StringIO()))
        left, right = Player(1, "甲"), Player(2, "乙")
        game = Game([left, right], rng=FixedRng(rng_val))
        trace = TraceContext()
        trace.game = game
        game.context = trace
        game.first_player = left
        for side_player, specs in ((left, left_chars), (right, right_chars)):
            for spec in specs:
                char = Character(spec, side_player)
                side_player.characters.append(char)
                char.init_cards()
                char.setup_deck()
        game.start_turn()
        left.max_cost = right.max_cost = 20
        return game, left, right

    @staticmethod
    def _run_to_turn_end(game, *, decisions=()):
        decided = list(decisions)
        game.pipeline.start_duel_combat()
        for _ in range(400):
            if game.is_over or not game.pipeline.in_duel_phase:
                break
            owner = game.special.decision_owner
            if owner is not None:
                action = decided.pop(0) if decided else game.special.options(owner)[0]
                game.special.apply(owner, action)
                continue
            game.next_step()

    def test_ally_guard_redirects_one_sided_attack_then_uses_standard_respond_to_die(self):
        guard_skill = {
            "id": "guard_counter",
            "name": "重盾顶退",
            "cost": 0,
            "out_of_combat": True,
            "dice": [{"type": "blunt", "level": 1, "entries": ["1物理"]}],
        }
        guard_passives = [
            {
                "name": "转火援护",
                "entries": [
                    {
                        "trigger": "before_attack_target",
                        "subject": "any",
                        "when": [
                            {"left": "$event.target.player", "op": "eq", "right": "$self.player"},
                            {"left": "$event.target", "op": "ne", "right": "$self"},
                            {"left": "$self.shield", "op": "ge", "right": 2},
                        ],
                        "operation": {
                            "op": "program",
                            "code": [
                                {
                                    "literal": {
                                        "title": "转火替友方接敌",
                                        "optional": True,
                                        "options": [
                                            {
                                                "id": "redirect",
                                                "label": "消耗2护盾转火至自身",
                                                "then": {
                                                    "op": "program",
                                                    "code": [
                                                        "$self", "normal", -2, "SHIELD",
                                                        "$event.die", "$self", "REDIRECT_ATTACK",
                                                    ],
                                                },
                                            }
                                        ],
                                    }
                                },
                                "CHOOSE_OPTION",
                            ],
                        },
                    },
                    {
                        "name": "重盾迎击",
                        "entries": [
                            {
                                "trigger": "before_one_sided_attack",
                                "subject": "target",
                                "operation": {
                                    "op": "program",
                                    "code": [
                                        "$self", "$self.skill_data",
                                        ["$event.item.id", "guard_counter", "EQ"],
                                        "FILTER", "FIRST", "SKILL_COPY", "respond_to_die",
                                        "INSERT_SKILL",
                                    ],
                                },
                            }
                        ],
                    },
                ],
            }
        ]
        # Scenario A: Guard declines redirect -> respond_to_die (subject: target) does NOT fire for ally;
        # even if forced manually, respond_to_die strictly requires target == responder.
        game_no, left_no, right_no = self._setup_game(
            left_chars=[
                {"id": "attacker", "name": "攻手", "rank": "NORMAL", "max_hp": 20, "skills": []},
            ],
            right_chars=[
                {"id": "ji_xia", "name": "季夏", "rank": "ELITE", "max_hp": 18, "skills": []},
                {"id": "ji_lan", "name": "纪岚", "rank": "ELITE", "max_hp": 15, "skills": [guard_skill],
                 "passive_skills": guard_passives},
            ],
            rng_val=4,
        )
        ji_xia_no, ji_lan_no = right_no.characters
        ji_lan_no.shield = 2
        atk_card_no = Card(left_no, {"id": "atk", "name": "单突", "cost": 0,
                                     "dice": [{"type": "pierce", "level": 3, "entries": ["5物理"]}]},
                           left_no.characters[0])
        game_no.place_in_duel(left_no.side, atk_card_no, 0)
        game_no.reveal_cards()
        self._run_to_turn_end(game_no, decisions=[SpecialAction("decline_option")])
        self.assertEqual(ji_xia_no.hp, 13)
        self.assertEqual(ji_lan_no.hp, 15)
        self.assertEqual(ji_lan_no.shield, 2)

        # Scenario B: Guard accepts redirect -> REDIRECT_ATTACK updates target to 纪岚 ->
        # BEFORE_ONE_SIDED_ATTACK fires for 纪岚 -> 重盾顶退 clashes and takes the hit when losing clash.
        game_yes, left_yes, right_yes = self._setup_game(
            left_chars=[
                {"id": "attacker", "name": "攻手", "rank": "NORMAL", "max_hp": 20, "skills": []},
            ],
            right_chars=[
                {"id": "ji_xia", "name": "季夏", "rank": "ELITE", "max_hp": 18, "skills": []},
                {"id": "ji_lan", "name": "纪岚", "rank": "ELITE", "max_hp": 15, "skills": [guard_skill],
                 "passive_skills": guard_passives},
            ],
            rng_val=5,
        )
        ji_xia_yes, ji_lan_yes = right_yes.characters
        ji_lan_yes.shield = 2
        atk_card_yes = Card(left_yes, {"id": "atk", "name": "单突", "cost": 0,
                                       "dice": [{"type": "pierce", "level": 3, "entries": ["5物理"]}]},
                            left_yes.characters[0])
        game_yes.place_in_duel(left_yes.side, atk_card_yes, 0)
        game_yes.reveal_cards()
        with game_yes.context.collect_facts() as facts:
            self._run_to_turn_end(game_yes, decisions=[SpecialAction("choose_option", option_id="redirect")])
        self.assertEqual(ji_xia_yes.hp, 18)
        self.assertEqual(ji_lan_yes.shield, 0)
        self.assertEqual(ji_lan_yes.hp, 10)
        self.assertIn(OpCode.REDIRECT_ATTACK, game_yes.context.operations)
        self.assertTrue(any(kind == "attack_redirected" and data["old_target"] == "季夏" and data["target"] == "纪岚"
                            for kind, data in facts))
        self.assertTrue(any(kind == "skill_intercept" and data["target"] == "纪岚" and data["card"] == "重盾顶退"
                            for kind, data in facts))

    def test_taunt_redirects_clashing_and_solo_attacks_without_responding(self):
        taunt_passive = [
            {
                "name": "嘲讽",
                "entries": [
                    {
                        "trigger": "before_dice_pair",
                        "subject": "any",
                        "when": [
                            {"left": "$event.side", "op": "ne", "right": "$self.player.side"},
                            {"left": "$event.target", "op": "ne", "right": "$self"},
                        ],
                        "operation": {
                            "op": "program",
                            "code": ["$event.die", "$self", "REDIRECT_ATTACK"],
                        },
                    }
                ],
            }
        ]
        game, left, right = self._setup_game(
            left_chars=[{"id": "a1", "name": "甲", "rank": "NORMAL", "max_hp": 20, "skills": []}],
            right_chars=[
                {"id": "b1", "name": "乙前", "rank": "NORMAL", "max_hp": 20, "skills": []},
                {"id": "tank", "name": "铁盾", "rank": "NORMAL", "max_hp": 20, "skills": [],
                 "passive_skills": taunt_passive},
            ],
            rng_val=2,
        )
        b1, tank = right.characters
        atk = Card(left, {"id": "atk", "name": "斩", "cost": 0,
                          "dice": [{"type": "slash", "level": 2, "entries": ["4物理"]}]}, left.characters[0])
        defn = Card(right, {"id": "def", "name": "守", "cost": 0,
                            "dice": [{"type": "block", "level": 2}]}, b1)
        game.place_in_duel(left.side, atk, 0)
        game.place_in_duel(right.side, defn, 0)
        game.reveal_cards()
        self._run_to_turn_end(game)
        self.assertEqual(b1.hp, 20)
        self.assertEqual(tank.hp, 16)

    def test_stealth_redirects_to_ally_or_cancels_attack_when_alone(self):
        stealth_passive = [
            {
                "name": "隐匿",
                "entries": [
                    {
                        "trigger": "before_attack_target",
                        "subject": "target",
                        "operation": {
                            "op": "program",
                            "code": [
                                "$event.die",
                                "$self.player.characters",
                                [
                                    "$event.item.is_alive",
                                    "$event.item", "$self", "IS", "NOT",
                                    "AND",
                                ],
                                "FILTER", "FIRST",
                                "REDIRECT_ATTACK",
                            ],
                        },
                    }
                ],
            }
        ]
        # With an ally alive: attack redirects onto ally.
        game1, left1, right1 = self._setup_game(
            left_chars=[{"id": "a1", "name": "攻", "rank": "NORMAL", "max_hp": 20, "skills": []}],
            right_chars=[
                {"id": "stealthed", "name": "隐者", "rank": "NORMAL", "max_hp": 25, "skills": [],
                 "passive_skills": stealth_passive},
                {"id": "ally", "name": "同伴", "rank": "NORMAL", "max_hp": 15, "skills": []},
            ],
            rng_val=3,
        )
        stealthed, ally = right1.characters
        atk1 = Card(left1, {"id": "atk", "name": "刺", "cost": 0,
                            "dice": [{"type": "pierce", "level": 2, "entries": ["4物理"]}]}, left1.characters[0])
        game1.place_in_duel(left1.side, atk1, 0)
        game1.reveal_cards()
        self._run_to_turn_end(game1)
        self.assertEqual(stealthed.hp, 25)
        self.assertEqual(ally.hp, 11)

        # Alone: REDIRECT_ATTACK(die, None) cancels the attack without hitting.
        game2, left2, right2 = self._setup_game(
            left_chars=[{"id": "a1", "name": "攻", "rank": "NORMAL", "max_hp": 20, "skills": []}],
            right_chars=[
                {"id": "stealthed", "name": "隐者", "rank": "NORMAL", "max_hp": 25, "skills": [],
                 "passive_skills": stealth_passive},
            ],
            rng_val=3,
        )
        solo_stealthed = right2.characters[0]
        atk2 = Card(left2, {"id": "atk", "name": "刺", "cost": 0,
                            "dice": [{"type": "pierce", "level": 2, "entries": ["4物理"]}]}, left2.characters[0])
        game2.place_in_duel(left2.side, atk2, 0)
        game2.reveal_cards()
        self._run_to_turn_end(game2)
        self.assertEqual(solo_stealthed.hp, 25)

    def test_redirect_attack_respects_anti_redirect_cancellation_and_invalid_targets(self):
        anti_redirect = {
            "name": "精准锁定",
            "entries": [
                {
                    "trigger": "BEFORE REDIRECT_ATTACK",
                    "subject": "any",
                    "when": [{"left": "$event.attacker", "op": "eq", "right": "$self"}],
                    "operation": {"op": "cancel"},
                }
            ],
        }
        try_taunt = {
            "name": "强拉",
            "entries": [
                {
                    "trigger": "before_attack_target",
                    "subject": "any",
                    "when": [{"left": "$event.target", "op": "ne", "right": "$self"}],
                    "operation": {"op": "program", "code": ["$event.die", "$self", "REDIRECT_ATTACK"]},
                }
            ],
        }
        game, left, right = self._setup_game(
            left_chars=[{"id": "a1", "name": "锁敌手", "rank": "NORMAL", "max_hp": 20, "skills": [],
                         "passive_skills": [anti_redirect]}],
            right_chars=[
                {"id": "pri", "name": "高血", "rank": "NORMAL", "max_hp": 25, "skills": []},
                {"id": "sec", "name": "低血", "rank": "NORMAL", "max_hp": 15, "skills": [],
                 "passive_skills": [try_taunt]},
            ],
            rng_val=3,
        )
        pri, sec = right.characters
        atk = Card(left, {"id": "atk", "name": "狙击", "cost": 0,
                          "dice": [{"type": "pierce", "level": 2, "entries": ["4物理"]}]}, left.characters[0])
        game.place_in_duel(left.side, atk, 0)
        game.reveal_cards()
        self._run_to_turn_end(game)
        self.assertEqual(pri.hp, 21)
        self.assertEqual(sec.hp, 15)

        # Same-side or dead target is rejected directly by handle_redirect_attack.
        ctx = game.context
        from models.dice import Dice
        test_die = Dice({"type": "slash", "level": 2})
        test_die.card = atk
        ctx.stack.extend((test_die, left.characters[0]))
        self.assertFalse(ctx.execute_op(OpCode.REDIRECT_ATTACK))
        pri.is_alive = False
        ctx.stack.extend((test_die, pri))
        self.assertFalse(ctx.execute_op(OpCode.REDIRECT_ATTACK))
