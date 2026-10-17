<#
.SYNOPSIS
    Update PinSaver on this machine: pull, build from a clean worktree, restart, verify.

.DESCRIPTION
    Runs on the host: the container has neither git nor the Docker socket, so the host does
    the work.

      1. git fetch --prune --tags, fast-forward the branch, require HEAD == origin/<branch>
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
$VersionUrl = "http://127.0.0.1:8000/api/version"

function Write-Step([string]$Text) {
    Write-Host ""
    Write-Host "== $Text" -ForegroundColor Cyan
}

function Invoke-Git([string[]]$Arguments) {
    # stderr is deliberately NOT redirected: with $ErrorActionPreference = "Stop", merging a
    # native command's stderr turns git's progress output ("From https://...") into a
    # terminating NativeCommandError. It goes to the console instead, and the exit code decides.
    $output = & git -C $Repo @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
    return $output
}

function Get-RunningCommit {
    # A plain .NET request on purpose: in Windows PowerShell 5.1 the first Invoke-RestMethod of a
    # session warms up the Internet Explorer parser, which adds seconds to the very first poll of
    # a loop that is supposed to notice a container coming up.
    try {
        $client = New-Object System.Net.WebClient
        $client.Headers.Add("Accept", "application/json")
        $json = $client.DownloadString($VersionUrl)
        $client.Dispose()
        return [string]($json | ConvertFrom-Json).commit
    } catch {
        return ""
    }
}

function Wait-ForCommit([string]$Expected, [int]$Seconds) {
    # Prints a dot per poll: a silent loop that may legitimately run for two minutes looks exactly
    # like a hang, and this one used to be silent.
    $deadline = (Get-Date).AddSeconds($Seconds)
    $reported = ""
    while ((Get-Date) -lt $deadline) {
        $seen = Get-RunningCommit
        if ($seen -eq $Expected) {
            Write-Host " ok" -ForegroundColor Green
            return $true
        }
        if ($seen -and $seen -ne $reported) {
            $reported = $seen
            Write-Host ""
            Write-Host "  container still reports $($seen.Substring(0, 7))" -ForegroundColor Yellow
            Write-Host "  waiting" -NoNewline
        }
        Write-Host "." -NoNewline
        Start-Sleep -Seconds 2
    }
    Write-Host ""
    return $false
}

function Start-Site {
    # Not named Start-Service: that is a built-in cmdlet, and shadowing it is a trap.
    & docker compose --project-directory $Repo up -d --no-build $Service
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose up failed"
    }
}

function Restore-PreviousImage {
    Write-Host "restoring $PreviousImage" -ForegroundColor Yellow
    & docker tag $PreviousImage $Image
    if ($LASTEXITCODE -ne 0) {
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
& docker info | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Docker Desktop is not running"
}

if ($Rollback) {
    Write-Step "Rolling back to $PreviousImage"
    Restore-PreviousImage
    exit 0
}

if (-not $SkipFetch) {
    Write-Step "Fetching origin/$Branch"
    Invoke-Git @("fetch", "--prune", "--tags", "origin", $Branch) | Out-Null
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
