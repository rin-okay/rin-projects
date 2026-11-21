"""Check for updates, install changed dependencies, and run Forge Mobile."""

import hashlib
import importlib.util
from pathlib import Path
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parent
    python = sys.executable
    # A failed update leaves the launch path available for the installed version.
    subprocess.run([python, "git_updates.py", "launch-updates.json"], cwd=root, check=False)

    requirements = root / "requirements.txt"
    stamp = root / ".venv" / "forge-mobile-requirements.sha256"
    digest = hashlib.sha256(requirements.read_bytes()).hexdigest()
    installed = stamp.read_text(encoding="ascii").strip() if stamp.is_file() else None
    if digest != installed or importlib.util.find_spec("aiohttp") is None:
        result = subprocess.run([python, "-m", "pip", "install", "-r", str(requirements)], cwd=root)
        if result.returncode:
            print("Forge Mobile could not install its Python dependencies.", flush=True)
            return result.returncode
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text(digest + "\n", encoding="ascii")

    return subprocess.call([python, "companion.py", *sys.argv[1:]], cwd=root)


if __name__ == "__main__":
    raise SystemExit(main())
