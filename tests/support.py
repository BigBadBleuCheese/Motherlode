import textwrap
import unittest

from motherlode import decompile_code
from motherlode.verify import compile_source


class RoundTripCase(unittest.TestCase):
    """Compiles each snippet the way The Sims 4 does, decompiles it, and requires every code object to verify."""

    def assertRoundTrips(self, source):
        source = textwrap.dedent(source)
        result = decompile_code(compile_source(source))
        problems = ["%s %s %s" % (f.status, f.path, f.detail or "") for f in result.unverified()]
        if result.compile_error or problems:
            self.fail("round trip failed\n--- input ---\n%s\n--- output ---\n%s\n--- problems ---\n%s\n%s" % (
                source, result.source, result.compile_error or "", "\n".join(problems)))
        return result

    def assertAllRoundTrip(self, snippets):
        for snippet in snippets:
            with self.subTest(snippet=snippet.strip().splitlines()[0]):
                self.assertRoundTrips(snippet)
