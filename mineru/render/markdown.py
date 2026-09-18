# Copyright (c) Opendatalab. All rights reserved.
"""严格 MiddleJson 到 Markdown 的轻量公共门面。"""

from __future__ import annotations

from ..types import MiddleJson
from .contracts import ImageRenderer, RenderMode

# docvortex FULL 模式的页分隔符（render/_internal/markdown/renderer.py: _PAGE_SEPARATOR）。
_PAGE_SEPARATOR = "\n\n---\n\n"


def render_markdown(
    middle_json: MiddleJson,
    *,
    mode: RenderMode = RenderMode.DEFAULT,
    asset_base_url: str = "",
    image_renderer: ImageRenderer | None = None,
) -> str:
    """惰性加载 Markdown 实现并渲染严格 MiddleJson。

    fork 扩展：FULL 模式下，若 ``extensions["mineru_page_types"]`` 携带页面类型，
    在每页内容前插入 ``<!-- page_type: ... -->`` 注释（与 3.x markdown 输出兼容）；
    DEFAULT 模式无可靠页边界，不插入注释。
    """
    from ..config import config
    from docvortex.render.markdown import render_markdown as _render_markdown

    markdown = _render_markdown(
        middle_json,
        mode=mode,
        asset_base_url=asset_base_url,
        image_renderer=image_renderer,
        latex_delimiters=config.render.latex_delimiters,
    )
    if mode is RenderMode.FULL:
        markdown = _insert_page_type_comments(middle_json, markdown)
    return markdown


def _insert_page_type_comments(middle_json: MiddleJson, markdown: str) -> str:
    """在 FULL 模式 markdown 的每页内容前插入页面类型注释。

    仅当 ``extensions["mineru_page_types"]`` 非空时生效；无标注的页保持原样。
    """
    page_types = (middle_json.extensions or {}).get("mineru_page_types") or {}
    if not page_types or not markdown:
        return markdown
    pages = middle_json.pages
    if markdown.count(_PAGE_SEPARATOR) != len(pages) - 1:
        # 分隔符数量与页面数对不上（如正文含字面 --- 或空页渲染差异），
        # 放弃注入以免注释错位。
        return markdown
    chunks = markdown.split(_PAGE_SEPARATOR)
    annotated: list[str] = []
    for page, chunk in zip(pages, chunks):
        info = page_types.get(str(page.page_idx)) or {}
        page_type = info.get("page_type")
        if not page_type:
            annotated.append(chunk)
            continue
        comment = f"<!-- page_type: {page_type}"
        if info.get("page_type_secondary"):
            comment += f"; page_type_secondary: {info['page_type_secondary']}"
        comment += " -->"
        annotated.append(f"{comment}\n{chunk.lstrip(chr(10))}" if chunk else comment)
    return _PAGE_SEPARATOR.join(annotated)


__all__ = ["render_markdown"]
