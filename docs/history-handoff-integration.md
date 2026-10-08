# HISTORY 第三条链路合并说明

## 当前结论

2026-10-08 按用户要求，将桌面 `code_handoff_33_36_20261006` 的第三条链路增量合入 `codex/icd-runtime-w1`。Windows/Linux 仍使用同一代码；未改变冻结 ICD、硬件接口、前两条工具链或默认接收能力。代码合并不等于三条实际部署链路全部验收。

完整输入定义仍唯一为 [v0.3 单文件汇总](interfaces/输入模拟器完整接口定义_v0.3_单文件汇总.md)，冻结指纹仍为 `22163dc21526ceadd63260b3d5670404a1064c4301e52b2a80edcf41a4fe8a27`。

## 合入内容

- `input_simulator/reference_pcap.py`：由冻结业务定义生成标准参考 PCAP。
- `input_simulator/replay_network_evidence.py`：解析实际 L2/IP/UDP 与标准帧，校核请求及反馈关联。
- `scripts/generate_reference_pcap.py`、`prepare_history_round2.py`：参考 PCAP 与 prepared PCAP 离线准备。
- `scripts/validate_history_round3_linux.sh`、`validate_history_round3_received.py`：隔离 Linux tcpreplay/tcpdump 发送与实际接收抓包核验。
- `scripts/validate_history_round4_linux.sh`、`validate_history_round4_gateway.py`：真实 SourceSession、重新编码当前 SID、标准网关准入诊断及持久化证据校核。
- `config/input-simulator-round4-development.json`：隔离网的 CONTROLLER 授权配置，与前两条 STIMULUS/CAN 配置分开保留，不覆盖实际部署示例。
- `artifacts/history/round1..round4/`：200 份原始证据，失败尝试与最终成功记录全部保留；外部报告、提示词和 bridge 设计原文保留供查阅。

共同导出器只增加可选本地 `ExportBinding.output_name`：允许对应通道原文件名或 Ethernet 的 `prepared.pcap`，拒绝路径、重复、错误通道和介质。原默认导出名字不变；它不是新 ICD 字段。

外部交付有 22 份不同的共享文件快照。除上述导出器增量与新增回归外，不用旧文件覆盖当前接收、配置、授权、生命周期、场景、自生发送与台账。旧源码汇总及旧清单不复制成第二份权威源码；其 237 项清单中两项 SHA 已过时，当前来源与工作副本指纹见 [验证清单](../artifacts/icd_gateway/history-handoff-integration-20261008.json)。

Round 4 清理脚本另修正两点：只写本次创建的证据目录；删除命名空间后核对实际清理及主机路由，验证失败时保留退出清理，不提前记录成功。使用伪 `ip` 的 Bash 回归验证失败分支，没有在 Windows 启动 Linux 原生链路。

## 已验证与未完成

新增 unittest 已纳入现有统一测试入口。Round 4 外部 pytest 风格测试转换为等价 unittest，无新增依赖。当前兼容性测试包括：新 SID HISTORY 报文走共同 Receiver；默认能力 `[1]` 的标准缺消费者反馈；显式 ReceptionService 对同一标准报文完整解码、RECEIVED/VALIDATED、probe0 和重复包去重；原 STIMULUS/CAN 配置不变；最终 Round 3/4 抓包用当前编解码库重新解析。

导入的最终 Round 3 是 `round3/retry_2`，最终 Round 4 是 `round4/retry_4`。它们是外部开发者在隔离 WSL2 Linux 上的历史证据，不是此次 Windows 新跑、麒麟环境资格、实物网卡资格或部署后的真实 3.6 验收。

Round 4 默认网关只声明 ID1；SourceSession 因 ID7 缺消费者而拒绝普通发送。脚本明确记录诊断探针，目标返回 RECEIVED/OK 后 FAILED/TARGET_MISSING。**不得将这份结果表述为业务应用成功或完整生产回放服务已完成。** 当前接收验证模式能按标准接口解码，不意味着模型应用，也不能冒称 SourceSession 的生产发送已打通。

`send_cli` 的 SCENARIO REPLAY 仍明确拒绝，未接入诊断脚本；完整 replay service、HISTORY CAN/canplayer 和批准回放策略的目标验证继续待办。外部 Round 5/5A 及 `docs/internal/model_consumer_bridge_v1.md` 是设计/局部资产调查，不是已实现 bridge，不替代外部 ICD；其 NO_GO 仅对应原作者当时的搜索范围。

## Linux 接续

共同 Python 环境按 [Linux 接续说明](linux-input-simulator-handoff.md) 准备。先运行只读验证：

```bash
python -X utf8 scripts/test_icd_runtime.py
python -X utf8 -m unittest discover -s tests/icd_gateway -p 'test_history*.py' -v
bash -n scripts/validate_history_round3_linux.sh
bash -n scripts/validate_history_round4_linux.sh
```

原生执行需要 Linux、root、iproute2、tcpreplay、tcpdump、ethtool、Scapy 及允许创建隔离 netns/veth 的批准环境。原脚本固定隔离 IP/MAC，不能直接对生产网络执行。Round 4 还保留原 `sys.prefix` 必须以 `/envs/uav-history-round4` 结尾的 Conda 环境门禁；普通 `.venv` 不能直接跑它，需要批准环境或后续统一修改门禁与环境证据，不能假装已支持目标环境。

新跑证据不得覆盖已有目录。例如，在已核定隔离环境中执行：

```bash
sudo env ROUND3_ATTEMPT=local-20261008-new bash scripts/validate_history_round3_linux.sh
sudo env ROUND4_OUTPUT_DIR="$PWD/artifacts/history/round4/local-20261008-new" ROUND4_PYTHON=/actual/conda/envs/uav-history-round4/bin/python bash scripts/validate_history_round4_linux.sh
```

第二条命令的解释器路径必须换成实际批准路径。先核定原脚本要求、依赖和权限，再运行；不得把诊断缺消费者结果当三条实收验收。Linux 待完成内容只追加 [唯一台账](superpowers/plans/linux-development-backlog.md)，不新建第二套待办；不勾选原 17 项完整 Linux 门禁，不改写原 41 责任与历史验收结论。
