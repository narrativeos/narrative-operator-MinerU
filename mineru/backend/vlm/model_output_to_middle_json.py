# Copyright (c) Opendatalab. All rights reserved.
import os

from tqdm import tqdm

from mineru.backend.utils.html_image_utils import replace_inline_table_images
from mineru.backend.utils.para_block_utils import (
    add_img_path_to_image_blocks,
    assign_block_uuids,
    build_para_blocks_from_preproc,
    cleanup_internal_para_block_metadata,
    merge_para_text_blocks,
)
from mineru.backend.utils.runtime_utils import cross_page_table_merge
from mineru.backend.vlm.vlm_magic_model import MagicModel
from mineru.utils.config_reader import get_table_enable
from mineru.utils.cut_image import cut_image_and_table
from mineru.utils.enum_class import ContentType
from mineru.utils.hash_utils import bytes_md5
from mineru.utils.title_level_postprocess import apply_title_leveling_to_pdf_info
from mineru.utils.pdfium_guard import close_pdfium_child, close_pdfium_document, pdfium_guard
from mineru.version import __version__


def _propagate_vlm_img_path(page_blocks: list, all_spans: list, width: int, height: int) -> None:
    """将截图后生成的 image_path 从 span 提升回对应的原始 VLM block。

    VLM 的 page_blocks 是原始模型输出（不会被 deepcopy），所以可以直接修改。
    注意：原始 VLM block 的 bbox 是 [0,1] 归一化坐标，而 span 的 bbox 是像素坐标，
    需要先将 span bbox 归一化后再匹配。使用容差匹配（±0.01）以处理精度差异。
    """
    # 构建归一化 bbox -> block 的映射（原始 VLM block 使用 [0,1] 坐标）
    # 同时保留原始列表用于容差匹配
    blocks_with_bbox = []
    for block in page_blocks:
        bbox = block.get("bbox")
        if bbox is not None:
            blocks_with_bbox.append(block)

    # 首先尝试精确匹配（round to 2 decimals）
    bbox_to_block: dict[tuple, dict] = {}
    for block in blocks_with_bbox:
        bbox_to_block[tuple(block["bbox"])] = block

    TOLERANCE = 0.01  # 归一化坐标容差
    for span in all_spans:
        span_type = span.get("type")
        if span_type not in (ContentType.IMAGE, ContentType.TABLE, ContentType.CHART, ContentType.INTERLINE_EQUATION):
            continue
        image_path = span.get("image_path")
        if not image_path:
            continue
        span_bbox = span.get("bbox")
        if span_bbox is None:
            continue
        # 将 span 的像素 bbox 归一化为 [0,1] 坐标以匹配原始 VLM block
        s_x0, s_y0, s_x1, s_y1 = span_bbox
        norm_bbox = (
            s_x0 / width,
            s_y0 / height,
            s_x1 / width,
            s_y1 / height,
        )
        # 先尝试精确匹配（保留两位小数）
        exact_key = (
            round(norm_bbox[0], 2),
            round(norm_bbox[1], 2),
            round(norm_bbox[2], 2),
            round(norm_bbox[3], 2),
        )
        block = bbox_to_block.get(exact_key)
        # 如果精确匹配失败，尝试容差匹配
        if block is None:
            for candidate in blocks_with_bbox:
                cb = candidate["bbox"]
                if (abs(cb[0] - norm_bbox[0]) <= TOLERANCE and
                    abs(cb[1] - norm_bbox[1]) <= TOLERANCE and
                    abs(cb[2] - norm_bbox[2]) <= TOLERANCE and
                    abs(cb[3] - norm_bbox[3]) <= TOLERANCE):
                    block = candidate
                    break
        if block is not None:
            block["img_path"] = image_path


def blocks_to_page_info(page_blocks, image_dict, page, image_writer, page_index) -> dict:
    """将blocks转换为页面信息"""

    scale = image_dict["scale"]
    page_pil_img = image_dict["img_pil"]
    page_img_md5 = bytes_md5(page_pil_img.tobytes())
    with pdfium_guard():
        width, height = map(int, page.get_size())

    magic_model = MagicModel(page_blocks, width, height)
    image_blocks = magic_model.get_image_blocks()
    table_blocks = magic_model.get_table_blocks()
    chart_blocks = magic_model.get_chart_blocks()
    title_blocks = magic_model.get_title_blocks()
    discarded_blocks = magic_model.get_discarded_blocks()
    code_blocks = magic_model.get_code_blocks()
    ref_text_blocks = magic_model.get_ref_text_blocks()
    phonetic_blocks = magic_model.get_phonetic_blocks()
    list_blocks = magic_model.get_list_blocks()

    text_blocks = magic_model.get_text_blocks()
    interline_equation_blocks = magic_model.get_interline_equation_blocks()

    all_spans = magic_model.get_all_spans()
    # 对image/table/chart/interline_equation的span截图
    for span in all_spans:
        if span["type"] in [ContentType.IMAGE, ContentType.TABLE, ContentType.CHART, ContentType.INTERLINE_EQUATION]:
            span = cut_image_and_table(span, page_pil_img, page_img_md5, page_index, image_writer, scale=scale)

    # 将 image_path 从 span 提升回对应的原始 block（模型输出），
    # 这样 model.json 中的视觉块也会包含 img_path，便于下游直接访问
    _propagate_vlm_img_path(page_blocks, all_spans, width, height)

    replace_inline_table_images(table_blocks, image_writer, page_index)

    page_blocks = []
    page_blocks.extend([
        *image_blocks,
        *table_blocks,
        *chart_blocks,
        *code_blocks,
        *ref_text_blocks,
        *phonetic_blocks,
        *title_blocks,
        *text_blocks,
        *interline_equation_blocks,
        *list_blocks,
    ])
    # 对page_blocks根据index的值进行排序
    page_blocks.sort(key=lambda x: x["index"])

    page_info = {
        "preproc_blocks": page_blocks,
        "discarded_blocks": discarded_blocks,
        "page_size": [width, height],
        "page_idx": page_index,
    }
    return page_info


def init_middle_json():
    return {"pdf_info": [], "_backend": "vlm", "_version_name": __version__}


def append_page_blocks_to_middle_json(
    middle_json,
    model_output_blocks_list,
    images_list,
    pdf_doc,
    image_writer,
    page_start_index=0,
    progress_bar=None,
):
    for offset, (page_blocks, image_dict) in enumerate(zip(model_output_blocks_list, images_list)):
        page_index = page_start_index + offset
        page = None
        try:
            with pdfium_guard():
                page = pdf_doc[page_index]
            page_info = blocks_to_page_info(page_blocks, image_dict, page, image_writer, page_index)
        finally:
            close_pdfium_child(page)
        middle_json["pdf_info"].append(page_info)
        if progress_bar is not None:
            progress_bar.update(1)


def finalize_middle_json(pdf_info_list):
    """从 VLM preproc_blocks 执行完整 finalize，客户端和服务端完整路径共用。"""
    build_para_blocks_from_preproc(pdf_info_list)
    merge_para_text_blocks(pdf_info_list)

    table_enable = get_table_enable(os.getenv('MINERU_VLM_TABLE_ENABLE', 'True').lower() == 'true')
    if table_enable:
        cross_page_table_merge(pdf_info_list)

    apply_title_leveling_to_pdf_info(pdf_info_list)

    cleanup_internal_para_block_metadata(pdf_info_list)
    add_img_path_to_image_blocks(pdf_info_list)
    assign_block_uuids(pdf_info_list)


def result_to_middle_json(model_output_blocks_list, images_list, pdf_doc, image_writer):
    middle_json = init_middle_json()
    with tqdm(total=len(model_output_blocks_list), desc="Processing pages") as progress_bar:
        append_page_blocks_to_middle_json(
            middle_json,
            model_output_blocks_list,
            images_list,
            pdf_doc,
            image_writer,
            progress_bar=progress_bar,
        )

    finalize_middle_json(middle_json["pdf_info"])
    close_pdfium_document(pdf_doc)
    return middle_json
