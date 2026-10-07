# Linux 输入模拟器开发接续

## 代码与范围

仓库：`https://github.com/Alanni44/hil_simulation.git`。当前开发分支：`codex/icd-runtime-w1`。分支名称沿用已有工作分支，不表示代码只完成 W1，也不是 Windows 专用分支。

本次模拟器工作位于仓库根目录的 `input_simulator/`、`icd_runtime/`、`icd_gateway/`、`tests/icd_runtime/` 和 `tests/icd_gateway/`。Windows 和 Linux 使用相同模块、配置格式及冻结 ICD。Windows 虚拟环境、缓存、浏览器截图、静态 QA 的本地 vendor、重复打包目录不上传，也不应复制到 Linux 使用。

当前只推进 PROTOCOL、SCENARIO 自行生成数据并经原工具链发送、标准接收解码和收发留痕。HISTORY 由外部接手人员负责，已有源码、测试、阶段计划及 `artifacts/icd_gateway/` 中的历史证据保留。当前不扩展 W4/W5，不将硬件采集、模型效果或正式替换资格列为发送里程碑前置。共享服务中的历史开发内容保留，不能据此推断目标后端已经接入。

## 拉取与环境

```bash
git clone --branch codex/icd-runtime-w1 --single-branch https://github.com/Alanni44/hil_simulation.git
cd hil_simulation
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-icd.txt
python -m pip check
```

Python 3.12 需要在目标 Linux 上预先可用。不要用系统旧 Python 3.6 安装本工作包，也不要覆盖旧 HIL 服务的依赖。若已克隆仓库，确认自己的本地修改已妥善保留后使用 `git fetch origin`、`git switch --track origin/codex/icd-runtime-w1`；已有该本地分支则切到该分支后 `git pull --ff-only`。不要强制重置自己的后续开发。

冻结 ICD 的共同指纹为 `22163dc21526ceadd63260b3d5670404a1064c4301e52b2a80edcf41a4fe8a27`。`.gitattributes` 禁止 Git 转换接口资料和已发布证据的换行，不能用格式化工具重写这些文件。两个旧 `hal_stub` 源文件保留已有 CRLF，避免历史原始字节指纹因平台换行产生差异；这不是 OS 专用实现。

## 最小验证与产生数据

先验证冻结资料和离线编码：

```bash
python -X utf8 scripts/build_contract_single_file.py --check
python -X utf8 -m icd_runtime --contract-dir docs/interfaces/baseline --expected-sha256 22163dc21526ceadd63260b3d5670404a1064c4301e52b2a80edcf41a4fe8a27
python -X utf8 -m unittest discover -s tests/icd_runtime -p 'test_*.py' -v
python -X utf8 -m unittest discover -s tests -p test_contract_single_file.py -v
python -X utf8 -m unittest discover -s tests -p test_development_backlog.py -v
python -X utf8 -c "import sys,unittest; sys.path.insert(0,'tests/icd_gateway'); names=['test_reception_service','test_can_ingress','test_send_run','test_send_cli']; r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromNames(names)); sys.exit(not r.wasSuccessful())"
```

生成当前完整运行配置中的三条样本，不发送网络数据：

```bash
python -X utf8 -m input_simulator.send_cli --contract-dir docs/interfaces/baseline --expected-sha256 22163dc21526ceadd63260b3d5670404a1064c4301e52b2a80edcf41a4fe8a27 --run-file config/generated-input-reception.json --output generated-new.jsonl --dry-run
```

输出必须使用不存在的新文件名。该配置生成目标步 0/80/160、风速 0/8/16 的完整环境输入。产生样本不等于链路发送完成。完整共用回归入口为 `python -X utf8 scripts/test_icd_runtime.py`；它运行全部网关测试，耗时大于上面的接续检查，也不证明实体通道或模型实时性。

静态 QA 脚本 `artifacts/interface_contract_validation/check_contract_v03.py` 是历史基线生成/校核工具，会写入冻结资料并校验原始 Word 文件。它不是运行时启动依赖；Linux 常规接续使用上面的只读 `--check`，不要缺少原文档时直接运行该生成脚本。

## 实体链路接续

共享接收和发送命令见 `icd_gateway/README.md` 开头的 Reception Milestone。`config/input-simulator-development.json` 当前为回环示例，必须按目标部署核定实际 IP、源/反馈端口、网卡、MAC 及授权身份；不能把回环示例当作实体 Scapy 部署。

- CANT 使用原 cantools/DBC、python-can 和 Linux SocketCAN；接收端显式加 `--can`，授权配置显式绑定 `CANFD_0` 到实际 `can0`。CAN FD 接口的设备、速率和权限由目标环境落实。
- ETHGEN 使用原 Scapy L2；指定实际网卡和源/目的单播 MAC，落实原始套接字权限及需要的系统抓包依赖。不要把普通 UDP 发送当成 ETHGEN 回退。
- HISTORY 的 canplayer/tcpreplay 与原回放分支保留，由第三条链路负责人接续。当前生成发送入口遇到未支持的回放动作明确拒绝，不跳过，也不伪造完成。

唯一待办仍为 `docs/superpowers/plans/linux-development-backlog.md`，本说明不新建第二套待办。当前目标主要对应 L-001/L-002/L-005/L-008/L-017；第三条 L-007/L-009 归接手人员。实际目标运行后应把命令、环境、完整 TX/RX 和真实结果追加到台账，缺环境的项目保持未执行。

接收验证模式仅给出标准 RECEIVED/VALIDATED、probe_id=0，不证明模型 APPLIED/CONSUMED，也不代表正式 3.3 平滑替换已验收。未来真实 3.3 仍通过相同冻结 ICD 和同一接收路径接入，不按模拟器/真实来源分流。
