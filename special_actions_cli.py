"""Player-facing timing and hot-seat choices for mid-turn actions."""

from displayer import Displayer, special_action_label, special_seats, timing_label
from pre_reveal_cli import _choose


def offer_actions(bridge):
    game = bridge.game
    seats = special_seats(game)
    if not seats:
        return
    if (game.pipeline.interrupt_space is not None and game.special.pending_attack is None
            and game.special.decision_owner is None):
        timing = timing_label(game.last_step)
        if not timing:
            return
        print(f"〔即时交锋 · {timing}〕")
    previous = bridge._private_player
    bridge.close_private_view()
    try:
        while seats and not game.is_over:
            pending = game.special.pending_attack
            if game.special.decision_owner is not None:
                player = game.special.decision_owner
            elif pending is not None:
                for number, slot in enumerate(game.special.duels, 1):
                    if slot.ready:
                        continue
                    target = slot.target_character.name if slot.target_character else f"常规交锋 {slot.target_duel_index + 1}"
                    print(f"即时交锋 {number}　{slot.attack_card.name} → {target}　待迎击")
                index = _choose([p.name for p in seats], f"选择接手方，回车由{seats[0].name}回应 ")
                player = seats[0 if index is None else index]
            else:
                index = _choose([p.name for p in seats], "特殊行动：选择接手方，回车继续当前对局 ")
                if index is None:
                    return
                player = seats[index]
            bridge.begin_private_view(player)
            actions = game.special.options(player)
            if actions:
                choice = Displayer(game, viewer_side=player.side).effect_choice()
                if choice:
                    die = f" · 第 {choice['die_position']} 骰" if choice["die_position"] else ""
                    print(f"{choice['source_name']}{die}　{choice['description']}")
                prompt = "选择行动，回车返回公开桌面 "
                if choice:
                    prompt = "选择技能，回车放弃此次选牌 " if choice["optional"] else "请输入选项编号 "
                index = _choose([special_action_label(action) for action in actions], prompt)
                if choice and index is None:
                    if not choice["optional"]:
                        continue
                    index = next(i for i, action in enumerate(actions) if action.kind == "decline_card")
                if index is not None:
                    old_space = game.pipeline.interrupt_space
                    bridge.execute(game.special.apply, player, actions[index])
                    # The game host pumps the interrupted duel before resuming the parent.
                    if game.pipeline.interrupt_space is not old_space or game.is_over:
                        return
                    if game.special.decision_owner is player:
                        seats = [player]
                        continue
            else:
                input("当前没有可执行的特殊行动，按回车返回公开桌面 ")
            bridge.close_private_view()
            seats = special_seats(game)
    finally:
        bridge.close_private_view()
        if previous is not None and not game.is_over:
            bridge.begin_private_view(previous)
