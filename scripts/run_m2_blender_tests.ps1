param(
    [string]$Blender = "blender",
    [ValidateRange(1, 100)]
    [int]$Repeat = 1
)

$ErrorActionPreference = "Stop"
$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$IntegrationScript = Join-Path $RepositoryRoot "tests\integration\run_extension_ui_suite.py"
$OutputPath = Join-Path $RepositoryRoot "benchmarks\results\m2_blender_repeatability.json"
$VersionLine = (& $Blender --version | Select-Object -First 1)
$Runs = @()

for ($Index = 1; $Index -le $Repeat; $Index++) {
    $Started = Get-Date
    $RunOutput = & $Blender --background --factory-startup --python-exit-code 1 --python $IntegrationScript 2>&1
    $ExitCode = $LASTEXITCODE
    $Text = $RunOutput -join "`n"
    $Passed = (
        $ExitCode -eq 0 -and
        $Text -match 'BSA_UI_RESULT=' -and
        $Text -match '"move_instruction_passed": true' -and
        $Text -match '"unlock_instruction_passed": true' -and
        $Text -match '"ai_data_review_is_read_only": true'
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
    requested_runs = $Repeat
    completed_runs = $Runs.Count
    passed_runs = $PassedRuns
    all_passed = ($PassedRuns -eq $Repeat)
    runs = $Runs
}
$Summary | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $OutputPath -Encoding UTF8

if (-not $Summary.all_passed) {
    throw "Blender M2 repeatability gate failed after $PassedRuns successful run(s)"
}

Write-Output "BSA_M2_REPEATABILITY_RESULT=$PassedRuns/$Repeat passed"
