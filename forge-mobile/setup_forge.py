"""Install the Forge Neo extensions bundled with Forge Mobile."""

import argparse
from pathlib import Path
import shutil
import sys

BUNDLE = Path(__file__).resolve().parent / "forge-neo-extensions"
EXTENSIONS = (
    (
        "img2img-hires-fix",
        "scripts/img2img_hires_fix_v2.py",
        b"img2img_hires_fix_extension",
        ("img2img_hires_fix_core.py", "javascript/img2img_hires_fix.js", "style.css"),
    ),
    (
        "forge-mobile-input-metadata",
        "scripts/input_archive.py",
        b"_fm_input_archive",
        (),
    ),
)


def read_source(path):
    return path.read_bytes().replace(b"\r\n", b"\n")


def setup(forge_root, *, check=False):
    root = forge_root.resolve()
    extension_root = root / "extensions"
    if not ((root / "webui.py").is_file() and (root / "modules_forge").is_dir()
            and extension_root.is_dir()):
        raise ValueError(f"Choose the Forge Neo folder containing webui.py, modules_forge, and extensions: {root}")

    installed = sorted(p for p in extension_root.iterdir() if p.is_dir() and not p.name.startswith("."))
    builtin = root / "extensions-builtin"
    if builtin.is_dir():
        installed.extend(sorted(p for p in builtin.iterdir() if p.is_dir() and not p.name.startswith(".")))

    missing = []
    for name, entrypoint, signature, support_files in EXTENSIONS:
        source = BUNDLE / name
        runtime_files = (entrypoint, *support_files)
        expected = {file: read_source(source / file) for file in runtime_files}
        target = extension_root / name
        candidates = []
        for folder in installed:
            script = folder / entrypoint
            if folder == target or (script.is_file() and signature in read_source(script)):
                candidates.append(folder)
        if candidates:
            if len(candidates) > 1:
                raise ValueError(f"Multiple copies of {name}: {', '.join(map(str, candidates))}")
            current = candidates[0]
            if all((current / file).is_file() and read_source(current / file) == data
                   for file, data in expected.items()):
                print(f"Already installed: {current}")
                continue
            raise ValueError(f"{current} differs from the bundled {name}. Move it outside extensions to keep a backup, then rerun setup.")
        if target.exists() or target.is_symlink():
            raise ValueError(f"Destination already exists: {target}")
        missing.append((source, target))

    if check:
        for _, target in missing:
            print(f"Missing: {target}")
        return 1 if missing else 0

    created = []
    try:
        for source, target in missing:
            target.mkdir()
            created.append(target)
            shutil.copytree(source, target, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    except OSError:
        for target in reversed(created):
            shutil.rmtree(target, ignore_errors=True)
        raise

    for target in created:
        print(f"Installed: {target}")
    if created:
        print("Start Forge Neo, then start or restart Forge Mobile.")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("forge_root", nargs="?", type=Path, help="Path to the Forge Neo installation")
    parser.add_argument("--check", action="store_true", help="Check the bundle without installing files")
    args = parser.parse_args()
    root = args.forge_root
    try:
        if root is None:
            print("Choose the Forge Neo installation folder. Stop Forge first if installing.")
            value = input("Forge Neo folder: ").strip().strip('"')
            if not value:
                raise ValueError("A Forge Neo folder is required.")
            root = Path(value)
        return setup(root, check=args.check)
    except (EOFError, OSError, ValueError) as error:
        print(f"Forge Mobile setup: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
