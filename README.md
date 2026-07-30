# HIL 仿真系统

硬件在环（HIL）仿真飞行验证系统，运行于 PXIe 模型运算设备。Simulink 负责无人机动力学计算，Python Bridge 负责坐标转换和三维渲染通信，C 核心负责 1ms 硬实时模型解算。

## 架构

```
后端 (Spring Boot)
  ↓ 任务/控制输入
Simulink (无人机动力学、控制算法)
  ↓ 实时状态 (V2.0 TCP 协议)
Python Bridge (坐标转换、状态缓存)
  ↓ 位姿更新
AirSim + UE4 (三维渲染)
```

- **Simulink**: 无人机位置、姿态、速度的权威数据源
- **Python Bridge**: 接收状态、校验协议、坐标转换、驱动 UE4 渲染
- **AirSim / UE4**: 渲染适配层，不再自行计算飞行动力学

通信协议详见 `C:\Users\裴鹏飞\Desktop\Simulink_三维视景通信协议草案_V2.0.md`

## 目录结构

```
hil_simulation/
  c_core/             C 硬实时核心 (1ms 调度、模型解算)
  python_services/    Python 控制与转发层
    shared/           共享库 (状态缓存、飞行状态解析、日志)
  matlab_scripts/     MATLAB 代码生成脚本 (R2018b 兼容)
  model/              Simulink 生成的 C 模型代码
  scripts/            启动/停止脚本
  config.yaml         配置文件
```

## 通信流程 (V2.0 协议)

```
TCP 连接
  → hello (握手)
  → 等待 ACK
  → mission_plan (航点规划)
  → 等待 ACK
  → vehicle_state (50Hz 实时状态)
  → (可选) simulation_event (暂停/恢复/重置/结束)
```

消息帧格式: `[4 字节大端长度头][UTF-8 JSON]`

Python Bridge 为 TCP Server (192.168.100.172:5000)，Simulink / HIL 为 TCP Client。

## 环境要求

| 组件 | 版本 |
|---|---|
| 操作系统 | Ubuntu 18.04 RT |
| Python | 3.6.9 |
| MATLAB | R2018b |
| 编译工具 | GCC 7, build-essential, libjson-c-dev |

## 快速开始

### 1. 安装依赖

```bash
sudo apt update
sudo apt install -y build-essential libjson-c-dev python3 python3-pip
pip3 install -r requirements.txt
```

### 2. 配置网络

编辑 `config.yaml`，确认 UE4 Bridge 地址与实际环境一致。

### 2. 生产部署

外部模型管理系统将不可变模型包放入受控本地目录；HIL 只校验包、调用
MATLAB/GCC 并运行唯一的已验证核心。它不提供模型上传、注册表、历史回滚、
活动软链接、远程下载或进程内热重载。包必须含 `package_manifest.json`、顶层
`.slx` 和显式 `hil_contract.json`；详细边界见
[`models/README.md`](models/README.md)。

### 3. 开发启动

`start_all.sh` 只接受已经完整验证的可执行程序，默认不请求 sudo。

```bash
chmod +x scripts/start_all.sh scripts/stop_all.sh
./scripts/start_all.sh /absolute/path/to/verified_model_rt
./scripts/stop_all.sh
```

### 4. 手动运行各组件

```bash
# 仅启动 Python 服务
cd python_services && python3 main.py
```

## 目标环境验收

`ert.tlc` 需要 Embedded Coder 许可证。第一周工具链精确版本固定在
[`config/target-toolchain.json`](config/target-toolchain.json)，Python 包固定在
[`requirements.txt`](requirements.txt)。从干净工作区只运行统一入口：

```bash
sudo apt update
sudo apt install -y build-essential libjson-c-dev python3 python3-pip
python3 -m pip install -r requirements.txt
bash scripts/run_ubuntu_acceptance.sh
```

该命令先运行 `python3 -m unittest discover -s tests -v` 的全部 Python 测试，
再执行 MATLAB ERT/GCC 与运行时合同验收。所有产物统一写入
`artifacts/acceptance/<UTC>-<Git短SHA>-week1-baseline/`，包括环境指纹、测试
报告、构建/运行日志、原始报文、断言、问题清单和唯一的 `result.json`。其中
`result.json.git_head` 必须等于当前 `git rev-parse HEAD`；工作区不干净、依赖
版本不符、测试跳过或断言失败均不得宣称通过，也不得引用 2026-07-27 的旧证据。

## 开发约束

- 开发环境 Windows，运行环境 Ubuntu 18.04 RT
- Python 兼容 3.6.9（不使用 3.7+ 特性）
- MATLAB 兼容 R2018b
- 通信协议严格遵循 V2.0，不得偏差
