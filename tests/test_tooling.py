import contextlib
import importlib.util
import io
import json
import marshal
import os
import shutil
import tempfile
import unittest
import zipfile

from motherlode.cli import destination, main
from motherlode.game import detect_installs, find_archives, steam_libraries
from motherlode.ide import write_project_files, write_stubs
from motherlode.verify import compile_source

PYC_HEADER = importlib.util.MAGIC_NUMBER + b"\0" * 12


def touch(path, data=b""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def write_archive(path, members):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        for name, source in members.items():
            z.writestr(name, PYC_HEADER + marshal.dumps(compile_source(source)))


def run_quietly(argv):
    with contextlib.redirect_stdout(io.StringIO()):
        return main(argv)


class TempDir(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir)

    def path(self, *parts):
        return os.path.join(self.dir, *parts)


class Layouts(TempDir):
    def make_windows(self, root):
        for name in ("base.zip", "core.zip", "simulation.zip"):
            touch(os.path.join(root, "Data", "Simulation", "Gameplay", name))
        touch(os.path.join(root, "Game", "Bin", "Python", "generated.zip"))

    def make_mac(self, app):
        for name in ("base.zip", "core.zip", "simulation.zip"):
            touch(os.path.join(app, "Contents", "Data", "Simulation", "Gameplay", name))
        touch(os.path.join(app, "Contents", "Python", "generated.zip"))

    def test_windows_install(self):
        root = self.path("The Sims 4")
        self.make_windows(root)
        self.assertEqual(sorted(find_archives(root)), ["base.zip", "core.zip", "generated.zip", "simulation.zip"])

    def test_mac_app_and_its_folder(self):
        folder = self.path("The Sims 4")
        app = os.path.join(folder, "The Sims 4.app")
        self.make_mac(app)
        self.assertEqual(len(find_archives(app)), 4)
        self.assertEqual(len(find_archives(folder)), 4)

    def test_unusual_layout_is_found_by_searching(self):
        root = self.path("Somewhere")
        self.make_windows(os.path.join(root, "nested", "game"))
        self.assertEqual(len(find_archives(root)), 4)

    def test_pack_folders_are_not_searched(self):
        root = self.path("The Sims 4")
        touch(os.path.join(root, "Delta", "EP01", "Gameplay", "simulation.zip"))
        self.assertEqual(find_archives(root), {})

    def test_steam_library_folders(self):
        steam = self.path("Steam")
        touch(os.path.join(steam, "steamapps", "libraryfolders.vdf"), (
            '"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"D:\\\\SteamLibrary"\n\t}\n'
            '\t"1"\t\t"E:\\\\Games"\n}\n').encode())
        self.assertEqual(steam_libraries(steam), [steam, "D:\\SteamLibrary", "E:\\Games"])

    def test_mac_app_inside_an_applications_subfolder(self):
        import motherlode.game as game
        applications = self.path("Applications")
        self.make_mac(os.path.join(applications, "EA Games", "The Sims 4.app"))
        os.makedirs(os.path.join(applications, "EA Games", "The Sims 4 Packs"))
        saved = game.MAC_APPLICATION_DIRS
        game.MAC_APPLICATION_DIRS = (applications,)
        try:
            self.assertEqual(game.detect_installs("darwin"), [os.path.join(applications, "EA Games", "The Sims 4.app")])
        finally:
            game.MAC_APPLICATION_DIRS = saved

    def test_detect_on_unknown_platform_returns_a_list(self):
        self.assertIsInstance(detect_installs("plan9"), list)


class OutputLayout(unittest.TestCase):
    def test_destinations_mirror_import_roots(self):
        self.assertEqual(destination("x/simulation.zip", "buffs/buff.pyc"), "scripts/buffs/buff.py")
        self.assertEqual(destination("x/core.zip", "sims4/log.pyc"), "scripts/sims4/log.py")
        self.assertEqual(destination("x/generated.zip", "protocolbuffers/Math_pb2.pyc"), "scripts/protocolbuffers/Math_pb2.py")
        self.assertEqual(destination("x/base.zip", "lib/abc.pyc"), "stdlib/abc.py")
        self.assertEqual(destination("x/MyMod.ts4script", "my_mod/main.pyc"), "MyMod/my_mod/main.py")


class EndToEnd(TempDir):
    def test_install_folder_becomes_ide_project(self):
        game = self.path("The Sims 4")
        gameplay = os.path.join(game, "Data", "Simulation", "Gameplay")
        write_archive(os.path.join(gameplay, "core.zip"), {
            "sims4/__init__.pyc": "",
            "sims4/math.pyc": "import _math\nfrom _math import Vector3, mod_2pi\nORIGIN = _math.ZERO\n",
        })
        write_archive(os.path.join(gameplay, "simulation.zip"), {
            "buffs/__init__.pyc": "",
            "buffs/buff.pyc": "import sims4.math\nfrom Math_pb2 import Quaternion\nclass Buff:\n    pass\n",
        })
        write_archive(os.path.join(gameplay, "base.zip"), {"lib/enum_lib.pyc": "X = 1\n"})
        write_archive(os.path.join(game, "Game", "Bin", "Python", "generated.zip"), {
            "protocolbuffers/__init__.pyc": "",
            "protocolbuffers/Math_pb2.pyc": "Quaternion = object\n",
        })
        out = self.path("out")
        self.assertEqual(run_quietly([game, "-o", out, "-j", "1"]), 0)
        for rel in ("scripts/sims4/math.py", "scripts/buffs/buff.py", "scripts/protocolbuffers/Math_pb2.py",
                    "stdlib/enum_lib.py", "motherlode-report.txt", "pyrightconfig.json",
                    ".vscode/settings.json", "ts4-python.iml", ".idea/modules.xml"):
            self.assertTrue(os.path.isfile(os.path.join(out, *rel.split("/"))), rel)
        with open(os.path.join(out, "stubs", "_math.pyi")) as f:
            stub = f.read()
        self.assertIn("class Vector3:", stub)
        self.assertIn("def mod_2pi(", stub)
        self.assertIn("ZERO: Any", stub)
        with open(os.path.join(out, "stubs", "Math_pb2.pyi")) as f:
            self.assertEqual(f.read(), "from protocolbuffers.Math_pb2 import *\n")
        with open(os.path.join(out, "pyrightconfig.json")) as f:
            config = json.load(f)
        self.assertEqual(config["extraPaths"], ["scripts"])
        self.assertEqual(config["stubPath"], "stubs")
        with open(os.path.join(out, "motherlode-report.json")) as f:
            report = json.load(f)
        self.assertTrue(all(r["verified"] == r["total"] for r in report["files"]))

    def test_rerun_replaces_previous_scripts(self):
        out = self.path("out")
        os.makedirs(os.path.join(out, "scripts", "gone"))
        touch(os.path.join(out, "motherlode-report.json"), b"{}")
        archive = self.path("simulation.zip")
        write_archive(archive, {"kept.pyc": "x = 1\n"})
        run_quietly([archive, "-o", out, "-j", "1"])
        self.assertFalse(os.path.exists(os.path.join(out, "scripts", "gone")))
        self.assertTrue(os.path.isfile(os.path.join(out, "scripts", "kept.py")))

    def test_unowned_folders_are_left_alone(self):
        out = self.path("out")
        os.makedirs(os.path.join(out, "scripts", "mine"))
        archive = self.path("simulation.zip")
        write_archive(archive, {"kept.pyc": "x = 1\n"})
        run_quietly([archive, "-o", out, "-j", "1"])
        self.assertTrue(os.path.isdir(os.path.join(out, "scripts", "mine")))


class ProjectFiles(TempDir):
    def test_without_stubs(self):
        write_project_files(self.dir, False)
        with open(self.path("pyrightconfig.json")) as f:
            self.assertNotIn("stubPath", json.load(f))
        with open(self.path("ts4-python.iml")) as f:
            self.assertNotIn("/stubs", f.read())

    def test_stubs_skip_known_modules(self):
        touch(self.path("scripts", "game_module.py"), b"import os\nimport game_module\nimport debugger\nimport _engine\n_engine.call()\n")
        self.assertEqual(write_stubs(self.dir), ["_engine"])


if __name__ == "__main__":
    unittest.main()
