"""Command line interface: decompile the installed game, script archives, folders, or single .pyc files."""

import argparse
import json
import multiprocessing
import os
import shutil
import subprocess
import sys
import time
import zipfile

from . import __version__
from .api import decompile_pyc_bytes
from .game import ARCHIVE_NAMES, detect_installs, find_archives, looks_like_install
from .ide import SCRIPTS, STDLIB, STUBS, write_project_files, write_stubs

REPORT_JSON = "motherlode-report.json"
REPORT_TEXT = "motherlode-report.txt"
MANAGED = (SCRIPTS, STDLIB, STUBS)


def destination(archive, member):
    """Where a .pyc from a script archive lands in the output, mirroring the game's import roots."""
    name = os.path.basename(archive).lower()
    rel = member[:-4] + ".py"
    if name == "base.zip":
        if rel.startswith("lib/"):
            rel = rel[4:]
        return STDLIB + "/" + rel
    if name in ARCHIVE_NAMES:
        return SCRIPTS + "/" + rel
    return os.path.splitext(os.path.basename(archive))[0] + "/" + rel


def is_archive(path):
    return os.path.isfile(path) and path.lower().endswith((".zip", ".ts4script")) and zipfile.is_zipfile(path)


def collect(inputs):
    """Yields (label, archive_or_none, member_or_path, output_relpath) for every .pyc to decompile."""
    for item in inputs:
        if looks_like_install(item):
            for archive in find_archives(item).values():
                yield from collect_zip(archive)
        elif is_archive(item):
            yield from collect_zip(item)
        elif os.path.isdir(item):
            for root, _, files in os.walk(item):
                for name in sorted(files):
                    if name.endswith(".pyc"):
                        path = os.path.join(root, name)
                        rel = os.path.relpath(path, item).replace(os.sep, "/")
                        yield (path, None, path, rel[:-4] + ".py")
        elif os.path.isfile(item) and item.endswith(".pyc"):
            yield (item, None, item, os.path.basename(item)[:-4] + ".py")
        else:
            raise SystemExit("motherlode: not a Sims 4 install, script archive, folder, or .pyc file: " + item)


def collect_zip(archive):
    with zipfile.ZipFile(archive) as z:
        for name in sorted(z.namelist()):
            if name.endswith(".pyc"):
                yield (archive + ":" + name, archive, name, destination(archive, name))


def work(job):
    label, archive, member, rel, out_dir, search = job
    started = time.time()
    if archive is not None:
        with zipfile.ZipFile(archive) as z:
            data = z.read(member)
    else:
        with open(member, "rb") as f:
            data = f.read()
    try:
        result = decompile_pyc_bytes(data, search=search)
    except Exception as e:
        return {"file": rel, "source": label, "error": "%s: %s" % (type(e).__name__, e), "total": 0, "verified": 0, "unverified": []}
    target = os.path.join(out_dir, *rel.split("/"))
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    with open(target, "w", encoding="utf-8", newline="\n") as f:
        f.write(result.source)
    return {
        "file": rel,
        "source": label,
        "error": result.compile_error or result.error,
        "total": result.total,
        "verified": result.verified,
        "unverified": [{"path": u.path, "status": u.status} for u in result.unverified()],
        "seconds": round(time.time() - started, 3),
    }


def clean_previous(out_dir):
    """Removes folders written by an earlier run, so files the game no longer has don't linger."""
    if not os.path.isfile(os.path.join(out_dir, REPORT_JSON)):
        return
    for name in MANAGED:
        path = os.path.join(out_dir, name)
        if os.path.isdir(path):
            shutil.rmtree(path)


def write_report(out_dir, records, sources):
    records = sorted(records, key=lambda r: r["file"])
    with open(os.path.join(out_dir, REPORT_JSON), "w", encoding="utf-8") as f:
        json.dump({"version": __version__, "sources": sources, "files": records}, f, indent=1)
    total = sum(r["total"] for r in records)
    verified = sum(r["verified"] for r in records)
    files_ok = sum(1 for r in records if r["total"] and r["verified"] == r["total"])
    lines = [
        "Motherlode %s" % __version__,
        "sources: " + ", ".join(sources),
        "files: %d, fully verified: %d" % (len(records), files_ok),
        "code objects: %d, verified: %d (%.2f%%)" % (total, verified, 100.0 * verified / max(total, 1)),
        "",
    ]
    for r in records:
        if r["unverified"] or r["error"]:
            lines.append(r["file"])
            if r["error"]:
                lines.append("    error: " + r["error"])
            for u in r["unverified"]:
                lines.append("    %s  %s" % (u["status"], u["path"]))
    with open(os.path.join(out_dir, REPORT_TEXT), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return files_ok, total, verified


def open_folder(path):
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except OSError:
        pass


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="motherlode",
        description="Decompile The Sims 4's Python 3.7 scripts and prove every function correct by recompiling it. "
                    "With no inputs, decompiles the game installed on this computer.")
    parser.add_argument("inputs", nargs="*", help="a Sims 4 install folder, script archives (.zip or .ts4script), folders of .pyc files, or .pyc files")
    parser.add_argument("-o", "--output", default="decompiled", help="folder for the .py files and report (default: %(default)s)")
    parser.add_argument("-j", "--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 1), help="parallel workers (default: %(default)s)")
    parser.add_argument("--no-search", action="store_true", help="skip retrying ambiguous structures for functions that fail verification")
    parser.add_argument("--list-installs", action="store_true", help="print the Sims 4 installs found on this computer and exit")
    parser.add_argument("--open", action="store_true", help="open the output folder when finished")
    parser.add_argument("--version", action="version", version="%(prog)s " + __version__)
    args = parser.parse_args(argv)

    if args.list_installs:
        installs = detect_installs()
        for path in installs:
            print(path)
        if not installs:
            print("No Sims 4 install found. Pass the game folder as an argument instead.")
        return 0 if installs else 1

    inputs = args.inputs
    if not inputs:
        installs = detect_installs()
        if not installs:
            example = "\"/Applications/EA Games/The Sims 4.app\"" if sys.platform == "darwin" else "\"D:\\Games\\The Sims 4\""
            raise SystemExit("motherlode: couldn't find The Sims 4 on this computer. "
                             "Pass the game's location as an argument, for example: motherlode " + example)
        inputs = installs[:1]
        print("Decompiling the game at " + installs[0])
        for other in installs[1:]:
            print("Also found " + other + " (pass it as an argument to use it instead)")

    out_dir = os.path.abspath(args.output)
    jobs = [(label, archive, member, rel, out_dir, not args.no_search) for label, archive, member, rel in collect(inputs)]
    if not jobs:
        raise SystemExit("motherlode: no .pyc files found")
    os.makedirs(out_dir, exist_ok=True)
    clean_previous(out_dir)
    records = []
    started = time.time()
    tty = sys.stderr.isatty()
    if args.jobs > 1:
        pool = multiprocessing.Pool(args.jobs, maxtasksperchild=200)
        results = pool.imap_unordered(work, jobs, chunksize=4)
    else:
        pool = None
        results = map(work, jobs)
    try:
        for record in results:
            records.append(record)
            if tty:
                sys.stderr.write("\r%d/%d %s" % (len(records), len(jobs), record["file"][-60:].ljust(60)))
                sys.stderr.flush()
            elif len(records) % 250 == 0:
                print("%d/%d files" % (len(records), len(jobs)))
    finally:
        if pool is not None:
            pool.close()
            pool.join()
    if tty:
        sys.stderr.write("\n")
    files_ok, total, verified = write_report(out_dir, records, [os.path.abspath(i) for i in inputs])

    scripts = os.path.join(out_dir, SCRIPTS)
    if os.path.isdir(scripts):
        stubs = write_stubs(out_dir)
        write_project_files(out_dir, bool(stubs))
    print("%d files decompiled in %.0fs; %d fully verified" % (len(records), time.time() - started, files_ok))
    print("%d of %d code objects verified (%.2f%%); details in %s" % (
        verified, total, 100.0 * verified / max(total, 1), os.path.join(out_dir, REPORT_TEXT)))
    if os.path.isdir(scripts):
        print("Game scripts: " + scripts)
        if os.path.isdir(os.path.join(out_dir, STUBS)):
            print("Engine module stubs: " + os.path.join(out_dir, STUBS))
        print("Open %s in PyCharm or VS Code to browse with code completion." % out_dir)
    if args.open:
        open_folder(out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
