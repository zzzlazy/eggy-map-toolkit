---
name: eggy-component-finder
description: 查询当前版本《蛋仔派对》地图组件、特效、EID、模型、结构族、属性和可写证据。适用于用户询问有哪些组件、某组件能否使用或需要组件目录；仅查询时不得修改地图。
---

# 蛋仔组件查询

使用插件提供的 `eggy-map` MCP 目录，不操作编辑器 UI，也不使用 OCR。

## 工作流

1. 用 `search_components` 按名称、EID、单位/特效、结构族或可写状态搜索；遵循分页游标，不臆测被截断的结果。
2. 用 `get_component` 查看目标项的模型、Prefab 证据、可接受属性及不可写原因。
3. 只有用户询问已放置元素时，才用 `list_maps` 精确定位地图，再以 `inspect_map` 读取实例。名称重复时让用户按保存时间选择 `map_ref`。
4. 区分“包内静态候选”“可写候选”和“编辑器账号当前可见”。包内出现不等于当前账号 UI 已开放；不要伪造 UI 证据。
5. 只返回调用结果中的版本化事实，不把实例引用当成跨地图稳定 ID。

本 Skill 不得调用 `add_component`、`delete_components`、`reconcile_map` 或 `rollback`。用户要求修改地图时改用 `$eggy-map-code-editor`。

需要解释证据等级或目录字段时读取 [references/catalog-contract.md](references/catalog-contract.md)。
