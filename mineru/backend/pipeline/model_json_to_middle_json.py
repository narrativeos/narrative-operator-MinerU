# Copyright (c) Opendatalab. All rights reserved.
import copy

from tqdm import tqdm

from mineru.backend.utils.html_image_utils import replace_inline_table_images
from mineru.backend.utils.formula_number import optimize_formula_number_blocks
from mineru.backend.utils.para_block_utils import (
    add_img_path_to_image_blocks,
    assign_block_uuids,
    assign_block_uuids_to_model_list,
)
from mineru.backend.utils.runtime_utils import cross_page_table_merge
from mineru.backend.pipeline.model_init import (
    AtomModelSingleton,
    run_ocr_inference,
)
from mineru.backend.pipeline.para_split import para_split
from mineru.backend.pipeline.page_type_classifier import (
    classify_all_pages,
    remove_garbled_blocks,
)
from mineru.utils.cut_image import cut_image_and_table
from mineru.utils.enum_class import ContentType, BlockType
from mineru.utils.title_level_postprocess import apply_title_leveling_to_pdf_info
from mineru.backend.pipeline.pipeline_magic_model import MagicModel
from mineru.utils.ocr_utils import OcrConfidence, rotate_vertical_crop_if_needed
from mineru.version import __version__
from mineru.utils.hash_utils import bytes_md5
from mineru.utils.pdfium_guard import close_pdfium_child, close_pdfium_document, pdfium_guard
from mineru.utils.span_pre_proc import (
    _clear_post_ocr_fallback,
    _restore_post_ocr_fallback,
)


def page_model_info_to_page_info(page_model_info, image_dict, page, image_writer, page_index, ocr_enable=False):
    scale = image_dict["scale"]
    page_pil_img = image_dict["img_pil"]
    page_img_md5 = bytes_md5(page_pil_img.tobytes())
    with pdfium_guard():
        page_w, page_h = map(int, page.get_size())
    magic_model = MagicModel(
        page_model_info,
        page,
        scale,
        page_pil_img,
        page_w,
        page_h,
        ocr_enable
    )

    """从magic_model对象中获取后面会用到的区块信息"""
    preproc_blocks = magic_model.get_preproc_blocks()
    discarded_blocks = magic_model.get_discarded_blocks()
    all_image_spans = magic_model.get_all_image_spans()

    # 对image/table/chart/interline_equation的span截图
    for span in all_image_spans:
        if span["type"] in [
            ContentType.IMAGE,
            ContentType.TABLE,
            ContentType.CHART,
            ContentType.INTERLINE_EQUATION
        ]:
            span = cut_image_and_table(span, page_pil_img, page_img_md5, page_index, image_writer, scale=scale)

    """构造page_info"""
    replace_inline_table_images(preproc_blocks, image_writer, page_index)

    page_info = make_page_info_dict(preproc_blocks, page_index, page_w, page_h, discarded_blocks)

    return page_info


def build_page_model_info(page_layout_dets, page_index, pil_img):
    page_info_dict = {'page_no': page_index, 'width': pil_img.width, 'height': pil_img.height}
    return {'layout_dets': page_layout_dets, 'page_info': page_info_dict}


def append_page_model_infos_to_middle_json(
    middle_json,
    page_model_infos,
    images_list,
    pdf_doc,
    image_writer,
    page_start_index=0,
    ocr_enable=False,
    progress_bar=None,
):
    for offset, (page_model_info, image_dict) in enumerate(zip(page_model_infos, images_list)):
        page_index = page_start_index + offset
        page = None
        try:
            with pdfium_guard():
                page = pdf_doc[page_index]
            page_info = page_model_info_to_page_info(
                copy.deepcopy(page_model_info),
                image_dict,
                page,
                image_writer,
                page_index,
                ocr_enable=ocr_enable,
            )
            if page_info is not None:
                # 将 image_path 从 preproc_blocks 的 span 提升回原始 layout_dets，
                # 这样 model.json 中的视觉块也会包含 img_path，便于下游直接访问
                _propagate_img_path_to_layout_dets(page_model_info, page_info.get("preproc_blocks", []))
            if page_info is None:
                with pdfium_guard():
                    page_w, page_h = map(int, page.get_size())
                page_info = make_page_info_dict([], page_index, page_w, page_h, [])
        finally:
            close_pdfium_child(page)
        middle_json["pdf_info"].append(page_info)
        if progress_bar is not None:
            progress_bar.update(1)


def append_batch_results_to_middle_json(
    middle_json,
    batch_results,
    images_list,
    pdf_doc,
    image_writer,
    page_start_index=0,
    ocr_enable=False,
    model_list=None,
    progress_bar=None,
):
    page_model_infos = []
    for offset, (image_dict, page_layout_dets) in enumerate(zip(images_list, batch_results)):
        page_index = page_start_index + offset
        page_model_info = build_page_model_info(page_layout_dets, page_index, image_dict['img_pil'])
        page_model_infos.append(page_model_info)

    # 在 MagicModel 构造之前为新增的 layout_dets 分配 block_id，
    # 这样 MagicModel.__copy_block_fields 可以继承 block_id 到 preproc_blocks
    # 只处理新增的页面，避免重复遍历已处理的页面
    assign_block_uuids_to_model_list(page_model_infos)
    if model_list is not None:
        model_list.extend(page_model_infos)

    append_page_model_infos_to_middle_json(
        middle_json,
        page_model_infos,
        images_list,
        pdf_doc,
        image_writer,
        page_start_index=page_start_index,
        ocr_enable=ocr_enable,
        progress_bar=progress_bar,
    )


def _iter_block_spans(block):
    for line in block.get("lines", []):
        for span in line.get("spans", []):
            yield span

    for sub_block in block.get("blocks", []):
        yield from _iter_block_spans(sub_block)


def _apply_post_ocr(pdf_info_list, lang=None):
    need_ocr_list = []
    img_crop_list = []

    for page_info in pdf_info_list:
        for block in page_info.get('preproc_blocks', []):
            for span in _iter_block_spans(block):
                if 'np_img' in span:
                    need_ocr_list.append(span)
                    # Keep post-OCR rec aligned with the main OCR pipeline for vertical tall crops.
                    img_crop_list.append(rotate_vertical_crop_if_needed(span['np_img']))
                    span.pop('np_img')

        for block in page_info.get('discarded_blocks', []):
            for span in _iter_block_spans(block):
                if 'np_img' in span:
                    need_ocr_list.append(span)
                    # Keep post-OCR rec aligned with the main OCR pipeline for vertical tall crops.
                    img_crop_list.append(rotate_vertical_crop_if_needed(span['np_img']))
                    span.pop('np_img')

    if len(img_crop_list) == 0:
        return

    atom_model_manager = AtomModelSingleton()
    ocr_model = atom_model_manager.get_atom_model(
        atom_model_name='ocr',
        det_db_box_thresh=0.3,
        lang=lang
    )
    ocr_res_list = run_ocr_inference(
        ocr_model.ocr, img_crop_list, det=False, tqdm_enable=True
    )[0]
    assert len(ocr_res_list) == len(
        need_ocr_list), f'ocr_res_list: {len(ocr_res_list)}, need_ocr_list: {len(need_ocr_list)}'
    for index, span in enumerate(need_ocr_list):
        ocr_text, ocr_score = ocr_res_list[index]
        if ocr_score > OcrConfidence.min_confidence:
            span['content'] = ocr_text
            span['score'] = float(f"{ocr_score:.3f}")
            _clear_post_ocr_fallback(span)
        elif _restore_post_ocr_fallback(span):
            continue
        else:
            span['content'] = ''
            span['score'] = 0.0


def _post_block_process(pdf_info_list):
    for page_info in pdf_info_list:
        for block_key in ["preproc_blocks", "para_blocks"]:
            for block in page_info.get(block_key, []):
                block_type = block.get("type")
                if block_type == BlockType.DOC_TITLE:
                    block["type"] = BlockType.TITLE
                    block["level"] = 1
                elif block_type == BlockType.PARAGRAPH_TITLE:
                    block["type"] = BlockType.TITLE
                    block["level"] = 2
                elif block_type == BlockType.VERTICAL_TEXT:
                    block["type"] = BlockType.TEXT


def apply_server_side_postprocess(pdf_info_list, lang=None):
    """执行只能在服务端完成的后处理；目前仅包含依赖 OCR 模型的 post-OCR。"""
    _apply_post_ocr(pdf_info_list, lang=lang)


def finalize_middle_json_from_preproc(pdf_info_list):
    """从 preproc_blocks 执行确定性 finalize，供服务端完整路径和客户端复用。"""
    remove_garbled_blocks(pdf_info_list)
    optimize_formula_number_blocks(pdf_info_list)
    para_split(pdf_info_list)
    cross_page_table_merge(pdf_info_list)
    apply_title_leveling_to_pdf_info(pdf_info_list)
    _post_block_process(pdf_info_list)
    add_img_path_to_image_blocks(pdf_info_list)
    assign_block_uuids(pdf_info_list)
    # 页面类型分类基于最终的 preproc_blocks，在所有 block 后处理之后执行
    classify_all_pages(pdf_info_list)


def finalize_middle_json(
    pdf_info_list,
    lang=None,
):
    """Apply document-level post processing once all page_info entries are ready."""
    apply_server_side_postprocess(pdf_info_list, lang=lang)
    finalize_middle_json_from_preproc(pdf_info_list)


def init_middle_json():
    return {"pdf_info": [], "_backend": "pipeline", "_version_name": __version__}


def result_to_middle_json(model_list, images_list, pdf_doc, image_writer, lang=None, ocr_enable=False, formula_enable=None):
    middle_json = init_middle_json()
    # 在 MagicModel 构造之前为 layout_dets 分配 block_id
    assign_block_uuids_to_model_list(model_list)
    with tqdm(total=len(model_list), desc="Processing pages") as progress_bar:
        append_page_model_infos_to_middle_json(
            middle_json,
            model_list,
            images_list,
            pdf_doc,
            image_writer,
            ocr_enable=ocr_enable,
            progress_bar=progress_bar,
        )

    finalize_middle_json(middle_json["pdf_info"], lang=lang)
    close_pdfium_document(pdf_doc)
    return middle_json


def _propagate_img_path_to_layout_dets(page_model_info: dict, preproc_blocks: list) -> None:
    """将截图后生成的 image_path 从 preproc_blocks 的 span 提升回原始 layout_dets。

    这样 model.json 中的视觉块也会包含 img_path，便于下游（如 Popo）直接访问，
    而不需要通过 bbox 模糊匹配从 middle.json 补充。

    使用两层匹配策略：
    1. 精确匹配（tuple 键查找）- O(1)
    2. 像素容差匹配（±2 像素）- O(n)，仅在精确匹配失败时启用
    """
    layout_dets = page_model_info.get("layout_dets", [])
    # 构建 bbox -> layout_det 的映射（使用 tuple 作为键）
    bbox_to_det: dict[tuple, dict] = {}
    for det in layout_dets:
        bbox = det.get("bbox")
        if bbox is not None:
            bbox_to_det[tuple(bbox)] = det

    # 从 preproc_blocks 中提取视觉块及其 image_path
    for block in preproc_blocks:
        block_type = block.get("type")
        if block_type not in (
            BlockType.IMAGE_BODY, BlockType.TABLE_BODY,
            BlockType.CHART_BODY, BlockType.INTERLINE_EQUATION,
        ):
            continue
        # 从 body 的 span 中提取 image_path，找到第一个后跳出
        found = False
        for line in block.get("lines", []):
            if found:
                break
            for span in line.get("spans", []):
                span_type = span.get("type")
                if span_type not in (ContentType.IMAGE, ContentType.TABLE, ContentType.CHART, ContentType.INTERLINE_EQUATION):
                    continue
                image_path = span.get("image_path")
                if not image_path:
                    continue
                span_bbox = span.get("bbox")
                if span_bbox is None:
                    continue
                # 策略 1: 精确匹配
                det = bbox_to_det.get(tuple(span_bbox))
                # 策略 2: 精确匹配失败时，像素容差匹配（±2 像素）
                if det is None:
                    det = _find_layout_det_by_bbox_tolerance(layout_dets, span_bbox, tolerance=2)
                if det is not None:
                    det["img_path"] = image_path
                    found = True
                    break


def _find_layout_det_by_bbox_tolerance(layout_dets: list, target_bbox: list, tolerance: int = 2) -> dict | None:
    """在 layout_dets 中寻找 bbox 与目标 bbox 在容差范围内的 layout_det。

    Args:
        layout_dets: layout_det 列表
        target_bbox: 目标 bbox [x0, y0, x1, y1]
        tolerance: 像素容差（默认 ±2 像素）

    Returns:
        匹配的 layout_det，或 None
    """
    for det in layout_dets:
        bbox = det.get("bbox")
        if bbox is None:
            continue
        if (abs(bbox[0] - target_bbox[0]) <= tolerance and
            abs(bbox[1] - target_bbox[1]) <= tolerance and
            abs(bbox[2] - target_bbox[2]) <= tolerance and
            abs(bbox[3] - target_bbox[3]) <= tolerance):
            return det
    return None


def make_page_info_dict(blocks, page_id, page_w, page_h, discarded_blocks):
    return_dict = {
        'preproc_blocks': blocks,
        'page_idx': page_id,
        'page_size': [page_w, page_h],
        'discarded_blocks': discarded_blocks,
    }
    return return_dict
