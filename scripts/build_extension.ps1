param(
    [string]$Blender = "blender",
    [string]$OutputDirectory = "dist"
)

$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
& $Blender --command extension build --output-dir $OutputDirectory
if ($LASTEXITCODE -ne 0) {
    throw "Extension build failed with exit code $LASTEXITCODE"
}
