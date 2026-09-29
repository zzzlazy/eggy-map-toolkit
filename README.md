# eggy-map-toolkit

用于《蛋仔派对》UGC 地图设计与本地制作的开源工具链：从玩家体验、路线与场景设计，到基础件装配、审计、组件查询和事务写入。

## 包含什么

- **设计 Skill**：17 种玩法类型、15 类视觉世界、参数化装配种子、主题与性能审计，以及 24 份匿名案例记录。
- **组件查询 Skill**：按当前游戏版本查询组件、模型、可写属性与证据。
- **制作 Skill / MCP**：13 个工具，支持地图检查、组件增删、批量调和、备份和回滚。
- **Python API**：严格编解码、引用检查、声明式编辑和事务部署。

匿名案例只支持其已记录的有限结论。合成设计模板通过审计不等于成品经过试玩；千件级装配仍需符合真实空间、镜头与设备性能。

## 环境与安装

Python 3.11 及以上。设备读写目前按 **macOS + MuMu** 的发现和版本匹配逻辑实现，已有游戏 **1.0.291** 的验证记录；其他版本不能据此视为可写。离线设计、单元测试与目录构建可独立运行。

```bash
git clone https://github.com/zzzlazy/eggy-map-toolkit.git
cd eggy-map-toolkit
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
```

### 只使用设计功能

设计 Skill 是一个自包含目录：

```text
plugin/eggy-map-tools/skills/eggy-map-designer/
```

把该目录复制到你的 Codex 技能目录即可使用；也可以直接让代理读取其中的 [SKILL.md](plugin/eggy-map-tools/skills/eggy-map-designer/SKILL.md)。内置脚本只依赖 Python 标准库，读写设备不属于设计流程。

```bash
cd plugin/eggy-map-tools/skills/eggy-map-designer
python3 scripts/route_genre.py --query "双人解谜"
python3 scripts/audit_type_support.py --type cooperative
python3 scripts/audit_visual_support.py --world industrial_mixed_scale --primary-type cooperative
python3 scripts/audit_research_coverage.py --design-packet \
  --primary cooperative --visual-world industrial_mixed_scale
```

查看 [视觉世界支持卡](plugin/eggy-map-tools/skills/eggy-map-designer/references/visual-world-support.md) 和 [参数化装配](plugin/eggy-map-tools/skills/eggy-map-designer/references/parametric-layout.md) 了解如何继续生成设计账和装配计划。

### 配置本地制作

仓库不分发真实游戏数据。先按 [本地组件目录](docs/local-catalog.md) 从你本地准备的同版本资料生成目录，再设置：

```bash
export EGGY_MAP_CATALOG_MANIFEST="$PWD/.local/catalog/catalog-manifest.json"
export EGGY_MAP_DATA_DIR="$PWD/.local/runtime"
python -m eggy_map_mcp
```

上述命令启动 STDIO MCP，供 MCP 客户端连接。它不会显示网页或交互式命令提示符。也可以在 MCP 客户端配置 `.venv/bin/python -m eggy_map_mcp`，并传入这两个环境变量的绝对路径。

MCP 启动和本地组件查询不需要 ADB。实际设备操作需要 ADB、用户授权的设备访问，以及唯一、符合版本与权限检查的 MuMu 实例。启动服务不代表通过设备写入检查；先调用 `device_status` 查看实际模式，缺少 ADB 时返回 `ADB_NOT_FOUND`。缺少组件目录会返回准备步骤。

### 构建三个 Skill + MCP 的本地插件

```bash
python tools/build_local_plugin.py \
  --catalog .local/catalog \
  --destination dist/eggy-map-tools
```

构建器生成当前平台/指定 Python 的 wheelhouse 和哈希锁。首次构建需要联网取得 Python 依赖，插件运行时从 wheelhouse 离线安装；请在目标平台上构建，并使用相同 Python 次版本。默认构建目录是 `dist`，不会修改已安装插件。已有输出目录不会被覆盖。

构建结果可交给支持本地插件的 Codex 安装入口；其他 MCP 客户端直接使用上一节的源码启动方式。插件清单位于 `.codex-plugin/plugin.json`，服务配置位于 `.mcp.json`。本仓库不修改你的个人 marketplace。

## 制作流程

1. 设计并审计体验、空间、状态与装配计划；明确未知属性和需试玩的指标。
2. 查询当前版本组件，检查目标地图，并取得绑定当前修订的 `map_ref`。
3. 向用户展示本次具体变更；用户退出编辑器、停在地图列表并批准后，执行一次写入。
4. 工具先完整备份，再校验和部署。用户手动进入编辑模式等待缓存重建；正常则保存，异常则不保存退出，再执行已批准的回滚。

写入保留既有版本校验、引用时效、属性白名单和事务边界。完整接口见 [MCP 合同](docs/mcp-api.md)。

## 开发与验证

```bash
python -m pytest -q
python tools/check_designer.py
python tools/check_release.py
python tools/build_smoke.py
```

测试和构建冒烟使用合成组件数据，不连接模拟器。GitHub Actions 检查源码、匿名案例引用和离线插件握手。真实设备表现需要在对应游戏版本、画质和人数下单独测试。

源码目录：`src`；插件与 Skills：`plugin`；测试：`tests`；提取、转换、构建和发布检查：`tools`。本地游戏资料与生成目录统一放在被忽略的 `.local` 下。

## 许可证与匿名化

原创代码、Skill 与蒸馏文档采用 [MIT](LICENSE)。依赖和游戏数据说明见 [第三方声明](THIRD_PARTY_NOTICES.md)。这是社区项目。

公开文件使用稳定案例编号，不包含具体作品名称、地图码、作者、截图、原始地图及身份映射。提交前可用 `tools/check_release.py --private-identities <仓库外的私有映射.json>` 额外扫描原名称、别名和标识；扫描只输出文件及规则，不输出命中的身份内容。不得把这个映射文件提交到仓库。
