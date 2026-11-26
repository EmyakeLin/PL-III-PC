"""The table and its bots read the same current hand restriction as skill payment."""
import unittest

from battle_mcp.bot import choose_move
from battle_mcp.challenges import CHALLENGES
from battle_mcp.engine import ArenaEngine
from battle_ui.session import BattleSession
from displayer import hand_key
from models.card import Card


class RestrictedHandPlayTests(unittest.TestCase):
    def opening(self, opponent):
        engine = ArenaEngine(("plan_b_annolin", opponent), seed=7)
        while not engine.required_sides():
            engine.advance()
        self.assertEqual(engine.required_sides(), [2])
        return engine, engine.game.players[1].characters[0]

    def test_current_restriction_and_lowest_cost_exception_reach_each_policy(self):
        for opponent in ("witness_residue", "lan_qing"):
            engine, actor = self.opening(opponent)
            hand = actor.player.cardspace.hand.content
            for stacks in (len(hand), len(hand) + 1, 0):
                actor.add_status("限制", stacks - actor.statuses.get("限制", 0))
                frame, moves = engine.state(2), engine.options(2)
                offered = [m for m in moves if m["kind"] in ("place", "end")]
                self.assertEqual(len(offered), len(hand) + 1)  # Humans may commit any of them.
                prices = [c.cost for c in hand]
                allowed = {hand_key(c) for c in hand if not stacks or c.cost == min(prices)}
                visible = frame["players"][1]["hand"]
                self.assertEqual({c["action_key"] for c in visible if not c["use_restricted"]}, allowed)
                self.assertIsNone(engine.state(1)["players"][1]["hand"])
                for policy in (choose_move, CHALLENGES[opponent].choose_move):
                    with self.subTest(opponent=opponent, stacks=stacks, policy=policy):
                        move = policy(frame, offered)
                        # The general policy holds pre-reveal attacks until that window.
                        reserve_only = policy is choose_move and all(c["pre_reveal"] for c in visible
                                                                     if c["action_key"] in allowed)
                        if not allowed or reserve_only:
                            self.assertEqual(move["kind"], "end")
                        else:
                            self.assertIn(move.get("card_id"), allowed)

    def test_same_printing_rechecks_instances_for_play_but_allows_discard(self):
        engine, actor = self.opening("witness_residue")
        zone = actor.player.cardspace.hand
        first = max(zone.content, key=lambda c: c.cost)
        second = Card(actor.player, first.data, actor)
        zone.add_card(second)
        actor.add_status("限制", 1)
        frame = engine.state(2)
        policies = (choose_move, CHALLENGES["witness_residue"].choose_move)
        self.assertNotEqual(hand_key(first), hand_key(second))
        for mode, kind, fallback in (("placement", "place", "end"), ("pre_reveal", "attack", "end_attack"),
                                     ("pre_reveal", "intercept", "let_through"),
                                     ("instant_response", "special_intercept", "special_pass_intercept")):
            blocked, available = (dict(kind=kind, card_id=hand_key(c), response_number=1) for c in (first, second))
            skip = dict(kind=fallback, response_number=1)
            for policy in policies:
                with self.subTest(kind=kind, policy=policy):
                    state = {**frame, "mode": mode}
                    self.assertIs(policy(state, [blocked, available, skip]), available)
                    self.assertIs(policy(state, [blocked, skip]), skip)
        discard = dict(kind="special_choose_card", target_card_id=hand_key(first), effect_target={})
        for policy in policies:
            self.assertIs(policy({**frame, "mode": "skill_choice"}, [discard]), discard)

        placement = next(m for m in engine.options(2) if m["kind"] == "place" and m["card_id"] == hand_key(second))
        engine.apply(2, placement)
        remaining = next(c for c in engine.state(2)["players"][1]["hand"] if c["id"] == first.id)
        self.assertEqual((remaining["action_key"], remaining["use_restricted"]), (first.id, True))

    def test_local_ai_plays_lowest_cost_at_equal_restriction(self):
        session = BattleSession(seed=7, roster=("plan_b_annolin", "witness_residue"))
        match = session.match
        player = match.game.placing
        match.act("ready", match.revision, side=player.side)
        player.characters[0].add_status("限制", len(player.cardspace.hand.content))
        session.ai_side = player.side
        before = list(player.cardspace.hand.content)
        self.assertTrue(session._ai_step(match.snapshot()))
        played, = set(before) - set(player.cardspace.hand.content)
        self.assertEqual(played.cost, min(c.cost for c in before))
