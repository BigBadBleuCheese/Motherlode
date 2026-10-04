"""Project files and stubs that let PyCharm, VS Code and other editors understand the decompiled scripts."""

import ast
import importlib.util
import json
import os
import sys
import sysconfig

SCRIPTS = "scripts"
STDLIB = "stdlib"
STUBS = "stubs"
MODULE_NAME = "ts4-python"
NOT_ENGINE = {"__builtin__"}
RENAMED_STDLIB = {"enum_lib": "enum"}


def module_index(root):
    names = set()
    for current, dirs, files in os.walk(root):
        rel = os.path.relpath(current, root)
        prefix = "" if rel == "." else rel.replace(os.sep, ".")
        for name in files:
            if not name.endswith((".py", ".pyi")):
                continue
            stem = name.rsplit(".", 1)[0]
            if stem == "__init__":
                if prefix:
                    names.add(prefix)
            else:
                names.add(prefix + "." + stem if prefix else stem)
        if prefix:
            names.add(prefix)
    return names


def is_standard(top, stdlib_names):
    if top in sys.builtin_module_names or top in stdlib_names:
        return True
    try:
        spec = importlib.util.find_spec(top)
    except (ImportError, ValueError):
        return False
    if spec is None:
        return False
    origin = spec.origin or ""
    return origin in ("built-in", "frozen") or origin.startswith(sysconfig.get_paths()["stdlib"])


def collect_engine_imports(scripts_dir, known):
    """Maps each unresolvable top-level module the scripts import to the names they use from it."""
    used = {}
    for current, _, files in os.walk(scripts_dir):
        for name in files:
            if not name.endswith(".py"):
                continue
            try:
                with open(os.path.join(current, name), encoding="utf-8") as f:
                    tree = ast.parse(f.read())
            except (SyntaxError, ValueError, OSError):
                continue
            bound = {}
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        top = alias.name.split(".")[0]
                        if known(top):
                            continue
                        used.setdefault(top, set())
                        if alias.asname and "." not in alias.name:
                            bound[alias.asname] = top
                        elif "." not in alias.name:
                            bound[top] = top
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module and "." not in node.module:
                    if known(node.module):
                        continue
                    names = used.setdefault(node.module, set())
                    names.update(a.name for a in node.names if a.name != "*")
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in bound:
                    used[bound[node.value.id]].add(node.attr)
    return used


def stub_text(names):
    lines = ["from typing import Any", "", "def __getattr__(name: str) -> Any: ...", ""]
    for name in sorted(names):
        if not name.isidentifier():
            continue
        if name[0].isupper() and not name.isupper():
            lines += ["", "class %s:" % name,
                      "    def __init__(self, *args: Any, **kwargs: Any) -> None: ...",
                      "    def __getattr__(self, name: str) -> Any: ...", ""]
        elif name.isupper():
            lines.append("%s: Any" % name)
        else:
            lines.append("def %s(*args: Any, **kwargs: Any) -> Any: ..." % name)
    return "\n".join(lines).rstrip() + "\n"


def write_stubs(out_dir):
    """Writes .pyi stubs for engine modules built into the game and for top-level aliases of protocol buffer modules."""
    scripts_dir = os.path.join(out_dir, SCRIPTS)
    stdlib_dir = os.path.join(out_dir, STDLIB)
    stubs_dir = os.path.join(out_dir, STUBS)
    scripts = module_index(scripts_dir)
    stdlib = {n.split(".")[0] for n in module_index(stdlib_dir)} if os.path.isdir(stdlib_dir) else set()

    def known(top):
        if top in scripts:
            return True
        if top.startswith("_") and top not in stdlib:
            return False
        return top not in RENAMED_STDLIB and is_standard(top, set())

    written = []
    for module, names in sorted(collect_engine_imports(scripts_dir, known).items()):
        if "protocolbuffers." + module in scripts:
            text = "from protocolbuffers.%s import *\n" % module
        elif module in RENAMED_STDLIB:
            text = "from %s import *\n" % RENAMED_STDLIB[module]
        elif module.startswith("_") and module not in NOT_ENGINE:
            text = stub_text(names)
        else:
            continue
        os.makedirs(stubs_dir, exist_ok=True)
        with open(os.path.join(stubs_dir, module + ".pyi"), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        written.append(module)
    return written


PYCHARM_MODULE = """<?xml version="1.0" encoding="UTF-8"?>
<module type="PYTHON_MODULE" version="4">
  <component name="NewModuleRootManager">
    <content url="file://$MODULE_DIR$">
      <sourceFolder url="file://$MODULE_DIR$/{scripts}" isTestSource="false" />
{stubs}    </content>
    <orderEntry type="inheritedJdk" />
    <orderEntry type="sourceFolder" forTests="false" />
  </component>
</module>
"""

PYCHARM_MODULES = """<?xml version="1.0" encoding="UTF-8"?>
<project version="4">
  <component name="ProjectModuleManager">
    <modules>
      <module fileurl="file://$PROJECT_DIR$/{name}.iml" filepath="$PROJECT_DIR$/{name}.iml" />
    </modules>
  </component>
</project>
"""


def write_project_files(out_dir, has_stubs):
    """Writes editor settings so the folder opens as a project with the game's import root configured."""
    pyright = {
        "pythonVersion": "3.7",
        "include": [SCRIPTS],
        "extraPaths": [SCRIPTS],
        "typeCheckingMode": "off",
        "reportMissingModuleSource": "none",
        "reportInvalidTypeForm": "none",
    }
    if has_stubs:
        pyright["stubPath"] = STUBS
    with open(os.path.join(out_dir, "pyrightconfig.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(pyright, f, indent=2)
        f.write("\n")

    vscode = os.path.join(out_dir, ".vscode")
    os.makedirs(vscode, exist_ok=True)
    settings = {
        "python.analysis.extraPaths": [SCRIPTS],
        "files.exclude": {"**/__pycache__": True},
    }
    if has_stubs:
        settings["python.analysis.stubPath"] = STUBS
    with open(os.path.join(vscode, "settings.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")

    stubs = '      <sourceFolder url="file://$MODULE_DIR$/%s" isTestSource="false" />\n' % STUBS if has_stubs else ""
    with open(os.path.join(out_dir, MODULE_NAME + ".iml"), "w", encoding="utf-8", newline="\n") as f:
        f.write(PYCHARM_MODULE.format(scripts=SCRIPTS, stubs=stubs))
    idea = os.path.join(out_dir, ".idea")
    os.makedirs(idea, exist_ok=True)
    with open(os.path.join(idea, "modules.xml"), "w", encoding="utf-8", newline="\n") as f:
        f.write(PYCHARM_MODULES.format(name=MODULE_NAME))
