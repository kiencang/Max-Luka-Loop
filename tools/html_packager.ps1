<#
.SYNOPSIS
    Thin PowerShell wrapper forwarding HTML image embedding, QA, reader shell injection, and PDF export to extract_assets.exe.
.DESCRIPTION
    Forwards -Action EmbedImages and -Action HtmlToPdf directly to tools\extract_assets\extract_assets.exe,
    which performs in-memory image optimization, Base64 embedding, Auto-QA, headless Edge/Chrome PDF export,
    and safe work directory cleanup with zero temp image files or PowerShell memory overhead.
    Compatible with Windows PowerShell 5.1 and PowerShell 7+.
#>
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('EmbedImages', 'HtmlToPdf')]
    [string]$Action,

    [Parameter(Mandatory = $true)]
    [string]$HtmlPath,

    [string]$OutHtmlPath = '',
    [string]$OutPdfPath = '',
    [switch]$AlsoPdf,
    [switch]$PreserveLayout,

    [ValidateRange(1, 100)]
    [int]$JpegQuality = 95,

    [ValidateRange(0, 10000)]
    [int]$MaxImageWidth = 1400,

    [string]$CleanDir = '',

    [ValidateRange(5, 600)]
    [int]$PdfTimeoutSeconds = 60
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

if ($Action -eq 'EmbedImages') {
    $exeArgs = @(
        '--mode', 'embed-images',
        "--html=$HtmlPath",
        "--quality=$JpegQuality",
        "--max-width=$MaxImageWidth",
        "--timeout-seconds=$PdfTimeoutSeconds"
    )
    if ($OutHtmlPath -and $OutHtmlPath.Trim()) {
        $exeArgs += "--out-html=$OutHtmlPath"
    }
    if ($OutPdfPath -and $OutPdfPath.Trim()) {
        $exeArgs += "--out-pdf=$OutPdfPath"
    }
    if ($AlsoPdf) {
        $exeArgs += '--also-pdf'
    }
    if ($PreserveLayout) {
        $exeArgs += '--preserve-layout'
    }
    if ($CleanDir -and $CleanDir.Trim()) {
        $exeArgs += "--clean-dir=$CleanDir"
    }
    Invoke-ExtractAssetsExe -Arguments $exeArgs
} else {
    $exeArgs = @(
        '--mode', 'html-to-pdf',
        "--html=$HtmlPath",
        "--timeout-seconds=$PdfTimeoutSeconds"
    )
    if ($OutPdfPath -and $OutPdfPath.Trim()) {
        $exeArgs += "--out-pdf=$OutPdfPath"
    }
    if ($CleanDir -and $CleanDir.Trim()) {
        $exeArgs += "--clean-dir=$CleanDir"
    }
    Invoke-ExtractAssetsExe -Arguments $exeArgs
}
