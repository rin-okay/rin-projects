"""Manage selected rin-projects extensions and launch an existing Forge Neo install."""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
from tempfile import NamedTemporaryFile

from git_updates import github_repo

HERE = Path(__file__).resolve().parent
STATE_NAME = ".rin-projects-extensions.json"
SOURCE_SUFFIXES = {".css", ".html", ".ini", ".js", ".json", ".md", ".py", ".txt"}
USER_CONTENT = {"state", "debug.json", "tests", "__pycache__"}


def git(*args):
    return subprocess.run(
        ["git", "-C", str(HERE.parent), *args], capture_output=True, check=True,
    ).stdout


def checkout_revision():
    top = Path(os.fsdecode(git("rev-parse", "--show-toplevel").rstrip(b"\r\n"))).resolve()
    origin = git("config", "--get", "remote.origin.url").decode("utf-8").strip()
    if top != HERE.parent or github_repo(origin) != "rin-okay/rin-projects":
        raise ValueError("Start the extension updater from a rin-okay/rin-projects Git checkout.")
    return git("rev-parse", "HEAD").decode("ascii").strip()


def safe_path(root, relative):
    path = PurePosixPath(relative)
    if not path.parts or path.is_absolute() or ".." in path.parts or ":" in relative or "\\" in relative:
        raise ValueError(f"Invalid extension path: {relative}")
    target = root.joinpath(*path.parts)
    if target.is_symlink() or not target.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Extension path points outside its folder: {target}")
    return target


def source_files(revision, spec):
    prefix = spec["source"] + "/"
    listing = git("ls-tree", "-rz", revision, "--", prefix)
    explicit = spec.get("files")
    files = {}
    for row in listing.split(b"\0"):
        if not row:
            continue
        info, path = row.split(b"\t", 1)
        mode, kind, blob = info.decode("ascii").split()
        relative = path.decode("utf-8").removeprefix(prefix)
        parts = PurePosixPath(relative)
        if kind != "blob" or mode not in {"100644", "100755"}:
            continue
        if explicit is not None and relative not in explicit:
            continue
        if parts.suffix not in SOURCE_SUFFIXES or USER_CONTENT.intersection(parts.parts):
            continue
        files[relative] = git("cat-file", "blob", blob)
    if not files or (explicit is not None and set(files) != set(explicit)):
        raise ValueError(f"Source files are missing in Git: {prefix}")
    return files


def digest(data):
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def write_atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, prefix=".rin-", delete=False) as handle:
        staged = Path(handle.name)
        try:
            handle.write(data)
        except OSError:
            handle.close()
            staged.unlink(missing_ok=True)
            raise
    try:
        staged.replace(path)
    finally:
        staged.unlink(missing_ok=True)


def deploy(target, files, previous):
    expected = {name: digest(data) for name, data in files.items()}
    changes = []
    for name in sorted(set(expected) | set(previous)):
        path = safe_path(target, name)
        current = path.read_bytes() if path.exists() else None
        old_hash = digest(current) if current is not None else None
        if old_hash == expected.get(name):
            continue
        if current is not None and old_hash != previous.get(name):
            raise ValueError(f"Local file differs: {path}")
        changes.append((path, current, files.get(name)))

    applied = []
    try:
        for path, current, replacement in changes:
            if replacement is None:
                path.unlink()
            else:
                write_atomic(path, replacement)
            applied.append((path, current))
    except OSError:
        for path, current in reversed(applied):
            if current is None:
                path.unlink(missing_ok=True)
            else:
                write_atomic(path, current)
        raise
    return expected, len(changes)


def find_target(root, name, spec):
    for conflict in spec.get("conflicts", ()):
        if (root / conflict).exists():
            raise ValueError(f"Overlaps with installed extension: {root / conflict}")
    dest = spec.get("target", name)
    candidates = [safe_path(root, folder) for folder in (dest, *spec.get("aliases", ()))]
    existing = [path for path in candidates if path.exists()]
    if len(existing) > 1:
        raise ValueError(f"Multiple installed copies: {', '.join(map(str, existing))}")
    target = existing[0] if existing else candidates[0]
    prerequisite = spec.get("requires")
    if prerequisite and not safe_path(target, prerequisite).is_file():
        raise ValueError(f"Install the upstream extension first: {target}")
    return target


def sync(root, catalog, state, selected, revision):
    failed = False
    for name in selected:
        try:
            spec = catalog[name]
            target = find_target(root / "extensions", name, spec)
            record = state.get(name, {})
            previous = record.get("files", {}) if record.get("target") == target.name else {}
            files, edits = deploy(target, source_files(revision, spec), previous)
            updated = {"enabled": True, "target": target.name, "files": files}
            if updated != record:
                state[name] = updated
                write_atomic(root / STATE_NAME, (json.dumps(state, indent=2) + "\n").encode())
            status = "updated" if edits else "current"
            print(f"{name}: {status} ({target.name})", flush=True)
        except (KeyError, ValueError, OSError, subprocess.CalledProcessError) as error:
            failed = True
            print(f"{name}: skipped. {error}", file=sys.stderr, flush=True)
    return 1 if failed else 0


def launch(root):
    launcher = root / "webui-user.bat"
    if not launcher.is_file():
        raise ValueError(f"Forge launcher is missing: {launcher}")
    if os.name != "nt":
        raise ValueError("Use the Windows launcher to start Forge. The sync command is portable.")
    subprocess.run([sys.executable, str(HERE / "git_updates.py"), str(HERE / "launch-updates.json")], cwd=HERE)
    result = subprocess.run([sys.executable, str(Path(__file__).resolve()), str(root), "sync"], cwd=HERE)
    if result.returncode:
        print("Starting Forge with the installed extension files.", flush=True)
    return subprocess.call([os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", launcher.name], cwd=root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("forge_root", nargs="?", type=Path)
    parser.add_argument("action", choices=("launch", "list", "enable", "disable", "sync"), nargs="?", default="launch")
    parser.add_argument("packages", nargs="*")
    args = parser.parse_args()
    try:
        root = args.forge_root
        if root is None:
            root = next((p for p in (Path.cwd(), *HERE.parents) if (p / "webui.py").is_file()), None)
            if root is None:
                value = input("Forge Neo folder: ").strip().strip('"')
                if not value:
                    raise ValueError("A Forge Neo folder is required.")
                root = Path(value)
        root = root.resolve()
        if not ((root / "webui.py").is_file() and (root / "modules_forge").is_dir()
                and (root / "extensions").is_dir()):
            raise ValueError(f"Choose the Forge Neo folder containing webui.py, modules_forge, and extensions: {root}")
        if args.action == "launch":
            return launch(root)
        catalog = json.loads((HERE / "forge-extensions.json").read_text(encoding="utf-8"))
        path = root / STATE_NAME
        if path.is_symlink():
            raise ValueError(f"Extension selection must be a local file: {path}")
        state = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        if not isinstance(state, dict):
            raise ValueError(f"Invalid extension selection: {path}")
        if args.action == "list":
            for name in catalog:
                print(f"{name}: {'enabled' if state.get(name, {}).get('enabled') else 'available'}")
            return 0
        if args.action in {"enable", "disable"}:
            if not args.packages:
                raise ValueError(f"Name the extensions to {args.action}. Use list to display the available IDs.")
            invalid = set(args.packages) - set(catalog)
            if invalid:
                raise ValueError(f"Unknown extensions: {', '.join(sorted(invalid))}")
        if args.action == "disable":
            for name in args.packages:
                if name in state:
                    state[name]["enabled"] = False
            write_atomic(path, (json.dumps(state, indent=2) + "\n").encode())
            return 0
        selected = args.packages if args.action == "enable" else [
            name for name, record in state.items() if record.get("enabled")
        ]
        if not selected:
            return 0
        revision = checkout_revision()
        return sync(root, catalog, state, dict.fromkeys(selected), revision)
    except (EOFError, KeyError, TypeError, ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"Forge extension updates: {error}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
