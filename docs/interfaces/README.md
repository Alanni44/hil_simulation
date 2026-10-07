# 输入模拟器接口资料

**唯一完整阅读入口：[输入模拟器完整接口定义 v0.3 单文件汇总](输入模拟器完整接口定义_v0.3_单文件汇总.md)。**

该文件自包含全部语义、输入字段、前后端 API、传输/端口/工具链、替换门禁及机器定义，无需再打开其他附件查参数。

- `baseline/`：14 份冻结来源，供运行库、校验与重建使用；不是另一份推荐阅读版本。v0.2 package Schema仅作为当前 API 资源元数据依赖保留，不能覆盖v0.3业务定义。
- `archive/v0.1/`、`archive/v0.2/`：7 份历史资料，仅作可恢复归档，不用于当前业务对接。

本次整理只改变存放路径，原始文件内容与共同HIL-ICD-1.0基线指纹不变。不要直接编辑汇总文件：修订共同基线后，通过`scripts/build_contract_single_file.py`重新生成；校核已有汇总用`--check`。

程序加载基线目录：`docs/interfaces/baseline`。静态QA入口：`artifacts/interface_contract_validation/check_contract_v03.py`。定义完整不代表应用、实时、硬件或正式3.3替换已经验收。
