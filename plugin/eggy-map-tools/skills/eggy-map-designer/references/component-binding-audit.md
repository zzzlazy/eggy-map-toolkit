# 组件角色绑定与可写证据

参数化装配中的 `component_role` 是设计角色，不是组件引用。例如 `basic_wall_panel`、`basic_ceiling_rib` 和 `basic_landmark_mass` 可以全部由同一种可变形基础件承担，也可以因枢轴、非均匀缩放或材质限制分成几个组件。组件角色绑定账负责把这些抽象角色逐项映射到**当前游戏版本、当前设备状态下的组件证据**，避免千件级清单在实施时临时找模型或把不存在的 EID 写进方案。

本账只能检查覆盖、一致性和证据状态，不能自行证明某条目录记录真实。`verified_writable` 必须来自本次工作记录中实际运行的组件目录与设备查询；截图、旧版本缓存、他图模型路径或设计推断只能作为候选线索。

## 何时使用

- 概念或灰盒只使用少量已知组件时，可以在普通资源表里记录。
- 参数化计划出现多个 `component_role`、准备生成数百件以上实例，或同一种基础件将承担多个装配职责时，建立机器可读绑定账。
- 只查询组件时由 `$eggy-component-finder` 负责；本账不修改地图。
- 准备部署时，绑定账必须与最终装配计划重新对账，不能沿用种子或旧版本的“已验证”状态。

## 机器可读结构

先从装配计划生成完整模板：

```bash
python3 scripts/audit_component_binding.py assembly-plan.json --template \
  --output component-binding.json
```

根字段：

| 字段 | 说明 |
|---|---|
| `schema_version` | 当前为 `1` |
| `stage` | `design` 或 `predeploy`；模板固定从 `design` 开始 |
| `game_version` | 实际查询版本；未查时只能写 `unknown` |
| `device_status` | `unknown/read_only/writable` |
| `catalog_source` | 本次查询来源和边界，不写笼统“官方组件” |
| `assembly_expected_total` | 与装配展开总数完全一致，防止绑定账沿用旧清单 |
| `bindings[]` | 每个实际使用的 `component_role` 恰好一项 |
| `verification_boundary` | 明确脚本只核对声明，真实性仍依赖本次外部证据 |

每条绑定至少包含：

| 字段 | 说明 |
|---|---|
| `component_role` | 装配件中的抽象角色名 |
| `construction_kind` | 必须与全部实际实例一致 |
| `instance_count` | 该角色真实展开数；装配变化后必须重算 |
| `used_layers` | 实际使用的 `COL/MASS/MID/ROUTE/PROP/FX…` |
| `used_design_roles` | 实际承担的轮廓、结构、导航、状态等职责 |
| `shape_family` | 所需几何家族，如 `box/cylinder/wedge/plate/ring` |
| `component_ref/component_name` | 候选或已验证组件；未查询时必须为 `null` |
| `evidence_status` | `unresolved/catalog_candidate/verified_writable` |
| `evidence_source` | 实际查询、目录记录或当前仍未查询的说明 |
| `pivot_and_scale_notes` | 原生边界、枢轴、旋转、允许缩放和精度限制 |
| `collision_policy` | `visual_only/continuous_proxy/gameplay_native/trigger_only/not_applicable` |
| `shadow_policy` | `off/focal/review/required/not_applicable` |
| `material_slots` | 该角色实际需要的主题材质槽；可见角色至少一项 |
| `substitution_notes` | 替换组件时必须保持的形状、接口、职责与性能约束 |

`instance_count/used_layers/used_design_roles` 由真实展开结果反算，不能手改成更好看的数字。脚本会拒绝漏角色、多余角色、同一角色跨多种构成来源、数量漂移、构成来源漂移，以及碰撞代理被标成纯视觉件。

## 三个证据阶段

### `unresolved`

- 没有当前版本查询结果；`component_ref/component_name` 必须为 `null`。
- 仍可完成空间和装配设计，但设计总账的 `component_evidence` 保持 `planned`。
- 记录所需形状、枢轴、缩放、碰撞与材质条件，便于一次批量查询所有角色。

### `catalog_candidate`

- 已找到一个目录候选，填写引用、名称和查询来源。
- 只证明目录线索匹配；账号 UI 是否可见、地图是否可写、非均匀缩放、碰撞和枢轴仍可能未知。
- 候选可以用于写入预览中的“待核对资源”，不能计为部署批准。

### `verified_writable`

- 在本次游戏版本和设备状态下已取得可写证据，并记录组件引用、名称与来源。
- `predeploy` 要求所有实际角色均为该状态，同时 `device_status=writable` 且 `game_version` 具体。
- 脚本通过仍不证明旋转、缩放、材质、碰撞和性能在地图里正确；这些由轴向转换、编辑模式与试玩验收负责。

## 基础件复用原则

同一个基础方块可以绑定多个抽象角色。例如墙板、梁、台阶侧脸和地标大体块可共用一个组件引用，但绑定条目仍分开，因为它们的尺寸范围、碰撞、阴影、材质槽和设计职责不同。反过来，一个抽象角色若需要两种不兼容枢轴或组件，则先在装配计划中拆成两个角色，不能在绑定账里藏条件分支。

选择候选时按以下顺序比较：

1. 能否形成所需基础形状和比例，不依赖未经验证的负缩放或镜像；
2. 枢轴能否稳定连接装配接口，批量旋转后是否仍对齐；
3. 可见表皮、连续碰撞代理和玩法设备是否能分离；
4. 材质/颜色能否承担主题语义，不靠每件独立逻辑换色；
5. 高频实例能否关闭不必要物理、投影和动态更新；
6. 替代组件是否保持原设计职责、包围盒与性能预算。

不要因为某个大型 Prefab 一次替代很多基础件，就自动视为更优。它只有在轮廓、接口、材质、碰撞、相机和性能都符合时才可替换；替换后重新展开、重算密度与关键视图，不沿用旧数量。

## 与类型种子联合使用

十七类种子可以一次生成六份相互引用的概念产物：

```bash
python3 scripts/generate_type_assembly_seed.py --type defense_strategy \
  --output assembly-seed.json \
  --design-output design-seed.json \
  --density-output density-seed.json \
  --binding-output component-binding-seed.json \
  --theme-output theme-adaptation-seed.json \
  --performance-output performance-seed.json
```

组件绑定种子会完整列出全部抽象角色，但全部保持 `unresolved`。先按真实主题重构装配族，再重新生成绑定模板；否则已经删除或新增的角色会与旧模板漂移。完成目录查询后逐项填写，再运行：

```bash
python3 scripts/audit_component_binding.py \
  assembly-plan.json component-binding.json --json
```

## 部署前门槛

绑定审计至少回答：

1. 每个展开角色是否恰好有一条绑定，数量、层级和职责是否仍一致；
2. 设计角色是否与组件构成来源一致，碰撞代理是否使用连续代理策略；
3. 高频可见基础件是否明确材质、碰撞和投影政策；
4. 当前版本、设备可写状态、引用、名称和证据来源是否齐全；
5. 所有候选是否已升级为实际 `verified_writable`，而非用旧缓存或名字猜测；
6. 装配、密度或主题发生变化后是否重新生成并复核本账。

只有这些条件成立，设计总账的 `component_evidence` 才能根据本次真实查询结果改为 `passed`。绑定审计器不能替操作者伪造这个状态，也不能授权地图写入。
