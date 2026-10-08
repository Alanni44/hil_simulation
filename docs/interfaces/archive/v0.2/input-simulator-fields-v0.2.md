# 输入模拟器逐字段索引

版本：0.2。与两份同版本Schema配套，所有字段的精确定义以Schema及《完整数据契约》的业务约束共同为准。

以下列出全部对象的直接字段。必填表示本对象required中的静态约束；条件必填、状态转换和跨引用规则须同时阅读Schema的allOf/oneOf及主文档。nullable只允许已声明不适用的空值，不能掩盖待确认定义。

## 资源与测试包

### Id

类型：string。minLength=1；maxLength=128

### UInt64

类型：string。pattern="^(0\|[1-9][0-9]{0,19})$"；Decimal uint64; runtime also checks maximum 18446744073709551615.

### PositiveUInt64

类型：string。pattern="^[1-9][0-9]{0,19}$"；Decimal uint64; runtime also checks maximum 18446744073709551615.

### Hash

类型：string。pattern="^[0-9a-f]{64}$"

### Value

类型：number 或 boolean 或 string 或 number[]。

### Values

类型：键值对象（值：`Value`）。

### ResourceRef

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| resource_id | string | 是 | minLength=1；maxLength=128 |
| sha256 | `Hash` | 是 |  |

### ProfileRef

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| profile_id | string | 是 | minLength=1；maxLength=128 |
| version | string | 是 | minLength=1；maxLength=128 |
| profile_hash | `Hash` | 是 |  |

### ScenarioRef

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| scenario_id | string | 是 | minLength=1；maxLength=128 |
| revision | string | 是 | pattern="^(0\|[1-9][0-9]{0,19})$"；Decimal uint64; runtime also checks maximum 18446744073709551615. |
| scenario_hash | `Hash` | 是 |  |

### PackageRef

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| package_id | string | 是 | minLength=1；maxLength=128 |
| revision | string | 是 | pattern="^(0\|[1-9][0-9]{0,19})$"；Decimal uint64; runtime also checks maximum 18446744073709551615. |
| package_hash | `Hash` | 是 |  |

### Pending

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| status | `"PENDING"` | 是 |  |
| pending_fields | string[] | 是 | minItems=1；maxItems=10000 |
| reason | string | 是 | minLength=1；maxLength=1024 |

### Rule

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| rule_id | string | 是 | minLength=1；maxLength=128 |
| kind | `CRC` / `COUNTER` / `SESSION` / `AUTH` / `MULTIFRAME` / `DEDUP` / `SYNC` / `TIMEOUT` / `SAFETY` | 是 |  |
| applicability | `REQUIRED` / `NOT_APPLICABLE` / `PENDING` | 是 |  |
| definition_resource | `ResourceRef` 或 null | 是 |  |
| definition_key | string 或 null | 是 |  |
| reason | string | 是 | minLength=1；maxLength=1024 |

包含条件约束，须同时执行Schema组合规则。

### Signal

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| signal_id | string | 是 | minLength=1；maxLength=128 |
| name | string | 是 | minLength=1；maxLength=256 |
| value_type | `NUMBER` / `INTEGER` / `BOOLEAN` / `STRING` / `NUMBER_VECTOR` / `INT64_DECIMAL` / `UINT64_DECIMAL` | 是 |  |
| unit | string 或 null | 是 |  |
| coordinate_frame | string 或 null | 是 |  |
| minimum | number 或 null | 是 |  |
| maximum | number 或 null | 是 |  |
| dimension | integer 或 null | 是 |  |
| writable | boolean | 是 |  |
| decimal_minimum | `DecimalInt64` / `DecimalUInt64` 或 null | 是 | 按value_type执行条件约束 |
| decimal_maximum | `DecimalInt64` / `DecimalUInt64` 或 null | 是 | 按value_type执行条件约束 |

包含条件约束，须同时执行Schema组合规则。

### Layout

分支1：

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| kind | `"FIXED_BITS"` | 是 |  |
| start_bit | integer | 是 | minimum=0；maximum=1048576 |
| bit_length | integer | 是 | minimum=1；maximum=1048576 |
| byte_order | `LITTLE_ENDIAN` / `BIG_ENDIAN` | 是 |  |
| bit_numbering | `LSB0` / `MSB0` / `DBC_MOTOROLA` | 是 |  |

分支2：

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| kind | `"RESOURCE_DEFINED"` | 是 |  |
| definition_resource | `ResourceRef` | 是 |  |
| definition_key | string | 是 | minLength=1；maxLength=256 |

### WireField

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| field_id | string | 是 | minLength=1；maxLength=128 |
| signal_id | string 或 null | 是 |  |
| role | `SIGNAL` / `COUNTER` / `CRC` / `SESSION` / `LENGTH` / `TIMESTAMP` / `DISCRIMINATOR` / `OTHER` | 是 |  |
| raw_type | `UINT` / `INT` / `FLOAT` / `BOOLEAN` / `STRING` / `BYTES` | 是 |  |
| layout | `Layout` | 是 |  |
| scale | number | 是 |  |
| offset | number | 是 |  |
| invalid_definition_key | string 或 null | 是 |  |

包含条件约束，须同时执行Schema组合规则。

### CanSelector

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| kind | `"CAN"` | 是 |  |
| arbitration_id | integer | 是 | minimum=0；maximum=536870911 |
| extended_id | boolean | 是 |  |
| payload_length | `0` / `1` / `2` / `3` / `4` / `5` / `6` / `7` / `8` / `12` / `16` / `20` / `24` / `32` / `48` / `64` | 是 |  |
| fd | boolean | 是 |  |
| brs | boolean | 是 |  |

包含条件约束，须同时执行Schema组合规则。

### Wire

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| status | `"CONFIRMED"` | 是 |  |
| transport | `CAN` / `CANFD` / `ETHERNET` / `SERIAL` / `AD` / `DA` / `IO` / `VIDEO` | 是 |  |
| definition_resource | `ResourceRef` | 是 |  |
| definition_key | string | 是 | minLength=1；maxLength=256 |
| codec_binding_id | string | 是 | minLength=1；maxLength=128 |
| selector | `CanSelector` 或 object（见Schema内字段） | 是 |  |
| fields | `WireField`[] | 是 | minItems=1；maxItems=10000 |
| rules | `Rule`[] | 是 | minItems=0；maxItems=10000 |
| golden_vectors | object（见Schema内字段）[] | 是 | minItems=1；maxItems=10000 |

包含条件约束，须同时执行Schema组合规则。

### Timing

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| status | `"CONFIRMED"` | 是 |  |
| trigger | `PERIODIC` / `EVENT` | 是 |  |
| period_us | string 或 null | 是 |  |
| deadline_us | string | 是 | pattern="^[1-9][0-9]{0,19}$"；Decimal uint64; runtime also checks maximum 18446744073709551615. |
| jitter_tolerance_us | string | 是 | pattern="^(0\|[1-9][0-9]{0,19})$"；Decimal uint64; runtime also checks maximum 18446744073709551615. |
| validity_us | string | 是 | pattern="^[1-9][0-9]{0,19}$"；Decimal uint64; runtime also checks maximum 18446744073709551615. |
| max_burst | integer | 是 | minimum=1；maximum=1000000 |
| timeout_rule_id | string | 是 | minLength=1；maxLength=128 |

包含条件约束，须同时执行Schema组合规则。

### Feedback

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| mode | `NONE` / `PERIODIC` / `PER_REQUEST` / `PENDING` | 是 |  |
| message_ids | string[] | 是 | minItems=0；maxItems=10000；uniqueItems=true |
| correlation_rule_id | string 或 null | 是 |  |
| application_evidence_binding_id | string 或 null | 是 |  |

包含条件约束，须同时执行Schema组合规则。

### Message

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| message_id | string | 是 | minLength=1；maxLength=128 |
| name | string | 是 | minLength=1；maxLength=256 |
| required | boolean | 是 |  |
| direction | `TO_36` / `FROM_36` | 是 |  |
| category | `MISSION` / `CONTROL` / `PARAMETER` / `ENVIRONMENT` / `FAULT` / `SENSOR` / `ACTUATOR` / `STATE` / `FEEDBACK` | 是 |  |
| transport_profile_id | string | 是 | minLength=1；maxLength=128 |
| control_role | `STIMULUS` / `CONTROLLER` / `OBSERVER` / `FEEDBACK` | 是 |  |
| signals | `Signal`[] | 是 | minItems=1；maxItems=10000 |
| wire | `Wire` | 是 |  |
| timing | `Timing` | 是 |  |
| feedback | `Feedback` | 是 |  |

### ProtocolDefinition

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| schema_version | `"protocol-0.2"` | 是 |  |
| name | string | 是 | minLength=1；maxLength=256 |
| icd_document_ref | `ResourceRef` | 是 |  |
| messages | `Message`[] | 是 | minItems=1；maxItems=10000 |

### Profile

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| ref | `ProfileRef` | 是 |  |
| approval | `DRAFT` / `FROZEN` | 是 |  |
| approval_ref | string 或 null | 是 |  |
| definition | `ProtocolDefinition` | 是 |  |

包含条件约束，须同时执行Schema组合规则。

### CanConfig

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| kind | `"CAN"` | 是 |  |
| driver_binding_id | string | 是 | minLength=1；maxLength=128 |
| channel_binding_id | string | 是 | minLength=1；maxLength=128 |
| nominal_bitrate | integer | 是 | minimum=1；maximum=10000000 |
| data_bitrate | integer 或 null | 是 |  |
| fd | boolean | 是 |  |
| driver_config_ref | `ResourceRef` | 是 |  |
| feedback_transport_id | string | 是 | minLength=1；maxLength=128 |
| synchronization_rule_id | string 或 null | 是 |  |

包含条件约束，须同时执行Schema组合规则。

### EthernetConfig

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| kind | `"ETHERNET"` | 是 |  |
| driver_binding_id | string | 是 | minLength=1；maxLength=128 |
| link_binding_id | string | 是 | minLength=1；maxLength=128 |
| stack | `L2` / `UDP` / `TCP` / `SOMEIP` / `CUSTOM` | 是 |  |
| local_endpoint_binding_id | string | 是 | minLength=1；maxLength=128 |
| remote_endpoint_binding_id | string | 是 | minLength=1；maxLength=128 |
| feedback_transport_id | string | 是 | minLength=1；maxLength=128 |
| session_rule_id | string 或 null | 是 |  |
| synchronization_rule_id | string 或 null | 是 |  |
| driver_config_ref | `ResourceRef` | 是 |  |

### OtherConfig

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| kind | `SERIAL` / `AD` / `DA` / `IO` / `VIDEO` | 是 |  |
| driver_binding_id | string | 是 | minLength=1；maxLength=128 |
| channel_binding_id | string | 是 | minLength=1；maxLength=128 |
| interface_definition_ref | `ResourceRef` | 是 |  |
| feedback_transport_id | string | 是 | minLength=1；maxLength=128 |
| synchronization_rule_id | string 或 null | 是 |  |

### Transport

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| transport_profile_id | string | 是 | minLength=1；maxLength=128 |
| medium | `CAN` / `CANFD` / `ETHERNET` / `SERIAL` / `AD` / `DA` / `IO` / `VIDEO` | 是 |  |
| configuration | `Pending` 或 object（见Schema内字段） | 是 |  |

包含条件约束，须同时执行Schema组合规则。

### Clock

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| domain_id | string | 是 | minLength=1；maxLength=128 |
| kind | `DEVICE` / `HOST_MONOTONIC` / `UTC` / `SIMULATION` / `CAPTURE_RELATIVE` | 是 |  |
| tick_unit | `"us"` | 是 |  |
| synchronization_ref | string 或 null | 是 |  |

### Mapping

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| mapping_id | string | 是 | minLength=1；maxLength=128 |
| message_id | string | 是 | minLength=1；maxLength=128 |
| signal_id | string | 是 | minLength=1；maxLength=128 |
| target_kind | `MODEL_INPUT` / `TASK_INPUT` / `PARAMETER` / `FAULT_INPUT` / `CONTROLLER_INPUT` | 是 |  |
| model_contract_ref | `ResourceRef` | 是 |  |
| target_path | string | 是 | minLength=1；maxLength=512 |
| source_unit | string 或 null | 是 |  |
| target_unit | string 或 null | 是 |  |
| source_frame | string 或 null | 是 |  |
| target_frame | string 或 null | 是 |  |
| conversion | object（见Schema内字段） | 是 |  |
| atomic_group_id | string 或 null | 是 |  |
| apply_boundary | `MODEL_STEP` / `TASK_COMMIT` | 是 |  |
| invalid_action | `REJECT` / `HOLD` / `SAFE_DEFAULT` | 是 |  |
| safe_default | `Value` 或 null | 是 |  |
| evidence_binding_id | string | 是 | minLength=1；maxLength=128 |

包含条件约束，须同时执行Schema组合规则。

### HistoryStream

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| stream_id | string | 是 | minLength=1；maxLength=128 |
| original_channel | string | 是 | minLength=1；maxLength=128 |
| direction | `TO_36` / `FROM_36` / `UNKNOWN` | 是 |  |
| medium | `CAN` / `CANFD` / `ETHERNET` | 是 |  |
| message_ids | string[] | 是 | minItems=1；maxItems=10000；uniqueItems=true |

### History

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| history_id | string | 是 | minLength=1；maxLength=128 |
| resource_ref | `ResourceRef` | 是 |  |
| format | `CAN_LOG` / `PCAP` / `PCAPNG` / `ENGINEERING_JSONL` | 是 |  |
| profile_ref | `ProfileRef` | 是 |  |
| origin_clock | `Clock` | 是 |  |
| streams | `HistoryStream`[] | 是 | minItems=1；maxItems=10000 |
| integrity | object（见Schema内字段） | 是 |  |
| engineering_schema_version | `"engineering-history-0.2"` 或 null | 是 |  |

包含条件约束，须同时执行Schema组合规则。

### EngineeringRecord

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| schema_version | `"engineering-history-0.2"` | 是 |  |
| sequence | string | 是 | pattern="^(0\|[1-9][0-9]{0,19})$"；Decimal uint64; runtime also checks maximum 18446744073709551615. |
| timestamp_us | string | 是 | pattern="^(0\|[1-9][0-9]{0,19})$"；Decimal uint64; runtime also checks maximum 18446744073709551615. |
| stream_id | string | 是 | minLength=1；maxLength=128 |
| message_id | string | 是 | minLength=1；maxLength=128 |
| values | `Values` | 是 |  |

### ReplayPolicy

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| replay_policy_id | string | 是 | minLength=1；maxLength=128 |
| history_id | string | 是 | minLength=1；maxLength=128 |
| stream_ids | string[] | 是 | minItems=1；maxItems=10000；uniqueItems=true |
| source_range | object（见Schema内字段） | 是 |  |
| clock_mode | `"SIM_RELATIVE"` | 是 |  |
| rate | object（见Schema内字段） | 是 |  |
| repeat_count | integer | 是 | minimum=1；maximum=1000000 |
| payload_mode | `RAW_VALIDATED` / `REENCODE` / `SESSION_REBUILD` | 是 |  |
| late_action | `STOP` / `DROP_APPROVED` | 是 |  |
| max_lateness_us | string | 是 | pattern="^(0\|[1-9][0-9]{0,19})$"；Decimal uint64; runtime also checks maximum 18446744073709551615. |
| channel_map | object（见Schema内字段）[] | 是 | minItems=1；maxItems=10000 |
| rewrites | object（见Schema内字段）[] | 是 | minItems=0；maxItems=10000 |
| approval_ref | string 或 null | 是 |  |
| repeat_gap_us | string | 是 | pattern="^(0\|[1-9][0-9]{0,19})$"；Decimal uint64; runtime also checks maximum 18446744073709551615. |
| repeat_session_rule_id | string 或 null | 是 |  |

包含条件约束，须同时执行Schema组合规则。

### Waveform

分支1：

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| shape | `"STEP"` | 是 |  |
| initial_value | number | 是 |  |
| final_value | number | 是 |  |
| step_after_us | string | 是 | pattern="^(0\|[1-9][0-9]{0,19})$"；Decimal uint64; runtime also checks maximum 18446744073709551615. |

分支2：

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| shape | `"RAMP"` | 是 |  |
| start_value | number | 是 |  |
| end_value | number | 是 |  |
| max_slew_per_second | number | 是 | exclusiveMinimum=0 |

分支3：

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| shape | `"SINE_SWEEP"` | 是 |  |
| offset | number | 是 |  |
| amplitude | number | 是 | minimum=0 |
| start_frequency_hz | number | 是 | exclusiveMinimum=0 |
| end_frequency_hz | number | 是 | exclusiveMinimum=0 |
| phase_rad | number | 是 |  |

### SendAction

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| kind | `"SEND"` | 是 |  |
| message_id | string | 是 | minLength=1；maxLength=128 |
| values | `Values` | 是 |  |

### WaveAction

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| kind | `"WAVEFORM"` | 是 |  |
| message_id | string | 是 | minLength=1；maxLength=128 |
| signal_id | string | 是 | minLength=1；maxLength=128 |
| unit | string | 是 | minLength=1；maxLength=64 |
| duration_us | string | 是 | pattern="^[1-9][0-9]{0,19}$"；Decimal uint64; runtime also checks maximum 18446744073709551615. |
| update_period_us | string | 是 | pattern="^[1-9][0-9]{0,19}$"；Decimal uint64; runtime also checks maximum 18446744073709551615. |
| waveform | `Waveform` | 是 |  |

### PeriodicStartAction

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| kind | `"PERIODIC_START"` | 是 |  |
| schedule_id | string | 是 | minLength=1；maxLength=128 |
| message_id | string | 是 | minLength=1；maxLength=128 |
| values | `Values` | 是 |  |

### PeriodicStopAction

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| kind | `"PERIODIC_STOP"` | 是 |  |
| schedule_id | string | 是 | minLength=1；maxLength=128 |

### WaitAction

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| kind | `"WAIT"` | 是 |  |
| source_event_id | string | 是 | minLength=1；maxLength=128 |
| stage | `RECEIVED` / `APPLIED` / `RESPONSE` / `SAFETY` | 是 |  |
| timeout_us | string | 是 | pattern="^[1-9][0-9]{0,19}$"；Decimal uint64; runtime also checks maximum 18446744073709551615. |
| assertion_ids | string[] | 是 | minItems=1；maxItems=10000；uniqueItems=true |

### ReplayAction

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| kind | `"REPLAY"` | 是 |  |
| history_id | string | 是 | minLength=1；maxLength=128 |
| replay_policy_id | string | 是 | minLength=1；maxLength=128 |

### FaultAction

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| kind | `"FAULT"` | 是 |  |
| fault_case_id | string | 是 | minLength=1；maxLength=128 |
| duration_us | string | 是 | pattern="^[1-9][0-9]{0,19}$"；Decimal uint64; runtime also checks maximum 18446744073709551615. |

### AssertAction

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| kind | `"ASSERT"` | 是 |  |
| source_event_id | string 或 null | 是 |  |
| assertion_ids | string[] | 是 | minItems=1；maxItems=10000；uniqueItems=true |

### CleanupAction

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| kind | `"END_CLEANUP"` | 是 |  |
| cleanup_rule_id | string | 是 | minLength=1；maxLength=128 |

### Event

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| event_id | string | 是 | minLength=1；maxLength=128 |
| at_sim_time_us | string | 是 | pattern="^(0\|[1-9][0-9]{0,19})$"；Decimal uint64; runtime also checks maximum 18446744073709551615. |
| priority | integer | 是 | minimum=-32768；maximum=32767 |
| action | `SendAction` 或 `WaveAction` 或 `PeriodicStartAction` 或 `PeriodicStopAction` 或 `WaitAction` 或 `ReplayAction` 或 `FaultAction` 或 `AssertAction` 或 `CleanupAction` | 是 |  |
| link_id | string 或 null | 是 |  |

包含条件约束，须同时执行Schema组合规则。

### ScenarioDefinition

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| schema_version | `"scenario-0.2"` | 是 |  |
| name | string | 是 | minLength=1；maxLength=256 |
| profile_ref | `ProfileRef` | 是 |  |
| model_binding_id | string | 是 | minLength=1；maxLength=128 |
| seed | integer | 是 | minimum=0；maximum=4294967295 |
| resource_refs | `ResourceRef`[] | 是 | minItems=0；maxItems=10000 |
| clock_policy | object（见Schema内字段） | 是 |  |
| readiness_assertion_ids | string[] | 是 | minItems=1；maxItems=10000；uniqueItems=true |
| events | `Event`[] | 是 | minItems=1；maxItems=10000 |
| on_failure | `"SAFE_STOP"` | 是 |  |
| cleanup_rule_id | string | 是 | minLength=1；maxLength=128 |

### ValidationError

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| path | string | 是 | pattern="^(\|/.*)$" |
| code | string | 是 | minLength=1；maxLength=128 |
| message | string | 是 | minLength=1；maxLength=1024 |

### Scenario

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| ref | `ScenarioRef` | 是 |  |
| definition | `ScenarioDefinition` | 是 |  |
| validation_status | `PENDING` / `VALID` / `INVALID` | 是 |  |
| validation_errors | `ValidationError`[] | 是 | minItems=0；maxItems=10000 |

### FaultCase

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| fault_case_id | string | 是 | minLength=1；maxLength=128 |
| scope | `APPLICATION` / `PHYSICAL` | 是 |  |
| kind | `DROP` / `DUPLICATE` / `REORDER` / `DELAY` / `INVALID_VALUE` / `BAD_APP_CRC` / `STOP_TX` / `GPS_LOSS` / `CUSTOM` | 是 |  |
| message_ids | string[] | 是 | minItems=1；maxItems=10000；uniqueItems=true |
| signal_ids | string[] | 是 | minItems=0；maxItems=10000；uniqueItems=true |
| parameters | `Values` | 是 |  |
| implementation_binding_id | string | 是 | minLength=1；maxLength=128 |
| allowed_modes | `EXPLORE` / `FORMAL`[] | 是 | minItems=1；maxItems=10000；uniqueItems=true |
| approval_ref | string 或 null | 是 |  |
| evidence_binding_ids | string[] | 是 | minItems=1；maxItems=10000；uniqueItems=true |

### Assertion

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| assertion_id | string | 是 | minLength=1；maxLength=128 |
| stage | `RECEIVED` / `APPLIED` / `RESPONSE` / `SAFETY` | 是 |  |
| observable_binding_id | string | 是 | minLength=1；maxLength=128 |
| field_path | string | 是 | minLength=1；maxLength=512 |
| operator | `EQUAL` / `IN_RANGE` / `DELTA_WITHIN` / `COUNT_AT_LEAST` / `ABSENT` | 是 |  |
| expected | `Value` 或 null | 是 |  |
| lower | number 或 null | 是 |  |
| upper | number 或 null | 是 |  |
| absolute_tolerance | number 或 null | 是 |  |
| unit | string 或 null | 是 |  |
| window_us | string | 是 | pattern="^[1-9][0-9]{0,19}$"；Decimal uint64; runtime also checks maximum 18446744073709551615. |

包含条件约束，须同时执行Schema组合规则。

### Case

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| case_id | string | 是 | minLength=1；maxLength=128 |
| required | boolean | 是 |  |
| message_ids | string[] | 是 | minItems=0；maxItems=10000；uniqueItems=true |
| scenario_ids | string[] | 是 | minItems=1；maxItems=10000；uniqueItems=true |
| link_ids | string[] | 是 | minItems=1；maxItems=10000；uniqueItems=true |
| assertion_ids | string[] | 是 | minItems=1；maxItems=10000；uniqueItems=true |
| environment | `WINDOWS_UNIT` / `LINUX_SOFTWARE` / `TARGET_REALTIME` / `PHYSICAL` | 是 |  |
| reference_resource_ref | `ResourceRef` 或 null | 是 |  |
| cleanup_rule_id | string | 是 | minLength=1；maxLength=128 |

### Link

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| link_id | string | 是 | minLength=1；maxLength=128 |
| branch | `SIGNAL_CAN` / `CAN_UTILS` / `SAVVYCAN` / `CAN_REPLAY` / `ETHERNET_GENERATOR` / `PCAP_REPLAY` | 是 |  |
| role | `SEND` / `OBSERVE` / `REPLAY` | 是 |  |
| transport_profile_id | string | 是 | minLength=1；maxLength=128 |
| message_ids | string[] | 是 | minItems=1；maxItems=10000；uniqueItems=true |
| history_ids | string[] | 是 | minItems=0；maxItems=10000；uniqueItems=true |
| tool_binding_ids | string[] | 是 | minItems=1；maxItems=10000；uniqueItems=true |
| feedback_collector_binding_id | string 或 null | 是 |  |
| control_owner_ref | string 或 null | 是 |  |
| qualification | `UNVERIFIED` / `SOFTWARE_VERIFIED` / `FORMAL_VERIFIED` / `REAL_SOURCE_REPLACED` | 是 |  |
| evidence_refs | string[] | 是 | minItems=0；maxItems=10000；uniqueItems=true |
| capability_scope | string[] | 是 | minItems=1；maxItems=10000 |

包含条件约束，须同时执行Schema组合规则。

### ManifestEntry

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| artifact_id | string | 是 | minLength=1；maxLength=128 |
| role | `ICD` / `PROTOCOL` / `SCENARIO` / `HISTORY` / `MODEL_CONTRACT` / `TRANSPORT_PROFILE` / `SIGNAL_MAP` / `CASE_SUITE` / `GOLDEN_VECTORS` / `RELEASE_BASELINE` | 是 |  |
| resource_ref | `ResourceRef` | 是 |  |
| size_bytes | string | 是 | pattern="^(0\|[1-9][0-9]{0,19})$"；Decimal uint64; runtime also checks maximum 18446744073709551615. |

### ReleaseBaseline

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| stage | `TEST_CANDIDATE` / `RELEASED` | 是 | 测试候选基线不等于已发布替换基线 |
| baseline_id | string | 是 | minLength=1；maxLength=128 |
| approval_ref | string | 是 | minLength=1；maxLength=128 |
| protected_artifacts | object（见Schema内字段）[] | 是 | minItems=1；maxItems=10000 |
| allowed_changes | `SOURCE_ENDPOINT` / `DEVICE_ID` / `CREDENTIAL_REF` / `AUTHORIZATION_REF` / `DEPLOYMENT_BINDING`[] | 是 | minItems=0；maxItems=10000；uniqueItems=true |

### PackageDefinition

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| schema_version | `"package-0.2"` | 是 |  |
| name | string | 是 | minLength=1；maxLength=256 |
| canonicalization | `"JCS_RFC8785"` | 是 |  |
| manifest | `ManifestEntry`[] | 是 | minItems=1；maxItems=10000 |
| profile | `Profile` | 是 |  |
| transports | `Transport`[] | 是 | minItems=1；maxItems=10000 |
| mappings | `Mapping`[] | 是 | minItems=1；maxItems=10000 |
| histories | `History`[] | 是 | minItems=0；maxItems=10000 |
| scenarios | `Scenario`[] | 是 | minItems=1；maxItems=10000 |
| replay_policies | `ReplayPolicy`[] | 是 | minItems=0；maxItems=10000 |
| fault_cases | `FaultCase`[] | 是 | minItems=0；maxItems=10000 |
| assertions | `Assertion`[] | 是 | minItems=1；maxItems=10000 |
| cases | `Case`[] | 是 | minItems=1；maxItems=10000 |
| links | `Link`[] | 是 | minItems=1；maxItems=10000 |
| release_baseline | `ReleaseBaseline` 或 null | 是 |  |

### Package

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| ref | `PackageRef` | 是 |  |
| definition | `PackageDefinition` | 是 |  |
| qualification | `DRAFT` / `FROZEN` | 是 |  |
| approval_ref | string 或 null | 是 |  |
| validation_status | `PENDING` / `VALID` / `INVALID` | 是 |  |
| validation_errors | `ValidationError`[] | 是 | minItems=0；maxItems=10000 |

包含条件约束，须同时执行Schema组合规则。

### Resource

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| resource_id | string | 是 | minLength=1；maxLength=128 |
| name | string | 是 | minLength=1；maxLength=256 |
| kind | `PROTOCOL` / `SCENARIO` / `HISTORY` / `SUPPORT` | 是 |  |
| format | `DBC` / `ARXML` / `ICD_JSON` / `SCENARIO_JSON` / `SCENARIO_YAML` / `CAN_LOG` / `PCAP` / `PCAPNG` / `ENGINEERING_JSONL` / `JSON` / `CSV` / `BINARY` | 是 |  |
| size_bytes | string | 是 | pattern="^(0\|[1-9][0-9]{0,19})$"；Decimal uint64; runtime also checks maximum 18446744073709551615. |
| sha256 | `Hash` | 是 |  |
| validation_status | `PENDING` / `VALID` / `INVALID` | 是 |  |
| validation_errors | `ValidationError`[] | 是 | minItems=0；maxItems=10000 |
| approval | `DRAFT` / `APPROVED` | 是 |  |
| approval_ref | string 或 null | 是 |  |

包含条件约束，须同时执行Schema组合规则。

### SerialInterface

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| schema_version | `"serial-interface-0.2"` | 是 |  |
| baud | integer | 是 | minimum=1 |
| data_bits | `5` / `6` / `7` / `8` | 是 |  |
| stop_bits | `1` / `1.5` / `2` | 是 |  |
| parity | `NONE` / `ODD` / `EVEN` | 是 |  |
| flow_control | `NONE` / `RTS_CTS` / `XON_XOFF` | 是 |  |
| electrical_standard | `RS232` / `RS422` / `RS485` | 是 |  |
| encoding_resource_ref | `ResourceRef` | 是 |  |
| receive_timeout_us | `PositiveUInt64` | 是 |  |

### IoInterface

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| schema_version | `"io-interface-0.2"` | 是 |  |
| medium | `AD` / `DA` / `IO` | 是 |  |
| channels | object（见Schema内字段）[] | 是 | minItems=1；maxItems=10000 |

### VideoInterface

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| schema_version | `"video-interface-0.2"` | 是 |  |
| format | `H264` / `H265` / `RAW` | 是 |  |
| width | integer | 是 | minimum=1 |
| height | integer | 是 | minimum=1 |
| frame_rate | object（见Schema内字段） | 是 |  |
| pixel_format | string | 是 | minLength=1；maxLength=128 |
| trigger_modes | `MANUAL` / `PERIODIC` / `SIM_EVENT`[] | 是 | minItems=1；maxItems=10000；uniqueItems=true |
| metadata_location | `SEI` / `SIDECAR` | 是 |  |
| annotation_resource_ref | `ResourceRef` 或 null | 是 |  |
| late_frame_action | `DROP_APPROVED` / `STOP` | 是 |  |
| sync_rule_id | string | 是 | minLength=1；maxLength=128 |
| completion_feedback_message_id | string | 是 | minLength=1；maxLength=128 |

包含条件约束，须同时执行Schema组合规则。

### VideoFrameMetadata

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| schema_version | `"video-frame-0.2"` | 是 |  |
| run_id | string | 是 | minLength=1；maxLength=128 |
| video_frame_id | string | 是 | pattern="^(0\|[1-9][0-9]{0,19})$"；Decimal uint64; runtime also checks maximum 18446744073709551615. |
| clock_domain_id | string | 是 | minLength=1；maxLength=128 |
| sim_time_us | string | 是 | pattern="^(0\|[1-9][0-9]{0,19})$"；Decimal uint64; runtime also checks maximum 18446744073709551615. |
| pts | string | 是 | pattern="^(0\|[1-9][0-9]{0,19})$"；Decimal uint64; runtime also checks maximum 18446744073709551615. |
| pts_timebase | object（见Schema内字段） | 是 |  |
| image_resource_ref | `ResourceRef` | 是 |  |
| annotation_resource_ref | `ResourceRef` 或 null | 是 |  |

### CrcParameters

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| algorithm_binding_id | string | 是 | minLength=1；maxLength=128 |
| field_id | string | 是 | minLength=1；maxLength=128 |
| width_bits | integer | 是 | minimum=1；maximum=64 |
| polynomial_hex | string | 是 | pattern="^0x[0-9a-f]{1,16}$" |
| initial_hex | string | 是 | pattern="^0x[0-9a-f]{1,16}$" |
| xor_out_hex | string | 是 | pattern="^0x[0-9a-f]{1,16}$" |
| reflect_input | boolean | 是 |  |
| reflect_output | boolean | 是 |  |
| coverage | `CrcCoverage` | 是 |  |

### CounterParameters

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| field_id | string | 是 | minLength=1；maxLength=128 |
| width_bits | integer | 是 | minimum=1；maximum=64 |
| initial_value | string | 是 | pattern="^(0\|[1-9][0-9]{0,19})$"；Decimal uint64; runtime also checks maximum 18446744073709551615. |
| increment | string | 是 | pattern="^[1-9][0-9]{0,19}$"；Decimal uint64; runtime also checks maximum 18446744073709551615. |
| rollover | `MODULO` / `STOP` | 是 |  |
| max_forward_gap | string | 是 | pattern="^(0\|[1-9][0-9]{0,19})$"；Decimal uint64; runtime also checks maximum 18446744073709551615. |
| repeat_action | `REJECT` / `IGNORE` / `ALLOW_APPROVED` | 是 |  |
| reset | `ON_SESSION` / `NEVER` | 是 |  |

### SessionParameters

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| state_machine_binding_id | string | 是 | minLength=1；maxLength=128 |
| protocol_definition_ref | `ResourceRef` | 是 |  |
| handshake_timeout_us | string | 是 | pattern="^[1-9][0-9]{0,19}$"；Decimal uint64; runtime also checks maximum 18446744073709551615. |
| inactivity_timeout_us | string | 是 | pattern="^[1-9][0-9]{0,19}$"；Decimal uint64; runtime also checks maximum 18446744073709551615. |
| reconnect_policy | `DENY` / `REAUTHENTICATE` / `APPROVED_RESUME` | 是 |  |
| dynamic_field_ids | string[] | 是 | minItems=0；maxItems=10000；uniqueItems=true |
| feedback_message_ids | string[] | 是 | minItems=0；maxItems=10000；uniqueItems=true |

### AuthParameters

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| auth_binding_id | string | 是 | minLength=1；maxLength=128 |
| algorithm_definition_ref | `ResourceRef` | 是 |  |
| identity_field_ids | string[] | 是 | minItems=1；maxItems=10000；uniqueItems=true |
| anti_replay_rule_id | string 或 null | 是 |  |
| credential_scope_binding_id | string | 是 | minLength=1；maxLength=128 |
| session_required | boolean | 是 |  |

### MultiFrameParameters

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| group_id | string | 是 | minLength=1；maxLength=128 |
| member_message_ids | string[] | 是 | minItems=1；maxItems=10000；uniqueItems=true |
| sequence_field_id | string | 是 | minLength=1；maxLength=128 |
| assembly_timeout_us | string | 是 | pattern="^[1-9][0-9]{0,19}$"；Decimal uint64; runtime also checks maximum 18446744073709551615. |
| missing_member_action | `REJECT_GROUP` / `SAFE_STOP` | 是 |  |
| max_inflight_groups | integer | 是 | minimum=1；maximum=1000000 |
| commit_boundary | `MODEL_STEP` / `TARGET_STEP` | 是 |  |
| target_step_field_id | string 或 null | 是 |  |

包含条件约束，须同时执行Schema组合规则。

### DedupParameters

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| key_field_ids | string[] | 是 | minItems=1；maxItems=10000；uniqueItems=true |
| window_us | string | 是 | pattern="^[1-9][0-9]{0,19}$"；Decimal uint64; runtime also checks maximum 18446744073709551615. |
| duplicate_action | `REJECT` / `IGNORE` | 是 |  |
| capacity | integer | 是 | minimum=1；maximum=1000000 |

### SyncParameters

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| clock_domain_ids | string[] | 是 | minItems=1；maxItems=10000；uniqueItems=true |
| method | `SIM_CLOCK` / `PTP` / `HARDWARE_TRIGGER` / `APPROVED` | 是 |  |
| synchronization_binding_id | string | 是 | minLength=1；maxLength=128 |
| max_skew_us | string | 是 | pattern="^(0\|[1-9][0-9]{0,19})$"；Decimal uint64; runtime also checks maximum 18446744073709551615. |
| on_clock_loss | `BLOCK` / `SAFE_STOP` | 是 |  |

### TimeoutParameters

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| watch_scope | `MESSAGE` / `GROUP` / `SESSION` | 是 |  |
| watch_id | string | 是 | minLength=1；maxLength=128 |
| clock | `SIMULATION` / `HOST_MONOTONIC` | 是 |  |
| timeout_us | string | 是 | pattern="^[1-9][0-9]{0,19}$"；Decimal uint64; runtime also checks maximum 18446744073709551615. |
| safety_rule_id | string | 是 | minLength=1；maxLength=128 |

### SafetyParameters

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| action_binding_id | string | 是 | minLength=1；maxLength=128 |
| stop_message_ids | string[] | 是 | minItems=0；maxItems=10000；uniqueItems=true |
| clear_queue_scope | `CURRENT_SESSION` / `APPROVED_ALL` | 是 |  |
| release_authorization | boolean | 是 |  |
| confirmation_assertion_ids | string[] | 是 | minItems=1；maxItems=10000；uniqueItems=true |
| deadline_us | string | 是 | pattern="^[1-9][0-9]{0,19}$"；Decimal uint64; runtime also checks maximum 18446744073709551615. |

### RuleDefinition

分支1：

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| rule_id | string | 是 | minLength=1；maxLength=128 |
| kind | `"CRC"` | 是 |  |
| parameters | `CrcParameters` | 是 |  |

分支2：

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| rule_id | string | 是 | minLength=1；maxLength=128 |
| kind | `"COUNTER"` | 是 |  |
| parameters | `CounterParameters` | 是 |  |

分支3：

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| rule_id | string | 是 | minLength=1；maxLength=128 |
| kind | `"SESSION"` | 是 |  |
| parameters | `SessionParameters` | 是 |  |

分支4：

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| rule_id | string | 是 | minLength=1；maxLength=128 |
| kind | `"AUTH"` | 是 |  |
| parameters | `AuthParameters` | 是 |  |

分支5：

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| rule_id | string | 是 | minLength=1；maxLength=128 |
| kind | `"MULTIFRAME"` | 是 |  |
| parameters | `MultiFrameParameters` | 是 |  |

分支6：

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| rule_id | string | 是 | minLength=1；maxLength=128 |
| kind | `"DEDUP"` | 是 |  |
| parameters | `DedupParameters` | 是 |  |

分支7：

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| rule_id | string | 是 | minLength=1；maxLength=128 |
| kind | `"SYNC"` | 是 |  |
| parameters | `SyncParameters` | 是 |  |

分支8：

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| rule_id | string | 是 | minLength=1；maxLength=128 |
| kind | `"TIMEOUT"` | 是 |  |
| parameters | `TimeoutParameters` | 是 |  |

分支9：

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| rule_id | string | 是 | minLength=1；maxLength=128 |
| kind | `"SAFETY"` | 是 |  |
| parameters | `SafetyParameters` | 是 |  |

### RuleResource

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| schema_version | `"rule-resource-0.2"` | 是 |  |
| rules | `RuleDefinition`[] | 是 | minItems=1；maxItems=10000 |

### DecimalInt64

类型：string。pattern="^(0\|-?[1-9][0-9]{0,18})$"；Runtime enforces -9223372036854775808 through 9223372036854775807.

### DecimalUInt64

类型：string。pattern="^(0\|[1-9][0-9]{0,19})$"；Decimal uint64; runtime also checks maximum 18446744073709551615.

### CrcCoverage

分支1：

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| mode | `"FIELD_CONCAT"` | 是 |  |
| field_ids | string[] | 是 | minItems=1；maxItems=10000；uniqueItems=true |
| include_padding | boolean | 是 |  |
| zero_crc_field | boolean | 是 |  |

分支2：

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| mode | `"BYTE_SPANS"` | 是 |  |
| spans | object（见Schema内字段）[] | 是 | minItems=1；maxItems=10000 |
| zero_crc_field | boolean | 是 |  |

分支3：

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| mode | `"RESOURCE_DEFINED"` | 是 |  |
| definition_resource | `ResourceRef` | 是 |  |
| definition_key | string | 是 | minLength=1；maxLength=128 |

## 管理接口

### Id

类型：string。minLength=1；maxLength=128

### Hash

类型：string。pattern="^[0-9a-f]{64}$"

### UInt64

类型：string。pattern="^(0\|[1-9][0-9]{0,19})$"；Decimal integer string. Server also enforces unsigned 64-bit maximum 18446744073709551615.

### UtcTime

类型：string。pattern="Z$"；format="date-time"

### Cursor

类型：string。minLength=1；maxLength=1024

### Action

类型：`START` / `PAUSE` / `RESUME` / `STOP` / `RESET` / `STEP`。

### Mode

类型：`EXPLORE` / `FORMAL`。

### ResourceKind

类型：`PROTOCOL` / `SCENARIO` / `HISTORY` / `SUPPORT`。

### Command

类型：`simulator_capabilities_get` / `simulator_profiles_list` / `simulator_profile_get` / `simulator_resources_list` / `simulator_scenarios_list` / `simulator_scenario_get` / `simulator_scenario_save` / `simulator_run_create` / `simulator_run_control` / `simulator_run_update_inputs` / `simulator_run_get` / `simulator_runs_list` / `simulator_records_list` / `simulator_report_get` / `simulator_resource_get` / `simulator_resource_import_begin` / `simulator_resource_import_chunk` / `simulator_resource_import_get` / `simulator_resource_import_commit` / `simulator_resource_import_abort` / `simulator_resource_read_chunk` / `simulator_packages_list` / `simulator_package_get` / `simulator_package_save` / `simulator_package_validate`。

### ErrorCode

类型：`INVALID_REQUEST` / `UNSUPPORTED_VERSION` / `UNAUTHORIZED` / `FORBIDDEN` / `NOT_FOUND` / `VERSION_CONFLICT` / `IDEMPOTENCY_CONFLICT` / `ICD_NOT_FROZEN` / `PROFILE_MISMATCH` / `MODEL_MAPPING_MISSING` / `RESOURCE_INVALID` / `TOOL_UNAVAILABLE` / `STATE_CONFLICT` / `CONTROL_CONFLICT` / `VALUE_OUT_OF_RANGE` / `OPERATION_NOT_ALLOWED` / `TIMEOUT` / `EVIDENCE_INCOMPLETE` / `INTERNAL_ERROR` / `REFERENCE_INVALID` / `ICD_PENDING` / `COVERAGE_INCOMPLETE` / `DIRECTION_UNKNOWN` / `REPLAY_UNSUPPORTED` / `CHUNK_CONFLICT` / `UPLOAD_EXPIRED` / `QUOTA_EXCEEDED` / `HASH_MISMATCH` / `RESOURCE_IN_USE`。

### ErrorDetail

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| path | string | 是 | pattern="^(\|/.*)$" |
| code | `ErrorCode` | 是 |  |
| message | string | 是 | maxLength=1024 |

### Error

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| code | `ErrorCode` | 是 |  |
| retryable | boolean | 是 |  |
| details | `ErrorDetail`[] | 是 | maxItems=100 |

### ProfileRef

引用 `urn:hil:input-simulator:package-contract:0.2#/$defs/ProfileRef`，字段见对应定义。

### ScenarioRef

引用 `urn:hil:input-simulator:package-contract:0.2#/$defs/ScenarioRef`，字段见对应定义。

### Values

引用 `urn:hil:input-simulator:package-contract:0.2#/$defs/Values`，字段见对应定义。

### Signal

引用 `urn:hil:input-simulator:package-contract:0.2#/$defs/Signal`，字段见对应定义。

### Profile

引用 `urn:hil:input-simulator:package-contract:0.2#/$defs/Profile`，字段见对应定义。

### ProfileSummary

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| ref | `ProfileRef` | 是 |  |
| name | string | 是 | minLength=1；maxLength=256 |
| approval | `DRAFT` / `FROZEN` | 是 |  |
| transports | `CAN` / `CANFD` / `ETHERNET` / `SERIAL` / `AD` / `DA` / `IO` / `VIDEO`[] | 是 | minItems=1；uniqueItems=true |
| message_count | integer | 是 | minimum=1；maximum=10000 |

### Resource

引用 `urn:hil:input-simulator:package-contract:0.2#/$defs/Resource`，字段见对应定义。

### ScenarioDraft

引用 `urn:hil:input-simulator:package-contract:0.2#/$defs/ScenarioDefinition`，字段见对应定义。

### Scenario

引用 `urn:hil:input-simulator:package-contract:0.2#/$defs/Scenario`，字段见对应定义。

### ScenarioSummary

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| ref | `ScenarioRef` | 是 |  |
| name | string | 是 | minLength=1；maxLength=256 |
| profile_ref | `ProfileRef` | 是 |  |
| validation_status | `PENDING` / `VALID` / `INVALID` | 是 |  |
| event_count | integer | 是 | minimum=1；maximum=10000 |

### Stats

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| tx_frames | `UInt64` | 是 |  |
| rx_frames | `UInt64` | 是 |  |
| received_inputs | `UInt64` | 是 |  |
| applied_inputs | `UInt64` | 是 |  |
| rejected_inputs | `UInt64` | 是 |  |

### Run

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| run_id | `Id` | 是 |  |
| revision | `UInt64` | 是 |  |
| mode | `Mode` | 是 |  |
| profile_ref | `ProfileRef` | 是 |  |
| scenario_ref | `ScenarioRef` | 是 |  |
| source_binding_ref | `Id` | 是 |  |
| state | `VALIDATING` / `BLOCKED` / `READY` / `RUNNING` / `WAITING` / `PAUSED` / `STOPPING` / `COMPLETED` / `FAILED` | 是 |  |
| result | `NOT_RUN` / `RUNNING` / `PASS` / `FAIL` / `INCOMPLETE` | 是 |  |
| available_actions | `Action`[] | 是 | uniqueItems=true |
| stats | `Stats` | 是 |  |
| evidence_complete | boolean | 是 |  |
| last_error | `Error` 或 null | 是 |  |
| created_at | `UtcTime` | 是 |  |
| updated_at | `UtcTime` | 是 |  |
| package_ref | `PackageRef` | 是 |  |
| link_ids | string[] | 是 | minItems=1；maxItems=10000；uniqueItems=true |
| clock_domain_id | string | 是 | minLength=1；maxLength=128 |
| sim_time_us | `UInt64` | 是 |  |
| step_index | `UInt64` | 是 |  |
| active_event_id | string 或 null | 是 |  |
| link_stats | object（见Schema内字段）[] | 是 | minItems=0；maxItems=10000 |

包含条件约束，须同时执行Schema组合规则。

### Record

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| record_id | `Id` | 是 |  |
| cursor | `Cursor` | 是 |  |
| run_id | `Id` | 是 |  |
| input_event_id | `Id` 或 null | 是 |  |
| operation_id | `Id` 或 null | 是 |  |
| kind | `TX` / `RX` / `RECEIVED` / `APPLIED` / `REJECTED` / `RESPONSE` / `SAFETY` / `TOOL_ERROR` / `OPERATION_RESULT` | 是 |  |
| timestamp | `UtcTime` | 是 |  |
| clock_domain | `Id` | 是 |  |
| monotonic_us | `UInt64` | 是 |  |
| message_id | `Id` 或 null | 是 |  |
| reason_code | string | 是 | minLength=1；maxLength=128 |
| evidence_refs | `Id`[] | 是 | maxItems=100 |
| step_index | `UInt64` | 否 |  |
| sim_time_us | `UInt64` | 否 |  |
| applied_values | `Values` | 否 |  |
| operation_result | `SUCCEEDED` / `FAILED` | 否 |  |
| new_run_id | `Id` | 否 |  |
| event_id | string 或 null | 是 |  |
| link_id | string 或 null | 是 |  |
| applied_mapping_ids | string[] | 否 | minItems=1；maxItems=10000；uniqueItems=true |

包含条件约束，须同时执行Schema组合规则。

### CaseResult

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| case_id | `Id` | 是 |  |
| required | boolean | 是 |  |
| result | `PASS` / `FAIL` / `NOT_RUN` / `NOT_APPLICABLE` / `INCOMPLETE` | 是 |  |
| reason_code | string | 是 | minLength=1；maxLength=128 |
| evidence_refs | `Id`[] | 是 |  |

包含条件约束，须同时执行Schema组合规则。

### Report

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| run_id | `Id` | 是 |  |
| mode | `Mode` | 是 |  |
| profile_ref | `ProfileRef` | 是 |  |
| scenario_ref | `ScenarioRef` | 是 |  |
| overall_result | `PASS` / `FAIL` / `INCOMPLETE` | 是 |  |
| evidence_complete | boolean | 是 |  |
| cases | `CaseResult`[] | 是 | minItems=1 |
| artifact_refs | `Id`[] | 是 |  |
| package_ref | `PackageRef` | 是 |  |
| qualification_level | `SOFTWARE_VERIFIED` / `FORMAL_VERIFIED` / `REAL_SOURCE_REPLACED` | 是 |  |
| environment_ref | `ResourceRef` | 是 |  |

包含条件约束，须同时执行Schema组合规则。

### Toolchain

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| branch_id | `SIGNAL_CAN` / `CAN_UTILS` / `SAVVYCAN` / `CAN_REPLAY` / `ETHERNET_GENERATOR` / `PCAP_REPLAY` | 是 |  |
| status | `AVAILABLE` / `UNAVAILABLE` / `UNVERIFIED` / `OUT_OF_SCOPE` | 是 |  |
| reason | string | 是 | maxLength=1024 |

### Binding

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| binding_id | `Id` | 是 |  |
| kind | `SOURCE` / `MODEL` / `REPLAY_POLICY` / `FAULT_CASE` / `CODEC` / `DRIVER` / `CHANNEL` / `LINK` / `ENDPOINT` / `CONVERSION` / `EVIDENCE` / `OBSERVABLE` / `CLEANUP` / `TOOL` / `RULE_IMPLEMENTATION` / `CREDENTIAL_SCOPE` / `SYNCHRONIZATION` | 是 |  |
| name | string | 是 | minLength=1；maxLength=256 |
| profile_ref | `ProfileRef` | 是 |  |
| available | boolean | 是 |  |

### Capabilities

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| api_version | `"0.2"` | 是 |  |
| supported_commands | `Command`[] | 是 | uniqueItems=true |
| supported_actions | `Action`[] | 是 | uniqueItems=true |
| modes | `Mode`[] | 是 | minItems=1；uniqueItems=true |
| toolchains | `Toolchain`[] | 是 |  |
| bindings | `Binding`[] | 是 | maxItems=1000 |
| idempotency_retention_ms | integer | 是 | minimum=1 |
| subscriptions_supported | `false` | 是 |  |
| resource_formats | `DBC` / `ARXML` / `ICD_JSON` / `SCENARIO_JSON` / `SCENARIO_YAML` / `CAN_LOG` / `PCAP` / `PCAPNG` / `ENGINEERING_JSONL` / `JSON` / `CSV` / `BINARY`[] | 是 | minItems=1；maxItems=10000 |
| schema_resources | object（见Schema内字段）[] | 是 | minItems=0；maxItems=10000 |
| limits | object（见Schema内字段） | 是 |  |

### ProfilePage

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| items | `ProfileSummary`[] | 是 | maxItems=500 |
| next_cursor | `Cursor` 或 null | 是 |  |

### ResourcePage

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| items | `Resource`[] | 是 | maxItems=500 |
| next_cursor | `Cursor` 或 null | 是 |  |

### ScenarioPage

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| items | `ScenarioSummary`[] | 是 | maxItems=500 |
| next_cursor | `Cursor` 或 null | 是 |  |

### RunPage

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| items | `Run`[] | 是 | maxItems=500 |
| next_cursor | `Cursor` 或 null | 是 |  |

### RecordPage

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| run_id | `Id` | 是 |  |
| items | `Record`[] | 是 | maxItems=500 |
| next_cursor | `Cursor` 或 null | 是 |  |
| complete | boolean | 是 |  |
| retention_gap | boolean | 是 |  |

### Meta

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| api_version | `"0.2"` | 是 |  |
| request_id | `Id` | 是 |  |

### ListParams

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| cursor | `Cursor` | 否 |  |
| limit | integer | 否 | minimum=1；maximum=500；default=100 |

### ProfileParams

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| profile_ref | `ProfileRef` | 是 |  |

### ResourceListParams

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| kind | `ResourceKind` | 否 |  |

包含条件约束，须同时执行Schema组合规则。

### ScenarioParams

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| scenario_ref | `ScenarioRef` | 是 |  |

### SaveParams

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| definition | `ScenarioDraft` | 是 |  |
| base_ref | `ScenarioRef` | 否 |  |

### CreateParams

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| package_ref | `PackageRef` | 是 |  |
| scenario_ref | `ScenarioRef` | 是 |  |
| mode | `Mode` | 是 |  |
| source_binding_ref | string | 是 | minLength=1；maxLength=128 |
| link_ids | string[] | 是 | minItems=1；maxItems=10000；uniqueItems=true |

### ControlParams

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| run_id | `Id` | 是 |  |
| expected_revision | `UInt64` | 是 |  |
| action | `Action` | 是 |  |

### UpdateParams

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| run_id | string | 是 | minLength=1；maxLength=128 |
| expected_revision | `UInt64` | 是 |  |
| message_id | string | 是 | minLength=1；maxLength=128 |
| values | `Values` | 是 |  |
| link_id | string | 是 | minLength=1；maxLength=128 |

### RunParams

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| run_id | `Id` | 是 |  |

### RecordParams

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| run_id | `Id` | 是 |  |
| after_cursor | `Cursor` | 否 |  |
| limit | integer | 否 | minimum=1；maximum=500；default=100 |

### Request

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| cmd | `Command` | 是 |  |
| params | `Meta` | 是 |  |

包含条件约束，须同时执行Schema组合规则。

### Response

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| kind | `"RESPONSE"` | 是 |  |
| api_version | `"0.2"` | 是 |  |
| request_id | `Id` | 是 |  |
| cmd | `Id` | 是 |  |
| status | `SUCCESS` / `ACCEPTED` / `REJECTED` / `FAILED` | 是 |  |
| code | string | 是 |  |
| message | string | 是 | maxLength=1024 |
| timestamp | `UtcTime` | 是 |  |
| operation_id | `Id` 或 null | 是 |  |
| data | 按组合Schema | 是 |  |
| error | `Error` 或 null | 是 |  |

包含条件约束，须同时执行Schema组合规则。

### PackageRef

引用 `urn:hil:input-simulator:package-contract:0.2#/$defs/PackageRef`，字段见对应定义。

### Package

引用 `urn:hil:input-simulator:package-contract:0.2#/$defs/Package`，字段见对应定义。

### PackageDefinition

引用 `urn:hil:input-simulator:package-contract:0.2#/$defs/PackageDefinition`，字段见对应定义。

### PackageSummary

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| ref | `PackageRef` | 是 |  |
| name | string | 是 | minLength=1；maxLength=256 |
| qualification | `DRAFT` / `FROZEN` | 是 |  |
| validation_status | `PENDING` / `VALID` / `INVALID` | 是 |  |
| scenario_count | integer | 是 | minimum=1 |

### PackagePage

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| items | `PackageSummary`[] | 是 | minItems=0；maxItems=500 |
| next_cursor | `Cursor` 或 null | 是 |  |

### PackageParams

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| package_ref | `PackageRef` | 是 |  |

### PackageSaveParams

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| definition | `PackageDefinition` | 是 |  |
| base_ref | `PackageRef` | 否 |  |

### ResourceParams

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| resource_ref | `ResourceRef` | 是 |  |

### ImportDeclaration

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| name | string | 是 | minLength=1；maxLength=256 |
| kind | `ResourceKind` | 是 |  |
| format | `DBC` / `ARXML` / `ICD_JSON` / `SCENARIO_JSON` / `SCENARIO_YAML` / `CAN_LOG` / `PCAP` / `PCAPNG` / `ENGINEERING_JSONL` / `JSON` / `CSV` / `BINARY` | 是 |  |
| size_bytes | `UInt64` | 是 |  |
| sha256 | `Hash` | 是 |  |

包含条件约束，须同时执行Schema组合规则。

### ImportBeginParams

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| declaration | `ImportDeclaration` | 是 |  |

### ImportParams

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| upload_id | string | 是 | minLength=1；maxLength=128 |

### ChunkParams

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| upload_id | string | 是 | minLength=1；maxLength=128 |
| offset_bytes | `UInt64` | 是 |  |
| data_base64 | string | 是 | minLength=4；maxLength=87384；pattern="^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==\|[A-Za-z0-9+/]{3}=)?$" |
| chunk_sha256 | `Hash` | 是 |  |

### ReadChunkParams

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| resource_ref | `ResourceRef` | 是 |  |
| offset_bytes | `UInt64` | 是 |  |
| length_bytes | integer | 是 | minimum=1；maximum=65536 |

### Upload

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| upload_id | string | 是 | minLength=1；maxLength=128 |
| state | `OPEN` / `COMMITTED` / `ABORTED` / `EXPIRED` | 是 |  |
| next_offset_bytes | `UInt64` | 是 |  |
| declaration | `ImportDeclaration` | 是 |  |
| max_chunk_bytes | integer | 是 | minimum=1；maximum=65536 |
| expires_at | `UtcTime` | 是 |  |
| resource_ref | `ResourceRef` 或 null | 是 |  |

包含条件约束，须同时执行Schema组合规则。

### ResourceChunk

| 字段 | 类型或枚举 | 必填 | 约束 |
|---|---|---|---|
| resource_ref | `ResourceRef` | 是 |  |
| offset_bytes | `UInt64` | 是 |  |
| length_bytes | integer | 是 | minimum=1；maximum=65536 |
| data_base64 | string | 是 | minLength=4；maxLength=87384；pattern="^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==\|[A-Za-z0-9+/]{3}=)?$" |
| chunk_sha256 | `Hash` | 是 |  |
| eof | boolean | 是 |  |
