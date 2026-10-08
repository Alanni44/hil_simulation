# HISTORY PCAP Round 5A：Real Model Assets / Internal Bridge Contract Gate

日期：2026-10-07（Asia/Shanghai）。根目录：`E:\GuoZhao\Desktop\UAVDemo\3_6\code_handoff_33_36_20261006`。
授权：[本轮任务文档](prompt_round5a_real_model_assets_bridge_contract_gate_20261007.md)。输出只新增本报告及 [INTERNAL Bridge V1](internal/model_consumer_bridge_v1.md)，未施工正式Consumer。

标签定义：**已确认**＝本次文件搜索、源码、hash或只读检查直接证明；**合理推测**＝依据冻结协议和源码选定的规范性设计，未实现/未运行；**待确认**＝缺真实资产、目标环境或负责人提供证据。下文每节明确证据标签；“冻结”只冻结设计，不宣称运行能力。

## 1. Executive Summary

```text
REAL_MODEL_ASSET_GATE = NO_GO
INTERNAL_BRIDGE_CONTRACT = FROZEN
ID7_CONSUMED = NOT_IMPLEMENTED / NOT_REQUIRED_FOR_MVP
REAL_MODEL_RUNNABLE = NOT_VERIFIED
REAL_E2 = NOT_EVALUATED
5B_REAL_MODEL_ENTRY = BLOCKED_BY_REAL_ASSETS
```

**已确认**：约定项目范围未发现真实quadrotor_hil package、hil_contract、model_contract.h、model_rt_bridge.h、build_script/等价模型生成流程、generated ABI、模型objects、build target或可执行体。找到的wrapper/contract validator及测试metadata不满足真实模型资产最低条件。NO_GO只针对本次实际搜索范围，不声称整个机器/其它主机没有模型。

**合理推测（本轮冻结设计）**：采用C启动instance + Gateway新run epoch组合；C为authoritative 1ms完成步；提前STAGED，S开始前最终四值ModelU commit/readback才APPLIED；127.0.0.1 UDP；contract path/group JSON；C OwnerRecord复核；年龄严格<100ms；同key同hash幂等；结果查询与UNKNOWN封存；先预留completion再执行；生命周期屏障和重启隔离。完整字段/Schema只维护在链接的INTERNAL V1。

**待确认（阻塞）**：真实模型提供者须提交可追溯包及同构建产物、getter、初始状态恢复入口、工具链/依赖/可执行体身份。FROZEN不等于模型ready或5B授权；NO_GO下禁止以fake进入“真实模型实施”。

## 2. Search Scope

**已确认**：按优先级核查handoff root、父目录`3_6`、整个`E:\GuoZhao\Desktop\UAVDemo`（包含telemetry-websocket-demo、winBoxDemo）。父目录与`3_6`是同一目录，不假报重复独立搜索。未扩大到其它盘符/私人目录。

先用`rg --files --hidden`枚举强相关名称，再用Python os.walk复核隐藏文件与rg可能忽略的项目文件。任务开始的可读业务范围共**752文件、无遍历权限错误**。搜索hil_contract.json、model_contract.h、model_rt_bridge.h、build_script.m、package_manifest.json、CMakeLists/Makefile、main_rt/main_rt.exe、config_loader.py，所有.m/.slx/.mdl/.zip/.7z/.o/.obj/.a/.so及quadrotor/multirotor相关文件；未发现真实资产或打包模型候选，无多个真实版本需要比较。唯一build名称脚本是`build_contract_single_file.py`，用于ICD文档汇总，不生成模型。

排除`.git`、node_modules、.pnpm-store、.conda-envs、.workbuddy、__pycache__、.pytest_cache（依赖环境、工具缓存/应用数据，不作为交付模型资产范围）；未把隐藏模型目录统一排除，未排除项目artifacts或backend target。未跟随symlink到范围外。结论适用于这些排除项之外；这些依赖/缓存不构成已验证模型来源。压缩模型候选为0，无须解压/修改任何真实文件。

**已确认**：读取Round5 Architecture Review全文、Round4 Report全文、README_代码整理及原SHA清单；检查Bindings/Queue/Receiver/Session、core_client、main_rt、wrapper、arbiter、local_udp及相关生成符号引用。工作区/父层未发现适用AGENTS.md；handoff非Git仓库，使用内容hash保护。

## 3. Asset Inventory

**已确认**：如下SHA256来自本次实际字节读取，分类反映其在本包中的用途。REAL_SOURCE_ARTIFACT仅表示真实共用基础源码，不表示真实模型生成资产。所有源码只能支持后续实现/审查，没有一项单独支持real E2。

| Asset | Path | SHA256 | Classification | Can support real E2? |
|---|---|---|---|---|
| C entry | [c_core/src/main_rt.c](../c_core/src/main_rt.c) | `63bf8a61b6a20ca4d9ea2195e292fba4d731a5e22a5efc0850f8dcbb61a4b2e1` | REFERENCE_ONLY | 否；仅源码/结构或历史参考 |
| Wrapper ABI requirement | [c_core/src/model_rt_wrapper.h](../c_core/src/model_rt_wrapper.h) | `a9c758c2ac51d4928b4c2fef7bc778baba10c3357c3815662a9d021c0b61e369` | REFERENCE_ONLY | 否；仅源码/结构或历史参考 |
| Wrapper symbols | [c_core/src/model_rt_wrapper.c](../c_core/src/model_rt_wrapper.c) | `f05125ba9528410f7eb7991b9546391fa807a49fe6f48bc15637ba41ab92fb94` | REFERENCE_ONLY | 否；仅源码/结构或历史参考 |
| Owner declaration | [c_core/src/control_arbiter.h](../c_core/src/control_arbiter.h) | `c82b8ce1d477117e9df5b82875d272234842557a9c5f49e0abf7cd22e871a577` | REFERENCE_ONLY | 否；仅源码/结构或历史参考 |
| Owner implementation | [c_core/src/control_arbiter.c](../c_core/src/control_arbiter.c) | `3d33e37ad0e6bbf66b893691594b744da95ec9703467423f726029c6850f0325` | REFERENCE_ONLY | 否；仅源码/结构或历史参考 |
| UDP declaration | [c_core/src/local_udp.h](../c_core/src/local_udp.h) | `a56fd113b7e84af31286080ef47fc9d5f1227a3dbbeb3286a660a50306d4a732` | REFERENCE_ONLY | 否；仅源码/结构或历史参考 |
| UDP transport | [c_core/src/local_udp.c](../c_core/src/local_udp.c) | `5df383a17f5c5010585d267f8d73a9d2266e239763d3fa84059d02b6b745d5f6` | REFERENCE_ONLY | 否；仅源码/结构或历史参考 |
| Python UDP reference | [python_services/core_client.py](../python_services/core_client.py) | `e739927edd665a3421c78ca1f55d3dcfba276178f838991cfa9e1746180ae984` | REFERENCE_ONLY | 否；仅源码/结构或历史参考 |
| Package/hash validator | [python_services/shared/model_package.py](../python_services/shared/model_package.py) | `e998b956d7f5c38f5156a6dbb817478fecbc1e4d2e59c9ac5090e4f916353dd7` | REFERENCE_ONLY | 否；仅源码/结构或历史参考 |
| Binding structural gate | [icd_gateway/model_bindings.py](../icd_gateway/model_bindings.py) | `9850bedbaddbec48b393b7c14254b73c91ff29c73c061f32d0cd976847733251` | REAL_SOURCE_ARTIFACT | 否；仅源码/结构或历史参考 |
| Queue primitives | [icd_gateway/model_queue.py](../icd_gateway/model_queue.py) | `784781229f031e21694ae430688c7b9609a57e5ad152d14f33eb37eef131cd47` | REAL_SOURCE_ARTIFACT | 否；仅源码/结构或历史参考 |
| Metadata fixture helper | [tests/icd_gateway/test_model_bindings.py](../tests/icd_gateway/test_model_bindings.py) | `4d033087cc9227705d8f17f258d294081f051ac1560b7adcef9fb141528b2d74` | TEST_FIXTURE | 否；仅源码/结构或历史参考 |
| Frozen example payloads | [docs/interfaces/baseline/input-simulator-v0.3.examples.json](../docs/interfaces/baseline/input-simulator-v0.3.examples.json) | `939dfc1fd12ff6bcf246b5b39ada1a8e13b8875ddad87520e49a87cd2808659f` | TEST_FIXTURE | 否；仅源码/结构或历史参考 |
| Frozen binding/probe catalogue | [docs/interfaces/baseline/input-simulator-icd-v0.3.json](../docs/interfaces/baseline/input-simulator-icd-v0.3.json) | `8ddeeac31fad309043ed8d60f8f1aa585c749f65f34a1bc972a05b3f16bf38b2` | REFERENCE_ONLY | 否；仅源码/结构或历史参考 |
| Frozen v0.3 specification | [docs/interfaces/baseline/input-simulator-data-contract-v0.3.md](../docs/interfaces/baseline/input-simulator-data-contract-v0.3.md) | `80d6412a9934442f0b526a25d4d72680777f0d370a3c9cf919994e308ad06998` | REFERENCE_ONLY | 否；仅源码/结构或历史参考 |
| 真实hil_contract | `hil_contract.json`（搜索范围内无实文件；非实际部署路径） | —（不存在，不造hash） | MISSING | 否 |
| 生成input契约 | `model_contract.h`（搜索范围内无实文件；非实际部署路径） | —（不存在，不造hash） | MISSING | 否 |
| 生成ABI bridge | `model_rt_bridge.h`（搜索范围内无实文件；非实际部署路径） | —（不存在，不造hash） | MISSING | 否 |
| MATLAB生成脚本 | `build_script.m 或等价生成流程`（搜索范围内无实文件；非实际部署路径） | —（不存在，不造hash） | MISSING | 否 |
| Simulink顶层/依赖 | `quadrotor_hil.slx / .mdl / dependencies`（搜索范围内无实文件；非实际部署路径） | —（不存在，不造hash） | MISSING | 否 |
| 真实生成C/C++及objects | `quadrotor_hil generated sources / .o / .a`（搜索范围内无实文件；非实际部署路径） | —（不存在，不造hash） | MISSING | 否 |
| 真实package manifest | `package_manifest.json`（搜索范围内无实文件；非实际部署路径） | —（不存在，不造hash） | MISSING | 否 |
| 真实C build target | `CMakeLists.txt / Makefile / link script`（搜索范围内无实文件；非实际部署路径） | —（不存在，不造hash） | MISSING | 否 |
| 真实可执行体 | `main_rt executable`（搜索范围内无实文件；非实际部署路径） | —（不存在，不造hash） | MISSING | 否 |
| 历史测试引用的六电机声明 | `artifacts/generic_models/multirotor_6/hil_contract.json`（搜索范围内无实文件；非实际部署路径） | —（不存在，不造hash） | MISSING | 否 |
| 目录动态合成metadata | `declared_runtime()`；内存对象，无独立资产文件 | —；helper源码hash见上 | SYNTHETIC_METADATA | 否；不落盘、不作production资产 |

**已确认**：REAL_DEPLOYMENT_ARTIFACT=0、真实quad GENERATED_ARTIFACT=0；REFERENCE_ONLY不升级为生成/部署资产。目录model_name、probe声明或真实PCAP不算模型产物。原文件清单237项中235项当前hash相符，`input_simulator/replay_export.py`、`tests/icd_gateway/test_replay_export.py`两项在本轮开始已不同；未还原或修复。清单是旧提取快照，不能拿其两项差异冒充本轮修改。

## 4. Real vs Fixture Classification

**已确认**：`declared_runtime()` docstring明确为Metadata test fixture only，动态从冻结97条mapping生成结构，无生成模型、ABI或E2 consumer。baseline examples是业务payload fixture，不是运行hil_contract。main_rt的V2兼容块（24–34）给默认4执行器/spec及setter转发，未提供ModelU/ModelY ABI，不能证明真实四电机包。

**已确认**：没有TEST_ONLY bridge/fake ABI header候选；“测试header没找到”不证明生产ABI存在。旧六电机测试路径亦不存在；即使未来提供，也不能默认用它代替quadrotor_hil。多个版本若后续提供，须按model_name/version/metadata/hash/step/ports/generator/冻结等价比对，绝不按mtime选最新。

## 5. hil_contract Validation

**已确认**：真实hil_contract.json不存在，以下真实资产检查均**未执行/不通过资产门禁**：model_name=quadrotor_hil、version整数2或3、step_s=0.001、三个input roots、motor_command mode、四个double、范围0..1、环境default/全部fault/参数exported_global/live/phase结构等价。不能填成fixture通过即真实通过。

**已确认**：现有[ModelBindings](../icd_gateway/model_bindings.py):22–76已经强制以上完整结构，map_message:78–89要求完整组快照并产生path/target_field/value_json。已有检查器足够做后续真实asset结构门禁；本轮没有重写checker、生成“兼容”hil_contract或缩减为只查ID7。

**待确认**：收到真实文件后必须在原Contract.load verified baseline上调用`ModelBindings(contract, "quadrotor_hil",真实JSON)`；通过仍只证明结构，ABI/行为另验。

## 6. Generated ABI Validation

**已确认**：model_rt_bridge.h缺失。wrapper.h:11–28需要MODEL_RT_BRIDGE_HEADER、MODEL_U_T_DEFINED/MODEL_Y_T_DEFINED，否则编译#error；wrapper.c:7–21需要ModelU_t/ModelY_t、MODEL_U_VAR/MODEL_Y_VAR、MODEL_INIT_FN/MODEL_STEP_FN/MODEL_TERM_FN；不存在production fallback ABI。故不能证明类型布局、真实符号或一致链接。

**已确认**：main_rt:354–362使用HilInputSpec、hil_contract_find_input、hil_contract_set_input，766–776使用set_actuators；这只证明调用要求。生成model_contract.h缺失，其“真实生成/同quad包/正式spec/setter/getter”均**待确认**。当前wrapper model_get_input返回真实变量指针的代码声明，不等于已验证motor getter。

**待确认（Blocking for final APPLIED probe）**：生成contract-backed input getter或经同构建验证的typed accessor；本轮没有添加getter，也没有用Python值回显伪造probe。

## 7. Build / Executable Trace

**已确认**：main_rt.c及wrapper引用build_script.m，但脚本不在搜索范围，标记**待提供**。只能确认源码注释称由build_script提供bridge；谁实际生成model_contract.h/bridge/C/C++、输出目录、MATLAB/Simulink/ERT版本、manifest/可复现hash、真实include/link命令均**待确认**，不猜。

| 检查 | 结论/标签 |
|---|---|
| main_rt源码 | 已确认存在；REFERENCE_ONLY |
| generated ModelU/ModelY与model functions | 已确认本范围无实体 |
| build target/script | 已确认无CMake/Make/模型构建脚本 |
| model executable/objects | 已确认未找到 |
| json-c/pthread/POSIX | 已确认源码依赖`json-c/json.h`、pthread、clock/UDP及Linux头；目标开发/链接库待确认 |
| host compiler | 已确认Windows PATH有MinGW gcc；不能证明Linux依赖或real build |
| Python core_client | 已确认依赖缺失config_loader，默认2s receipt；不是可直接运行正式bridge |
| compile feasibility | 已确认缺生成头是静态编译阻塞；未制造stub/补ABI/编译或运行模型 |

**已确认**：本轮没有部署、安装依赖、启动C、执行真实PCAP→Model或运行MATLAB。文件存在不能升级成真实可构建；不假报已编译binary或目标库存在。

## 8. ModelBindings Against Real Asset

```text
REAL_HIL_CONTRACT_BINDINGS = NOT_RUN_ASSET_MISSING
FIXTURE_BINDINGS_CHECK = 9 PASSED / 1 ERROR / 10 TOTAL
```

**已确认**：使用现有隔离Python3.12 `E:\GuoZhao\Desktop\UAVDemo\.conda-envs\uav-history-pcap\python.exe -B -X utf8 -m unittest discover -s tests/icd_gateway -p test_model_bindings.py -v`。本次10 tests、9 pass、0 failures、1 error，5.054s，exit1。唯一error为既有`test_existing_six_motor_declaration_is_not_full_v03_qualification`读取缺失六电机hil_contract的FileNotFoundError。未跳过、修复或补假fixture；本次结果不等于real model qualified。

**已确认**：`scripts/build_contract_single_file.py --check` exit0、SINGLE_FILE_CONTENT_VERIFIED；14 embedded sources、663 schema refs、59 business messages、97 bindings。仅验证冻结文档汇总一致性，runtime hardware replacement仍NOT_VERIFIED。未重跑历史1001项全量回归，Round4记录不冒充本次结果。

## 9. Missing Assets / Blocking Dependencies

**已确认**：资产gate缺件依次为真实quad package与manifest、完整hil_contract、generated contract/bridge/ABI源、build script及generator metadata、可追溯build/link target与依赖、executable与hash；缺这些不是“轻微可选项”，所以NO_GO而非CONDITIONAL_GO。

**待确认**：getter、模型完整initial state/inputs/parameters恢复、实际motor index mapping及输入double型别、同机mono clock域、C端RFC8785/SHA256与真实构建验证。这些不能靠本轮源码声明补齐。模型负责人待项目指定；提供方应按6、7节给同包证据，而非另找同名header拼装。

**合理推测**：建议真实资产到位后冻结identity record；此为记录格式，**不生成任何生产metadata/真实hash**：

```json
{
  "model_id": "quadrotor_hil",
  "model_package_hash": null,
  "hil_contract_sha256": null,
  "model_contract_header_sha256": null,
  "model_rt_bridge_header_sha256": null,
  "generated_model_artifact_sha256": null,
  "build_script_sha256": null,
  "model_executable_sha256": null,
  "matlab_version": null,
  "simulink_version": null,
  "ert_version": null,
  "generator_identity": null,
  "solver_step_s": 0.001,
  "baseline_sha256": "22163dc21526ceadd63260b3d5670404a1064c4301e52b2a80edcf41a4fe8a27"
}
```

null表示待提供，不是可用identity。model_package_hash严格采用现有[model_package.py](../python_services/shared/model_package.py):69–91遍历排序相对path、NUL、文件hash、NUL，排除manifest；manifest必须覆盖所有payload并匹配实际值。generated artifact多文件用明确完整列表/逐文件hash的RFC8785摘要；不得只hash一个无关文件。build_identity_sha256=该完整identity record（不含build_identity_sha256字段）的RFC8785 SHA256，绑定源包、生成头、ABI、脚本、binary、工具链与基线。构建产物不在源package中时也必须进入此复合身份；5B后每个真实E2绑定相同真实identity，不只写文件名。

## 10. Authoritative Model Step Decision

**已确认**：main_rt:1027–1048先apply_live_update，后mission/arbiter final motor write，再model_step、sequence++；sequence是当前进程完成调用计数，wrapper未loaded可能no-op。C旧reset（690–726）不归零，不能直接解释为新run step0。

**合理推测（冻结）**：C为1ms权威，sequence=epoch内真实已完成generated step次数。完成S−1→关闭S边界→commit目标S→final writer→readback/APPLIED→model_step#S→sequence=S。预stage必须在S闭合前，不能只检查sequence值；闭合后LATE。5B需增加边界闭合/epoch初始化、loaded门禁及一致status发布；Python仅对账，不收到S通知后再发送赶S。

## 11. Epoch / Core Instance Decision

**合理推测（冻结）**：A单C启动ID能区分重启但不能分run；B单Gateway epoch不能独立识别C restart；选C组合。C随机128位instance每进程一次；Gateway随机epoch每新run/RESET，C在验证真实初态/step0 CONFIGURED屏障接受。RESET新epoch/步0；PAUSE/RESUME同epoch保留模型状态/步但新SID；STOP终结epoch。Gateway restart不热接管旧epoch，先safe/close并reset/restart至step0；模型替换必须新C进程。

## 12. Bridge Transport Decision

**已确认**：local_udp绑定127.0.0.1、main_rt固定cmd9997，Pythonstdlib可用；旧set_inputs为单槽pending/next-sequence accepted。**合理推测（冻结）**：复用回环UDP，8192bytes严格JSON/peer校验/绝对deadline，非RT处理。旧set_inputs/core_request不直接当正式接口，保留旧语义但在ICD owner有效时排除同path旧写者。最小六operations及闭集control见INTERNAL V1第1节，无新框架。

## 13. Request Identity

**合理推测（冻结）**：required包括bridge_version/instance/epoch/model/package/build_identity/contract/baseline、SID/request_sequence/transaction/message、original canonical hash、完整原BusinessMessage、immutable request hash、target/received/deadline/valid_for、source/lane/owner_revision及组payload。执行key固定(instance,epoch,model,package,SID,sequence)，transaction/message与原record一致。request_id只RPC关联。两hash重算，不接受Python自报替代验证；ns/revision为规范uint64十进制字符串。

## 14. Payload / Path Mapping

**合理推测（冻结）**：仅ID7完整`flight_control.motor_command[4]`组JSON，固定path，C generated contract映射至真实ModelU；不发target_field/offset、任意path。PythonBindings负责冻结结构等价和逻辑message门禁；C负责真实ABI authority。ID7/V1其它root动态刺激暂不支持，initial配置仍必须完整。

## 15. Control Ownership Contract

**已确认**：PythonQueue检查source/lane及path writer但不授予Owner；C arbiter只有source/命令/超时，无SID/epoch/revision，默认DEMO；SemanticGuards控制选择需PAUSED，外源实际producer registered CONTROLLER与selector STIMULUS身份一致。

**合理推测（冻结）**：C OwnerRecord=(producer SID,source,lane,revision,expires_at,session_expires_at,last_valid_received)，由可信Gateway管理边界安装，stage不能登记owner。SET_OWNER必须PAUSED/CAS旧revision、safe0、取消旧stage；每stage/apply复核活record，source/lane相符。新有效stage从原received续100ms控制租约；重复/Heartbeat不续控制；旧已应用命令deadline独立，future stage不能延长旧值。RESUME先新SID/PAUSED授权后提交prepared_owner_revision，只保留本次屏障后的新owner。

## 16. Deadline / Expiry Contract

**已确认**：Queue enqueue:123及begin_step:189用age>=100ms拒绝；v0.3独立100ms单调超时与从target起模型TTL100ms。旧arbiter_get用`>`、DEMO豁免，不满足拟接入路径。

**合理推测（冻结）**：deadline=original received+100000000；STAGE和APPLY/probe均需received≤now<deadline且owner/session未到期。99999999ns在其它门禁通过时允许，100000000ns拒绝，重传不续。模型值区间[S,S+100)，到S+100边界safe；mono更早则先safe；PAUSED立即安全不等模型推进。C/Python必须同Linuxboot/time namespace；跨Windows/WSL时钟不比较，UNVERIFIED不ready。C必须独立watchdog，无Heartbeat续控制漏洞。

## 17. Idempotency

**合理推测（冻结）**：同K同两hash返回已发生状态，不二次应用、不重设时间；同K异hash/transaction/message/mapping拒绝冲突RPC且保留原record。query只读，换request_id不会制造新执行身份。terminal至少5秒保留；清记录也保留epoch/SID的sequence高水位，旧sequence不重新stage。

## 18. STAGED Semantics

**合理推测（冻结）**：C完整验证并预留路径/stage/completion后不可变暂存，STAGED/OK只证明未来请求持有，effects=NOT_COMMITTED；不是APPLIED、VALIDATED的wire同义词或默认已执行。target到来时再检全部门禁；同target/path冲突不合并、不覆盖。Python逻辑条目仍计入4096，不能receipt一到就释放未决身份。

## 19. APPLIED Semantics

**合理推测（冻结）**：选方案A，在最终四值ModelU commit/readback且target实际S、owner/deadline仍有效、最后writer不覆盖后产生APPLIED；consumer1007关联完整ID7，path64证明四值读回。model_step尚未执行；step成功/业务响应是另层事实。若其后step失败保留E2，不伪报未应用。ID7不发送CONSUMED。

## 20. Final ModelU Readback Probe

**已确认**：main_rt final actuator函数接float然后转double，旧路径可能舍入且覆盖；wrapper model_get_input提供指针但真实field accessor缺失。**合理推测（冻结）**：所有writers结束、紧邻model_step前从真实ModelU读回4个binary64值；无容差/clamp，数值与expected精确相等、+0/-0规范为0；hash为RFC8785四值array。5B需保留ID7 double精度、通过生成setter/getter证明，不能直接把旧float路径当精确通路。

**待确认（Blocking）**：真实生成getter/type/布局/初态；读回失败或已写后超时effects=WRITE_UNVERIFIED，safe/revoke，不能拿REJECTED断言must_not_apply成立。真实getter缺失与设计已冻结并不矛盾：语义明确，但部署不可ready。

## 21. Result Query / UNKNOWN

**合理推测（冻结）**：get_input_result校验全部identity/K/两hash，不二次执行；返回STAGED/APPLIED/REJECTED/UNKNOWN。绝对query_deadline=received+100ms，用catalogue model_apply_ack_timeout_ms，不因无关包/重传重置；外部ack_timeout_ms=200仍保持原义。窗口内查真实terminal，窗口后未知则停止新写/safe/revoke并一次FAILED/TIMEOUT；E2仍NOT_EVALUATED，不声称未应用。

**合理推测（冻结）**：已封存wire terminal后，迟到APPLIED仅本地归档late E2/异常，该用例FAIL；不追加成功Ack、不改历史FAILED。已结束epoch5秒内只读查旧record可行，新instance不响应成旧record；C内存结果崩溃丢失只能UNKNOWN。旧SID不复活，反馈历史路由/tombstone需5D实现。

## 22. Lifecycle / Restart Rules

**合理推测（冻结）**：START配置verified；PAUSE冻结步、safe/revoke/旧stage拒绝；RESUME新SID重新授权且不追赶；STOP safe/终结epoch；RESET只PAUSED/STOPPED恢复显式initial全部state/inputs/parameters，新epoch step0 CONFIGURED。session expiry独立safe/revoke；C restart新instance使旧stage失效；Gateway restart不继续旧epoch。STOP/RESET与S冲突按C同一串行屏障线性化，已APPLIED不抹除；冻结态安全服务边界不偷偷推进model。完整表及control RPC字段见V1第7节。

## 23. Capacity / Completion Retention

**合理推测（冻结）**：全局Python未决QUEUED+STAGED+in-flight≤4096，C staged≤4096（同请求副本）；completion≤8192包含所有stage预约与control结果。请求成为executable前原子预约completion，无槽CAPACITY、无写。终态至少5000ms、非RT回收，未决/tombstone不得静默丢弃；满则背压，无独立无限队列。安全动作不得被容量阻止，固定emergency安全状态槽只记安全事实，不给未预约ID7造E2。旧epoch/sequence高水位阻止记录清理后重执行。

## 24. Error Mapping

**合理推测（冻结）**：BAD_BRIDGE_VERSION→MODEL；instance/epoch mismatch→STATE；model/hash mismatch→MODEL；duplicate conflict→BUSINESS_FAILED；owner mismatch→CONTROL_OWNER；LATE/EXPIRED/STATE/CAPACITY/TARGET_MISSING同已有码；APPLY_FAILED→BUSINESS_FAILED；PROBE_MISMATCH→SAFETY；UNKNOWN_RESULT在窗口终结后→TIMEOUT；内部BAD_SCHEMA→BUSINESS_FAILED。不新增wire enum。失败effects另留NOT_COMMITTED/WRITE_UNVERIFIED/UNKNOWN，不能把wire FAILED全解释为“未写”。完整表在V1第9节。

## 25. Security Boundary

**已确认**：旧local UDP是回环bind，无密码学认证；core_request忽略实际sender且仅看request_id。**合理推测（冻结）**：受控主机本地信任域，可信supervisor预绑定唯一Gateway peer/instance，不能首包抢占；双方实际回环peer/hash/request/instance/epoch/build identity校验；禁止任意path/offset/cmd/文件路径/shell/external bind/透传，legacy writer亦需隔离。随机bridge session token仅建议，不宣称已实现认证；本机恶意进程和物理fail-safe不由loopback解决。

## 26. Internal Bridge V1 Schema

**合理推测（冻结）**：[model_consumer_bridge_v1.md](internal/model_consumer_bridge_v1.md)是唯一权威：六operations、request/response envelope、11个$defs、闭集control action、required/range/nullability/enums、两hash、model/build/epoch身份、STAGED/APPLIED/REJECTED/UNKNOWN、effects、probe64/1007及管理结果。Schema采用Draft2020-12，引用仅本地；跨字段等式、时间/状态约束为紧接的规范性语义条款，JSON Schema检查不能代替这些运行检查。本轮只文档，不生成生产代码/types或新增wire schema。

## 27. 5B Entry Gate

**合理推测（冻结）**：开始修改C Core做真实模型桥前，必须有本轮之外的5B实施授权且全部满足：

- REAL_MODEL_ASSET_GATE != NO_GO，真实同quad包合同/生成ABI/hash/build trace可证明。
- 真实hil_contract通过现有ModelBindings；缺少getter/exact executable时虽可CONDITIONAL_GO，仍须补齐本轮列出的5B强制项。
- 本V1字段、C权威S边界、instance/epoch、owner、精确100ms、最终probe时机、query/UNKNOWN封存和completion预约均遵守本冻结设计。
- 真实getter机制/双精度写入/初始状态恢复路径已识别，不靠fixture/默认4电机结构。
- 目标Linux构建依赖及C RFC8785/hash实现可追溯；同机mono时钟域有部署证据。

**已确认**：当前资产NO_GO，故5B真实模型实施入口未打开。可单独授权`5B-TEST-HARNESS / C_TEST_ABI_ONLY`验证协议代码，仍不是real E2，也不改implemented_message_ids=7。初始化/生命周期/正式Heartbeat及Status/完整授权/异步ACK能力是后续真实线上门禁，不以本报告发布能力。

## 28. Risks / Open Questions

| 项目 | 标签与下一步 |
|---|---|
| 真实资产位置在包外 | 待确认；本次未擅自扩盘搜索，提供方提交同包或明确相关路径后再核查 |
| generator/MATLAB/ERT/可复现build | 待确认；只有源码注释，没有生成与链接证据 |
| getter/initial state与fault语义 | 待确认；字段probe不等于有效执行器/动力学/物理输出 |
| binary64/float转换 | 已确认旧函数经过float；5B需保真，不改冻结double协议 |
| shared lock/边界/owner线性化 | 合理推测需统一串行屏障，旧sequence+1/命令线程不能代替 |
| RFC8785 C支持/实际编译依赖 | 待确认；新hash设计不能靠普通JSON序列化蒙混 |
| 时钟及实时指标 | 待确认；Windows审查不证明Linuxnamespace时钟、1ms±10us或麒麟资格 |
| UDP丢包与内存记录崩溃 | 合理推测已有精确UNKNOWN政策，运行效果待5B–5F验收 |
| 源授权/模型ready/capability | 已确认Round4只是admission、capabilities[1]；本轮不提升 |
| 既有缺fixture与旧清单差异 | 已确认未修；不能将本轮通过的文档检查描述为全量回归通过 |

**合理推测（交付自检）**：准确性4/5（缺真实模型，结论严格限搜索范围）；完整性4/5（29节/完整schema，运行资格未具备）；清晰度4/5（机器schema较长，但仅一个权威）；可执行性4/5（5B gate明确，仍待真实资产提供）；简洁性4/5（报告必要重复摘要用于handoff），平均4.0。优先改进是真实同包证据、getter/构建/时钟资格，不以额外假模型提高评分。这是交付自检，不是real-model qualification。

## 29. Definition of Done

**已确认（本轮交付要求）**：

- [x] 已读Round5审查、Round4报告、README和原SHA清单。
- [x] 已搜索约定handoff/父目录/3_6/UAVDemo范围，无任意全盘或私目录扫描。
- [x] 找到的候选逐项分类/hash；真实不存在者MISSING，不编造真实hash。
- [x] 已否定本次范围内真实hil_contract/generated ABI/build executable trace。
- [x] 真实Bindings检查因资产缺失NOT_RUN；fixture检查9pass/1error诚实记录。
- [x] 已给出NO_GO及缺件清单，未用fixture美化CONDITIONAL_GO/GO。
- [x] 已冻结C权威step、instance/epoch、UDP、身份/hash、payload path、OwnerRecord。
- [x] 已冻结精确100ms、幂等、STAGED/APPLIED、真实final readback要求及ID7不发CONSUMED。
- [x] 已冻结query/UNKNOWN/迟到终态、生命周期/重启、容量预约/保留、错误映射、安全边界。
- [x] 已给完整INTERNAL V1 Schema和5B真实模型入口门禁。
- [x] 仅新增报告/内部文档；没有修改C/Receiver/Queue/Session、frozen v0.3、Round1–4 artifacts或capabilities。

**已确认（保护检查限制）**：开工对465个既有文件计算过hash，但所用隔离进程临时目录在退出后不可重读，完整465项开工/完工hash比较未能完成；不假报全量保护PASS。开工已在工具输出保留的关键源码/基线hash可复核，原237项旧清单检查结果也可与开工结果比较。最终统计467文件、仅本次两份文档新增，与开工文件数相符；当前467项hash另存工具会话内存，用于最后文档定稿前后的完整对比。项目无Git，未伪报git diff。以下Schema/设计样本、章节、本地链接检查仅验证文档，不验证正式桥/真实模型：

- **已确认**：Draft2020-12 Schema自检PASS；14个设计请求样本、6个设计响应样本通过，12个非法结构/状态/operation/transaction样本被拒绝。样本仅在验证进程内存，不生成模型metadata文件、不计真实E2。
- **已确认**：在内存检查设计样本的原canonical hash、全envelope hash、payload对应、deadline等式、probe值/hash；跨字段运行门禁仍须5B实现并实测，未把Schema语法通过说成正式桥通过。
- **已确认**：29个必需章节、24个本地链接，broken_links=0；报告与contract交叉链接存在。
- **已确认**：22个开工/写文档前工具输出保留的关键源码/基线/旧报告SHA256与完工相同；原237项清单仍仅上述2项预先存在差异，无新增清单差异。
- **已确认**：最终定稿阶段完整467文件hash比对，仅两份输出文档内容变化，465个非输出既有文件一致，新增/删除=0。此阶段比较不能补回丢失的开工快照，故完整开工465项比对仍NOT_COMPLETED；仅本轮指定两份文档新增的结论另由开工465/最终467清点和全部写操作路径支持。
- **已确认**：Bindings本次9pass/1error，冻结单文件check通过；real model run/build/PCAP→Model未执行，real E2 NOT_EVALUATED。

**已确认（本轮边界）**：未实现stage/getter/Consumer，未修回归，未运行PCAP→Model，未产生APPLIED/CONSUMED，未更改旧证据。5A已完成资产门禁与契约设计交付；5B真实模型仍因缺资产不能开始。
