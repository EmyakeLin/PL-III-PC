"""Focused regression suite for entry authors, the compiler and the executor.

Run with python -m unittest tests.entry_semantics.
"""
MODULES = (
    "tests.test_emyake",
    "tests.test_liu_yin",
    "tests.test_plan_b_sa",
    "tests.test_waa_east_four",
    "tests.test_carrier_challenge.CarrierTests",
    "tests.test_lan_qing",
    "tests.test_entry_authoring_contract",
    "tests.test_entry_execution_paths",
    "tests.test_die_response_semantics",
    "tests.test_range_amount_semantics",
    "tests.test_scheduled_effect_semantics",
    "tests.test_shared_status_entries",
    "tests.test_rear_duel",
)


def load_tests(loader, suite, pattern):
    suite.addTests(loader.loadTestsFromNames(MODULES))
    return suite
