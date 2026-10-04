import unittest

from tests.support import RoundTripCase


class Functions(RoundTripCase):
    def test_signatures(self):
        self.assertAllRoundTrip([
            "def f(a, b=1, *c, d, e=2, **f):\n    pass\n",
            "def f(*, a):\n    pass\n",
            "def f(a=[], b={'k': 1}, c=lambda: 0):\n    return a, b, c\n",
            "def f(a: int, b: 'str' = 'x') -> bool:\n    return True\n",
        ])

    def test_decorators(self):
        self.assertAllRoundTrip([
            "@a\n@b.c(1)\ndef f():\n    pass\n",
            "class C:\n    @property\n    def p(self):\n        return 1\n    @p.setter\n    def p(self, v):\n        pass\n",
        ])

    def test_closures(self):
        self.assertAllRoundTrip([
            "def f(x):\n    def g():\n        return x\n    return g\n",
            "def f(x):\n    return lambda: x + 1\n",
            "def f(self):\n    super().f()\n",
        ])


class Classes(RoundTripCase):
    def test_classes(self):
        self.assertAllRoundTrip([
            "class A:\n    pass\n",
            "class A(B, metaclass=M):\n    x = 1\n    def f(self):\n        return __class__\n",
            "class A(*bases, **kw):\n    pass\n",
            "class A:\n    def __private(self):\n        return self.__value\n    def call(self):\n        return self.__private()\n",
            "class A:\n    class __Inner:\n        pass\n",
        ])

    def test_dead_code_scopes(self):
        self.assertAllRoundTrip([
            "class Logger:\n    def debug(self, message, *args):\n        if __debug__:\n            log(lambda: message)\n",
            "class A:\n    def f(self):\n        if __debug__:\n            super().f()\n",
        ])


if __name__ == "__main__":
    unittest.main()
