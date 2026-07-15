# Copyright (c) Opendatalab. All rights reserved.
"""页面类型分类器 - 基于规则推断页面语义类型。

根据布局分析结果（block-level）中的 block 类型分布、位置、文本内容等特征，
通过启发式规则推断每个页面的类型（封面、目录、正文、章节起始等）。

不依赖额外的深度学习模型，所有推断基于已有的 layout 分析结果。
"""
from typing import Dict, List

from mineru.utils.enum_class import BlockType, PageType


# ─── 阈值常量 ───────────────────────────────────────────────────────────

# 空白页：有效 block 数阈值
BLANK_BLOCK_THRESHOLD = 0

# 封面/封底：内容稀疏阈值（有效 block 数）
COVER_MAX_BLOCKS = 8
BACK_COVER_MAX_BLOCKS = 3

# 目录页：index block 占比阈值
TOC_INDEX_RATIO_THRESHOLD = 0.5

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
) -> str:
    """推断单个页面的类型。

    Args:
        page_info: 页面信息字典，包含 preproc_blocks、page_size 等字段
        page_idx: 页面索引（0-based）
        total_pages: 文档总页数

    Returns:
        PageType 枚举值字符串
    """
    blocks = page_info.get("preproc_blocks", [])
    page_size = page_info.get("page_size", [0, 0])
    page_w, page_h = page_size[0], page_size[1]
    block_counts = _get_block_type_counts(blocks)
    block_text = _get_block_text(blocks)

    # 1. 空白页
    if len(blocks) <= BLANK_BLOCK_THRESHOLD:
        return PageType.BLANK

    # 2. 封面页（第一页 + 包含 doc_title + 内容稀疏）
    if page_idx == 0 and _has_doc_title(blocks) and _is_content_sparse(blocks):
        return PageType.COVER

    # 3. 封底页（最后一页 + 内容非常稀疏）
    if page_idx == total_pages - 1 and _is_very_sparse(blocks):
        return PageType.BACK_COVER

    # 4. 版权页（包含版权关键词）—— 在 half_title 之前检查，避免版权页被误判为半标题页
    if _contains_keyword(block_text, COPYRIGHT_KEYWORDS):
        return PageType.COPYRIGHT

    # 5. 版本记录页
    if _contains_keyword(block_text, COLOPHON_KEYWORDS):
        return PageType.COLOPHON

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
                    return PageType.HALF_TITLE

    # 7. 目录页（index block 占主导）
    index_count = block_counts.get(BlockType.INDEX, 0)
    if len(blocks) > 0 and index_count / len(blocks) >= TOC_INDEX_RATIO_THRESHOLD:
        return PageType.TOC

    # 8. 参考文献页（ref_text 占主导）
    ref_count = block_counts.get(BlockType.REF_TEXT, 0)
    if len(blocks) > 0 and ref_count / len(blocks) >= REFERENCE_RATIO_THRESHOLD:
        return PageType.REFERENCE

    # 9. 致谢页
    if _contains_keyword(block_text, ACKNOWLEDGMENT_KEYWORDS):
        # 只有当致谢相关文本是主要内容时才判定
        if _is_title_or_text_dominant(blocks, ACKNOWLEDGMENT_KEYWORDS):
            return PageType.ACKNOWLEDGMENT

    # 10. 附录页
    if _contains_keyword(block_text, APPENDIX_KEYWORDS):
        if _is_title_or_text_dominant(blocks, APPENDIX_KEYWORDS):
            return PageType.APPENDIX

    # 11. 术语表页
    if _contains_keyword(block_text, GLOSSARY_KEYWORDS):
        if _is_title_or_text_dominant(blocks, GLOSSARY_KEYWORDS):
            return PageType.GLOSSARY

    # 12. 索引页（注意与目录区分：索引通常有更密集的条目和页码）
    if _contains_keyword(block_text, INDEX_KEYWORDS):
        if _is_title_or_text_dominant(blocks, INDEX_KEYWORDS):
            return PageType.INDEX

    # 13. 章节起始页（以标题开头，且不在文档开头/结尾的稀疏区域）
    if _has_doc_title(blocks) or _is_title_at_top(blocks, page_h):
        # 章节起始页的特征：有标题 + 标题位于顶部 + 该页其他内容不多
        title_count = (
            block_counts.get(BlockType.DOC_TITLE, 0)
            + block_counts.get(BlockType.PARAGRAPH_TITLE, 0)
            + block_counts.get(BlockType.TITLE, 0)
        )
        if title_count > 0 and title_count / max(len(blocks), 1) < 0.8:
            # 标题不是页面的全部内容（否则可能是半标题页）
            return PageType.CHAPTER_START

    # 14. 图片为主页
    if _calculate_visual_area_ratio(blocks, page_w, page_h) >= IMAGE_DOMINANT_AREA_RATIO:
        return PageType.IMAGE_DOMINANT

    # 15. 默认：正文页
    return PageType.BODY


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

    Args:
        pdf_info_list: 页面信息列表（middle.json 中的 pdf_info 数组）
    """
    total_pages = len(pdf_info_list)
    for idx, page_info in enumerate(pdf_info_list):
        page_type = infer_page_type(page_info, idx, total_pages)
        page_info["page_type"] = page_type