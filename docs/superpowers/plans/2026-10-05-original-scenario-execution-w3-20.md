# Original Scenario Execution W3.20 Implementation Plan

> Use executing-plans and test-driven-development in the existing shared checkout. No commits, new branches, worktrees, baseline edits or platform-specific implementation.

**Goal:** 继续原W3，补原ScenarioSource与ScenarioPlan之间缺失的共用运行控制器；不开发新增自生数据配置格式/入口。

**Architecture:** 原ScenarioPlan惰性时间表交给单owner ScenarioExecution，由明确ScenarioDriver处理原link_id及全部事件。driver必须在任何执行前预检整份计划/根断言/原工具/授权/真实时钟与探针，默认无driver拒绝。控制器负责有界在途、原handle关联、WAIT屏障、显式MODEL_STEP、不追赶迟到事件、失败与停止调用九项清理；不自己发送UDP替代原工具，不把driver结果升级模型资格。

**Tech Stack:** 现有Python3.12/ScenarioPlan/ICDError、标准库ABC/dataclasses/threading，无新增依赖。

## Scope And Completion Boundary

- 原W3仍未完成；本包是运行控制器，不是完整六工具/回放/实机验收。生产driver、真实时钟/probe、暂停恢复的新SID/清队列、回放repeat/RESET/initial_inputs、授权负例实际执行仍需接通。保持整体M3/M4未勾选。
- begin收到原ScheduledAction（原link_id、完整Stimulus、原REPLAY策略/负例/清理内容不变），不增ICD字段。root assertions单独由driver开启并等待实际结果，不能遗漏。
- start/advance/stop只接受显式uint32模型步；不读取墙钟、不模拟模型。事件绝对at_step不重写，漏步TIMEOUT，不追赶；WAIT完成后若后续绝对步已过，明确失败，不能擅自重定时。
- driver返回原handle的严格Progress：PENDING/COMPLETE/FAILED。COMPLETE只表示该handler结束，qualification始终NOT_EVALUATED；缺driver或预检失败不得进入RUNNING。预检不允许启动发送器或取号。
- WAIT阻塞同一步后续事件，普通ASSERT不阻塞其他事件但未完成不能结束；END/root终点必须等所有在途和根断言完成再清理。清理累计全部九项true回执才LOCAL_STOPPED；不足则CLEANUP_PENDING/FAILED，不能报告安全已验证或释放预约。
- 默认64在途/4096运行记录/16MiB；每条根断言独立handle/模型步期限，计入在途与记录上限；超过明确容量的资源在启动前拒绝，不能将最多10000条Schema定义误说成当前运行器可同时执行10000条。启动预估记录容量涵盖整个有限动作流，超限在执行前拒绝，不默默evict/drain；记录保留所有终态的原handle和根assertion_id关联。所有入口串行owner，driver回调重入拒绝；非ICDError异常也记录具体失败操作并尝试清理，全部错误归一到冻结词汇，运行与清理错误分开保存，不回滚原计数或重试begin。

## Tasks

- [x] 先RED：缺运行控制器；原link/十事件、波形/周期完整值、根断言、WAIT同一步屏障、回执身份、漏步/回退、在途上限/完整记录预算、driver异常、失败/停止清理及九项不足。
- [x] 实现input_simulator/scenario_execution.py与有限状态/不可变记录，不修改冻结ScenarioSource或原编译器。
- [x] 回归原scenario/assertion/waveform及全共用入口，复核边界；保存独立w3-20报告。
- [x] 唯一linux-development-backlog.md追加原W3本包与真实driver/时钟/工具/清理移交，保持41责任/17未执行Linux；整体计划只追加进度，不宣布原第三阶段完成。

**Scoped result:** 32专项/714共用/34选定静态通过，独立只读复核无剩余重要scoped发现。仅本工作包完成；完整原第三阶段和上述Original W3 Finish Gate仍未完成。生产driver不存在，运行器不进入线上资格就绪状态。

## Original W3 Finish Gate

三类资源已解析/编译不等于运行：尚须完整生产driver覆盖原六工具、原三回放模式/重复轮次与重建会话、WAIT/ASSERT真实探针、负例授权/不应用证据、暂停恢复/单步复位、九项真实清理及连续证据终点。Windows可开发部分继续同一代码；必须Linux的后端和真实模型/RT只移交唯一待办，不另开发Windows替代版。上述共用事项完成后，才恢复新增自生数据配置与自动入口草案。
