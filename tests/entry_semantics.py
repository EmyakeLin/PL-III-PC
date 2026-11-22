"""Focused regression suite for entry authors, the compiler and the executor.

Run with python -m unittest tests.entry_semantics.
"""
MODULES = (
    "tests.test_entry_authoring_contract",
    "tests.test_entry_execution_paths",
    "tests.test_die_response_semantics",
    "tests.test_range_amount_semantics",
    "tests.test_scheduled_effect_semantics",
)


def load_tests(loader, suite, pattern):
    suite.addTests(loader.loadTestsFromNames(MODULES))
    return suite
