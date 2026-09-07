# -*- coding: utf-8 -*-
"""TOPSIS 逼近理想解综合排序。"""
import numpy as np

from .entropy import _direction_unify


def topsis(X, weights):
    """TOPSIS 法: 返回 (D+, D-, 贴近度C, 名次)"""
    V = _direction_unify(X)
    V = V / np.sqrt((V ** 2).sum(axis=0, keepdims=True))   # 向量归一化
    V = V * weights                                        # 加权
    V_pos, V_neg = V.max(axis=0), V.min(axis=0)            # 正/负理想解
    D_pos = np.sqrt(((V - V_pos) ** 2).sum(axis=1))
    D_neg = np.sqrt(((V - V_neg) ** 2).sum(axis=1))
    C = D_neg / (D_pos + D_neg + 1e-12)                    # 相对贴近度
    rank = C.argsort()[::-1].argsort() + 1
    return D_pos, D_neg, C, rank


def grade_of(c):
    """按贴近度划分档位(阈值可按业务需要调整)"""
    if c >= 0.75:
        return 'T1(国际一流)'
    if c >= 0.50:
        return 'T2(优秀)'
    if c >= 0.25:
        return 'T3(合格)'
    return 'T4(待优化)'
