# -*- coding: utf-8 -*-
"""指标体系定义 (4 个准则层, 12 个指标)。"""
import numpy as np

CRITERIA = [
    'B1空间拓扑与相对关系',
    'B2像素级与边界精度',
    'B3多模态复合评分',
    'B4全局分区与语义一致',
]

# (指标名, 所属准则, 方向: 1=正向越大越好, -1=负向越小越好)
INDICATORS = [
    ('C1重叠面积比',              CRITERIA[0],  1),
    ('C2曼哈顿角点对齐误差',       CRITERIA[0], -1),
    ('C3最小权重边覆盖匹配相似度', CRITERIA[0],  1),
    ('C4平均交并比mIoU',          CRITERIA[1],  1),
    ('C5边界精度',                CRITERIA[1],  1),
    ('C6像素准确率',              CRITERIA[1],  1),
    ('C7空间得分Spatial',         CRITERIA[2],  1),
    ('C8锚点得分Anchor',          CRITERIA[2],  1),
    ('C9格式得分Format',          CRITERIA[2],  1),
    ('C10上下文得分Context',      CRITERIA[2],  1),
    ('C11统一页面分区评分',       CRITERIA[3],  1),
    ('C12块级语义纯度',           CRITERIA[3],  1),
]
IND_NAMES  = [x[0] for x in INDICATORS]
DIRECTIONS = np.array([x[2] for x in INDICATORS], dtype=float)
N_IND      = len(INDICATORS)
