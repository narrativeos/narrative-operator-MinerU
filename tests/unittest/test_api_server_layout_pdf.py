"""fork 扩展：layout_pdf 输出格式与 PDF 页级进度 API 行为。"""

import asyncio
import io
from pathlib import Path

import pytest
from docvortex.schema import MiddleJson, PageInfo, Producer, TextBlock
from pypdf import PdfReader, PdfWriter

import mineru.parser.api_server as api_server
from mineru.integrations.docvortex import build_metadata
from mineru.parser import ParseResult
from mineru.parser.api_server import CreateJobRequest, FileStore


def _three_page_pdf() -> bytes:
    """构造 3 页空白 PDF，页面无可提取文本，便于断言叠加层。"""
    writer = PdfWriter()
    for _ in range(3):
        writer.add_blank_page(width=612, height=792)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _middle_json_with_boxes() -> MiddleJson:
    """每页一个带 bbox 的 text block，供版面框绘制消费。"""
    pages = [
        PageInfo(
            page_idx=idx,
            blocks=[
                TextBlock(type="text", index=0, bbox=(0.1, 0.1, 0.5, 0.3), content=[{"type": "text", "content": f"p{idx}"}])
            ],
        )
        for idx in range(3)
    ]
    return MiddleJson(
        pages=pages,
        is_full_document=True,
        metadata={"file_suffix": "pdf", "producer": Producer(name="mineru", version="test")},
        extensions=build_metadata(effort="medium", parse_mode="txt"),
    )


def _page_text(pdf_bytes: bytes, index: int) -> str:
    return PdfReader(io.BytesIO(pdf_bytes)).pages[index].extract_text() or ""


def test_layout_pdf_format_is_registered() -> None:
    """layout_pdf 进入本地默认输出格式与 OutputFiles 响应模型。"""
    assert "layout_pdf" in api_server._LOCAL_PARSE_OUTPUT_FORMATS
    assert "layout_pdf" in api_server.OutputFiles.model_fields
    assert "progress" in api_server.JobFileResult.model_fields


def test_render_layout_pdf_full_document_overlays_every_page() -> None:
    """无页范围时全部页面绘制版面框，标签可提取。"""
    pdf_bytes = _three_page_pdf()
    result = ParseResult(middle_json=_middle_json_with_boxes())

    out = api_server._render_layout_pdf_bytes(pdf_bytes, result, "")

    assert len(PdfReader(io.BytesIO(out)).pages) == 3
    for idx in range(3):
        assert "text" in _page_text(out, idx)


def test_render_layout_pdf_page_range_only_overlays_selected_page() -> None:
    """页范围只叠加选中页，其余页保持原始内容。"""
    pdf_bytes = _three_page_pdf()
    result = ParseResult(middle_json=_middle_json_with_boxes())

    out = api_server._render_layout_pdf_bytes(pdf_bytes, result, "2")

    assert "text" not in _page_text(out, 0)
    assert "text" in _page_text(out, 1)
    assert "text" not in _page_text(out, 2)


def test_run_job_exposes_page_progress_and_layout_pdf(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """_run_job 透传页级进度回调，完成后清除 progress 并产出 layout.pdf。"""
    pdf_bytes = _three_page_pdf()
    source = tmp_path / "demo.pdf"
    source.write_bytes(pdf_bytes)
    events: list[tuple[int, int, str]] = []

    async def fake_parse_async(*args: object, **kwargs: object) -> ParseResult:
        callback = kwargs.get("progress_callback")
        assert callable(callback)
        callback(0, 3, "prepare")
        callback(2, 3, "inference")
        callback(3, 3, "done")
        events.extend([(0, 3, "prepare"), (2, 3, "inference"), (3, 3, "done")])
        return ParseResult(middle_json=_middle_json_with_boxes())

    monkeypatch.setattr("mineru.parser.api_server.parse_async", fake_parse_async)
    file_store = FileStore(tmp_path / "api-files")
    request = CreateJobRequest.model_validate(
        {
            "files": [{"source": {"type": "local", "path": str(source)}}],
            "tier": "standard",
            "output_formats": ["middle_json", "layout_pdf"],
        }
    )
    rec = api_server.JobStore().create(request, file_store)

    asyncio.run(
        api_server._run_job(
            rec,
            request,
            file_store,
            image_analysis=True,
            allow_local_source=True,
        )
    )

    assert events == [(0, 3, "prepare"), (2, 3, "inference"), (3, 3, "done")]
    fr = rec.files[0]
    assert fr.status == "completed"
    assert fr.progress is None
    assert fr.output_files is not None
    assert fr.output_files.layout_pdf is not None
    assert fr.output_files.layout_pdf.file_id is not None
