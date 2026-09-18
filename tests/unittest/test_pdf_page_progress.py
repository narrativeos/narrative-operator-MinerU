"""fork 扩展：PDF 页级进度回调事件序列与兜底行为。"""

import asyncio
from types import SimpleNamespace

import pytest
from docvortex.schema import DocumentProperties

import mineru.backend.analyze as analyze_module
from mineru.backend.analysis.pdf import window as window_module


class _FakeDocument:
    """仅提供窗口编排消费的 page_count。"""

    def __init__(self, page_count: int) -> None:
        self.page_count = page_count


class _FakeState:
    """窗口输入占位，满足 _inference_options 与资源关闭契约。"""

    def __init__(self, window: object) -> None:
        self.window = window
        self.images_pil_list = []
        self.high_vlm_blocks = []

    def close(self) -> None:
        return None


class _FakeVlmPredictor:
    """记录一次批量抽取调用并返回空结果。"""

    async def aio_batch_extract_with_layout(self, **options: object) -> list:
        return [[]]


def test_aio_process_pdf_windows_emits_page_stage_events(monkeypatch: pytest.MonkeyPatch) -> None:
    """异步窗口循环按 prepare/inference/postprocess/done 报告页级事件。"""
    monkeypatch.setenv("MINERU_PROCESSING_WINDOW_SIZE", "2")
    events: list[tuple[int, int, str]] = []
    monkeypatch.setattr(window_module, "_prepare_locked_window", lambda *a, **k: _FakeState(a[2]))
    monkeypatch.setattr(
        window_module,
        "_finish_locked_window",
        lambda state, result, **k: [[{}]] * (state.window.end - state.window.start + 1),
    )

    model_list = asyncio.run(
        window_module.aio_process_pdf_windows(
            b"",
            _FakeDocument(5),
            effort="high",
            parse_mode="txt",
            image_analysis=False,
            hybrid_model=object(),
            vlm_predictor=_FakeVlmPredictor(),
            progress_callback=lambda current, total, stage: events.append((current, total, stage)),
        )
    )

    assert len(model_list) == 5
    assert events == [
        (0, 5, "prepare"),
        (0, 5, "inference"),
        (0, 5, "postprocess"),
        (2, 5, "prepare"),
        (2, 5, "inference"),
        (2, 5, "postprocess"),
        (4, 5, "prepare"),
        (4, 5, "inference"),
        (4, 5, "postprocess"),
        (5, 5, "done"),
    ]


def test_progress_callback_exception_does_not_break_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    """进度回调抛异常只告警，解析继续完成。"""
    monkeypatch.setenv("MINERU_PROCESSING_WINDOW_SIZE", "4")
    monkeypatch.setattr(window_module, "_prepare_locked_window", lambda *a, **k: _FakeState(a[2]))
    monkeypatch.setattr(
        window_module,
        "_finish_locked_window",
        lambda state, result, **k: [[{}]] * (state.window.end - state.window.start + 1),
    )

    def broken(current: int, total: int, stage: str) -> None:
        raise RuntimeError("progress sink unavailable")

    model_list = asyncio.run(
        window_module.aio_process_pdf_windows(
            b"",
            _FakeDocument(3),
            effort="high",
            parse_mode="txt",
            image_analysis=False,
            hybrid_model=object(),
            vlm_predictor=_FakeVlmPredictor(),
            progress_callback=broken,
        )
    )

    assert len(model_list) == 3


def test_flash_txt_mode_reports_single_inference_span(monkeypatch: pytest.MonkeyPatch) -> None:
    """Flash TXT 无窗口循环，报告 inference 起点与 done 终点。"""
    events: list[tuple[int, int, str]] = []
    monkeypatch.setattr("docvortex.analyzers.native.PdfModel", lambda: SimpleNamespace(predict=lambda document: [[], [], []]))
    monkeypatch.setattr(window_module, "attach_visual_block_images_from_pdf", lambda *a, **k: None)

    model_list = window_module.process_pdf_windows(
        b"",
        _FakeDocument(3),
        effort="flash",
        parse_mode="txt",
        image_analysis=False,
        flash_txt_mode=True,
        hybrid_model=None,
        vlm_predictor=None,
        progress_callback=lambda current, total, stage: events.append((current, total, stage)),
    )

    assert len(model_list) == 3
    assert events == [(0, 3, "inference"), (3, 3, "done")]


def test_aio_doc_analyze_forwards_progress_callback(monkeypatch: pytest.MonkeyPatch) -> None:
    """非原生异步路径把 progress_callback 透传给同步 doc_analyze。"""
    monkeypatch.setattr("mineru.model.vlm.client.uses_native_async_vlm", lambda vlm_config: False)
    captured: dict[str, object] = {}

    def fake_doc_analyze(*args: object, **kwargs: object) -> tuple[object, object]:
        captured["progress_callback"] = kwargs.get("progress_callback")
        return object(), object()

    monkeypatch.setattr(analyze_module, "doc_analyze", fake_doc_analyze)
    callback = lambda current, total, stage: None  # noqa: E731

    asyncio.run(
        analyze_module.aio_doc_analyze(
            b"",
            effort="medium",
            file_suffix="pdf",
            source_properties=DocumentProperties(),
            progress_callback=callback,
        )
    )

    assert captured["progress_callback"] is callback
