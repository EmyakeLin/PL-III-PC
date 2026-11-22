from collections import Counter


class TurnHistory:
    """Facts about completed skill uses and clash results in the current turn."""

    def __init__(self):
        self.skill_uses = Counter()
        self.clashes = Counter()
        self.hand_plays = Counter()
        self.previous_hand_plays = Counter()

    def clear(self):
        self.previous_hand_plays, self.hand_plays = self.hand_plays, Counter()
        self.skill_uses.clear()
        self.clashes.clear()

    def record_skill(self, actor, skill_id):
        self.skill_uses[actor, skill_id] += 1

    def record_clash(self, position, actor, result):
        self.clashes[position, actor, result] += 1

    def clash_count(self, subject, result, position=None):
        return sum(count for (place, actor, outcome), count in self.clashes.items()
                   if outcome == result and (subject is actor or subject is actor.player)
                   and (position is None or position == place))
