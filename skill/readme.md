# 可复用 PYNQ 技能包

本目录为截图“3.3.5.2 技能包”要求的提交目录。包含一个通用 PYNQ skill，覆盖提示词工作流、案例/报告模板、校验脚本和踩坑清单。无本团队私有引脚或模型依赖；更换题目或板型后提供新工程配置即可使用。

## 快速使用

1. 将整个 `pynq-bringup/` 交给大模型，要求“读取 SKILL.md，并按目标板配置排查当前问题”。支持 Codex 的环境也可以将该文件夹复制到用户 skills 目录再调用 `$pynq-bringup`；本次只在项目内创建，没有全局安装。
2. 在本 README 所在目录执行以下命令，Python 3.9+，无第三方依赖，无硬件写操作：

```text
python pynq-bringup/scripts/check.py --manifest pynq-bringup/assets/example/manifest.json --expected pynq-bringup/assets/example/golden.json --actual pynq-bringup/assets/example/observed.json --timing pynq-bringup/assets/example/timing.json
python pynq-bringup/scripts/test_check.py
```

示例数据为人为构造，仅演示校验器。时序文件是明确的归一化 JSON，并不是 Vivado 原始报告；需要使用者从自己的报告摘录数据并标注来源。`unconstrained_paths` 不知道时不能填 0，应先完善/审查约束。

## 每一项的适用范围、用法与失效条件

|项目|适用范围与使用方法|失效条件|已验证效果/来源|
|---|---|---|---|
|SKILL.md + references/workflow.md|PYNQ 启动、共享外设、性能瓶颈；替换模板中的目标和操作范围|无法确认板型、所有者或引脚时，只进行只读排查|来自 LCD 未启用、诊断环境缺失、相机路径不一致的实际排查，见 evidence.md|
|assets/acceptance-template.md|将目标工程的检查命令、证据、回滚填入验收报告|没有实物观察时不能填写硬件已通过|模板覆盖此前将驱动回应误认为实物完成的风险|
|scripts/check.py：manifest|输入同目录相对路径→SHA256 的非空 JSON 清单|只能证明文件未变，不能证明 bit/hwh 属于同一次构建；配对由构建来源另行证明|测试覆盖正确文件、篡改、缺失、目录逃逸|
|scripts/check.py：expected/actual|黄金 JSON 对象子集比对；对象可有额外字段，数组必须等长，标量类型严格|黄金结果过宽会漏检；浮点容差暂不支持|测试覆盖额外字段、类型错误与结果不一致|
|scripts/check.py：timing|输入 WNS/WHS、DRC、未约束路径数、资源预算及用量|不解析原始报告，不校验异步例外，不证明引脚电气或外设时序|测试覆盖负裕量、NaN、DRC、未约束路径和资源超预算|
|references/pitfalls.md|按触发现象选择排查分支，不把单次经验当作唯一原因|外围电路/协议不同，不能照抄结论|每项明确触发、排查与边界|
|references/evidence.md|查阅这些方法来自哪些观察，以及哪些未验证|历史实测不代表本轮重新测过|本包与硬件验证分层记载|

校验成功退出 0，数据不符退出 1，命令参数错误退出 2；输出 JSON 可接入 CI。报告不包含密码、令牌或硬编码网络地址。

## 迁移到陌生队伍的工程

提供本队的板型、接口映射、服务启动方式、配对构建产物、目标黄金结果和性能约束。无需沿用本项目的书架、S3、LED 通道或 D36A。脚本可直接独立复制运行，报告模板用相对链接定位。硬件相关操作必须依据目标工程已有协议，技能不提供跨板通用寄存器地址。

本包当前验证记录见 `验证结果.txt`。未在第二种 PYNQ 板卡做实物回归，通用性来自参数与流程解耦，不宣称已完成跨板实测。
