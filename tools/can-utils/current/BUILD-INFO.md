# canplayer 本地构建信息

- 工具：can-utils 的 `canplayer`。
- 上游：`https://github.com/linux-can/can-utils.git`，提交 `834ceef1f1eabec67625389172eebf1050d2f42b`。
- 构建：本机 Linux，以仓库上游 Makefile 执行 `make canplayer`；未安装或替换系统软件包。
- 可执行文件 SHA-256：`e08355bfa6deab79bf9e8cfb1e96c8e3bf2a4f059f1e9f2467006e6a77739a96`。
- L-007 软件验证使用 `can2` vcan，且只回放非业务测试 ID `0x125` 和 `0x126`。该副本不构成真实控制器、总线仲裁、硬件时间戳、模型应用或正式业务发送资格。
