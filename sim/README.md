# 验证

`python sim/run_checks.py` 先还原源码，再运行书名匹配、灯带几何、坐姿规则等选定测试。仅验证软件行为，不保证相机识别准确率或机械到位。

FPGA 仿真在还原目录执行 `vivado -mode batch -source Vivado/paper_sorter_bridge/sim.tcl`。测试参数对应约 1152 pps、19.8 秒进纸、25 秒送纸、0/40/55 度槽位；仿真输出位于生成目录，不入库。
