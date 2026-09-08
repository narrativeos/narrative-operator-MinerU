# -*- coding: utf-8 -*-
"""逐页 -> 全书聚合模块 (Page-level -> Book-level)。"""
import numpy as np
import pandas as pd

from .indicators import IND_NAMES, N_IND
from .entropy import _direction_unify

PAGE_W_A4, PAGE_H_A4 = 595.28, 841.89   # A4 页面尺寸 (pt)


def page_gravity(blocks, default=None):
    """由 MinerU 风格的 blocks 计算单页视觉重心 (按 bbox 面积加权)。
    blocks: list[dict], 每个元素含 'bbox': [x1, y1, x2, y2]
    返回 (cx, cy); blocks 为空时返回 default。"""
    xs, ys, ws = [], [], []
    for b in blocks or []:
        x1, y1, x2, y2 = b['bbox']
        w = max(0.0, (x2 - x1) * (y2 - y1))
        if w <= 0:
            continue
        xs.append((x1 + x2) / 2.0)
        ys.append((y1 + y2) / 2.0)
        ws.append(w)
    if not ws:
        return default
    ws = np.asarray(ws, dtype=float)
    cx = float((np.asarray(xs) * ws).sum() / ws.sum())
    cy = float((np.asarray(ys) * ws).sum() / ws.sum())
    return cx, cy


class BookAggregator:
    """逐页 -> 全书聚合器。
    承载单本书的逐页 12 指标向量与辅助信息, 依次执行:
    噪声页剔除 -> 全书均值/方差聚合(版面指纹) -> 跨页对称性分析 -> 3σ异常页检测 -> 质检报告。"""

    def __init__(self, name):
        self.name = name
        self.pages = []            # 有效页列表 (未过滤前为全部页)
        self.dropped_pages = []    # 被剔除的噪声页
        self.fingerprint = None    # 全书版面指纹: 12 指标均值向量
        self.stability = None      # 12 指标标准差向量
        self.cv = None             # 方向统一后的变异系数向量
        self.stability_index = None
        self.spread_symmetry = None
        self.outliers = pd.DataFrame(columns=['页码', '异常指标', '最大偏离(σ)'])

    def add_page(self, page_no, metrics, coverage=1.0, text_blocks=None,
                 center=None, page_width=None):
        """登记一页数据。
        metrics    : 长度 12 的指标向量 (顺序与 INDICATORS 一致)
        coverage   : 该页版面覆盖率 (用于噪声页剔除)
        text_blocks: 该页文本块数量 (用于噪声页剔除, 可空)
        center     : (cx, cy) 页面视觉重心 (用于跨页对称性分析, 可空)
        page_width : 页宽 (与 center 配套, 可空)"""
        m = np.asarray(metrics, dtype=float)
        if m.shape[0] != N_IND:
            raise ValueError(f'第{page_no}页: 指标数应为 {N_IND}, 实际 {m.shape[0]}')
        self.pages.append({
            'page_no': int(page_no), 'metrics': m, 'coverage': float(coverage),
            'text_blocks': (None if text_blocks is None else int(text_blocks)),
            'center': center,
            'page_width': (None if page_width is None else float(page_width))})
        return self

    # ---- 策略二: 核心页面采样 (剔除空白页/版权页等噪声) ----
    def filter_noise_pages(self, coverage_min=0.10, min_text_blocks=3):
        """剔除噪声页 (空白页/版权页等无版面信息页)。

        保留判据: 版面覆盖率达标 (cov_ok) 或 文本块数达标 (tb_ok), 满足其一即保留。
        - 整页表格/图片: coverage 高但 text_blocks=0, 靠 cov_ok 保留 (不再误判为噪声);
        - 空白页/版权页: coverage 低且文本块不足, 被剔除;
        - text_blocks 为 None (CSV 输入未提供) 时, 仅按 coverage 判断。
        """
        kept, dropped = [], []
        for p in self.pages:
            cov_ok = p['coverage'] >= coverage_min
            tb_ok = (p['text_blocks'] is not None) and (p['text_blocks'] >= min_text_blocks)
            (kept if (cov_ok or tb_ok) else dropped).append(p)
        self.pages, self.dropped_pages = kept, dropped
        return [p['page_no'] for p in dropped]

    def _matrix(self):
        return np.vstack([p['metrics'] for p in self.pages])

    # ---- 策略一: 全书均值/方差聚合 -> 版面指纹 + 排版稳定性 ----
    def aggregate(self):
        if len(self.pages) == 0:
            raise ValueError(f'《{self.name}》去噪后无有效正文页, 无法聚合')
        M = self._matrix()
        self.fingerprint = M.mean(axis=0)          # 绝对风格
        self.stability = M.std(axis=0)             # 排版波动
        U = _direction_unify(M)
        um = U.mean(axis=0)
        self.cv = np.where(np.abs(um) > 1e-9, U.std(axis=0) / np.abs(um), 0.0)
        self.stability_index = float(1.0 / (1.0 + float(self.cv.mean())))  # 越大越稳定
        return self.fingerprint, self.stability

    # ---- 策略三: 跨页 (Spread) 拓扑分析: 左右页视觉重心镜像对称度 ----
    def spread_analysis(self):
        ordered = sorted(self.pages, key=lambda p: p['page_no'])
        devs = []
        for i in range(0, len(ordered) - 1, 2):
            left, right = ordered[i], ordered[i + 1]
            if left['center'] is None or right['center'] is None or not left['page_width']:
                continue
            w = left['page_width']
            lx, ly = left['center']
            rx, ry = right['center']
            # 左页重心做镜像后与右页重心比较: 偏差越小, 跨页越对称
            devs.append([abs((w - lx) - rx) / w, abs(ly - ry) / w])
        if not devs:
            self.spread_symmetry = None
            return None
        self.spread_symmetry = float(1.0 - float(np.mean(devs)))
        return self.spread_symmetry

    # ---- 异常页检测: 方向统一后低于全书均值 n_sigma 个标准差的"劣化页" ----
    def detect_outliers(self, n_sigma=3.0):
        rows = []
        if len(self.pages) >= 5:
            U = _direction_unify(self._matrix())
            mu, sd = U.mean(axis=0), U.std(axis=0)
            Z = (U - mu) / np.where(sd < 1e-12, 1.0, sd)
            for i, p in enumerate(self.pages):
                bad = np.where(Z[i] < -n_sigma)[0]
                if bad.size:
                    rows.append({
                        '页码': p['page_no'],
                        '异常指标': '; '.join(IND_NAMES[j] for j in bad),
                        '最大偏离(σ)': round(float(-Z[i][bad].max()), 2),
                    })
        self.outliers = pd.DataFrame(rows, columns=['页码', '异常指标', '最大偏离(σ)'])
        return self.outliers

    # ---- 全书排版一致性质检报告 ----
    def qa_report_text(self, n_sigma=3.0):
        bar = '=' * 72
        L = [bar, f'《{self.name}》全书排版一致性质检报告', bar]
        total = len(self.pages) + len(self.dropped_pages)
        dropped_nos = ', '.join(str(p['page_no']) for p in self.dropped_pages) or '无'
        L.append(f'总页数: {total} | 有效正文页: {len(self.pages)} | '
                 f'剔除噪声页: {len(self.dropped_pages)} 页 (页码: {dropped_nos})')
        si = f'{self.stability_index:.4f}' if self.stability_index is not None else '未计算'
        ss = f'{self.spread_symmetry:.4f}' if self.spread_symmetry is not None else '未计算(缺重心数据)'
        L.append(f'排版稳定性指数: {si} (越大越稳定) | 跨页对称度: {ss} (越大越对称)')
        L.append('')
        L.append('【全书版面指纹】均值 ± 标准差:')
        if self.fingerprint is not None:
            for nm, mu, sd in zip(IND_NAMES, self.fingerprint, self.stability):
                L.append(f'  {nm:<24s} {mu:>10.4f} ± {sd:.4f}')
        L.append('')
        L.append(f'【异常页检测】判据: 方向统一后劣化方向偏离全书均值超过 {n_sigma:g}σ')
        if len(self.outliers) == 0:
            L.append('  未检测到偏离超阈值的页面, 全书排版风格高度一致。')
        else:
            L.append(f'  共检测到 {len(self.outliers)} 个异常页:')
            for _, r in self.outliers.iterrows():
                L.append(f"  第 {int(r['页码']):>3d} 页: {r['异常指标']}  "
                         f"(最大偏离 {r['最大偏离(σ)']:.1f}σ)")
        L.append('')
        return '\n'.join(L)


def load_book_pages_from_csv(csv_path):
    """加载 MinerU 逐页指标 CSV, 返回 {书名: BookAggregator} (未去噪, 由 pipeline 统一处理)。
    列顺序 (19 列): 书名, 页码, 版面覆盖率, 文本块数, 重心x, 重心y, 页宽, C1~C12
    其中 文本块数/重心x/重心y/页宽 可留空。"""
    df = pd.read_csv(csv_path)
    need = 7 + N_IND
    if df.shape[1] < need:
        raise ValueError(f'逐页 CSV 应含 {need} 列 (书名,页码,版面覆盖率,文本块数,重心x,重心y,页宽 + C1~C12), '
                         f'实际读到 {df.shape[1]} 列')
    books = {}
    for book, g in df.groupby(df.columns[0], sort=False):
        agg = BookAggregator(str(book))
        for _, row in g.iterrows():
            cx, cy, pw, tb, cov = row.iloc[4], row.iloc[5], row.iloc[6], row.iloc[3], row.iloc[2]
            center = None if (pd.isna(cx) or pd.isna(cy)) else (float(cx), float(cy))
            agg.add_page(row.iloc[1], row.iloc[7:7 + N_IND].values,
                         coverage=(1.0 if pd.isna(cov) else float(cov)),
                         text_blocks=(None if pd.isna(tb) else int(tb)),
                         center=center,
                         page_width=(None if pd.isna(pw) else float(pw)))
        books[str(book)] = agg
    return books

