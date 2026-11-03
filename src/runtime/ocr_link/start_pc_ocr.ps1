param(
    [string]$BindAddress = '0.0.0.0',
    [int]$Port = 8765,
    [string]$TokenFile = 'output/ocr-link-token',
    [string]$OutputRoot = 'output/ocr-link-server',
    [string]$OptionsFile = 'board_ocr/paddle_lite_trial/v6_tiny/pc_options_precision.json',
    [switch]$LegacyProcesses
)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskRoot
$taskPython = Join-Path $taskRoot '.venv-gpu/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $TokenFile)) {
    & $taskPython -c 'from pathlib import Path; import secrets,sys; p=Path(sys.argv[1]); p.parent.mkdir(parents=True,exist_ok=True); p.open("x",encoding="ascii").write(secrets.token_urlsafe(32))' $TokenFile
    if ($LASTEXITCODE -ne 0) { throw 'Token creation failed' }
    & icacls $TokenFile /inheritance:r /grant:r "$($env:USERNAME):(F)" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Token ACL update failed' }
    Write-Host 'Created private token file; copy it to the board via SSH, then chmod 600. Token is not printed.'
}
$taskArguments = @('-m','ocr_link.server','--host',$BindAddress,'--port',"$Port",'--token-file',$TokenFile,'--output-root',$OutputRoot)
$taskArguments += @('--options', $OptionsFile)
if (-not $LegacyProcesses) { $taskArguments += '--resident-models' }
& $taskPython @taskArguments
exit $LASTEXITCODE
