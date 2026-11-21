<#
.SYNOPSIS
    Builds tools\extract_assets\extract_assets.exe from tools\src\extract_assets.py via PyInstaller (CI & dev tool).
.DESCRIPTION
    Shared single-source build script used both locally by developers and on GitHub Actions (windows-latest).
    Not called during normal PDF translation workflows. Compatible with Windows PowerShell 5.1 and PowerShell 7+.
#>
param(
    [string]$OutDir = '',
    [string]$PythonExe = 'python',
    # CI/release: fail instead of warning when tools\models\egret_medium.onnx is missing
    # (fetch it first with dev\egret\fetch_model.ps1). The product cannot extract figures without it.
    [switch]$RequireEgretModel
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

$srcScript = Join-Path $PSScriptRoot 'src\extract_assets.py'
if (-not (Test-Path -LiteralPath $srcScript -PathType Leaf)) {
    throw "Build source not found: $srcScript"
}
$absSrc = (Resolve-Path -LiteralPath $srcScript).Path

$rawOutDir = if ($OutDir -and $OutDir.Trim()) { $OutDir } else { Join-Path $PSScriptRoot 'extract_assets' }
$absOutDir = Resolve-SafeOutDirectory -OutDir $rawOutDir -ParamName '-OutDir'

$tempBase = if ($env:TEMP -and $env:TEMP.Trim()) { $env:TEMP } else { [System.IO.Path]::GetTempPath() }
$stageRoot = Join-Path $tempBase ("max_luka_pyi_build_" + [Guid]::NewGuid().ToString("N"))
Assert-SafeOutputPath -TargetPath $stageRoot -Label 'TempBuildRoot' -IsDirectory
[void][System.IO.Directory]::CreateDirectory($stageRoot)

$prevUtf8 = $env:PYTHONUTF8
$prevNoPyc = $env:PYTHONDONTWRITEBYTECODE
try {
    $env:PYTHONUTF8 = '1'
    $env:PYTHONDONTWRITEBYTECODE = '1'

    & $PythonExe -m PyInstaller --version | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller not available under '$PythonExe'. Install build deps via: pip install -r tools\src\requirements-build.txt"
    }

    $distDir = Join-Path $stageRoot 'dist'
    $workDir = Join-Path $stageRoot 'work'
    $specDir = Join-Path $stageRoot 'spec'
    # numpy and ctypes stay in: onnxruntime (Egret detector) needs both.
    # yaml: PyInstaller picks PyYAML up from onnxruntime's optional tooling when it happens to be installed
    # (e.g. a dev venv that also has transformers); the extractor never uses it, so builds match CI.
    $excludes = @(
        'PIL', 'tkinter', 'matplotlib', 'scipy', 'pandas', 'cv2', 'unittest',
        'fontTools', 'lxml', 'setuptools', 'pkg_resources', 'torch', 'transformers', 'yaml',
        'multiprocessing', 'ssl', 'xml'
    )
    $srcDir = Join-Path $PSScriptRoot 'src'
    $pyiArgs = @(
        '-m', 'PyInstaller',
        '--noconfirm', '--clean', '--onedir',
        '--name', 'extract_assets',
        '--paths', $srcDir,
        '--hidden-import', 'pymupdf',
        '--hidden-import', 'onnxruntime',
        '--hidden-import', 'figure_detector.egret',
        '--distpath', $distDir,
        '--workpath', $workDir,
        '--specpath', $specDir
    )
    # Egret Medium ONNX model (exported by dev\egret\export_onnx.py) ships inside _internal\models\.
    $egretModel = Join-Path $PSScriptRoot 'models\egret_medium.onnx'
    if (Test-Path -LiteralPath $egretModel -PathType Leaf) {
        $egretItem = Get-Item -LiteralPath $egretModel -Force
        if (Test-IsReparsePoint -Item $egretItem) {
            throw "Refusing to bundle symlink/junction model: $egretModel"
        }
        $pyiArgs += @('--add-data', ((Resolve-Path -LiteralPath $egretModel).Path + ';models'))
    } elseif ($RequireEgretModel) {
        throw "Egret model not found: $egretModel. Run dev\egret\fetch_model.ps1 (or export it with dev\egret\export_onnx.py) before building."
    } else {
        Write-Warning "Egret model not found ($egretModel): building without it; figure extraction will stop with an error at runtime."
    }
    foreach ($mod in $excludes) {
        $pyiArgs += @('--exclude-module', $mod)
    }
    $pyiArgs += $absSrc

    Write-Output "Building extract_assets.exe from $absSrc..."
    & $PythonExe @pyiArgs
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE"
    }

    $builtDir = Join-Path $distDir 'extract_assets'
    $builtExe = Join-Path $builtDir 'extract_assets.exe'
    if (-not (Test-Path -LiteralPath $builtExe -PathType Leaf)) {
        throw "PyInstaller build did not produce expected executable: $builtExe"
    }

    & $builtExe --help | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Smoke check (--help) failed on built executable: $builtExe"
    }

    if (Test-Path -LiteralPath $absOutDir) {
        Remove-Item -LiteralPath $absOutDir -Recurse -Force
    }
    $parentOut = Split-Path $absOutDir -Parent
    if ($parentOut -and -not (Test-Path -LiteralPath $parentOut -PathType Container)) {
        [void][System.IO.Directory]::CreateDirectory($parentOut)
    }
    Copy-Item -LiteralPath $builtDir -Destination $absOutDir -Recurse -Force

    $stats = Get-ChildItem -LiteralPath $absOutDir -Recurse -File | Measure-Object -Property Length -Sum
    Write-Output ("Built extract_assets -> {0} ({1} files, {2:N0} bytes)" -f $absOutDir, $stats.Count, $stats.Sum)
} finally {
    if ($null -eq $prevUtf8) { Remove-Item Env:PYTHONUTF8 -ErrorAction SilentlyContinue } else { $env:PYTHONUTF8 = $prevUtf8 }
    if ($null -eq $prevNoPyc) { Remove-Item Env:PYTHONDONTWRITEBYTECODE -ErrorAction SilentlyContinue } else { $env:PYTHONDONTWRITEBYTECODE = $prevNoPyc }
    Remove-Item -LiteralPath $stageRoot -Recurse -Force -ErrorAction SilentlyContinue
}
