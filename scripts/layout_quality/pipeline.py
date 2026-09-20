# -*- coding: utf-8 -*-
"""主流程: 组合赋权与 TOPSIS 评估 (输入为书级矩阵)。"""
import os

import numpy as np
import pandas as pd

from .indicators import IND_NAMES, N_IND
from .ahp import ahp_subjective_weights
from .entropy import entropy_weight
from .topsis import topsis, grade_of
from .scoring import book_quality_score, score_row
from .service import analyze_book


def run_evaluation(X, sample_names, alpha=0.5):
    """
    X          : 决策矩阵 (n_samples x 12), 列顺序与 INDICATORS 严格一致
                 (在逐页->全书架构中, 此处传入每本书的"全书版面指纹"均值向量)
    sample_names: 样本名称列表
    alpha      : 主观(AHP)权重在组合权重中的占比, 0~1, 默认 0.5 主客观各半
    """
    X = np.asarray(X, dtype=float)
    assert X.shape[1] == N_IND, f'决策矩阵应为 {N_IND} 列, 实际 {X.shape[1]} 列'

    print('=' * 72)
    print('Step 1  AHP 主观赋权')
    print('=' * 72)
    w_sub = ahp_subjective_weights()
    print()

    print('=' * 72)
    print('Step 2  熵权法客观赋权')
    print('=' * 72)
    w_obj, E = entropy_weight(X)
    for name, e, w in zip(IND_NAMES, E, w_obj):
        print(f'    {name:<20s} 信息熵E={e:.4f}   客观权重={w:.4f}')
    print()

    print('=' * 72)
    print(f'Step 3  主客观组合赋权 (alpha={alpha}, 即主观{alpha:.0%} / 客观{1-alpha:.0%})')
    print('=' * 72)
    w_final = alpha * w_sub + (1 - alpha) * w_obj
    w_final = w_final / w_final.sum()
    for name, ws, wo, wf in zip(IND_NAMES, w_sub, w_obj, w_final):
        print(f'    {name:<20s} 主观={ws:.4f}  客观={wo:.4f}  组合={wf:.4f}')
    print()

    print('=' * 72)
    print('Step 4  TOPSIS 综合排序')
    print('=' * 72)
    D_pos, D_neg, C, rank = topsis(X, w_final)
    result = pd.DataFrame({
        '样本': sample_names,
        'D+距离': np.round(D_pos, 4),
        'D-距离': np.round(D_neg, 4),
        '综合贴近度': np.round(C, 4),
        '名次': rank,
        '档位': [grade_of(c) for c in C],
    }).sort_values('名次').reset_index(drop=True)
    print(result.to_string(index=False))
    return result, w_final


# ============================================================
# 单本书质检: 去噪 / 聚合 / 跨页对称 / 异常页检测
# ============================================================
def run_book_qa(agg, csv_path=None, n_sigma=3.0, coverage_min=0.10, min_text_blocks=3,
                w_sub=None):
    """单本书质检 (Step 0): 去噪 / 聚合 / 跨页对称 / 异常页检测 / 全书综合评分。
    agg      : 未去噪的 BookAggregator
    csv_path : 若指定, 将逐页指标明细写入该路径 (即 <hybrid_auto>/layout_quality.csv),
               并在同目录写入全书综合评分 layout_quality_score.csv
    w_sub    : 12 维 AHP 主观权重; 未指定时内部计算 (批量调用时传入避免重复计算)
    质检报告与全书综合评分打印到 stdout。
    返回 (逐页明细 DataFrame, 质检报告全文)"""
    if w_sub is None:
        w_sub = ahp_subjective_weights(verbose=False)
    # 核心计算收敛在 service.analyze_book (与 FastAPI 端点共用, 无副作用)
    result = analyze_book(agg, n_sigma=n_sigma, coverage_min=coverage_min,
                          min_text_blocks=min_text_blocks, w_sub=w_sub)
    detail = pd.DataFrame(result['pages'])
    qa = result['qa_report']
    score = result['score']
    print(qa)

    # 全书版面质量综合评分 (绝对分: 12 指标归一化子分的 AHP 加权平均)
    sym = agg.spread_symmetry
    ss = f'{sym:.4f}' if sym is not None else '未计算(缺重心数据)'
    print('=' * 72)
    print('全书版面质量综合评分 (绝对分, 单本书独立计算)')
    print('=' * 72)
    print(f"  综合评分: {score['value']:.4f} (百分制: {score['percent']:.2f})  档位: {score['grade']}")
    print(f"  排版稳定性指数: {score['stability_index']:.4f} | 跨页对称度: {ss} | "
          f"异常页数: {score['outlier_count']}")
    if csv_path:
        parent = os.path.dirname(os.path.abspath(csv_path))
        os.makedirs(parent, exist_ok=True)
        detail.to_csv(csv_path, index=False, encoding='utf-8-sig')
        print(f'逐页指标明细已保存: {csv_path}')
        score_csv = os.path.join(parent, 'layout_quality_score.csv')
        pd.DataFrame([score_row(agg, w_sub)]).to_csv(score_csv, index=False,
                                                     encoding='utf-8-sig')
        print(f'全书综合评分已保存: {score_csv}')
    return detail, qa


# ============================================================
# 全书层流水线: 逐书质检 + TOPSIS 综合评分
# ============================================================
def run_book_level_pipeline(books, page_csv_paths=None, alpha=0.5, n_sigma=3.0,
                            coverage_min=0.10, min_text_blocks=3, out_dir='.'):
    """逐页 -> 全书双层评估主流水线。
    books         : {书名: BookAggregator} (未去噪)
    page_csv_paths: 可选 {书名: 逐页明细 CSV 路径}; 指定时每本书的逐页明细写入各自路径
                    (目录模式: <hybrid_auto>/layout_quality.csv);
                    未指定时合并逐页明细写入 out_dir (CSV 输入模式)
    输出          : 版面量化综合评分结果 CSV (+ 逐页版面指标明细 CSV)
    返回          : (综合评分 DataFrame, 组合权重, 质检报告全文)"""
    if len(books) < 2:
        raise ValueError('TOPSIS 排序至少需要 2 本书')

    print('=' * 72)
    print('Step 0  逐页 -> 全书聚合 (去噪 / 聚合 / 跨页对称 / 异常页检测)')
    print('=' * 72)

    w_sub = ahp_subjective_weights(verbose=False)
    details, qa_texts, extra = {}, [], []
    for name, agg in books.items():
        detail, qa = run_book_qa(agg, csv_path=(page_csv_paths or {}).get(name),
                                 n_sigma=n_sigma, coverage_min=coverage_min,
                                 min_text_blocks=min_text_blocks, w_sub=w_sub)
        details[name] = detail
        qa_texts.append(qa)
        total = len(agg.pages) + len(agg.dropped_pages)
        sym = agg.spread_symmetry
        score, _ = book_quality_score(agg, w_sub)
        extra.append({
            '样本': name,
            '总页数': total,
            '有效页数': len(agg.pages),
            '剔除噪声页': len(agg.dropped_pages),
            '综合评分': round(score, 4),
            '档位(绝对)': grade_of(score),
            '排版稳定性指数': round(agg.stability_index, 4),
            '跨页对称度': (None if sym is None else round(sym, 4)),
            '异常页数': len(agg.outliers),
        })
    print()

    X = np.vstack([agg.fingerprint for agg in books.values()])
    result, w_final = run_evaluation(X, list(books.keys()), alpha=alpha)
    result = result.merge(pd.DataFrame(extra), on='样本', how='left')
    cols = ['样本', '综合评分', '档位(绝对)', '综合贴近度', '名次', '档位',
            '排版稳定性指数', '跨页对称度', '总页数', '有效页数', '剔除噪声页',
            '异常页数', 'D+距离', 'D-距离']
    result = result[cols]

    os.makedirs(out_dir, exist_ok=True)
    score_csv = os.path.join(out_dir, '版面量化综合评分结果.csv')
    result.to_csv(score_csv, index=False, encoding='utf-8-sig')
    print(f'综合评分结果已保存: {score_csv}')

    if not page_csv_paths:
        # CSV 输入模式: 合并逐页明细 (含书名列) 写入 out_dir
        detail_cols = ['书名', '页码', 'page_idx', '是否有效', '版面覆盖率', '文本块数'] + IND_NAMES
        combined = pd.concat(
            [d.assign(书名=n) for n, d in details.items()], ignore_index=True)
        combined = combined[detail_cols]
        detail_csv = os.path.join(out_dir, '逐页版面指标明细.csv')
        combined.to_csv(detail_csv, index=False, encoding='utf-8-sig')
        print(f'逐页指标明细已保存: {detail_csv}')

    return result, w_final, '\n'.join(qa_texts)


# ============================================================
# 书级数据加载 (兼容旧版: 已有书级聚合数据时直接 TOPSIS)
# ============================================================
def load_metrics_from_csv(csv_path):
    """加载书级 MinerU 指标数据。
    CSV 格式: 第一列为样本名, 其后 12 列为 C1~C12 指标(顺序与 INDICATORS 严格一致)。
    返回: 决策矩阵 X, 样本名列表"""
    df = pd.read_csv(csv_path)
    sample_names = df.iloc[:, 0].astype(str).tolist()
    X = df.iloc[:, 1:1 + N_IND].astype(float).values
    if X.shape[1] != N_IND:
        raise ValueError(f'CSV 应含样本名后 {N_IND} 列指标, 实际读到 {X.shape[1]} 列')
    return X, sample_names

