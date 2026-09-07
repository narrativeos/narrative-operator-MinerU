# -*- coding: utf-8 -*-
"""演示数据: 书级基线 + 逐页模拟, 以及内置自检。"""
import re

import numpy as np

from .indicators import N_IND
from .aggregator import BookAggregator, PAGE_W_A4, PAGE_H_A4
from .pipeline import run_book_level_pipeline

# 内置书级基线 (模拟由 MinerU 输出计算的 12 项指标均值, 作为逐页模拟的种子)
DEMO_DATA = {
    '学术期刊A':   [0.86, 4.2, 0.88, 0.91, 0.93, 0.96, 0.90, 0.87, 0.92, 0.89, 0.93, 0.95],
    '高校教材B':   [0.88, 3.5, 0.90, 0.93, 0.94, 0.97, 0.92, 0.90, 0.93, 0.91, 0.94, 0.96],
    '文学小说C':   [0.72, 6.8, 0.75, 0.85, 0.88, 0.93, 0.80, 0.76, 0.85, 0.78, 0.82, 0.88],
    '图文画册D':   [0.78, 5.5, 0.80, 0.87, 0.86, 0.91, 0.82, 0.80, 0.83, 0.81, 0.85, 0.84],
    '辞典工具书E': [0.90, 3.0, 0.91, 0.94, 0.95, 0.98, 0.93, 0.91, 0.95, 0.92, 0.95, 0.97],
    '时尚杂志F':   [0.65, 8.2, 0.68, 0.79, 0.82, 0.88, 0.72, 0.68, 0.76, 0.70, 0.74, 0.80],
    '儿童绘本G':   [0.60, 9.5, 0.62, 0.75, 0.78, 0.85, 0.68, 0.63, 0.72, 0.66, 0.70, 0.76],
    '工程图纸H':   [0.83, 4.8, 0.85, 0.89, 0.92, 0.95, 0.88, 0.85, 0.90, 0.93, 0.90, 0.92],
}
# 列顺序: C1重叠面积比 | C2角点误差(px) | C3边覆盖相似度 | C4mIoU | C5边界精度 | C6像素准确率
#         | C7空间得分 | C8锚点得分 | C9格式得分 | C10上下文得分 | C11分区评分 | C12语义纯度

# 逐页模拟风格参数: jitter=逐页指标波动幅度(占基线比例), grav=重心抖动(pt), anomalies=注入的排版失控页
STYLE_PARAMS = {
    '学术期刊A':   {'jitter': 0.012, 'grav': 3.0,  'anomalies': (27, 28, 29)},
    '高校教材B':   {'jitter': 0.015, 'grav': 4.0,  'anomalies': ()},
    '文学小说C':   {'jitter': 0.030, 'grav': 6.0,  'anomalies': ()},
    '图文画册D':   {'jitter': 0.050, 'grav': 12.0, 'anomalies': ()},
    '辞典工具书E': {'jitter': 0.010, 'grav': 2.0,  'anomalies': ()},
    '时尚杂志F':   {'jitter': 0.080, 'grav': 25.0, 'anomalies': ()},
    '儿童绘本G':   {'jitter': 0.070, 'grav': 20.0, 'anomalies': ()},
    '工程图纸H':   {'jitter': 0.020, 'grav': 5.0,  'anomalies': ()},
}


def simulate_demo_books(n_pages=40):
    """基于 DEMO_DATA 书级基线, 为每本书模拟 n_pages 页的逐页指标数据。
    每本书包含: 1 个空白页(第3页) + 1 个版权页(第4页) 作为噪声页,
    指定书目额外注入排版失控的异常页, 用于验证 3σ 异常检测。"""
    books = {}
    for seed, (name, base) in enumerate(DEMO_DATA.items()):
        cfg = STYLE_PARAMS[name]
        rng = np.random.default_rng(2026 + seed)
        agg = BookAggregator(name)
        base = np.asarray(base, dtype=float)
        for pg in range(1, n_pages + 1):
            cx = PAGE_W_A4 / 2 + rng.normal(0, cfg['grav'])
            cy = PAGE_H_A4 / 2 + rng.normal(0, cfg['grav'])
            if pg == 3:   # 空白页 (噪声, 应被剔除)
                agg.add_page(pg, np.zeros(N_IND), coverage=0.03, text_blocks=0,
                             center=(cx, cy), page_width=PAGE_W_A4)
                continue
            if pg == 4:   # 版权页 (噪声, 应被剔除)
                agg.add_page(pg, base * 0.6, coverage=0.07, text_blocks=2,
                             center=(cx, cy), page_width=PAGE_W_A4)
                continue
            m = base + rng.normal(0.0, cfg['jitter'] * np.abs(base) + 1e-4)
            if pg in cfg['anomalies']:   # 注入排版失控: 角点误差激增 + 语义纯度骤降
                m[1] = m[1] * 3.0 + 4.0
                m[11] = max(0.30, m[11] - 0.30)
            m = np.where(np.arange(N_IND) == 1, np.maximum(m, 0.3), np.clip(m, 0.0, 1.0))
            agg.add_page(pg, m,
                         coverage=float(rng.uniform(0.50, 0.85)),
                         text_blocks=int(rng.integers(8, 30)),
                         center=(cx, cy), page_width=PAGE_W_A4)
        books[name] = agg
    return books


def run_demo(n_pages=40, alpha=0.5, n_sigma=3.0, out_dir='.'):
    """运行内置模拟演示, 并执行基础自检。
    返回 (综合评分 DataFrame, 组合权重, 质检报告全文)。"""
    books = simulate_demo_books(n_pages=n_pages)
    result, w_final, qa_text = run_book_level_pipeline(books, alpha=alpha,
                                                       n_sigma=n_sigma, out_dir=out_dir)

    # ---- 基础自检 ----
    assert abs(float(w_final.sum()) - 1.0) < 1e-6, '组合权重之和不为1'
    assert result['综合贴近度'].between(0, 1).all(), '贴近度超出[0,1]'
    assert result['综合评分'].between(0, 1).all(), '综合评分超出[0,1]'
    assert result.loc[result['综合评分'].idxmax(), '样本'] == '辞典工具书E', '绝对分最高的书不是辞典工具书E'
    assert sorted(result['名次'].tolist()) == list(range(1, len(result) + 1)), '名次序号异常'
    assert re.search(r'第\s*27\s*页', qa_text), '注入的异常页(学术期刊A 第27-29页)未被检出'
    assert '剔除噪声页: 2 页' in qa_text, '空白页/版权页未被正确剔除'
    print()
    print('自检通过: 组合权重和为1, 贴近度/综合评分均在[0,1]区间, 名次无异常;')
    print('          绝对分最高的书为辞典工具书E (基线最优);')
    print('          噪声页(空白页/版权页)被正确剔除, 注入的排版失控页被 3σ 准则成功检出。')
    return result, w_final, qa_text
