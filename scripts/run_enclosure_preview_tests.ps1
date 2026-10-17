param(
    [string]$Blender = "blender",
    [string]$Output = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Script = Join-Path $Root "tests\integration\run_enclosure_preview_suite.py"

if ($Output) {
    $env:BSA_ENCLOSURE_PREVIEW_OUTPUT = $Output
}

& $Blender --background --factory-startup --python-exit-code 1 --python $Script
if ($LASTEXITCODE -ne 0) {
    throw "Blender 外壳装配预览集成测试失败"
}
