"""Fast-forward the Git checkouts listed in a launcher manifest."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys


def github_repo(url):
    match = re.fullmatch(r"(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)"
                         r"([\w.-]+/[\w.-]+?)(?:\.git)?/?", url)
    return match[1].lower() if match else None


def update_checkout(path, upstream, branch):
    """Verify a checkout's identity before fetching or moving its branch."""
    expected = github_repo(upstream)
    if expected is None:
        raise ValueError("expected a GitHub repository URL")

    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}
    env.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes")
    # A launch from a shell that uses another Git worktree must still use -C.
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
        env.pop(key, None)

    def git(*args, check=True, timeout=8):
        return subprocess.run(
            ["git", "-C", str(path), *args], env=env, text=True, errors="replace",
            capture_output=True, check=check, timeout=timeout,
        )

    if not path.is_dir():
        return "skipped (checkout folder not found)"
    root = git("rev-parse", "--show-toplevel", check=False)
    if root.returncode or Path(root.stdout.strip()).resolve() != path.resolve():
        return "skipped (not a standalone Git checkout)"
    origin = git("config", "--get", "remote.origin.url", check=False).stdout.strip()
    if github_repo(origin) != expected:
        return "skipped (origin differs from the update manifest)"
    if git("check-ref-format", "--branch", branch, check=False).returncode:
        raise ValueError("invalid release branch in the update manifest")
    current = git("symbolic-ref", "--quiet", "--short", "HEAD", check=False).stdout.strip()
    if current != branch:
        return f"skipped (checkout is not on {branch})"
    if git("status", "--porcelain", "--untracked-files=no", "--ignore-submodules=none").stdout:
        return "skipped (tracked files have local changes)"

    head = git("rev-parse", "HEAD").stdout.strip()
    git("fetch", "--no-tags", "--no-recurse-submodules", "origin", f"refs/heads/{branch}", timeout=25)
    release = git("rev-parse", "FETCH_HEAD").stdout.strip()
    if head == release:
        return f"up to date ({head[:8]})"
    if git("merge-base", "--is-ancestor", head, release, check=False).returncode:
        return "skipped (local commits or rewritten upstream history)"
    git("merge", "--ff-only", "--no-autostash", "--no-overwrite-ignore", release, timeout=25)
    return f"updated {head[:8]} to {release[:8]}"


def main():
    if len(sys.argv) != 2:
        print("Usage: git_updates.py UPDATE_MANIFEST.json")
        return 2
    if os.environ.get("FORGE_SKIP_UPDATES") == "1":
        print("[updates] Disabled for this launch.")
        return 0
    manifest = Path(sys.argv[1]).resolve()
    try:
        entries = json.loads(manifest.read_text(encoding="utf-8"))
        if not isinstance(entries, list):
            raise ValueError("expected a list of Git checkouts")
    except (OSError, ValueError) as error:
        print(f"[updates] Could not read {manifest.name}: {error}", flush=True)
        return 1

    for entry in entries:
        name = entry.get("name", "Checkout") if isinstance(entry, dict) else "Checkout"
        try:
            path = (manifest.parent / entry["path"]).resolve()
            result = update_checkout(path, entry["origin"], entry["branch"])
        except FileNotFoundError:
            result = "skipped (Git for Windows is not on PATH)"
        except subprocess.TimeoutExpired:
            result = "skipped (Git timed out)"
        except subprocess.CalledProcessError as error:
            result = f"skipped (git {error.cmd[3]} exited with code {error.returncode})"
        except (OSError, KeyError, TypeError, ValueError) as error:
            result = f"skipped ({error})"
        print(f"[updates] {name}: {result}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
