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
New-Item -ItemType Directory -Force build-evidence | Out-Null
& $Python packaging/validate_assets.py $Assets $Kind
if ($LASTEXITCODE -ne 0) { throw 'Assets or release model failed validation' }
@{kind=$Kind;automatic_analysis=($Kind -ne 'development');engine='broadcast-rules-v1';version='1.0.0.integration-preview5'} | ConvertTo-Json | Set-Content (Join-Path $Assets 'build-policy.json') -Encoding utf8
$env:PATH = "$Assets\tools;$env:PATH"
& $Python -m pytest -q --junitxml=build-evidence/windows-tests.xml
if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
& $Python -m PyInstaller --clean --noconfirm packaging/editor.spec
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed' }
& $Python packaging/collect_notices.py dist/BaseballScoutingAIEditor
if ($LASTEXITCODE -ne 0) { throw 'License collection failed' }
$PreviousPath = $env:PATH
try {
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
    $Report = Join-Path $PWD 'build-evidence\portable-smoke.json'
    if (Test-Path $Report) { Remove-Item $Report }
    $UnicodeInstall = Join-Path $env:TEMP ('야구 설치 Martínez ' + [guid]::NewGuid().ToString('N'))
    Copy-Item dist/BaseballScoutingAIEditor $UnicodeInstall -Recurse
    $Exe = Join-Path $UnicodeInstall 'BaseballScoutingAIEditor.exe'
    $Process = Start-Process -FilePath $Exe -WorkingDirectory $UnicodeInstall -ArgumentList @('--self-test', "`"$Report`"") -PassThru
    if (-not $Process.WaitForExit(180000)) { $Process.Kill(); throw 'Frozen EXE test timed out' }
    if ($Process.ExitCode -ne 0 -or -not (Test-Path $Report)) { throw 'Frozen EXE smoke failed' }
    $Result = Get-Content $Report -Raw | ConvertFrom-Json
    if ($Result.synthetic_render -ne 'PASS' -or $Result.gui_construction -ne 'PASS') { throw 'Frozen workflow failed' }
} finally {
    $env:PATH = $PreviousPath
    if ($UnicodeInstall -and (Test-Path $UnicodeInstall)) { Remove-Item $UnicodeInstall -Recurse -Force }
}
$Zip = Join-Path $PWD "BaseballScoutingAIEditor-Windows-x64-$Kind.zip"
if (Test-Path $Zip) { throw 'ZIP exists; preserve it before rebuilding' }
Copy-Item build-evidence dist/BaseballScoutingAIEditor/build-evidence -Recurse
# Complete corresponding source is distributed beside the application artifact.
Compress-Archive -Path dist/BaseballScoutingAIEditor -DestinationPath $Zip
$Hash = (Get-FileHash $Zip -Algorithm SHA256).Hash.ToLower()
"$Hash  $([IO.Path]::GetFileName($Zip))" | Set-Content "$Zip.sha256" -Encoding ascii
@{file=[IO.Path]::GetFileName($Zip);sha256=$Hash;version='1.0.0.integration-preview5';kind=$Kind} | ConvertTo-Json | Set-Content build-evidence/portable-package.json -Encoding utf8
Write-Host "$Kind portable ZIP and SHA-256 created."
