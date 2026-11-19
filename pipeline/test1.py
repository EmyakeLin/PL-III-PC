"""运行一个回合开始节点并检查广播。"""
import unittest
from types import SimpleNamespace

from .pipeline import Pipeline
from .pipeline_base import PipelineTriggerNode


class TurnStartNodeTest(unittest.TestCase):
    def test_broadcasts_turn_start(self):
        events = []
        context = SimpleNamespace(dispatch_pipeline=events.append)
        pipeline = Pipeline(SimpleNamespace(context=context), [PipelineTriggerNode("on_turn_start")])
        self.assertEqual(pipeline.next_step(), "on_turn_start")
        self.assertEqual(events, ["on_turn_start"])


if __name__ == "__main__":
    unittest.main()
