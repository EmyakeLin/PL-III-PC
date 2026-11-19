class ValueBounds:
    """Bounds attached to one evaluation, applied after its ordinary modifiers."""

    def __init__(self):
        self.minimum = float("-inf")
        self.maximum = float("inf")

    def apply(self, value):
        return min(self.maximum, max(self.minimum, value))

    def set_floor(self, value):
        # A later boundary can narrow the interval established by earlier entries.
        self.minimum = self.apply(value)

    def set_ceiling(self, value):
        self.maximum = self.apply(value)
