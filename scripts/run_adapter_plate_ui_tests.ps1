param(
    [string]$Blender = "blender"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Script = Join-Path $Root "tests\integration\run_adapter_plate_ui_suite.py"

& $Blender --background --factory-startup --python-exit-code 1 --python $Script
if ($LASTEXITCODE -ne 0) {
    throw "Blender 转接板界面集成测试失败"
}

