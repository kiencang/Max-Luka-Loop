<#
.SYNOPSIS
    Unified test runner for Max Luka Loop (PowerShell suite by default; optional -IncludePython for dev).
.EXAMPLE
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests\run_tests.ps1
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests\run_tests.ps1 -IncludePython
#>
param(
    [switch]$IncludePython
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$psSuite = Join-Path $PSScriptRoot 'test_powershell.ps1'
if (-not (Test-Path -LiteralPath $psSuite -PathType Leaf)) {
    throw "Missing PowerShell test suite: $psSuite"
}

$psExe = (Get-Process -Id $PID).Path
if (-not $psExe) {
    $psExe = if ($PSVersionTable.PSEdition -eq 'Core') { 'pwsh.exe' } else { 'powershell.exe' }
}

Write-Output ">>> Running PowerShell unit & integration suite ($psExe, Zero system Python)..."
& $psExe -NoProfile -ExecutionPolicy Bypass -File $psSuite
if ($LASTEXITCODE -ne 0) {
    throw "PowerShell test suite failed with exit code $LASTEXITCODE"
}

if ($IncludePython) {
    Write-Output ''
    Write-Output '>>> Running Python dev unit suite (tests\test_extract_assets.py)...'
    $pyCmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pyCmd) {
        throw 'System python executable not found (required when -IncludePython is specified).'
    }
    $prevUtf8 = $env:PYTHONUTF8
    $prevPyc = $env:PYTHONDONTWRITEBYTECODE
    $pyExit = 0
    try {
        $env:PYTHONUTF8 = '1'
        $env:PYTHONDONTWRITEBYTECODE = '1'
        & $pyCmd.Source -m unittest discover -s $PSScriptRoot -p 'test_*.py' -v
        $pyExit = $LASTEXITCODE
    } finally {
        if ($null -eq $prevUtf8) { Remove-Item Env:PYTHONUTF8 -ErrorAction SilentlyContinue } else { $env:PYTHONUTF8 = $prevUtf8 }
        if ($null -eq $prevPyc) { Remove-Item Env:PYTHONDONTWRITEBYTECODE -ErrorAction SilentlyContinue } else { $env:PYTHONDONTWRITEBYTECODE = $prevPyc }
    }
    if ($pyExit -ne 0) {
        throw "Python unit test suite failed with exit code $pyExit"
    }
}

Write-Output ''
Write-Output 'ALL TEST SUITES PASSED.'
