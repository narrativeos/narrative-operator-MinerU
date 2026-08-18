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
TOC_LINE_CANDIDATE_THRESHOLD = 3
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
# 引导符：U+2026 省略号 / U+00B7 中圆点允许 1 个以上；ASCII '.' 仅允许 2 个以上
# （避免把标题中的小数点如 "4.0" 误判为引导符，见 Phase 0 报告 Q3）。
_TOC_LINE_PATTERN = re.compile(
    r"(?:第[一二三四五六七八九十百千\d]+[篇章节部]|[\d]+(?:\.[\d]+)*)\s*"
    r".*?(?:[……·]{1,}|\.{2,})\s*[\dIVXivx]+"
)

# 杂志/生活类目录行模式：页码(2-3位数字) + 可选空白 + 文章标题(至少4个非数字字符)
# 例如: "010京沪高铁，让旅客出行更美好" (无空格), "070 黔味越山海，酸香漫京城" (有空格)
_MAGAZINE_TOC_LINE_PATTERN = re.compile(
    r"^\s*\d{2,3}\s?[^\d\s].{4,}"
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

# 目录页页眉关键词
_TOC_HEADER_PATTERN = re.compile(r"目\s*录|CONTENTS", re.IGNORECASE)


def _count_toc_lines_in_page(page_info: Dict) -> int:
    """统计页面文本中 TOC 条目行数（学术型 + 杂志型）。"""
    total = 0
    for block in page_info.get("preproc_blocks", []):
        text = ""
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text += str(span.get("content", ""))
        for ln in text.split("\n"):
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
        for ln in text.split("\n"):
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

    # 兜底：目录页眉 + 行数足够（覆盖独立的简短目录页），先于候选判断
    toc: Set[int] = set()
    for i, p in enumerate(pdf_info_list):
        if counts[i] >= 2 and _page_has_toc_header(p):
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

# 正文起始检测：章标题模式（第X章 / Chapter N / X.Y 开头）
_BODY_HEADING_PATTERN = re.compile(
    r"第[一二三四五六七八九十百千\d]+章|Chapter\s+\d+|^\d+\.\d+\s",
    re.IGNORECASE,
)

# 前置页标题关键词（供参考；前置页判定主要依赖 front-matter 位置）
PREFACE_TITLE_KEYWORDS = [
    "序", "前言", "Foreword", "Preface", "作者简介", "编者的话",
    "主编简介", "出版说明", "内容简介", "使用说明",
]


def _block_text(block: Dict) -> str:
    """提取单个 block 的文本。"""
    return "".join(
        str(span.get("content", ""))
        for line in block.get("lines", [])
        for span in line.get("spans", [])
    )


def _is_large_centered_title(blocks: List[Dict], page_w: float) -> bool:
    """是否有大号居中标题（封面特征）：bbox 归一化后居中且宽度足够。"""
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
        if 0.25 < center_x < 0.75 and width > 0.25:
            return True
    return False


def _detect_body_start_from_headings(pdf_info_list: List[Dict]) -> int:
    """回退：从第一个章标题推断正文起始页（1-based）。无则返回 1。"""
    for i, page in enumerate(pdf_info_list):
        for block in page.get("preproc_blocks", []):
            if block.get("type") not in (
                BlockType.DOC_TITLE, BlockType.PARAGRAPH_TITLE, BlockType.TITLE,
            ):
                continue
            if _BODY_HEADING_PATTERN.search(_block_text(block)):
                return i + 1
    return 1


def _detect_body_start(pdf_info_list: List[Dict], toc_pages: Set[int]) -> int:
    """文档级正文起始页：目录后一页；无目录时用章标题回退。"""
    if toc_pages:
        return max(toc_pages) + 1
    return _detect_body_start_from_headings(pdf_info_list)


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


def _contains_keyword(text: str, keywords: List[str]) -> bool:
    """检查文本是否包含任一关键词（不区分大小写）。"""
    text_lower = text.lower()
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

    # 版权/版本记录检测：对于杂志TOC页面使用更严格的检测，
    # 避免板块标题中的英文词（如"印象Impression"）误触发
    if is_mag_toc:
        has_copyright = _has_strict_copyright_in_non_toc_blocks(page_info)
        has_colophon = _has_strict_colophon_in_non_toc_blocks(page_info)
    else:
        has_copyright = _contains_keyword(block_text, COPYRIGHT_KEYWORDS)
        has_colophon = _contains_keyword(block_text, COLOPHON_KEYWORDS)

    # 1. 空白页
    if len(blocks) <= BLANK_BLOCK_THRESHOLD:
        return (PageType.BLANK, None)

    # 2. 封面页（首页 + doc_title；或前置页 + 居中大标题 + 内容稀疏，排除目录页与表格页）
    if page_idx == 0 and _has_doc_title(blocks) and _is_content_sparse(blocks):
        return (PageType.COVER, None)
    if (
        is_front_matter
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

    # 6. 半标题页（封面后的几页 + 内容极少 + 只有标题）
    if page_idx <= 3 and len(blocks) <= HALF_TITLE_MAX_BLOCKS:
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

    # 10. 附录页
    if _contains_keyword(block_text, APPENDIX_KEYWORDS):
        if _is_title_or_text_dominant(blocks, APPENDIX_KEYWORDS):
            return (PageType.APPENDIX, None)

    # 11. 术语表页
    if _contains_keyword(block_text, GLOSSARY_KEYWORDS):
        if _is_title_or_text_dominant(blocks, GLOSSARY_KEYWORDS):
            return (PageType.GLOSSARY, None)

    # 12. 索引页（注意与目录区分：索引通常有更密集的条目和页码）
    if _contains_keyword(block_text, INDEX_KEYWORDS):
        if _is_title_or_text_dominant(blocks, INDEX_KEYWORDS):
            return (PageType.INDEX, None)

    # 13. 前置页（front matter 默认：正文前的非封面/版权/目录页，即序/前言/作者简介等）
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
    # 文档级正文起始页：目录后一页；无目录时用章标题回退
    body_start = _detect_body_start(pdf_info_list, toc_pages)
    for idx, page_info in enumerate(pdf_info_list):
        primary_type, secondary_type = infer_page_type(
            page_info, idx, total_pages, toc_pages=toc_pages, body_start=body_start
        )
        page_info["page_type"] = primary_type
        if secondary_type:
            page_info["page_type_secondary"] = secondary_type