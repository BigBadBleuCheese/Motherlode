"""Reconstructs Python 3.7 source from code objects compiled by CPython 3.7."""

import dis
import types

from .bytecode import (
    CO_ASYNC_GENERATOR, CO_COROUTINE, CO_FUTURE_ANNOTATIONS, CO_GENERATOR, CO_OPTIMIZED,
    CO_VARARGS, CO_VARKEYWORDS, OR_POP_JUMPS, POP_JUMPS, UNCONDITIONAL, decode,
)
from . import syntax as S


class Fail(Exception):
    pass


BINARY_OPS = {
    "BINARY_POWER": "**", "BINARY_MULTIPLY": "*", "BINARY_MATRIX_MULTIPLY": "@", "BINARY_FLOOR_DIVIDE": "//",
    "BINARY_TRUE_DIVIDE": "/", "BINARY_MODULO": "%", "BINARY_ADD": "+", "BINARY_SUBTRACT": "-",
    "BINARY_LSHIFT": "<<", "BINARY_RSHIFT": ">>", "BINARY_AND": "&", "BINARY_XOR": "^", "BINARY_OR": "|",
}
INPLACE_OPS = {k.replace("BINARY_", "INPLACE_"): v for k, v in BINARY_OPS.items()}
UNARY_OPS = {"UNARY_POSITIVE": "+", "UNARY_NEGATIVE": "-", "UNARY_NOT": "not", "UNARY_INVERT": "~"}
COMPREHENSIONS = ("<listcomp>", "<setcomp>", "<dictcomp>", "<genexpr>")
CONVERSIONS = {0: None, 1: "s", 2: "r", 3: "a"}


class Marker(S.Expr):
    def emit(self, w):
        raise Fail("internal marker reached output: " + type(self).__name__)


class CodeRef(Marker):
    def __init__(self, code):
        self.code = code


class MethodRef(Marker):
    def __init__(self, obj, name):
        self.obj = obj
        self.name = name


class GetIter(Marker):
    def __init__(self, value):
        self.value = value


class YieldFromIter(Marker):
    def __init__(self, value):
        self.value = value


class CallStar(Marker):
    def __init__(self, items):
        self.items = items


class CallKw(Marker):
    def __init__(self, items):
        self.items = items


class BuildClass(Marker):
    pass


class ClosureRef(Marker):
    def __init__(self, name):
        self.name = name


class FunctionObj(Marker):
    def __init__(self, code, defaults, kwdefaults, annotations):
        self.code = code
        self.defaults = defaults
        self.kwdefaults = kwdefaults
        self.annotations = annotations


class ClassObj(Marker):
    def __init__(self, func, name, bases, keywords):
        self.func = func
        self.name = name
        self.bases = bases
        self.keywords = keywords


class Unpack(Marker):
    def __init__(self, source, count, star):
        self.source = source
        self.targets = [None] * count
        self.star = star
        self.filled = 0


class UnpackSlot(Marker):
    def __init__(self, unpack, index):
        self.unpack = unpack
        self.index = index


class Chain(Marker):
    def __init__(self, source):
        self.source = source
        self.targets = []


class Placeholder(Marker):
    def __init__(self):
        self.target = None
        self.done = False


class ImportModule(Marker):
    def __init__(self, name, fromlist, level):
        self.name = name
        self.fromlist = fromlist
        self.level = level
        self.names = []


class ImportedName(Marker):
    def __init__(self, module, name):
        self.module = module
        self.name = name


class Atom:
    __slots__ = ("expr", "index", "kind", "target", "after")

    def __init__(self, expr, index, kind, target, after):
        self.expr = expr
        self.index = index
        self.kind = kind
        self.target = target
        self.after = after

    @property
    def sense(self):
        return self.kind in ("POP_JUMP_IF_TRUE", "JUMP_IF_TRUE_OR_POP")


class Loop:
    def __init__(self, top):
        self.top = top


class Frame:
    def __init__(self, start, end, loop, mode, stack=None, stop_at=(), stop_after_return=False):
        self.i = start
        self.start = start
        self.end = end
        self.loop = loop
        self.mode = mode
        self.stack = list(stack) if stack else []
        self.stmts = []
        self.stop = None
        self.stop_at = stop_at
        self.stop_after_return = stop_after_return
        self.exit = None
        self.placeholder = None
        self.pending = None


def is_none(expr):
    return isinstance(expr, S.Const) and expr.value is None


def simple(fn):
    def wrapper(self, frame, op):
        fn(self, frame, op)
        frame.i += 1
    return wrapper


class Session:
    """Decisions forced for particular code objects, and the decision points each one reached."""

    def __init__(self):
        self.forced = {}
        self.points = {}

    def choice(self, code, key):
        return self.forced.get(code, {}).get(key, 0)

    def record(self, code, key):
        pts = self.points.setdefault(code, [])
        if key not in pts:
            pts.append(key)


class CodeDecompiler:
    def __init__(self, code, private=None, session=None):
        self.session = session or Session()
        self.private = code.co_name if (not code.co_flags & CO_OPTIMIZED and code.co_name != "<module>") else private
        self.code = code
        self.ins = decode(code)
        self.n = len(self.ins)
        self.lines = line_table(code, self.ins)
        self.future_annotations = bool(code.co_flags & CO_FUTURE_ANNOTATIONS)
        self.memo_atoms = {}
        if code.co_name == "<module>":
            self.kind = "module"
        elif code.co_name == "<lambda>":
            self.kind = "lambda"
        elif code.co_name in COMPREHENSIONS and code.co_argcount == 1 and code.co_varnames[:1] == (".0",):
            self.kind = "comprehension"
        elif not code.co_flags & CO_OPTIMIZED:
            self.kind = "class"
        else:
            self.kind = "function"

    def resolve(self, index):
        steps = 0
        while index is not None and index < self.n and self.ins[index].opname in UNCONDITIONAL and steps < 64:
            nxt = self.ins[index].target
            if nxt == index:
                break
            index = nxt
            steps += 1
        return index

    def exit_of(self, end):
        if end >= self.n:
            return None
        return self.resolve(end)

    def run(self, frame):
        frame.exit = self.exit_of(frame.end)
        ins = self.ins
        while frame.i < frame.end and frame.stop is None:
            op = ins[frame.i]
            if not frame.stack and frame.pending is None:
                frame.pending = frame.i
            if frame.mode == "cmp" and len(frame.stack) == 1 and (op.opname == "COMPARE_OP" or (op.opname == "DUP_TOP" and ins[frame.i + 1].opname == "ROT_THREE")):
                return frame
            if frame.stop_at and op.opname in frame.stop_at and not frame.stack:
                frame.stop = op.opname
                break
            handler = getattr(self, "op_" + op.opname, None)
            if handler is None:
                raise Fail("unsupported opcode " + op.opname)
            emitted = len(frame.stmts)
            handler(frame, op)
            if not frame.stack and len(frame.stmts) == emitted:
                frame.pending = None
            if frame.mode == "target" and frame.placeholder.done and not frame.stack:
                frame.stop = "target"
        if frame.stop is None and frame.i != frame.end:
            raise Fail("walked past the end of a region [%d, %d) to %d" % (frame.start, frame.end, frame.i))
        return frame

    def block(self, start, end, loop, stop_at=(), stop_after_return=False):
        frame = self.run(Frame(start, end, loop, "stmt", stop_at=stop_at, stop_after_return=stop_after_return))
        if frame.stack:
            raise Fail("values left on the stack at the end of a block")
        return frame

    def body(self, start, end, loop):
        return self.block(start, end, loop).stmts

    def eval_range(self, start, end, stack):
        frame = self.run(Frame(start, end, None, "expr", stack))
        if frame.stop is not None:
            raise Fail("expression evaluation stopped early")
        return frame.stack

    def eval_one(self, start, end):
        stack = self.eval_range(start, end, [])
        if len(stack) != 1:
            raise Fail("expected exactly one value")
        return stack[0]

    def emit(self, frame, stmt):
        if frame.mode != "stmt":
            raise Fail("statement inside an expression")
        if stmt.line is None:
            start = frame.pending if frame.pending is not None else min(frame.i, self.n - 1)
            stmt.line = self.lines[start] if self.n else None
        frame.pending = None
        frame.stmts.append(stmt)

    def push(self, frame, value):
        self.mark(value, frame.i)
        frame.stack.append(value)

    def mark(self, value, index):
        if isinstance(value, S.Expr) and value.line is None:
            lines = [c.line for c in value.children() if getattr(c, "line", None) is not None]
            if lines:
                value.line = min(lines)
            elif index < self.n:
                value.line = self.lines[index]
        return value

    def pop(self, frame):
        if not frame.stack:
            raise Fail("stack underflow")
        return frame.stack.pop()

    def popn(self, frame, count):
        if count == 0:
            return []
        if len(frame.stack) < count:
            raise Fail("stack underflow")
        items = frame.stack[-count:]
        del frame.stack[-count:]
        return items

    @simple
    def op_NOP(self, frame, op):
        pass

    @simple
    def op_LOAD_CONST(self, frame, op):
        v = op.argval
        if isinstance(v, types.CodeType):
            self.push(frame, CodeRef(v))
        else:
            self.push(frame, S.Const(v))

    @simple
    def op_LOAD_NAME(self, frame, op):
        self.push(frame, S.Name(op.argval))

    op_LOAD_GLOBAL = op_LOAD_FAST = op_LOAD_DEREF = op_LOAD_CLASSDEREF = op_LOAD_NAME

    @simple
    def op_LOAD_CLOSURE(self, frame, op):
        self.push(frame, ClosureRef(op.argval))

    @simple
    def op_LOAD_ATTR(self, frame, op):
        self.push(frame, S.Attribute(self.value(self.pop(frame)), op.argval))

    @simple
    def op_LOAD_METHOD(self, frame, op):
        self.push(frame, MethodRef(self.value(self.pop(frame)), op.argval))

    @simple
    def op_CALL_METHOD(self, frame, op):
        args = [self.value(a) for a in self.popn(frame, op.arg)]
        m = self.pop(frame)
        if not isinstance(m, MethodRef):
            raise Fail("CALL_METHOD without LOAD_METHOD")
        self.push(frame, S.Call(S.Attribute(m.obj, m.name), args, []))

    def value(self, v):
        if isinstance(v, Chain):
            if v.targets:
                raise Fail("partially assigned value reused")
            return self.value(v.source)
        if isinstance(v, (MethodRef, Unpack, UnpackSlot, Chain, Placeholder, ImportModule, ImportedName,
                          CallStar, CallKw, BuildClass, ClosureRef, YieldFromIter, CodeRef)):
            raise Fail("marker used as a value: " + type(v).__name__)
        if isinstance(v, GetIter):
            raise Fail("GET_ITER result used as a value")
        if isinstance(v, FunctionObj):
            return self.function_expr(v)
        if isinstance(v, ClassObj):
            raise Fail("class object used as a value")
        return v

    def function_expr(self, fn):
        if fn.code.co_name == "<lambda>":
            return S.Lambda(self.arguments(fn), self.child(fn.code).lambda_body())
        raise Fail("function object used as a value")

    def make_call(self, func, args, keywords):
        if isinstance(func, BuildClass):
            if len(args) < 2 or not isinstance(args[0], FunctionObj) or not isinstance(args[1], S.Const):
                raise Fail("malformed class creation")
            return ClassObj(args[0], args[1].value, [self.value(a) for a in args[2:]], keywords)
        if isinstance(func, FunctionObj) and func.code.co_name in COMPREHENSIONS:
            if len(args) != 1 or keywords or not isinstance(args[0], GetIter):
                raise Fail("malformed comprehension call")
            return self.child(func.code).comprehension(self.value(args[0].value))
        if len(args) == 1 and not keywords and self.is_definition(args[0]):
            return S.Call(self.value(func), args, keywords)
        return S.Call(self.value(func), [a if isinstance(a, S.Starred) else self.value(a) for a in args], keywords)

    def is_definition(self, v):
        if isinstance(v, FunctionObj):
            return v.code.co_name != "<lambda>"
        if isinstance(v, ClassObj):
            return True
        if isinstance(v, S.Call) and len(v.args) == 1 and not v.keywords:
            return self.is_definition(v.args[0])
        return False

    @simple
    def op_CALL_FUNCTION(self, frame, op):
        args = self.popn(frame, op.arg)
        func = self.pop(frame)
        self.push(frame, self.make_call(func, args, []))

    @simple
    def op_CALL_FUNCTION_KW(self, frame, op):
        names = self.pop(frame)
        if not isinstance(names, S.Const) or not isinstance(names.value, tuple):
            raise Fail("CALL_FUNCTION_KW without names")
        args = self.popn(frame, op.arg)
        func = self.pop(frame)
        k = len(names.value)
        pos = args[:len(args) - k]
        kws = [S.Keyword(n, self.value(v)) for n, v in zip(names.value, args[len(args) - k:])]
        self.push(frame, self.make_call(func, pos, kws))

    @simple
    def op_CALL_FUNCTION_EX(self, frame, op):
        kwargs = self.pop(frame) if op.arg & 1 else None
        star = self.pop(frame)
        func = self.pop(frame)
        args = []
        positional_star = True
        if isinstance(star, CallStar):
            for item in star.items:
                args.extend(self.spread(item, S.Starred))
        elif isinstance(star, S.Tuple) or (isinstance(star, S.Const) and isinstance(star.value, tuple)):
            args.extend(self.spread(star, S.Starred))
            positional_star = False
        else:
            args.append(S.Starred(self.value(star)))
        keywords = []
        if kwargs is not None:
            if isinstance(kwargs, CallKw):
                for item in kwargs.items:
                    keywords.extend(self.kw_spread(item, True))
            else:
                keywords.extend(self.kw_spread(kwargs, positional_star))
        self.push(frame, self.make_call(func, args, keywords))

    def const_like(self, value, source):
        c = S.Const(value)
        c.line = source.line
        return c

    def spread(self, item, starred):
        if isinstance(item, S.Tuple):
            return [self.arg_value(e) for e in item.elts]
        if isinstance(item, S.Const) and isinstance(item.value, tuple):
            return [self.const_like(v, item) for v in item.value]
        return [starred(self.value(item))]

    def kw_spread(self, item, allow_names):
        if allow_names and isinstance(item, S.Dict) and item.keys and getattr(item, "display", False):
            names = []
            for k in item.keys:
                if not isinstance(k, S.Const) or not S.is_identifier(k.value) or k.value in names:
                    break
                names.append(k.value)
            else:
                return [S.Keyword(n, v) for n, v in zip(names, item.values)]
        return [S.Keyword(None, self.value(item))]

    def arg_value(self, v):
        if self.is_definition(v):
            return v
        return self.value(v)

    @simple
    def op_BUILD_TUPLE(self, frame, op):
        items = self.popn(frame, op.arg)
        if items and all(isinstance(i, ClosureRef) for i in items):
            self.push(frame, ClosureRef(None))
            return
        self.push(frame, S.Tuple([self.arg_value(i) for i in items]))

    @simple
    def op_BUILD_LIST(self, frame, op):
        self.push(frame, S.List([self.value(i) for i in self.popn(frame, op.arg)]))

    @simple
    def op_BUILD_SET(self, frame, op):
        self.push(frame, S.Set([self.value(i) for i in self.popn(frame, op.arg)]))

    @simple
    def op_BUILD_MAP(self, frame, op):
        items = [self.value(i) for i in self.popn(frame, op.arg * 2)]
        d = S.Dict(items[0::2], items[1::2])
        d.display = True
        self.push(frame, d)

    @simple
    def op_BUILD_CONST_KEY_MAP(self, frame, op):
        keys = self.pop(frame)
        if not isinstance(keys, S.Const) or not isinstance(keys.value, tuple):
            raise Fail("BUILD_CONST_KEY_MAP without keys")
        values = [self.value(v) for v in self.popn(frame, op.arg)]
        d = S.Dict([self.const_like(k, v) for k, v in zip(keys.value, values)], values)
        d.display = True
        self.push(frame, d)

    @simple
    def op_BUILD_TUPLE_UNPACK_WITH_CALL(self, frame, op):
        self.push(frame, CallStar(self.popn(frame, op.arg)))

    @simple
    def op_BUILD_MAP_UNPACK_WITH_CALL(self, frame, op):
        self.push(frame, CallKw(self.popn(frame, op.arg)))

    def unpack_display(self, frame, op, cls):
        elts = []
        for item in self.popn(frame, op.arg):
            elts.extend(self.spread(item, S.Starred))
        self.push(frame, cls(elts))

    @simple
    def op_BUILD_TUPLE_UNPACK(self, frame, op):
        self.unpack_display(frame, op, S.Tuple)

    @simple
    def op_BUILD_LIST_UNPACK(self, frame, op):
        self.unpack_display(frame, op, S.List)

    @simple
    def op_BUILD_SET_UNPACK(self, frame, op):
        self.unpack_display(frame, op, S.Set)

    @simple
    def op_BUILD_MAP_UNPACK(self, frame, op):
        keys, values = [], []
        for item in self.popn(frame, op.arg):
            if isinstance(item, S.Dict) and getattr(item, "display", False):
                keys.extend(item.keys)
                values.extend(item.values)
            else:
                keys.append(None)
                values.append(self.value(item))
        self.push(frame, S.Dict(keys, values))

    @simple
    def op_BUILD_SLICE(self, frame, op):
        parts = [self.value(p) for p in self.popn(frame, op.arg)]
        parts = [None if is_none(p) else p for p in parts]
        if op.arg == 2:
            self.push(frame, S.Slice(parts[0], parts[1], None))
        else:
            self.push(frame, S.Slice(parts[0], parts[1], parts[2] if parts[2] is not None else S.Const(None)))

    @simple
    def op_BINARY_SUBSCR(self, frame, op):
        index = self.value(self.pop(frame))
        self.push(frame, S.Subscript(self.value(self.pop(frame)), index))

    def binary(self, frame, op, symbol, inplace):
        right = self.value(self.pop(frame))
        left = self.value(self.pop(frame))
        self.push(frame, S.BinOp(left, symbol, right, inplace))

    @simple
    def op_COMPARE_OP(self, frame, op):
        right = self.value(self.pop(frame))
        left = self.value(self.pop(frame))
        if op.argval == "exception match":
            raise Fail("exception match outside an except clause")
        self.push(frame, S.Compare(left, [op.argval], [right]))

    @simple
    def op_FORMAT_VALUE(self, frame, op):
        spec = self.value(self.pop(frame)) if op.arg & 4 else None
        value = self.value(self.pop(frame))
        if isinstance(spec, S.Const) and not isinstance(spec.value, str):
            raise Fail("non-string format spec")
        self.push(frame, S.FormattedValue(value, CONVERSIONS[op.arg & 3], spec))

    @simple
    def op_BUILD_STRING(self, frame, op):
        parts = []
        for p in self.popn(frame, op.arg):
            p = self.value(p)
            if isinstance(p, S.Const) and isinstance(p.value, str):
                parts.append(p)
            elif isinstance(p, S.FormattedValue):
                parts.append(p)
            elif isinstance(p, S.JoinedStr):
                parts.extend(p.values)
            else:
                raise Fail("unexpected f-string part")
        self.push(frame, S.JoinedStr(parts))

    @simple
    def op_GET_ITER(self, frame, op):
        self.push(frame, GetIter(self.pop(frame)))

    @simple
    def op_YIELD_VALUE(self, frame, op):
        v = self.value(self.pop(frame))
        self.push(frame, S.Yield(None if is_none(v) else v))

    @simple
    def op_GET_YIELD_FROM_ITER(self, frame, op):
        self.push(frame, YieldFromIter(self.value(self.pop(frame))))

    @simple
    def op_GET_AWAITABLE(self, frame, op):
        self.push(frame, S.Await(self.value(self.pop(frame))))

    @simple
    def op_YIELD_FROM(self, frame, op):
        none = self.pop(frame)
        it = self.pop(frame)
        if not is_none(none):
            raise Fail("YIELD_FROM without None")
        if isinstance(it, YieldFromIter):
            self.push(frame, S.YieldFrom(it.value))
        elif isinstance(it, S.Await):
            self.push(frame, it)
        else:
            raise Fail("YIELD_FROM without an iterator")

    def op_DUP_TOP(self, frame, op):
        if frame.i + 2 < self.n and self.ins[frame.i + 1].opname == "ROT_THREE" and self.ins[frame.i + 2].opname == "COMPARE_OP" and len(frame.stack) >= 2:
            self.chained_compare(frame)
            return
        self.plain_dup_top(frame, op)
        frame.i += 1

    def plain_dup_top(self, frame, op):
        top = frame.stack[-1] if frame.stack else None
        if top is None:
            raise Fail("DUP_TOP on empty stack")
        if not isinstance(top, (ClosureRef, Marker)) or isinstance(top, Chain):
            chain = top if isinstance(top, Chain) else Chain(top)
            frame.stack[-1] = chain
            self.push(frame, chain)
        else:
            self.push(frame, top)

    @simple
    def op_DUP_TOP_TWO(self, frame, op):
        if len(frame.stack) < 2:
            raise Fail("DUP_TOP_TWO underflow")
        frame.stack.extend(frame.stack[-2:])

    def is_swap(self, frame, values):
        if frame.mode != "stmt" or len(frame.stack) != len(values):
            return False
        for v in values:
            if isinstance(v, Marker) or (isinstance(v, S.BinOp) and v.inplace):
                return False
        return True

    def op_ROT_TWO(self, frame, op):
        if len(frame.stack) < 2:
            raise Fail("ROT_TWO underflow")
        a, b = frame.stack[-2], frame.stack[-1]
        if self.is_swap(frame, [a, b]):
            self.tuple_swap(frame, [a, b])
        else:
            frame.stack[-2], frame.stack[-1] = b, a
        frame.i += 1

    def op_ROT_THREE(self, frame, op):
        i = frame.i
        if len(frame.stack) < 3:
            raise Fail("ROT_THREE underflow")
        if i + 1 < self.n and self.ins[i + 1].opname == "ROT_TWO" and self.is_swap(frame, frame.stack[-3:]):
            self.tuple_swap(frame, frame.stack[-3:])
            frame.i += 2
            return
        a, b, c = frame.stack[-3:]
        frame.stack[-3:] = [c, a, b]
        frame.i += 1

    def tuple_swap(self, frame, values):
        k = len(values)
        del frame.stack[-k:]
        u = Unpack(S.Tuple([self.value(v) for v in values]), k, None)
        for idx in reversed(range(k)):
            self.push(frame, UnpackSlot(u, idx))

    def op_POP_TOP(self, frame, op):
        v = self.pop(frame)
        if isinstance(v, ImportModule):
            if v.fromlist is None or not v.names:
                raise Fail("unexpected module pop")
            self.emit(frame, S.ImportFrom(v.name or None, v.names, v.level))
        elif isinstance(v, (Chain, UnpackSlot, Placeholder)):
            raise Fail("dangling assignment marker")
        else:
            self.emit(frame, S.ExprStmt(self.value(v)))
        frame.i += 1

    def store(self, frame, target, value):
        if isinstance(value, UnpackSlot):
            u = value.unpack
            if u.targets[value.index] is not None:
                raise Fail("slot stored twice")
            u.targets[value.index] = S.Starred(target) if value.index == u.star else target
            u.filled += 1
            if u.filled == len(u.targets):
                self.store(frame, S.Tuple(u.targets), u.source)
            return
        if isinstance(value, Chain):
            value.targets.append(target)
            if not any(v is value for v in frame.stack):
                self.store_many(frame, value.targets, value.source)
            return
        self.store_many(frame, [target], value)

    def store_many(self, frame, targets, value):
        if isinstance(value, Placeholder):
            if len(targets) != 1:
                raise Fail("multiple targets for a loop or with variable")
            value.target = targets[0]
            value.done = True
            return
        if isinstance(value, UnpackSlot):
            if len(targets) != 1:
                raise Fail("chained assignment into a slot")
            self.store(frame, targets[0], value)
            return
        if isinstance(value, Chain):
            value.targets.extend(targets)
            if not any(v is value for v in frame.stack):
                self.store_many(frame, value.targets, value.source)
            return
        if len(targets) == 1:
            target = targets[0]
            if isinstance(value, ImportedName):
                if not isinstance(target, S.Name):
                    raise Fail("import into a non-name")
                value.module.names.append((value.name, target.name))
                return
            if isinstance(value, ImportModule):
                if not isinstance(target, S.Name) or value.fromlist is not None and not is_none(value.fromlist) or value.level:
                    raise Fail("unexpected import store")
                top = value.name.split(".")[0]
                if target.name == top:
                    self.emit(frame, S.Import(value.name, None))
                elif "." not in value.name:
                    self.emit(frame, S.Import(value.name, target.name))
                else:
                    raise Fail("dotted import stored under another name")
                return
            stmt = self.definition(target, value)
            if stmt is not None:
                self.emit(frame, stmt)
                return
            if isinstance(value, S.BinOp) and value.inplace:
                if self.matches_target(target, value.left):
                    self.emit(frame, S.AugAssign(target, value.op, value.right))
                    return
                raise Fail("in-place result stored to a different target")
            if (self.kind in ("module", "class") and isinstance(target, S.Subscript)
                    and isinstance(target.value, S.Name) and target.value.name == "__annotations__"
                    and isinstance(target.index, S.Const) and isinstance(target.index.value, str)):
                name = target.index.value
                prev = frame.stmts[-1] if frame.stmts else None
                if isinstance(prev, S.Assign) and len(prev.targets) == 1 and isinstance(prev.targets[0], S.Name) and prev.targets[0].name == name:
                    frame.stmts[-1] = S.AnnAssign(S.Name(name), self.value(value), prev.value, self.future_annotations)
                else:
                    self.emit(frame, S.AnnAssign(S.Name(name), self.value(value), None, self.future_annotations))
                return
        self.emit(frame, S.Assign(targets, self.value(value)))

    def matches_target(self, target, left):
        if isinstance(target, S.Name):
            return isinstance(left, S.Name) and left.name == target.name
        if isinstance(target, S.Attribute):
            return isinstance(left, S.Attribute) and left.attr == target.attr and left.value is target.value
        if isinstance(target, S.Subscript):
            return isinstance(left, S.Subscript) and left.value is target.value and left.index is target.index
        return False

    def definition(self, target, value):
        decorators = []
        inner = value
        while isinstance(inner, S.Call) and len(inner.args) == 1 and not inner.keywords and isinstance(inner.args[0], (FunctionObj, ClassObj, S.Call)):
            decorators.append(inner.func)
            inner = inner.args[0]
        if isinstance(inner, FunctionObj) and inner.code.co_name != "<lambda>":
            if not isinstance(target, S.Name) or not self.same_name(target.name, inner.code.co_name):
                raise Fail("function stored under a different name")
            return self.function_def(inner, decorators)
        if isinstance(inner, ClassObj):
            if not isinstance(target, S.Name) or not self.same_name(target.name, inner.name):
                raise Fail("class stored under a different name")
            try:
                body = self.child(inner.func.code).class_body()
            except (Fail, RecursionError) as e:
                body = [S.Unsupported(str(e))]
            return S.ClassDef(inner.name, inner.bases, inner.keywords, body, decorators)
        if decorators:
            return None
        return None

    def child(self, code):
        return CodeDecompiler(code, self.private, self.session)

    def same_name(self, stored, defined):
        if stored == defined:
            return True
        if self.private and defined.startswith("__") and not defined.endswith("__"):
            owner = self.private.lstrip("_")
            return bool(owner) and stored == "_" + owner + defined
        return False

    def function_def(self, fn, decorators):
        code = fn.code
        args = self.arguments(fn)
        try:
            body = self.child(code).function_body()
        except (Fail, RecursionError) as e:
            body = [S.Unsupported(str(e))]
        returns = fn.annotations.get("return")
        is_async = bool(code.co_flags & (CO_COROUTINE | CO_ASYNC_GENERATOR))
        return S.FunctionDef(code.co_name, args, body, decorators, returns, bool(code.co_flags & CO_FUTURE_ANNOTATIONS), is_async)

    def arguments(self, fn):
        code = fn.code
        names = code.co_varnames
        argc = code.co_argcount
        kwc = code.co_kwonlyargcount
        args = list(names[:argc])
        kwonly = list(names[argc:argc + kwc])
        pos = argc + kwc
        vararg = kwarg = None
        if code.co_flags & CO_VARARGS:
            vararg = names[pos]
            pos += 1
        if code.co_flags & CO_VARKEYWORDS:
            kwarg = names[pos]
        return S.Arguments(args, vararg, kwonly, kwarg, fn.defaults, fn.kwdefaults, fn.annotations,
                           bool(code.co_flags & CO_FUTURE_ANNOTATIONS))

    def store_op(self, frame, op):
        value = self.pop(frame)
        self.store(frame, S.Name(op.argval), value)
        frame.i += 1

    op_STORE_NAME = op_STORE_FAST = op_STORE_GLOBAL = op_STORE_DEREF = store_op

    def op_STORE_ATTR(self, frame, op):
        obj = self.value(self.pop(frame))
        value = self.pop(frame)
        self.store(frame, S.Attribute(obj, op.argval), value)
        frame.i += 1

    def op_STORE_SUBSCR(self, frame, op):
        index = self.value(self.pop(frame))
        obj = self.value(self.pop(frame))
        value = self.pop(frame)
        self.store(frame, S.Subscript(obj, index), value)
        frame.i += 1

    @simple
    def op_UNPACK_SEQUENCE(self, frame, op):
        source = self.pop(frame)
        u = Unpack(source, op.arg, None)
        for idx in reversed(range(op.arg)):
            self.push(frame, UnpackSlot(u, idx))

    @simple
    def op_UNPACK_EX(self, frame, op):
        before = op.arg & 0xFF
        after = op.arg >> 8
        source = self.pop(frame)
        u = Unpack(source, before + 1 + after, before)
        for idx in reversed(range(before + 1 + after)):
            self.push(frame, UnpackSlot(u, idx))

    def delete(self, frame, target):
        self.emit(frame, S.Delete([target]))
        frame.i += 1

    def op_DELETE_NAME(self, frame, op):
        self.delete(frame, S.Name(op.argval))

    op_DELETE_FAST = op_DELETE_GLOBAL = op_DELETE_DEREF = op_DELETE_NAME

    def op_DELETE_ATTR(self, frame, op):
        self.delete(frame, S.Attribute(self.value(self.pop(frame)), op.argval))

    def op_DELETE_SUBSCR(self, frame, op):
        index = self.value(self.pop(frame))
        obj = self.value(self.pop(frame))
        self.delete(frame, S.Subscript(obj, index))

    @simple
    def op_SETUP_ANNOTATIONS(self, frame, op):
        pass

    @simple
    def op_IMPORT_NAME(self, frame, op):
        fromlist = self.pop(frame)
        level = self.pop(frame)
        if not isinstance(level, S.Const):
            raise Fail("import level is not a constant")
        fl = fromlist.value if isinstance(fromlist, S.Const) else fromlist
        self.push(frame, ImportModule(op.argval, fl, level.value))

    def op_IMPORT_FROM(self, frame, op):
        top = frame.stack[-1] if frame.stack else None
        if not isinstance(top, ImportModule):
            raise Fail("IMPORT_FROM without a module")
        if top.fromlist is None:
            self.import_as(frame, top)
            return
        self.push(frame, ImportedName(top, op.argval))
        frame.i += 1

    def import_as(self, frame, module):
        i = frame.i
        parts = module.name.split(".")
        k = 1
        while True:
            op = self.ins[i]
            if op.opname != "IMPORT_FROM" or k >= len(parts) or op.argval != parts[k]:
                raise Fail("unexpected import-as sequence")
            k += 1
            nxt = self.ins[i + 1]
            if nxt.opname == "ROT_TWO" and self.ins[i + 2].opname == "POP_TOP":
                i += 3
                continue
            break
        store = self.ins[i + 1]
        if not store.opname.startswith("STORE_") or self.ins[i + 2].opname != "POP_TOP" or k != len(parts):
            raise Fail("unexpected import-as store")
        self.pop(frame)
        self.emit(frame, S.Import(module.name, store.argval))
        frame.i = i + 3

    def op_IMPORT_STAR(self, frame, op):
        m = self.pop(frame)
        if not isinstance(m, ImportModule):
            raise Fail("IMPORT_STAR without module")
        self.emit(frame, S.ImportFrom(m.name or None, [("*", None)], m.level))
        frame.i += 1

    @simple
    def op_LOAD_BUILD_CLASS(self, frame, op):
        self.push(frame, BuildClass())

    @simple
    def op_MAKE_FUNCTION(self, frame, op):
        self.pop(frame)
        code = self.pop(frame)
        if not isinstance(code, CodeRef):
            raise Fail("MAKE_FUNCTION without code")
        flags = op.arg
        if flags & 8:
            self.pop(frame)
        annotations = {}
        kwdefaults = {}
        defaults = []
        if flags & 4:
            ann = self.pop(frame)
            if not isinstance(ann, S.Dict):
                raise Fail("annotations are not a dict")
            for k, v in zip(ann.keys, ann.values):
                annotations[k.value] = v
        if flags & 2:
            kd = self.pop(frame)
            if not isinstance(kd, S.Dict):
                raise Fail("keyword defaults are not a dict")
            for k, v in zip(kd.keys, kd.values):
                kwdefaults[k.value] = v
        if flags & 1:
            d = self.pop(frame)
            if isinstance(d, S.Tuple):
                defaults = list(d.elts)
            elif isinstance(d, S.Const) and isinstance(d.value, tuple):
                defaults = [self.const_like(v, d) for v in d.value]
            else:
                raise Fail("defaults are not a tuple")
        self.push(frame, FunctionObj(code.code, defaults, kwdefaults, annotations))

    def op_RETURN_VALUE(self, frame, op):
        v = self.value(self.pop(frame))
        self.emit(frame, S.Return(None if is_none(v) else v))
        frame.i += 1
        if frame.stop_after_return and (frame.i >= frame.end or self.ins[frame.i].is_target):
            frame.stop = "return"

    def op_RAISE_VARARGS(self, frame, op):
        args = [self.value(a) for a in self.popn(frame, op.arg)]
        exc = args[0] if args else None
        cause = args[1] if len(args) > 1 else None
        self.emit(frame, S.Raise(exc, cause))
        frame.i += 1

    def op_BREAK_LOOP(self, frame, op):
        if frame.loop is None:
            raise Fail("break outside a loop")
        self.emit(frame, S.Break())
        frame.i += 1

    def op_CONTINUE_LOOP(self, frame, op):
        if frame.loop is None:
            raise Fail("continue outside a loop")
        self.emit(frame, S.Continue())
        frame.i += 1

    def op_JUMP_ABSOLUTE(self, frame, op):
        if frame.mode != "stmt":
            raise Fail("jump inside an expression")
        target = self.resolve(op.target)
        if frame.loop is not None and target == self.resolve(frame.loop.top):
            self.emit(frame, S.Continue())
            frame.i += 1
            return
        if frame.i == frame.end - 1 and target == frame.exit:
            frame.i += 1
            return
        raise Fail("unstructured jump")

    op_JUMP_FORWARD = op_JUMP_ABSOLUTE

    @simple
    def op_POP_BLOCK(self, frame, op):
        if frame.mode != "stmt":
            raise Fail("POP_BLOCK inside an expression")


    def op_POP_JUMP_IF_FALSE(self, frame, op):
        first = Atom(None, op.index, op.opname, op.target, op.index + 1)
        self.conditional(frame, first)

    op_POP_JUMP_IF_TRUE = op_POP_JUMP_IF_FALSE

    def conditional(self, frame, first):
        if first.expr is None:
            first.expr = self.value(self.pop(frame))
            restore = True
        else:
            restore = False
        if frame.mode == "atom" and not frame.stack:
            frame.stop = first
            return
        if frame.mode == "vatom" and not frame.stack:
            if self.ternary(frame, first):
                return
            frame.stop = first
            return
        if self.ternary(frame, first):
            return
        if first.kind in POP_JUMPS and self.value_boolop(frame, first):
            return
        if frame.mode == "stmt" and not frame.stack:
            self.if_statement(frame, first)
            return
        if restore:
            frame.stack.append(first.expr)
        raise Fail("conditional jump not understood")

    def op_JUMP_IF_FALSE_OR_POP(self, frame, op):
        if frame.mode == "vatom" and len(frame.stack) == 1:
            frame.stop = Atom(self.value(self.pop(frame)), op.index, op.opname, op.target, op.index + 1)
            return
        first = Atom(self.value(self.pop(frame)), op.index, op.opname, op.target, op.index + 1)
        if not self.value_boolop(frame, first):
            raise Fail("boolean operator not understood")

    op_JUMP_IF_TRUE_OR_POP = op_JUMP_IF_FALSE_OR_POP

    def sim_atom(self, start, limit):
        key = (start, limit)
        if key in self.memo_atoms:
            r = self.memo_atoms[key]
            if isinstance(r, Fail):
                raise r
            return r
        try:
            frame = self.run(Frame(start, limit, None, "atom"))
            if not isinstance(frame.stop, Atom):
                raise Fail("no condition found")
            r = frame.stop
        except Fail as e:
            self.memo_atoms[key] = e
            raise
        self.memo_atoms[key] = r
        return r

    def collect_atoms(self, first, limit):
        atoms = [first]
        j = first.after
        while len(atoms) < 64 and j < limit:
            try:
                a = self.sim_atom(j, limit)
            except Fail:
                break
            atoms.append(a)
            j = a.after
        return atoms

    def parse_cond(self, atoms, lo, hi, nxt, cond, after, memo=None):
        if memo is None:
            memo = {}
        key = (lo, hi, nxt, cond, after)
        if key in memo:
            return memo[key]
        memo[key] = None
        result = self._parse_cond(atoms, lo, hi, nxt, cond, after, memo)
        memo[key] = result
        return result

    def _parse_cond(self, atoms, lo, hi, nxt, cond, after, memo):
        if hi - lo == 1:
            a = atoms[lo]
            if self.resolve(a.target) != nxt or a.after != after:
                return None
            if a.sense == cond:
                return a.expr
            if folds_under_not(a.expr):
                return None
            return negate(a.expr)
        for neg in (False, True):
            c = cond != neg
            for op in ("and", "or"):
                cond2 = op == "or"
                nxt2 = nxt if cond2 == c else self.resolve(after)
                operands = self.split_cond(atoms, lo, hi, nxt, c, after, nxt2, cond2, memo)
                if operands:
                    flat = []
                    for o in operands:
                        if isinstance(o, S.BoolOp) and o.op == op:
                            flat.extend(o.values)
                        else:
                            flat.append(o)
                    e = S.BoolOp(op, flat)
                    return negate(e) if neg else e
        return None

    def split_cond(self, atoms, lo, hi, nxt, c, after, nxt2, cond2, memo):
        for e in range(lo + 1, hi):
            first = self.parse_cond(atoms, lo, e, nxt2, cond2, atoms[e - 1].after, memo)
            if first is None:
                continue
            last = self.parse_cond(atoms, e, hi, nxt, c, after, memo)
            if last is not None:
                return [first, last]
            rest = self.split_cond(atoms, e, hi, nxt, c, after, nxt2, cond2, memo)
            if rest:
                return [first] + rest
        return None

    def ternary(self, frame, first):
        base = list(frame.stack)
        atoms = self.collect_atoms(first, frame.end)
        for k in range(len(atoms), 0, -1):
            last = atoms[k - 1]
            L = last.target
            after = last.after
            if not (after < L <= frame.end):
                continue
            j = self.ins[L - 1]
            if j.opname not in UNCONDITIONAL or L - 1 < after:
                continue
            E = self.within(j.target, frame)
            if E is None or not L < E:
                continue
            cond = self.parse_cond(atoms, 0, k, self.resolve(L), False, after)
            if cond is None:
                continue
            try:
                s1 = self.eval_range(after, L - 1, base)
                s2 = self.eval_range(L, E, base)
            except Fail:
                continue
            if len(s1) != len(base) + 1 or len(s2) != len(base) + 1:
                continue
            if any(x is not y for x, y in zip(s1, base)) or any(x is not y for x, y in zip(s2, base)):
                continue
            frame.stack = base + [self.mark(S.IfExp(cond, self.value(s1[-1]), self.value(s2[-1])), after)]
            frame.i = E
            return True
        return False

    def within(self, target, frame):
        if target <= frame.end:
            return target
        if frame.end < self.n and self.ins[frame.end].opname in UNCONDITIONAL and self.resolve(frame.end) == self.resolve(target):
            return frame.end
        return None

    def value_boolop(self, frame, first):
        base = list(frame.stack)
        atoms = [first]
        join = self.within(first.target, frame) if first.kind in OR_POP_JUMPS else None
        if first.kind in OR_POP_JUMPS and join is None:
            return False
        if join is not None and join != first.target:
            first.target = join
        j = first.index + 1
        while len(atoms) < 128:
            limit = join if join is not None else frame.end
            if j >= limit:
                return False
            try:
                f = self.run(Frame(j, limit, None, "vatom"))
            except Fail:
                return False
            if isinstance(f.stop, Atom):
                a = f.stop
                atoms.append(a)
                if a.kind in OR_POP_JUMPS:
                    t = self.within(a.target, frame)
                    if t is None:
                        return False
                    a.target = t
                    join = t if join is None else max(join, t)
                j = a.index + 1
                continue
            if f.stop is None and join is not None and f.i == join and len(f.stack) == 1:
                atoms.append(Atom(self.value(f.stack[0]), None, None, None, join))
                break
            return False
        else:
            return False
        if join is None or join > frame.end:
            return False
        expr = self.parse_value(atoms, 0, len(atoms), join, top=True)
        if expr is None:
            return False
        frame.stack = base + [self.mark(expr, join)]
        frame.i = join
        return True

    def parse_value(self, atoms, lo, hi, end_pos, top=False):
        if hi - lo == 1:
            return atoms[lo].expr

        def to_end(a):
            if a.kind in OR_POP_JUMPS:
                return a.target == end_pos
            if a.kind in POP_JUMPS:
                return not top and a.target == end_pos + 1
            return False

        level = None
        boundaries = []
        for m in range(lo, hi - 1):
            a = atoms[m]
            if to_end(a):
                if level is None:
                    level = a.sense
                if a.sense == level:
                    boundaries.append(m)
                else:
                    break
        if not boundaries:
            return None
        op = "or" if level else "and"
        operands = []
        s = lo
        for m in boundaries:
            o = self.parse_value(atoms, s, m + 1, atoms[m].index)
            if o is None:
                return None
            operands.append(o)
            s = m + 1
        o = self.parse_value(atoms, s, hi, end_pos, top)
        if o is None:
            return None
        operands.append(o)
        flat = []
        for o in operands:
            if isinstance(o, S.BoolOp) and o.op == op:
                flat.extend(o.values)
            else:
                flat.append(o)
        return S.BoolOp(op, flat)

    def if_statement(self, frame, first):
        key = ("if", first.index)
        self.session.record(self.code, key)
        want = self.session.choice(self.code, key)
        atoms = self.collect_atoms(first, frame.end)
        seen = 0
        last = None
        for k in range(len(atoms), 0, -1):
            L = atoms[k - 1].target
            after = atoms[k - 1].after
            cond = self.parse_cond(atoms, 0, k, self.resolve(L), False, after)
            if cond is None:
                continue
            for body, orelse, nxt in self.if_shapes(frame, after, L):
                try:
                    b = body()
                    o = orelse()
                except Fail as e:
                    last = e
                    continue
                if seen < want:
                    seen += 1
                    continue
                self.emit(frame, S.If(cond, b, o))
                frame.i = nxt
                return
        if seen:
            raise Fail("forced choice does not exist")
        raise last or Fail("if statement not understood")

    def if_shapes(self, frame, after, L):
        R = frame.end
        X = frame.exit
        rL = self.resolve(L)
        loop = frame.loop
        none = lambda: []
        if L == after:
            yield none, none, L
            return
        labels = [L]
        for k in range(after + 1, R + 1 if R < self.n else R):
            if k != L and self.ins[k].opname in UNCONDITIONAL and self.resolve(k) == rL:
                labels.append(k)
        for label in labels:
            yield from self.if_shapes_for(after, label, R, X, loop)

    def if_shapes_for(self, after, L, R, X, loop):
        none = lambda: []
        rL = self.resolve(L)
        if after < L <= R:
            j = L - 1
            jop = self.ins[j]
            if j >= after and jop.opname in UNCONDITIONAL:
                T = jop.target
                rT = self.resolve(T)
                if L < T <= R:
                    yield (lambda: self.body(after, j, loop)), (lambda: self.body(L, T, loop)), T
                elif rT == X and X is not None:
                    if j == after and loop is not None and rT == self.resolve(loop.top):
                        yield (lambda: [S.Continue()]), none, L
                    yield (lambda: self.body(after, j, loop)), (lambda: self.body(L, R, loop)), R
            yield (lambda: self.body(after, L, loop)), none, L
        elif rL == X and X is not None:
            yield (lambda: self.body(after, R, loop)), none, R

    def chained_compare(self, frame):
        i = frame.i
        ins = self.ins
        if len(frame.stack) < 2:
            raise Fail("chained comparison underflow")
        left = self.value(frame.stack[-2])
        comps = [self.value(frame.stack[-1])]
        ops = []
        base = frame.stack[:-2]
        cleanup = None
        form = None
        k = i
        while True:
            if ins[k].opname != "DUP_TOP" or ins[k + 1].opname != "ROT_THREE" or ins[k + 2].opname != "COMPARE_OP":
                raise Fail("malformed chained comparison")
            ops.append(ins[k + 2].argval)
            jmp = ins[k + 3]
            if jmp.opname == "JUMP_IF_FALSE_OR_POP":
                f = "value"
            elif jmp.opname == "POP_JUMP_IF_FALSE":
                f = "cond"
            else:
                raise Fail("malformed chained comparison jump")
            if form is None:
                form, cleanup = f, jmp.target
            elif form != f or cleanup != jmp.target:
                raise Fail("inconsistent chained comparison")
            sub = self.run(Frame(k + 4, cleanup, None, "cmp"))
            if len(sub.stack) != 1:
                raise Fail("chained comparison operand")
            comps.append(self.value(sub.stack[0]))
            k = sub.i
            if ins[k].opname == "DUP_TOP":
                continue
            if ins[k].opname != "COMPARE_OP":
                raise Fail("chained comparison end")
            ops.append(ins[k].argval)
            break
        expr = self.mark(S.Compare(left, ops, comps), k)
        last = ins[k + 1]
        if form == "value" and last.opname == "RETURN_VALUE":
            if ins[cleanup].opname != "ROT_TWO" or ins[cleanup + 1].opname != "POP_TOP" or ins[cleanup + 2].opname != "RETURN_VALUE" or k + 2 != cleanup:
                raise Fail("chained comparison return layout")
            frame.stack = base
            self.emit(frame, S.Return(expr))
            frame.i = cleanup + 3
            return
        if form == "value":
            if last.opname != "JUMP_FORWARD" or ins[cleanup].opname != "ROT_TWO" or ins[cleanup + 1].opname != "POP_TOP":
                raise Fail("chained comparison cleanup")
            if last.target != cleanup + 2 or k + 2 != cleanup:
                raise Fail("chained comparison layout")
            frame.stack = base + [self.mark(expr, k)]
            frame.i = cleanup + 2
            return
        if last.opname not in POP_JUMPS or ins[k + 2].opname != "JUMP_FORWARD" or k + 3 != cleanup:
            raise Fail("chained comparison condition layout")
        if ins[cleanup].opname != "POP_TOP":
            raise Fail("chained comparison condition cleanup")
        after = cleanup + 1
        if after < self.n and ins[after].opname in UNCONDITIONAL and not last.jumps_on_true:
            after += 1
        frame.stack = base
        atom = Atom(expr, last.index, last.opname, last.target, after)
        self.conditional(frame, atom)

    def loop_kind(self, start, end):
        for k in range(start, end - 1):
            if self.ins[k].opname == "GET_ITER" and self.ins[k + 1].opname == "FOR_ITER":
                return k
        return None

    def op_SETUP_LOOP(self, frame, op):
        if frame.mode != "stmt" or frame.stack:
            raise Fail("loop inside an expression")
        s = op.index
        E = op.target
        rE = self.resolve(E)
        ends = [k for k in range(s + 1, min(E, frame.end)) if self.ins[k].opname in UNCONDITIONAL and self.resolve(k) == rE]
        if E <= frame.end:
            ends.append(E)
        elif frame.exit == rE:
            ends.append(frame.end)
        g = self.loop_kind(s + 1, E)
        last = None
        key = ("loop", s)
        self.session.record(self.code, key)
        want = self.session.choice(self.code, key)
        seen = 0
        for end in ends:
            stmt = None
            if g is not None and g < end:
                try:
                    stmt = self.for_loop(frame, s, end, g)
                except Fail as e:
                    last = e
            if stmt is None:
                try:
                    stmt = self.while_loop(frame, s, end)
                except Fail as e:
                    last = e
                    continue
            if seen < want:
                seen += 1
                continue
            self.emit(frame, stmt)
            frame.i = end
            return
        if seen:
            raise Fail("forced choice does not exist")
        raise last or Fail("loop end not found")

    def target_after(self, start, limit):
        ph = Placeholder()
        frame = Frame(start, limit, None, "target", [ph])
        frame.placeholder = ph
        self.run(frame)
        if frame.stop != "target":
            raise Fail("assignment target not found")
        return ph.target, frame.i

    def for_loop(self, frame, s, E, g):
        it = self.eval_one(s + 1, g)
        f = g + 1
        C = self.ins[f].target
        if E < C + 1:
            raise Fail("for loop ends before its exit")
        target, b = self.target_after(f + 1, C)
        body_end = C
        if self.ins[C - 1].opname == "JUMP_ABSOLUTE" and self.ins[C - 1].target == f and C - 1 >= b:
            body_end = C - 1
        body = self.body(b, body_end, Loop(f))
        if self.ins[C].opname != "POP_BLOCK":
            raise Fail("for loop without POP_BLOCK")
        orelse = self.body(C + 1, E, frame.loop) if C + 1 < E else []
        return S.For(target, it, body, orelse)

    def while_loop(self, frame, s, E):
        top = s + 1
        try:
            first = self.sim_atom(top, E)
        except Fail:
            first = None
        if first is not None:
            atoms = self.collect_atoms(first, E)
            for k in range(len(atoms), 0, -1):
                A = atoms[k - 1].target
                if not (atoms[k - 1].after <= A < E) or self.ins[A].opname != "POP_BLOCK":
                    continue
                cond = self.parse_cond(atoms, 0, k, self.resolve(A), False, atoms[k - 1].after)
                if cond is None:
                    continue
                after = atoms[k - 1].after
                body_end = A
                if self.ins[A - 1].opname == "JUMP_ABSOLUTE" and self.resolve(self.ins[A - 1].target) == top and A - 1 >= after:
                    body_end = A - 1
                try:
                    body = self.body(after, body_end, Loop(top))
                    orelse = self.body(A + 1, E, frame.loop) if A + 1 < E else []
                except Fail:
                    continue
                return S.While(cond, body, orelse)
        end = E
        if end - 1 > top and self.ins[end - 1].opname == "POP_BLOCK":
            end -= 1
        if end - 1 >= top and self.ins[end - 1].opname == "JUMP_ABSOLUTE" and self.resolve(self.ins[end - 1].target) == top:
            end -= 1
        body = self.body(top, end, Loop(top))
        return S.While(S.Const(True), body, [])

    def op_SETUP_EXCEPT(self, frame, op):
        if frame.mode != "stmt" or frame.stack:
            raise Fail("try inside an expression")
        stmt, nxt = self.try_except(frame, op.index, op.target)
        self.emit(frame, stmt)
        frame.i = nxt

    def try_except(self, frame, s, H):
        ins = self.ins
        O = None
        if ins[H - 1].opname in UNCONDITIONAL and ins[H - 2].opname == "POP_BLOCK":
            body_end = H - 2
            O = ins[H - 1].target
        elif ins[H - 1].opname == "POP_BLOCK":
            body_end = H - 1
        else:
            body_end = H
        body = self.body(s + 1, body_end, frame.loop)
        handlers = []
        ends = []
        h = H
        while True:
            op = ins[h]
            if op.opname == "DUP_TOP":
                k = h + 1
                while k < frame.end and not (ins[k].opname == "COMPARE_OP" and ins[k].argval == "exception match"):
                    k += 1
                if k >= frame.end:
                    raise Fail("except clause without match")
                etype = self.eval_one(h + 1, k)
                jf = ins[k + 1]
                if jf.opname != "POP_JUMP_IF_FALSE":
                    raise Fail("except clause without jump")
                nxt = jf.target
                p = k + 2
                if ins[p].opname != "POP_TOP":
                    raise Fail("except clause layout")
                if ins[p + 1].opname.startswith("STORE_"):
                    name = ins[p + 1].argval
                    if ins[p + 2].opname != "POP_TOP" or ins[p + 3].opname != "SETUP_FINALLY":
                        raise Fail("named except clause layout")
                    cleanup = ins[p + 3].target
                    hb_end = cleanup
                    if ins[cleanup - 2].opname == "POP_BLOCK" and ins[cleanup - 1].opname == "LOAD_CONST":
                        hb_end = cleanup - 2
                    hbody = self.body(p + 4, hb_end, frame.loop)
                    c = cleanup
                    seq = [ins[c + t].opname for t in range(5)]
                    if seq[0] != "LOAD_CONST" or not seq[1].startswith("STORE_") or not seq[2].startswith("DELETE_") or seq[3] != "END_FINALLY" or seq[4] != "POP_EXCEPT":
                        raise Fail("named except cleanup layout")
                    q = c + 5
                    if q < self.n and ins[q].opname in UNCONDITIONAL and q < nxt:
                        ends.append(ins[q].target)
                        q += 1
                    if q != nxt:
                        raise Fail("named except clause leftovers")
                    handlers.append(S.Handler(etype, name, hbody, self.lines[h]))
                elif ins[p + 1].opname == "POP_TOP" and ins[p + 2].opname == "POP_TOP":
                    hframe = self.block(p + 3, nxt, frame.loop, stop_at=("POP_EXCEPT",), stop_after_return=True)
                    q = hframe.i
                    if hframe.stop == "POP_EXCEPT":
                        q += 1
                        if q < nxt and ins[q].opname in UNCONDITIONAL:
                            ends.append(ins[q].target)
                            q += 1
                    if q != nxt:
                        raise Fail("except clause leftovers")
                    handlers.append(S.Handler(etype, None, hframe.stmts, self.lines[h]))
                else:
                    raise Fail("except clause layout")
                h = nxt
                continue
            if op.opname == "POP_TOP" and ins[h + 1].opname == "POP_TOP" and ins[h + 2].opname == "POP_TOP":
                hframe = self.block(h + 3, frame.end, frame.loop, stop_at=("POP_EXCEPT",), stop_after_return=True)
                q = hframe.i
                if hframe.stop == "POP_EXCEPT":
                    q += 1
                    if q < self.n and ins[q].opname in UNCONDITIONAL:
                        ends.append(ins[q].target)
                        q += 1
                    if q < self.n and ins[q].opname == "END_FINALLY":
                        q += 1
                handlers.append(S.Handler(None, None, hframe.stmts, self.lines[h]))
                P = q
                break
            if op.opname == "END_FINALLY":
                P = h + 1
                break
            raise Fail("except clause not understood")
        orelse = []
        nxt = P
        if O is not None and O == P:
            later = [t for t in ends if t > P]
            if later and all(t == later[0] for t in later) and later[0] <= frame.end:
                orelse = self.body(P, later[0], frame.loop)
                nxt = later[0]
            elif ends and all(self.resolve(t) == frame.exit for t in ends) and frame.exit is not None and P < frame.end:
                orelse = self.body(P, frame.end, frame.loop)
                nxt = frame.end
        return S.Try(body, handlers, orelse, None), nxt

    def op_SETUP_FINALLY(self, frame, op):
        if frame.mode != "stmt" or frame.stack:
            raise Fail("try inside an expression")
        s = op.index
        F = op.target
        ins = self.ins
        body_end = F
        if ins[F - 2].opname == "POP_BLOCK" and ins[F - 1].opname == "LOAD_CONST" and ins[F - 1].argval is None:
            body_end = F - 2
        body = self.body(s + 1, body_end, frame.loop)
        fframe = self.block(F, frame.end, frame.loop, stop_at=("END_FINALLY",))
        if fframe.stop != "END_FINALLY":
            raise Fail("finally without END_FINALLY")
        final = fframe.stmts
        if len(body) == 1 and isinstance(body[0], S.Try) and body[0].finalbody is None and body[0].handlers:
            stmt = S.Try(body[0].body, body[0].handlers, body[0].orelse, final)
        else:
            stmt = S.Try(body, [], [], final)
        self.emit(frame, stmt)
        frame.i = fframe.i + 1

    def op_SETUP_WITH(self, frame, op):
        if frame.mode != "stmt" or len(frame.stack) != 1:
            raise Fail("with inside an expression")
        ctx = self.value(self.pop(frame))
        s = op.index
        F = op.target
        ins = self.ins
        if ins[s + 1].opname == "POP_TOP":
            target = None
            b = s + 2
        else:
            target, b = self.target_after(s + 1, F)
        body_end = F
        if ins[F - 2].opname == "POP_BLOCK" and ins[F - 1].opname == "LOAD_CONST" and ins[F - 1].argval is None and F - 2 >= b:
            body_end = F - 2
        body = self.body(b, body_end, frame.loop)
        if [ins[F + t].opname for t in range(3)] != ["WITH_CLEANUP_START", "WITH_CLEANUP_FINISH", "END_FINALLY"]:
            raise Fail("with cleanup layout")
        items = [(ctx, target)]
        if len(body) == 1 and isinstance(body[0], S.With) and not body[0].is_async:
            items += body[0].items
            body = body[0].body
        self.emit(frame, S.With(items, body))
        frame.i = F + 3

    def lambda_body(self):
        frame = self.block(0, self.n, None)
        expr = statements_to_expr(frame.stmts)
        if expr is None:
            raise Fail("lambda body is not an expression")
        return expr

    def function_body(self):
        stmts = self.body(0, self.n, None)
        stmts = self.finish_body(stmts)
        dead = []
        if self.code.co_flags & (CO_GENERATOR | CO_ASYNC_GENERATOR) and not self.has_yield():
            dead.append(S.ExprStmt(S.Yield(None)))
        dead.extend(self.phantom_references())
        if dead:
            stmts.append(S.If(S.Name("__debug__"), dead, []))
        return self.place_declarations(self.declarations(), stmts)

    def place_declarations(self, decls, stmts):
        first = next((s.line for s in stmts if s.line is not None), None)
        if first is not None:
            line = first - 1 if first - 1 > self.code.co_firstlineno else first
            for d in decls:
                d.line = line
        return decls + stmts

    def phantom_references(self):
        used = set()
        captured = set()
        for op in self.ins:
            if op.opname in ("LOAD_CLOSURE", "LOAD_DEREF", "STORE_DEREF", "DELETE_DEREF", "LOAD_CLASSDEREF"):
                used.add(op.argval)
            if op.opname == "LOAD_CLOSURE":
                captured.add(op.argval)
        out = []
        cells = [c for c in self.code.co_cellvars if c not in captured]
        free = [f for f in self.code.co_freevars if f not in used]
        if free:
            out.append(S.ExprStmt(S.Tuple([S.Name(f) for f in free]) if len(free) > 1 else S.Name(free[0])))
        if cells:
            params = self.code.co_varnames[:self.code.co_argcount + self.code.co_kwonlyargcount + bool(self.code.co_flags & CO_VARARGS) + bool(self.code.co_flags & CO_VARKEYWORDS)]
            for c in cells:
                if c not in params and not any(op.opname == "STORE_DEREF" and op.argval == c for op in self.ins):
                    out.append(S.Assign([S.Name(c)], S.Const(None)))
            names = S.Tuple([S.Name(c) for c in cells]) if len(cells) > 1 else S.Name(cells[0])
            out.append(S.ExprStmt(S.Lambda(S.Arguments([], None, [], None, [], {}, {}, False), names)))
        return out

    def has_yield(self):
        return any(op.opname in ("YIELD_VALUE", "YIELD_FROM") for op in self.ins)

    def finish_body(self, stmts):
        ins = self.ins
        n = self.n
        if stmts and isinstance(stmts[-1], S.Return) and stmts[-1].value is None:
            dead = (n >= 3 and ins[n - 2].opname == "LOAD_CONST" and ins[n - 2].argval is None
                    and not ins[n - 2].is_target and ins[n - 3].opname in ("RETURN_VALUE", "RAISE_VARARGS"))
            stmts = stmts[:-1]
            if dead:
                stmts = make_last_compound(stmts)
        return stmts

    def declarations(self):
        code = self.code
        out = []
        globals_ = []
        nonlocals = []
        for op in self.ins:
            if op.opname in ("STORE_GLOBAL", "DELETE_GLOBAL") and op.argval not in globals_:
                globals_.append(op.argval)
            if self.kind in ("class", "module") and op.opname == "LOAD_GLOBAL" and op.argval not in globals_:
                globals_.append(op.argval)
            if op.opname in ("STORE_DEREF", "DELETE_DEREF") and op.argval in code.co_freevars and op.argval not in nonlocals:
                nonlocals.append(op.argval)
        if globals_:
            out.append(S.Global(globals_))
        if nonlocals:
            out.append(S.Global(nonlocals, nonlocal_=True))
        return out

    def module_body(self):
        stmts = self.body(0, self.n, None)
        stmts = self.finish_body(stmts)
        k = 0
        while k < len(stmts) and isinstance(stmts[k], S.ImportFrom) and stmts[k].module == "__future__" and not stmts[k].level:
            k += 1
        return stmts[:k] + self.declarations() + stmts[k:]

    def class_body(self):
        tail = [op.opname for op in self.ins[-4:]]
        if tail == ["LOAD_CLOSURE", "DUP_TOP", "STORE_NAME", "RETURN_VALUE"] and self.ins[-2].argval == "__classcell__":
            stmts = self.body(0, self.n - 4, None)
        else:
            stmts = self.finish_body(self.body(0, self.n, None))
        k = 0
        for name in ("__module__", "__qualname__"):
            if k < len(stmts) and isinstance(stmts[k], S.Assign) and len(stmts[k].targets) == 1 and isinstance(stmts[k].targets[0], S.Name) and stmts[k].targets[0].name == name:
                k += 1
        return self.place_declarations(self.declarations(), stmts[k:])

    def comprehension(self, outer_iter):
        name = self.code.co_name
        ins = self.ins
        i = 0
        if name != "<genexpr>":
            if ins[0].opname not in ("BUILD_LIST", "BUILD_SET", "BUILD_MAP") or ins[0].arg != 0:
                raise Fail("comprehension start")
            i = 1
        generators = []
        first = True
        while True:
            if first:
                if ins[i].opname != "LOAD_FAST" or ins[i].argval != ".0":
                    raise Fail("comprehension source")
                it = outer_iter
                f = i + 1
                first = False
            else:
                g = i
                while g < self.n and not (ins[g].opname == "GET_ITER" and ins[g + 1].opname == "FOR_ITER"):
                    g += 1
                it = self.eval_one(i, g)
                f = g + 1
            if ins[f].opname != "FOR_ITER":
                raise Fail("comprehension loop")
            C = ins[f].target
            target, b = self.target_after(f + 1, C)
            ifs = []
            try:
                atom = self.sim_atom(b, C)
            except Fail:
                atom = None
            if atom is not None:
                atoms = self.collect_atoms(atom, C)
                for k in range(len(atoms), 0, -1):
                    if self.resolve(atoms[k - 1].target) != f:
                        continue
                    cond = self.parse_cond(atoms, 0, k, f, False, atoms[k - 1].after)
                    if cond is not None:
                        ifs = list(cond.values) if isinstance(cond, S.BoolOp) and cond.op == "and" else [cond]
                        b = atoms[k - 1].after
                        break
            generators.append(S.Comprehension(target, it, ifs))
            nested = self.loop_kind(b, C)
            if nested is not None and self.is_nested_loop(b, nested):
                i = b
                continue
            return self.comprehension_element(name, b, C, f, generators)

    def is_nested_loop(self, b, g):
        try:
            self.eval_one(b, g)
            return True
        except Fail:
            return False

    def comprehension_element(self, name, b, C, f, generators):
        ins = self.ins
        stop = {"<listcomp>": "LIST_APPEND", "<setcomp>": "SET_ADD", "<dictcomp>": "MAP_ADD", "<genexpr>": "YIELD_VALUE"}[name]
        candidates = [x for x in range(b, C) if ins[x].opname == stop]
        for k in candidates:
            try:
                stack = self.eval_range(b, k, [])
            except Fail:
                continue
            if name == "<dictcomp>":
                if len(stack) != 2:
                    continue
                return S.DictComp(self.value(stack[1]), self.value(stack[0]), generators)
            if len(stack) != 1:
                continue
            elt = self.value(stack[0])
            if name == "<listcomp>":
                return S.ListComp(elt, generators)
            if name == "<setcomp>":
                return S.SetComp(elt, generators)
            return S.GeneratorExp(elt, generators)
        raise Fail("comprehension element")


def _binary_handler(symbol, inplace):
    return simple(lambda self, frame, op: self.binary(frame, op, symbol, inplace))


def _unary_handler(symbol):
    return simple(lambda self, frame, op: self.push(frame, S.UnaryOp(symbol, self.value(self.pop(frame)))))


for _name, _sym in BINARY_OPS.items():
    setattr(CodeDecompiler, "op_" + _name, _binary_handler(_sym, False))
for _name, _sym in INPLACE_OPS.items():
    setattr(CodeDecompiler, "op_" + _name, _binary_handler(_sym, True))
for _name, _sym in UNARY_OPS.items():
    setattr(CodeDecompiler, "op_" + _name, _unary_handler(_sym))


def line_table(code, ins):
    starts = dict(dis.findlinestarts(code))
    out = []
    current = code.co_firstlineno
    offsets = sorted(starts)
    k = 0
    for op in ins:
        while k < len(offsets) and offsets[k] <= op.offset:
            current = starts[offsets[k]]
            k += 1
        out.append(current)
    return out


def folds_under_not(expr):
    return isinstance(expr, S.Compare) and len(expr.ops) == 1 and expr.ops[0] in ("is", "is not", "in", "not in")


def negate(expr):
    if isinstance(expr, S.UnaryOp) and expr.op == "not":
        return expr.operand
    n = S.UnaryOp("not", expr)
    n.line = expr.line
    return n


def make_last_compound(stmts):
    for m in range(len(stmts) - 1, -1, -1):
        s = stmts[m]
        if isinstance(s, S.If) and not s.orelse and s.body and isinstance(s.body[-1], (S.Return, S.Raise)) and m + 1 < len(stmts):
            return stmts[:m] + [S.If(s.test, s.body, stmts[m + 1:])]
    return stmts


def statements_to_expr(stmts):
    if len(stmts) == 1 and isinstance(stmts[0], S.Return):
        return stmts[0].value if stmts[0].value is not None else S.Const(None)
    if len(stmts) == 2 and isinstance(stmts[0], S.If) and isinstance(stmts[1], S.Return) and not stmts[0].orelse:
        body = statements_to_expr(stmts[0].body)
        orelse = statements_to_expr(stmts[1:])
        if body is not None and orelse is not None:
            return S.IfExp(stmts[0].test, body, orelse)
    if len(stmts) == 1 and isinstance(stmts[0], S.If) and stmts[0].orelse:
        body = statements_to_expr(stmts[0].body)
        orelse = statements_to_expr(stmts[0].orelse)
        if body is not None and orelse is not None:
            return S.IfExp(stmts[0].test, body, orelse)
    return None


def decompile_code(code, session=None):
    d = CodeDecompiler(code, None, session)
    if d.kind == "module":
        return d.module_body()
    if d.kind == "class":
        return d.class_body()
    return d.function_body()
