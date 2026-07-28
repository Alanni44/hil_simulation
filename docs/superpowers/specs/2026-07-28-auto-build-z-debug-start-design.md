# Z 调试启动脚本自动生成设计

## 目标

Ubuntu RT 操作员只需执行：

```bash
./scripts/start_z_debug.sh
```

脚本自行定位或生成四旋翼实时模型可执行文件，然后继续既有的无 WebSocket Z 任务启动流程。

## 模型可执行文件选择

1. 若设置了 `HIL_Z_MODEL_EXECUTABLE`，将它视为高级显式覆盖；必须为绝对、普通且可执行的文件。
2. 否则读取 `artifacts/z_mission/logs/build_result.json`。仅当其中 `code` 为零且 `exe_path` 指向绝对、普通且可执行的文件时，复用该产物。
3. 若构建结果清单缺失、不可解析、非成功或其产物无效，调用 `scripts/build_quadrotor_demo.sh`。
4. 自动构建成功后，使用构建脚本最终输出的绝对可执行路径，并再次执行绝对路径、普通文件与执行权限校验。

脚本不猜测二进制名称；构建结果清单或构建脚本输出是唯一可信来源。

## 启动与失败处理

模型路径解析完成后，保留现有预检、任务加载、UE4 目标校验、锁、PID 所有权和无 WebSocket 启动顺序。

若自动构建失败，启动脚本以非零退出，且不创建模型/调试进程。若构建成功但后续预检失败，保留现有受限回滚行为。

## 使用方式

日常：

```bash
./scripts/start_z_debug.sh
```

高级覆盖：

```bash
HIL_Z_MODEL_EXECUTABLE=/absolute/path/to/verified_model_rt \
  ./scripts/start_z_debug.sh
```

不再接受位置参数，避免出现“手动路径”与自动选择同时存在的歧义。

## 验证范围

按用户要求，不增加或运行回归测试。实施后仅运行 Bash 语法检查；Ubuntu RT、MATLAB、GCC 和真实 UE4 联调仍由目标机执行。
