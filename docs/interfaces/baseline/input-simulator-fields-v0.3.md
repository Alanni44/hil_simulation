# 输入参数逐字段定义 v0.3

本文件与业务Schema、ICD目录同属HIL-ICD-1.0；全部字段由本项目定义，并区分标书要求与设计值。

所有业务object为封闭对象，全部列出的属性必填，oneOf按对应分支执行；引用展开对应定义。ManagementUpdateParams是API合并片段，闭合限制在最终Request执行。默认值是界面初始化值，不是接收端省略字段后的自动补值。REQUIRED_EXPLICIT_VALUE/REQUIRED_CONTENT/REQUIRED_CONTENT_SHA256表示值须显式提供或从实际资源计算，不代表未定义字段。

范围包含两端。JSON number为有限IEEE754 double；64位时间/修订号用十进制字符串并检查uint64实际上限。未知键、错误类型、未允许的null、缺失、越界一律拒绝。'-'表示标识、编码数据或标签等非物理量；1为无量纲，model_step=1ms，byte=字节。

本表覆盖1409行字段/引用/分支记录（不是独立物理信号数量）及97条模型路径。时序、状态与跨字段约束必须同时遵守主契约；管理API其余25命令字段参见v0.3 API Schema及v0.2字段索引中保持不变的元数据部分。

## Identity

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `run_id` | string | 是 | 1..128 chars | - | "item-01" | - |
| `source_id` | string | 是 | 1..128 chars | - | "item-01" | - |
| `vehicle_id` | string | 是 | 1..128 chars | - | "vehicle-01" | - |
| `scenario_id` | string | 是 | 1..128 chars | - | "item-01" | - |
| `model_id` | string | 是 | quadrotor_hil / multirotor_6_hil / fixed_wing_hil | - | "quadrotor_hil" | - |
| `definition_version` | const | 是 | "HIL-ICD-1.0" | - | "HIL-ICD-1.0" | - |

## Header

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `session_id` | integer | 是 | 0..4294967295 | 1 | 0 | - |
| `sequence` | integer | 是 | 1..4294967295 | 1 | 1 | - |
| `target_step` | integer | 是 | 0..4294967295 | model_step | 0 | - |
| `transaction_id` | integer | 是 | 1..4294967295 | 1 | 1 | - |
| `valid_for_ms` | integer | 是 | 1..1000 | ms | 100 | - |

## SessionOpen

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `identity` | ref:Identity | 是 | 见引用定义 | 见引用 | 见引用 | - |
| `roles` | array | 是 | 1..3 items | - | ["STIMULUS"] | - |
| `roles[]` | string | 是 | STIMULUS / CONTROLLER / OBSERVER | - | "STIMULUS" | - |
| `baseline_sha256` | string | 是 | ^[0-9a-f]{64}$ | - | REQUIRED_CONTENT_SHA256 | - |
| `nonce_hex` | string | 是 | ^[0-9a-f]{32}$ | - | FRESH_128_BIT_NONCE | - |
| `requested_lease_ms` | integer | 是 | 500..5000 | ms | 1000 | - |

## Heartbeat

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `last_rx_sequence` | integer | 是 | 0..4294967295 | 1 | 0 | - |
| `sender_step` | integer | 是 | 0..4294967295 | model_step | 0 | - |

## Origin

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `latitude_deg` | number | 是 | -85..85 | deg | 0 | - |
| `longitude_deg` | number | 是 | -180..180 | deg | 0 | - |
| `height_ellipsoid_m` | number | 是 | -500..10000 | m | 0 | - |
| `geoid_separation_m` | number | 是 | -120..120 | m | 0 | - |
| `horizontal_datum` | const | 是 | "WGS84" | - | "WGS84" | - |
| `height_datum` | const | 是 | "ELLIPSOID" | - | "ELLIPSOID" | - |
| `frame` | const | 是 | "NED" | - | "NED" | - |
| `body_frame` | const | 是 | "FRD" | - | "FRD" | - |

## LocalPoint

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `north_m` | number | 是 | -100000..100000 | m | 0 | - |
| `east_m` | number | 是 | -100000..100000 | m | 0 | - |
| `down_m` | number | 是 | -10000..1000 | m | 0 | - |

## GeoPoint

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `latitude_deg` | number | 是 | -85..85 | deg | 0 | - |
| `longitude_deg` | number | 是 | -180..180 | deg | 0 | - |
| `height_m` | number | 是 | -500..10000 | m | 0 | - |
| `height_datum` | string | 是 | ELLIPSOID / MSL / AGL | - | "ELLIPSOID" | - |

## Quaternion

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `q_w` | number | 是 | -1..1 | 1 | 1 | - |
| `q_x` | number | 是 | -1..1 | 1 | 0 | - |
| `q_y` | number | 是 | -1..1 | 1 | 0 | - |
| `q_z` | number | 是 | -1..1 | 1 | 0 | - |

## InitialState

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `position` | ref:LocalPoint | 是 | 见引用定义 | 见引用 | 见引用 | - |
| `velocity_n_mps` | number | 是 | -200..200 | m/s | 0 | - |
| `velocity_e_mps` | number | 是 | -200..200 | m/s | 0 | - |
| `velocity_d_mps` | number | 是 | -100..100 | m/s | 0 | - |
| `orientation` | ref:Quaternion | 是 | 见引用定义 | 见引用 | 见引用 | - |
| `p_radps` | number | 是 | -20..20 | rad/s | 0 | - |
| `q_radps` | number | 是 | -20..20 | rad/s | 0 | - |
| `r_radps` | number | 是 | -20..20 | rad/s | 0 | - |
| `airborne` | boolean | 是 | - | bool | false | - |

## RunConfigure

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `model_id` | string | 是 | quadrotor_hil / multirotor_6_hil / fixed_wing_hil | - | "quadrotor_hil" | - |
| `step_us` | const | 是 | 1000 | - | 1000 | - |
| `communication_cycle_ms` | const | 是 | 80 | - | 80 | - |
| `origin` | ref:Origin | 是 | 见引用定义 | 见引用 | 见引用 | - |
| `initial_state` | ref:InitialState | 是 | 见引用定义 | 见引用 | 见引用 | - |
| `random_seed` | integer | 是 | 1..4294967295 | 1 | 1 | - |
| `active_channels` | array | 是 | 1..56 items | - | ["ETH_0"] | - |
| `active_channels[]` | string | 是 | CANFD_0 / CANFD_1 / CANFD_2 / CANFD_3 / CAN_0 / CAN_1 / CAN_2 / CAN_3 / ETH_0 / ETH_1 / ETH_2 / ETH_3 / RS232_0 / RS232_1 / RS232_2 / RS232_3 / RS422_0 / RS422_1 / RS422_2 / RS422_3 / RS422_4 / RS422_5 / RS422_6 / RS422_7 / AD_0 / AD_1 / AD_2 / AD_3 / AD_4 / AD_5 / AD_6 / AD_7 / DA_0 / DA_1 / DA_2 / DA_3 / DA_4 / DA_5 / DA_6 / DA_7 / TTL_0 / TTL_1 / TTL_2 / TTL_3 / TTL_4 / TTL_5 / TTL_6 / TTL_7 / TTL_8 / TTL_9 / TTL_10 / TTL_11 / TTL_12 / TTL_13 / TTL_14 / TTL_15 | - | "CANFD_0" | - |
| `sensor_profile` | ref:SensorConfig | 是 | 见引用定义 | 见引用 | 见引用 | - |
| `terrain_resource_sha256` | string | 是 | ^[0-9a-f]{64}$ | - | REQUIRED_CONTENT_SHA256 | variant-1 |
| `terrain_resource_sha256` | null | 是 | - | - | null | variant-2 |
| `obstacle_resource_sha256` | string | 是 | ^[0-9a-f]{64}$ | - | REQUIRED_CONTENT_SHA256 | variant-1 |
| `obstacle_resource_sha256` | null | 是 | - | - | null | variant-2 |
| `controller` | string | 是 | NONE / DEMO_MISSION / PX4_SITL / PHYSICAL_UUT | - | "NONE" | - |
| `recording` | boolean | 是 | - | bool | true | - |
| `max_duration_steps` | integer | 是 | 1..86400000 | model_step | 600000 | - |
| `initial_inputs` | ref:InitialInputs | 是 | 见引用定义 | 见引用 | 见引用 | - |

## Lifecycle

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `action` | const | 是 | "START" | - | "START" | variant-1 |
| `expected_state` | string | 是 | CONFIGURED / RUNNING / PAUSED / STOPPED | - | "CONFIGURED" | variant-1 |
| `reset_policy` | const | 是 | "NOT_APPLICABLE" | - | "NOT_APPLICABLE" | variant-1 |
| `action` | const | 是 | "PAUSE" | - | "PAUSE" | variant-2 |
| `expected_state` | string | 是 | CONFIGURED / RUNNING / PAUSED / STOPPED | - | "CONFIGURED" | variant-2 |
| `reset_policy` | const | 是 | "NOT_APPLICABLE" | - | "NOT_APPLICABLE" | variant-2 |
| `action` | const | 是 | "RESUME" | - | "RESUME" | variant-3 |
| `expected_state` | string | 是 | CONFIGURED / RUNNING / PAUSED / STOPPED | - | "CONFIGURED" | variant-3 |
| `reset_policy` | const | 是 | "NOT_APPLICABLE" | - | "NOT_APPLICABLE" | variant-3 |
| `action` | const | 是 | "STOP" | - | "STOP" | variant-4 |
| `expected_state` | string | 是 | CONFIGURED / RUNNING / PAUSED / STOPPED | - | "CONFIGURED" | variant-4 |
| `reset_policy` | const | 是 | "NOT_APPLICABLE" | - | "NOT_APPLICABLE" | variant-4 |
| `action` | const | 是 | "RESET" | - | "RESET" | variant-5 |
| `expected_state` | string | 是 | CONFIGURED / RUNNING / PAUSED / STOPPED | - | "CONFIGURED" | variant-5 |
| `reset_policy` | const | 是 | "NEW_SESSION_RESTORE_INITIAL" | - | "NEW_SESSION_RESTORE_INITIAL" | variant-5 |
| `action` | const | 是 | "STEP" | - | "STEP" | variant-6 |
| `expected_state` | const | 是 | "PAUSED" | - | "PAUSED" | variant-6 |
| `reset_policy` | const | 是 | "NOT_APPLICABLE" | - | "NOT_APPLICABLE" | variant-6 |
| `step_count` | integer | 是 | 1..1000 | model_step | 1 | variant-6 |

## ControlOwner

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `source` | string | 是 | NONE / DEMO_MISSION / PX4_SITL / PHYSICAL_UUT | - | "NONE" | - |
| `role` | string | 是 | STIMULUS / CONTROLLER | - | "STIMULUS" | - |
| `mode` | string | 是 | MANUAL / AUTO | - | "MANUAL" | - |
| `lease_ms` | const | 是 | 100 | - | 100 | - |
| `transfer_policy` | const | 是 | "PAUSED_SAFE_VALUES_FIRST" | - | "PAUSED_SAFE_VALUES_FIRST" | - |
| `input_lane` | string | 是 | INTERNAL_CONTROLLER / FLIGHT_CONTROL / ACTUATOR | - | "INTERNAL_CONTROLLER" | - |

## FlightQuad

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `motor_command` | array | 是 | 4..4 items | - | [0,0,0,0] | - |
| `motor_command[]` | number | 是 | 0..1 | 1 | 0 | - |

## FlightHex

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `motor_command` | array | 是 | 6..6 items | - | [0,0,0,0,0,0] | - |
| `motor_command[]` | number | 是 | 0..1 | 1 | 0 | - |

## FlightFixed

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `throttle` | number | 是 | 0..1 | 1 | 0 | - |
| `roll_cmd` | number | 是 | -1..1 | 1 | 0 | - |
| `pitch_cmd` | number | 是 | -1..1 | 1 | 0 | - |
| `yaw_cmd` | number | 是 | -1..1 | 1 | 0 | - |

## Environment

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `wind_n_mps` | number | 是 | -50..50 | m/s | 0 | - |
| `wind_e_mps` | number | 是 | -50..50 | m/s | 0 | - |
| `wind_d_mps` | number | 是 | -50..50 | m/s | 0 | - |
| `pressure_pa` | number | 是 | 1000..120000 | Pa | 101325 | - |
| `temperature_k` | number | 是 | 150..350 | K | 288.15 | - |
| `ground_height_m` | number | 是 | -1000..10000 | m | 0 | - |

## FaultQuad

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `gps_bias_n_m` | number | 是 | -1000..1000 | m | 0 | - |
| `gps_bias_e_m` | number | 是 | -1000..1000 | m | 0 | - |
| `gps_bias_d_m` | number | 是 | -1000..1000 | m | 0 | - |
| `imu_bias_p_radps` | number | 是 | -10..10 | rad/s | 0 | - |
| `imu_bias_q_radps` | number | 是 | -10..10 | rad/s | 0 | - |
| `imu_bias_r_radps` | number | 是 | -10..10 | rad/s | 0 | - |
| `motor_1_failed` | boolean | 是 | - | bool | false | - |
| `motor_2_failed` | boolean | 是 | - | bool | false | - |
| `motor_3_failed` | boolean | 是 | - | bool | false | - |
| `motor_4_failed` | boolean | 是 | - | bool | false | - |
| `command_delay_ms` | number | 是 | 0..1000 | ms | 0 | - |
| `sensor_delay_ms` | number | 是 | 0..1000 | ms | 0 | - |
| `packet_loss_ratio` | number | 是 | 0..1 | 1 | 0 | - |

## FaultHex

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `gps_bias_n_m` | number | 是 | -1000..1000 | m | 0 | - |
| `gps_bias_e_m` | number | 是 | -1000..1000 | m | 0 | - |
| `gps_bias_d_m` | number | 是 | -1000..1000 | m | 0 | - |
| `imu_bias_p_radps` | number | 是 | -10..10 | rad/s | 0 | - |
| `imu_bias_q_radps` | number | 是 | -10..10 | rad/s | 0 | - |
| `imu_bias_r_radps` | number | 是 | -10..10 | rad/s | 0 | - |
| `motor_1_failed` | boolean | 是 | - | bool | false | - |
| `motor_2_failed` | boolean | 是 | - | bool | false | - |
| `motor_3_failed` | boolean | 是 | - | bool | false | - |
| `motor_4_failed` | boolean | 是 | - | bool | false | - |
| `command_delay_ms` | number | 是 | 0..1000 | ms | 0 | - |
| `sensor_delay_ms` | number | 是 | 0..1000 | ms | 0 | - |
| `packet_loss_ratio` | number | 是 | 0..1 | 1 | 0 | - |
| `motor_5_failed` | boolean | 是 | - | bool | false | - |
| `motor_6_failed` | boolean | 是 | - | bool | false | - |

## FaultFixed

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `gps_bias_n_m` | number | 是 | -1000..1000 | m | 0 | - |
| `gps_bias_e_m` | number | 是 | -1000..1000 | m | 0 | - |
| `gps_bias_d_m` | number | 是 | -1000..1000 | m | 0 | - |
| `imu_bias_p_radps` | number | 是 | -10..10 | rad/s | 0 | - |
| `imu_bias_q_radps` | number | 是 | -10..10 | rad/s | 0 | - |
| `imu_bias_r_radps` | number | 是 | -10..10 | rad/s | 0 | - |
| `motor_1_failed` | boolean | 是 | - | bool | false | - |
| `motor_2_failed` | boolean | 是 | - | bool | false | - |
| `motor_3_failed` | boolean | 是 | - | bool | false | - |
| `motor_4_failed` | boolean | 是 | - | bool | false | - |
| `command_delay_ms` | number | 是 | 0..1000 | ms | 0 | - |
| `sensor_delay_ms` | number | 是 | 0..1000 | ms | 0 | - |
| `packet_loss_ratio` | number | 是 | 0..1 | 1 | 0 | - |

## ActuatorQuad

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `motor_command` | array | 是 | 4..4 items | - | [0,0,0,0] | - |
| `motor_command[]` | number | 是 | 0..1 | 1 | 0 | - |

## ActuatorHex

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `motor_command` | array | 是 | 6..6 items | - | [0,0,0,0,0,0] | - |
| `motor_command[]` | number | 是 | 0..1 | 1 | 0 | - |

## ActuatorFixed

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `throttle` | number | 是 | 0..1 | 1 | 0 | - |
| `roll_cmd` | number | 是 | -1..1 | 1 | 0 | - |
| `pitch_cmd` | number | 是 | -1..1 | 1 | 0 | - |
| `yaw_cmd` | number | 是 | -1..1 | 1 | 0 | - |

## TuneQuad

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `mass_kg` | number | 是 | 0.2..25 | kg | 1.5 | - |
| `inertia_xx_kgm2` | number | 是 | 0.001..2 | kg*m2 | 0.029 | - |
| `inertia_yy_kgm2` | number | 是 | 0.001..2 | kg*m2 | 0.029 | - |
| `inertia_zz_kgm2` | number | 是 | 0.001..4 | kg*m2 | 0.055 | - |
| `thrust_coefficient_n` | number | 是 | 0.5..20 | N | 4.2 | - |
| `moment_coefficient_nm` | number | 是 | 0.001..2 | N*m | 0.08 | - |
| `linear_drag_ns_m` | number | 是 | 0..20 | N*s/m | 0.25 | - |
| `angular_drag_nms` | number | 是 | 0..5 | N*m*s | 0.02 | - |
| `wind_n_bias_mps` | number | 是 | -30..30 | m/s | 0 | - |
| `wind_e_bias_mps` | number | 是 | -30..30 | m/s | 0 | - |
| `wind_d_bias_mps` | number | 是 | -30..30 | m/s | 0 | - |
| `motor_efficiency` | number | 是 | 0.2..1.2 | 1 | 1 | - |

## TuneHex

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `mass_kg` | number | 是 | 0.1..100 | kg | 2 | - |
| `inertia_xx_kgm2` | number | 是 | 0.0001..10 | kg*m2 | 0.03 | - |
| `inertia_yy_kgm2` | number | 是 | 0.0001..10 | kg*m2 | 0.03 | - |
| `inertia_zz_kgm2` | number | 是 | 0.0001..10 | kg*m2 | 0.05 | - |
| `linear_drag_ns_m` | number | 是 | 0..100 | N*s/m | 0.2 | - |
| `angular_drag_nms` | number | 是 | 0..100 | N*m*s | 0.02 | - |
| `wind_n_bias_mps` | number | 是 | -50..50 | m/s | 0 | - |
| `wind_e_bias_mps` | number | 是 | -50..50 | m/s | 0 | - |
| `wind_d_bias_mps` | number | 是 | -50..50 | m/s | 0 | - |
| `thrust_coefficient_n` | number | 是 | 0.01..100 | N | 4.2 | - |

## TuneFixed

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `mass_kg` | number | 是 | 0.1..100 | kg | 2 | - |
| `inertia_xx_kgm2` | number | 是 | 0.0001..10 | kg*m2 | 0.03 | - |
| `inertia_yy_kgm2` | number | 是 | 0.0001..10 | kg*m2 | 0.03 | - |
| `inertia_zz_kgm2` | number | 是 | 0.0001..10 | kg*m2 | 0.05 | - |
| `linear_drag_ns_m` | number | 是 | 0..100 | N*s/m | 0.2 | - |
| `angular_drag_nms` | number | 是 | 0..100 | N*m*s | 0.02 | - |
| `wind_n_bias_mps` | number | 是 | -50..50 | m/s | 0 | - |
| `wind_e_bias_mps` | number | 是 | -50..50 | m/s | 0 | - |
| `wind_d_bias_mps` | number | 是 | -50..50 | m/s | 0 | - |
| `wing_area_m2` | number | 是 | 0.01..20 | m2 | 0.25 | - |

## WaypointAction

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `type` | const | 是 | "NONE" | - | "NONE" | variant-1 |
| `type` | const | 是 | "PHOTO" | - | "PHOTO" | variant-2 |
| `pitch_deg` | number | 是 | -90..90 | deg | -45 | variant-2 |
| `yaw_deg` | number | 是 | -180..180 | deg | 0 | variant-2 |
| `count` | integer | 是 | 1..100 | 1 | 1 | variant-2 |
| `interval_ms` | integer | 是 | 1..60000 | ms | 1000 | variant-2 |
| `type` | const | 是 | "MONITOR" | - | "MONITOR" | variant-3 |
| `duration_ms` | integer | 是 | 1..3600000 | ms | 1000 | variant-3 |
| `target_id` | string | 是 | 1..128 chars | - | "item-01" | variant-3 |

## Waypoint

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `waypoint_id` | string | 是 | 1..128 chars | - | "item-01" | - |
| `order` | integer | 是 | 0..49 | 1 | 0 | - |
| `coordinate` | ref:GeoPoint | 是 | 见引用定义 | 见引用 | 见引用 | - |
| `speed_mps` | number | 是 | 0.1..100 | m/s | 5 | - |
| `dwell_ms` | integer | 是 | 0..3600000 | ms | 0 | - |
| `acceptance_radius_m` | number | 是 | 0.1..100 | m | 2 | - |
| `action` | ref:WaypointAction | 是 | 见引用定义 | 见引用 | 见引用 | - |

## RouteGeometry

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `type` | const | 是 | "LINE" | - | "LINE" | variant-1 |
| `start` | ref:GeoPoint | 是 | 见引用定义 | 见引用 | 见引用 | variant-1 |
| `end` | ref:GeoPoint | 是 | 见引用定义 | 见引用 | 见引用 | variant-1 |
| `type` | const | 是 | "CIRCLE" | - | "CIRCLE" | variant-2 |
| `center` | ref:GeoPoint | 是 | 见引用定义 | 见引用 | 见引用 | variant-2 |
| `radius_m` | number | 是 | 1..10000 | m | 100 | variant-2 |
| `clockwise` | boolean | 是 | - | bool | true | variant-2 |
| `laps` | integer | 是 | 1..100 | 1 | 1 | variant-2 |
| `type` | const | 是 | "POLYGON" | - | "POLYGON" | variant-3 |
| `vertices` | array | 是 | 3..50 items | - | REQUIRED_CONTENT | variant-3 |
| `vertices[]` | ref:GeoPoint | 是 | 见引用定义 | 见引用 | 见引用 | variant-3 |
| `closed` | boolean | 是 | - | bool | true | variant-3 |
| `type` | const | 是 | "FREE_CURVE" | - | "FREE_CURVE" | variant-4 |
| `control_points` | array | 是 | 2..50 items | - | REQUIRED_CONTENT | variant-4 |
| `control_points[]` | ref:GeoPoint | 是 | 见引用定义 | 见引用 | 见引用 | variant-4 |
| `interpolation` | const | 是 | "CATMULL_ROM_CENTRIPETAL" | - | "CATMULL_ROM_CENTRIPETAL" | variant-4 |
| `sampling_distance_m` | number | 是 | 0.1..100 | m | 5 | variant-4 |

## TaskDetails

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `type` | const | 是 | "INSPECTION" | - | "INSPECTION" | variant-1 |
| `interval_ms` | integer | 是 | 1..3600000 | ms | 1000 | variant-1 |
| `inspection_count` | integer | 是 | 1..10000 | 1 | 1 | variant-1 |
| `type` | const | 是 | "PHOTO" | - | "PHOTO" | variant-2 |
| `pitch_deg` | number | 是 | -90..90 | deg | -45 | variant-2 |
| `yaw_deg` | number | 是 | -180..180 | deg | 0 | variant-2 |
| `capture_at_step` | integer | 是 | 0..4294967295 | model_step | 0 | variant-2 |
| `photo_count` | integer | 是 | 1..10000 | 1 | 1 | variant-2 |
| `type` | const | 是 | "MONITOR" | - | "MONITOR" | variant-3 |
| `duration_ms` | integer | 是 | 1..86400000 | ms | 60000 | variant-3 |
| `sample_period_ms` | integer | 是 | 1..10000 | ms | 100 | variant-3 |
| `type` | const | 是 | "CRUISE" | - | "CRUISE" | variant-4 |
| `laps` | integer | 是 | 1..100 | 1 | 1 | variant-4 |
| `cruise_speed_mps` | number | 是 | 0.1..100 | m/s | 5 | variant-4 |

## Task

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `task_id` | string | 是 | 1..128 chars | - | "item-01" | - |
| `name` | string | 是 | 1..256 chars | - | "task-01" | - |
| `details` | ref:TaskDetails | 是 | 见引用定义 | 见引用 | 见引用 | - |
| `priority` | integer | 是 | 0..255 | 1 | 100 | - |
| `start_step` | integer | 是 | 0..4294967295 | model_step | 0 | - |
| `end_step` | integer | 是 | 1..4294967295 | model_step | 600000 | - |
| `area` | array | 是 | 3..50 items | - | REQUIRED_CONTENT | - |
| `area[]` | ref:GeoPoint | 是 | 见引用定义 | 见引用 | 见引用 | - |
| `target_ids` | array | 是 | 0..100 items | - | [] | - |
| `target_ids[]` | string | 是 | 1..128 chars | - | "item-01" | - |
| `depends_on` | array | 是 | 0..100 items | - | [] | - |
| `depends_on[]` | string | 是 | 1..128 chars | - | "item-01" | - |
| `route_id` | string | 是 | 1..128 chars | - | "item-01" | - |
| `log_id` | string | 是 | 1..128 chars | - | "item-01" | - |
| `timeout_ms` | integer | 是 | 1..86400000 | ms | 600000 | - |

## MissionLoad

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `mission_id` | string | 是 | 1..128 chars | - | "item-01" | - |
| `revision` | integer | 是 | 1..4294967295 | 1 | 1 | - |
| `route_id` | string | 是 | 1..128 chars | - | "item-01" | - |
| `route_name` | string | 是 | 1..256 chars | - | "route-01" | - |
| `geometry` | ref:RouteGeometry | 是 | 见引用定义 | 见引用 | 见引用 | - |
| `waypoints` | array | 是 | 1..50 items | - | REQUIRED_CONTENT | - |
| `waypoints[]` | ref:Waypoint | 是 | 见引用定义 | 见引用 | 见引用 | - |
| `landing_point` | ref:GeoPoint | 是 | 见引用定义 | 见引用 | 见引用 | - |
| `takeoff_height_agl_m` | number | 是 | 1..1000 | m | 10 | - |
| `completion_radius_m` | number | 是 | 0.1..100 | m | 2 | - |
| `tasks` | array | 是 | 0..100 items | - | [] | - |
| `tasks[]` | ref:Task | 是 | 见引用定义 | 见引用 | 见引用 | - |
| `execute_from_index` | integer | 是 | 0..49 | 1 | 0 | - |
| `controller` | string | 是 | DEMO_MISSION / PX4_SITL / PHYSICAL_UUT | - | "DEMO_MISSION" | - |
| `failsafe` | const | 是 | "HOLD_THEN_LAND" | - | "HOLD_THEN_LAND" | - |
| `hold_timeout_ms` | integer | 是 | 100..60000 | ms | 1000 | - |

## MissionControl

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `mission_id` | string | 是 | 1..128 chars | - | "item-01" | - |
| `action` | string | 是 | START / PAUSE / RESUME / ABORT | - | "START" | - |
| `expected_revision` | integer | 是 | 1..4294967295 | 1 | 1 | - |
| `abort_policy` | string | 是 | HOLD / LAND | - | "LAND" | - |

## FlightCommand

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `action` | const | 是 | "TAKEOFF" | - | "TAKEOFF" | variant-1 |
| `height_agl_m` | number | 是 | 1..1000 | m | 10 | variant-1 |
| `vertical_speed_mps` | number | 是 | 0.1..10 | m/s | 2 | variant-1 |
| `action` | const | 是 | "LAND" | - | "LAND" | variant-2 |
| `landing_point` | ref:GeoPoint | 是 | 见引用定义 | 见引用 | 见引用 | variant-2 |
| `descent_speed_mps` | number | 是 | 0.1..5 | m/s | 1 | variant-2 |
| `action` | const | 是 | "HOVER" | - | "HOVER" | variant-3 |
| `position` | ref:GeoPoint | 是 | 见引用定义 | 见引用 | 见引用 | variant-3 |
| `duration_ms` | integer | 是 | 1..3600000 | ms | 10000 | variant-3 |
| `action` | const | 是 | "ACCELERATE" | - | "ACCELERATE" | variant-4 |
| `target_speed_mps` | number | 是 | 0.1..100 | m/s | 10 | variant-4 |
| `acceleration_mps2` | number | 是 | 0.1..10 | m/s2 | 1 | variant-4 |
| `action` | const | 是 | "DECELERATE" | - | "DECELERATE" | variant-5 |
| `target_speed_mps` | number | 是 | 0..100 | m/s | 0 | variant-5 |
| `deceleration_mps2` | number | 是 | 0.1..10 | m/s2 | 1 | variant-5 |
| `action` | const | 是 | "ATTITUDE" | - | "ATTITUDE" | variant-6 |
| `roll_rad` | number | 是 | -0.78..0.78 | rad | 0 | variant-6 |
| `pitch_rad` | number | 是 | -0.78..0.78 | rad | 0 | variant-6 |
| `yaw_rad` | number | 是 | -3.141592653589793..3.141592653589793 | rad | 0 | variant-6 |
| `duration_ms` | integer | 是 | 1..60000 | ms | 1000 | variant-6 |
| `action` | const | 是 | "SET_MODE" | - | "SET_MODE" | variant-7 |
| `mode` | string | 是 | MANUAL / AUTO | - | "MANUAL" | variant-7 |
| `action` | const | 是 | "SET_TARGET" | - | "SET_TARGET" | variant-8 |
| `target_position` | ref:GeoPoint | 是 | 见引用定义 | 见引用 | 见引用 | variant-8 |
| `altitude_agl_m` | number | 是 | 0..1000 | m | 10 | variant-8 |
| `speed_mps` | number | 是 | 0..100 | m/s | 5 | variant-8 |
| `heading_rad` | number | 是 | -3.141592653589793..3.141592653589793 | rad | 0 | variant-8 |
| `climb_rate_mps` | number | 是 | -10..10 | m/s | 0 | variant-8 |

## Target

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `target_id` | string | 是 | 1..128 chars | - | "item-01" | - |
| `name` | string | 是 | 1..256 chars | - | "target-01" | - |
| `kind` | string | 是 | AIR / GROUND / SURFACE | - | "AIR" | - |
| `affiliation` | string | 是 | FRIENDLY / HOSTILE / NEUTRAL / UNKNOWN | - | "FRIENDLY" | - |
| `position` | ref:GeoPoint | 是 | 见引用定义 | 见引用 | 见引用 | - |
| `velocity_n_mps` | number | 是 | -500..500 | m/s | 0 | - |
| `velocity_e_mps` | number | 是 | -500..500 | m/s | 0 | - |
| `velocity_d_mps` | number | 是 | -100..100 | m/s | 0 | - |
| `heading_rad` | number | 是 | -3.141592653589793..3.141592653589793 | rad | 0 | - |
| `size_m` | number | 是 | 0.1..10000 | m | 1 | - |
| `rcs_m2` | number | 是 | 0..100000 | m2 | 1 | - |
| `active` | boolean | 是 | - | bool | true | - |
| `visible` | boolean | 是 | - | bool | true | - |

## Targets

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `revision` | integer | 是 | 1..4294967295 | 1 | 1 | - |
| `operation` | string | 是 | REPLACE_ALL / UPSERT / REMOVE | - | "REPLACE_ALL" | - |
| `targets` | array | 是 | 0..100 items | - | [] | - |
| `targets[]` | ref:Target | 是 | 见引用定义 | 见引用 | 见引用 | - |
| `remove_ids` | array | 是 | 0..100 items | - | [] | - |
| `remove_ids[]` | string | 是 | 1..128 chars | - | "item-01" | - |

## EnvironmentExt

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `air_density_kg_m3` | number | 是 | 0.01..2 | kg/m3 | 1.225 | - |
| `humidity_ratio` | number | 是 | 0..1 | 1 | 0.5 | - |
| `rain_mm_h` | number | 是 | 0..300 | mm/h | 0 | - |
| `visibility_m` | number | 是 | 1..100000 | m | 10000 | - |
| `turbulence_sigma_mps` | number | 是 | 0..20 | m/s | 0 | - |
| `turbulence_length_m` | number | 是 | 1..10000 | m | 100 | - |
| `gust_n_mps` | number | 是 | -50..50 | m/s | 0 | - |
| `gust_e_mps` | number | 是 | -50..50 | m/s | 0 | - |
| `gust_d_mps` | number | 是 | -50..50 | m/s | 0 | - |
| `gravity_mps2` | number | 是 | 9..10 | m/s2 | 9.80665 | - |
| `solar_irradiance_w_m2` | number | 是 | 0..1500 | W/m2 | 0 | - |
| `illumination_lux` | number | 是 | 0..200000 | lux | 10000 | - |
| `density_mode` | string | 是 | IDEAL_GAS / EXPLICIT | - | "IDEAL_GAS" | - |

## SystemStimulus

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `engine_load_ratio` | number | 是 | 0..1 | 1 | 0 | - |
| `fuel_supply_ratio` | number | 是 | 0..1 | 1 | 1 | - |
| `hydraulic_supply_pa` | number | 是 | 0..40000000 | Pa | 0 | - |
| `electrical_supply_v` | number | 是 | 0..60 | V | 28 | - |
| `avionics_powered` | boolean | 是 | - | bool | true | - |
| `payload_mass_kg` | number | 是 | 0..100 | kg | 0 | - |
| `payload_force_frd_n` | array | 是 | 3..3 items | - | [0,0,0] | - |
| `payload_force_frd_n[]` | number | 是 | -10000..10000 | N | 0 | - |
| `payload_moment_frd_nm` | array | 是 | 3..3 items | - | [0,0,0] | - |
| `payload_moment_frd_nm[]` | number | 是 | -1000..1000 | N*m | 0 | - |
| `engine_fault` | boolean | 是 | - | bool | false | - |
| `fuel_leak_kg_s` | number | 是 | 0..10 | kg/s | 0 | - |
| `hydraulic_leak_ratio` | number | 是 | 0..1 | 1 | 0 | - |
| `electrical_fault` | string | 是 | NONE / OPEN / SHORT / UNDERVOLTAGE | - | "NONE" | - |

## BusFault

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `kind` | const | 是 | "DELAY" | - | "DELAY" | variant-1 |
| `channel_id` | string | 是 | 1..32 chars | - | "CANFD_0" | variant-1 |
| `delay_ms` | integer | 是 | 0..1000 | ms | 10 | variant-1 |
| `duration_ms` | integer | 是 | 1..60000 | ms | 1000 | variant-1 |
| `kind` | const | 是 | "DROP" | - | "DROP" | variant-2 |
| `channel_id` | string | 是 | 1..32 chars | - | "CANFD_0" | variant-2 |
| `probability` | number | 是 | 0..1 | 1 | 0.1 | variant-2 |
| `random_seed` | integer | 是 | 1..4294967295 | 1 | 1 | variant-2 |
| `duration_ms` | integer | 是 | 1..60000 | ms | 1000 | variant-2 |
| `kind` | const | 是 | "DUPLICATE" | - | "DUPLICATE" | variant-3 |
| `channel_id` | string | 是 | 1..32 chars | - | "CANFD_0" | variant-3 |
| `copies` | integer | 是 | 1..10 | 1 | 1 | variant-3 |
| `interval_us` | integer | 是 | 0..1000000 | us | 1000 | variant-3 |
| `duration_ms` | integer | 是 | 1..60000 | ms | 1000 | variant-3 |
| `kind` | const | 是 | "CORRUPT" | - | "CORRUPT" | variant-4 |
| `channel_id` | string | 是 | 1..32 chars | - | "CANFD_0" | variant-4 |
| `byte_offset` | integer | 是 | 0..65535 | 1 | 0 | variant-4 |
| `xor_mask` | integer | 是 | 1..255 | 1 | 1 | variant-4 |
| `duration_ms` | integer | 是 | 1..60000 | ms | 1000 | variant-4 |
| `kind` | const | 是 | "DISCONNECT" | - | "DISCONNECT" | variant-5 |
| `channel_id` | string | 是 | 1..32 chars | - | "CANFD_0" | variant-5 |
| `duration_ms` | integer | 是 | 1..60000 | ms | 1000 | variant-5 |
| `kind` | const | 是 | "TRAFFIC_LOAD" | - | "TRAFFIC_LOAD" | variant-6 |
| `channel_id` | string | 是 | 1..32 chars | - | "ETH_0" | variant-6 |
| `load_ratio` | number | 是 | 0..0.7 | 1 | 0.2 | variant-6 |
| `frame_size_bytes` | integer | 是 | 64..1518 | byte | 128 | variant-6 |
| `duration_ms` | integer | 是 | 1..60000 | ms | 1000 | variant-6 |
| `kind` | const | 是 | "ELECTRICAL" | - | "ELECTRICAL" | variant-7 |
| `channel_id` | string | 是 | 1..32 chars | - | "CANFD_0" | variant-7 |
| `mode` | string | 是 | CAN_H_OPEN / CAN_L_OPEN / CAN_H_L_SHORT / SERIAL_OPEN / SERIAL_SHORT | - | "CAN_H_OPEN" | variant-7 |
| `duration_ms` | integer | 是 | 1..10000 | ms | 1000 | variant-7 |
| `kind` | const | 是 | "CLEAR" | - | "CLEAR" | variant-8 |
| `channel_id` | string | 是 | 1..32 chars | - | "CANFD_0" | variant-8 |
| `kind` | const | 是 | "REORDER" | - | "REORDER" | variant-9 |
| `channel_id` | string | 是 | 1..32 chars | - | "CANFD_0" | variant-9 |
| `window_frames` | integer | 是 | 2..64 | 1 | 2 | variant-9 |
| `window_ms` | integer | 是 | 1..1000 | ms | 20 | variant-9 |
| `duration_ms` | integer | 是 | 1..60000 | ms | 1000 | variant-9 |

## SerialWrite

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `channel_id` | string | 是 | RS232_0 / RS232_1 / RS232_2 / RS232_3 / RS422_0 / RS422_1 / RS422_2 / RS422_3 / RS422_4 / RS422_5 / RS422_6 / RS422_7 | - | "RS232_0" | - |
| `bytes_hex` | string | 是 | ^(?:[0-9a-f]{2}){1,1024}$ | - | "00" | - |
| `receive_timeout_ms` | integer | 是 | 1..10000 | ms | 100 | - |
| `flush_before` | boolean | 是 | - | bool | false | - |

## AnalogWrite

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `values_v` | array | 是 | 8..8 items | - | [0,0,0,0,0,0,0,0] | - |
| `values_v[]` | number | 是 | -10..10 | V | 0 | - |
| `enabled` | array | 是 | 8..8 items | - | [false,false,false,false,false,false,false,false] | - |
| `enabled[]` | boolean | 是 | - | bool | false | - |
| `slew_v_s` | number | 是 | 0.1..1000 | V/s | 10 | - |

## DigitalWrite

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `levels` | array | 是 | 16..16 items | - | [false,false,false,false,false,false,false,false,false,false,false,false,false,false,false,false] | - |
| `levels[]` | boolean | 是 | - | bool | false | - |
| `enabled` | array | 是 | 16..16 items | - | [false,false,false,false,false,false,false,false,false,false,false,false,false,false,false,false] | - |
| `enabled[]` | boolean | 是 | - | bool | false | - |
| `pulse_width_us` | array | 是 | 16..16 items | - | [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0] | - |
| `pulse_width_us[]` | integer | 是 | 0..1000000 | us | 0 | - |

## VideoConfig

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `codec` | const | 是 | "H264" | - | "H264" | variant-1 |
| `width` | const | 是 | 1280 | - | 1280 | variant-1 |
| `height` | const | 是 | 720 | - | 720 | variant-1 |
| `fps_num` | const | 是 | 30 | - | 30 | variant-1 |
| `fps_den` | const | 是 | 1 | - | 1 | variant-1 |
| `pixel_format` | const | 是 | "YUV420P" | - | "YUV420P" | variant-1 |
| `bitrate_bps` | const | 是 | 12000000 | - | 12000000 | variant-1 |
| `gop_frames` | const | 是 | 30 | - | 30 | variant-1 |
| `max_frame_bytes` | const | 是 | 2097152 | - | 2097152 | variant-1 |
| `stream_id` | string | 是 | 1..128 chars | - | "item-01" | variant-1 |
| `resource_sha256` | string | 是 | ^[0-9a-f]{64}$ | - | REQUIRED_CONTENT_SHA256 | variant-1 |
| `trigger` | string | 是 | MANUAL / PERIODIC / EXTERNAL / PHASE / EVENT | - | "MANUAL" | variant-1 |
| `period_ms` | integer | 是 | 1..60000 | ms | 1000 | variant-1 |
| `phase` | string | 是 | ANY / TAKEOFF / FLYING / LANDING / LANDED | - | "ANY" | variant-1 |
| `event_id` | string | 是 | 1..128 chars | - | "item-01" | variant-1 |
| `loop` | boolean | 是 | - | bool | false | variant-1 |
| `stream_numeric_id` | integer | 是 | 1..4294967295 | 1 | 1 | variant-1 |
| `codec` | const | 是 | "H265" | - | "H265" | variant-2 |
| `width` | const | 是 | 1280 | - | 1280 | variant-2 |
| `height` | const | 是 | 720 | - | 720 | variant-2 |
| `fps_num` | const | 是 | 30 | - | 30 | variant-2 |
| `fps_den` | const | 是 | 1 | - | 1 | variant-2 |
| `pixel_format` | const | 是 | "YUV420P" | - | "YUV420P" | variant-2 |
| `bitrate_bps` | const | 是 | 8000000 | - | 8000000 | variant-2 |
| `gop_frames` | const | 是 | 30 | - | 30 | variant-2 |
| `max_frame_bytes` | const | 是 | 2097152 | - | 2097152 | variant-2 |
| `stream_id` | string | 是 | 1..128 chars | - | "item-01" | variant-2 |
| `resource_sha256` | string | 是 | ^[0-9a-f]{64}$ | - | REQUIRED_CONTENT_SHA256 | variant-2 |
| `trigger` | string | 是 | MANUAL / PERIODIC / EXTERNAL / PHASE / EVENT | - | "MANUAL" | variant-2 |
| `period_ms` | integer | 是 | 1..60000 | ms | 1000 | variant-2 |
| `phase` | string | 是 | ANY / TAKEOFF / FLYING / LANDING / LANDED | - | "ANY" | variant-2 |
| `event_id` | string | 是 | 1..128 chars | - | "item-01" | variant-2 |
| `loop` | boolean | 是 | - | bool | false | variant-2 |
| `stream_numeric_id` | integer | 是 | 1..4294967295 | 1 | 1 | variant-2 |
| `codec` | const | 是 | "RAW" | - | "RAW" | variant-3 |
| `width` | const | 是 | 640 | - | 640 | variant-3 |
| `height` | const | 是 | 480 | - | 480 | variant-3 |
| `fps_num` | const | 是 | 30 | - | 30 | variant-3 |
| `fps_den` | const | 是 | 1 | - | 1 | variant-3 |
| `pixel_format` | const | 是 | "BGR24" | - | "BGR24" | variant-3 |
| `bitrate_bps` | const | 是 | 221184000 | - | 221184000 | variant-3 |
| `gop_frames` | const | 是 | 1 | - | 1 | variant-3 |
| `max_frame_bytes` | const | 是 | 921600 | - | 921600 | variant-3 |
| `stream_id` | string | 是 | 1..128 chars | - | "item-01" | variant-3 |
| `resource_sha256` | string | 是 | ^[0-9a-f]{64}$ | - | REQUIRED_CONTENT_SHA256 | variant-3 |
| `trigger` | string | 是 | MANUAL / PERIODIC / EXTERNAL / PHASE / EVENT | - | "MANUAL" | variant-3 |
| `period_ms` | integer | 是 | 1..60000 | ms | 1000 | variant-3 |
| `phase` | string | 是 | ANY / TAKEOFF / FLYING / LANDING / LANDED | - | "ANY" | variant-3 |
| `event_id` | string | 是 | 1..128 chars | - | "item-01" | variant-3 |
| `loop` | boolean | 是 | - | bool | false | variant-3 |
| `stream_numeric_id` | integer | 是 | 1..4294967295 | 1 | 1 | variant-3 |

## VideoControl

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `stream_id` | string | 是 | 1..128 chars | - | "item-01" | - |
| `action` | string | 是 | START / PAUSE / RESUME / STOP / TRIGGER / SEEK | - | "START" | - |
| `frame_index` | integer | 是 | 0..4294967295 | 1 | 0 | - |
| `trigger_id` | string | 是 | 1..128 chars | - | "item-01" | - |
| `sync_mode` | const | 是 | "MODEL_STEP" | - | "MODEL_STEP" | - |
| `late_policy` | const | 是 | "DROP_AND_REPORT" | - | "DROP_AND_REPORT" | - |

## VideoAnnotation

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `stream_id` | string | 是 | 1..128 chars | - | "item-01" | - |
| `frame_index` | integer | 是 | 0..4294967295 | 1 | 0 | - |
| `capture_step` | integer | 是 | 0..4294967295 | model_step | 0 | - |
| `position` | ref:GeoPoint | 是 | 见引用定义 | 见引用 | 见引用 | - |
| `orientation` | ref:Quaternion | 是 | 见引用定义 | 见引用 | 见引用 | - |
| `phase` | string | 是 | TAKEOFF / FLYING / LANDING / LANDED | - | "TAKEOFF" | - |
| `task_id` | string | 是 | 1..128 chars | - | "item-01" | - |
| `target_ids` | array | 是 | 0..100 items | - | [] | - |
| `target_ids[]` | string | 是 | 1..128 chars | - | "item-01" | - |
| `label` | string | 是 | 0..1024 chars | - | "frame-annotation" | - |

## ClockSync

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `nonce` | integer | 是 | 1..4294967295 | 1 | 1 | - |
| `sender_mono_ns` | string | 是 | ^(0\|[1-9][0-9]{0,19})$ | ns | "0" | - |
| `utc_time` | string | 是 | - | - | "2026-10-02T00:00:00Z" | - |
| `model_step` | integer | 是 | 0..4294967295 | model_step | 0 | - |
| `mode` | const | 是 | "TWO_WAY_MEASUREMENT" | - | "TWO_WAY_MEASUREMENT" | - |
| `max_uncertainty_us` | const | 是 | 500 | - | 500 | - |

## ResourceChunk

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `resource_sha256` | string | 是 | ^[0-9a-f]{64}$ | - | REQUIRED_CONTENT_SHA256 | - |
| `resource_kind` | string | 是 | MODEL / VIDEO / TERRAIN / OBSTACLES / MISSION | - | "MODEL" | - |
| `size_bytes` | integer | 是 | 1..4294967295 | byte | 1 | - |
| `offset_bytes` | integer | 是 | 0..4294967295 | byte | 0 | - |
| `chunk_length` | integer | 是 | 1..32768 | 1 | 1 | - |
| `data_base64` | string | 是 | 4..43692 chars | - | "AA==" | - |
| `chunk_sha256` | string | 是 | ^[0-9a-f]{64}$ | - | REQUIRED_CONTENT_SHA256 | - |
| `final` | boolean | 是 | - | bool | false | - |

## Query

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `query` | string | 是 | CAPABILITIES / STATE / TASKS / IO / VIDEO / RECORDS / DIAGNOSTICS | - | "CAPABILITIES" | - |
| `cursor` | string | 是 | 0..128 chars | - | "" | - |
| `limit` | integer | 是 | 1..1000 | 1 | 100 | - |

## RecordControl

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `record_id` | string | 是 | 1..128 chars | - | "item-01" | - |
| `action` | string | 是 | START / STOP / MARK | - | "START" | - |
| `include` | array | 是 | 1..6 items | - | ["WIRE","STATE","EVIDENCE"] | - |
| `include[]` | string | 是 | WIRE / STATE / COMMAND / TASK / VIDEO / EVIDENCE | - | "WIRE" | - |
| `mark` | string | 是 | 0..256 chars | - | "" | - |
| `retention_days` | integer | 是 | 1..3650 | 1 | 90 | - |

## Cleanup

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `clear_model_faults` | const | 是 | true | - | true | - |
| `clear_bus_faults` | const | 是 | true | - | true | - |
| `safe_actuators` | const | 是 | true | - | true | - |
| `stop_video` | const | 是 | true | - | true | - |
| `stop_periodic_senders` | const | 是 | true | - | true | - |
| `stop_replay` | const | 是 | true | - | true | - |
| `release_control` | const | 是 | true | - | true | - |
| `flush_receive_queues` | const | 是 | true | - | true | - |
| `close_session` | const | 是 | true | - | true | - |

## SessionClose

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `reason` | string | 是 | NORMAL / ABORT / RESET / REPLACE_SOURCE | - | "NORMAL" | - |
| `cleanup` | ref:Cleanup | 是 | 见引用定义 | 见引用 | 见引用 | - |

## SensorConfig

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `imu_rate_hz` | const | 是 | 250 | - | 250 | - |
| `gps_rate_hz` | const | 是 | 20 | - | 20 | - |
| `magnetometer_rate_hz` | const | 是 | 50 | - | 50 | - |
| `barometer_rate_hz` | const | 是 | 50 | - | 50 | - |
| `frame` | const | 是 | "FRD" | - | "FRD" | - |
| `imu_accel_noise_sigma_mps2` | number | 是 | 0..20 | m/s2 | 0 | - |
| `imu_gyro_noise_sigma_radps` | number | 是 | 0..2 | rad/s | 0 | - |
| `gps_noise_sigma_m` | number | 是 | 0..100 | m | 0 | - |
| `magnetic_field_ned_ut` | array | 是 | 3..3 items | - | [20,0,45] | - |
| `magnetic_field_ned_ut[]` | number | 是 | -100..100 | uT | 0 | - |
| `barometer_noise_sigma_pa` | number | 是 | 0..1000 | Pa | 0 | - |
| `random_seed` | integer | 是 | 1..4294967295 | 1 | 1 | - |

## PhysicalChannelConfig

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `canfd_nominal_bps` | const | 是 | 500000 | - | 500000 | - |
| `canfd_data_bps` | const | 是 | 2000000 | - | 2000000 | - |
| `can_nominal_bps` | const | 是 | 500000 | - | 500000 | - |
| `can_termination_ohm` | const | 是 | 120 | - | 120 | - |
| `canfd_brs` | const | 是 | true | - | true | - |
| `serial_baud` | const | 是 | 921600 | - | 921600 | - |
| `serial_data_bits` | const | 是 | 8 | - | 8 | - |
| `serial_parity` | const | 是 | "NONE" | - | "NONE" | - |
| `serial_stop_bits` | const | 是 | 2 | - | 2 | - |
| `ethernet_speed_mbps` | const | 是 | 1000 | - | 1000 | - |
| `ttl_level_v` | const | 是 | 3.3 | - | 3.3 | - |
| `analog_range_v` | const | 是 | 10 | - | 10 | - |
| `sync_clock_hz` | const | 是 | 1000 | - | 1000 | - |
| `sync_enable_active` | const | 是 | "HIGH" | - | "HIGH" | - |
| `ttl_directions` | array | 是 | 16..16 items | - | ["INPUT","INPUT","INPUT","INPUT","INPUT","INPUT","INPUT","INPUT","INPUT","INPUT","INPUT","INPUT","INPUT","INPUT","INPUT","INPUT"] | - |
| `ttl_directions[]` | string | 是 | INPUT / OUTPUT | - | "INPUT" | - |
| `ad_calibration` | array | 是 | 8..8 items | - | [{"gain":1,"offset_v":0,"measured":false},{"gain":1,"offset_v":0,"measured":false},{"gain":1,"offset_v":0,"measured":false},{"gain":1,"offset_v":0,"measured":false},{"gain":1,"offset_v":0,"measured":false},{"gain":1,"offset_v":0,"measured":false},{"gain":1,"offset_v":0,"measured":false},{"gain":1,"offset_v":0,"measured":false}] | - |
| `ad_calibration[].gain` | number | 是 | 0.5..2 | 1 | 1 | - |
| `ad_calibration[].offset_v` | number | 是 | -1..1 | V | 0 | - |
| `ad_calibration[].measured` | boolean | 是 | - | bool | false | - |
| `da_calibration` | array | 是 | 8..8 items | - | [{"gain":1,"offset_v":0,"measured":false},{"gain":1,"offset_v":0,"measured":false},{"gain":1,"offset_v":0,"measured":false},{"gain":1,"offset_v":0,"measured":false},{"gain":1,"offset_v":0,"measured":false},{"gain":1,"offset_v":0,"measured":false},{"gain":1,"offset_v":0,"measured":false},{"gain":1,"offset_v":0,"measured":false}] | - |
| `da_calibration[].gain` | number | 是 | 0.5..2 | 1 | 1 | - |
| `da_calibration[].offset_v` | number | 是 | -1..1 | V | 0 | - |
| `da_calibration[].measured` | boolean | 是 | - | bool | false | - |

## Terrain

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `resource_sha256` | string | 是 | ^[0-9a-f]{64}$ | - | REQUIRED_CONTENT_SHA256 | - |
| `height_datum` | const | 是 | "ELLIPSOID" | - | "ELLIPSOID" | - |
| `activate_at_step` | integer | 是 | 0..4294967295 | model_step | 0 | - |
| `outside_grid` | const | 是 | "REJECT_ROUTE" | - | "REJECT_ROUTE" | - |

## Obstacle

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `obstacle_id` | string | 是 | 1..128 chars | - | "item-01" | - |
| `center` | ref:GeoPoint | 是 | 见引用定义 | 见引用 | 见引用 | - |
| `geometry` | string | 是 | CYLINDER / BOX | - | "CYLINDER" | - |
| `radius_m` | number | 是 | 0.1..10000 | m | 1 | - |
| `width_m` | number | 是 | 0.1..10000 | m | 1 | - |
| `length_m` | number | 是 | 0.1..10000 | m | 1 | - |
| `height_m` | number | 是 | 0.1..10000 | m | 1 | - |
| `heading_rad` | number | 是 | -3.141592653589793..3.141592653589793 | rad | 0 | - |
| `clearance_m` | number | 是 | 0..1000 | m | 5 | - |
| `active` | boolean | 是 | - | bool | true | - |

## Obstacles

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `resource_sha256` | string | 是 | ^[0-9a-f]{64}$ | - | REQUIRED_CONTENT_SHA256 | - |
| `revision` | integer | 是 | 1..4294967295 | 1 | 1 | - |
| `activate_at_step` | integer | 是 | 0..4294967295 | model_step | 0 | - |

## VideoFrameMetadata

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `stream_id` | string | 是 | 1..128 chars | - | "item-01" | - |
| `frame_index` | integer | 是 | 0..4294967295 | 1 | 0 | - |
| `pts_us` | string | 是 | ^(0\|[1-9][0-9]{0,19})$ | us | "0" | - |
| `capture_step` | integer | 是 | 0..4294967295 | model_step | 0 | - |
| `resource_sha256` | string | 是 | ^[0-9a-f]{64}$ | - | REQUIRED_CONTENT_SHA256 | - |
| `offset_bytes` | integer | 是 | 0..4294967295 | byte | 0 | - |
| `length_bytes` | integer | 是 | 1..2097152 | byte | 1 | - |
| `frame_sha256` | string | 是 | ^[0-9a-f]{64}$ | - | REQUIRED_CONTENT_SHA256 | - |
| `keyframe` | boolean | 是 | - | bool | true | - |
| `annotation` | ref:VideoAnnotation | 是 | 见引用定义 | 见引用 | 见引用 | - |
| `stream_numeric_id` | integer | 是 | 1..4294967295 | 1 | 1 | - |

## SessionOpened

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `session_id` | integer | 是 | 1..4294967295 | 1 | 1 | - |
| `lease_ms` | integer | 是 | 500..5000 | ms | 1000 | - |
| `receiver_step` | integer | 是 | 0..4294967295 | model_step | 0 | - |
| `baseline_sha256` | string | 是 | ^[0-9a-f]{64}$ | - | REQUIRED_CONTENT_SHA256 | - |
| `accepted_roles` | array | 是 | 1..3 items | - | ["STIMULUS"] | - |
| `accepted_roles[]` | string | 是 | STIMULUS / CONTROLLER / OBSERVER | - | "STIMULUS" | - |
| `capabilities` | ref:Capabilities | 是 | 见引用定义 | 见引用 | 见引用 | - |

## Ack

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `request_sequence` | integer | 是 | 1..4294967295 | 1 | 1 | - |
| `request_message_id` | integer | 是 | 0..65535 | 1 | 1 | - |
| `stage` | string | 是 | RECEIVED / VALIDATED / APPLIED / CONSUMED / FAILED | - | "RECEIVED" | - |
| `error` | string | 是 | OK / SCHEMA / VERSION / HASH / AUTHORIZATION / MODEL / CONTROL_OWNER / RANGE / STATE / STALE_SESSION / DUPLICATE / OUT_OF_ORDER / LATE / EXPIRED / BUFFER_FULL / FRAGMENT / CRC / UNSUPPORTED / TARGET_MISSING / TIMEOUT / BUSINESS_FAILED / SAFETY / RESOURCE / CLOCK_UNSYNC / CAPACITY | - | "OK" | - |
| `applied_step` | integer | 是 | 0..4294967295 | model_step | 0 | - |
| `model_revision` | integer | 是 | 0..4294967295 | 1 | 0 | - |
| `probe_id` | integer | 是 | 0..4294967295 | 1 | 0 | - |

## Status

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `state` | string | 是 | CONFIGURED / RUNNING / PAUSED / STOPPED / FAILED | - | "CONFIGURED" | - |
| `phase` | string | 是 | TAKEOFF / FLYING / LANDING / LANDED | - | "TAKEOFF" | - |
| `control_source` | string | 是 | NONE / DEMO_MISSION / PX4_SITL / PHYSICAL_UUT | - | "NONE" | - |
| `safety_active` | boolean | 是 | - | bool | false | - |
| `model_step` | integer | 是 | 0..4294967295 | model_step | 0 | - |
| `last_applied_sequence` | integer | 是 | 0..4294967295 | 1 | 0 | - |
| `receive_queue_depth` | integer | 是 | 0..4096 | 1 | 0 | - |
| `missed_deadline_count` | integer | 是 | 0..4294967295 | 1 | 0 | - |
| `received_count` | integer | 是 | 0..4294967295 | 1 | 0 | - |
| `rejected_count` | integer | 是 | 0..4294967295 | 1 | 0 | - |
| `applied_count` | integer | 是 | 0..4294967295 | 1 | 0 | - |
| `consumed_count` | integer | 是 | 0..4294967295 | 1 | 0 | - |

## State

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `model_step` | integer | 是 | 0..4294967295 | model_step | 0 | - |
| `position` | ref:LocalPoint | 是 | 见引用定义 | 见引用 | 见引用 | - |
| `vn_mps` | number | 是 | -500..500 | m/s | 0 | - |
| `ve_mps` | number | 是 | -500..500 | m/s | 0 | - |
| `vd_mps` | number | 是 | -500..500 | m/s | 0 | - |
| `orientation` | ref:Quaternion | 是 | 见引用定义 | 见引用 | 见引用 | - |
| `p_radps` | number | 是 | -100..100 | rad/s | 0 | - |
| `q_radps` | number | 是 | -100..100 | rad/s | 0 | - |
| `r_radps` | number | 是 | -100..100 | rad/s | 0 | - |
| `airborne` | boolean | 是 | - | bool | false | - |
| `ax_mps2` | number | 是 | -200..200 | m/s2 | 0 | - |
| `ay_mps2` | number | 是 | -200..200 | m/s2 | 0 | - |
| `az_mps2` | number | 是 | -200..200 | m/s2 | 0 | - |
| `engine_rpm` | number | 是 | 0..100000 | rpm | 0 | variant-1 |
| `engine_rpm` | null | 是 | - | - | null | variant-2 |
| `fuel_remaining_kg` | number | 是 | 0..10000 | kg | 0 | variant-1 |
| `fuel_remaining_kg` | null | 是 | - | - | null | variant-2 |
| `hydraulic_pressure_pa` | number | 是 | 0..40000000 | Pa | 0 | variant-1 |
| `hydraulic_pressure_pa` | null | 是 | - | - | null | variant-2 |
| `electrical_voltage_v` | number | 是 | 0..60 | V | 28 | variant-1 |
| `electrical_voltage_v` | null | 是 | - | - | null | variant-2 |
| `avionics_state` | string | 是 | OK / DEGRADED / FAILED / UNAVAILABLE | - | "UNAVAILABLE" | - |

## Sensors

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `model_step` | integer | 是 | 0..4294967295 | model_step | 0 | - |
| `imu.specific_force_frd_mps2` | array | 是 | 3..3 items | - | [0,0,-9.80665] | - |
| `imu.specific_force_frd_mps2[]` | number | 是 | -200..200 | m/s2 | 0 | - |
| `imu.angular_rate_frd_radps` | array | 是 | 3..3 items | - | [0,0,0] | - |
| `imu.angular_rate_frd_radps[]` | number | 是 | -100..100 | rad/s | 0 | - |
| `imu.valid` | boolean | 是 | - | bool | true | - |
| `imu.sample_step` | integer | 是 | 0..4294967295 | model_step | 0 | - |
| `imu.age_ms` | integer | 是 | 0..100000 | ms | 0 | - |
| `gps.position` | ref:GeoPoint | 是 | 见引用定义 | 见引用 | 见引用 | - |
| `gps.velocity_ned_mps` | array | 是 | 3..3 items | - | [0,0,0] | - |
| `gps.velocity_ned_mps[]` | number | 是 | -500..500 | m/s | 0 | - |
| `gps.fix_type` | string | 是 | NO_FIX / FIX_2D / FIX_3D | - | "FIX_3D" | - |
| `gps.satellites` | integer | 是 | 0..64 | 1 | 12 | - |
| `gps.hdop` | number | 是 | 0.1..99 | 1 | 1 | - |
| `gps.valid` | boolean | 是 | - | bool | true | - |
| `gps.sample_step` | integer | 是 | 0..4294967295 | model_step | 0 | - |
| `gps.age_ms` | integer | 是 | 0..100000 | ms | 0 | - |
| `magnetometer.field_frd_ut` | array | 是 | 3..3 items | - | [20,0,45] | - |
| `magnetometer.field_frd_ut[]` | number | 是 | -100..100 | uT | 0 | - |
| `magnetometer.valid` | boolean | 是 | - | bool | true | - |
| `magnetometer.sample_step` | integer | 是 | 0..4294967295 | model_step | 0 | - |
| `magnetometer.age_ms` | integer | 是 | 0..100000 | ms | 0 | - |
| `barometer.pressure_pa` | number | 是 | 1000..120000 | Pa | 101325 | - |
| `barometer.temperature_k` | number | 是 | 150..350 | K | 288.15 | - |
| `barometer.valid` | boolean | 是 | - | bool | true | - |
| `barometer.sample_step` | integer | 是 | 0..4294967295 | model_step | 0 | - |
| `barometer.age_ms` | integer | 是 | 0..100000 | ms | 0 | - |

## IOStatus

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `model_step` | integer | 是 | 0..4294967295 | model_step | 0 | - |
| `ad_v` | array | 是 | 8..8 items | - | [0,0,0,0,0,0,0,0] | - |
| `ad_v[]` | number | 是 | -10..10 | V | 0 | - |
| `ad_valid` | array | 是 | 8..8 items | - | [false,false,false,false,false,false,false,false] | - |
| `ad_valid[]` | boolean | 是 | - | bool | false | - |
| `da_v` | array | 是 | 8..8 items | - | [0,0,0,0,0,0,0,0] | - |
| `da_v[]` | number | 是 | -10..10 | V | 0 | - |
| `ttl_in` | array | 是 | 16..16 items | - | [false,false,false,false,false,false,false,false,false,false,false,false,false,false,false,false] | - |
| `ttl_in[]` | boolean | 是 | - | bool | false | - |
| `ttl_out` | array | 是 | 16..16 items | - | [false,false,false,false,false,false,false,false,false,false,false,false,false,false,false,false] | - |
| `ttl_out[]` | boolean | 是 | - | bool | false | - |
| `serial_channel` | string | 是 | 1..32 chars | - | "RS232_0" | - |
| `serial_rx_hex` | string | 是 | ^(?:[0-9a-f]{2}){0,1024}$ | - | "" | - |

## VideoStatus

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `stream_id` | string | 是 | 1..128 chars | - | "item-01" | - |
| `state` | string | 是 | READY / RUNNING / PAUSED / STOPPED / FAILED | - | "READY" | - |
| `last_received_frame` | integer | 是 | 0..4294967295 | 1 | 0 | - |
| `last_consumed_frame` | integer | 是 | 0..4294967295 | 1 | 0 | - |
| `model_step` | integer | 是 | 0..4294967295 | model_step | 0 | - |
| `dropped_frames` | integer | 是 | 0..4294967295 | 1 | 0 | - |
| `pts_error_us` | integer | 是 | -10000000..10000000 | us | 0 | - |
| `decoder_queue_depth` | integer | 是 | 0..4 | 1 | 0 | - |
| `error` | string | 是 | OK / SCHEMA / VERSION / HASH / AUTHORIZATION / MODEL / CONTROL_OWNER / RANGE / STATE / STALE_SESSION / DUPLICATE / OUT_OF_ORDER / LATE / EXPIRED / BUFFER_FULL / FRAGMENT / CRC / UNSUPPORTED / TARGET_MISSING / TIMEOUT / BUSINESS_FAILED / SAFETY / RESOURCE / CLOCK_UNSYNC / CAPACITY | - | "OK" | - |

## TaskStatus

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `mission_id` | string | 是 | 1..128 chars | - | "item-01" | - |
| `task_id` | string | 是 | 1..128 chars | - | "item-01" | - |
| `route_id` | string | 是 | 1..128 chars | - | "item-01" | - |
| `waypoint_index` | integer | 是 | 0..50 | 1 | 0 | - |
| `state` | string | 是 | QUEUED / ACTIVE / PAUSED / COMPLETED / ABORTED / FAILED | - | "QUEUED" | - |
| `progress_ratio` | number | 是 | 0..1 | 1 | 0 | - |
| `model_step` | integer | 是 | 0..4294967295 | model_step | 0 | - |
| `log_id` | string | 是 | 1..128 chars | - | "item-01" | - |
| `error` | string | 是 | OK / SCHEMA / VERSION / HASH / AUTHORIZATION / MODEL / CONTROL_OWNER / RANGE / STATE / STALE_SESSION / DUPLICATE / OUT_OF_ORDER / LATE / EXPIRED / BUFFER_FULL / FRAGMENT / CRC / UNSUPPORTED / TARGET_MISSING / TIMEOUT / BUSINESS_FAILED / SAFETY / RESOURCE / CLOCK_UNSYNC / CAPACITY | - | "OK" | - |

## RecordStatus

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `record_id` | string | 是 | 1..128 chars | - | "item-01" | - |
| `state` | string | 是 | RECORDING / FINALIZED / FAILED | - | "RECORDING" | - |
| `start_step` | integer | 是 | 0..4294967295 | model_step | 0 | - |
| `end_step` | integer | 是 | 0..4294967295 | model_step | 0 | - |
| `size_bytes` | integer | 是 | 0..9007199254740991 | byte | 0 | - |
| `record_sha256` | string | 是 | ^[0-9a-f]{64}$ | - | REQUIRED_CONTENT_SHA256 | variant-1 |
| `record_sha256` | null | 是 | - | - | null | variant-2 |
| `wire_records` | integer | 是 | 0..4294967295 | 1 | 0 | - |
| `state_records` | integer | 是 | 0..4294967295 | 1 | 0 | - |
| `video_frames` | integer | 是 | 0..4294967295 | 1 | 0 | - |
| `error` | string | 是 | OK / SCHEMA / VERSION / HASH / AUTHORIZATION / MODEL / CONTROL_OWNER / RANGE / STATE / STALE_SESSION / DUPLICATE / OUT_OF_ORDER / LATE / EXPIRED / BUFFER_FULL / FRAGMENT / CRC / UNSUPPORTED / TARGET_MISSING / TIMEOUT / BUSINESS_FAILED / SAFETY / RESOURCE / CLOCK_UNSYNC / CAPACITY | - | "OK" | - |

## Diagnostic

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `channel_id` | string | 是 | 1..32 chars | - | "ETH_0" | - |
| `model_step` | integer | 是 | 0..4294967295 | model_step | 0 | - |
| `latency_p99_us` | integer | 是 | 0..10000000 | us | 0 | - |
| `jitter_p99_us` | integer | 是 | 0..10000000 | us | 0 | - |
| `cycle_us` | integer | 是 | 0..10000000 | us | 80000 | - |
| `traffic_ratio` | number | 是 | 0..1 | 1 | 0 | - |
| `crc_errors` | integer | 是 | 0..4294967295 | 1 | 0 | - |
| `loss_count` | integer | 是 | 0..4294967295 | 1 | 0 | - |
| `clock_synchronized` | boolean | 是 | - | bool | false | - |
| `clock_uncertainty_us` | integer | 是 | 0..10000000 | us | 10000000 | - |
| `qualification` | string | 是 | SOFTWARE_ONLY / PHYSICAL_PASSED / FAILED | - | "SOFTWARE_ONLY" | - |

## Capabilities

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `baseline_version` | const | 是 | "HIL-ICD-1.0" | - | "HIL-ICD-1.0" | - |
| `baseline_sha256` | string | 是 | ^[0-9a-f]{64}$ | - | REQUIRED_CONTENT_SHA256 | - |
| `model_ids` | array | 是 | 1..3 items | - | ["quadrotor_hil"] | - |
| `model_ids[]` | string | 是 | quadrotor_hil / multirotor_6_hil / fixed_wing_hil | - | "quadrotor_hil" | - |
| `implemented_message_ids` | array | 是 | 1..255 items | - | [1] | - |
| `implemented_message_ids[]` | integer | 是 | 1..255 | 1 | 1 | - |
| `qualified_channels` | array | 是 | 0..56 items | - | [] | - |
| `qualified_channels[]` | string | 是 | CANFD_0 / CANFD_1 / CANFD_2 / CANFD_3 / CAN_0 / CAN_1 / CAN_2 / CAN_3 / ETH_0 / ETH_1 / ETH_2 / ETH_3 / RS232_0 / RS232_1 / RS232_2 / RS232_3 / RS422_0 / RS422_1 / RS422_2 / RS422_3 / RS422_4 / RS422_5 / RS422_6 / RS422_7 / AD_0 / AD_1 / AD_2 / AD_3 / AD_4 / AD_5 / AD_6 / AD_7 / DA_0 / DA_1 / DA_2 / DA_3 / DA_4 / DA_5 / DA_6 / DA_7 / TTL_0 / TTL_1 / TTL_2 / TTL_3 / TTL_4 / TTL_5 / TTL_6 / TTL_7 / TTL_8 / TTL_9 / TTL_10 / TTL_11 / TTL_12 / TTL_13 / TTL_14 / TTL_15 | - | "CANFD_0" | - |
| `max_payload_bytes` | const | 是 | 65536 | - | 65536 | - |
| `max_target_ahead_steps` | const | 是 | 1000 | - | 1000 | - |
| `queue_capacity` | const | 是 | 4096 | - | 4096 | - |
| `supported_codecs` | array | 是 | 0..3 items | - | [] | - |
| `supported_codecs[]` | string | 是 | H264 / H265 / RAW | - | "H264" | - |
| `initialization_port_ready` | boolean | 是 | - | bool | false | - |
| `extended_environment_ready` | boolean | 是 | - | bool | false | - |
| `system_model_ready` | boolean | 是 | - | bool | false | - |
| `hex_motor_faults_ready` | boolean | 是 | - | bool | false | - |
| `phase_controller_ready` | boolean | 是 | - | bool | false | - |
| `replacement_ready` | boolean | 是 | - | bool | false | - |
| `available_probes` | array | 是 | 0..157 items | - | [] | - |
| `available_probes[]` | ref:ProbeName | 是 | 见引用定义 | 见引用 | 见引用 | - |

## Evidence

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `event_id` | string | 是 | 1..128 chars | - | "item-01" | - |
| `request_sequence` | integer | 是 | 1..4294967295 | 1 | 1 | - |
| `message_id` | integer | 是 | 0..65535 | 1 | 1 | - |
| `stage` | string | 是 | E0 / E1 / E2 / E3 | - | "E0" | - |
| `model_step` | integer | 是 | 0..4294967295 | model_step | 0 | - |
| `mono_ns` | string | 是 | ^(0\|[1-9][0-9]{0,19})$ | - | "0" | - |
| `probe_id` | ref:ProbeName | 是 | 见引用定义 | 见引用 | 见引用 | - |
| `business_result` | string | 是 | NOT_EVALUATED / PASS / FAIL | - | "NOT_EVALUATED" | - |
| `payload_sha256` | string | 是 | ^[0-9a-f]{64}$ | - | REQUIRED_CONTENT_SHA256 | - |
| `trace_id` | string | 是 | 1..128 chars | - | "item-01" | - |
| `error` | string | 是 | OK / SCHEMA / VERSION / HASH / AUTHORIZATION / MODEL / CONTROL_OWNER / RANGE / STATE / STALE_SESSION / DUPLICATE / OUT_OF_ORDER / LATE / EXPIRED / BUFFER_FULL / FRAGMENT / CRC / UNSUPPORTED / TARGET_MISSING / TIMEOUT / BUSINESS_FAILED / SAFETY / RESOURCE / CLOCK_UNSYNC / CAPACITY | - | "OK" | - |

## ResourceAck

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `resource_sha256` | string | 是 | ^[0-9a-f]{64}$ | - | REQUIRED_CONTENT_SHA256 | - |
| `next_offset` | integer | 是 | 0..4294967295 | 1 | 0 | - |
| `complete` | boolean | 是 | - | bool | false | - |
| `stored_bytes` | integer | 是 | 0..4294967295 | byte | 0 | - |
| `error` | string | 是 | OK / SCHEMA / VERSION / HASH / AUTHORIZATION / MODEL / CONTROL_OWNER / RANGE / STATE / STALE_SESSION / DUPLICATE / OUT_OF_ORDER / LATE / EXPIRED / BUFFER_FULL / FRAGMENT / CRC / UNSUPPORTED / TARGET_MISSING / TIMEOUT / BUSINESS_FAILED / SAFETY / RESOURCE / CLOCK_UNSYNC / CAPACITY | - | "OK" | - |

## ClockStatus

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `nonce` | integer | 是 | 1..4294967295 | 1 | 1 | - |
| `receive_mono_ns` | string | 是 | ^(0\|[1-9][0-9]{0,19})$ | - | "0" | - |
| `send_mono_ns` | string | 是 | ^(0\|[1-9][0-9]{0,19})$ | - | "0" | - |
| `model_step` | integer | 是 | 0..4294967295 | model_step | 0 | - |
| `uncertainty_us` | integer | 是 | 0..10000000 | us | 10000000 | - |
| `synchronized` | boolean | 是 | - | bool | false | - |

## BusinessMessage

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `message_id` | const | 是 | 1 | - | 1 | variant-1 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-1 |
| `payload` | ref:SessionOpen | 是 | 见引用定义 | 见引用 | 见引用 | variant-1 |
| `message_id` | const | 是 | 2 | - | 2 | variant-2 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-2 |
| `payload` | ref:Heartbeat | 是 | 见引用定义 | 见引用 | 见引用 | variant-2 |
| `message_id` | const | 是 | 3 | - | 3 | variant-3 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-3 |
| `payload` | ref:RunConfigure | 是 | 见引用定义 | 见引用 | 见引用 | variant-3 |
| `message_id` | const | 是 | 4 | - | 4 | variant-4 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-4 |
| `payload` | ref:Lifecycle | 是 | 见引用定义 | 见引用 | 见引用 | variant-4 |
| `message_id` | const | 是 | 5 | - | 5 | variant-5 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-5 |
| `payload` | ref:InitialState | 是 | 见引用定义 | 见引用 | 见引用 | variant-5 |
| `message_id` | const | 是 | 6 | - | 6 | variant-6 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-6 |
| `payload` | ref:ControlOwner | 是 | 见引用定义 | 见引用 | 见引用 | variant-6 |
| `message_id` | const | 是 | 7 | - | 7 | variant-7 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-7 |
| `payload` | ref:FlightQuad | 是 | 见引用定义 | 见引用 | 见引用 | variant-7 |
| `message_id` | const | 是 | 8 | - | 8 | variant-8 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-8 |
| `payload` | ref:FlightHex | 是 | 见引用定义 | 见引用 | 见引用 | variant-8 |
| `message_id` | const | 是 | 9 | - | 9 | variant-9 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-9 |
| `payload` | ref:FlightFixed | 是 | 见引用定义 | 见引用 | 见引用 | variant-9 |
| `message_id` | const | 是 | 10 | - | 10 | variant-10 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-10 |
| `payload` | ref:Environment | 是 | 见引用定义 | 见引用 | 见引用 | variant-10 |
| `message_id` | const | 是 | 11 | - | 11 | variant-11 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-11 |
| `payload` | ref:FaultQuad | 是 | 见引用定义 | 见引用 | 见引用 | variant-11 |
| `message_id` | const | 是 | 12 | - | 12 | variant-12 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-12 |
| `payload` | ref:FaultHex | 是 | 见引用定义 | 见引用 | 见引用 | variant-12 |
| `message_id` | const | 是 | 13 | - | 13 | variant-13 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-13 |
| `payload` | ref:FaultFixed | 是 | 见引用定义 | 见引用 | 见引用 | variant-13 |
| `message_id` | const | 是 | 14 | - | 14 | variant-14 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-14 |
| `payload` | ref:ActuatorQuad | 是 | 见引用定义 | 见引用 | 见引用 | variant-14 |
| `message_id` | const | 是 | 15 | - | 15 | variant-15 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-15 |
| `payload` | ref:ActuatorHex | 是 | 见引用定义 | 见引用 | 见引用 | variant-15 |
| `message_id` | const | 是 | 16 | - | 16 | variant-16 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-16 |
| `payload` | ref:ActuatorFixed | 是 | 见引用定义 | 见引用 | 见引用 | variant-16 |
| `message_id` | const | 是 | 17 | - | 17 | variant-17 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-17 |
| `payload` | ref:TuneQuad | 是 | 见引用定义 | 见引用 | 见引用 | variant-17 |
| `message_id` | const | 是 | 18 | - | 18 | variant-18 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-18 |
| `payload` | ref:TuneHex | 是 | 见引用定义 | 见引用 | 见引用 | variant-18 |
| `message_id` | const | 是 | 19 | - | 19 | variant-19 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-19 |
| `payload` | ref:TuneFixed | 是 | 见引用定义 | 见引用 | 见引用 | variant-19 |
| `message_id` | const | 是 | 20 | - | 20 | variant-20 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-20 |
| `payload` | ref:MissionLoad | 是 | 见引用定义 | 见引用 | 见引用 | variant-20 |
| `message_id` | const | 是 | 21 | - | 21 | variant-21 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-21 |
| `payload` | ref:MissionControl | 是 | 见引用定义 | 见引用 | 见引用 | variant-21 |
| `message_id` | const | 是 | 22 | - | 22 | variant-22 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-22 |
| `payload` | ref:FlightCommand | 是 | 见引用定义 | 见引用 | 见引用 | variant-22 |
| `message_id` | const | 是 | 23 | - | 23 | variant-23 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-23 |
| `payload` | ref:Targets | 是 | 见引用定义 | 见引用 | 见引用 | variant-23 |
| `message_id` | const | 是 | 24 | - | 24 | variant-24 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-24 |
| `payload` | ref:EnvironmentExt | 是 | 见引用定义 | 见引用 | 见引用 | variant-24 |
| `message_id` | const | 是 | 25 | - | 25 | variant-25 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-25 |
| `payload` | ref:SystemStimulus | 是 | 见引用定义 | 见引用 | 见引用 | variant-25 |
| `message_id` | const | 是 | 26 | - | 26 | variant-26 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-26 |
| `payload` | ref:BusFault | 是 | 见引用定义 | 见引用 | 见引用 | variant-26 |
| `message_id` | const | 是 | 27 | - | 27 | variant-27 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-27 |
| `payload` | ref:SerialWrite | 是 | 见引用定义 | 见引用 | 见引用 | variant-27 |
| `message_id` | const | 是 | 28 | - | 28 | variant-28 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-28 |
| `payload` | ref:AnalogWrite | 是 | 见引用定义 | 见引用 | 见引用 | variant-28 |
| `message_id` | const | 是 | 29 | - | 29 | variant-29 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-29 |
| `payload` | ref:DigitalWrite | 是 | 见引用定义 | 见引用 | 见引用 | variant-29 |
| `message_id` | const | 是 | 30 | - | 30 | variant-30 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-30 |
| `payload` | ref:VideoConfig | 是 | 见引用定义 | 见引用 | 见引用 | variant-30 |
| `message_id` | const | 是 | 31 | - | 31 | variant-31 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-31 |
| `payload` | ref:VideoControl | 是 | 见引用定义 | 见引用 | 见引用 | variant-31 |
| `message_id` | const | 是 | 32 | - | 32 | variant-32 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-32 |
| `payload` | ref:VideoAnnotation | 是 | 见引用定义 | 见引用 | 见引用 | variant-32 |
| `message_id` | const | 是 | 33 | - | 33 | variant-33 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-33 |
| `payload` | ref:ClockSync | 是 | 见引用定义 | 见引用 | 见引用 | variant-33 |
| `message_id` | const | 是 | 34 | - | 34 | variant-34 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-34 |
| `payload` | ref:ResourceChunk | 是 | 见引用定义 | 见引用 | 见引用 | variant-34 |
| `message_id` | const | 是 | 35 | - | 35 | variant-35 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-35 |
| `payload` | ref:Query | 是 | 见引用定义 | 见引用 | 见引用 | variant-35 |
| `message_id` | const | 是 | 36 | - | 36 | variant-36 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-36 |
| `payload` | ref:RecordControl | 是 | 见引用定义 | 见引用 | 见引用 | variant-36 |
| `message_id` | const | 是 | 37 | - | 37 | variant-37 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-37 |
| `payload` | ref:Cleanup | 是 | 见引用定义 | 见引用 | 见引用 | variant-37 |
| `message_id` | const | 是 | 38 | - | 38 | variant-38 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-38 |
| `payload` | ref:SessionClose | 是 | 见引用定义 | 见引用 | 见引用 | variant-38 |
| `message_id` | const | 是 | 39 | - | 39 | variant-39 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-39 |
| `payload` | ref:SensorConfig | 是 | 见引用定义 | 见引用 | 见引用 | variant-39 |
| `message_id` | const | 是 | 40 | - | 40 | variant-40 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-40 |
| `payload` | ref:PhysicalChannelConfig | 是 | 见引用定义 | 见引用 | 见引用 | variant-40 |
| `message_id` | const | 是 | 41 | - | 41 | variant-41 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-41 |
| `payload` | ref:Terrain | 是 | 见引用定义 | 见引用 | 见引用 | variant-41 |
| `message_id` | const | 是 | 42 | - | 42 | variant-42 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-42 |
| `payload` | ref:Obstacles | 是 | 见引用定义 | 见引用 | 见引用 | variant-42 |
| `message_id` | const | 是 | 43 | - | 43 | variant-43 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-43 |
| `payload` | ref:VideoFrameMetadata | 是 | 见引用定义 | 见引用 | 见引用 | variant-43 |
| `message_id` | const | 是 | 129 | - | 129 | variant-44 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-44 |
| `payload` | ref:SessionOpened | 是 | 见引用定义 | 见引用 | 见引用 | variant-44 |
| `message_id` | const | 是 | 130 | - | 130 | variant-45 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-45 |
| `payload` | ref:Ack | 是 | 见引用定义 | 见引用 | 见引用 | variant-45 |
| `message_id` | const | 是 | 131 | - | 131 | variant-46 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-46 |
| `payload` | ref:Status | 是 | 见引用定义 | 见引用 | 见引用 | variant-46 |
| `message_id` | const | 是 | 132 | - | 132 | variant-47 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-47 |
| `payload` | ref:State | 是 | 见引用定义 | 见引用 | 见引用 | variant-47 |
| `message_id` | const | 是 | 133 | - | 133 | variant-48 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-48 |
| `payload` | ref:Sensors | 是 | 见引用定义 | 见引用 | 见引用 | variant-48 |
| `message_id` | const | 是 | 134 | - | 134 | variant-49 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-49 |
| `payload` | ref:IOStatus | 是 | 见引用定义 | 见引用 | 见引用 | variant-49 |
| `message_id` | const | 是 | 135 | - | 135 | variant-50 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-50 |
| `payload` | ref:VideoStatus | 是 | 见引用定义 | 见引用 | 见引用 | variant-50 |
| `message_id` | const | 是 | 136 | - | 136 | variant-51 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-51 |
| `payload` | ref:TaskStatus | 是 | 见引用定义 | 见引用 | 见引用 | variant-51 |
| `message_id` | const | 是 | 137 | - | 137 | variant-52 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-52 |
| `payload` | ref:RecordStatus | 是 | 见引用定义 | 见引用 | 见引用 | variant-52 |
| `message_id` | const | 是 | 138 | - | 138 | variant-53 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-53 |
| `payload` | ref:Diagnostic | 是 | 见引用定义 | 见引用 | 见引用 | variant-53 |
| `message_id` | const | 是 | 139 | - | 139 | variant-54 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-54 |
| `payload` | ref:Capabilities | 是 | 见引用定义 | 见引用 | 见引用 | variant-54 |
| `message_id` | const | 是 | 140 | - | 140 | variant-55 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-55 |
| `payload` | ref:Evidence | 是 | 见引用定义 | 见引用 | 见引用 | variant-55 |
| `message_id` | const | 是 | 141 | - | 141 | variant-56 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-56 |
| `payload` | ref:ResourceAck | 是 | 见引用定义 | 见引用 | 见引用 | variant-56 |
| `message_id` | const | 是 | 142 | - | 142 | variant-57 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-57 |
| `payload` | ref:ClockStatus | 是 | 见引用定义 | 见引用 | 见引用 | variant-57 |
| `message_id` | const | 是 | 44 | - | REQUIRED_EXPLICIT_VALUE | variant-58 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-58 |
| `payload` | ref:RawBus | 是 | 见引用定义 | 见引用 | 见引用 | variant-58 |
| `message_id` | const | 是 | 45 | - | REQUIRED_EXPLICIT_VALUE | variant-59 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-59 |
| `payload` | ref:SensorFault | 是 | 见引用定义 | 见引用 | 见引用 | variant-59 |

## APIInput

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `cmd` | const | 是 | "simulator_run_update_inputs" | - | REQUIRED_EXPLICIT_VALUE | - |
| `params.run_id` | string | 是 | 1..128 chars | - | "item-01" | - |
| `params.expected_revision` | string | 是 | ^(0\|[1-9][0-9]{0,19})$ | - | "0" | - |
| `params.link_id` | string | 是 | CANT / CUTIL / SAVVY / CANREPLAY / ETHGEN / ETHREPLAY | - | "CANT" | - |
| `params.message` | ref:BusinessInputMessage | 是 | 见引用定义 | 见引用 | 见引用 | - |
| `params.api_version` | const | 是 | "0.3" | - | REQUIRED_EXPLICIT_VALUE | - |
| `params.request_id` | string | 是 | 1..128 chars | - | REQUIRED_EXPLICIT_VALUE | - |

## TerrainResource

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `resource_id` | string | 是 | 1..128 chars | - | "item-01" | - |
| `origin` | ref:Origin | 是 | 见引用定义 | 见引用 | 见引用 | - |
| `rows` | integer | 是 | 2..4096 | 1 | 2 | - |
| `columns` | integer | 是 | 2..4096 | 1 | 2 | - |
| `spacing_n_m` | number | 是 | 0.1..1000 | m | 1 | - |
| `spacing_e_m` | number | 是 | 0.1..1000 | m | 1 | - |
| `height_datum` | const | 是 | "ELLIPSOID" | - | "ELLIPSOID" | - |
| `heights_m` | array | 是 | 4..16777216 items | - | [0,0,0,0] | - |
| `heights_m[]` | number | 是 | -500..10000 | m | 0 | - |
| `nodata_policy` | const | 是 | "REJECT_ROUTE_OUTSIDE_GRID" | - | "REJECT_ROUTE_OUTSIDE_GRID" | - |

## ObstaclesResource

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `revision` | integer | 是 | 1..4294967295 | 1 | 1 | - |
| `obstacles` | array | 是 | 0..10000 items | - | [] | - |
| `obstacles[]` | ref:Obstacle | 是 | 见引用定义 | 见引用 | 见引用 | - |

## BusinessInputMessage

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `message_id` | const | 是 | 1 | - | 1 | variant-1 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-1 |
| `payload` | ref:SessionOpen | 是 | 见引用定义 | 见引用 | 见引用 | variant-1 |
| `message_id` | const | 是 | 2 | - | 2 | variant-2 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-2 |
| `payload` | ref:Heartbeat | 是 | 见引用定义 | 见引用 | 见引用 | variant-2 |
| `message_id` | const | 是 | 3 | - | 3 | variant-3 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-3 |
| `payload` | ref:RunConfigure | 是 | 见引用定义 | 见引用 | 见引用 | variant-3 |
| `message_id` | const | 是 | 4 | - | 4 | variant-4 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-4 |
| `payload` | ref:Lifecycle | 是 | 见引用定义 | 见引用 | 见引用 | variant-4 |
| `message_id` | const | 是 | 5 | - | 5 | variant-5 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-5 |
| `payload` | ref:InitialState | 是 | 见引用定义 | 见引用 | 见引用 | variant-5 |
| `message_id` | const | 是 | 6 | - | 6 | variant-6 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-6 |
| `payload` | ref:ControlOwner | 是 | 见引用定义 | 见引用 | 见引用 | variant-6 |
| `message_id` | const | 是 | 7 | - | 7 | variant-7 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-7 |
| `payload` | ref:FlightQuad | 是 | 见引用定义 | 见引用 | 见引用 | variant-7 |
| `message_id` | const | 是 | 8 | - | 8 | variant-8 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-8 |
| `payload` | ref:FlightHex | 是 | 见引用定义 | 见引用 | 见引用 | variant-8 |
| `message_id` | const | 是 | 9 | - | 9 | variant-9 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-9 |
| `payload` | ref:FlightFixed | 是 | 见引用定义 | 见引用 | 见引用 | variant-9 |
| `message_id` | const | 是 | 10 | - | 10 | variant-10 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-10 |
| `payload` | ref:Environment | 是 | 见引用定义 | 见引用 | 见引用 | variant-10 |
| `message_id` | const | 是 | 11 | - | 11 | variant-11 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-11 |
| `payload` | ref:FaultQuad | 是 | 见引用定义 | 见引用 | 见引用 | variant-11 |
| `message_id` | const | 是 | 12 | - | 12 | variant-12 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-12 |
| `payload` | ref:FaultHex | 是 | 见引用定义 | 见引用 | 见引用 | variant-12 |
| `message_id` | const | 是 | 13 | - | 13 | variant-13 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-13 |
| `payload` | ref:FaultFixed | 是 | 见引用定义 | 见引用 | 见引用 | variant-13 |
| `message_id` | const | 是 | 14 | - | 14 | variant-14 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-14 |
| `payload` | ref:ActuatorQuad | 是 | 见引用定义 | 见引用 | 见引用 | variant-14 |
| `message_id` | const | 是 | 15 | - | 15 | variant-15 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-15 |
| `payload` | ref:ActuatorHex | 是 | 见引用定义 | 见引用 | 见引用 | variant-15 |
| `message_id` | const | 是 | 16 | - | 16 | variant-16 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-16 |
| `payload` | ref:ActuatorFixed | 是 | 见引用定义 | 见引用 | 见引用 | variant-16 |
| `message_id` | const | 是 | 17 | - | 17 | variant-17 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-17 |
| `payload` | ref:TuneQuad | 是 | 见引用定义 | 见引用 | 见引用 | variant-17 |
| `message_id` | const | 是 | 18 | - | 18 | variant-18 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-18 |
| `payload` | ref:TuneHex | 是 | 见引用定义 | 见引用 | 见引用 | variant-18 |
| `message_id` | const | 是 | 19 | - | 19 | variant-19 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-19 |
| `payload` | ref:TuneFixed | 是 | 见引用定义 | 见引用 | 见引用 | variant-19 |
| `message_id` | const | 是 | 20 | - | 20 | variant-20 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-20 |
| `payload` | ref:MissionLoad | 是 | 见引用定义 | 见引用 | 见引用 | variant-20 |
| `message_id` | const | 是 | 21 | - | 21 | variant-21 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-21 |
| `payload` | ref:MissionControl | 是 | 见引用定义 | 见引用 | 见引用 | variant-21 |
| `message_id` | const | 是 | 22 | - | 22 | variant-22 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-22 |
| `payload` | ref:FlightCommand | 是 | 见引用定义 | 见引用 | 见引用 | variant-22 |
| `message_id` | const | 是 | 23 | - | 23 | variant-23 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-23 |
| `payload` | ref:Targets | 是 | 见引用定义 | 见引用 | 见引用 | variant-23 |
| `message_id` | const | 是 | 24 | - | 24 | variant-24 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-24 |
| `payload` | ref:EnvironmentExt | 是 | 见引用定义 | 见引用 | 见引用 | variant-24 |
| `message_id` | const | 是 | 25 | - | 25 | variant-25 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-25 |
| `payload` | ref:SystemStimulus | 是 | 见引用定义 | 见引用 | 见引用 | variant-25 |
| `message_id` | const | 是 | 26 | - | 26 | variant-26 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-26 |
| `payload` | ref:BusFault | 是 | 见引用定义 | 见引用 | 见引用 | variant-26 |
| `message_id` | const | 是 | 27 | - | 27 | variant-27 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-27 |
| `payload` | ref:SerialWrite | 是 | 见引用定义 | 见引用 | 见引用 | variant-27 |
| `message_id` | const | 是 | 28 | - | 28 | variant-28 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-28 |
| `payload` | ref:AnalogWrite | 是 | 见引用定义 | 见引用 | 见引用 | variant-28 |
| `message_id` | const | 是 | 29 | - | 29 | variant-29 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-29 |
| `payload` | ref:DigitalWrite | 是 | 见引用定义 | 见引用 | 见引用 | variant-29 |
| `message_id` | const | 是 | 30 | - | 30 | variant-30 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-30 |
| `payload` | ref:VideoConfig | 是 | 见引用定义 | 见引用 | 见引用 | variant-30 |
| `message_id` | const | 是 | 31 | - | 31 | variant-31 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-31 |
| `payload` | ref:VideoControl | 是 | 见引用定义 | 见引用 | 见引用 | variant-31 |
| `message_id` | const | 是 | 32 | - | 32 | variant-32 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-32 |
| `payload` | ref:VideoAnnotation | 是 | 见引用定义 | 见引用 | 见引用 | variant-32 |
| `message_id` | const | 是 | 33 | - | 33 | variant-33 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-33 |
| `payload` | ref:ClockSync | 是 | 见引用定义 | 见引用 | 见引用 | variant-33 |
| `message_id` | const | 是 | 34 | - | 34 | variant-34 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-34 |
| `payload` | ref:ResourceChunk | 是 | 见引用定义 | 见引用 | 见引用 | variant-34 |
| `message_id` | const | 是 | 35 | - | 35 | variant-35 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-35 |
| `payload` | ref:Query | 是 | 见引用定义 | 见引用 | 见引用 | variant-35 |
| `message_id` | const | 是 | 36 | - | 36 | variant-36 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-36 |
| `payload` | ref:RecordControl | 是 | 见引用定义 | 见引用 | 见引用 | variant-36 |
| `message_id` | const | 是 | 37 | - | 37 | variant-37 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-37 |
| `payload` | ref:Cleanup | 是 | 见引用定义 | 见引用 | 见引用 | variant-37 |
| `message_id` | const | 是 | 38 | - | 38 | variant-38 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-38 |
| `payload` | ref:SessionClose | 是 | 见引用定义 | 见引用 | 见引用 | variant-38 |
| `message_id` | const | 是 | 39 | - | 39 | variant-39 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-39 |
| `payload` | ref:SensorConfig | 是 | 见引用定义 | 见引用 | 见引用 | variant-39 |
| `message_id` | const | 是 | 40 | - | 40 | variant-40 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-40 |
| `payload` | ref:PhysicalChannelConfig | 是 | 见引用定义 | 见引用 | 见引用 | variant-40 |
| `message_id` | const | 是 | 41 | - | 41 | variant-41 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-41 |
| `payload` | ref:Terrain | 是 | 见引用定义 | 见引用 | 见引用 | variant-41 |
| `message_id` | const | 是 | 42 | - | 42 | variant-42 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-42 |
| `payload` | ref:Obstacles | 是 | 见引用定义 | 见引用 | 见引用 | variant-42 |
| `message_id` | const | 是 | 43 | - | 43 | variant-43 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-43 |
| `payload` | ref:VideoFrameMetadata | 是 | 见引用定义 | 见引用 | 见引用 | variant-43 |
| `message_id` | const | 是 | 44 | - | REQUIRED_EXPLICIT_VALUE | variant-44 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-44 |
| `payload` | ref:RawBus | 是 | 见引用定义 | 见引用 | 见引用 | variant-44 |
| `message_id` | const | 是 | 45 | - | REQUIRED_EXPLICIT_VALUE | variant-45 |
| `header` | ref:Header | 是 | 见引用定义 | 见引用 | 见引用 | variant-45 |
| `payload` | ref:SensorFault | 是 | 见引用定义 | 见引用 | 见引用 | variant-45 |

## Stimulus

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `message_id` | const | 是 | 1 | - | 1 | variant-1 |
| `payload` | ref:SessionOpen | 是 | 见引用定义 | 见引用 | 见引用 | variant-1 |
| `message_id` | const | 是 | 2 | - | 2 | variant-2 |
| `payload` | ref:Heartbeat | 是 | 见引用定义 | 见引用 | 见引用 | variant-2 |
| `message_id` | const | 是 | 3 | - | 3 | variant-3 |
| `payload` | ref:RunConfigure | 是 | 见引用定义 | 见引用 | 见引用 | variant-3 |
| `message_id` | const | 是 | 4 | - | 4 | variant-4 |
| `payload` | ref:Lifecycle | 是 | 见引用定义 | 见引用 | 见引用 | variant-4 |
| `message_id` | const | 是 | 5 | - | 5 | variant-5 |
| `payload` | ref:InitialState | 是 | 见引用定义 | 见引用 | 见引用 | variant-5 |
| `message_id` | const | 是 | 6 | - | 6 | variant-6 |
| `payload` | ref:ControlOwner | 是 | 见引用定义 | 见引用 | 见引用 | variant-6 |
| `message_id` | const | 是 | 7 | - | 7 | variant-7 |
| `payload` | ref:FlightQuad | 是 | 见引用定义 | 见引用 | 见引用 | variant-7 |
| `message_id` | const | 是 | 8 | - | 8 | variant-8 |
| `payload` | ref:FlightHex | 是 | 见引用定义 | 见引用 | 见引用 | variant-8 |
| `message_id` | const | 是 | 9 | - | 9 | variant-9 |
| `payload` | ref:FlightFixed | 是 | 见引用定义 | 见引用 | 见引用 | variant-9 |
| `message_id` | const | 是 | 10 | - | 10 | variant-10 |
| `payload` | ref:Environment | 是 | 见引用定义 | 见引用 | 见引用 | variant-10 |
| `message_id` | const | 是 | 11 | - | 11 | variant-11 |
| `payload` | ref:FaultQuad | 是 | 见引用定义 | 见引用 | 见引用 | variant-11 |
| `message_id` | const | 是 | 12 | - | 12 | variant-12 |
| `payload` | ref:FaultHex | 是 | 见引用定义 | 见引用 | 见引用 | variant-12 |
| `message_id` | const | 是 | 13 | - | 13 | variant-13 |
| `payload` | ref:FaultFixed | 是 | 见引用定义 | 见引用 | 见引用 | variant-13 |
| `message_id` | const | 是 | 14 | - | 14 | variant-14 |
| `payload` | ref:ActuatorQuad | 是 | 见引用定义 | 见引用 | 见引用 | variant-14 |
| `message_id` | const | 是 | 15 | - | 15 | variant-15 |
| `payload` | ref:ActuatorHex | 是 | 见引用定义 | 见引用 | 见引用 | variant-15 |
| `message_id` | const | 是 | 16 | - | 16 | variant-16 |
| `payload` | ref:ActuatorFixed | 是 | 见引用定义 | 见引用 | 见引用 | variant-16 |
| `message_id` | const | 是 | 17 | - | 17 | variant-17 |
| `payload` | ref:TuneQuad | 是 | 见引用定义 | 见引用 | 见引用 | variant-17 |
| `message_id` | const | 是 | 18 | - | 18 | variant-18 |
| `payload` | ref:TuneHex | 是 | 见引用定义 | 见引用 | 见引用 | variant-18 |
| `message_id` | const | 是 | 19 | - | 19 | variant-19 |
| `payload` | ref:TuneFixed | 是 | 见引用定义 | 见引用 | 见引用 | variant-19 |
| `message_id` | const | 是 | 20 | - | 20 | variant-20 |
| `payload` | ref:MissionLoad | 是 | 见引用定义 | 见引用 | 见引用 | variant-20 |
| `message_id` | const | 是 | 21 | - | 21 | variant-21 |
| `payload` | ref:MissionControl | 是 | 见引用定义 | 见引用 | 见引用 | variant-21 |
| `message_id` | const | 是 | 22 | - | 22 | variant-22 |
| `payload` | ref:FlightCommand | 是 | 见引用定义 | 见引用 | 见引用 | variant-22 |
| `message_id` | const | 是 | 23 | - | 23 | variant-23 |
| `payload` | ref:Targets | 是 | 见引用定义 | 见引用 | 见引用 | variant-23 |
| `message_id` | const | 是 | 24 | - | 24 | variant-24 |
| `payload` | ref:EnvironmentExt | 是 | 见引用定义 | 见引用 | 见引用 | variant-24 |
| `message_id` | const | 是 | 25 | - | 25 | variant-25 |
| `payload` | ref:SystemStimulus | 是 | 见引用定义 | 见引用 | 见引用 | variant-25 |
| `message_id` | const | 是 | 26 | - | 26 | variant-26 |
| `payload` | ref:BusFault | 是 | 见引用定义 | 见引用 | 见引用 | variant-26 |
| `message_id` | const | 是 | 27 | - | 27 | variant-27 |
| `payload` | ref:SerialWrite | 是 | 见引用定义 | 见引用 | 见引用 | variant-27 |
| `message_id` | const | 是 | 28 | - | 28 | variant-28 |
| `payload` | ref:AnalogWrite | 是 | 见引用定义 | 见引用 | 见引用 | variant-28 |
| `message_id` | const | 是 | 29 | - | 29 | variant-29 |
| `payload` | ref:DigitalWrite | 是 | 见引用定义 | 见引用 | 见引用 | variant-29 |
| `message_id` | const | 是 | 30 | - | 30 | variant-30 |
| `payload` | ref:VideoConfig | 是 | 见引用定义 | 见引用 | 见引用 | variant-30 |
| `message_id` | const | 是 | 31 | - | 31 | variant-31 |
| `payload` | ref:VideoControl | 是 | 见引用定义 | 见引用 | 见引用 | variant-31 |
| `message_id` | const | 是 | 32 | - | 32 | variant-32 |
| `payload` | ref:VideoAnnotation | 是 | 见引用定义 | 见引用 | 见引用 | variant-32 |
| `message_id` | const | 是 | 33 | - | 33 | variant-33 |
| `payload` | ref:ClockSync | 是 | 见引用定义 | 见引用 | 见引用 | variant-33 |
| `message_id` | const | 是 | 34 | - | 34 | variant-34 |
| `payload` | ref:ResourceChunk | 是 | 见引用定义 | 见引用 | 见引用 | variant-34 |
| `message_id` | const | 是 | 35 | - | 35 | variant-35 |
| `payload` | ref:Query | 是 | 见引用定义 | 见引用 | 见引用 | variant-35 |
| `message_id` | const | 是 | 36 | - | 36 | variant-36 |
| `payload` | ref:RecordControl | 是 | 见引用定义 | 见引用 | 见引用 | variant-36 |
| `message_id` | const | 是 | 37 | - | 37 | variant-37 |
| `payload` | ref:Cleanup | 是 | 见引用定义 | 见引用 | 见引用 | variant-37 |
| `message_id` | const | 是 | 38 | - | 38 | variant-38 |
| `payload` | ref:SessionClose | 是 | 见引用定义 | 见引用 | 见引用 | variant-38 |
| `message_id` | const | 是 | 39 | - | 39 | variant-39 |
| `payload` | ref:SensorConfig | 是 | 见引用定义 | 见引用 | 见引用 | variant-39 |
| `message_id` | const | 是 | 40 | - | 40 | variant-40 |
| `payload` | ref:PhysicalChannelConfig | 是 | 见引用定义 | 见引用 | 见引用 | variant-40 |
| `message_id` | const | 是 | 41 | - | 41 | variant-41 |
| `payload` | ref:Terrain | 是 | 见引用定义 | 见引用 | 见引用 | variant-41 |
| `message_id` | const | 是 | 42 | - | 42 | variant-42 |
| `payload` | ref:Obstacles | 是 | 见引用定义 | 见引用 | 见引用 | variant-42 |
| `message_id` | const | 是 | 43 | - | 43 | variant-43 |
| `payload` | ref:VideoFrameMetadata | 是 | 见引用定义 | 见引用 | 见引用 | variant-43 |
| `message_id` | const | 是 | 44 | - | REQUIRED_EXPLICIT_VALUE | variant-44 |
| `payload` | ref:RawBus | 是 | 见引用定义 | 见引用 | 见引用 | variant-44 |
| `message_id` | const | 是 | 45 | - | REQUIRED_EXPLICIT_VALUE | variant-45 |
| `payload` | ref:SensorFault | 是 | 见引用定义 | 见引用 | 见引用 | variant-45 |

## ResourceRef

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `resource_id` | string | 是 | 1..128 chars | - | "item-01" | - |
| `sha256` | string | 是 | ^[0-9a-f]{64}$ | - | REQUIRED_CONTENT_SHA256 | - |
| `size_bytes` | integer | 是 | 1..4294967295 | byte | 1 | - |
| `format` | string | 是 | DBC / ARXML / ICD_JSON / SCENARIO_JSON / SCENARIO_YAML / CAN_LOG / PCAP / PCAPNG / ENGINEERING_JSONL / JSON / CSV / BINARY | - | "DBC" | - |
| `encoding` | string | 是 | UTF8 / BINARY | - | "UTF8" | - |
| `media_type` | string | 是 | 1..128 chars | - | "application/json" | - |
| `file_name` | string | 是 | 1..256 chars | - | "resource.json" | - |

## ProtocolSource

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `source_type` | const | 是 | "PROTOCOL" | - | "PROTOCOL" | - |
| `baseline_version` | const | 是 | "HIL-ICD-1.0" | - | "HIL-ICD-1.0" | - |
| `business_schema_sha256` | string | 是 | ^[0-9a-f]{64}$ | - | REQUIRED_CONTENT_SHA256 | - |
| `wire_catalog_sha256` | string | 是 | ^[0-9a-f]{64}$ | - | REQUIRED_CONTENT_SHA256 | - |
| `resources` | array | 是 | 2..100 items | - | REQUIRED_CONTENT | - |
| `resources[]` | ref:ResourceRef | 是 | 见引用定义 | 见引用 | 见引用 | - |
| `message_ids` | array | 是 | 1..255 items | - | REQUIRED_CONTENT | - |
| `message_ids[]` | integer | 是 | 1..255 | 1 | 1 | - |

## Waveform

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `kind` | const | 是 | "CONSTANT" | - | "CONSTANT" | variant-1 |
| `value` | number | 是 | -1000000..1000000 | TARGET_UNIT | 0 | variant-1 |
| `kind` | const | 是 | "STEP" | - | "STEP" | variant-2 |
| `before` | number | 是 | -1000000..1000000 | TARGET_UNIT | 0 | variant-2 |
| `after` | number | 是 | -1000000..1000000 | TARGET_UNIT | 1 | variant-2 |
| `change_step` | integer | 是 | 0..4294967295 | model_step | 0 | variant-2 |
| `kind` | const | 是 | "RAMP" | - | "RAMP" | variant-3 |
| `start_value` | number | 是 | -1000000..1000000 | TARGET_UNIT | 0 | variant-3 |
| `end_value` | number | 是 | -1000000..1000000 | TARGET_UNIT | 1 | variant-3 |
| `duration_steps` | integer | 是 | 1..86400000 | model_step | 1000 | variant-3 |
| `kind` | const | 是 | "SINE" | - | "SINE" | variant-4 |
| `offset` | number | 是 | -1000000..1000000 | TARGET_UNIT | 0 | variant-4 |
| `amplitude` | number | 是 | 0..1000000 | TARGET_UNIT | 1 | variant-4 |
| `frequency_hz` | number | 是 | 0.001..50 | Hz | 1 | variant-4 |
| `phase_rad` | number | 是 | -3.141592653589793..3.141592653589793 | rad | 0 | variant-4 |
| `kind` | const | 是 | "CHIRP" | - | "CHIRP" | variant-5 |
| `offset` | number | 是 | -1000000..1000000 | TARGET_UNIT | 0 | variant-5 |
| `amplitude` | number | 是 | 0..1000000 | TARGET_UNIT | 1 | variant-5 |
| `start_frequency_hz` | number | 是 | 0.001..50 | Hz | 0.1 | variant-5 |
| `end_frequency_hz` | number | 是 | 0.001..50 | Hz | 10 | variant-5 |
| `duration_steps` | integer | 是 | 1..86400000 | model_step | 10000 | variant-5 |
| `phase_rad` | number | 是 | -3.141592653589793..3.141592653589793 | rad | 0 | variant-5 |

## Assertion

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `assertion_id` | string | 是 | 1..128 chars | - | "item-01" | - |
| `stage` | string | 是 | E1 / E2 / E3 | - | "E1" | - |
| `message_id` | integer | 是 | 1..255 | 1 | 10 | - |
| `probe_id` | ref:ProbeName | 是 | 见引用定义 | 见引用 | 见引用 | - |
| `field_path` | string | 是 | 1..512 chars | - | "environment.wind_n_mps" | - |
| `operator` | string | 是 | EQ / NE / LT / LE / GT / GE / WITHIN / EVENTUALLY | - | "EQ" | - |
| `expected` | number | 是 | -1000000000..1000000000 | 1 | -1000000000 | variant-1 |
| `expected` | boolean | 是 | - | bool | false | variant-2 |
| `expected` | string | 是 | 0..256 chars | - | "OK" | variant-3 |
| `tolerance` | number | 是 | 0..1000000 | TARGET_UNIT | 0 | - |
| `timeout_steps` | integer | 是 | 1..86400000 | model_step | 1000 | - |
| `sample_count` | integer | 是 | 1..100000 | 1 | 1 | - |

## Event

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `event_id` | string | 是 | 1..128 chars | - | "item-01" | variant-1 |
| `at_step` | integer | 是 | 0..4294967295 | model_step | 0 | variant-1 |
| `priority` | integer | 是 | 0..255 | 1 | 100 | variant-1 |
| `link_id` | string | 是 | CANT / CUTIL / SAVVY / CANREPLAY / ETHGEN / ETHREPLAY | - | "CANT" | variant-1 |
| `type` | const | 是 | "SEND" | - | "SEND" | variant-1 |
| `stimulus` | ref:Stimulus | 是 | 见引用定义 | 见引用 | 见引用 | variant-1 |
| `event_id` | string | 是 | 1..128 chars | - | "item-01" | variant-2 |
| `at_step` | integer | 是 | 0..4294967295 | model_step | 0 | variant-2 |
| `priority` | integer | 是 | 0..255 | 1 | 100 | variant-2 |
| `link_id` | string | 是 | CANT / CUTIL / SAVVY / CANREPLAY / ETHGEN / ETHREPLAY | - | "CANT" | variant-2 |
| `type` | const | 是 | "WAVEFORM" | - | "WAVEFORM" | variant-2 |
| `stimulus` | ref:Stimulus | 是 | 见引用定义 | 见引用 | 见引用 | variant-2 |
| `field_path` | string | 是 | 1..512 chars | - | "wind_n_mps" | variant-2 |
| `waveform` | ref:Waveform | 是 | 见引用定义 | 见引用 | 见引用 | variant-2 |
| `duration_steps` | integer | 是 | 1..86400000 | model_step | 1000 | variant-2 |
| `sample_period_steps` | integer | 是 | 1..10000 | model_step | 80 | variant-2 |
| `event_id` | string | 是 | 1..128 chars | - | "item-01" | variant-3 |
| `at_step` | integer | 是 | 0..4294967295 | model_step | 0 | variant-3 |
| `priority` | integer | 是 | 0..255 | 1 | 100 | variant-3 |
| `link_id` | string | 是 | CANT / CUTIL / SAVVY / CANREPLAY / ETHGEN / ETHREPLAY | - | "CANT" | variant-3 |
| `type` | const | 是 | "PERIODIC_START" | - | "PERIODIC_START" | variant-3 |
| `sender_id` | string | 是 | 1..128 chars | - | "item-01" | variant-3 |
| `stimulus` | ref:Stimulus | 是 | 见引用定义 | 见引用 | 见引用 | variant-3 |
| `period_steps` | integer | 是 | 1..10000 | model_step | 80 | variant-3 |
| `count` | integer | 是 | 1..1000000 | 1 | 10 | variant-3 |
| `event_id` | string | 是 | 1..128 chars | - | "item-01" | variant-4 |
| `at_step` | integer | 是 | 0..4294967295 | model_step | 0 | variant-4 |
| `priority` | integer | 是 | 0..255 | 1 | 100 | variant-4 |
| `link_id` | string | 是 | CANT / CUTIL / SAVVY / CANREPLAY / ETHGEN / ETHREPLAY | - | "CANT" | variant-4 |
| `type` | const | 是 | "PERIODIC_STOP" | - | "PERIODIC_STOP" | variant-4 |
| `sender_id` | string | 是 | 1..128 chars | - | "item-01" | variant-4 |
| `event_id` | string | 是 | 1..128 chars | - | "item-01" | variant-5 |
| `at_step` | integer | 是 | 0..4294967295 | model_step | 0 | variant-5 |
| `priority` | integer | 是 | 0..255 | 1 | 100 | variant-5 |
| `link_id` | string | 是 | CANT / CUTIL / SAVVY / CANREPLAY / ETHGEN / ETHREPLAY | - | "CANT" | variant-5 |
| `type` | const | 是 | "WAIT" | - | "WAIT" | variant-5 |
| `assertion` | ref:Assertion | 是 | 见引用定义 | 见引用 | 见引用 | variant-5 |
| `event_id` | string | 是 | 1..128 chars | - | "item-01" | variant-6 |
| `at_step` | integer | 是 | 0..4294967295 | model_step | 0 | variant-6 |
| `priority` | integer | 是 | 0..255 | 1 | 100 | variant-6 |
| `link_id` | string | 是 | CANT / CUTIL / SAVVY / CANREPLAY / ETHGEN / ETHREPLAY | - | "CANT" | variant-6 |
| `type` | const | 是 | "REPLAY" | - | "REPLAY" | variant-6 |
| `history_id` | string | 是 | 1..128 chars | - | "item-01" | variant-6 |
| `policy` | ref:ReplayPolicy | 是 | 见引用定义 | 见引用 | 见引用 | variant-6 |
| `event_id` | string | 是 | 1..128 chars | - | "item-01" | variant-7 |
| `at_step` | integer | 是 | 0..4294967295 | model_step | 0 | variant-7 |
| `priority` | integer | 是 | 0..255 | 1 | 100 | variant-7 |
| `link_id` | string | 是 | CANT / CUTIL / SAVVY / CANREPLAY / ETHGEN / ETHREPLAY | - | "CANT" | variant-7 |
| `type` | const | 是 | "FAULT" | - | "FAULT" | variant-7 |
| `stimulus` | ref:Stimulus | 是 | 见引用定义 | 见引用 | 见引用 | variant-7 |
| `event_id` | string | 是 | 1..128 chars | - | "item-01" | variant-8 |
| `at_step` | integer | 是 | 0..4294967295 | model_step | 0 | variant-8 |
| `priority` | integer | 是 | 0..255 | 1 | 100 | variant-8 |
| `link_id` | string | 是 | CANT / CUTIL / SAVVY / CANREPLAY / ETHGEN / ETHREPLAY | - | "CANT" | variant-8 |
| `type` | const | 是 | "ASSERT" | - | "ASSERT" | variant-8 |
| `assertion` | ref:Assertion | 是 | 见引用定义 | 见引用 | 见引用 | variant-8 |
| `event_id` | string | 是 | 1..128 chars | - | "item-01" | variant-9 |
| `at_step` | integer | 是 | 0..4294967295 | model_step | 0 | variant-9 |
| `priority` | integer | 是 | 0..255 | 1 | 100 | variant-9 |
| `link_id` | string | 是 | CANT / CUTIL / SAVVY / CANREPLAY / ETHGEN / ETHREPLAY | - | "CANT" | variant-9 |
| `type` | const | 是 | "END_CLEANUP" | - | "END_CLEANUP" | variant-9 |
| `cleanup` | ref:Cleanup | 是 | 见引用定义 | 见引用 | 见引用 | variant-9 |
| `event_id` | string | 是 | 1..128 chars | - | "item-01" | variant-10 |
| `at_step` | integer | 是 | 0..4294967295 | model_step | 0 | variant-10 |
| `priority` | integer | 是 | 0..255 | 1 | 100 | variant-10 |
| `link_id` | string | 是 | CANT / CUTIL / SAVVY / CANREPLAY / ETHGEN / ETHREPLAY | - | "CANT" | variant-10 |
| `type` | const | 是 | "NEGATIVE_SEND" | - | "NEGATIVE_SEND" | variant-10 |
| `stimulus` | ref:Stimulus | 是 | 见引用定义 | 见引用 | 见引用 | variant-10 |
| `mutation` | ref:NegativeMutation | 是 | 见引用定义 | 见引用 | 见引用 | variant-10 |
| `expected_error` | string | 是 | SCHEMA / VERSION / HASH / AUTHORIZATION / MODEL / CONTROL_OWNER / RANGE / STATE / STALE_SESSION / DUPLICATE / OUT_OF_ORDER / LATE / EXPIRED / BUFFER_FULL / FRAGMENT / CRC / UNSUPPORTED / TARGET_MISSING / TIMEOUT / BUSINESS_FAILED / SAFETY / RESOURCE / CLOCK_UNSYNC / CAPACITY | - | "RANGE" | variant-10 |
| `must_not_apply` | const | 是 | true | - | true | variant-10 |
| `authorization_case_id` | string | 是 | 1..128 chars | - | "T02" | variant-10 |

## ScenarioSource

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `source_type` | const | 是 | "SCENARIO" | - | "SCENARIO" | - |
| `scenario_id` | string | 是 | 1..128 chars | - | "item-01" | - |
| `version` | integer | 是 | 1..4294967295 | 1 | 1 | - |
| `clock` | const | 是 | "MODEL_STEP" | - | "MODEL_STEP" | - |
| `seed` | integer | 是 | 1..4294967295 | 1 | 1 | - |
| `events` | array | 是 | 1..100000 items | - | REQUIRED_CONTENT | - |
| `events[]` | ref:Event | 是 | 见引用定义 | 见引用 | 见引用 | - |
| `collision_policy` | const | 是 | "REJECT_SAME_WRITABLE_TARGET_STEP" | - | "REJECT_SAME_WRITABLE_TARGET_STEP" | - |
| `sort_order` | const | 是 | "STEP_PRIORITY_EVENT_ID_ASC" | - | "STEP_PRIORITY_EVENT_ID_ASC" | - |
| `cleanup` | ref:Cleanup | 是 | 见引用定义 | 见引用 | 见引用 | - |
| `assertions` | array | 是 | 1..10000 items | - | REQUIRED_CONTENT | - |
| `assertions[]` | ref:Assertion | 是 | 见引用定义 | 见引用 | 见引用 | - |

## HistoryStream

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `stream_id` | string | 是 | 1..128 chars | - | "item-01" | - |
| `direction` | string | 是 | TO_36 / FROM_36 | - | "TO_36" | - |
| `original_channel` | string | 是 | CANFD / CAN / ETHERNET / RS232 / RS422 / AD / DA / TTL | - | "CANFD" | - |
| `message_ids` | array | 是 | 0..255 items | - | [] | - |
| `message_ids[]` | integer | 是 | 1..255 | 1 | 1 | - |
| `records` | integer | 是 | 0..9007199254740991 | 1 | 0 | - |
| `clock` | string | 是 | CAPTURE_MONOTONIC / MODEL_STEP / UTC | - | "CAPTURE_MONOTONIC" | - |
| `epoch_ns` | string | 是 | ^(0\|[1-9][0-9]{0,19})$ | - | "0" | - |
| `uncertainty_us` | integer | 是 | 0..10000000 | us | 10000000 | - |
| `truncated_packets` | integer | 是 | 0..9007199254740991 | 1 | 0 | - |
| `lost_packets` | integer | 是 | 0..9007199254740991 | 1 | 0 | - |

## ReplayPolicy

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `mode` | string | 是 | REENCODE / RAW_VALIDATED / SESSION_REBUILD | - | "REENCODE" | - |
| `start_offset_ns` | string | 是 | ^(0\|[1-9][0-9]{0,19})$ | - | "0" | - |
| `end_offset_ns` | string | 是 | ^(0\|[1-9][0-9]{0,19})$ | - | "1000000000" | - |
| `rate` | string | 是 | 1X / 0.5X / 2X / 4X | - | "1X" | - |
| `execution_mode` | string | 是 | ONLINE / OFFLINE | - | "ONLINE" | - |
| `repeat_count` | integer | 是 | 1..10000 | 1 | 1 | - |
| `repeat_gap_steps` | integer | 是 | 0..1000000 | model_step | 100 | - |
| `session_policy` | string | 是 | NEW_SESSION_PER_REPEAT / CURRENT_VALID_SESSION | - | "NEW_SESSION_PER_REPEAT" | - |
| `rewrite_fields` | array | 是 | 0..6 items | - | [] | - |
| `rewrite_fields[]` | string | 是 | SESSION / SEQUENCE / TARGET_STEP / TRANSACTION / SOURCE_ENDPOINT / CRC | - | "SESSION" | - |
| `filter_direction` | const | 是 | "TO_36_ONLY" | - | "TO_36_ONLY" | - |
| `seek_policy` | const | 是 | "OFFLINE_ONLY" | - | "OFFLINE_ONLY" | - |
| `restore_policy` | const | 是 | "RESET_MODEL_AND_CLEAR_QUEUES" | - | "RESET_MODEL_AND_CLEAR_QUEUES" | - |
| `incomplete_capture_policy` | const | 是 | "REJECT_ONLINE" | - | "REJECT_ONLINE" | - |
| `feedback_policy` | const | 是 | "COLLECT_NOT_INJECT" | - | "COLLECT_NOT_INJECT" | - |

## HistorySource

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `source_type` | const | 是 | "HISTORY" | - | "HISTORY" | - |
| `history_id` | string | 是 | 1..128 chars | - | "item-01" | - |
| `resource` | ref:ResourceRef | 是 | 见引用定义 | 见引用 | 见引用 | - |
| `streams` | array | 是 | 1..100 items | - | REQUIRED_CONTENT | - |
| `streams[]` | ref:HistoryStream | 是 | 见引用定义 | 见引用 | 见引用 | - |
| `policy` | ref:ReplayPolicy | 是 | 见引用定义 | 见引用 | 见引用 | - |
| `integrity_verified` | const | 是 | true | - | true | - |
| `decoder_baseline_sha256` | string | 是 | ^[0-9a-f]{64}$ | - | REQUIRED_CONTENT_SHA256 | - |

## SourceInputs

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `baseline_version` | const | 是 | "HIL-ICD-1.0" | - | "HIL-ICD-1.0" | - |
| `baseline_sha256` | string | 是 | ^[0-9a-f]{64}$ | - | REQUIRED_CONTENT_SHA256 | - |
| `protocol` | ref:ProtocolSource | 是 | 见引用定义 | 见引用 | 见引用 | - |
| `scenario` | ref:ScenarioSource | 是 | 见引用定义 | 见引用 | 见引用 | variant-1 |
| `scenario` | null | 是 | - | - | null | variant-2 |
| `history` | ref:HistorySource | 是 | 见引用定义 | 见引用 | 见引用 | variant-1 |
| `history` | null | 是 | - | - | null | variant-2 |

## ManagementUpdateParams

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `run_id` | string | 是 | 1..128 chars | - | "item-01" | - |
| `expected_revision` | string | 是 | ^(0\|[1-9][0-9]{0,19})$ | - | "0" | - |
| `link_id` | string | 是 | CANT / CUTIL / SAVVY / CANREPLAY / ETHGEN / ETHREPLAY | - | "CANT" | - |
| `message` | ref:BusinessInputMessage | 是 | 见引用定义 | 见引用 | 见引用 | - |

## RawBus

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `medium` | const | 是 | "CAN" | - | REQUIRED_EXPLICIT_VALUE | variant-1 |
| `channel_id` | string | 是 | CAN_0 / CAN_1 / CAN_2 / CAN_3 | - | "CAN_0" | variant-1 |
| `can_id` | integer | 是 | 1536..1791 | 1 | 1536 | variant-1 |
| `extended` | const | 是 | false | - | REQUIRED_EXPLICIT_VALUE | variant-1 |
| `rtr` | const | 是 | false | - | REQUIRED_EXPLICIT_VALUE | variant-1 |
| `dlc` | integer | 是 | 1..8 | 1 | 1 | variant-1 |
| `data_hex` | string | 是 | ^(?:[0-9a-f]{2}){1,8}$ | - | "00" | variant-1 |
| `medium` | const | 是 | "CANFD" | - | REQUIRED_EXPLICIT_VALUE | variant-2 |
| `channel_id` | string | 是 | CANFD_0 / CANFD_1 / CANFD_2 / CANFD_3 | - | "CANFD_0" | variant-2 |
| `can_id` | integer | 是 | 1536..1791 | 1 | 1536 | variant-2 |
| `extended` | const | 是 | false | - | REQUIRED_EXPLICIT_VALUE | variant-2 |
| `brs` | const | 是 | true | - | REQUIRED_EXPLICIT_VALUE | variant-2 |
| `data_length` | integer | 是 | 1 / 2 / 3 / 4 / 5 / 6 / 7 / 8 / 12 / 16 / 20 / 24 / 32 / 48 / 64 | 1 | 1 | variant-2 |
| `data_hex` | string | 是 | ^(?:[0-9a-f]{2}){1,64}$ | - | "00" | variant-2 |
| `medium` | const | 是 | "ETHERNET" | - | REQUIRED_EXPLICIT_VALUE | variant-3 |
| `channel_id` | string | 是 | ETH_0 / ETH_1 / ETH_2 / ETH_3 | - | "ETH_0" | variant-3 |
| `destination_udp_port` | const | 是 | 36150 | - | REQUIRED_EXPLICIT_VALUE | variant-3 |
| `payload_hex` | string | 是 | ^(?:[0-9a-f]{2}){1,1200}$ | - | "00" | variant-3 |
| `ttl` | integer | 是 | 1..64 | 1 | 1 | variant-3 |

## ProbeName

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `` | string | 是 | NO_PROBE / fixed_wing_hil.input.flight_control.throttle / fixed_wing_hil.input.flight_control.roll_cmd / fixed_wing_hil.input.flight_control.pitch_cmd / fixed_wing_hil.input.flight_control.yaw_cmd / fixed_wing_hil.input.environment.wind_n_mps / fixed_wing_hil.input.environment.wind_e_mps / fixed_wing_hil.input.environment.wind_d_mps / fixed_wing_hil.input.environment.pressure_pa / fixed_wing_hil.input.environment.temperature_k / fixed_wing_hil.input.environment.ground_height_m / fixed_wing_hil.input.fault.gps_bias_n_m / fixed_wing_hil.input.fault.gps_bias_e_m / fixed_wing_hil.input.fault.gps_bias_d_m / fixed_wing_hil.input.fault.imu_bias_p_radps / fixed_wing_hil.input.fault.imu_bias_q_radps / fixed_wing_hil.input.fault.imu_bias_r_radps / fixed_wing_hil.input.fault.motor_1_failed / fixed_wing_hil.input.fault.motor_2_failed / fixed_wing_hil.input.fault.motor_3_failed / fixed_wing_hil.input.fault.motor_4_failed / fixed_wing_hil.input.fault.command_delay_ms / fixed_wing_hil.input.fault.sensor_delay_ms / fixed_wing_hil.input.fault.packet_loss_ratio / fixed_wing_hil.input.parameters.mass_kg / fixed_wing_hil.input.parameters.inertia_xx_kgm2 / fixed_wing_hil.input.parameters.inertia_yy_kgm2 / fixed_wing_hil.input.parameters.inertia_zz_kgm2 / fixed_wing_hil.input.parameters.linear_drag_ns_m / fixed_wing_hil.input.parameters.angular_drag_nms / fixed_wing_hil.input.parameters.wind_n_bias_mps / fixed_wing_hil.input.parameters.wind_e_bias_mps / fixed_wing_hil.input.parameters.wind_d_bias_mps / fixed_wing_hil.input.parameters.wing_area_m2 / multirotor_6_hil.input.flight_control.motor_command / multirotor_6_hil.input.environment.wind_n_mps / multirotor_6_hil.input.environment.wind_e_mps / multirotor_6_hil.input.environment.wind_d_mps / multirotor_6_hil.input.environment.pressure_pa / multirotor_6_hil.input.environment.temperature_k / multirotor_6_hil.input.environment.ground_height_m / multirotor_6_hil.input.fault.gps_bias_n_m / multirotor_6_hil.input.fault.gps_bias_e_m / multirotor_6_hil.input.fault.gps_bias_d_m / multirotor_6_hil.input.fault.imu_bias_p_radps / multirotor_6_hil.input.fault.imu_bias_q_radps / multirotor_6_hil.input.fault.imu_bias_r_radps / multirotor_6_hil.input.fault.motor_1_failed / multirotor_6_hil.input.fault.motor_2_failed / multirotor_6_hil.input.fault.motor_3_failed / multirotor_6_hil.input.fault.motor_4_failed / multirotor_6_hil.input.fault.command_delay_ms / multirotor_6_hil.input.fault.sensor_delay_ms / multirotor_6_hil.input.fault.packet_loss_ratio / multirotor_6_hil.input.parameters.mass_kg / multirotor_6_hil.input.parameters.inertia_xx_kgm2 / multirotor_6_hil.input.parameters.inertia_yy_kgm2 / multirotor_6_hil.input.parameters.inertia_zz_kgm2 / multirotor_6_hil.input.parameters.linear_drag_ns_m / multirotor_6_hil.input.parameters.angular_drag_nms / multirotor_6_hil.input.parameters.wind_n_bias_mps / multirotor_6_hil.input.parameters.wind_e_bias_mps / multirotor_6_hil.input.parameters.wind_d_bias_mps / multirotor_6_hil.input.parameters.thrust_coefficient_n / quadrotor_hil.input.flight_control.motor_command / quadrotor_hil.input.environment.wind_n_mps / quadrotor_hil.input.environment.wind_e_mps / quadrotor_hil.input.environment.wind_d_mps / quadrotor_hil.input.environment.pressure_pa / quadrotor_hil.input.environment.temperature_k / quadrotor_hil.input.environment.ground_height_m / quadrotor_hil.input.fault.gps_bias_n_m / quadrotor_hil.input.fault.gps_bias_e_m / quadrotor_hil.input.fault.gps_bias_d_m / quadrotor_hil.input.fault.imu_bias_p_radps / quadrotor_hil.input.fault.imu_bias_q_radps / quadrotor_hil.input.fault.imu_bias_r_radps / quadrotor_hil.input.fault.motor_1_failed / quadrotor_hil.input.fault.motor_2_failed / quadrotor_hil.input.fault.motor_3_failed / quadrotor_hil.input.fault.motor_4_failed / quadrotor_hil.input.fault.command_delay_ms / quadrotor_hil.input.fault.sensor_delay_ms / quadrotor_hil.input.fault.packet_loss_ratio / quadrotor_hil.input.parameters.mass_kg / quadrotor_hil.input.parameters.inertia_xx_kgm2 / quadrotor_hil.input.parameters.inertia_yy_kgm2 / quadrotor_hil.input.parameters.inertia_zz_kgm2 / quadrotor_hil.input.parameters.thrust_coefficient_n / quadrotor_hil.input.parameters.moment_coefficient_nm / quadrotor_hil.input.parameters.linear_drag_ns_m / quadrotor_hil.input.parameters.angular_drag_nms / quadrotor_hil.input.parameters.wind_n_bias_mps / quadrotor_hil.input.parameters.wind_e_bias_mps / quadrotor_hil.input.parameters.wind_d_bias_mps / quadrotor_hil.input.parameters.motor_efficiency / multirotor_6_hil.input.fault.motor_5_failed / multirotor_6_hil.input.fault.motor_6_failed / consumer.SessionOpen / consumer.Heartbeat / consumer.RunConfigure / consumer.Lifecycle / consumer.InitialState / consumer.ControlOwner / consumer.FlightQuad / consumer.FlightHex / consumer.FlightFixed / consumer.Environment / consumer.FaultQuad / consumer.FaultHex / consumer.FaultFixed / consumer.ActuatorQuad / consumer.ActuatorHex / consumer.ActuatorFixed / consumer.TuneQuad / consumer.TuneHex / consumer.TuneFixed / consumer.MissionLoad / consumer.MissionControl / consumer.FlightCommand / consumer.Targets / consumer.EnvironmentExt / consumer.SystemStimulus / consumer.BusFault / consumer.SerialWrite / consumer.AnalogWrite / consumer.DigitalWrite / consumer.VideoConfig / consumer.VideoControl / consumer.VideoAnnotation / consumer.ClockSync / consumer.ResourceChunk / consumer.Query / consumer.RecordControl / consumer.Cleanup / consumer.SessionClose / consumer.SensorConfig / consumer.PhysicalChannelConfig / consumer.Terrain / consumer.Obstacles / consumer.VideoFrameMetadata / consumer.SessionOpened / consumer.Ack / consumer.Status / consumer.State / consumer.Sensors / consumer.IOStatus / consumer.VideoStatus / consumer.TaskStatus / consumer.RecordStatus / consumer.Diagnostic / consumer.Capabilities / consumer.Evidence / consumer.ResourceAck / consumer.ClockStatus / consumer.RawBus / consumer.SensorFault | - | "NO_PROBE" | - |

## InitialInputs

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `model_id` | const | 是 | "quadrotor_hil" | - | "quadrotor_hil" | variant-1 |
| `flight_control` | ref:FlightQuad | 是 | 见引用定义 | 见引用 | 见引用 | variant-1 |
| `environment` | ref:Environment | 是 | 见引用定义 | 见引用 | 见引用 | variant-1 |
| `fault` | ref:FaultQuad | 是 | 见引用定义 | 见引用 | 见引用 | variant-1 |
| `parameters` | ref:TuneQuad | 是 | 见引用定义 | 见引用 | 见引用 | variant-1 |
| `environment_ext` | ref:EnvironmentExt | 是 | 见引用定义 | 见引用 | 见引用 | variant-1 |
| `system_stimulus` | ref:SystemStimulus | 是 | 见引用定义 | 见引用 | 见引用 | variant-1 |
| `sensor_fault` | ref:SensorFault | 是 | 见引用定义 | 见引用 | 见引用 | variant-1 |
| `model_id` | const | 是 | "multirotor_6_hil" | - | "multirotor_6_hil" | variant-2 |
| `flight_control` | ref:FlightHex | 是 | 见引用定义 | 见引用 | 见引用 | variant-2 |
| `environment` | ref:Environment | 是 | 见引用定义 | 见引用 | 见引用 | variant-2 |
| `fault` | ref:FaultHex | 是 | 见引用定义 | 见引用 | 见引用 | variant-2 |
| `parameters` | ref:TuneHex | 是 | 见引用定义 | 见引用 | 见引用 | variant-2 |
| `environment_ext` | ref:EnvironmentExt | 是 | 见引用定义 | 见引用 | 见引用 | variant-2 |
| `system_stimulus` | ref:SystemStimulus | 是 | 见引用定义 | 见引用 | 见引用 | variant-2 |
| `sensor_fault` | ref:SensorFault | 是 | 见引用定义 | 见引用 | 见引用 | variant-2 |
| `model_id` | const | 是 | "fixed_wing_hil" | - | "fixed_wing_hil" | variant-3 |
| `flight_control` | ref:FlightFixed | 是 | 见引用定义 | 见引用 | 见引用 | variant-3 |
| `environment` | ref:Environment | 是 | 见引用定义 | 见引用 | 见引用 | variant-3 |
| `fault` | ref:FaultFixed | 是 | 见引用定义 | 见引用 | 见引用 | variant-3 |
| `parameters` | ref:TuneFixed | 是 | 见引用定义 | 见引用 | 见引用 | variant-3 |
| `environment_ext` | ref:EnvironmentExt | 是 | 见引用定义 | 见引用 | 见引用 | variant-3 |
| `system_stimulus` | ref:SystemStimulus | 是 | 见引用定义 | 见引用 | 见引用 | variant-3 |
| `sensor_fault` | ref:SensorFault | 是 | 见引用定义 | 见引用 | 见引用 | variant-3 |

## SensorFault

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `gps_valid` | boolean | 是 | - | bool | true | - |
| `gps_fix_type` | string | 是 | NO_FIX / FIX_2D / FIX_3D | - | "FIX_3D" | - |
| `gps_freeze` | boolean | 是 | - | bool | false | - |
| `gps_stale_ms` | integer | 是 | 0..1000 | ms | 0 | - |
| `imu_valid` | boolean | 是 | - | bool | true | - |
| `imu_freeze` | boolean | 是 | - | bool | false | - |
| `imu_stale_ms` | integer | 是 | 0..1000 | ms | 0 | - |
| `magnetometer_valid` | boolean | 是 | - | bool | true | - |
| `barometer_valid` | boolean | 是 | - | bool | true | - |
| `duration_steps` | integer | 是 | 0..86400000 | model_step | 0 | - |
| `clear_at_end` | boolean | 是 | - | bool | true | - |

## NegativeMutation

| 字段路径 | 类型/引用 | 必填 | 范围/枚举 | 单位 | 初值/赋值规则 | 分支 |
|---|---|---|---|---|---|---|
| `kind` | const | 是 | "PATCH_VALUE" | - | REQUIRED_EXPLICIT_VALUE | variant-1 |
| `field_path` | string | 是 | 1..512 chars | - | "wind_n_mps" | variant-1 |
| `value` | number | 是 | -100000000000000000000..100000000000000000000 | TARGET_UNIT | 1000000 | variant-1/variant-1 |
| `value` | string | 是 | 0..256 chars | - | "invalid" | variant-1/variant-2 |
| `value` | boolean | 是 | - | bool | false | variant-1/variant-3 |
| `kind` | const | 是 | "DROP_FIELD" | - | REQUIRED_EXPLICIT_VALUE | variant-2 |
| `field_path` | string | 是 | 1..512 chars | - | "wind_n_mps" | variant-2 |
| `kind` | const | 是 | "ADD_UNKNOWN_FIELD" | - | REQUIRED_EXPLICIT_VALUE | variant-3 |
| `field_path` | string | 是 | 1..512 chars | - | "unexpected_input" | variant-3 |
| `value` | number | 是 | -100000000000000000000..100000000000000000000 | TARGET_UNIT | 1 | variant-3/variant-1 |
| `value` | string | 是 | 0..256 chars | - | "invalid" | variant-3/variant-2 |
| `value` | boolean | 是 | - | bool | false | variant-3/variant-3 |
| `kind` | const | 是 | "CRC_XOR" | - | REQUIRED_EXPLICIT_VALUE | variant-4 |
| `xor_mask` | integer | 是 | 1..255 | 1 | 1 | variant-4 |
| `kind` | const | 是 | "SEQUENCE_OVERRIDE" | - | REQUIRED_EXPLICIT_VALUE | variant-5 |
| `sequence` | integer | 是 | 0..4294967295 | 1 | 0 | variant-5 |
| `kind` | const | 是 | "SESSION_OVERRIDE" | - | REQUIRED_EXPLICIT_VALUE | variant-6 |
| `session_id` | integer | 是 | 0..4294967295 | 1 | 0 | variant-6 |
| `kind` | const | 是 | "TARGET_STEP_OVERRIDE" | - | REQUIRED_EXPLICIT_VALUE | variant-7 |
| `target_step` | integer | 是 | 0..4294967295 | 1 | 0 | variant-7 |
| `kind` | const | 是 | "TRUNCATE" | - | REQUIRED_EXPLICIT_VALUE | variant-8 |
| `remove_tail_bytes` | integer | 是 | 1..1200 | 1 | 1 | variant-8 |
| `kind` | const | 是 | "F64_BITS" | - | REQUIRED_EXPLICIT_VALUE | variant-9 |
| `field_path` | string | 是 | 1..512 chars | - | "wind_n_mps" | variant-9 |
| `bits_hex_le` | string | 是 | ^[0-9a-f]{16}$ | - | "000000000000f87f" | variant-9 |

## 模型端口与参数绑定

| 模型 | 输入路径 | 字段/符号 | 类型×维数 | 单位 | 范围 | 初值 | 应用/安全 | 现有实现状态 |
|---|---|---|---|---|---|---|---|---|
| fixed_wing_hil | `flight_control.throttle` | `throttle` | double×1 | 1 | 0..1 | 0 | TARGET_MODEL_STEP / ZERO_ON_100MS_TIMEOUT | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| fixed_wing_hil | `flight_control.roll_cmd` | `roll_cmd` | double×1 | 1 | -1..1 | 0 | TARGET_MODEL_STEP / ZERO_ON_100MS_TIMEOUT | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| fixed_wing_hil | `flight_control.pitch_cmd` | `pitch_cmd` | double×1 | 1 | -1..1 | 0 | TARGET_MODEL_STEP / ZERO_ON_100MS_TIMEOUT | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| fixed_wing_hil | `flight_control.yaw_cmd` | `yaw_cmd` | double×1 | 1 | -1..1 | 0 | TARGET_MODEL_STEP / ZERO_ON_100MS_TIMEOUT | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| fixed_wing_hil | `environment.wind_n_mps` | `wind_n_mps` | double×1 | m/s | -50..50 | 0 | TARGET_MODEL_STEP / RESTORE_CONFIGURED_DEFAULT_ON_SESSION_END | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| fixed_wing_hil | `environment.wind_e_mps` | `wind_e_mps` | double×1 | m/s | -50..50 | 0 | TARGET_MODEL_STEP / RESTORE_CONFIGURED_DEFAULT_ON_SESSION_END | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| fixed_wing_hil | `environment.wind_d_mps` | `wind_d_mps` | double×1 | m/s | -50..50 | 0 | TARGET_MODEL_STEP / RESTORE_CONFIGURED_DEFAULT_ON_SESSION_END | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| fixed_wing_hil | `environment.pressure_pa` | `pressure_pa` | double×1 | Pa | 1000..120000 | 101325 | TARGET_MODEL_STEP / RESTORE_CONFIGURED_DEFAULT_ON_SESSION_END | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| fixed_wing_hil | `environment.temperature_k` | `temperature_k` | double×1 | K | 150..350 | 288.15 | TARGET_MODEL_STEP / RESTORE_CONFIGURED_DEFAULT_ON_SESSION_END | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| fixed_wing_hil | `environment.ground_height_m` | `ground_height_m` | double×1 | m | -1000..10000 | 0 | TARGET_MODEL_STEP / RESTORE_CONFIGURED_DEFAULT_ON_SESSION_END | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| fixed_wing_hil | `fault.gps_bias_n_m` | `gps_bias_n_m` | double×1 | m | -1000..1000 | 0 | TARGET_MODEL_STEP / CLEAR_ON_CLEANUP | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| fixed_wing_hil | `fault.gps_bias_e_m` | `gps_bias_e_m` | double×1 | m | -1000..1000 | 0 | TARGET_MODEL_STEP / CLEAR_ON_CLEANUP | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| fixed_wing_hil | `fault.gps_bias_d_m` | `gps_bias_d_m` | double×1 | m | -1000..1000 | 0 | TARGET_MODEL_STEP / CLEAR_ON_CLEANUP | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| fixed_wing_hil | `fault.imu_bias_p_radps` | `imu_bias_p_radps` | double×1 | rad/s | -10..10 | 0 | TARGET_MODEL_STEP / CLEAR_ON_CLEANUP | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| fixed_wing_hil | `fault.imu_bias_q_radps` | `imu_bias_q_radps` | double×1 | rad/s | -10..10 | 0 | TARGET_MODEL_STEP / CLEAR_ON_CLEANUP | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| fixed_wing_hil | `fault.imu_bias_r_radps` | `imu_bias_r_radps` | double×1 | rad/s | -10..10 | 0 | TARGET_MODEL_STEP / CLEAR_ON_CLEANUP | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| fixed_wing_hil | `fault.motor_1_failed` | `motor_1_failed` | bool×1 | bool | 0..1 | false | TARGET_MODEL_STEP / CLEAR_ON_CLEANUP | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| fixed_wing_hil | `fault.motor_2_failed` | `motor_2_failed` | bool×1 | bool | 0..1 | false | TARGET_MODEL_STEP / CLEAR_ON_CLEANUP | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| fixed_wing_hil | `fault.motor_3_failed` | `motor_3_failed` | bool×1 | bool | 0..1 | false | TARGET_MODEL_STEP / CLEAR_ON_CLEANUP | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| fixed_wing_hil | `fault.motor_4_failed` | `motor_4_failed` | bool×1 | bool | 0..1 | false | TARGET_MODEL_STEP / CLEAR_ON_CLEANUP | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| fixed_wing_hil | `fault.command_delay_ms` | `command_delay_ms` | double×1 | ms | 0..1000 | 0 | TARGET_MODEL_STEP / CLEAR_ON_CLEANUP | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| fixed_wing_hil | `fault.sensor_delay_ms` | `sensor_delay_ms` | double×1 | ms | 0..1000 | 0 | TARGET_MODEL_STEP / CLEAR_ON_CLEANUP | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| fixed_wing_hil | `fault.packet_loss_ratio` | `packet_loss_ratio` | double×1 | 1 | 0..1 | 0 | TARGET_MODEL_STEP / CLEAR_ON_CLEANUP | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| fixed_wing_hil | `parameters.mass_kg` | `uav_mass_kg` | double×1 | kg | 0.1..100 | 2 | TARGET_MODEL_STEP / RESTORE_INITIAL_ON_RESET | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| fixed_wing_hil | `parameters.inertia_xx_kgm2` | `uav_inertia_xx_kgm2` | double×1 | kg*m2 | 0.0001..10 | 0.03 | TARGET_MODEL_STEP / RESTORE_INITIAL_ON_RESET | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| fixed_wing_hil | `parameters.inertia_yy_kgm2` | `uav_inertia_yy_kgm2` | double×1 | kg*m2 | 0.0001..10 | 0.03 | TARGET_MODEL_STEP / RESTORE_INITIAL_ON_RESET | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| fixed_wing_hil | `parameters.inertia_zz_kgm2` | `uav_inertia_zz_kgm2` | double×1 | kg*m2 | 0.0001..10 | 0.05 | TARGET_MODEL_STEP / RESTORE_INITIAL_ON_RESET | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| fixed_wing_hil | `parameters.linear_drag_ns_m` | `uav_linear_drag_ns_m` | double×1 | N*s/m | 0..100 | 0.2 | TARGET_MODEL_STEP / RESTORE_INITIAL_ON_RESET | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| fixed_wing_hil | `parameters.angular_drag_nms` | `uav_angular_drag_nms` | double×1 | N*m*s | 0..100 | 0.02 | TARGET_MODEL_STEP / RESTORE_INITIAL_ON_RESET | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| fixed_wing_hil | `parameters.wind_n_bias_mps` | `uav_wind_n_bias_mps` | double×1 | m/s | -50..50 | 0 | TARGET_MODEL_STEP / RESTORE_INITIAL_ON_RESET | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| fixed_wing_hil | `parameters.wind_e_bias_mps` | `uav_wind_e_bias_mps` | double×1 | m/s | -50..50 | 0 | TARGET_MODEL_STEP / RESTORE_INITIAL_ON_RESET | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| fixed_wing_hil | `parameters.wind_d_bias_mps` | `uav_wind_d_bias_mps` | double×1 | m/s | -50..50 | 0 | TARGET_MODEL_STEP / RESTORE_INITIAL_ON_RESET | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| fixed_wing_hil | `parameters.wing_area_m2` | `uav_wing_area_m2` | double×1 | m2 | 0.01..20 | 0.25 | TARGET_MODEL_STEP / RESTORE_INITIAL_ON_RESET | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| multirotor_6_hil | `flight_control.motor_command` | `motor_command` | double×6 | 1 | 0..1 | [0,0,0,0,0,0] | TARGET_MODEL_STEP / ZERO_ON_100MS_TIMEOUT | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| multirotor_6_hil | `environment.wind_n_mps` | `wind_n_mps` | double×1 | m/s | -50..50 | 0 | TARGET_MODEL_STEP / RESTORE_CONFIGURED_DEFAULT_ON_SESSION_END | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| multirotor_6_hil | `environment.wind_e_mps` | `wind_e_mps` | double×1 | m/s | -50..50 | 0 | TARGET_MODEL_STEP / RESTORE_CONFIGURED_DEFAULT_ON_SESSION_END | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| multirotor_6_hil | `environment.wind_d_mps` | `wind_d_mps` | double×1 | m/s | -50..50 | 0 | TARGET_MODEL_STEP / RESTORE_CONFIGURED_DEFAULT_ON_SESSION_END | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| multirotor_6_hil | `environment.pressure_pa` | `pressure_pa` | double×1 | Pa | 1000..120000 | 101325 | TARGET_MODEL_STEP / RESTORE_CONFIGURED_DEFAULT_ON_SESSION_END | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| multirotor_6_hil | `environment.temperature_k` | `temperature_k` | double×1 | K | 150..350 | 288.15 | TARGET_MODEL_STEP / RESTORE_CONFIGURED_DEFAULT_ON_SESSION_END | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| multirotor_6_hil | `environment.ground_height_m` | `ground_height_m` | double×1 | m | -1000..10000 | 0 | TARGET_MODEL_STEP / RESTORE_CONFIGURED_DEFAULT_ON_SESSION_END | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| multirotor_6_hil | `fault.gps_bias_n_m` | `gps_bias_n_m` | double×1 | m | -1000..1000 | 0 | TARGET_MODEL_STEP / CLEAR_ON_CLEANUP | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| multirotor_6_hil | `fault.gps_bias_e_m` | `gps_bias_e_m` | double×1 | m | -1000..1000 | 0 | TARGET_MODEL_STEP / CLEAR_ON_CLEANUP | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| multirotor_6_hil | `fault.gps_bias_d_m` | `gps_bias_d_m` | double×1 | m | -1000..1000 | 0 | TARGET_MODEL_STEP / CLEAR_ON_CLEANUP | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| multirotor_6_hil | `fault.imu_bias_p_radps` | `imu_bias_p_radps` | double×1 | rad/s | -10..10 | 0 | TARGET_MODEL_STEP / CLEAR_ON_CLEANUP | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| multirotor_6_hil | `fault.imu_bias_q_radps` | `imu_bias_q_radps` | double×1 | rad/s | -10..10 | 0 | TARGET_MODEL_STEP / CLEAR_ON_CLEANUP | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| multirotor_6_hil | `fault.imu_bias_r_radps` | `imu_bias_r_radps` | double×1 | rad/s | -10..10 | 0 | TARGET_MODEL_STEP / CLEAR_ON_CLEANUP | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| multirotor_6_hil | `fault.motor_1_failed` | `motor_1_failed` | bool×1 | bool | 0..1 | false | TARGET_MODEL_STEP / CLEAR_ON_CLEANUP | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| multirotor_6_hil | `fault.motor_2_failed` | `motor_2_failed` | bool×1 | bool | 0..1 | false | TARGET_MODEL_STEP / CLEAR_ON_CLEANUP | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| multirotor_6_hil | `fault.motor_3_failed` | `motor_3_failed` | bool×1 | bool | 0..1 | false | TARGET_MODEL_STEP / CLEAR_ON_CLEANUP | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| multirotor_6_hil | `fault.motor_4_failed` | `motor_4_failed` | bool×1 | bool | 0..1 | false | TARGET_MODEL_STEP / CLEAR_ON_CLEANUP | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| multirotor_6_hil | `fault.command_delay_ms` | `command_delay_ms` | double×1 | ms | 0..1000 | 0 | TARGET_MODEL_STEP / CLEAR_ON_CLEANUP | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| multirotor_6_hil | `fault.sensor_delay_ms` | `sensor_delay_ms` | double×1 | ms | 0..1000 | 0 | TARGET_MODEL_STEP / CLEAR_ON_CLEANUP | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| multirotor_6_hil | `fault.packet_loss_ratio` | `packet_loss_ratio` | double×1 | 1 | 0..1 | 0 | TARGET_MODEL_STEP / CLEAR_ON_CLEANUP | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| multirotor_6_hil | `parameters.mass_kg` | `uav_mass_kg` | double×1 | kg | 0.1..100 | 2 | TARGET_MODEL_STEP / RESTORE_INITIAL_ON_RESET | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| multirotor_6_hil | `parameters.inertia_xx_kgm2` | `uav_inertia_xx_kgm2` | double×1 | kg*m2 | 0.0001..10 | 0.03 | TARGET_MODEL_STEP / RESTORE_INITIAL_ON_RESET | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| multirotor_6_hil | `parameters.inertia_yy_kgm2` | `uav_inertia_yy_kgm2` | double×1 | kg*m2 | 0.0001..10 | 0.03 | TARGET_MODEL_STEP / RESTORE_INITIAL_ON_RESET | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| multirotor_6_hil | `parameters.inertia_zz_kgm2` | `uav_inertia_zz_kgm2` | double×1 | kg*m2 | 0.0001..10 | 0.05 | TARGET_MODEL_STEP / RESTORE_INITIAL_ON_RESET | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| multirotor_6_hil | `parameters.linear_drag_ns_m` | `uav_linear_drag_ns_m` | double×1 | N*s/m | 0..100 | 0.2 | TARGET_MODEL_STEP / RESTORE_INITIAL_ON_RESET | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| multirotor_6_hil | `parameters.angular_drag_nms` | `uav_angular_drag_nms` | double×1 | N*m*s | 0..100 | 0.02 | TARGET_MODEL_STEP / RESTORE_INITIAL_ON_RESET | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| multirotor_6_hil | `parameters.wind_n_bias_mps` | `uav_wind_n_bias_mps` | double×1 | m/s | -50..50 | 0 | TARGET_MODEL_STEP / RESTORE_INITIAL_ON_RESET | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| multirotor_6_hil | `parameters.wind_e_bias_mps` | `uav_wind_e_bias_mps` | double×1 | m/s | -50..50 | 0 | TARGET_MODEL_STEP / RESTORE_INITIAL_ON_RESET | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| multirotor_6_hil | `parameters.wind_d_bias_mps` | `uav_wind_d_bias_mps` | double×1 | m/s | -50..50 | 0 | TARGET_MODEL_STEP / RESTORE_INITIAL_ON_RESET | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| multirotor_6_hil | `parameters.thrust_coefficient_n` | `uav_thrust_coefficient_n` | double×1 | N | 0.01..100 | 4.2 | TARGET_MODEL_STEP / RESTORE_INITIAL_ON_RESET | CURRENT_DECLARATION_REQUIRES_BEHAVIOR_QUALIFICATION |
| quadrotor_hil | `flight_control.motor_command` | `motor_command` | double×4 | 1 | 0..1 | [0,0,0,0] | TARGET_MODEL_STEP / ZERO_ON_100MS_TIMEOUT | CURRENT_TEMPLATE_REQUIRES_BEHAVIOR_QUALIFICATION |
| quadrotor_hil | `environment.wind_n_mps` | `wind_n_mps` | double×1 | m/s | -50..50 | 0 | TARGET_MODEL_STEP / RESTORE_CONFIGURED_DEFAULT_ON_SESSION_END | CURRENT_TEMPLATE_REQUIRES_BEHAVIOR_QUALIFICATION |
| quadrotor_hil | `environment.wind_e_mps` | `wind_e_mps` | double×1 | m/s | -50..50 | 0 | TARGET_MODEL_STEP / RESTORE_CONFIGURED_DEFAULT_ON_SESSION_END | CURRENT_TEMPLATE_REQUIRES_BEHAVIOR_QUALIFICATION |
| quadrotor_hil | `environment.wind_d_mps` | `wind_d_mps` | double×1 | m/s | -50..50 | 0 | TARGET_MODEL_STEP / RESTORE_CONFIGURED_DEFAULT_ON_SESSION_END | CURRENT_TEMPLATE_REQUIRES_BEHAVIOR_QUALIFICATION |
| quadrotor_hil | `environment.pressure_pa` | `pressure_pa` | double×1 | Pa | 1000..120000 | 101325 | TARGET_MODEL_STEP / RESTORE_CONFIGURED_DEFAULT_ON_SESSION_END | CURRENT_TEMPLATE_REQUIRES_BEHAVIOR_QUALIFICATION |
| quadrotor_hil | `environment.temperature_k` | `temperature_k` | double×1 | K | 150..350 | 288.15 | TARGET_MODEL_STEP / RESTORE_CONFIGURED_DEFAULT_ON_SESSION_END | CURRENT_TEMPLATE_REQUIRES_BEHAVIOR_QUALIFICATION |
| quadrotor_hil | `environment.ground_height_m` | `ground_height_m` | double×1 | m | -1000..10000 | 0 | TARGET_MODEL_STEP / RESTORE_CONFIGURED_DEFAULT_ON_SESSION_END | CURRENT_TEMPLATE_REQUIRES_BEHAVIOR_QUALIFICATION |
| quadrotor_hil | `fault.gps_bias_n_m` | `gps_bias_n_m` | double×1 | m | -1000..1000 | 0 | TARGET_MODEL_STEP / CLEAR_ON_CLEANUP | CURRENT_TEMPLATE_REQUIRES_BEHAVIOR_QUALIFICATION |
| quadrotor_hil | `fault.gps_bias_e_m` | `gps_bias_e_m` | double×1 | m | -1000..1000 | 0 | TARGET_MODEL_STEP / CLEAR_ON_CLEANUP | CURRENT_TEMPLATE_REQUIRES_BEHAVIOR_QUALIFICATION |
| quadrotor_hil | `fault.gps_bias_d_m` | `gps_bias_d_m` | double×1 | m | -1000..1000 | 0 | TARGET_MODEL_STEP / CLEAR_ON_CLEANUP | CURRENT_TEMPLATE_REQUIRES_BEHAVIOR_QUALIFICATION |
| quadrotor_hil | `fault.imu_bias_p_radps` | `imu_bias_p_radps` | double×1 | rad/s | -10..10 | 0 | TARGET_MODEL_STEP / CLEAR_ON_CLEANUP | CURRENT_TEMPLATE_REQUIRES_BEHAVIOR_QUALIFICATION |
| quadrotor_hil | `fault.imu_bias_q_radps` | `imu_bias_q_radps` | double×1 | rad/s | -10..10 | 0 | TARGET_MODEL_STEP / CLEAR_ON_CLEANUP | CURRENT_TEMPLATE_REQUIRES_BEHAVIOR_QUALIFICATION |
| quadrotor_hil | `fault.imu_bias_r_radps` | `imu_bias_r_radps` | double×1 | rad/s | -10..10 | 0 | TARGET_MODEL_STEP / CLEAR_ON_CLEANUP | CURRENT_TEMPLATE_REQUIRES_BEHAVIOR_QUALIFICATION |
| quadrotor_hil | `fault.motor_1_failed` | `motor_1_failed` | bool×1 | bool | 0..1 | false | TARGET_MODEL_STEP / CLEAR_ON_CLEANUP | CURRENT_TEMPLATE_REQUIRES_BEHAVIOR_QUALIFICATION |
| quadrotor_hil | `fault.motor_2_failed` | `motor_2_failed` | bool×1 | bool | 0..1 | false | TARGET_MODEL_STEP / CLEAR_ON_CLEANUP | CURRENT_TEMPLATE_REQUIRES_BEHAVIOR_QUALIFICATION |
| quadrotor_hil | `fault.motor_3_failed` | `motor_3_failed` | bool×1 | bool | 0..1 | false | TARGET_MODEL_STEP / CLEAR_ON_CLEANUP | CURRENT_TEMPLATE_REQUIRES_BEHAVIOR_QUALIFICATION |
| quadrotor_hil | `fault.motor_4_failed` | `motor_4_failed` | bool×1 | bool | 0..1 | false | TARGET_MODEL_STEP / CLEAR_ON_CLEANUP | CURRENT_TEMPLATE_REQUIRES_BEHAVIOR_QUALIFICATION |
| quadrotor_hil | `fault.command_delay_ms` | `command_delay_ms` | double×1 | ms | 0..1000 | 0 | TARGET_MODEL_STEP / CLEAR_ON_CLEANUP | CURRENT_TEMPLATE_REQUIRES_BEHAVIOR_QUALIFICATION |
| quadrotor_hil | `fault.sensor_delay_ms` | `sensor_delay_ms` | double×1 | ms | 0..1000 | 0 | TARGET_MODEL_STEP / CLEAR_ON_CLEANUP | CURRENT_TEMPLATE_REQUIRES_BEHAVIOR_QUALIFICATION |
| quadrotor_hil | `fault.packet_loss_ratio` | `packet_loss_ratio` | double×1 | 1 | 0..1 | 0 | TARGET_MODEL_STEP / CLEAR_ON_CLEANUP | CURRENT_TEMPLATE_REQUIRES_BEHAVIOR_QUALIFICATION |
| quadrotor_hil | `parameters.mass_kg` | `uav_mass_kg` | double×1 | kg | 0.2..25 | 1.5 | TARGET_MODEL_STEP / RESTORE_INITIAL_ON_RESET | CURRENT_TEMPLATE_REQUIRES_BEHAVIOR_QUALIFICATION |
| quadrotor_hil | `parameters.inertia_xx_kgm2` | `uav_inertia_xx_kgm2` | double×1 | kg*m2 | 0.001..2 | 0.029 | TARGET_MODEL_STEP / RESTORE_INITIAL_ON_RESET | CURRENT_TEMPLATE_REQUIRES_BEHAVIOR_QUALIFICATION |
| quadrotor_hil | `parameters.inertia_yy_kgm2` | `uav_inertia_yy_kgm2` | double×1 | kg*m2 | 0.001..2 | 0.029 | TARGET_MODEL_STEP / RESTORE_INITIAL_ON_RESET | CURRENT_TEMPLATE_REQUIRES_BEHAVIOR_QUALIFICATION |
| quadrotor_hil | `parameters.inertia_zz_kgm2` | `uav_inertia_zz_kgm2` | double×1 | kg*m2 | 0.001..4 | 0.055 | TARGET_MODEL_STEP / RESTORE_INITIAL_ON_RESET | CURRENT_TEMPLATE_REQUIRES_BEHAVIOR_QUALIFICATION |
| quadrotor_hil | `parameters.thrust_coefficient_n` | `uav_thrust_coefficient_n` | double×1 | N | 0.5..20 | 4.2 | TARGET_MODEL_STEP / RESTORE_INITIAL_ON_RESET | CURRENT_TEMPLATE_REQUIRES_BEHAVIOR_QUALIFICATION |
| quadrotor_hil | `parameters.moment_coefficient_nm` | `uav_moment_coefficient_nm` | double×1 | N*m | 0.001..2 | 0.08 | TARGET_MODEL_STEP / RESTORE_INITIAL_ON_RESET | CURRENT_TEMPLATE_REQUIRES_BEHAVIOR_QUALIFICATION |
| quadrotor_hil | `parameters.linear_drag_ns_m` | `uav_linear_drag_ns_m` | double×1 | N*s/m | 0..20 | 0.25 | TARGET_MODEL_STEP / RESTORE_INITIAL_ON_RESET | CURRENT_TEMPLATE_REQUIRES_BEHAVIOR_QUALIFICATION |
| quadrotor_hil | `parameters.angular_drag_nms` | `uav_angular_drag_nms` | double×1 | N*m*s | 0..5 | 0.02 | TARGET_MODEL_STEP / RESTORE_INITIAL_ON_RESET | CURRENT_TEMPLATE_REQUIRES_BEHAVIOR_QUALIFICATION |
| quadrotor_hil | `parameters.wind_n_bias_mps` | `uav_wind_n_bias_mps` | double×1 | m/s | -30..30 | 0 | TARGET_MODEL_STEP / RESTORE_INITIAL_ON_RESET | CURRENT_TEMPLATE_REQUIRES_BEHAVIOR_QUALIFICATION |
| quadrotor_hil | `parameters.wind_e_bias_mps` | `uav_wind_e_bias_mps` | double×1 | m/s | -30..30 | 0 | TARGET_MODEL_STEP / RESTORE_INITIAL_ON_RESET | CURRENT_TEMPLATE_REQUIRES_BEHAVIOR_QUALIFICATION |
| quadrotor_hil | `parameters.wind_d_bias_mps` | `uav_wind_d_bias_mps` | double×1 | m/s | -30..30 | 0 | TARGET_MODEL_STEP / RESTORE_INITIAL_ON_RESET | CURRENT_TEMPLATE_REQUIRES_BEHAVIOR_QUALIFICATION |
| quadrotor_hil | `parameters.motor_efficiency` | `uav_motor_efficiency` | double×1 | 1 | 0.2..1.2 | 1 | TARGET_MODEL_STEP / RESTORE_INITIAL_ON_RESET | CURRENT_TEMPLATE_REQUIRES_BEHAVIOR_QUALIFICATION |
| multirotor_6_hil | `fault.motor_5_failed` | `motor_5_failed` | bool×1 | bool | 0..1 | false | TARGET_MODEL_STEP / CLEAR_ON_CLEANUP | REQUIRED_IMPLEMENTATION |
| multirotor_6_hil | `fault.motor_6_failed` | `motor_6_failed` | bool×1 | bool | 0..1 | false | TARGET_MODEL_STEP / CLEAR_ON_CLEANUP | REQUIRED_IMPLEMENTATION |
