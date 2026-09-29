# 题材适配账与视觉证据

总设计账会说明世界句、记忆剪影、比例、基础形状、装配族、材质节奏和颜色语义；参数化装配账会说明几何、区域、变体与数量。两份文件即使数字一致，也可能只得到“通用骨架换色”。题材适配账逐一绑定每个真实装配族与区域，要求它们说明怎样用基础件形成该世界，并记录真实游玩相机中的复核证据。

本账能证明覆盖、来源一致和复核状态，不能仅凭文字判断画面好看。`reviewed/tested` 必须对应账内命名的真实游玩视角；编辑器俯视图、详情封面或设计推断不能替代。

## 生成起点

已有总设计账和装配计划时生成模板：

```bash
python3 scripts/audit_theme_adaptation.py \
  design-plan.json assembly-plan.json \
  --template --output theme-adaptation.json
```

只有主类型时，也可让类型种子同时输出：

```bash
python3 scripts/generate_type_assembly_seed.py --type chapter_challenge \
  --output assembly-seed.json \
  --design-output design-seed.json \
  --density-output density-seed.json \
  --binding-output component-binding-seed.json \
  --theme-output theme-adaptation-seed.json \
  --performance-output performance-seed.json
```

模板会从真实展开结果写入装配族、区域、数量、布局、变体、职责、可用复核视角和比例锚点；创意字段保持 `unresolved`。这表示没有漏项，不表示题材已经完成，更不表示可以部署。

## 根字段与阶段

| 字段 | 说明 |
|---|---|
| `schema_version` | 当前为 `1` |
| `stage` | `design/review/predeploy` |
| `primary_type/density_profile` | 必须与总设计账一致 |
| `assembly_expected_total` | 必须与本次参数展开一致 |
| `theme_identity` | 世界句、剪影、比例、形状、材质、颜色、世界状态和禁用清单的原样快照；主题变化后必须重建或对账 |
| `family_adaptations[]` | 每个实际装配族恰好一项 |
| `zone_adaptations[]` | 每个实际区域恰好一项 |
| `global_reviews[]` | 八项视觉与成本复核，不得缺项 |
| `verification_boundary` | 声明脚本只核对结构化记录，视觉结论仍依赖真实相机证据 |

三个阶段分别表示：

- `design`：允许装配族和区域为 `unresolved`，全局复核为 `planned`；
- `review`：所有族和区域至少写到 `planned`，必须形成具体形状、结构、材质、变体和景深方案；
- `predeploy`：总设计账本身必须是 `maturity=final/stage=predeploy`，所有族和区域为 `reviewed`，八项全局复核均为 `tested`。

升级阶段不能靠改一个枚举值。审计器会检查所需内容与命名视角是否同时存在。

## 装配族适配

每个 `family_adaptations[]` 先锁定自动派生字段：

- `family_name/instance_count/zones/layouts/variant_names/design_roles`；
- `available_review_views`，只能来自该族实际区域所属世界壳体。

再完成以下创意合同：

| 字段 | 必须说明什么 |
|---|---|
| `motif_sentence` | 这个族在场所中反复出现的具体构造动作，不写“符合主题” |
| `silhouette_contribution` | 它从远处贡献什么高低、开口、方向或地标轮廓 |
| `structural_grammar` | 支撑、跨接、节点、接缝、端头与转角怎样成立 |
| `shape_roles[]` | 从主题卡 `base_shapes` 选形状并逐一说明职责 |
| `material_applications[]` | 从主题卡颜色语义选角色，说明材质落在大面、边框、接触边、状态面还是焦点 |
| `contact_and_clearance` | 表皮、连续碰撞、多人净宽、机关扫掠和相机口袋怎样分离 |
| `variant_rules[]` | A/B/C 等每个真实变体改变什么外观；入口、出口、净空、公平和玩法窗口保持什么 |
| `world_state_response` | 该族保持稳定还是响应世界状态；至少一个族必须真实变化 |
| `prefab_removal_expectation` | 隐藏少量主题 Prefab 后仍由哪些基础结构表达题材 |
| `banned_shortcuts[]` | 此族最容易退化成的换色、悬空、随机散件或一体 Prefab 捷径 |
| `reviewed_views[]` | 实际复核过的游玩相机视角；`reviewed` 至少一项 |

进入 `review/predeploy` 后，所有声明形状中至少使用主题卡里的两个形状，并让至少一个形状跨装配族复用，形成统一的形状语言。每个变体都必须有规则，不能只写“随机变化”；未声明的变化会破坏接口、碰撞和公平。

## 区域适配

`zone_adaptations[]` 自动锁定实际实例数、装配族、层级、职责、世界壳体、可用视角和比例锚点。每个区域再写：

- `foreground`：角色附近的接触厚度、边缘、五金、植被或家具；
- `midground`：下一处可达动作、风险、活动或交互；
- `background`：低成本方向剪影和尺度，不复制近景微件；
- `scale_anchors`：至少两个来自所属世界壳体的熟悉尺度物；
- `route_or_activity_readability`：下一动作如何通过形、值、光和构图被读到；
- `density_rationale`：为什么细节集中在此处，哪些背面与留白刻意稀疏；
- `reviewed_views`：`reviewed` 至少两个真实视角，防止只把出生首屏做满。

区域与装配计划或世界壳体发生任何增删后，旧适配账会因数量、族、层级、职责或视角漂移而失败。重新生成模板，再迁移仍然有效的创意合同。

## 八项全局复核

`global_reviews[]` 必须恰好包含：

1. `silhouette`：黑白剪影仍能分出地标、合法开口和危险边；
2. `prefab_removal`：隐藏少量主题资产后，基础件世界仍有题材；
3. `three_distance`：前景接触、中景动作、远景方向各司其职；
4. `grayscale`：路线、危险、交互和目标不只靠色相；
5. `repetition`：连续复制有受控节奏，接口与公平不漂移；
6. `state`：可见变化与权威状态同源并能复位；
7. `clearance`：主题细节不侵入多人、相机、落点和机关扫掠；
8. `cost`：最密视角应用碰撞、投影、透明、动态与降级策略后仍符合目标设备合同。

`planned` 填方法和验收标准，`result` 保持空；`tested` 必须写结果并引用至少一个可用游玩视角。脚本检查引用与状态，但不会根据一句“通过”自动相信视觉事实；工作记录中仍需保留截图、试玩或设备测量摘要。

## 审计命令与边界

```bash
python3 scripts/audit_theme_adaptation.py \
  design-plan.json assembly-plan.json theme-adaptation.json --json
```

审计会拒绝：装配族或区域漏项、数量/职责/布局/变体漂移、主题身份过期、使用主题卡外的形状或颜色角色、变体覆盖不完整、只用一个族一个形状、没有世界状态响应、伪造不可用相机视角，以及 `predeploy` 仍含未审内容。

它不会自动判断形状组合是否美观、材质是否真的存在、光照是否正确、Prefab 隐藏后的画面是否成立，也不会提供组件 EID。组件来源另走 [组件角色绑定与可写证据](component-binding-audit.md)，数量与区域另走 [基础件装配与成品密度](assembly-and-density.md)，视觉语法来源见 [视觉主题与世界构成蓝图](visual-theme-playbooks.md)。
