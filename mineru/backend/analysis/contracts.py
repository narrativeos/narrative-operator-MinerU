# Copyright (c) Opendatalab. All rights reserved.
"""文档分析分支汇合前使用的内部结果契约。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal, TypeAlias

AnalyzeEffort: TypeAlias = Literal["flash", "medium", "high", "xhigh"]
# 请求阶段允许自动分类，分析结果中的模式必须已经收敛为 txt 或 ocr。
ParseMode: TypeAlias = Literal["auto", "txt", "ocr"]
ResolvedParseMode: TypeAlias = Literal["txt", "ocr"]
OfficeSuffix: TypeAlias = Literal["doc", "docx", "ppt", "pptx", "xls", "xlsx", "rtf", "odt", "ods", "odp"]
# fork 扩展：PDF 页级进度阶段。prepare=窗口渲染准备，inference=VLM/OCR 推理，
# postprocess=窗口内回填，done=全部页面完成（current_page == total_pages）。
PageProgressStage: TypeAlias = Literal["prepare", "inference", "postprocess", "done"]
# fork 扩展：页级进度回调 (current_page, total_pages, stage)。
# current_page 为 0 基的下一个待处理页索引，done 时等于 total_pages。
PageProgressCallback: TypeAlias = Callable[[int, int, PageProgressStage], None]


@dataclass(slots=True)
class AnalysisResult:
    """封装 model-list 及分析分支最终采用的元数据和计时结果。"""

    model_list: list[list[dict[str, Any]]]
    effort: AnalyzeEffort
    parse_mode: ResolvedParseMode
    elapsed: float
    layout_geometry: dict[str, Any] | None = None
    # fork 扩展：block 溯源映射 {str(page_idx): {str(block_index): block_id}}
    block_id_map: dict[str, dict[str, str]] | None = None
    # fork 扩展：页面类型分类 {str(page_idx): {"page_type": ..., ...}}
    page_types: dict[str, dict[str, str]] | None = None
