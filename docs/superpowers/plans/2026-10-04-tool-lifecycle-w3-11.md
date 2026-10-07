# Original Tool Lifecycle W3.11 Implementation Plan

> **For agentic workers:** Use executing-plans and test-driven-development inline. Independent read-only review only. No implementation delegation, commit, branch, worktree or frozen QA generation.

**Goal:** 实现六原分支的真实安装证据、共用有界直接子进程监督和本地发送互斥，为后续正式授权/各工具后端封装提供共同生命周期，不把诊断进程当业务发送或完整工具资格。

**Architecture:** 沿批准设计保留原分支。`tools.py`核对冻结目录六分支，映射既定管理API名称并只探测安装事实；`tool_process.py`负责可信内部argv运行、原二进制stdout/stderr、退出/超时/停止及容量；本地接口预约不代表标准SessionGranted/ControlOwner。全工具实际启动参数、完整进程树清理、部署权限/后端/GUI与发送接执行器仍由共同后续和Linux目标完成，不引入转发中心或Windows后端。

**Tech Stack:** Python3.12标准库importlib.metadata/util、shutil、subprocess、threading、time，现有Contract/ICDError；不安装新依赖或原工具。

## Constraints And Interfaces

- 冻结14源、v0.3、原C与六原工具保持；41责任/17 Linux未执行保留。此包不勾选完整M3/M4或整体完成。
- 六分支固定为CANT/CUTIL/SAVVY/CANREPLAY/ETHGEN/ETHREPLAY，API名称分别SIGNAL_CAN/CAN_UTILS/SAVVYCAN/CAN_REPLAY/ETHERNET_GENERATOR/PCAP_REPLAY。未知/缺失/重复目录拒绝。
- `ToolInventory(contract).inspect()->tuple[ToolInstallation,...]`读取实际模块规格、distribution版本及PATH绝对可执行文件/sha256，不导入工具或启动GUI、不执行版本命令、不能发现安装就标AVAILABLE。不可用链标UNAVAILABLE，其余UNVERIFIED；目标Linux/SocketCAN/网卡/时序/授权均待验证。API行严格只有branch_id/status/reason，其余本地诊断不加入冻结接口。
- `ChannelReservations(capacity=64).reserve(run_id,branch_id,interfaces:tuple,*,mode)->ChannelReservation`支持OBSERVE/SEND。OBSERVE不持发送预约，SEND同一物理接口仅一owner；多接口原子预检/预约；opaque返回对象仅本簿接受，旧token/伪造token/外簿token拒绝；release只释放该owner，容量满不自动删除。预约不是线上控制权，禁止据此发送。
- `ProcessSupervisor(argv:tuple[str,...], *, cwd:Path, timeout_ms=10000, output_limit=1MiB, stop_timeout_ms=1000)`仅供可信内部诊断/未来已审核工具适配器，不是API执行任意命令入口；argv首项为现存绝对普通可执行文件，cwd明确绝对目录，拒绝shell/batch脚本，不扩展shell/环境变量。shell=False、stdin=DEVNULL、close_fds=True；不增加Windows创建旗标或复制实现。
- `start()->ProcessSnapshot`只一次；`poll()->ProcessSnapshot`核对实际returncode、mono期限、双管道状态；`stop()->ProcessSnapshot`terminate→有限wait→kill→有限wait；`close()`永久关闭且保留结果；`snapshot`不可变bytes和实际PID/returncode/时间/error。READY/输出不是链路接收/模型反馈；退出0且全输出完整才EXITED，非零/输出超限/读失败/超时为FAILED，主动停止为STOPPED。
- stdout/stderr reader各原始bytes，合并保留不超过显式额度；观察到超限立即记录BUFFER_FULL并kill直接子进程，不静默截断为成功；保留前缀、实际观察bytes和output_complete=false。Popen创建时间无法保证有界，不承诺RT；超时以启动前mono计且每次poll/stop核对。直接子进程终态与管道EOF分别核对，管道持有者/进程树未完成不释放实际设备/发送权或报告清理完成；Linux树生命周期是剩余资格。

## Task 1: Installation Evidence And Local Interface Reservations

**Files:** Create `input_simulator/tools.py`, `tests/icd_gateway/test_tools.py`.

- [x] RED六API行/真实安装版本/文件hash且无AVAILABLE、未知/篡改目录、实际库不导入、不可变快照、观察不持发送权、跨分支物理接口冲突、多接口原子失败、满容量/重复run、伪造/外簿/已释放token。

```python
inventory = ToolInventory(contract).inspect()
assert len(inventory) == 6
assert all(item.api_row()['status'] != 'AVAILABLE' for item in inventory)
book = ChannelReservations()
first = book.reserve('run-1', 'CANT', ('can0',), mode='SEND')
book.reserve('watch-1', 'CUTIL', ('can0',), mode='OBSERVE')
with raises(ICDError):
    book.reserve('run-2', 'CANREPLAY', ('can0', 'can1'), mode='SEND')
book.release(first)
```

- [x] Run `python -X utf8 -m unittest discover -s tests/icd_gateway -p test_tools.py -v`，观察明确缺失模块断言失败。
- [x] GREEN冻结目录核验、真实安装与本地预约，确保预约不能生成标准授权或ready。影子模块先RED后校验实际distribution RECORD/origin归属，另真实Python可执行文件bytes/hash只探测不启动，10专项通过。状态仅依据依赖证据，不按宿主OS分流；完整安装UNVERIFIED，缺依赖UNAVAILABLE，目标后端仍待验证。

## Task 2: Actual Bounded Process Lifecycle

**Files:** Create `input_simulator/tool_process.py`, `tests/icd_gateway/test_tool_process.py`.

- [x] RED实际独立Python诊断子进程：binary双流/非零/无shell特殊argv、输出超限、大双流无deadlock、实际超时终止/手动停止/永久close、缺文件/非法参数、启动失败、退出后管道EOF与快照不可变。不把该worker冒充原六工具或实际消费者。

```python
worker = ProcessSupervisor((sys.executable, '-c', "import os; os.write(1,b'out'); os.write(2,b'err')"), cwd=root)
worker.start()
while worker.poll().state == 'RUNNING':
    time.sleep(0.005)
assert worker.snapshot.stdout == b'out'
assert worker.snapshot.stderr == b'err'
assert worker.snapshot.returncode == 0
worker.close()
```

- [x] Run `python -X utf8 -m unittest discover -s tests/icd_gateway -p test_tool_process.py -v`，先缺失模块RED，再实现最小可靠监督并GREEN。期限/自然退出/EOF与wait异常先RED后修正，19专项通过；自然EXITED等EOF也受原执行期限约束。
- [x] 独立只读复核新模块和专项；发现先RED后修正，最终19进程/10工具/6原CLI及独立同数复核通过，无剩余重要scoped发现。固定源码完整公共入口522通过（67协议/448网关/3台账/4汇总，网关357.666s），另34静态/59-72-85-800/依赖/编译/14源-663refs/41-17守护通过。首轮446网关exit1发现OS诊断分流且运行中修正EOF期限，已等待终态、保留原守护并固定重跑，不计首轮为验收。
- [x] 写独立`artifacts/icd_gateway/w3-11-validation.json`；追加唯一台账Linux安装版本/实际工具启动/GUI/SocketCAN/网卡/进程树/权限/超时/停止/实际授予与反馈要求，共用剩余完整执行器/六wrapper/场景/API/Robot/持久证据不推为Linux重写。本包仅完整实现所列共用基础，不勾选整体里程碑或目标验收。

## Reviewed Scope And Sources

本包落在M3-01至M3-06的安装报告/生命周期/互斥共用部分；它不是六工具业务执行全部完成。已批准设计与用户继续推进授权有效，沿既有分解直接执行，不改整体目标。不采用静态写死“可用”报告、Windows版工具替代或把任意argv暴露到管理API。

Python3.12官方subprocess文档已核对：binary pipes、Popen.poll/wait/terminate/kill、timeout和创建阶段限制；`https://docs.python.org/3.12/library/subprocess.html`。安装证据使用官方`https://docs.python.org/3.12/library/importlib.metadata.html`描述的实际distribution metadata。
