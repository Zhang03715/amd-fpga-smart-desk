# Z2 转接板程序

2026-10-27 实板预览基线：`adapter_control.lcd_bringup`使用独立摄像头进程持续采集最新帧，主进程独占LCD/MMIO，刷新批次间采样按键；BACK离开时关闭摄像头。S3 UART在此验证程序中未启用。实际屏幕要求反色关闭，Panel默认值已修正。

新增原生RGB565转换与三字节SPI命令（opcode0x04，MSB先发；status bit12表示支持）。C驱动只在能力位存在时使用该命令，否则回退单字节；不能把新命令直接发送给旧overlay。原生转换随机向量逐字节对照通过。候选板端目录`/home/xilinx/amd_lcd_burst_20261027`，原软件/bitstream目录保留在`/home/xilinx/amd_lcd_camera_20261020_r3`。新bitstream及报告位于项目`output/lcd-burst-20261027`；构建先运行`build_lcd_burst.tcl`，旧的无I/O约束检查失败产物保留，`finish_lcd_burst.tcl`从已路由DCP补充外设约束并生成本次验证bitstream。完整新构建脚本现已包含这些约束；已存在的输出需另设目录保留后再构建。

固定相同预览尺寸、每帧传输量中位数75840字节、目标刷新上限10的实板对比：同一C转换路径下，旧FPGA约2.67FPS，新FPGA约3.40FPS（各取120帧）；传输中位数0.3365秒降到0.2595秒。首个整屏153600字节实测0.388秒。目标参数10不代表实际达到10FPS。详细证据`output/lcd-burst-20261027/board-evidence.json`，仍属短期稳定性观察，不是流畅视频验收。

新实现50MHz下setup WNS +1.873ns、hold WHS +0.045ns，DRC无错误；四键/UART RX明确按异步输入例外处理，输出使用一个20ns fabric周期的工程启动到PAD预算。该预算不代表外设数据手册或线缆实测时序，首轮10ns试验失败记录也保留。SPI频率仍为5MHz。RTL覆盖三字节顺序、连续包、后续命令和包中复位恢复，并保持原有外设仿真通过；本轮不启用电机。

2026-10-19 r3：只接受新找书请求更新页面归属，旧请求重试不抢回显示；90秒后观察到的结果保持超时，不重新作为新结果展示；book.status返回独立快照。进入番茄钟页面只在idle时启动25分钟，正在运行或暂停的计时不被重置。菜单缓存字体并按像素宽度省略过长文本。底层OCR协议结果仍可查询，界面超时不等于服务器作业被强制终止。

2026-10-19：菜单新增末项Book result，与UART找书请求共享AdapterService。页面显示idle/searching/found/not_found/failed/timeout/cancelled/expired及匹配数；OK取消展示，BACK返回菜单。90秒等待后显示结果未知；完成30秒后结果过期。取消不保证正在执行的OCR线程终止，但迟到结果不恢复已取消页面。book.status/book.cancel为AdapterService本地业务接口，尚未注册为S3云端工具。灯带找书映射未配置，页面始终明确未应用指示，不据识别成功声称点灯。语音端完整结果仍按原协议回传。

软件测试：`.venv/Scripts/python.exe -m unittest adapter_control.test_book_lifecycle adapter_control.test_adapter adapter_control.test_remote_configuration`。预览：`.venv/Scripts/python.exe -m adapter_control.run --keys up,ok --preview output/book-status-menu-20261019.png`。没有键盘文字输入：找书目标来自既有UART/服务请求，菜单本轮只查看及取消。

这套程序控制 Z2 40 针口上的 ST7789V SPI 屏幕、四个菜单按键、S3 UART 和两路 WS2812。四路 D36A 脉冲控制接口已提供，但菜单程序始终关闭电机。它使用单个 `AdapterService`，继承现有 `DeskService`，菜单和 S3 请求共享计时器、提醒事件及存储。

当前交付是软件和自定义 overlay 源码。主机 PNG、Python 测试和 RTL 仿真已验证；屏幕、电机、灯带及 S3 的联合实板效果仍待验证。不要把 PNG 预览当作屏幕实测，也不要使用系统 `base.bit` 代替本目录的自定义 overlay。

## 主机运行

在 Windows PowerShell 执行：

```powershell
Set-Location D:\project\AMD
& .\.venv\Scripts\python.exe -m unittest adapter_control.test_adapter -v
& .\.venv\Scripts\python.exe -m adapter_control.run --once --preview output/adapter-menu.png
```

预览确认键进入番茄钟：

```powershell
& .\.venv\Scripts\python.exe -m adapter_control.run --keys down,ok --preview output/adapter-timer.png
```

静态图片预览（修改成真实文件路径）：

```powershell
& .\.venv\Scripts\python.exe -m adapter_control.run --image C:/Users/example/Pictures/test.jpg --keys down,down,ok --preview output/adapter-camera.png
```

无 `--bitfile` 时只生成一张 PNG 并退出，不访问 FPGA，不连接 UART，不自动调用 OCR。`--keys` 仅供主机预览。摄像头预览也可使用 `--camera 0 --keys down,down,ok`，需要当前 Python 环境能导入 `cv2`。

依赖见 `requirements.txt`。在本机缺少 Pillow 时使用当前解释器安装：

```powershell
& .\.venv\Scripts\python.exe -m pip install -r adapter_control/requirements.txt
```

## FPGA 构建与仿真

在项目根目录执行 RTL 仿真：

```powershell
& .\Vivado\adapter_control\simulate.ps1
```

脚本默认使用 `D:/AMDDesignTools/2025.2/Vivado/bin`，可通过 `-VivadoBin` 指定其他安装目录。成功时 `Vivado/adapter_control/simulation/xsim.log` 包含 `PASS: SPI byte/DC/reset, WS2812 pulse/reset/two channels/256 pixels, button debounce, four motor count/stop/watchdog`。

第一次生成独立项目、BD 和 IP：

```powershell
& 'D:/AMDDesignTools/2025.2/Vivado/bin/vivado.bat' -mode batch -source Vivado/adapter_control/build.tcl -log Vivado/adapter_control/build.log -journal Vivado/adapter_control/build.jou
```

第一次直接进行完整 bitstream 构建：

```powershell
$env:ADAPTER_BUILD_BITSTREAM = '1'
& 'D:/AMDDesignTools/2025.2/Vivado/bin/vivado.bat' -mode batch -source Vivado/adapter_control/build.tcl -log Vivado/adapter_control/build-full.log -journal Vivado/adapter_control/build-full.jou
Remove-Item Env:ADAPTER_BUILD_BITSTREAM
```

若 `generated/adapter.xpr` 已存在，使用恢复选项。先确认没有另一个 Vivado 正在构建同一项目：

```powershell
$env:ADAPTER_RESUME_BUILD = '1'
$env:ADAPTER_BUILD_BITSTREAM = '1'
& 'D:/AMDDesignTools/2025.2/Vivado/bin/vivado.bat' -mode batch -source Vivado/adapter_control/build.tcl -log Vivado/adapter_control/build-resume.log -journal Vivado/adapter_control/build-resume.jou
Remove-Item Env:ADAPTER_RESUME_BUILD
Remove-Item Env:ADAPTER_BUILD_BITSTREAM
```

成功完整构建后导出 `Vivado/adapter_control/output/adapter.bit` 和同名 `adapter.hwh`，并生成 `timing.txt`、`drc.txt`。须检查实现结果及报告，文件存在本身不证明时序或实板功能通过。该工程独立于现有 Vivado 工程。

## 板端运行

将项目文件复制到 `/home/xilinx/AMD`，保持 `adapter_control`、`voice_bridge` 和匹配的 `.bit/.hwh`。使用系统已有的 PYNQ Python 环境，不另装 PYNQ。先确认依赖：

```bash
cd /home/xilinx/AMD
python3 -c "import pynq; from PIL import Image; import cv2; print('dependencies OK')"
```

没有摄像头时先显示菜单：

```bash
python3 -m adapter_control.run --bitfile Vivado/adapter_control/output/adapter.bit --led-counts 1,1
```

接入 UVC 摄像头后：

```bash
python3 -m adapter_control.run --bitfile Vivado/adapter_control/output/adapter.bit --camera 0 --led-counts 1,1 --db-path output/adapter.sqlite
```

`--led-counts` 必须改为两条灯带实际灯珠数，每路 1～256。启动会发送完整熄灯帧。`--camera 0` 一次打开一个设备；第二个摄像头可用 `--camera 1` 单独验证，不代表当前程序同步显示两个摄像头。Linux `/dev/video*` 编号还可能包含非采集节点。

板端先停止旧串口服务及其他可能加载 overlay 的程序。当前进程独占 AXI UART Lite 和命令桥，不能再启动第二个 `DeskService` 进程来争用接口。退出用 `Ctrl+C`，程序尝试关闭所有电机；PL 另有看门狗。

## 接线与菜单

以 Z2 **物理引脚号**为准，完整清单在 `hardware/z2_spi_menu/pinout.csv`，FPGA 约束在同目录 `pins.xdc`。

| 外设 | Z2 物理脚 | 说明 |
|---|---|---|
| LCD SCL | 27 | SPI SCK |
| LCD SDA | 28 | SPI MOSI，数据输入，不是 I²C SDA |
| LCD CS / DC / RST | 29 / 31 / 32 | 3.3V 逻辑 |
| BACK / UP / DOWN / OK | 33 / 37 / 38 / 40 | 按下接地，低有效 |
| S3 RX GPIO18 | 35 | Z2 TX → S3 RX |
| S3 TX GPIO17 | 36 | Z2 RX ← S3 TX |
| LED1 / LED2 数据 | 3 / 26 | 经 5V AHCT 缓冲接两条灯带 DIN |

2026-10-31：书架服务 `voice_bridge.shelf_book_adapter` 改用 LED1（FPGA 通道 0），
包括书本定位、相机标定和坐姿异常红灯。统一配置在 `voice_bridge/shelf_calibration.py`
的 `SHELF_LED_CHANNEL`。更新板端 Python 后，将原 LED2 的整条 60 灯珠链移到 LED1，
保持 DIN 方向和 5V/GND 接序。仅换接口且灯带、摄像头位置不变时，原坐标标定可复用；
若移动了灯带或摄像头，需要重新标定。旧演示脚本及旧菜单仍可能固定使用 LED2，
不要与书架服务同时运行。既有 FPGA 程序已支持两个接口，不必重新生成 bitstream。

LCD VCC 使用规划的 3.3V，GND 共地；实际模块供电和接口须在装配前核对。灯带使用独立 5V 电源并与 Z2 共地，不从 Z2 3.3V 供电。数据接灯带 **DIN 输入端**；连接器顺序为 `5V / DIN / GND`，接头机械兼容性单独核对。D36A 电机电源独立，P1 的 5V 输出和 ADC 暂不接。物理脚 5/19/21 预留 NC；Pmod A 与部分信号共用管脚，不可同时驱动。

| 按键 | 功能 |
|---|---|
| UP / DOWN | 主菜单循环选择 |
| OK | 进入所选页；番茄钟项启动 25 分钟；熄灯项请求两路熄灯 |
| BACK | 回主菜单，不取消计时器 |

主菜单含 Status、Pomodoro 25 min、Camera preview、Lights off。初版页面使用英文。按键由 PL 做 20ms 消抖，Python 仅响应新按下边沿，没有长按连发。状态页保留 `Hardware test pending`，避免在未实测时显示“全部正常”。

## 参数与运行边界

默认面板 240×320、RGB565、SPI mode 0、5MHz。可用 JSON 调整 MADCTL、颜色顺序、显示偏移和反色，例如：

```json
{"width":240,"height":320,"x_offset":0,"y_offset":0,"madctl":0,"inversion":true}
```

保存为 `output/panel.json` 后追加 `--panel-config output/panel.json`。这是配置格式示例，不是已经实测的面板校准结果。屏幕旋转、偏移、RGB/BGR、初始化序列都需真实屏幕验证。

SPI 当前逐字节通过 MMIO 下发，并仅重绘变化矩形。全屏 RGB565 为 153600 字节，实际开销还包括 MMIO、CS 和 Python；不能据 5MHz 理论带宽承诺摄像头预览帧率。循环在一次刷新完成后再等 1 秒，不是实测 1fps。预览不等于 OCR，更不自动产生坐姿检测结果。

UART 为 115200、8N1，沿用 `voice_bridge` 的换行 JSON 协议和事件格式。收发线程只搬运字节，服务执行仍在主线程。例如 S3 发送一行：

```json
{"v":1,"type":"request","id":"timer-1","action":"timer.start","params":{"minutes":25}}
```

菜单与串口使用同一个服务对象，定时完成事件从同一串口发回；`posture.update` 的现有视觉入口边界不变。LCD 发送与初始化等待期间会处理 UART 队列；独立 RX/TX 线程避免被 LCD、灯带或发送等待直接阻塞，但 Python 调度无法保证 16 字节硬件 FIFO 绝不溢出。高负载吞吐仍需板端验证。`light.scene` 成功只表示命令桥完成两路发送，不证明实际灯珠发光；异常后 `applied=false`、硬件状态记为 unknown，不宣称跨灯带原子提交。

摄像头在独立线程中保存最新帧。超过 2 秒没有新帧则不再显示旧图；时间是主机读取完成时间，不是传感器曝光时间。静态图片有 `not live` 标记。取帧后端若无法停止，退出会提示重新启动进程后再打开设备；不能把后台线程当作摄像头驱动超时机制。

`Motors(bridge)` 默认 `allow=False`，主程序不暴露运动菜单或语音运动工具。低层接口仅接受显式启用后的有限步数，四路独立 STEP/DIR/EN；复位和停止均使 EN、STEP 低。500ms 未显式喂狗会关闭电机，长于该时间的实验需要持续喂狗。已经移除限位输入；没有回零、位置反馈、编码器解析或自动搬运。更多接口与验证边界见 `docs/Z2转接板程序准备与验证.md`。

完整构建已于2026-10-13完成，内部时序通过、DRC 0项。外部25个IO未设置板级输入/输出延迟（TIMING-18），实际屏幕/串口/灯带/电机仍待测。交付包 `output/z2-adapter-ready.zip` 内包含源码、bit/hwh及SHA清单；运行 `python tools/package_adapter.py` 可重新打包，`python tools/check_adapter_contract.py` 检查引脚和生成设计一致性。
