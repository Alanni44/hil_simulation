# Controlled Original Tool Commands W3.12

**Goal:** 沿已批准设计补齐CUTIL观察、CANREPLAY和ETHREPLAY的共用参数构建；不启动Linux工具，不将参数/导出资源当实际发送授权。

**Architecture:** `ToolCommandBuilder`只接受本簿有效预约及冻结通道绑定。观察参数固定为candump日志/纳秒/RxTx与正式双向ID过滤；回放通过原ReplayExporter重新完整核验PreparedReplay后生成逐通道单轮参数、原文件hash和准确首次offset。没有shell、任意附加参数、工具内改速/跳包/无限循环。输出不可变且execution_ready/authorized_to_transmit始终false，不能直接传入进程监督器当批准执行。

**Scope:** 此阶段为M3-02/03/05/06的参数准备部分。CANT/cansend实时发送、SavvyCAN GUI/backend、Ostinato/Scapy实际网卡与全部实际会话/调度/反馈联动继续原后续任务；六分支不删除、不替换。原C、14冻结源、41责任和17未执行Linux门禁保持。

## Tasks

- [x] 先RED有效预约核验：本簿身份、释放/外簿/伪造拒绝，核验不释放预约。
- [x] 先RED观察命令：仅CUTIL/OBSERVE、CANFD通道一一绑定、无any/未知通道/重复或额外接口；13正式双向CAN ID准确过滤，观察不授权发送。
- [x] 先RED回放命令：三模式PCAP/CAN完整资源、固定单轮/显式接口与绝对文件路径、hash/不可变/首次offset保留；不同分支/模式/介质/预约与资源篡改、CAN不可表达时序拒绝。
- [x] GREEN最小共用实现；参数构建不持久化、不启动进程、不声称时序/工具/模型就绪；现有导出器负责独占持久化。
- [x] 独立只读复核，重要问题先失败测试后修正；固定版本539共用/34选定静态、冻结14源/663引用及41/17台账守护通过。canplayer stdout特殊打印接口先RED后拒绝，最终17专项通过；独立17专项/19导出及篡改/期间释放预约探针通过，无遗留重要发现。
- [x] 写独立`artifacts/icd_gateway/w3-12-validation.json`，唯一台账追加Linux实际版本/参数/时序/权限/停止/授权/原TXRX验证与共用未完任务，不勾选整体里程碑。

## Verification

专项：`python -X utf8 -m unittest discover -s tests/icd_gateway -p test_tool_commands.py -v`。
回归：`python -X utf8 scripts/test_icd_runtime.py`；原CLI/共用无OS分流守护和41/17责任包含在入口。

## Sources And Boundaries

参数核对上游源而非猜测GUI选项：
https://raw.githubusercontent.com/linux-can/can-utils/master/candump.c
https://raw.githubusercontent.com/linux-can/can-utils/master/canplayer.c
https://raw.githubusercontent.com/appneta/tcpreplay/master/src/tcpreplay_opts.def

这些主线参数仍须Linux实际锁定版本资格验证。candump纳秒显示不证明硬件纳秒时钟；canplayer微秒可表达性不证明调度达标；tcpreplay纳秒输入/实际调度仍未验证。逐通道首次offset必须由后续统一执行器按真实模型步协调，工具自身首包立即发送不能代替对齐。每轮真实授权/RESET/清队列/新SID仍由完整执行器承担，参数包没有执行入口。
