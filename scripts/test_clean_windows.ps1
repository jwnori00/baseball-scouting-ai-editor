param(
    [Parameter(Mandatory=$true)][string]$Exe,
    [Parameter(Mandatory=$true)][string]$Plan,
    [Parameter(Mandatory=$true)][string]$Report
)
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT' -or -not [Environment]::Is64BitProcess) { throw 'Windows x64 required' }
foreach ($Tool in @('python','python3','pip','ffmpeg','ffprobe','tesseract')) {
    if (Get-Command $Tool -ErrorAction SilentlyContinue) {
        throw "Clean PC prerequisite not established: $Tool is on PATH. Use a fresh Windows test VM."
    }
}
$Exe = (Resolve-Path $Exe).Path
$Plan = (Resolve-Path $Plan).Path
if (Test-Path $Report) { throw 'Preserve existing acceptance report before running' }
$Process = Start-Process -FilePath $Exe -ArgumentList @('--acceptance-test', "`"$Plan`"", "`"$Report`"") -Wait -PassThru
if (-not (Test-Path $Report)) { throw 'Executable did not produce acceptance report' }
if ($Process.ExitCode -ne 0) { throw 'Acceptance failed or required metrics remain NOT_EVALUATED. Read report.' }
Write-Host 'Automated local checks passed. Complete manual GUI/offline checklist in docs/PACKAGING.md.'
