from __future__ import annotations

import pytest
from docvortex.schema import Producer

from mineru.config import Config
from mineru.integrations.docvortex import build_metadata
from mineru.render import render_markdown
from mineru.render.contracts import RenderMode
from mineru.types import (
    EquationBlock,
    MiddleJson,
    PageBlock,
    PageInfo,
    TextBlock,
)


def _middle(*pages: PageInfo, file_suffix: str = "docx", page_types: dict[str, dict[str, str]] | None = None) -> MiddleJson:
    """构造最小严格 MiddleJson 测试对象。"""
    extensions = build_metadata(
        effort="flash",
        parse_mode="txt",
    )
    if page_types is not None:
        extensions = {**extensions, "mineru_page_types": page_types}
    return MiddleJson(
        pages=list(pages),
        is_full_document=True,
        metadata={"file_suffix": file_suffix, "producer": Producer(name="mineru", version="test")},
        extensions=extensions,
    )


def _page(page_idx: int, *blocks: PageBlock) -> PageInfo:
    """构造一页并保留调用方给定的 block 顺序。"""
    return PageInfo(page_idx=page_idx, blocks=list(blocks))


def test_equation_uses_content_then_image_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证行间公式定界符配置及空公式图片回退。"""
    configured = Config(
        render={
            "latex_delimiters": {
                "display": {"left": "\\[", "right": "\\]"},
                "inline": {"left": "\\(", "right": "\\)"},
            }
        }
    )
    monkeypatch.setattr("mineru.config.config", configured)
    middle = _middle(
        _page(
            0,
            EquationBlock(type="equation", index=0, content="x=1"),
            EquationBlock(type="equation", index=1, content="", image_path="images/e.png"),
            TextBlock(
                type="text",
                index=2,
                content=[{"type": "text", "content": "inline "}, {"type": "equation_inline", "content": "y"}],
            ),
        )
    )

    assert render_markdown(middle) == "\\[\nx=1\n\\]\n\n![](images/e.png)\n\ninline \\(y\\)"


def test_full_mode_inserts_page_type_comments() -> None:
    """FULL 模式在每页内容前插入 page_type 注释（含 secondary）。"""
    middle = _middle(
        _page(0, TextBlock(type="text", index=0, content=[{"type": "text", "content": "cover text"}])),
        _page(1, TextBlock(type="text", index=0, content=[{"type": "text", "content": "toc text"}])),
        page_types={
            "0": {"page_type": "cover"},
            "1": {"page_type": "toc", "page_type_secondary": "copyright"},
        },
    )
    assert render_markdown(middle, mode=RenderMode.FULL) == (
        "<!-- page_type: cover -->\ncover text\n\n---\n\n<!-- page_type: toc; page_type_secondary: copyright -->\ntoc text"
    )


def test_full_mode_skips_pages_without_page_type() -> None:
    """无标注的页保持原样，不插入注释。"""
    middle = _middle(
        _page(0, TextBlock(type="text", index=0, content=[{"type": "text", "content": "cover text"}])),
        _page(1, TextBlock(type="text", index=0, content=[{"type": "text", "content": "body text"}])),
        page_types={"0": {"page_type": "cover"}},
    )
    assert render_markdown(middle, mode=RenderMode.FULL) == ("<!-- page_type: cover -->\ncover text\n\n---\n\nbody text")


def test_default_mode_omits_page_type_comments() -> None:
    """DEFAULT 模式无可靠页边界，不插入注释。"""
    middle = _middle(
        _page(0, TextBlock(type="text", index=0, content=[{"type": "text", "content": "cover text"}])),
        _page(1, TextBlock(type="text", index=0, content=[{"type": "text", "content": "toc text"}])),
        page_types={"0": {"page_type": "cover"}, "1": {"page_type": "toc"}},
    )
    assert render_markdown(middle) == "cover text\n\ntoc text"


def test_full_mode_without_page_types_unchanged() -> None:
    """extensions 无 mineru_page_types 时 FULL 输出与共享渲染一致。"""
    middle = _middle(
        _page(0, TextBlock(type="text", index=0, content=[{"type": "text", "content": "only page"}])),
    )
    assert render_markdown(middle, mode=RenderMode.FULL) == "only page"
