"""Mechanically consolidate the frozen contract without changing its sources."""

import argparse
import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "docs" / "interfaces" / "输入模拟器完整接口定义_v0.3_单文件汇总.md"
SOURCE_FILES = (
    "input-simulator-data-contract-v0.3.md",
    "input-simulator-fields-v0.3.md",
    "input-simulator-business-v0.3.schema.json",
    "input-simulator-api-v0.3.schema.json",
    "input-simulator-package-v0.2.schema.json",
    "input-simulator-icd-v0.3.json",
    "input-simulator-canfd-v0.3.dbc",
    "input-simulator-coverage-v0.3.md",
    "input-simulator-coverage-v0.3.json",
    "input-simulator-v0.3.baseline.json",
    "input-simulator-v0.3.manifest.json",
    "input-simulator-v0.3.examples.json",
    "input-simulator-v0.3.golden.json",
    "input-simulator-v0.3.qa.json",
)
SCHEMA_FILES = SOURCE_FILES[2:5]
SOURCE_LABELS = (
    "语义契约原文", "逐字段定义原文", "业务 Schema", "管理 API Schema",
    "兼容资源元数据 Schema", "实际 ICD 目录", "CAN FD DBC",
    "需求对照原文", "机器可读需求对照", "共同基线指纹",
    "定义文件清单", "完整结构测试数据", "全部编码黄金向量", "静态校验报告",
)


def language(name):
    return "json" if name.endswith(".json") else "dbc" if name.endswith(".dbc") else "markdown"


def start_marker(name):
    return f"<!-- BEGIN EMBED {name} -->\n`````{language(name)}\n"


def end_marker(name):
    return f"\n`````\n<!-- END EMBED {name} -->\n"


def walk(value):
    yield value
    if isinstance(value, dict):
        for item in value.values():
            yield from walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk(item)


def demote(text):
    lines = text.splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    return "\n".join("#" + line if re.match(r"^#{1,5} ", line) else line for line in lines).strip()


def cell(value):
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return value.replace("|", "\\|").replace("\r", " ").replace("\n", "<br>").replace("`", "&#96;")


def constraints(schema):
    keys = ("const", "enum", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
            "multipleOf", "minLength", "maxLength", "pattern", "format", "minItems", "maxItems",
            "uniqueItems", "minProperties", "maxProperties", "additionalProperties",
            "unevaluatedProperties", "x-decimal-maximum")
    return "; ".join(f"{key}={cell(schema[key])}" for key in keys if key in schema) or "见结构/语义约束"


def schema_rows(schema, path="$", required="定义根", branch="通用"):
    if isinstance(schema, bool):
        yield f"| `{cell(path)}` | boolean schema | {required} | {cell(schema)} | - | - | {branch} |"
        return
    kind = schema.get("type", "ref" if "$ref" in schema else "const" if "const" in schema else "组合/枚举")
    if "$ref" in schema:
        kind = schema["$ref"]
    initial = schema.get("default", schema.get("x-default-policy", "不自动补值；按必填/分支规则显式提供"))
    yield (f"| `{cell(path)}` | {cell(kind)} | {required} | {constraints(schema)} | "
           f"{cell(schema.get('x-unit', '-'))} | {cell(initial)} | {cell(branch)} |")
    for key, sub in schema.get("properties", {}).items():
        need = "是" if key in schema.get("required", []) else "否/按组合约束"
        yield from schema_rows(sub, f"{path}.{key}", need, branch)
    if isinstance(schema.get("items"), (dict, bool)):
        yield from schema_rows(schema["items"], path + "[]", "数组元素", branch)
    for key in ("oneOf", "anyOf", "allOf", "prefixItems"):
        for index, sub in enumerate(schema.get(key, [])):
            yield from schema_rows(sub, path, required, f"{branch}/{key}[{index}]")
    for key in ("if", "then", "else", "not", "contains", "propertyNames"):
        if isinstance(schema.get(key), (dict, bool)):
            yield from schema_rows(schema[key], path, "按条件", f"{branch}/{key}")
    for key, sub in schema.get("dependentSchemas", {}).items():
        yield from schema_rows(sub, path, "按字段依赖", f"{branch}/dependentSchemas:{key}")


def definition_tables(schema, prefix):
    result = []
    for name, definition in schema["$defs"].items():
        result.extend((f"### {prefix}.{name}\n", "| 字段路径 | 类型/引用 | 必填 | 范围/枚举/结构限制 | 单位 | 初值/赋值规则 | 分支 |",
                       "|---|---|---|---|---|---|---|", *schema_rows(definition), ""))
    return "\n".join(result)


def build_document(directory):
    directory = Path(directory)
    sources = {name: (directory / name).read_bytes() for name in SOURCE_FILES}
    parsed = {name: json.loads(raw) for name, raw in sources.items() if name.endswith(".json")}
    catalog = parsed["input-simulator-icd-v0.3.json"]
    api = parsed["input-simulator-api-v0.3.schema.json"]
    baseline = parsed["input-simulator-v0.3.baseline.json"]
    parts = [
        "# 输入模拟器完整接口定义 v0.3：单文件汇总\n",
        "汇总日期：2026-10-03。共同业务基线：HIL-ICD-1.0。定义权：本项目。\n",
        "**这是单文件、自包含的接口阅读与交付版本。机器定义均已完整嵌入本文件，不需要另开任何附件才能查到字段、规则或编码。**\n",
        "本文件是现有冻结定义的汇编，不是新 ICD 版本；不是应用实现完成或硬件验收通过的声明。原始 14 份资料的内容、字节数和 SHA256 均在本文件内保留并校核。程序原有依赖文件无需迁移，编译版本不能用汇总文件整体哈希替代共同基线指纹。\n",
        f"共同基线指纹：`{baseline['baseline_sha256']}`。算法与四个原始组件见第六章及附录。\n",
        "## 阅读导航\n",
        "1. [第一章：范围与开发对接要点](#overview)\n2. [第二章：完整语义契约](#semantics)\n3. [第三章：完整业务、三源与模型字段](#fields)\n4. [第四章：前后端 API 与资源元数据全部字段](#management)\n5. [第五章：传输、端口与原工具链](#wire)\n6. [第六章：覆盖与验收](#acceptance)\n7. [附录：全部机器定义和原文快照](#embedded)\n",
        '<a id="overview"></a>\n## 第一章：范围与开发对接要点\n',
        "### 1.1 完整范围\n",
        "- 三种输入源：PROTOCOL、SCENARIO、HISTORY，包含源参数、资源身份、事件/波形/断言、回放与清理规则。\n- 45 类 TO_36 输入、14 类 FROM_36 反馈；管理 API 共 25 个命令。\n- 13 类 PACKED_LE/CAN FD 消息、正式 UDP 与独立视频分片协议。\n- 56 个物理逻辑端口、97 条模型绑定，以及原六条工具链。\n- 会话、授权、时钟、时序、错误、反馈和 E0/E1/E2/E3 证据；正式 3.3 替换门禁。\n",
        "### 1.2 两种接口，不是两套业务定义\n",
        "**管理接口**是前端与后端交互的 JSON 请求/响应，见第四章 API 字段。**正式数据接口**是模拟器或真实 3.3 与 3.6 之间的报文，见第二、三、五章。管理命令的 ACCEPTED 不能当作模型 APPLIED；两者通过请求、会话、序列、事务与真实证据关联。\n",
        "模拟器临时代行 3.3 输出职责；3.6 只有一条标准接收/解码/映射路径。未来真实 3.3 必须遵守同一字段、编码、时序与反馈，只切换允许的部署配置，不能增加真实源专用解析器。\n",
        "### 1.3 必须读懂的字段规则\n",
        "业务对象封闭；按选定分支发送全部必填字段。初值用于界面初始化，不允许接收端补值；未知键、缺失、错误类型、越界、非法 null、NaN/Infinity 均拒绝。字段与 Schema 的引用在本文件内均有完整定义，`ref` 不表示尚未确认。时间与修订号的 uint64 使用十进制字符串并验证实际上限。\n",
        "### 1.4 版本与优先级\n",
        "语义契约、业务 Schema、ICD 目录和 DBC 共同构成基线；正文语义优先于仅结构可表达的规则，字段/字节布局按对应完整定义执行。发生矛盾应阻止发布并修订共同基线，不自行补容错。\n",
        "管理 API 的 `$id` 是 `urn:hil:input-simulator:api:0.3`。其原始 title/comment 中继承的 0.2 字样不决定业务版本，本汇总为保留原始哈希不修改这些描述。兼容资源元数据 Schema 的 `$id` 为 `urn:hil:input-simulator:package-contract:0.2`，仅在现有管理/资源引用边界内使用，不能覆盖 v0.3 业务字段。其草稿结构允许的 Pending、自由 Values、旧协议/场景对象不授权正式运行：正式 Profile 和三类业务 Source 必须通过第二章规则及 v0.3 强类型定义，禁止携带未落实 wire/timing/feedback 或使用旧演示数据。\n",
        '<a id="semantics"></a>\n## 第二章：完整语义契约\n',
        "以下保留冻结契约的全部语义，不缩写安全或替换要求。原文第 16 节描述的是 2026-10-02 定义发布时的验证边界，不是当前代码开发进度。原文中的文件名是本汇总内的来源标识，内容全部见本文件附录。\n",
        demote(sources[SOURCE_FILES[0]].decode("utf-8")),
        '\n<a id="fields"></a>\n## 第三章：完整业务、三源与模型字段\n',
        "以下完整展开原有 1409 行字段/引用/分支记录和模型绑定索引，不将其误称为 1409 个物理信号。业务 Schema 的全部 92 个定义也已内嵌；引用名称可在本文件中直接搜索。原表提及的管理/元数据字段在第四章全部展开，无需再打开 v0.2 文件。\n",
        demote(sources[SOURCE_FILES[1]].decode("utf-8")),
        '\n<a id="management"></a>\n## 第四章：前后端 API 与资源元数据全部字段\n',
        "字段表是原 Schema 的机械展开，`oneOf/anyOf/allOf/if/then` 分支需按组合规则执行，不能将所有分支属性简单合并。严格校验以附录完整 Schema 加第二章语义为准。`#/$defs/X` 在当前 Schema 内解析；URN 引用在本文件附录三份 Schema 的 `$id` 注册表内解析，不需要网络下载或外部文件。\n",
        "### 管理命令清单\n",
        "| 序号 | 命令 |\n|---|---|",
        *[f"| {index} | `{command}` |" for index, command in enumerate(api["$defs"]["Command"]["enum"], 1)],
        "\n### 管理 API 全部定义\n",
        definition_tables(api, "API"),
        "\n### 兼容资源元数据全部定义\n",
        "此处完整保留当前 API 的依赖闭包。旧业务草稿结构并非另一个可选业务 ICD；v0.3 规则明确禁止的资源，不因兼容 Schema 结构合法而可运行。\n",
        definition_tables(parsed["input-simulator-package-v0.2.schema.json"], "META"),
        '\n<a id="wire"></a>\n## 第五章：传输、端口与原工具链\n',
        "第二章给出编码语义；本章列出全部目录条目。机器原文包含精确 header、CRC、偏移、枚举、周期、容量、通道配置和探针表。\n",
        "### 5.1 所有 PACKED_LE 字段布局\n",
        "| 消息 ID/名称 | CAN ID | 字段 | 偏移 byte | 长度 byte | 类型 | 枚举代码 |\n|---|---|---|---|---|---|---|",
    ]
    for entry in catalog["messages"]:
        for field in entry.get("fields", []):
            parts.append(f"| {entry['id']}/{entry['name']} | 0x{entry['can_id']:03X} | `{field['name']}` | {field['offset']} | {field['size']} | {field['type']} | {cell(field.get('enum_codes', '-'))} |")
    for heading, key in (("5.2 CAN FD、UDP 与视频帧精确布局", "codecs"),
                         ("5.3 全部物理通道参数", "channels"),
                         ("5.4 六条原工具链的完整声明", "toolchains"),
                         ("5.5 容量、安全、时序与替换白名单", "policy"),
                         ("5.6 模型与消息适用矩阵", "model_message_matrix"),
                         ("5.7 全部探针 ID 与名称", "probe_catalog")):
        parts.extend((f"\n### {heading}\n", "```json\n" + json.dumps(catalog[key], ensure_ascii=False, indent=2) + "\n```\n"))
    parts.extend((
        '<a id="acceptance"></a>\n## 第六章：覆盖与验收\n',
        demote(sources["input-simulator-coverage-v0.3.md"].decode("utf-8")),
        "\n### 验证边界\n",
        "附录静态报告的 STATIC_PASS 仅证明其列出的结构/覆盖/测试数据一致性；不等于服务实现、模型实际消费、硬件资格或真实 3.3 替换。Windows 软件、Linux 软件、目标实时、物理接口与正式替换应分别报告；未执行项不能合并为通过。\n",
        "### 四组件基线指纹\n",
        "指纹只由原始业务 Schema、ICD 目录、CAN FD DBC、语义契约的原始字节 SHA256 组成，再对恰含四个组件键的对象做 RFC8785 规范化并 SHA256。附录给出实际值。对汇总文件、重新格式化的 Schema 或字段表取哈希均不能替代该指纹。\n",
        '<a id="embedded"></a>\n## 附录：全部机器定义和原文快照\n',
        "这些不是附件链接，而是本文件内的完整内容。以下 14 段保留原始 UTF8 字节，BEGIN/END 标记及其后代码块用于定位；字节数是内容本身，不含代码围栏。原文件名仅作身份标识。\n",
        "三份 Schema 按各自 `$id` 注册，全部 `$ref` 可在本文件内解析。业务 Schema 对应正式业务，API Schema 对应管理请求/响应，兼容元数据 Schema 对应资源包管理；不能互相替代。DBC 还须配合共同分片/CRC/会话校验，不能单独决定业务成功。\n",
        "examples 全部是结构测试数据，golden 是 85 条编码测试片，不是已授权会话或可直接联调的完整运行包；真实资源哈希、设备校准和消费证据不得伪造。\n",
    ))
    for index, (name, label) in enumerate(zip(SOURCE_FILES, SOURCE_LABELS), 1):
        raw = sources[name]
        parts.extend((f"\n### A{index:02d} {label}\n", f"来源标识：`{name}`；字节数：{len(raw)}；SHA256：`{hashlib.sha256(raw).hexdigest()}`。\n",
                      start_marker(name) + raw.decode("utf-8") + end_marker(name)))
    return "\n".join(parts) + "\n"


def verify_document(document, directory):
    directory = Path(directory)
    encoded = document.encode("utf-8")
    embedded = {}
    for name in SOURCE_FILES:
        original = (directory / name).read_bytes()
        marker = start_marker(name).encode("ascii")
        if encoded.count(marker) != 1:
            raise ValueError(f"missing or duplicate snapshot: {name}")
        offset = encoded.index(marker) + len(marker)
        raw = encoded[offset:offset + len(original)]
        if raw != original or not encoded[offset + len(raw):].startswith(end_marker(name).encode("ascii")):
            raise ValueError(f"snapshot differs from frozen source: {name}")
        if name.endswith(".json"):
            embedded[name] = json.loads(raw)
    manifest = embedded["input-simulator-v0.3.manifest.json"]
    for entry in manifest["files"]:
        raw = (directory / entry["file"]).read_bytes()
        if len(raw) != entry["size_bytes"] or hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise ValueError(f"source manifest mismatch: {entry['file']}")
    schemas = {embedded[name]["$id"]: embedded[name] for name in SCHEMA_FILES}
    count = 0
    for root in schemas.values():
        for node in walk(root):
            if not isinstance(node, dict) or "$ref" not in node:
                continue
            ref = node["$ref"]
            identity, separator, pointer = ref.partition("#")
            target = schemas[identity] if identity else root
            if separator and pointer:
                if not pointer.startswith("/"):
                    raise ValueError(f"unsupported reference: {ref}")
                for part in pointer[1:].split("/"):
                    target = target[part.replace("~1", "/").replace("~0", "~")]
            count += 1
    catalog = embedded["input-simulator-icd-v0.3.json"]
    return {
        "status": "SINGLE_FILE_CONTENT_VERIFIED",
        "embedded_sources": len(SOURCE_FILES), "resolved_schema_references": count,
        "business_messages": len(catalog["messages"]),
        "management_commands": len(embedded["input-simulator-api-v0.3.schema.json"]["$defs"]["Command"]["enum"]),
        "golden_vectors": len(embedded["input-simulator-v0.3.golden.json"]["vectors"]),
        "physical_channels": len(catalog["channels"]), "model_bindings": len(catalog["model_bindings"]),
        "runtime_hardware_replacement": "NOT_VERIFIED_BY_THIS_CONSOLIDATION",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true", help="verify existing output without rewriting")
    args = parser.parse_args()
    directory = ROOT / "docs" / "interfaces" / "baseline"
    if args.check:
        document = args.output.read_bytes().decode("utf-8")
    else:
        document = build_document(directory)
        verify_document(document, directory)
        args.output.write_bytes(document.encode("utf-8"))
    print(json.dumps(verify_document(document, directory), ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
