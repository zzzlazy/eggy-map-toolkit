# 参数化装配与千件级坐标展开

本文件把装配配方变成可部署前展开的空间计划。参数化不是把“一排墙”伪装成完成度，而是让每个重复实例拥有确定位置、接口、变体、职责和唯一名称。公式可以压缩设计文档；最终写入预览仍必须展开为真实实例数与明确组件清单。

这里的数学只描述设计坐标，不证明游戏当前版本的轴向、欧拉角顺序、组件枢轴或缩放语义。先检查现有地图和组件目录，再把设计基向量转换成实际 `position/rotation/scale`。

## 1. 用局部基向量隔离地图轴向

每个装配体采用右手局部坐标：

- `u`：装配体右方；
- `v`：装配体上方；
- `f`：装配体出口/前进方向；
- `O`：装配体局部原点在世界中的位置；
- `U,V,F`：某个局部件相对原点的坐标。

世界位置按下式计算：

`P_world = O + U·u + V·v + F·f`

`u/v/f` 必须近似单位长度、两两垂直，并满足右手关系。不要只交换两个轴来“镜像”：这会改变手性，可能造成模型翻转、法线或旋转错误。镜像优先做成明确的 B 变体；负缩放只有当前组件与发布管线实测支持时才用。

## 2. 装配族参数合同

每个装配族先声明：

| 字段 | 内容 |
|---|---|
| `family` | 稳定名称，例如 `WALL_BAY`、`ARENA_SECTOR` |
| `W/H/D` | 标称宽、高、深；使用当前地图标定单位 |
| `origin` | 底面中心、入口中心或其他明确基准 |
| `entry_port` | 局部位置、朝向、净宽/净高和允许误差 |
| `exit_port` | 与下一实例连接的位置、朝向与净空 |
| `clearance_box` | 玩家、相机、机关扫掠或多人占位不可侵入体积 |
| `pieces` | 局部件角色、形状、局部变换、层和成本职责 |
| `variants` | A/B/C 的保留项、可变项和删加差额 |
| `allowed_layouts` | 可沿直线、折线、圆弧、网格、辐射或只允许独立放置 |
| `interface_owner` | 相邻实例共享支柱、碰撞或收口时由谁计数 |

局部件坐标优先写成参数表达式，例如 `U=-0.42W, V=0.5H, F=0`。表达式只允许已声明参数和基本算术；不要把条件、随机或组件属性藏在坐标字符串里。

## 3. 接口先于复制

相邻实例 `A → B` 至少校验：

- A 的出口世界位置与 B 的入口世界位置误差不超过声明的 `ε_pos`；
- 两接口的前进方向夹角不超过 `ε_dir`，除非接口本身声明转角；
- 地面高差、坡度、落点长度和净宽符合当前玩家/载具标定；
- 碰撞代理连续但不重复叠两层；
- 表皮接缝无漏光、穿插闪烁、意外台阶或卡缝；
- 护栏、路线边和灯带在连接处保持语义连续；
- 机关、门体、玩家和相机的净空盒没有互相侵入。

接口误差必须以设计单位记录，不写“基本对齐”。美术表皮可用盖板、法兰、岩片或植被收缝，但不能用它掩盖真实通行断层。

## 4. 六种布局生成器

### 4.1 直线序列

适合竞速走廊、厂房跨、街墙、桥与管线。第 `i` 个实例：

`O_i = O_0 + i·S·f`

其中 `S` 是接口步长，不必等于模型深度。用 `A,A,B,A,C,B` 等确定序列分配变体；不要逐件调用无种子随机。

直线并不等于单调。每隔若干跨改变整体高度、侧面开口、中层结构、视线或动作，但在转折实例处显式切换基向量，不能让接缝自动漂移。

### 4.2 折线/中心线站点

适合峡谷、山路、长章节和不规则街区。先定义中心线站点 `Q_0…Q_n`，每段切向作为 `f`，用稳定上向 `v` 计算 `u`。急转角使用专门 `CORNER/CLIFF_TURN/WALL_CORNER` 装配族，不让两个直线段直接互相穿插。

对每个站点记录累计路程、地面高程、切向、坡度、路线净宽和远期可见地标。站点间距来自装配接口和动作节拍，不从总长度平均切分。

展开器的 `polyline` 输入使用世界坐标 `points` 作为**已经定距的装配站点**，并用 `up` 作为上向提示；每站朝向下一站，末站沿用入向。它不会自动把任意折线等距采样，也不会替急转角生成收口，因此设计者必须先按接口步长布点，并把急转、岔口和跨章门槛拆成独立装配族。相邻点重合、前进方向与上向平行都会被拒绝。

### 4.3 圆弧与环形序列

适合竞技场、环形赛道、塔环、能源核心和观景环。给定圆心 `C`、半径 `R`、上向 `v`、初始径向 `a`，令 `b=a×v`：

`r(θ)=a·cosθ+b·sinθ`

`O(θ)=C+R·r(θ)+h(θ)·v`

`u=r(θ), f=-a·sinθ+b·cosθ`

扇区角度必须整除或显式处理尾缝；最后一扇区既要检查视觉闭环，也要检查碰撞、出生公平和逆行/套圈。若环上有缺口、入口或终局收缩，单独建变体，不用删除随机扇区。

### 4.4 网格与建筑阵列

适合厂房柱网、货架、城市街区、农田和经营站点：

`O_(i,j)=O_0+i·S_u·u+j·S_f·f`

先区分结构网格与玩家路线。柱网可以规则，墙、门、工作站和街口根据拓扑占用网格；不要先填满再从装饰中硬挖通路。相邻格共享墙或碰撞时指定唯一所有者，避免两面重叠墙闪烁。

### 4.5 中心辐射

适合社交中心、任务大厅、章节选择和资源热点。以中心 `C` 和若干角度 `θ_k` 放置入口地标；每个分支的局部 `f` 指向离开中心的方向，返回门架反向。

各分支可以有不同表皮，但中心接口、返回语言和行进成本要明确。社交图允许距离不完全公平，争夺图则必须实测从各出生点到分支目标的时间与视线。

展开器的 `radial` 输入由 `center/radius/up/radial0/count/start_angle_deg/step_angle_deg` 确定位置，`facing=outward|inward` 决定接口朝外还是朝心，`rise_per_step` 只用于明确的层级变化。它和 `arc` 的区别在朝向：`arc` 的 `f` 沿圆周切线，`radial` 的 `f` 沿半径；不能用错后再靠模型欧拉角补偿。

### 4.6 垂直堆叠与螺旋

适合攀爬塔、矿井、立体生存和多层科幻舱。每层记录 `O_k`、地面高程、上/下层对应、掉落回收和相机遮挡。螺旋可用圆弧公式叠加 `h(θ)`，但头顶净空、内外侧真实路程和长坠落等待必须单独校验。

不要依靠“每层加固定高度”假设玩家一定看得见下一层；每个转折需恢复上方目标、当前落点和掉落去向中的至少两项。

展开器的 `vertical` 输入由 `origin/basis/count/step_v` 建立楼层序列，可用 `step_u/step_f` 做逐层偏移，并用 `twist_deg_per_step` 旋转每层局部朝向；`step_v` 不得为零。绕固定圆心的真正螺旋仍使用带 `rise_per_step` 的 `arc`，不要把同一原点只旋转不抬升的重叠件冒充塔体。

## 5. 变体是受控差异

每个装配族将局部件分为：

- `LOCKED`：碰撞面、接口、门洞、必要护栏和路线净空，视觉变体不得改变；
- `SWAPPABLE`：表皮、支撑样式、窗洞、植被簇、材质或色阶；
- `OPTIONAL`：近景微件、破损、灯、标牌和收口；
- `STATEFUL`：会显隐、移动、换色或表达状态的件，不能与纯静态变体混算。

使用确定的变体序列，并设置相邻约束，例如 C 破损跨不能连续两次、同一近景窗形不连续超过三跨、危险色变体只出现在真实危险段。变化要追随转角、功能、状态与镜头，不逐件随机抖动。

有机地貌可给表皮位置、尺度和倾斜增加有界扰动，但 `LOCKED` 碰撞、落点边、接口和路线色保持稳定。记录扰动种子或显式结果，保证再次展开不会整体变化。

## 6. 多尺度展开顺序

参数化布局按四层生成，不在一条循环里平均撒所有物件：

1. **宏观**：章节包围盒、中心线、竞技场、建筑体块、远景主轮廓；
2. **中层**：墙跨、梁柱、桥跨、屋架、岩壁段、工作站和景观簇；
3. **接触与信息**：碰撞代理、平台侧脸、护栏、落点边、路线灯、输入/输出框；
4. **表面与氛围**：分缝、法兰、枝叶、碎石、标签、灯和粒子。

先完成上一层的包围盒、接口和数量账本，再生成下一层。后层可以依附前层，但不能反过来决定关键路径或碰撞。

## 7. 按拓扑展开的参考种子

这些是原创结构示例，不是固定配额：

| 地图骨架 | 参数化组合 | 适合的类型 | 先验证 |
|---|---|---|---|
| 封闭生产走廊 | 两侧 `WALL_BAY` 直线/折线＋顶部屋架网格＋周期 `PIPE_RACK`＋工作站节点 | 竞速、章节、经营 | 包裹、转角、净高、管线来源/去向 |
| 环形风暴场 | `ARENA_SECTOR × N`＋中心危险环＋外侧观战框景 | 生存、积分 | 扇区闭环、出生时间、永久安全角、终局收缩 |
| 中心节庆岛 | 中心地标＋辐射门架＋各分支 `PHOTO_ACTIVITY_STAGE`＋返回接口 | 社交、探索 | 中心可见、换景回流、多人镜头和占用 |
| 垂直遗迹塔 | 楼层体块＋螺旋桥/楼梯＋每层门架＋外侧远景轮廓 | 攀爬、章节、叙事 | 头顶遮挡、坠落恢复、内外侧路程、下一层目标 |
| 山谷中心线 | 折线站点＋两侧 `CLIFF_SEGMENT`＋桥/洞口转折族＋地貌簇 | 竞速、长挑战、探索 | 路线与岩壁间距、镜头、漏缝、远期地标 |
| 工作站网络 | 建筑网格＋输入/加工/输出站＋运输线＋升级变体 | 经营、合作 | 资源流、操作净空、共享墙、满仓和重置 |

一张地图可以组合两个生成器，例如“直线厂房进入圆形质检厅”，但交界必须使用独立 `HANDOFF` 装配族并单独计数。

### 十七类主类型的布局路由

下表只决定第一版空间编译路径，不替代相应类型的循环、状态和基础件套件。`explicit` 应只承担独立地标、门槛、急转、特殊接口和少量不规则节点，不能让本可参数化的数百件重新退化成手写坐标。

| 主类型 | 优先布局组合 | 主要装配单位 | 必须另建的接口 |
|---|---|---|---|
| `short_race` | `polyline + linear` | 路线跨、壳体跨 | 急转、超车袋、终点框 |
| `chapter_challenge` | `polyline + vertical + explicit` | 章节场景包、交通跨 | 跨章门槛、检查点、尺度转换 |
| `mechanism_puzzle` | `grid + explicit` | 谜题房间、共享交通 | 观察位、重置口、锁定出口 |
| `cooperative` | 两条 `polyline/linear + explicit` | 角色侧结构、交接单元 | 因果反馈、会合、缺员旁路 |
| `narrative_exploration` | `radial + polyline + vertical` | 地标场景、过渡路线 | 揭示镜头、返回边、状态换景 |
| `social_showcase` | `radial + arc` | 中心地标、社交目的地 | 到达、活动、离开/回流口 |
| `survival` | `arc + radial` | 竞技扇区、外壳跨 | 出生保护、观战、终局收缩 |
| `score_contest` | `radial + arc + explicit` | 出生扇区、资源节点、热点 | 得分口、侧翼、追赶入口 |
| `management_simulation` | `grid + polyline` | 生产单元、站点行、运输线 | 输入/输出、容量、扩建与装卸 |
| `rhythm_performance` | `linear/arc + explicit` | 轨道跨、舞台壳体 | 倒计时、判定线、结果舞台 |
| `combat_boss` | `arc + radial` | 战斗扇区、Boss 外观骨架 | 弱点、复活、安全口、结果框 |
| `defense_strategy` | `polyline + grid` | 路径跨、建设槽 | 源点、漏怪口、核心要塞 |
| `stealth_infiltration` | `grid + polyline + explicit` | 潜行单元、遮蔽簇 | 观察位、目标提交、撤离口 |
| `turn_based_strategy` | `grid + radial` | 棋盘格、行动台 | 当前行动者、解析与终局舞台 |
| `sports_match` | `grid + linear + arc` | 场地扇区、看台跨 | 球门、出界、死球重启 |
| `sandbox_creation` | `grid + radial` | 建造区、目录台 | 保存、撤销、测试、退出 |
| `social_deduction` | `radial + grid + polyline` | 功能房、会议中心、通道 | 私密简报、报告、投票、淘汰后路线 |

混合地图先按主类型建立上述骨架，再只在命名节拍内加入次类型所需的局部布局；不要把两行完整拼成互不相干的两张地图。

## 8. 唯一命名与分块

每个展开件使用：

`<MAP>_<ZONE>_<FAMILY>_<PLACEMENT>_<VARIANT>_<PIECE>`

例如 `MWF_ASM_WALL_007_B_PANEL_03`。编号按放置实例稳定，不因删掉某个可选局部件而给后续实例全部重排。名称必须能反查区域、装配族、放置编号、变体与局部件。

千件级清单按空间视区或章节分块，而不是按模型类型分成“所有方块/所有灯”。每块声明：包围盒、相邻接口、展开数、共享件差额、成本角色和人工抽查点。这样可局部替换、降级和定位接缝问题。

## 9. 从公式到写入清单

写入前完成以下门检：

1. 固定世界轴、地图边界、装配基向量和组件枢轴证据；
2. 解析所有参数与变体，禁止保留 `若干/N 组/重复到终点`；
3. 生成每个局部件的世界位置、世界朝向/基向量、目标尺寸和唯一名称；
4. 扣除共享接口、变体删件、不可见背面与合并输出，并记录净差额；
5. 校验接口位置/方向、碰撞连续、净空、边界与机关扫掠；
6. 用密度审计器核对装配、区域、分层和声明总数；
7. 抽查每个装配族的首个、中间、转角和最后实例，不能只看第一个；
8. 转换为当前版本可写组件属性；未经证明的欧拉角、缩放、碰撞或镜像保持未知，不猜值。

成品还要把空间承诺写成 `quality_contract`，由跨账本门禁用每件的世界基向量与目标尺寸计算真实轴对齐包围盒。它至少声明全图 `build_bounds`、最低可见世界占比、必需完成层与设计职责、与必需职责一一对应的最低空间实例数、所有可见区域的边界/最低可见实例/最低装配族数/最低三轴跨度/必需职责及最低职责实例数，以及确实需要完全统一重复的装配族和理由。区域名同时写入设计总账 `theme.world_shells[].assembly_zones`；准备部署时两边必须双向覆盖。这样“公式展开了两千件”仍不能掩盖全部堆在原点、越过地图边界、漏掉某一壳体、只有一个挂名轮廓件、没有路线/结构价值或只复制一个变体。

参数公式通过不代表画面正确。最终仍要在编辑模式检查接缝、枢轴、遮挡、碰撞和 A/B/C 变体节奏，并在目标设备测试峰值视区。

## 10. 机器可读展开器

数百件以上的参数化方案写成临时 JSON，并运行：

```bash
python3 scripts/expand_assembly_plan.py plan.json --output expanded.json
python3 scripts/expand_assembly_plan.py plan.json --summary-only
python3 scripts/expand_assembly_plan.py --example
python3 scripts/expand_assembly_plan.py --example-layout polyline
python3 scripts/generate_type_assembly_seed.py --all-summary
python3 scripts/generate_type_assembly_seed.py --type cooperative \
  --output assembly-seed.json \
  --density-output density-seed.json \
  --design-output design-seed.json \
  --binding-output component-binding-seed.json \
  --theme-output theme-adaptation-seed.json \
  --performance-output performance-seed.json
python3 scripts/audit_build_bundle.py design-seed.json assembly-seed.json \
  --density-plan density-seed.json --json
python3 scripts/audit_theme_adaptation.py design-seed.json assembly-seed.json \
  theme-adaptation-seed.json --json
python3 scripts/audit_performance_plan.py design-seed.json assembly-seed.json \
  performance-seed.json --json
```

`generate_type_assembly_seed.py` 为十七种主类型各提供一个**基础件主导的设计坐标种子**：至少三个装配族、三个可见区域、两种布局生成器，并真实展开到所声明空间档的数量下限。它用于防止概念方案停在百件灰盒，也用于展示如何把房壳、路线、节点、竞技扇区、地标和格单元组织成千件级世界；输出中的 `seed_status/not_deployable_until/seed_acceptance` 明确记录其边界。`--density-output` 从真实展开实例反算装配族、区域、层级、总数和抽象资产词汇；灰盒数采用实际连续碰撞代理数，不按百分比猜测。`--design-output` 同时生成一个 `maturity=concept` 的设计总账，把主类型、密度证据、装配族和世界壳体区域与另两份账对齐。`--binding-output` 完整列出所有实际 `component_role` 的组件绑定模板，但全部保持 `unresolved`；填写当前版本证据前读取 [组件角色绑定与可写证据](component-binding-audit.md)。`--theme-output` 再按真实装配族、区域、变体和世界壳体视角生成题材适配模板，创意字段同样保持 `unresolved`；填写方法见 [题材适配账与视觉证据](theme-adaptation-audit.md)。`--performance-output` 建立一个全局最坏状态和逐区最密视区，从展开结果反算成本候选上限，但全部保持 `unmeasured`；填写方法见 [性能与降级预算](performance-and-budget.md)。设计/装配/密度三账应立即通过跨账本算术检查，另外三表只证明角色、题材和性能视区没有漏项，所有实际审计状态仍保持 `planned`。

这套种子不含组件 EID、玩法机关、最终地图边界、当前版本轴向转换或成品 `quality_contract`，所以必须根据主题和节拍重构，不能改个前缀就部署，也不能用它的数量通过视觉验收。种子的密度档只是该类型常见首个连续场域起点；实际世界若有物理分离场景、长章节或开放尺度，仍须先按空间证据升级到 `multi_scene/long_world`，再增加壳体、分区和有效实例。`--all-summary` 用来比较类型覆盖与展开规模，`--self-test` 会逐类验证密度下限、装配族/区域/布局覆盖、基础件可见占比、设计/装配/密度三账一致性、组件角色绑定完整覆盖、题材适配族/区域未解析边界，以及全局与逐区性能视图完整且未伪造实测。

输入结构：

- 根级：`schema_version=1`、`name_prefix`、可选 `expected_total/max_expanded`、`construction_strategy`、`quality_contract`、`families` 和 `placements`；成品的 `construction_strategy` 用 `primitive_led/hybrid/asset_led` 声明构成方式、`primitive_visible_share_min` 与理由；
- 成品的 `quality_contract` 包含 `build_bounds/minimum_world_visible_share/required_completion_layers/required_design_roles/minimum_design_role_counts/zone_targets/uniform_family_exceptions/rationale`。每个区域目标包含 `bounds/minimum_world_visible_instances/minimum_family_count/minimum_extent/required_design_roles/minimum_design_role_counts`，可另列 `required_layers`；同级最低职责数字典的键必须与必需职责完全一致、每项至少为 1，且不接受 `COLLISION/LOGIC` 充当空间质量职责。所有界限都是设计世界坐标，不是未经验证的游戏轴向；
- 装配族：`name`、数值 `parameters`、`variants`，以及每个局部件的 `name/component_role/layer/cost_role/construction_kind/design_roles/local_position/local_size`；`construction_kind` 必须是 `BASIC_PRIMITIVE/THEME_ASSET/GAMEPLAY_DEVICE/COLLISION_PROXY/FX_LIGHT_AUDIO/LOGIC_ONLY` 之一，碰撞代理与纯逻辑件分别使用对应成本角色；
- `design_roles` 至少一项，允许 `SILHOUETTE/ENCLOSURE/STRUCTURE/CONTACT/NAVIGATION/DANGER/INTERACTION/GOAL/STATE_FEEDBACK/SCALE_REFERENCE/SURFACE_DETAIL/ATMOSPHERE/COLLISION/LOGIC`。碰撞代理必须含 `COLLISION`，纯逻辑件必须含 `LOGIC`，可见基础件、主题资产和视听件至少含一个可见职责；一件可同时承担两到三个真实职责，但不能用泛化标签掩盖无效复制；
- 局部坐标与尺寸可以使用参数、数字和 `+ - * /`，不执行函数、属性、索引或任意代码；
- 局部件可用 `include_variants/exclude_variants` 控制受控删件，用 `local_basis` 指定相对朝向；
- 放置器支持 `linear/polyline/grid/arc/radial/vertical/explicit`。`polyline` 使用已定距站点，`radial` 区分朝外/朝心，`vertical` 支持逐层偏移与扭转；急转、岔口、门槛和特殊接口仍使用独立装配族。字段不确定时先运行 `--example-layout <布局名>`，示例明确标为设计坐标种子，不带成品质量合同；
- 每个放置器声明区域、装配族、确定变体序列与参数覆盖；重复世界帧、左手/非正交基、非法表达式、未知变体、重复名称、非正尺寸和异常展开量会被拒绝。

输出为摘要与完全展开的 `instances`。每件包含唯一名称、区域、装配族、放置编号、变体、局部件、组件角色、层、成本角色、构成来源、设计职责、世界位置、世界基向量和局部目标尺寸；摘要同时给出六类构成来源与各设计职责的展开数。`audit_build_bundle.py` 再据此核验质量合同，拒绝同构成类别中位置/朝向/尺寸完全相同的空间件，并检查全图与分区包围盒、层、职责、可见占比、空间跨度、装配族覆盖和重复变体。脚本故意不输出游戏欧拉角、缩放或组件属性：这些必须在当前版本组件目录和现有地图轴向核对后，由实施步骤转换。

`expanded.json` 是临时设计产物，不放入技能目录，也不直接写地图。先抽查世界基向量和转角，再把展开摘要转录到密度账本，用 `audit_density_plan.py` 做区域/分层计数对账；二者通过仍不替代组件能力、碰撞与编辑模式验收。
