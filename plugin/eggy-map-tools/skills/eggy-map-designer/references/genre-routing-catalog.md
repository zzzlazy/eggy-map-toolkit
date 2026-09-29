# 常见地图叫法路由表

玩家和作者常用题材名、平台标签或社区简称描述地图；这些词不能直接决定结构。先找“玩家反复做什么”和“谁拥有胜负/完成”，再把叫法路由为一个主类型、最多一个次类型和必要修饰器。

需要快速检索时运行 `python3 scripts/route_genre.py --query "<社区叫法>"`。脚本从本页表格读取候选、修饰器、误分类边界和下一道权威问题；它的 `committed_primary_type` 有意始终保持为空，必须由体验契约确认重复动词、终局、恢复和题材剥离测试后再定类。`--all-summary` 用于检查本页是否仍覆盖全部主类型和修饰器。

## 四问路由

1. **重复动词**：玩家整局最常做的是跑、判断、合作、争夺、经营、读招、建造、隐蔽还是围绕比赛对象攻守？
2. **权威终局**：冲线、章节进度、谜题状态、存活、比分、剧情状态、目录完成、Boss 生命、核心生命、检测/撤离、行动权、比赛对象还是作品保存中的哪一个决定结束？
3. **失败后回哪里**：就近复位、当前房间、章节检查点、观战、下一回合、经营阶段、重试 Boss，还是退出创作会话？
4. **题材剥离测试**：删去标题、封面、灯色和角色模型后，剩下的状态与动作仍属于什么类型？

回答不清时先写两个候选合同，各画一条 30 秒核心循环；选择能解释大多数强制时间、失败和重玩理由的一个作为主类型。

## 社区叫法到设计合同

| 常见叫法 | 默认主类型 | 常见次类型/修饰器 | 决胜问题 | 最容易误判 |
|---|---|---|---|---|
| 短跑酷、竞速、速通 | `short_race` | `vertical_climb`、`vehicles`、`rising_pressure` | 终局是否由冲线/时间决定 | 用机关数量代替流动、超车和短复位 |
| 超长跑酷、闯关、爬塔 | `chapter_challenge` | `narrative_exploration` 次类型、`vertical_climb`、`cumulative_growth` | 是否靠多章、检查点和长期进展留人 | 只拉长距离，不改变动作/场景/恢复 |
| 机关训练、单机制变奏 | `mechanism_puzzle` 或 `chapter_challenge` | `short_race` 次类型 | 乐趣来自理解规则，还是稳定执行动作 | “按钮很多”不等于谜题，“单规则”不等于短图 |
| 密室、解密、逃脱房 | `mechanism_puzzle` | `narrative_exploration` 次类型、`horror` | 门是否由可推理状态打开 | 随机试密码、长文字和追逐题材冒充谜题 |
| 双人图、合作闯关 | `cooperative` | `mechanism_puzzle`/`chapter_challenge` 次类型、`escort_collection` | 一人的什么动作改变另一人的什么机会 | 两条独立路线或同时到达被误叫合作 |
| 搬运、护送、找伙伴 | `chapter_challenge`/`cooperative`/`narrative_exploration` 之一 | `escort_collection` | 对象是主进度载体还是独立胜负循环 | 只显示计数，不处理对象丢失、归属和重复交付 |
| 生存、坚持 N 分钟、大逃杀 | `survival` | `random_variation`、`rising_pressure` | 存活/淘汰是否决定终局 | 固定时间加销毁板却没有危险教学和收敛 |
| 地板消失、别被扫下去、毒圈 | `survival` | `random_variation`、`rising_pressure` | 危险如何压缩安全空间并结束回合 | 随机秒杀、永久安全角、第二局残留 |
| 解压、拆图、破坏房间、砸盲盒 | `chapter_challenge` 或 `score_contest` | `destructible_world` | 有限目标/房间完成后开路，还是个人/队伍破坏得分决定结算 | 可打模型、碎裂特效和高血量冒充目标身份、命中去重、依赖面、奖励与重置合同 |
| 积分赛、占点、夺旗、资源争夺 | `score_contest` | `escort_collection`、`asymmetric_roles` | 得分事件和归属是否是权威 | 把拾取、携带、提交和去重混成一个触发 |
| 团队射击、擂台、PVP | `score_contest` 或 `survival` | `asymmetric_roles`、`random_variation` | 以分数、击败数还是最后存活结算 | 伤害模型很复杂但出生、返场、平局不闭合 |
| 躲猫猫、猫鼠、搜寻者 | `score_contest`/`survival` | `asymmetric_roles`，必要时 `stealth_infiltration` 次类型 | 玩家互相搜捕，还是环境传感器决定侦测—目标—撤离 | 阵营换色冒充角色差异；把环境潜行与 PVP 躲藏混为一类 |
| 狼人杀、太空狼人、阵营推理、谁是内鬼 | `social_deduction` | `narrative_exploration` 次类型，必要时 `asymmetric_roles` 扩展角色 | 私密分角、场上行为、会议/投票、淘汰权限和多阵营条件是否共同决定终局 | 只有换色阵营与自由聊天；共享提示或观战镜头泄露身份 |
| 谋杀谜案、剧本推理 | `social_deduction` 或 `narrative_exploration` | `mechanism_puzzle`/`narrative_exploration` 次类型 | 玩家是在多人不完整信息中判断活人，还是探索一个预设答案 | 把固定剧情谜底误当阵营对抗，或让系统直接显示凶手 |
| 暗杀、潜入、偷取后撤离 | `stealth_infiltration` | `horror`、`cooperative` 次类型 | 传感器、警戒和目标后撤离是否拥有终局 | 黑暗、监控红灯和守卫模型冒充检测合同 |
| 追逐逃生、逃离学校/医院 | `chapter_challenge` 或 `stealth_infiltration` | `horror`、`rising_pressure` | 玩家是在跑障碍，还是主动管理暴露并可恢复警戒 | 只凭“逃离/被抓”题材选择潜行；边界反例见 [《case-008》](exemplars/case-008.md) |
| 恐怖图、规则怪谈 | `narrative_exploration`/`mechanism_puzzle`/`chapter_challenge`/`stealth_infiltration` 之一 | `horror` | 去掉黑暗与惊吓后，哪个循环仍决定进展 | 把恐怖当主类型，用不可读和突发失败制造难度 |
| 剧情、RPG、冒险 | `narrative_exploration` 或 `chapter_challenge` | `combat_boss`/`mechanism_puzzle` 次类型、`escort_collection` | 世界状态/选择，还是动作章节决定进展 | 对话量代替空间事件；多个支线终点争夺权威 |
| 开放世界、任务探索 | `narrative_exploration` | `management_simulation`/`cooperative` 次类型、`random_variation` | 地标、事件和回访变化是否是主循环 | 大地图没有地标网络、当前目标或返回闭环 |
| 打卡、家园、派对房、角色扮演 | `social_showcase` | `narrative_exploration`/`management_simulation` 可选支线 | 到达—活动—换景—返回是否构成有效会话 | 只有布景和购买入口，没有可做的事与回流 |
| 农场、餐厅、工厂、店铺、养成 | `management_simulation` | `cooperative` 或 `survival` 次类型 | 输入—加工—交付—收益—新瓶颈是否闭合 | 挂机涨数、购买列表和总进度冒充事务 |
| 塔防、守城、波次防御 | `defense_strategy` | `management_simulation` 次类型 | 路径、波次、漏怪和核心是否决定终局 | 自动打怪但没有建设/职业选择；经营系统与防线脱节 |
| 白天建造晚上守、基地生存 | `defense_strategy` 或 `management_simulation` | 另一个作次类型，组合方式常为 `phase_shift` | 重玩理由是防线验证还是生产扩张 | 两阶段各自一套资源、失败和终点，没有交接锁 |
| Boss 战、团本、PVE | `combat_boss` | `narrative_exploration`/`cooperative` 次类型 | Boss 生命、阶段和团灭是否决定结束 | 大模型、高血量和弹幕数量代替读招/反制/输出窗 |
| Boss Rush、连续首领 | `combat_boss` | `chapter_challenge` 次类型 | 每个 Boss 是同一战斗课程的阶段还是独立长章节 | 战后旧投射物、阶段监听和玩家状态未清理 |
| 音游、节奏演出、舞蹈判定 | `rhythm_performance` | `social_showcase` 可选支线 | 谱面判定、连击和乐句结算是否是主终局 | 有 BGM、鼓点或闪灯就叫音游 |
| 音乐跑酷、踩点机关 | `short_race`/`chapter_challenge` 之一 | `rhythm` | 跑到终点仍是目标，节奏只改变时机吗 | 重复建立谱面终局与竞速终局 |
| 赛车、摩托、飞行赛道 | `short_race` 或 `chapter_challenge` | `vehicles` | 冲线/圈速是否决定结束 | 在步行赛道末期才换车，没有三档驾驶与镜头标定 |
| 足球、篮球、冰球等 | `sports_match` | `vehicles`（载具球赛） | 比赛对象是否有控球、出界、死球与重启 | 球只是一件交分道具，实质仍是积分搬运 |
| 棋牌、卡牌、棋盘、轮流行动 | `turn_based_strategy` | `management_simulation`/`narrative_exploration` 次类型 | 当前行动者与解析阶段是否限制合法输入 | 用技能冷却或轮流站按钮冒充回合权威 |
| 肉鸽、随机房、随机事件 | `chapter_challenge`/`survival`/`management_simulation` 之一 | `random_variation`、`cumulative_growth` | 随机改变哪个主循环，谁仍决定终局 | 把“肉鸽”当主类型；候选不做兼容和可解过滤 |
| 创造、盖房、绘画、DIY 沙盒 | `sandbox_creation` | `social_showcase` 次类型 | 作品放置、权限、预算、撤销和保存是否是主循环 | 只有若干摆设按钮，没有预览、校验和可靠回退 |
| 多小游戏派对、轮换玩法 | `survival` 或 `score_contest` | `random_variation` | 多轮最终按存活、总分还是淘汰结算 | 每个小游戏各带终点/计时器，轮间状态不清理 |
| 纯观赏演出、过场电影 | `narrative_exploration` 或 `social_showcase` | `rhythm`/`horror` | 玩家是否通过观察/选择推进，或只是可退出地观看 | 强制镜头无跳过、无控制归还、无退出 |

## 选择次类型还是修饰器

- 它若拥有独立的输入—反馈—失败—清理循环，并占据可标出的强制节拍，可作次类型。
- 它若只改变速度、空间包络、压力、身份、感官、随机条件、任务对象或能力成长，用修饰器。
- 它若只有题材、颜色、角色或模型变化，既不是次类型也不是修饰器，写入视觉主题。
- 两个系统若都声称决定终局，先指定优先级和原子交接；做不到就删掉一个终局。

## 能力不足时的降级

先查当前版本组件和可写证据。若无法可靠实现所选主类型的最小权威循环，不要用外观假装实现：

- 没有可信视线/检测能力：把潜行降为有预告的章节追逐或观察解谜，并明确不是潜行；
- 没有稳定目标/路径能力：把塔防降为玩家主动守点的生存/积分图；
- 没有可靠伤害和阶段提交：把 Boss 降为分阶段机关生存；
- 没有低延迟统一时钟：把纯音游降为节奏修饰的跑酷/演出；
- 没有局内保存/撤销：把创造沙盒降为一次性合作搭建或社交摆设活动；
- 没有比赛对象的边界/重启权威：把体育降为明确的积分搬运，而不是假装有界外与死球。
- 没有私密分角、会议冻结、每人选票与淘汰权限：把阵营推理降为公开非对称合作、阵营积分或叙事谜案。
- 没有可靠的受击、对象身份或原子销毁/奖励能力：把可破坏世界降为明确按钮、收集或顺序机关驱动的场景变体，并取消“自由拆除/物理破坏”承诺。

降级后重新跑主类型审计，不能保留原类型名称和质量承诺。
