/* The maintenance page: archive totals, backup downloads, incremental backup. */

const REQUEST_HEADER = { 'X-PinSaver-Request': '1' };
const PORT_NOTICE = 'This page is served by the maintenance listener only. Open it on the ' +
    'admin port (PINSAVER_ADMIN_PORT, 8001 by default), not on the site port.';

let running = false;
let downloadUntil = 0;

function formatBytes(bytes) {
    if (!bytes) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let value = bytes;
    let unit = 0;
    while (value >= 1024 && unit < units.length - 1) {
        value /= 1024;
        unit += 1;
    }
    return `${value.toFixed(unit > 0 && value < 10 ? 1 : 0)} ${units[unit]}`;
}

function formatTime(iso) {
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return iso || '';
    return date.toLocaleString('en-US', {
        year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
    });
}

async function requestJson(path, options) {
    const response = await fetch(path, options);
    if (!response.ok) {
        const error = new Error(`request failed (${response.status})`);
        error.status = response.status;
        throw error;
    }
    return response.json();
}

function setStatus(id, text, kind) {
    const element = document.getElementById(id);
    element.textContent = text || '';
    element.className = kind ? `status ${kind}` : 'status';
}

function statCard(label, value, sub) {
    const card = document.createElement('div');
    card.className = 'stat';

    const labelEl = document.createElement('span');
    labelEl.className = 'label';
    labelEl.textContent = label;
    card.append(labelEl);

    const valueEl = document.createElement('span');
    valueEl.className = 'value';
    valueEl.textContent = value;
    card.append(valueEl);

    if (sub) {
        const subEl = document.createElement('span');
        subEl.className = 'sub';
        subEl.textContent = sub;
        card.append(subEl);
    }

    return card;
}

function renderState(state) {
    document.getElementById('stats').replaceChildren(
        statCard('Pins', String(state.pins.active), `${state.pins.deleted} deleted`),
        statCard('Images', String(state.originals.files), formatBytes(state.originals.bytes)),
        statCard('Database', formatBytes(state.database.bytes)),
        statCard('Backups', String(state.backups.count), formatBytes(state.backups.bytes))
    );

    const paths = document.getElementById('paths');
    paths.replaceChildren();
    for (const line of [`Database: ${state.database.path}`,
                        `Images: ${state.originals.path}`,
                        `Backups: ${state.backups.path}`]) {
        const row = document.createElement('div');
        row.textContent = line;
        paths.append(row);
    }

    document.getElementById('lastBackup').textContent = state.backups.last_backup_utc
        ? `Last backup: ${formatTime(state.backups.last_backup_utc)}`
        : 'No backup has been taken yet.';

    document.getElementById('fullBackup').textContent =
        `Download full backup (${formatBytes(state.database.bytes + state.originals.bytes)})`;
}

function renderBackups(payload) {
    const container = document.getElementById('backupList');
    if (!payload.backups.length) {
        const empty = document.createElement('p');
        empty.className = 'empty';
        empty.textContent = 'No backups on disk yet.';
        container.replaceChildren(empty);
        return;
    }

    const head = document.createElement('tr');
    for (const title of ['Name', 'Created', 'Size', '']) {
        const cell = document.createElement('th');
        cell.textContent = title;
        head.append(cell);
    }
    const thead = document.createElement('thead');
    thead.append(head);

    const tbody = document.createElement('tbody');
    for (const item of payload.backups) {
        const row = document.createElement('tr');

        const name = document.createElement('td');
        name.className = 'name';
        name.textContent = item.name;

        const created = document.createElement('td');
        created.textContent = formatTime(item.created_utc);

        const size = document.createElement('td');
        size.textContent = formatBytes(item.bytes);

        const linkCell = document.createElement('td');
        const link = document.createElement('a');
        link.href = `/api/admin/backups/${encodeURIComponent(item.name)}`;
        link.textContent = 'Download';
        linkCell.append(link);

        row.append(name, created, size, linkCell);
        tbody.append(row);
    }

    const table = document.createElement('table');
    table.append(thead, tbody);
    container.replaceChildren(table);
}

function showPortNotice() {
    const notice = document.getElementById('portNotice');
    notice.textContent = PORT_NOTICE;
    notice.hidden = false;
    document.getElementById('stats').textContent = 'Unavailable here.';
    document.getElementById('backupList').textContent = 'Unavailable here.';
}

async function refresh() {
    const [state, backups] = await Promise.all([
        requestJson('/api/admin/state'),
        requestJson('/api/admin/backups')
    ]);
    renderState(state);
    renderBackups(backups);
}

async function runBackup() {
    if (running || Date.now() < downloadUntil) return;
    running = true;

    const button = document.getElementById('runBackup');
    button.disabled = true;
    setStatus('backupStatus', 'Creating the backup…');

    try {
        const payload = await requestJson('/api/admin/backup', {
            method: 'POST',
            headers: REQUEST_HEADER
        });
        const backup = payload.backup;
        setStatus('backupStatus',
            `${backup.name} created: ${backup.originals} image(s), ${formatBytes(backup.bytes)}.`,
            'ok');
        await refresh();
    } catch (error) {
        const message = error.status === 409
            ? 'A backup is already running, try again in a moment.'
            : `Backup failed: ${error.message}`;
        setStatus('backupStatus', message, 'error');
    } finally {
        running = false;
        button.disabled = false;
    }
}

function onFullBackupClick() {
    if (Date.now() < downloadUntil) return;
    downloadUntil = Date.now() + 15000;
    setStatus('fullStatus', 'Preparing the archive…');
    setTimeout(() => setStatus('fullStatus', ''), 15000);
}

// Build badge in the header: version links to the release tag, commit to the commit.
async function loadBuildInfo() {
    let info;
    try {
        const response = await fetch('/api/version');
        if (!response.ok) return;
        info = await response.json();
    } catch (error) {
        console.log('Build info unavailable:', error);
        return;
    }

    const badge = document.getElementById('buildBadge');
    const versionLink = document.getElementById('buildVersion');
    const commitLink = document.getElementById('buildCommit');
    const commitSep = document.getElementById('buildCommitSep');
    if (!badge || !info || !info.version) return;

    versionLink.textContent = 'v' + info.version;
    versionLink.href = info.tag_url || `${info.repo_url}/releases/tag/v${info.version}`;
    versionLink.title = `Release ${info.tag || 'v' + info.version}`;

    if (info.commit) {
        commitLink.textContent = info.short + (info.dirty ? '*' : '');
        commitLink.href = info.commit_url;
        commitLink.title = [
            `commit ${info.short}`,
            info.commit_date ? info.commit_date.slice(0, 10) : null,
            info.dirty ? 'uncommitted changes' : null
        ].filter(Boolean).join(', ');
        commitLink.hidden = false;
        commitSep.hidden = false;
    }

    badge.hidden = false;
}

async function init() {
    try {
        await refresh();
    } catch (error) {
        if (error.status === 404) {
            showPortNotice();
        } else {
            document.getElementById('stats').textContent = `Failed to load: ${error.message}`;
            document.getElementById('backupList').textContent = `Failed to load: ${error.message}`;
        }
    }
    loadBuildInfo();
}

document.getElementById('runBackup').addEventListener('click', runBackup);
document.getElementById('fullBackup').addEventListener('click', onFullBackupClick);
init();
