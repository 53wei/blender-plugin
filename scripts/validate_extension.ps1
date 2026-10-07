param(
    [string]$Blender = "blender"
)

$ErrorActionPreference = "Stop"
& $Blender --command extension validate
if ($LASTEXITCODE -ne 0) {
    throw "Extension validation failed with exit code $LASTEXITCODE"
}
