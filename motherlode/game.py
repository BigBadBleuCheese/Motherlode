"""Finds the compiled script archives in a Sims 4 installation."""

import os

ARCHIVES = (
    ("Data", "Simulation", "Gameplay", "base.zip"),
    ("Data", "Simulation", "Gameplay", "core.zip"),
    ("Data", "Simulation", "Gameplay", "simulation.zip"),
    ("Game", "Bin", "Python", "generated.zip"),
)

MAC_ROOT = ("The Sims 4.app", "Contents")


def find_archives(install_dir):
    """Returns the paths of the script archives under a Sims 4 install folder."""
    found = []
    roots = [install_dir, os.path.join(install_dir, *MAC_ROOT)]
    for parts in ARCHIVES:
        for root in roots:
            path = os.path.join(root, *parts)
            if os.path.isfile(path):
                found.append(path)
                break
    return found


def looks_like_install(path):
    return os.path.isdir(path) and bool(find_archives(path))
