<#
.SYNOPSIS
    Shared path safety, reparse-point guards, and extract_assets.exe runner for PowerShell 5.1 & 7+ scripts in tools\.
.DESCRIPTION
    Dot-sourced by extract_pdf_assets.ps1, pdf_fallback_tools.ps1, and html_packager.ps1.
    Kept in tools\ so $PSScriptRoot-based workspace root and tool binary resolution remain consistent.
#>

function Test-IsReparsePoint {
    <# Returns True for filesystem links (SymbolicLink/Junction), ignoring OS cloud-sync placeholders (OneDrive/Dropbox/iCloud). #>
    param([System.IO.FileSystemInfo]$Item)
    if ($null -eq $Item) { return $false }
    if (($Item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -eq 0) { return $false }
    return ($Item.LinkType -in @('SymbolicLink', 'Junction'))
}

function Test-HasCloudPlaceholderFiles {
    <# Detects Windows Cloud Filter offline/recall placeholder attributes (Offline | RecallOnOpen | RecallOnDataAccess = 0x441000). #>
    param([string]$DirectoryPath)
    if (-not $DirectoryPath -or -not (Test-Path -LiteralPath $DirectoryPath -PathType Container)) { return $false }
    foreach ($f in (Get-ChildItem -LiteralPath $DirectoryPath -Recurse -Force -File -ErrorAction SilentlyContinue)) {
        if (([int]$f.Attributes -band 0x441000) -ne 0) {
            return $true
        }
    }
    return $false
}

function Assert-SafeOutputPath {
    <# Blocks symlinks/junctions (ReparsePoint) on output directory/file and workspace/temp ancestors. #>
    param(
        [string]$TargetPath,
        [string]$Label = 'OutputPath',
        [switch]$IsDirectory
    )
    if (-not $TargetPath -or -not $TargetPath.Trim()) { return }

    [System.Management.Automation.ProviderInfo]$provider = $null
    [System.Management.Automation.PSDriveInfo]$drive = $null
    $resolved = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($TargetPath, [ref]$provider, [ref]$drive)
    if ($null -eq $provider -or $provider.Name -ne 'FileSystem') {
        throw "Refusing non-filesystem path for ${Label}: $TargetPath"
    }
    $normTarget = [System.IO.Path]::GetFullPath($resolved).TrimEnd('\', '/')

    $anchors = New-Object 'System.Collections.Generic.List[string]'
    $anchorCandidates = @((Split-Path $PSScriptRoot -Parent))
    $loc = Get-Location
    if ($loc.Provider.Name -eq 'FileSystem') { $anchorCandidates += $loc.ProviderPath }
    if ($env:TEMP -and $env:TEMP.Trim()) { $anchorCandidates += $env:TEMP }
    foreach ($ac in $anchorCandidates) {
        if (-not $ac) { continue }
        $na = [System.IO.Path]::GetFullPath($ac).TrimEnd('\', '/')
        if ($na -and ($anchors -notcontains $na)) { [void]$anchors.Add($na) }
    }

    $matchedAnchor = $null
    foreach ($a in $anchors) {
        if ($normTarget.StartsWith($a + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
            if (-not $matchedAnchor -or $a.Length -gt $matchedAnchor.Length) {
                $matchedAnchor = $a
            }
        }
    }

    if ($matchedAnchor) {
        $rel = $normTarget.Substring($matchedAnchor.Length).TrimStart('\', '/')
        $probe = $matchedAnchor
        foreach ($seg in ($rel -split '[\\/]+')) {
            if (-not $seg) { continue }
            $probe = Join-Path $probe $seg
            $item = Get-Item -LiteralPath $probe -Force -ErrorAction SilentlyContinue
            if ($item -and (Test-IsReparsePoint -Item $item)) {
                throw "Refusing to write through symlink/junction (ReparsePoint) for ${Label}: $probe"
            }
        }
    } else {
        $cursor = $normTarget
        $driveRoot = [System.IO.Path]::GetPathRoot($normTarget).TrimEnd('\', '/')
        while ($cursor -and -not $cursor.Equals($driveRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
            $item = Get-Item -LiteralPath $cursor -Force -ErrorAction SilentlyContinue
            if ($item -and (Test-IsReparsePoint -Item $item)) {
                throw "Refusing to write through symlink/junction (ReparsePoint) for ${Label}: $cursor"
            }
            $parent = Split-Path $cursor -Parent
            if (-not $parent -or $parent -eq $cursor) { break }
            $cursor = $parent.TrimEnd('\', '/')
        }
    }

    $leaf = Get-Item -LiteralPath $normTarget -Force -ErrorAction SilentlyContinue
    if ($leaf) {
        if (Test-IsReparsePoint -Item $leaf) {
            throw "Refusing to overwrite symlink/junction (ReparsePoint) for ${Label}: $normTarget"
        }
        if ($IsDirectory -and -not $leaf.PSIsContainer) {
            throw "Expected directory path for ${Label}, found file: $normTarget"
        }
        if (-not $IsDirectory -and $leaf.PSIsContainer) {
            throw "Expected file path for ${Label}, found directory: $normTarget"
        }
    }
}

function Assert-LocalNoUncPath {
    param([string]$PathValue, [string]$ParamName = 'Path')
    if (-not $PathValue) { return }
    $t = $PathValue.Trim()
    if ($t -match '^(?i)file://[^/]' -or
        $t -match '^(?i)(?:Microsoft\.PowerShell\.Core\\)?FileSystem::(?:\\\\|//)' -or
        $t -match '^(?:\\\\|//)') {
        throw "Refusing UNC/network path for ${ParamName}: $PathValue"
    }
    if ([System.IO.Path]::IsPathRooted($t)) {
        try {
            $u = [System.Uri]$t
            if ($u.IsUnc) {
                throw "Refusing UNC/network path for ${ParamName}: $PathValue"
            }
        } catch [System.UriFormatException] {}
    }
    if ($t -notmatch '^(?i)https?://') {
        $adsCheck = $t -replace '^(?i)(?:Microsoft\.PowerShell\.Core\\)?FileSystem::', ''
        if ($adsCheck -match '^(?i)file:///') {
            $adsCheck = [System.Uri]::UnescapeDataString(($adsCheck -replace '^(?i)file:///', ''))
        }
        $adsBody = if ($adsCheck -match '^[A-Za-z]:') { $adsCheck.Substring(2) } else { $adsCheck }
        if ($adsBody.Contains(':')) {
            throw "Refusing NTFS Alternate Data Stream / colon in path for ${ParamName}: $PathValue"
        }
    }
}

function Resolve-SafeOutDirectory {
    <# Validates output directory path against UNC/reparse points, optionally creating it. #>
    param(
        [string]$OutDir,
        [string]$ParamName = '-OutDir',
        [switch]$Create
    )
    if (-not $OutDir -or -not $OutDir.Trim()) {
        throw "$ParamName cannot be empty."
    }
    Assert-LocalNoUncPath -PathValue $OutDir -ParamName $ParamName
    $outDirFull = [System.IO.Path]::GetFullPath($ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutDir)).TrimEnd('\', '/')
    Assert-LocalNoUncPath -PathValue $outDirFull -ParamName $ParamName
    Assert-SafeOutputPath -TargetPath $outDirFull -Label $ParamName -IsDirectory
    if (Test-Path -LiteralPath $outDirFull -PathType Container) {
        foreach ($entry in (New-Object System.IO.DirectoryInfo($outDirFull)).GetFileSystemInfos()) {
            if (Test-IsReparsePoint -Item $entry) {
                throw "Refusing to write into $ParamName containing symlink/junction: $($entry.FullName)"
            }
        }
    } elseif ($Create) {
        [void][System.IO.Directory]::CreateDirectory($outDirFull)
    }
    if (Test-Path -LiteralPath $outDirFull -PathType Container) {
        return (Resolve-Path -LiteralPath $outDirFull).Path
    }
    return $outDirFull
}

function Test-UsesLegacyNativeArgPassing {
    <# True when this host joins native-command arguments without escaping trailing backslashes (PS 5.1, PS 7.0-7.2, or Legacy mode). #>
    if ($PSVersionTable.PSEdition -eq 'Desktop') { return $true }
    $mode = Get-Variable -Name PSNativeCommandArgumentPassing -ValueOnly -ErrorAction SilentlyContinue
    return ($null -eq $mode -or "$mode" -eq 'Legacy')
}

function ConvertTo-NativeArgument {
    <#
    Prepares one argument for legacy native-command passing. Legacy hosts wrap an argument containing
    whitespace in double quotes but leave trailing backslashes alone, so 'C:\my dir\' becomes "C:\my dir\"
    and the closing quote is read as an escaped literal quote, swallowing every later argument.
    Doubling the trailing backslashes makes the native parser read them back as the original backslashes.
    #>
    param([AllowEmptyString()][string]$Value)
    if ($Value -match '\s' -and $Value -match '(\\+)$') {
        return $Value + $Matches[1]
    }
    return $Value
}

function Invoke-ExtractAssetsExe {
    <# Resolves tools\extract_assets\extract_assets.exe safely, sets UTF-8 stdio env vars, executes it, and verifies exit code. #>
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )
    $exeDir = Join-Path $PSScriptRoot 'extract_assets'
    $exePath = Join-Path $exeDir 'extract_assets.exe'
    if (-not (Test-Path -LiteralPath $exePath -PathType Leaf)) {
        throw "Extractor executable not found: $exePath. Download the ready-to-use package (max-luka-loop-win-x64.zip) from GitHub Releases or run tools\build_extractor.ps1 for local dev builds."
    }
    $dirItem = Get-Item -LiteralPath $exeDir -Force -ErrorAction SilentlyContinue
    if ($dirItem -and (Test-IsReparsePoint -Item $dirItem)) {
        throw "Refusing to execute through symlink/junction: $exeDir"
    }
    $exeItem = Get-Item -LiteralPath $exePath -Force -ErrorAction SilentlyContinue
    if ($exeItem -and (Test-IsReparsePoint -Item $exeItem)) {
        throw "Refusing to execute symlink/junction: $exePath"
    }

    $hasCloudPlaceholders = Test-HasCloudPlaceholderFiles -DirectoryPath $exeDir
    if ($hasCloudPlaceholders) {
        Write-Warning "One or more files in tools\extract_assets\ are cloud placeholders (not yet downloaded offline). If execution fails, enable 'Always keep on this device' / 'Available offline' for this folder."
    }

    $prevPythonUtf8 = $env:PYTHONUTF8
    $prevPythonIoEnc = $env:PYTHONIOENCODING
    $exeExit = 0
    $nativeArgs = if (Test-UsesLegacyNativeArgPassing) {
        @($Arguments | ForEach-Object { ConvertTo-NativeArgument -Value $_ })
    } else {
        $Arguments
    }
    try {
        $env:PYTHONUTF8 = '1'
        $env:PYTHONIOENCODING = 'utf-8'
        & $exePath @nativeArgs
        $exeExit = $LASTEXITCODE
    } finally {
        if ($null -eq $prevPythonUtf8) { Remove-Item Env:PYTHONUTF8 -ErrorAction SilentlyContinue } else { $env:PYTHONUTF8 = $prevPythonUtf8 }
        if ($null -eq $prevPythonIoEnc) { Remove-Item Env:PYTHONIOENCODING -ErrorAction SilentlyContinue } else { $env:PYTHONIOENCODING = $prevPythonIoEnc }
    }
    if ($exeExit -ne 0) {
        $hint = if ($hasCloudPlaceholders) { " (Cloud placeholder files detected in tools\extract_assets\; enable 'Always keep on this device' / 'Available offline'.)" } else { "" }
        throw "extract_assets.exe failed with exit code $exeExit$hint"
    }
}
