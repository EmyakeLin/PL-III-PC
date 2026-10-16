from pipeline.pipeline import Pipeline
from pipeline.pipeline_steps import step_list
from pipeline.pipeline_errors import (
    PipelineError,
    PipelineSystemError,
    PipelineCompileError,
    PipelineScopeError,
    PipelineRecursionLimitError,
    PipelineFlowControl,
    PipelineFinished,
    PipelineHalted,
    PipelineMishapError,
    StackUnderflowError,
    InvalidTargetError,
    CostExceededError,
)

from player.player import Player

from game import Game

from loader import load_characters_from_packs

if __name__ == "__main__":

    all_characters = load_characters_from_packs()

    game = Game([Player(1, "p1"), Player(2, "p2")])

    



    cont = True
    while True:
        try:
            game.pipeline.next_step()
        except PipelineFinished:
            print("战斗管线平稳结算结束。")
            break

        cont_input = input("continue? type anything to stop")
        if cont_input == "":
            pass
        else:
            break


