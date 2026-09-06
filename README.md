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

默认通信协议为 V2.0；固定翼可按下文切换到 V3.0。

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

Python Bridge 为 TCP Server (192.168.3.122:5000)，Simulink / HIL 为 TCP Client。

## 固定翼 V3.0

将 `config.yaml` 中 `bridge.protocol_version` 设为 `"3.0"`，并重新构建带
`protocol_v3` 的固定翼模型包后，Python Bridge 将作为 TCP Server 监听
`fixed_wing_v3.host:port`；固定翼 C 核心/Simulink 作为 TCP Client，以
`FixedWing01` 身份按 50 Hz 发送 V3 `vehicle_state`。每帧仍是
`[4 字节大端长度头][UTF-8 JSON]`，没有换行分隔。

C 核心通过 `HIL_V3_TCP_HOST`、`HIL_V3_TCP_PORT`（未设置时为
`127.0.0.1:5000`）指定 Bridge 地址。连接后严格执行
`hello → ack → mission_plan → ack → vehicle_state@50Hz`，断线后在独立的
非实时线程重连，因此不会阻塞 1 ms 模型周期。

必填数据包括位置、姿态、速度、加速度、FRD 角速度、0~1 油门和飞行阶段；空气
动力学数据按 `V_air = V_ground - V_wind` 计算，并在真空速低于模型契约的
`tas_min_mps` 时省略。迎角/侧滑角采用 `alpha=atan2(w,u)`、`beta=asin(v/TAS)`。

真实副翼、升降舵、方向舵仅在固定翼 `hil_contract.json` 明确声明时发送：可声明
已验证的命令到舵偏角映射，或声明 SLX 的真实舵面输出字段；绝不会把
`roll_cmd`、`pitch_cmd`、`yaw_cmd`直接伪装成舵面角。

V3 服务只保留最新有效状态；500 ms 未更新会标记数据陈旧，2 s 未更新会标记
通信超时。该同一状态链供 AirSim `simSetKinematics` 注入（启用
`fixed_wing_v3.airsim_enabled` 时）、HUD、日志和 WebSocket `get_state` 使用。

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

### GitLab 受控模型发布（可选）

系统可从企业自建 GitLab 的**已发布版本**读取一个不可变模型包。该功能默认关闭；
它不上传、修改、删除 GitLab 内容，也不替代 GitLab 的分支、合并请求或权限管理。

1. 在 `config.yaml` 的 `gitlab_release` 中设置 `enabled: true`、企业 GitLab 的 HTTPS
   `base_url`、允许使用的 `projects` 白名单，以及统一发布资产名
   `hil_model_package.zip`。
2. 将 `deploy/systemd/gitlab-release.env.example` 复制为
   `/etc/hil/gitlab-release.env`，填入仅有 `read_api` 权限的项目或群组访问令牌，并设置
   `root:hil` 所有者和 `0640` 权限。令牌仅由 Python 服务进程读取，不写入 YAML、浏览器、
   审计文件或 Git 仓库。
3. 重启 `hil-python-services`。打开 `web/hil_console.html` 后，连接 WebSocket，输入
   白名单内项目路径，选择 Release，执行“验证并暂存”。
4. 暂存会限制下载大小、拒绝非 HTTPS/跨源地址、拒绝 ZIP 路径穿越和符号链接，并通过现有
   `package_manifest.json` 与 `hil_contract.json` 校验。校验成功后，包才会原子发布到
   `/opt/hil/packages/gitlab/<project>/<tag>/`；同一版本不可覆盖。
5. 控制台返回现有 `build_package` / `deploy_package` 所需参数。代码生成、单实例停止旧核、
   启动新核及健康检查仍完全遵循原有执行链路。

若尚未填写自建实例地址、项目或令牌，控制台会显示“未配置”，且不会发起 GitLab 网络请求。
本地审计记录位于 `artifacts/gitlab-audit/`，仅包含项目、标签、提交、哈希和模型版本。

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

### 5. 虚拟四旋翼飞控联调（软件闭环）

虚拟飞控默认关闭。将 `config.yaml` 中的
`virtual_quad_fc.enabled` 设为 `true` 后重启 Python 服务。C 核心会在
`127.0.0.1:9996` 以 250 Hz 发布独立的模型状态快照；虚拟飞控只使用该
快照生成 IMU、气压计、GPS、模型真值和健康帧，UE4 的 50 Hz 状态流不参与
传感器闭环。

虚拟飞控不会自行取得控制权。先通过 WebSocket 选择唯一控制源，再启动闭环
目标场景：

```json
{"cmd":"select_control_source","params":{"source":"physical_uut"}}
{"cmd":"virtual_fc_start","params":{"scenario":"takeoff"}}
```

可用场景：`idle`、`takeoff`、`hover`、`forward`、`turn`、`land`。场景不再直接
写固定电机值：虚拟飞控只从自己接收的 IMU、GPS、气压计更新状态估计，并以位置
→速度→姿态→电机的串级控制器在 250 Hz 重算电机命令；IMU/GPS/气压计任一数据
超过安全新鲜度阈值时进入 `FAILSAFE` 并发送零推力。

也可下发任意 NED 目标或路线：

```json
{"cmd":"virtual_fc_set_target","params":{"north_m":20,"east_m":5,"down_m":-5,"yaw_deg":90}}
{"cmd":"virtual_fc_load_route","params":{"waypoints":[{"north_m":0,"east_m":0,"down_m":-5},{"north_m":20,"east_m":0,"down_m":-5},{"north_m":20,"east_m":0,"down_m":0,"landing":true}]}}
```

路线仅在到达当前点且速度降低后才切换下一点。运行状态和记录路径通过
`virtual_fc_status` 获取；停止场景使用 `virtual_fc_stop`。可通过
`virtual_fc_inject_fault` 注入 `sensor_invalid`、`model_invalid`、固定延迟
`fixed_delay_ms`、随机丢包 `packet_loss_ratio`，以及一次性的
`duplicate_next`、`out_of_order_next`、`timestamp_rollback_next`、
`invalid_frame_next`；用 `{"name":"clear"}` 清除故障。每次服务启动会在
`runtime/virtual_fc/<UTC>/frames.ndjson` 留下传感器、执行器、拒绝原因和故障
事件的原始记录。为避免长期浸泡测试耗尽磁盘，`virtual_quad_fc.recording`
默认每 64 MiB 将已完成的记录压缩为 `frames.NNNN.ndjson.gz`，每次运行最多保留
512 MiB 原始记录，并在服务启动时清理 14 天前的历史运行目录。

执行器帧必须含严格单调的 `sequence` 和 `timestamp_us`，并含四个 `[0,1]`
电机命令。帧不合法、重复、乱序或时间回退时在适配器边界丢弃，绝不会转发给 C
核心；有效帧仍要经过 C 核的 `physical_uut` 互斥选择及 100 ms 超时归零保护。

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
