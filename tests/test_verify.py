import unittest

from motherlode.verify import EQUIVALENT, EXACT, MISSING, UNCOMPILED, WRONG, compile_source, verify


def status_map(code, source):
    error, results = verify(code, source)
    return error, {r.path: r.status for r in results}


class Verifier(unittest.TestCase):
    ORIGINAL = "def f(a, b):\n    if a:\n        return 1\n    return b\n\ndef g():\n    return 2\n"

    def setUp(self):
        self.code = compile_source(self.ORIGINAL)

    def test_identical_source_is_exact(self):
        error, statuses = status_map(self.code, self.ORIGINAL)
        self.assertIsNone(error)
        self.assertEqual(set(statuses.values()), {EXACT})

    def test_changed_constant_is_wrong(self):
        _, statuses = status_map(self.code, self.ORIGINAL.replace("return 2", "return 3"))
        self.assertEqual(statuses["/<module>/g"], WRONG)
        self.assertEqual(statuses["/<module>/f"], EXACT)

    def test_inverted_condition_is_wrong(self):
        _, statuses = status_map(self.code, self.ORIGINAL.replace("if a:", "if not a:"))
        self.assertEqual(statuses["/<module>/f"], WRONG)

    def test_missing_function_is_reported(self):
        _, statuses = status_map(self.code, "def f(a, b):\n    if a:\n        return 1\n    return b\n")
        self.assertEqual(statuses["/<module>/g"], MISSING)

    def test_syntax_error_marks_everything_uncompiled(self):
        error, statuses = status_map(self.code, "def f(:\n")
        self.assertIsNotNone(error)
        self.assertEqual(set(statuses.values()), {UNCOMPILED})

    def test_dead_trailing_return_is_equivalent(self):
        code = compile_source("def f(a):\n    if a:\n        return 1\n    else:\n        return 2\n")
        _, statuses = status_map(code, "def f(a):\n    if a:\n        return 1\n    return 2\n")
        self.assertEqual(statuses["/<module>/f"], EQUIVALENT)


if __name__ == "__main__":
    unittest.main()
