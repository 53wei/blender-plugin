param(
    [string]$Blender = "blender",
    [string]$Output = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Script = Join-Path $Root "tests\integration\run_adapter_plate_mesh_suite.py"

if ($Output) {
    $env:BSA_ADAPTER_PLATE_OUTPUT = $Output
}

& $Blender --background --factory-startup --python-exit-code 1 --python $Script
if ($LASTEXITCODE -ne 0) {
    throw "Blender 转接板真实网格集成测试失败"
}
