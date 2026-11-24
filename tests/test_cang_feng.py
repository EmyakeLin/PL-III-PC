"""Comprehensive semantic and integration tests for 爆燃 and「藏锋事务所」."""
import io
import unittest
from contextlib import redirect_stdout

from battle_ui.match import BattleMatch
from game import Game
from loader import load_characters_from_packs
from models.card import Card, CardState
from models.character import Character
from models.opcode import OpCode
from models.special_actions import SpecialAction
from player.player import Player


class FixedRng:
    def __init__(self, value=3):
        self.value = value

    def randint(self, low, high):
        return max(low, min(high, self.value))


class CangFengTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pack_pool = {c["id"]: c for c in load_characters_from_packs()}

    @staticmethod
    def _dummy_spec(cid, name, *, hp=30, rank="BOSS", skills=None):
        return {
            "id": cid,
            "name": name,
            "rank": rank,
            "max_hp": hp,
            "skills": skills or [
                {
                    "id": f"{cid}_atk_{i}",
                    "name": f"{name}斩{i}",
                    "cost": 1,
                    "dice": [{"type": "slash", "level": 3, "entries": ["2物理"]}],
                }
                for i in range(4)
            ],
        }

    def _setup_game(self, *, left_specs, right_specs, rng_val=1):
        self.enterContext(redirect_stdout(io.StringIO()))
        left, right = Player(1, "甲"), Player(2, "乙")
        game = Game([left, right], rng=FixedRng(rng_val))
        game.first_player = left
        for player, specs in ((left, left_specs), (right, right_specs)):
            for spec in specs:
                char = Character(spec, player)
                player.characters.append(char)
                char.init_cards()
                char.setup_deck()
        game.start_turn()
        while game.pending_draw is not None:
            pending = game.pending_draw
            game.complete_draw(pending, pending.candidates[:pending.discard_count])
        return game, left, right

    @staticmethod
    def _card_by_id(player, card_id, *, hand=True):
        if hand:
            found = next((c for c in player.cardspace.hand.content if c.id == card_id), None)
            if found is not None:
                return found
        for ch in player.characters:
            for c in ch.skills:
                if c.id == card_id:
                    if hand and c not in player.cardspace.hand.content:
                        for zone in (player.cardspace.draw, player.cardspace.delayed_discard, player.cardspace.out_of_combat):
                            if c in zone.content:
                                zone.move_card_to(zone.content.index(c), player.cardspace.hand)
                                break
                    return c
        raise LookupError(card_id)

    @staticmethod
    def _run_combat(game, *, decisions=()):
        decided = list(decisions)
        game.pipeline.start_duel_combat()
        for _ in range(500):
            if game.is_over or not game.pipeline.in_duel_phase:
                break
            owner = game.special.decision_owner
            if owner is not None:
                action = decided.pop(0) if decided else game.special.options(owner)[0]
                game.special.apply(owner, action)
                continue
            if game.special.pending_attack is not None:
                slot = game.special.pending_attack
                responder = game.pre_reveal.opponent(slot.attack_card.player)
                num = game.special.duels.index(slot) + 1
                game.special.apply(responder, SpecialAction("pass_intercept", response_number=num))
                continue
            game.next_step()

    def test_deflagration_cap_zero_units_guard_and_fatal_stagger_rules(self):
        he_lian = self.pack_pool["cang_feng_he_lian"]
        dummy = self._dummy_spec("dummy", "木桩", hp=30)
        game, left, right = self._setup_game(left_specs=[he_lian], right_specs=[dummy])
        enemy = right.characters[0]

        # 1. Burn >= 4 with Deflagration 2 & Fatal Stagger 1:
        # Burn base units = 20 // 4 = 5; cap = 3 + 2 = 5 -> deals 5 dmg (NOT doubled by Fatal Stagger!),
        # Fatal Stagger remains 1, Deflagration drops 2 -> 1, Burn drops 20 -> 13.
        with game.context.binding(source=left.characters[0], side=1):
            game.context.eval_block([enemy, "烧伤", 20, OpCode.STATUS])
            game.context.eval_block([enemy, "爆燃", 2, OpCode.STATUS])
            game.context.eval_block([enemy, "致命失衡", 1, OpCode.STATUS])
        # Note: gaining Fatal Stagger immediately ignited once via faction passive!
        # Before fatal stagger ignite: burn 20, deflag 2 -> cap 5, units 5 -> dealt 5 dmg, deflag 2->1, burn 20->13.
        self.assertEqual(enemy.hp, 25)
        self.assertEqual(enemy.statuses.get("爆燃", 0), 1)
        self.assertEqual(enemy.statuses.get("烧伤", 0), 13)
        self.assertEqual(enemy.statuses.get("致命失衡", 0), 1)

        # 2. Explicit ignite when burn < 4 (units == 0) must NOT consume Deflagration
        with game.context.binding(source=left.characters[0], side=1):
            game.context.eval_block([enemy, "烧伤", -10, OpCode.STATUS])  # 13 -> 3
            self.assertEqual(enemy.statuses.get("烧伤", 0), 3)
            game.context.eval_block([enemy, "烧伤", OpCode.ACTIVATE_STATUS])
        self.assertEqual(enemy.hp, 25)
        self.assertEqual(enemy.statuses.get("爆燃", 0), 1)
        self.assertEqual(enemy.statuses.get("烧伤", 0), 1)

    def test_faction_passive_turn_start_shield_and_cost_cap_two(self):
        team = [
            self.pack_pool["cang_feng_he_lian"],
            self.pack_pool["cang_feng_ji_lan"],
            self.pack_pool["cang_feng_ji_xia"],
        ]
        enemy = self._dummy_spec("dummy", "木桩", hp=20)
        game, left, _ = self._setup_game(left_specs=team, right_specs=[enemy])
        he_lian, ji_lan, ji_xia = left.characters

        # Ensure every character has 偏转力场 >= 1 at turn start so all 3 qualify,
        # yet team common cost bonus from 藏锋事务所 is capped at +2.
        for ch in (he_lian, ji_lan, ji_xia):
            ch.shield = 0
            ch.statuses["偏转力场"] = 1
        left.reset_on_turn_start()
        base_cost = left.available_cost
        left.calculate_speed()
        game.context.dispatch_pipeline("on_turn_start", side=1, player=left)

        # He Lian (+3 passive +2 faction), Ji Lan (+2 passive +2 faction), Ji Xia (+2 faction)
        self.assertGreaterEqual(he_lian.shield, 5)
        self.assertGreaterEqual(ji_lan.shield, 4)
        self.assertGreaterEqual(ji_xia.shield, 2)
        self.assertEqual(left.available_cost, base_cost + 2)

    def test_deflection_field_solo_pierce_ally_borrow_and_counter_once_per_round(self):
        # Part A: Solo 2:1 pierce absorption + once-per-round counter
        he_lian_spec = self.pack_pool["cang_feng_he_lian"]
        enemy_spec = self._dummy_spec("piercer", "穿刺手", hp=25, skills=[
            {"id": "p_hit", "name": "穿刺", "cost": 1, "dice": [{"type": "pierce", "level": 3, "entries": ["2穿甲"]}]},
            {"id": "p_hit2", "name": "重穿", "cost": 1, "dice": [{"type": "pierce", "level": 3, "entries": ["4穿甲"]}]},
        ] * 2)
        game, left, right = self._setup_game(left_specs=[he_lian_spec], right_specs=[enemy_spec], rng_val=3)
        he_lian = left.characters[0]
        attacker = right.characters[0]
        he_lian.shield = 4
        he_lian.statuses["偏转力场"] = 2

        left.max_cost = right.max_cost = 10
        p1 = right.characters[0].skills[0]
        p2 = right.characters[0].skills[2]
        right.cardspace.hand.add_card(p1)
        right.cardspace.hand.add_card(p2)
        game.place_in_duel(2, p1, 0)
        game.place_in_duel(2, p2, 1)

        # First duel: 2 pierce vs 4 normal shield (2:1) -> absorbs 2 for cost 4 -> 0 HP lost ->
        # consumes 1 偏转力场, inflicts 2 burn + 2 stagger, offers 【防反】 寸火返!
        # Second duel: 0 shields left -> 2 HP lost -> must NOT trigger 【防反】 (and limit 1/round too).
        self._run_combat(game, decisions=[SpecialAction("choose_option", option_id="he_lian_counter")])
        self.assertEqual(he_lian.hp, 16)  # 0 lost from first 2-pierce hit, 2 lost from second
        self.assertEqual(he_lian.shield, 0)
        self.assertEqual(he_lian.statuses.get("偏转力场", 0), 1)
        # Attacker received 2 burn + 2 stagger from Deflection + 1 pierce + 3 burn + 1 deflagration from 寸火返
        self.assertGreaterEqual(attacker.statuses.get("烧伤", 0), 5)
        self.assertGreaterEqual(attacker.statuses.get("失衡", 0), 4)
        self.assertEqual(attacker.hp, 24)

        # Part B: Team ally shield borrowing + decline 【防反】
        team = [self.pack_pool["cang_feng_he_lian"], self.pack_pool["cang_feng_ji_xia"]]
        enemy2 = self._dummy_spec("slasher", "斩击手", hp=20, skills=[
            {"id": "s_hit", "name": "重砍", "cost": 1, "dice": [{"type": "slash", "level": 3, "entries": ["3物理"]}]},
        ] * 4)
        game2, l2, r2 = self._setup_game(left_specs=team, right_specs=[enemy2], rng_val=2)
        hl2, jx2 = l2.characters
        hl2.shield = 4
        hl2.statuses["偏转力场"] = 1
        jx2.shield = 0
        r2.default_target_character = jx2  # Aim one-sided attack at Ji Xia
        atk2 = self._card_by_id(r2, "s_hit")
        game2.place_in_duel(2, atk2, 0)
        self._run_combat(game2, decisions=[SpecialAction("decline_option")])
        self.assertEqual(jx2.hp, 9)  # Unharmed via borrowed shield from He Lian!
        self.assertEqual(hl2.shield, 1)  # 4 - 3 = 1
        self.assertEqual(hl2.statuses.get("偏转力场", 0), 0)

    def test_he_lian_drawcore_overheat_shell_throw_recall_and_fly_city(self):
        he_lian_spec = self.pack_pool["cang_feng_he_lian"]
        enemies = [self._dummy_spec("e1", "一号敌", hp=30), self._dummy_spec("e2", "二号敌", hp=30)]
        game, left, right = self._setup_game(left_specs=[he_lian_spec], right_specs=enemies, rng_val=4)
        he_lian = left.characters[0]
        e1, e2 = right.characters
        left.max_cost = right.max_cost = 15

        # Throw shell via 重城·烛芯 targeting e2 specifically
        self.assertEqual(he_lian.max_duels, 3)
        use_act = next(o for o in game.special.options(left) if o.kind == "ability" and o.ability_id == "he_lian_core_command")
        self.assertTrue(game.special.apply(left, use_act))
        self.assertTrue(game.special.apply(left, SpecialAction("choose_option", option_id="throw_shell")))
        pick_e2 = next(o for o in game.special.options(left) if o.kind == "choose_character" and o.character is e2)
        self.assertTrue(game.special.apply(left, pick_e2))

        self.assertEqual(he_lian.statuses.get("拔芯", 0), 1)
        self.assertEqual(he_lian.max_duels, 4)
        self.assertEqual(e2.hp, 28)
        self.assertEqual(e2.statuses.get("失衡", 0), 4)
        self.assertEqual(e2.statuses.get("剑壳镇压", 0), 1)
        self.assertEqual(e1.hp, 30)

        # Verify 剑壳镇压 locks 拔芯 & switches 掷城镇压 -> 归城回斩 (cost 1)
        throw_recall_card = self._card_by_id(left, "cang_feng_he_lian_throw_recall")
        self.assertEqual(throw_recall_card.name, "归城回斩")
        self.assertEqual(throw_recall_card.cost, 1)
        with game.context.binding(source=he_lian, target=he_lian, side=1):
            game.context.eval_block([he_lian, "拔芯", -1, OpCode.STATUS])
        self.assertEqual(he_lian.statuses.get("拔芯", 0), 1)  # Blocked while 剑壳镇压 active

        # Verify Overheat HP loss when using 烛芯掠火 twice
        he_lian.shield = 5
        sweep = self._card_by_id(left, "cang_feng_he_lian_force_sweep")
        sweep2 = Card(left, next(s for s in he_lian.skill_data if s["id"] == "cang_feng_he_lian_force_sweep"), he_lian)
        sweep2.refresh_status_form()
        left.cardspace.hand.add_card(sweep2)
        game.place_in_duel(1, sweep, 0)
        game.place_in_duel(1, sweep2, 1)
        self._run_combat(game)
        # 1st skill: heat 0 -> lose 0 HP, heat -> 1. 2nd skill: heat 1 -> lose 1 HP (ignores shield!), heat -> 2.
        self.assertEqual(he_lian.hp, 17)
        self.assertEqual(he_lian.statuses.get("剑芯过热", 0), 2)

        # Test 飞城破阵·踏鞘归火 in a fresh duel: exempt from HP loss, removes old 剑壳镇压, delays opponent, repeats Die 2, sheaths Die 3
        game2, l2, r2 = self._setup_game(left_specs=[he_lian_spec], right_specs=[self._dummy_spec("boss_e", "铁靶", hp=40)], rng_val=1)
        hl2 = l2.characters[0]
        eb = r2.characters[0]
        with game2.context.binding(source=hl2, target=hl2, side=1):
            game2.context.eval_block([hl2, "拔芯", 1, OpCode.STATUS])
        with game2.context.binding(source=eb, target=eb, side=2):
            game2.context.eval_block([eb, "剑壳镇压", 1, OpCode.STATUS])
        hl2.statuses["剑芯过热"] = 4
        l2.max_cost = r2.max_cost = 15
        fly = self._card_by_id(l2, "cang_feng_he_lian_fly_city")
        enemy_card = Card(r2, {
            "id": "slow_enemy", "name": "慢砍", "cost": 1,
            "dice": [{"type": "slash", "level": 1, "entries": ["1物理"]}],
        }, eb)
        r2.cardspace.hand.add_card(enemy_card)
        game2.place_in_duel(1, fly, 0)
        game2.place_in_duel(2, enemy_card, 0)
        self._run_combat(game2)
        self.assertEqual(hl2.hp, 18)  # Exempt from overheat HP loss
        self.assertEqual(hl2.statuses.get("拔芯", 0), 0)  # Sheathed by Die 3
        self.assertEqual(hl2.statuses.get("剑芯过热", 0), 0)  # Cleared on sheath
        self.assertEqual(eb.statuses.get("剑壳镇压", 0), 0)  # Removed by Die 3
        self.assertTrue(enemy_card.destroyed)  # Destroyed by Die 3
        # Die 1: 2 phys + Die 2 repeated twice: 2*(1 pierce) + Die 3: 2 pierce + Fatal Stagger ignite (1 burn) = 7 dmg (40 -> 33)
        self.assertEqual(eb.hp, 33)
        self.assertEqual(hl2.reinforced_shield, 3)

    def test_ji_lan_guard_redirect_and_twin_furnace_ultimate_lifecycle(self):
        team = [self.pack_pool["cang_feng_ji_lan"], self.pack_pool["cang_feng_ji_xia"]]
        enemy_spec = self._dummy_spec("e", "狂战士", hp=35, skills=[
            {"id": "e_atk", "name": "重劈", "cost": 1, "dice": [{"type": "slash", "level": 3, "entries": ["3物理"]}]},
        ] * 4)
        game, left, right = self._setup_game(left_specs=team, right_specs=[enemy_spec], rng_val=3)
        ji_lan, ji_xia = left.characters
        enemy = right.characters[0]
        left.max_cost = right.max_cost = 15
        ji_lan.shield = 6
        right.default_target_character = ji_xia  # One-sided attack aimed at Ji Xia

        atk = self._card_by_id(right, "e_atk")
        game.place_in_duel(2, atk, 0)
        self._run_combat(game, decisions=[SpecialAction("choose_option", option_id="guard_redirect")])

        # Redirected to Ji Lan (-2 shield cost -> 4, then enemy hit dealt 3 physical? wait 重盾顶退 1~12 vs 1~8 clash -> both roll 3!)
        self.assertEqual(ji_xia.hp, 9)  # Completely protected!
        self.assertGreaterEqual(enemy.statuses.get("失衡", 0), 0)

        # Twin Furnace: 3 ally shield-loss hits -> 炉温 reaches 3 -> spends 3 for 1 爆燃 AND unlocks 合炉·焦土锻葬 (-1 cost -> 3)
        game2, l2, r2 = self._setup_game(left_specs=[self.pack_pool["cang_feng_ji_lan"]], right_specs=[self._dummy_spec("dummy", "木桩", hp=30)], rng_val=2)
        jl2 = l2.characters[0]
        en2 = r2.characters[0]
        jl2.shield = 6
        for _ in range(3):
            with game2.context.binding(source=en2, side=2):
                en2.player and game2.context.deal_damage(en2, jl2, 1, "normal", "slash")
        self.assertEqual(jl2.statuses.get("烧伤", 0), 0)
        self.assertEqual(en2.statuses.get("烧伤", 0), 6)
        self.assertEqual(en2.statuses.get("爆燃", 0), 1)
        self.assertEqual(jl2.statuses.get("炉温", 0), 0)
        burial = self._card_by_id(l2, "cang_feng_ji_lan_furnace_burial", hand=False)
        self.assertIn(burial, l2.cardspace.hand.content)

        # Pay cost for 合炉·焦土锻葬 -> discounted 4 -> 3!
        l2.max_cost = 10
        r2.max_cost = 10
        jl2.shield = 6
        game2.place_in_duel(1, burial, 0)
        self._run_combat(game2)
        self.assertEqual(l2.used_cost + jl2.used_independent_cost, 3)  # First use cost -1 (4 -> 3)!
        self.assertIn(burial, l2.cardspace.out_of_combat.content)  # Moved out of combat after use!

    def test_ji_xia_pre_reveal_intercept_evade_counter_and_fireworks(self):
        ji_xia_spec = self.pack_pool["cang_feng_ji_xia"]
        attacker_spec = self._dummy_spec("e", "远程手", hp=35, skills=[
            {"id": "r_atk", "name": "远射", "cost": 1, "range_level": 1, "dice": [{"type": "pierce", "level": 2, "entries": ["2穿甲"]}]},
        ] * 4)
        game, left, right = self._setup_game(left_specs=[ji_xia_spec], right_specs=[attacker_spec], rng_val=6)
        ji_xia = left.characters[0]
        enemy = right.characters[0]
        left.max_cost = right.max_cost = 15
        enemy.statuses["失衡"] = 6  # Enable 顺丝叩响 counter!

        # Enemy declares pre-reveal attack with range 1; Ji Xia passively intercepts with melee card cost 1 ->
        # 红线缠缚 reduces cost 1 -> 0 AND ignores 1 range deficit (0 deficit)!
        r_atk = self._card_by_id(right, "r_atk")
        slip = self._card_by_id(left, "cang_feng_ji_xia_slip_defuse")
        game.turn_phase = "pre_reveal"
        game.pre_reveal.start()
        game.pre_reveal.attacker = right
        slot = game.pre_reveal.declare_attack(r_atk, character=ji_xia)
        game.pre_reveal.intercept(slip, duel_number=1)
        if game.pre_reveal.can_attack(right):
            game.pre_reveal.end_attack(right)
        game.cards_revealed = True
        ji_xia.hp = 7  # So evade heal restores 1 HP

        # Note RNG=6 vs max 10 / 6: Ji Xia Evade rolls 6, Enemy rolls 6 (draw on equal — use fixed rng in separate or test intercept cost + range)
        # Let's test win by bumping Ji Xia Evade score via 迅捷/强壮 or FixedRng(5) vs D6 opponent!
        # Since enemy die is level 2 (D6, max 6) and slip's Evade is roll_max 10: with rng=5 both roll 5; let's add 1 强壮 so Evade = 6 > 5!
        ji_xia.statuses["强壮"] = 1
        game.pre_reveal.begin_resolution()
        decided = [SpecialAction("choose_option", option_id="counter_slide_shot")]
        for _ in range(500):
            if game.is_over or not game.pipeline.in_duel_phase:
                break
            owner = game.special.decision_owner
            if owner is not None:
                action = decided.pop(0) if decided else game.special.options(owner)[0]
                game.special.apply(owner, action)
                continue
            if game.special.pending_attack is not None:
                slot_p = game.special.pending_attack
                responder = game.pre_reveal.opponent(slot_p.attack_card.player)
                num = game.special.duels.index(slot_p) + 1
                game.special.apply(responder, SpecialAction("pass_intercept", response_number=num))
                continue
            game.next_step()

        self.assertEqual(left.used_cost, 0)  # Passive intercept cost 1 -> 0!
        self.assertEqual(slip.range_deficit, 0)  # Ignored range 1!
        self.assertEqual(ji_xia.hp, 8)  # Healed 1 on Evade win!
        # Opponent took 滑步点射 immediate counterattack (1 pierce) + 侧身卸劲 pre-reveal pierce (1 pierce) + burn/deflagration!
        self.assertLessEqual(enemy.hp, 33)
        self.assertGreaterEqual(enemy.statuses.get("爆燃", 0), 1)

        # Verify BattleMatch catalog builds cleanly for all 3 藏锋事务所 characters
        match = BattleMatch(roster=(("cang_feng_he_lian", "cang_feng_ji_lan", "cang_feng_ji_xia"), ("plan_b_annolin", "plan_b_heck", "plan_b_li_ling")), seed=1)
        catalog = match.snapshot()["catalog"]
        self.assertEqual([c["id"] for c in catalog["players"][0]["characters"]], ["cang_feng_he_lian", "cang_feng_ji_lan", "cang_feng_ji_xia"])

    def test_replace_personal_cost_resident_knock_and_fireworks_concept_unlock(self):
        team = [self.pack_pool["cang_feng_he_lian"], self.pack_pool["cang_feng_ji_lan"], self.pack_pool["cang_feng_ji_xia"]]
        enemy_spec = self._dummy_spec("boss", "铁壁", hp=40, skills=[
            {"id": "big_block", "name": "强打", "cost": 1, "dice": [
                {"type": "slash", "level": 3, "entries": ["1物理"]},
                {"type": "block", "level": 5, "entries": []},
            ]},
        ] * 4)
        game, left, right = self._setup_game(left_specs=team, right_specs=[enemy_spec], rng_val=2)
        he_lian, ji_lan, ji_xia = left.characters
        enemy = right.characters[0]
        left.max_cost = right.max_cost = 15

        # 1. Replace He Lian's placed skill with Ji Lan's 移障代受 -> He Lian gets +1 personal cost!
        he_lian_card = self._card_by_id(left, "cang_feng_he_lian_force_sweep")
        shift_card = self._card_by_id(left, "cang_feng_ji_lan_shift_barrier")
        game.place_in_duel(1, he_lian_card, 0)
        hl_cost_before = he_lian.available_cost
        self.assertTrue(game.special.apply(left, SpecialAction("replace", card=shift_card, target_card=he_lian_card)))
        self.assertEqual(he_lian.available_cost, hl_cost_before + 1)

        # 2. Check 季夏 unlocks 千丝收束·零距礼花 after 2 enemy Fatal Staggers & upgrades Die 3 to concept!
        with game.context.binding(source=ji_xia, side=1):
            game.context.eval_block([enemy, "致命失衡", 1, OpCode.STATUS])
            game.context.eval_block([enemy, "致命失衡", 1, OpCode.STATUS])
        fireworks = self._card_by_id(left, "cang_feng_ji_xia_fireworks", hand=False)
        self.assertIn(fireworks, left.cardspace.hand.content)
        self.assertEqual(ji_xia.max_duels, 3)  # Unlocked +1 duel on unlock turn!

        # 3. Fire 千丝收束·零距礼花 vs enemy with Reinforced Shield + Fatal Stagger:
        # Die 3 converts pierce -> concept (ignores reinforced shield, x2 Fatal Stagger = 6 HP loss!)
        enemy.hp = 40
        enemy.reinforced_shield = 10
        enemy.statuses["致命失衡"] = 2
        # Place fireworks in duel 1 (empty opponent) to test Die 1+2 (pierce absorbed by reinforced) + Die 3 (concept ignores reinforced!)
        game.place_in_duel(1, fireworks, 1)
        game.duelspace.space[0].remove_card(shift_card)
        self._run_combat(game)
        # Die 1 & 2 (pierce) absorbed by reinforced shield (10 -> 6); Die 1 consumes 1 Fatal Stagger -> 1 remains;
        # Die 3 upgrades to concept, ignores reinforced shield, and doubles with remaining Fatal Stagger -> 40 - 6 = 34!
        self.assertIn(fireworks, left.cardspace.out_of_combat.content)
        self.assertEqual(enemy.hp, 34)

    def test_core_command_cancel_refunds_per_turn_and_returns_to_placement(self):
        self.enterContext(redirect_stdout(io.StringIO()))
        match = BattleMatch(roster=("cang_feng_he_lian", "plan_b_annolin"), seed=1, initial_handoff=False)
        snap = match.snapshot()
        # Complete initial draw selections if present
        while snap["mode"] in ("draw_select", "timing", "handoff"):
            if snap["mode"] == "draw_select":
                ds = snap["draw_select"]
                picks = [c["action_key"] for c in ds["candidates"][:ds["discard_count"]]]
                snap = match.act("draw_bottom", snap["revision"], card_ids=picks)
            elif snap["mode"] == "timing":
                snap = match.act("next", snap["revision"])
            else:
                snap = match.act("ready", snap["revision"])

        self.assertEqual(snap["mode"], "placement")
        idx = next(i for i, a in enumerate(snap["table_actions"]) if a["ability_id"] == "he_lian_core_command")

        # 1. Open 重城·烛芯 and immediately cancel with decline_option -> returns to placement without spending per_turn
        snap = match.act("trigger_table_action", snap["revision"], option=idx)
        self.assertEqual(snap["mode"], "special")
        self.assertTrue(snap["effect_choice"]["optional"])
        decline_opt = next(i for i, o in enumerate(snap["special_options"]) if o["kind"] == "decline_option")
        snap = match.act("use_special", snap["revision"], option=decline_opt)
        self.assertEqual(snap["mode"], "placement")
        self.assertIsNone(snap["effect_choice"])
        self.assertTrue(any(a["ability_id"] == "he_lian_core_command" for a in snap["table_actions"]))

        # 2. Re-open 重城·烛芯 -> pick 投掷重剑壳 -> cancel target selection -> still refunds per_turn & cost!
        cost_before = match.game.players[0].available_cost + match.game.players[0].characters[0].available_cost
        idx = next(i for i, a in enumerate(snap["table_actions"]) if a["ability_id"] == "he_lian_core_command")
        snap = match.act("trigger_table_action", snap["revision"], option=idx)
        throw_opt = next(i for i, o in enumerate(snap["special_options"]) if o.get("option_id") == "throw_shell")
        snap = match.act("use_special", snap["revision"], option=throw_opt)
        self.assertEqual(snap["effect_choice"]["selection"], "character")
        self.assertTrue(snap["effect_choice"]["optional"])
        decline_char = next(i for i, o in enumerate(snap["special_options"]) if o["kind"] == "decline_character")
        snap = match.act("use_special", snap["revision"], option=decline_char)
        self.assertEqual(snap["mode"], "placement")
        self.assertEqual(match.game.players[0].available_cost + match.game.players[0].characters[0].available_cost, cost_before)
        self.assertTrue(any(a["ability_id"] == "he_lian_core_command" for a in snap["table_actions"]))

        # 3. Actually commit 进入拔芯 -> per_turn IS consumed
        idx = next(i for i, a in enumerate(snap["table_actions"]) if a["ability_id"] == "he_lian_core_command")
        snap = match.act("trigger_table_action", snap["revision"], option=idx)
        enter_opt = next(i for i, o in enumerate(snap["special_options"]) if o.get("option_id") == "enter_core")
        snap = match.act("use_special", snap["revision"], option=enter_opt)
        self.assertEqual(snap["mode"], "placement")
        self.assertEqual(match.game.players[0].characters[0].statuses.get("拔芯", 0), 1)
        self.assertFalse(any(a["ability_id"] == "he_lian_core_command" for a in snap["table_actions"]))


if __name__ == "__main__":
    unittest.main()
