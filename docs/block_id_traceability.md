# block_id 溯源字段说明（下游应用指南）

**版本**: v1.1
**日期**: 2026-09-18
**适用 MinerU**: 4.0.1（fork）
**影响范围**: model_output.json, middle_json.json, content_list.json, content_list_v2.json

> **v1.1 变更**：身份串调整为 **页码 + bbox + 内容摘要**。
> 1. **加入 bbox**：block 的页面位置参与身份，同页同内容但位置不同的 block 必然不同 id；
> 2. **移除块序号（`index`）与类型（`type`）**：前序 block 增删导致的序号位移
>    **不再**改变已有 block 的 `block_id`（v1.0 下会全部变化）。
> v1.0 及之前产出的 `block_id` 与本版本**不兼容**，升级后重新解析即可得到新 id。
>
> **v1.0 变更**：`block_id` 由随机 UUIDv4 改为**确定性 UUIDv5**。
> 同一文档、同一解析输出下，同一 block 在多次运行、不同机器间得到完全相同的
> `block_id`，可用于跨次运行的 diff、变更追踪与稳定引用。
> 此前版本（随机 UUIDv4）产出的 `block_id` 与新算法**不兼容**，
> 升级后重新解析即可得到新 id。

---

## 一、概述

MinerU 4.0 的共享文档协议（MiddleJson）中 block 为严格 schema
（`extra='forbid'`），不再携带 3.x 时代的 `block_id` 字段。本 fork 在
**仅 PDF 解析路径**上重新引入 block 级溯源：

- 每个 block 分配一个 `block_id`（UUIDv5 字符串，36 字符）；
- `block_id` 直接写入 `model_output.json` 的 block；
- 严格产物（middle_json.json 等）通过顶层 `extensions.mineru_block_ids`
  映射表按「页码 + 块序号」反查；
- Content List V1/V2 的每个条目直接携带 `block_id` / `block_ids`。

**非 PDF 输入（EPUB/HTML/OFD/Office/CSV 等）不分配 `block_id`**，
相关字段不存在，下游需按可选字段处理。

---

## 二、block_id 的派生规则

`block_id` 是 UUIDv5（基于名称的确定性哈希），由以下身份串派生：

```
identity = f"{page_idx}:{bbox_key}:{content_digest}"
block_id = uuid5(NAMESPACE, identity)
```

| 成分 | 说明 |
|------|------|
| `NAMESPACE` | 固定常量 `uuid5(NAMESPACE_URL, "https://mineru.net/block-id")`，跨进程/跨机器可复现 |
| `page_idx` | 页面在文档中的序号（0 起） |
| `bbox_key` | block 的 `bbox`（4 个归一化坐标）格式化为 5 位小数字符串，如 `0.10000,0.10000,0.50000,0.20000`；bbox 缺失或非法时回退为 `pos:{页内位置序号}` |
| `content_digest` | `content` 字段经规范化 JSON 序列化（`sort_keys`、紧凑分隔符）后的 SHA-256 摘要；无 `content` 字段时为空串 |

> bbox 保留 5 位小数（1e-5，约 A4 页宽的 0.01%）：足以区分页面上不同的
> block，同时容忍布局/OCR 输出的常见位置抖动（1e-3 量级）与浮点表示噪声。

### 2.1 稳定性保证

**相同输入 + 相同解析输出 ⇒ 相同 `block_id`**，与运行次数、进程、机器无关。

### 2.2 何时会变

以下情况 `block_id` 会变化，均为预期行为：

| 变化原因 | 说明 |
|----------|------|
| block 内容变化 | 内容摘要参与身份；内容变了即视为"另一个 block" |
| block bbox 变化 | 布局/OCR 输出导致位置变化（超过 5 位小数精度，即 > 1e-5）即视为"另一个 block" |
| block 换页 | `page_idx` 参与身份 |
| 派生算法升级 | 见本文档版本历史；升级后需重新解析 |

**不会变的情况**（v1.1 起）：前序 block 增删导致的 `index` 序号位移、
block 类型重分类（如 `text` → `paragraph_title`）均**不改变**已有 block 的 id。

### 2.3 作用域

`block_id` 是**文档内唯一**，不是全局唯一：两本不同文档中，
同页同 bbox 同内容的 block 会得到相同 id。
**下游若跨文档存储（如数据库主键），必须自行附加文档级命名空间**
（如 `doc_id + "/" + block_id`）。

### 2.4 幂等与自定义 id

分配逻辑幂等：已存在 `block_id` 的 block 不会被重算。
上游若在 raw model_list 中预置了自定义 `block_id`，将原样保留并透传到
`mineru_block_ids` 映射与 Content List 输出。

---

## 三、各输出格式中的体现

### 3.1 model_output.json（ModelJson）

每个 block 直接携带 `block_id` 字段：

```json
{
    "pages": [
        [
            {
                "type": "text",
                "index": 0,
                "bbox": [0.1, 0.1, 0.5, 0.2],
                "content": [{"type": "text", "content": "hello"}],
                "block_id": "3f2c…（36 字符 UUIDv5）"
            }
        ]
    ]
}
```

这是 `block_id` 的**权威来源**。

### 3.2 middle_json.json（MiddleJson）

严格 schema 的 block **不携带** `block_id`；映射表位于顶层
`extensions.mineru_block_ids`：

```json
{
    "pages": [
        {
            "page_idx": 0,
            "blocks": [
                {"type": "text", "index": 0, "bbox": [0.1, 0.1, 0.5, 0.2], "content": [...]}
            ]
        }
    ],
    "extensions": {
        "mineru_block_ids": {
            "0": {"0": "3f2c…", "1": "a91d…"}
        }
    }
}
```

映射结构：`{str(page_idx): {str(block_index): block_id}}`。
反查方式：取 block 的 `page_idx` 与 `index` 字段作为两级 key。

> 注意：乱码 block 在分配 id **之前**被删除，因此 `block_index`
> 可能出现**空洞**（如某页只有 `"0"`、`"2"`），属正常现象。

### 3.3 content_list.json / content_list_v2.json

每个条目直接携带溯源字段（仅 PDF 且映射存在时写入）：

```json
{
    "type": "text",
    "page_idx": 0,
    "bbox": [[0.1, 0.1], [0.5, 0.2]],
    "block_id": "3f2c…",
    "text": "hello"
}
```

| 字段 | 出现条件 | 说明 |
|------|----------|------|
| `block_id` | 条目对应单个 block | 该 block 的 id |
| `block_ids` | 条目对应参考文献组（多个 block 合并渲染） | 组内各 block 的 id 数组，按块序排列 |
| *两者都不存在* | 非 PDF 输入，或该页无映射 | 按可选字段处理 |

### 3.4 structured_content.json / markdown

**不包含** `block_id`（structured_content 不输出 extensions，
markdown 仅有 `page_type` 注释）。需要溯源时请使用
`middle_json.json` 的 `extensions.mineru_block_ids` 反查。

---

## 四、下游接入建议

### 4.1 推荐用法

1. **稳定引用**：以 `block_id` 作为 block 的业务主键（附加文档级前缀）；
2. **跨次 diff**：对同一文档两次解析结果按 `block_id` 对齐，
   id 相同即同一 block，可直接比较内容/几何变化；
3. **反查链路**：`middle_json.json` block → `(page_idx, index)` →
   `extensions.mineru_block_ids` → `block_id` → `model_output.json` 中的原始 block。

### 4.2 示例代码

```python
import json

middle = json.loads(open("middle_json.json").read())
block_ids = middle.get("extensions", {}).get("mineru_block_ids", {})

for page in middle["pages"]:
    page_map = block_ids.get(str(page["page_idx"]), {})
    for block in page["blocks"]:
        block_id = page_map.get(str(block.get("index")))
        if block_id:
            # 用 block_id 关联下游数据
            ...
```

### 4.3 兼容性要求

- `block_id`、`block_ids`、`mineru_block_ids` 均为**可选字段**：
  非 PDF 输入、旧版本输出中不存在，读取时必须容错；
- 不要解析 `block_id` 的内部结构，只当作不透明字符串；
- 派生算法变更会随本文档版本历史公告，**不会**静默变化。

---

## 五、常见问题

**Q: 为什么 middle.json 的 block 上没有 block_id？**
A: MinerU 4.0 共享协议对 block 使用严格 schema（禁止额外字段），
fork 不修改共享协议，改为通过 `extensions.mineru_block_ids` 映射透传。

**Q: 同一页两个内容完全相同的 block，id 会冲突吗？**
A: 正常布局下不会。bbox 参与身份，同页同内容但位置不同的 block id 必然不同；
跨页同内容同样因 `page_idx` 不同而不同。
极端情况下（同页、同 bbox、同内容的两个 block，即完全重叠）会得到相同 id，
这在有效布局中不会出现；无 bbox 的 block 回退为页内位置序号区分。

**Q: 两次解析同一文档，某个 block 的 id 变了，一定是 bug 吗？**
A: 不一定。内容、bbox、页码任一变化都会改变 id（见 2.2）；
而序号位移、类型重分类不会改变 id。
若解析输出完全一致而 id 不同，才属于异常（请检查 MinerU 版本是否跨了
派生算法升级点）。

**Q: 非 PDF 文档能拿到 block_id 吗？**
A: 目前不能。溯源仅覆盖 PDF 解析路径。

**Q: 旧输出（随机 UUIDv4）能继续用吗？**
A: 能读，但 id 与新算法不互通，无法用于跨版本 diff。建议重新解析。

---

## 六、联系信息

如有问题，请联系 MinerU 开发团队。
