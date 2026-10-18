# 矩形转接板 P1 开发者测试报告

日期：2026-10-18  
环境：Windows、Python 3.12、Blender 4.5.12 LTS  
范围：合成四孔矩形转接板的参数核心、创建事务、真实网格、独立回读和失败回滚。

## 测试结果

| 检查项 | 结果 |
|---|---:|
| 全仓纯 Python 回归 | 135/135 通过 |
| 转接板 P1 专项测试 | 11/11 通过 |
| Blender 真实创建 | 已提交并验证 |
| Blender Extension manifest / build | 通过 / 通过 |
| 设计尺寸 | 80 × 40 × 3 mm |
| Blender 回读尺寸 | 79.999998 × 39.999999 × 3.000000 mm |
| 实际贯穿孔 | 4/4 |
| 网格流形 | 是 |
| 网格连通分量 | 1 |
| 顶点 / 面 | 328 / 504 |
| 错误孔径注入 | 已拒绝并回滚 |
| 同事务额外对象注入 | 已拒绝并回滚 |
| 既有参考物体 | 变换保持不变 |

尺寸差异来自 Blender 单精度网格坐标，均低于当前 `0.02 mm` 回读容差。容差没有为失败样例
放宽；错误孔径被改成 99 mm 后仍明确失败。

## 证据命令

```powershell
python -m unittest discover -s tests -p "test_*.py" -q
.\scripts\run_adapter_plate_mesh_tests.ps1 `
  -Blender "D:\Blender Foundation\Blender\blender.exe" `
  -Output "dist\adapter_plate_p1.blend"
```

Blender 结果摘要：

```json
{
  "status": "COMMITTED",
  "rollback_status": "ROLLED_BACK",
  "extra_object_rollback_status": "ROLLED_BACK",
  "object_count": 1,
  "through_hole_count": 4,
  "is_manifold": true,
  "connected_components": 1,
  "vertex_count": 328,
  "face_count": 504
}
```

测试时 Blender 尝试写用户扩展缓存，受当前沙箱权限限制产生一条缓存警告；进程退出码、网格
创建、保存和所有断言均正常。测试没有联网，也没有读取或写入 API Key。

## 结论与限制

当前可以准确表述为：“项目能在 Blender 4.5.12 中事务化创建一个带四个真实贯穿孔的矩形
转接板，并从实际网格验证尺寸、孔位、流形和回滚。”

不能表述为“已经支持任意零件”“已经完成正式 UI”“AI 已经会建模”或“已经验证可打印”。
本报告使用公开合成尺寸，没有真实设备、支架、切片或实物装配证据。
