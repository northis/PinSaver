# AGENTS.md — PinSaver

PinSaver is a personal Pinterest archive: a FastAPI + SQLite server that serves a vanilla-JS web UI
(masonry gallery, carousel, delete) plus a Chrome MV3 extension that saves pins from Pinterest,
marks already-archived pins in favorites and pushes the archive back to Pinterest.

## Layout

| Path | What is there |
| --- | --- |
| `src/` | FastAPI server and hand-run scripts (`server.py`, `models.py`, `archive.py`, `images.py`, `pinterest.py`, `importer.py`, `updateDelete.py`, `backup.py`, `convert_heic.py`, `buildinfo.py`) |
| `src/static/` | web UI served as-is, no build step (HTML/CSS/JS, PWA manifest, icons, service worker, maintenance page `admin.*`) |
| `extension/` | Chrome MV3 extension (content script, service worker, options page, icons) |
| `tools/` | scripts run by hand whose output is committed (`make_extension_icons.py`, `make_pwa_icons.py`, `bump_version.py`) |
| `tests/` | offline pytest suite (`PINSAVER_DATA_DIR` points it at a temporary directory) |
| `Dockerfile`, `docker-compose.yml` | the image (runtime only) and how it runs: the archive is bind-mounted |
| `deploy/` | host-side update script (`windows/update.ps1`) and the sitehub fragment (`sitehub/pinsaver.yml`) |
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
python src/convert_heic.py                      # convert stored HEIC originals to JPEG
python tools/bump_version.py X.Y.Z              # bump the version everywhere
python tools/bump_version.py --check            # verify every copy of the version matches
python tools/make_extension_icons.py            # regenerate extension PNGs from extension/icon.svg
python tools/make_pwa_icons.py                  # regenerate the PWA icons from the header emoji
python -m pytest -q                             # the offline test suite
docker compose up -d --build                    # build and run the site in a container
docker compose ps                               # healthy means the healthcheck passed
powershell -ExecutionPolicy Bypass -File deploy\windows\update.ps1   # host-side update with rollback
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
- The PWA icons in `src/static/icons/` and `src/static/favicon.svg` are the header emoji (📌),
  rendered by `tools/make_pwa_icons.py`; never edit those PNGs by hand either. The manifest is an
  explicit route at the root (`/manifest.webmanifest`, served as `application/manifest+json`),
  because `.webmanifest` is missing from some mimetype tables, and `/favicon.ico` redirects to
  `/static/favicon.svg`.

## Deployment

- The site runs in a container **on the owner's PC**, next to the archive; sitehub (Traefik on the
  Ubuntu host) reaches it over the SoftEther VPN at `${PINSAVER_BIND_ADDR}` (default `10.77.77.21`),
  and Cloudflare Access is the only gate in front of it. Nothing inside the app authenticates.
- The maintenance page is a **second listener of the same process** (`PINSAVER_ADMIN_HOST` /
  `PINSAVER_ADMIN_PORT`, default `127.0.0.1:8001`; `0` disables it, and it must differ from `PORT`).
  It reads the database and hands out the whole archive, so every admin route takes
  `Depends(require_local)`: the guard compares the port of the socket that accepted the request
  (`scope["server"]`) — never a header — and answers 404 everywhere else. It is published on local
  addresses only (`PINSAVER_ADMIN_BIND_ADDR`, default `127.0.0.1`), never on the site's VPN address.
- **Exactly three paths are public** — `/manifest.webmanifest`, `/static/favicon.svg` and
  `/static/icons/*` — in two independent layers: a Bypass policy in Cloudflare Access and the
  `pinsaver-pwa` router in sitehub (`deploy/sitehub/pinsaver.yml`). Google's WebAPK builder fetches
  them without a session; without them Android cannot install the app. Everything else, including
  `/api/*`, `/images/*` and `/share`, stays behind the JWT check.
- The archive is never baked into the image: `docker-compose.yml` mounts the working copy as `/data`
  and the image sets `PINSAVER_DATA_DIR=/data`. The container has no git and no `docker.sock`; the
  commit it reports comes from `.git/HEAD` and `refs/`, which `.dockerignore` keeps in the build
  context, or from the `PINSAVER_COMMIT` build arg that `update.ps1` passes.
- Mutating endpoints require `X-PinSaver-Request: 1` and reject foreign `http(s)` origins. Any new
  mutating route must take `Depends(require_csrf)`, and every client must send the header
  (`background.js` for the extension, `app.js` for the site, `admin.js` for the maintenance page,
  the service worker for the share flow).
- `GET /share` renders from the URL parameters only and must never read the database or write:
  anyone can open it with any parameters. Saving happens in `POST /api/pins/resolve`.
- `src/static/sw.js` intercepts exactly one request (`POST /share`) and caches nothing; it is served
  from the root by an explicit route so it can control `/share`. Keep it that way: the old
  `/static/sw.js` registration is unregistered and its caches dropped by `app.js`.
- `src/pinterest.py` resolves a link anonymously (no cookies). Its parser is a pure function and
  `tests/fixtures/pin_page.html` drives it: refresh the fixture with
  `python tools/resolve_pin.py <pin link> --save-fixture` when Pinterest changes its markup.

## Conventions

- Python 3.10+; modules in `src/` are not a package and import each other by bare name
  (`from models import ...`), so scripts are started as `python src/<script>.py`.
- Frontend is vanilla JS/CSS/HTML with no bundler and no npm; `src/static/` is served as-is and CSS/JS
  URLs are cache-busted with `?v=<version>` by the `/` route in `server.py`.
- New API routes go into `src/server.py` with a docstring, and the README API table gets a row.
- `src/images.py` decides what a downloaded image is stored as: the format comes from the bytes, never
  from the extension of the link, and HEIC/HEIF is converted to JPEG (the HEIC is kept next to it, and
  `/images` converts a legacy `.heic` on the fly).
- The extension talks to the server only through `background.js` (`API_REQUEST` messages) to bypass
  Chrome Private Network Access; `server.py` answers Pinterest origins with CORS/PNA headers. A
  message carries only `path` and fetch `options`: `content.js` never knows the server address,
  while `background.js` holds `serverUrl`, matches the exact `${method} ${path}` pairs of its
  allowlist and checks the host permission granted at runtime. The archive address is granted per
  origin and stored nowhere in the repository; `server.py` needs no changes for it.
- README is Russian; code, comments and docstrings are English.

## Data safety

- The working copy **is** production: never run `git reset`, `git clean`, `git stash` or
  `git checkout` here unless the user explicitly asks.
- Never commit `pinterest_archive.db`, `originals/`, `backups/`, `testPages/` or `.env`.
- `pinterest_archive.db` is a live SQLite file next to the running server: don't rewrite or delete it
  from scripts, and run `python src/backup.py` before risky operations.
- The server has no authentication and binds `0.0.0.0` by default — keep it on a trusted network and
  never expose it to the internet.
