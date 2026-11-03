$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
$assets=Join-Path $root '.build-tools\paper-classifier'
$server=Get-ChildItem -LiteralPath (Join-Path $assets 'runtime') -Filter 'llama-server.exe' -Recurse | Select-Object -First 1
if(-not $server){throw 'Run tools/setup_paper_classifier.py first.'}
$model=Join-Path $assets 'Qwen3-4B-Q4_K_M.gguf'
if(-not (Test-Path -LiteralPath $model)){throw 'Model download is not complete.'}
$logs=Join-Path $root 'output\paper-classification'
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$arguments=@('--model',$model,'--alias','paper-qwen3-4b','--host','127.0.0.1','--port','8769','--ctx-size','4096','--parallel','1','--n-gpu-layers','99','--threads','6','--batch-size','256','--ubatch-size','128','--jinja')
$process=Start-Process -FilePath $server.FullName -ArgumentList $arguments -WorkingDirectory $server.DirectoryName -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logs 'model-stdout.log') -RedirectStandardError (Join-Path $logs 'model-stderr.log')
$process.Id | Set-Content -LiteralPath (Join-Path $logs 'model.pid')
Write-Output ('LOCAL_MODEL_PID '+$process.Id)
