"""Command line interface: decompile a Sims 4 install, script archives, folders, or single .pyc files."""

import argparse
import json
import multiprocessing
import os
import sys
import time
import zipfile

from . import __version__
from .api import decompile_pyc_bytes
from .game import find_archives, looks_like_install


def collect(inputs):
    """Yields (label, archive_or_none, member_or_path, output_relpath) for every .pyc to decompile."""
    for item in inputs:
        if looks_like_install(item):
            for archive in find_archives(item):
                yield from collect_zip(archive)
        elif os.path.isfile(item) and item.lower().endswith(".zip"):
            yield from collect_zip(item)
        elif os.path.isdir(item):
            for root, _, files in os.walk(item):
                for name in sorted(files):
                    if name.endswith(".pyc"):
                        path = os.path.join(root, name)
                        rel = os.path.relpath(path, item)
                        yield (path, None, path, rel[:-4] + ".py")
        elif os.path.isfile(item) and item.endswith(".pyc"):
            yield (item, None, item, os.path.basename(item)[:-4] + ".py")
        else:
            raise SystemExit("motherlode: not a Sims 4 install, .zip, folder, or .pyc file: " + item)


def collect_zip(archive):
    prefix = os.path.splitext(os.path.basename(archive))[0]
    with zipfile.ZipFile(archive) as z:
        for name in sorted(z.namelist()):
            if name.endswith(".pyc"):
                yield (archive + ":" + name, archive, name, os.path.join(prefix, name[:-4] + ".py"))


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
    target = os.path.join(out_dir, rel)
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


def write_report(out_dir, records):
    records = sorted(records, key=lambda r: r["file"])
    with open(os.path.join(out_dir, "motherlode-report.json"), "w", encoding="utf-8") as f:
        json.dump({"version": __version__, "files": records}, f, indent=1)
    total = sum(r["total"] for r in records)
    verified = sum(r["verified"] for r in records)
    files_ok = sum(1 for r in records if r["total"] and r["verified"] == r["total"])
    lines = [
        "Motherlode %s" % __version__,
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
    with open(os.path.join(out_dir, "motherlode-report.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return files_ok, total, verified


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="motherlode",
        description="Decompile The Sims 4's Python 3.7 scripts and prove every function correct by recompiling it.")
    parser.add_argument("inputs", nargs="+", help="a Sims 4 install folder, script .zip archives, folders of .pyc files, or .pyc files")
    parser.add_argument("-o", "--output", default="decompiled", help="folder for the .py files and report (default: %(default)s)")
    parser.add_argument("-j", "--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 1), help="parallel workers (default: %(default)s)")
    parser.add_argument("--no-search", action="store_true", help="skip retrying ambiguous structures for functions that fail verification")
    parser.add_argument("--version", action="version", version="%(prog)s " + __version__)
    args = parser.parse_args(argv)

    jobs = [(label, archive, member, rel, args.output, not args.no_search) for label, archive, member, rel in collect(args.inputs)]
    if not jobs:
        raise SystemExit("motherlode: no .pyc files found")
    os.makedirs(args.output, exist_ok=True)
    records = []
    done = 0
    started = time.time()
    if args.jobs > 1:
        pool = multiprocessing.Pool(args.jobs, maxtasksperchild=200)
        results = pool.imap_unordered(work, jobs, chunksize=4)
    else:
        pool = None
        results = map(work, jobs)
    try:
        for record in results:
            records.append(record)
            done += 1
            if sys.stderr.isatty():
                sys.stderr.write("\r%d/%d %s" % (done, len(jobs), record["file"][-60:].ljust(60)))
                sys.stderr.flush()
    finally:
        if pool is not None:
            pool.close()
            pool.join()
    if sys.stderr.isatty():
        sys.stderr.write("\n")
    files_ok, total, verified = write_report(args.output, records)
    print("%d files decompiled in %.0fs; %d fully verified" % (len(records), time.time() - started, files_ok))
    print("%d of %d code objects verified (%.2f%%); see %s" % (
        verified, total, 100.0 * verified / max(total, 1), os.path.join(args.output, "motherlode-report.txt")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
