import textwrap
import unittest

from motherlode import decompile_code
from motherlode.verify import compile_source, find


class LineNumbers(unittest.TestCase):
    """Decompiled statements land on the lines they came from, so line tables match the original."""

    def assertSameLines(self, source):
        source = textwrap.dedent(source)
        original = compile_source(source)
        result = decompile_code(original)
        self.assertTrue(result.ok, result.source)
        rebuilt = compile_source(result.source)
        for f in result.functions:
            a = find(original, f.path)
            b = find(rebuilt, f.path)
            with self.subTest(path=f.path):
                self.assertEqual(a.co_firstlineno, b.co_firstlineno, result.source)
                self.assertEqual(a.co_lnotab, b.co_lnotab, result.source)

    def test_gaps_left_by_docstrings_and_comments(self):
        self.assertSameLines('''
            """Module docstring."""

            import os

            def f(a):
                """Docstring."""
                # comment
                x = a + 1

                return x
            ''')

    def test_multiline_calls_and_displays(self):
        self.assertSameLines('''
            x = f(a,
                  b,
                  c=1)
            y = {
                'a': 1,
                'b': g(
                    2),
            }
            ''')

    def test_decorated_definitions(self):
        self.assertSameLines('''
            @deco1
            @deco2(
               3)
            def f(a,
                  b=4):
                return a
            ''')

    def test_huge_single_statement_keeps_optimizer_behavior(self):
        items = ",\n".join("    'key%d': (%d, 'value %d', None)" % (i, i, i) for i in range(200))
        source = "TUNABLES = {\n" + items + "\n}\nNAMES = ('a', 'b')\n"
        self.assertSameLines(source)


if __name__ == "__main__":
    unittest.main()
