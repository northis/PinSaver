<#
.SYNOPSIS
    Update PinSaver on this machine: pull, build from a clean worktree, restart, verify.

.DESCRIPTION
    Runs on the host: the container has neither git nor the Docker socket, so the host does
    the work.

      1. git fetch --prune --tags, fast-forward the branch, require HEAD == origin/<branch>
         (the fetch is retried: a concurrent git process - the push you just ran, an
         editor's git integration - can hold a ref lock for a second and fail it)
      2. read __version__ from src/buildinfo.py at the target commit, warn if it is untagged
      3. exit early when the running container already reports that commit
      4. tag the current image as pinsaver:previous
      5. build from a detached worktree of the target commit, passing the commit, its date,
         the version and the build time as build args (that is what the site badge shows)
      6. docker compose up -d --no-build, then wait for /api/version to report the commit
      7. on timeout: put pinsaver:previous back and fail

    ASCII only on purpose: Windows PowerShell 5.1 mangles non-ASCII source files.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File deploy\windows\update.ps1
    powershell -ExecutionPolicy Bypass -File deploy\windows\update.ps1 -Rollback
    powershell -ExecutionPolicy Bypass -File deploy\windows\update.ps1 -Force -SkipFetch
#>
[CmdletBinding()]
param(
    [string]$Branch = "master",
    [int]$KeepImages = 3,
    [int]$TimeoutSeconds = 120,
    [switch]$Force,
    [switch]$SkipFetch,
    [switch]$Rollback
)

$ErrorActionPreference = "Stop"

$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Service = "pinsaver"
$Image = "pinsaver:latest"
$PreviousImage = "pinsaver:previous"

function Write-Step([string]$Text) {
    Write-Host ""
    Write-Host "== $Text" -ForegroundColor Cyan
}

function Invoke-Native([string]$File, [string[]]$Arguments) {
    # Windows PowerShell 5.1 turns a native command's stderr into a *terminating* error as soon as
    # the stream is redirected and $ErrorActionPreference is Stop - and both docker and git write
    # progress, warnings and tracebacks to stderr. Drop the preference for the call, merge the
    # streams, and let the exit code decide. Output mixes real lines with error records: callers
    # keep the strings.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & $File @Arguments 2>&1
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
    return [pscustomobject]@{ Output = @($output); Code = $code }
}

function Get-NativeText($Result) {
    # Real output lines only: stderr arrives as error records and is not data.
    return @($Result.Output | Where-Object { $_ -is [string] })
}

function Get-NativeDiagnosis($Result) {
    # The other way round: everything a failed call said, stderr included. git and docker explain
    # themselves there, and a bare "failed with exit code 1" leaves the operator with nothing to
    # act on - which is exactly how a transient ref lock turns into a mystery.
    return @($Result.Output | ForEach-Object { "$_" } | Where-Object { "$_".Trim() })
}

function Invoke-Git([string[]]$Arguments) {
    $result = Invoke-Native "git" (@("-C", $Repo) + $Arguments)
    if ($result.Code -ne 0) {
        $why = Get-NativeDiagnosis $result | Select-Object -Last 3
        $detail = if ($why) { ":`n  " + ($why -join "`n  ") } else { "" }
        throw "git $($Arguments -join ' ') failed with exit code $($result.Code)$detail"
    }
    return Get-NativeText $result
}

function Get-RunningCommit {
    # Ask the container itself through the Docker CLI, the way duosave does. Going through the
    # host's published port was fragile: Docker Desktop wires 127.0.0.1:8000 up a moment after the
    # container starts, and a local filter can answer in the app's place. This way the answer always
    # comes from the process we are waiting for, and $script:ProbeError says why not.
    $script:ProbeError = ""
    # A single line on purpose: a multi-line script does not survive the trip through the Docker
    # CLI as an argument (it arrives with its newlines mangled and Python refuses it). The wrapper
    # above swallows the traceback if the request fails, and the exit code is what counts.
    $probe = "import json, urllib.request; " +
        "print(json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/version', timeout=3))['commit'])"
    $result = Invoke-Native "docker" @(
        "compose", "--project-directory", $Repo, "exec", "-T", $Service, "python", "-c", $probe
    )
    if ($result.Code -ne 0) {
        $script:ProbeError = "the container is not answering yet"
        return ""
    }
    $line = Get-NativeText $result | Select-Object -First 1
    return "$line".Trim()
}

function Wait-ForCommit([string]$Expected, [int]$Seconds) {
    # Prints a dot per poll and names whatever the container says instead: a silent loop that may
    # legitimately run for two minutes looks exactly like a hang.
    $deadline = (Get-Date).AddSeconds($Seconds)
    $detail = ""
    while ((Get-Date) -lt $deadline) {
        $seen = Get-RunningCommit
        if ($seen -eq $Expected) {
            Write-Host " ok" -ForegroundColor Green
            return $true
        }
        if ($seen) {
            $now = "the container still reports $($seen.Substring(0, 7))"
        } else {
            $now = $script:ProbeError
        }
        if ($now -and $now -ne $detail) {
            $detail = $now
            Write-Host ""
            Write-Host "  $now" -ForegroundColor Yellow
            Write-Host "  waiting" -NoNewline
        }
        Write-Host "." -NoNewline
        Start-Sleep -Seconds 2
    }
    Write-Host ""
    if ($detail) {
        Write-Host "  last answer: $detail" -ForegroundColor Yellow
    }
    return $false
}

function Test-PublishedPort {
    # A container that reports the right commit is not the same as a site answering on this
    # machine: Docker Desktop publishes the port a moment later. Warn, never fail: the update
    # itself has already succeeded.
    $result = Invoke-Native "docker" @("compose", "--project-directory", $Repo, "port", $Service, "8000")
    $published = Get-NativeText $result | Select-Object -First 1
    if (-not $published) {
        return
    }

    $address = $published.Trim()
    try {
        $client = New-Object System.Net.WebClient
        $client.DownloadString("http://$address/health") | Out-Null
        $client.Dispose()
        Write-Host "the site answers on http://$address" -ForegroundColor Green
    } catch {
        Write-Host "warning: the container is up, but http://$address does not answer from here" -ForegroundColor Yellow
        Write-Host "  Docker Desktop sometimes needs a moment to publish the port. If it stays silent," -ForegroundColor Yellow
        Write-Host "  check 'docker compose ps' and 'docker compose logs $Service'." -ForegroundColor Yellow
    }
}

function Start-Site {
    # Not named Start-Service: that is a built-in cmdlet, and shadowing it is a trap.
    $result = Invoke-Native "docker" @(
        "compose", "--project-directory", $Repo, "up", "-d", "--no-build", $Service
    )
    if ($result.Code -ne 0) {
        Get-NativeText $result | ForEach-Object { Write-Host "  $_" }
        throw "docker compose up failed"
    }
}

function Restore-PreviousImage {
    Write-Host "restoring $PreviousImage" -ForegroundColor Yellow
    $tagged = Invoke-Native "docker" @("tag", $PreviousImage, $Image)
    if ($tagged.Code -ne 0) {
        Write-Host "no $PreviousImage to restore" -ForegroundColor Yellow
        return
    }
    Start-Site
    Write-Host "previous image is running again" -ForegroundColor Yellow
}

function Remove-OldImages([int]$Keep) {
    $tags = & docker images pinsaver --format "{{.Tag}} {{.CreatedAt}}" |
        Where-Object { $_ -match "^[0-9a-f]{7,} " } |
        Sort-Object { ($_ -split " ")[1] } -Descending
    $stale = @($tags | Select-Object -Skip $Keep)
    foreach ($line in $stale) {
        $tag = ($line -split " ")[0]
        Write-Host "removing pinsaver:$tag"
        & docker rmi "pinsaver:$tag" | Out-Null
    }
}

Write-Step "Checking the working copy"
foreach ($tool in @("git", "docker")) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        throw "$tool is not in PATH"
    }
}
$dockerInfo = Invoke-Native "docker" @("info")
if ($dockerInfo.Code -ne 0) {
    throw "Docker Desktop is not running"
}

if ($Rollback) {
    Write-Step "Rolling back to $PreviousImage"
    Restore-PreviousImage
    exit 0
}

if (-not $SkipFetch) {
    Write-Step "Fetching origin/$Branch"
    # --force: a branch or a tag that moved on the remote (a force-push, a re-tagged release)
    # must not stop the update - the remote is what gets deployed, and the `merge --ff-only`
    # below still refuses a history that diverged.
    # Retried: git answers a ref lock held by a concurrent process with exit code 1, and that
    # process is usually the push the operator ran a moment ago.
    $attempts = 3
    for ($attempt = 1; ; $attempt++) {
        try {
            Invoke-Git @("fetch", "--prune", "--tags", "--force", "origin", $Branch) | Out-Null
            break
        } catch {
            Write-Host "  $($_.Exception.Message)" -ForegroundColor Yellow
            if ($attempt -ge $attempts) {
                throw "cannot fetch origin/$Branch (see above); fix that, or deploy what is already checked out with -SkipFetch"
            }
            Write-Host "  retrying in 3 s (a concurrent git process may hold a ref lock)" -ForegroundColor Yellow
            Start-Sleep -Seconds 3
        }
    }
}

$currentBranch = (Invoke-Git @("rev-parse", "--abbrev-ref", "HEAD") | Select-Object -First 1).Trim()
if ($currentBranch -ne $Branch) {
    throw "on branch '$currentBranch', expected '$Branch'"
}

Write-Step "Fast-forwarding $Branch"
Invoke-Git @("merge", "--ff-only", "origin/$Branch") | Out-Null

$target = (Invoke-Git @("rev-parse", "HEAD") | Select-Object -First 1).Trim()
$origin = (Invoke-Git @("rev-parse", "origin/$Branch") | Select-Object -First 1).Trim()
if ($target -ne $origin) {
    throw "HEAD ($target) differs from origin/$Branch ($origin)"
}
$short = $target.Substring(0, 7)

$versionFile = (Invoke-Git @("show", "${target}:src/buildinfo.py") | Out-String)
if ($versionFile -notmatch '__version__\s*=\s*"([^"]+)"') {
    throw "cannot read __version__ from src/buildinfo.py at $short"
}
$version = $Matches[1]

$tagged = (Invoke-Git @("tag", "--points-at", $target) | Where-Object { $_ -eq "v$version" })
if (-not $tagged) {
    Write-Host "warning: $short is not tagged v$version - the badge will link to a missing tag" -ForegroundColor Yellow
}

$running = Get-RunningCommit
if ($running -eq $target -and -not $Force) {
    Write-Host "already running $short, nothing to do (use -Force to rebuild)" -ForegroundColor Green
    exit 0
}

Write-Step "Building $version ($short)"
$commitDate = (Invoke-Git @("show", "-s", "--format=%cI", $target) | Select-Object -First 1).Trim()
$created = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")

if ($running) {
    & docker tag $Image $PreviousImage
    if ($LASTEXITCODE -ne 0) {
        throw "cannot tag the current image as $PreviousImage"
    }
}

$worktree = Join-Path $env:TEMP ("pinsaver-build-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
Invoke-Git @("worktree", "add", "--detach", $worktree, $target) | Out-Null
try {
    & docker build -t $Image -t "pinsaver:$short" `
        --build-arg "PINSAVER_COMMIT=$target" `
        --build-arg "PINSAVER_COMMIT_DATE=$commitDate" `
        --build-arg "PINSAVER_VERSION=$version" `
        --build-arg "PINSAVER_CREATED=$created" `
        $worktree
    if ($LASTEXITCODE -ne 0) {
        throw "docker build failed"
    }
} finally {
    Invoke-Git @("worktree", "remove", "--force", $worktree) | Out-Null
}

Write-Step "Starting $Service"
Start-Site

Write-Host ""
Write-Host "== Waiting for /api/version to report $short" -ForegroundColor Cyan -NoNewline
if (-not (Wait-ForCommit $target $TimeoutSeconds)) {
    Write-Host "the new image did not report $short within $TimeoutSeconds s" -ForegroundColor Red
    Restore-PreviousImage
    exit 1
}

Remove-OldImages $KeepImages

Write-Host ""
Write-Host "PinSaver $version ($short) is up" -ForegroundColor Green
Test-PublishedPort
