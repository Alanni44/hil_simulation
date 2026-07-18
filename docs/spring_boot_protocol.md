# Spring Boot ↔ HIL 通信协议 V1.0

## 传输层

| 项目 | 说明 |
|------|------|
| 协议 | WebSocket |
| 端口 | 8100 |
| 路径 | `ws://{host}:8100/ws/hil` |
| 帧格式 | JSON 文本帧 |
| 心跳 | 客户端每 5s 发送 `{"cmd":"ping"}`，服务端回复 `{"cmd":"pong"}` |

## 格式

**请求：**
```json
{"cmd": "command_name", "params": {...}, "seq": 1}
```

**响应：**
```json
{"cmd": "command_name", "code": 0, "msg": "success", "data": {...}, "seq": 1}
```

| code | 含义 |
|------|------|
| 0 | success |
| -1 | 参数/命令错误 |
| -2 | 内部错误 |

## 指令

### 1. 生命周期

| cmd | 方向 | params | data | 说明 |
|-----|------|--------|------|------|
| hello | HIL→后端 | source: "model" | source: "model" | 连接身份 |
| load_model | 后端→HIL | model_id, model_name | status | 准备模型 |
| start_sim | 后端→HIL | — | status, sim_time | 启动仿真 |
| stop_sim | 后端→HIL | — | status | 停止 |
| pause_sim | 后端→HIL | — | status | 暂停 |
| resume_sim | 后端→HIL | — | status | 恢复 |
| set_param | 后端→HIL | key, value | status | 在线调参 |
| get_status | 后端→HIL | — | model_status, sim_time, fps | 运行状态 |

### 2. 飞行控制（向后兼容 UE4 协议）

| cmd | params | data.status | 说明 |
|-----|--------|-------------|------|
| takeoff | height | taking_off | 起飞 |
| land | — | landing | 降落 |
| hover | — | hovering | 悬停 |
| move_position | x, y, height, speed | executing | 飞向目标 |
| move_velocity | vx, vy, vz, duration | executing | 速度控制 |

### 3. 数据查询

| cmd | data | 说明 |
|-----|------|------|
| get_state | position{x,y,height}, velocity{vx,vy,vz}, status | 即时查询 |

### 4. 推送（HIL→后端）

**flight_data (10Hz):**
```json
{
  "cmd": "flight_data",
  "data": {
    "position": {"x": 20.3, "y": 10.2, "height": 29.8},
    "attitude": {"yaw": 45.2, "pitch": 2.1, "roll": -1.3},
    "velocity": {"vx": 4.9, "vy": 0.1, "vz": 0.0},
    "timestamp": "2026-07-17T14:00:01.000Z",
    "frame": 12345
  }
}
```

**sim_heartbeat (1Hz):**
```json
{
  "cmd": "sim_heartbeat",
  "data": {
    "sim_time": 123.4,
    "rt_factor": 0.98,
    "task_cpu": 5,
    "status": "running"
  }
}
```

## 与 UE4 的关系

| | WebSocket(后端) | TCP(UE4) |
|---|---|---|
| 协议 | WebSocket JSON | TCP JSON + \n |
| 端口 | 8100 | 8889 |
| 方向 | 双向 req/res + push | 单向 push |
| position | x, y, height | x, y, height |
| velocity | vx, vy, vz | vx, vy, vz |
| attitude | yaw, pitch, roll | roll, pitch, yaw |
| status | "flying"/"landed" | "Flying"/"Landed" |

飞行控制指令 `takeoff/land/hover/move_position/move_velocity` 同名同参，后端可透传。
