import unittest

from src import main


class EnsureGraphicalEnvironmentTests(unittest.TestCase):
    def test_passes_with_display_variable(self) -> None:
        env = {"DISPLAY": ":0"}
        # Should not raise when DISPLAY is set.
        main.ensure_graphical_environment(env)

    def test_fails_without_display_variables(self) -> None:
        with self.assertRaises(AssertionError) as ctx:
            main.ensure_graphical_environment({})

        self.assertIn("No graphical display detected", str(ctx.exception))
        self.assertIn("Hint: export DISPLAY=:0", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
