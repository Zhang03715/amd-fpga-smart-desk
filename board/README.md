# 板端部署

还原源码后查看 `hardware/z2_spi_menu/pinout.csv` 与 `Vivado/paper_sorter_bridge/paper_stop.xdc`。灯带连接 LED1（通道 0），横向物理编号 31–44，纵向 30–22，整链 60 颗。

Z2 需要匹配的 bit/hwh、Python 依赖和 `voice_bridge.usb_service`；S3 原生 USB 接 Z2 Hub，Wi-Fi 网关与电脑同网。纸面拍照和坐姿共用一台摄像头，书架使用另一台，按 USB 拓扑确认设备。

服务部署脚本包含历史路径和地址，需先审查修改，不能直接套用到新板。凭据须现场生成，禁止提交。电机无位置传感器，启动后先手动置于第 1 槽基准并确认，避免不经检查运动。

提交源码中的历史内网地址已替换为文档占位地址 `192.0.2.10`，部署前必须填写实际地址。上游 MQTT 文档中的递增十六进制 key/nonce 只是协议示例，不是本项目凭据。
