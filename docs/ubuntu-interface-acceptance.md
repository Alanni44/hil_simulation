# Ubuntu 模型接口与 UE4 V2.0 验收方法

本文档对应“模型输入合同 + 参数分类 + UE4 V2.0 50 Hz 输出”改造。本文档中的命令**不得在 Windows 上作为验收执行**；本次开发未执行任何单元测试、MATLAB 构建、网络联调或实时测试。

## 前置条件

- 操作系统：Ubuntu 18.04 RT。
- MATLAB：R2018b，已安装 Simulink Coder 与 Embedded Coder。
- 编译器：GCC 7.x。
- Python：3.6.9。
- Python 依赖：`PyYAML`、`json-c` 开发库和项目既有依赖均已安装。
- UE4 侧 Python Bridge 已在 `config.yaml` 的 `ue4_tcp.host:port` 上作为 TCP 服务端监听。
- 使用干净的 Git 检出；运行前 `git status --porcelain` 不得输出内容。

## 本轮范围

已实现并需验收：

- `hil_contract.json` V2：飞控、环境、故障三类输入；UE4 50 Hz 输出和三轴加速度；固定 1 ms 执行约束。
- 输入命令：`set_inputs` 按合同字段、类型、维度和范围校验，整组原子提交，在下一个模型步前生效。
- 参数命令：`live` 与 `reset_only` 分级；`reset_only` 只允许 `PAUSED` 状态提交。
- UE4：HIL 侧 TCP 客户端连接 UE4 侧 Python Bridge 服务端；先 `hello` 确认，再固定 50 Hz 发送 `vehicle_state`。
- 坐标转换：NED `(north,east,down)` 映射为 V2.0 `(x,y,height)=(north,east,-down)`；垂直速度与垂直加速度符号反转；姿态为弧度。

本轮明确不实现、不验收：PX4 虚拟传感器输出、平台遥测输出、实时抖动/30 分钟稳定性门槛，以及把航点/目标/载荷直接绑定到 SLX 根输入。现有 `load_mission` 仍用于 UE4 航迹通知；模型合同不得声明 `inputs.mission.enabled=true`，避免伪称模型已接收任务输入。

## 验收步骤

### 1. 运行 Python 合同和协议测试

```bash
cd /path/to/hil_simulation
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  tests.test_model_registry \
  tests.test_v2_protocol \
  tests.test_static_contract
```

通过标准：退出码为 `0`；所有测试均为 `OK`。若出现失败，不得继续执行模型构建验收。

### 2. 构建并运行合同验收模型

```bash
cd /path/to/hil_simulation
HIL_DEPLOY_MODE=development HIL_SKIP_REALTIME_GATE=1 \
  python3 scripts/accept_runtime_contract.py
```

通过标准：

- 验收脚本退出码为 `0`，新建 `artifacts/acceptance/<run-id>/result.json`。
- `result.json.status` 为 `passed`，其中 `git_head` 等于 `git rev-parse HEAD`。
- `environment.json` 显示 Ubuntu 18.04 RT、MATLAB R2018b、GCC 7.x、Python 3.6.9。
- `source-manifest.json` 包含模型包、C、MATLAB、Python、脚本、生成代码和可执行文件的哈希。
- 篡改任一合同字段、删除 `wind_d_mps`、删除加速度输出、改变单位、使 `reset_only` 允许 `RUNNING`，均必须在 `VALIDATING` 或 `BUILDING` 阶段失败。

### 3. 验证输入命令的原子性

部署完成后，通过 WebSocket 或本地 UDP 指令端口发送：

```json
{
  "request_id": "input-positive",
  "cmd": "set_inputs",
  "params": {
    "flight_control": {"throttle": 0.5, "roll_cmd": 0.1},
    "environment": {"wind_n_mps": 3.0},
    "fault": {"packet_loss_ratio": 0.02}
  }
}
```

再发送一个混合合法/非法的请求：

```json
{
  "request_id": "input-atomic-reject",
  "cmd": "set_inputs",
  "params": {
    "flight_control": {"throttle": 0.7},
    "fault": {"packet_loss_ratio": 1.2}
  }
}
```

通过标准：

- 第一条回执 `accepted=true`，并在下一模型步后的状态中体现对应模型行为。
- 第二条回执 `accepted=false`，`reason` 为 `atomic input group rejected`，且第一条已生效的输入值和模型行为均不得被第二条部分覆盖。
- 未声明输入组、未知字段、布尔字段使用数值、数组维度错误、数值越界必须被拒绝。

### 4. 验证 UE4 V2.0 会话和 50 Hz 状态流

UE4 侧 Python Bridge 服务端应记录以下顺序：

1. HIL TCP 客户端连接。
2. 收到 `hello`，其中 `role` 为 `simulink_state_source`、`state_rate_hz` 为 `50`、坐标约定为 `x_forward_y_right_height_up`、角度单位为 `rad`。
3. 服务端发送 `ack`，`data.accepted=true` 且 `data.ref_type="hello"`。
4. 收到 `mission_plan` 后确认；之后才检查 `vehicle_state`。

对 10 秒 `vehicle_state` 报文计数，允许 TCP/操作系统调度造成的短时抖动，但平均频率必须在 49–51 Hz，且报文 `seq` 严格递增。

对已知状态 `north=10,east=20,down=30,vn=1,ve=2,vd=3,ax=4,ay=5,az=6`，通过标准为：

```json
{
  "position": {"x": 10, "y": 20, "height": -30},
  "velocity": {"vx": 1, "vy": 2, "vz": -3},
  "acceleration": {"ax": 4, "ay": 5, "az": -6}
}
```

`vehicle_state.data` 必须包含 `mission_id`、`sim_time`、`position`、`attitude`、`velocity`、`acceleration`、`angular_velocity`；不得把内部 `RUNNING`、`PAUSED`、`RESETTING`、`ENDED` 写入 V2.0 `flight_state` 字段。内部 `reset` 对外只能发送 `simulation_event.data.event="reset_scene"`。

## 未通过处理

任一命令失败时，保留对应的 `artifacts/acceptance/<run-id>` 目录、`build.log`、`runtime.log`、`packets.ndjson`、`assertions.json` 与 `result.json`，并以该目录中的 Git 提交号、哈希、失败阶段和原始报文定位问题。不得通过修改证据包或跳过失败断言宣称验收通过。
