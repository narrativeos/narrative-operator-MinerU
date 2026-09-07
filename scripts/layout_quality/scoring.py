# -*- coding: utf-8 -*-
"""全书版面质量综合评分 (绝对分)。

与 TOPSIS 综合贴近度 (相对分, 依赖批内样本集, 需至少 2 本书) 不同,
绝对分对单本书独立计算, 单/多书模式口径一致:

    全书版面指纹 (12 指标均值向量)
      -> 逐指标归一化到 [0,1] 子分 (越大越好)
      -> AHP 主观权重加权平均
      -> grade_of 定档 (T1~T4)

排版稳定性指数 / 跨页对称度 仅作辅助列展示, 不进总分。
"""
import numpy as np

from .indicators import IND_NAMES, N_IND
from .topsis import grade_of

# C2 (曼哈顿角点对齐误差, pt) 归一化尺度: 误差 10pt (约 3.5mm) 记半分
C2_SCALE = 10.0


def normalize_fingerprint(fingerprint):
    """全书版面指纹 (12 指标均值向量) -> [0,1] 子分 (越大越好)。
    正向指标 (C1, C3~C12) 本身在 [0,1], 直接截断;
    负向指标 C2 (误差, pt, 无界) 用 1/(1+x/C2_SCALE) 衰减: 0 误差 -> 1, 误差越大越接近 0。"""
    fp = np.asarray(fingerprint, dtype=float)
    if fp.shape[0] != N_IND:
        raise ValueError(f'版面指纹应为 {N_IND} 维, 实际 {fp.shape[0]} 维')
    s = np.clip(fp, 0.0, 1.0).copy()
    s[1] = 1.0 / (1.0 + max(float(fp[1]), 0.0) / C2_SCALE)
    return s


def book_quality_score(agg, w_sub):
    """全书版面质量综合评分 (绝对分)。
    agg  : 已聚合 (aggregate() 之后) 的 BookAggregator
    w_sub: 12 维 AHP 主观权重 (和为 1)
    返回 (综合评分 [0,1], 12 维归一化子分)"""
    if agg.fingerprint is None:
        raise ValueError(f'《{agg.name}》尚未聚合, 请先调用 aggregate()')
    w = np.asarray(w_sub, dtype=float)
    s = normalize_fingerprint(agg.fingerprint)
    return float((w * s).sum()), s


def score_row(agg, w_sub):
    """全书综合评分 CSV 行 (单行, 列含辅助指标与 12 维子分)。"""
    score, s = book_quality_score(agg, w_sub)
    sym = agg.spread_symmetry
    return {
        '书名': agg.name,
        '有效页数': len(agg.pages),
        '综合评分': round(score, 4),
        '百分制': round(score * 100, 2),
        '档位': grade_of(score),
        '排版稳定性指数': (None if agg.stability_index is None
                       else round(agg.stability_index, 4)),
        '跨页对称度': (None if sym is None else round(sym, 4)),
        '异常页数': len(agg.outliers),
        **{f'{nm}子分': round(float(v), 4) for nm, v in zip(IND_NAMES, s)},
    }
