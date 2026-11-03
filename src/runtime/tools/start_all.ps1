param([switch]$NoUI,[switch]$CheckOnly)
$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $root
$logs=Join-Path $root 'output\one-click'
$binary=Join-Path $root 'supervisor\dist\DeskHub-batch-20261103.exe'
$running=Join-Path $env:LOCALAPPDATA 'AmdDeskHub\running.json'
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$mutex=New-Object System.Threading.Mutex($false,'Local\AMDDeskOneClick')
if(-not $mutex.WaitOne(0)){Write-Host '启动正在进行，请等待已有窗口完成。';exit 0}
function Probe($url,$headers){
 try {
  $request=[Net.HttpWebRequest]::Create($url);$request.Proxy=$null;$request.AllowAutoRedirect=$false;$request.Timeout=3000;$request.ReadWriteTimeout=3000
  foreach($key in $headers.Keys){$request.Headers[$key]=$headers[$key]}
  $response=$request.GetResponse()
  try {$reader=New-Object IO.StreamReader($response.GetResponseStream());try{return ($reader.ReadToEnd()|ConvertFrom-Json)}finally{$reader.Dispose()}}finally{$response.Dispose()}
 }catch{return $null}
}
function Port-Free($port){
 $client=New-Object Net.Sockets.TcpClient
 try{$task=$client.ConnectAsync('127.0.0.1',$port);if(-not $task.Wait(1000)){return $true};return (-not $client.Connected)}catch{return $true}finally{$client.Dispose()}
}
function Ready($name,$port,$url,$headers,$check,$start){
 $status=Probe $url $headers
 if($status -and (& $check $status)){Write-Host "[就绪] $name（复用已有服务）";return}
 if(-not (Port-Free $port)){
  # An occupied service may still be loading its model. Wait instead of duplicating it.
  Write-Host "[等待] $name 已启动，检查加载状态…"
 }else{Write-Host "[启动] $name";& $start}
 $deadline=(Get-Date).AddSeconds(120)
 do {
  $status=Probe $url $headers
  if($status -and (& $check $status)){Write-Host "[就绪] $name";return}
  Start-Sleep -Milliseconds 750
 }while((Get-Date) -lt $deadline)
 throw "$name 未在120秒内就绪，端口 $port；日志目录：$logs。请勿连续重复启动。"
}
function Open-Console {
 $previous=$null
 try{$previous=Get-Content -LiteralPath $running -Raw|ConvertFrom-Json}catch{}
 if($previous){
  $owner=Get-Process -Id $previous.pid -ErrorAction SilentlyContinue
  $uri=$null;try{$uri=[Uri]$previous.url}catch{}
  $valid=$owner -and $uri -and $uri.Host -eq '127.0.0.1' -and $uri.Scheme -eq 'http'
  if($valid -and $owner.Path -eq $binary){Start-Process $previous.url;return}
  $oldBinaries=@((Join-Path $root 'supervisor\dist\DeskHub.exe'),(Join-Path $root 'supervisor\dist\DeskHub-20261103.exe'),(Join-Path $root 'supervisor\dist\DeskHub-20261103-r2.exe'),(Join-Path $root 'supervisor\dist\DeskHub-20261103-r3.exe'),(Join-Path $root 'supervisor\dist\DeskHub.exe'))
  if($valid -and $owner.Path -in $oldBinaries){
   Write-Host '[更新] 关闭本项目旧版上位机，保留配对设置；正在进行的请求需稍后确认结果。'
   Stop-Process -Id $owner.Id -Force
  }
 }
 Start-Process -FilePath $binary -WorkingDirectory $root -WindowStyle Hidden
 Write-Host '[启动] 最新上位机；考试、课表、文件分类和错题整理已包含。'
}
try{
 foreach($path in @('.venv\Scripts\python.exe','.venv-gpu\Scripts\python.exe','output\ocr-link-token','supervisor\dist\DeskHub-batch-20261103.exe','.venv-layout\Scripts\python.exe','.build-tools\doclayout-v3\inference.pdiparams')){
  if(-not(Test-Path -LiteralPath (Join-Path $root $path))){throw "缺少启动文件：$path"}
 }
 $token=(Get-Content -LiteralPath (Join-Path $root 'output\ocr-link-token') -Raw).Trim()
 if(-not $token){throw 'OCR认证文件为空'}
 if($CheckOnly){
  $book=Probe 'http://127.0.0.1:8765/v1/health' @{Authorization="Bearer $token"}
  $model=Probe 'http://127.0.0.1:8769/health' @{}
  $paper=Probe 'http://127.0.0.1:8770/health' @{}
  $layout=Probe 'http://127.0.0.1:8772/health' @{}
  [pscustomobject]@{FilesReady=$true;BookshelfReady=($book.status -eq 'ready' -and $book.inference_location -eq 'local_pc_gpu');ModelReady=($model.status -eq 'ok');PaperReady=($paper.service -eq 'local-paper-classifier' -and $paper.model_ready -eq $true);LayoutReady=($layout.ready -eq $true);UI=$binary}|Format-List
  return
 }
 Ready '书架GPU OCR' 8765 'http://127.0.0.1:8765/v1/health' @{Authorization="Bearer $token"} {param($s) $s.status -eq 'ready' -and $s.inference_location -eq 'local_pc_gpu'} {
  Start-Process -FilePath 'powershell.exe' -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File ocr_link\start_pc_ocr.ps1' -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logs 'bookshelf.log') -RedirectStandardError (Join-Path $logs 'bookshelf-error.log')|Out-Null
 }
 Write-Host '[预热] 书架OCR模型（首次启动需要加载模型，请稍候）'
 & (Join-Path $root '.venv\Scripts\python.exe') (Join-Path $PSScriptRoot 'warmup_bookshelf.py')
 if($LASTEXITCODE -ne 0){throw '书架OCR预热失败，请查看 output/ocr-warmup 日志'}
 Ready '文件分类模型' 8769 'http://127.0.0.1:8769/health' @{} {param($s) $s.status -eq 'ok'} {& (Join-Path $PSScriptRoot 'start_paper_model.ps1')}
 Ready '文件分类服务' 8770 'http://127.0.0.1:8770/health' @{} {param($s) $s.service -eq 'local-paper-classifier' -and $s.model_ready -eq $true} {
  Start-Process -FilePath (Join-Path $root '.venv\Scripts\python.exe') -ArgumentList '-u -m paper_sorting.server' -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logs 'paper-api.log') -RedirectStandardError (Join-Path $logs 'paper-api-error.log')|Out-Null
 }
 Ready '错题版面常驻模型' 8772 'http://127.0.0.1:8772/health' @{} {param($s) $s.service -eq 'resident-question-layout' -and $s.ready -eq $true} {
  Start-Process -FilePath (Join-Path $root '.venv-layout\Scripts\python.exe') -ArgumentList '-u -m question_extraction.layout_server' -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logs 'layout.log') -RedirectStandardError (Join-Path $logs 'layout-error.log')|Out-Null
 }
 if(-not $NoUI){Open-Console}
 Write-Host '电脑端启动完成。Z2、S3和电脑需连接同一网络，S3原生USB接回Z2 Hub。'
 Write-Host '本脚本不烧录设备，也不修改板端网络地址；换热点后需检查连接设置。'
 Write-Host '关闭此窗口，后台服务继续运行。模拟测试请使用“本地界面测试.cmd”。'
}catch{Write-Host ('启动失败：'+$_.Exception.Message) -ForegroundColor Red;exit 1}
finally{$mutex.ReleaseMutex();$mutex.Dispose()}
