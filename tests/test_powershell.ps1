<#
.SYNOPSIS
    Zero-dependency PowerShell 5.1 & 7+ unit & integration test suite for Max Luka Loop tools\.
.DESCRIPTION
    Tests tools\_path_guards.ps1, tools\extract_pdf_assets.ps1, tools\pdf_fallback_tools.ps1,
    tools\html_packager.ps1, and bundled extract_assets.exe without requiring system Python,
    System.Drawing, WinRT, or Pester.
#>
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$script:CurrentPsExe = (Get-Process -Id $PID).Path
if (-not $script:CurrentPsExe) {
    $script:CurrentPsExe = if ($PSVersionTable.PSEdition -eq 'Core') { 'pwsh.exe' } else { 'powershell.exe' }
}

$repoRoot = Split-Path $PSScriptRoot -Parent
$toolsDir = Join-Path $repoRoot 'tools'
$script:Passed = 0
$script:Failed = 0

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw "Assertion failed: $Message" }
}

function Assert-Equal {
    param($Expected, $Actual, [string]$Message)
    if ($Expected -ne $Actual) {
        throw "Assertion failed ($Message): expected [$Expected], got [$Actual]"
    }
}

function Assert-Throws {
    param([scriptblock]$Action, [string]$ExpectedPattern = '', [string]$Message = 'Expected exception')
    $threw = $false
    $errMsg = ''
    try {
        & $Action
    } catch {
        $threw = $true
        $errMsg = $_.Exception.Message
    }
    if (-not $threw) { throw "Assertion failed ($Message): no exception thrown" }
    if ($ExpectedPattern -and ($errMsg -notmatch $ExpectedPattern)) {
        throw "Assertion failed ($Message): error '$errMsg' did not match '$ExpectedPattern'"
    }
}

function Invoke-TestCase {
    param([string]$Name, [scriptblock]$Body)
    try {
        & $Body
        $script:Passed++
        Write-Output ("[PASS] {0}" -f $Name)
    } catch {
        $script:Failed++
        Write-Output ("[FAIL] {0} -> {1}" -f $Name, $_.Exception.Message)
    }
}

function New-MinimalVectorPdf {
    <#
    Creates a valid 1-page PDF 1.4 with a small vector bar chart (axes, 5 bars, tick labels) and a Figure 1
    caption (pure ASCII, no Python). A chart rather than a single flat rectangle: the Egret layout model scores
    a lone filled box as low as 0.43 next to a long caption, while real charts score > 0.9.
    #>
    param(
        [string]$OutPath,
        [string]$Caption = 'Figure 1: Sample vector diagram for testing'
    )
    $safeCap = $Caption.Replace('\', '\\').Replace('(', '\(').Replace(')', '\)')
    $chart = "0 0 0 RG 1 w 90 590 m 90 730 l S 90 590 m 290 590 l S`n" +
        "0.2 0.4 0.8 rg 105 590 22 60 re f 141 590 22 95 re f 177 590 22 40 re f 213 590 22 120 re f 249 590 22 80 re f`n" +
        "0 0 0 rg BT /F1 8 Tf 80 588 Td (0) Tj ET BT /F1 8 Tf 76 628 Td (40) Tj ET BT /F1 8 Tf 76 668 Td (80) Tj ET BT /F1 8 Tf 72 708 Td (120) Tj ET`n"
    $streamBody = "$chart" + "BT /F1 12 Tf 70 565 Td ($safeCap) Tj ET`n"
    $streamBytesLen = [System.Text.Encoding]::ASCII.GetByteCount($streamBody)

    $objs = @(
        "1 0 obj`n<< /Type /Catalog /Pages 2 0 R >>`nendobj`n",
        "2 0 obj`n<< /Type /Pages /Kids [3 0 R] /Count 1 >>`nendobj`n",
        "3 0 obj`n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>`nendobj`n",
        "4 0 obj`n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>`nendobj`n",
        "5 0 obj`n<< /Length $streamBytesLen >>`nstream`n$streamBody`nendstream`nendobj`n"
    )

    $sb = New-Object System.Text.StringBuilder
    [void]$sb.Append("%PDF-1.4`n")
    $offsets = New-Object 'System.Collections.Generic.List[int]'
    foreach ($o in $objs) {
        [void]$offsets.Add([System.Text.Encoding]::ASCII.GetByteCount($sb.ToString()))
        [void]$sb.Append($o)
    }
    $xrefOffset = [System.Text.Encoding]::ASCII.GetByteCount($sb.ToString())
    [void]$sb.Append("xref`n0 $($objs.Count + 1)`n0000000000 65535 f `n")
    foreach ($off in $offsets) {
        [void]$sb.Append(("{0:D10} 00000 n `n" -f $off))
    }
    [void]$sb.Append("trailer`n<< /Size $($objs.Count + 1) /Root 1 0 R >>`nstartxref`n$xrefOffset`n%%EOF`n")
    [System.IO.File]::WriteAllText($OutPath, $sb.ToString(), [System.Text.Encoding]::ASCII)
}

function Write-PngChunk {
    param(
        [System.IO.Stream]$Stream,
        [string]$Type,
        [byte[]]$Data
    )
    $lenBytes = [BitConverter]::GetBytes([uint32]$Data.Length)
    if ([BitConverter]::IsLittleEndian) { [Array]::Reverse($lenBytes) }
    $Stream.Write($lenBytes, 0, 4)

    $typeBytes = [System.Text.Encoding]::ASCII.GetBytes($Type)
    $Stream.Write($typeBytes, 0, 4)
    if ($Data.Length -gt 0) { $Stream.Write($Data, 0, $Data.Length) }

    if (-not $script:PngCrcTable) {
        $tbl = New-Object int64[] 256
        for ($n = 0; $n -lt 256; $n++) {
            [int64]$c = $n
            for ($k = 0; $k -lt 8; $k++) {
                if (($c -band 1) -ne 0) {
                    $c = [int64]3988292384 -bxor ($c -shr 1)
                } else {
                    $c = $c -shr 1
                }
            }
            $tbl[$n] = $c
        }
        $script:PngCrcTable = $tbl
    }
    [int64]$crc = 4294967295
    foreach ($b in $typeBytes) {
        $crc = $script:PngCrcTable[($crc -bxor $b) -band 255] -bxor ($crc -shr 8)
    }
    foreach ($b in $Data) {
        $crc = $script:PngCrcTable[($crc -bxor $b) -band 255] -bxor ($crc -shr 8)
    }
    $crc = $crc -bxor [int64]4294967295
    $crcBytes = [BitConverter]::GetBytes([uint32]$crc)
    if ([BitConverter]::IsLittleEndian) { [Array]::Reverse($crcBytes) }
    $Stream.Write($crcBytes, 0, 4)
}

function New-TestPng {
    <# Creates a valid RGB (ColorType=2) or RGBA (ColorType=6) PNG using pure .NET streams (PS 5.1 & PS 7 compatible). #>
    param(
        [string]$OutPath,
        [int]$Width,
        [int]$Height,
        [byte]$ColorType,
        [byte[]]$RawPixels
    )
    $bpp = if ($ColorType -eq 6) { 4 } else { 3 }
    $rowBytes = $Width * $bpp
    $scanlines = New-Object byte[] (($rowBytes + 1) * $Height)
    for ($y = 0; $y -lt $Height; $y++) {
        $dstOff = $y * ($rowBytes + 1)
        $scanlines[$dstOff] = 0
        [Array]::Copy($RawPixels, $y * $rowBytes, $scanlines, $dstOff + 1, $rowBytes)
    }

    [int64]$s1 = 1
    [int64]$s2 = 0
    for ($i = 0; $i -lt $scanlines.Length; $i++) {
        $s1 = ($s1 + [int64]$scanlines[$i]) % 65521
        $s2 = ($s2 + $s1) % 65521
    }
    [uint32]$adler = ($s2 -shl 16) -bor $s1

    $zlibMs = New-Object System.IO.MemoryStream
    try {
        $zlibMs.WriteByte(0x78)
        $zlibMs.WriteByte(0x9C)
        $ds = New-Object System.IO.Compression.DeflateStream($zlibMs, [System.IO.Compression.CompressionMode]::Compress, $true)
        try { $ds.Write($scanlines, 0, $scanlines.Length) } finally { $ds.Dispose() }
        $adlerBytes = [BitConverter]::GetBytes($adler)
        if ([BitConverter]::IsLittleEndian) { [Array]::Reverse($adlerBytes) }
        $zlibMs.Write($adlerBytes, 0, 4)
        $idatPayload = $zlibMs.ToArray()
    } finally {
        $zlibMs.Dispose()
    }

    $pngMs = New-Object System.IO.MemoryStream
    try {
        [byte[]]$sig = 137, 80, 78, 71, 13, 10, 26, 10
        $pngMs.Write($sig, 0, 8)

        $ihdr = New-Object byte[] 13
        $wBytes = [BitConverter]::GetBytes([uint32]$Width)
        $hBytes = [BitConverter]::GetBytes([uint32]$Height)
        if ([BitConverter]::IsLittleEndian) { [Array]::Reverse($wBytes); [Array]::Reverse($hBytes) }
        [Array]::Copy($wBytes, 0, $ihdr, 0, 4)
        [Array]::Copy($hBytes, 0, $ihdr, 4, 4)
        $ihdr[8] = 8
        $ihdr[9] = $ColorType
        $ihdr[10] = 0; $ihdr[11] = 0; $ihdr[12] = 0
        Write-PngChunk -Stream $pngMs -Type 'IHDR' -Data $ihdr
        Write-PngChunk -Stream $pngMs -Type 'IDAT' -Data $idatPayload
        Write-PngChunk -Stream $pngMs -Type 'IEND' -Data ([byte[]]@())
        [System.IO.File]::WriteAllBytes($OutPath, $pngMs.ToArray())
    } finally {
        $pngMs.Dispose()
    }
}

function Invoke-CliPs1 {
    param([string]$ScriptPath, [string[]]$CliArgs)
    $allArgs = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $ScriptPath) + $CliArgs
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out = (& $script:CurrentPsExe @allArgs 2>&1 | Out-String -Width 4096)
        $out = ($out -replace '\r?\n\s*\|\s+', ' ')
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prevEap
    }
    return @{ ExitCode = $code; Output = $out }
}

function Find-LocalBrowser {
    foreach ($pair in @(
        @(${env:ProgramFiles(x86)}, 'Microsoft\Edge\Application\msedge.exe'),
        @($env:ProgramFiles,        'Microsoft\Edge\Application\msedge.exe'),
        @($env:LocalAppData,        'Microsoft\Edge\Application\msedge.exe'),
        @($env:ProgramFiles,        'Google\Chrome\Application\chrome.exe'),
        @(${env:ProgramFiles(x86)}, 'Google\Chrome\Application\chrome.exe'),
        @($env:LocalAppData,        'Google\Chrome\Application\chrome.exe')
    )) {
        if ($pair[0] -and (Test-Path -LiteralPath (Join-Path $pair[0] $pair[1]) -PathType Leaf)) {
            return (Join-Path $pair[0] $pair[1])
        }
    }
    return $null
}

. (Join-Path $toolsDir '_path_guards.ps1')

$tmpRoot = Join-Path $env:TEMP ('max_luka_ps_suite_' + [guid]::NewGuid().ToString('N'))
[void][System.IO.Directory]::CreateDirectory($tmpRoot)

try {
    Invoke-TestCase 'All tools\ and tests\ PowerShell scripts avoid legacy GDI+, dynamic C#, and WinRT dependencies' {
        $psFiles = @(Get-ChildItem -LiteralPath $toolsDir -Filter '*.ps1' -File) + @(Get-ChildItem -LiteralPath $PSScriptRoot -Filter '*.ps1' -File)
        $forbidden = @(
            ('System' + '.Drawing'),
            ('Add-' + 'Type'),
            ('System.Runtime.' + 'WindowsRuntime'),
            ('Windows.Data.' + 'Pdf')
        )
        foreach ($f in $psFiles) {
            $tokens = $null; $errs = $null
            [void][System.Management.Automation.Language.Parser]::ParseFile($f.FullName, [ref]$tokens, [ref]$errs)
            $codeText = (($tokens | Where-Object { $_.Kind -ne 'Comment' } | ForEach-Object { $_.Text }) -join "`n")
            foreach ($pat in $forbidden) {
                Assert-True ($codeText -notmatch [regex]::Escape($pat)) "$($f.Name) still references PS7-incompatible API '$pat'"
            }
        }
    }

    Invoke-TestCase 'AST syntax check for all tools\ and tests\ PowerShell scripts' {
        $psFiles = @(Get-ChildItem -LiteralPath $toolsDir -Filter '*.ps1' -File) + @(Get-ChildItem -LiteralPath $PSScriptRoot -Filter '*.ps1' -File)
        foreach ($f in $psFiles) {
            $tokens = $null; $errs = $null
            [void][System.Management.Automation.Language.Parser]::ParseFile($f.FullName, [ref]$tokens, [ref]$errs)
            Assert-Equal 0 $errs.Count "Syntax errors in $($f.Name)"
        }
    }

    Invoke-TestCase 'Assert-LocalNoUncPath blocks UNC/network prefixes and allows local paths' {
        foreach ($bad in @('\\server\share\a.pdf', '//server/share/a.pdf', 'file://server/share/a.pdf', 'FileSystem::\\server\share')) {
            Assert-Throws { Assert-LocalNoUncPath -PathValue $bad -ParamName 'Test' } 'Refusing UNC' "Should block $bad"
        }
        Assert-LocalNoUncPath -PathValue 'C:\Users\Test\doc.pdf' -ParamName 'Test'
        Assert-LocalNoUncPath -PathValue 'work\assets' -ParamName 'Test'
    }

    Invoke-TestCase 'Test-IsReparsePoint and Assert-SafeOutputPath block junctions (including broken junctions)' {
        $sub = Join-Path $tmpRoot 'junc_case'
        [void][System.IO.Directory]::CreateDirectory($sub)
        $real = Join-Path $sub 'real'
        $realSub = Join-Path $real 'real_subdir'
        $junc = Join-Path $sub 'junc'
        [void][System.IO.Directory]::CreateDirectory($realSub)
        [System.IO.File]::WriteAllText((Join-Path $real 'direct_existing.html'), 'old')
        [System.IO.File]::WriteAllText((Join-Path $realSub 'existing.html'), 'old')
        cmd /c mklink /J "`"$junc`"" "`"$real`"" | Out-Null
        try {
            $realItem = Get-Item -LiteralPath $real -Force
            $juncItem = Get-Item -LiteralPath $junc -Force
            Assert-True (-not (Test-IsReparsePoint -Item $realItem)) 'Normal folder should not be flagged'
            Assert-True (Test-IsReparsePoint -Item $juncItem) 'Active junction should be flagged'
            Assert-Throws { Assert-SafeOutputPath -TargetPath (Join-Path $junc 'out.html') -Label 'TestOut' } 'symlink/junction' 'Should block write through junction'

            # Outside workspace/CWD/TEMP (else branch): must catch junction above existing dirs/files up to drive root
            $prevTemp = $env:TEMP
            $env:TEMP = Join-Path $sub '__isolated_anchor__'
            try {
                Assert-Throws { Assert-SafeOutputPath -TargetPath (Join-Path $junc 'real_subdir\new.html') -Label 'TestOut' } 'symlink/junction' 'Should block new file in existing subdir under outside junction'
                Assert-Throws { Assert-SafeOutputPath -TargetPath (Join-Path $junc 'real_subdir\existing.html') -Label 'TestOut' } 'symlink/junction' 'Should block existing file in existing subdir under outside junction'
                Assert-Throws { Assert-SafeOutputPath -TargetPath (Join-Path $junc 'direct_existing.html') -Label 'TestOut' } 'symlink/junction' 'Should block existing file directly under outside junction'
                Assert-Throws { Assert-SafeOutputPath -TargetPath (Join-Path $junc 'real_subdir') -Label 'TestDir' -IsDirectory } 'symlink/junction' 'Should block existing subdir directory under outside junction'

                $ancestorHasReparse = $false
                $pCursor = Split-Path $realSub -Parent
                while ($pCursor) {
                    $pIt = Get-Item -LiteralPath $pCursor -Force -ErrorAction SilentlyContinue
                    if ($pIt -and (Test-IsReparsePoint -Item $pIt)) { $ancestorHasReparse = $true; break }
                    $pNext = Split-Path $pCursor -Parent
                    if (-not $pNext -or $pNext -eq $pCursor) { break }
                    $pCursor = $pNext
                }
                if (-not $ancestorHasReparse) {
                    Assert-SafeOutputPath -TargetPath (Join-Path $realSub 'ok.html') -Label 'TestOut'
                }
            } finally {
                $env:TEMP = $prevTemp
            }

            Remove-Item -LiteralPath $real -Recurse -Force
            $brokenItem = Get-Item -LiteralPath $junc -Force
            Assert-True (Test-IsReparsePoint -Item $brokenItem) 'Broken junction should still be flagged'
        } finally {
            if (Test-Path -LiteralPath $junc) { cmd /c rmdir "`"$junc`"" | Out-Null }
        }
    }

    Invoke-TestCase 'Test-HasCloudPlaceholderFiles detects Offline attribute without false positives' {
        Assert-True (-not (Test-HasCloudPlaceholderFiles -DirectoryPath (Join-Path $toolsDir 'extract_assets'))) 'tools\extract_assets should have 0 placeholders'
        $cdir = Join-Path $tmpRoot 'cloud_placeholder'
        [void][System.IO.Directory]::CreateDirectory($cdir)
        $cfile = Join-Path $cdir 'dummy.dll'
        [System.IO.File]::WriteAllText($cfile, 'x')
        $fi = Get-Item -LiteralPath $cfile -Force
        $fi.Attributes = $fi.Attributes -bor [System.IO.FileAttributes]::Offline
        try {
            Assert-True (Test-HasCloudPlaceholderFiles -DirectoryPath $cdir) 'Should detect Offline file attribute'
        } finally {
            $fi.Attributes = $fi.Attributes -band (-bnot [System.IO.FileAttributes]::Offline)
        }
    }

    $viDocName = "T$([char]0x00E0)i li$([char]0x1EC7)u m$([char]0x1EAB)u.pdf"
    $viAssetsSub = "Th$([char]0x01B0) m$([char]0x1EE5)c $([char]0x1EA3)nh\assets1"
    $samplePdf = Join-Path $tmpRoot $viDocName
    New-MinimalVectorPdf -OutPath $samplePdf -Caption 'Figure 1: Minimal vector box with a long enough caption to test word compaction limit'

    Invoke-TestCase 'extract_pdf_assets.ps1 handles -PdfPath, Vietnamese paths, word compaction, and size limit' {
        $extractPs1 = Join-Path $toolsDir 'extract_pdf_assets.ps1'
        $outAssets = Join-Path $tmpRoot $viAssetsSub
        $r1 = Invoke-CliPs1 $extractPs1 @('-PdfPath', $samplePdf, '-OutDir', $outAssets, '-Meta', '-MaxMetaWords', '4')
        Assert-Equal 0 $r1.ExitCode "extract_pdf_assets failed: $($r1.Output)"
        Assert-True ($r1.Output -match 'Resolved PDF ->') 'Missing Resolved PDF output'
        Assert-True ($r1.Output -match 'Extracted 1 figures') "Expected 1 figure, got: $($r1.Output)"
        Assert-True ($r1.Output -match '=== MANIFEST JSON START ===') 'Missing manifest block'
        Assert-True ($r1.Output -match '"caption":\s*"Figure 1: Minimal vector\.\.\."') "Expected 4-word truncated caption in stdout: $($r1.Output)"

        $manifestOnDisk = Get-Content (Join-Path $outAssets 'manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        Assert-Equal 1 $manifestOnDisk.figures.Count 'manifest figure count'
        Assert-True ($manifestOnDisk.figures[0].caption -match 'word compaction limit$') 'Full caption must remain on disk'

        $rLimit = Invoke-CliPs1 $extractPs1 @('-PdfPath', $samplePdf, '-OutDir', $outAssets, '-Meta', '-MaxMetaBytes', '40')
        Assert-Equal 0 $rLimit.ExitCode "extract_pdf_assets limit failed: $($rLimit.Output)"
        Assert-True ($rLimit.Output -match 'Manifest too large for stdout') 'Should report manifest exceeds byte limit'
    }

    Invoke-TestCase 'extract_pdf_assets.ps1 resolves -TranscriptPath by application/pdf mime_type without .pdf extension' {
        $extractPs1 = Join-Path $toolsDir 'extract_pdf_assets.ps1'
        $blobPdf = Join-Path $tmpRoot 'attachment_blob_noext'
        Copy-Item -LiteralPath $samplePdf -Destination $blobPdf -Force
        $transcript = Join-Path $tmpRoot 'transcript.jsonl'
        $uriEsc = $blobPdf.Replace('\', '\\')
        $line = '{"type":"USER_INPUT","media":[{"mime_type":"application/pdf","uri":"' + $uriEsc + '"}]}'
        [System.IO.File]::WriteAllText($transcript, $line + "`n", (New-Object System.Text.UTF8Encoding($false)))

        $outAssets = Join-Path $tmpRoot 'assets_transcript'
        $r = Invoke-CliPs1 $extractPs1 @('-TranscriptPath', $transcript, '-OutDir', $outAssets, '-Meta')
        Assert-Equal 0 $r.ExitCode "Transcript extraction failed: $($r.Output)"
        Assert-True ($r.Output -match 'Extracted 1 figures') "Expected 1 figure via transcript: $($r.Output)"
    }

    Invoke-TestCase 'pdf_fallback_tools.ps1 RenderPages, CropFromJson, non-locking overwrite, and input validation' {
        $fbPs1 = Join-Path $toolsDir 'pdf_fallback_tools.ps1'
        $fbDir = Join-Path $tmpRoot 'fallback_work'
        $pagesDir = Join-Path $fbDir 'pages'
        $cropsDir = Join-Path $fbDir 'crops'

        $rRender = Invoke-CliPs1 $fbPs1 @('-Action', 'RenderPages', '-PdfPath', $samplePdf, '-OutDir', $pagesDir, '-Scale', '1.5')
        Assert-Equal 0 $rRender.ExitCode "RenderPages failed: $($rRender.Output)"
        $page1 = Join-Path $pagesDir 'page_1.png'
        Assert-True (Test-Path -LiteralPath $page1 -PathType Leaf) 'page_1.png not rendered'

        $specOk = Join-Path $fbDir 'crop_ok.json'
        $specData = @(
            @{ page_png = $page1; box = @(0.05, 0.10, 0.60, 0.40); out_name = 'fig_trim.png'; auto_trim = $true },
            @{ page_png = $page1; box = @(0.05, 0.10, 0.60, 0.40); out_name = 'fig_raw.png'; auto_trim = $false }
        ) | ConvertTo-Json
        [System.IO.File]::WriteAllText($specOk, $specData, (New-Object System.Text.UTF8Encoding($false)))
        $rCrop = Invoke-CliPs1 $fbPs1 @('-Action', 'CropFromJson', '-SpecJson', $specOk, '-OutDir', $cropsDir)
        Assert-Equal 0 $rCrop.ExitCode "CropFromJson failed: $($rCrop.Output)"
        $trimFile = Join-Path $cropsDir 'fig_trim.png'
        $rawFile = Join-Path $cropsDir 'fig_raw.png'
        Assert-True (Test-Path -LiteralPath $trimFile -PathType Leaf) 'fig_trim.png missing'
        Assert-True (Test-Path -LiteralPath $rawFile -PathType Leaf) 'fig_raw.png missing'
        Assert-True ((Get-Item -LiteralPath $trimFile).Length -lt (Get-Item -LiteralPath $rawFile).Length) 'Auto-trim should produce tighter output than raw crop'

        # Non-locking overwrite of source image inside cropsDir
        $specOverwrite = Join-Path $fbDir 'crop_overwrite.json'
        $ovData = @(@{ page_png = (Join-Path $cropsDir 'fig_raw.png'); box = @(0.1, 0.1, 0.9, 0.9); out_name = 'fig_raw.png'; auto_trim = $false }) | ConvertTo-Json
        [System.IO.File]::WriteAllText($specOverwrite, $ovData, (New-Object System.Text.UTF8Encoding($false)))
        $rOv = Invoke-CliPs1 $fbPs1 @('-Action', 'CropFromJson', '-SpecJson', $specOverwrite, '-OutDir', $cropsDir)
        Assert-Equal 0 $rOv.ExitCode "Non-locking crop overwrite failed: $($rOv.Output)"

        # Security/validation rejections
        foreach ($badSpec in @(
            @{ label = 'traversal out_name'; obj = @(@{ page_png = $page1; box = @(0.1, 0.1, 0.5, 0.5); out_name = '..\bad.png' }); pattern = 'Path traversal blocked' },
            @{ label = 'reserved Windows device out_name'; obj = @(@{ page_png = $page1; box = @(0.1, 0.1, 0.5, 0.5); out_name = 'CON.png' }); pattern = 'reserved/invalid Windows filename' },
            @{ label = 'trailing dot out_name'; obj = @(@{ page_png = $page1; box = @(0.1, 0.1, 0.5, 0.5); out_name = 'fig1.png.' }); pattern = 'reserved/invalid Windows filename' },
            @{ label = 'outside page_png'; obj = @(@{ page_png = 'C:\Windows\System32\calc.exe'; box = @(0.1, 0.1, 0.5, 0.5); out_name = 'ok.png' }); pattern = 'Path traversal blocked' },
            @{ label = 'invalid box coords'; obj = @(@{ page_png = $page1; box = @(0.6, 0.1, 0.5, 0.5); out_name = 'ok.png' }); pattern = 'Invalid crop box' }
        )) {
            $badFile = Join-Path $fbDir 'bad_crop.json'
            [System.IO.File]::WriteAllText($badFile, ($badSpec.obj | ConvertTo-Json), (New-Object System.Text.UTF8Encoding($false)))
            $rBad = Invoke-CliPs1 $fbPs1 @('-Action', 'CropFromJson', '-SpecJson', $badFile, '-OutDir', $cropsDir)
            Assert-True ($rBad.ExitCode -ne 0 -and $rBad.Output -match $badSpec.pattern) "$($badSpec.label): expected '$($badSpec.pattern)', got $($rBad.Output)"
        }
    }

    Invoke-TestCase 'html_packager.ps1 Auto-QA catches failures and passes valid HTML (single quotes + code blocks + MathJax)' {
        $packPs1 = Join-Path $toolsDir 'html_packager.ps1'
        $qaDir = Join-Path $tmpRoot 'qa_cases'
        [void][System.IO.Directory]::CreateDirectory($qaDir)

        # Create an opaque 240x160 noisy photo PNG (compresses smaller as JPEG) & a 60x60 transparent PNG without System.Drawing
        $photoPng = Join-Path $qaDir 'photo.png'
        $photoRaw = New-Object byte[] (240 * 160 * 3)
        (New-Object System.Random(42)).NextBytes($photoRaw)
        New-TestPng -OutPath $photoPng -Width 240 -Height 160 -ColorType 2 -RawPixels $photoRaw

        $alphaPng = Join-Path $qaDir 'alpha.png'
        $alphaRaw = New-Object byte[] (60 * 60 * 4)
        $pxOff = (10 * 60 + 10) * 4
        $alphaRaw[$pxOff] = 10; $alphaRaw[$pxOff + 1] = 20; $alphaRaw[$pxOff + 2] = 30; $alphaRaw[$pxOff + 3] = 120
        New-TestPng -OutPath $alphaPng -Width 60 -Height 60 -ColorType 6 -RawPixels $alphaRaw

        # Passing HTML with single quotes, duplicate local image path, <pre><code> LaTeX-like text, table-wrapper, and both images
        $goodIn = Join-Path $qaDir 'good.html'
        $goodOut = Join-Path $qaDir 'good_out.html'
        $goodHtml = @'
<!DOCTYPE html>
<html><head><title>QA</title></head>
<body>
<header><h1 id='top'>Tieu de</h1></header>
<p><a href='#top'>Dau trang</a></p>
<pre><code>grep '\(foo\|bar\)' \\[host]\share</code></pre>
<p>Inline code <code>\[0-9\]</code></p>
<div class='table-wrapper'><table><thead><tr><th>A</th></tr></thead><tbody><tr><td>1</td></tr></tbody></table></div>
<figure><img src='photo.png' alt='Anh mau'><figcaption>Hinh 1</figcaption></figure>
<figure><img src='photo.png' alt='Anh mau lap'><figcaption>Hinh 1 lap</figcaption></figure>
<figure><img src='alpha.png' alt='Anh trong suot'><figcaption>Hinh 2</figcaption></figure>
</body></html>
'@
        [System.IO.File]::WriteAllText($goodIn, $goodHtml, (New-Object System.Text.UTF8Encoding($false)))
        $rGood = Invoke-CliPs1 $packPs1 @('-Action', 'EmbedImages', '-HtmlPath', $goodIn, '-OutHtmlPath', $goodOut, '-MaxImageWidth', '200')
        Assert-Equal 0 $rGood.ExitCode "Good HTML failed: $($rGood.Output)"
        Assert-True ($rGood.Output -match 'Quality=95%') "Expected default JpegQuality=95%, got: $($rGood.Output)"
        Assert-True ($rGood.Output -match '\[QA PASS\] Base64 images: 3 \| Tables wrapped: 1/1') "Unexpected QA pass output: $($rGood.Output)"
        Assert-True ($rGood.Output -match 'Injected reader shell -> CSS, Toolbar, Script') 'Expected shell injection'
        $outText = [System.IO.File]::ReadAllText($goodOut, [System.Text.Encoding]::UTF8)
        Assert-True ($outText -match 'data:image/jpeg;base64,') 'Expected rich photo resized/compressed to JPEG'
        Assert-True ($outText -match 'data:image/png;base64,') 'Expected transparent PNG preserved as PNG'

        # Idempotent re-injection check
        $goodOut2 = Join-Path $qaDir 'good_out2.html'
        $rIdemp = Invoke-CliPs1 $packPs1 @('-Action', 'EmbedImages', '-HtmlPath', $goodOut, '-OutHtmlPath', $goodOut2)
        Assert-Equal 0 $rIdemp.ExitCode "Idempotent pack failed: $($rIdemp.Output)"
        Assert-True ($rIdemp.Output -match 'Reader shell already present \(skipped injection\)') "Expected skipped injection: $($rIdemp.Output)"

        # Grayscale photo PNG (>=200 8-bit tones -> JPEG) and wide low-color PNG (resized PNG) via extract_assets.exe
        $grayPhotoPng = Join-Path $qaDir 'gray_photo.png'
        $gpRaw = New-Object byte[] (220 * 120 * 3)
        $rng = New-Object System.Random(17)
        for ($y = 0; $y -lt 120; $y++) {
            for ($x = 0; $x -lt 220; $x++) {
                $v = [Math]::Max(0, [Math]::Min(255, [int](($x / 220.0) * 220 + 15 + $rng.Next(-15, 16))))
                $off = ($y * 220 + $x) * 3
                $gpRaw[$off] = [byte]$v; $gpRaw[$off + 1] = [byte]$v; $gpRaw[$off + 2] = [byte]$v
            }
        }
        New-TestPng -OutPath $grayPhotoPng -Width 220 -Height 120 -ColorType 2 -RawPixels $gpRaw

        $wideDiagPng = Join-Path $qaDir 'wide_diag.png'
        $wdW = 600; $wdH = 240; $wdStride = $wdW * 3
        $wdRow0 = New-Object byte[] $wdStride
        $wdRow1 = New-Object byte[] $wdStride
        for ($x = 0; $x -lt $wdW; $x++) {
            $blk = ([Math]::Floor($x / 24) % 2) -eq 0
            $c0 = if ($blk) { [byte]25 } else { [byte]235 }
            $c1 = if ($blk) { [byte]235 } else { [byte]25 }
            $off = $x * 3
            $wdRow0[$off] = $c0; $wdRow0[$off + 1] = $c0; $wdRow0[$off + 2] = 245
            $wdRow1[$off] = $c1; $wdRow1[$off + 1] = $c1; $wdRow1[$off + 2] = 245
        }
        $wdRaw = New-Object byte[] ($wdStride * $wdH)
        for ($y = 0; $y -lt $wdH; $y++) {
            $srcRow = if (([Math]::Floor($y / 24) % 2) -eq 0) { $wdRow0 } else { $wdRow1 }
            [Array]::Copy($srcRow, 0, $wdRaw, $y * $wdStride, $wdStride)
        }
        New-TestPng -OutPath $wideDiagPng -Width $wdW -Height $wdH -ColorType 2 -RawPixels $wdRaw

        $optInHtml = Join-Path $qaDir 'opt_embed_in.html'
        $optOutHtml = Join-Path $qaDir 'opt_embed_out.html'
        [System.IO.File]::WriteAllText(
            $optInHtml,
            '<!DOCTYPE html><html><head><title>Opt</title></head><body><figure><img src="gray_photo.png" alt="Grayscale photo"></figure><figure><img src="wide_diag.png" alt="Wide diagram"></figure></body></html>',
            (New-Object System.Text.UTF8Encoding($false))
        )
        $rOptEmbed = Invoke-CliPs1 $packPs1 @('-Action', 'EmbedImages', '-HtmlPath', $optInHtml, '-OutHtmlPath', $optOutHtml, '-PreserveLayout', '-JpegQuality', '85', '-MaxImageWidth', '200')
        Assert-Equal 0 $rOptEmbed.ExitCode "EmbedImages grayscale/wide failed: $($rOptEmbed.Output)"
        Assert-True ($rOptEmbed.Output -match 'Optimized 2/2 images') "Expected both images optimized: $($rOptEmbed.Output)"
        $optHtmlText = [System.IO.File]::ReadAllText($optOutHtml, [System.Text.Encoding]::UTF8)
        $mGray = [regex]::Match($optHtmlText, 'src="data:image/jpeg;base64,([^"]+)" alt="Grayscale photo"')
        Assert-True $mGray.Success 'Grayscale continuous-tone photo PNG should embed as compressed JPEG'
        Assert-True (([Convert]::FromBase64String($mGray.Groups[1].Value)).Length -lt (Get-Item -LiteralPath $grayPhotoPng).Length) 'Grayscale photo JPEG should shrink file size'
        $mWide = [regex]::Match($optHtmlText, 'src="data:image/png;base64,([^"]+)" alt="Wide diagram"')
        Assert-True $mWide.Success 'Wide low-color diagram PNG should stay PNG'
        Assert-True (([Convert]::FromBase64String($mWide.Groups[1].Value)).Length -lt (Get-Item -LiteralPath $wideDiagPng).Length) 'Wide diagram PNG should be resized and smaller'

        # Real LaTeX with MathJax <script> passes
        $mathOk = Join-Path $qaDir 'math_ok.html'
        [System.IO.File]::WriteAllText($mathOk, '<!DOCTYPE html><html><head><script id="MathJax-script" async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script></head><body><p>Formula \(a+b\)</p></body></html>', (New-Object System.Text.UTF8Encoding($false)))
        $rMath = Invoke-CliPs1 $packPs1 @('-Action', 'EmbedImages', '-HtmlPath', $mathOk, '-OutHtmlPath', (Join-Path $qaDir 'math_out.html'))
        Assert-Equal 0 $rMath.ExitCode "MathJax HTML failed: $($rMath.Output)"

        # Comments containing fake failures, nested <code>, and nested tables inside .table-wrapper must pass cleanly
        $commentOk = Join-Path $qaDir 'comment_ok.html'
        $commentOut = Join-Path $qaDir 'comment_out.html'
        $commentHtml = @'
<!DOCTYPE html><html>
<!-- </head><body><img src="missing.png"><table></table><div class="table-wrapper"></div>\(bad\)<a href="#ghost">G</a><span id="ghost"></span> -->
<head><title>Comment Safe</title></head>
<body>
<h1 id="ok">OK</h1><a href="#ok">Link</a>
<pre><code>outer <code>inner</code> \(ignore\)</code></pre>
<div class="table-wrapper"><table><tr><td><table><tr><td>Sub</td></tr></table></td></tr></table></div>
</body></html>
'@
        [System.IO.File]::WriteAllText($commentOk, $commentHtml, (New-Object System.Text.UTF8Encoding($false)))
        $rComment = Invoke-CliPs1 $packPs1 @('-Action', 'EmbedImages', '-HtmlPath', $commentOk, '-OutHtmlPath', $commentOut)
        Assert-Equal 0 $rComment.ExitCode "Comment-safe QA HTML failed: $($rComment.Output)"
        Assert-True ($rComment.Output -match '\[QA PASS\] Base64 images: 0 \| Tables wrapped: 2/2') "Unexpected comment-safe QA output: $($rComment.Output)"

        # Negative QA cases (structure + security policy)
        foreach ($neg in @(
            @{ name = 'missing alt'; html = '<!DOCTYPE html><html><head></head><body><img src="photo.png"></body></html>'; pat = 'missing alt attribute' },
            @{ name = 'unembedded img'; html = '<!DOCTYPE html><html><head></head><body><img src="missing.png" alt="x"></body></html>'; pat = 'un-embedded local.*missing\.png' },
            @{ name = 'unwrapped table'; html = '<!DOCTYPE html><html><head></head><body><table><tr><td>1</td></tr></table></body></html>'; pat = 'table-wrapper container' },
            @{ name = 'empty wrapper sibling table'; html = '<!DOCTYPE html><html><head></head><body><div class="table-wrapper"></div><table><tr><td>1</td></tr></table></body></html>'; pat = 'table-wrapper container' },
            @{ name = 'broken anchor'; html = '<!DOCTYPE html><html><head></head><body><a href="#nope">Link</a></body></html>'; pat = 'Broken internal anchor' },
            @{ name = 'commented anchor target'; html = '<!DOCTYPE html><html><head></head><body><a href="#ghost">Link</a><!-- <h2 id="ghost">Ghost</h2> --></body></html>'; pat = 'Broken internal anchor' },
            @{ name = 'latex no mathjax'; html = '<!DOCTYPE html><html><head></head><body><p>Value \(x\)</p></body></html>'; pat = 'Detected LaTeX math delimiters' },
            @{ name = 'commented mathjax'; html = '<!DOCTYPE html><html><head><!-- <script id="MathJax-script"></script> --></head><body><p>Value \(x\)</p></body></html>'; pat = 'Detected LaTeX math delimiters' },
            @{ name = 'spoofed reader shell script'; html = '<!DOCTYPE html><html><head></head><body><script data-reader-shell="script">alert(1)</script></body></html>'; pat = 'Disallowed <script>' },
            @{ name = 'iframe blocked'; html = '<!DOCTYPE html><html><head></head><body><iframe src="https://evil.example"></iframe></body></html>'; pat = 'Disallowed HTML tag' },
            @{ name = 'inline onclick blocked'; html = '<!DOCTYPE html><html><head></head><body><button onclick="alert(1)">X</button></body></html>'; pat = 'Disallowed inline event handler' },
            @{ name = 'javascript href blocked'; html = '<!DOCTYPE html><html><head></head><body><a href="javascript:alert(1)">Bad</a></body></html>'; pat = 'Disallowed dangerous URI' },
            @{ name = 'external img blocked'; html = '<!DOCTYPE html><html><head></head><body><img src="https://evil.example/px.png" alt="px"></body></html>'; pat = 'Disallowed external <img> URL' },
            @{ name = 'external css url blocked'; html = '<!DOCTYPE html><html><head><style>body{background:url(https://evil.example/a.png)}</style></head><body></body></html>'; pat = 'Disallowed external resource' }
        )) {
            $negFile = Join-Path $qaDir 'neg.html'
            [System.IO.File]::WriteAllText($negFile, $neg.html, (New-Object System.Text.UTF8Encoding($false)))
            $rNeg = Invoke-CliPs1 $packPs1 @('-Action', 'EmbedImages', '-HtmlPath', $negFile, '-OutHtmlPath', (Join-Path $qaDir 'neg_out.html'))
            Assert-True ($rNeg.ExitCode -ne 0 -and $rNeg.Output -match $neg.pat) "QA negative [$($neg.name)] expected '$($neg.pat)', got: $($rNeg.Output)"
        }
    }

    Invoke-TestCase 'html_packager.ps1 -PreserveLayout skips reader shell, relaxes table-wrapper, and cleans work' {
        $packPs1 = Join-Path $toolsDir 'html_packager.ps1'
        $extractPs1 = Join-Path $toolsDir 'extract_pdf_assets.ps1'
        $plRoot = Join-Path $tmpRoot 'preserve_ws'
        $plWork = Join-Path $plRoot 'work'
        $plOut = Join-Path $plRoot 'output'
        [void][System.IO.Directory]::CreateDirectory($plWork)
        [void][System.IO.Directory]::CreateDirectory($plOut)

        Push-Location $plRoot
        try {
            $rExt = Invoke-CliPs1 $extractPs1 @('-PdfPath', $samplePdf, '-OutDir', 'work\assets', '-Meta')
            Assert-Equal 0 $rExt.ExitCode "PreserveLayout extract failed: $($rExt.Output)"

            # Write intermediate translated.md to verify -CleanDir cleans the full work folder
            [System.IO.File]::WriteAllText((Join-Path $plWork 'translated.md'), "<!-- p:1 -->`nNoi dung dich`n<!-- /p:1 -->", (New-Object System.Text.UTF8Encoding($false)))

            # Draft with unwrapped table, inline styles, section page, and no reader shell
            $plDraft = Join-Path $plWork 'draft.html'
            $plHtml = @'
<!DOCTYPE html><html><head><title>Layout Preserved</title><style>.pdf-page{max-width:960px;}</style></head>
<body><section id="pdf-page-1" class="pdf-page"><p><a href="#pdf-page-1">Trang 1</a></p><table><tr><td>Bang khong can table-wrapper</td></tr></table><figure><img src="assets/fig_p1_1.png" alt="So do 1"><figcaption>Hinh 1</figcaption></figure></section></body></html>
'@
            [System.IO.File]::WriteAllText($plDraft, $plHtml, (New-Object System.Text.UTF8Encoding($false)))

            $rPl = Invoke-CliPs1 $packPs1 @('-Action', 'EmbedImages', '-HtmlPath', 'work\draft.html', '-OutHtmlPath', 'output\pl_vi.html', '-PreserveLayout', '-AlsoPdf', '-CleanDir', 'work')
            Assert-Equal 0 $rPl.ExitCode "PreserveLayout pack failed: $($rPl.Output)"
            Assert-True ($rPl.Output -match '\[QA PASS\] Base64 images: 1 \| Tables: 1 \(wrapper optional\)') "Unexpected PreserveLayout QA output: $($rPl.Output)"
            Assert-True ($rPl.Output -match 'PreserveLayout mode: skipped reader shell injection') "Expected skipped shell log: $($rPl.Output)"
            Assert-True (-not (Test-Path -LiteralPath $plWork)) 'work\ (including translated.md) should be cleaned'

            $plOutHtml = Join-Path $plOut 'pl_vi.html'
            Assert-True (Test-Path -LiteralPath $plOutHtml -PathType Leaf) 'pl_vi.html missing'
            $plText = [System.IO.File]::ReadAllText($plOutHtml, [System.Text.Encoding]::UTF8)
            Assert-True ($plText -match 'data:image/png;base64,') 'PreserveLayout should still embed Base64 image'
            Assert-True ($plText -notmatch 'rsfv-toolbar|data-reader-shell|<script') 'PreserveLayout must inject zero reader shell CSS/JS'
            if (Find-LocalBrowser) {
                Assert-True (Test-Path -LiteralPath (Join-Path $plOut 'pl_vi.pdf') -PathType Leaf) 'pl_vi.pdf missing despite browser installed'
            }

            # Negative checks still enforced under -PreserveLayout
            $plBad = Join-Path $plRoot 'bad_pl.html'
            foreach ($neg in @(
                @{ name = 'missing body'; html = '<!DOCTYPE html><html><head></head><p>No body</p></html>'; pat = 'complete <head>' },
                @{ name = 'missing alt'; html = '<!DOCTYPE html><html><head></head><body><img src="x.png"></body></html>'; pat = 'missing alt attribute' },
                @{ name = 'unembedded img'; html = '<!DOCTYPE html><html><head></head><body><img src="missing.png" alt="x"></body></html>'; pat = 'un-embedded local' },
                @{ name = 'broken anchor'; html = '<!DOCTYPE html><html><head></head><body><a href="#bad">Link</a></body></html>'; pat = 'Broken internal anchor' },
                @{ name = 'latex no mathjax'; html = '<!DOCTYPE html><html><head></head><body><p>Formula \(a+b\)</p></body></html>'; pat = 'Detected LaTeX math delimiters' },
                @{ name = 'inline script blocked under PreserveLayout'; html = '<!DOCTYPE html><html><head></head><body><script>console.log(1)</script></body></html>'; pat = 'Disallowed <script>' },
                @{ name = 'external img blocked under PreserveLayout'; html = '<!DOCTYPE html><html><head></head><body><img src="https://evil.example/p.png" alt="p"></body></html>'; pat = 'Disallowed external <img> URL' }
            )) {
                [System.IO.File]::WriteAllText($plBad, $neg.html, (New-Object System.Text.UTF8Encoding($false)))
                $rNeg = Invoke-CliPs1 $packPs1 @('-Action', 'EmbedImages', '-HtmlPath', $plBad, '-OutHtmlPath', (Join-Path $plRoot 'bad_pl_out.html'), '-PreserveLayout')
                Assert-True ($rNeg.ExitCode -ne 0 -and $rNeg.Output -match $neg.pat) "PreserveLayout QA [$($neg.name)] expected '$($neg.pat)', got: $($rNeg.Output)"
            }
        } finally {
            Pop-Location
        }
    }

    Invoke-TestCase 'html_packager.ps1 auto-numbers collisions (_2, _3), syncs paired PDF, and preserves in-place mode' {
        $packPs1 = Join-Path $toolsDir 'html_packager.ps1'
        $colRoot = Join-Path $tmpRoot 'collision_ws'
        $colWork = Join-Path $colRoot 'work'
        $colOut = Join-Path $colRoot 'output'
        [void][System.IO.Directory]::CreateDirectory($colWork)
        [void][System.IO.Directory]::CreateDirectory($colOut)

        $src1 = Join-Path $colWork 'draft1.html'
        $src2 = Join-Path $colWork 'draft2.html'
        [System.IO.File]::WriteAllText($src1, '<!DOCTYPE html><html><head><title>V1</title></head><body><p>Version 1</p></body></html>', (New-Object System.Text.UTF8Encoding($false)))
        [System.IO.File]::WriteAllText($src2, '<!DOCTYPE html><html><head><title>V2</title></head><body><p>Version 2</p></body></html>', (New-Object System.Text.UTF8Encoding($false)))

        $targetLayout = Join-Path $colOut 'doc_layout_vi.html'
        $rCol1 = Invoke-CliPs1 $packPs1 @('-Action', 'EmbedImages', '-HtmlPath', $src1, '-OutHtmlPath', $targetLayout, '-PreserveLayout', '-AlsoPdf')
        Assert-Equal 0 $rCol1.ExitCode "Collision run 1 failed: $($rCol1.Output)"
        Assert-True ($rCol1.Output -notmatch 'Output collision avoided') 'Run 1 should not trigger auto-numbering'

        $rCol2 = Invoke-CliPs1 $packPs1 @('-Action', 'EmbedImages', '-HtmlPath', $src2, '-OutHtmlPath', $targetLayout, '-PreserveLayout', '-AlsoPdf')
        Assert-Equal 0 $rCol2.ExitCode "Collision run 2 failed: $($rCol2.Output)"
        Assert-True ($rCol2.Output -match 'Output collision avoided; auto-numbered ->') "Expected auto-number log: $($rCol2.Output)"
        $targetLayout2 = Join-Path $colOut 'doc_layout_vi_2.html'
        Assert-True (Test-Path -LiteralPath $targetLayout2 -PathType Leaf) 'doc_layout_vi_2.html missing'
        Assert-True (([System.IO.File]::ReadAllText($targetLayout, [System.Text.Encoding]::UTF8)) -match 'Version 1') 'Run 1 output must remain intact'
        Assert-True (([System.IO.File]::ReadAllText($targetLayout2, [System.Text.Encoding]::UTF8)) -match 'Version 2') 'Run 2 output should be in _2'

        # Run 3 with same base path bumps cleanly to _3
        $rCol3 = Invoke-CliPs1 $packPs1 @('-Action', 'EmbedImages', '-HtmlPath', $src2, '-OutHtmlPath', $targetLayout, '-PreserveLayout', '-AlsoPdf')
        Assert-Equal 0 $rCol3.ExitCode "Collision run 3 failed: $($rCol3.Output)"
        $targetLayout3 = Join-Path $colOut 'doc_layout_vi_3.html'
        Assert-True (Test-Path -LiteralPath $targetLayout3 -PathType Leaf) 'Run 3 should create _3.html'

        # Orphaned PDF collision should still bump BOTH HTML and PDF to _2
        $orphanPdf = Join-Path $colOut 'orphan_vi.pdf'
        [System.IO.File]::WriteAllText($orphanPdf, 'ORIGINAL_PDF', (New-Object System.Text.UTF8Encoding($false)))
        $rOrphan = Invoke-CliPs1 $packPs1 @('-Action', 'EmbedImages', '-HtmlPath', $src2, '-OutHtmlPath', (Join-Path $colOut 'orphan_vi.html'), '-AlsoPdf')
        Assert-Equal 0 $rOrphan.ExitCode "Orphan PDF collision failed: $($rOrphan.Output)"
        Assert-True (Test-Path -LiteralPath (Join-Path $colOut 'orphan_vi_2.html') -PathType Leaf) 'Orphan collision should produce orphan_vi_2.html'
        Assert-Equal 'ORIGINAL_PDF' ([System.IO.File]::ReadAllText($orphanPdf, [System.Text.Encoding]::UTF8)) 'Orphaned PDF must not be overwritten'

        # Omitting -OutHtmlPath updates source in place without _2
        $inPlace = Join-Path $colWork 'inplace.html'
        [System.IO.File]::WriteAllText($inPlace, '<!DOCTYPE html><html><head><title>IP</title></head><body><p>InPlace</p></body></html>', (New-Object System.Text.UTF8Encoding($false)))
        $rIp = Invoke-CliPs1 $packPs1 @('-Action', 'EmbedImages', '-HtmlPath', $inPlace)
        Assert-Equal 0 $rIp.ExitCode "In-place run failed: $($rIp.Output)"
        Assert-True (([System.IO.File]::ReadAllText($inPlace, [System.Text.Encoding]::UTF8)) -match 'data-reader-shell') 'In-place should update source HTML directly'
        Assert-True (-not (Test-Path -LiteralPath (Join-Path $colWork 'inplace_2.html'))) 'In-place must not create _2'

        if (Find-LocalBrowser) {
            Assert-True (Test-Path -LiteralPath (Join-Path $colOut 'doc_layout_vi.pdf') -PathType Leaf) 'Run 1 PDF missing'
            Assert-True (Test-Path -LiteralPath (Join-Path $colOut 'doc_layout_vi_2.pdf') -PathType Leaf) 'Run 2 paired _2.pdf missing'
            Assert-True (Test-Path -LiteralPath (Join-Path $colOut 'doc_layout_vi_3.pdf') -PathType Leaf) 'Run 3 paired _3.pdf missing'
            Assert-True (Test-Path -LiteralPath (Join-Path $colOut 'orphan_vi_2.pdf') -PathType Leaf) 'Orphan collision paired _2.pdf missing'

            $standalonePdf = Join-Path $colOut 'standalone.pdf'
            [System.IO.File]::WriteAllText($standalonePdf, 'EXISTING_PDF', (New-Object System.Text.UTF8Encoding($false)))
            $rPdfCol = Invoke-CliPs1 $packPs1 @('-Action', 'HtmlToPdf', '-HtmlPath', $targetLayout2, '-OutPdfPath', $standalonePdf)
            Assert-Equal 0 $rPdfCol.ExitCode "Standalone HtmlToPdf collision failed: $($rPdfCol.Output)"
            Assert-True (Test-Path -LiteralPath (Join-Path $colOut 'standalone_2.pdf') -PathType Leaf) 'Standalone HtmlToPdf should auto-number _2.pdf'
            Assert-Equal 'EXISTING_PDF' ([System.IO.File]::ReadAllText($standalonePdf, [System.Text.Encoding]::UTF8)) 'Standalone existing PDF must remain intact'
        }
    }

    Invoke-TestCase 'html_packager.ps1 -CleanDir safety guards, lock resilience, and end-to-end -AlsoPdf' {
        $packPs1 = Join-Path $toolsDir 'html_packager.ps1'
        $extractPs1 = Join-Path $toolsDir 'extract_pdf_assets.ps1'
        $e2eDir = Join-Path $tmpRoot 'e2e_ws'
        $workDir = Join-Path $e2eDir 'work'
        $outDir = Join-Path $e2eDir 'output'
        [void][System.IO.Directory]::CreateDirectory($workDir)
        [void][System.IO.Directory]::CreateDirectory($outDir)

        Push-Location $e2eDir
        try {
            $r1 = Invoke-CliPs1 $extractPs1 @('-PdfPath', $samplePdf, '-OutDir', 'work\assets', '-Meta')
            Assert-Equal 0 $r1.ExitCode "E2E step 1 failed: $($r1.Output)"

            $draft = Join-Path $workDir 'draft.html'
            [System.IO.File]::WriteAllText($draft, '<!DOCTYPE html><html><head><title>E2E</title></head><body><h1>E2E</h1><figure><img src="assets/fig_p1_1.png" alt="Diagram"><figcaption>Figure 1</figcaption></figure></body></html>', (New-Object System.Text.UTF8Encoding($false)))

            # Refuses unsafe CleanDir outside work\
            $rUnsafe = Invoke-CliPs1 $packPs1 @('-Action', 'EmbedImages', '-HtmlPath', 'work\draft.html', '-OutHtmlPath', 'output\unsafe_vi.html', '-CleanDir', 'output')
            Assert-True ($rUnsafe.ExitCode -ne 0 -and $rUnsafe.Output -match 'Refusing to clean unsafe directory') "Should refuse CleanDir output: $($rUnsafe.Output)"
            Assert-True (-not (Test-Path -LiteralPath (Join-Path $outDir 'unsafe_vi.html'))) 'Invalid -CleanDir must fail before any output is written (a re-run would otherwise create _2)'

            # Full packaging with -AlsoPdf and -CleanDir work
            $rOk = Invoke-CliPs1 $packPs1 @('-Action', 'EmbedImages', '-HtmlPath', 'work\draft.html', '-OutHtmlPath', 'output\e2e_vi.html', '-AlsoPdf', '-CleanDir', 'work')
            Assert-Equal 0 $rOk.ExitCode "E2E step 4 failed: $($rOk.Output)"
            Assert-True (Test-Path -LiteralPath (Join-Path $outDir 'e2e_vi.html') -PathType Leaf) 'e2e_vi.html missing'
            Assert-True (-not (Test-Path -LiteralPath $workDir)) 'work\ should be cleaned after success'
            if (Find-LocalBrowser) {
                Assert-True (Test-Path -LiteralPath (Join-Path $outDir 'e2e_vi.pdf') -PathType Leaf) 'e2e_vi.pdf missing despite browser installed'
            }

            # Lock resilience when work\ holds a locked file
            [void][System.IO.Directory]::CreateDirectory($workDir)
            $draft2 = Join-Path $workDir 'draft.html'
            [System.IO.File]::WriteAllText($draft2, '<!DOCTYPE html><html><head><title>Lock</title></head><body><h1>Lock</h1></body></html>', (New-Object System.Text.UTF8Encoding($false)))
            $fs = [System.IO.File]::Open((Join-Path $workDir 'locked.tmp'), [System.IO.FileMode]::Create, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
            try {
                $rLock = Invoke-CliPs1 $packPs1 @('-Action', 'EmbedImages', '-HtmlPath', 'work\draft.html', '-OutHtmlPath', 'output\lock_vi.html', '-CleanDir', 'work')
                Assert-Equal 0 $rLock.ExitCode "Locked work\ should warn rather than fail: $($rLock.Output)"
                Assert-True ($rLock.Output -match 'Could not fully clean temp directory') "Expected lock warning: $($rLock.Output)"
            } finally {
                $fs.Dispose()
            }
        } finally {
            Pop-Location
        }
    }

    Invoke-TestCase 'Path arguments with spaces and a trailing backslash reach extract_assets.exe intact' {
        Assert-Equal 'C:\my dir\\' (ConvertTo-NativeArgument -Value 'C:\my dir\') 'Trailing backslash after whitespace must be doubled'
        Assert-Equal '--out-dir=C:\a b\\\\' (ConvertTo-NativeArgument -Value '--out-dir=C:\a b\\') 'Every trailing backslash must be doubled'
        Assert-Equal 'C:\nospace\' (ConvertTo-NativeArgument -Value 'C:\nospace\') 'Unquoted arguments must stay unchanged'
        Assert-Equal 'C:\my dir\x.pdf' (ConvertTo-NativeArgument -Value 'C:\my dir\x.pdf') 'No trailing backslash: unchanged'
        Assert-Equal '' (ConvertTo-NativeArgument -Value '') 'Empty argument stays empty'

        $fbPs1 = Join-Path $toolsDir 'pdf_fallback_tools.ps1'
        $memoPdf = Join-Path (Join-Path $PSScriptRoot 'fixtures') 'synthetic_scanned_memo.pdf'
        $spacedDir = Join-Path $tmpRoot 'spaced out dir'
        # Call the wrapper in-process: spawning powershell.exe would hit the same legacy quoting bug one layer
        # earlier (in the test harness itself), so only the wrapper -> extract_assets.exe hop is exercised here.
        $out = (& $fbPs1 -Action RenderPages -PdfPath $memoPdf -OutDir ($spacedDir + '\') -Pages '1' 2>&1 | Out-String)
        Assert-True (Test-Path -LiteralPath (Join-Path $spacedDir 'page_1.png') -PathType Leaf) "RenderPages with spaced OutDir ending in '\' failed: $out"
    }

    Invoke-TestCase 'Committed fixtures (standard, pure scan, mixed scan) extract and fallback cleanly' {
        $fixDir = Join-Path $PSScriptRoot 'fixtures'
        $extractPs1 = Join-Path $toolsDir 'extract_pdf_assets.ps1'
        $fbPs1 = Join-Path $toolsDir 'pdf_fallback_tools.ps1'
        $fixOut = Join-Path $tmpRoot 'fix_verify'

        # 1. Standard 6-page multi-feature benchmark PDF
        $stdPdf = Join-Path $fixDir 'synthetic_urban_benchmark.pdf'
        $stdAssets = Join-Path $fixOut 'std'
        $rStd = Invoke-CliPs1 $extractPs1 @('-PdfPath', $stdPdf, '-OutDir', $stdAssets, '-Meta')
        Assert-Equal 0 $rStd.ExitCode "Standard fixture failed: $($rStd.Output)"
        $mStd = Get-Content (Join-Path $stdAssets 'manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        Assert-Equal 180 $mStd.dpi 'Standard fixture manifest dpi'
        Assert-Equal 6 $mStd.total_pages 'Standard fixture page count'
        Assert-Equal 0 $mStd.scanned_pages.Count 'Standard fixture should have 0 scanned pages'
        Assert-Equal 8 $mStd.figures.Count 'Standard fixture should extract 8 figures (rejecting code box and Table 1)'
        Assert-True ($mStd.figures[0].caption -match '^Figure 1:') 'Fig 1 flowchart caption'
        Assert-Equal 'vector' $mStd.figures[0].source 'Fig 1 should be classified as vector'
        Assert-True ($mStd.figures[0].drawings -ge 10) 'Fig 1 should report vector drawings count'
        Assert-Equal 'figure' $mStd.figures[0].placement 'Fig 1 placement'
        Assert-True ($mStd.figures[1].caption -match '^Figure 2:') 'Fig 2 multipanel caption'
        Assert-Equal 'raster' $mStd.figures[1].source 'Fig 2 should be classified as raster'
        Assert-True ($mStd.figures[2].caption -match '^Figure 3:') 'Fig 3 chalkboard caption'
        Assert-Equal $null $mStd.figures[3].caption 'Table 2 row 1 thumbnail should have null caption'
        Assert-Equal 'table_cell' $mStd.figures[3].placement 'Table 2 row 1 thumbnail should report table_cell placement'
        Assert-True ($mStd.figures[3].context -match 'Botanical Foreground') 'Table 2 row 1 thumbnail should capture adjacent row text'
        Assert-Equal $null $mStd.figures[4].caption 'Table 2 row 2 thumbnail should have null caption'
        Assert-Equal 'table_cell' $mStd.figures[4].placement 'Table 2 row 2 thumbnail should report table_cell placement'
        Assert-True ($mStd.figures[4].context -match 'Facade Geometry') 'Table 2 row 2 thumbnail should capture adjacent row text'
        Assert-True ($mStd.figures[5].caption -match '^Figure 4:') 'Fig 4 vector chart caption'
        Assert-Equal 'vector' $mStd.figures[5].source 'Fig 4 should be classified as vector'
        Assert-True ($mStd.figures[6].caption -match '^Fig\. S1:') 'Fig S1 supplementary caption'
        Assert-True ($mStd.figures[7].caption -match '^Fig\. S2:') 'Fig S2 rectification vector caption'
        foreach ($fig in $mStd.figures) {
            Assert-Equal 4 @($fig.box).Count "Normalized box array length for $($fig.file)"
            Assert-True ($fig.box[0] -ge 0.0 -and $fig.box[2] -le 1.0 -and $fig.box[0] -lt $fig.box[2]) "Normalized box X bounds for $($fig.file)"
            Assert-True ($fig.box[1] -ge 0.0 -and $fig.box[3] -le 1.0 -and $fig.box[1] -lt $fig.box[3]) "Normalized box Y bounds for $($fig.file)"
        }

        # 2. Pure 2-page scanned PDF: Egret crops the photos straight from the page scans (no scanned_pages left
        #    for the manual fallback); RenderPages + CropFromJson auto_trim still work for manual crops
        $scanPdf = Join-Path $fixDir 'synthetic_scanned_memo.pdf'
        $scanAssets = Join-Path $fixOut 'scan'
        $rScan = Invoke-CliPs1 $extractPs1 @('-PdfPath', $scanPdf, '-OutDir', $scanAssets, '-Meta')
        Assert-Equal 0 $rScan.ExitCode "Scan fixture failed: $($rScan.Output)"
        $mScan = Get-Content (Join-Path $scanAssets 'manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        Assert-Equal 2 $mScan.total_pages 'Scan fixture page count'
        Assert-Equal 0 $mScan.scanned_pages.Count 'Scan pages with cropped figures are not left for the manual fallback'
        Assert-Equal 3 $mScan.figures.Count 'Egret should crop 2 photos on page 1 and 1 on page 2'
        foreach ($fig in $mScan.figures) { Assert-Equal 'raster' $fig.source "Scanned crop $($fig.file) must be raster (Group B)" }

        $scanPages = Join-Path $fixOut 'scan_pages'
        $rFb = Invoke-CliPs1 $fbPs1 @('-Action', 'RenderPages', '-PdfPath', $scanPdf, '-OutDir', $scanPages, '-Scale', '1.5')
        Assert-Equal 0 $rFb.ExitCode "RenderPages on scan fixture failed: $($rFb.Output)"
        $p2Png = Join-Path $scanPages 'page_2.png'
        Assert-True (Test-Path -LiteralPath $p2Png -PathType Leaf) 'Scan page_2.png missing'

        $cropSpec = Join-Path $fixOut 'scan_crop.json'
        $cropData = @(@{ page_png = $p2Png; box = @(0.14, 0.16, 0.86, 0.54); out_name = 'corgi_trim.png'; auto_trim = $true }) | ConvertTo-Json
        [System.IO.File]::WriteAllText($cropSpec, $cropData, (New-Object System.Text.UTF8Encoding($false)))
        $rCrop = Invoke-CliPs1 $fbPs1 @('-Action', 'CropFromJson', '-SpecJson', $cropSpec, '-OutDir', $scanAssets)
        Assert-Equal 0 $rCrop.ExitCode "CropFromJson on scan fixture failed: $($rCrop.Output)"
        Assert-True (Test-Path -LiteralPath (Join-Path $scanAssets 'corgi_trim.png') -PathType Leaf) 'Trimmed scan figure missing'

        # 3. Mixed 3-page PDF (electronic p1 & p3, scanned p2)
        $mixPdf = Join-Path $fixDir 'synthetic_mixed_scan_report.pdf'
        $mixAssets = Join-Path $fixOut 'mix'
        $rMix = Invoke-CliPs1 $extractPs1 @('-PdfPath', $mixPdf, '-OutDir', $mixAssets, '-Meta')
        Assert-Equal 0 $rMix.ExitCode "Mixed fixture failed: $($rMix.Output)"
        $mMix = Get-Content (Join-Path $mixAssets 'manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        Assert-Equal 3 $mMix.total_pages 'Mixed fixture page count'
        Assert-Equal 0 $mMix.scanned_pages.Count 'Mixed fixture: the photo on scanned page 2 is cropped directly'
        Assert-Equal 3 $mMix.figures.Count 'Mixed fixture should extract p1, the p2 scan photo and p3'
        Assert-True ($mMix.figures[0].caption -match '^Figure 1:') 'Mixed p1 caption'
        Assert-Equal 'raster' $mMix.figures[0].source 'Mixed p1 should be raster'
        Assert-Equal 2 $mMix.figures[1].page 'Mixed second figure comes from scanned page 2'
        Assert-Equal 'raster' $mMix.figures[1].source 'Mixed p2 scan crop should be raster'
        Assert-True ($mMix.figures[2].caption -match '^Figure 3:') 'Mixed p3 caption'
        Assert-Equal 'vector' $mMix.figures[2].source 'Mixed p3 should be vector'

        # Selective -Pages rendering on mixed PDF (render only scanned page 2, and bracketed [1, 3])
        $mixPagesScanOnly = Join-Path $fixOut 'mix_scan_only'
        $rMixP2 = Invoke-CliPs1 $fbPs1 @('-Action', 'RenderPages', '-PdfPath', $mixPdf, '-OutDir', $mixPagesScanOnly, '-Pages', '2', '-Scale', '1.2')
        Assert-Equal 0 $rMixP2.ExitCode "RenderPages -Pages 2 failed: $($rMixP2.Output)"
        Assert-True (Test-Path -LiteralPath (Join-Path $mixPagesScanOnly 'page_2.png') -PathType Leaf) 'page_2.png should be rendered'
        Assert-True (-not (Test-Path -LiteralPath (Join-Path $mixPagesScanOnly 'page_1.png'))) 'page_1.png should NOT be rendered'
        Assert-True (-not (Test-Path -LiteralPath (Join-Path $mixPagesScanOnly 'page_3.png'))) 'page_3.png should NOT be rendered'

        $mixPagesBrackets = Join-Path $fixOut 'mix_p1_p3'
        $rMixP13 = Invoke-CliPs1 $fbPs1 @('-Action', 'RenderPages', '-PdfPath', $mixPdf, '-OutDir', $mixPagesBrackets, '-Pages', '[1, 3]', '-Scale', '1.2')
        Assert-Equal 0 $rMixP13.ExitCode "RenderPages -Pages [1, 3] failed: $($rMixP13.Output)"
        Assert-True (Test-Path -LiteralPath (Join-Path $mixPagesBrackets 'page_1.png') -PathType Leaf) 'page_1.png missing'
        Assert-True (-not (Test-Path -LiteralPath (Join-Path $mixPagesBrackets 'page_2.png'))) 'page_2.png should NOT be rendered'
        Assert-True (Test-Path -LiteralPath (Join-Path $mixPagesBrackets 'page_3.png') -PathType Leaf) 'page_3.png missing'

        foreach ($badPages in @('0', '99', '3-1', 'abc')) {
            $rBadPg = Invoke-CliPs1 $fbPs1 @('-Action', 'RenderPages', '-PdfPath', $mixPdf, '-OutDir', $mixPagesScanOnly, '-Pages', $badPages)
            Assert-True ($rBadPg.ExitCode -ne 0) "Invalid -Pages '$badPages' should fail"
        }
    }

    Invoke-TestCase 'Bundled layout_samples PDFs extract exact figures, captions, and zero UI/banner false positives' {
        $samplesDir = Join-Path $PSScriptRoot 'layout_samples'
        $extractPs1 = Join-Path $toolsDir 'extract_pdf_assets.ps1'
        $sampleOut = Join-Path $tmpRoot 'layout_samples_out'

        # 1. journal_2col_academic.pdf: 6 figures (3 table_cell thumbnails + Fig 1..3 with full multi-line Fig 3 caption)
        $jAssets = Join-Path $sampleOut 'journal'
        $rJ = Invoke-CliPs1 $extractPs1 @('-PdfPath', (Join-Path $samplesDir 'journal_2col_academic.pdf'), '-OutDir', $jAssets, '-Dpi', '96', '-Meta')
        Assert-Equal 0 $rJ.ExitCode "journal_2col_academic failed: $($rJ.Output)"
        $mJ = Get-Content (Join-Path $jAssets 'manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        # 7 images: Fig 1, 3 table_cell thumbnails, the 2 panels of Fig 2 (its whole-figure box scores 0.4984 < 0.5,
        # so as in Docling the panels stay separate; Docling links a caption to one graphic only, so one panel
        # carries the Fig 2 caption and the other has none) and Fig 3.
        Assert-Equal 7 $mJ.figures.Count 'journal_2col_academic figure count'
        Assert-Equal 0 $mJ.scanned_pages.Count 'journal_2col_academic scanned pages'
        $jThumbCount = @($mJ.figures | Where-Object { $_.placement -eq 'table_cell' }).Count
        Assert-Equal 3 $jThumbCount 'journal_2col_academic table_cell thumbnails'
        Assert-Equal 1 @($mJ.figures | Where-Object { $_.caption -match '^Figure 2:' }).Count 'journal_2col_academic Fig 2 caption on one panel'
        Assert-Equal 1 @($mJ.figures | Where-Object { $_.page -eq 3 -and $_.placement -eq 'figure' -and -not $_.caption }).Count 'journal_2col_academic Fig 2 second panel uncaptioned'
        $jFig3 = @($mJ.figures | Where-Object { $_.caption -match '^Figure 3:' })
        Assert-Equal 1 $jFig3.Count 'journal_2col_academic Fig 3'
        Assert-True ($jFig3[0].caption -match 'ksat = 0\.04 cm/s') 'journal_2col_academic full Fig 3 multi-line caption'

        # 2. executive_magazine_mixed.pdf: Fig 1, Fig 2 (both tables on p2 rejected) + 3 crops from scanned page 3
        $mAssets = Join-Path $sampleOut 'magazine'
        $rM = Invoke-CliPs1 $extractPs1 @('-PdfPath', (Join-Path $samplesDir 'executive_magazine_mixed.pdf'), '-OutDir', $mAssets, '-Dpi', '96', '-Meta')
        Assert-Equal 0 $rM.ExitCode "executive_magazine_mixed failed: $($rM.Output)"
        $mM = Get-Content (Join-Path $mAssets 'manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        Assert-Equal 5 $mM.figures.Count 'executive_magazine_mixed figure count'
        Assert-Equal 0 $mM.scanned_pages.Count 'executive_magazine_mixed: scanned page 3 is cropped directly'
        Assert-Equal 1 @($mM.figures | Where-Object { $_.page -eq 2 }).Count 'executive_magazine_mixed p2: tables must not become images'
        Assert-Equal 3 @($mM.figures | Where-Object { $_.page -eq 3 -and $_.source -eq 'raster' }).Count 'executive_magazine_mixed p3 scan crops'
        Assert-True ($mM.figures[1].caption -match 'Page 3') 'executive_magazine_mixed full Fig 2 multi-line caption'

        # 3. product_datasheet_grid.pdf: exact 3 figures (hero banner, left sidebar, and 3 pricing cards rejected)
        $dAssets = Join-Path $sampleOut 'datasheet'
        $rD = Invoke-CliPs1 $extractPs1 @('-PdfPath', (Join-Path $samplesDir 'product_datasheet_grid.pdf'), '-OutDir', $dAssets, '-Dpi', '96', '-Meta')
        Assert-Equal 0 $rD.ExitCode "product_datasheet_grid failed: $($rD.Output)"
        $mD = Get-Content (Join-Path $dAssets 'manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        Assert-Equal 3 $mD.figures.Count 'product_datasheet_grid figure count'
        Assert-Equal 0 $mD.scanned_pages.Count 'product_datasheet_grid scanned pages'
        Assert-True ($mD.figures[0].caption -match '^Figure 1:') 'datasheet Fig 1 caption'
        Assert-True ($mD.figures[1].caption -match '^Figure 2:') 'datasheet Fig 2 caption'
        Assert-True ($mD.figures[2].caption -match '^Figure 3:') 'datasheet Fig 3 caption'
    }

    Invoke-TestCase 'extract_pdf_assets.ps1 always uses the bundled Egret model and offers no other detector' {
        $extractPs1 = Join-Path $toolsDir 'extract_pdf_assets.ps1'
        $egretModel = Join-Path $toolsDir 'extract_assets\_internal\models\egret_medium.onnx'
        $egDir = Join-Path $tmpRoot 'egret_only'
        $memoPdf = Join-Path $repoRoot 'tests\fixtures\synthetic_scanned_memo.pdf'

        Assert-True (Test-Path -LiteralPath $egretModel -PathType Leaf) "Release build must bundle the Egret model: $egretModel"
        $r = Invoke-CliPs1 $extractPs1 @('-PdfPath', $memoPdf, '-OutDir', (Join-Path $egDir 'scan'), '-Meta')
        Assert-Equal 0 $r.ExitCode "Extraction failed: $($r.Output)"
        Assert-True ($r.Output -notmatch 'heuristic') "No fallback detector may run: $($r.Output)"
        $m = Get-Content (Join-Path $egDir 'scan\manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        Assert-Equal 'egret' $m.detector 'manifest must record the Egret detector'

        # The wrapper has no -Detector parameter: an extra '-Detector heuristic' is ignored and Egret still runs.
        $rSel = Invoke-CliPs1 $extractPs1 @('-Detector', 'heuristic', '-PdfPath', $memoPdf, '-OutDir', (Join-Path $egDir 'sel'), '-Meta')
        Assert-Equal 0 $rSel.ExitCode "Extraction with a stray -Detector argument failed: $($rSel.Output)"
        $mSel = Get-Content (Join-Path $egDir 'sel\manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        Assert-Equal 'egret' $mSel.detector 'The rule-based detector must not be reachable through the wrapper'
    }

    Invoke-TestCase 'Security hardening: NTFS ADS, metachar filenames, auto-sanitization, HtmlToPdf QA, allowlist, and CSP' {
        $extractPs1 = Join-Path $toolsDir 'extract_pdf_assets.ps1'
        $packPs1 = Join-Path $toolsDir 'html_packager.ps1'
        $secDir = Join-Path $tmpRoot 'sec_hardening'
        [void][System.IO.Directory]::CreateDirectory($secDir)

        # 1. _path_guards.ps1 blocks NTFS ADS
        Assert-Throws { Assert-LocalNoUncPath -PathValue 'output\doc.html:evil.exe' -ParamName 'Out' } 'NTFS Alternate Data Stream' 'Should block NTFS ADS'

        # 2. PDF filename with PowerShell metacharacters extracts safely without executing expressions
        $weirdPdf = Join-Path $secDir 'report_$(whoami)_$x.pdf'
        New-MinimalVectorPdf -OutPath $weirdPdf
        $weirdAssets = Join-Path $secDir 'assets'
        $rWeird = Invoke-CliPs1 $extractPs1 @('-PdfPath', $weirdPdf, '-OutDir', $weirdAssets, '-Meta')
        Assert-Equal 0 $rWeird.ExitCode "Weird filename PDF extraction failed: $($rWeird.Output)"
        Assert-True (Test-Path -LiteralPath (Join-Path $weirdAssets 'fig_p1_1.png') -PathType Leaf) 'Extracted figure missing for metachar PDF'

        # 3. Output filename auto-sanitization (CON.html & metachar name) + CSP meta injection
        $okDraft = Join-Path $secDir 'ok_draft.html'
        [System.IO.File]::WriteAllText($okDraft, '<!DOCTYPE html><html><head><title>Sec</title></head><body><h1>Safe</h1></body></html>', (New-Object System.Text.UTF8Encoding($false)))
        $secOut = Join-Path $secDir 'out'
        $rCon = Invoke-CliPs1 $packPs1 @('-Action', 'EmbedImages', '-HtmlPath', $okDraft, '-OutHtmlPath', (Join-Path $secOut 'CON.html'), '-PreserveLayout')
        Assert-Equal 0 $rCon.ExitCode "Auto-sanitizing CON.html failed: $($rCon.Output)"
        Assert-True ($rCon.Output -match 'Sanitized unsafe output filename') 'Should report sanitized filename'
        $sanCon = Join-Path $secOut 'doc_CON.html'
        Assert-True (Test-Path -LiteralPath $sanCon -PathType Leaf) 'doc_CON.html should be written'
        $conHtml = [System.IO.File]::ReadAllText($sanCon, [System.Text.Encoding]::UTF8)
        Assert-True ($conHtml -match 'http-equiv="Content-Security-Policy" data-max-luka-csp="1"') 'CSP meta should be injected'
        Assert-True ($conHtml -match "script-src 'none';") 'PreserveLayout without MathJax should lock script-src none'

        $rMetaOut = Invoke-CliPs1 $packPs1 @('-Action', 'EmbedImages', '-HtmlPath', $okDraft, '-OutHtmlPath', (Join-Path $secOut 'report_$(calc)_vi.html'))
        Assert-Equal 0 $rMetaOut.ExitCode "Auto-sanitizing metachar output failed: $($rMetaOut.Output)"
        Assert-True ($rMetaOut.Output -match 'Sanitized unsafe output filename') 'Should report sanitized metachar output'
        $sanMeta = Join-Path $secOut 'report_(calc)_vi.html'
        Assert-True (Test-Path -LiteralPath $sanMeta -PathType Leaf) 'Sanitized metachar HTML should exist'
        $metaHtml = [System.IO.File]::ReadAllText($sanMeta, [System.Text.Encoding]::UTF8)
        Assert-True ($metaHtml -match "script-src 'sha256-") 'Normal mode should inject SHA-256 CSP for reader_shell'

        # 4. Direct -Action HtmlToPdf must enforce Auto-QA and block malicious <script>
        $evilHtml = Join-Path $secDir 'evil_script.html'
        [System.IO.File]::WriteAllText($evilHtml, '<!DOCTYPE html><html><head></head><body><script>alert(1)</script></body></html>', (New-Object System.Text.UTF8Encoding($false)))
        $evilPdf = Join-Path $secOut 'evil_script.pdf'
        $rEvilPdf = Invoke-CliPs1 $packPs1 @('-Action', 'HtmlToPdf', '-HtmlPath', $evilHtml, '-OutPdfPath', $evilPdf)
        Assert-True ($rEvilPdf.ExitCode -ne 0 -and $rEvilPdf.Output -match 'Disallowed <script>') "HtmlToPdf should block malicious script: $($rEvilPdf.Output)"
        Assert-True (-not (Test-Path -LiteralPath $evilPdf)) 'evil_script.pdf must not be created'

        # 5. Red-team allowlist & ADS rejections via CLI
        $badPayloads = @(
            @{ Name = 'search_ms'; Html = '<!DOCTYPE html><html><head></head><body><a href="search-ms:crumb=location:\\evil\s">x</a></body></html>'; Rx = 'Disallowed dangerous URI' },
            @{ Name = 'latex_js';  Html = '<!DOCTYPE html><html><head><script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script></head><body><p>\( \href{javascript:alert(1)}{x} \)</p></body></html>'; Rx = 'Disallowed dangerous URI' },
            @{ Name = 'svg_anim';  Html = '<!DOCTYPE html><html><head></head><body><svg><animate attributeName="href" to="javascript:alert(1)"/></svg></body></html>'; Rx = 'Disallowed HTML tag' },
            @{ Name = 'css_iset';  Html = '<!DOCTYPE html><html><head><style>body{background:image-set("https://evil.example/px.png" 1x);}</style></head><body></body></html>'; Rx = 'Disallowed external resource' }
        )
        foreach ($bp in $badPayloads) {
            $pHtml = Join-Path $secDir ($bp.Name + '.html')
            [System.IO.File]::WriteAllText($pHtml, $bp.Html, (New-Object System.Text.UTF8Encoding($false)))
            $rBad = Invoke-CliPs1 $packPs1 @('-Action', 'EmbedImages', '-HtmlPath', $pHtml, '-OutHtmlPath', (Join-Path $secOut ($bp.Name + '_out.html')), '-PreserveLayout')
            Assert-True ($rBad.ExitCode -ne 0 -and $rBad.Output -match $bp.Rx) "Payload $($bp.Name) should fail QA: $($rBad.Output)"
        }

        $rAds = Invoke-CliPs1 $packPs1 @('-Action', 'EmbedImages', '-HtmlPath', $okDraft, '-OutHtmlPath', (Join-Path $secOut 'doc.html:evil.exe'), '-PreserveLayout')
        Assert-True ($rAds.ExitCode -ne 0 -and $rAds.Output -match 'NTFS Alternate Data Stream') "NTFS ADS output should be rejected: $($rAds.Output)"
    }
} finally {
    Remove-Item -LiteralPath $tmpRoot -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Output ("=== PowerShell Suite Summary: {0} passed, {1} failed ===" -f $script:Passed, $script:Failed)
if ($script:Failed -gt 0) { exit 1 }
