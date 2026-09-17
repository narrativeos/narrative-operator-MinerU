# Copyright (c) Opendatalab. All rights reserved.
"""页面类型与块类型常量（fork 扩展）。

MinerU 4.0 将块类型枚举迁移到了 docvortex（``docvortex.schema.BlockType``），
但 fork 的页面类型分类器（``mineru/backend/pipeline/page_type_classifier.py``）
仍需要 3.x 时代的字符串常量（含 4.0 已不再产出的历史类型，如 ``title``、
``abstract``）。本模块提供：

- :class:`PageType`：页面语义类型常量（从 3.x ``mineru.utils.enum_class`` 迁移）。
- :class:`BlockType`：块类型字符串常量（与 4.0 raw model_list 的 ``type``
  字段取值一致，并保留历史类型以兼容分类器规则）。

分类器对 ``block.get("type")``（普通字符串）与这些常量做比较，因此这里使用
普通字符串常量而非 Enum，保持与 3.x 行为完全一致。
"""


class PageType:
    """页面类型枚举，用于标识整页的语义角色。

    页面类型基于布局分析结果（block-level）通过规则推断得出，
    不依赖额外的深度学习模型。
    """

    # 封面相关
    COVER = "cover"                      # 封面页：文档封面，通常包含主标题、作者、日期等
    HALF_TITLE = "half_title"            # 半标题页：只有书名/文档名的简化标题页（扉页前的那页）
    TITLE_PAGE = "title_page"            # 扉页页：标准扉页（标准名称+编号+主编/批准部门/施行日期）
    ANNOUNCEMENT = "announcement"        # 发布公告页：主管部门发布/批准标准的公告（第X号）
    PUBLICATION_INFO = "publication_info"  # 出版信息页：出版社/地址/印张/定价等出版元数据
    COPYRIGHT = "copyright"              # 版权页：包含版权信息、ISBN 等
    COLOPHON = "colophon"                # 版本记录页：排版/印刷信息页面
    BACK_COVER = "back_cover"            # 封底页：文档最后一页，内容稀疏
    PREFACE = "preface"                  # 前置页：序/前言/作者简介等正文前内容（front matter）
    FOREWORD = "foreword"                # 前言页：前言/修订说明/起草单位等（含续页）

    # 导航相关
    TOC = "toc"                          # 目录页：以目录/索引内容为主的页面
    INDEX = "index"                      # 索引页：按字母/拼音排序的索引条目页面
    GLOSSARY = "glossary"                # 术语表页：术语及其解释的页面

    # 正文结构
    CHAPTER_START = "chapter_start"      # 章节起始页：以章节标题开头的页面
    BODY = "body"                        # 正文页：常规内容页面（最常见）
    APPENDIX = "appendix"                # 附录页
    ACKNOWLEDGMENT = "acknowledgment"    # 致谢页
    REFERENCE = "reference"              # 参考文献页
    NORMATIVE_REFERENCES = "normative_references"  # 引用标准页：规范性引用文件/引用标准

    # 特殊内容
    BLANK = "blank"                      # 空白页：几乎没有有效内容
    IMAGE_DOMINANT = "image_dominant"    # 图片为主页：以图片/图表为主，文本较少


class BlockType:
    """块类型字符串常量（4.0 raw model_list 取值 + 3.x 历史类型）。

    4.0 的 raw model_list 中 ``type`` 字段取值与 ``docvortex.schema.BlockType``
    一致；此处额外保留 3.x 历史类型（``title``、``abstract`` 等），4.0 流水线
    已将其归一化，分类器规则中引用这些常量时自然不命中，行为安全。
    """

    IMAGE = "image"
    TABLE = "table"
    CHART = "chart"
    IMAGE_BODY = "image_body"
    TABLE_BODY = "table_body"
    CHART_BODY = "chart_body"
    CAPTION = "caption"
    IMAGE_CAPTION = "image_caption"
    TABLE_CAPTION = "table_caption"
    CHART_CAPTION = "chart_caption"
    ALGORITHM_CAPTION = "algorithm_caption"
    FOOTNOTE = "footnote"
    IMAGE_FOOTNOTE = "image_footnote"
    TABLE_FOOTNOTE = "table_footnote"
    CHART_FOOTNOTE = "chart_footnote"
    TEXT = "text"
    TITLE = "title"  # 3.x 历史类型，4.0 已归一化为 doc_title/paragraph_title
    INTERLINE_EQUATION = "interline_equation"
    EQUATION = "equation"
    LIST = "list"
    INDEX = "index"
    DISCARDED = "discarded"
    CODE = "code"
    CODE_BODY = "code_body"
    CODE_CAPTION = "code_caption"
    CODE_FOOTNOTE = "code_footnote"
    ALGORITHM = "algorithm"
    REF_TEXT = "ref_text"
    PHONETIC = "phonetic"
    HEADER = "header"
    FOOTER = "footer"
    PAGE_NUMBER = "page_number"
    ASIDE_TEXT = "aside_text"
    PAGE_FOOTNOTE = "page_footnote"
    ABSTRACT = "abstract"  # 3.x 历史类型，4.0 已归一化为 text
    DOC_TITLE = "doc_title"
    PARAGRAPH_TITLE = "paragraph_title"
    VERTICAL_TEXT = "vertical_text"
    HEADER_IMAGE = "header_image"
    FOOTER_IMAGE = "footer_image"
    FORMULA_NUMBER = "formula_number"


__all__ = ["BlockType", "PageType"]
