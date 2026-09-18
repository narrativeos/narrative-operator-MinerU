# Copyright (c) Opendatalab. All rights reserved.
"""统一 PDF、EPUB、HTML、OFD、CSV/TSV 与 Office/RTF 文档分析的稳定公共门面。"""

from __future__ import annotations

from typing import cast

from docvortex.document.contracts import HtmlSourceContext
from docvortex.schema import DocumentMetadata, DocumentProperties, Producer
from loguru import logger

from ..config import VlmConfig, config
from ..integrations.docvortex import build_metadata, read_source_properties
from ..types import FILE_SUFFIXES, FileSuffix, MiddleJson, ModelJson
from ..utils.async_utils import run_sync
from ..utils.logger import configure_global_log_level
from ..version import __version__ as mineru_version
from .analysis.contracts import AnalysisResult, AnalyzeEffort, OfficeSuffix, PageProgressCallback, ParseMode

_SUPPORTED_ANALYZE_EFFORTS = {"flash", "medium", "high", "xhigh"}


def _log_infer_performance(file_suffix: str, page_count: int, elapsed: float) -> None:
    """使用未舍入耗时统一记录 model-list 生产速度。"""
    speed = page_count / elapsed if elapsed > 0 else 0.0
    logger.debug(
        f"model_list infer finished, file_suffix={file_suffix}, pages={page_count}, "
        f"cost={elapsed:.6f}s, speed={speed:.3f} page/s"
    )


def doc_analyze(
    file_bytes: bytes,
    effort: AnalyzeEffort = "high",
    parse_mode: ParseMode = "auto",
    image_analysis: bool = True,
    page_index_map: list[int] | None = None,
    file_suffix: FileSuffix = "pdf",
    source_context: HtmlSourceContext | None = None,
    vlm_config: VlmConfig | None = None,
    source_properties: DocumentProperties | None = None,
    progress_callback: PageProgressCallback | None = None,
) -> tuple[MiddleJson, ModelJson]:
    """生产严格 ModelJson，并在统一边界构造严格 MiddleJson。

    fork 扩展：``progress_callback`` 仅 PDF 输入生效，报告页级进度事件。
    """
    configure_global_log_level()
    _validate_analyze(effort, file_suffix, page_index_map)

    if source_properties is None:
        source_properties = read_source_properties(file_bytes, file_suffix, source_context)

    if file_suffix == "pdf":
        from .analysis.pdf.pipeline import analyze_pdf

        result = analyze_pdf(
            file_bytes,
            effort=effort,
            parse_mode=parse_mode,
            image_analysis=image_analysis,
            vlm_config=vlm_config,
            progress_callback=progress_callback,
        )
    elif file_suffix in ("csv", "tsv"):
        from .analysis.csv import analyze_csv

        result = analyze_csv(file_bytes)
    elif file_suffix == "epub":
        from .analysis.epub import analyze_epub

        result = analyze_epub(file_bytes)
    elif file_suffix == "html":
        from .analysis.html import analyze_html

        result = analyze_html(file_bytes, source_context=source_context)
    elif file_suffix == "ofd":
        from .analysis.ofd import analyze_ofd

        result = analyze_ofd(file_bytes)
    else:
        from .analysis.office import analyze_office

        result = analyze_office(file_bytes, cast(OfficeSuffix, file_suffix))

    if file_suffix == "pdf":
        _apply_page_traceability(result)

    model_json = _build_model_json(result, file_suffix, page_index_map, source_properties)
    from .postprocess.document import model_json_to_middle_json

    middle_json = model_json_to_middle_json(
        _model_json_for_postprocess(model_json),
        llm_aided_config=config.llm_aided,
    )
    return middle_json, model_json


async def aio_doc_analyze(
    file_bytes: bytes,
    effort: AnalyzeEffort = "high",
    parse_mode: ParseMode = "auto",
    image_analysis: bool = True,
    page_index_map: list[int] | None = None,
    file_suffix: FileSuffix = "pdf",
    source_context: HtmlSourceContext | None = None,
    vlm_config: VlmConfig | None = None,
    source_properties: DocumentProperties | None = None,
    progress_callback: PageProgressCallback | None = None,
) -> tuple[MiddleJson, ModelJson]:
    """vLLM/HTTP 的 PDF 分析使用原生异步编排，其余路径保持受控线程回退。

    fork 扩展：``progress_callback`` 仅 PDF 输入生效，报告页级进度事件。
    """
    configure_global_log_level()
    _validate_analyze(effort, file_suffix, page_index_map)
    native_async = False
    if file_suffix == "pdf" and effort in {"high", "xhigh"}:
        from ..model.vlm.client import uses_native_async_vlm

        native_async = await run_sync(uses_native_async_vlm, vlm_config)
    if not native_async:
        return await run_sync(
            doc_analyze,
            file_bytes=file_bytes,
            effort=effort,
            parse_mode=parse_mode,
            image_analysis=image_analysis,
            page_index_map=page_index_map,
            file_suffix=file_suffix,
            source_context=source_context,
            vlm_config=vlm_config,
            source_properties=source_properties,
            progress_callback=progress_callback,
        )
    if source_properties is None:
        source_properties = await run_sync(read_source_properties, file_bytes, file_suffix, source_context)
    from .analysis.pdf.pipeline import aio_analyze_pdf
    from .postprocess.document import aio_model_json_to_middle_json

    result = await aio_analyze_pdf(
        file_bytes,
        effort=effort,
        parse_mode=parse_mode,
        image_analysis=image_analysis,
        vlm_config=vlm_config,
        progress_callback=progress_callback,
    )
    await run_sync(_apply_page_traceability, result)
    model_json = await run_sync(_build_model_json, result, file_suffix, page_index_map, source_properties)
    middle_json = await aio_model_json_to_middle_json(
        _model_json_for_postprocess(model_json), llm_aided_config=config.llm_aided
    )
    return middle_json, model_json


def _validate_analyze(effort: AnalyzeEffort, file_suffix: FileSuffix, page_index_map: list[int] | None) -> None:
    """在加载重依赖之前统一验证同步、异步入口参数。"""
    if file_suffix not in FILE_SUFFIXES:
        raise ValueError(f"Unsupported file suffix: {file_suffix!r}")
    if file_suffix != "pdf" and page_index_map:
        raise ValueError(f"page_index_map is only supported for PDF files, got {file_suffix!r}")
    if effort not in _SUPPORTED_ANALYZE_EFFORTS:
        raise ValueError(f"Unsupported analyze effort: {effort}")


def _apply_page_traceability(result: AnalysisResult) -> None:
    """fork 扩展：乱码清理 + block_id 分配 + 页面类型分类（仅 PDF）。

    在 ModelJson 构造前操作 raw model_list：
    - 乱码 block 直接删除，不会出现在任何下游产物中；
    - ``block_id`` 写入 block（ModelJson 允许额外字段，model_output.json 保留）；
    - block_id 映射与页面类型写入 result，由 :func:`_build_model_json`
      放入 extensions（postprocess 自动透传到 middle_json.json /
      structured_content.json）。
    """
    from ..utils.block_trace import assign_block_uuids_to_model_list, build_block_id_map
    from .pipeline.page_type_classifier import classify_model_list, remove_garbled_model_blocks

    removed = remove_garbled_model_blocks(result.model_list)
    if removed:
        logger.info(f"page traceability: removed {removed} garbled blocks")
    assign_block_uuids_to_model_list(result.model_list)
    result.block_id_map = build_block_id_map(result.model_list)
    result.page_types = classify_model_list(result.model_list)


def _model_json_for_postprocess(model_json: ModelJson) -> ModelJson:
    """fork 扩展：若 block 含 ``block_id``，生成去除该字段的副本供 postprocess。

    docvortex postprocess 的 MiddleJson block 校验禁止额外字段
    （``extra='forbid'``），postprocess 前必须剥离 ``block_id``；
    返回给调用方的 ModelJson（model_output.json）仍保留 ``block_id``。
    """
    has_block_id = any(isinstance(block, dict) and "block_id" in block for page in model_json.pages for block in page)
    if not has_block_id:
        return model_json
    from ..utils.block_trace import strip_block_ids_from_model_list

    return model_json.model_copy(update={"pages": strip_block_ids_from_model_list(model_json.pages)})


def _build_model_json(
    result: AnalysisResult,
    file_suffix: FileSuffix,
    page_index_map: list[int] | None,
    source_properties: DocumentProperties,
) -> ModelJson:
    """共享模型协议构造，保持生产者、页映射和 MinerU 扩展完全一致。"""
    _log_infer_performance(file_suffix, len(result.model_list), result.elapsed)
    extensions = build_metadata(effort=result.effort, parse_mode=result.parse_mode)
    if file_suffix == "pdf" and result.layout_geometry is not None:
        from docvortex.document.pdf.layout import LAYOUT_EXTENSION, remap_layout_geometry

        extensions[LAYOUT_EXTENSION] = remap_layout_geometry(result.layout_geometry, page_index_map)
    # fork 扩展：block 溯源映射与页面类型分类
    if result.block_id_map:
        extensions["mineru_block_ids"] = result.block_id_map
    if result.page_types:
        extensions["mineru_page_types"] = result.page_types
    return ModelJson(
        pages=result.model_list,
        page_index_map=page_index_map or [],
        metadata=DocumentMetadata(
            file_suffix=file_suffix,
            producer=Producer(name="mineru", version=mineru_version),
            document=source_properties.model_copy(deep=True),
        ),
        extensions=extensions,
    )


__all__ = ["doc_analyze", "aio_doc_analyze"]
