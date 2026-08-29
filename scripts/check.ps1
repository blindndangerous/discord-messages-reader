<#
.SYNOPSIS
    Runs the full CI-equivalent check suite locally.

.DESCRIPTION
    Mirrors the checks performed by .github/workflows/ci.yml and
    .github/workflows/security.yml so failures are caught before pushing.

    Every check runs even if an earlier one fails, so a single run shows
    everything that is broken. A summary table is printed at the end and the
    script exits non-zero if any check failed.

    External scanners (osv-scanner) are looked up on PATH. No tool
    version is pinned here on purpose: the local run always uses whatever is
    installed. If a scanner is missing the check is reported as SKIPPED with a
    loud, explicit banner -- it is never skipped silently.

.EXAMPLE
    powershell -NoProfile -File scripts/check.ps1
#>

[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Always operate from the repository root, whatever the caller's cwd is.
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $RepoRoot

$Rule = '-' * 72
$Results = New-Object System.Collections.ArrayList

function Add-Result {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$Status,
        [Parameter(Mandatory)][string]$Detail
    )
    $null = $Results.Add([pscustomobject]@{
            Name   = $Name
            Status = $Status
            Detail = $Detail
        })
}

function Invoke-Check {
    <#
        Runs one check. $Executable must be resolvable on PATH; if it is not,
        the check is reported as SKIPPED rather than FAILED.
    #>
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$Executable,
        [Parameter(Mandatory)][AllowEmptyCollection()][string[]]$CommandArgs,
        [string]$InstallHint = ''
    )

    $display = "$Executable $($CommandArgs -join ' ')"

    Write-Host ''
    Write-Host $Rule
    Write-Host "CHECK: $Name"
    Write-Host "  > $display"
    Write-Host $Rule

    if (-not (Get-Command $Executable -CommandType Application -ErrorAction SilentlyContinue)) {
        Write-Host ''
        Write-Host '########################################################################'
        Write-Host "#  SKIPPED - $Executable not installed"
        Write-Host "#  Check '$Name' did NOT run. It was not verified."
        if ($InstallHint) {
            Write-Host "#  Install it with: $InstallHint"
        }
        Write-Host '########################################################################'
        Write-Host ''
        Add-Result -Name $Name -Status 'SKIP' -Detail "$Executable not installed"
        return
    }

    $started = Get-Date
    # Native commands signal failure through the exit code, not exceptions, so
    # relax the error preference here and read $LASTEXITCODE explicitly.
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        if ($CommandArgs.Count -gt 0) {
            & $Executable @CommandArgs
        }
        else {
            & $Executable
        }
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
    $elapsed = '{0:N1}s' -f ((Get-Date) - $started).TotalSeconds

    if ($exitCode -eq 0) {
        Write-Host ""
        Write-Host "[ PASS ] $Name ($elapsed)"
        Add-Result -Name $Name -Status 'PASS' -Detail $elapsed
    }
    else {
        Write-Host ""
        Write-Host "[ FAIL ] $Name (exit code $exitCode, $elapsed)"
        Add-Result -Name $Name -Status 'FAIL' -Detail "exit $exitCode after $elapsed"
    }
}

Write-Host $Rule
Write-Host 'Local CI-equivalent check suite'
Write-Host "Repository: $RepoRoot"
Write-Host 'All checks run; failures are collected and summarised at the end.'
Write-Host $Rule

# --- Mirrors .github/workflows/ci.yml -----------------------------------
Invoke-Check -Name 'ruff check' `
    -Executable 'uv' -CommandArgs @('run', '--locked', 'ruff', 'check', '.') `
    -InstallHint 'winget install astral-sh.uv'

Invoke-Check -Name 'ruff format --check' `
    -Executable 'uv' -CommandArgs @('run', '--locked', 'ruff', 'format', 'build.py', 'tests/', '--check') `
    -InstallHint 'winget install astral-sh.uv'

Invoke-Check -Name 'mypy' `
    -Executable 'uv' -CommandArgs @('run', '--locked', 'mypy', 'appModules/discord/') `
    -InstallHint 'winget install astral-sh.uv'

Invoke-Check -Name 'pytest' `
    -Executable 'uv' -CommandArgs @('run', '--locked', 'pytest', '--tb=short') `
    -InstallHint 'winget install astral-sh.uv'

Invoke-Check -Name 'bandit' `
    -Executable 'uv' -CommandArgs @('run', '--locked', 'bandit', '-r', 'appModules/', '-c', 'pyproject.toml') `
    -InstallHint 'winget install astral-sh.uv'

Invoke-Check -Name 'pip-audit' `
    -Executable 'uv' -CommandArgs @('run', '--locked', 'pip-audit') `
    -InstallHint 'winget install astral-sh.uv'

# --- Mirrors .github/workflows/security.yml -----------------------------
Invoke-Check -Name 'zizmor' `
    -Executable 'uv' -CommandArgs @('run', '--locked', 'zizmor', '--persona=regular', '.github/workflows/') `
    -InstallHint 'winget install astral-sh.uv'

Invoke-Check -Name 'osv-scanner' `
    -Executable 'osv-scanner' -CommandArgs @('scan', 'source', '--lockfile=uv.lock', '--config=osv-scanner.toml') `
    -InstallHint 'winget install Google.OSVScanner'

# --- Summary ------------------------------------------------------------
$passed = @($Results | Where-Object { $_.Status -eq 'PASS' }).Count
$failed = @($Results | Where-Object { $_.Status -eq 'FAIL' }).Count
$skipped = @($Results | Where-Object { $_.Status -eq 'SKIP' }).Count

$nameWidth = ($Results | ForEach-Object { $_.Name.Length } | Measure-Object -Maximum).Maximum
if ($nameWidth -lt 6) { $nameWidth = 6 }

Write-Host ''
Write-Host $Rule
Write-Host 'SUMMARY'
Write-Host $Rule
foreach ($result in $Results) {
    $label = $result.Name.PadRight($nameWidth)
    Write-Host ("  [ {0} ] {1}  {2}" -f $result.Status.PadRight(4), $label, $result.Detail)
}
Write-Host $Rule
Write-Host "  $passed passed, $failed failed, $skipped skipped, $($Results.Count) total"

if ($skipped -gt 0) {
    Write-Host ''
    Write-Host "  WARNING: $skipped check(s) were SKIPPED and are NOT verified locally."
    Write-Host '  CI will still run them. See the SKIPPED banners above.'
}

if ($failed -gt 0) {
    Write-Host ''
    Write-Host "  RESULT: FAIL - $failed check(s) failed. Fix them before pushing."
    Write-Host $Rule
    exit 1
}

Write-Host ''
Write-Host '  RESULT: PASS - all executed checks succeeded.'
Write-Host $Rule
exit 0
