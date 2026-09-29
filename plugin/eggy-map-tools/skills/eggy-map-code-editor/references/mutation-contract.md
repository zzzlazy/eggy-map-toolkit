# 写入与回滚合同

## Manifest

`reconcile_map` 接受 schema 1。manifest 自身包含最新 `map_ref`、`cleanup_policy`、可选 `managed_prefix`、可选地图设置和组件数组；每个组件包含唯一逻辑名、版本化 `component_ref`、中心/尺寸/旋转/朝向，以及目录明确允许的颜色和属性。逻辑名没有固定前缀。

- `managed_only`：复用并更新声明项；可用 `managed_prefix` 删除同命名空间中已不再声明的顶层组件。未提供前缀时不删除其他旧组件。
- `whitelist`：删除所有未声明顶层组件及后代，必须显式选择；任一未知反向引用都会让整个事务失败。

## 写入结果

地图内容写工具内部依次完成：修订检查、完整三件套备份、新目录生成、严格解码、结构验证、二次修订检查、暂存哈希、权限恢复和原子目录交换。外层归档和索引在普通写入中保持不变，由游戏在用户确认后保存刷新。

`reset_map_upload_failure` 同样先做修订检查和完整三件套备份，但只允许将精确目标地图的 `map_upload_fail_tag` 从布尔值 `true` 改为 `false`。服务器验证其他地图、目标地图其他字段、地图目录和归档都未改变，再对 `index.conf` 做带哈希与权限校验的原子文件交换。它不取消云端上传，也不能修改正在运行游戏进程中的上传锁。

成功结果返回新的 `map_ref` 和 `deployment_id`。旧地图引用立即视为过期。备份长期保留。

## 常见失败码

- `DEVICE_NOT_UNIQUE`、`PACKAGE_NOT_UNIQUE`：当前设备或游戏根不唯一。
- `PROFILE_MISMATCH`：当前游戏构建与目录不匹配，只能查询。
- `STALE_MAP_REF`、`CONCURRENT_SAVE`：地图在读取或部署期间变化；重新列出地图。
- `COMPONENT_NOT_WRITABLE`、`INVALID_PROPERTY`：构建器或属性闭包未开放。
- `EDITOR_NOT_CONFIRMED_CLOSED`：尚未确认退出编辑器。
- `UPLOAD_FAILURE_NOT_SET`：目标地图的持久化上传失败标记不是 `true`，不会写入。
- `MAP_ARCHIVED`：目标地图已有删除/归档时间，不允许复位上传失败状态。
- `VALIDATION_FAILED`：本地输出未通过完整门禁，设备未部署。
- `ROLLBACK_FAILED`：恢复未能完成；不要继续保存，保留现场处理。
