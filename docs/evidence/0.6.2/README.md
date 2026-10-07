# 0.6.2 公开验收证据

日期：2026-10-07。这里是经发布检查的只读结果副本，来自本项目公开 Desk/Lamp/Chair 合成夹具；不包含真实用户资产、API Key、认证头或原始模型正文。日常 `benchmarks/results/` 仍被 Git 忽略。

## 真实模型的两轮结果

- [第一轮全量：18/20](planning_qwen_local_full_2026_10_07.json)：AI 正向任务 6/8；两条自相矛盾的保持原位约束触发回滚。不能删除这轮失败，只保留成功结果。
- [澄清提示词后：20/20](planning_qwen_local_constraint_clarified_2026_10_07.json)：AI 正向任务 8/8、正确拒绝 4/4；零跳过、零任务范围外修改。

固定集包含 8 个本地正向任务、8 个 AI 正向任务、4 个拒绝任务，每轮实际调用模型 9 次。模型为本机 `qwen/qwen3-4b-2507`，格式为 `json_schema`；没有付费云端调用。第二轮成功不能外推为任意指令准确率 100%。

## 界面流程与重复验证

- [源码真实模型流程](qwen_local_source_ui_2026_10_07.json)。
- [隔离安装包真实模型流程](qwen_local_isolated_installed_ui_2026_10_07.json)。
- [默认安装包真实模型流程](qwen_local_default_installed_ui_2026_10_07.json)。
- [Schema 模式模拟服务流程](provider_schema_installed_0_6_2.json)。
- [隔离安装包模拟 AI 重复运行 20 次](ai_installed_repeatability_0_6_2.json)。

界面流程测试通过 Blender 后台操作器运行，覆盖发送同意、确认前只读、确认执行、事务验证与独立最终目标；它不是人工点击窗口的排版验收。20 次重复测试访问本机模拟服务，不是 20 轮真实模型能力测试。

完整结论、失败诊断和已知风险见 [中文验收报告](../../RELEASE_0.6.2_TEST_REPORT.md)。复现方法见 [中文评测说明](../../MODEL_EVALUATION.md)。当前版本仍为 M2 开发者测试版，不是完整自动构图、自动建模或已通过外部用户验证的产品。
