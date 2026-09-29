# 组件目录合同

- `component_ref` 只在当前目录指纹下有效；目录更新后重新查询。
- `kind=unit` 是地图单位候选，`kind=effect` 目前只读。
- `static_status` 描述包内门禁证据，不代表用户界面当前可见。
- `write_capability.writable=true` 还要求运行时 Profile 匹配；真正写入前服务器会再次检查。
- `supported_properties` 是代码写入白名单。目录中出现但未列入此字段的属性不得传给写工具。
- `color_supported` 仅说明当前 Prefab 有已识别的 `paint_area1` 槽。
- 地图返回的 `map_ref` 和 `unit_ref` 都绑定当次文件修订；保存后需重新读取。
