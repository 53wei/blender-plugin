param(
    [string]$Blender = "blender"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$UiScript = Join-Path $Root "tests\integration\run_adapter_plate_ui_suite.py"
$AiScript = Join-Path $Root "tests\integration\run_print_intent_provider_suite.py"

& $Blender --background --factory-startup --python-exit-code 1 --python $UiScript
if ($LASTEXITCODE -ne 0) {
    throw "Blender 转接板界面集成测试失败"
}

& $Blender --background --factory-startup --online-mode --python-exit-code 1 --python $AiScript
if ($LASTEXITCODE -ne 0) {
    throw "Blender 打印件 AI 需求集成测试失败"
}

