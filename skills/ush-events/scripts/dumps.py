"""List memory dumps and, with --copy, archive them with a verified SHA-256.

Usage (from the project root):

    python -B skills/ush-events/scripts/dumps.py [--data-dir DIR]
    python -B skills/ush-events/scripts/dumps.py --copy [--delete-source] [--data-dir ...]

Without flags the script only prints the inventory as JSON. Reading a dump's
content usually needs an elevated console; the skill hands the user a block
for that and never runs it itself.

``--copy`` copies each readable dump to
``<data-dir>/dumps/<stem>-<modified UTC YYYYmmdd-HHMMSS>-<sha256[:12]><ext>``:

- the copy is written to a temporary file in ``dumps/`` and only a verified
  copy is moved to its name with ``os.rename``, which refuses an existing
  target on Windows; an existing file is never overwritten (same hash:
  ``already_copied``; another hash: ``not_copied``);
- the free space of the target is checked first (free >= size);
- ``verified`` means equal sizes and equal SHA-256 of the source, read again
  after the copy, and of the copy, both computed in this run;
- ``manifest.json`` in ``dumps/`` is an append-only JSON list; an unreadable
  or corrupt manifest stops the run before any copy and is left untouched.

``--delete-source`` (only with ``--copy``) removes a source only after a
verified copy in this run, after the manifest entry naming that copy has been
written, and after a fresh hash of the source right before the removal that
still matches; every failure keeps the source (``source_kept``). After the
removal attempt that same entry (written in this run) is rewritten with the
outcome; entries of earlier runs are never changed.

Every access to the machine goes through the seven injectable functions of
``dumpfiles``; inject all of them (tests) or none (a real run).

Exit codes: 0 everything done; 1 something not copied, not verified or not
deleted, or the inventory or manifest could not be read; 2 bad arguments.
"""

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# load_script does not put this directory on sys.path; dumpfiles lives next to this file.
sys.path.insert(0, str(Path(__file__).absolute().parent))
# The shared data-directory resolution lives in skills/ush-common/scripts.
sys.path.insert(0, str(Path(__file__).absolute().parents[2] / "ush-common" / "scripts"))

import datadir
import dumpfiles
from dumpfiles import describe, iso

MACHINE_FUNCTIONS = ("read_value", "list_dir", "stat", "open_file", "copy", "remove",
                     "disk_usage")
MANIFEST = "manifest.json"
TEMP_PREFIX = ".partial-"


class ManifestError(Exception):
    """The manifest exists but cannot be read as a JSON list."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dumps.py",
        description=(
            "List memory dumps (read-only). With --copy, copy each readable dump "
            "to <data-dir>/dumps/ and verify it by SHA-256."
        ),
    )
    parser.add_argument("--data-dir", default=None, help=datadir.HELP)
    parser.add_argument("--copy", action="store_true",
                        help="copy each readable dump to <data-dir>/dumps/ and verify it")
    parser.add_argument("--delete-source", action="store_true",
                        help="with --copy: remove each original after a verified copy "
                             "(irreversible)")
    return parser


def read_manifest(path: Path) -> list:
    """The manifest list; [] when there is none yet. Anything else raises ManifestError."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return []
    except (OSError, UnicodeDecodeError) as exc:
        raise ManifestError(f"{path} could not be read: {describe(exc)}") from exc
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ManifestError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise ManifestError(f"{path} is not a JSON list")
    return data


def write_manifest(path: Path, entries: list) -> None:
    """Write the whole list through a temporary file, so a crash never leaves half a file.

    The earlier entries are written back unchanged; only new ones are added.
    """
    handle, temp = tempfile.mkstemp(dir=path.parent, prefix=TEMP_PREFIX, suffix=".json")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            json.dump(entries, out, ensure_ascii=True, indent=1)
            out.write("\n")
        os.replace(temp, path)  # the manifest only; dump copies never use os.replace
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


def store_entry(path: Path, new: dict, old: dict | None = None) -> None:
    """Re-read the manifest, then add `new` (or put it in place of this run's `old`) and write.

    Re-reading keeps entries another run wrote since this one started.
    """
    entries = read_manifest(path)
    if old is not None and old in entries:
        entries[len(entries) - 1 - entries[::-1].index(old)] = new
    else:
        entries.append(new)
    write_manifest(path, entries)


def copy_name(entry: dict, source_hash: str) -> str:
    """<stem>-<modified UTC YYYYmmdd-HHMMSS>-<sha256[:12]><ext>, the suffix's case kept."""
    name = Path(entry["name"])
    moment = datetime.fromisoformat(entry["modified"]).astimezone(timezone.utc)
    return f"{name.stem}-{moment:%Y%m%d-%H%M%S}-{source_hash[:12]}{name.suffix}"


def copy_one(entry: dict, dumps_dir: Path, fn: dict, now: datetime) -> dict:
    """Copy and verify one dump; the source is never removed here (see main).

    Returns {"result": ..., "manifest": entry or None}; the manifest entry
    exists only when a copy was made or found.
    """
    source = entry["path"]
    result = {"name": entry["name"], "source": source, "status": "not_copied",
              "reason": None, "copy": None, "sha256": None, "verified": False,
              "source_deleted": False, "source_kept": True}

    def refuse(reason):
        result["reason"] = reason
        return {"result": result, "manifest": None}

    if not entry.get("readable"):
        return refuse(f"not readable: {entry.get('reason') or 'unknown reason'}")
    if entry.get("modified") is None or entry.get("size") is None:
        return refuse("its size or modification time could not be read")
    try:
        source_hash, source_size = dumpfiles.digest(source, fn["open_file"])
    except PermissionError as exc:
        return refuse(f"{dumpfiles.NEEDS_ADMIN} to read it: {describe(exc)}")
    except OSError as exc:
        return refuse(f"the source could not be read: {describe(exc)}")
    target = dumps_dir / copy_name(entry, source_hash)
    result["sha256"] = source_hash

    if target.exists():
        try:
            target_hash, target_size = dumpfiles.digest(target)
        except OSError as exc:
            return refuse(f"{target} exists and could not be read: {describe(exc)}")
        if (target_hash, target_size) != (source_hash, source_size):
            return refuse(f"{target.name} already exists with another SHA-256; it is not "
                          "overwritten")
        result.update(status="already_copied", copy=str(target), verified=True)
    else:
        try:
            free = fn["disk_usage"](str(dumps_dir)).free
        except OSError as exc:
            return refuse(f"the free space of {dumps_dir} could not be read: {describe(exc)}")
        if free < source_size:
            return refuse(f"not enough free space in {dumps_dir}: {free} bytes free, "
                          f"{source_size} needed")
        copied, verified, reason = _copy_verified(source, source_hash, source_size, target,
                                                  dumps_dir, fn)
        if not verified:
            result["reason"] = reason
            # A copy that was made but failed verification is recorded too.
            record = _manifest_entry(result, entry, now) if copied else None
            return {"result": result, "manifest": record}
        result.update(status="copied", copy=str(target), verified=True)

    return {"result": result, "manifest": _manifest_entry(result, entry, now)}


def _copy_verified(source, source_hash, source_size, target: Path, dumps_dir: Path,
                   fn: dict) -> tuple[bool, bool, str | None]:
    """Copy to a temporary file in dumps/, verify, then rename.

    Returns (copied, verified, reason): ``copied`` is True once the copy
    function succeeded, whatever the verification says. An unverified copy is
    discarded, so dumps/ holds only verified copies.
    """
    try:
        handle, temp_name = tempfile.mkstemp(dir=dumps_dir, prefix=TEMP_PREFIX,
                                             suffix=".tmp")
    except OSError as exc:
        return False, False, (f"no temporary file could be made in {dumps_dir}: "
                              f"{describe(exc)}")
    os.close(handle)
    temp = Path(temp_name)
    try:
        try:
            fn["copy"](source, str(temp))
        except OSError as exc:
            return False, False, f"the copy failed: {describe(exc)}"
        try:
            copy_hash, copy_size = dumpfiles.digest(temp)
            again_hash, again_size = dumpfiles.digest(source, fn["open_file"])
        except OSError as exc:
            return True, False, f"the copy could not be verified: {describe(exc)}"
        if not (copy_size == again_size == source_size
                and copy_hash == again_hash == source_hash):
            return True, False, (f"the copy did not match the source (source {again_hash}, "
                           f"{again_size} bytes; copy {copy_hash}, {copy_size} bytes); "
                           "the copy was discarded")
        try:
            os.rename(temp, target)  # refuses an existing target on Windows
        except OSError as exc:
            return True, False, (f"the verified copy could not be named {target.name}: "
                                 f"{describe(exc)}")
        return True, True, None
    finally:
        temp.unlink(missing_ok=True)


def _delete_source(result: dict, fn: dict) -> None:
    """Remove the source only if its fresh hash still matches the verified copy."""
    try:
        fresh, _ = dumpfiles.digest(result["source"], fn["open_file"])
    except OSError as exc:
        result["reason"] = f"source kept: it could not be hashed again: {describe(exc)}"
        return
    if fresh != result["sha256"]:
        result["reason"] = "source kept: it changed after the copy"
        return
    try:
        fn["remove"](result["source"])
    except OSError as exc:
        result["reason"] = f"source kept: it could not be removed: {describe(exc)}"
        return
    result.update(source_deleted=True, source_kept=False)


def _manifest_entry(result: dict, entry: dict, now: datetime) -> dict:
    return {"name": entry["name"], "source": entry["path"], "copy": result["copy"],
            "size": entry["size"], "sha256": result["sha256"], "copied_at": iso(now),
            "verified": result["verified"], "source_deleted": result["source_deleted"],
            "reason": result["reason"]}


def main(argv=None, read_value=None, list_dir=None, stat=None, open_file=None,
         copy=None, remove=None, disk_usage=None, now=None) -> int:
    given = {"read_value": read_value, "list_dir": list_dir, "stat": stat,
             "open_file": open_file, "copy": copy, "remove": remove,
             "disk_usage": disk_usage}
    injected = [name for name, value in given.items() if value is not None]
    if injected and len(injected) != len(MACHINE_FUNCTIONS):
        missing = sorted(set(MACHINE_FUNCTIONS) - set(injected))
        raise TypeError(f"inject all machine functions or none; missing: {', '.join(missing)}")
    if not injected:
        given = {name: getattr(dumpfiles, f"default_{name}") for name in MACHINE_FUNCTIONS}

    parser = build_parser()
    args = parser.parse_args(argv)
    if args.delete_source and not args.copy:
        parser.error("--delete-source needs --copy")
    try:
        data_dir = datadir.resolve(args.data_dir)
    except datadir.DataDirError as exc:
        parser.error(str(exc))
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    dumps_dir = data_dir / "dumps"
    manifest_path = dumps_dir / MANIFEST

    inventory = dumpfiles.read_all(given["read_value"], given["list_dir"], given["stat"],
                                   given["open_file"])
    output = {"generated_at": iso(now), "inventory": inventory}
    if not args.copy:
        print(json.dumps(output, ensure_ascii=True, indent=1))
        return 1 if inventory["status"] == "unreadable" else 0

    output.update(dumps_dir=str(dumps_dir), manifest=str(manifest_path), results=[])
    try:
        read_manifest(manifest_path)  # a corrupt manifest stops the run before any copy
    except ManifestError as exc:
        output["error"] = f"{exc}; nothing was copied and the manifest was not changed"
        print(json.dumps(output, ensure_ascii=True, indent=1))
        return 1
    try:
        dumps_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        output["error"] = f"{dumps_dir} could not be created: {describe(exc)}"
        print(json.dumps(output, ensure_ascii=True, indent=1))
        return 1

    ok = inventory["status"] != "unreadable"
    for entry in inventory["files"]:
        done = copy_one(entry, dumps_dir, given, now)
        result = done["result"]
        output["results"].append(result)
        if done["manifest"] is not None:
            # The entry naming the verified copy is on disk before any removal.
            try:
                store_entry(manifest_path, done["manifest"])
            except (OSError, ManifestError) as exc:
                if args.delete_source and result["verified"]:
                    result["reason"] = ("source kept: the manifest entry naming its copy "
                                        "could not be written")
                output["error"] = f"{manifest_path} could not be written: {describe(exc)}"
                print(json.dumps(output, ensure_ascii=True, indent=1))
                return 1
            if args.delete_source and result["verified"]:
                _delete_source(result, given)
                # Rewrite only this run's own entry; every other entry stays unchanged.
                try:
                    store_entry(manifest_path, _manifest_entry(result, entry, now),
                                old=done["manifest"])
                except (OSError, ManifestError) as exc:
                    done_text = ("the source was deleted, but " if result["source_deleted"]
                                 else "")
                    output["error"] = (
                        f"{done_text}{manifest_path} could not be updated after the "
                        f"removal step: {describe(exc)}; its entry for {entry['name']} "
                        f"names the verified copy {result['copy']} and still says "
                        "source_deleted false")
                    print(json.dumps(output, ensure_ascii=True, indent=1))
                    return 1
        if not result["verified"] or (args.delete_source and not result["source_deleted"]):
            ok = False
    print(json.dumps(output, ensure_ascii=True, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
