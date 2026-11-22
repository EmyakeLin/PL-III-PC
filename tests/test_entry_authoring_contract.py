"""Exercise the entry shown in the author guide and the primitives behind it."""
import itertools
import json
import unittest
from pathlib import Path

from models.card import Card
from models.dice import Dice
from models.opcode import OpCode
from player.card_space import CardSpace
from tests.test_entry_execution_paths import TraceContext, actor_for, resolve_entry


GUIDE = Path(__file__).resolve().parents[1] / "docs" / "词条与内核开发规范.md"


def guide_example(name):
    marker = f"<!-- example: {name} -->\n```json\n"
    _, found, example = GUIDE.read_text(encoding="utf-8").partition(marker)
    if not found:
        raise ValueError(f"开发规范缺少示例 {name!r}")
    return json.loads(example.split("\n```", 1)[0])


class EntryAuthoringTests(unittest.TestCase):
    def test_documented_hits_count_even_on_an_empty_draw_pile(self):
        ctx = TraceContext()
        owner, opponent = actor_for(ctx, 1), actor_for(ctx, 2)
        ctx.game = owner.game
        ctx.game.players = [owner.player, opponent.player]
        zones = owner.player.cardspace = CardSpace(owner.player)
        ctx.register_entries(owner, [guide_example("round-draw")])

        def hit(source, target):
            card = Card(source.player, {"id": "sample", "name": "样本", "cost": 0}, source)
            die = Dice({"type": "slash", "level": 1})
            die.card = card
            ctx.operations.clear()
            ctx.dispatch_pipeline("on_dice_hit", source=source, target=target, card=card, die=die,
                                  side=source.player.side)
            return tuple(ctx.operations)

        check = (OpCode.ROUND_TRIGGER_COUNT, OpCode.LT, OpCode.WHEN)
        award = (*check, OpCode.RECORD_ROUND_TRIGGER, OpCode.DRAW)
        self.assertEqual(hit(opponent, owner), ())
        self.assertEqual(hit(owner, opponent), award)
        self.assertEqual(owner.round_triggers["回响"], 1)
        self.assertEqual(zones.hand.content, [])

        cards = [Card(owner.player, {"id": str(n), "name": str(n), "cost": 0}, owner) for n in range(2)]
        zones.draw.content.extend(cards)
        self.assertEqual(hit(owner, opponent), award)
        self.assertEqual(hit(owner, opponent), check)
        self.assertEqual(owner.round_triggers["回响"], 2)
        self.assertEqual(zones.hand.content, cards[:1])
        owner.begin_dice_round()
        self.assertEqual(hit(owner, opponent), award)
        self.assertEqual(owner.round_triggers["回响"], 1)
        self.assertEqual(zones.hand.content, cards)

    def test_counter_queries_leave_counts_intact_for_any_limit_holder_and_key(self):
        ctx = TraceContext()
        actors = [actor_for(ctx, side) for side in (1, 2)]
        keys = ("回响", "another counter")
        for used, limit, holder, key in itertools.product((0, 1, 2, 10**12), (0, 1, 2, 3, 10**12 + 1), actors, keys):
            with self.subTest(used=used, limit=limit, side=holder.player.side, key=key):
                for actor in actors:
                    actor.begin_dice_round()
                if used:
                    holder.round_triggers[key] = used
                initial = [dict(actor.round_triggers) for actor in actors]
                for _ in range(2):
                    ctx.eval_block([holder, key, OpCode.ROUND_TRIGGER_COUNT, limit, OpCode.LT])
                    self.assertEqual(ctx.pop(), used < limit)
                    self.assertEqual([dict(actor.round_triggers) for actor in actors], initial)
                ctx.eval_block([holder, key, OpCode.RECORD_ROUND_TRIGGER])
                for actor, counts in zip(actors, initial):
                    expected = {**counts, key: used + 1} if actor is holder else counts
                    self.assertEqual(dict(actor.round_triggers), expected)
                self.assertEqual(ctx.stack, [])

    def test_cap_status_matches_explicit_settlement_including_the_status_event(self):
        short = "CAP_STATUS $event.target $event.key $event.cap"
        expanded = {"op": "program", "code": [
            "$event.target", "$event.key", "STATUS_COUNT", "$event.cap", "GT",
            ["$event.target", "$event.key", "$event.cap", "$event.target", "$event.key",
             "STATUS_COUNT", "SUB", "STATUS"], "WHEN",
        ]}
        for key, stacks, cap in itertools.product(("资源甲", "resource_b"), (0, 1, 5, 10**12), (0, 1, 4, 10**12)):
            for operation in (short, expanded):
                with self.subTest(key=key, stacks=stacks, cap=cap, operation=operation):
                    ctx = TraceContext()
                    owner, target = actor_for(ctx, 1), actor_for(ctx, 2)
                    target.statuses[key] = stacks
                    owner.statuses[key] = 7
                    changes = []

                    def read_change(vm):
                        event = vm.event
                        changes.append((event["source"], event["target"], event["status"], event["actual_delta"]))

                    ctx.register_entries(None, [{"trigger": "AFTER STATUS", "operation": read_change}])
                    resolve_entry(ctx, owner, {"trigger": "on_dice_hit", "operation": operation},
                                  source=owner, target=target, key=key, cap=cap)
                    self.assertEqual(changes, [(owner, target, key, cap - stacks)] if stacks > cap else [])
                    self.assertEqual(ctx.operations.count(OpCode.STATUS), int(stacks > cap))
                    self.assertEqual(target.statuses.get(key, 0), min(stacks, cap))
                    self.assertEqual(owner.statuses[key], 7)
                    self.assertEqual(ctx.stack, [])
