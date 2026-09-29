# 全类型设计计划审计

`scripts/audit_design_plan.py` 检查地图设计是否跨层闭合：体验契约、拓扑、节拍、主题、装配预算、类型专项合同、参考证据、试玩矩阵与其他审计状态。它不评价文案是否优美，也不证明组件可写、碰撞正确或实际好玩；这些仍由目录证据、专项脚本和试玩完成。

## 两个轴：工作阶段与成熟度

- `stage=design`：允许指标、场景与专项审计保持 `planned`，用于概念、灰盒和成品方案迭代；
- `stage=predeploy`：必须同时 `maturity=final`，目标人数与专项场景不能仍为 planned，阻塞未知项必须解决；
- `maturity=concept`：体验、主循环、拓扑、初步节拍、世界语法与预计预算已明确；
- `maturity=graybox`：关键尺寸、失败恢复、类型闭环和节拍耗时已有可玩验证；
- `maturity=final`：空间体量、中层结构、表皮/氛围、性能职责和实施清单已经补齐。

不要通过把 `stage` 提前写成 `predeploy` 获得质量。脚本只验证声明与结构；同一工作流仍需实际运行密度、状态与展开审计，并把真实结果写回计划。

## 类型标识

| 标识 | 中文类型 |
|---|---|
| `short_race` | 短竞速 |
| `chapter_challenge` | 章节挑战 |
| `mechanism_puzzle` | 机制/解谜 |
| `cooperative` | 双人/多人合作 |
| `narrative_exploration` | 叙事/探索 |
| `survival` | 生存/淘汰 |
| `score_contest` | 积分/争夺 |
| `social_showcase` | 休闲/社交/展示 |
| `management_simulation` | 经营/模拟/建造 |
| `rhythm_performance` | 纯音游/节奏演出 |
| `combat_boss` | Boss/PvE 战斗 |
| `defense_strategy` | 防守/塔防 |
| `stealth_infiltration` | 潜行/渗透 |
| `turn_based_strategy` | 回合策略/棋盘卡牌 |
| `sports_match` | 体育对局 |
| `sandbox_creation` | 创造沙盒 |
| `social_deduction` | 阵营推理/社交推理 |

一个计划必须有一个 `primary_type`，最多一个不同的 `secondary_type`。选择次类型时同时填写 `hybrid`：组合方式、次类型作用、命名节拍范围、强制时间与最长停摆、权威终局、入口/出口、冲突优先级、同时失败、状态交接、清理所有者、共享视觉语法和不可用时的降级。声明次类型意味着承担该类型的完整专项合同与试玩项；若只是一个机关、题材或短暂情绪，应改成主类型内部职责或修饰器。

## 根级结构

```json
{
  "schema_version": 1,
  "stage": "design",
  "maturity": "concept",
  "primary_type": "short_race",
  "secondary_type": null,
  "experience": {},
  "topology": {},
  "beats": [],
  "theme": {},
  "assembly_budget": {},
  "complexity_budget": {},
  "type_modules": {},
  "hybrid": null,
  "modifiers": [],
  "modifier_contracts": {},
  "modifier_interactions": [],
  "evidence": {},
  "verification": {},
  "audits": {}
}
```

完整字段模板由脚本生成，不在文档复制一份容易失效的长 JSON。`--example` 输出 `stage=design/maturity=concept`，所有试玩与专项审计保持 `planned`，组件能力未知项保持阻塞；它不会伪造 `tested/passed` 证据：

```bash
python3 scripts/audit_design_plan.py --example --type short_race
python3 scripts/audit_design_plan.py --example --type cooperative
python3 scripts/audit_design_plan.py --example --type management_simulation
python3 scripts/audit_design_plan.py --example --type rhythm_performance
python3 scripts/audit_design_plan.py --example --type combat_boss
python3 scripts/audit_design_plan.py --example --type sandbox_creation
python3 scripts/audit_design_plan.py --example --type social_deduction
python3 scripts/audit_design_plan.py --example --type defense_strategy --secondary management_simulation --hybrid-mode phase_shift
python3 scripts/audit_design_plan.py --example --type sandbox_creation --secondary social_showcase --hybrid-mode optional_branch
python3 scripts/audit_design_plan.py --example --type short_race --modifier vehicles
python3 scripts/audit_design_plan.py --example --type chapter_challenge --modifier destructible_world
python3 scripts/audit_design_plan.py plan.json --json
```

`--example --type` 支持全部十七种标识；再加 `--secondary` 可生成任意不同类型的结构模板，`--hybrid-mode` 可显式选择 `overlay/local_station/optional_branch/phase_shift`，再加 `--modifier` 可生成十种结构修饰器之一的合同与专项试玩占位。省略组合方式时只采用模式库中登记的建议值，未登记组合退回局部站点；实际方案应显式选择，并让研究证据包核对完全相同的有向主次与组合方式。任意组合能通过结构审计不等于设计上值得混合，先按 [混合类型地图模式库](hybrid-map-patterns.md) 与 [专项混合类型模式库](specialized-hybrid-patterns.md) 判断主次；自动模板只提供一个有边界的局部站点或已登记的常见组合模式。`rhythm_performance` 已拥有完整节奏循环，不能再叠加 `rhythm` 修饰器；后者只用于改变其他主循环的节拍条件。十七种主类型各有不同的原创世界句、记忆剪影、基础形状、装配族和世界壳体示例，用来避免模板全部退化为同一工厂换皮；真正立项仍按 [地图概念合成与创意分化](concept-synthesis.md) 生成并比较候选，再按 [场所形态、世界壳体与关键镜头](world-shells-and-keyframes.md) 重写真实场景。模板按类型给出约 1,000–2,600 件的不同展开种子，混合模板再为次循环增加一个局部展开种子，目的是防止所有类型退化成同一百件灰盒；它们只展示字段和对账方式，不是推荐主题、硬配额、性能上限、已通过审计或已经试玩的地图。

## `hybrid` 交接合同

`secondary_scope` 必须逐项引用 `beats[].name`，并且只能引用 `secondary`、`handoff` 或确实共享的节拍；所有标为 `secondary/handoff` 的节拍都必须纳入范围。这样审计器能拒绝“次类型存在于全图”的空声明以及偷偷占用主节拍的组合。

`time_budget` 包含：

- `forced_secondary_seconds_max`：目标流程中玩家无法绕过的次循环总上限；可选支线必须为 `0`；
- `continuous_primary_pause_seconds_max`：主循环被连续冻结的最长时间，不能大于前项；
- `measurement`：从哪个入口锁到哪个清理提交计时、在哪个设备与人数下测量。

其余必填字段是 `entry_condition`、`exit_condition`、`simultaneous_failure` 与 `cleanup_owner`。入口必须幂等；出口覆盖完成、失败、放弃或缺员；同时失败只允许一个终局裁决；清理所有者负责计时器、占用、对象、临时 UI/镜头和代次。`state_handoff` 说明需要快照、提交与恢复的状态，`fallback` 则保证次循环不可用时主终局仍闭合。

只要存在次类型，试玩矩阵还会自动要求四项边界指标：强制次循环时间、主循环最长停摆、交接恢复时间、残留数量；以及重复进入、放弃/超时、主次同时失败、降级和第二次进入五个场景。这些项目不能被主类型与次类型各自单测替代。

## 共用合同

### `experience`

必须包含受众、`[最少,最多]` 人数、`[最短,最长]` 目标秒数、1–3 个主要动词、记忆画面、成功定义、失败恢复、情绪曲线和主题承诺。社交图也要定义一次有效会话循环与退出，不用传统通关率代替。

### `topology`

支持：`linear_chain/branch_and_rejoin/loop_track/hub_and_spoke/arena/open_network/vertical_layers`。声明入口、终端/退出、恢复节点、带角色的节点和带 `critical/optional/recovery/return/handoff` 类型的有向边。

审计器拒绝：未知节点、重复边、从入口不可达的孤岛，以及无法到达任何终端/退出的非终端节点。图可含循环，但循环必须存在离开路径。

### `beats`

概念至少 3 拍，灰盒/成品至少 4 拍。每拍包含名称、`primary/secondary/handoff/shared` 所有者、可见信息、玩家动作、后果和反馈；灰盒以后还要给目标秒数。没有次类型时不能出现 secondary/handoff；有次类型时至少有一拍真正属于次循环或交接。

### `theme`

必须包含世界句、记忆剪影、2–4 个比例词、基础形状、装配族、材质节奏、语义色、世界状态变化、禁用清单和 `world_shells`。语义色至少覆盖环境、结构、路线、交互和目标；危险或阵营仅在适用时增加。

每个 `world_shells[]` 必须声明：唯一名称、所覆盖的拓扑节点与节拍、至少一个 `assembly_zones` 真实装配区域、可画出的剪影、包裹策略、`foreground/midground/background` 三层景深、至少两个比例锚点、至少两个来自全局主题卡的装配族、至少两个状态变体、进入/离开转场，以及至少两个真实相机复核视角。每个 `review_views[]` 使用 `spawn/entry/action/reveal/recovery/return/terminal` 之一，并列出相机意图和至少三个必须同时出现的信息。

设计总账审计器拒绝未知节点/节拍/装配族、同一节拍重复归属、节点或节拍漏场景、覆盖入口却没有 `spawn/entry` 镜头、覆盖终端却没有 `terminal` 镜头。`micro_space/themed_short` 至少一个壳体，`multi_scene` 至少两个，`long_world` 至少三个。跨账本审计再要求 `assembly_zones` 与装配计划 `quality_contract.zone_targets` 双向覆盖，并要求主题与各壳体承诺的装配族以同名可见实例实际出现在对应区域。结构检查不能判断文字是否对应真实画面；设计方法与人工复核见 [场所形态、世界壳体与关键镜头](world-shells-and-keyframes.md)。

### `assembly_budget`

记录密度档、密度档选择证据、灰盒数、规划展开总数、资产词汇数和 `COL/MASS/MID/ROUTE/MECH/PROP/FX/LOGIC/SAFE` 分层计数；分层之和必须等于总数，成品总数必须高于灰盒数。密度档必须在知道真实空间合同后、计算现有数量前选择：

| `density_profile` | 审计下限 | 适用空间合同 |
|---|---:|---|
| `micro_space` | 300 | 单个小房间/小场域、单规则实验或明确刻意极简，不宣称大世界 |
| `themed_short` | 800 | 一个连续主题场域、约两分钟短图或同尺度短章节 |
| `multi_scene` | 2000 | 两个以上物理分离场景、明显尺度转换或各自需要壳体的章节 |
| `long_world` | 5000 | 长章节、开放世界或高密度连续世界 |

下限不是要求刷件，区间上限也不是限制；它只阻止把空间合同未完成的百件灰盒叫作成品。`density_profile_evidence` 要写可核对的场景数、连续空间、尺度转换、关键镜头或可玩范围，不能写“因为当前只有这些组件”。成品若低于所选档位下限，`assembly_budget.low_count_exception` 必须是结构化对象，而不是一句理由：

```json
{
  "density_profile": "micro_space",
  "density_profile_evidence": "一个可从出生与反向视角完整观察的封闭小房间",
  "low_count_exception": {
    "mode": "micro_space | deliberate_minimalism | large_asset_led",
    "scope_evidence": "为何真实空间尺度或大型资产能支撑低实例数",
    "layer_coverage": [
      {"layer": "MASS", "handled_by": "实际承担宏观体量的件或资产"},
      {"layer": "MID", "handled_by": "实际承担中层结构的件或资产"}
    ],
    "visual_review_views": ["出生首屏", "反向或终点复核视角"],
    "tradeoff": "主动舍弃了什么，以及为何不会伪装成高密度世界"
  }
}
```

`layer_coverage` 必须至少覆盖 `MASS` 和 `MID`，人工复核视角至少两个。`micro_space` 例外只允许配合 `density_profile=micro_space`；较大空间不能借它假装缩小。`large_asset_led` 还需与装配计划的资产主导构成策略一致。达到所选档位下限后不得保留过期例外。总设计账与密度账必须使用完全相同的档位、选择证据和例外；此处只做总账，装配公式仍交给密度审计器。

### `complexity_budget`

成品计划必须把视觉/物理峰值与状态/触发峰值分开申报：

- `visual`：`visible_peak/collision_peak/shadow_peak/dynamic_peak/transparent_layer_peak/switch_load_peak`；除透明层数外，各组件峰值不得超过规划展开总数；
- `logic`：`persistent_state_count/event_entry_count/active_timer_peak/action_fanout_peak/spawned_object_peak/reset_item_count`；
- `measurement`：分别说明视觉统计方法、逻辑追踪方法和最坏状态；
- `degradation_order`：至少两步，先删除无职责或非焦点成本，再触及玩法反馈、碰撞与主轮廓。

概念/灰盒可暂不提供此表，`maturity=final` 缺失时审计失败。所有数字都可先是设计估计，但 `predeploy` 前必须用目标设备、目标人数和实际状态回填；公共缓存里的批加载单位或 `eca_trigger_count` 不能直接代填峰值。数百件以上或高动态/透明/逻辑方案再用 `scripts/audit_performance_plan.py` 把这些全局峰值与真实展开区域、逐视区候选上限、冷进入/稳定/最坏交互结果和降级步骤对齐，详见 [性能与降级预算](performance-and-budget.md)。

## 十七种专项合同

`type_modules` 只包含主类型和实际次类型。各类型必须回答：

| 类型 | 专项内容 |
|---|---|
| 短竞速 | 冲线规则、流动线、超车/并行、检查点与短复位 |
| 章节挑战 | 至少两章的动作身份、视觉身份、检查点和恢复；难度波形与重进 |
| 机制/解谜 | 课程型或合集型；共享接口；至少两个含局部规则、观察、输入、正误反馈、复位与完成的谜题单元；4–8 步教学/节奏；渐进提示、检查点与整单元重置 |
| 合作 | 至少两个角色及独占动词；至少一次“A 动作—世界变化—B 机会—反馈—恢复” |
| 叙事/探索 | 至少两个地标；统一剧情状态所有者；每个事件写入口锁、控制模式、玩家选择/跳过、至少两项原子状态提交、即时与下一节拍反馈、控制权返回、重新定向和中断恢复；另写回访/重载重建与无文字导航 |
| 生存/淘汰 | 开始/房主/无输入合同、危险教学、阶段调度、升级、安全空间变化、随机兼容、淘汰/观战、平局/无人和整局重置 |
| 积分/争夺 | 得分循环、归属与防重复、热点迁移、公平、反雪球、平局/超时和重置 |
| 社交/展示 | 至少两个地标；活动的到达、参与、离开/返回、占用释放和会话清理 |
| 经营/模拟 | 输入—加工—产出—交付流、货物生命周期、所有权、容量、员工/顾客或自动化、升级选择、可见世界变化、长期目录/终局、持久化和恢复 |
| 纯音游/节奏演出 | 唯一谱面时钟；至少两路提示；判定窗、输入去重、分数/连击、难度曲线、延迟/静音降级与序列重置 |
| Boss/PvE 战斗 | 至少两个阶段及预告/威胁/反制/转换/恢复；伤害权威、至少两种玩家工具、场地恢复、多人缩放、击败/团灭与重试 |
| 防守/塔防 | 核心；至少一条入口—路径—插槽—漏怪—恢复完整路线；至少两波、资源事务、目标/寻路、多人归属与清场 |
| 潜行/渗透 | 至少四个检测状态；传感器规则/预告/反制/恢复、遮蔽、工具、怀疑反馈、目标/撤离、多人信息与警戒清理 |
| 回合策略 | 唯一行动权；至少三个阶段和两种合法动作；局面反馈、资源/所有权、私有信息、解析顺序、超时/掉线、终局/平局/重赛 |
| 体育对局 | 至少两队、比赛对象至少四个状态、至少三个场区；控球/接触、界外重启、进球提交、开球、非法比赛、平局/加时/重置 |
| 创造沙盒 | 创作循环；至少三类目录和四个建造状态；放置校验、权限、预算、撤销/删除、保存/加载、测试/展示与退出清理 |
| 阵营推理 | 至少两个角色/阵营、四个阶段、两类任务/证据和两个胜利谓词；私密分角、报告/会议、每人选票、淘汰权限、掉线、平票和第二局清理 |

这些是结构门，不是固定机制。字段通过不代表合同内容合理；仍需按 [常见类型设计蓝图](type-playbooks.md)、[专项主类型设计蓝图](specialized-type-playbooks.md) 和相关案例评审具体决策。

## 修饰器合同

可选修饰器：`rising_pressure/escort_collection/vehicles/asymmetric_roles/rhythm/horror/vertical_climb/random_variation/cumulative_growth/destructible_world`。每个启用项都在 `modifier_contracts` 中声明作用、前提、反馈、失败恢复、重置、专项指标，以及该修饰器独有的权威、包络、异常与清理字段；详见 [结构修饰器蓝图](modifier-playbooks.md)。修饰器列表与合同键必须完全一致。

审计器分别要求：压力的开始/路径余量/终局优先级；任务对象的身份/生命周期/交付；载具的三档转弯制动镜头标定；非对称角色的信息/能力/反制；节奏的权威时钟/判定窗/延迟；恐怖的可读性/张力/感官降级；垂直层的坠落图/镜头/越序；随机的候选/可解过滤/兼容矩阵；累计成长的输入去重/上限/档位/空间标定；可破坏世界的目标身份/四态、伤害去重、原子销毁、依赖结构、碰撞切换、碎片预算与终局优先级。试玩矩阵自动加入各自的异常场景。

启用两个以上修饰器时，`modifier_interactions` 必须覆盖每一对，写明这两个修饰器、相互作用、冲突优先级、共同最坏状态和清理责任。单独可玩不能替代组合验证。

## 参考、假设与未知项

`evidence.required_reference_axes` 必须精确覆盖本次需要解释的经验轴：所有设计都包含 `primary_loop/world_grammar/spatial_scale`，混合类型再加 `secondary_loop/hybrid_relation`，启用修饰器再加 `modifier`。`hybrid_relation` 只接受同一有向主次、同一组合方式的案例；两端分别有正向案例不能合并填补。可引用的其他轴为 `assembly/performance/failure_boundary`。

`evidence.references` 的每项记录名称、`verified/partial/provisional` 来源状态、用于什么决策、证据边界，以及 `supports[]`。每条支持都把一个轴标成 `verified_positive/partial_positive/boundary_only`；只有前两者能填补该轴，`boundary_only` 只能支持禁用项或反例。未被正向案例填补的必需轴必须逐项写入 `evidence.reference_gaps[]`，包含缺口原因和下一条研究问题。不能用一条笼统 `reference_gap` 掩盖机制、世界语法和尺度证据的不同缺口，也不能把合成模板、组件目录或标题/封面反例当成优秀作品背书。

```json
{
  "evidence": {
    "required_reference_axes": ["primary_loop", "spatial_scale", "world_grammar"],
    "references": [
      {
        "name": "一个已审计案例",
        "status": "partial",
        "used_for": "已直接观察到的一项主循环决策",
        "limits": "未验证恢复与终局",
        "supports": [
          {"axis": "primary_loop", "coverage_status": "partial_positive"}
        ]
      }
    ],
    "reference_gaps": [
      {
        "axis": "world_grammar",
        "reason": "尚无同题材可控镜头与代码装配证据",
        "next_research_question": "哪张案例能同时显示前中远景与基础件构成？"
      },
      {
        "axis": "spatial_scale",
        "reason": "现有案例尺度不同",
        "next_research_question": "哪张同规模地图能验证路线宽度与峰值视区？"
      }
    ]
  }
}
```

至少写一个带验证方法的假设。每个未知项记录内容、影响、验证方式和 `blocking`；`predeploy` 拒绝任何阻塞未知项，但允许保留不会影响安全写入、且已安排人工验收的非阻塞未知项。

## 类型驱动的试玩矩阵

`verification.metrics` 和 `verification.scenarios` 由类型自动决定。所有地图都检查首个目标理解、失败恢复、完成/退出、首次玩家、正常流程和目标人数；脚本再按类型要求专项项，例如：

- 竞速：快/慢玩家、检查点跳过、通关时长与拥堵；
- 解谜：入口可读、错误输入、越序、提示超时、房间重进、检查点恢复、重复重置、规则复述、提示依赖与错因归因；
- 合作：缺员、同时失败、交接越序、主动操作占比和最长等待；
- 生存/争夺：无人/平局、第二局、超时冲突、公平与终局收敛；
- 所有类型：首屏信息优先级与取得控制后的无输入基线；生存再检查阶段提示、随机最坏组合和默认终局不会提前成立；
- 社交：满员占用、走散回流、放弃交互和活动到达率；
- 经营：满容量、并发/中断事务、第二循环、货物丢失/复制、目录与终点不一致、权威保存者缺席、加载重建、首次完整产出、目录可读性与资源一致性。
- 叙事：重复进入、演出中断、跳过、回访、重载恢复、选择后果可见性和归还控制后的重新定向；
- 纯音游：静音、延迟两端、早/晚/重复输入、暂停恢复、第二段序列及时间误差/连击归因；
- Boss/防守：同步伤害、阶段阈值、团灭/重试；空/满防线、并发购买、卡路、漏怪冲突和第二轮波次；
- 潜行/回合：视野边界、并发检测、警戒恢复；非当前输入、超时、掉线、旧动作、平局和第二局；
- 体育/沙盒：同时触球、出界、错误方向、死球、加时；超预算/重叠放置、并发编辑、撤销、保存重载和会话清理；
- 阵营推理：重复分角、同时报告、会议冻结、重复/平票、淘汰者输入、私密动作晚到、角色掉线、第二局及身份泄露率；
- 混合类型：强制次循环时间、主循环最长停摆、交接恢复、残留数量，以及重复进入、放弃/超时、同时失败、降级和第二次进入；
- 修饰器：按 [结构修饰器蓝图](modifier-playbooks.md) 自动加入无输入/极端包络、丢失对象、载具卡死、缺角色、静音/延迟、惊吓中断、最大坠落、随机最坏组合、成长去重、重复命中/依赖坍塌/奖励原子性与第二次进入等对应场景。

每项写 `status=planned/tested/not_applicable`、方法以及目标或实测结果；不适用时说明理由。`predeploy` 不接受 planned。

## 与专项脚本的关系

推荐顺序：

1. 设计阶段运行 `audit_design_plan.py`，发现跨层缺口；
2. 参数化装配运行 `expand_assembly_plan.py`，抽查世界基向量和转角；若尚只有主类型，可先用 `generate_type_assembly_seed.py --type <主类型> --design-output <设计种子> --density-output <密度种子> --binding-output <组件绑定种子> --theme-output <题材适配种子> --performance-output <性能种子>` 生成六份结构对齐的概念起点，再按真实主题、拓扑、边界和节拍重构，不能把种子升级状态冒充实际验证；
3. 把展开数写入密度账本并运行 `audit_density_plan.py`；
4. 用 `audit_theme_adaptation.py <设计总账> <装配计划> --template --output <题材适配账>` 生成逐族、逐区模板；`review` 前消除 `unresolved`，`predeploy` 前让每个族/区域经过命名游玩视角复核，并完成八项全局视觉测试；
5. 用 `audit_component_binding.py <装配计划> --template --output <组件绑定账>` 生成角色绑定模板；设计阶段允许 `unresolved`，但 `predeploy` 必须写明当前游戏版本、可写设备状态，并让每个角色都达到 `verified_writable`；
6. 把真实状态图运行 `audit_state_plan.py`，并让其中的 `primary_type/secondary_type` 与总设计账一致；脚本会按两种类型、混合交接及功能共同生成必测异常矩阵；
7. 运行 `audit_build_bundle.py design-plan.json assembly-plan.json --density-plan density-plan.json`，证明总设计账、展开清单和密度账描述同一份构建；
8. 用 `audit_performance_plan.py <设计总账> <装配计划> --template --output <性能账>` 建立全局最坏状态和逐区最密视区；回填明确版本、设备、画质、最大人数、冷进入/稳定/最坏交互结果及降级处置；
9. 完成其余灰盒、目标设备与目标人数测试，写回指标、场景和未知项；
10. 将专项结果写入 `audits`，再以 `stage=predeploy` 重跑总审计。

`audits` 记录 `build_bundle/density/state/parameter_expansion/theme_adaptation/performance/component_evidence` 的 `planned/passed/not_applicable`。题材适配审计只证明每个族、区域和视觉测试都有结构化记录，不能替代真实相机判断；性能审计只证明展开上限、峰值声明和设备记录结构一致，不能从数量推导帧率；组件绑定审计只证明每个抽象角色都有结构化记录，不能替代目录查询、设备状态和版本证据。只有实际完成对应复核后才能把 `theme_adaptation/performance/component_evidence` 标成 `passed`。所有 predeploy 计划不论总数都必须通过参数展开、密度、跨账本、题材适配、目标设备性能与当前版本组件证据检查，防止把成品压到数量阈值下绕过对账、用通用千件骨架换色冒充完整世界，或只报全图总数掩盖最坏视区；复杂类型或启用修饰器的计划还必须通过状态审计。

总审计不会读取外部日志来替声明背书。批准写入前应在同一次工作记录中实际运行专项脚本，并保留摘要；修改计划后相关状态重新降为 planned。

跨账本门禁不会把自然语言装配族名猜成组件引用。它验证数量、分层、区域、成本/构成来源、设计职责、装配族使用、变体覆盖、最低可见基础件占比和三个账本的一致性；成品装配计划还用 `quality_contract` 核验全图/分区包围盒、可见世界占比、必需完成层/职责、全图与分区最低职责实例数、分区最低实例/装配族/空间跨度、完全重合空间件和无解释的单变体重复。这样不能用一个轮廓件给数千个表皮小件“挂名过审”；但职责标签仍需人工确认语义真实。EID、属性、枢轴、游戏欧拉角、真实碰撞与可写性仍由当前版本组件证据和写入流程负责，记录格式见 [组件角色绑定与可写证据](component-binding-audit.md)。
