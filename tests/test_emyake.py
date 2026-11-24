"""Exercise Emyake's printed programs on physical cards and actual combat rounds."""
import random
import unittest
from unittest.mock import patch

from battle_mcp.challenges import CHALLENGES
from battle_ui.match import BattleMatch
from displayer import Displayer
from entry.entry import Entry
from game import Game
from loader import load_characters_from_packs
from models.card import Card
from models.character import Character
from models.opcode import OpCode
from player.player import Player


class EmyakeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = next(s for s in load_characters_from_packs() if s["id"] == "emyake_lin_yu")

    def setUp(self):
        self.left, self.right = Player(1, "林羽方"), Player(2, "陪练方")
        self.game = Game([self.left, self.right], rng=random.Random(151))
        self.game.first_player = self.left
        dummy = dict(id="dummy", name="陪练", rank="NORMAL", max_hp=100, skills=[])
        self.game.deploy_rosters([[self.spec], [dummy]])
        self.actor, self.enemy = self.left.characters[0], self.right.characters[0]
        self.ctx = self.game.context
        self.game.start_turn()
        self.cards = {c.name: c for c in self.actor.skills}
        self.events = []
        self.ctx.record = lambda event, **data: self.events.append((event, data))

    def status(self, holder, name, balance):
        change = balance - holder.statuses.get(name, 0)
        if change:
            self.ctx.eval_block([holder, name, change, OpCode.STATUS])

    def opposition(self, scores, **traits):
        dice = [dict(type="slash", level=1, calc_formula=str(v), entries=[]) for v in scores]
        return Card(self.right, dict(id="opponent", name="对练", cost=0, dice=dice, **traits), self.enemy)

    def fight(self, name, scores=(), *, choose=None, **traits):
        card = self.cards[name]
        self.assertTrue(self.game.place_in_duel(1, card, 0))
        if scores:
            self.assertTrue(self.game.place_in_duel(2, self.opposition(scores, **traits), 0))
        self.start_duel(choose)
        return card

    def start_duel(self, choose=None):
        self.game.reveal_cards()
        self.game.pipeline.start_duel_combat()
        self.run_duel(choose)

    def run_duel(self, choose=None):
        for _ in range(2000):
            if not self.game.pipeline.in_duel_phase:
                return
            pending = self.game.special.option_decision
            if pending:
                self.assertEqual(self.game.next_step(), "wait_option_choice")
                options = self.game.special.options(pending.player)
                wanted = choose(pending) if choose else None
                action = next((o for o in options if wanted is not None and o.option_id == wanted), None)
                if action is None:
                    action = next((o for o in options if o.kind == "decline_option"), options[0])
                self.game.special.apply(pending.player, action)
            elif pending_card := self.game.special.card_decision:
                options = self.game.special.options(pending_card.player)
                self.game.special.apply(pending_card.player, options[-1])
            else:
                self.game.next_step()
        self.fail("交锋未能结束")

    def test_roster_and_all_printed_programs(self):
        self.assertEqual((self.actor.max_hp,self.actor.statuses["铭刻"]), (12,3))
        self.assertEqual((len(self.left.cardspace.draw.content),len(self.left.cardspace.out_of_combat.content)),(11,1))
        for card in self.cards.values():
            for face in (card.data, *card.data.get("forms", {}).values()):
                for raw in face.get("entries",()):
                    Entry.from_spec(card, raw)
                for data in face["dice"]:
                    die = self.game.init_dice(data)
                    die.card = card
                    for raw in data.get("entries",()):
                        if isinstance(raw,dict):
                            Entry.from_spec(die,raw)
                    self.assertIn(data["printed_text"],card.describe())

    def test_phantom_per_confirmed_hit_and_actual_spend(self):
        cases = [([100,100,-1],0,'pay',0), ([-1,100,-1],1,'pay',1),
                 ([-1,-1,-1],2,'pay',2), ([-1,-1,-1],2,'one',1),
                 ([-1,-1,-1],2,None,0), ([-1,-1,1000],2,'pay',0)]
        for scores,hits,choice,paid in cases:
            with self.subTest(scores=scores,choice=choice):
                self.setUp()
                self.status(self.actor,'铭刻',6)
                card=self.fight('流华幻影',scores,choose=lambda _:choice,ignore_range=3)
                last_hit=scores[2]<0
                self.assertEqual(card.use_state.get('前骰命中',0),hits)
                self.assertEqual(self.actor.statuses['铭刻'],6-paid)
                self.assertEqual(100-self.enemy.hp,hits+last_hit+paid)
                self.assertEqual(self.enemy.statuses.get('裂伤',0),2*hits+2*last_hit+paid)

    def test_folded_credit_and_shield_cleanup(self):
        self.status(self.actor,'羽流·终',4)
        self.status(self.actor,'铭刻',12)
        self.ctx.dispatch_pipeline('on_turn_start')
        self.assertEqual((self.actor.statuses['折影化铭刻'],self.actor.statuses['铭刻']),(4,14))
        self.ctx.eval_block([self.actor,'铭刻',2,OpCode.SPEND_STATUS])
        self.assertEqual(self.actor.turn_state['折影额度'],2)
        self.actor.add_shield('normal',4)
        self.actor.hp=8
        self.game.finish_turn()
        self.assertEqual((self.actor.shield,self.actor.hp),(3,9))
        self.assertEqual((self.actor.statuses['铭刻'],self.actor.statuses['折影化铭刻']),(10,4))
        self.game.start_turn()
        self.ctx.dispatch_pipeline('on_turn_start')
        self.assertEqual(self.actor.statuses['折影化铭刻'],8)
        self.assertEqual(self.actor.turn_state['折影额度'],8)

    def test_storage_rounding_damage_credit_and_restraint(self):
        self.status(self.actor,'羽流·延攻',2)
        self.status(self.enemy,'裂伤',8)
        die=self.cards['流华幻影'].get_current_die(self.game)
        self.ctx.stack.extend([self.enemy,5,'normal','slash'])
        self.ctx.execute_op(OpCode.DAMAGE,damage_die=die)
        self.assertEqual(self.enemy.rule_state['裂伤存伤'],140)
        self.ctx.eval_block([self.enemy,1,'pierce','none',OpCode.DAMAGE])
        self.assertEqual(self.enemy.rule_state['裂伤存伤'],140)
        self.status(self.enemy,'裂伤',20)
        self.status(self.enemy,'裂伤拘束',2)
        for _ in range(2):
            self.ctx.eval_block([self.enemy,'裂伤',5,OpCode.STATUS])
            self.assertEqual((self.enemy.statuses['裂伤'],self.enemy.statuses['裂伤拘束']),(24,1))
        self.enemy.begin_dice_round()
        self.ctx.eval_block([self.enemy,'裂伤',5,OpCode.STATUS])
        self.assertNotIn('裂伤拘束',self.enemy.statuses)
        self.ctx.eval_block([self.enemy,'裂伤',1,OpCode.STATUS])
        self.assertNotIn('裂伤',self.enemy.statuses)
        self.assertEqual((self.enemy.rule_state['裂伤存伤'],self.enemy.hp),(0,92))

    def test_card_target_and_character_target(self):
        card=self.cards['折影吞噬']
        self.left.cardspace.draw.move_card_to(card,self.left.cardspace.hand)
        target=self.opposition([1])
        self.game.place_in_duel(2,target,0)
        ally=Character(dict(id='ally',name='同伴',rank='NORMAL',max_hp=20,skills=[]),self.right)
        self.right.characters.append(ally)
        own,other=self.opposition([1]),self.opposition([1])
        other.character=ally
        for reply in (own,other):
            self.right.cardspace.hand.add_card(reply)
        phase=self.game.pre_reveal
        phase.start()
        duel=phase.declare_attack(card,character=self.enemy)
        self.assertEqual(phase.intercept_cards(self.right,1),[own])
        with self.assertRaises(ValueError):
            phase.intercept(other,1)
        phase.intercept(own,1)
        self.assertIs(duel.target_character,self.enemy)
        self.setUp()
        card=self.cards['折影吞噬']
        self.left.cardspace.draw.move_card_to(card,self.left.cardspace.hand)
        target=self.opposition([1])
        self.game.place_in_duel(2,target,0)
        phase=self.game.pre_reveal
        phase.start()
        duel=phase.declare_attack(card,duel_index=0)
        self.assertTrue(duel.ready)
        self.assertIs(duel.required_card,target)
        self.assertEqual(phase.pending_for(self.right),[])

    def test_flashback_paid_free_mandatory_and_declined(self):
        for marks,free,choice,uses,left in [(4,False,'counter',1,0),(4,False,None,0,4),
                        (13,False,None,1,9),(0,True,'free',0,0),(0,False,None,0,0)]:
            with self.subTest(marks=marks,free=free,choice=choice):
                self.setUp()
                self.status(self.actor,'铭刻',marks)
                self.actor.turn_state['纯粹之心迎击']=free
                self.game.place_in_duel(2,self.opposition([0]),0)
                self.start_duel(lambda _:choice)
                flashed=[e for k,e in self.events if k=='skill_used' and e['card']=='闪回识破']
                self.assertEqual(len(flashed),int(uses>0 or free))
                self.assertEqual(self.actor.turn_state.get('闪回识破次数',0),uses)
                self.assertEqual(self.actor.statuses.get('铭刻',0),left)
                if flashed:
                    self.assertGreaterEqual(self.enemy.statuses.get('裂伤',0),2)
                    self.assertNotIn('羽流·势',self.actor.statuses)
                    self.assertEqual(self.actor.statuses.get('羽流·制衡'),1)

    def test_folding_returns_exact_card_and_seals_next_turn(self):
        card=self.cards['折影吞噬']
        def face_turn():
            entry=dict(trigger='on_skill_use',operation={'op':'program','code':['$self','对练使用',1,'STATUS']})
            foe=self.opposition([-100],ignore_range=3,entries=[entry])
            self.game.place_in_duel(1,card,0)
            self.game.place_in_duel(2,foe,0)
            self.start_duel()
            return foe
        first=face_turn()
        self.assertIn(first,self.right.cardspace.out_of_combat.content)
        self.assertIn(card,self.left.cardspace.hand.content)
        self.game.finish_turn()
        self.game.start_turn()
        second=face_turn()
        self.assertEqual(self.enemy.statuses.get('对练使用'),1)
        self.assertIn(second,self.right.cardspace.out_of_combat.content)
        self.assertIs(self.right.cardspace.draw.content[-1],first)

    def test_sharp_heart_and_stance_results(self):
        for choice,stacks,used in [('hold',24,True),('allow',0,False)]:
            self.setUp()
            self.status(self.enemy,'裂伤',24)
            self.fight('羽流剑反',choose=lambda _:choice)
            self.assertEqual(self.enemy.statuses.get('裂伤',0),stacks)
            self.assertEqual(self.actor.turn_state.get('锋破间之心已用',False),used)
        for score,key in [(-100,'羽流·延攻'),(100,'羽流·反制')]:
            self.setUp()
            self.status(self.actor,'羽流·势',2)
            self.fight('虚空障壁',[score]*4)
            self.assertNotIn('羽流·势',self.actor.statuses)
            self.assertEqual(self.actor.statuses.get(key),1)
        self.setUp()
        self.status(self.actor,'羽流·势',2)
        self.status(self.actor,'羽流·制衡',3)
        self.fight('虚空障壁')
        self.assertEqual(self.actor.statuses.get('羽流·终'),1)
        self.assertNotIn('羽流·势',self.actor.statuses)

    def test_status_catalog_shows_each_printed_rule_once(self):
        catalog = Displayer(self.game).catalog()["statuses"]
        for name in ("羽流·势", "羽流·延攻", "羽流·反制", "羽流·制衡", "羽流·终",
                     "裂伤", "裂伤拘束", "铭刻", "折影化铭刻", "折影", "破甲"):
            with self.subTest(name=name):
                self.assertEqual(catalog[name], [self.spec["status_rules"][name]["description"]])
        self.assertTrue(any("回合结束" in line for line in catalog["涡流"]))

    def test_solo_stance_settles_before_the_first_slash_hits_or_returns_to_hand(self):
        for name, stacks, shield in [("折影吞噬", 2, 1), ("折影交织", 5, 3),
                                     ("折影交织", 4, 0)]:
            with self.subTest(card=name, stacks=stacks):
                self.setUp()
                self.status(self.actor, "羽流·势", stacks)
                at_hit = []
                resolve_hit = self.ctx.resolve_hit

                def observe(**event):
                    if event["card"] is self.cards[name] and event["die"].position == 1:
                        actor = Displayer(self.game).snapshot()["players"][0]["characters"][0]
                        at_hit.append((actor["statuses"].get("羽流·势"), actor["statuses"].get("羽流·制衡"),
                                       actor["shields"]["normal"]))
                    return resolve_hit(**event)

                with patch.object(self.ctx, "resolve_hit", side_effect=observe):
                    card = self.fight(name)
                self.assertEqual(at_hit, [(None, 1, shield)] if shield else [(stacks, None, 0)])
                spent = [e["amount"] for k, e in self.events if k == "status_spent" and e["name"] == "羽流·势"]
                self.assertEqual(spent, [stacks] if shield else [])
                if name == "折影吞噬":
                    self.assertIn(card, self.left.cardspace.hand.content)

    def test_weave_spends_five_once_for_the_first_slash_verdict(self):
        for score, stance in [(1, "羽流·延攻"), (8, "羽流·制衡"), (100, "羽流·反制")]:
            with self.subTest(score=score):
                self.setUp()
                self.status(self.actor, "羽流·势", 5)
                with patch.object(self.game.rng, "randint", side_effect=lambda low, high: low):
                    self.fight("折影交织", [score] * 4)
                self.assertEqual(self.actor.statuses.get(stance), 1)
                self.assertNotIn("羽流·势", self.actor.statuses)
                self.assertEqual([e["amount"] for k, e in self.events
                                  if k == "status_spent" and e["name"] == "羽流·势"], [5])
                if stance == "羽流·反制":
                    self.assertEqual(len(self.left.cardspace.hand.content), 3)
                elif stance == "羽流·制衡":
                    self.assertEqual(self.actor.shield, 3)
                else:
                    self.assertEqual(self.actor.statuses["强壮"], 3)

    def test_stance_requires_an_actual_gain_and_does_not_transfer_to_the_next_slash(self):
        self.status(self.actor, "羽流·势", 5)
        self.ctx.register_entries(self.actor, [{
            "trigger": "BEFORE STATUS", "subject": "target",
            "when": [{"left": "$event.status", "op": "eq", "right": "羽流·制衡"},
                     {"left": "$event.die.position", "op": "eq", "right": 1}],
            "operation": {"op": "cancel"},
        }])
        self.fight("折影交织")
        self.assertEqual(self.actor.statuses["羽流·势"], 5)
        self.assertNotIn("羽流·制衡", self.actor.statuses)
        self.assertEqual(self.actor.shield, 0)
        self.assertFalse(any(k == "status_spent" and e["name"] == "羽流·势" for k, e in self.events))

    def test_unopposed_first_slash_can_settle_even_when_range_prevents_the_hit(self):
        self.status(self.actor, "羽流·势", 2)
        self.fight("虚空障壁", [-100], range_level=1)
        self.assertEqual(self.actor.statuses.get("羽流·制衡"), 1)
        self.assertNotIn("羽流·势", self.actor.statuses)
        self.assertFalse(any(k == "solo_attack" for k, _ in self.events))
        self.assertEqual(self.enemy.hp, self.enemy.max_hp)

    def test_weave_replacement_on_either_trigger(self):
        for ranged in (False,True):
            self.setUp()
            card=self.cards['折影交织']
            self.game.place_in_duel(1,card,0)
            if ranged:
                self.game.place_in_duel(2,self.opposition([-100,-100],range_level=1),0)
            else:
                self.ctx.eval_block([card,OpCode.DESTROY])
            self.start_duel()
            self.assertIn(card,self.left.cardspace.hand.content)
            self.assertEqual(self.left.turn_cost_adjustment,3)
            self.assertEqual([e['card'] for k,e in self.events if k=='skill_used'].count('闪回识破'),1)
            self.assertNotIn('折影交织',[e['card'] for k,e in self.events if k=='skill_used'])
            self.assertEqual(self.enemy.hp,97)

    def test_flash_evade_and_weave_skill_keep_their_own_hit_carrier_scope(self):
        for woven, enemy_range, expected in ((False, 0, [2]), (False, 3, [2]), (True, 3, [])):
            with self.subTest(woven=woven, enemy_range=enemy_range):
                self.setUp()
                card = self.cards["折影交织" if woven else "闪回识破"]
                foe = self.opposition([100, 100], range_level=enemy_range)
                hit_attempts = []
                self.ctx.register_entries(self.enemy, [{"trigger": "before_dice_hit",
                    "operation": lambda ctx: hit_attempts.append(ctx.event["die"].position)}])
                for die in foe.dice:
                    die["entries"] = [
                        "1超穿甲",
                        {"trigger": "on_dice_hit", "operation": {"op": "program",
                         "code": ["$event.target", "受击标记", 1, "STATUS"]}},
                        {"trigger": "on_clash_win", "operation": {"op": "program",
                         "code": ["$event.target", "外来效果", 1, "STATUS", "$self", "拼胜收益", 1, "STATUS"]}},
                    ]
                self.assertTrue(self.game.place_in_duel(1, card, 0))
                self.assertTrue(self.game.place_in_duel(2, foe, 0))
                self.start_duel()
                self.assertEqual([d.position for d in foe.instantiated_dice if d.landed_hits], expected)
                self.assertEqual(hit_attempts, expected)
                self.assertEqual(self.actor.hp, 12 - len(expected))
                self.assertEqual(self.actor.statuses.get("受击标记", 0), len(expected))
                self.assertEqual(self.actor.statuses.get("外来效果", 0), len(expected))
                self.assertEqual(self.enemy.statuses["拼胜收益"], 2)
                self.assertEqual(self.actor.statuses.get("羽流·反制", 0), int(woven or not enemy_range))

    def test_gaining_ignore_range_restores_the_same_die_but_not_an_explicit_blank(self):
        for explicit, expected in ((False, "slash"), (True, "blank")):
            with self.subTest(explicit=explicit):
                self.setUp()
                spec = dict(type="slash", level=1, calc_formula="50", entries=[
                            "2超穿甲", {"trigger": "on_clash_win", "operation": {"op": "program",
                                       "code": ["$self", "复原词条", 1, "STATUS"]}}],
                            ignore_range_amount={"value": {"field": "$event.card.use_state",
                                                           "key": "无视", "default": 0}})
                card = Card(self.left, dict(id="scope", name="测试", cost=0, dice=[spec]), self.actor)
                observed = []
                def grant(ctx):
                    die = ctx.event["die"]
                    observed.append((die, die.type))
                    if explicit:
                        ctx.eval_block([die, OpCode.BLANK_DIE])
                    ctx.eval_block([card, "无视", 3, OpCode.SET_SKILL_STATE])
                    observed.append((die, die.type))
                self.ctx.register_entries(self.actor, [dict(trigger="before_dice_use", operation=grant)])
                self.game.place_in_duel(1, card, 0)
                self.game.place_in_duel(2, self.opposition([1], range_level=3), 0)
                self.start_duel()
                die, = card.instantiated_dice
                self.assertEqual(observed, [(die, "blank"), (die, expected)])
                self.assertEqual(die.landed_hits, int(not explicit))
                self.assertEqual(self.enemy.hp, 100 if explicit else 98)
                self.assertEqual(self.actor.statuses.get("复原词条", 0), int(not explicit))

    def test_weave_against_carrier_brand_keeps_both_public_clashes_after_flash_dissolves(self):
        for route in ("regular", "intercept", "pull"):
            for first in (1, 2):
                with self.subTest(route=route, first=first):
                    match = BattleMatch([["emyake_lin_yu"], ["structured_carrier"]], seed=151,
                                        extra_packs=CHALLENGES["carrier"].packs, open_rosters=True)
                    game = match.game
                    left, right = game.players
                    actor, boss = left.characters[0], right.characters[0]
                    game.first_player = game.players[first - 1]
                    game.start_turn()
                    weave = next(c for c in actor.skills if c.name == "折影交织")
                    brand = next(c for c in boss.skills if c.name == "威压烙印")
                    if route != "intercept":
                        self.assertTrue(game.place_in_duel(1, weave, 0))
                    if route == "regular":
                        self.assertTrue(game.place_in_duel(2, brand, 0))
                        game.reveal_cards()
                        game.pipeline.start_duel_combat()
                    else:
                        phase = game.pre_reveal
                        slot = phase.stage_attack(brand, actor if route == "intercept" else None,
                                                  0 if route == "pull" else None, right.cardspace.draw)
                        if route == "intercept":
                            if weave not in left.cardspace.hand.content:
                                left.cardspace.draw.move_card_to(weave, left.cardspace.hand)
                            phase.phase = "intercept"
                            phase.intercept(weave, 1)
                        slot.ready = True
                        phase.phase = "ready"
                        phase.begin_resolution()
                    rolls = []
                    for _ in range(500):
                        if not game.pipeline.in_duel_phase:
                            break
                        if player := game.special.decision_owner:
                            options = game.special.options(player)
                            game.special.apply(player, next((o for o in options if o.kind.startswith("decline")), options[0]))
                            continue
                        nodes = game.next_step()
                        if isinstance(nodes, tuple) and match._combat_stop(nodes) and "logic_dice_clash" in nodes:
                            sides = match.snapshot()["frame"]["combat"]["sides"]
                            rolls.append([(s["card_id"], s["die_number"]) for s in sides])
                    else:
                        self.fail("迎击未结算完毕")
                    self.assertEqual(rolls, [[("emyake_flash", n), ("carrier_brand", n)] for n in (1, 2)])
                    self.assertIn(weave, left.cardspace.hand.content)
                    self.assertEqual(left.turn_cost_adjustment, 3)
                    frame = match.snapshot()["frame"]
                    slot, = frame["duels"] if route == "regular" else frame["pre_reveal"]["duels"]
                    resolved, = slot["sides"][0]["resolved_cards"]
                    self.assertEqual(resolved["name"], "闪回识破")
                    self.assertTrue(resolved["no_hit_carrier"])
                    self.assertEqual([d["no_hit_carrier"] for d in resolved["dice"]], [True, False])
                    self.assertEqual([d["position"] for d in resolved["live_dice"]], [1, 2])
                    self.assertTrue(all(d["result"] in ("win", "lose", "draw") for d in resolved["live_dice"]))
                    self.assertEqual(slot["sides"][0]["cards"], [])
                    self.assertFalse(slot["sides"][1]["cards"][0]["skipped"])

    def test_weave_bursts_at_24_after_increases_in_either_initiative(self):
        for first in (1,2):
            self.setUp()
            self.game.first_player=self.game.players[first-1]
            self.status(self.actor,'铭刻',13)
            self.status(self.enemy,'裂伤',23)
            self.enemy.rule_state['裂伤存伤']=140
            self.fight('折影交织')
            bursts=[e for k,e in self.events if k=='direct_damage' and e.get('source')=='裂伤爆发']
            self.assertEqual([e['grade'] for e in bursts],['concept'])
            self.assertNotIn('裂伤',self.enemy.statuses)

    def test_heart_keeps_printed_and_negative_modifiers(self):
        self.enemy.add_shield('normal',5)
        self.fight('纯粹之心',[-1]*4,choose=lambda _:'normal',ignore_range=3)
        self.assertTrue(self.enemy.turn_state.get('suppress_dice_increases'))
        self.ctx.eval_block([self.enemy,'normal',2,OpCode.SHIELD])
        self.assertEqual(self.enemy.shield,0)
        card=Card(self.right,dict(id='score',name='计分',cost=0,dice=[dict(type='slash',level=4,final_bonus=3)]),self.enemy)
        die=card.get_current_die(self.game)
        self.ctx.eval_block([die,7,OpCode.DIE_FINAL_ADD,die,-2,OpCode.DIE_FINAL_ADD,
                             card,2,OpCode.SKILL_LEVEL_ADD,die,-1,OpCode.DIE_LEVEL_ADD])
        self.status(self.enemy,'强壮',4)
        self.status(self.enemy,'虚弱',1)
        die.value=4
        self.assertEqual((die.get_value(),die.level.value),(4+3-2-1,3))
        self.assertEqual(sum(k=='clash_scored' for k,e in self.events),1)

    def test_storm_atomic_price(self):
        for marks,choice,used in [(2,None,0),(3,None,0),(3,'pay',1),(13,None,1)]:
            self.setUp()
            self.status(self.actor,'铭刻',marks)
            self.fight('刻刃风暴',choose=lambda _:choice)
            self.assertEqual(sum(k=='skill_used' for k,e in self.events),used)
            self.assertEqual(self.actor.statuses.get('铭刻',0),marks-3*used)
            self.assertEqual(self.left.available_cost,5-3*used)
            self.assertEqual(self.enemy.statuses.get('裂伤拘束',0),2*used)

    def test_narrow_loss_to_draw(self):
        self.status(self.actor,'羽流·制衡',2)
        with patch.object(self.game.rng,'randint',return_value=1):
            self.fight('铭刻闪动',[4,5],ignore_range=3)
        results=[tuple(row[4] for row in e['sides']) for k,e in self.events if k=='clash_scored']
        self.assertEqual(results,[('draw','draw'),('lose','win')])


    def test_paid_response_follows_the_actual_redirected_target(self):
        teammate = Character(dict(id='ally',name='队友',rank='NORMAL',max_hp=40,skills=[]),self.left)
        self.left.characters.append(teammate)
        ally_card=Card(self.left,dict(id='ally_skill',name='队友技能',cost=0,
                         dice=[dict(type='evade',level=1)]),teammate)
        attack=self.opposition([100])
        attack.dice[0]['entries']=['3物理',dict(trigger='before_dice_pair',operation={'op':'program',
            'code':['$event.die','$player','OPPONENT',{'field':'characters'},'FIRST','ROUTE_DIE_ATTACK']})]
        self.status(self.actor,'铭刻',4)
        self.game.place_in_duel(1,ally_card,0)
        self.game.place_in_duel(2,attack,0)
        self.game.reveal_cards()
        self.game.pipeline.start_duel_combat()
        self.run_duel(lambda _:'counter')
        self.assertEqual(self.actor.hp,12)
        self.assertEqual(self.actor.turn_state.get('闪回识破次数'),1)
        self.assertEqual(self.enemy.statuses.get('裂伤'),2)

    def test_riposte_replaces_a_teammate_and_spends_no_marks_as_a_payment(self):
        teammate = Character(dict(id='ally',name='队友',rank='NORMAL',max_hp=40,skills=[]),self.left)
        self.left.characters.append(teammate)
        old=Card(self.left,dict(id='old',name='旧牌',cost=0,dice=[]),teammate)
        self.game.place_in_duel(1,old,0)
        card=self.cards['羽流剑反']
        self.left.cardspace.draw.move_card_to(card,self.left.cardspace.hand)
        move=next(o for o in self.game.special.options(self.left) if o.kind=='replace' and o.target_card is old)
        self.game.special.apply(self.left,move)
        self.assertIn(old,self.left.cardspace.hand.content)
        self.assertFalse(card.get_current_die(self.game).reverses_clash)
        foe=self.opposition([0,0,0],ignore_range=3)
        self.game.place_in_duel(2,foe,0)
        self.game.reveal_cards()
        self.game.pipeline.start_duel_combat()
        self.run_duel()
        self.assertEqual(self.actor.statuses['铭刻'],2)
        self.assertFalse(any(k=='status_spent' and e['name']=='铭刻' for k,e in self.events))
        self.assertTrue(all(s[0][2]%4==0 for k,e in self.events if k=='clash_scored' for s in [e['sides']]))

    def test_counter_stance_shared_action_budget_and_personal_fee(self):
        self.status(self.actor,'羽流·反制',3)
        self.ctx.dispatch_pipeline('on_turn_start')
        self.assertEqual(self.actor.available_cost,4)
        self.assertEqual(self.actor.ability_effects['置卡或换卡机会'],2)
        for key in ['place','replace']:
            self.assertEqual(self.actor.ability_permission(key),'置卡或换卡机会')
            self.assertTrue(self.actor.spend_ability_effect(self.actor.ability_permission(key)))
        self.assertIsNone(self.actor.ability_permission('place'))

    def test_probe_unlocks_only_after_an_actual_non_win(self):
        for score, unlocked in [(100,True),(-100,False)]:
            self.setUp()
            card=self.fight('试探交锋',[score]*4)
            self.assertEqual(bool(card.use_state.get('激活剩余骰子')),unlocked)
            self.assertEqual(sum(k=='clash_scored' for k,_ in self.events),4 if unlocked else 2)



    def test_piercing_repeat_spends_all_and_caps_end_bonus(self):
        self.status(self.actor, "铭刻", 7)
        self.status(self.actor, "羽流·终", 5)
        self.fight("片羽穿空", [-100, 1000, -100], choose=lambda _: "pay", ignore_range=3)
        self.assertNotIn("铭刻", self.actor.statuses)
        self.assertEqual(self.enemy.hp, 92)
        self.assertEqual(sum(event == "clash_scored" for event, _ in self.events), 3)
        self.assertTrue(any(event == "card_destroyed" for event, _ in self.events))

    def test_guard_stance_sum_and_fractional_payment(self):
        self.status(self.actor, "羽流·势", 5)
        for key in ("羽流·延攻", "羽流·反制", "羽流·制衡"):
            self.status(self.actor, key, 3)
        card = self.fight("刻刃护卫", choose=lambda _: "pay")
        self.assertEqual(card.level_bonus, 3)
        self.assertEqual(self.actor.statuses["羽流·势"], 5)
        self.assertEqual(self.actor.statuses["铭刻"], 2)
        self.assertEqual(self.enemy.hp, 99)
        self.assertEqual(self.enemy.statuses["裂伤"], 2)

    def test_storm_recipient_selects_discards_and_slow_applies_before_speed(self):
        self.status(self.actor, "羽流·制衡", 3)
        self.status(self.actor, "铭刻", 13)
        hand = [self.opposition([i]) for i in range(3)]
        for card in hand:
            self.right.cardspace.hand.add_card(card)
        self.fight("刻刃风暴")
        self.assertEqual(self.right.cardspace.hand.content, hand[:1])
        self.assertEqual(self.right.next_turn_common_cost, -2)
        self.game.finish_turn()
        self.game.prepare_turn()
        self.assertEqual(self.enemy.statuses["虚弱"], 3)
        self.assertTrue(any(k == "status_changed" and e["name"] == "限制" and e["total"] == 3
                            for k, e in self.events))
        self.assertNotIn("限制", self.enemy.statuses)  # 陪练方空过，预约先兑现，再清除。


    def test_phantom_bonus_follows_the_receipt_when_a_payment_is_reduced(self):
        self.status(self.actor, "铭刻", 6)
        self.ctx.register_entries(self.actor, [{
            "trigger": "BEFORE SPEND_STATUS", "subject": "target",
            "when": [{"left": "$event.status", "op": "eq", "right": "铭刻"}],
            "operation": {"op": "program", "code": [1, "MIN"]},
        }])
        self.fight("流华幻影", [-1] * 3, choose=lambda _: "pay", ignore_range=3)
        self.assertEqual((self.actor.statuses["铭刻"], self.enemy.hp, self.enemy.statuses["裂伤"]), (5, 96, 7))

    def test_only_two_paid_response_skills_in_one_turn(self):
        self.status(self.actor, "铭刻", 20)
        self.game.place_in_duel(2, self.opposition([100] * 7), 0)
        self.start_duel(lambda _: "counter")
        flashes = [event for event, data in self.events if event == "skill_used" and data["card"] == "闪回识破"]
        self.assertEqual((len(flashes), self.actor.statuses["铭刻"]), (2, 12))
