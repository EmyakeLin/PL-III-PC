from dataclasses import dataclass


@dataclass(frozen=True)
class DrawChoice:
    player: object
    candidates: tuple
    keep: int

    @classmethod
    def from_deck(cls, player, look, keep):
        if not 0 <= keep <= look:
            raise ValueError("留牌数须介于零与查看张数之间。")
        candidates = tuple(player.cardspace.draw.content[:look])
        return cls(player, candidates, min(len(candidates), keep))

    @property
    def discard_count(self):
        return len(self.candidates) - self.keep

    def settle(self, bottom):
        cards = tuple(bottom)
        draw = self.player.cardspace.draw
        if tuple(draw.content[:len(self.candidates)]) != self.candidates:
            raise ValueError("候选牌序已改变。")
        if (len(cards) != self.discard_count or len(set(cards)) != len(cards)
                or any(card not in self.candidates for card in cards)):
            raise ValueError("置底牌的数量、身份或来源无效。")
        for card in cards:
            draw.move_card_to(card, draw)
        self.player.draw_card(self.keep)
