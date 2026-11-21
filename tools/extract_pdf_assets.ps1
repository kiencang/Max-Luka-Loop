<#
.SYNOPSIS
    Thin PowerShell wrapper forwarding PDF extraction and transcript resolution to extract_assets.exe.
.DESCRIPTION
    Resolves the PDF (via -PdfPath or -TranscriptPath) and runs tools\extract_assets\extract_assets.exe
    with all path safety guards, manifest generation, and bounded stdout compaction handled natively.
    Compatible with Windows PowerShell 5.1 and PowerShell 7+.
#>
param(
    [string]$PdfPath = '',
    [string]$TranscriptPath = '',
    [string]$OutDir = 'work\assets',
    [ValidateRange(36, 1200)]
    [int]$Dpi = 180,
    [switch]$Meta,
    [ValidateRange(0, 10485760)]
    [int]$MaxMetaBytes = 16384,
    [ValidateRange(0, 1000)]
    [int]$MaxMetaWords = 20
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$pathGuardsScript = Join-Path $PSScriptRoot '_path_guards.ps1'
$pathGuardsItem = Get-Item -LiteralPath $pathGuardsScript -Force -ErrorAction SilentlyContinue
if (-not $pathGuardsItem -or $pathGuardsItem.PSIsContainer) {
    throw "Required helper script not found: $pathGuardsScript"
}
if ((($pathGuardsItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) -and ($pathGuardsItem.LinkType -in @('SymbolicLink', 'Junction'))) {
    throw "Refusing to dot-source symlink/junction: $pathGuardsScript"
}
. $pathGuardsScript

if (-not $PdfPath -and -not $TranscriptPath) {
    throw 'Either -PdfPath or -TranscriptPath must be provided.'
}

$exeArgs = @(
    '--mode', 'extract',
    "--out-dir=$OutDir",
    "--dpi=$Dpi",
    "--max-meta-bytes=$MaxMetaBytes",
    "--max-meta-words=$MaxMetaWords"
)
if ($Meta) {
    $exeArgs += @('--meta', '--stdout-meta')
}
if ($PdfPath -and $PdfPath.Trim()) {
    $exeArgs += '--print-resolved'
    $exeArgs += @('--', $PdfPath)
} else {
    $exeArgs += "--transcript=$TranscriptPath"
}

Invoke-ExtractAssetsExe -Arguments $exeArgs
