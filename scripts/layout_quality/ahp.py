# -*- coding: utf-8 -*-
"""AHP 主观赋权 (特征向量法 + 一致性检验)。"""
import numpy as np

from .indicators import CRITERIA, INDICATORS, IND_NAMES, N_IND

# Saaty 随机一致性指标 RI 表
RI_TABLE = {1: 0.0, 2: 0.0, 3: 0.58, 4: 0.90, 5: 1.12,
            6: 1.24, 7: 1.32, 8: 1.41, 9: 1.45, 10: 1.49}


def ahp_weight(matrix, name='判断矩阵'):
    """AHP 特征向量法, 返回归一化权重, 自动做一致性检验"""
    A = np.asarray(matrix, dtype=float)
    n = A.shape[0]
    eig_vals, eig_vecs = np.linalg.eig(A)
    idx = int(np.argmax(eig_vals.real))
    lambda_max = float(eig_vals[idx].real)
    w = np.abs(eig_vecs[:, idx].real)
    w = w / w.sum()
    CI = (lambda_max - n) / (n - 1) if n > 2 else 0.0
    RI = RI_TABLE.get(n, 1.49)
    CR = CI / RI if RI > 0 else 0.0
    print(f'  [{name}] lambda_max={lambda_max:.4f}  CI={CI:.4f}  CR={CR:.4f}', end='')
    if CR < 0.1:
        print('  -> 一致性检验通过')
    else:
        print('  -> 一致性检验未通过')
        raise ValueError(f'{name} 一致性检验未通过 (CR={CR:.4f}>=0.1), 请重新调整专家打分')
    return w


# ---- 专家判断矩阵 (Saaty 1-9 标度, 可替换为你自己的专家打分) ----
# 准则层: 重要性排序 B4全局语义一致 > B2像素精度 > B3多模态复合 > B1空间拓扑
B_MATRIX = [
    [1,   1/3, 1/2, 1/4],
    [3,   1,   2,   1/2],
    [2,   1/2, 1,   1/3],
    [4,   2,   3,   1  ],
]

# 指标层: 各准则组内两两比较
C_MATRICES = {
    CRITERIA[0]: [                # B1 组: C1, C2, C3
        [1,   2,   1/3],
        [1/2, 1,   1/4],
        [3,   4,   1  ],
    ],
    CRITERIA[1]: [                # B2 组: C4, C5, C6
        [1,   2,   3],
        [1/2, 1,   2],
        [1/3, 1/2, 1],
    ],
    CRITERIA[2]: [                # B3 组: C7, C8, C9, C10
        [1,   2,   2,   1/2],
        [1/2, 1,   1,   1/3],
        [1/2, 1,   1,   1/3],
        [2,   3,   3,   1  ],
    ],
    CRITERIA[3]: [                # B4 组: C11, C12
        [1,   1/2],
        [2,   1  ],
    ],
}


def ahp_subjective_weights(verbose=True):
    """两级 AHP 主观权重: 准则层 B x 指标层 C -> 12 维指标权重 (和为 1)。
    verbose: 是否打印一致性检验与权重明细。"""
    w_B = ahp_weight(B_MATRIX, name='准则层B')
    if verbose:
        print('  准则层主观权重:')
        for cri, w in zip(CRITERIA, w_B):
            print(f'    {cri:<14s} {w:.4f}')
    w_sub = np.zeros(N_IND)
    for b, cri in enumerate(CRITERIA):
        g_idx = [i for i, t in enumerate(INDICATORS) if t[1] == cri]
        w_local = ahp_weight(C_MATRICES[cri], name=f'指标层{cri[:2]}')
        for local, gi in enumerate(g_idx):
            w_sub[gi] = w_B[b] * w_local[local]
    w_sub /= w_sub.sum()
    if verbose:
        print('  指标层主观权重:')
        for name, w in zip(IND_NAMES, w_sub):
            print(f'    {name:<20s} {w:.4f}')
    return w_sub
