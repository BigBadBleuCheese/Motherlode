"""Instruction decoding for CPython 3.7 code objects."""

import dis
import marshal
import types

HEADER_SIZE = 16
MAGIC = (3394).to_bytes(2, "little") + b"\r\n"

JUMP_OPS = set(dis.hasjrel) | set(dis.hasjabs)
UNCONDITIONAL = {"JUMP_FORWARD", "JUMP_ABSOLUTE"}
POP_JUMPS = {"POP_JUMP_IF_FALSE", "POP_JUMP_IF_TRUE"}
OR_POP_JUMPS = {"JUMP_IF_FALSE_OR_POP", "JUMP_IF_TRUE_OR_POP"}
CONDITIONAL = POP_JUMPS | OR_POP_JUMPS

CO_OPTIMIZED = 0x1
CO_NEWLOCALS = 0x2
CO_VARARGS = 0x4
CO_VARKEYWORDS = 0x8
CO_NESTED = 0x10
CO_GENERATOR = 0x20
CO_COROUTINE = 0x80
CO_ITERABLE_COROUTINE = 0x100
CO_ASYNC_GENERATOR = 0x200
CO_FUTURE_ANNOTATIONS = 0x100000


class Instruction:
    __slots__ = ("index", "offset", "opname", "opcode", "arg", "argval", "target", "is_target")

    def __init__(self, index, offset, opname, opcode, arg, argval):
        self.index = index
        self.offset = offset
        self.opname = opname
        self.opcode = opcode
        self.arg = arg
        self.argval = argval
        self.target = None
        self.is_target = False

    @property
    def jumps_on_true(self):
        return self.opname in ("POP_JUMP_IF_TRUE", "JUMP_IF_TRUE_OR_POP")

    def __repr__(self):
        extra = " -> %d" % self.target if self.target is not None else (" %r" % (self.argval,) if self.arg is not None else "")
        return "<%d %s%s>" % (self.index, self.opname, extra)


def decode(code):
    raw = list(dis.get_instructions(code))
    out = []
    offset_index = {}
    pending = []
    for r in raw:
        if r.opname == "EXTENDED_ARG":
            pending.append(r.offset)
            continue
        idx = len(out)
        offset_index[r.offset] = idx
        for o in pending:
            offset_index[o] = idx
        pending = []
        out.append(Instruction(idx, r.offset, r.opname, r.opcode, r.arg, r.argval))
    end = len(out)
    offset_index[len(code.co_code)] = end
    for ins in out:
        if ins.opcode in JUMP_OPS:
            ins.target = offset_index[ins.argval]
            if ins.target < end:
                out[ins.target].is_target = True
    return out


def load_pyc_bytes(data):
    if data[:4] != MAGIC:
        raise ValueError("not a Python 3.7 .pyc file (magic %s)" % data[:4].hex())
    code = marshal.loads(data[HEADER_SIZE:])
    if not isinstance(code, types.CodeType):
        raise ValueError("pyc does not contain a code object")
    return code


def load_pyc(path):
    with open(path, "rb") as f:
        return load_pyc_bytes(f.read())
