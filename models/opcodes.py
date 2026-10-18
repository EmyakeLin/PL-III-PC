
from models.opcode import OpCode

from models.duel import DuelSlot


def handle_add(ctx):
    # 此时如果栈元素不足 2 个，ctx.pop() 会自动触发 StackUnderflowError
    b = ctx.pop()
    a = ctx.pop()
    ctx.push(a + b)

def handle_dup(ctx):
    ctx.dup()

def handle_pop(ctx):
    ctx.pop()

def handle_draw(ctx):
    """Required: [subject = Player(), draw_count, OpCode.DRAW]"""
    draw_count = ctx.pop()
    subject = ctx.pop()
    for _ in range(draw_count):
        if len(subject.cardspace.draw.content) > 0:
            subject.cardspace.draw.move_card_to(0, subject.cardspace.hand)
        else:
            break


def handle_place(ctx):
    """Required: [side, duel_index, card = Card(), OpCode.PLACE]"""
    from models.card import CardState
    card = ctx.pop()
    idx = ctx.pop()
    side = ctx.pop()
    if idx < len(ctx.game.duelspace.space):
        ds = ctx.game.duelspace.space[idx]
        ds.add_content(side, card)
        clist = ds.get_content(side)
        for c in clist:
            c.state = CardState.PLACED_FACE_DOWN
        if card.character:
            card.character.used_duels += 1
    else:
        missing_duels = idx+1 - len(ctx.game.duelspace.space)

        for i in range(missing_duels):
            eds = DuelSlot()
            ctx.game.duelspace.append_new_duel(eds)
        ds = ctx.game.duelspace.space[idx]
        ds.add_content(side, card)
        clist = ds.get_content(side)
        for c in clist:
            c.state = CardState.PLACED_FACE_DOWN
        if card.character:
            card.character.used_duels += 1

DISPATCH_TABLE = {
    OpCode.ADD: handle_add,
    OpCode.DUP: handle_dup,
    OpCode.POP: handle_pop,
    OpCode.DRAW: handle_draw,
    OpCode.PLACE: handle_place,
}
