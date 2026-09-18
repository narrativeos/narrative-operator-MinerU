# -*- coding: utf-8 -*-
"""从 MinerU 输出 (model.json + middle.json) 提取逐页版面量化指标。

数据源:
    model.json   : 布局模型原始检测 (逐页 block 列表, 归一化 bbox, 13 类细粒度类型)
    middle.json  : 后处理结果 (pdf_info 逐页, 绝对 pt bbox, 6 类类型,
                   lines/spans 含 OCR score, 表格块含 table_body 子块)

指标口径 (自一致性 / 结构启发式, 无需 Ground Truth):
    C1 重叠面积比(+)          : 后处理块与原始检测框的重叠面积 / 后处理块面积
    C2 曼哈顿角点对齐误差(-)  : 块边到对齐簇 (页边距/栏边界) 的平均曼哈顿偏离 (pt)
    C3 边覆盖匹配相似度(+)    : 块边被其他共线块边覆盖的平均长度比例
    C4 平均交并比mIoU(+)      : 原始检测与后处理匹配框对的平均 IoU
    C5 边界精度(+)            : 1 - 匹配框对平均归一化边界位移
    C6 像素准确率(+)          : 匹配框对交集/并集面积的聚合比值
    C7 空间得分(+)            : 边距均衡 + 左缘规整度 + 垂直间距规律性
    C8 锚点得分(+)            : 锚点关联满足率 (image↔caption, paragraph_title→正文)
    C9 格式得分(+)            : span 高度一致性 + 行距规律性 + 行左缘对齐一致性
    C10 上下文得分(+)         : 阅读顺序 (index) 与空间顺序的一致率
    C11 统一页面分区评分(+)   : 正文类块面积落入估计正文区的比例
    C12 块级语义纯度(+)       : 块类型-内容一致性 (结合 OCR 置信度)

辅助字段 (供 BookAggregator 去噪/跨页对称分析):
    coverage 版面覆盖率 | text_blocks 文本块数 | center 视觉重心 | page_width 页宽
"""
import json
import os

import numpy as np

from .indicators import N_IND
from .aggregator import BookAggregator, page_gravity

# middle.json 块类型 <- 可匹配的 model.json 原始类型
# (4.0 的 model/middle 共用同一套 BlockType 字符串, chart 归入 image 兼容集)
MODEL_TO_MIDDLE_TYPES = {
    'title': {'doc_title', 'paragraph_title', 'title'},
    'text': {'text', 'ocr_text'},
    'table': {'table'},
    'image': {'image', 'chart'},
    'interline_equation': {'equation', 'inline_formula'},
    'ref_text': {'ref_text'},
}

# 4.0 块类型 (BlockType 字符串) -> 3.x middle 块类型
_40_TO_LEGACY_TYPE = {
    'text': 'text',
    'doc_title': 'title',
    'paragraph_title': 'title',
    'title': 'title',
    'table': 'table',
    'image': 'image',
    'chart': 'image',
    'equation': 'interline_equation',
    'ref_text': 'ref_text',
    'list': 'text',
    'index': 'text',
    'code': 'text',
    'header': 'text',
    'footer': 'text',
    'page_number': 'text',
    'aside_text': 'text',
    'page_footnote': 'text',
}

# docvortex_layout 扩展缺失时的兜底页尺寸 (A4, pt)
_DEFAULT_PAGE_SIZE = (595.0, 842.0)

# 正文类块 (参与空间/分区类指标)
BODY_TYPES = ('text', 'title', 'table', 'interline_equation', 'ref_text')
# 文本类块 (参与噪声页剔除/格式类指标)
TEXT_TYPES = ('text', 'title', 'ref_text')


# ============================================================
# 几何基础
# ============================================================
def _box_area(box):
    x1, y1, x2, y2 = box
    return max(0.0, (x2 - x1) * (y2 - y1))


def _inter_area(a, b):
    lo_x = max(a[0], b[0])
    lo_y = max(a[1], b[1])
    hi_x = min(a[2], b[2])
    hi_y = min(a[3], b[3])
    if hi_x <= lo_x or hi_y <= lo_y:
        return 0.0
    return (hi_x - lo_x) * (hi_y - lo_y)


def _iou(a, b):
    inter = _inter_area(a, b)
    union = _box_area(a) + _box_area(b) - inter
    return inter / union if union > 0 else 0.0


def _h_overlap_ratio(a, b):
    """水平方向重叠比例 (相对较窄块)。"""
    lo = max(a[0], b[0])
    hi = min(a[2], b[2])
    if hi <= lo:
        return 0.0
    narrow = min(a[2] - a[0], b[2] - b[0])
    return (hi - lo) / narrow if narrow > 0 else 0.0


def _one_minus_cv(vals):
    """1 - 变异系数, 截断到 [0, 1]; 数据不足时返回中性值 0.5。"""
    if len(vals) < 2:
        return 0.5
    m = float(np.mean(vals))
    if m <= 1e-9:
        return 0.5
    return float(np.clip(1.0 - float(np.std(vals)) / m, 0.0, 1.0))


def _edge_tol(page_w, page_h, tol_pt=2.0):
    """边对齐容差: 至少 2pt, 且不超过页面短边的 0.5%。"""
    return max(tol_pt, 0.005 * min(page_w, page_h))


# ============================================================
# model.json <-> middle.json 框匹配
# ============================================================
def _match_boxes(middle_blocks, model_abs):
    """贪心匹配 middle 块与 model 框 (类型兼容 + IoU 最大)。
    model_abs: [(box, model_type), ...] 绝对坐标
    返回 [(mid_idx, model_idx, iou), ...]"""
    pairs = []
    for i, mb in enumerate(middle_blocks):
        compat = MODEL_TO_MIDDLE_TYPES.get(mb['type'], set())
        for j, (box, mtype) in enumerate(model_abs):
            if mtype not in compat:
                continue
            v = _iou(mb['bbox'], box)
            if v > 0.05:
                pairs.append((v, i, j))
    pairs.sort(reverse=True)
    used_m, used_x = set(), set()
    matched = []
    for v, i, j in pairs:
        if i in used_m or j in used_x:
            continue
        used_m.add(i)
        used_x.add(j)
        matched.append((i, j, v))
    return matched


# ============================================================
# B1 空间拓扑与相对关系
# ============================================================
def _c1_overlap_ratio(blocks, model_abs):
    """C1 重叠面积比(+): 后处理块与原始检测框的重叠面积 / 后处理块面积。
    衡量后处理结果是否被原始检测支撑 (不凭空造框)。"""
    total = 0.0
    covered = 0.0
    for b in blocks:
        area = _box_area(b['bbox'])
        if area <= 0:
            continue
        total += area
        best = 0.0
        for box, _ in model_abs:
            best = max(best, _inter_area(b['bbox'], box))
        covered += min(best, area)
    return covered / total if total > 0 else 0.0


def _c2_alignment_error(blocks, page_w, page_h):
    """C2 曼哈顿角点对齐误差(-): 块边到对齐簇的平均曼哈顿偏离 (pt)。
    将全部竖直边/水平边坐标做 1D 聚类 (簇中心即对齐线), 取各边到最近簇中心的距离均值。"""
    xs, ys = [], []
    for b in blocks:
        x1, y1, x2, y2 = b['bbox']
        xs.extend([x1, x2])
        ys.extend([y1, y2])

    def cluster_dev(coords, span):
        if not coords:
            return 0.0
        tau = _edge_tol(span, span)
        coords = sorted(coords)
        clusters = [[coords[0]]]
        for c in coords[1:]:
            if c - clusters[-1][-1] <= tau:
                clusters[-1].append(c)
            else:
                clusters.append([c])
        centers = [sum(cl) / len(cl) for cl in clusters]
        return sum(min(abs(c - ce) for ce in centers) for c in coords) / len(coords)

    return (cluster_dev(xs, page_w) + cluster_dev(ys, page_h)) / 2.0


def _c3_edge_coverage(blocks, page_w, page_h):
    """C3 最小权重边覆盖匹配相似度(+): 每条块边被其他共线块边覆盖的平均长度比例。
    衡量块边之间的对齐/延续结构 (栏线、边距、表格线等)。"""
    tau = _edge_tol(page_w, page_h)
    v_edges = []   # (x, y1, y2)
    h_edges = []   # (y, x1, x2)
    for b in blocks:
        x1, y1, x2, y2 = b['bbox']
        if x2 > x1:
            v_edges.append((x1, y1, y2))
            v_edges.append((x2, y1, y2))
        if y2 > y1:
            h_edges.append((y1, x1, x2))
            h_edges.append((y2, x1, x2))

    def coverage(edges):
        if not edges:
            return 1.0
        total = 0.0
        for k, (c, a, b2) in enumerate(edges):
            length = b2 - a
            if length <= 0:
                continue
            ivs = []
            for j, (c2, a2, b3) in enumerate(edges):
                if j == k or abs(c2 - c) > tau:
                    continue
                lo, hi = max(a, a2), min(b2, b3)
                if hi > lo:
                    ivs.append((lo, hi))
            ivs.sort()
            covered, cur_lo, cur_hi = 0.0, None, None
            for lo, hi in ivs:
                if cur_lo is None:
                    cur_lo, cur_hi = lo, hi
                elif lo <= cur_hi:
                    cur_hi = max(cur_hi, hi)
                else:
                    covered += cur_hi - cur_lo
                    cur_lo, cur_hi = lo, hi
            if cur_lo is not None:
                covered += cur_hi - cur_lo
            total += min(covered, length) / length
        return total / len(edges)

    return (coverage(v_edges) + coverage(h_edges)) / 2.0


# ============================================================
# B2 像素级与边界精度 (model.json <-> middle.json 自一致性)
# ============================================================
def _c456_boundary_metrics(blocks, model_abs, page_w, page_h):
    """C4 mIoU(+) / C5 边界精度(+) / C6 像素准确率(+)。
    C4: 匹配框对平均 IoU (逐对平均, 小框权重高)
    C5: 1 - 匹配框对平均归一化边界位移 (对微小偏移敏感)
    C6: 匹配框对交集/并集面积的聚合比值 (整体像素口径)"""
    matched = _match_boxes(blocks, model_abs)
    if not matched:
        return 0.0, 0.0, 0.0
    ious = [v for _, _, v in matched]
    c4 = float(np.mean(ious))
    shifts = []
    inter_sum, union_sum = 0.0, 0.0
    for i, j, _ in matched:
        a = blocks[i]['bbox']
        b = model_abs[j][0]
        num = (abs(a[0] - b[0]) + abs(a[2] - b[2])
               + abs(a[1] - b[1]) + abs(a[3] - b[3]))
        shifts.append(num / (2.0 * (page_w + page_h)))
        inter = _inter_area(a, b)
        inter_sum += inter
        union_sum += _box_area(a) + _box_area(b) - inter
    c5 = float(np.clip(1.0 - float(np.mean(shifts)), 0.0, 1.0))
    c6 = inter_sum / union_sum if union_sum > 0 else 0.0
    return c4, c5, c6

# ============================================================
# B3 多模态复合评分 (结构启发式)
# ============================================================
def _c7_spatial_score(blocks, page_w, page_h):
    """C7 空间得分(+): 左缘规整度 + 左右边距均衡 + 垂直间距规律性。"""
    body = [b for b in blocks if b['type'] in BODY_TYPES]
    if len(body) < 3:
        return 0.5
    lefts = [b['bbox'][0] for b in body]
    rights = [page_w - b['bbox'][2] for b in body]
    s_left = _one_minus_cv(lefts)
    s_bal = float(np.clip(1.0 - abs(float(np.mean(lefts)) - float(np.mean(rights))) / page_w, 0.0, 1.0))
    ordered = sorted(body, key=lambda b: (b['bbox'][1], b['bbox'][0]))
    gaps = []
    for a, b in zip(ordered, ordered[1:]):
        gap = b['bbox'][1] - a['bbox'][3]
        if -0.05 * page_h <= gap <= 0.5 * page_h:
            gaps.append(abs(gap))
    s_gap = _one_minus_cv(gaps) if len(gaps) >= 3 else 0.5
    return float(np.mean([s_left, s_bal, s_gap]))


def _c8_anchor_score(model_abs, page_h):
    """C8 锚点得分(+): 锚点关联满足率。
    检查: image 附近存在 caption/footnote; paragraph_title 下方存在正文块。"""
    images = [box for box, t in model_abs if t == 'image']
    captions = [box for box, t in model_abs if t in ('image_caption', 'image_footnote')]
    titles = [box for box, t in model_abs if t == 'paragraph_title']
    texts = [box for box, t in model_abs if t in ('text', 'ocr_text')]
    checks = []
    for img in images:
        h = max(img[3] - img[1], 1e-9)
        ok = any(_h_overlap_ratio(img, cap) > 0.3
                 and -0.2 * h <= cap[1] - img[3] <= 1.5 * h
                 for cap in captions)
        checks.append(ok)
    for t in titles:
        ok = any(_h_overlap_ratio(t, tx) > 0.3
                 and 0 <= tx[1] - t[3] <= 0.5 * page_h
                 for tx in texts)
        checks.append(ok)
    if not checks:
        return 0.5
    return float(sum(checks) / len(checks))


def _c9_format_score(blocks):
    """C9 格式得分(+): span 高度一致性 + 行距规律性 + 行左缘对齐一致性。"""
    span_heights = []
    line_gap_scores = []
    align_scores = []
    for b in blocks:
        if b['type'] not in TEXT_TYPES:
            continue
        lines = b.get('lines', [])
        for ln in lines:
            for sp in ln.get('spans', []):
                sb = sp['bbox']
                if sb[3] > sb[1]:
                    span_heights.append(sb[3] - sb[1])
        if len(lines) >= 3:
            tops = [ln['bbox'][1] for ln in lines]
            bots = [ln['bbox'][3] for ln in lines]
            gaps = [tops[i + 1] - bots[i] for i in range(len(lines) - 1)]
            gaps = [g for g in gaps if g >= 0]
            if len(gaps) >= 2:
                line_gap_scores.append(_one_minus_cv(gaps))
        if lines:
            lxs = [ln['bbox'][0] for ln in lines]
            align_scores.append(_one_minus_cv(lxs))
    parts = []
    if span_heights:
        parts.append(_one_minus_cv(span_heights))
    if line_gap_scores:
        parts.append(float(np.mean(line_gap_scores)))
    if align_scores:
        parts.append(float(np.mean(align_scores)))
    return float(np.mean(parts)) if parts else 0.5


def _c10_context_score(blocks, page_w, page_h):
    """C10 上下文得分(+): 阅读顺序 (index) 与空间顺序的一致率。
    相邻 (按 index) 块对, 后一块应不显著上移, 或切换到右侧栏。"""
    ordered = [b for b in blocks if 'index' in b]
    if len(ordered) < 3:
        return 0.5
    ordered = sorted(ordered, key=lambda b: b['index'])
    ok = 0
    for a, b in zip(ordered, ordered[1:]):
        ab, bb = a['bbox'], b['bbox']
        if bb[1] >= ab[1] - 0.05 * page_h or bb[0] >= ab[2] - 0.05 * page_w:
            ok += 1
    return ok / (len(ordered) - 1)


# ============================================================
# B4 全局分区与语义一致
# ============================================================
def _c11_partition_score(blocks):
    """C11 统一页面分区评分(+): 正文类块面积落入估计正文区 (y 方向 5%~95% 分位带) 的比例。"""
    body = [b for b in blocks if b['type'] in BODY_TYPES]
    if not body:
        return 0.5
    ys = []
    for b in body:
        ys.extend([b['bbox'][1], b['bbox'][3]])
    lo, hi = np.percentile(ys, [5, 95])
    inside, total = 0.0, 0.0
    for b in body:
        x1, y1, x2, y2 = b['bbox']
        area = max(0.0, (x2 - x1) * (y2 - y1))
        total += area
        inside += max(0.0, min(y2, hi) - max(y1, lo)) * max(0.0, x2 - x1)
    return inside / total if total > 0 else 0.5


def _c12_semantic_purity(blocks):
    """C12 块级语义纯度(+): 块类型-内容一致性 (结合 OCR 置信度)。
    文本类块: 非空 span 占比 x 平均 OCR score; 表格块: 是否含 table_body 子块;
    图像块: 1.0; 公式块: 是否含 span 内容。"""
    scores = []
    for b in blocks:
        t = b['type']
        spans = [sp for ln in b.get('lines', []) for sp in ln.get('spans', [])]
        if t in TEXT_TYPES:
            if not spans:
                scores.append(0.2)
                continue
            non_empty = [sp for sp in spans if str(sp.get('content', '')).strip()]
            if not non_empty:
                scores.append(0.2)
                continue
            frac = len(non_empty) / len(spans)
            mean_score = float(np.mean([sp.get('score', 1.0) for sp in non_empty]))
            scores.append(frac * mean_score)
        elif t == 'table':
            has_body = any(s.get('type') == 'table_body' for s in b.get('blocks', []))
            scores.append(1.0 if has_body else 0.5)
        elif t == 'image':
            scores.append(1.0)
        elif t == 'interline_equation':
            scores.append(1.0 if spans else 0.5)
        else:
            scores.append(0.8)
    return float(np.mean(scores)) if scores else 0.0

# ============================================================
# 主入口
# ============================================================
def extract_page_metrics(model_page, middle_page):
    """从单页 model.json + middle.json 数据提取 12 指标与辅助字段。
    model_page  : model.json 中该页的 block 列表 (归一化 bbox)
    middle_page : middle.json pdf_info 中该页的 dict
    返回 dict: metrics(长度 12, 顺序与 INDICATORS 一致), coverage,
               text_blocks, center, page_width"""
    page_w, page_h = float(middle_page['page_size'][0]), float(middle_page['page_size'][1])
    blocks = middle_page.get('para_blocks', [])
    model_abs = [
        (tuple(float(v) * s for v, s in zip(b['bbox'], (page_w, page_h, page_w, page_h))), b['type'])
        for b in (model_page or [])
    ]

    if not blocks:
        return {'metrics': [0.0] * N_IND, 'coverage': 0.0, 'text_blocks': 0,
                'center': None, 'page_width': page_w}

    c1 = _c1_overlap_ratio(blocks, model_abs)
    c2 = _c2_alignment_error(blocks, page_w, page_h)
    c3 = _c3_edge_coverage(blocks, page_w, page_h)
    c4, c5, c6 = _c456_boundary_metrics(blocks, model_abs, page_w, page_h)
    c7 = _c7_spatial_score(blocks, page_w, page_h)
    c8 = _c8_anchor_score(model_abs, page_h)
    c9 = _c9_format_score(blocks)
    c10 = _c10_context_score(blocks, page_w, page_h)
    c11 = _c11_partition_score(blocks)
    c12 = _c12_semantic_purity(blocks)
    metrics = [c1, c2, c3, c4, c5, c6, c7, c8, c9, c10, c11, c12]

    coverage = sum(_box_area(b['bbox']) for b in blocks) / (page_w * page_h)
    text_blocks = sum(1 for b in blocks if b['type'] in TEXT_TYPES)
    center = page_gravity(blocks)
    return {'metrics': metrics, 'coverage': float(np.clip(coverage, 0.0, 1.0)),
            'text_blocks': text_blocks, 'center': center, 'page_width': page_w}


def _find_file(directory, suffix):
    """在目录顶层查找以 suffix 结尾的文件 (兼容 MIME 编码文件名前缀)。"""
    for name in sorted(os.listdir(directory)):
        if name.endswith(suffix) and os.path.isfile(os.path.join(directory, name)):
            return os.path.join(directory, name)
    return None


def load_book_from_hybrid_dir(hybrid_dir, book_name=None):
    """从 MinerU 输出目录加载单本书的逐页数据 (自动识别 3.x / 4.0 格式)。
    返回 BookAggregator (未去噪, 由 pipeline 统一处理)。
    书名默认取输出目录的父目录名 (即解析任务名)。

    3.x 目录含 ``*_model.json`` + ``*_middle.json`` (pdf_info/para_blocks, 绝对 bbox);
    4.0 目录含 ``model_output.json`` + ``middle_json.json`` (归一化 bbox, 页尺寸在
    docvortex_layout 扩展)。两者都缺失时抛 FileNotFoundError。"""
    if _is_40_dir(hybrid_dir):
        return load_book_from_40_dir(hybrid_dir, book_name=book_name)
    model_path = _find_file(hybrid_dir, '_model.json')
    middle_path = _find_file(hybrid_dir, '_middle.json')
    if model_path is None or middle_path is None:
        raise FileNotFoundError(
            f'{hybrid_dir} 下未找到 *_model.json / *_middle.json 或 '
            f'model_output.json / middle_json.json, 不是有效的 MinerU 输出目录')
    with open(model_path, encoding='utf-8') as f:
        model = json.load(f)
    with open(middle_path, encoding='utf-8') as f:
        middle = json.load(f)
    pages = middle['pdf_info']
    if book_name is None:
        book_name = os.path.basename(os.path.dirname(os.path.abspath(hybrid_dir)))

    agg = BookAggregator(book_name)
    for i, mp in enumerate(pages):
        mpage = model[i] if i < len(model) else []
        r = extract_page_metrics(mpage, mp)
        agg.add_page(int(mp.get('page_idx', i)) + 1, r['metrics'],
                     coverage=r['coverage'], text_blocks=r['text_blocks'],
                     center=r['center'], page_width=r['page_width'])
    return agg


# ============================================================
# 4.0 格式适配 (ModelJson + MiddleJson, 归一化 bbox)
# ============================================================
def _is_40_dir(directory):
    """判断目录是否为 4.0 输出 (含 model_output.json 与 middle_json.json)。"""
    return (
        os.path.isfile(os.path.join(directory, 'model_output.json'))
        and os.path.isfile(os.path.join(directory, 'middle_json.json'))
    )


def _span_text(span):
    """从 4.0 InlineSpan (dict) 提取纯文本 (兼容嵌套 hyperlink 子节点)。"""
    if not isinstance(span, dict):
        return ''
    content = span.get('content', '')
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return ''.join(_span_text(c) for c in content)
    return ''


def _page_size_from_layout(model_dict, page_idx, fallback=_DEFAULT_PAGE_SIZE):
    """从 4.0 ModelJson 的 docvortex_layout 扩展读取页尺寸 (pt), 缺失时兜底。"""
    layout = (model_dict.get('extensions') or {}).get('docvortex_layout') or {}
    for p in layout.get('pages') or []:
        if p.get('page_idx') == page_idx:
            w, h = p.get('width_pt'), p.get('height_pt')
            if w and h and w > 0 and h > 0:
                return (float(w), float(h))
    return fallback


def _match_model_lines(middle_block, model_page, page_w, page_h):
    """从 model_page 中找到与 middle_block 最佳匹配的 model block 的行级 bbox。

    匹配条件: 类型兼容 (MODEL_TO_MIDDLE_TYPES) + IoU 最大 (阈值 0.3)。
    返回行级 bbox 列表 (绝对坐标, 每行 [x1,y1,x2,y2]) 或 None。
    """
    btype = _40_TO_LEGACY_TYPE.get(middle_block.get('type'))
    if btype not in TEXT_TYPES:
        return None
    mbbox = middle_block.get('bbox')
    if mbbox is None:
        return None
    # 找到与该 middle 类型兼容的 model 类型集合
    compatible_types = set()
    for mid_type, model_types in MODEL_TO_MIDDLE_TYPES.items():
        if mid_type == btype:
            compatible_types = model_types
            break
    if not compatible_types:
        return None
    best_iou = 0.0
    best_lines = None
    for mb in model_page:
        mtype = mb.get('type')
        if mtype not in compatible_types:
            continue
        mbbox_m = mb.get('bbox')
        if mbbox_m is None:
            continue
        iou = _iou(mbbox, mbbox_m)
        if iou > best_iou:
            best_iou = iou
            lines = mb.get('lines')
            if lines:
                best_lines = lines
    if best_iou >= 0.3 and best_lines:
        # 将归一化 bbox (0-1) 转换为绝对坐标 (pt)
        abs_lines = []
        for lb in best_lines:
            lbbox = lb.get('bbox') if isinstance(lb, dict) else lb
            if isinstance(lbbox, (list, tuple)) and len(lbbox) == 4:
                abs_lines.append([
                    lbbox[0] * page_w, lbbox[1] * page_h,
                    lbbox[2] * page_w, lbbox[3] * page_h,
                ])
        return abs_lines if abs_lines else None
    return None


def _build_lines_from_line_bboxes(line_bboxes, spans, abs_bbox):
    """从行级 bbox 列表创建 line/span 结构 (供 C9 行结构指标)。

    每行一个 span, span bbox 与行 bbox 相同 (C9 只使用 bbox 几何, 不使用 content)。
    若 line_bboxes 为空则回退到块级单行合成。
    """
    if not line_bboxes:
        return [{'bbox': abs_bbox, 'spans': spans}] if spans else []
    lines = []
    for lbbox in line_bboxes:
        line_spans = [{'bbox': lbbox, 'type': 'text', 'content': '', 'score': 1.0}]
        lines.append({'bbox': lbbox, 'spans': line_spans})
    return lines



def _middle_block_to_legacy(block, page_w, page_h, line_bboxes=None):
    """把 4.0 middle block (dict, 归一化 bbox) 转成 3.x para_block (绝对 bbox)。

    文本类块: content (InlineSpan 列表) 展平为 spans (score=1.0, 无 OCR 置信度);
    表格块: 补 table_body 子块; 其余块: lines=[]。
    line_bboxes: 可选的行级 bbox 列表 (绝对坐标), 用于 C9 行结构指标;
                 提供时按行拆分 lines/spans, 否则回退到块级单行合成。"""
    if not isinstance(block, dict):
        return None
    btype = _40_TO_LEGACY_TYPE.get(block.get('type'))
    bbox = block.get('bbox')
    if btype is None or bbox is None:
        return None
    abs_bbox = [bbox[0] * page_w, bbox[1] * page_h, bbox[2] * page_w, bbox[3] * page_h]
    legacy = {
        'bbox': abs_bbox,
        'type': btype,
        'angle': 0,
        'index': block.get('index', 0) or 0,
    }
    if btype in TEXT_TYPES:
        spans = []
        for sp in block.get('content', []) or []:
            text = _span_text(sp)
            if not text:
                continue
            spans.append({'bbox': abs_bbox, 'type': 'text', 'content': text, 'score': 1.0})
        if line_bboxes:
            legacy['lines'] = _build_lines_from_line_bboxes(line_bboxes, spans, abs_bbox)
        else:
            legacy['lines'] = [{'bbox': abs_bbox, 'spans': spans}] if spans else []
    else:
        legacy['lines'] = []
    if btype == 'table':
        legacy['blocks'] = [{'type': 'table_body', 'bbox': abs_bbox}]
    return legacy


def _build_agg_from_40(model_dict, middle_dict, book_name):
    """从 4.0 ModelJson + MiddleJson (dict) 构建 BookAggregator。"""
    agg = BookAggregator(book_name)
    model_pages = model_dict.get('pages') or []
    for i, mpage in enumerate(middle_dict.get('pages') or []):
        page_idx = mpage.get('page_idx', i)
        page_w, page_h = _page_size_from_layout(model_dict, page_idx)
        model_page = model_pages[i] if i < len(model_pages) else []
        para_blocks = []
        for b in mpage.get('blocks') or []:
            line_bboxes = _match_model_lines(b, model_page, page_w, page_h)
            legacy = _middle_block_to_legacy(b, page_w, page_h, line_bboxes=line_bboxes)
            if legacy is not None:
                para_blocks.append(legacy)
        middle_page = {
            'page_size': [page_w, page_h],
            'page_idx': page_idx,
            'preproc_blocks': [],
            'discarded_blocks': [],
            'para_blocks': para_blocks,
        }
        r = extract_page_metrics(model_page, middle_page)
        agg.add_page(
            page_idx + 1, r['metrics'],
            coverage=r['coverage'], text_blocks=r['text_blocks'],
            center=r['center'], page_width=r['page_width'],
        )
    return agg


def load_book_from_40_dir(hybrid_dir, book_name=None):
    """从 4.0 MinerU 输出目录 (model_output.json + middle_json.json) 加载单本书。

    Raises:
        FileNotFoundError: model_output/middle_json 缺失。
    """
    model_path = os.path.join(hybrid_dir, 'model_output.json')
    middle_path = os.path.join(hybrid_dir, 'middle_json.json')
    if not (os.path.isfile(model_path) and os.path.isfile(middle_path)):
        raise FileNotFoundError(
            f'{hybrid_dir} 下未找到 model_output.json / middle_json.json, '
            f'不是有效的 4.0 输出目录')
    with open(model_path, encoding='utf-8') as f:
        model = json.load(f)
    with open(middle_path, encoding='utf-8') as f:
        middle = json.load(f)
    if book_name is None:
        book_name = os.path.basename(os.path.dirname(os.path.abspath(hybrid_dir)))
    return _build_agg_from_40(model, middle, book_name)


def load_book_from_parse_result(result, book_name=None):
    """从内存中的 4.0 ParseResult 构建 BookAggregator (供 V1 API 评分使用)。

    直接读取 middle_json 与 model_output, 无需落盘。缺少 model_output 时
    匹配类指标 (C1/C4/C5/C6/C8) 退化为无原始检测框, 其余指标仍可计算。"""
    middle_dict = result.to_dict(skip_defaults=True)
    model_output = getattr(result, '_model_output', None)
    model_dict = (
        model_output.to_dict(skip_defaults=False) if model_output is not None
        else {'pages': []}
    )
    if book_name is None:
        book_name = 'parse_result'
    return _build_agg_from_40(model_dict, middle_dict, book_name)

