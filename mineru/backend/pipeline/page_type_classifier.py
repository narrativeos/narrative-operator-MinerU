# Copyright (c) Opendatalab. All rights reserved.
"""页面类型分类器 - 基于规则推断页面语义类型。

根据布局分析结果（block-level）中的 block 类型分布、位置、文本内容等特征，
通过启发式规则推断每个页面的类型（封面、目录、正文、章节起始等）。

不依赖额外的深度学习模型，所有推断基于已有的 layout 分析结果。
"""
import re
from typing import Dict, List, Optional, Set

from mineru.utils.enum_class import BlockType, PageType


# ─── 阈值常量 ───────────────────────────────────────────────────────────

# 空白页：有效 block 数阈值
BLANK_BLOCK_THRESHOLD = 0

# 封面/封底：内容稀疏阈值（有效 block 数）
COVER_MAX_BLOCKS = 8
BACK_COVER_MAX_BLOCKS = 3

# 目录页：index block 占比阈值
TOC_INDEX_RATIO_THRESHOLD = 0.5

# 目录页（行密度增强）：候选页 TOC 行阈值 / 主导区间占比 / 最短区间页数
# 候选阈值取 2：国标目录续页（如"25 接地装置 …… (69)"）TOC 行常不足 3 行，
# 取 2 可让续页与主目录页合并为同一区间；正文误报由"最短区间页数 + 主导区间占比"兜底。
TOC_LINE_CANDIDATE_THRESHOLD = 2
TOC_DOMINANT_RATIO = 0.2
TOC_MIN_RANGE_PAGES = 2

# 参考文献页：ref_text block 占比阈值
REFERENCE_RATIO_THRESHOLD = 0.5

# 章节起始页：标题 block 在页面顶部占比
CHAPTER_START_TITLE_TOP_RATIO = 0.3

# 图片为主页：visual block 面积占比阈值
IMAGE_DOMINANT_AREA_RATIO = 0.7

# 半标题页：block 数极少且只有一个标题
HALF_TITLE_MAX_BLOCKS = 3

# 版权页关键词
COPYRIGHT_KEYWORDS = [
    "copyright", "isbn", "©", "著作权", "版权所有", "版权",
    "copyright page", "all rights reserved",
]

# 版本记录页关键词
COLOPHON_KEYWORDS = [
    "版本记录", "排印", "印刷", "印次", "印数", "开本", "字数",
    "版次", "印张", "collophon", "printing", "impression",
]

# 致谢页关键词
ACKNOWLEDGMENT_KEYWORDS = [
    "致谢", "acknowledgment", "acknowledgements", "thanks", "感谢",
]

# 附录页关键词
APPENDIX_KEYWORDS = [
    "附录", "appendix", "附录", "supplement",
]

# 附录标题模式（"附 录 A" / "附录A" / "附录 A" / "Appendix A"，后跟字母/数字编号）。
# 附录起始页的标题常以 TEXT 块（居中大字）呈现而非 TITLE 块，
# 故用独立模式匹配，要求 block 文本以附录标题开头（^ 锚定），
# 避免正文中"按照附录 A 的要求"等引用误触发。
_APPENDIX_TITLE_PATTERN = re.compile(
    r"^(?:附\s*录|appendix)\s*[A-Z0-9]", re.IGNORECASE
)

# 术语表页关键词
GLOSSARY_KEYWORDS = [
    "术语表", "glossary", "术语", "词汇表", "名词解释", "terminology",
]

# 索引页关键词
INDEX_KEYWORDS = [
    "索引", "index", "字母索引", "主题索引", "人名索引", "书名索引",
]


# ─── 目录页检测增强（TOC 行密度 + 连续区间 + 主导区间）───────────────

# TOC 条目行模式（章节号 + 引导符 + 页码）。
# 引导符：U+2026 省略号 / U+00B7 中圆点 / ASCII '.' 均要求 2 个以上
# （避免把标题中的小数点如 "4.0" 误判为引导符，见 Phase 0 报告 Q3；
# 单点引导符会把正文 "12.2 xxx …… 见表 22。" 误判为目录行）。
# 负向前瞻排除 "见表/见 表" 行：正文 "…… 见表 N。" 是表格引用而非目录条目。
# 页码允许括号包裹（国标目录形如 "1 总 则 …… (1)"）。
_TOC_LINE_PATTERN = re.compile(
    r"(?:第[一二三四五六七八九十百千\d]+[篇章节部]|[\d]+(?:\.[\d]+)*)\s*"
    r".*?(?!\s*见\s*表)(?:[…]{2,}|[·]{2,}|\.{2,})\s*[（(]?\s*[\dIVXivx]+\s*[)）]?"
)

# 杂志/生活类目录行模式：页码(2-3位数字) + 可选空白 + 文章标题(至少7个非数字字符)
# 例如: "010京沪高铁，让旅客出行更美好" (无空格), "070 黔味越山海，酸香漫京城" (有空格)
# 注意：行尾为列表标点（；;。等）的行不算目录行 —— 正文编号列表项
# （如 "19 测量轴电压；"）与目录行同为"数字+文字"形态，但目录条目不以列表标点结尾。
# 负向前瞻 (?!\.\d)：页码数字后紧跟 ".数字" 的是条款号（如 "12.2 集合式电容器"、
# "19.1 绝缘油"），属正文章节标题而非杂志目录行，必须排除。
# 标题长度下限取 7（[^\d\s] + .{6,}）：正文章标题（如 "16 串联补偿装置"，标题 6 字）
# 与杂志目录行同为"数字+文字"形态，但杂志文章标题通常更长；短标题（<7 字）的章
# 标题不应被计为目录行，否则正文页会被误判为目录页。
_MAGAZINE_TOC_LINE_PATTERN = re.compile(
    r"^\s*\d{2,3}(?!\.\d)\s?[^\d\s].{6,}(?<![；;。．,，、:：!！?？])$"
)

# 杂志目录板块标题模式：中文标题 + 英文标题（空格分隔）
# 例如: "印象Impression", "专题 Feature", "畅游 Journey", "寻味Cuisine"
_MAGAZINE_TOC_SECTION_PATTERN = re.compile(
    r"[一-龥]{1,6}\s*[A-Za-z]{2,}"
)

# 杂志目录行阈值：至少 N 行杂志类目录条目才认为是目录页
MAGAZINE_TOC_LINE_THRESHOLD = 5

# 版权页专用关键词（更严格，避免与杂志TOC板块标题中的英文词混淆）
# 这些关键词通常只出现在真正的版权/出版信息中
_STRICT_COPYRIGHT_KEYWORDS = [
    "isbn", "©", "著作权", "版权所有", "copyright page", "all rights reserved",
    "ISSN", "CN", "出版者", "发行人", "publisher",
]

# 版本记录页专用关键词（更严格）
_STRICT_COLOPHON_KEYWORDS = [
    "版本记录", "排印", "印刷单位", "印次", "印数", "开本", "字数",
    "版次", "印张", "collophon", "printing", "出版日期",
]

# ─── 版权页/版本记录页结构化信号 ───────────────────────────────────────
# 真正的版权页/版本记录页由"结构化元数据"定义，而非单个通用词。
# 通用词（版权/著作权/印刷/开本等）在出版类书籍正文中高频出现，
# 仅凭关键词会出现大量误判（如《出版学基础》正文：67 版权 + 140 版本记录误判）。

# 版权页强信号：ISBN 后跟数字 / CIP 数据 / 定价+元 / ©
_ISBN_PATTERN = re.compile(r"ISBN\s*[:：]?\s*\d", re.IGNORECASE)
_CIP_PATTERN = re.compile(r"图书在版编目|CIP\s*数据", re.IGNORECASE)
_PRICE_PATTERN = re.compile(r"定价\s*[:：]?\s*[\d.]+\s*元")

# 版本记录页字段（"标签: 值"元数据格式，避免正文中"开本/印张"等词误触发）
_COLOPHON_FIELD_PATTERNS = [
    re.compile(r"印次\s*[:：]?\s*\d"),
    re.compile(r"印数\s*[:：]?\s*[\d.]+"),
    re.compile(r"开本\s*[:：]?\s*[\d一二三四五六七八九十大中小]"),
    re.compile(r"印张\s*[:：]?\s*[\d.]+"),
    re.compile(r"字数\s*[:：]?\s*[\d.]+"),
    re.compile(r"版次\s*[:：]?\s*\d"),
]
# 版本记录页判定所需的最少"标签: 值"字段数
COLOPHON_MIN_FIELDS = 3

# 目录页页眉关键词（国标目录页眉为"目次"，书籍为"目录"）
_TOC_HEADER_PATTERN = re.compile(r"目\s*[录次]|CONTENTS", re.IGNORECASE)


# OCR 输出常含 <sub>/<sup> 行内标签（如 "测量轴电压<sub>；</sub>"），
# 行级模式匹配前需剥离，否则行尾标点检查等规则会因标签干扰而失效。
_INLINE_TAG_PATTERN = re.compile(r"</?(?:sub|sup)>", re.IGNORECASE)


def _strip_inline_tags(text: str) -> str:
    """剥离 <sub>/<sup> 行内标签，还原纯文本。"""
    return _INLINE_TAG_PATTERN.sub("", text)


def _count_toc_lines_in_page(page_info: Dict) -> int:
    """统计页面文本中 TOC 条目行数（学术型 + 杂志型）。"""
    total = 0
    for block in page_info.get("preproc_blocks", []):
        text = ""
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text += str(span.get("content", ""))
        for ln in _strip_inline_tags(text).split("\n"):
            if _TOC_LINE_PATTERN.search(ln):
                total += 1
            elif _MAGAZINE_TOC_LINE_PATTERN.search(ln.strip()):
                total += 1
    return total


def _count_magazine_toc_lines_in_page(page_info: Dict) -> int:
    """统计页面中杂志类目录条目行数（页码数字 + 文章标题格式）。"""
    total = 0
    for block in page_info.get("preproc_blocks", []):
        text = ""
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text += str(span.get("content", ""))
        for ln in _strip_inline_tags(text).split("\n"):
            if _MAGAZINE_TOC_LINE_PATTERN.search(ln.strip()):
                total += 1
    return total


def _page_has_magazine_toc_section(blocks: List[Dict]) -> bool:
    """检查页面是否有杂志目录板块标题（中文+英文标题模式）。"""
    title_types = {BlockType.DOC_TITLE, BlockType.PARAGRAPH_TITLE, BlockType.TITLE}
    for block in blocks:
        if block.get("type") in title_types:
            block_text = ""
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    block_text += span.get("content", "")
            if _MAGAZINE_TOC_SECTION_PATTERN.search(block_text):
                return True
    return False


def _page_is_magazine_toc(page_info: Dict) -> bool:
    """判断页面是否为杂志/生活类目录页。

    判定条件：
    - 5+ 杂志类目录行，或
    - 3+ 杂志类目录行 + 杂志板块标题
    """
    mag_toc_count = _count_magazine_toc_lines_in_page(page_info)
    blocks = page_info.get("preproc_blocks", [])
    has_section = _page_has_magazine_toc_section(blocks)
    if mag_toc_count >= MAGAZINE_TOC_LINE_THRESHOLD:
        return True
    if mag_toc_count >= 3 and has_section:
        return True
    return False


def _has_strict_copyright_in_non_toc_blocks(page_info: Dict) -> bool:
    """检查页面是否有真正的版权信息（在非TOC板块标题的block中）。
    
    用于区分：
    - 真正的版权页（有ISBN、著作权声明等独立block）
    - 杂志TOC页面（板块标题中的英文词如"Impression"误触发版权检测）
    """
    title_types = {BlockType.DOC_TITLE, BlockType.PARAGRAPH_TITLE, BlockType.TITLE}
    for block in page_info.get("preproc_blocks", []):
        # 跳过TOC板块标题block（避免"印象Impression"等误触发）
        if block.get("type") in title_types:
            block_text = ""
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    block_text += span.get("content", "")
            if _MAGAZINE_TOC_SECTION_PATTERN.search(block_text):
                continue
        # 检查非标题block中的严格版权关键词
        block_text = ""
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                block_text += span.get("content", "")
        if _contains_keyword(block_text, _STRICT_COPYRIGHT_KEYWORDS):
            return True
    return False


def _has_strict_colophon_in_non_toc_blocks(page_info: Dict) -> bool:
    """检查页面是否有真正的版本记录信息（在非TOC板块标题的block中）。
    
    用于区分：
    - 真正的版本记录页（有印刷单位、印次、印数等独立block）
    - 杂志TOC页面（板块标题中的英文词如"Impression"误触发版本记录检测）
    """
    title_types = {BlockType.DOC_TITLE, BlockType.PARAGRAPH_TITLE, BlockType.TITLE}
    for block in page_info.get("preproc_blocks", []):
        # 跳过TOC板块标题block
        if block.get("type") in title_types:
            block_text = ""
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    block_text += span.get("content", "")
            if _MAGAZINE_TOC_SECTION_PATTERN.search(block_text):
                continue
        # 检查非标题block中的严格版本记录关键词
        block_text = ""
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                block_text += span.get("content", "")
        if _contains_keyword(block_text, _STRICT_COLOPHON_KEYWORDS):
            return True
    return False


def _is_copyright_page(block_text: str) -> bool:
    """判断是否为版权页：需至少一个结构化强信号。

    仅凭"版权/著作权/版权所有"等通用词不足以判定（出版类书籍正文高频出现），
    必须出现 ISBN/CIP/定价/© 等结构化元数据信号。
    """
    if _ISBN_PATTERN.search(block_text):
        return True
    if _CIP_PATTERN.search(block_text):
        return True
    if _PRICE_PATTERN.search(block_text):
        return True
    if "©" in block_text:
        return True
    return False


def _is_colophon_page(block_text: str) -> bool:
    """判断是否为版本记录页：需 ≥ COLOPHON_MIN_FIELDS 个"标签: 值"元数据字段。

    仅凭"印刷/开本/印张"等通用词不足以判定（出版类书籍正文高频出现），
    必须出现多个"标签: 值"格式的元数据字段（如 版次 2020 / 印张 15.5）。
    """
    count = sum(1 for pat in _COLOPHON_FIELD_PATTERNS if pat.search(block_text))
    return count >= COLOPHON_MIN_FIELDS


def _page_has_toc_header(page_info: Dict) -> bool:
    """页面是否含目录页眉（"目 录" / "CONTENTS"）。"""
    text = _get_block_text(page_info.get("preproc_blocks", []))
    return bool(_TOC_HEADER_PATTERN.search(text))


def _detect_toc_page_set(pdf_info_list: List[Dict]) -> Set[int]:
    """文档级目录页检测，返回目录页集合（1-based）。

    方法（与 Popo detect_toc_pages 同思路）：
    1. 候选页：页面 TOC 行数 >= TOC_LINE_CANDIDATE_THRESHOLD
    2. 合并连续候选页为区间，丢弃过短区间
    3. 保留主导区间（总行数 >= 最大区间行数的 TOC_DOMINANT_RATIO），
       避免把正文/索引页误判为目录
    4. 含 "目 录" 页眉且行数足够的页面强制加入（兜底独立的简短目录页）
    """
    counts = [_count_toc_lines_in_page(p) for p in pdf_info_list]

    # 兜底：目录页眉 + 至少 1 行目录行（覆盖独立的简短目录页，
    # 如国标"目次"页目录条目无编号、行计数偏少的情况），先于候选判断
    toc: Set[int] = set()
    for i, p in enumerate(pdf_info_list):
        if counts[i] >= 1 and _page_has_toc_header(p):
            toc.add(i + 1)

    candidates = [
        i + 1 for i, c in enumerate(counts) if c >= TOC_LINE_CANDIDATE_THRESHOLD
    ]
    if not candidates:
        return toc

    # 合并连续候选页为区间
    ranges: List[tuple] = []
    start = prev = candidates[0]
    for p in candidates[1:]:
        if p - prev > 1:
            ranges.append((start, prev))
            start = p
        prev = p
    ranges.append((start, prev))

    # 丢弃过短区间
    ranges = [r for r in ranges if r[1] - r[0] + 1 >= TOC_MIN_RANGE_PAGES]
    if not ranges:
        return toc

    def _range_lines(r: tuple) -> int:
        return sum(counts[i] for i in range(r[0] - 1, r[1]))

    # 按总行数排序，保留主导区间
    ranges.sort(key=_range_lines, reverse=True)
    top = _range_lines(ranges[0])
    threshold = max(top * TOC_DOMINANT_RATIO, 1)
    kept = [r for r in ranges if _range_lines(r) >= threshold]

    for s, e in kept:
        toc.update(range(s, e + 1))

    return toc


# ─── 前置页/封面增强 ───────────────────────────────────────────────────

# 正文起始检测：章标题模式（第X章 / Chapter N / X.Y 开头 / 国标单级编号 "1 总则" 开头）。
# 负向前瞻紧跟编号数字之后（\s* 跳过编号与后续字符间的空格）：
#   (?!k[VWA]?) 排除单位后缀（"10 kV～500 kV 输变电设备…" 是标准名称/电压范围，
#                不是章标题，否则封面页会污染 heading_start）；
#   (?!\s*[…·]{2,}) 排除含点线引导符的目录条目（"1 范围 …… 1"）。
_BODY_HEADING_PATTERN = re.compile(
    r"第[一二三四五六七八九十百千\d]+章|Chapter\s+\d+|^\d+\.\d+\s|^\d{1,2}(?!\s*k[VWA]?)(?!\s*[…·]{2,})\s+\S",
    re.IGNORECASE,
)

# 编号章标题模式（仅用于 title 类 block，判定正文起始/前言区间边界）。
# 比 _BODY_HEADING_PATTERN 更严格：只认 "第X章" 与 "N 标题" 单级编号，
# 避免正文条款号 "5.1 xxx" 误触发。
# (?!k[VWA]?) 排除单位后缀：封面标题 "10 kV～500 kV 输变电设备…" 的
# "10 kV" 不是章标题，否则会误判正文起始、导致前言检测提前终止。
_NUMBERED_CHAPTER_TITLE_PATTERN = re.compile(
    r"第[一二三四五六七八九十百千\d]+章|^\d{1,2}(?!\s*k[VWA]?)\s+\S",
    re.IGNORECASE,
)

# 前置页标题关键词（供参考；前置页判定主要依赖 front-matter 位置）
PREFACE_TITLE_KEYWORDS = [
    "序", "前言", "Foreword", "Preface", "作者简介", "编者的话",
    "主编简介", "出版说明", "内容简介", "使用说明", "编制说明",
]


def _block_text(block: Dict) -> str:
    """提取单个 block 的文本。"""
    return "".join(
        str(span.get("content", ""))
        for line in block.get("lines", [])
        for span in line.get("spans", [])
    )


def _is_garbled_block_text(text: str) -> bool:
    """纯符号乱码：无中文、无字母数字、去空白后长度 >= 3。

    OCR 常把 PDF 装饰性符号（页边花体、分隔符）误识别为 `! " # $ %`
    之类的纯符号串。真正的文本 block 必含中文/字母/数字，故该规则
    不会误删正常内容。
    """
    s = text.strip()
    if len(s) < 3:
        return False
    if any("\u4e00" <= c <= "\u9fff" for c in s):
        return False
    if any(c.isalnum() for c in s):
        return False
    return True


def remove_garbled_blocks(pdf_info_list: List[Dict]) -> int:
    """删除 preproc_blocks 中的纯符号乱码 block（OCR 误识别的装饰符号）。

    应在所有 block 后处理之前调用，使后续 para 构建、标题分级、页面类型
    分类都基于干净的 block。原地修改 pdf_info_list，返回删除的 block 数。
    """
    removed = 0
    for page_info in pdf_info_list:
        blocks = page_info.get("preproc_blocks", [])
        kept = []
        for block in blocks:
            if _is_garbled_block_text(_block_text(block)):
                removed += 1
            else:
                kept.append(block)
        page_info["preproc_blocks"] = kept
    return removed


def _is_large_centered_title(blocks: List[Dict], page_w: float) -> bool:
    """是否有大号居中标题（封面特征）：bbox 归一化后居中且宽度足够。

    宽度阈值取 0.2（而非 0.25）：前置区扉页标题（如"编 制 说 明"）宽度常
    在 0.2~0.25 之间，取 0.2 可让这类稀疏标题页落入封面兜底，而非半标题页。
    """
    title_types = {BlockType.DOC_TITLE, BlockType.PARAGRAPH_TITLE, BlockType.TITLE}
    for block in blocks:
        if block.get("type") not in title_types:
            continue
        content = _block_text(block).strip()
        if len(content) < 2:
            continue
        bbox = block.get("bbox")
        if not bbox or len(bbox) < 4:
            continue
        # 兼容绝对坐标与归一化坐标
        if max(abs(v) for v in bbox) <= 1.0:
            width = bbox[2] - bbox[0]
            center_x = (bbox[0] + bbox[2]) / 2
        else:
            if page_w <= 0:
                continue
            width = (bbox[2] - bbox[0]) / page_w
            center_x = ((bbox[0] + bbox[2]) / 2) / page_w
        if 0.25 < center_x < 0.75 and width >= 0.2:
            return True
    return False


def _detect_body_start_from_headings(
    pdf_info_list: List[Dict],
    toc_pages: Optional[Set[int]] = None,
) -> int:
    """回退：从第一个章标题推断正文起始页（1-based）。无则返回 1。

    目录页（toc_pages）被跳过：目录条目（如 "1 范围 …… 1"）虽形似章标题，
    但只是页码索引，不得作为正文起始依据，否则 heading_start 会被误判为
    目录页页码（1），导致 body_start 失效。
    """
    for i, page in enumerate(pdf_info_list):
        if toc_pages and (i + 1) in toc_pages:
            continue
        for block in page.get("preproc_blocks", []):
            if block.get("type") not in (
                BlockType.DOC_TITLE, BlockType.PARAGRAPH_TITLE, BlockType.TITLE,
            ):
                continue
            if _BODY_HEADING_PATTERN.search(_block_text(block)):
                return i + 1
    return 1


def _page_has_numbered_chapter_title(page_info: Dict) -> bool:
    """页面是否有编号章标题（title 类 block 以 "第X章" / "N 标题" 开头）。

    仅检查标题类 block，避免正文条款号（"5.1 xxx"）或普通文本误触发。
    用于前言区间边界：前言/修订说明续页之后出现的第一个编号章标题
    即正文开始，前言区间不得越过该页。
    """
    title_types = {BlockType.DOC_TITLE, BlockType.PARAGRAPH_TITLE, BlockType.TITLE}
    for block in page_info.get("preproc_blocks", []):
        if block.get("type") not in title_types:
            continue
        if _NUMBERED_CHAPTER_TITLE_PATTERN.search(_block_text(block).strip()):
            return True
    return False


def _page_has_appendix_title(page_info: Dict) -> bool:
    """页面是否有附录标题（"附 录 A" / "附录A" / "Appendix A"）。

    附录起始页的标题常以 TEXT 块（居中大字）呈现而非 TITLE 块，
    故检查所有 block（不仅 title 类）。要求 block 文本以附录标题
    开头（^ 锚定）且较短，避免正文中"按照附录 A 的要求"等引用误触发。
    """
    for block in page_info.get("preproc_blocks", []):
        text = _block_text(block).strip()
        if not text or len(text) > 20:
            continue
        if _APPENDIX_TITLE_PATTERN.search(text):
            return True
    return False


def _detect_body_start(pdf_info_list: List[Dict], toc_pages: Set[int]) -> int:
    """文档级正文起始页：前置目录后一页；无目录时用章标题回退。

    只统计位于首个章标题之前的目录页（前置目录），避免正文区误报的
    "目录页"（如编号列表密集的正文页）把 body_start 推后，
    导致正文前若干页被误判为前置页/封面。
    """
    if not toc_pages:
        return _detect_body_start_from_headings(pdf_info_list)
    # 找到首个章标题时，用它排除正文区误报的目录页（只统计前置目录）。
    # 传入 toc_pages 让章标题扫描跳过目录页（目录条目不是章标题）。
    heading_start = _detect_body_start_from_headings(pdf_info_list, toc_pages)
    if heading_start > 1:
        front_toc = [p for p in toc_pages if p < heading_start]
        if front_toc:
            # 正文起始 = 首个章标题页（而非目录后一页）：目录与章标题之间
            # 可能存在前言/修订说明等前置页，body_start 取章标题页才能让
            # 这些页落入 front matter 区间被正确分类（如 foreword）。
            return heading_start
    # 未找到章标题（回退哨兵值 1）时，沿用旧逻辑：目录后一页
    return max(toc_pages) + 1


# ─── 标准类前置页检测（扉页/公告/出版信息/前言/引用标准）──────────────
# 国标/行标等标准文档的前置部分有固定版式，用结构化信号判定，
# 避免落入泛化的 cover/preface 兜底。

# 标准编号模式（GB/T 50150、GB50150-2016、"GB 50 1 50" 等 OCR 变体）
_STANDARD_NO_PATTERN = re.compile(
    r"(?:GB|JB|DL|HG|SH|NB|CJJ|CECS)\s*/?\s*T?\s*\d", re.IGNORECASE
)

# 扉页页：标准名称关键词 + 结构化字段（主编/批准部门、施行日期等）
_TITLE_PAGE_NAME_KEYWORDS = [
    "国家标准", "行业标准", "地方标准", "团体标准", "企业标准",
]
_TITLE_PAGE_FIELD_PATTERNS = [
    re.compile(r"主编单位|主编部门|批准部门|发布部门|归口单位|起草单位"),
    re.compile(r"施行日期|实施日期|发布日期"),
    re.compile(r"标准编号"),
]
TITLE_PAGE_MIN_FIELDS = 2


def _is_title_page(block_text: str) -> bool:
    """判断是否为标准扉页页：标准名称 + ≥2 个结构化字段（或 1 字段+标准编号）。"""
    if not _contains_keyword(block_text, _TITLE_PAGE_NAME_KEYWORDS):
        return False
    norm = _normalize_cjk_whitespace(block_text)
    fields = sum(1 for p in _TITLE_PAGE_FIELD_PATTERNS if p.search(norm))
    if fields >= TITLE_PAGE_MIN_FIELDS:
        return True
    return fields >= 1 and bool(_STANDARD_NO_PATTERN.search(norm))


# 发布公告页：标题含"公告" + "第X号"编号（OCR 常在数字间插空格，如 "第 1 093 号"）
_ANNOUNCEMENT_TITLE_KEYWORDS = ["公告"]
_ANNOUNCEMENT_NO_PATTERN = re.compile(r"第\s*\d[\d\s]{0,11}号")


def _is_announcement_page(blocks: List[Dict], block_text: str) -> bool:
    """判断是否为发布公告页：标题 block 含"公告"且页面有"第X号"编号。"""
    title_types = {BlockType.DOC_TITLE, BlockType.PARAGRAPH_TITLE, BlockType.TITLE}
    for block in blocks:
        if block.get("type") in title_types and _contains_keyword(
            _block_text(block), _ANNOUNCEMENT_TITLE_KEYWORDS
        ):
            return bool(_ANNOUNCEMENT_NO_PATTERN.search(block_text))
    return False


# 出版信息页：出版发行关键词 + 标准编号 + ≥2 个出版元数据字段
_PUB_INFO_KEYWORDS = ["出版发行", "出版社", "出版公司"]
_PUB_INFO_FIELD_PATTERNS = [
    re.compile(r"印\s*张"),
    re.compile(r"定\s*价"),
    re.compile(r"网址|www\.|http", re.IGNORECASE),
    re.compile(r"地\s*址"),
    re.compile(r"统一书号|ISBN", re.IGNORECASE),
    re.compile(r"开\s*本"),
    re.compile(r"印\s*次|印\s*数"),
]
PUB_INFO_MIN_FIELDS = 2


def _is_publication_info_page(block_text: str) -> bool:
    """判断是否为出版信息页：出版发行 + 标准编号 + ≥2 个出版元数据字段。

    要求标准编号是为了与书籍版权页区分（书籍版权页无 GB/JB 等标准编号，
    仍走 copyright/colophon 判定，保持既有行为）。
    """
    if not _contains_keyword(block_text, _PUB_INFO_KEYWORDS):
        return False
    norm = _normalize_cjk_whitespace(block_text)
    if not _STANDARD_NO_PATTERN.search(norm):
        return False
    fields = sum(1 for p in _PUB_INFO_FIELD_PATTERNS if p.search(norm))
    return fields >= PUB_INFO_MIN_FIELDS


# 前言页标题关键词
FOREWORD_TITLE_KEYWORDS = ["前言", "foreword"]


def _detect_foreword_pages(
    pdf_info_list: List[Dict],
    toc_pages: Set[int],
    body_start: int,
) -> Set[int]:
    """文档级前言页检测，返回前言页集合（1-based，含续页）。

    前言从含"前言"标题的前置页开始，到目录页、正文起始页或首个编号章
    标题页之前结束（覆盖修订说明、起草单位等续页）。

    编号章标题边界是兜底：当 body_start 检测失效（被误推后）时，
    前言区间不会吞掉 "1 范围" 之后的正文页。
    """
    if body_start is None:
        return set()
    start = None
    for i in range(min(body_start - 1, len(pdf_info_list))):
        if _page_has_numbered_chapter_title(pdf_info_list[i]):
            # 已越过正文起始（编号章标题），前言不可能在其后
            return set()
        blocks = pdf_info_list[i].get("preproc_blocks", [])
        if _is_title_or_text_dominant(blocks, FOREWORD_TITLE_KEYWORDS):
            start = i + 1
            break
    if start is None:
        return set()
    # 前言区间不得越过首个编号章标题页（正文开始）。
    # 只扫描 body_start 之前的页：body_start 本身即正文起始页，
    # 其上的编号章标题是正文的标志而非前言的边界，纳入会误清空前言区间。
    for j in range(start, min(body_start - 1, len(pdf_info_list))):
        if _page_has_numbered_chapter_title(pdf_info_list[j]):
            return set(range(start, j))
    end = body_start - 1
    later_toc = [p for p in toc_pages if p > start]
    if later_toc:
        end = min(end, min(later_toc) - 1)
    if end < start:
        return set()
    return set(range(start, end + 1))


# 引用标准页标题关键词（"引用标准"章，区别于"参考文献"）
NORMATIVE_REFERENCE_KEYWORDS = [
    "规范性引用文件", "引用标准", "引用文件", "normative references",
]


# ─── 辅助函数 ───────────────────────────────────────────────────────────

def _get_block_type_counts(blocks: List[Dict]) -> Dict[str, int]:
    """统计各类型 block 的数量。"""
    counts: Dict[str, int] = {}
    for block in blocks:
        btype = block.get("type", "")
        counts[btype] = counts.get(btype, 0) + 1
    return counts


def _get_block_text(blocks: List[Dict]) -> str:
    """提取所有 block 中的文本内容。"""
    texts = []
    for block in blocks:
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                content = span.get("content", "")
                if content:
                    texts.append(content)
    return " ".join(texts)


def _normalize_cjk_whitespace(text: str) -> str:
    """去除 CJK 字符之间的空白。

    OCR 常在中文词内部插入空格（如 "术 语"、"总 则"），导致关键词/正则
    匹配失败。仅去除两个 CJK 字符之间的空白，不影响英文与数字排版。
    """
    return re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)


def _contains_keyword(text: str, keywords: List[str]) -> bool:
    """检查文本是否包含任一关键词（不区分大小写，CJK 间空白归一化）。"""
    text_lower = _normalize_cjk_whitespace(text).lower()
    for kw in keywords:
        if kw.lower() in text_lower:
            return True
    return False


def _calculate_visual_area_ratio(blocks: List[Dict], page_w: float, page_h: float) -> float:
    """计算视觉类 block（image/table/chart）的面积占页面总面积的比例。"""
    if page_w <= 0 or page_h <= 0:
        return 0.0
    page_area = page_w * page_h
    visual_types = {BlockType.IMAGE, BlockType.TABLE, BlockType.CHART, BlockType.CODE}
    total_visual_area = 0.0

    for block in blocks:
        btype = block.get("type", "")
        if btype in visual_types:
            bbox = block.get("bbox")
            if bbox and len(bbox) >= 4:
                x0, y0, x1, y1 = bbox[0], bbox[1], bbox[2], bbox[3]
                area = max(0, x1 - x0) * max(0, y1 - y0)
                total_visual_area += area

    return min(total_visual_area / page_area, 1.0)


def _has_doc_title(blocks: List[Dict]) -> bool:
    """检查是否包含 doc_title 类型的 block。"""
    return BlockType.DOC_TITLE in _get_block_type_counts(blocks)


def _has_paragraph_title(blocks: List[Dict]) -> bool:
    """检查是否包含 paragraph_title 类型的 block。"""
    return BlockType.PARAGRAPH_TITLE in _get_block_type_counts(blocks)


def _is_title_at_top(blocks: List[Dict], page_h: float) -> bool:
    """检查是否有标题 block 位于页面顶部区域。"""
    if not blocks or page_h <= 0:
        return False
    title_types = {BlockType.DOC_TITLE, BlockType.PARAGRAPH_TITLE, BlockType.TITLE}
    for block in blocks:
        if block.get("type") in title_types:
            bbox = block.get("bbox")
            if bbox and len(bbox) >= 4:
                # 标题顶部位于页面前 30% 区域
                if bbox[1] < page_h * CHAPTER_START_TITLE_TOP_RATIO:
                    return True
    return False


def _is_content_sparse(blocks: List[Dict]) -> bool:
    """判断页面内容是否稀疏（block 数量少）。"""
    return len(blocks) <= COVER_MAX_BLOCKS


def _has_table_block(blocks: List[Dict]) -> bool:
    """页面是否含表格块（封面页不应有表格）。"""
    return any(b.get("type") == BlockType.TABLE for b in blocks)


def _is_very_sparse(blocks: List[Dict]) -> bool:
    """判断页面内容是否非常稀疏。"""
    return len(blocks) <= BACK_COVER_MAX_BLOCKS


def _get_text_block_count(block_counts: Dict[str, int]) -> int:
    """获取文本类 block 的数量。"""
    text_types = {BlockType.TEXT, BlockType.REF_TEXT}
    return sum(block_counts.get(t, 0) for t in text_types)


# ─── 主分类函数 ─────────────────────────────────────────────────────────

def infer_page_type(
    page_info: Dict,
    page_idx: int,
    total_pages: int,
    toc_pages: Optional[Set[int]] = None,
    body_start: Optional[int] = None,
    foreword_pages: Optional[Set[int]] = None,
) -> tuple:
    """推断单个页面的类型。

    Args:
        page_info: 页面信息字典，包含 preproc_blocks、page_size 等字段
        page_idx: 页面索引（0-based）
        total_pages: 文档总页数
        toc_pages: 文档级检测出的目录页集合（1-based）；为 None 时回退到
            INDEX 块占比规则（保持旧调用兼容）
        body_start: 文档级正文起始页（1-based）；为 None 时禁用前置页/封面
            front-matter 判定（保持旧调用兼容）
        foreword_pages: 文档级检测出的前言页集合（1-based，含续页）；
            为 None 时禁用 foreword 判定（保持旧调用兼容）

    Returns:
        (primary_type, secondary_type) 元组。
        primary_type 为 PageType 枚举值字符串，secondary_type 为
        次要类型（如 TOC+Copyright 混合页时为 Copyright）或 None。
    """
    blocks = page_info.get("preproc_blocks", [])
    page_size = page_info.get("page_size", [0, 0])
    page_w, page_h = page_size[0], page_size[1]
    block_counts = _get_block_type_counts(blocks)
    block_text = _get_block_text(blocks)

    # 前置页（正文开始前）：仅当 body_start 已知时启用
    is_front_matter = body_start is not None and (page_idx + 1) < body_start

    # 提前检测页面是否包含多种类型特征（用于混合页判定）
    is_mag_toc = _page_is_magazine_toc(page_info)
    is_toc_in_set = toc_pages is not None and (page_idx + 1) in toc_pages
    index_count = block_counts.get(BlockType.INDEX, 0)
    is_index_toc = (len(blocks) > 0 and index_count / len(blocks) >= TOC_INDEX_RATIO_THRESHOLD)
    is_toc = is_toc_in_set or is_index_toc or is_mag_toc

    # 版权/版本记录检测：
    # - 杂志TOC页：沿用严格关键词检测（避免板块标题误触发，保留 TOC+版权 混合页判定）
    # - 普通页：基于结构化元数据信号（ISBN/CIP/定价/© 及 版本记录字段），
    #   避免出版类书籍正文中"版权/著作权/印刷/开本"等通用词导致的大量误判
    if is_mag_toc:
        has_copyright = _has_strict_copyright_in_non_toc_blocks(page_info)
        has_colophon = _has_strict_colophon_in_non_toc_blocks(page_info)
    else:
        has_copyright = _is_copyright_page(block_text)
        has_colophon = _is_colophon_page(block_text)

    # 1. 空白页
    if len(blocks) <= BLANK_BLOCK_THRESHOLD:
        return (PageType.BLANK, None)

    # 1a. 前言页（文档级前言区间，含修订说明/起草单位等续页）。
    # 前置到封面/半标题判定之前：前言页常有大号居中标题（如"前言"），
    # 若先走封面兜底会被误判为 cover，必须先按文档级前言区间归类。
    if foreword_pages is not None and (page_idx + 1) in foreword_pages:
        return (PageType.FOREWORD, None)

    # 2a. 封面页（首页 + doc_title）
    if page_idx == 0 and _has_doc_title(blocks) and _is_content_sparse(blocks):
        return (PageType.COVER, None)

    # 2b. 发布公告页（前置页 + 标题含"公告" + "第X号"编号）
    if is_front_matter and _is_announcement_page(blocks, block_text):
        return (PageType.ANNOUNCEMENT, None)

    # 2c. 扉页页（前置页 + 标准名称 + 主编/批准/施行等结构化字段）
    if is_front_matter and _is_title_page(block_text):
        return (PageType.TITLE_PAGE, None)

    # 2d. 出版信息页（前置页 + 出版发行 + 标准编号 + 出版元数据字段）
    if is_front_matter and _is_publication_info_page(block_text):
        return (PageType.PUBLICATION_INFO, None)

    # 2e. 封面页兜底（前置页 + 居中大标题 + 内容稀疏，排除目录页与表格页）。
    # 仅限正文开始之前的页面：正文区之后的稀疏标题页（如附录起始页、
    # "编制说明"扉页）不应判为 cover。body_start 未知（None）时不启用
    # （与原 is_front_matter 语义一致，保持旧调用兼容）。
    if (
        (body_start is not None and (page_idx + 1) < body_start)
        and (toc_pages is None or (page_idx + 1) not in toc_pages)
        and _is_large_centered_title(blocks, page_w)
        and _is_content_sparse(blocks)
        and not _has_table_block(blocks)
    ):
        return (PageType.COVER, None)

    # 3. 封底页（最后一页 + 内容非常稀疏）
    if page_idx == total_pages - 1 and _is_very_sparse(blocks):
        return (PageType.BACK_COVER, None)

    # 4. 版权页 + 目录混合检测
    if has_copyright:
        if is_toc:
            # 版权 + 目录混合页：主类型为 TOC，次要类型为 COPYRIGHT
            return (PageType.TOC, PageType.COPYRIGHT)
        return (PageType.COPYRIGHT, None)

    # 5. 版本记录页 + 目录混合检测
    if has_colophon:
        if is_toc:
            # 版本记录 + 目录混合页：主类型为 TOC，次要类型为 COLOPHON
            return (PageType.TOC, PageType.COLOPHON)
        return (PageType.COLOPHON, None)

    # 6. 半标题页（封面后的几页 + 内容极少 + 只有标题）。
    # 排除含目录页眉（"目次/目录"）的页面：国标"目次"页常为
    # "标题 + 1 个目录文本块"的稀疏结构，不得误判为半标题页。
    # 排除含编号章标题（"1 范围" / "第X章"）的页面：正文起始章标题页
    # 常为"章标题 + 1 个文本块"的稀疏结构，应判 chapter_start 而非半标题页。
    if (
        page_idx <= 3
        and len(blocks) <= HALF_TITLE_MAX_BLOCKS
        and not _page_has_toc_header(page_info)
        and not _page_has_numbered_chapter_title(page_info)
    ):
        # 半标题页通常只有标题类 block，没有复杂内容
        non_title_types = set(block_counts.keys()) - {
            BlockType.DOC_TITLE, BlockType.PARAGRAPH_TITLE, BlockType.TITLE
        }
        if len(non_title_types) == 0 or (
            len(non_title_types) == 1 and BlockType.TEXT in non_title_types
        ):
            # 确保不是封面（封面已经在前面的判断中处理）
            if not _has_doc_title(blocks) or len(blocks) < COVER_MAX_BLOCKS:
                # 进一步检查：半标题页通常只有一两个 block
                if len(blocks) <= 2:
                    return (PageType.HALF_TITLE, None)

    # 7. 目录页（行密度区间检测优先；index block 占比兜底）
    if is_toc_in_set:
        return (PageType.TOC, None)
    if is_index_toc:
        return (PageType.TOC, None)
    # 杂志类目录页兜底
    if is_mag_toc:
        return (PageType.TOC, None)

    # 8. 参考文献页（ref_text 占主导）
    ref_count = block_counts.get(BlockType.REF_TEXT, 0)
    if len(blocks) > 0 and ref_count / len(blocks) >= REFERENCE_RATIO_THRESHOLD:
        return (PageType.REFERENCE, None)

    # 9. 致谢页
    if _contains_keyword(block_text, ACKNOWLEDGMENT_KEYWORDS):
        # 只有当致谢相关文本是主要内容时才判定
        if _is_title_or_text_dominant(blocks, ACKNOWLEDGMENT_KEYWORDS):
            return (PageType.ACKNOWLEDGMENT, None)

    # 10. 附录页。
    # 附录起始页的标题常以 TEXT 块（居中大字）呈现而非 TITLE 块，
    # 故除标题主导判定外，再用 _page_has_appendix_title 匹配"附 录 A"等标题。
    if _contains_keyword(block_text, APPENDIX_KEYWORDS):
        if _is_title_or_text_dominant(blocks, APPENDIX_KEYWORDS) \
                or _page_has_appendix_title(page_info):
            return (PageType.APPENDIX, None)

    # 11. 术语表页。
    # 排除含编号章标题（"1 范围" / "3 术语和定义"）的正文页：标准正文的
    # "术语和定义"是编号章节（与"1 范围""2 规范性引用文件"并列），并非独立
    # 术语表页；真正的术语表页以"术语表/术语"为主标题，不含编号章标题。
    if _contains_keyword(block_text, GLOSSARY_KEYWORDS):
        if _is_title_or_text_dominant(blocks, GLOSSARY_KEYWORDS):
            if not _page_has_numbered_chapter_title(page_info):
                return (PageType.GLOSSARY, None)

    # 12. 索引页（注意与目录区分：索引通常有更密集的条目和页码）
    if _contains_keyword(block_text, INDEX_KEYWORDS):
        if _is_title_or_text_dominant(blocks, INDEX_KEYWORDS):
            return (PageType.INDEX, None)

    # 12b. 引用标准页（标题为"引用标准/规范性引用文件"，区别于参考文献）。
    # 同样排除含编号章标题的正文页：正文"2 规范性引用文件"是编号章节，
    # 真正的引用标准页以"引用标准/规范性引用文件"为主标题，不含编号章标题。
    if _contains_keyword(block_text, NORMATIVE_REFERENCE_KEYWORDS):
        if _is_title_or_text_dominant(blocks, NORMATIVE_REFERENCE_KEYWORDS):
            if not _page_has_numbered_chapter_title(page_info):
                return (PageType.NORMATIVE_REFERENCES, None)

    # 14. 前置页（front matter 默认：正文前的非封面/版权/目录页，即序/前言/作者简介等）
    if is_front_matter:
        return (PageType.PREFACE, None)

    # 14. 章节起始页（以标题开头，且不在文档开头/结尾的稀疏区域）
    if _has_doc_title(blocks) or _is_title_at_top(blocks, page_h):
        # 章节起始页的特征：有标题 + 标题位于顶部 + 该页其他内容不多
        title_count = (
            block_counts.get(BlockType.DOC_TITLE, 0)
            + block_counts.get(BlockType.PARAGRAPH_TITLE, 0)
            + block_counts.get(BlockType.TITLE, 0)
        )
        if title_count > 0 and title_count / max(len(blocks), 1) < 0.8:
            # 标题不是页面的全部内容（否则可能是半标题页）
            return (PageType.CHAPTER_START, None)

    # 15. 图片为主页
    if _calculate_visual_area_ratio(blocks, page_w, page_h) >= IMAGE_DOMINANT_AREA_RATIO:
        return (PageType.IMAGE_DOMINANT, None)

    # 16. 默认：正文页
    return (PageType.BODY, None)


def _is_title_or_text_dominant(blocks: List[Dict], keywords: List[str]) -> bool:
    """判断页面是否以包含特定关键词的标题/文本为主导。

    用于区分"页面标题是致谢/附录"和"页面只是偶然提到致谢/附录"。
    """
    title_types = {
        BlockType.DOC_TITLE,
        BlockType.PARAGRAPH_TITLE,
        BlockType.TITLE,
        BlockType.ABSTRACT,
    }
    for block in blocks:
        if block.get("type") in title_types:
            block_text = ""
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    block_text += span.get("content", "")
            if _contains_keyword(block_text, keywords):
                return True
    return False


# ─── 批量处理函数 ───────────────────────────────────────────────────────

def classify_all_pages(pdf_info_list: List[Dict]) -> None:
    """为 pdf_info_list 中的每个页面推断并设置 page_type。

    直接在每个 page_info 字典上增加 'page_type' 字段，原地修改。
    若检测到混合类型页面，同时增加 'page_type_secondary' 字段。

    Args:
        pdf_info_list: 页面信息列表（middle.json 中的 pdf_info 数组）
    """
    total_pages = len(pdf_info_list)
    # 文档级目录页检测（连续区间 + 主导区间），供页面级判定使用
    toc_pages = _detect_toc_page_set(pdf_info_list)
    # 文档级正文起始页：前置目录后一页；无目录时用章标题回退
    body_start = _detect_body_start(pdf_info_list, toc_pages)
    # 文档级前言页检测（含修订说明/起草单位等续页）
    foreword_pages = _detect_foreword_pages(pdf_info_list, toc_pages, body_start)
    for idx, page_info in enumerate(pdf_info_list):
        primary_type, secondary_type = infer_page_type(
            page_info, idx, total_pages,
            toc_pages=toc_pages, body_start=body_start,
            foreword_pages=foreword_pages,
        )
        page_info["page_type"] = primary_type
        if secondary_type:
            page_info["page_type_secondary"] = secondary_type
        else:
            # 清除上一次分类遗留的次要类型，避免陈旧值残留
            page_info.pop("page_type_secondary", None)