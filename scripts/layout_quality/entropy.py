# -*- coding: utf-8 -*-
"""熵权法客观赋权。"""
import numpy as np

from .indicators import DIRECTIONS


def _direction_unify(X):
    """负向指标取反, 统一为"越大越优" """
    X = np.asarray(X, dtype=float).copy()
    neg = DIRECTIONS < 0
    X[:, neg] = -X[:, neg]
    return X


def entropy_weight(X):
    """熵权法: 返回 (客观权重, 各指标信息熵)"""
    Z = _direction_unify(X)
    zmin, zmax = Z.min(axis=0), Z.max(axis=0)
    rng = np.where(zmax - zmin == 0, 1.0, zmax - zmin)
    Y = (Z - zmin) / rng + 1e-3             # min-max 标准化 + 平移避免 ln(0)
    P = Y / Y.sum(axis=0, keepdims=True)    # 比重
    k = 1.0 / np.log(Z.shape[0])
    E = -k * np.sum(P * np.log(P), axis=0)  # 信息熵
    D = 1.0 - E                             # 差异系数(冗余度)
    if D.sum() <= 1e-12:
        # 样本间无差异 (如完全相同的两本书): 差异系数全 0, 退化为等权
        return np.full(X.shape[1], 1.0 / X.shape[1]), E
    W = D / D.sum()
    return W, E
