# HIL 任意 Simulink 模型构建契约设计

## 目标

使上传的 `.slx` 模型能够在 Ubuntu 18.04、MATLAB R2018b、Python 3.6.9 与 GCC 7.x 目标环境中，以可审计的方式生成并连接 HIL C 核心。构建仅接受满足明确接口契约的模型；不再通过猜测模型拓扑让不兼容模型“带病运行”。

## 模型接口契约

- 根级 Inport 和 Outport 必须是标量数值信号。允许 `double`、`single`、有符号/无符号整数和布尔值；拒绝 Bus、向量、矩阵、定点和枚举端口。
- 必须映射 `pos_x`、`pos_y`、`pos_z`。缺少任一字段时，构建返回非零状态并说明缺失字段。
- 可选映射包括姿态、速度、加速度、经纬高和 `airborne`。缺少可选字段时，生成的 C 访问宏返回固定默认值并在构建结果中记录。
- 标准字段首先通过 `adapt_model.m` 中的别名匹配；调用方可提供映射 JSON 覆盖或补充别名匹配。
- 仅已识别为数值标量的 Inport 可接收命令或 `tune` 请求。未知、只读、非有限或非标量值必须被拒绝并记录日志。

## MATLAB 构建层

- `build_script.m` 以 ERT 实际生成的模型主头文件作为唯一 ABI 来源，发现外部输入/输出类型、全局变量、初始化/步进/终止符号与字段声明。
- 构建脚本生成 `model_rt_bridge.h`，将实际 ERT 类型别名为 `ModelU_t` 和 `ModelY_t`，并导出真实模型符号。
- `model_rt_wrapper.h` 包含该 bridge 头，保证 `main_rt.c` 和 `model_rt_wrapper.c` 使用相同 ABI。
- `model_config.h` 在 `ModelU_t` 已定义后使用，生成状态读取宏、类型安全输入写入宏与调参类型表。GCC 命令不得再使用 `-include model_config.h`。
- `adapt_model.m` 只分析和验证接口，不再将 Constant、Step、Scope 或 ToWorkspace 自动替换为端口，也不修改上传模型拓扑。

## C 核心

- 状态读取使用按字段生成的宏：存在映射时读取模型成员；缺失可选字段时直接返回默认值，永不引用不存在的成员。
- 调参表包含字段名、偏移、数值类型和可写标记。C 核心依据类型写入，避免把 `double` 写入 `float`、整数或布尔字段所造成的内存破坏。
- UDP 命令线程只更新互斥保护的待应用快照；1 ms 循环在模型 `step` 前统一应用快照，避免并发读写模型输入。

## 验证与部署

- `integration_test.sh` 必须正确检查文件与进程状态，按 `FlightState_t` 的 30 个解包字段使用正确索引，并在调参后收到状态时判定成功。
- 增加静态回归测试，验证构建命令不再强制包含 `model_config.h`、严格输出契约存在、测试脚本的状态索引不越界。
- 目标机验收必须运行 `scripts/integration_test.sh` 并保留 MATLAB、GCC 和测试输出日志。
- Python 依赖固定为兼容 Python 3.6 的版本；启动脚本要求显式设置 `SLX_PATH` 或提供存在的默认路径。

## 非目标

- 本次不支持 Bus、向量、矩阵、枚举或定点端口。
- 本次不自动推断 Scope 连接、Constant 参数语义或模型内部拓扑。
- 本次不在 Windows 上宣称完成 MATLAB R2018b/Ubuntu 实机验证。
