"""Player-facing timing and hot-seat choices for mid-turn actions."""

from displayer import special_action_label, special_seats, timing_label
from pre_reveal_cli import _choose


def offer_actions(game):
    seats = special_seats(game)
    if not seats:
        return
    if game.pipeline.interrupt_space is not None and game.special.pending_attack is None:
        timing = timing_label(game.last_step)
        if not timing:
            return
        print(f"〔即时交锋 · {timing}〕")
    previous = game._private_player
    game.close_private_view()
    try:
        while seats and not game.is_over:
            pending = game.special.pending_attack
            if pending is not None:
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
            game.begin_private_view(player)
            actions = game.special.options(player)
            if actions:
                index = _choose([special_action_label(action) for action in actions],
                                "选择行动，回车返回公开桌面 ")
                if index is not None:
                    old_space = game.pipeline.interrupt_space
                    game.special.apply(player, actions[index])
                    game.close_private_view()
                    # The game host pumps the interrupted duel before resuming the parent.
                    if game.pipeline.interrupt_space is not old_space or game.is_over:
                        return
            else:
                input("当前没有可执行的特殊行动，按回车返回公开桌面 ")
            game.close_private_view()
            seats = special_seats(game)
    finally:
        game.close_private_view()
        if previous is not None and not game.is_over:
            game.begin_private_view(previous)
