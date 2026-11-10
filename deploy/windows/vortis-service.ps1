
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('install', 'uninstall', 'status')]
    [string] $Command = 'status',

    [string] $InstallRoot,
    [string] $ListenHost = '127.0.0.1',
    [int]    $ListenPort = 8000
)

$ErrorActionPreference = 'Stop'
$TaskName = 'Vortis'

function Write-Info  ($msg) { Write-Host "[info]  $msg" -ForegroundColor Cyan }
function Write-Ok    ($msg) { Write-Host "[ok]    $msg" -ForegroundColor Green }
function Write-Warn2 ($msg) { Write-Host "[warn]  $msg" -ForegroundColor Yellow }
function Write-Fail  ($msg) {
    Write-Host "[fail]  $msg" -ForegroundColor Red
    exit 1
}

function Get-DefaultInstallRoot {
    if ($script:InstallRoot) { return $script:InstallRoot }
    if ($env:VORTIS_HOME) { return $env:VORTIS_HOME }
    return (Join-Path $env:LOCALAPPDATA 'Vortis')
}

function Install-Task {
    $root = Get-DefaultInstallRoot
    $srcDir = Join-Path $root 'src'
    if (-not (Test-Path $srcDir)) {
        Write-Fail "Vortis source not found at $srcDir. Run install.ps1 first."
    }

    $uvCmd = Get-Command uv -ErrorAction SilentlyContinue
    if (-not $uvCmd) {
        $uvFallback = Join-Path $env:USERPROFILE '.local\bin\uv.exe'
        if (Test-Path $uvFallback) {
            $uvPath = $uvFallback
        } else {
            Write-Fail "uv.exe not found on PATH or at $uvFallback. Re-run install.ps1."
        }
    } else {
        $uvPath = $uvCmd.Source
    }

    $isLoopback = ($ListenHost -eq '127.0.0.1' -or $ListenHost -eq 'localhost')
    if (-not $isLoopback -and -not $env:VORTIS_API_KEY) {
        Write-Fail @"
ListenHost is $ListenHost (non-loopback) but `$env:VORTIS_API_KEY is
not set. An unauthenticated non-loopback bind is refused by vortis serve
and would also create a security hole. Set the env var first:

    `$env:VORTIS_API_KEY = (uv run vortis auth generate-key)

then re-run with -ListenHost 0.0.0.0.
"@
    }

    if (-not $isLoopback) {
        Write-Info "Persisting VORTIS_API_KEY to User environment so the scheduled task can read it at logon."
        [System.Environment]::SetEnvironmentVariable(
            'VORTIS_API_KEY',
            $env:VORTIS_API_KEY,
            'User'
        )
    }

    Write-Info "Registering scheduled task '$TaskName'..."
    Write-Info "  Working dir : $srcDir"
    Write-Info "  Listen      : $ListenHost`:$ListenPort"
    Write-Info "  User        : $env:USERNAME"

    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Info "Existing task found - replacing."
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    }

    $action = New-ScheduledTaskAction `
        -Execute $uvPath `
        -Argument "run vortis serve --host $ListenHost --port $ListenPort" `
        -WorkingDirectory $srcDir

    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 1) `
        -ExecutionTimeLimit (New-TimeSpan -Seconds 0)

    $principal = New-ScheduledTaskPrincipal `
        -UserId $env:USERNAME `
        -LogonType Interactive `
        -RunLevel Limited

    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Description 'Vortis API server (loopback default - see deploy/windows/README.md)' | Out-Null

    Write-Ok "Task '$TaskName' registered."
    Write-Info "It will start automatically at next logon."
    Write-Info "To start it now: Start-ScheduledTask -TaskName $TaskName"
}

function Uninstall-Task {
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $existing) {
        Write-Warn2 "Task '$TaskName' is not registered - nothing to remove."
        return
    }
    Write-Info "Stopping '$TaskName' (if running)..."
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Write-Info "Unregistering '$TaskName'..."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Ok "Task '$TaskName' removed."
}

function Show-Status {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $task) {
        Write-Host "Task '$TaskName' is not registered."
        Write-Host "Install it with:"
        Write-Host "  powershell -ExecutionPolicy Bypass -File `"$PSCommandPath`" install"
        return
    }
    $info = Get-ScheduledTaskInfo -TaskName $TaskName
    Write-Host "Task    : $TaskName"
    Write-Host "State   : $($task.State)"
    Write-Host "LastRun : $($info.LastRunTime)"
    Write-Host "LastRes : 0x$('{0:X8}' -f $info.LastTaskResult)"
    Write-Host "NextRun : $($info.NextRunTime)"
}

switch ($Command) {
    'install'   { Install-Task }
    'uninstall' { Uninstall-Task }
    'status'    { Show-Status }
}
