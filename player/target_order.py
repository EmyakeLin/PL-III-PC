"""A seat may reserve the next otherwise-unspecified target for a live decision."""

from concurrent.futures import Future
from dataclasses import dataclass


@dataclass(frozen=True)
class TargetChoice:
    candidates: tuple
    default: object


class TargetOrder:
    """One outstanding declaration. Resolution retains its exact execution frame."""

    def __init__(self):
        self.offered = Future()
        self._answer = Future()

    def resolve(self, candidates, default):
        self.offered.set_result(TargetChoice(tuple(candidates), default))
        return self._answer.result()

    def submit(self, target):
        if not self.offered.done() or self._answer.done():
            raise ValueError("当前没有等待答复的目标选择。")
        choice = self.offered.result()
        if target not in choice.candidates or not target.is_alive:
            raise ValueError("目标必须是此次选择中的存活敌人。")
        self._answer.set_result(target)

    def cancel(self):
        self._answer.cancel()
