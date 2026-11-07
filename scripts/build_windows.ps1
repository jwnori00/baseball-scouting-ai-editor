param(
    [string]$Assets = '',
    [ValidateSet('development','rules-preview','release')][string]$Kind = 'development',
    [switch]$DependenciesInstalled
)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not [Environment]::Is64BitProcess -or $env:OS -ne 'Windows_NT') { throw 'Windows x64 required' }
if (-not $Assets) { $Assets = Join-Path $PWD 'vendor\portable' }
$Assets = (Resolve-Path $Assets).Path
$env:BSAE_BUILD_ASSETS = $Assets
$env:BSAE_BUILD_KIND = $Kind
$env:QT_QPA_PLATFORM = 'offscreen'
if (-not $DependenciesInstalled) {
    py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'venv failed' }
    $Python = Join-Path $PWD '.venv\Scripts\python.exe'
    & $Python -m pip install -r requirements-dev.txt
    if ($LASTEXITCODE -ne 0) { throw 'Locked dependency install failed' }
    & $Python -m pip install --no-deps --no-build-isolation -e .
    if ($LASTEXITCODE -ne 0) { throw 'Project install failed' }
} else { $Python = (Get-Command python).Source }
$BuildTag = ((& git rev-parse --short HEAD).Trim() + '-' + [guid]::NewGuid().ToString('N'))
$OutputFolder = Join-Path $PWD ('build-output\' + $BuildTag)
New-Item -ItemType Directory $OutputFolder | Out-Null
New-Item -ItemType Directory -Force build-evidence | Out-Null
$PriorEvidence = Join-Path $OutputFolder 'prior-evidence'
foreach ($Pattern in @('portable-smoke*.json','layout-*.json','layout-*.png','unpacked-exe.*','archive-check.json','windows-tests.xml','build-info.json','CLIENT_MANUAL.txt','windows-version.txt','portable-package.json','platform-status.json')) {
    foreach ($Existing in Get-ChildItem build-evidence -Filter $Pattern -File) {
        New-Item -ItemType Directory -Force $PriorEvidence | Out-Null
        Move-Item $Existing.FullName (Join-Path $PriorEvidence $Existing.Name)
    }
}
& $Python packaging/validate_assets.py $Assets $Kind
if ($LASTEXITCODE -ne 0) { throw 'Assets or release model failed validation' }
& $Python packaging/write_build_policy.py $Assets $Kind
if ($LASTEXITCODE -ne 0) { throw 'Build provenance failed' }
$BuildInfo = Get-Content (Join-Path $Assets 'build-policy.json') -Raw | ConvertFrom-Json
$env:PATH = "$Assets\tools;$env:PATH"
& $Python -m pytest -q --junitxml=build-evidence/windows-tests.xml
if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
& $Python -m PyInstaller --clean --noconfirm packaging/editor.spec
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed' }
& $Python packaging/collect_notices.py dist/BaseballScoutingAIEditor
if ($LASTEXITCODE -ne 0) { throw 'License collection failed' }
Copy-Item build-evidence/CLIENT_MANUAL.txt dist/BaseballScoutingAIEditor/사용설명서.txt
Copy-Item build-evidence/CLIENT_MANUAL.txt dist/BaseballScoutingAIEditor/_internal/docs/CLIENT_MANUAL.txt
$PreviousPath = $env:PATH
try {
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
    $Report = Join-Path $PWD 'build-evidence\portable-smoke.json'
    if (Test-Path $Report) { Remove-Item $Report }
    $UnicodeInstall = Join-Path $env:TEMP ('야구 설치 Martínez ' + [guid]::NewGuid().ToString('N'))
    Copy-Item dist/BaseballScoutingAIEditor $UnicodeInstall -Recurse
    $Exe = Join-Path $UnicodeInstall 'BaseballScoutingAIEditor.exe'
    $Signature = Get-AuthenticodeSignature $Exe
    @{signature_status=[string]$Signature.Status;clean_user_pc='NOT_TESTED';smart_screen='NOT_TESTED';antivirus_scan='NOT_TESTED';hosted_windows='GitHub Actions'} | ConvertTo-Json | Set-Content build-evidence/platform-status.json -Encoding utf8
    $PreviousScale = $env:QT_SCALE_FACTOR
    try {
        foreach ($Scale in @('1','1.5','2')) {
            $env:QT_SCALE_FACTOR = $Scale
            $LayoutReport = Join-Path $PWD ('build-evidence\layout-' + $Scale + '.json')
            $LayoutProcess = Start-Process -FilePath $Exe -WorkingDirectory $UnicodeInstall -ArgumentList @('--layout-probe', "`"$LayoutReport`"") -PassThru
            if (-not $LayoutProcess.WaitForExit(30000)) { $LayoutProcess.Kill(); throw 'DPI probe timeout' }
            if ($LayoutProcess.ExitCode -ne 0) { throw ('DPI layout probe failed: ' + $Scale) }
        }
    } finally { $env:QT_SCALE_FACTOR = $PreviousScale }

    $Process = Start-Process -FilePath $Exe -WorkingDirectory $UnicodeInstall -ArgumentList @('--self-test', "`"$Report`"") -PassThru
    if (-not $Process.WaitForExit(180000)) { $Process.Kill(); throw 'Frozen EXE test timed out' }
    if ($Process.ExitCode -ne 0 -or -not (Test-Path $Report)) { throw 'Frozen EXE smoke failed' }
    $Result = Get-Content $Report -Raw | ConvertFrom-Json
    if ($Result.synthetic_render -ne 'PASS' -or $Result.gui_construction -ne 'PASS') { throw 'Frozen workflow failed' }
} finally {
    $env:PATH = $PreviousPath
    if ($UnicodeInstall -and (Test-Path $UnicodeInstall)) { Remove-Item $UnicodeInstall -Recurse -Force }
}
$Zip = Join-Path $OutputFolder "BaseballScoutingAIEditor-Windows-x64-$Kind.zip"
Copy-Item build-evidence dist/BaseballScoutingAIEditor/build-evidence -Recurse
# Complete corresponding source is distributed beside the application artifact.
Compress-Archive -Path dist/BaseballScoutingAIEditor -DestinationPath $Zip
$Hash = (Get-FileHash $Zip -Algorithm SHA256).Hash.ToLower()
"$Hash  $([IO.Path]::GetFileName($Zip))" | Set-Content "$Zip.sha256" -Encoding ascii
@{file=[IO.Path]::GetFileName($Zip);sha256=$Hash;version=$BuildInfo.version;kind=$Kind;engine=$BuildInfo.engine;commit=$BuildInfo.commit;built_at=$BuildInfo.built_at} | ConvertTo-Json | Set-Content build-evidence/portable-package.json -Encoding utf8
Write-Host "$Kind portable ZIP and SHA-256 created."

# Verify the delivered archive, not only the pre-ZIP build directory.
$ArchivePreviousPath = $env:PATH
$env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
$UnzipRoot = Join-Path $env:TEMP ('야구 RC ZIP ' + [guid]::NewGuid().ToString('N'))
try {
    if ((Get-FileHash $Zip -Algorithm SHA256).Hash.ToLower() -ne $Hash) { throw 'ZIP checksum mismatch' }
    Expand-Archive -Path $Zip -DestinationPath $UnzipRoot
    $UnpackedExe = Join-Path $UnzipRoot 'BaseballScoutingAIEditor\BaseballScoutingAIEditor.exe'
    $UnpackedReport = Join-Path $PWD 'build-evidence\unpacked-exe.json'
    $Probe = Start-Process -FilePath $UnpackedExe -ArgumentList @('--layout-probe', "`"$UnpackedReport`"") -PassThru
    if (-not $Probe.WaitForExit(30000)) { $Probe.Kill(); throw 'Unpacked EXE timeout' }
    if ($Probe.ExitCode -ne 0) { throw 'Unpacked EXE failed' }
    @{zip_sha256='PASS';unpacked_executable='PASS';commit=$BuildInfo.commit} | ConvertTo-Json | Set-Content build-evidence/archive-check.json -Encoding utf8
} finally {
    $env:PATH = $ArchivePreviousPath
    if (Test-Path $UnzipRoot) { Remove-Item $UnzipRoot -Recurse -Force }
}

if ($env:GITHUB_OUTPUT) {
    "zip=$Zip" >> $env:GITHUB_OUTPUT
    "checksum=$Zip.sha256" >> $env:GITHUB_OUTPUT
}
Write-Host "Verified portable archive: $Zip"
