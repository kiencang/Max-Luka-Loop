<#
.SYNOPSIS
    Thin PowerShell wrapper forwarding fallback PDF page rendering and PNG cropping to extract_assets.exe.
.DESCRIPTION
    Provides -Action RenderPages and -Action CropFromJson by forwarding directly to
    tools\extract_assets\extract_assets.exe, which handles path safety, allowed-root checks, and imaging.
    Compatible with Windows PowerShell 5.1 and PowerShell 7+.
#>
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('RenderPages', 'CropFromJson')]
    [string]$Action,

    [string]$PdfPath = '',
    [string]$OutDir = '.',
    [ValidateRange(0.5, 10.0)]
    [double]$Scale = 2.5,
    [string]$Pages = '',
    [string]$SpecJson = ''
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

if ($Action -eq 'RenderPages') {
    if (-not $PdfPath -or -not $PdfPath.Trim()) {
        throw '-PdfPath is required for -Action RenderPages'
    }
    $scaleStr = $Scale.ToString([System.Globalization.CultureInfo]::InvariantCulture)
    $exeArgs = @('--mode', 'render-pages', "--out-dir=$OutDir", "--scale=$scaleStr")
    if ($Pages -and $Pages.Trim()) {
        $exeArgs += "--pages=$Pages"
    }
    $exeArgs += @('--', $PdfPath)
    Invoke-ExtractAssetsExe -Arguments $exeArgs
} else {
    if (-not $SpecJson -or -not $SpecJson.Trim()) {
        throw '-SpecJson is required for -Action CropFromJson'
    }
    Invoke-ExtractAssetsExe -Arguments @('--mode', 'crop-json', "--spec=$SpecJson", "--out-dir=$OutDir")
}
