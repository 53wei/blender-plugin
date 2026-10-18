# Blender 场景编辑助手 — Developer Specification v0.3

**状态**：Implementation Baseline / 开发基线  
**日期**：2026-09-10  
**目标运行环境**：Blender 5.2 LTS（首发开发线）  
**工作仓库名**：`blender-scene-assistant`  
**文档用途**：供 Codex / 开发者直接建立工程、实现 M1–M6、编写测试与做设计决策。  

> **硬约束：这是正式产品工程，不是“先接模型跑个 Demo”。在 M1 本地确定性闭环通过前，不接 LLM、不做聊天 UI、不扩 mesh 建模、不为了演示效果绕过测试。**

---

## 0. 文档优先级与变更规则

本开发规范建立在项目方向 v0.1 与项目开发标准 v0.2 之上，并把其中的产品判断落实为可编码的接口和验收条件。冲突时，优先级为：**最新 ADR（Architecture Decision Record） > 本文档 > 项目开发标准 v0.2 > 项目方向 v0.1**。

任何会改变以下事项的修改都必须新建 ADR，而不是直接改代码：动作语义、Scene IR 字段、坐标系约定、事务/回滚语义、LLM 与本地计算边界、隐私策略、MVP 范围。每个 ADR 必须写清：背景、选择、备选方案、代价、验证方式。

版本规则：文档使用 `major.minor`。小版本允许补充实现细节；如果核心问题、产品定位或动作语义发生不兼容变化，升级 major。

---

## 1. 产品定义

### 1.1 一句话定义

**用尽可能少的 LLM 调用，把用户的自然语言场景意图转换成可靠、可验证、可撤销的 Blender 编辑。**

### 1.2 主要用户问题

用户已经拥有桌子、椅子、灯、书架、商品、道具等 3D 资产，但把这些资产组织成满足空间关系和编辑约束、并可继续手工修改的 Blender 场景，仍需要大量重复操作。产品缩短的是：

`高层意图 -> 结构化计划 -> 确定性空间计算 -> Blender 状态改变 -> 自动验证/恢复`

产品不以“模型能否从零生成复杂 3D”为核心竞争维度。

### 1.3 首版用户价值

首版只承诺在**已有资产的场景编排和连续编辑**上提供价值：多对象摆放、相对关系、基础对齐、锁定保护、计划预览、验证、撤销/检查点。用户最终得到原生可编辑 `.blend` 工程，而不是不可修改的渲染图。

### 1.4 非目标 / Non-goals

MVP 与首个正式作品版本明确不做：

- 任意 mesh 建模、网格雕刻、自动拓扑、UV、骨骼、动画生成。
- text-to-3D / image-to-3D 模型研发。
- 用自由脚本让 LLM 直接执行任意 `bpy` 代码。
- Blender + UE5 双端支持。
- “自动判断绝对美观”的通用审美优化器。
- 自建模型推理服务、代用户承担模型额度或计费。
- 大规模云端账户系统、团队协作系统、在线资产市场。

### 1.5 产品差异化

竞争力必须来自系统架构，而不是模型品牌：

1. **Deterministic Core**：坐标、bbox、落面、对齐、锁、diff、验证和回滚由本地程序完成。
2. **Constrained Planning**：LLM 只能输出白名单 JSON Plan，不能自由执行脚本。
3. **Low Model Dependence**：能本地解析就不调用模型；需要模型时只传相关对象摘要和最小上下文。
4. **Verifiable Editing**：每个动作有 precondition / postcondition；结果由 verifier 判定，不依赖“看起来差不多”。
5. **Transactional Safety**：失败要可回滚，锁定对象不得被未授权动作改变。

---

## 2. 发布与技术基线

### 2.1 Blender 版本

首个开发和评测基线固定在 **Blender 5.2 LTS**。开发中只保证该主线；4.5 LTS 等兼容性属于后续工作，不在 M1–M3 的承诺范围。

### 2.2 扩展形态

正式分发形态按 Blender Extension 组织：根目录包含 `blender_manifest.toml` 与 `__init__.py`。发布前必须通过 Blender 官方 extension validate/build 命令。正式接入模型 API 后，manifest 声明 `network` 权限，并在运行时遵守 Blender 在线访问设置。

### 2.3 依赖原则

- Blender 交互层使用 `bpy` / `mathutils`。
- `core/` 与 `domain/` 尽量保持纯 Python，避免为了单元测试必须启动 Blender。
- M1 不引入第三方运行时依赖。
- M2 需要 HTTP/Schema 库时，优先评估标准库；如引入第三方 wheel，必须固定版本、记录许可证并随 extension 自包含分发。
- 不把 API Key、场景内容、prompt 写入源码或提交仓库。

### 2.4 线程与进程约束

任何后台线程不得持续访问 `bpy`。Blender 状态读取、对象修改和验证必须在安全的 Blender 主执行上下文完成。未来网络调用如果做异步化，网络层和 Blender API 层必须彻底解耦；不要让持久后台线程同时操作 `bpy`。

---

## 3. 总体架构

```text
┌──────────────────────────────────────────────────────────┐
│ Blender UI / Extension Panel                             │
│ 指令输入 · Plan Preview · Confirm · Result · Undo        │
└───────────────────────┬──────────────────────────────────┘
                        │
                Application Service
                        │
        ┌───────────────┼────────────────────┐
        │               │                    │
 Local Parser      LLM Planner          Scene Reader
        │               │                    │
        └───────> ActionPlan <──────── SceneSnapshot
                        │
                  Plan Validator
                        │
                 Transaction Manager
                        │
             ┌──────────┴──────────┐
             │                     │
       Spatial Engine          Executor
             │                     │
             └──────────┬──────────┘
                        │
                     Blender
                        │
                     Verifier
                        │
          PASS -> Commit | FAIL -> Rollback
                        │
             Metrics / Structured Logs
```

架构上必须保持**语义层**与**执行层**可替换：LLM Provider 换掉不应改变 action semantics；UI 换掉不应改变 executor；benchmark 应直接调用 application/core API，而不依赖点击 UI。

---

## 4. 模块职责与禁止越界

| 模块 | 负责 | 不负责 |
|---|---|---|
| `ui/` | Blender Panel、输入、预览、确认、结果展示 | 空间计算、业务判断 |
| `application/` | use case 编排、事务生命周期、依赖注入 | 直接写复杂 bpy 逻辑 |
| `domain/` | Scene IR、Action、Constraint、Result、错误类型 | Blender 具体 API |
| `blender_adapter/scene_reader.py` | 从 Blender 构造 SceneSnapshot | 规划意图 |
| `core/spatial.py` | bbox、关系、候选位置、容差 | 调用网络/LLM |
| `core/validator.py` | JSON/plan/precondition 校验 | 直接修改场景 |
| `blender_adapter/executor.py` | 把 validated action 应用到 Blender | 猜测用户意图 |
| `core/verifier.py` | postcondition、锁保护、diff 检查 | 视觉审美评分 |
| `core/checkpoint.py` | 捕获/恢复受影响状态 | 跨会话版本控制（MVP） |
| `planner/local_parser.py` | 明确命令的本地解析 | 高层模糊语义 |
| `planner/llm/` | 自然语言 -> ActionPlan | 自由脚本执行、几何求解 |
| `infra/logging.py` | JSONL 事件、metrics、redaction | 记录密钥 |

**禁止出现一个“大而全”的 `agent.py` 同时做 prompt、坐标、bpy、回滚和 UI。**

---

## 5. Domain Model / Scene IR

### 5.1 SceneSnapshot

SceneSnapshot 是 planner、validator、benchmark 的只读输入。不得直接把 `bpy.types.Object` 泄露到 domain 层。

```python
@dataclass(frozen=True)
class SceneSnapshot:
    schema_version: str
    snapshot_id: str
    scene_name: str
    unit_scale: float
    objects: tuple[ObjectState, ...]
    active_camera_id: str | None
    created_at: str
    fingerprint: str
```

### 5.2 ObjectState

```python
@dataclass(frozen=True)
class ObjectState:
    object_id: str          # 稳定内部 ID，不依赖显示名唯一性
    name: str
    object_type: str        # MESH / EMPTY / CAMERA ...
    matrix_world: tuple[float, ...]   # 4x4, row-major/column-major 必须统一
    location_world: tuple[float, float, float]
    rotation_euler: tuple[float, float, float]
    scale: tuple[float, float, float]
    bbox_world: BoundingBox
    dimensions_world: tuple[float, float, float]
    parent_id: str | None
    locked: bool
    visible: bool
```

### 5.3 BoundingBox

M1 使用 **world-space AABB**，明确承认对旋转复杂物体不够精确。M1 不偷偷实现半套 OBB。

```python
@dataclass(frozen=True)
class BoundingBox:
    min_xyz: tuple[float, float, float]
    max_xyz: tuple[float, float, float]
    center: tuple[float, float, float]
```

M3 之后如果 AABB 已被 benchmark 证明不足，再通过 ADR 引入 OBB / mesh ray-cast。

### 5.4 稳定 object_id

对象显示名可被用户重命名，不能作为唯一主键。首版在对象 custom property 中维护 UUID：

`object["bsa_object_id"] = "uuid-v4"`

读取时如果不存在则生成；复制对象时需检测重复 ID 并修复。日志、plan、constraint 一律引用 `object_id`，UI 同时展示友好 `name`。

### 5.5 Lock 持久化

锁定状态使用 custom property 持久化：

`object["bsa_locked"] = True/False`

`hide_select` 只能作为 UI 辅助，不作为业务层锁语义的唯一来源。任何执行动作在 precondition 阶段都必须拒绝修改 `bsa_locked=True` 的对象，除非动作本身是显式 `unlock`。

---

## 6. 坐标、单位与空间语义

### 6.1 内部坐标

- 所有执行与验证使用 Blender world space。
- 输入的明确距离在进入 domain 后转换为 Blender scene units。
- UI 可以显示 m/cm，但 domain 不混用单位字符串和裸浮点数。
- 所有比较使用显式 tolerance，不直接用浮点 `==`。

### 6.2 MVP tolerance

以下为工程默认值，必须集中配置，不允许散落 magic number：

```python
POSITION_EPS = 1e-4
SURFACE_GAP_EPS = 1e-3
LOCK_TRANSFORM_EPS = 1e-6
MIN_CLEARANCE = 0.02       # scene units, fixture 可覆盖
```

如果 fixture 的单位不同，测试配置必须显式覆盖。

### 6.3 `place_on` 语义

M1 的 `place_on(A, B)` 只支持“可视为水平支撑面的目标”：

1. 读取 B 的 world AABB top Z。
2. 读取 A 的 world AABB bottom Z。
3. 平移 A，使 `A.bottom_z ~= B.top_z + clearance_z`。
4. X/Y 默认保持；若同时存在区域/相对约束，则由 spatial engine 计算 X/Y。
5. verifier 检查垂直 gap、A 中心是否落在 B 顶面投影允许区域内。

如果目标旋转过大、支撑面不可由 AABB 合理描述，返回 `SPATIAL_UNSUPPORTED_GEOMETRY`，不得假装成功。

### 6.4 `left/right/front/back` 语义

M1 先固定成**世界坐标框架**，避免“桌子局部朝向”引入隐含歧义：

- right_of: +X
- left_of: -X
- front_of: -Y（若团队选择 +Y，必须在 ADR-001 中一次性冻结）
- back_of: +Y

进入 M3 之前再评估 `frame="target_local"`。如果引入，Action 必须显式带 `frame`，不允许靠 planner 猜。

### 6.5 冲突约束

当动作组合无法同时满足，如“lamp 在 desk 左边且右边”，validator 必须在执行前拒绝 plan。执行器不能自行选择其中一个。

---

## 7. Action Protocol v0.1

### 7.1 顶层 ActionPlan

所有 planner（本地或 LLM）必须输出同一个协议。LLM 不拥有额外的隐藏执行能力。

```json
{
  "schema_version": "0.1",
  "plan_id": "uuid",
  "source": "local_parser|llm",
  "scene_fingerprint": "sha256:...",
  "requires_confirmation": true,
  "actions": [],
  "constraints": [],
  "user_summary": "把台灯放到桌面右侧，并锁定桌子"
}
```

### 7.2 M1/M2 白名单动作

```text
move
rotate
scale_uniform
place_on
relative_place
align
lock
unlock
checkpoint
undo
```

M1 必须实现：`place_on`、`relative_place(left/right)`、`lock`、`checkpoint/undo`。其余可以只有 schema，不进入首个验收闭环。

### 7.3 `place_on`

```json
{
  "action_id": "a1",
  "type": "place_on",
  "object_id": "lamp-id",
  "target_id": "desk-id",
  "region": "center|left|right|front|back",
  "clearance": 0.0
}
```

### 7.4 `relative_place`

```json
{
  "action_id": "a2",
  "type": "relative_place",
  "object_id": "bookshelf-id",
  "target_id": "desk-id",
  "relation": "left_of|right_of|front_of|back_of",
  "distance": 0.25,
  "frame": "world"
}
```

### 7.5 `move`

```json
{
  "action_id": "a3",
  "type": "move",
  "object_id": "lamp-id",
  "delta": [0.2, 0.0, 0.0],
  "space": "world"
}
```

### 7.6 `lock/unlock`

```json
{"action_id":"a4","type":"lock","object_id":"desk-id"}
```

`unlock` 必须是用户意图显式产生的 action，不能因为后续动作需要移动被锁对象而自动解锁。

### 7.7 Constraint

```json
{
  "constraint_id": "c1",
  "type": "preserve_transform",
  "object_id": "desk-id",
  "severity": "hard"
}
```

MVP 只支持 hard constraints。soft constraints 属于后续规划优化，不进入当前实现。

### 7.8 Plan Schema 校验规则

- 未知字段：默认拒绝（fail closed）。
- 未知 action type：拒绝。
- object_id / target_id 不存在：拒绝。
- 被锁对象作为写目标：拒绝。
- 数值 NaN/Infinity：拒绝。
- 超出安全范围的 scale / distance：拒绝或要求确认。
- `scene_fingerprint` 与当前相关对象状态不一致：返回 `PLAN_STALE`，要求重新规划/重新预览。

---

## 8. Scene Fingerprint 与 stale-plan 防护

Plan Preview 与真正执行之间，用户可能手工移动了对象。不能执行基于旧状态算出的 plan。

M1 做相关对象 fingerprint：按 object_id 排序，将以下字段规范化后 SHA-256：

`object_id + matrix_world + dimensions + locked`

Plan 保存 fingerprint；Confirm 时重新计算。不同则不执行，UI 显示“场景已改变，请重新生成计划”。

此机制比单纯的进程内 revision counter 更可靠，因为它能捕获用户在 Blender UI 中的手动变化。

---

## 9. 执行事务模型

每个 ActionPlan 按一个事务处理。核心顺序不得绕过：

```text
1. Capture current snapshot / fingerprint
2. Validate plan schema
3. Validate references & locks
4. Validate preconditions
5. Capture checkpoint for affected objects
6. Compute candidate transforms (pure calculation when possible)
7. Apply actions
8. Refresh scene state
9. Verify postconditions + hard constraints + unauthorized diff
10. PASS -> commit result
11. FAIL -> rollback checkpoint -> verify rollback
```

### 9.1 Affected Set

执行前必须算出 `affected_object_ids`。只有这些对象允许发生业务层变更。执行后将 before/after snapshot 做 diff：如果出现集合外 transform 变化，事务失败并回滚。

### 9.2 Checkpoint v0.1

M1 不仅依赖 Blender 全局 Undo Stack。产品自己的 checkpoint 至少保存：

- `matrix_world`
- `bsa_locked`
- M1 中被执行器修改的其他自定义属性

恢复后再次读取 SceneSnapshot 并与 checkpoint 做容差比较。只有 rollback verification 通过才能返回 `ROLLED_BACK`。

### 9.3 部分执行失败

一个 plan 中第 3 个 action 失败时，不保留前 2 个 action 的结果；MVP 采用 **all-or-nothing**。未来如果要支持 partial commit，必须单独 ADR。

---

## 10. Verifier Specification

Verifier 是正式作品的核心，不是 debug 辅助。

### 10.1 输出结构

```python
@dataclass(frozen=True)
class VerificationResult:
    passed: bool
    checks: tuple[CheckResult, ...]
    unauthorized_changes: tuple[str, ...]
    summary: str
```

每个 CheckResult 包含：`check_type / object_ids / expected / actual / tolerance / passed`。

### 10.2 必须验证的项目

**place_on**：
- A.bottom_z 与 B.top_z gap 在容差内。
- A 的参考点位于 B 的允许 XY footprint。
- 如果声明 clearance，实际 clearance 符合。

**relative_place**：
- 中心/边界关系满足 relation。
- 距离达到最小要求。

**lock/preserve_transform**：
- 锁定对象 before/after transform delta 在 `LOCK_TRANSFORM_EPS` 内。

**unauthorized changes**：
- 不在 affected set 的对象没有业务层 transform 变化。

**rollback**：
- rollback 后所有 checkpoint 字段恢复。

### 10.3 “看起来成功”禁止作为判定

截图可以用于演示和后续视觉 benchmark，但 M1–M3 的 pass/fail 必须来自结构化 scene state。

---

## 11. 本地解析器与 LLM 调用边界

### 11.1 调用决策

用户输入先经过 `LocalParser`。能够确定解析的命令不调用模型，例如：

- “撤销”
- “锁定桌子”
- “台灯向右移动 20cm”
- “把书架左移 0.5m”

含高层语义、复合关系或指代歧义时调用 LLM，例如：

- “把这些东西整理成紧凑的小工作室，桌子靠墙，灯放右边。”
- “保持主要家具不动，把背景稍微收紧一点。”

### 11.2 LLM 输入最小化

默认只发送：

- 用户当前指令。
- 场景单位比例。
- 最多 20 个候选可见对象的 `object_id/name/type/dimensions/location/locked` 摘要。
- 支持的 action schema 与有限枚举。

0.6.0 不发送上轮 focus、state diff、相机摘要或已有 hard constraints；这些字段只有在对应功能和重新确认的数据预览完成后才允许加入。

默认不发送 mesh 顶点、纹理、完整 `.blend`、全部历史、截图。只有明确功能需要且用户同意后才扩展。

### 11.3 LLM 输出要求

- 只接受 JSON 候选计划；模型不能提供 `plan_id/source/scene_fingerprint/requires_confirmation`，这些可信字段由本地主进程补齐。
- temperature/采样策略由 provider adapter 配置，但 parser 不能依赖自然语言“解释文本”。
- 第一次 schema validation 失败可以做至多一次 repair request；仍失败即返回错误，不无限重试。
- 模型永远不能返回可执行 Python 作为正常动作。

### 11.4 Provider 接口

```python
class PlannerProvider(Protocol):
    def plan(self, request: PlannerRequest) -> PlannerResponse: ...

@dataclass(frozen=True)
class PlannerUsage:
    provider: str
    model: str
    input_tokens: int | None
    output_tokens: int | None
    estimated_cost: float | None
    latency_ms: int

@dataclass(frozen=True)
class PlannerResponse:
    plan_payload: dict
    usage: PlannerUsage
    request_id: str | None
    request_count: int
    repair_count: int
```

Provider adapter 只处理认证、HTTP、模型参数、usage 解析；业务 prompt 组装和 schema validation 不散落到 provider 文件。

---

## 12. BYOK、隐私与安全

### 12.1 API Key

正式产品采用 BYOK。开发阶段优先通过环境变量注入 key。不得：

- 把 key 保存在 `.blend`。
- 把 key 写入日志。
- 把 key 提交到 git。
- 把用户 key 先传到开发者服务器再转发，除非未来明确改变产品架构并新增安全评审。

正式 UI 需要 CredentialStore 抽象。若暂时无法安全使用 OS credential store，宁可提供“本次会话使用 / 环境变量配置”，也不要把明文 key 混入项目文件。

### 12.2 网络访问

M1 完全无网络。M2 引入 provider 时：

- manifest 显式声明 network 权限。
- 启动请求前检查 Blender 是否允许在线访问。
- 网络失败必须是可恢复错误，不允许破坏当前 scene。
- 网络层不能在请求未完成期间修改 Blender state。

### 12.3 数据最小化

默认只把完成语义解析所必需的场景摘要发送给 provider。UI 在第一次启用模型时应明确说明“会把哪些对象元数据发送给第三方模型服务”。遥测默认关闭；MVP 不做后台遥测上传。

### 12.4 任意代码执行

禁止实现“模型输出 Python -> `exec()`”。禁止把任意字符串拼接后交给 Blender Python 执行。所有能力必须经过 action whitelist。

---

## 13. UI / UX Contract

### 13.1 正式用户流

```text
用户输入意图
  -> 解析
  -> Plan Preview（对象 + 动作 + 约束 + 风险）
  -> 用户 Confirm / Reject
  -> 执行事务
  -> Verification Result
  -> 成功：可继续编辑 / Undo
  -> 失败：自动回滚 + 明确错误
```

### 13.2 Preview 必须显示

- 计划影响的对象名称。
- 每个动作的人类可读描述。
- 当前锁定对象。
- 是否会调用 LLM（以及 provider/model，若发生）。
- 需要用户特别确认的高风险动作。

### 13.3 不允许的 UX

- 用户点击一次后后台静默执行大量不可见动作。
- 失败后只显示“Something went wrong”。
- 自动移动锁定对象再把它移回来。
- 为了“成功率”悄悄降低 verifier 标准。

---

## 14. 错误模型

所有可预期错误使用稳定 code，不通过解析异常字符串驱动 UI。

| Code | 含义 | 默认处理 |
|---|---|---|
| `PLAN_SCHEMA_INVALID` | ActionPlan 格式不合法 | 不执行；展示具体字段 |
| `PLAN_STALE` | Preview 后场景已变化 | 重新读取并规划 |
| `OBJECT_NOT_FOUND` | 引用对象不存在 | 不执行 |
| `OBJECT_LOCKED` | 尝试修改锁定对象 | 不执行 |
| `ACTION_NOT_SUPPORTED` | 不在白名单 | 不执行 |
| `PRECONDITION_FAILED` | 执行前约束不满足 | 不执行 |
| `SPATIAL_UNSUPPORTED_GEOMETRY` | 当前算法无法可靠处理几何 | 不执行；说明限制 |
| `POSTCONDITION_FAILED` | 动作后验证失败 | 自动 rollback |
| `UNAUTHORIZED_CHANGE` | 非 affected object 被改变 | 自动 rollback |
| `ROLLBACK_FAILED` | 恢复校验失败 | 停止后续动作，高优先级错误 |
| `PRINT_SPEC_INVALID` | 参数化打印件规格无效或越界 | 不生成几何；指出字段 |
| `PRINT_PROFILE_INVALID` | 打印配置包含无效参数 | 不执行检查；要求修正配置 |
| `NETWORK_DISABLED` | Blender 禁止在线访问 | 保持场景不变 |
| `PROVIDER_AUTH_ERROR` | API key/认证失败 | 保持场景不变 |
| `PROVIDER_RATE_LIMIT` | 模型限流/额度 | 保持场景不变，可稍后重试 |
| `PROVIDER_OUTPUT_INVALID` | 模型输出无法修复为 schema | 不执行 |
| `INTERNAL_ERROR` | 未分类 bug | 记录 trace，保持/恢复事务 |

---

## 15. 日志与可观测性

### 15.1 本地 structured logging

使用 JSONL。每行一个事件，至少：

```json
{
  "ts": "ISO-8601",
  "level": "INFO",
  "event": "action.completed",
  "session_id": "...",
  "plan_id": "...",
  "action_id": "...",
  "duration_ms": 18,
  "result": "pass"
}
```

### 15.2 事件名称

- `scene.snapshot.created`
- `plan.created`
- `plan.validation_failed`
- `transaction.started`
- `action.started`
- `action.completed`
- `verification.completed`
- `transaction.committed`
- `transaction.rolled_back`
- `rollback.failed`
- `llm.request.completed`

### 15.3 日志安全

默认不记录 API Key；默认不记录完整 prompt；如 debug 模式允许保存 prompt，必须显式开关并对 key/authorization header 永久 redaction。

---

## 16. Benchmark 与正式作品指标

### 16.1 核心指标

| 指标 | 定义 |
|---|---|
| Task Success Rate | 最终状态满足任务所有 hard constraints 的比例 |
| Constraint Preservation | 多轮编辑后此前 hard constraints 仍成立的比例 |
| Unauthorized Change Rate | 未授权对象发生变化的任务比例 |
| Rollback Accuracy | 失败后完整恢复 checkpoint 的比例 |
| LLM Calls / Successful Task | 完成成功任务所需模型调用次数 |
| Tokens / Cost | 成功任务输入/输出 token 与模型费用 |
| Local Execution Ratio | 无模型参与完成的动作比例 |
| Time / Retries | 总耗时与用户/模型重试次数 |

### 16.2 Baseline

至少比较：

- **Baseline A：Blender 手工操作** — 验证是否真的节省操作。
- **Baseline B：普通 LLM 直接/自由操作 Blender** — 验证 constrained architecture 在成本/可靠性/可控性上是否有优势。

不要求所有指标都赢；至少要有一个与架构直接相关、可重复的明显优势，同时诚实报告代价。

### 16.3 Benchmark Case 格式

```json
{
  "case_id": "mvp_001",
  "fixture": "desk_lamp.blend",
  "initial_assertions": [],
  "instruction": "把台灯放到桌面右侧，桌子不要动",
  "expected_constraints": [
    {"type":"on","object":"lamp-id","target":"desk-id"},
    {"type":"right_of","object":"lamp-id","target":"desk-id"},
    {"type":"preserve_transform","object":"desk-id"}
  ]
}
```

Benchmark runner 必须能在没有 UI 的情况下执行固定 JSON plan；M2 以后再增加“自然语言 -> plan -> execute”的端到端组。

---

## 17. 测试策略

### 17.1 测试金字塔

**Pure unit tests**：domain schema、容差、关系判断、plan validator、diff、错误映射。尽量不依赖 `bpy`。  
**Blender integration tests**：SceneReader、Executor、Checkpoint、真实 matrix/bbox、Undo/restore。  
**End-to-end tests**：固定 `.blend` + instruction/plan + verifier。  
**Manual UX tests**：Panel、Preview、Confirm、错误信息。

### 17.2 Headless 集成测试

仓库提供脚本，使测试可通过 Blender background mode 执行。原则形式：

```bash
blender --background tests/fixtures/desk_lamp.blend \
  --python tests/integration/run_m1_suite.py
```

返回码非 0 表示失败；CI 读取 JUnit/JSON 结果。测试代码不得依赖开发者个人 Blender 配置。

### 17.3 M1 必测案例

1. lamp 正常 place_on desk -> PASS。
2. lamp place_on + right_of -> PASS。
3. desk lock 后尝试 move desk -> `OBJECT_LOCKED` 且状态不变。
4. 修改 lamp 后 desk fingerprint 不变。
5. 人为制造 postcondition failure -> 自动 rollback -> checkpoint diff 为 0。
6. Preview 后手动移动 desk -> Confirm -> `PLAN_STALE`。
7. 目标对象不存在 -> 不修改任何对象。
8. 重复执行同一 fixture + 同一 plan -> 结果一致。

### 17.4 回归原则

每个已发现并修复的真实 bug 必须新增一个 regression test。禁止只修代码不留测试。

---

## 18. Repository Structure

```text
blender-scene-assistant/
├─ blender_manifest.toml
├─ __init__.py
├─ LICENSE
├─ README.md
├─ AGENTS.md
├─ pyproject.toml                 # 开发工具配置，不假设 Blender 会安装依赖
├─ bsa/
│  ├─ ui/
│  │  ├─ panel.py
│  │  ├─ operators.py
│  │  └─ properties.py
│  ├─ application/
│  │  ├─ service.py
│  │  └─ transaction.py
│  ├─ domain/
│  │  ├─ scene.py
│  │  ├─ actions.py
│  │  ├─ constraints.py
│  │  ├─ results.py
│  │  └─ errors.py
│  ├─ core/
│  │  ├─ spatial.py
│  │  ├─ validator.py
│  │  ├─ verifier.py
│  │  ├─ diff.py
│  │  └─ fingerprint.py
│  ├─ blender_adapter/
│  │  ├─ scene_reader.py
│  │  ├─ executor.py
│  │  ├─ checkpoint.py
│  │  └─ ids.py
│  ├─ planner/
│  │  ├─ local_parser.py
│  │  ├─ context_builder.py
│  │  └─ llm/
│  │     ├─ base.py
│  │     ├─ openai.py            # M2 后
│  │     └─ usage.py
│  └─ infra/
│     ├─ config.py
│     ├─ logging.py
│     └─ credentials.py
├─ tests/
│  ├─ unit/
│  ├─ integration/
│  ├─ e2e/
│  └─ fixtures/
│     └─ desk_lamp.blend
├─ benchmarks/
│  ├─ cases/
│  ├─ runner.py
│  └─ results/.gitkeep
├─ docs/
│  ├─ DEVELOPMENT_SPEC.md
│  ├─ decisions/
│  │  ├─ ADR-000-template.md
│  │  └─ ADR-001-coordinate-semantics.md
│  ├─ benchmark_spec.md
│  └─ privacy.md
└─ scripts/
   ├─ run_blender_tests.*
   ├─ build_extension.*
   └─ validate_extension.*
```

原则：Blender specific 代码集中在 `ui/` 与 `blender_adapter/`；核心 domain 不允许到处 `import bpy`。

---

## 19. Extension Manifest 首版约定

M1 可先不声明 network。正式进入 M2 并支持 API 后再增加权限。

```toml
schema_version = "1.0.0"
id = "blender_scene_assistant"
version = "0.1.0"
name = "Blender Scene Assistant"
tagline = "Reliable natural-language scene editing with deterministic execution"
maintainer = "<maintainer>"
type = "add-on"
blender_version_min = "5.2.0"
license = ["SPDX:GPL-3.0-or-later"]

# M2 以后：
# [permissions]
# network = "Connect to the AI provider selected by the user"
```

如不准备发布到 Blender 官方 Extensions Platform，许可证/分发策略仍需单独决定；不要因为 Demo 阶段方便就忽略许可证。

---

## 20. Coding Standards

### 20.1 基本规则

- Python 全量 type hints，公共接口有 docstring。
- 业务逻辑函数尽量小、可测试、无隐藏副作用。
- 禁止 bare `except:`；异常必须映射为 domain error 或重新抛出。
- 禁止 magic number，容差/限值集中配置。
- 禁止用对象显示名作为长期唯一标识。
- 禁止在 `core/` 中读取全局 `bpy.context`。
- 禁止直接 `exec`/`eval` 模型输出。
- 修改 Blender state 的代码必须可定位到 executor/checkpoint 层。
- 日志使用稳定 event name，不在业务代码到处 `print()`。

### 20.2 API 设计

优先显式输入输出：

```python
result = service.execute_plan(plan, expected_scene_fingerprint)
```

不要设计成：

```python
GlobalAgent.run_everything_from_context()
```

### 20.3 Determinism

同 fixture、同 plan、同 Blender 版本，在无用户并发编辑时结果必须在 tolerance 内相同。随机行为必须有显式 seed，并默认不用于 M1。

---

## 21. Codex Working Contract（必须放入 AGENTS.md）

Codex 在这个仓库中工作时遵守以下约束：

1. 先阅读 `docs/DEVELOPMENT_SPEC.md` 和最新 ADR，再写代码。
2. 当前里程碑优先于“顺便做得更完整”；不得未经请求扩 scope。
3. M1 禁止引入 LLM、HTTP、聊天 UI、mesh editing。
4. 每实现一个 domain 行为先补/写测试，再连接 Blender UI。
5. 不用自由 Python 执行替代 action schema。
6. 不弱化 verifier 让失败测试通过；先解释失败原因。
7. 所有 Blender state 变更必须经过 transaction/executor。
8. 新增字段/action/error code 必须同步 schema、测试、文档。
9. 遇到无法可靠支持的几何，返回明确 unsupported error，不做静默近似。
10. 完成任务时报告：改了什么、测试了什么、仍有哪些已知风险。

---

## 22. M0：仓库初始化 Definition of Done

M0 只建立“可以严肃开发”的地基，不追求功能。

必须完成：

- 仓库目录按本规范建立。
- `blender_manifest.toml` 可通过 validate。
- Extension 能安装、启用、禁用，无 console exception。
- `AGENTS.md` 写入 Codex Working Contract。
- `docs/DEVELOPMENT_SPEC.md` 放入仓库。
- `ADR-001-coordinate-semantics.md` 冻结 M1 轴向语义。
- 基础日志可写 session event。
- `.gitignore` 排除 key、临时 `.blend1`、构建产物、私有 benchmark 输出。

**M0 不写 LLM。**

---

## 23. M1：Deterministic Core Definition of Done

M1 是整个项目第一个生死关。只有全部通过才进入 M2。

必须实现的闭环：

```text
加载 desk + lamp fixture
-> SceneReader 构造 snapshot
-> plan: place_on(lamp, desk) + right_of(lamp, desk)
-> validator PASS
-> capture checkpoint
-> executor 应用动作
-> verifier PASS
-> lock(desk)
-> 修改 lamp
-> verifier 证明 desk 未变化
-> restore checkpoint
-> verifier 证明恢复成功
```

M1 完成条件：

- 8 个 M1 必测案例全部自动化通过。
- 同样测试连续运行至少 20 次，无非确定性失败。
- 任一失败都不会留下半执行 scene state。
- 所有失败有结构化 error code。
- 无 LLM、无网络依赖。
- 有一份 `m1_results.json` 保存测试/性能基础数据。

M1 未通过时，不进入 LLM 集成。

---

## 24. M2：Intent Planning / LLM Definition of Done

M2 才允许接模型。第一版只接一个 provider 即可，架构保持 provider-neutral。

必须实现：

- `LocalParser` 优先分流明确命令。
- `ContextBuilder` 只取相关对象摘要。
- `PlannerProvider` 抽象。
- 一个真实 provider adapter。
- JSON schema validation + 最多一次 repair。
- usage/latency/token 记录。
- API Key 不进入 `.blend` 与日志。
- 模型输出不能直接执行，必须经过 validator/preview/confirm。

M2 验收：固定自然语言任务能稳定得到可执行 plan；模型不可用、限流、输出错误时 scene 仍保持不变。

0.6.1 的补充约束（ADR 008）：AI 只开放 `place_on/move/lock`，`unlock` 只接受明确本地指令。预览由本地读取实际动作生成，模型摘要不能充当确认依据。固定任务同时检查最终用户目标和任务允许变化集合，不能只检查执行计划自己的 affected set。20 个公开合成任务分别提供 `review/replay/live` 模式，默认不联网，真实 HTTP 预算默认 2 次（包括修复）；跳过不算已测模型失败，回放不产生模型准确率。该版本仍属于 M2 验收，不提前增加构图、建模或连续记忆功能。

0.6.2 的补充约束（ADR 009）：增加显式 `output_format=json_object/json_schema` 会话配置，默认保留通用模式。结构化模式由候选协议模块生成关闭额外字段的正式 Schema，限定本轮对象及启用动作；工作进程、UI 与评测入口必须一致。Schema 不替代本地语义校验、确认、事务或验证器，不自动降级或增加请求预算。移动向量的字典序列化必须是 JSON 数组；保持原位约束不等于保持网格形状。仍在 M2，没有新增动作或放宽几何支持。

0.6.3 的界面补充（ADR 010）：用户确认精简呈现，主界面按阶段显示一个主要动作。设置与发送详情展开状态只存在于会话，不进入业务动作协议；旧项目的精确控制展开状态不能撑开主屏。完整发送数据有展开入口，实际动作、保护约束、模型来源及执行确认不可省略；发送同意与执行确认仍独立。缺少模型要给出可恢复的设置入口。头像绘制 92 像素、点击半径 42 像素不变。角色图由用户指定；用户随后于 2026-10-16 确认拥有使用权并要求提交公开仓库，来源记录仍需保留。不扩充动作、不修改执行器、事务、验证器或网络权限策略。

参数化打印件 P0（ADR 011）是用户明确授权的新实验轨，不修改 0.6.3 场景动作。本阶段仅建立轴对齐矩形电路板外壳的毫米制领域模型、确定性尺寸推导与 FDM 规则检查；没有 Blender 网格写入、AI 规划、切片器控制或真实打印成功声明。对象创建进入 P1 前必须先设计新的白名单 action，并扩展 checkpoint、executor 与 verifier 支持创建/替换/删除的原子回滚。

0.7.0 的转接板 P2 界面（ADR 016）新增独立的 `N → BSA → 3D 打印零件` 产品入口，并把
右下角助手入口切换到该流程。界面只支持矩形板和两组固定语义双孔，按“填写参数 → 本地检查 →
确认创建 → 验证结果”推进；输入变化必须废弃旧摘要。检查阶段不得修改场景，确认后的唯一写入
路径是 `AdapterPlateCreationService` 与 `BlenderAdapterPlatePort`。P2 不接 AI、不导出、
不声明实物可打印；旧场景领航员保留为折叠功能。

参数化打印件 P1（ADR 012）新增独立的 `create_enclosure_preview` 白名单创建计划和事务服务，
不混入只支持既有对象变换的场景动作协议 0.1。纯核心先生成毫米制部件清单，Blender 适配器
按场景单位创建底板、四面侧壁、线框上盖、电路板代理、实心固定柱和接口开口代理；提交前
必须核对部件集合、角色、形状、中心、尺寸、事务标记及既有场景不变。任何不一致都删除本次
新建物体并验证恢复。P1 是装配体积预览，不包含布尔开孔、空心螺丝柱、连接结构、流形检查
或 STL/3MF 导出，不能称为可直接打印模型。P2 必须另行冻结并测试这些几何规则。

3D 打印零件助手的 AI/BYOK 边界由 ADR 013 冻结。新产品提供“按尺寸创建”和“按用途设计”
两个入口，但最终共享同一套参数模型、事务、验证和版本差异。现有 OpenAI-compatible 服务地址、
模型、会话级临时密钥、输出格式、连接测试和隔离网络进程继续复用；没有 API 时，本地尺寸建模
不能被阻断。打印件 AI 只能输出 `needs_input`、`design_candidate`、`parameter_patch` 三类严格
候选，不能复用旧场景 ActionPlan 直接写 Blender，也不能输出 Python。每个零件族必须先建立关闭
字段 Schema、纯 Python 测试和本地验证器，之后才允许接入 AI 和 UI。

---

## 25. M3：连续编辑与约束

目标：证明这不是单轮 prompt demo。

新增能力：

- 多轮 hard constraints。
- focus/reference state。
- `preserve_transform`。
- state diff 上下文。
- plan stale detection。
- 用户锁定/解锁。
- checkpoint history（有限深度即可）。

验收示例：

“桌子靠墙，灯放桌面右侧” -> “桌子不要动，把书架放左边” -> “灯再往里一点” -> “撤销最后一步”。

最后 verifier 必须证明桌子 transform 全程未被未授权修改。

---

## 26. M4–M6 概览

**M4 Product UX / Packaging**：正式 Panel、Plan Preview、confirm/reject、provider settings、extension build/validate。  
**M5 Benchmark / User Validation**：固定任务集、两种 baseline、真实资产小样本试用、失败分类。  
**M6 Portfolio Release**：可复现 release、README、架构图、benchmark 报告、Demo、已知限制、case study。

“做完功能”不等于完成项目；没有 benchmark 和真实反馈，不算正式作品完结。

---

## 27. First Sprint：直接交给 Codex 的任务队列

### DEV-001 — Bootstrap Extension Repository

**目标**：建立可安装/禁用的 Blender 5.2 Extension 骨架。  
**验收**：manifest validate 通过；启用/禁用无异常；目录符合第 18 节。  
**禁止**：不做网络、不做模型。

### DEV-002 — Domain Types

实现 `SceneSnapshot / ObjectState / BoundingBox / ActionPlan / Action / Constraint / Result / DomainError`。  
**验收**：纯 Python 单测；序列化/反序列化稳定；未知 action fail closed。

### DEV-003 — Stable Object IDs + SceneReader

实现 `bsa_object_id`、重复 UUID 检测、world transform、world AABB、lock state。  
**验收**：fixture 的 snapshot 可输出确定 JSON；重复读 fingerprint 一致。

### DEV-004 — Fingerprint + Diff

实现相关对象 fingerprint 和 transform diff。  
**验收**：手动移动 desk 后 fingerprint 必变；无变化时稳定。

### DEV-005 — Spatial `place_on`

实现 candidate transform 计算，先不直接写 bpy。  
**验收**：lamp bottom 对齐 desk top；unsupported geometry 返回明确错误。

### DEV-006 — `relative_place(left/right)`

M1 按 world frame 实现，距离和 clearance 使用集中配置。  
**验收**：left/right verifier 自动通过。

### DEV-007 — Transaction + Executor

实现 affected set、precondition、checkpoint、apply、verify、commit/rollback。  
**验收**：中途故意失败时 scene 恢复。

### DEV-008 — Lock Semantics

实现 `bsa_locked`、lock/unlock、executor guard。  
**验收**：锁定对象永远不能被普通 action 修改。

### DEV-009 — Verifier

实现 place_on、left/right、preserve_transform、unauthorized change、rollback verification。  
**验收**：输出结构化 CheckResult，不依赖截图人工判断。

### DEV-010 — M1 Headless Suite

建立 `desk_lamp.blend` fixture 和第 17.3 节 8 个案例。  
**验收**：命令行可一次运行全部案例并输出机器可读结果。

**Sprint Gate：DEV-001 ~ DEV-010 全绿后，才创建任何 LLM issue。**

---

## 28. 首个端到端输入与预期

固定 fixture：`desk_lamp.blend`。对象：`Desk`、`Lamp`。

输入 plan：

```json
{
  "schema_version": "0.1",
  "plan_id": "m1-demo-001",
  "source": "test",
  "scene_fingerprint": "<generated>",
  "requires_confirmation": false,
  "actions": [
    {
      "action_id": "a1",
      "type": "place_on",
      "object_id": "<lamp-id>",
      "target_id": "<desk-id>",
      "region": "right",
      "clearance": 0.0
    },
    {
      "action_id": "a2",
      "type": "lock",
      "object_id": "<desk-id>"
    }
  ],
  "constraints": [
    {
      "constraint_id": "c1",
      "type": "preserve_transform",
      "object_id": "<desk-id>",
      "severity": "hard"
    }
  ],
  "user_summary": "Place lamp on the right side of desk and protect desk"
}
```

成功输出最低要求：

```json
{
  "status": "COMMITTED",
  "plan_id": "m1-demo-001",
  "verification": {
    "passed": true,
    "unauthorized_changes": [],
    "checks": [
      {"check_type":"place_on","passed":true},
      {"check_type":"region_right","passed":true},
      {"check_type":"preserve_transform","passed":true}
    ]
  }
}
```

---

## 29. Go / No-Go 产品关卡

| Gate | 问题 | Go | No-Go |
|---|---|---|---|
| G1 技术 | 确定性 core 能否稳定执行/验证/恢复？ | M1 全绿 | 修底层，不接 LLM |
| G2 架构 | 大部分工作是否真的移出 LLM？ | local ratio 高、调用受控 | 重新切职责 |
| G3 竞争 | 对直接 Agent 是否至少一项明确优势？ | 成本/可靠/可控之一稳定胜出 | 收缩场景或改 framing |
| G4 价值 | 是否存在手工明显繁琐、工具明显省事的任务族？ | 可重复出现 | 换任务族 |
| G5 用户 | 真实用户是否愿意第二次用？ | 有主动复用 | 若只有“挺酷”继续收缩 |
| G6 作品 | contribution 是否清楚属于你？ | 架构+指标+取舍可解释 | 补 benchmark/case study |

日常开发不重复审判项目意义；只在 gate 或出现新证据时正式复盘。

---

## 30. Definition of Done：正式作品完成线

只有以下证据齐备，才能把项目称为正式作品：

- 可安装、可复现的 Blender Extension release。
- 固定任务集自动验证，不靠挑成功案例。
- 多轮编辑证明 lock / constraint / stale plan / rollback 是真实系统能力。
- 与手工 Blender 和普通直接 Agent 至少各做一组可复现实验。
- 记录成功率、调用次数、token/费用、耗时、重试和本地执行比例。
- 至少少量真实用户使用自己的资产试用，并有失败/阻塞记录。
- README 能解释问题、非目标、架构、动作协议、测试、评测、局限。
- Demo 展示“意图 -> plan -> confirm -> execute -> verify/rollback”，而不是只有最终画面。
- 有失败案例和明确不支持的任务。
- repo 不含秘密、个人绝对路径、无法复现的手工步骤。

---

## 31. 开发开始前的唯一执行顺序

```text
1. 把本文件保存为 docs/DEVELOPMENT_SPEC.md
2. 创建 AGENTS.md，复制第 21 节
3. DEV-001：Extension skeleton + manifest validate
4. DEV-002 ~ DEV-004：Domain / SceneReader / Fingerprint
5. DEV-005 ~ DEV-009：Spatial / Transaction / Lock / Verifier
6. DEV-010：Headless M1 suite
7. M1 Gate Review
8. 只有 G1=GO，才创建 M2 LLM/provider 任务
```

如果 Codex 在第 3 步就开始写 OpenAI/Claude 调用，视为违反本开发规范，应立即回退。

---

## 32. 外部技术参考（截至 2026-09-10）

- Blender LTS：https://www.blender.org/download/lts/
- Blender Python API：https://docs.blender.org/api/current/
- Blender Extensions / Getting Started：https://docs.blender.org/manual/en/latest/advanced/extensions/getting_started.html
- Blender Python threading gotcha：https://docs.blender.org/api/current/info_gotchas_threading.html
- Blender MCP baseline：https://github.com/ahujasid/blender-mcp

本规范中的产品范围、指标与 Go/No-Go 规则来自本项目 v0.1/v0.2 文档；Blender Extension 包结构、manifest、网络权限与 LTS 选择参考 Blender 官方文档。实现时如果官方 API 行为与本规范冲突，以目标 Blender 5.2 LTS 的实际 API/官方文档为准，并用 ADR 记录变更。

---

# Appendix A — ADR Template

```markdown
# ADR-XXX: <title>

Status: Proposed / Accepted / Superseded
Date: YYYY-MM-DD

## Context
为什么需要做这个决定？现有证据是什么？

## Decision
选择什么？语义要精确。

## Alternatives
至少列出一个被拒绝方案及原因。

## Consequences
得到什么，牺牲什么？

## Validation
用什么测试/benchmark 证明这个决定有效？
```

# Appendix B — PR Checklist

每个 PR 至少检查：scope 是否属于当前 milestone；新增行为是否有测试；是否绕过 transaction；是否修改 schema/错误码而未更新文档；是否记录秘密；是否弱化 verifier；是否有无法解释的 magic number；是否在非必要路径引入 LLM；是否能复现测试命令。

# Appendix C — 当前明确的开放问题

以下问题**暂不在实现前拍脑袋解决**，等 benchmark/用户证据出现后再决策：

- `left/right/front/back` 是否从 world frame 升级为 target-local frame。
- AABB 何时不足，需要 OBB / ray-cast / collision mesh。
- 是否加入 camera、material actions。
- 是否同时支持 Blender 4.5 LTS。
- Provider 是否需要多模型自动选择。
- 是否需要本地小模型完全替代云端 LLM。
- 是否从“初学者”收缩到电商摆场、游戏关卡预摆、产品可视化等更具体用户群。

这些开放问题进入 backlog，不得阻塞 M1。

---

## 33. 3D 打印零件助手增量基线（2026-10-18）

原规范的场景编排 M1–M6 保留为已完成能力与历史基线。正式产品新增“3D 打印零件助手”方向时，
以 ADR 013 和 ADR 014 覆盖与零件意图、AI 边界和转接板修改语义有关的旧范围描述。

当前已完成的打印件里程碑包含：

1. 纯 Python 矩形转接板参数模型；
2. 圆形贯穿孔规格、轮廓包含和孔重叠验证；
3. 改变板宽/板深并保持全部安装模式世界孔位的确定性修改；
4. `needs_input`、`design_candidate`、`parameter_patch` 三类关闭字段 AI 候选解析；
5. 中文开发文档、离线演示和单元测试。
6. 强制确认的 `create_adapter_plate_mesh` 计划；
7. Blender 单一封闭板件网格和真实圆形贯穿孔；
8. 创建检查点、实际网格回读、流形/连通/孔几何验证和失败回滚。

当前里程碑不包含正式 UI、网络请求、导出或可打印声明。下一里程碑必须继续遵守：

- 先测试创建计划、事务、执行器和独立验证，再连接 Blender UI；
- AI 候选不能替代本地几何验证，也不能直接执行 Python / `bpy`；
- 用户确认前不修改 Blender；后置验证失败必须回滚；
- 不支持的孔型和结构返回明确错误，不用近似几何冒充成功。
