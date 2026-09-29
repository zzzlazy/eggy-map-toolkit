# 在本地生成组件目录

设计 Skill 和测试不需要游戏数据。真实设备制作需要与游戏版本匹配的组件目录；该目录包含游戏派生数据，因此由使用者本地生成，不随此仓库发布。

## 已有目录源

如果已有 `unit-components.csv`、`effect-components.csv` 和解码表，直接运行：

```bash
eggy-map-build-catalog \
  --catalog .local/catalog-source \
  --decoded-bindicts .local/catalog-source/decoded-bindicts \
  --output .local/catalog \
  --version-code <实际整数版本号> \
  --version-name <实际游戏版本> \
  --apk-sha256 <本地对应安装包的SHA256>
```

尖括号为需要替换的参数；版本、包摘要和输入表必须来自同一构建。输出目录必须不存在。

## 从本地 NPK 提取表

准备本地游戏代码归档和与你的格式匹配的 NeoXtractor checkout。本项目使用它的 `core/npk/eggyparty_codes.py`、`core/npk/decryption.py`、`core/rotor.py` 和 `core/bindict/parser.py`，不自动下载解析器。归档格式未知或解码失败时保留错误，不执行提取的模块。

```bash
python tools/index_neox_script_archive.py \
  .local/game/code.npk .local/index.tsv \
  --neoxtractor-root /absolute/path/to/NeoXtractor
```

从索引中查找所需表的 `filename`，使用同一行 `signature` 提取对应模块，然后解码其中的 Bindict：

```bash
python tools/extract_neox_script_module.py \
  .local/game/code.npk <索引中的signature> .local/modules/editor_unit.json \
  --neoxtractor-root /absolute/path/to/NeoXtractor
python tools/decode_neox_bindict_blob.py \
  .local/modules/editor_unit.json .local/decoded/editor_unit.full.json \
  --neoxtractor-root /absolute/path/to/NeoXtractor
```

对以下五张必需表分别执行：`editor_unit`、`editor_trigger`、`editor_virtual_point`、`editor_decoration`、`editor_model`。可选增加 `editor_effect` 和 `editor_model_language_zh`；缺少它们时特效表为空、名称可能回退到组件编号。

`prepare_catalog_sources.py` 接受完整解码器的 `data` 封装，也接受既有 `bindicts[].parsed.data` 封装，生成当前 API 需要的 CSV 和标准表：

```bash
python tools/prepare_catalog_sources.py \
  --decoded .local/decoded \
  --output .local/catalog-source \
  --apk-sha256 <本地对应安装包的SHA256>
```

此快捷转换器覆盖目前制作器支持的四种结构族，以及可选特效查询。它不是完整游戏组件目录生成器；已有更完整的 CSV 目录可走第一节接口。模型尺寸必须来自解码表，缺失时组件保持不可写，不能凭视觉补值。

## 写能力证据

仅从游戏表中发现组件不会使它可写。快捷转换器默认写入 `unverified` 静态状态。已有本地静态门禁审查时，通过 `--static-gates .local/static-gates.json` 提供与包摘要匹配的记录：

```json
{
  "apk_sha256": "<与命令一致的本地包摘要>",
  "components": {
    "<组件EID>": {
      "status": "pass",
      "evidence": "记录同版本静态规则的核对依据；不是UI可见或完整试玩的声明"
    }
  }
}
```

`status` 允许 `pass/blocked/unverified`。未登记组件保持 `unverified`；不接受其他包版本的审查记录。不能为解锁写入而批量标为 `pass`。即使静态规则通过，运行时仍检查结构族、预制体、模型绑定、尺寸、属性和设备版本。

最后按第一节编译，设置 `EGGY_MAP_CATALOG_MANIFEST` 后调用 `device_status` 和 `get_component` 查看实际能力。目录成功构建只证明输入可解析，不证明新版本已获得设备写入支持。

所有归档、解码表、审查记录及生成目录应留在 `.local` 或仓库外；本地插件构建产物也不提交到 GitHub。
