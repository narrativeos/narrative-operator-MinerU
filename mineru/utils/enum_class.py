# Copyright (c) Opendatalab. All rights reserved.
from enum import Enum

class BlockType:
    IMAGE = 'image'
    TABLE = 'table'
    CHART = 'chart'
    IMAGE_BODY = 'image_body'
    TABLE_BODY = 'table_body'
    CHART_BODY = 'chart_body'
    CAPTION = 'caption'  # generic caption type (e.g., for Word documents)
    IMAGE_CAPTION = 'image_caption'
    TABLE_CAPTION = 'table_caption'
    CHART_CAPTION = 'chart_caption'
    ALGORITHM_CAPTION = 'algorithm_caption'
    FOOTNOTE = 'footnote'  # pp_layout中的vision_footnote
    IMAGE_FOOTNOTE = 'image_footnote'
    TABLE_FOOTNOTE = 'table_footnote'
    CHART_FOOTNOTE = 'chart_footnote'
    TEXT = 'text'
    TITLE = 'title'
    INTERLINE_EQUATION = 'interline_equation'
    EQUATION = "equation"  # 公式(独立公式)
    LIST = 'list'
    INDEX = 'index'
    DISCARDED = 'discarded'

    # Added in vlm 2.5
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

    # Added in pp_doclayout_v2
    ABSTRACT = "abstract"
    DOC_TITLE = "doc_title"
    PARAGRAPH_TITLE = "paragraph_title"
    VERTICAL_TEXT = "vertical_text"
    HEADER_IMAGE = "header_image"
    FOOTER_IMAGE = "footer_image"
    FORMULA_NUMBER = "formula_number"

class ContentType:
    IMAGE = 'image'
    TABLE = 'table'
    CHART = 'chart'
    TEXT = 'text'
    INTERLINE_EQUATION = 'interline_equation'
    INLINE_EQUATION = 'inline_equation'
    EQUATION = 'equation'
    HYPERLINK = 'hyperlink'


class ContentTypeV2:
    CODE = 'code'
    ALGORITHM = "algorithm"
    EQUATION_INTERLINE = 'equation_interline'
    IMAGE = 'image'
    TABLE = 'table'
    CHART = 'chart'
    TABLE_SIMPLE = 'simple_table'
    TABLE_COMPLEX = 'complex_table'
    LIST = 'list'
    LIST_TEXT = 'text_list'
    LIST_REF = 'reference_list'
    INDEX = 'index'
    TITLE = 'title'
    PARAGRAPH = 'paragraph'
    SPAN_TEXT = 'text'
    SPAN_EQUATION_INLINE = 'equation_inline'
    SPAN_PHONETIC = 'phonetic'
    SPAN_MD = 'md'
    SPAN_CODE_INLINE = 'code_inline'
    PAGE_HEADER = "page_header"
    PAGE_FOOTER = "page_footer"
    PAGE_NUMBER = "page_number"
    PAGE_ASIDE_TEXT = "page_aside_text"
    PAGE_FOOTNOTE = "page_footnote"


class MakeMode:
    MM_MD = 'mm_markdown'
    NLP_MD = 'nlp_markdown'
    CONTENT_LIST = 'content_list'
    CONTENT_LIST_V2 = 'content_list_v2'


class ModelPath:
    vlm_root_hf = "opendatalab/MinerU2.5-Pro-2605-1.2B"
    vlm_root_modelscope = "OpenDataLab/MinerU2.5-Pro-2605-1.2B"
    pipeline_root_modelscope = "OpenDataLab/PDF-Extract-Kit-1.0"
    pipeline_root_hf = "opendatalab/PDF-Extract-Kit-1.0"
    pp_doclayout_v2 = "models/Layout/PP-DocLayoutV2"
    unimernet_small = "models/MFR/unimernet_hf_small_2503"
    pp_formulanet_plus_m = "models/MFR/pp_formulanet_plus_m"
    pytorch_paddle = "models/OCR/paddleocr_torch"
    slanet_plus = "models/TabRec/SlanetPlus/slanet-plus.onnx"
    unet_structure = "models/TabRec/UnetStructure/unet.onnx"
    paddle_table_cls = "models/TabCls/paddle_table_cls/PP-LCNet_x1_0_table_cls.onnx"


class SplitFlag:
    CROSS_PAGE = 'cross_page'
    LINES_DELETED = 'lines_deleted'


class ImageType:
    PIL = 'pil_img'
    BASE64 = 'base64_img'


class NotExtractType(Enum):
    TEXT = BlockType.TEXT
    TITLE = BlockType.TITLE
    HEADER = BlockType.HEADER
    FOOTER = BlockType.FOOTER
    PAGE_NUMBER = BlockType.PAGE_NUMBER
    PAGE_FOOTNOTE = BlockType.PAGE_FOOTNOTE
    REF_TEXT = BlockType.REF_TEXT
    TABLE_CAPTION = BlockType.TABLE_CAPTION
    IMAGE_CAPTION = BlockType.IMAGE_CAPTION
    TABLE_FOOTNOTE = BlockType.TABLE_FOOTNOTE
    IMAGE_FOOTNOTE = BlockType.IMAGE_FOOTNOTE
    CODE_CAPTION = BlockType.CODE_CAPTION
    PHONETIC = BlockType.PHONETIC


class PageType:
    """页面类型枚举，用于标识整页的语义角色。

    页面类型基于布局分析结果（block-level）通过规则推断得出，
    不依赖额外的深度学习模型。
    """
    # 封面相关
    COVER = "cover"                      # 封面页：文档封面，通常包含主标题、作者、日期等
    HALF_TITLE = "half_title"            # 半标题页：只有书名/文档名的简化标题页（扉页前的那页）
    COPYRIGHT = "copyright"              # 版权页：包含版权信息、ISBN 等
    COLOPHON = "colophon"                # 版本记录页：排版/印刷信息页面
    BACK_COVER = "back_cover"            # 封底页：文档最后一页，内容稀疏
    PREFACE = "preface"                  # 前置页：序/前言/作者简介等正文前内容（front matter）

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

    # 特殊内容
    BLANK = "blank"                      # 空白页：几乎没有有效内容
    IMAGE_DOMINANT = "image_dominant"    # 图片为主页：以图片/图表为主，文本较少
