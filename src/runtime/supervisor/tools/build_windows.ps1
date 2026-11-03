param([string]$OutputName="DeskHub.exe")
$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
if([IO.Path]::GetFileName($OutputName) -ne $OutputName){throw "OutputName must be a file name"}
$binary=Join-Path "$root\dist" $OutputName
& "$root\..\.venv\Scripts\python.exe" "$PSScriptRoot\sync_product_ui.py"
if($LASTEXITCODE -ne 0){throw 'Product UI sync failed'}
$compiler='C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$args=@('/nologo','/target:winexe','/platform:anycpu','/optimize+','/r:System.Web.Extensions.dll','/r:System.Windows.Forms.dll','/r:System.Drawing.dll','/r:System.Security.dll',"/out:$binary")
foreach($name in @('index.html','style.css','app.js')){$args+="/resource:$root\web\$name,$name"}
$args+="$root\windows\DeskHub.cs"
& $compiler @args
if($LASTEXITCODE -ne 0){throw 'Windows build failed'}
Get-FileHash $binary -Algorithm SHA256
