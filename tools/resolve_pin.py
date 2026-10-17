"""
Resolve a Pinterest link the way the server does, and print what came back.

Handy for checking the resolver against the live site without a phone, and for refreshing the
committed test fixture when Pinterest changes its markup:

    python tools/resolve_pin.py https://pin.it/abc123
    python tools/resolve_pin.py https://www.pinterest.com/pin/1234567890/ --save-fixture
    python tools/resolve_pin.py https://www.pinterest.com/pin/1234567890/ --dump-html page.html

Writes nothing to the database.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pinterest import (  # noqa: E402
    PIN_URL_TEMPLATE,
    PinLookupError,
    extract_pin_id,
    fetch_pin_page,
    fixture_page,
    parse_pin_page,
)

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "pin_page.html"


def main() -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument(
        "link", help="pin link: a full URL or a pin.it short link, on its own or inside text"
    )
    parser.add_argument(
        "--save-fixture",
        action="store_true",
        help=f"rewrite {FIXTURE_PATH.name} from this pin (a few kilobytes, commit it)",
    )
    parser.add_argument("--dump-html", metavar="FILE", help="write the raw page for inspection")
    args = parser.parse_args()

    try:
        pin_id = extract_pin_id(args.link)
    except PinLookupError as error:
        print(f"not a pin link: {error.detail or error.reason}")
        return 2

    print(f"pin id: {pin_id}")

    try:
        html = fetch_pin_page(pin_id)
        pin = parse_pin_page(pin_id, html)
    except PinLookupError as error:
        print(f"failed: {error.reason} ({error.detail})")
        return 1

    print(f"file id: {pin.file_id}")
    print(f"image  : {pin.image_url}")
    print(f"ext    : {pin.extension}")
    print(f"video  : {pin.is_video}")

    if args.dump_html:
        Path(args.dump_html).write_text(html, encoding="utf-8")
        print(f"raw page written to {args.dump_html}")

    if args.save_fixture:
        FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
        header = (
            f"<!-- Trimmed from a live pin page ({date.today().isoformat()}, pin {pin_id}): only what\n"
            "     the resolver reads, attribute order included. Refresh with:\n"
            f"       python tools/resolve_pin.py {PIN_URL_TEMPLATE.format(pin_id=pin_id)} --save-fixture -->\n"
        )
        FIXTURE_PATH.write_text(header + fixture_page(html, pin), encoding="utf-8")
        print(f"fixture written to {FIXTURE_PATH}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
