import unittest

from tests.support import RoundTripCase


class Conditionals(RoundTripCase):
    def test_if(self):
        self.assertAllRoundTrip([
            "def f(a):\n    if a:\n        x = 1\n    else:\n        x = 2\n    return x\n",
            "def f(a, b):\n    if a and b:\n        return 1\n    return 2\n",
            "def f(a, b, c):\n    if a and b or c:\n        g()\n    elif b:\n        h()\n    else:\n        i()\n",
            "def f(a):\n    if a:\n        return 1\n    else:\n        return 2\n",
            "def f(a):\n    if not a:\n        return\n    g(a)\n",
            "def f(a, b):\n    if a:\n        if b:\n            g()\n        else:\n            h()\n    else:\n        i()\n",
            "def f(a, b):\n    if a:\n        pass\n    if not (a is None or b is None):\n        g()\n",
            "def f(a, b, c):\n    if (a or b) and not c:\n        g()\n",
        ])

    def test_conditions_with_comparison_chains(self):
        self.assertAllRoundTrip([
            "def f(a, b, c):\n    if a < b < c and c:\n        return 1\n",
            "def f(o, s):\n    for i in range(len(s)):\n        if o == s[i] != ':':\n            return s.startswith(':', i + 1)\n    raise E(o)\n",
        ])


class Loops(RoundTripCase):
    def test_for(self):
        self.assertAllRoundTrip([
            "def f(a):\n    for x in a:\n        if x:\n            continue\n        g(x)\n    else:\n        h()\n",
            "def f(a):\n    for x in a:\n        if x:\n            break\n    else:\n        return 1\n    return 2\n",
            "def f(a):\n    for x in a:\n        for y in x:\n            if y:\n                return y\n",
            "def f(a):\n    for x in a:\n        return x\n",
            "def f(a, b):\n    for x in a:\n        if b:\n            for y in x:\n                g(y)\n        else:\n            h(x)\n",
        ])

    def test_while(self):
        self.assertAllRoundTrip([
            "def f(a):\n    while a:\n        a -= 1\n        if a == 3:\n            break\n    return a\n",
            "def f(a):\n    while True:\n        if a():\n            break\n        b()\n",
            "def f(a):\n    while a and not a.done:\n        a = a.next\n    else:\n        g()\n",
            "def f(a):\n    while True:\n        return a\n",
            "def f(p):\n    while p:\n        o, r = p.pop()\n        if o in s:\n            continue\n        for c in k(o):\n            if c is None:\n                continue\n            p.append(c)\n",
        ])

    def test_continue_in_branches(self):
        self.assertAllRoundTrip([
            "def f(c, t):\n    for x in c:\n        if t == 1:\n            if x:\n                continue\n            else:\n                s = False\n        elif t == 2:\n            if x:\n                s = False\n            else:\n                continue\n        else:\n            s = x\n        g(s)\n",
            "def f(r, n, i):\n    for s in r:\n        if s in n:\n            v = n[s]\n            if i < v['e'] and v['r'] != i:\n                continue\n        for q in r[s]:\n            yield q\n",
        ])


class Exceptions(RoundTripCase):
    def test_try(self):
        self.assertAllRoundTrip([
            "def f(a):\n    try:\n        g()\n    except E as e:\n        h(e)\n    except (F, G):\n        pass\n    except:\n        raise\n    else:\n        k()\n    finally:\n        z()\n",
            "def f(a):\n    try:\n        return a()\n    except E:\n        return None\n",
            "def f(a):\n    try:\n        return a()\n    except E as e:\n        return e\n    finally:\n        g()\n",
            "def f(a):\n    for x in a:\n        try:\n            g(x)\n        except E:\n            continue\n        else:\n            break\n",
            "def f(a):\n    try:\n        g()\n    finally:\n        h()\n",
            "def f(a):\n    try:\n        g()\n    except:\n        pass\n    return a\n",
        ])

    def test_with(self):
        self.assertAllRoundTrip([
            "def f(a):\n    with a as b, c:\n        d(b)\n",
            "def f(a):\n    with a:\n        return 1\n",
            "def f(a):\n    with a as (b, c):\n        pass\n",
        ])


if __name__ == "__main__":
    unittest.main()
