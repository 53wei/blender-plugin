# 矩形转接板 P1：Blender 真实网格与创建事务

日期：2026-10-18  
状态：核心与 Blender 4.5 创建事务已实现，尚未接入插件正式 UI。

## 用户最终会看到什么

给定一份已经确认的矩形转接板设计，P1 会生成必须确认的
`create_adapter_plate_mesh` 计划。确认后，Blender 场景中出现一个独立集合和一个原生网格对象：

- 板的外形、厚度和圆角来自毫米参数；
- 所有圆孔真实贯穿板体，不是线框或圆柱代理；
- 整块板是一个封闭、单一连通的流形网格；
- 网格可以继续在 Blender 中查看和编辑。

当前合成案例为 80 × 40 × 3 mm、2 mm 圆角、四个贯穿孔。Blender 4.5.12 实测结果为
328 个顶点、504 个面、1 个连通分量和 4 个贯穿孔。

本机开发者检查图生成在 `dist/adapter_plate_p1.png`，对应工程为
`dist/adapter_plate_p1.blend`；两者都在忽略目录中，不进入源码历史。检查图只能证明当前合成
模型被正确创建，不能证明实物打印和装配成功。

## 事务和独立验证

所有 Blender 状态变更都经过 `AdapterPlateCreationService` 和
`BlenderAdapterPlatePort`，执行器不接收 Python 字符串。

1. 写入前拒绝未知版本、非法 ID、无确认标记、同名板件、重复事务和未验证设计；
2. 创建前记录既有对象身份、变换和锁定状态；
3. 从二维外轮廓与反向孔轮廓三角剖分，再沿 Z 轴生成封闭网格；
4. 创建后从实际网格重新测量尺寸、圆角、孔数、孔中心和孔径；
5. 检查每条网格边为流形边、整个网格只有一个连通分量；
6. 检查本事务只创建一个板件对象，既有场景没有变化；
7. 任一检查失败，删除本事务创建的对象、网格和集合，再验证检查点恢复。

Blender 集成测试故意注入了错误孔径和同事务额外对象，两种情况都触发完整回滚；验证器没有
为了让测试通过而放宽容差。

## 本地验证

```powershell
python -m unittest tests.test_adapter_plate_mesh -v
python -m unittest discover -s tests -p "test_*.py" -v
.\scripts\run_adapter_plate_mesh_tests.ps1 `
  -Blender "D:\Blender Foundation\Blender\blender.exe" `
  -Output "dist\adapter_plate_p1.blend"
& "D:\Blender Foundation\Blender\blender.exe" `
  "dist\adapter_plate_p1.blend" --background `
  --python "demos\render_adapter_plate_mesh.py" -- "dist\adapter_plate_p1.png"
```

## 当前仍然不能做什么

- 正式插件界面还没有转接板参数表或“创建”按钮；
- 还没有把 AI 零件候选接入真实 Provider 请求；
- 还没有修改已经创建的 Blender 网格，P0 的保孔位修改目前只在参数层完成；
- 没有尺寸标注、孔点击信息、撤销版本列表或 STL/3MF 导出；
- 没有检查最小边距、最小壁厚、悬垂、切片结果、材料收缩或打印机误差；
- 没有真实打印和试装记录，因此不能称为“已验证可打印”。

下一阶段应实现统一参数界面和创建确认流程，让用户不运行开发脚本也能完成“填写尺寸 → 检查 →
确认 → 创建”。之后再接 AI 候选请求；AI 仍只能填写严格候选，不能直接操作 Blender。
