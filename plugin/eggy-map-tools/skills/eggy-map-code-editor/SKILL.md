---
name: eggy-map-code-editor
description: 通过本地 MCP、完整备份、严格离线验证和原子部署检查或修改《蛋仔派对》可编辑地图。适用于添加、删除、调和、验证和回滚组件，以及修复上传失败状态导致的地图无法删除；仅查组件时使用 eggy-component-finder。
---

# 蛋仔地图代码编辑

地图写入由 `eggy-map` MCP 完成；用户始终负责模拟器界面操作。

## 必须遵守

- 不操作 UI，不使用 OCR，不重启游戏或模拟器，不执行 `force-stop`，不按 Android 返回键，不进入运行/试玩模式。
- 写入前先调用 `device_status`。只有 `mode=writable` 才能继续。
- 用 `list_maps` 按精确名称取得最新 `map_ref`。同名多份时必须让用户按保存时间选择，不能猜。
- 写入前必须由用户明确确认已经退出编辑器并停在地图列表；随后只调用一次对应写工具并传 `editor_closed_confirmed=true`。
- 每次调用 `add_component`、`delete_components`、`reset_map_upload_failure`、`reconcile_map` 或 `rollback` 前，先向用户列明本次目标和副作用并取得该次写入批准；一次批准只对应一次写调用。
- 不接受任意设备路径、原始单位 ID 或任意 MessagePack 字段；只使用 MCP 返回的不透明引用和属性白名单。

## 操作选择

- 新增单个组件：先查 `component_ref`，再调用 `add_component`。
- 删除：先 `inspect_map`，按 `unit_ref` 调用 `delete_components`。服务器会扩展完整后代闭包并拒绝未知引用或不支持的出生点删除。
- 修复上传失败状态：遇到保存报上传错误（如 `504-66`）且地图因“正在上传”无法删除时，先按精确名称取得最新 `map_ref`，再调用 `reset_map_upload_failure`。它只把该地图索引中的持久化 `map_upload_fail_tag` 从 `true` 复位为 `false`，不会取消云端上传，也不会清除游戏进程内的上传锁。
- 声明式编辑：调用 `reconcile_map`。默认 `managed_only`；没有 `managed_prefix` 时只新增、更新和去重。只有用户明确要求清空未声明元素时才选 `whitelist`。
- 只读检查：调用 `validate_map`。
- 异常恢复：用户退出且不保存后，按 `deployment_id` 调用 `rollback`。

地图内容部署成功后告诉用户：手动进入编辑模式等待缓存重建并查看；正常则保存退出，异常则不要保存、退出后回滚。上传失败状态复位成功后不要进入或保存地图，直接从地图列表删除；若仍提示“地图正上传中”，说明进程内锁仍在，由用户手动完全关闭并重新打开游戏后再删除。云端上传失败、本地持久化标记和进程内上传锁必须分开报告。

需要构造 manifest 或解释失败码时读取 [references/mutation-contract.md](references/mutation-contract.md)。
