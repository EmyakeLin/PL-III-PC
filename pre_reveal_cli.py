"""Hot-seat decisions between regular placement and the shared reveal."""


def _choose(options, prompt):
    for number, label in enumerate(options, 1):
        print(f"  [{number}] {label}")
    while True:
        answer = input(prompt).strip()
        if not answer:
            return None
        if answer.isdecimal() and 1 <= int(answer) <= len(options):
            return int(answer) - 1
        print("请输入列表中的编号，或按回车。")


def _show_duels(phase):
    print("\n开牌前交锋 · 公开桌面")
    for number, slot in enumerate(phase.space.space, 1):
        if slot.intercept_card is not None:
            target = f"{slot.intercept_card.name}（迎击）"
        elif slot.target_duel_index is not None:
            target = f"常规交锋 {slot.target_duel_index + 1}"
        else:
            target = slot.target_character.name
        status = "已就绪" if slot.ready else "待迎击"
        print(f"开牌前交锋 {number}　{slot.attack_card.name} → {target}　{status}")


def _actions(phase):
    for player in phase.eligible_players():
        if phase.can_attack(player):
            yield f"{player.name} · 主动出牌", player, "attack", None
            yield f"{player.name} · 结束主动进攻", player, "end", None
        for number in phase.pending_for(player):
            yield f"{player.name} · 回应开牌前交锋 {number}", player, "respond", number


def _attack(game, player, card):
    enemy = game.pre_reveal.opponent(player)
    characters = [c for c in enemy.characters if c.is_alive]
    targets = [f"{c.name}　生命 {c.hp}/{c.max_hp}" for c in characters]
    targets.extend(f"常规交锋 {n}　对手扣置 {len(slot.get_content(enemy.side))} 张"
                   for n, slot in enumerate(game.duelspace.space, 1))
    target = _choose(targets, "选择目标，回车返回公开桌面 ")
    if target is not None:
        if target < len(characters):
            game.pre_reveal.declare_attack(card, character=characters[target])
        else:
            game.pre_reveal.declare_attack(card, duel_index=target - len(characters))


def run_declarations(game):
    phase = game.pre_reveal
    game.close_private_view()
    while phase.actor is not None and not game.is_over:
        game.offer_special_actions()
        if phase.actor is None or game.is_over:
            break
        _show_duels(phase)
        actions = list(_actions(phase))
        choice = _choose([a[0] for a in actions], "任何可行动的玩家均可接手，选择行动编号 ")
        if choice is None:
            continue
        _, player, action, number = actions[choice]
        if action == "end":
            phase.end_attack(player)
            continue

        game.begin_private_view(player)
        try:
            cards = phase.attack_cards(player) if action == "attack" else phase.intercept_cards(player)
            labels = [f"{c.character.name} · {c.describe()}　个人费 {c.character.available_cost}" for c in cards]
            print(f"{player.name}　通用费 {player.available_cost}")
            if action == "respond":
                labels.append(f"放行开牌前交锋 {number}")
            elif not cards:
                input("当前手中没有可主动打出的牌，按回车回到公开桌面 ")
                continue
            index = _choose(labels, "选择手牌或操作，回车暂缓并返回公开桌面 ")
            if index is not None:
                if action == "attack":
                    _attack(game, player, cards[index])
                elif index == len(cards):
                    phase.pass_intercept(duel_number=number, player=player)
                else:
                    phase.intercept(cards[index], duel_number=number)
        finally:
            game.close_private_view()
