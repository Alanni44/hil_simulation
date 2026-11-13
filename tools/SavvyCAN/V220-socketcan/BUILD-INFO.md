# SavvyCAN V220 SocketCAN 本地构建

- SavvyCAN 源码：V220，提交 7c576c5ffe240da7d4aae9741162a4583efff6b0。
- Qt 基础：Ubuntu 18.04 的 Qt 5.9.5 二进制开发包，仅解包到临时构建目录，未安装到系统。
- Qt SerialBus 源码：v5.9.5，提交 9b1700a54e4199c08e9175709640d433420e77b0；SocketCAN 与 CAN FD 配置均为启用。
- 该版本的 SerialBus 接收路径不再将数据长度限制为 8 字节，并保留 CAN FD 格式标记处理。
- 为使 V220 在 Qt 5.9 上构建，临时源码副本仅做了 API 兼容改动（随机数、字体宽度、字符串/容器 API、枚举序列化及 Qt 5.9 无本地回显元数据时的接收标注）；未改变 SocketCAN 收发语义，也未修改仓库源码。
- 启动：tools/SavvyCAN/V220-socketcan/run-savvycan-socketcan。启动器只设置其自身目录下的动态库和 Qt 插件路径，不修改系统配置。
- 受限发送入口：`SavvyCAN-hil-authorized --hil-authorized-send REQUEST_JSON SHA256` 是基于上述 V220 构建的项目隔离可执行文件。它只接受哈希绑定的 `HIL_SAVVYCAN_AUTHORIZED_SEND_1` 请求，且只写标准 ID、64 字节、FD+BRS 的 SocketCAN 帧；实际写入仍使用 SavvyCAN `SerialBusConnection`/Qt SerialBus SocketCAN 后端，而不是 Python 或 `cansend` 替代。当前二进制 SHA-256：`3a8073a52d7e6dbe198089bf37a90f9361a8aa07bc4dcc66735bb1f9a46b92ec`。
- 该入口没有通用命令执行、交互式报文编辑或独立授权能力；只有项目的当前 `SourceSession`、原始协议帧组与发送 reservation 都通过复核后，适配器才会产生该请求并启动它。
- 该工具包用于 L-006 软件观察及受控发送验证。实体 CAN-FD 总线的发送资格仍须使用真实标准会话、外部正式发报授权和硬件验收。
