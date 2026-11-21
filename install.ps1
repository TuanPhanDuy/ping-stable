# Install pingstable on Windows:
#   irm https://github.com/TuanPhanDuy/ping-stable/releases/latest/download/install.ps1 | iex
# ASCII only: irm | iex may not decode the script as UTF-8.
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$Repo = "TuanPhanDuy/ping-stable"
$Version = if ($env:PINGSTABLE_VERSION) { $env:PINGSTABLE_VERSION } else { "latest" }
$Base = if ($Version -eq "latest") { "https://github.com/$Repo/releases/latest/download" } else { "https://github.com/$Repo/releases/download/$Version" }
$Dir = if ($env:PINGSTABLE_DIR) { $env:PINGSTABLE_DIR } else { Join-Path $env:LOCALAPPDATA "pingstable" }
$Exe = Join-Path $Dir "pingstable.exe"

[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
New-Item -ItemType Directory -Force -Path $Dir | Out-Null

Write-Host "Downloading pingstable-windows-x64.exe..."
Invoke-WebRequest -Uri "$Base/pingstable-windows-x64.exe" -OutFile $Exe -UseBasicParsing

$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (-not (($UserPath -split ";") -contains $Dir)) {
    $NewPath = if ($UserPath) { "$UserPath;$Dir" } else { $Dir }
    [Environment]::SetEnvironmentVariable("Path", $NewPath, "User")
    $env:Path = "$env:Path;$Dir"
    Write-Host "Added $Dir to your user PATH (open a new terminal to use it everywhere)."
}

Write-Host "Installed: $Exe ($(& $Exe --version))"
Write-Host "Try: pingstable wifi"
