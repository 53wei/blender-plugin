# 真实模型与固定任务评测说明

版本：0.6.2；日期：2026-10-07。固定回放不是 AI 准确率，真实合成任务实测也不是外部用户验证。

## 先测试什么

任务集 `benchmarks/cases/planning_v1.json` 包含 20 个公开合成任务：8 个本地正向任务、8 个 AI 正向任务、4 个拒绝任务。每例独立创建 Desk、Lamp、Chair，判定方向和最终位置、锁定、预期路由，以及哪些物体允许变化。预期答案不会发给模型。

内存入口验证纯业务链；Blender 入口验证相同任务在 Blender 4.5 中的实际状态。Blender 入口必须以出厂配置启动，不得载入用户文件。自动确认只发生在一次性评测夹具，插件正常使用仍需用户两次确认：发送数据与执行动作。

## 三种模式

以下命令在项目根目录执行。把 `blender` 换为本机程序绝对路径也可以。

先查看 ai_01 的发送数据，不联网、不执行：

```powershell
python -m benchmarks.runner --case ai_01
```

报告保存在 `benchmarks/results/planning_memory_review.json`。其中没有预期位置或固定候选答案。这里是合成夹具数据，不会读取当前打开的用户场景。

回放人工编写的固定候选，无模型调用：

```powershell
python -m benchmarks.runner --mode replay
blender --background --factory-startup --python-exit-code 1 --python tests/integration/run_planning_benchmark.py -- --output benchmarks/results/planning_blender_replay.json
```

## 真实模型：先一条，不直接跑全量

自行选定一个兼容 `/chat/completions` 和 JSON 输出的服务。API 地址、模型名可以提供给开发者；Key 不要发到聊天、写入源码或出现在录像里。给运行评测的终端设置 `BSA_API_KEY`，或使用已有 `OPENAI_API_KEY`；不要把真实密钥直接粘贴到会保存历史的命令中。临时在 Blender 面板里输入的 Key 不会自动提供给独立评测进程。

先审查 ai_01；确认允许把这些公开合成数据发送到所选服务，再运行：

```powershell
python -m benchmarks.runner --mode live --case ai_01 --api-base "https://你的服务地址/v1" --model "你的模型名" --max-requests 2
```

同一真实任务也可以直接在一次性 Blender 夹具中评测：

```powershell
blender --background --factory-startup --online-mode --python-exit-code 1 --python tests/integration/run_planning_benchmark.py -- --mode live --case ai_01 --api-base "https://你的服务地址/v1" --model "你的模型名" --max-requests 2 --output benchmarks/results/planning_blender_live_smoke.json
```

只有用户明确执行 `live` 才联网。远程服务必须 HTTPS。默认总上限为 2 次 HTTP；无效候选的一次修复也占额度。这是请求次数上限，不是费用上限，超时或无效输出也可能收费。服务价格和账户额度由用户确认，脚本不代替服务商计费。

试跑结果正确后才考虑去掉 `--case`、改为 `--max-requests 18`。任务集最多 9 个 AI 路由任务，每例最多两次请求；本地任务不花模型 Token。某些服务不支持当前 JSON 参数或模型名，连接测试成功也不保证规划兼容。

### 本机 LM Studio

0.6.2 提供 `--output-format json_schema`；默认 `json_object` 继续服务既有通用接口。正式 Schema 生成自候选协议，不会允许任意 Python，也不会代替本地校验。LM Studio 官方结构化输出说明：https://lmstudio.ai/docs/developer/openai-compat/structured-output 。本机实测旧模式 HTTP 400，新模式可调用 `qwen/qwen3-4b-2507`。

LM Studio 未开启认证时不需要 Key。注意评测会继承 Key 环境变量；纯本机测试先清空**当前终端进程**的旧变量，不删除用户持久配置：

```powershell
$env:BSA_API_KEY = ""
$env:OPENAI_API_KEY = ""
blender --background --factory-startup --online-mode --python-exit-code 1 --python tests/integration/run_planning_benchmark.py -- --mode live --case ai_01 --api-base "http://127.0.0.1:1234/v1" --model "qwen/qwen3-4b-2507" --output-format json_schema --timeout 60 --max-requests 2 --output benchmarks/results/planning_local_smoke.json
```

用 `127.0.0.1` 而非局域网明文 HTTP 地址。服务器必须已启动，模型名以本机 `/models` 为准。未启动或格式不支持就明确失败，不会自动换服务。固定的一条真实 UI 验收入口是 `tests/integration/run_local_model_ui_suite.py`，仅测试本机示例地址及模型，要求出厂启动与在线权限；`-- --installed` 可验收隔离安装包。它只操作脚本创建的一次性三物体场景，不操作用户打开的文件。

2026-10-07 的第一次全量结果为 18/20，AI 正向任务 6/8；两个失败都因对移动对象添加保持原位约束而回滚。澄清提示词后的一轮结果为 20/20，AI 正向任务 8/8；每轮 9 次请求、0 跳过、0 任务范围外修改。原始报告分别为 `planning_qwen_local_full_2026_10_07.json` 和 `planning_qwen_local_constraint_clarified_2026_10_07.json`，位于 `benchmarks/results/`。只证明这个固定任务集，不可宣称真实模型通用成功率 100%。

## 怎么读报告

- `mode` 区分审查、回放和真实模型，`engine` 区分内存和 Blender。
- `suite_sha256` 关联固定任务内容，`extension_version` 关联实现版本。
- `output_format` 记录真实调用的返回格式，便于复现服务兼容条件。
- `task_success_count` 只统计正向任务；`correct_rejection_count` 单独统计安全拒绝。
- `task_unauthorized_changes` 按用户任务检查额外修改，不是计划自己声称的授权范围。
- `network_request_count` 包含已尝试、失败和修复的 HTTP 请求。
- `real_model_success_rate` 只在真实模式统计已请求且未因预算中断的 AI 正向任务。应同时看 `measured_ai_task_count` 与 `skipped_count`；只测一条不能宣称全量准确率。
- Token 未返回或失败时为未知，不可当作零消耗。结果不保存模型正文、Key、认证头或私有场景。

返回码为 0 表示已运行任务未失败，预算跳过仍可能存在；必须查看跳过数量，不能把它理解为完整验收通过。

## 已发现并修复的问题

模型摘要可能说“只查看，不移动”，动作却要求摆放。现在执行前清单由本地真实动作生成，不再依赖摘要。模型也可能先解除锁定再移动；AI 解锁已在候选解析和执行前校验两层禁止。本地明确的独立解锁指令仍可使用。

还存在语义风险：合法动作也可能摆错方向，或改变不该改变的对象。评测能用预先定义的答案检出这些错误，但插件并没有可靠的通用自然语言意图验证器。使用时必须检查实际动作清单，不能因显示“验证通过”就认为 AI 完全理解了要求。

## 你作为作品作者下一步应该做什么

1. 自己完成 5 条代表性任务，先记录手动操作时间，再记录插件操作时间、修改次数和失败原因。暂时没有外部用户，可以诚实称为开发者自测。
2. 用自己的一个真实资产场景重复同样任务，不只用方块。保存操作前文件；记录不支持几何和需要手动修正的情况。
3. 录制一个 60–90 秒演示：安装、点助手、输入、检查发送内容、检查实际动作、确认、查看结果。Key 和服务账户信息不能入镜。
4. 面试前能讲清楚“模型只提出计划、本地事务执行、独立任务评测”的区别，并亲自读懂一个动作从解析到验证的完整路径。

先完成这些证据，再决定新增哪种多物体动作；不要把尚未验证的自动构图能力写入简历。
