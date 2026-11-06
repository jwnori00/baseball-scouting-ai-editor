param([Parameter(Mandatory=$true)][string]$Assets)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not [Environment]::Is64BitProcess -or $env:OS -ne 'Windows_NT') { throw 'Windows x64 required' }
$Assets = (Resolve-Path $Assets).Path
$env:BSAE_BUILD_ASSETS = $Assets
$env:QT_QPA_PLATFORM = 'offscreen'
py -3.12 -m venv .venv
if ($LASTEXITCODE -ne 0) { throw 'venv failed' }
$Python = Join-Path $PWD '.venv\Scripts\python.exe'
& $Python -m pip install -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw 'Locked dependency install failed' }
& $Python -m pip install --no-deps --no-build-isolation -e .
if ($LASTEXITCODE -ne 0) { throw 'Dependency install failed' }
& $Python packaging/validate_assets.py $Assets
if ($LASTEXITCODE -ne 0) { throw 'Assets failed validation' }
New-Item -ItemType Directory -Force build-evidence | Out-Null
$env:PATH = "$Assets\tools;$env:PATH"
& $Python -m pytest -q --junitxml=build-evidence/windows-tests.xml
if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
& $Python -m PyInstaller --clean --noconfirm packaging/editor.spec
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed' }
& $Python packaging/collect_notices.py dist/BaseballScoutingAIEditor
if ($LASTEXITCODE -ne 0) { throw 'License collection failed' }
# Isolated PATH verifies the executable uses bundled tools.
$PreviousPath = $env:PATH
try {
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
    $Exe = Join-Path $PWD 'dist\BaseballScoutingAIEditor\BaseballScoutingAIEditor.exe'
    $Report = Join-Path $PWD 'build-evidence\portable-smoke.json'
    Remove-Item $Report -ErrorAction SilentlyContinue
    $Process = Start-Process -FilePath $Exe -ArgumentList @('--self-test', "`"$Report`"") -PassThru -Wait
    if ($Process.ExitCode -ne 0 -or -not (Test-Path $Report)) { throw 'Frozen EXE smoke failed' }
    $Result = Get-Content $Report -Raw | ConvertFrom-Json
    if ($Result.synthetic_render -ne 'PASS') { throw 'Frozen renderer failed' }
} finally { $env:PATH = $PreviousPath }
$Zip = Join-Path $PWD 'BaseballScoutingAIEditor-Windows-x64-dev.zip'
if (Test-Path $Zip) { throw 'ZIP exists; preserve it before rebuilding' }
Copy-Item build-evidence dist/BaseballScoutingAIEditor/build-evidence -Recurse
Compress-Archive -Path dist/BaseballScoutingAIEditor -DestinationPath $Zip
$Hash = (Get-FileHash $Zip -Algorithm SHA256).Hash.ToLower()
"$Hash  $([IO.Path]::GetFileName($Zip))" | Set-Content "$Zip.sha256" -Encoding ascii
Write-Host 'Development ZIP created. Baseball accuracy NOT_EVALUATED. Do not label this a completed 1.0 release.'
