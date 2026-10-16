"""
Bump the project version, or check that every copy of it is in sync.

The version lives in `src/buildinfo.py` and is mirrored into
`extension/manifest.json`. Run this script by hand and commit the result:

    python tools/bump_version.py 1.2.0   # bump both files
    python tools/bump_version.py --check # verify they match, exit 1 if not
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILDINFO_PATH = ROOT / "src" / "buildinfo.py"
MANIFEST_PATH = ROOT / "extension" / "manifest.json"

VERSION_PATTERN = re.compile(r'__version__\s*=\s*"([^"]+)"')
MANIFEST_VERSION_PATTERN = re.compile(r'("version"\s*:\s*")([^"]+)(")')


def read_buildinfo_version() -> str:
    """Return `__version__` from src/buildinfo.py."""
    match = VERSION_PATTERN.search(BUILDINFO_PATH.read_text(encoding="utf-8"))
    if not match:
        raise SystemExit(f"no __version__ found in {BUILDINFO_PATH}")
    return match.group(1)


def read_manifest_version() -> str:
    """Return the version from extension/manifest.json."""
    match = MANIFEST_VERSION_PATTERN.search(MANIFEST_PATH.read_text(encoding="utf-8"))
    if not match:
        raise SystemExit(f'no "version" found in {MANIFEST_PATH}')
    return match.group(2)


def write_manifest_version(version: str) -> None:
    """Replace the version in extension/manifest.json, keeping the formatting."""
    text = MANIFEST_PATH.read_text(encoding="utf-8")
    updated, count = MANIFEST_VERSION_PATTERN.subn(rf"\g<1>{version}\g<3>", text, count=1)
    if count != 1:
        raise SystemExit(f'could not update "version" in {MANIFEST_PATH}')
    MANIFEST_PATH.write_text(updated, encoding="utf-8")


def write_buildinfo_version(version: str) -> None:
    """Replace `__version__` in src/buildinfo.py."""
    text = BUILDINFO_PATH.read_text(encoding="utf-8")
    updated, count = VERSION_PATTERN.subn(f'__version__ = "{version}"', text, count=1)
    if count != 1:
        raise SystemExit(f"could not update __version__ in {BUILDINFO_PATH}")
    BUILDINFO_PATH.write_text(updated, encoding="utf-8")


def main() -> None:
    """Entry point."""
    if len(sys.argv) == 2 and sys.argv[1] == "--check":
        buildinfo_version = read_buildinfo_version()
        manifest_version = read_manifest_version()
        if buildinfo_version != manifest_version:
            raise SystemExit(
                f"version mismatch: src/buildinfo.py has {buildinfo_version}, "
                f"extension/manifest.json has {manifest_version}. "
                f"Run: python tools/bump_version.py {buildinfo_version}"
            )
        print(f"versions in sync: {buildinfo_version}")
        return

    if len(sys.argv) != 2 or not re.fullmatch(r"\d+\.\d+\.\d+", sys.argv[1]):
        raise SystemExit(__doc__.strip().splitlines()[-2].strip())

    version = sys.argv[1]
    write_buildinfo_version(version)
    write_manifest_version(version)
    print(f"version set to {version}:")
    print(f"  src/buildinfo.py")
    print(f"  extension/manifest.json")
    print("now commit and tag it: git tag -a v" + version + ' -m "PinSaver ' + version + '"')


if __name__ == "__main__":
    main()
