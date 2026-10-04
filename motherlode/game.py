"""Finds Sims 4 installations and the compiled script archives inside them."""

import glob
import os
import re
import string
import sys

GAMEPLAY = ("base.zip", "core.zip", "simulation.zip")
GENERATED = "generated.zip"
ARCHIVE_NAMES = GAMEPLAY + (GENERATED,)

WINDOWS_LAYOUT = {
    "base.zip": ("Data", "Simulation", "Gameplay"),
    "core.zip": ("Data", "Simulation", "Gameplay"),
    "simulation.zip": ("Data", "Simulation", "Gameplay"),
    "generated.zip": ("Game", "Bin", "Python"),
}
MAC_LAYOUT = {
    "base.zip": ("Contents", "Data", "Simulation", "Gameplay"),
    "core.zip": ("Contents", "Data", "Simulation", "Gameplay"),
    "simulation.zip": ("Contents", "Data", "Simulation", "Gameplay"),
    "generated.zip": ("Contents", "Python"),
}
MAC_APP = "The Sims 4.app"
MAC_APPLICATION_DIRS = ("/Applications", "~/Applications")
SKIP_DIRS = re.compile(r"^(Delta|__Installer|EP\d+|GP\d+|SP\d+|FP\d+|Support|_CommonRedist)$", re.IGNORECASE)

WINDOWS_RELATIVE_INSTALLS = (
    ("Program Files", "EA Games", "The Sims 4"),
    ("Program Files (x86)", "EA Games", "The Sims 4"),
    ("Program Files (x86)", "Origin Games", "The Sims 4"),
    ("Program Files", "Origin Games", "The Sims 4"),
    ("Program Files (x86)", "Steam", "steamapps", "common", "The Sims 4"),
    ("Program Files", "Steam", "steamapps", "common", "The Sims 4"),
    ("SteamLibrary", "steamapps", "common", "The Sims 4"),
    ("Program Files", "Epic Games", "TheSims4"),
    ("EA Games", "The Sims 4"),
    ("Origin Games", "The Sims 4"),
    ("Games", "The Sims 4"),
)
REGISTRY_KEYS = (
    r"SOFTWARE\WOW6432Node\Maxis\The Sims 4",
    r"SOFTWARE\Maxis\The Sims 4",
)


def find_archives(path):
    """Returns {archive name: path} for the script archives under an install folder, app bundle, or the folder holding the app."""
    found = {}
    bases = [(path, WINDOWS_LAYOUT), (path, MAC_LAYOUT), (os.path.join(path, MAC_APP), MAC_LAYOUT)]
    for name in ARCHIVE_NAMES:
        for base, layout in bases:
            candidate = os.path.join(base, *layout[name], name)
            if os.path.isfile(candidate):
                found[name] = candidate
                break
    if len(found) < len(ARCHIVE_NAMES) and os.path.isdir(path):
        for name, candidate in search_archives(path).items():
            found.setdefault(name, candidate)
    return found


def search_archives(path, max_depth=6):
    found = {}
    root_depth = path.rstrip(os.sep).count(os.sep)
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if not SKIP_DIRS.match(d)]
        if root.count(os.sep) - root_depth >= max_depth:
            dirs[:] = []
        for name in files:
            lower = name.lower()
            if lower in ARCHIVE_NAMES and lower not in found:
                parent = os.path.basename(root).lower()
                if (lower == GENERATED and parent == "python") or (lower in GAMEPLAY and parent == "gameplay"):
                    found[lower] = os.path.join(root, name)
    return found


def looks_like_install(path):
    return os.path.isdir(path) and len(find_archives(path)) == len(ARCHIVE_NAMES)


def steam_libraries(steam_root):
    libraries = [steam_root]
    vdf = os.path.join(steam_root, "steamapps", "libraryfolders.vdf")
    try:
        with open(vdf, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return libraries
    for match in re.finditer(r'"path"\s+"([^"]+)"', text):
        libraries.append(match.group(1).replace("\\\\", "\\"))
    for match in re.finditer(r'^\s*"\d+"\s+"([^"]+)"', text, re.MULTILINE):
        libraries.append(match.group(1).replace("\\\\", "\\"))
    return libraries


def windows_candidates():
    candidates = []
    try:
        import winreg
    except ImportError:
        winreg = None
    if winreg is not None:
        for key in REGISTRY_KEYS:
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    with winreg.OpenKey(hive, key) as handle:
                        value, _ = winreg.QueryValueEx(handle, "Install Dir")
                        candidates.append(value)
                except OSError:
                    pass
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as handle:
                steam, _ = winreg.QueryValueEx(handle, "SteamPath")
                for library in steam_libraries(os.path.normpath(steam)):
                    candidates.append(os.path.join(library, "steamapps", "common", "The Sims 4"))
        except OSError:
            pass
    for letter in string.ascii_uppercase[2:]:
        drive = letter + ":\\"
        if not os.path.isdir(drive):
            continue
        for parts in WINDOWS_RELATIVE_INSTALLS:
            candidates.append(os.path.join(drive, *parts))
    return candidates


def mac_candidates():
    home = os.path.expanduser("~")
    candidates = []
    for applications in MAC_APPLICATION_DIRS:
        applications = os.path.expanduser(applications)
        candidates.append(os.path.join(applications, MAC_APP))
        candidates.extend(sorted(glob.glob(os.path.join(applications, "*", MAC_APP))))
    steam = os.path.join(home, "Library", "Application Support", "Steam")
    for library in steam_libraries(steam):
        candidates.append(os.path.join(library, "steamapps", "common", "The Sims 4"))
    return candidates


def linux_candidates():
    home = os.path.expanduser("~")
    candidates = []
    for steam in (os.path.join(home, ".steam", "steam"), os.path.join(home, ".local", "share", "Steam")):
        for library in steam_libraries(steam):
            candidates.append(os.path.join(library, "steamapps", "common", "The Sims 4"))
    return candidates


def detect_installs(platform=None):
    """Returns the Sims 4 installs found on this machine, most likely first."""
    platform = platform or sys.platform
    if platform.startswith("win"):
        candidates = windows_candidates()
    elif platform == "darwin":
        candidates = mac_candidates()
    else:
        candidates = linux_candidates()
    installs = []
    seen = set()
    for path in candidates:
        try:
            real = os.path.normcase(os.path.realpath(path))
        except (OSError, ValueError):
            continue
        if real in seen or not os.path.isdir(path):
            continue
        seen.add(real)
        if looks_like_install(path):
            installs.append(path)
    return installs
