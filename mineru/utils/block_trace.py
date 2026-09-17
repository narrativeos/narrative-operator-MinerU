# Copyright (c) Opendatalab. All rights reserved.
"""Block 级溯源工具（fork 扩展，适配 MinerU 4.0 raw model_list）。

MinerU 4.0 的 ``doc_analyze`` 产出严格 ``ModelJson``（raw model_list 为
``list[list[dict]]``，block 含 ``type``/``index``/``bbox``/``content`` 等字段），
再经 docvortex postprocess 转换为 ``MiddleJson``。``MiddleJson`` 的 block 使用
``extra='forbid'``，无法携带自定义字段；而 ``ModelJson`` 的 pages 保留原始
dict，允许额外字段。

本模块提供：

- :func:`assign_block_uuids_to_model_list`：为每个 block 原地写入 ``block_id``
  （UUID），使 ``model_output.json`` 中的 block 可被下游稳定引用。
- :func:`build_block_id_map`：生成 ``{page_idx: {block_index: block_id}}``
  映射，写入 ``ModelJson.extensions["mineru_block_ids"]``，供
  ``middle_json.json`` / ``structured_content.json`` 等严格产物做溯源。
- :func:`strip_block_ids_from_model_list`：生成去除 ``block_id`` 的深拷贝，
  用于 postprocess 前构造可被 ``MiddleJson`` 接受的输入。
"""

from __future__ import annotations

import copy
import uuid


def assign_block_uuids_to_model_list(model_list: list[list[dict]]) -> None:
    """为 raw model_list 中每个 block 原地分配 ``block_id``（UUID 字符串）。

    已存在 ``block_id`` 的 block 保持不变（幂等）。
    """
    for page_blocks in model_list:
        for block in page_blocks:
            if isinstance(block, dict) and not block.get("block_id"):
                block["block_id"] = str(uuid.uuid4())


def build_block_id_map(model_list: list[list[dict]]) -> dict[str, dict[str, str]]:
    """生成 ``{str(page_idx): {str(block_index): block_id}}`` 映射。

    ``block_index`` 取 block 的 ``index`` 字段（4.0 raw model_list 的原始
    块序号）；缺失时回退为页面内位置序号。
    """
    mapping: dict[str, dict[str, str]] = {}
    for page_idx, page_blocks in enumerate(model_list):
        page_map: dict[str, str] = {}
        for position, block in enumerate(page_blocks):
            if not isinstance(block, dict):
                continue
            block_id = block.get("block_id")
            if not block_id:
                continue
            index = block.get("index", position)
            page_map[str(index)] = str(block_id)
        if page_map:
            mapping[str(page_idx)] = page_map
    return mapping


def strip_block_ids_from_model_list(model_list: list[list[dict]]) -> list[list[dict]]:
    """返回去除 ``block_id`` 字段的深拷贝（不修改原列表）。

    docvortex postprocess 的 ``MiddleJson`` 校验禁止 block 携带额外字段，
    因此 postprocess 前必须使用本函数生成的干净副本。
    """
    clean: list[list[dict]] = []
    for page_blocks in model_list:
        clean_page: list[dict] = []
        for block in page_blocks:
            if isinstance(block, dict) and "block_id" in block:
                clean_page.append({k: v for k, v in block.items() if k != "block_id"})
            else:
                clean_page.append(copy.deepcopy(block))
        clean.append(clean_page)
    return clean


__all__ = [
    "assign_block_uuids_to_model_list",
    "build_block_id_map",
    "strip_block_ids_from_model_list",
]
