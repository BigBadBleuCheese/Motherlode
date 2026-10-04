"""Source-level syntax tree produced by the decompiler, and its rendering back to Python 3.7 source.

Nodes carry the line number their bytecode came from; rendering places them on those lines so the
recompiled line table matches the original and tracebacks from the game point at the right lines.
"""

import keyword
import math

YIELD = 0
TUPLE = 1
LAMBDA = 2
IFEXP = 3
OR = 4
AND = 5
NOT = 6
CMP = 7
BOR = 8
BXOR = 9
BAND = 10
SHIFT = 11
ARITH = 12
TERM = 13
UNARY = 14
POWER = 15
AWAIT = 16
PRIMARY = 17
ATOM = 18

BINARY_PREC = {
    "|": BOR, "^": BXOR, "&": BAND, "<<": SHIFT, ">>": SHIFT,
    "+": ARITH, "-": ARITH, "*": TERM, "@": TERM, "/": TERM, "//": TERM, "%": TERM, "**": POWER,
}

INDENT = "    "


class Writer:
    def __init__(self, track_lines=True):
        self.out = [""]
        self.depth = 0
        self.indent = ""
        self.track_lines = track_lines

    @property
    def line(self):
        return len(self.out)

    def write(self, text):
        self.out[-1] += text

    def newline(self):
        self.out.append("")

    def at(self, line):
        if not self.track_lines or line is None or line <= self.line:
            return
        if not self.out[-1].strip():
            pending = self.out[-1]
            self.out[-1] = ""
            while self.line < line:
                self.newline()
            self.write(pending)
            return
        while self.line < line:
            if self.depth == 0:
                self.write(" \\")
            self.newline()
        self.write(self.indent + INDENT)

    def statement(self, line):
        if self.out[-1].strip():
            self.newline()
        else:
            self.out[-1] = ""
        if self.track_lines and line is not None:
            while self.line < line:
                self.newline()
        self.write(self.indent)

    def expr(self, e, minimum):
        self.at(e.line)
        if e.prec < minimum:
            self.open("(")
            e.emit(self)
            self.close(")")
        else:
            e.emit(self)

    def open(self, text):
        self.write(text)
        self.depth += 1

    def close(self, text):
        self.depth -= 1
        self.write(text)

    def sequence(self, items, emit_item):
        for i, item in enumerate(items):
            if i:
                self.write(", ")
            emit_item(item)

    def text(self):
        return "\n".join(line.rstrip() for line in self.out).rstrip() + "\n"


def to_src(node, minimum=0):
    w = Writer(track_lines=False)
    w.expr(node, minimum)
    return w.text().rstrip("\n")


class Expr:
    prec = ATOM
    line = None

    def emit(self, w):
        raise NotImplementedError(type(self).__name__)

    def src(self):
        return to_src(self)

    def children(self):
        out = []
        for v in self.__dict__.values():
            if isinstance(v, Expr):
                out.append(v)
            elif isinstance(v, list):
                out.extend(x for x in v if isinstance(x, (Expr, Keyword)))
        return out

    def __repr__(self):
        try:
            return "<%s %s>" % (type(self).__name__, self.src())
        except Exception:
            return "<%s>" % type(self).__name__


class Name(Expr):
    def __init__(self, name):
        self.name = name

    def emit(self, w):
        w.write(self.name)


def _float_src(value):
    if math.isinf(value):
        return "1e309" if value > 0 else "-1e309"
    if math.isnan(value):
        return "(1e309 - 1e309)"
    return repr(value)


def const_src(v):
    if v is Ellipsis:
        return "..."
    if isinstance(v, float):
        return _float_src(v)
    if isinstance(v, complex):
        if v.real == 0 and math.copysign(1, v.real) > 0 and not math.isinf(v.imag) and not math.isnan(v.imag):
            return repr(v.imag) + "j"
        return repr(v)
    if isinstance(v, tuple):
        if len(v) == 1:
            return "(" + const_src(v[0]) + ",)"
        return "(" + ", ".join(const_src(x) for x in v) + ")"
    if isinstance(v, frozenset):
        if not v:
            return "frozenset()"
        return "{" + ", ".join(const_src(x) for x in sorted(v, key=repr)) + "}"
    return repr(v)


class Const(Expr):
    def __init__(self, value):
        self.value = value

    @property
    def prec(self):
        v = self.value
        if isinstance(v, bool) or v is None or v is Ellipsis:
            return ATOM
        if isinstance(v, (int, float)) and (v < 0 or (isinstance(v, float) and math.copysign(1, v) < 0)):
            return UNARY
        if isinstance(v, complex) and (v.real != 0 or math.copysign(1, v.real) < 0):
            return ARITH
        return ATOM

    def emit(self, w):
        w.write(const_src(self.value))


class Attribute(Expr):
    prec = PRIMARY

    def __init__(self, value, attr):
        self.value = value
        self.attr = attr

    def emit(self, w):
        v = self.value
        if isinstance(v, Const) and isinstance(v.value, int) and not isinstance(v.value, bool):
            w.at(v.line)
            w.write("(" + const_src(v.value) + ")")
        else:
            w.expr(v, PRIMARY)
        w.write("." + self.attr)


class Subscript(Expr):
    prec = PRIMARY

    def __init__(self, value, index):
        self.value = value
        self.index = index

    def emit(self, w):
        w.expr(self.value, PRIMARY)
        w.open("[")
        emit_index(w, self.index)
        w.close("]")


def emit_index(w, index):
    if isinstance(index, Tuple) and index.elts and not any(isinstance(e, Starred) for e in index.elts):
        w.at(index.line)
        for i, e in enumerate(index.elts):
            if i:
                w.write(", ")
            if isinstance(e, Slice):
                w.at(e.line)
                e.emit(w)
            else:
                w.expr(e, LAMBDA)
        if len(index.elts) == 1:
            w.write(",")
    elif isinstance(index, Slice):
        w.at(index.line)
        index.emit(w)
    else:
        w.expr(index, TUPLE)


class Slice(Expr):
    def __init__(self, lower, upper, step):
        self.lower = lower
        self.upper = upper
        self.step = step

    def emit(self, w):
        if self.lower is not None:
            w.expr(self.lower, LAMBDA)
        w.write(":")
        if self.upper is not None:
            w.expr(self.upper, LAMBDA)
        if self.step is not None:
            w.write(":")
            w.expr(self.step, LAMBDA)


class Starred(Expr):
    def __init__(self, value):
        self.value = value

    def emit(self, w):
        w.write("*")
        w.expr(self.value, BOR)


class Keyword:
    line = None

    def __init__(self, name, value):
        self.name = name
        self.value = value

    def emit(self, w):
        if self.name is None:
            w.at(self.value.line)
            w.write("**")
            w.expr(self.value, BOR)
        else:
            w.at(self.value.line)
            w.write(self.name + "=")
            w.expr(self.value, LAMBDA)


def emit_arg(w, a):
    if isinstance(a, Keyword):
        a.emit(w)
    elif isinstance(a, Starred):
        w.at(a.line)
        a.emit(w)
    else:
        w.expr(a, LAMBDA)


class Call(Expr):
    prec = PRIMARY

    def __init__(self, func, args, keywords):
        self.func = func
        self.args = args
        self.keywords = keywords

    def emit(self, w):
        w.expr(self.func, PRIMARY)
        if len(self.args) == 1 and not self.keywords and isinstance(self.args[0], GeneratorExp):
            w.at(self.args[0].line)
            self.args[0].emit(w)
            return
        w.open("(")
        w.sequence(list(self.args) + list(self.keywords), lambda a: emit_arg(w, a))
        w.close(")")


class BinOp(Expr):
    def __init__(self, left, op, right, inplace=False):
        self.left = left
        self.op = op
        self.right = right
        self.inplace = inplace
        self.prec = BINARY_PREC[op]

    def emit(self, w):
        if self.op == "**":
            w.expr(self.left, AWAIT)
            w.write(" ** ")
            w.expr(self.right, UNARY)
            return
        w.expr(self.left, self.prec)
        w.write(" " + self.op + " ")
        w.expr(self.right, self.prec + 1)


class UnaryOp(Expr):
    def __init__(self, op, operand):
        self.op = op
        self.operand = operand
        self.prec = NOT if op == "not" else UNARY

    def emit(self, w):
        if self.op == "not":
            w.write("not ")
            w.expr(self.operand, NOT)
            return
        w.write(self.op)
        o = self.operand
        nested = (isinstance(o, UnaryOp) and o.op in ("-", "+") and self.op in ("-", "+")) or (isinstance(o, Const) and o.prec == UNARY)
        if nested:
            w.open("(")
            w.expr(o, 0)
            w.close(")")
        else:
            w.expr(o, UNARY)


class BoolOp(Expr):
    def __init__(self, op, values):
        self.op = op
        self.values = values
        self.prec = OR if op == "or" else AND

    def emit(self, w):
        for i, v in enumerate(self.values):
            if i:
                w.write(" " + self.op + " ")
            w.expr(v, self.prec + 1)


class Compare(Expr):
    prec = CMP

    def __init__(self, left, ops, comparators):
        self.left = left
        self.ops = ops
        self.comparators = comparators

    def emit(self, w):
        w.expr(self.left, BOR)
        for op, c in zip(self.ops, self.comparators):
            w.write(" " + op + " ")
            w.expr(c, BOR)


class IfExp(Expr):
    prec = IFEXP

    def __init__(self, test, body, orelse):
        self.test = test
        self.body = body
        self.orelse = orelse

    def emit(self, w):
        w.expr(self.body, OR)
        w.write(" if ")
        w.expr(self.test, OR)
        w.write(" else ")
        w.expr(self.orelse, LAMBDA)


class Tuple(Expr):
    prec = TUPLE

    def __init__(self, elts):
        self.elts = elts

    def emit(self, w):
        if not self.elts:
            w.write("()")
            return
        w.sequence(self.elts, lambda e: emit_arg(w, e))
        if len(self.elts) == 1:
            w.write(",")


class List(Expr):
    def __init__(self, elts):
        self.elts = elts

    def emit(self, w):
        w.open("[")
        w.sequence(self.elts, lambda e: emit_arg(w, e))
        w.close("]")


class Set(Expr):
    def __init__(self, elts):
        self.elts = elts

    def emit(self, w):
        w.open("{")
        w.sequence(self.elts, lambda e: emit_arg(w, e))
        w.close("}")


class Dict(Expr):
    def __init__(self, keys, values):
        self.keys = keys
        self.values = values

    def children(self):
        return [k for k in self.keys if k is not None] + list(self.values)

    def emit(self, w):
        w.open("{")

        def item(pair):
            k, v = pair
            if k is None:
                w.at(v.line)
                w.write("**")
                w.expr(v, BOR)
            else:
                w.expr(k, LAMBDA)
                w.write(": ")
                w.expr(v, LAMBDA)
        w.sequence(list(zip(self.keys, self.values)), item)
        w.close("}")


class Yield(Expr):
    prec = YIELD

    def __init__(self, value):
        self.value = value

    def emit(self, w):
        if self.value is None:
            w.write("yield")
        else:
            w.write("yield ")
            w.expr(self.value, TUPLE)


class YieldFrom(Expr):
    prec = YIELD

    def __init__(self, value):
        self.value = value

    def emit(self, w):
        w.write("yield from ")
        w.expr(self.value, LAMBDA)


class Await(Expr):
    prec = AWAIT

    def __init__(self, value):
        self.value = value

    def emit(self, w):
        w.write("await ")
        w.expr(self.value, PRIMARY)


class Lambda(Expr):
    prec = LAMBDA

    def __init__(self, args, body):
        self.args = args
        self.body = body

    def children(self):
        return self.args.children() + [self.body]

    def emit(self, w):
        w.write("lambda")
        if self.args.has_any():
            w.write(" ")
            self.args.emit(w, lambda_=True)
        w.write(": ")
        w.expr(self.body, LAMBDA)


class Comprehension:
    line = None

    def __init__(self, target, iter, ifs, is_async=False):
        self.target = target
        self.iter = iter
        self.ifs = ifs
        self.is_async = is_async

    def emit(self, w):
        w.write(" async for " if self.is_async else " for ")
        emit_target(w, self.target)
        w.write(" in ")
        w.expr(self.iter, OR)
        for cond in self.ifs:
            w.write(" if ")
            w.expr(cond, OR)


class ListComp(Expr):
    brackets = "[]"

    def __init__(self, elt, generators):
        self.elt = elt
        self.generators = generators

    def children(self):
        out = [self.elt]
        for g in self.generators:
            out.append(g.iter)
            out.extend(g.ifs)
        return out

    def emit(self, w):
        w.open(self.brackets[0])
        w.expr(self.elt, LAMBDA)
        for g in self.generators:
            g.emit(w)
        w.close(self.brackets[1])


class SetComp(ListComp):
    brackets = "{}"


class GeneratorExp(ListComp):
    brackets = "()"


class DictComp(Expr):
    def __init__(self, key, value, generators):
        self.key = key
        self.value = value
        self.generators = generators

    def children(self):
        out = [self.key, self.value]
        for g in self.generators:
            out.append(g.iter)
            out.extend(g.ifs)
        return out

    def emit(self, w):
        w.open("{")
        w.expr(self.key, LAMBDA)
        w.write(": ")
        w.expr(self.value, LAMBDA)
        for g in self.generators:
            g.emit(w)
        w.close("}")


class FormattedValue(Expr):
    def __init__(self, value, conversion, spec):
        self.value = value
        self.conversion = conversion
        self.spec = spec

    def emit(self, w):
        JoinedStr([self]).emit(w)


class JoinedStr(Expr):
    def __init__(self, values):
        self.values = values

    def _pieces(self, quote):
        out = []
        for v in self.values:
            if isinstance(v, Const):
                out.append(_escape_fstring_literal(v.value, quote))
            elif isinstance(v, FormattedValue):
                inner = to_src(v.value, LAMBDA)
                if inner.startswith("{"):
                    inner = " " + inner
                text = "{" + inner
                if v.conversion:
                    text += "!" + v.conversion
                if v.spec is not None:
                    spec = v.spec
                    if isinstance(spec, Const):
                        text += ":" + _escape_fstring_literal(spec.value, quote)
                    elif isinstance(spec, JoinedStr):
                        text += ":" + spec._pieces(quote)
                    elif isinstance(spec, FormattedValue):
                        text += ":" + JoinedStr([spec])._pieces(quote)
                    else:
                        raise ValueError("unsupported format spec")
                text += "}"
                out.append(text)
            else:
                raise ValueError("unsupported f-string part")
        return "".join(out)

    def _expr_text(self):
        parts = []

        def walk(values):
            for v in values:
                if isinstance(v, FormattedValue):
                    parts.append(to_src(v.value, LAMBDA))
                    if isinstance(v.spec, JoinedStr):
                        walk(v.spec.values)
                    elif isinstance(v.spec, FormattedValue):
                        walk([v.spec])
        walk(self.values)
        return "".join(parts)

    def emit(self, w):
        exprs = self._expr_text()
        if "\\" in exprs:
            raise ValueError("f-string expression cannot contain a backslash")
        for quote in ("'", '"', "'''", '"""'):
            if quote not in exprs and quote[0] not in exprs:
                w.write("f" + quote + self._pieces(quote) + quote)
                return
        raise ValueError("no usable quote for f-string")


def _escape_fstring_literal(text, quote):
    body = repr(text)
    if body[0] == '"' and quote != '"':
        body = body[1:-1].replace("\\\"", "\"").replace(quote[0], "\\" + quote[0])
    elif body[0] == "'" and quote != "'":
        body = body[1:-1].replace("\\'", "'").replace(quote[0], "\\" + quote[0])
    else:
        body = body[1:-1]
    return body.replace("{", "{{").replace("}", "}}")


class Arguments:
    def __init__(self, args, vararg, kwonly, kwarg, defaults, kw_defaults, annotations, future_annotations):
        self.args = args
        self.vararg = vararg
        self.kwonly = kwonly
        self.kwarg = kwarg
        self.defaults = defaults
        self.kw_defaults = kw_defaults
        self.annotations = annotations
        self.future_annotations = future_annotations

    def children(self):
        return list(self.defaults) + list(self.kw_defaults.values()) + list(self.annotations.values())

    def has_any(self):
        return bool(self.args or self.vararg or self.kwonly or self.kwarg)

    def emit(self, w, lambda_=False):
        items = []
        first_default = len(self.args) - len(self.defaults)
        for i, a in enumerate(self.args):
            items.append((a, "", self.defaults[i - first_default] if i >= first_default else None))
        if self.vararg is not None:
            items.append((self.vararg, "*", None))
        elif self.kwonly:
            items.append((None, "*", None))
        for k in self.kwonly:
            items.append((k, "", self.kw_defaults.get(k)))
        if self.kwarg is not None:
            items.append((self.kwarg, "**", None))

        def item(entry):
            name, prefix, default = entry
            ann = None if lambda_ or name is None else self.annotations.get(name)
            if ann is not None:
                w.at(ann.line)
            w.write(prefix + (name or ""))
            if ann is not None:
                w.write(": ")
                emit_annotation(w, ann, self.future_annotations)
            if default is not None:
                w.write(" = " if ann is not None else "=")
                w.expr(default, LAMBDA)
        w.sequence(items, item)


def emit_annotation(w, ann, future):
    if future and isinstance(ann, Const) and isinstance(ann.value, str):
        w.at(ann.line)
        w.write(ann.value)
    else:
        w.expr(ann, LAMBDA)


def emit_target(w, target, nested=False):
    if isinstance(target, Tuple):
        if nested or not target.elts:
            w.open("(")
        for i, e in enumerate(target.elts):
            if i:
                w.write(", ")
            emit_target(w, e, True)
        if len(target.elts) == 1:
            w.write(",")
        if nested or not target.elts:
            w.close(")")
    elif isinstance(target, Starred):
        w.write("*")
        emit_target(w, target.value, True)
    else:
        w.expr(target, PRIMARY)


def emit_rhs(w, value):
    if isinstance(value, Tuple) and value.elts:
        w.at(value.line)
        value.emit(w)
    else:
        w.expr(value, YIELD)


def spans_lines(node, line):
    if line is None or node is None:
        return False
    stack = [node]
    while stack:
        n = stack.pop()
        if n is None:
            continue
        nl = getattr(n, "line", None)
        if nl is not None and nl > line:
            return True
        if isinstance(n, (JoinedStr, FormattedValue)):
            continue
        if isinstance(n, (Expr, Arguments)):
            stack.extend(n.children())
        elif isinstance(n, Keyword):
            stack.append(n.value)
    return False


def emit_value(w, value, emit):
    emit(w, value)


class Stmt:
    line = None
    compound = False

    def emit(self, w):
        raise NotImplementedError(type(self).__name__)


class Assign(Stmt):
    def __init__(self, targets, value):
        self.targets = targets
        self.value = value

    def emit(self, w):
        for t in self.targets:
            emit_target(w, t, nested=len(self.targets) > 1 and isinstance(t, Tuple))
            w.write(" = ")
        emit_value(w, self.value, emit_rhs)


class AugAssign(Stmt):
    def __init__(self, target, op, value):
        self.target = target
        self.op = op
        self.value = value

    def emit(self, w):
        emit_target(w, self.target)
        w.write(" " + self.op + "= ")
        emit_value(w, self.value, emit_rhs)


class AnnAssign(Stmt):
    def __init__(self, target, annotation, value, future):
        self.target = target
        self.annotation = annotation
        self.value = value
        self.future = future

    def emit(self, w):
        emit_target(w, self.target)
        w.write(": ")
        emit_annotation(w, self.annotation, self.future)
        if self.value is not None:
            w.write(" = ")
            emit_value(w, self.value, lambda w_, v: w_.expr(v, LAMBDA))


class ExprStmt(Stmt):
    def __init__(self, value):
        self.value = value

    def emit(self, w):
        emit_value(w, self.value, emit_rhs)


class Return(Stmt):
    def __init__(self, value):
        self.value = value

    def emit(self, w):
        if self.value is None:
            w.write("return")
            return
        w.write("return ")
        if isinstance(self.value, Tuple) and self.value.elts:
            w.at(self.value.line)
            self.value.emit(w)
        else:
            w.expr(self.value, TUPLE)


class Raise(Stmt):
    def __init__(self, exc, cause):
        self.exc = exc
        self.cause = cause

    def emit(self, w):
        if self.exc is None:
            w.write("raise")
            return
        w.write("raise ")
        w.expr(self.exc, LAMBDA)
        if self.cause is not None:
            w.write(" from ")
            w.expr(self.cause, LAMBDA)


class Delete(Stmt):
    def __init__(self, targets):
        self.targets = targets

    def emit(self, w):
        w.write("del ")
        for i, t in enumerate(self.targets):
            if i:
                w.write(", ")
            emit_target(w, t, True)


class Simple(Stmt):
    def __init__(self, text):
        self.text = text

    def emit(self, w):
        w.write(self.text)


def Pass():
    return Simple("pass")


def Break():
    return Simple("break")


def Continue():
    return Simple("continue")


class Global(Stmt):
    def __init__(self, names, nonlocal_=False):
        self.names = names
        self.nonlocal_ = nonlocal_

    def emit(self, w):
        w.write(("nonlocal " if self.nonlocal_ else "global ") + ", ".join(self.names))


class Import(Stmt):
    def __init__(self, module, asname):
        self.module = module
        self.asname = asname

    def emit(self, w):
        w.write("import " + self.module + (" as " + self.asname if self.asname else ""))


class ImportFrom(Stmt):
    def __init__(self, module, names, level):
        self.module = module
        self.names = names
        self.level = level

    def emit(self, w):
        names = ", ".join(n if a is None or a == n else n + " as " + a for n, a in self.names)
        w.write("from " + "." * self.level + (self.module or "") + " import " + names)


def emit_block(w, stmts, header_line):
    stmts = stmts or [Pass()]
    outer = w.indent
    w.indent = outer + INDENT
    inline = (w.track_lines and header_line is not None and all(not s.compound for s in stmts)
              and all(s.line == header_line for s in stmts) and len(stmts) <= 3)
    if inline:
        w.write(" ")
        for i, s in enumerate(stmts):
            if i:
                w.write("; ")
            s.emit(w)
    else:
        emit_statements(w, stmts)
    w.indent = outer


def emit_statements(w, stmts):
    prev = None
    for s in stmts:
        if (w.track_lines and prev is not None and not prev.compound and not s.compound and s.line is not None
                and s.line == w.line and prev.line == s.line):
            w.write("; ")
        else:
            w.statement(s.line)
        s.emit(w)
        prev = s


def emit_header_expr(w, expr):
    w.expr(expr, LAMBDA)


class If(Stmt):
    compound = True

    def __init__(self, test, body, orelse):
        self.test = test
        self.body = body
        self.orelse = orelse

    def emit(self, w, keyword_="if"):
        w.write(keyword_ + " ")
        emit_header_expr(w, self.test)
        w.write(":")
        emit_block(w, self.body, w.line)
        if self.orelse:
            if len(self.orelse) == 1 and isinstance(self.orelse[0], If):
                w.statement(self.orelse[0].line)
                self.orelse[0].emit(w, "elif")
            else:
                w.statement(None)
                w.write("else:")
                emit_block(w, self.orelse, w.line)


class While(Stmt):
    compound = True

    def __init__(self, test, body, orelse):
        self.test = test
        self.body = body
        self.orelse = orelse

    def emit(self, w):
        w.write("while ")
        emit_header_expr(w, self.test)
        w.write(":")
        emit_block(w, self.body, w.line)
        if self.orelse:
            w.statement(None)
            w.write("else:")
            emit_block(w, self.orelse, w.line)


class For(Stmt):
    compound = True

    def __init__(self, target, iter, body, orelse, is_async=False):
        self.target = target
        self.iter = iter
        self.body = body
        self.orelse = orelse
        self.is_async = is_async

    def emit(self, w):
        w.write("async for " if self.is_async else "for ")
        emit_target(w, self.target)
        w.write(" in ")
        if isinstance(self.iter, Tuple) and self.iter.elts:
            w.at(self.iter.line)
            self.iter.emit(w)
        else:
            w.expr(self.iter, LAMBDA)
        w.write(":")
        emit_block(w, self.body, w.line)
        if self.orelse:
            w.statement(None)
            w.write("else:")
            emit_block(w, self.orelse, w.line)


class Handler:
    def __init__(self, type_, name, body, line=None):
        self.type = type_
        self.name = name
        self.body = body
        self.line = line


class Try(Stmt):
    compound = True

    def __init__(self, body, handlers, orelse, finalbody):
        self.body = body
        self.handlers = handlers
        self.orelse = orelse
        self.finalbody = finalbody

    def emit(self, w):
        w.write("try:")
        emit_block(w, self.body, w.line)
        for h in self.handlers:
            w.statement(h.line)
            if h.type is None:
                w.write("except:")
            else:
                w.write("except ")
                emit_header_expr(w, h.type)
                if h.name:
                    w.write(" as " + h.name)
                w.write(":")
            emit_block(w, h.body, w.line)
        if self.orelse:
            w.statement(None)
            w.write("else:")
            emit_block(w, self.orelse, w.line)
        if self.finalbody is not None:
            w.statement(None)
            w.write("finally:")
            emit_block(w, self.finalbody, w.line)


class With(Stmt):
    compound = True

    def __init__(self, items, body, is_async=False):
        self.items = items
        self.body = body
        self.is_async = is_async

    def emit(self, w):
        w.write("async with " if self.is_async else "with ")
        for i, (ctx, target) in enumerate(self.items):
            if i:
                w.write(", ")
            w.expr(ctx, LAMBDA)
            if target is not None:
                w.write(" as ")
                emit_target(w, target, True)
        w.write(":")
        emit_block(w, self.body, w.line)


def emit_decorators(w, decorators):
    for i, d in enumerate(decorators):
        if i:
            w.statement(d.line)
        w.write("@")
        if isinstance(d, (Call, Attribute, Name)):
            w.at(d.line)
            d.emit(w)
        else:
            w.expr(d, PRIMARY)
    if decorators:
        w.statement(None)


class FunctionDef(Stmt):
    compound = True

    def __init__(self, name, args, body, decorators, returns, future_annotations, is_async=False):
        self.name = name
        self.args = args
        self.body = body
        self.decorators = decorators
        self.returns = returns
        self.future_annotations = future_annotations
        self.is_async = is_async

    def emit(self, w):
        emit_decorators(w, self.decorators)
        w.write(("async def " if self.is_async else "def ") + self.name)
        w.open("(")
        self.args.emit(w)
        w.close(")")
        if self.returns is not None:
            w.write(" -> ")
            emit_annotation(w, self.returns, self.future_annotations)
        w.write(":")
        emit_block(w, self.body, w.line)


class ClassDef(Stmt):
    compound = True

    def __init__(self, name, bases, keywords, body, decorators):
        self.name = name
        self.bases = bases
        self.keywords = keywords
        self.body = body
        self.decorators = decorators

    def emit(self, w):
        emit_decorators(w, self.decorators)
        w.write("class " + self.name)
        args = list(self.bases) + list(self.keywords)
        if args:
            w.open("(")
            w.sequence(args, lambda a: emit_arg(w, a))
            w.close(")")
        w.write(":")
        emit_block(w, self.body, w.line)


class Unsupported(Stmt):
    def __init__(self, reason):
        self.reason = reason

    def emit(self, w):
        w.write("raise NotImplementedError(" + repr("motherlode could not decompile this: " + self.reason) + ")")


def render(stmts, track_lines=True):
    w = Writer(track_lines)
    emit_statements(w, stmts)
    return w.text()


def is_identifier(text):
    return isinstance(text, str) and text.isidentifier() and not keyword.iskeyword(text)
