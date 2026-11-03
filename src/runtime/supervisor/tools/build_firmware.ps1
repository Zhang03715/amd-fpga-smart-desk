$ErrorActionPreference='Stop'
$root=Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$esp='D:/soft/study/Espressif'
$python="$esp/python_env/idf5.5_py3.11_env/Scripts/python.exe"
$env:IDF_PATH="$esp/frameworks/esp-idf-v5.5.4"
$env:IDF_COMPONENT_MANAGER='0'
$env:IDF_PYTHON_ENV_PATH="$esp/python_env/idf5.5_py3.11_env"
$env:GIT_CONFIG_COUNT='1'
$env:GIT_CONFIG_KEY_0='safe.directory'
$env:GIT_CONFIG_VALUE_0=$env:IDF_PATH
$env:ESP_ROM_ELF_DIR="$esp/tools/esp-rom-elfs/20241011"
$env:PATH="$esp/python_env/idf5.5_py3.11_env/Scripts;$esp/tools/xtensa-esp-elf/esp-14.2.0_20260121/xtensa-esp-elf/bin;$esp/tools/cmake/3.30.2/bin;$esp/tools/ninja/1.12.1;"+$env:PATH
& $python "$PSScriptRoot/prepare_offline_idf.py"
if($LASTEXITCODE -ne 0){throw 'Offline dependency preparation failed'}
& $python "$env:IDF_PATH/tools/idf.py" -C "$root/firmware/xiaozhi-amd" -DAMD_OFFLINE_BUILD=ON reconfigure build
if($LASTEXITCODE -ne 0){throw 'Firmware build failed'}
Copy-Item -LiteralPath "$root/firmware/xiaozhi-amd/build/xiaozhi.bin" -Destination "$root/supervisor/dist/esp32-s3-gateway.bin"
