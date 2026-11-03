# 构建

先运行 `python build/materialize.py`，再在 `build/worktree` 内执行构建命令。源码映射同时恢复 Java、CMake 和工具入口要求的大小写名称。

Vivado：`vivado -mode batch -source Vivado/adapter_control/build.tcl`；基础工程成功后执行 `vivado -mode batch -source Vivado/paper_sorter_bridge/build.tcl`。需要 Vivado 2025.2 和 PYNQ-Z2 board files。

Windows：准备 Python 环境后执行 `powershell -File supervisor/tools/build_windows.ps1 -OutputName DeskHub-batch-20261103.exe`。Android：按 `supervisor/tools/build_android.py` 依赖准备 JDK 和 Android SDK 后运行。测试签名和私钥不提交，部署者生成自己的签名。

S3：使用 ESP-IDF 构建 `firmware/xiaozhi-amd`，依赖由 IDF Component Manager 获取。模型由对应模块的下载脚本和说明准备；不包含权重、CUDA、SDK 和虚拟环境。

`tools/start_all.ps1` 是已配置环境的启动器，不负责新机器安装。运行前必须准备全部依赖、更新模型路径、创建 OCR 认证文件并将其安全同步到 Z2。

综合、实现报告及大模型使用记录本轮不上传。
