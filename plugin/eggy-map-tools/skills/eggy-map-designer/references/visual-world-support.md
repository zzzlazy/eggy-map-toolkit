# 视觉世界支持卡

本文件把题材从“十个宽泛章节”收紧为十五个稳定的视觉世界 ID。它解决两个问题：同属一个大题材的世界不再共用一份空泛换皮建议；另一名设计者也能直接取得基础件语法、装配族、壳体起点、状态轴和反捷径检查，而不必重新翻找案例。

设计资料与实证仍是两条轴：`design_space.status=complete` 只表示技能能给出一份可执行的合成起点；`empirical.status` 才说明本地优秀样本实际观察到了什么。前者不能把 `boundary_only` 或 `missing` 升级成正向案例，也不能证明题材与某个玩法类型的组合已经成熟。

## 使用命令

查看十五类概况：

```bash
python3 scripts/audit_visual_support.py --all-summary
```

取得一个视觉世界的完整支持卡：

```bash
python3 scripts/audit_visual_support.py --world industrial_mixed_scale
```

玩法主类型已确定时一并生成形态配对：

```bash
python3 scripts/audit_visual_support.py \
  --world vehicle_track_facility --primary-type sports_match
```

配对结果只选择灰盒壳体的起点。若玩法类型与视觉世界没有共同默认形态，结果会保留玩法拓扑，再要求把题材的 `MASS/MID/route_contact/state_detail` 语法翻译进去；它不会因为“交集为空”而换掉权威主循环，也不会把 17×15 种组合声称为已有样本。

## 十五个稳定 ID

| ID | 视觉世界 | 与相邻题材必须区分的重点 |
|---|---|---|
| `canyon_mountain_cave` | 峡谷/山地/洞穴 | 地层方向、洞内外包裹、栈道承重与坠落恢复 |
| `tropical_mud_character_world` | 热带泥地/角色场景 | 湿泥过程、角色尺度锚点以及角色动作留下的空间后果 |
| `winter_garden_showcase` | 冬季花园/展示 | 植被聚簇与留白、可达活动中景、冷暖焦点迁移 |
| `cellar_food_facility` | 酒窖/食品设施 | 原料—加工—出料设备链、容器/管线与压力面同屏可读 |
| `modern_city_narrative` | 现代城市/剧情空间 | 公共地标、街景—室内门槛、人口/设施同机位变化 |
| `school_human_scale_interior` | 学校/人类尺度室内 | 房间功能、连续门槛、家具簇和目标人数净空 |
| `industrial_mixed_scale` | 工业/混合尺度 | 厂房壳体、设备来源去向、巨物尺度锚点与生产状态 |
| `island_survival_world` | 岛屿/生存资源世界 | 资源分区、建造等级、扩张边界和可回望世界进度 |
| `vehicle_track_facility` | 车辆/赛道设施 | 连续路面、弯前视距、内外护栏、高速复位而非放大步行图 |
| `toy_candy_fairy_miniature` | 玩具/糖果/童话/微缩 | 两个熟悉尺度物、卡扣包装结构、材料拆分和巨物路线化 |
| `ancient_castle_historic_street` | 古建/城堡/历史街区 | 明确地域时代、层高柱距、屋顶承重排水与街巷开合 |
| `scifi_station_cyber_facility` | 科幻/空间站/赛博设施 | 厚壁舱段、气闸连接、统一面板网格与断电恢复 |
| `ocean_underwater_floating` | 海洋/海底/漂浮世界 | 先选海床/沉船/浮岛/垂直封套，流向、系泊和透明预算分开 |
| `horror_ruin_mystery` | 恐怖/废墟/悬疑空间 | 可信正常基线、局部异常、同机位回望与可靠安全规则 |
| `abstract_dream_music_data` | 抽象/梦境/音乐/数据空间 | 可复述几何规则、视觉休止、音画与权威状态同源 |

权威资料存放在 [视觉世界机器目录](visual-world-catalog.json)。每个条目必须至少包含三类基础形状、四个装配族、两种世界状态轴、两种壳体起点、五层基础件展开说明、三项实景证明门和三项禁用捷径。`scripts/audit_visual_support.py --self-test` 会把目录 ID 与研究覆盖账逐一对齐，并验证所有 Markdown 章节锚点。

## 支持卡怎样进入设计

1. 先由主类型支持卡确定权威循环、专项字段、异常场景和千件级装配种子；视觉世界不能改变终局所有者。
2. 从支持卡的 `profile.world_sentence_pattern` 改写本图世界句，不直接复制示例；再冻结记忆剪影、比例词和至少一种真实世界状态。
3. 把 `base_shape_roles` 转成当前版本可写的组件角色。它们是形状职责，不是 EID；未经目录查询不得填具体组件。
4. 用 `assembly_families` 改造主类型种子中的装配族，而不是在通用骨架外圈追加主题装饰。每个族都分别展开 `mass/mid/route_contact/state_detail/proxy_split`。
5. 从 `primary_type_pairing.recommended_start` 起草壳体卡，但以实际玩家关系、镜头和终局为准。交集为空时保留玩法形态，重新设计题材壳体，而非强行采用题材默认形态。
6. 把 `proof_gates` 写入关键镜头与试玩；把 `banned_shortcuts` 写入禁用清单。隐藏少量地标 Prefab 后，基础件仍须表达此世界。
7. 研究包中的 `supported_claims` 只用于它明确覆盖的决定。`current_limit` 原样进入参考缺口；不能用合成目录、同题材截图或另一种玩法的案例补成正向证据。

## 基础件数量的正确增长

支持卡不会给某个题材硬塞固定件数。成品数量先由真实空间合同和主类型密度档决定，再由视觉世界决定“数千个基本件花在哪里”：

- `mass` 完成可走地形、主包裹、地标和远期轮廓；
- `mid` 完成承重、接口、转角、厚度、设备链、家具簇或地貌层理，这是高完成度的主要增长层；
- `route_contact` 把视觉表皮与可靠碰撞、落点、多人净宽和机关扫掠分开；
- `state_detail` 只沿权威事件、使用痕迹和关键镜头增加变化；
- `proxy_split` 主动降低不可达背景、密集微件、透明、碰撞和投影成本。

因此“几千件”必须来自多个有职责的壳体、装配族和受控变体。把平面机械切成碎片、在不可见背面铺细件、平均撒植物/灯/窗，或复制同一小件凑数，仍会在密度、题材适配和逐视区性能门禁中失败。

## 证据边界

视觉支持卡始终输出 `deployable=false`。当前实证状态由 `eggy-map-designer/references/research-coverage.json` 实时读取，不在本文件复制一份会过期的状态表。若不再收集样本，`partial_positive/boundary_only/missing` 都保持原样；设计仍可作为明确标注的推断继续，但最终交付必须列出没有被样本验证的镜头、状态和性能问题。
