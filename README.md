# PinSaver — локальный архив пинов Pinterest

PinSaver — это self-hosted архив пинов Pinterest в исходном качестве: сервер на FastAPI + SQLite
с веб-интерфейсом (мозаика, бесконечная прокрутка, полноэкранная карусель, удаление) и расширение
Chrome, которое сохраняет пины прямо со страниц Pinterest, помечает уже сохранённое в избранном
и умеет заливать архив обратно в профиль.

Версия и коммит сборки всегда видны: в шапке сайта и на странице настроек расширения — `vX.Y.Z`
ведёт на тег релиза, короткий хеш — на коммит в GitHub.

## Возможности

- **Веб-интерфейс** — мозаика с бесконечной прокруткой, полноэкранная карусель, сортировки
  (новые, старые, по рейтингу, случайно) и фильтр удалённых пинов.
- **Расширение Chrome** — кнопка «Save» на странице пина сохраняет оригинал изображения в архив.
- **Метки в избранном** — на страницах профиля каждый пин получает значок: `✓` (уже в архиве) или
  `↓` (можно сохранить одним кликом).
- **Синхронизация в Pinterest** — плавающая кнопка «🔄 Sync to Pinterest» заливает архив обратно
  в профиль (Quick Saves).
- **Рейтинг** — повторные сохранения одного и того же изображения увеличивают счётчик: видно, что
  нравится больше.
- **Проверка удалённых пинов** — headless Chromium проходит по ссылкам и помечает то, что Pinterest
  больше не отдаёт.
- **Бэкапы** — инкрементальные zip-архивы базы и новых оригиналов.

## Состав

| Путь | Что там |
| --- | --- |
| `src/` | сервер FastAPI и скрипты (`server.py`, `models.py`, `importer.py`, `updateDelete.py`, `backup.py`, `buildinfo.py`) |
| `src/static/` | веб-интерфейс (vanilla JS/CSS/HTML, без сборки) и PWA-манифест |
| `extension/` | расширение Chrome MV3 (content script, service worker, страница настроек, иконки) |
| `tools/` | скрипты, которые запускают руками, а результат коммитят (`make_extension_icons.py`, `bump_version.py`) |
| `Dockerfile`, `docker-compose.yml` | сборка образа и запуск: в образ идёт только рантайм, архив монтируется с хоста |
| `deploy/` | хостовые скрипты и конфиги: `windows/update.ps1`, `sitehub/pinsaver.yml` |
| `tests/` | офлайн-тесты (pytest): архив не трогают, сети не требуют |
| `originals/`, `pinterest_archive.db`, `backups/` | данные, в git не попадают |

## Быстрый старт

### 1. Клонировать и поставить зависимости

```bash
git clone https://github.com/northis/PinSaver.git
cd PinSaver
python -m pip install -r src/requirements.txt -r src/requirements-tools.txt
```

Нужен Python 3.10+. `requirements.txt` — то, что нужно серверу (его же ставит контейнер),
`requirements-tools.txt` — хостовые скрипты и инструменты: `updateDelete.py` требует Playwright с
браузером, `importer.py` — BeautifulSoup, `tools/` — Pillow.

Тесты идут офлайн и не трогают архив:

```bash
python -m pip install -r src/requirements-dev.txt
python -m pytest -q
```

### 2. Настроить окружение

```bash
cp .env.example .env
```

```env
HOST=0.0.0.0
PORT=8000
```

### 3. Создать базу

```bash
python src/models.py
```

Появятся `pinterest_archive.db` и папка `originals/` для картинок.

### 4. Запустить сервер

```bash
python src/server.py
```

Сайт — `http://localhost:8000`, версия и коммит — в шапке страницы.

### 5. Поставить расширение

1. Открой `chrome://extensions/`, включи «Режим разработчика».
2. «Загрузить распакованное расширение» → папка `extension/`.
3. Открой настройки расширения (клик по иконке в панели или «Подробнее» → «Параметры расширения»)
   и проверь адрес сервера — по умолчанию `http://localhost:8000`.

## Запуск в Docker

```bash
docker compose up -d --build
```

В образ идёт только рантайм (`src/requirements.txt`), а архив — база, `originals/` и `backups/` —
монтируется с хоста как `/data`, поэтому пересборка и удаление контейнера данные не трогают.
Порт публикуется дважды, и это осознанно: `127.0.0.1:8000` нужен расширению (в его
`host_permissions` только localhost и 127.0.0.1), а `${PINSAVER_BIND_ADDR}:8000` — Traefik'у на
хосте sitehub, куда тот ходит по VPN. Настройки — в `.env` (см. `.env.example`).

```bash
curl http://127.0.0.1:8000/api/version   # версия и коммит, вшитые в образ
docker compose ps                        # healthy означает, что healthcheck прошёл
docker compose logs -f pinsaver          # логи: json-file, 10 МБ x 3
docker compose down                      # остановить; данные остаются на месте
```

Версия и коммит попадают в образ двумя путями: `update.ps1` передаёт их build-аргументами, а при
обычной сборке коммит читается из `.git/HEAD` и `refs/`, которые `.dockerignore` оставляет в образе
(самого git в контейнере нет). Поэтому бейдж на сайте и `/api/version` показывают то, что реально
собрано, а не то, что лежит в рабочей копии.

## Публикация в интернете: sitehub + Cloudflare Access

Сайт живёт на этом ПК, а наружу его отдаёт [sitehub](https://github.com/northis/sitehub) — Traefik на
Ubuntu-сервере с wildcard-сертификатом, который ходит к нам по SoftEther VPN на
`${PINSAVER_BIND_ADDR}:8000`. Порядок:

1. Контейнер поднят на ПК (`docker compose up -d`), адрес в VPN — тот же, что у duosave
   (`10.77.77.21`).
2. В sitehub в `traefik/dynamic/vpn-sites.yml` вставляется фрагмент `deploy/sitehub/pinsaver.yml`
   (заменить домен и адрес VPN). Он добавляет **два** роутера: основной — за проверкой
   `cf-access-verify@file`, и публичный для трёх путей: `/static/manifest.json`,
   `/static/icon-192.png`, `/static/icon-512.png`. Без публичного роутера Google не соберёт WebAPK,
   и PinSaver не появится в системном «Поделиться».
3. В Cloudflare Access этим же трём путям нужна политика **Bypass** (Include = Everyone): политика на
   крае и проверка на входе sitehub — два независимых слоя, нужны оба.
4. Проверка:

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://pinsaver.<домен>/static/manifest.json   # 200 без сессии
curl -s -o /dev/null -w '%{http_code}\n' https://pinsaver.<домен>/static/icon-192.png    # 200 без сессии
```

Сайт без сессии Access открываться не должен: внутри приложения авторизации нет, Access — единственный
вход снаружи. Порт `8000` в интернет не публикуется (в `ports` только `127.0.0.1` и VPN-адрес), а
изменяющие запросы требуют заголовок `X-PinSaver-Request: 1` и отвергают чужие источники.

## Обновление

```powershell
powershell -ExecutionPolicy Bypass -File deploy\windows\update.ps1
powershell -ExecutionPolicy Bypass -File deploy\windows\update.ps1 -Rollback
```

Скрипт делает `git fetch`, fast-forward, читает версию в целевом коммите, собирает образ из **чистого
worktree** этого коммита (незакоммиченные правки в образ не попадают), поднимает контейнер и ждёт,
пока `/api/version` не покажет новый коммит; если не дождался — возвращает прошлый образ и падает с
ошибкой. Если контейнер уже на нужном коммите, скрипт просто выходит (`-Force` — пересобрать).

Руками то же самое: `git pull` и `docker compose up -d --build`.

После обновления сервера **перезагрузите расширение** в `chrome://extensions`: в нём появился заголовок
гарда, и старое расширение получит `403` с текстом «reload the extension».

## Расширение Chrome

### Сохранение пина

На любой странице пина появляется кнопка «Save» — она скачивает оригинал изображения в `originals/`
и добавляет запись в базу. Повторное сохранение того же изображения не создаёт дубликат, а поднимает
рейтинг.

### Метки в избранном

На странице профиля (свои или чужие сохранённые пины) каждый пин получает значок в левом верхнем углу:

- **✓ (зелёный)** — пин уже в архиве;
- **↓ (серый)** — нажми, чтобы сохранить.

### Синхронизация обратно в Pinterest

На любой странице Pinterest в правом нижнем углу появляется кнопка «🔄 Sync to Pinterest»: она
по очереди отправляет не удалённые пины из архива в твой профиль. Нужен активный вход в Pinterest —
расширение использует cookies браузера.

### Настройки

На странице настроек — адрес сервера, кнопка проверки соединения, ссылка на архив, иконка
расширения и бейдж сборки: версия расширения (из манифеста, ведёт на тег релиза) и короткий хеш
коммита (приходит с сервера, ведёт на коммит в GitHub). Если сервер недоступен, вместо хеша
показывается «server unavailable».

## Веб-интерфейс

- сортировки **Newest / Oldest / Top / Random** и кнопка **Deleted** — показать только то, что
  удалено с Pinterest;
- счётчик под шапкой — сколько пинов загружено из общего числа;
- клик по пину открывает карусель (`←`/`→`, `Esc`), кнопка `⛶` — то же самое;
- кнопка `✕` на карточке удаляет пин из архива, с галочкой «Also delete the image file» — вместе
  с файлом в `originals/`.

## Проверка удалённых пинов

```bash
playwright install chromium   # один раз
python src/updateDelete.py
```

Скрипт открывает каждую ссылку в headless Chromium и ставит `is_deleted` тем пинам, которых больше
нет. Результат виден по кнопке **Deleted** в веб-интерфейсе.

## Бэкапы

```bash
python src/backup.py
```

В `backups/` появляется zip: база целиком плюс только те файлы из `originals/`, что новее прошлого
бэкапа. Время последнего бэкапа — в `backups/backup_state.json`.

## Импорт из экспорта Pinterest

Если база потеряна, а картинки в `originals/` остались:

```bash
python src/importer.py
```

Скрипт разбирает HTML-файлы экспорта Pinterest в корне проекта и восстанавливает записи по тем
картинкам, что есть на диске. Схлопнуть дубликаты по `file_id` можно так:

```bash
python src/migrate_duplicates.py
```

## Версия, хеш и релизы

Единственный источник версии — `__version__` в `src/buildinfo.py`; `tools/bump_version.py` переносит
её в `extension/manifest.json`, так что руками версию больше нигде править не нужно.

```bash
python tools/bump_version.py 1.2.0    # поднять версию в обоих файлах
python tools/bump_version.py --check  # проверить, что версии совпадают
```

- `GET /api/version` (`src/buildinfo.py`) отдаёт версию, коммит, дату коммита, признак незакоммиченных
  правок и ссылки на тег и коммит; сайт рисует из этого бейдж в шапке, расширение — бейдж в настройках;
- хеш у сайта и у расширения ведёт на коммит, версия — на `releases/tag/vX.Y.Z`; звёздочка у хеша
  означает, что в рабочей копии есть незакоммиченные правки;
- порядок релиза: `python tools/bump_version.py X.Y.Z` → коммит → `git tag -a vX.Y.Z -m "PinSaver X.Y.Z"`
  → `git push --follow-tags origin master` → GitHub Release по этому тегу.

Иконки расширения — тоже генерируемые: мастер-файл `extension/icon.svg`, из него рисуются PNG
(Chrome не умеет SVG-иконки):

```bash
python tools/make_extension_icons.py
```

## Команды

| Команда | Что делает |
| --- | --- |
| `python src/server.py` | сайт и API на `HOST:PORT` из `.env` |
| `python src/models.py` | создать базу и папку `originals/` |
| `python src/importer.py` | импорт пинов из HTML-экспорта Pinterest |
| `python src/updateDelete.py` | пометить пины, удалённые с Pinterest |
| `python src/backup.py` | инкрементальный бэкап в `backups/` |
| `python src/migrate_duplicates.py` | схлопнуть дубликаты по `file_id` |
| `python src/buildinfo.py` | напечатать версию, коммит и ссылки |
| `python tools/bump_version.py X.Y.Z` | поднять версию в `src/` и `extension/` |
| `python tools/make_extension_icons.py` | перерисовать PNG-иконки из `extension/icon.svg` |
| `playwright install chromium` | поставить браузер для `updateDelete.py` |
| `python -m pytest -q` | офлайн-тесты (архив и сеть не трогают) |
| `docker compose up -d --build` | собрать и поднять сайт в контейнере |
| `docker compose down` | остановить контейнер (данные на хосте остаются) |
| `deploy\windows\update.ps1` | обновление с хоста: сборка из чистого worktree, откат при неудаче |

## API

| Метод | Путь | Описание |
| --- | --- | --- |
| GET | `/api/pins` | страница пинов (`offset`, `limit`, `sort`, `deleted`) |
| GET | `/api/pins/sync` | идентификаторы всех не удалённых пинов — для синхронизации |
| POST | `/api/pins` | добавить пин (`pin_id`, `original_url`) |
| POST | `/api/pins/check` | проверить, какие пины уже в архиве (`pins[]` из `pin_id`, `file_id`) |
| DELETE | `/api/pins/{pin_id}` | удалить пин (`delete_file` — вместе с картинкой) |
| GET | `/api/version` | версия, коммит и ссылки на репозиторий |
| GET | `/images/{filename}` | отдать картинку из `originals/` |
| GET | `/health` | проверка доступности сервера |
| GET | `/` | главная страница |

## Структура проекта

```
PinSaver/
├── src/
│   ├── server.py             # FastAPI: API, отдача сайта и картинок
│   ├── models.py             # схема SQLite и модель Pin
│   ├── buildinfo.py          # версия и коммит (источник версии проекта)
│   ├── parser.py             # разбор HTML-экспорта Pinterest
│   ├── importer.py           # импорт разобранных пинов в базу
│   ├── migrate_duplicates.py # схлопывание дубликатов по file_id
│   ├── updateDelete.py       # проверка удалённых пинов через Playwright
│   ├── backup.py             # инкрементальные бэкапы
│   ├── requirements.txt      # рантайм: его же ставит контейнер
│   ├── requirements-tools.txt # хостовые скрипты: Playwright, BeautifulSoup, Pillow
│   ├── requirements-dev.txt  # pytest
│   └── static/               # сайт: index.html, app.js, styles.css, sw.js, PWA-иконки
├── Dockerfile                # образ: только рантайм, архив монтируется
├── docker-compose.yml        # запуск, порты, монтирование /data
├── deploy/
│   ├── windows/update.ps1    # обновление с хоста с откатом
│   └── sitehub/pinsaver.yml  # фрагмент для traefik/dynamic/vpn-sites.yml
├── tests/                    # офлайн-тесты pytest
├── extension/
│   ├── manifest.json         # манифест MV3 (версия синхронизируется bump_version.py)
│   ├── background.js         # service worker: прокси API-запросов, клик по иконке
│   ├── content.js            # кнопка Save, метки в избранном, синхронизация
│   ├── styles.css            # стили уведомлений, значков и кнопки синхронизации
│   ├── options.html          # страница настроек
│   ├── options.js            # логика настроек и бейджа версии
│   ├── icon.svg              # мастер-иконка (Pinterest-стиль)
│   └── icon16/32/48/128.png  # PNG-иконки, отрисованные из icon.svg
├── tools/
│   ├── make_extension_icons.py  # SVG → PNG-иконки расширения
│   └── bump_version.py          # версия в src/ и extension/ + проверка синхронности
├── originals/                # оригиналы картинок (в git не попадает)
├── pinterest_archive.db      # база SQLite (в git не попадает)
├── backups/                  # zip-бэкапы (в git не попадает)
└── .env                      # настройки сервера (создать из .env.example)
```

## Данные и безопасность

- Внутри приложения авторизации нет: единственный вход снаружи — Cloudflare Access (см. «Публикация в
  интернете»). Локально сервер слушает `0.0.0.0` — держи его в доверенной сети.
- Изменяющие запросы (`POST /api/pins`, `POST /api/pins/check`, `DELETE /api/pins/{pin_id}`) требуют
  заголовок `X-PinSaver-Request: 1` и отвергают чужие `http(s)`-источники: страница со стороны не может
  ни добавить, ни удалить пин. Расширение и service worker ставят заголовок сами.
- `GET /images/{filename}` принимает только простое имя файла: до 2.0.0 `..%5c..` позволял прочитать
  любой файл на машине, включая `.env` и саму базу — теперь это закрыто и покрыто тестом.
- У контейнера нет доступа к `docker.sock`, git и хосту: обновление запускается вручную с хоста
  (`deploy\windows\update.ps1`).
- Из браузера к API обращается только расширение: CORS открыт исключительно для `*.pinterest.com`
  (и только чтобы обойти Private Network Access), остальные источники получают отказ.
- `pinterest_archive.db`, `originals/`, `backups/`, `testPages/` и `.env` перечислены в `.gitignore` —
  в репозиторий попадает только код.
- Перед рискованными операциями делай `python src/backup.py`.

## Лицензия

MIT
