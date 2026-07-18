# Spring Boot ↔ Python Bridge 通信协议 V1.0

## 通道

| 项目 | 说明 |
|------|------|
| 协议 | TCP |
| 端口 | 8100 |
| 模式 | 请求-响应（短连接），每条 JSON 以 `\n` 结尾 |
| 编码 | UTF-8 |

## 指令表

| cmd | 请求参数 | 响应 | 备注 |
|-----|---------|------|------|
| init_sim | initial_lat, initial_lon, initial_alt, initial_roll, initial_pitch, initial_yaw | success/error | 初始化仿真参数 |
| takeoff | 无 | success/error | 起飞（目标高度 50m） |
| land | 无 | success/error | 降落 |
| hover | 无 | success/error | 立即悬停（保持当前位置） |
| move_position | x, y, height, speed | success/error | 飞向目标点 |
| move_velocity | vx, vy, vz, duration | success/error | 按速度矢量飞行 |
| tune | pid_kp_roll, pid_ki_roll, pid_kd_roll, target_alt 等 | success/error | 在线调参 |
| get_state | 无 | 状态数据 | 查询当前飞行状态 |

## 响应格式

### 成功

```
{"code": "success"}
```

### 失败

```
{"code": "error", "msg": "错误描述"}
```

### get_state 返回

```
{
    "code": "success",
    "position": {"x": 20.3, "y": 10.2, "height": 29.8},
    "velocity": {"vx": 4.9, "vy": 0.1, "vz": 0.0},
    "attitude": {"roll": 0.05, "pitch": 0.03, "yaw": 0.02},
    "status": "Flying"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| position.x / y | double | 水平位置 (m) |
| position.height | double | 高度 (m) |
| velocity.vx / vy / vz | float | 速度 (m/s) |
| attitude.roll / pitch / yaw | float | 姿态角 (rad) |
| status | string | "Flying" 或 "Landed" |

## 样例

### 1. init_sim

请求：
```
{"cmd": "init_sim", "params": {"initial_lat": 39.9, "initial_lon": 116.4, "initial_alt": 100.0, "initial_roll": 0.0, "initial_pitch": 0.0, "initial_yaw": 0.0}}
```

响应：
```
{"code": "success"}
```

### 2. takeoff

请求：
```
{"cmd": "takeoff"}
```

响应：
```
{"code": "success"}
```

### 3. land

请求：
```
{"cmd": "land"}
```

响应：
```
{"code": "success"}
```

### 4. move_position

请求：
```
{"cmd": "move_position", "params": {"x": 20.0, "y": 10.0, "height": 30.0, "speed": 5.0}}
```

响应：
```
{"code": "success"}
```

### 5. move_velocity

请求：
```
{"cmd": "move_velocity", "params": {"vx": 5.0, "vy": 0.0, "vz": 2.0, "duration": 0.1}}
```

响应：
```
{"code": "success"}
```

### 6. tune

请求：
```
{"cmd": "tune", "params": {"pid_kp_roll": 1.5, "pid_ki_roll": 0.1, "target_alt": 80.0}}
```

响应：
```
{"code": "success"}
```

### 7. get_state

请求：
```
{"cmd": "get_state"}
```

响应：
```
{
    "code": "success",
    "position": {"x": 20.3, "y": 10.2, "height": 29.8},
    "velocity": {"vx": 4.9, "vy": 0.1, "vz": 0.0},
    "attitude": {"roll": 0.05, "pitch": 0.03, "yaw": 0.02},
    "status": "Flying"
}
```
