---
name: pynq-bringup
description: Diagnose and reproduce PYNQ overlay and peripheral bring-up, coordinate shared hardware ownership, and verify deployment artifacts and timing evidence. Use for PYNQ boot, overlay, camera identity and integrated peripheral failures; adapt board-specific configuration before hardware actions.
---

# PYNQ 可复现联调

目标：在不覆盖现有运行状态的前提下，定位启动、overlay、外设与服务链路的问题，形成可复查的部署证据。该技能不依赖书架、电机或某块转接板；具体引脚、寄存器协议、bitstream 和驱动由目标项目提供。

## 执行流程

1. 先读目标项目配置、启动服务与现有日志。确定板型、物理脚号/封装脚号/逻辑通道映射、bit/hwh 配对、驱动版本及资源所有者；缺少映射时不猜引脚。
2. 将用户现象拆成可证伪假设。参考 [排障工作流](references/workflow.md)，每次只用一个最小读操作或短时诊断排除一个原因。已有业务进程占用硬件时，优先走它的接口。
3. 离线先执行 [校验工具](scripts/check.py)：文件清单与 SHA256、黄金 JSON 子集、归一化时序与 DRC。命令见包级 README。示例数据只是工具演示，不能作为真实硬件验证。
4. 涉及 overlay 下载、GPIO 输出或服务重启时，遵守用户已授权范围。先确认独占关系和恢复路径，备份将修改的文件；不能让两个进程持有相同命令桥。停止共享所有者后才做独立硬件诊断，结束后恢复服务并检查实际业务回应。
5. 逐层记录：软件校验、驱动/API 回应、图像/光学/机械实测。驱动 ready、DONE 亮、任务 accepted 均不等于外设实际完成。没有实测就写未验证，见 [证据与案例](references/evidence.md)。
6. 使用 [验收模板](assets/acceptance-template.md) 输出问题、假设、命令、证据、变更、回滚和未验证项。若权限不足、端口被未知进程占用、映射不明确或连续出现不响应，停止依赖该条件的动作并报告阻塞。

## 关键约束

- `Overlay(..., download=False)` 仍依赖正确 PYNQ/XRT 环境，不能据此断定现有 PL 与描述文件一致。先核对标识/版本与构建哈希；仅在项目已定义恢复策略时下载匹配程序。
- PS 进入 Linux 与 PL 完成配置是两层状态，启动策略以项目服务定义为准。不要仅根据 DONE LED 判定 Linux 是否启动。
- 相机选择优先使用稳定设备路径或 USB 拓扑，而不是把 `/dev/video0` 永久绑定某个物理相机。拍照与预览两条路径都要核对。
- RGB/BGR、RGB565 和屏幕方向分别验证；先看源图，再看编码，再检查显示初始化。
- 时序只报告已检查的范围。WNS/WHS 非负不证明未约束外设时序或异步路径已正确覆盖。
- 网络令牌、密码不写进技能和报告；使用操作者已有凭据，诊断输出屏蔽秘密。
