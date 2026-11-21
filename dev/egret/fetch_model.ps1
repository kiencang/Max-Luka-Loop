<#
.SYNOPSIS
    Downloads the pinned Egret Medium ONNX model into tools\models\ and verifies its SHA-256 (CI, release, dev).
.DESCRIPTION
    tools\models\ is not in git (78 MB). The model exported by dev\egret\export_onnx.py is published once as an
    asset of the GitHub release 'model-egret-medium-v1'; this script fetches it and refuses any file whose
    SHA-256 differs from the pinned value. To ship a new model: export it, upload it to a new model-* release,
    then update $Url and $Sha256 below in the same commit.
    Not part of the translation workflow. Compatible with Windows PowerShell 5.1 and PowerShell 7+.
#>
param(
    [string]$OutPath = '',
    [string]$Url = 'https://github.com/kiencang/Max-Luka-Loop/releases/download/model-egret-medium-v1/egret_medium.onnx',
    [string]$Sha256 = '06da7202c1fcfc9eb984830857c51c1e3993e8ba36a21f76c74d4c0756d1fbcc'
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
if (-not $OutPath -or -not $OutPath.Trim()) {
    $OutPath = Join-Path $repoRoot 'tools\models\egret_medium.onnx'
}
$expected = $Sha256.Trim().ToLowerInvariant()

function Get-Sha256Lower([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

if (Test-Path -LiteralPath $OutPath -PathType Leaf) {
    if ((Get-Sha256Lower $OutPath) -eq $expected) {
        Write-Output "Egret model already present and verified -> $OutPath"
        exit 0
    }
    Write-Warning "Existing model does not match the pinned SHA-256; downloading again: $OutPath"
}

$outDir = Split-Path $OutPath -Parent
[void][System.IO.Directory]::CreateDirectory($outDir)
$tmp = Join-Path $outDir ('egret_download_' + [Guid]::NewGuid().ToString('N') + '.part')
try {
    # Windows PowerShell 5.1 may default to TLS 1.0/1.1, which GitHub refuses.
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    Write-Output "Downloading Egret model from $Url ..."
    $prevProgress = $ProgressPreference
    $ProgressPreference = 'SilentlyContinue'  # the progress bar makes Invoke-WebRequest very slow on 5.1
    try {
        Invoke-WebRequest -Uri $Url -OutFile $tmp -UseBasicParsing
    } finally {
        $ProgressPreference = $prevProgress
    }
    $actual = Get-Sha256Lower $tmp
    if ($actual -ne $expected) {
        throw "SHA-256 mismatch for downloaded Egret model: expected $expected, got $actual ($Url)"
    }
    Move-Item -LiteralPath $tmp -Destination $OutPath -Force
    Write-Output ("Egret model verified -> {0} ({1:N0} bytes, sha256={2})" -f $OutPath, (Get-Item -LiteralPath $OutPath).Length, $actual)
} finally {
    if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue }
}
