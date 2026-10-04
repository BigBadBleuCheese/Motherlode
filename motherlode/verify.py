"""Proves decompiled source correct by recompiling it and comparing code objects."""

import dis
import types

ATTRS = ("co_argcount", "co_kwonlyargcount", "co_nlocals", "co_flags",
         "co_code", "co_names", "co_varnames", "co_freevars", "co_cellvars", "co_name")

EXACT = "exact"
EQUIVALENT = "equivalent"
WRONG = "wrong"
MISSING = "missing"
UNCOMPILED = "uncompiled"
GOOD = (EXACT, EQUIVALENT)

_UNCONDITIONAL = {"JUMP_ABSOLUTE", "JUMP_FORWARD"}
_TERMINAL = {"RETURN_VALUE", "RAISE_VARARGS", "BREAK_LOOP", "CONTINUE_LOOP"}
_JUMPS = set(dis.hasjrel) | set(dis.hasjabs)


def compile_source(source, filename="<motherlode>"):
    return compile(source, filename, "exec", dont_inherit=True, optimize=2)


def const_key(c):
    if isinstance(c, types.CodeType):
        return ("code", c.co_name)
    if isinstance(c, (float, complex)):
        return (type(c).__name__, repr(c))
    if isinstance(c, (tuple, frozenset)):
        items = [const_key(x) for x in c]
        if isinstance(c, frozenset):
            items.sort(key=repr)
        return (type(c).__name__, tuple(items))
    return (type(c).__name__, c)


def canonical(co):
    """Layout-independent control flow: unconditional jumps become edges and unreachable code drops out."""
    ins = [i for i in dis.get_instructions(co) if i.opname != "EXTENDED_ARG"]
    at = {i.offset: n for n, i in enumerate(ins)}
    for raw in dis.get_instructions(co):
        if raw.opname == "EXTENDED_ARG":
            nxt = raw.offset + 2
            while nxt not in at:
                nxt += 2
            at[raw.offset] = at[nxt]

    def resolve(off):
        seen = set()
        while ins[at[off]].opname in _UNCONDITIONAL and off not in seen:
            seen.add(off)
            off = ins[at[off]].argval
        return ins[at[off]].offset

    order = {}
    trace = []
    queue = [0]
    while queue:
        off = resolve(queue.pop(0))
        if off in order:
            continue
        while True:
            off = resolve(off)
            if off in order:
                trace.append(("GOTO", off))
                break
            order[off] = len(order)
            i = ins[at[off]]
            trace.append(("I", off))
            if i.opcode in _JUMPS:
                queue.append(i.argval)
            if i.opname in _TERMINAL:
                break
            n = at[off] + 1
            if n >= len(ins):
                break
            off = ins[n].offset
    out = []
    for kind, off in trace:
        if kind == "GOTO":
            out.append(("GOTO", order[off]))
            continue
        i = ins[at[off]]
        if i.opcode in _JUMPS:
            out.append((i.opname, order[resolve(i.argval)]))
            continue
        a = i.argval
        if isinstance(a, types.CodeType):
            a = ("code", a.co_name)
        elif i.opcode < dis.HAVE_ARGUMENT:
            a = None
        else:
            a = const_key(a) if i.opname == "LOAD_CONST" else repr(a)
        out.append((i.opname, a))
    return tuple(out)


def own_status(a, b):
    bad = [attr for attr in ATTRS if getattr(a, attr) != getattr(b, attr)]
    if [const_key(c) for c in a.co_consts] != [const_key(c) for c in b.co_consts]:
        bad.append("co_consts")
    if not bad:
        return EXACT, bad
    if set(bad) <= {"co_code", "co_consts"}:
        try:
            if canonical(a) == canonical(b):
                return EQUIVALENT, bad
        except Exception:
            pass
    return WRONG, bad


def children(co):
    seen = {}
    out = []
    for c in co.co_consts:
        if isinstance(c, types.CodeType):
            i = seen.get(c.co_name, 0)
            seen[c.co_name] = i + 1
            out.append(((c.co_name, i), c))
    return out


class FunctionResult:
    __slots__ = ("path", "status", "detail")

    def __init__(self, path, status, detail=None):
        self.path = path
        self.status = status
        self.detail = detail

    @property
    def ok(self):
        return self.status in GOOD


def compare_tree(orig, new, path="", idx=0):
    here = path + "/" + orig.co_name + ("#%d" % idx if idx else "")
    if new is None:
        yield FunctionResult(here, MISSING)
        for (_, i), c in children(orig):
            yield from compare_tree(c, None, here, i)
        return
    status, bad = own_status(orig, new)
    yield FunctionResult(here, status, bad or None)
    nk = dict(children(new))
    for key, c in children(orig):
        yield from compare_tree(c, nk.get(key), here, key[1])


def verify(code, source):
    """Returns (compile_error, [FunctionResult]) for source decompiled from code."""
    try:
        new = compile_source(source)
    except (SyntaxError, ValueError, RecursionError, MemoryError) as e:
        results = [FunctionResult(r.path, UNCOMPILED) for r in compare_tree(code, None)]
        return "%s: %s" % (type(e).__name__, e), results
    return None, list(compare_tree(code, new))


def find(co, path):
    parts = [p for p in path.split("/") if p][1:]
    for name in parts:
        idx = 0
        if "#" in name:
            name, idx = name.rsplit("#", 1)
            idx = int(idx)
        co = dict(children(co)).get((name, idx))
        if co is None:
            return None
    return co
