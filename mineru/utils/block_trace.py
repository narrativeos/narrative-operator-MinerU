# Copyright (c) Opendatalab. All rights reserved.
"""Block 级溯源工具（fork 扩展，适配 MinerU 4.0 raw model_list）。

MinerU 4.0 的 ``doc_analyze`` 产出严格 ``ModelJson``（raw model_list 为
``list[list[dict]]``，block 含 ``type``/``index``/``bbox``/``content`` 等字段），
再经 docvortex postprocess 转换为 ``MiddleJson``。``MiddleJson`` 的 block 使用
``extra='forbid'``，无法携带自定义字段；而 ``ModelJson`` 的 pages 保留原始
dict，允许额外字段。

本模块提供：

- :func:`assign_block_uuids_to_model_list`：为每个 block 原地写入 ``block_id``
  （确定性 UUIDv5），使 ``model_output.json`` 中的 block 可被下游稳定引用。
  同一文档中身份（页码 + bbox + 内容摘要）相同的 block 在多次
  解析间始终得到相同 ``block_id``，便于跨次运行 diff 与追踪。
- :func:`build_block_id_map`：生成 ``{page_idx: {block_index: block_id}}``
  映射，写入 ``ModelJson.extensions["mineru_block_ids"]``，供
  ``middle_json.json`` / ``structured_content.json`` 等严格产物做溯源。
- :func:`strip_block_ids_from_model_list`：生成去除 ``block_id`` 的深拷贝，
  用于 postprocess 前构造可被 ``MiddleJson`` 接受的输入。
"""

from __future__ import annotations

import copy
import hashlib
import json
import uuid

# 固定命名空间：保证 block_id 在不同进程、不同机器间可复现。
_BLOCK_ID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://mineru.net/block-id")

# bbox 保留小数位：归一化坐标位于 [0, 1]，5 位（1e-5）足以区分不同 block，
# 同时容忍布局/OCR 输出的常见位置抖动（1e-3 量级）与浮点表示噪声。
_BBOX_PRECISION = 5


def _content_digest(block: dict) -> str:
    """计算 block 内容（``content`` 字段）的规范化摘要。

    使用 ``sort_keys`` 的紧凑 JSON 序列化，字段顺序变化不影响摘要；
    无 ``content`` 字段时摘要为空串。
    """
    payload = json.dumps(block.get("content"), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _bbox_key(block: dict, position: int) -> str:
    """生成身份串的位置成分：规范化 bbox；bbox 缺失或非法时回退为页内位置序号。"""
    bbox = block.get("bbox")
    if (
        isinstance(bbox, (list, tuple))
        and len(bbox) == 4
        and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in bbox)
    ):
        return ",".join(f"{float(v):.{_BBOX_PRECISION}f}" for v in bbox)
    return f"pos:{position}"


def _deterministic_block_id(page_idx: int, block: dict, position: int) -> str:
    """由 block 身份（页码 + bbox + 内容摘要）派生 UUIDv5。"""
    identity = f"{page_idx}:{_bbox_key(block, position)}:{_content_digest(block)}"
    return str(uuid.uuid5(_BLOCK_ID_NAMESPACE, identity))


def assign_block_uuids_to_model_list(model_list: list[list[dict]]) -> None:
    """为 raw model_list 中每个 block 原地分配 ``block_id``（确定性 UUIDv5 字符串）。

    已存在 ``block_id`` 的 block 保持不变（幂等）。
    """
    for page_idx, page_blocks in enumerate(model_list):
        for position, block in enumerate(page_blocks):
            if not isinstance(block, dict) or block.get("block_id"):
                continue
            block["block_id"] = _deterministic_block_id(page_idx, block, position)


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
