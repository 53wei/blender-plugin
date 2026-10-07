param(
    [string]$Blender = "blender",
    [ValidateRange(1, 100)]
    [int]$Repeat = 1
)

$ErrorActionPreference = "Stop"
$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$IntegrationScript = Join-Path $RepositoryRoot "tests\integration\run_m1_suite.py"
$OutputPath = Join-Path $RepositoryRoot "benchmarks\results\m1_blender_repeatability.json"
$VersionLine = (& $Blender --version | Select-Object -First 1)
$Runs = @()

for ($Index = 1; $Index -le $Repeat; $Index++) {
    $Started = Get-Date
    $RunOutput = & $Blender --background --factory-startup --python-exit-code 1 --python $IntegrationScript 2>&1
    $ExitCode = $LASTEXITCODE
    $RunOutput | Write-Output
    $Committed = (($RunOutput -join "`n") -match '"status": "COMMITTED"')
    $Runs += [PSCustomObject]@{
        run = $Index
        exit_code = $ExitCode
        committed = $Committed
        duration_ms = [Math]::Round(((Get-Date) - $Started).TotalMilliseconds, 1)
    }
    if ($ExitCode -ne 0 -or -not $Committed) {
        break
    }
}

$PassedRuns = @($Runs | Where-Object { $_.exit_code -eq 0 -and $_.committed }).Count
$Summary = [PSCustomObject]@{
    blender_version = $VersionLine
    requested_runs = $Repeat
    completed_runs = $Runs.Count
    passed_runs = $PassedRuns
    all_passed = ($PassedRuns -eq $Repeat)
    runs = $Runs
}
$Summary | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $OutputPath -Encoding UTF8

if (-not $Summary.all_passed) {
    throw "Blender M1 repeatability gate failed after $PassedRuns successful run(s)"
}

Write-Output "BSA_REPEATABILITY_RESULT=$PassedRuns/$Repeat passed"
