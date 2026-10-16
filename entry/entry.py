
from enum import Enum, auto

class TriggerType(Enum):
    PIPELINE = auto()
    OPCODE = auto()

class Entry():
    def __init__(self, owner, trigger_type: TriggerType, trigger, operation, timing = "AFTER"):
        # timing is only available if trigger_type = OPCODE
        self.owner = owner
        self.trigger_type = trigger_type
        self.trigger = trigger
        self.operation = operation
        self.timing = timing

    
