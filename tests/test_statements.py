import unittest

from tests.support import RoundTripCase


class Assignments(RoundTripCase):
    def test_assignments(self):
        self.assertAllRoundTrip([
            "a = 1\na = b = c\na, b = c\na, (b, c) = d\na, *b = c\n*a, b, c = d\n",
            "a, b = b, a\na, b, c = c, b, a\na.x, b = b, a.x\n",
            "a.b = 1\na[b] = 2\na[b:c] = d\nret = a[b] = f(b)\n",
            "a += 1\na.b -= 2\na[b] *= 3\na.b.c //= 4\na[b][c] **= 5\n",
            "for k, (v, w) in d.items():\n    pass\n",
        ])

    def test_annotations(self):
        self.assertAllRoundTrip([
            "x: int = 1\ny: str\nz: tuple = (a, b)\n",
            "class C:\n    x: int = 1\n    y: 'List[int]'\n",
            "from __future__ import annotations\nx: List[int] = []\ndef f(a: int, *b: str, c: Dict = None, **d: Any) -> Tuple[int, str]:\n    pass\n",
        ])

    def test_deletes(self):
        self.assertAllRoundTrip([
            "del a\ndel a.b\ndel a[b]\ndel a[1:2]\n",
            "def f(x):\n    del x\n",
        ])


class Imports(RoundTripCase):
    def test_imports(self):
        self.assertAllRoundTrip([
            "import a\nimport a.b.c\nimport a as b\nimport a.b.c as d\nimport a.b as c\n",
            "from a import b\nfrom a import b as c, d\nfrom . import x\nfrom ..m import y\nfrom q import *\n",
            "def f():\n    import os\n    from sys import path as p\n    return os, p\n",
        ])


class Scopes(RoundTripCase):
    def test_global_and_nonlocal(self):
        self.assertAllRoundTrip([
            "def f(x):\n    global G\n    G = x\n",
            "def f():\n    v = 1\n    def g():\n        nonlocal v\n        v += 1\n    return g\n",
            "global X\nX = 1\n",
            "from __future__ import annotations\nglobal X\nX = 1\n",
        ])

    def test_raise_and_return(self):
        self.assertAllRoundTrip([
            "def f(x):\n    if x:\n        raise ValueError('x')\n    raise\n",
            "def f(x):\n    raise ValueError from x\n",
            "def f(x):\n    return x, 1\n",
            "def f(x):\n    return (yield x)\n",
        ])


if __name__ == "__main__":
    unittest.main()
