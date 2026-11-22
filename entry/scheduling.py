from dataclasses import dataclass

from entry.predicates import compile_when
from models.opcode import OpCode


@dataclass(frozen=True)
class ScheduleTerms:
    event: str
    event_type: str
    after_turns: int
    through_turns: int | None
    uses: int | None
    require_source_alive: bool
    require_target_alive: bool
    conditions: tuple


@dataclass(frozen=True)
class CaptureValues:
    names: tuple

    def __call__(self, ctx):
        captured = {name: ctx.pop() for name in reversed(self.names)}
        ctx.push(captured)


@dataclass(frozen=True)
class ScheduledProgram:
    program: object


def expand_schedule(spec, compile_body):
    required = {"event", "source", "target", "after_turns", "through_turns", "uses",
                "require_source_alive", "require_target_alive", "then"}
    if not isinstance(spec, dict) or not required <= spec.keys() or set(spec) - required - {"when", "capture", "event_type"}:
        raise ValueError("预约需要事件、来源、对象、起止回合、次数、存活条件和执行内容")
    event, start, end, uses = (spec[key] for key in ("event", "after_turns", "through_turns", "uses"))
    event_type = spec.get("event_type", "pipeline")
    if event_type not in ("event", "pipeline"):
        raise ValueError("预约事件类型须为 event 或 pipeline")
    if (not isinstance(event, str) or not event or type(start) is not int or start < 0
            or end is not None and (type(end) is not int or end < start)
            or uses is not None and (type(uses) is not int or uses < 1)):
        raise ValueError("无效的预约事件、回合范围或次数")
    if any(type(spec[key]) is not bool for key in ("require_source_alive", "require_target_alive")):
        raise ValueError("预约的来源和对象存活条件须分别指定布尔值")
    capture = spec.get("capture", {})
    if not isinstance(capture, dict) or not isinstance(spec["then"], list):
        raise ValueError("预约的 capture 为具名字段，then 为指令列表")
    terms = ScheduleTerms(event, event_type, start, end, uses, spec["require_source_alive"], spec["require_target_alive"],
                          compile_when(spec.get("when", []), None, None))
    return [spec["source"], spec["target"], *capture.values(), CaptureValues(tuple(capture)),
            terms, ScheduledProgram(compile_body(spec["then"])), OpCode.SCHEDULE_EFFECT]


@dataclass(eq=False)
class ScheduledEffect:
    source: object
    target: object
    capture: dict
    terms: ScheduleTerms
    block: list
    authority: int
    first_turn: int
    last_turn: int | None
    remaining: int | None
    executing: bool = False

    def expired(self, turn):
        return ((self.last_turn is not None and turn > self.last_turn)
                or self.terms.require_source_alive and not getattr(self.source, "is_alive", False)
                or self.terms.require_target_alive and not getattr(self.target, "is_alive", False))


def schedule_effect(ctx):
    block, terms, captured, target, source = ctx.pop(), ctx.pop(), ctx.pop(), ctx.pop(), ctx.pop()
    turn = ctx.game.turn_number
    effect = ScheduledEffect(source, target, captured, terms, block, ctx.event.get("authority", 0),
                             turn + terms.after_turns, None if terms.through_turns is None else turn + terms.through_turns,
                             terms.uses)
    if effect.expired(turn):
        return False
    ctx.scheduled_effects.append(effect)
    return True


def deliver_scheduled(ctx, event_type, event, fields, valid=None):
    from entry.program import execute_program_block

    for effect in tuple(ctx.scheduled_effects):
        if effect not in ctx.scheduled_effects:
            continue
        turn = ctx.game.turn_number
        if effect.expired(turn):
            ctx.scheduled_effects.remove(effect)
            continue
        if (effect.executing or effect.terms.event_type != event_type or effect.terms.event != event or turn < effect.first_turn
                or getattr(ctx.game, "is_over", False) or valid is not None and not valid()):
            continue
        observed = {**fields, "node_id": event}
        delivery = {**observed, "scheduled": effect}
        if not all(clause.evaluate(effect.source, delivery) for clause in effect.terms.conditions):
            continue
        if effect.remaining is not None:
            effect.remaining -= 1
            if effect.remaining == 0:
                ctx.scheduled_effects.remove(effect)
        previous_event, previous_stack, previous_executions = ctx.event, ctx.stack, ctx.executions
        ctx.stack, ctx.executions = [], []
        ctx.event = {**delivery, "observed": observed, "source": effect.source, "target": effect.target,
                     "side": getattr(getattr(effect.source, "player", None), "side", None), "authority": effect.authority}
        effect.executing = True
        try:
            execute_program_block(ctx, effect.block)
        finally:
            effect.executing = False
            ctx.event, ctx.stack, ctx.executions = previous_event, previous_stack, previous_executions
