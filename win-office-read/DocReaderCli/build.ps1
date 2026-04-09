param(
    [string]$Configuration = "Release",
    [string]$Runtime = "win-x64",
    [string]$OutputDir = "publish"
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectFile = Join-Path $scriptDir "DocReaderCli.csproj"
$publishDir = Join-Path $scriptDir $OutputDir
$exePath = Join-Path $publishDir "DocReaderCli.exe"
$zipPath = Join-Path $publishDir "DocReaderCli-$Runtime.zip"

Write-Host "==> Restoring dependencies"
dotnet restore $projectFile

Write-Host "==> Publishing single-file binary"
dotnet publish $projectFile -c $Configuration -r $Runtime --self-contained true `
    -p:PublishSingleFile=true `
    -p:EnableCompressionInSingleFile=true `
    -p:IncludeNativeLibrariesForSelfExtract=true `
    -p:IncludeAllContentForSelfExtract=true `
    -o $publishDir

if (-not (Test-Path $exePath)) {
    throw "Build output not found: $exePath"
}

Write-Host "==> Creating release zip"
Compress-Archive -Path $exePath -DestinationPath $zipPath -Force

Write-Host "==> Build complete"
Write-Host "Executable: $exePath"
Write-Host "Zip: $zipPath"
