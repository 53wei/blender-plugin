param(
    [string]$Blender = "blender",
    [ValidateRange(1, 100)]
    [int]$Repeat = 1,
    [string]$UserRoot = ""
)

$ErrorActionPreference = "Stop"
$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$IntegrationScript = Join-Path $RepositoryRoot "tests\integration\run_provider_ui_suite.py"
$OutputPath = Join-Path $RepositoryRoot "benchmarks\results\ai_blender_repeatability.json"
$VersionLine = (& $Blender --version | Select-Object -First 1)
$ManifestVersion = (Get-Content -LiteralPath (Join-Path $RepositoryRoot "blender_manifest.toml") | Where-Object { $_ -match '^version = ' }) -replace '^version = "|"$', ''

if ($UserRoot) {
    $ResolvedUserRoot = [System.IO.Path]::GetFullPath($UserRoot)
    $RepositoryPrefix = [System.IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\') + '\'
    if (-not $ResolvedUserRoot.StartsWith($RepositoryPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "UserRoot must stay inside the repository"
    }
    $env:BLENDER_USER_CONFIG = Join-Path $ResolvedUserRoot "config"
    $env:BLENDER_USER_SCRIPTS = Join-Path $ResolvedUserRoot "scripts"
    $env:BLENDER_USER_EXTENSIONS = Join-Path $ResolvedUserRoot "extensions"
    $env:BLENDER_USER_DATAFILES = Join-Path $ResolvedUserRoot "datafiles"
}

$Runs = @()
for ($Index = 1; $Index -le $Repeat; $Index++) {
    $Started = Get-Date
    $RunOutput = & $Blender --background --online-mode --python-exit-code 1 --python $IntegrationScript 2>&1
    $ExitCode = $LASTEXITCODE
    $Text = $RunOutput -join "`n"
    $Passed = (
        $ExitCode -eq 0 -and
        $Text -match 'BSA_PROVIDER_UI_RESULT=' -and
        $Text -match '"ai_data_review_required": true' -and
        $Text -match '"ai_plan_previewed_before_execution": true' -and
        $Text -match '"ai_plan_verified_after_confirmation": true' -and
        $Text -match '"ai_planning_cancel_is_read_only": true' -and
        $Text -match '"ai_stale_result_rejected": true' -and
        $Text -match '"trusted_action_preview_passed": true' -and
        $Text -match ('"extension_version": "' + [regex]::Escape($ManifestVersion) + '"') -and
        (-not $UserRoot -or $Text -match '"installed_package": true')
    )
    $Runs += [PSCustomObject]@{
        run = $Index
        exit_code = $ExitCode
        passed = $Passed
        duration_ms = [Math]::Round(((Get-Date) - $Started).TotalMilliseconds, 1)
    }
    if (-not $Passed) {
        $RunOutput | Write-Output
        break
    }
}

$PassedRuns = @($Runs | Where-Object { $_.passed }).Count
$Summary = [PSCustomObject]@{
    blender_version = $VersionLine
    installed_package = [bool]$UserRoot
    requested_runs = $Repeat
    completed_runs = $Runs.Count
    passed_runs = $PassedRuns
    all_passed = ($PassedRuns -eq $Repeat)
    runs = $Runs
}
$Summary | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $OutputPath -Encoding UTF8

if (-not $Summary.all_passed) {
    throw "Blender AI repeatability gate failed after $PassedRuns successful run(s)"
}

Write-Output "BSA_AI_REPEATABILITY_RESULT=$PassedRuns/$Repeat passed"
