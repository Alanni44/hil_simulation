## HIL 生产模式完整测试流程

### 1. 环境准备

**硬件/操作系统**
- Ubuntu 18.04
- 至少 4 GB RAM, 2 CPU 核心

**必需软件**
```bash
sudo apt update
sudo apt install -y build-essential libjson-c-dev python3 python3-pip
pip3 install pyyaml
```

**必需工具**
- MATLAB R2018b（已安装于 `/usr/local/MATLAB/R2018b`）
- Quad_sim.slx（位于桌面 `Quad-Simulink-Simulation-master/Quad-Simulink-Simulation-master/`）

---

### 2. 代码部署

```bash
cd ~/桌面
git clone https://github.com/Alanni44/hil_simulation.git
cd hil_simulation
```

确认项目结构：
```bash
ls tests/prod_test/production_test.sh       # 一键测试脚本
ls matlab_scripts/analyze_model.m           # 模型分析脚本
ls matlab_scripts/adapt_model.m             # 模型适配脚本
ls matlab_scripts/build_script.m            # ERT 代码生成 + 编译
ls c_core/src/main_rt.c                     # C 核心 RT 调度
ls tests/full_integration_test.py           # 自动化测试驱动
```

---

### 3. 启动测试

```bash
bash tests/prod_test/production_test.sh
```

**脚本自动执行以下 4 个阶段:**

#### Phase 0: 编译 C 核心

1. **preflight 检查** — 验证 SLX 文件存在、MATLAB 可用、GCC/Python/libjson-c/pyyaml 已安装
2. **analyze_model.m** — 加载 Quad_sim.slx，输出 `interface.json`（根级 Inport/Outport 数量、求解器类型、连续状态信息）
3. **adapt_model.m** — 将根级 Constant/Step 块转为 Inport，Scope/ToWorkspace 块转为 Outport
4. **build_script.m** — ERT 代码生成 → 生成 `model_mapping.h` + `model_config.h` → GCC 编译
5. **输出** — `models/executables/Quad_sim_rt` 可执行文件

#### Phase 1: 启动服务

| 终端 | 进程 | 端口 | 作用 |
|---|---|---|---|
| UE4 模拟器 | `tests/test_ue4_client.py` | TCP 5000 | 模拟 Python Bridge Server |
| Python 服务 | `python_services/main.py` | UDP 9998 + TCP client | 状态缓存 + V2.0 bridge |
| C 核心 | `models/executables/Quad_sim_rt` | UDP 9997 (cmd) + 9998 (status) + 9999 (monitor) | 1ms RT 模型解算 |

#### Phase 2: 运行测试

`tests/full_integration_test.py` 通过 UDP 9997 发送命令，通过 UDP 9999 读取 FlightState，执行 6 大场景 25 项自动化检查:

| 场景 | 测试内容 | 验证点 |
|---|---|---|
| **S1 飞行参数** | takeoff → move_position(20,10,20) → hover → land | 位置跟随、漂移 <0.5m、高度变化正确 |
| **S2 模型参数调参** | tune mass/gravity/drag/PID | 参数修改后行为变化 (响应正确) |
| **S3 航点导航** | load_mission 3 个航点 | waypoint_index 递增、高度在航点范围内 |
| **S4 V2.0 协议** | TCP 5000 连接 + hello ACK + mission_plan ACK + vehicle_state 50Hz | 协议完整性 |
| **S5 状态完整性** | UDP 9998 持续输出、NaN/Inf 校验、sim_time 单调、flight_state 合法码 | 数据质量 |
| **S6 异常恢复** | 非法 tune key、负质量、降落→重起飞 | 程序健壮性 |

#### Phase 3: 清理

- 停止所有子进程
- 清理残留端口

---

### 4. 可选环境变量

| 变量 | 说明 | 默认值 |
|---|---|---|
| `SLX_PATH` | 自定义 .slx 文件路径 | 自动检测 `~/桌面/Quad-Simulink-Simulation-master/.../Quad_sim.slx` |
| `BUILD_ALWAYS=1` | 强制重新 MATLAB → ERT → GCC 编译 | 仅首次使用 |
| `SKIP_RT=1` | 降级到 Python mock_core | 生产模式已禁用此选项 |

---

### 5. 预期结果

**preflight 阶段输出:**
```
[preflight] Checking required paths...
  Desktop: /home/user/桌面
  [OK]  SLX: /home/user/桌面/Quad-Simulink-Simulation-master/.../Quad_sim.slx
  [OK]  MATLAB: /usr/local/MATLAB/R2018b/bin/matlab
  [OK]  gcc: /usr/bin/gcc
  [OK]  g++: /usr/bin/g++
  [OK]  python3: /usr/bin/python3
  [OK]  libjson-c-dev: /usr/include/json-c/json.h
  [OK]  pyyaml

All production requirements met — MATLAB_ERT mode
Pipeline: analyze_model.m → adapt_model.m → build_script.m → ERT → GCC
```

**测试结果输出:**
```
============================================================
  结果: 25 通过, 0 失败 (共 25)
============================================================
  [PASS] S1a-takeoff: 爬升至 ~15m — avg_z=15.1
  [PASS] S1b-move: 飞向 (20,10,20) — pos=(19.5,9.8,20.1)
  [PASS] S1c-hover: 1s 漂移 <0.5m — drift=0.02m
  ... (共 25 项)
  [PASS] S6d-reto: 重起飞 flight_state≠5 — fs=3

All tests passed.
```

---

### 6. 故障排查

| 问题 | 原因 | 解决 |
|---|---|---|
| `SLX path not found` | 桌面有中文名称 | 设置 `SLX_PATH` 环境变量指向正确路径 |
| `MATLAB not found` | MATLAB 未安装在标准位置 | 确认 `which matlab` 或修改 `find_matlab()` 函数 |
| `libjson-c-dev not found` | 缺少依赖 | `sudo apt install -y libjson-c-dev` |
| `model_config.h: 没有那个文件` | GCC fallback 失败 | 确认 MATLAB ERT 构建成功 |
| C 核心启动失败 | 无 root 权限 | 脚本已自动尝试两次（先无 sudo，再 sudo） |

### 7. 成功标志

- [x] MATLAB ERT 代码生成成功
- [x] GCC 编译生成 `Quad_sim_rt` 可执行文件
- [x] C 核心以 1ms RT 调度运行
- [x] 所有 6 个测试场景全部 PASS
- [x] V2.0 协议验证通过
- [x] 在线调参 (飞行参数 + 模型参数) 功能正常
