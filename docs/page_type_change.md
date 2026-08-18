# 页面类型（page_type）字段变更说明

**版本**: v2.0  
**日期**: 2026-08-18  
**影响范围**: middle.json, content_list.json, content_list_v2.json, markdown 输出

---

## 一、变更概述

本次更新增强了页面类型分类器，主要改进包括：

1. **新增 `page_type_secondary` 字段**：支持混合类型页面（如目录+版权页）
2. **新增杂志/生活类目录页识别**：能正确识别 `010京沪高铁` 等杂志风格目录条目
3. **优化版权/版本记录页检测**：避免杂志目录板块标题中的英文词（如 `印象Impression`）误触发版权检测

---

## 二、字段说明

### 2.1 `page_type`（主类型）— 保持不变

| 值 | 说明 |
|----|------|
| `cover` | 封面页 |
| `half_title` | 半标题页（扉页） |
| `copyright` | 版权页 |
| `colophon` | 版本记录页 |
| `back_cover` | 封底页 |
| `preface` | 前置页（序/前言/作者简介等） |
| `toc` | **目录页**（含杂志/生活类目录） |
| `index` | 索引页 |
| `glossary` | 术语表页 |
| `chapter_start` | 章节起始页 |
| `body` | 正文页 |
| `appendix` | 附录页 |
| `acknowledgment` | 致谢页 |
| `reference` | 参考文献页 |
| `blank` | 空白页 |
| `image_dominant` | 图片为主页 |

**向后兼容**: `page_type` 字段的取值和含义与之前完全一致，下游软件无需修改即可正常工作。

### 2.2 `page_type_secondary`（次要类型）— **新增字段**

当页面同时包含多种类型内容时，此字段标记次要类型。

| 值 | 说明 | 示例场景 |
|----|------|----------|
| `copyright` | 页面同时包含目录和版权信息 | 杂志最后一页：目录 + ISSN/印刷单位 |
| `colophon` | 页面同时包含目录和版本记录 | 目录页 + 印次/印数信息 |
| *不存在* | 页面只有单一类型 | 纯目录页、纯正文页等 |

**注意**: 此字段是可选的。如果页面只有单一类型，则该字段不存在（或为 null）。

---

## 三、各输出格式中的体现

### 3.1 middle.json

```json
{
    "pdf_info": [
        {
            "preproc_blocks": [...],
            "page_type": "toc",
            "page_type_secondary": "copyright"
        }
    ]
}
```

### 3.2 content_list.json / content_list_v2.json

每个段落对象和页面包装器中都会包含这两个字段：

```json
{
    "page_type": "toc",
    "page_type_secondary": "copyright",
    "contents": [...]
}
```

### 3.3 Markdown 输出

```markdown
<!-- page_type: toc; page_type_secondary: copyright -->
# 专题 Feature
...
```

如果无次要类型，格式为：
```markdown
<!-- page_type: toc -->
```

---

## 四、典型场景示例

### 场景 1：纯杂志目录页

```
页面内容：
  印象Impression
    010京沪高铁，让旅客出行更美好
    012铁路客票，便民惠旅新升级
  专题 Feature
    014高铁上看风景
    016高邮活虾

结果：
  page_type = "toc"
  page_type_secondary = 不存在
```

### 场景 2：目录 + 版权混合页

```
页面内容：
  寻味Cuisine
    070 黔味越山海，酸香漫京城
    076 羊城餐桌十二时辰
  [下方有] 印刷单位：北京盛通印刷股份有限公司
           ISSN: xxx-xxx
           著作权声明...

结果：
  page_type = "toc"
  page_type_secondary = "copyright"
```

### 场景 3：纯版权页

```
页面内容：
  著作权所有
  ISBN: 978-7-xxx
  出版者：xxx出版社

结果：
  page_type = "copyright"
  page_type_secondary = 不存在
```

---

## 五、下游软件适配建议

### 5.1 最小适配（推荐）

如果下游软件只关心主类型，**无需任何修改**。`page_type` 字段的含义和取值保持不变。

### 5.2 完整适配

如果需要利用次要类型信息：

```python
page_type = page_info.get('page_type')           # 主类型（始终存在）
page_type_secondary = page_info.get('page_type_secondary')  # 次要类型（可选）

if page_type == 'toc':
    if page_type_secondary == 'copyright':
        # 处理目录+版权混合页
        pass
    else:
        # 处理纯目录页
        pass
```

### 5.3 过滤逻辑调整

如果之前有类似逻辑：
```python
if page_type in ['copyright', 'colophon']:
    skip_page()
```

现在需要考虑：`page_type` 为 `toc` 但 `page_type_secondary` 为 `copyright` 的页面。
根据业务需求决定：
- 如果想保留目录内容：只检查 `page_type == 'toc'` 即可
- 如果想跳过所有含版权信息的页面：
  ```python
  if page_type == 'copyright' or page_type_secondary == 'copyright':
      skip_page()
  ```

---

## 六、测试数据

使用真实杂志 PDF 测试，4页分类结果如下：

| 页码 | page_type | page_type_secondary | 说明 |
|------|-----------|-------------------|------|
| 1 | `preface` | — | 前置页 |
| 2 | `toc` | — | 纯杂志目录页 |
| 3 | `toc` | `copyright` | 目录+版权混合页 |
| 4 | `chapter_start` | — | 章节起始页 |

---

## 七、常见问题

**Q: `page_type_secondary` 是否可能为 `toc`？**  
A: 不会。`toc` 始终是主类型，不会作为次要类型出现。

**Q: 是否可能同时有 `page_type_secondary` 和第三个类型？**  
A: 目前不支持三级类型。如果页面有三种以上类型混合，`page_type` 为最主要的类型，`page_type_secondary` 为次重要的类型。

**Q: 旧的 middle.json 文件（无 `page_type_secondary` 字段）能否被新软件读取？**  
A: 可以。`page_type_secondary` 是可选字段，不存在时等同于无次要类型。

---

## 八、联系信息

如有问题，请联系 MinerU 开发团队。