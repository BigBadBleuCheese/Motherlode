import unittest

from tests.support import RoundTripCase


class Constants(RoundTripCase):
    def test_constants(self):
        self.assertAllRoundTrip([
            "x = 1\ny = -2\nz = 3.5\nw = -0.0\nv = 1e309\nu = 2j\nt = (1+2j)\n",
            "x = 'text'\ny = b'bytes'\nz = None\nw = True\nv = ...\n",
            "x = (1, 2, 'three')\ny = ()\nz = (1,)\n",
            "x = 'quote \\' and \" and \\n newline'\n",
            "x = (1).real\ny = 1.5.real\n",
        ])


class Operators(RoundTripCase):
    def test_arithmetic_and_precedence(self):
        self.assertAllRoundTrip([
            "x = a + b * c\ny = (a + b) * c\nz = a - (b - c)\nw = a ** b ** c\nv = (a ** b) ** c\n",
            "x = -a ** 2\ny = (-a) ** 2\nz = a ** -b\nw = ~a\nv = not a\nu = - -a\n",
            "x = a // b % c @ d\ny = a << b >> c\nz = a & b | c ^ d\n",
            "x = a if b else c\ny = (a if b else c) if d else e\nz = a if b else c if d else e\n",
            "x = lambda: a\ny = (lambda: a)()\nz = [lambda q, *r, s=1, **t: q]\n",
        ])

    def test_comparisons(self):
        self.assertAllRoundTrip([
            "x = a < b\ny = a is not b\nz = a not in b\nw = not a in b\n",
            "x = a < b < c\ny = a == b != c <= d\n",
            "def f(a, b, c):\n    return a < b < c\n",
            "def f(a, b, c):\n    if a < b < c:\n        return 1\n    return 2\n",
            "x = (a < b) < c\ny = a < (b < c)\n",
        ])

    def test_boolean_values(self):
        self.assertAllRoundTrip([
            "x = a and b\ny = a or b\nz = a and b and c\nw = a or b or c\n",
            "x = a and b or c\ny = a or b and c\nz = (a or b) and c\nw = a and (b or c)\n",
            "x = (a and b) or (c and d)\ny = (a or b) and (c or d)\nz = a or (b and c) or d\n",
            "x = not (a and b)\ny = f(a or b, c and d)\nz = [a or b]\n",
            "x = a or (b if c else d)\ny = (a if b else c) or d\n",
        ])


class Calls(RoundTripCase):
    def test_calls(self):
        self.assertAllRoundTrip([
            "f()\nf(a)\nf(a, b=1)\nf(*a)\nf(**k)\nf(*a, **k)\n",
            "f(a, *b, c, d=1, **e)\nf(*a, *b)\nf(**a, **b)\nf(a=1, **b)\n",
            "f(**{'a': 1})\nf(*a, **{'b': 2})\nf(x=1, *y)\n",
            "obj.method(1, 2)\nobj.attr.method()\nf(x)(y)(z)\n",
            "f(x for x in y)\nf((x for x in y), z)\n",
        ])


class Displays(RoundTripCase):
    def test_displays(self):
        self.assertAllRoundTrip([
            "x = [a, b]\ny = {a, b}\nz = {a: b, c: d}\nw = {'a': 1, 'b': 2}\n",
            "x = [*a, 1, 2]\ny = {*a, *b}\nz = (*a, b)\nw = {**a, 'b': 1, **c}\n",
            "x = []\ny = {}\nz = set()\n",
            "x = a[1]\ny = a[1:2]\nz = a[::2]\nw = a[1:2, 3]\nv = a[:, None]\nu = a[x:y:z]\n",
        ])

    def test_comprehensions(self):
        self.assertAllRoundTrip([
            "x = [a for a in b]\ny = {a for a in b}\nz = {a: c for a, c in b}\nw = list(a for a in b)\n",
            "x = [a for a in b if a if not c]\ny = [a * c for a in b for c in a if c]\n",
            "x = [a if c else d for a in b]\ny = [a or c for a in b]\n",
            "x = [[c for c in a] for a in b]\ny = {k: [v for v in vs if v] for k, vs in d.items()}\n",
            "def f(self):\n    return [x for x in self.items if x.valid and x is not self]\n",
        ])

    def test_fstrings(self):
        self.assertAllRoundTrip([
            "x = f'{a}'\ny = f'{a!r} and {b:>10}'\nz = f'{a:{w}.{p}}'\n",
            "x = f\"{d['k']}\"\ny = f'{{literal}} {a}'\n",
        ])


class Yields(RoundTripCase):
    def test_generators(self):
        self.assertAllRoundTrip([
            "def f(x):\n    yield x\n    yield\n    y = yield x\n    yield from x\n",
            "def f():\n    return\n    yield\n",
            "def f(x):\n    for i in x:\n        yield i, i\n",
        ])


if __name__ == "__main__":
    unittest.main()
