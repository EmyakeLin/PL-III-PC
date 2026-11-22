class RosterDraft:
    """Select each team from the shared pool in seat order."""

    def __init__(self, pool, seats, maximum):
        self.pool = list(pool)
        self.seats = seats
        self.maximum = maximum
        self.teams = []
        if maximum < 1 or len(self.pool) < seats and not any(c.get("mirror_allowed") for c in self.pool):
            raise ValueError("共享角色池无法为双方各留一名角色。")

    @property
    def limit(self):
        reserve = 0 if any(c.get("mirror_allowed") for c in self.pool) else self.seats - len(self.teams) - 1
        return min(self.maximum, len(self.pool) - reserve)

    def submit(self, team):
        team = list(team)
        if len(self.teams) == self.seats or not 1 <= len(team) <= self.limit:
            raise ValueError("出战人数不在本席位可选范围内。")
        remaining = self.pool.copy()
        for member in team:
            if member not in remaining:
                raise ValueError("角色已经被选取或不在共享角色池中。")
            remaining.remove(member)
        self.pool = remaining + [member for member in team if member.get("mirror_allowed")]
        self.teams.append(team)
