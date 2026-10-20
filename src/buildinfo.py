"""
Version and build metadata of the running PinSaver checkout.

The version below is the single source of truth for the whole project: the web
UI header and the extension options page show it together with the commit the
running code comes from. `tools/bump_version.py` copies it into the extension
manifest, so bump it here and nowhere else.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

__version__ = "2.6.0"

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPO_URL = "https://github.com/northis/PinSaver"
SHORT_COMMIT_LEN = 7


def normalize_repo_url(url: str) -> str:
    """
    Turn any git remote form into a browsable https URL.

    Args:
        url: Remote URL from `git remote get-url origin` or from the environment.

    Returns:
        URL without the `.git` suffix and the trailing slash.
    """
    url = (url or "").strip()
    if not url:
        return DEFAULT_REPO_URL

    # git@github.com:owner/repo.git and ssh://git@github.com/owner/repo.git
    match = re.match(r"^(?:ssh://)?git@([^:/]+)[:/](.+)$", url)
    if match:
        url = f"https://{match.group(1)}/{match.group(2)}"
    elif url.startswith("git://"):
        url = "https://" + url[len("git://"):]
    elif url.startswith("ssh://"):
        url = "https://" + url[len("ssh://"):].split("@")[-1]

    if url.endswith(".git"):
        url = url[: -len(".git")]

    return url.rstrip("/")


def git(*args: str) -> str | None:
    """
    Run a git command inside the repository.

    Args:
        args: Arguments passed to git.

    Returns:
        Stripped stdout, or None when git is missing or the command fails.
    """
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    if result.returncode != 0:
        return None

    return result.stdout.strip()


def head_commit(git_dir: Path | None = None) -> str | None:
    """
    Read HEAD straight from `.git`, without running git.

    Used as a fallback for copies of the repository that have no git binary
    (for example a trimmed checkout), so the commit is still known.

    Args:
        git_dir: Directory of the git repository, `.git` by default.

    Returns:
        Full commit hash, or None when it cannot be resolved.
    """
    git_dir = git_dir or REPO_ROOT / ".git"

    try:
        head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return None

    if not head.startswith("ref: "):
        return head or None

    ref = head[len("ref: "):].strip()

    # A worktree points at the real git dir instead of holding its own refs.
    try:
        pointer = (git_dir / "gitdir").read_text(encoding="utf-8").strip()
    except OSError:
        pointer = None
    if pointer:
        nested = head_commit(Path(pointer))
        if nested:
            return nested

    try:
        return (git_dir / ref).read_text(encoding="utf-8").strip() or None
    except OSError:
        pass

    try:
        for line in (git_dir / "packed-refs").read_text(encoding="utf-8").splitlines():
            if line.startswith("#") or not line.strip():
                continue
            sha, _, name = line.partition(" ")
            if name.strip() == ref:
                return sha.strip()
    except OSError:
        pass

    return None


def build_info() -> dict:
    """
    Collect version, commit and repository links for the running checkout.

    Resolved on every call, so the site header reflects the checkout as it is
    right now (a long-running server picks up a fresh `git pull`).

    Returns:
        Dictionary with version, commit, short, commit_url, commit_date,
        dirty, repo_url, tag and tag_url.
    """
    commit = os.getenv("PINSAVER_COMMIT") or git("rev-parse", "HEAD") or head_commit()

    commit_date = os.getenv("PINSAVER_COMMIT_DATE") or None
    if commit and not commit_date:
        commit_date = git("show", "-s", "--format=%cI", commit)

    repo_url = normalize_repo_url(
        os.getenv("PINSAVER_REPO_URL") or git("remote", "get-url", "origin") or DEFAULT_REPO_URL
    )

    dirty = False
    if commit:
        dirty = bool(git("status", "--porcelain"))

    tag = f"v{__version__}"

    return {
        "version": __version__,
        "commit": commit,
        "short": commit[:SHORT_COMMIT_LEN] if commit else None,
        "commit_url": f"{repo_url}/commit/{commit}" if commit else None,
        "commit_date": commit_date,
        "dirty": dirty,
        "repo_url": repo_url,
        "tag": tag,
        "tag_url": f"{repo_url}/releases/tag/{tag}",
    }


if __name__ == "__main__":
    import json

    print(json.dumps(build_info(), indent=2))
