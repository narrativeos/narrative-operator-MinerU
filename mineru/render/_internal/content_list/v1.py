# Copyright (c) Opendatalab. All rights reserved.
"""严格 MiddleJson 到扁平 Content List V1 的渲染实现。"""

from __future__ import annotations

from typing import Any

from docvortex.options import LatexDelimitersConfig
from ....types import (
    RAW_ALGORITHM,
    AlgorithmBodyBlock,
    BlockType,
    ChartBlock,
    CodeBlock,
    CodeBodyBlock,
    DocTitleBlock,
    EquationBlock,
    ImageBlock,
    IndexBlock,
    ListBlock,
    MiddleJson,
    PageAuxTextBlock,
    PageFootnoteBlock,
    ParagraphTitleBlock,
    TableBlock,
    TextBlock,
)
from docvortex.render.fragments import render_inline_content, render_internal_link
from .common import (
    PageRenderUnit,
    ReferenceGroup,
    flatten_index_leaves,
    flatten_list_leaves,
    iter_page_units,
    normalize_bbox,
    normalized_index_content,
    render_annotation_texts,
    render_embedded_content,
    resolve_legacy_image_source,
    unit_bbox,
    visual_body,
)

_IMAGE_CAPTION_TYPES = {str(BlockType.IMAGE_CAPTION)}
_IMAGE_FOOTNOTE_TYPES = {str(BlockType.IMAGE_FOOTNOTE)}
_TABLE_CAPTION_TYPES = {str(BlockType.TABLE_CAPTION)}
_TABLE_FOOTNOTE_TYPES = {str(BlockType.TABLE_FOOTNOTE)}
_CHART_CAPTION_TYPES = {str(BlockType.CHART_CAPTION)}
_CHART_FOOTNOTE_TYPES = {str(BlockType.CHART_FOOTNOTE)}
_CODE_CAPTION_TYPES = {str(BlockType.CODE_CAPTION)}
_CODE_FOOTNOTE_TYPES = {str(BlockType.CODE_FOOTNOTE)}


def render_content_list(
    middle_json: MiddleJson,
    *,
    asset_base_url: str = "",
    latex_delimiters: LatexDelimitersConfig | None = None,
) -> list[dict[str, Any]]:
    """把严格 MiddleJson 无副作用地渲染为扁平 Content List V1。"""
    if not isinstance(middle_json, MiddleJson):
        raise TypeError("render_content_list expects a MiddleJson instance")
    if not isinstance(asset_base_url, str):
        raise TypeError("asset_base_url must be a string")

    delimiters = latex_delimiters or LatexDelimitersConfig()
    # fork 扩展：block 溯源与页面类型（来自 ModelJson extensions，postprocess 透传）
    extensions = middle_json.extensions or {}
    block_ids = extensions.get("mineru_block_ids", {})
    page_types = extensions.get("mineru_page_types", {})
    output: list[dict[str, Any]] = []
    for page in middle_json.pages:
        page_type_info = page_types.get(str(page.page_idx), {})
        for unit in iter_page_units(page.blocks):
            item = _render_unit(
                unit,
                page_idx=page.page_idx,
                asset_base_url=asset_base_url,
                delimiters=delimiters,
            )
            if item is not None:
                _annotate_traceability(item, unit, block_ids, page_type_info, page.page_idx)
                output.append(item)
    return output


def _annotate_traceability(
    item: dict[str, Any],
    unit: PageRenderUnit,
    block_ids: dict[str, dict[str, str]],
    page_type_info: dict[str, str],
    page_idx: int,
) -> None:
    """fork 扩展：为 V1 item 写入 ``block_id``/``block_ids`` 与 ``page_type``。

    仅在 extensions 携带对应数据时写入，保持无 fork 扩展时的输出不变。
    """
    if page_type_info:
        item["page_type"] = page_type_info.get("page_type")
        if page_type_info.get("page_type_secondary"):
            item["page_type_secondary"] = page_type_info["page_type_secondary"]
    page_map = block_ids.get(str(page_idx))
    if not page_map:
        return
    if isinstance(unit, ReferenceGroup):
        ids = [page_map[str(block.index)] for block in unit.blocks if str(block.index) in page_map]
        if ids:
            item["block_ids"] = ids
    else:
        if block_id := page_map.get(str(unit.index)):
            item["block_id"] = block_id


def _render_unit(
    unit: PageRenderUnit,
    *,
    page_idx: int,
    asset_base_url: str,
    delimiters: LatexDelimitersConfig,
) -> dict[str, Any] | None:
    """把一个页面渲染单元转换为 V1 item，并补齐 bbox 与 page_idx。"""
    item = _render_unit_content(unit, asset_base_url=asset_base_url, delimiters=delimiters)
    if item is None:
        return None
    if bbox := normalize_bbox(unit_bbox(unit)):
        item["bbox"] = bbox
    item["page_idx"] = page_idx
    return item


def _render_unit_content(
    unit: PageRenderUnit,
    *,
    asset_base_url: str,
    delimiters: LatexDelimitersConfig,
) -> dict[str, Any] | None:
    """按严格 block 类型构造 V1 专有字段。"""
    if isinstance(unit, ReferenceGroup):
        return {
            "type": "list",
            "sub_type": "ref_text",
            "list_items": [render_inline_content(block.content, delimiters) for block in unit.blocks if block.content],
        }
    if isinstance(unit, TextBlock):
        item = {"type": "text", "text": render_inline_content(unit.content, delimiters)}
        _add_anchor(item, unit.anchor)
        return item
    if isinstance(unit, (DocTitleBlock, ParagraphTitleBlock)):
        item: dict[str, Any] = {
            "type": "text",
            "text": render_inline_content(unit.content, delimiters),
            "text_level": unit.level,
        }
        _add_anchor(item, unit.anchor)
        return item
    if isinstance(unit, PageFootnoteBlock):
        item = {"type": "page_footnote", "text": render_inline_content(unit.content, delimiters)}
        _add_anchor(item, unit.anchor)
        return item
    if isinstance(unit, PageAuxTextBlock):
        return {"type": str(unit.type), "text": render_inline_content(unit.content, delimiters)}
    if isinstance(unit, EquationBlock):
        item = {
            "type": "equation",
            "img_path": resolve_legacy_image_source(unit, asset_base_url),
        }
        if latex := unit.content.strip():
            item["text"] = latex
            item["text_format"] = "latex"
        return item
    if isinstance(unit, ListBlock):
        return {
            "type": "list",
            "sub_type": str(unit.sub_type or BlockType.TEXT),
            "list_items": [
                render_inline_content(leaf.block.content, delimiters)
                for leaf in flatten_list_leaves(unit)
                if leaf.block.content
            ],
        }
    if isinstance(unit, IndexBlock):
        return {"type": "index", "list_items": _render_index_items(unit, delimiters)}
    if isinstance(unit, ImageBlock):
        return _render_image(unit, asset_base_url, delimiters)
    if isinstance(unit, TableBlock):
        return _render_table(unit, asset_base_url, delimiters)
    if isinstance(unit, ChartBlock):
        return _render_chart(unit, asset_base_url, delimiters)
    if isinstance(unit, CodeBlock):
        return _render_code(unit, delimiters)
    return None


def _render_index_items(block: IndexBlock, delimiters: LatexDelimitersConfig) -> list[str]:
    """把递归目录叶子渲染为带缩进和可选内部链接的 V1 字符串。"""
    items: list[str] = []
    for leaf in flatten_index_leaves(block):
        content = normalized_index_content(leaf.block)
        label = render_inline_content(content, delimiters).strip()
        if not label:
            continue
        if leaf.block.anchor:
            label = render_internal_link(label, leaf.block.anchor)
        items.append(f"{'    ' * leaf.depth}- {label}")
    return items


def _render_image(
    block: ImageBlock,
    asset_base_url: str,
    delimiters: LatexDelimitersConfig,
) -> dict[str, Any]:
    """构造 V1 图片 item。"""
    body = visual_body(block)
    item: dict[str, Any] = {
        "type": "image",
        "img_path": resolve_legacy_image_source(body, asset_base_url),
        "image_caption": render_annotation_texts(block, _IMAGE_CAPTION_TYPES, delimiters),
        "image_footnote": render_annotation_texts(block, _IMAGE_FOOTNOTE_TYPES, delimiters),
    }
    if content := render_embedded_content(body.content, asset_base_url=asset_base_url, delimiters=delimiters):
        item["content"] = content
    if block.sub_type:
        item["sub_type"] = block.sub_type
    return item


def _render_table(
    block: TableBlock,
    asset_base_url: str,
    delimiters: LatexDelimitersConfig,
) -> dict[str, Any]:
    """构造 V1 表格 item。"""
    body = visual_body(block)
    item: dict[str, Any] = {
        "type": "table",
        "img_path": resolve_legacy_image_source(body, asset_base_url),
        "table_caption": render_annotation_texts(block, _TABLE_CAPTION_TYPES, delimiters),
        "table_footnote": render_annotation_texts(block, _TABLE_FOOTNOTE_TYPES, delimiters),
    }
    if content := render_embedded_content(body.content, asset_base_url=asset_base_url, delimiters=delimiters):
        item["table_body"] = content
    return item


def _render_chart(
    block: ChartBlock,
    asset_base_url: str,
    delimiters: LatexDelimitersConfig,
) -> dict[str, Any]:
    """构造 V1 图表 item。"""
    body = visual_body(block)
    item: dict[str, Any] = {
        "type": "chart",
        "img_path": resolve_legacy_image_source(body, asset_base_url),
        "content": render_embedded_content(body.content, asset_base_url=asset_base_url, delimiters=delimiters),
        "chart_caption": render_annotation_texts(block, _CHART_CAPTION_TYPES, delimiters),
        "chart_footnote": render_annotation_texts(block, _CHART_FOOTNOTE_TYPES, delimiters),
    }
    if block.sub_type:
        item["sub_type"] = block.sub_type
    return item


def _render_code(block: CodeBlock, delimiters: LatexDelimitersConfig) -> dict[str, Any]:
    """构造 V1 代码或算法 item。"""
    body = visual_body(block)
    if isinstance(body, CodeBodyBlock):
        body_content = body.content
    elif isinstance(body, AlgorithmBodyBlock):
        body_content = render_inline_content(body.content, delimiters)
    else:
        raise TypeError(f"Unsupported code body: {type(body).__name__}")
    return {
        "type": "code",
        "sub_type": "algorithm" if block.sub_type == RAW_ALGORITHM else "code",
        "code_body": body_content,
        "code_caption": render_annotation_texts(block, _CODE_CAPTION_TYPES, delimiters),
        "code_footnote": render_annotation_texts(block, _CODE_FOOTNOTE_TYPES, delimiters),
    }


def _add_anchor(item: dict[str, Any], anchor: str | None) -> None:
    """把非空文档锚点写入兼容 item。"""
    if anchor and anchor.strip():
        item["anchor"] = anchor.strip()


__all__ = ["render_content_list"]
