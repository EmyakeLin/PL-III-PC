"""通过正式对局管线运行原型中的三骰对两张双骰场景。"""
import unittest


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromName(
        "tests.test_combat.CombatTests.test_three_dice_against_two_skills_and_next_slot"
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
