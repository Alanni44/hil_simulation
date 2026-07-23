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
  tests/              测试工具 (mock_core、UE4 模拟器)
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
pip3 install pyyaml
```

### 2. 配置网络

编辑 `config.yaml`，确认 UE4 Bridge 地址与实际环境一致。

### 3. Demo 测试 — 圆形航线

UE4 组先启动 Python Bridge Server（监听 TCP 5000），或使用本地模拟器：

```bash
# 终端 1: 模拟 UE4 Bridge Server
python3 tests/test_ue4_client.py
```

然后启动 Demo：

```bash
# 终端 2: 一键启动
chmod +x scripts/demo_circle.sh
./scripts/demo_circle.sh
```

流程: mock_core (CSV 50Hz UDP) → Python 服务 → TCP Bridge → UE4

### 4. 生产启动

```bash
chmod +x scripts/start_all.sh scripts/stop_all.sh
./scripts/start_all.sh    # 编译 RT 可执行文件 + 启动所有服务
./scripts/stop_all.sh     # 停止所有服务
```

### 5. 手动运行各组件

```bash
# 模拟 C 核心 (CSV 轨迹回放)
python3 tests/mock_core.py --csv tests/uav_circle_test_50hz_60s.csv

# 仅启动 Python 服务
cd python_services && python3 main.py
```

## 开发约束

- 开发环境 Windows，运行环境 Ubuntu 18.04 RT
- Python 兼容 3.6.9（不使用 3.7+ 特性）
- MATLAB 兼容 R2018b
- 通信协议严格遵循 V2.0，不得偏差
