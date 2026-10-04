"""Public entry points: decompile a code object or .pyc and verify the result."""

import types

from . import syntax as S
from .bytecode import load_pyc, load_pyc_bytes
from .decompiler import Fail, Session, decompile_code as _decompile_statements
from .verify import GOOD, WRONG, find, verify

MAX_ALTERNATIVES = 4
MAX_TRIALS = 60


class Result:
    """Decompiled source plus the per-code-object verification verdicts."""

    def __init__(self, source, compile_error, functions, error=None):
        self.source = source
        self.compile_error = compile_error
        self.functions = functions
        self.error = error

    @property
    def total(self):
        return len(self.functions)

    @property
    def verified(self):
        return sum(1 for f in self.functions if f.status in GOOD)

    @property
    def ok(self):
        return self.compile_error is None and self.verified == self.total

    def unverified(self):
        return [f for f in self.functions if f.status not in GOOD]


def render_code(code, session=None):
    try:
        stmts = _decompile_statements(code, session)
        return S.render(stmts), None
    except (Fail, RecursionError, ValueError) as e:
        return S.render([S.Unsupported(str(e))]), "%s: %s" % (type(e).__name__, e)


def _status(functions, path):
    for f in functions:
        if f.path == path:
            return f.status
    return None


def _attempt(code, session):
    source, error = render_code(code, session)
    compile_error, functions = verify(code, source)
    return source, error, compile_error, functions


def _search(code, session, source, error, compile_error, functions):
    """Retries ambiguous decisions in functions that failed verification, keeping any that verify."""
    trials = 0
    targets = [f.path for f in functions if f.status == WRONG]
    for path in targets:
        if _status(functions, path) in GOOD:
            continue
        target = find(code, path)
        if not isinstance(target, types.CodeType):
            continue
        points = list(session.points.get(target, []))
        fixed = False
        for key in points:
            for alt in range(1, MAX_ALTERNATIVES + 1):
                if trials >= MAX_TRIALS:
                    return source, error, compile_error, functions
                trials += 1
                previous = dict(session.forced.get(target, {}))
                session.forced.setdefault(target, {})[key] = alt
                attempt = _attempt(code, session)
                if attempt[2] is None and _status(attempt[3], path) in GOOD and \
                        sum(f.status in GOOD for f in attempt[3]) > sum(f.status in GOOD for f in functions):
                    source, error, compile_error, functions = attempt
                    fixed = True
                    break
                session.forced[target] = previous
                if attempt[1] and "forced choice does not exist" in attempt[1]:
                    break
            if fixed:
                break
    return source, error, compile_error, functions


def decompile_code(code, search=True):
    session = Session()
    source, error, compile_error, functions = _attempt(code, session)
    if search and compile_error is None and any(f.status == WRONG for f in functions):
        source, error, compile_error, functions = _search(code, session, source, error, compile_error, functions)
    return Result(source, compile_error, functions, error)


def decompile_pyc(path, search=True):
    return decompile_code(load_pyc(path), search)


def decompile_pyc_bytes(data, search=True):
    return decompile_code(load_pyc_bytes(data), search)
