param(
    [string]$Configuration = "Release",
    [string]$Runtime = "win-x64",
    [string]$OutputDir = "publish",
    [switch]$BypassRelaunched
)

$ErrorActionPreference = "Stop"

if (-not $BypassRelaunched) {
    $powershellExe = if (Get-Command powershell -ErrorAction SilentlyContinue) { "powershell" } else { "pwsh" }
    $argumentList = @(
        "-ExecutionPolicy", "Bypass",
        "-File", ('"{0}"' -f $PSCommandPath),
        "-BypassRelaunched"
    )

    if ($Configuration -ne "Release") {
        $argumentList += @("-Configuration", ('"{0}"' -f $Configuration))
    }
    if ($Runtime -ne "win-x64") {
        $argumentList += @("-Runtime", ('"{0}"' -f $Runtime))
    }
    if ($OutputDir -ne "publish") {
        $argumentList += @("-OutputDir", ('"{0}"' -f $OutputDir))
    }

    $process = Start-Process -FilePath $powershellExe -ArgumentList $argumentList -Wait -PassThru -NoNewWindow
    exit $process.ExitCode
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectFile = Join-Path $scriptDir "DocUnlockCli.csproj"
$publishDir = Join-Path $scriptDir $OutputDir
$exePath = Join-Path $publishDir "DocUnlockCli.exe"
$zipPath = Join-Path $publishDir "DocUnlockCli-$Runtime.zip"

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
