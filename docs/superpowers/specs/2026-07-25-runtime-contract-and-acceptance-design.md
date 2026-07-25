# HIL 实时模型契约、UE4 状态与验收证据设计

## 背景与决定

本系统的职责是接入甲方提供的 Simulink `.slx`，在 Ubuntu 18.04 RT、MATLAB R2018b、GCC 7.x 和 Python 3.6.9 上生成并运行 ERT 模型，向 UE4 输出确定的飞行状态。

已确认的范围：

- 每个模型必须配套一份显式的 `hil_contract.json`；它是模型接入、在线调参和数据转换的唯一业务契约。
- UE4 渲染所需的位置、姿态和速度是必需数据，模型不能缺失后以零值或伪造数据替代。
- 单位、坐标和姿态约定采用航空/无人机常用规范。
- 当前不实施硬件接口（CAN、RS422、实体飞控）。模型上传、归档、版本、审批和展示由外部模型管理系统承担；HIL 不实现这些业务功能。

## 目标架构

```text
外部模型管理系统
  ├─ 模型包归档、版本、审批、状态展示
  └─ package_path + request_id + 哈希
          |
          v
SLX 模型包 + hil_contract.json
          |
          v
MATLAB 分析与 ERT 代码生成 ----> 结构/类型/字段严格校验
          |
          v
GCC 编译的 C 实时核心 (1 ms)
          |             |
          |             +--> 参数命令、生命周期命令、确认回执
          v
规范化 NED 飞行状态 UDP
          |
          v
Python UE4 适配层 ----> UE4 渲染坐标、姿态和任务事件
```

`hil_contract.json` 由模型交付方提供，或由平台维护人员根据模型 ICD 补录；外部模型管理系统负责保存、审批和展示。HIL 平台不得通过端口名称、Constant 块或 C 结构内存偏移猜测其业务语义。

## 坐标、单位与必需状态

### 内部标准状态

C 实时核心输出的规范状态采用局部导航 NED 坐标系：North-East-Down，原点由模型契约说明，所有状态附带单调递增的 `sim_time_s` 和序号。

| 字段 | 单位 | 规则 |
| --- | --- | --- |
| `north_m`, `east_m`, `down_m` | m | 必需；局部 NED 位置 |
| `vn_mps`, `ve_mps`, `vd_mps` | m/s | 必需；NED 速度 |
| `q_w`, `q_x`, `q_y`, `q_z` | 无量纲 | 必需；单位四元数，表示机体 FRD 到导航 NED 的姿态 |
| `p_radps`, `q_radps`, `r_radps` | rad/s | 必需；机体系角速度 |
| `airborne` | bool | 必需；飞行/离地状态 |
| `sim_time_s`, `sequence` | s、无量纲 | 必需；仿真时间与状态序号 |

契约可另外声明 GPS 经纬高、加速度、电池、执行器、告警等遥测字段。经纬高到本地坐标的转换只允许在定义了地理原点和椭球基准时使用。

### UE4 适配

Python UE4 Bridge 是唯一允许进行 NED 到 Unreal 坐标变换的组件。它将四元数转为 UE4 所需旋转表示，转换公式和轴向在代码与测试中固定。UE4 对外协议可保留 `x_forward_y_right_height_up` 的渲染字段，但不得再被视为 C 核心的内部状态标准。

构建必须在以下情况失败：缺少任一必需字段、字段非标量、字段类型不受支持、映射未声明单位、四元数来源/坐标系不一致。运行时必须拒绝 NaN、Inf、零范数四元数和明显无效的状态，而不是静默转为默认值。

## 模型包、外部交接与模型契约

外部模型管理系统归档并交给 HIL 的不是单一 `.slx`，而是一个不可变模型包：

```text
<package_path>/
  package_manifest.json
  <top_model>.slx
  hil_contract.json
  dependencies/
    referenced_model.slx        # 若使用 Model Reference
    parameters.sldd             # 若使用 Data Dictionary
    init_model.m                # 若使用初始化脚本
    lookup_table.mat            # 若使用查表数据
    custom_code/                # 若使用经批准的 S-Function 源码
    matlab_functions/           # 若模型依赖外部 MATLAB 函数
```

`package_manifest.json` 至少声明 `model_ref`、外部系统的 `model_revision_ref`、`top_model`、MATLAB 版本、全部文件 SHA-256 和包 SHA-256。版本引用只用于日志和审计；HIL 不提供版本浏览、激活历史版本或回滚接口。

外部系统提交构建/部署请求时至少传入：`request_id`、`operation`、`model_ref`、`model_revision_ref`、受控的 `package_path` 和 `package_sha256`。HIL 仅从允许的本地受控目录读取包，核验哈希后进入构建流程；生产环境不由 HIL 从任意 URL 下载并编译模型。

HIL 返回的构建结果至少包含：`request_id`、状态（`RECEIVED`、`VALIDATING`、`BUILDING`、`VERIFYING`、`READY`、`DEPLOYED` 或 `FAILED`）、模型/契约哈希、失败阶段、日志路径和验收证据路径。外部模型管理系统负责将结果展示给操作人员并保存其历史。

模型包中的 `hil_contract.json` 至少包含：

```json
{
  "contract_version": 1,
  "model_name": "example_uav",
  "state": {
    "frame": "NED",
    "orientation": "FRD_TO_NED_QUATERNION",
    "outputs": {
      "north_m": "pos_n",
      "east_m": "pos_e",
      "down_m": "pos_d",
      "vn_mps": "vel_n",
      "ve_mps": "vel_e",
      "vd_mps": "vel_d",
      "q_w": "quat_w",
      "q_x": "quat_x",
      "q_y": "quat_y",
      "q_z": "quat_z",
      "p_radps": "rate_p",
      "q_radps": "rate_q",
      "r_radps": "rate_r",
      "airborne": "airborne"
    }
  },
  "parameters": []
}
```

MATLAB 分析阶段负责确认契约映射到真实根级输出或经明确支持的 ERT 可导出信号；代码生成阶段再以生成头文件为 ABI 真相源验证字段和类型。两阶段任一失败均不得产生可部署可执行程序。模型开发方对变量语义、单位、坐标和参数类别负责；HIL 对模式、类型和生成 ABI 一致性负责；UE4 仅消费规范化状态，不依赖任何模型内部字段名。

## 在线参数策略

每个参数在契约中必须明确：生成代码中的符号/字段、数值类型、单位、默认值、最小值、最大值、更新类别和允许的任务阶段。只接受有限的标量数值或布尔值。

| 类别 | 例子 | 应用规则 |
| --- | --- | --- |
| `live` | 风速/风向、阵风、传感器噪声、偏置、链路延迟丢包、速度和爬升限制 | 在下一次 `model_step()` 前原子生效 |
| `reset_only` | 质量、惯量、重心、气动系数、推进曲线、控制器增益、初始状态 | 仅暂停后执行复位时生效 |
| `readonly` | 由模型计算的状态或诊断量 | 只读，不接受写入 |

禁止把求解器步长、模型拓扑、端口映射、代码生成配置、线程优先级或任意内存位置暴露为参数。

参数命令使用 `request_id`。C 核心先做名称、类型、范围和运行状态校验；仅通过校验的整组参数才会在同一仿真步边界一次性提交。回执必须返回每一字段的接受/拒绝原因与生效序号。

## 生命周期

C 实时核心实现下列状态：

```text
RUNNING <-> PAUSED
   |           |
   v           v
RESETTING ----> RUNNING
   |
   v
ENDED
```

- `pause`：停止调用 `model_step()`，但保持通信和回执；仿真时间与状态序号不前进。
- `resume`：从 `PAUSED` 恢复周期运行。
- `reset`：重新初始化模型、输入快照和任务状态；`reset_only` 参数在此边界应用。
- `mission_end`：停止任务驱动并进入 `ENDED`；此后不再步进，直到明确复位。

Python 仅在收到 C 核心的成功回执后，才向 UE4 发送相应的生命周期事件。现有单向转发不得作为操作成功的依据。

## HIL 与外部模型管理系统的边界

外部模型管理系统负责模型上传、文件归档、版本号、审批、模型列表、下载授权和页面展示。HIL 仅作为受控的构建与运行执行器：校验已交接的模型包、调用 MATLAB/GCC、启动或停止唯一活动实例、维护在线参数和返回运行/验收结果。

HIL 保留独立的临时工作目录、构建缓存和验收证据目录，以避免 MATLAB 文件生成冲突并支持问题审计；这些目录不是模型版本仓库。删除或禁用本地模型 registry、历史构建激活、回滚、活动模型软链接、远程 SLX 下载和运行中热切换入口。每次外部系统请求部署新包时，HIL 必须先停止现有核心、完成完整构建验证，然后启动唯一的新实例。

任务航线、目标、仿真控制和在线参数也不属于模型包。外部系统在模型部署成功后，通过独立的 `load_mission`、生命周期或 `tune` 请求发送；HIL 仍以当前模型契约作为最终校验依据。

## 真实测试与证据包

Windows 上的单元测试和静态检查只能证明脚本/协议逻辑，不能作为目标环境验收成功的证据。每个实现包必须同时交付 Ubuntu 18.04 RT 上的可重复执行测试，并保存：

```text
artifacts/acceptance/<UTC-run-id>/
  environment.json       # Ubuntu 内核、GCC、MATLAB、Python 版本
  source-manifest.json   # 合同、SLX、源码和生成代码的 SHA-256
  build.log              # MATLAB ERT 与 GCC 完整输出
  runtime.log            # 核心、Python Bridge 的日志
  packets.ndjson         # 原始命令、回执、规范状态、UE4 报文
  assertions.json        # 每项断言、时间、结果、失败原因
  result.json            # 唯一汇总结论；任意 skip/失败即为 failed
```

所有验收脚本必须在依赖缺失时失败，不得以“跳过”标记通过。每项改造的最低实测证据如下：

| 改造包 | Ubuntu 真实测试 | 通过证据 |
| --- | --- | --- |
| 契约与构建校验 | 有效模型成功 ERT/GCC；分别缺失姿态、速度、单位的模型失败 | 三份失败断言和一份成功构建日志 |
| 在线参数 | 真实 ERT 测试模型以可调 `gain` 驱动输出；运行中修改 `gain` | 修改确认回执，且生效序号后的输出按预期变化 |
| 规范状态 | 固定输入运行模型并监听 C UDP | NED 位置、速度、归一化四元数及状态序号均通过断言 |
| UE4 适配 | 使用协议模拟 UE4 接收端 | 已知 NED 位置、90°偏航、速度的 UE4 报文轴向和旋转均正确 |
| 生命周期 | 运行、暂停、恢复、复位、结束的完整序列 | 暂停时序号冻结、恢复后递增、复位后状态重置、每个请求有对应回执 |
| 外部模型管理对接 | 从受控目录接收模型包和构建请求 | 请求、包/契约哈希、构建回执和证据路径完整对应 |
| 单模型部署 | 导入第二个模型前停止旧运行实例 | 无本地热切换/回滚入口；新实例仅在完整验证后启动 |

## 非目标

- 当前不新增 CAN、CANFD、RS422、MAVLink 或真实飞控链路。
- 当前不实现模型上传、版本、回滚、多人协同和运行中的模型热切换；这些业务能力由外部模型管理系统负责。
- 不修改甲方模型的控制拓扑来迁就平台；模型不满足契约时由交付方修正模型或契约。
