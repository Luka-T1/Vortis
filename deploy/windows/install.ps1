
[CmdletBinding()]
param(
    [switch] $SkipService,
    [switch] $Service,
    [switch] $Force
)

$ErrorActionPreference = 'Stop'

if (-not $SkipService -and $env:VORTIS_SKIP_SERVICE) { $SkipService = $true }
if (-not $Service     -and $env:VORTIS_SERVICE)      { $Service     = $true }
if (-not $Force       -and $env:VORTIS_FORCE)        { $Force       = $true }

function Write-Info  ($msg) { Write-Host "[info]  $msg" -ForegroundColor Cyan }
function Write-Ok    ($msg) { Write-Host "[ok]    $msg" -ForegroundColor Green }
function Write-Warn2 ($msg) { Write-Host "[warn]  $msg" -ForegroundColor Yellow }
function Write-Fail  ($msg) {
    Write-Host "[fail]  $msg" -ForegroundColor Red
    throw [System.InvalidOperationException]::new([string] $msg)
}

function Update-PathFromRegistry {
    $machinePath = [System.Environment]::GetEnvironmentVariable('Path', 'Machine')
    $userPath    = [System.Environment]::GetEnvironmentVariable('Path', 'User')
    $combined    = "$machinePath;$userPath"
    $env:Path = [System.Environment]::ExpandEnvironmentVariables($combined)
}

function Install-WithWinget {
    param(
        [string] $WingetId,    # e.g. 'Python.Python.3.13'
        [string] $CommandName  # e.g. 'python' or 'git'
    )
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        return $null
    }
    Write-Info "  Installing $WingetId via winget (silent)..."
    & winget install --id $WingetId --silent --accept-source-agreements --accept-package-agreements 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Warn2 "  winget install $WingetId exited $LASTEXITCODE"
        return $null
    }
    Update-PathFromRegistry
    $cmd = Get-Command $CommandName -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

Write-Info "Checking OS..."
if ($PSVersionTable.Platform -and $PSVersionTable.Platform -ne 'Win32NT') {
    Write-Fail "install.ps1 is for native Windows. On Linux/macOS use install.sh."
}

$build = [System.Environment]::OSVersion.Version.Build
if ($build -lt 17763) {
    Write-Fail "Windows 10 1809 (build 17763) or newer is required. Detected build $build."
}
Write-Ok "Windows build $build"

function Get-PythonCommand {
    $seen = @{}
    foreach ($name in @('python', 'python3')) {
        foreach ($cmd in @(Get-Command $name -All -CommandType Application -ErrorAction SilentlyContinue)) {
            if (-not $cmd.Source -or $seen.ContainsKey($cmd.Source)) { continue }
            $seen[$cmd.Source] = $true
            try {
                $version = & $cmd.Source --version 2>$null
                $match = [regex]::Match(($version -join ' '), '^Python (\d+)\.(\d+)\.\d+')
                if ($LASTEXITCODE -eq 0 -and $match.Success -and
                    [int]$match.Groups[1].Value -eq 3 -and
                    [int]$match.Groups[2].Value -ge 11 -and
                    [int]$match.Groups[2].Value -le 13) {
                    return $cmd.Source
                }
            } catch {
            }
            Write-Warn2 "  Ignoring unavailable or unsupported Python at $($cmd.Source)"
        }
    }
    return $null
}

Write-Info "Checking Python (3.11 - 3.13)..."
$pythonExe = Get-PythonCommand
if (-not $pythonExe) {
    Write-Info "Python not on PATH - attempting auto-install via winget..."
    $null = Install-WithWinget -WingetId 'Python.Python.3.13' -CommandName 'python'
    $pythonExe = Get-PythonCommand
    if (-not $pythonExe) {
        Write-Fail @"
Python 3.11 - 3.13 not found and auto-install via winget failed.

Install manually from https://python.org (check 'Add python.exe to PATH'
during install) or via winget:

    winget install Python.Python.3.13

Then re-run this installer.
"@
    }
}

$verRaw = & $pythonExe --version 2>&1
$verMatch = [regex]::Match($verRaw, '(\d+)\.(\d+)\.(\d+)')
if (-not $verMatch.Success) {
    Write-Fail "Could not parse Python version from: $verRaw"
}
$pyMajor = [int]$verMatch.Groups[1].Value
$pyMinor = [int]$verMatch.Groups[2].Value
if ($pyMajor -ne 3 -or $pyMinor -lt 11 -or $pyMinor -gt 13) {
    Write-Fail @"
Found Python $pyMajor.$pyMinor at $pythonExe, but Vortis requires
3.11 - 3.13. Python 3.14 has no numpy Windows wheels yet (#432, will
re-open once numpy ships cp314).
"@
}
Write-Ok "Python $pyMajor.$pyMinor ($pythonExe)"

Write-Info "Checking git..."
$gitExe = (Get-Command git -ErrorAction SilentlyContinue).Source
if (-not $gitExe) {
    Write-Info "git not on PATH - attempting auto-install via winget..."
    $gitExe = Install-WithWinget -WingetId 'Git.Git' -CommandName 'git'
    if (-not $gitExe) {
        Write-Fail @"
git not found and auto-install via winget failed.

Install manually via winget:

    winget install Git.Git

or download from https://git-scm.com, then re-run this installer.
"@
    }
}
Write-Ok "git ($gitExe)"

Write-Info "Checking uv..."
$uvExe = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $uvExe) {
    Write-Info "Installing uv via astral.sh/uv (official PowerShell installer)..."
    try {
        Invoke-RestMethod -Uri 'https://astral.sh/uv/install.ps1' -UseBasicParsing | Invoke-Expression
    } catch {
        Write-Fail "uv install failed: $($_.Exception.Message)"
    }
    $uvDir = Join-Path $env:USERPROFILE '.local\bin'
    if (Test-Path (Join-Path $uvDir 'uv.exe')) {
        $env:Path = "$uvDir;$env:Path"
    }
    $uvExe = (Get-Command uv -ErrorAction SilentlyContinue).Source
    if (-not $uvExe) {
        Write-Fail "uv installed but isn't on PATH. Re-open a fresh PowerShell and re-run."
    }
}
Write-Ok "uv ($uvExe)"

$installRoot = if ($env:VORTIS_HOME) {
    $env:VORTIS_HOME
} else {
    Join-Path $env:LOCALAPPDATA 'Vortis'
}
$srcDir = Join-Path $installRoot 'src'

Write-Info "Install root: $installRoot"

if (-not (Test-Path $installRoot)) {
    New-Item -ItemType Directory -Path $installRoot | Out-Null
}

$repoUrl = if ($env:VORTIS_REPO_URL) {
    $env:VORTIS_REPO_URL
} else {
    'https://github.com/Luka-T1/Vortis.git'
}

if (Test-Path (Join-Path $srcDir '.git')) {
    if ($Force) {
        Write-Info "Force: pulling latest from $repoUrl..."
        & $gitExe -C $srcDir pull --ff-only
        if ($LASTEXITCODE -ne 0) { Write-Fail "git pull failed" }
    } else {
        Write-Ok "Repository already cloned (use -Force to update)"
    }
} else {
    Write-Info "Cloning $repoUrl..."
    if ($repoUrl -like 'file://*' -or (Test-Path -LiteralPath $repoUrl -ErrorAction SilentlyContinue)) {
        & $gitExe clone $repoUrl $srcDir
    } else {
        & $gitExe clone --filter=blob:none $repoUrl $srcDir
    }
    if ($LASTEXITCODE -ne 0) { Write-Fail "git clone failed" }
    Write-Ok "Cloned to $srcDir"
}

function Test-MsvcLinker {
    foreach ($cmd in @(Get-Command link.exe -All -CommandType Application -ErrorAction SilentlyContinue)) {
        $item = Get-Item -LiteralPath $cmd.Source -ErrorAction SilentlyContinue
        if ($item -and $item.VersionInfo.CompanyName -match '^Microsoft' -and
            $item.VersionInfo.OriginalFilename -ieq 'link.exe') {
            return $true
        }
    }
    if (-not ${env:ProgramFiles(x86)}) { return $false }
    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    if (-not (Test-Path -LiteralPath $vswhere)) { return $false }
    $found = & $vswhere -latest -products * `
        -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
        -find 'VC\Tools\MSVC\**\bin\Host*\*\link.exe' 2>$null
    if ($LASTEXITCODE -ne 0) { return $false }
    foreach ($linker in $found) {
        if (Test-Path -LiteralPath $linker -PathType Leaf) { return $true }
    }
    return $false
}

Write-Info "Checking MSVC build tools (needed to compile the native extension)..."
if (Test-MsvcLinker) {
    Write-Ok "MSVC build tools present"
} else {
    Write-Fail @"
MSVC build tools not found.

The next step compiles the mandatory vortis-rust extension, which
needs the MSVC linker (link.exe). Without it every cargo build script
fails with "error: linker ``link.exe`` not found".

Install via winget - expect a multi-GB download and a UAC prompt:

    winget install --id Microsoft.VisualStudio.2022.BuildTools ``
        --override "--wait --quiet --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"

--override is load-bearing: the default Build Tools install ships no
workload at all, so VCTools has to be requested explicitly.

Alternatively download "Build Tools for Visual Studio" from
https://visualstudio.microsoft.com/downloads/ and select the
"Desktop development with C++" workload.

Then re-run this installer.
"@
}

Write-Info "Running 'uv sync --extra desktop --group desktop-native' in $srcDir (this can take a few minutes)..."
Push-Location $srcDir
try {
    & $uvExe sync --extra desktop --group desktop-native
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "uv sync failed with exit code $LASTEXITCODE. Check the output above."
    }
} finally {
    Pop-Location
}
Write-Ok "Dependencies installed"

Write-Info "Checking Ollama..."
$ollamaExe = (Get-Command ollama -ErrorAction SilentlyContinue).Source
if (-not $ollamaExe) {
    Write-Info "  Ollama not on PATH - downloading the official installer (~150 MB)..."
    $ollamaSetup = Join-Path $env:TEMP 'OllamaSetup.exe'
    $prevProgress = $ProgressPreference
    $ProgressPreference = 'SilentlyContinue'
    try {
        Invoke-WebRequest `
            -Uri 'https://ollama.com/download/OllamaSetup.exe' `
            -OutFile $ollamaSetup `
            -UseBasicParsing
    } catch {
        Remove-Item $ollamaSetup -ErrorAction SilentlyContinue  # clean up partial download
        $ProgressPreference = $prevProgress
        Write-Fail "Ollama download failed: $($_.Exception.Message)`nInstall manually from https://ollama.com, then re-run."
    } finally {
        $ProgressPreference = $prevProgress
    }
    Write-Info "  Running OllamaSetup.exe /S (this can take a minute)..."
    Start-Process -FilePath $ollamaSetup -ArgumentList '/S' -Wait
    Remove-Item $ollamaSetup -ErrorAction SilentlyContinue
    Update-PathFromRegistry
    $ollamaExe = (Get-Command ollama -ErrorAction SilentlyContinue).Source
    if (-not $ollamaExe) {
        Write-Fail "Ollama installer ran but 'ollama' isn't on PATH. Open a fresh PowerShell and re-run, or install manually from https://ollama.com."
    }
}
Write-Ok "Ollama ($ollamaExe)"

Write-Info "Waiting for Ollama daemon..."
$ollamaReady = $false
for ($i = 0; $i -lt 60; $i++) {
    try { & $ollamaExe list 2>&1 | Out-Null } catch { }
    if ($LASTEXITCODE -eq 0) {
        $ollamaReady = $true
        break
    }
    if ($i -eq 5) {
        Start-Process -FilePath $ollamaExe -ArgumentList 'serve' -WindowStyle Hidden -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 1
}
if (-not $ollamaReady) {
    Write-Warn2 "Ollama daemon didn't become ready in 60s. Continuing - bg-orchestrator will retry later."
}

$modelPullOk = $false
if ($ollamaReady) {
    Write-Info "Pulling qwen3.5:2b (~1.5 GB) so 'vortis' works on first run..."
    & $ollamaExe pull 'qwen3.5:2b'
    if ($LASTEXITCODE -eq 0) {
        $modelPullOk = $true
        Write-Ok "Starter model ready"
    } else {
        Write-Warn2 "ollama pull failed; the bg-orchestrator will retry once Ollama is reachable."
    }
} else {
    Write-Warn2 "Skipping model pull - daemon wasn't ready."
}

$binDir = Join-Path $installRoot 'bin'
$shimPath = Join-Path $binDir 'vortis.cmd'

if (-not (Test-Path $binDir)) {
    New-Item -ItemType Directory -Path $binDir | Out-Null
}

$shimContent = @"
@echo off
setlocal
set "SRC=%~dp0..\src"
uv run --project "%SRC%" vortis %*
"@
Set-Content -Path $shimPath -Value $shimContent -Encoding ASCII

$userPath = [System.Environment]::GetEnvironmentVariable('Path', 'User')
$pathOnUser = $false
if ($userPath) {
    foreach ($entry in ($userPath -split ';')) {
        $expanded = [System.Environment]::ExpandEnvironmentVariables($entry)
        if ($expanded -ieq $binDir) { $pathOnUser = $true; break }
    }
}
$pathNeedsRefresh = $false
if (-not $pathOnUser) {
    $newUserPath = if ($userPath) { "$userPath;$binDir" } else { $binDir }
    [System.Environment]::SetEnvironmentVariable('Path', $newUserPath, 'User')
    $pathNeedsRefresh = $true
}
Write-Ok "vortis shim installed at $shimPath"

$serviceScript = Join-Path $srcDir 'deploy\windows\vortis-service.ps1'
$shouldInstallService = $false

$isAdmin = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent()
).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if ($Service -and -not $isAdmin) {
    Write-Fail "-Service was requested, but this PowerShell is not elevated. Register-ScheduledTask needs admin rights - re-run from an elevated PowerShell, or drop -Service."
}
if ($Service) {
    $shouldInstallService = $true
} elseif ($SkipService) {
    $shouldInstallService = $false
} elseif (-not $isAdmin) {
    Write-Warn2 "Skipping scheduled-task setup - this PowerShell is not elevated."
    Write-Warn2 "  Register-ScheduledTask requires admin. To install the service later:"
    Write-Warn2 "    Right-click PowerShell -> Run as administrator, then run:"
    Write-Warn2 "    powershell -ExecutionPolicy Bypass -File `"$serviceScript`" install"
} else {
    $isInteractive = [Environment]::UserInteractive `
        -and -not [System.Console]::IsInputRedirected
    if ($isInteractive) {
        $reply = Read-Host "Register Vortis as a Windows scheduled task (auto-start at logon, loopback only)? [y/N]"
        $shouldInstallService = ($reply -match '^[yY]')
    } else {
        Write-Warn2 "Non-interactive install - skipping scheduled-task setup."
        Write-Warn2 "To register the service later, run (from an elevated PowerShell):"
        Write-Warn2 "  powershell -ExecutionPolicy Bypass -File `"$serviceScript`" install"
    }
}

if ($shouldInstallService) {
    if (-not (Test-Path $serviceScript)) {
        Write-Fail "Service script not found at $serviceScript (the clone may be missing files; try -Force)."
    }
    Write-Info "Installing scheduled task..."
    & powershell -ExecutionPolicy Bypass -File $serviceScript install -InstallRoot $installRoot
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "Scheduled task setup failed."
    }
    Write-Ok "Scheduled task 'Vortis' registered (loopback default)."
}

Write-Host ""
Write-Host "  +----------------------------------+" -ForegroundColor Green
Write-Host "  |   Vortis install complete    |" -ForegroundColor Green
Write-Host "  +----------------------------------+" -ForegroundColor Green
Write-Host ""
Write-Host "  Repo:    $srcDir"

$nextCmd = if ($modelPullOk) { 'vortis' } else { 'vortis doctor' }

if ($pathNeedsRefresh) {
    Write-Host ""
    Write-Host "  Run it:  open a NEW PowerShell, then: $nextCmd" -ForegroundColor Yellow
    Write-Host "           (the vortis shim was added to your User PATH; the"
    Write-Host "            current PowerShell won't see it until restart)"
} else {
    Write-Host "  Run it:  $nextCmd"
}

if (-not $modelPullOk) {
    Write-Host ""
    Write-Host "  NOTE: the qwen3.5:2b model didn't finish downloading." -ForegroundColor Yellow
    Write-Host "        Chat will fail until the bg-orchestrator finishes the retry."
    Write-Host "        'vortis doctor' shows progress."
}

if ($shouldInstallService) {
    Write-Host ""
    Write-Host "  Service: schtasks /Query /TN Vortis     (status)"
    Write-Host "           powershell -File `"$serviceScript`" uninstall    (remove)"
}
Write-Host ""
Write-Host "  Docs:    https://github.com/Luka-T1/Vortis"
Write-Host ""
