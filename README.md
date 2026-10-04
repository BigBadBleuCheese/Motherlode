# Motherlode

A decompiler for The Sims 4's Python scripts that proves its own output.

The game ships its simulation code as compiled Python 3.7 bytecode inside a handful of `.zip` archives. Decompilers have been turning that back into source for years, but they get some functions wrong, and when they do, nothing tells you: the output compiles, it reads fine, and it behaves differently from the game.

Motherlode closes that gap. After decompiling a file, it compiles the result with the same compiler and settings the game uses and compares every function's bytecode with the game's, instruction by instruction. A function that matches is proven to be the game's code. A function that doesn't is listed in the report, so you know exactly what not to trust.

## Results

Measured on the full game install (3,323 script files, 72,954 functions, classes, lambdas and comprehensions):

| Archive | Files | Fully verified files | Code objects verified |
|---|---:|---:|---:|
| `simulation.zip` | 2,724 | 99.27% | 99.95% |
| `core.zip` | 121 | 98.35% | 99.93% |
| `generated.zip` | 58 | 100.00% | 100.00% |
| `base.zip` (EA's copy of the standard library) | 420 | 97.62% | 99.85% |
| **All** | **3,323** | **99.04%** | **99.93%** |

For comparison, the same check applied to decompyle3 3.9.3 on the game's own code (everything except `base.zip`) verifies 52.4% of files and 72.6% of code objects. Another 7.6% of its code objects compile but don't match, and those include real logic errors, such as `sims4.commands` code that returns `None` where the game returns `True`.

A full install decompiles in about a minute and a half on two cores.

## Requirements

Python 3.7, the same version the game runs. If you build script mods you already have it. Motherlode has no other dependencies.

## Usage

Install it from GitHub:

```
py -3.7 -m pip install git+https://github.com/BigBadBleuCheese/Motherlode
```

Point it at your game folder:

```
motherlode "C:\Program Files\EA Games\The Sims 4" -o decompiled
```

You can also run it from a clone without installing (`py -3.7 -m motherlode ...`), and you can give it individual `.zip` archives, folders of `.pyc` files, or single `.pyc` files instead of the install folder.

The output folder gets one `.py` file per script, laid out the way the game's archives are (`decompiled/simulation/buffs/buff.py`, and so on), plus two reports:

- `motherlode-report.txt` lists every function that did not verify, by file.
- `motherlode-report.json` has the same information for tools.

Options:

- `-j N` sets the number of worker processes (default: one less than your CPU count).
- `--no-search` skips the retry pass described below, which is faster but verifies slightly less.

## How it works

Most decompilers match bytecode against a grammar of known patterns. When the compiler's optimizer rearranges jumps in a way the grammar doesn't expect, they either give up or quietly pick the wrong structure. The classic example in the game's code is `if a and b: return x` followed by `return y`, which a grammar-based decompiler can nest the wrong way, so the function returns `None` when `a` is false.

Motherlode targets exactly one compiler: CPython 3.7 with `-OO`, the way EA builds the game. It reconstructs loops and `try`/`with` blocks from the explicit block markers 3.7 emits, rebuilds `if` statements and `and`/`or` chains by inverting what the 3.7 compiler does with conditions, and accounts for the optimizer's jump threading and dead-code rules. When a function could have come from more than one structure, the result is compiled and checked; if it doesn't match, Motherlode retries the alternatives and keeps the one that does.

Two verdicts count as verified:

- **exact**: the bytecode is identical.
- **equivalent**: the instructions and control flow are identical, and the only difference is unreachable code or jump layout. These functions behave identically.

### Line numbers

Statements are written on the same line numbers they occupy in EA's source files. Blank space shows up where comments and docstrings used to be. The upside is that line numbers in the game's exception logs point at the right line of the decompiled file.

## What can't be recovered

- **Comments, docstrings and `assert` statements.** The game is compiled with `-OO`, which removes docstrings and asserts from the bytecode entirely.
- **Formatting.** Names, constants and structure come back exactly. Quoting style, parentheses and line wrapping are Motherlode's own.
- **Some unreachable code.** Code after a `return` is partly removed by the compiler, so a few functions whose dead code was only half removed can't be reproduced exactly. They behave the same and are listed in the report.
- **Native modules.** A few modules ship as compiled machine code (`.pyd` files under `Game\Bin\Python\DLLs`), not Python bytecode, so no Python decompiler can recover them.

## Using it as a library

```python
from motherlode import decompile_pyc

result = decompile_pyc("buff.pyc")
print(result.source)
for f in result.unverified():
    print(f.status, f.path)
```

## Running the tests

```
py -3.7 -m unittest
```

Each test compiles a snippet the way the game does, decompiles it, and requires every code object to verify.

## A note on the game's code

Motherlode contains no game code. It works on the copy of the game you already have. The scripts it produces are EA's work, so use them the way the modding community always has: to understand the game and build mods for it.

## License

MIT
