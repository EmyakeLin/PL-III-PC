from pipeline import Pipeline
from pipeline_steps import step_list, on_turn_start

pipeline = Pipeline(step_list)

on_turn_start.execute()
