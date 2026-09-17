# Copyright (c) Opendatalab. All rights reserved.
"""Fork 扩展包：页面类型分类等 3.x 遗留工具（4.0 架构下的适配层）。"""

from .page_type_classifier import (
    classify_all_pages,
    classify_model_list,
    infer_page_type,
    raw_model_list_to_page_infos,
    remove_garbled_model_blocks,
)

__all__ = [
    "classify_all_pages",
    "classify_model_list",
    "infer_page_type",
    "raw_model_list_to_page_infos",
    "remove_garbled_model_blocks",
]
