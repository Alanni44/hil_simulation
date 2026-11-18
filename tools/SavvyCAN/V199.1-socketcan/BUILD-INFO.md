# SavvyCAN V199.1 SocketCAN 本地构建

- SavvyCAN 源码：`V199.1`，提交 `305dafd3b6b89bbff7a40dff378432b5ec3c6307`。
- Qt 基础：Ubuntu 18.04 的 Qt 5.9.5 二进制开发包，仅解包到临时构建目录，未安装到系统。
- Qt SerialBus 源码：`v5.9.5`，提交 `9b1700a54e4199c08e9175709640d433420e77b0`；SocketCAN 与 CAN FD 配置均为启用。
- 为兼容当前 Linux 头文件，在 Qt SerialBus 的临时构建副本中补充了 `linux/sockios.h`，以提供 `SIOCGSTAMP` 定义；未修改 SavvyCAN 源码。
- 启动：`tools/SavvyCAN/V199.1-socketcan/run-savvycan-socketcan`。启动器只设置其自身目录下的动态库和 Qt 插件路径，不修改系统配置。
- 该工具包用于 L-006 软件观察验证；业务报文发送仍须使用真实标准会话与外部正式发报授权。
