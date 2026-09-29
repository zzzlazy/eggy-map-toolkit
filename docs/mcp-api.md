# 本地 MCP 与插件合同

## 版本和边界

- 插件：`eggy-map-tools 0.1.0`
- Python API / MCP：`0.2.0`
- 传输：本地 STDIO
- 目标环境：当前受支持的 macOS、MuMu 和版本锁定游戏构建
- 组件目录：由使用者本地生成；候选数量和可写范围以实际目录与运行时检查为准

本服务不操作编辑器 UI，不使用 OCR，不进入运行模式，也不重启或停止游戏。调用方不能传入任意设备路径、原始 MessagePack 字段或原始实例 ID。

## 工具

| 工具 | 模式 | 合同 |
|---|---|---|
| `device_status` | 只读 | 返回设备唯一性、root、进程和 Profile 模式 |
| `list_maps` | 只读 | 精确名称查询并签发绑定当前修订的不透明 `map_ref` |
| `search_components` | 只读 | 分页搜索单位与特效，返回结构族、证据和写门禁 |
| `get_component` | 只读 | 返回版本化 `component_ref`、模型、属性 Schema 和拒写原因 |
| `inspect_map` | 只读 | 返回层级、变换、引用概况及快照绑定的 `unit_ref` |
| `validate_map` | 只读 | 严格检查格式、层级、缓存、批任务和碰撞引用 |
| `add_component` | 写入 | 新增一个 Schema 支持的组件 |
| `delete_components` | 写入 | 按 `unit_ref` 删除完整闭包；出生点和未知引用拒绝 |
| `reset_map_upload_failure` | 写入 | 仅复位目标地图索引中的本地上传失败标记；不取消云端上传或进程内锁 |
| `reconcile_map` | 写入 | 按 manifest 幂等新增、复用、更新和删除 |
| `get_deployment` | 只读 | 查看一个部署或回滚回执 |
| `list_deployments` | 只读 | 查看本地保留的部署记录 |
| `rollback` | 写入 | 恢复完整地图目录、归档、索引、权限和双重哈希 |

MCP 的五个写工具带 `readOnlyHint=false` 和 `destructiveHint=true`；Skill 在调用前必须取得用户对该次写入的确认。

## Reconcile manifest

```text
{
  "schema_version": 1,
  "map_ref": "<opaque-current-map-ref>",
  "cleanup_policy": "managed_only",
  "managed_prefix": null,
  "components": [
    {
      "logical_name": "<caller-chosen-name>",
      "component_ref": "<versioned-component-ref>",
      "transform": {
        "center": <finite-number-triple>,
        "size": <positive-number-triple>,
        "rotation_deg": <finite-number-triple>,
        "forward_axis": <supported-axis-or-null>
      },
      "color": null,
      "properties": {},
      "role": "obstacle"
    }
  ],
  "map_settings": {},
  "constraints": {}
}
```

示例中的值只说明 Schema，不代表任何地图实例。`managed_only` 默认不删除未声明组件；提供 `managed_prefix` 时仅清理该命名空间中未声明的顶层组件。`whitelist` 必须显式选择，并删除所有未声明顶层组件及其后代。

组件按“逻辑名 + 组件类型”匹配。重复项保留实例标识最小且引用闭合的一项；同一 manifest 对首次结果再次调和必须达到逐文件零差异。

## 统一事务

写工具按以下顺序执行：

1. 获取设备和地图互斥锁，复核唯一设备、root、进程和 Profile。
2. 连续冻结地图目录、外层归档和索引，记录完整库存、UID、GID、权限、SHA-256 与 BLAKE2b。
3. 只在全新本地目录生成输出，严格解码并验证业务闭包。
4. 重新确认源修订未变化，将文件推入动态地图根内的同级暂存位置。
5. 校验暂存哈希，恢复权限，再进行日志化目录交换。
6. 校验部署后的文件、目录、权限和进程；失败时立即恢复并复核原状态。
7. 长期保存部署回执和完整备份。

普通写入不改外层归档和索引。由游戏在用户手动确认地图正常并保存后刷新它们。派生编辑器缓存、预载、批任务和静态碰撞缓存可以被安全清空，并在首次进入编辑模式时由游戏重建。

## 结构化错误

成功响应为 `{"ok": true, "result": ...}`；预期失败为 `{"ok": false, "error": {"code": ..., "message": ..., "context": ...}}`。关键错误包括：

- `DEVICE_NOT_UNIQUE` / `PACKAGE_NOT_UNIQUE`
- `PROFILE_MISMATCH`
- `STALE_MAP_REF` / `CONCURRENT_SAVE`
- `COMPONENT_NOT_WRITABLE` / `INVALID_PROPERTY`
- `EDITOR_NOT_CONFIRMED_CLOSED`
- `VALIDATION_FAILED`
- `ROLLBACK_FAILED`

所有失败都不返回成功部署回执。Profile 不匹配、同名地图未消歧、引用过期或属性不受支持时，设备必须保持不变。

## 目录维护与发布

新游戏构建不会自动获得写能力。维护者需针对新包静态提取目录，在全新目录运行：

```bash
eggy-map-build-catalog \
  --catalog <component-catalog> \
  --decoded-bindicts <decoded-package-tables> \
  --output <fresh-output> \
  --version-code <version-code> \
  --version-name <version-name> \
```

完成合成测试和人工审核后，通过 `tools/build_local_plugin.py --catalog <本地目录> --destination dist/eggy-map-tools` 构建本地插件。构建器生成 wheelhouse 和 `requirements.lock`，检查三个 Skill 与插件清单，不修改已安装插件或个人 marketplace。目录生成流程见 [本地组件目录](local-catalog.md)。
