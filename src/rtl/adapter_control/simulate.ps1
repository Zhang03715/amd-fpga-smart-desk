param([string]$VivadoBin='D:/AMDDesignTools/2025.2/Vivado/bin')
$ErrorActionPreference='Stop'
$taskFolder=Join-Path $PSScriptRoot 'simulation'
New-Item -ItemType Directory -Force $taskFolder | Out-Null
Push-Location $taskFolder
try {
    & (Join-Path $VivadoBin 'xvlog.bat') --sv ../adapter_io.v ../tb_adapter.sv
    if ($LASTEXITCODE -ne 0) { throw 'RTL compilation failed' }
    & (Join-Path $VivadoBin 'xelab.bat') tb_adapter -s tb_adapter_sim
    if ($LASTEXITCODE -ne 0) { throw 'RTL elaboration failed' }
    & (Join-Path $VivadoBin 'xsim.bat') tb_adapter_sim -runall
    if ($LASTEXITCODE -ne 0) { throw 'RTL simulation failed' }
    if (-not (Select-String -Path xsim.log -Pattern 'PASS: SPI byte/DC/reset' -Quiet)) { throw 'Test completion marker missing' }
} finally { Pop-Location }
