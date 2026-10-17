# AGENTS.md — PinSaver

PinSaver is a personal Pinterest archive: a FastAPI + SQLite server that serves a vanilla-JS web UI
(masonry gallery, carousel, delete) plus a Chrome MV3 extension that saves pins from Pinterest,
marks already-archived pins in favorites and pushes the archive back to Pinterest.

## Layout

| Path | What is there |
| --- | --- |
| `src/` | FastAPI server and hand-run scripts (`server.py`, `models.py`, `importer.py`, `updateDelete.py`, `backup.py`, `buildinfo.py`) |
| `src/static/` | web UI served as-is, no build step (HTML/CSS/JS, PWA manifest, service worker) |
| `extension/` | Chrome MV3 extension (content script, service worker, options page, icons) |
| `tools/` | scripts run by hand whose output is committed (`make_extension_icons.py`, `bump_version.py`) |
| `originals/`, `pinterest_archive.db`, `backups/` | data — never committed |

## Commands

```bash
python -m pip install -r src/requirements.txt -r src/requirements-tools.txt   # server + host tools
python -m pip install -r src/requirements-dev.txt                             # pytest
python src/models.py                            # create the database and originals/
python src/server.py                            # site on HOST:PORT from .env (default 0.0.0.0:8000)
python src/backup.py                            # incremental backup into backups/
python src/updateDelete.py                      # mark pins deleted from Pinterest (needs chromium)
python src/importer.py                          # rebuild the database from a Pinterest HTML export
python src/migrate_duplicates.py                # merge duplicates by file_id
python tools/bump_version.py X.Y.Z              # bump the version everywhere
python tools/bump_version.py --check            # verify every copy of the version matches
python tools/make_extension_icons.py            # regenerate extension PNGs from extension/icon.svg
python -m pytest -q                             # the offline test suite
```

`requirements.txt` is the runtime (the container installs exactly that); `requirements-tools.txt` adds
what only the host scripts and `tools/` need, so the image never pulls Playwright.

Tests are offline — no Docker, no network, no real archive: `PINSAVER_DATA_DIR` points every path at a
temporary directory. There is no CI, so also run `node --check` on the JS files you touch.

## Versioning

- The single source of truth is `__version__` in `src/buildinfo.py`. Never edit the version anywhere
  else: `tools/bump_version.py X.Y.Z` writes it into `src/buildinfo.py` and `extension/manifest.json`
  and `--check` fails when the two drift apart.
- Bump the **minor** version for a release (`1.1.0` → `1.2.0`), tag that commit
  (`git tag -a v1.2.0 -m "PinSaver 1.2.0"`) and push tags with the branch:
  `git push --follow-tags origin master`. Run `git config push.followTags true` once per clone.
- `src/buildinfo.py` resolves version, commit, commit date, dirty state and repository URLs, with
  `PINSAVER_COMMIT`, `PINSAVER_COMMIT_DATE` and `PINSAVER_REPO_URL` as environment overrides and a
  `.git`-reading fallback for checkouts without git.
- `GET /api/version` exposes that dict; the site header (`app.js`) and the extension options page
  (`options.js`) render it as `vX.Y.Z` (release tag link) and short commit (commit link), with `*`
  when the working copy has uncommitted changes. The extension takes its version from the manifest and
  the commit from the server, so the badge is never stale.
- The extension icons are generated from `extension/icon.svg` by `tools/make_extension_icons.py`
  (Chrome does not accept SVG icons); never edit the PNGs by hand.

## Conventions

- Python 3.10+; modules in `src/` are not a package and import each other by bare name
  (`from models import ...`), so scripts are started as `python src/<script>.py`.
- Frontend is vanilla JS/CSS/HTML with no bundler and no npm; `src/static/` is served as-is and CSS/JS
  URLs are cache-busted with `?v=<version>` by the `/` route in `server.py`.
- New API routes go into `src/server.py` with a docstring, and the README API table gets a row.
- The extension talks to the server only through `background.js` (`API_REQUEST` messages) to bypass
  Chrome Private Network Access; `server.py` answers Pinterest origins with CORS/PNA headers.
- README is Russian; code, comments and docstrings are English.

## Data safety

- The working copy **is** production: never run `git reset`, `git clean`, `git stash` or
  `git checkout` here unless the user explicitly asks.
- Never commit `pinterest_archive.db`, `originals/`, `backups/`, `testPages/` or `.env`.
- `pinterest_archive.db` is a live SQLite file next to the running server: don't rewrite or delete it
  from scripts, and run `python src/backup.py` before risky operations.
- The server has no authentication and binds `0.0.0.0` by default — keep it on a trusted network and
  never expose it to the internet.
