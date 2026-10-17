# 参数化电路板外壳 P1：Blender 装配预览

状态：核心与 Blender 4.5 创建事务已实现，尚未接入插件正式 UI。日期：2026-10-16。

## 用户现在能得到什么

给定 P0 的电路板和外壳参数，P1 会生成一份强类型、必须确认的
`create_enclosure_preview` 计划。确认后，Blender 中出现一个独立集合，包含：

- 1 个底板；
- 4 个侧壁；
- 1 个线框上盖；
- 1 个线框电路板代理；
- 与安装孔一一对应的实心固定柱；
- 与接口一一对应的线框开口代理。

默认合成板为 70 × 50 × 12 mm，四个安装孔和一个前侧 USB 接口，因此共生成 12 个部件。
外壳外尺寸为 76 × 56 × 23 mm。线框上盖保留在真实装配位置，让用户看见内部关系，而不是
为了展示效果偷偷改变装配尺寸。

## 事务和验证

所有 Blender 状态变更只经过 `EnclosurePreviewService` 与
`BlenderEnclosurePreviewPort`。执行器不会接收或执行 Python 字符串。

1. 写入前拒绝未知协议版本、非法 ID、无确认标记、同名外壳和重复事务。
2. 创建前记录既有对象身份、变换和锁定状态。
3. 每个新对象记录外壳 ID、事务 ID、部件 ID、角色和形状。
4. 创建后回读并核对部件集合、中心和毫米尺寸，容差为 `1e-5 mm`。
5. 任一检查失败，只删除本事务新建对象和集合，再验证既有场景恢复。

Blender 4.5.12 的后台集成测试既验证成功创建，也故意把上盖回读宽度改错 1 mm，证明真实
Blender 对象会被完整回滚，而不是放宽验证器。

## 这还不是可打印模型

P1 是装配体积预览，不能导出后直接承诺打印成功：

- 接口目前是开口代理，还没有从侧壁做布尔减法；
- 固定柱目前是实心圆柱，还没有螺丝通孔；
- 上盖没有卡扣、螺丝连接或装配公差结构；
- 圆角参数保存在设计规格中，但 P1 仍使用直角预览体；
- 没有非流形、自相交、最小特征、悬垂或切片检查；
- 没有 STL/3MF 导出和真实打印装配记录。

这些内容属于 P2，必须先写新的 ADR 和纯 Python/Blender 测试再实现。

## 本地验证

```powershell
python -m unittest tests.test_enclosure_design tests.test_enclosure_preview -v
.\scripts\run_enclosure_preview_tests.ps1 `
  -Blender "D:\Blender Foundation\Blender\blender.exe" `
  -Output "dist\enclosure_preview_p1.blend"
```

生成的 `dist/enclosure_preview_p1.blend` 是本机开发者预览，不进入源码历史，也不能作为真实
打印成功证据。实际运行记录见 `PARAMETRIC_ENCLOSURE_P1_TEST_REPORT.md`。
