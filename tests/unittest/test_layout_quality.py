# -*- coding: utf-8 -*-
"""Unit tests for the layout quality scoring tool (scripts/layout_quality)."""
import json
import os
import shutil
import sys
import tempfile
import unittest

import numpy as np

# 保证仓库根目录可导入 scripts 命名空间包 (与 pytest 启动方式无关)
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from scripts.layout_quality.aggregator import BookAggregator, page_gravity  # noqa: E402
from scripts.layout_quality.ahp import (  # noqa: E402
    B_MATRIX, C_MATRICES, ahp_subjective_weights, ahp_weight,
)
from scripts.layout_quality.demo import run_demo  # noqa: E402
from scripts.layout_quality.entropy import entropy_weight  # noqa: E402
from scripts.layout_quality import extractor, service  # noqa: E402
from scripts.layout_quality.extractor import (  # noqa: E402
    extract_page_metrics,
    load_book_from_hybrid_dir,
)
from scripts.layout_quality.indicators import CRITERIA, IND_NAMES, N_IND  # noqa: E402
from scripts.layout_quality.pipeline import run_book_qa, run_evaluation  # noqa: E402
from scripts.layout_quality.scoring import (  # noqa: E402
    book_quality_score, normalize_fingerprint,
)
from scripts.layout_quality.topsis import grade_of, topsis  # noqa: E402

# 仓库内一份真实 MinerU 输出 (存在时才跑真实数据用例)
_DEMO3_DIR = os.path.join(
    _REPO_ROOT, 'output', '00491048-e95a-435b-b444-ce81ed972127', 'demo3', 'hybrid_auto')


# 最小合法 PDF (结构完整, 可通过 magika 内容嗅探; 解析作业被 mock, 不真实读取)
_FAKE_PDF_BYTES = b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 841] >>
endobj
xref
0 4
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
trailer
<< /Size 4 /Root 1 0 R >>
startxref
190
%%EOF
"""


def _make_minimal_hybrid_dir(root, book, x2=515):
    """构造最小合法 hybrid_auto 目录 (1 页, 3 个文本块, 满足噪声页阈值)。"""
    import json
    backend = os.path.join(root, book, 'hybrid_auto')
    os.makedirs(backend)
    para_blocks = []
    for i, y in enumerate((100, 200, 300)):
        para_blocks.append({
            'bbox': [80, y, x2, y + 60], 'type': 'text', 'angle': 0, 'index': i + 1,
            'lines': [{'bbox': [80, y + 5, x2, y + 15], 'spans': [
                {'bbox': [80, y + 5, x2, y + 15], 'type': 'text',
                 'content': 'hello', 'score': 0.99}]}],
        })
    middle = {'pdf_info': [{
        'page_size': [595, 841], 'page_idx': 0,
        'preproc_blocks': [], 'discarded_blocks': [],
        'para_blocks': para_blocks,
    }]}
    model = [[{'type': 'text', 'bbox': [80 / 595, y / 841, x2 / 595, (y + 60) / 841],
               'angle': 0, 'content': None} for y in (100, 200, 300)]]
    with open(os.path.join(backend, f'{book}_middle.json'), 'w') as f:
        json.dump(middle, f)
    with open(os.path.join(backend, f'{book}_model.json'), 'w') as f:
        json.dump(model, f)
    return backend


def _make_no_valid_pages_hybrid_dir(root, book):
    """构造去噪后无有效正文页的 hybrid_auto 目录。

    单页仅 1 个小图块 (非文本类), 文本块数=0 且版面覆盖率极低,
    会被 filter_noise_pages 全部剔除, 触发 aggregate() 的
    "去噪后无有效正文页" ValueError (模拟表格/图片为主的试验报告)。
    """
    backend = os.path.join(root, book, 'hybrid_auto')
    os.makedirs(backend)
    para_blocks = [
        {'bbox': [100, 100, 140, 140], 'type': 'image', 'angle': 0,
         'index': 1, 'lines': []},
    ]
    middle = {'pdf_info': [{
        'page_size': [595, 841], 'page_idx': 0,
        'preproc_blocks': [], 'discarded_blocks': [],
        'para_blocks': para_blocks,
    }]}
    model = [[{'type': 'image', 'bbox': [100 / 595, 100 / 841,
                                          140 / 595, 140 / 841],
               'angle': 0, 'content': None}]]
    with open(os.path.join(backend, f'{book}_middle.json'), 'w') as f:
        json.dump(middle, f)
    with open(os.path.join(backend, f'{book}_model.json'), 'w') as f:
        json.dump(model, f)
    return backend


def _make_full_page_table_hybrid_dir(root, book):
    """构造整页大表格的 hybrid_auto 目录 (coverage 高 ~0.73, 文本块数=0)。

    模拟试验报告里"整页一个表格"的正常版面: 版面覆盖率达标但无文本块,
    去噪时应靠 coverage 保留并参与评分 (而非被误判为噪声)。
    """
    backend = os.path.join(root, book, 'hybrid_auto')
    os.makedirs(backend)
    para_blocks = [
        {'bbox': [50, 50, 545, 791], 'type': 'table', 'angle': 0, 'index': 1,
         'lines': [], 'blocks': [{'type': 'table_body',
                                   'bbox': [50, 50, 545, 791]}]},
    ]
    middle = {'pdf_info': [{
        'page_size': [595, 841], 'page_idx': 0,
        'preproc_blocks': [], 'discarded_blocks': [],
        'para_blocks': para_blocks,
    }]}
    model = [[{'type': 'table', 'bbox': [50 / 595, 50 / 841,
                                          545 / 595, 791 / 841],
               'angle': 0, 'content': None}]]
    with open(os.path.join(backend, f'{book}_middle.json'), 'w') as f:
        json.dump(middle, f)
    with open(os.path.join(backend, f'{book}_model.json'), 'w') as f:
        json.dump(model, f)
    return backend


class TestAHP(unittest.TestCase):
    def test_builtin_matrices_pass_consistency(self):
        w_b = ahp_weight(B_MATRIX, name='test-B')
        self.assertAlmostEqual(float(w_b.sum()), 1.0, places=6)
        for cri in CRITERIA:
            w = ahp_weight(C_MATRICES[cri], name=f'test-{cri[:2]}')
            self.assertAlmostEqual(float(w.sum()), 1.0, places=6)

    def test_inconsistent_matrix_raises(self):
        # 明显不一致的判断矩阵 (CR >= 0.1) 应抛错
        bad = [[1, 9, 9], [1 / 9, 1, 9], [1 / 9, 1 / 9, 1]]
        with self.assertRaises(ValueError):
            ahp_weight(bad, name='bad')


class TestEntropyAndTopsis(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(0)
        self.X = rng.uniform(0.5, 1.0, size=(5, N_IND))
        self.X[:, 1] = rng.uniform(1.0, 10.0, size=5)  # C2 为负向指标, 量纲不同

    def test_entropy_weights_sum_to_one(self):
        w, e = entropy_weight(self.X)
        self.assertAlmostEqual(float(w.sum()), 1.0, places=6)
        self.assertTrue((w >= 0).all())
        self.assertTrue(((e >= 0) & (e <= 1 + 1e-9)).all())

    def test_entropy_weight_identical_samples(self):
        # 两本完全相同的书: 差异系数全 0, 应退化为等权而非 NaN
        base = [0.9, 4.0, 0.8, 0.9, 0.9, 0.95, 0.85, 0.8, 0.9, 0.88, 0.9, 0.95]
        X = np.tile(base, (2, 1))
        w, e = entropy_weight(X)
        self.assertTrue(np.isfinite(w).all())
        self.assertAlmostEqual(float(w.sum()), 1.0, places=9)
        np.testing.assert_allclose(w, np.full(N_IND, 1.0 / N_IND), atol=1e-12)

    def test_topsis_closeness_in_unit_interval(self):
        w, _ = entropy_weight(self.X)
        d_pos, d_neg, c, rank = topsis(self.X, w)
        self.assertTrue(((c >= 0) & (c <= 1)).all())
        self.assertEqual(sorted(rank.tolist()), list(range(1, len(c) + 1)))
        # 名次 1 的样本贴近度最高
        self.assertEqual(int(rank[c.argmax()]), 1)

    def test_grade_boundaries(self):
        self.assertEqual(grade_of(0.9), 'T1(国际一流)')
        self.assertEqual(grade_of(0.6), 'T2(优秀)')
        self.assertEqual(grade_of(0.3), 'T3(合格)')
        self.assertEqual(grade_of(0.1), 'T4(待优化)')


class TestBookAggregator(unittest.TestCase):
    def _make_book(self, name='test', n=10, seed=1):
        rng = np.random.default_rng(seed)
        agg = BookAggregator(name)
        for pg in range(1, n + 1):
            m = np.full(N_IND, 0.9) + rng.normal(0, 0.01, N_IND)
            m[1] = 4.0 + rng.normal(0, 0.5)
            agg.add_page(pg, m, coverage=0.6, text_blocks=10,
                         center=(300 + rng.normal(0, 2), 420), page_width=595.0)
        return agg

    def test_filter_noise_pages(self):
        agg = self._make_book()
        agg.add_page(99, np.zeros(N_IND), coverage=0.02, text_blocks=0)
        dropped = agg.filter_noise_pages(coverage_min=0.10, min_text_blocks=3)
        self.assertEqual(dropped, [99])
        self.assertEqual(len(agg.pages), 10)

    def test_filter_noise_pages_keeps_full_page_table_or_image(self):
        """整页表格/图片 (coverage 高但 text_blocks=0) 不应被误判为噪声,
        而空白页 (coverage 低且无文本块) 仍应被剔除。"""
        agg = self._make_book()
        agg.add_page(50, np.full(N_IND, 0.9), coverage=0.73, text_blocks=0)  # 整页表格
        agg.add_page(51, np.full(N_IND, 0.9), coverage=0.52, text_blocks=0)  # 整页图片
        agg.add_page(99, np.zeros(N_IND), coverage=0.02, text_blocks=0)      # 空白页
        dropped = agg.filter_noise_pages(coverage_min=0.10, min_text_blocks=3)
        self.assertEqual(dropped, [99])
        kept_nos = [p['page_no'] for p in agg.pages]
        self.assertIn(50, kept_nos)
        self.assertIn(51, kept_nos)

    def test_filter_noise_pages_text_blocks_none_uses_coverage_only(self):
        """text_blocks 为 None (CSV 未提供) 时, 仅按 coverage 判断。"""
        agg = self._make_book()
        agg.add_page(60, np.full(N_IND, 0.9), coverage=0.40, text_blocks=None)  # 保留
        agg.add_page(61, np.zeros(N_IND), coverage=0.02, text_blocks=None)      # 剔除
        dropped = agg.filter_noise_pages(coverage_min=0.10, min_text_blocks=3)
        self.assertEqual(dropped, [61])
        kept_nos = [p['page_no'] for p in agg.pages]
        self.assertIn(60, kept_nos)

    def test_aggregate_and_stability(self):
        agg = self._make_book()
        agg.filter_noise_pages()
        fp, st = agg.aggregate()
        self.assertEqual(fp.shape, (N_IND,))
        self.assertTrue(0.0 < agg.stability_index <= 1.0)

    def test_spread_symmetry(self):
        agg = self._make_book()
        agg.filter_noise_pages()
        sym = agg.spread_analysis()
        self.assertIsNotNone(sym)
        self.assertTrue(0.0 <= sym <= 1.0)

    def test_outlier_detection(self):
        agg = self._make_book(n=20)
        # 注入劣化页: C12 骤降
        agg.pages[-1]['metrics'] = agg.pages[-1]['metrics'].copy()
        agg.pages[-1]['metrics'][11] = 0.2
        agg.filter_noise_pages()
        agg.detect_outliers(n_sigma=2.0)
        self.assertIn(20, agg.outliers['页码'].tolist())

    def test_full_page_table_dir_scores_successfully(self):
        """整页表格 (coverage 高, text_blocks=0) 应参与评分, 不抛"无有效正文页"。"""
        from scripts.layout_quality.service import analyze_hybrid_dir
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            backend = _make_full_page_table_hybrid_dir(tmp, 'report')
            result = analyze_hybrid_dir(backend)
        self.assertEqual(result['book'], 'report')
        self.assertEqual(result['valid_pages'], 1)
        self.assertEqual(result['dropped_pages'], [])
        self.assertTrue(0.0 <= result['score']['value'] <= 1.0)
class TestDemoPipeline(unittest.TestCase):
    def test_run_demo_self_check(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            result, w_final, qa_text = run_demo(n_pages=40, out_dir=tmp)
            # 演示模式 (无 hybrid_auto 目录): 评分 CSV + 合并逐页明细写入 out_dir, 质检报告仅打印到 stdout
            for f in ('版面量化综合评分结果.csv', '逐页版面指标明细.csv'):
                self.assertTrue(os.path.isfile(os.path.join(tmp, f)), f'缺少输出文件 {f}')
        self.assertAlmostEqual(float(w_final.sum()), 1.0, places=6)
        self.assertEqual(len(result), 8)
        self.assertTrue(result['综合贴近度'].between(0, 1).all())
        self.assertIn('剔除噪声页: 2 页', qa_text)

    def test_run_evaluation_column_check(self):
        X = np.zeros((3, N_IND - 1))
        with self.assertRaises(AssertionError):
            run_evaluation(X, ['a', 'b', 'c'])


class TestExtractor(unittest.TestCase):
    def _synthetic_page(self, n_blocks=6, page_size=(595, 841)):
        """构造一页规整的单栏文本版面 (middle 与 model 基本一致)。"""
        w, h = page_size
        middle_blocks = []
        model_blocks = []
        y = 100.0
        for i in range(n_blocks):
            bbox = [80.0, y, w - 80.0, y + 60.0]
            middle_blocks.append({
                'bbox': bbox, 'type': 'text', 'angle': 0, 'index': i + 1,
                'lines': [
                    {'bbox': [80.0, y + 5.0, w - 80.0, y + 15.0],
                     'spans': [{'bbox': [80.0, y + 5.0, w - 80.0, y + 15.0],
                                'type': 'text', 'content': 'line1', 'score': 0.99}]},
                    {'bbox': [80.0, y + 25.0, w - 80.0, y + 35.0],
                     'spans': [{'bbox': [80.0, y + 25.0, w - 80.0, y + 35.0],
                                'type': 'text', 'content': 'line2', 'score': 0.98}]},
                ],
            })
            model_blocks.append({
                'type': 'text',
                'bbox': [bbox[0] / w, bbox[1] / h, bbox[2] / w, bbox[3] / h],
                'angle': 0, 'content': None,
            })
            y += 90.0
        middle_page = {'page_size': list(page_size), 'page_idx': 0,
                       'preproc_blocks': middle_blocks, 'para_blocks': middle_blocks,
                       'discarded_blocks': []}
        return model_blocks, middle_page

    def test_synthetic_page_metrics_ranges(self):
        model_page, middle_page = self._synthetic_page()
        r = extract_page_metrics(model_page, middle_page)
        self.assertEqual(len(r['metrics']), N_IND)
        c1, c2, c3, c4, c5, c6, c7, c8, c9, c10, c11, c12 = r['metrics']
        # 规整版面: 自一致性指标应接近 1
        self.assertGreater(c1, 0.95)
        self.assertLess(c2, 1.0)          # 对齐误差应很小 (pt)
        self.assertGreater(c4, 0.95)
        self.assertGreater(c5, 0.95)
        self.assertGreater(c6, 0.95)
        for v in (c3, c7, c8, c9, c10, c11, c12):
            self.assertTrue(0.0 <= v <= 1.0, f'指标越界: {v}')
        # 辅助字段
        self.assertTrue(0.0 < r['coverage'] < 1.0)
        self.assertEqual(r['text_blocks'], 6)
        self.assertEqual(r['page_width'], 595.0)
        cx, cy = r['center']
        self.assertTrue(0 < cx < 595 and 0 < cy < 841)

    def test_empty_page_returns_zeros(self):
        middle_page = {'page_size': [595, 841], 'page_idx': 0, 'para_blocks': []}
        r = extract_page_metrics([], middle_page)
        self.assertEqual(r['metrics'], [0.0] * N_IND)
        self.assertEqual(r['coverage'], 0.0)
        self.assertIsNone(r['center'])

    def test_page_gravity_area_weighted(self):
        blocks = [
            {'bbox': [0, 0, 10, 10]},    # 面积 100, 中心 (5, 5)
            {'bbox': [0, 20, 100, 30]},  # 面积 1000, 中心 (50, 25)
        ]
        cx, cy = page_gravity(blocks)
        self.assertAlmostEqual(cx, (5 * 100 + 50 * 1000) / 1100, places=6)
        self.assertAlmostEqual(cy, (5 * 100 + 25 * 1000) / 1100, places=6)

    @unittest.skipUnless(os.path.isdir(_DEMO3_DIR), 'demo3 真实输出不存在, 跳过')
    def test_real_mineru_output(self):
        agg = load_book_from_hybrid_dir(_DEMO3_DIR, book_name='demo3')
        self.assertEqual(len(agg.pages), 10)
        for p in agg.pages:
            m = p['metrics']
            self.assertEqual(len(m), N_IND)
            c1, c2, c3, c4, c5, c6, c7, c8, c9, c10, c11, c12 = m
            self.assertTrue(0.0 <= c1 <= 1.0)
            self.assertGreaterEqual(c2, 0.0)
            for v in (c3, c4, c5, c6, c7, c8, c9, c10, c11, c12):
                self.assertTrue(0.0 <= v <= 1.0, f'指标越界: {v}')
            self.assertTrue(0.0 <= p['coverage'] <= 1.0)
            self.assertIsNotNone(p['center'])
        # 真实论文版面: 自一致性指标应较高
        fp = np.mean([p['metrics'] for p in agg.pages], axis=0)
        self.assertGreater(fp[3], 0.8)   # C4 mIoU
        self.assertGreater(fp[11], 0.8)  # C12 语义纯度


class TestLayoutQuality40Format(unittest.TestCase):
    """4.0 输出格式 (model_output.json + middle_json.json, 归一化 bbox) 适配。"""

    PAGE_W, PAGE_H = 595.0, 842.0

    def _make_40_dir(self, root):
        backend = os.path.join(root, 'demo3', 'out')
        os.makedirs(backend)
        w, h = self.PAGE_W, self.PAGE_H
        middle = {
            'schema': 'docvortex.middle', 'schema_version': '2.0',
            'metadata': {'file_suffix': 'pdf',
                         'producer': {'name': 'mineru', 'version': '4.0'}},
            'extensions': {}, 'is_full_document': True,
            'pages': [{
                'page_idx': 0,
                'blocks': [
                    {'type': 'text', 'index': 1,
                     'bbox': [80 / w, 100 / h, 515 / w, 160 / h],
                     'content': [{'type': 'text', 'content': 'hello world'}]},
                    {'type': 'text', 'index': 2,
                     'bbox': [80 / w, 200 / h, 515 / w, 260 / h],
                     'content': [{'type': 'text', 'content': 'second para'}]},
                    {'type': 'text', 'index': 3,
                     'bbox': [80 / w, 300 / h, 515 / w, 360 / h],
                     'content': [{'type': 'text', 'content': 'third para'}]},
                    {'type': 'table', 'index': 4,
                     'bbox': [50 / w, 400 / h, 545 / w, 700 / h], 'content': []},
                ],
            }],
        }
        model = {
            'schema': 'docvortex.model', 'schema_version': '2.0',
            'metadata': {'file_suffix': 'pdf',
                         'producer': {'name': 'mineru', 'version': '4.0'}},
            'extensions': {'docvortex_layout': {'version': 1, 'pages': [
                {'page_idx': 0, 'width_pt': w, 'height_pt': h}]}},
            'pages': [[
                {'type': 'text', 'bbox': [80 / w, 100 / h, 515 / w, 160 / h]},
                {'type': 'text', 'bbox': [80 / w, 200 / h, 515 / w, 260 / h]},
                {'type': 'text', 'bbox': [80 / w, 300 / h, 515 / w, 360 / h]},
                {'type': 'table', 'bbox': [50 / w, 400 / h, 545 / w, 700 / h]},
            ]],
            'page_index_map': [],
        }
        with open(os.path.join(backend, 'middle_json.json'), 'w', encoding='utf-8') as f:
            json.dump(middle, f)
        with open(os.path.join(backend, 'model_output.json'), 'w', encoding='utf-8') as f:
            json.dump(model, f)
        return backend

    def test_page_size_from_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = self._make_40_dir(tmp)
            with open(os.path.join(backend, 'model_output.json'), encoding='utf-8') as f:
                model = json.load(f)
            self.assertEqual(
                extractor._page_size_from_layout(model, 0), (self.PAGE_W, self.PAGE_H))
            self.assertEqual(
                extractor._page_size_from_layout({}, 0),
                extractor._DEFAULT_PAGE_SIZE)

    def test_block_conversion(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = self._make_40_dir(tmp)
            with open(os.path.join(backend, 'middle_json.json'), encoding='utf-8') as f:
                middle = json.load(f)
            w, h = self.PAGE_W, self.PAGE_H
            text = extractor._middle_block_to_legacy(middle['pages'][0]['blocks'][0], w, h)
            self.assertEqual(text['type'], 'text')
            self.assertAlmostEqual(text['bbox'][0], 80.0)
            self.assertEqual(text['lines'][0]['spans'][0]['content'], 'hello world')
            table = extractor._middle_block_to_legacy(middle['pages'][0]['blocks'][3], w, h)
            self.assertEqual(table['type'], 'table')
            self.assertEqual(table['blocks'][0]['type'], 'table_body')
            self.assertIsNone(extractor._middle_block_to_legacy(
                {'type': 'unknown', 'bbox': [0, 0, 1, 1]}, w, h))

    def test_load_40_dir_auto_detect(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = self._make_40_dir(tmp)
            agg = extractor.load_book_from_hybrid_dir(backend)
            self.assertEqual(len(agg.pages), 1)
            p = agg.pages[0]
            self.assertEqual(p['text_blocks'], 3)
            self.assertGreater(p['coverage'], 0.1)

    def test_analyze_40_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = self._make_40_dir(tmp)
            result = service.analyze_hybrid_dir(backend)
            self.assertEqual(result['book'], 'demo3')
            self.assertTrue(0.0 <= result['score']['value'] <= 1.0)
            self.assertIn('grade', result['score'])

    def test_analyze_parse_result(self):
        """内存 ParseResult 评分 (mock, 不加载模型)。"""
        from types import SimpleNamespace

        w, h = self.PAGE_W, self.PAGE_H
        middle_dict = {
            'schema': 'docvortex.middle', 'schema_version': '2.0',
            'metadata': {'file_suffix': 'pdf',
                         'producer': {'name': 'mineru', 'version': '4.0'}},
            'extensions': {}, 'is_full_document': True,
            'pages': [{
                'page_idx': 0,
                'blocks': [
                    {'type': 'text', 'index': 1,
                     'bbox': [80 / w, 100 / h, 515 / w, 160 / h],
                     'content': [{'type': 'text', 'content': 'hello world'}]},
                    {'type': 'text', 'index': 2,
                     'bbox': [80 / w, 200 / h, 515 / w, 260 / h],
                     'content': [{'type': 'text', 'content': 'second para'}]},
                    {'type': 'text', 'index': 3,
                     'bbox': [80 / w, 300 / h, 515 / w, 360 / h],
                     'content': [{'type': 'text', 'content': 'third para'}]},
                ],
            }],
        }
        model_dict = {
            'schema': 'docvortex.model', 'schema_version': '2.0',
            'metadata': {'file_suffix': 'pdf',
                         'producer': {'name': 'mineru', 'version': '4.0'}},
            'extensions': {'docvortex_layout': {'version': 1, 'pages': [
                {'page_idx': 0, 'width_pt': w, 'height_pt': h}]}},
            'pages': [[
                {'type': 'text', 'bbox': [80 / w, 100 / h, 515 / w, 160 / h]},
                {'type': 'text', 'bbox': [80 / w, 200 / h, 515 / w, 260 / h]},
                {'type': 'text', 'bbox': [80 / w, 300 / h, 515 / w, 360 / h]},
            ]],
            'page_index_map': [],
        }
        result = SimpleNamespace(
            to_dict=lambda **kw: middle_dict,
            _model_output=SimpleNamespace(to_dict=lambda **kw: model_dict),
        )
        out = service.analyze_parse_result(result, book_name='mem')
        self.assertEqual(out['book'], 'mem')
        self.assertTrue(0.0 <= out['score']['value'] <= 1.0)

    # ---- C9 行结构: lines 字段匹配与使用 ----

    def _make_40_dir_with_lines(self, root):
        """构造含 lines 字段的 4.0 目录 (3 个文本块, 每块 4 行)。"""
        backend = os.path.join(root, 'demo3', 'out')
        os.makedirs(backend)
        w, h = self.PAGE_W, self.PAGE_H
        def _lines_for_block(y0, n_lines=4, line_h=15, gap=5):
            lines = []
            y = y0
            for _ in range(n_lines):
                lines.append({'bbox': [80 / w, y / h, 515 / w, (y + line_h) / h]})
                y += line_h + gap
            return lines
        middle = {
            'schema': 'docvortex.middle', 'schema_version': '2.0',
            'metadata': {'file_suffix': 'pdf',
                         'producer': {'name': 'mineru', 'version': '4.0'}},
            'extensions': {}, 'is_full_document': True,
            'pages': [{
                'page_idx': 0,
                'blocks': [
                    {'type': 'text', 'index': 1,
                     'bbox': [80 / w, 100 / h, 515 / w, 160 / h],
                     'content': [{'type': 'text', 'content': 'line1 line2 line3 line4'}]},
                    {'type': 'text', 'index': 2,
                     'bbox': [80 / w, 200 / h, 515 / w, 260 / h],
                     'content': [{'type': 'text', 'content': 'para2'}]},
                    {'type': 'text', 'index': 3,
                     'bbox': [80 / w, 300 / h, 515 / w, 360 / h],
                     'content': [{'type': 'text', 'content': 'para3'}]},
                ],
            }],
        }
        model = {
            'schema': 'docvortex.model', 'schema_version': '2.0',
            'metadata': {'file_suffix': 'pdf',
                         'producer': {'name': 'mineru', 'version': '4.0'}},
            'extensions': {'docvortex_layout': {'version': 1, 'pages': [
                {'page_idx': 0, 'width_pt': w, 'height_pt': h}]}},
            'pages': [[
                {'type': 'text', 'bbox': [80 / w, 100 / h, 515 / w, 160 / h],
                 'lines': _lines_for_block(100)},
                {'type': 'text', 'bbox': [80 / w, 200 / h, 515 / w, 260 / h],
                 'lines': _lines_for_block(200)},
                {'type': 'text', 'bbox': [80 / w, 300 / h, 515 / w, 360 / h],
                 'lines': _lines_for_block(300)},
            ]],
            'page_index_map': [],
        }
        with open(os.path.join(backend, 'middle_json.json'), 'w', encoding='utf-8') as f:
            json.dump(middle, f)
        with open(os.path.join(backend, 'model_output.json'), 'w', encoding='utf-8') as f:
            json.dump(model, f)
        return backend

    def test_match_model_lines(self):
        """_match_model_lines: 类型兼容 + IoU 匹配, 返回绝对坐标行 bbox。"""
        w, h = self.PAGE_W, self.PAGE_H
        middle_block = {'type': 'text', 'bbox': [80 / w, 100 / h, 515 / w, 160 / h]}
        model_page = [
            {'type': 'text', 'bbox': [80 / w, 100 / h, 515 / w, 160 / h],
             'lines': [{'bbox': [80 / w, 100 / h, 515 / w, 115 / h]},
                       {'bbox': [80 / w, 120 / h, 515 / w, 135 / h]}]},
            {'type': 'text', 'bbox': [80 / w, 200 / h, 515 / w, 260 / h],
             'lines': [{'bbox': [80 / w, 200 / h, 515 / w, 215 / h]}]},
        ]
        result = extractor._match_model_lines(middle_block, model_page, w, h)
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 2)
        self.assertAlmostEqual(result[0][0], 80.0)
        self.assertAlmostEqual(result[0][1], 100.0)
        self.assertAlmostEqual(result[0][2], 515.0)
        self.assertAlmostEqual(result[0][3], 115.0)

    def test_match_model_lines_no_match(self):
        """_match_model_lines: 无匹配时返回 None。"""
        w, h = self.PAGE_W, self.PAGE_H
        middle_block = {'type': 'image', 'bbox': [0.1, 0.1, 0.5, 0.5]}
        model_page = [{'type': 'text', 'bbox': [0.1, 0.1, 0.5, 0.5], 'lines': []}]
        self.assertIsNone(extractor._match_model_lines(middle_block, model_page, w, h))
        middle_block = {'type': 'text', 'bbox': [0.1, 0.1, 0.5, 0.5]}
        model_page = [{'type': 'image', 'bbox': [0.1, 0.1, 0.5, 0.5], 'lines': []}]
        self.assertIsNone(extractor._match_model_lines(middle_block, model_page, w, h))
        middle_block = {'type': 'text', 'bbox': [0.1, 0.1, 0.5, 0.5]}
        model_page = [{'type': 'text', 'bbox': [0.8, 0.8, 0.9, 0.9], 'lines': [{'bbox': [0.8, 0.8, 0.9, 0.9]}]}]
        self.assertIsNone(extractor._match_model_lines(middle_block, model_page, w, h))


    def test_build_lines_from_line_bboxes(self):
        """_build_lines_from_line_bboxes: 每行一个 span, bbox 与行相同。"""
        abs_bbox = [80.0, 100.0, 515.0, 160.0]
        line_bboxes = [
            [80.0, 100.0, 515.0, 115.0],
            [80.0, 120.0, 515.0, 135.0],
            [80.0, 140.0, 515.0, 155.0],
        ]
        spans = [{'bbox': abs_bbox, 'type': 'text', 'content': 'hello', 'score': 1.0}]
        lines = extractor._build_lines_from_line_bboxes(line_bboxes, spans, abs_bbox)
        self.assertEqual(len(lines), 3)
        for i, ln in enumerate(lines):
            self.assertEqual(ln['bbox'], line_bboxes[i])
            self.assertEqual(len(ln['spans']), 1)
            self.assertEqual(ln['spans'][0]['bbox'], line_bboxes[i])
        fallback = extractor._build_lines_from_line_bboxes([], spans, abs_bbox)
        self.assertEqual(len(fallback), 1)
        self.assertEqual(fallback[0]['bbox'], abs_bbox)

    def test_middle_block_to_legacy_with_lines(self):
        """_middle_block_to_legacy: 提供 line_bboxes 时按行拆分 lines/spans。"""
        w, h = self.PAGE_W, self.PAGE_H
        block = {'type': 'text', 'index': 1,
                 'bbox': [80 / w, 100 / h, 515 / w, 160 / h],
                 'content': [{'type': 'text', 'content': 'hello world'}]}
        line_bboxes = [
            [80.0, 100.0, 515.0, 115.0],
            [80.0, 120.0, 515.0, 135.0],
            [80.0, 140.0, 515.0, 155.0],
        ]
        legacy = extractor._middle_block_to_legacy(block, w, h, line_bboxes=line_bboxes)
        self.assertEqual(legacy['type'], 'text')
        self.assertEqual(len(legacy['lines']), 3)
        self.assertEqual(legacy['lines'][0]['bbox'], [80.0, 100.0, 515.0, 115.0])
        legacy_no_lines = extractor._middle_block_to_legacy(block, w, h)
        self.assertEqual(len(legacy_no_lines['lines']), 1)

    def test_c9_improves_with_lines(self):
        """C9: 有 lines 数据时能测量真实行结构。"""
        w, h = self.PAGE_W, self.PAGE_H
        blocks_with_lines = []
        blocks_without_lines = []
        for i, y0 in enumerate([100, 200, 300]):
            block_bbox = [80 / w, y0 / h, 515 / w, (y0 + 60) / h]
            block = {'type': 'text', 'index': i + 1, 'bbox': block_bbox,
                     'content': [{'type': 'text', 'content': f'para{i}'}]}
            line_bboxes = []
            y = y0
            for _ in range(4):
                line_bboxes.append([80.0, float(y), 515.0, float(y + 15)])
                y += 20
            legacy_with = extractor._middle_block_to_legacy(block, w, h, line_bboxes=line_bboxes)
            blocks_with_lines.append(legacy_with)
            legacy_without = extractor._middle_block_to_legacy(block, w, h)
            blocks_without_lines.append(legacy_without)
        c9_with = extractor._c9_format_score(blocks_with_lines)
        c9_without = extractor._c9_format_score(blocks_without_lines)
        self.assertGreater(c9_with, 0.8)
        self.assertGreater(c9_without, 0.0)
        self.assertGreaterEqual(c9_with, c9_without - 0.1)

    def test_load_40_dir_with_lines(self):
        """端到端: 含 lines 的 4.0 目录加载后 C9 应反映行级结构。"""
        with tempfile.TemporaryDirectory() as tmp:
            backend = self._make_40_dir_with_lines(tmp)
            agg = extractor.load_book_from_hybrid_dir(backend)
            self.assertEqual(len(agg.pages), 1)
            p = agg.pages[0]
            self.assertEqual(p['text_blocks'], 3)
            c9 = p['metrics'][8]
            self.assertGreater(c9, 0.5)



class TestBookQa(unittest.TestCase):
    """单本书质检: run_book_qa + 目录模式 CLI (输出 <目录>/layout_quality.csv)。"""

    def _make_book_agg(self, name, n=6, seed=3):
        rng = np.random.default_rng(seed)
        agg = BookAggregator(name)
        for pg in range(1, n + 1):
            m = np.full(N_IND, 0.9) + rng.normal(0, 0.01, N_IND)
            m[1] = 4.0 + rng.normal(0, 0.5)
            agg.add_page(pg, m, coverage=0.6, text_blocks=10,
                         center=(300, 420), page_width=595.0)
        return agg

    def test_run_book_qa_writes_csv(self):
        import tempfile
        import pandas as pd
        agg = self._make_book_agg('solo')
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = os.path.join(tmp, 'layout_quality.csv')
            detail, qa = run_book_qa(agg, csv_path=csv_path)
            self.assertEqual(len(detail), 6)
            self.assertEqual(detail.columns.tolist(),
                             ['页码', '是否有效', '版面覆盖率', '文本块数'] + IND_NAMES)
            self.assertTrue(os.path.isfile(csv_path))
            df = pd.read_csv(csv_path)
            self.assertEqual(df.shape, (6, 4 + N_IND))
        self.assertIn('《solo》全书排版一致性质检报告', qa)

    def test_run_book_qa_without_csv(self):
        import tempfile
        agg = self._make_book_agg('solo2')
        with tempfile.TemporaryDirectory() as tmp:
            detail, qa = run_book_qa(agg)   # 不指定 csv_path, 不写任何文件
            self.assertEqual(len(detail), 6)
            self.assertEqual(os.listdir(tmp), [])
        self.assertIn('《solo2》全书排版一致性质检报告', qa)

    def _make_hybrid_dir(self, root, book, x2=515):
        """构造最小合法 hybrid_auto 目录 (1 页, 3 个文本块, 满足噪声页阈值)。"""
        import json
        backend = os.path.join(root, book, 'hybrid_auto')
        os.makedirs(backend)
        para_blocks = []
        for i, y in enumerate((100, 200, 300)):
            para_blocks.append({
                'bbox': [80, y, x2, y + 60], 'type': 'text', 'angle': 0, 'index': i + 1,
                'lines': [{'bbox': [80, y + 5, x2, y + 15], 'spans': [
                    {'bbox': [80, y + 5, x2, y + 15], 'type': 'text',
                     'content': 'hello', 'score': 0.99}]}],
            })
        middle = {'pdf_info': [{
            'page_size': [595, 841], 'page_idx': 0,
            'preproc_blocks': [], 'discarded_blocks': [],
            'para_blocks': para_blocks,
        }]}
        model = [[{'type': 'text', 'bbox': [80 / 595, y / 841, x2 / 595, (y + 60) / 841],
                   'angle': 0, 'content': None} for y in (100, 200, 300)]]
        with open(os.path.join(backend, f'{book}_middle.json'), 'w') as f:
            json.dump(middle, f)
        with open(os.path.join(backend, f'{book}_model.json'), 'w') as f:
            json.dump(model, f)
        return backend

    def test_cli_single_dir_writes_layout_quality_csv(self):
        import tempfile
        import pandas as pd
        with tempfile.TemporaryDirectory() as tmp:
            backend = self._make_hybrid_dir(tmp, 'solo')
            import scripts.layout_quality.cli as cli
            result, w_final, qa = cli.main([backend])
            self.assertIsNone(result)      # 单本书无 TOPSIS 结果
            self.assertIsNone(w_final)
            self.assertIn('《solo》', qa)
            # 逐页明细写入 <hybrid_auto>/layout_quality.csv
            self.assertTrue(os.path.isfile(os.path.join(backend, 'layout_quality.csv')))
            # 全书综合评分写入 <hybrid_auto>/layout_quality_score.csv (单行)
            score_csv = os.path.join(backend, 'layout_quality_score.csv')
            self.assertTrue(os.path.isfile(score_csv))
            sdf = pd.read_csv(score_csv)
            self.assertEqual(len(sdf), 1)
            self.assertEqual(sdf['书名'].iloc[0], 'solo')
            self.assertTrue(0.0 <= float(sdf['综合评分'].iloc[0]) <= 1.0)
            self.assertIn('档位', sdf.columns.tolist())

    def test_cli_multi_dir_writes_each_and_score(self):
        import tempfile
        import pandas as pd
        with tempfile.TemporaryDirectory() as tmp:
            b1 = self._make_hybrid_dir(tmp, 'bookA')
            b2 = self._make_hybrid_dir(tmp, 'bookB', x2=500)   # 略不同, 避免完全同分
            out_dir = os.path.join(tmp, 'out')
            import scripts.layout_quality.cli as cli
            result, w_final, qa = cli.main([b1, b2, '--out', out_dir])
            self.assertEqual(len(result), 2)
            self.assertTrue(os.path.isfile(os.path.join(b1, 'layout_quality.csv')))
            self.assertTrue(os.path.isfile(os.path.join(b2, 'layout_quality.csv')))
            self.assertTrue(os.path.isfile(os.path.join(b1, 'layout_quality_score.csv')))
            self.assertTrue(os.path.isfile(os.path.join(b2, 'layout_quality_score.csv')))
            score_csv = os.path.join(out_dir, '版面量化综合评分结果.csv')
            self.assertTrue(os.path.isfile(score_csv))
            sdf = pd.read_csv(score_csv)
            # 绝对分 (综合评分) 与相对分 (综合贴近度) 双口径并列
            self.assertIn('综合评分', sdf.columns.tolist())
            self.assertIn('档位(绝对)', sdf.columns.tolist())
            self.assertIn('综合贴近度', sdf.columns.tolist())
            self.assertTrue(sdf['综合评分'].between(0, 1).all())


class TestBookQualityScore(unittest.TestCase):
    """全书版面质量综合评分 (绝对分): 归一化 / 加权 / 边界。"""

    def _agg(self, name, fp, n=6):
        """构造固定指纹的聚合器 (每页指标 = fp, 无噪声)。"""
        agg = BookAggregator(name)
        for pg in range(1, n + 1):
            agg.add_page(pg, list(fp), coverage=0.6, text_blocks=10,
                         center=(300, 420), page_width=595.0)
        agg.filter_noise_pages()
        agg.aggregate()
        return agg

    def test_perfect_book_scores_one(self):
        fp = [1.0, 0.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]
        agg = self._agg('perfect', fp)
        w = ahp_subjective_weights(verbose=False)
        score, _ = book_quality_score(agg, w)
        self.assertAlmostEqual(score, 1.0, places=9)
        self.assertEqual(grade_of(score), 'T1(国际一流)')

    def test_worst_book_scores_near_zero(self):
        fp = [0.0, 100.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        agg = self._agg('worst', fp)
        w = ahp_subjective_weights(verbose=False)
        score, _ = book_quality_score(agg, w)
        self.assertLess(score, 0.05)
        self.assertEqual(grade_of(score), 'T4(待优化)')

    def test_c2_normalization_monotonic(self):
        base = [0.9, 0.0, 0.8, 0.9, 0.9, 0.95, 0.85, 0.8, 0.9, 0.88, 0.9, 0.95]
        s0 = normalize_fingerprint(base)
        s1 = normalize_fingerprint([0.9, 10.0, 0.8, 0.9, 0.9, 0.95, 0.85, 0.8, 0.9, 0.88, 0.9, 0.95])
        s2 = normalize_fingerprint([0.9, 100.0, 0.8, 0.9, 0.9, 0.95, 0.85, 0.8, 0.9, 0.88, 0.9, 0.95])
        self.assertAlmostEqual(s0[1], 1.0, places=9)     # 0 误差 -> 满分
        self.assertAlmostEqual(s1[1], 0.5, places=9)     # 10pt 误差 -> 半分
        self.assertGreater(s1[1], s2[1])                  # 单调递减
        self.assertTrue(((s0 >= 0) & (s0 <= 1)).all())

    def test_score_requires_aggregation(self):
        agg = BookAggregator('empty')
        w = ahp_subjective_weights(verbose=False)
        with self.assertRaises(ValueError):
            book_quality_score(agg, w)


class TestLayoutQualityService(unittest.TestCase):
    """API 服务层: analyze_book / analyze_hybrid_dir (纯计算, 无副作用)。"""

    def test_analyze_hybrid_dir_payload(self):
        import tempfile
        from scripts.layout_quality.service import analyze_hybrid_dir
        with tempfile.TemporaryDirectory() as tmp:
            backend = _make_minimal_hybrid_dir(tmp, 'solo')
            result = analyze_hybrid_dir(backend)
        self.assertEqual(result['book'], 'solo')
        self.assertEqual(result['total_pages'], 1)
        self.assertEqual(result['valid_pages'], 1)
        self.assertEqual(result['dropped_pages'], [])
        score = result['score']
        self.assertTrue(0.0 <= score['value'] <= 1.0)
        self.assertAlmostEqual(score['percent'], score['value'] * 100, places=2)
        self.assertIn(score['grade'],
                      ('T1(国际一流)', 'T2(优秀)', 'T3(合格)', 'T4(待优化)'))
        self.assertEqual(len(score['sub_scores']), N_IND)
        self.assertEqual(len(result['fingerprint']), N_IND)
        self.assertEqual(len(result['pages']), 1)
        self.assertEqual(result['pages'][0]['页码'], 1)
        self.assertEqual(result['pages'][0]['是否有效'], '是')
        self.assertIn('《solo》', result['qa_report'])

    def test_analyze_hybrid_dir_json_serializable(self):
        import json
        import tempfile
        from scripts.layout_quality.service import analyze_hybrid_dir
        with tempfile.TemporaryDirectory() as tmp:
            backend = _make_minimal_hybrid_dir(tmp, 'solo')
            data = json.loads(json.dumps(analyze_hybrid_dir(backend),
                                         ensure_ascii=False))
        self.assertEqual(data['book'], 'solo')
        self.assertEqual(len(data['score']['sub_scores']), N_IND)

    def test_analyze_hybrid_dir_writes_nothing(self):
        """API 服务层为只读计算: 不向 hybrid_auto 目录写任何文件。"""
        import tempfile
        from scripts.layout_quality.service import analyze_hybrid_dir
        with tempfile.TemporaryDirectory() as tmp:
            backend = _make_minimal_hybrid_dir(tmp, 'solo')
            before = set(os.listdir(backend))
            analyze_hybrid_dir(backend)
            self.assertEqual(set(os.listdir(backend)), before)

    def test_analyze_hybrid_dir_missing_json(self):
        import tempfile
        from scripts.layout_quality.service import analyze_hybrid_dir
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                analyze_hybrid_dir(tmp)


class _FakeTask:
    def __init__(self, task_id, status, output_dir, file_names, backend, parse_method):
        self.task_id = task_id
        self.status = status
        self.output_dir = output_dir
        self.file_names = file_names
        self.backend = backend
        self.parse_method = parse_method

    def to_status_payload(self, request, queued_ahead=None):
        return {'task_id': self.task_id, 'status': self.status}


class _FakeTaskManager:
    _tasks = {}

    @classmethod
    def register(cls, **kwargs):
        task = _FakeTask(**kwargs)
        cls._tasks[task.task_id] = task
        return task

    def get(self, task_id):
        return self._tasks.get(task_id)


class TestLayoutQualityAPI(unittest.TestCase):
    """FastAPI 端点: /layout_quality 与 /tasks/{task_id}/layout_quality。"""

    @classmethod
    def setUpClass(cls):
        try:
            from fastapi.testclient import TestClient
            import mineru.cli.fast_api as fast_api_module
        except Exception as exc:
            raise unittest.SkipTest(f'无法导入 mineru.cli.fast_api: {exc}')
        cls.app = fast_api_module.app
        cls.client = TestClient(cls.app)
        # 注入假任务管理器 (不启动真实 lifespan)
        cls._original_tm = getattr(cls.app.state, 'task_manager', None)
        cls.app.state.task_manager = _FakeTaskManager()

    @classmethod
    def tearDownClass(cls):
        if cls._original_tm is None:
            try:
                del cls.app.state.task_manager
            except AttributeError:
                pass
        else:
            cls.app.state.task_manager = cls._original_tm

    def test_get_layout_quality_by_path(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            backend = _make_minimal_hybrid_dir(tmp, 'api')
            resp = self.client.get('/layout_quality', params={'path': backend})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['book'], 'api')
        self.assertEqual(data['total_pages'], 1)
        self.assertTrue(0.0 <= data['score']['value'] <= 1.0)
        self.assertEqual(len(data['pages']), 1)
        self.assertIn('qa_report', data)

    def test_get_layout_quality_missing_dir(self):
        resp = self.client.get('/layout_quality',
                               params={'path': '/nonexistent/lq/xyz'})
        self.assertEqual(resp.status_code, 404)

    def test_get_layout_quality_dir_without_json(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            resp = self.client.get('/layout_quality', params={'path': tmp})
        self.assertEqual(resp.status_code, 400)

    def test_get_task_layout_quality(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            _make_minimal_hybrid_dir(tmp, 'demo3')
            _FakeTaskManager().register(
                task_id='t-lq-1', status='completed', output_dir=tmp,
                file_names=['demo3'], backend='hybrid-engine', parse_method='auto')
            resp = self.client.get('/tasks/t-lq-1/layout_quality')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['task_id'], 't-lq-1')
        self.assertEqual(data['book'], 'demo3')
        self.assertTrue(0.0 <= data['score']['value'] <= 1.0)

    def test_get_task_layout_quality_not_found(self):
        resp = self.client.get('/tasks/no-such-task/layout_quality')
        self.assertEqual(resp.status_code, 404)

    def test_get_task_layout_quality_pending(self):
        _FakeTaskManager().register(
            task_id='t-lq-2', status='pending', output_dir='/tmp',
            file_names=['x'], backend='hybrid-engine', parse_method='auto')
        resp = self.client.get('/tasks/t-lq-2/layout_quality')
        self.assertEqual(resp.status_code, 202)

    def test_get_task_layout_quality_missing_json(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            # 输出目录存在但无 model/middle json (解析时未开启对应 return 选项)
            os.makedirs(os.path.join(tmp, 'demo3', 'hybrid_auto'))
            _FakeTaskManager().register(
                task_id='t-lq-3', status='completed', output_dir=tmp,
                file_names=['demo3'], backend='hybrid-engine', parse_method='auto')
            resp = self.client.get('/tasks/t-lq-3/layout_quality')
        self.assertEqual(resp.status_code, 404)


class _InlineTaskManager:
    """假任务管理器: submit 时内联执行 (被 monkeypatch 的) 解析作业,
    模拟真实 AsyncTaskManager._run_task 流程 (含版面质量评分)。"""

    def __init__(self):
        self._tasks = {}

    async def submit(self, task):
        import mineru.cli.fast_api as fa
        self._tasks[task.task_id] = task
        uploads = [
            fa.StoredUpload(original_name=n, stem=s, path=p)
            for n, s, p in zip(task.upload_names, task.file_names, task.uploads)
        ]
        await fa.run_parse_job(
            output_dir=task.output_dir, uploads=uploads,
            request_options=task, config={},
        )
        if getattr(task, 'return_layout_quality', False):
            task.layout_quality = await fa.compute_task_layout_quality(task)
        task.status = fa.TASK_COMPLETED
        task.completed_at = fa.utc_now_iso()
        return task

    def get(self, task_id):
        return self._tasks.get(task_id)

    async def wait_for_terminal_state(self, task_id):
        return self._tasks[task_id]

    def build_status_payload(self, task, request):
        return task.to_status_payload(request)


async def _fake_run_parse_job(output_dir, uploads, request_options,
                              config, progress_callback=None):
    """假解析作业: 只写最小 hybrid_auto 目录, 不做真实模型推理。"""
    for upload in uploads:
        _make_minimal_hybrid_dir(output_dir, upload.stem)
    return [upload.stem for upload in uploads]


async def _fake_run_parse_job_no_valid_pages(output_dir, uploads, request_options,
                                             config, progress_callback=None):
    """假解析作业: 只写去噪后无有效正文页的 hybrid_auto 目录 (评分会抛 ValueError)。"""
    for upload in uploads:
        _make_no_valid_pages_hybrid_dir(output_dir, upload.stem)
    return [upload.stem for upload in uploads]


class TestLayoutQualityParseFlow(unittest.TestCase):
    """解析流程 return_layout_quality 选项: 同步 /file_parse 与异步 /tasks。"""

    @classmethod
    def setUpClass(cls):
        try:
            from fastapi.testclient import TestClient
            import mineru.cli.fast_api as fast_api_module
        except Exception as exc:
            raise unittest.SkipTest(f'无法导入 mineru.cli.fast_api: {exc}')
        cls.fa = fast_api_module
        cls.app = fast_api_module.app
        cls.client = TestClient(cls.app)
        cls._original_tm = getattr(cls.app.state, 'task_manager', None)
        cls.app.state.task_manager = _InlineTaskManager()
        # 任务输出重定向到临时目录, 避免污染仓库 output/
        cls._output_root = tempfile.mkdtemp(prefix='lq_parse_flow_')
        cls._original_output_root = os.environ.get('MINERU_API_OUTPUT_ROOT')
        os.environ['MINERU_API_OUTPUT_ROOT'] = cls._output_root
        # 替换真实解析作业 (不跑模型)
        cls._original_run_parse_job = fast_api_module.run_parse_job
        fast_api_module.run_parse_job = _fake_run_parse_job

    @classmethod
    def tearDownClass(cls):
        cls.fa.run_parse_job = cls._original_run_parse_job
        if cls._original_output_root is None:
            os.environ.pop('MINERU_API_OUTPUT_ROOT', None)
        else:
            os.environ['MINERU_API_OUTPUT_ROOT'] = cls._original_output_root
        shutil.rmtree(cls._output_root, ignore_errors=True)
        if cls._original_tm is None:
            try:
                del cls.app.state.task_manager
            except AttributeError:
                pass
        else:
            cls.app.state.task_manager = cls._original_tm

    def _post_file_parse(self, **extra_form):
        # 显式关闭所有 return 选项 (不依赖 API 默认值, 避免默认值变更影响用例)
        form = {
            'lang_list': 'ch',
            'backend': 'hybrid-engine',
            'parse_method': 'auto',
            'return_md': 'false',
            'return_middle_json': 'false',
            'return_model_output': 'false',
            'return_layout_quality': 'false',
            'return_content_list': 'false',
            'return_images': 'false',
            'response_format_zip': 'false',
        }
        form.update(extra_form)
        return self.client.post(
            '/file_parse',
            files=[('files', ('demo3.pdf', _FAKE_PDF_BYTES, 'application/pdf'))],
            data=form,
        )

    def test_file_parse_json_includes_layout_quality(self):
        resp = self._post_file_parse(return_layout_quality='true')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('layout_quality', data)
        lq = data['layout_quality']
        self.assertEqual(lq['book'], 'demo3')
        self.assertTrue(0.0 <= lq['score']['value'] <= 1.0)
        # 强制落盘不膨胀响应: middle/model 未请求则不返回
        self.assertNotIn('middle_json', data['results']['demo3'])
        self.assertNotIn('model_output', data['results']['demo3'])

    def test_file_parse_default_no_layout_quality(self):
        """_post_file_parse 默认关闭 return_layout_quality, 响应不含 layout_quality。"""
        resp = self._post_file_parse()
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('layout_quality', resp.json())

    def test_file_parse_zip_includes_layout_quality_json(self):
        import io
        import zipfile
        resp = self._post_file_parse(
            return_layout_quality='true', response_format_zip='true')
        self.assertEqual(resp.status_code, 200)
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        # 评分文件与 middle/model json 同目录 (hybrid_auto 内), 不在 zip 根目录
        arcname = 'demo3/hybrid_auto/layout_quality.json'
        self.assertIn(arcname, zf.namelist())
        self.assertNotIn('layout_quality.json', zf.namelist())
        lq = json.loads(zf.read(arcname))
        self.assertEqual(lq['book'], 'demo3')
        self.assertIn('score', lq)

    def test_file_parse_default_returns_zip(self):
        """response_format_zip 默认 True (有意设计: zip 可打包所有输出物),
        不传该参数时 /file_parse 默认返回 zip 而非 JSON。"""
        import io
        import zipfile
        resp = self.client.post(
            '/file_parse',
            files=[('files', ('demo3.pdf', _FAKE_PDF_BYTES, 'application/pdf'))],
            data={
                'lang_list': 'ch',
                'backend': 'hybrid-engine',
                'parse_method': 'auto',
                'return_md': 'false',
                'return_middle_json': 'false',
                'return_model_output': 'false',
                'return_content_list': 'false',
                'return_images': 'false',
                'return_layout_quality': 'false',
                # 不传 response_format_zip, 验证默认值 (True) 生效
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn('application/zip', resp.headers.get('content-type', ''))
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        self.assertIsInstance(zf.namelist(), list)

    def test_async_task_result_includes_layout_quality(self):
        resp = self.client.post(
            '/tasks',
            files=[('files', ('demo3.pdf', _FAKE_PDF_BYTES, 'application/pdf'))],
            data={
                'lang_list': 'ch',
                'backend': 'hybrid-engine',
                'parse_method': 'auto',
                'return_md': 'false',
                'return_middle_json': 'false',
                'return_model_output': 'false',
                'return_content_list': 'false',
                'return_images': 'false',
                'return_layout_quality': 'true',
                'response_format_zip': 'false',  # 显式返回 JSON (API 默认已改为 zip)
            },
        )
        self.assertEqual(resp.status_code, 202)
        task_id = resp.json()['task_id']
        resp = self.client.get(f'/tasks/{task_id}/result')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('layout_quality', data)
        self.assertTrue(0.0 <= data['layout_quality']['score']['value'] <= 1.0)

    def test_task_layout_quality_endpoint_reuses_cache(self):
        """解析时已评分的任务, 端点直接复用缓存 (n_sigma 默认 3.0)。"""
        resp = self._post_file_parse(return_layout_quality='true')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        task_id = data['task_id']
        resp = self.client.get(f'/tasks/{task_id}/layout_quality')
        self.assertEqual(resp.status_code, 200)
        cached = resp.json()
        self.assertEqual(cached['task_id'], task_id)
        self.assertEqual(cached['score']['value'],
                         data['layout_quality']['score']['value'])


class TestRunTaskLayoutQualityWiring(unittest.TestCase):
    """真实 AsyncTaskManager._run_task: return_layout_quality 开启时解析后评分。"""

    @classmethod
    def setUpClass(cls):
        # 4.0 架构移除了 mineru/cli/fast_api.py，接线测试待移植到新 CLI 后恢复
        try:
            import mineru.cli.fast_api  # noqa: F401
        except Exception as exc:
            raise unittest.SkipTest(f'无法导入 mineru.cli.fast_api: {exc}')

    def _run(self, return_layout_quality, fake_job=_fake_run_parse_job):
        import asyncio
        import mineru.cli.fast_api as fa
        from mineru.cli.sqlite_queue import SQLiteQueueManager
        tmp = tempfile.mkdtemp(prefix='lq_wiring_')
        task = fa.AsyncParseTask(
            task_id='t-wiring', status=fa.TASK_PENDING, backend='hybrid-engine',
            file_names=['demo3'], created_at=fa.utc_now_iso(), output_dir=tmp,
            effort='medium', parse_method='auto', lang_list=['ch'],
            formula_enable=True, table_enable=True, image_analysis=True,
            server_url=None, return_md=False, return_middle_json=False,
            return_model_output=False, return_layout_quality=return_layout_quality,
            return_content_list=False, return_images=False,
            response_format_zip=False, return_original_file=False,
            return_layout_pdf=False,
            client_side_output_generation=False, start_page_id=0, end_page_id=99999,
            upload_names=['demo3.pdf'], uploads=[os.path.join(tmp, 'demo3.pdf')],
        )
        manager = fa.AsyncTaskManager(fa.app)
        # 队列持久化重定向到临时 DB, 避免污染开发库
        manager._sqlite = SQLiteQueueManager(db_path=os.path.join(tmp, 'queue.db'))
        original = fa.run_parse_job
        fa.run_parse_job = fake_job
        try:
            asyncio.run(manager._run_task(task))
        finally:
            fa.run_parse_job = original
            shutil.rmtree(tmp, ignore_errors=True)
        return task

    def test_run_task_computes_layout_quality_when_enabled(self):
        task = self._run(return_layout_quality=True)
        self.assertEqual(task.status, 'completed')
        self.assertIsNotNone(task.layout_quality)
        self.assertEqual(task.layout_quality['book'], 'demo3')
        self.assertIn('score', task.layout_quality)

    def test_run_task_skips_layout_quality_when_disabled(self):
        task = self._run(return_layout_quality=False)
        self.assertEqual(task.status, 'completed')
        self.assertIsNone(task.layout_quality)

    def test_run_task_layout_quality_failure_does_not_fail_task(self):
        """评分失败 (去噪后无有效正文页, 抛 ValueError) 时任务仍应成功完成,
        layout_quality 为 None —— best-effort, 评分失败不影响解析结果。"""
        task = self._run(return_layout_quality=True,
                         fake_job=_fake_run_parse_job_no_valid_pages)
        self.assertEqual(task.status, 'completed')
        self.assertIsNone(task.layout_quality)


class TestCreateResultZipLayoutPdf(unittest.TestCase):
    """create_result_zip: return_layout_pdf 控制 {name}_layout.pdf 是否入 zip。

    与 return_original_file 对称: layout.pdf 只进 zip 不进 JSON, 由
    return_layout_pdf 开关控制 (默认 True 保持历史行为, 可显式关闭)。
    """

    @classmethod
    def setUpClass(cls):
        # 4.0 架构移除了 mineru/cli/fast_api.py，接线测试待移植到新 CLI 后恢复
        try:
            import mineru.cli.fast_api  # noqa: F401
        except Exception as exc:
            raise unittest.SkipTest(f'无法导入 mineru.cli.fast_api: {exc}')

    def _make_parse_dir_with_layout_pdf(self, tmp):
        import mineru.cli.fast_api as fa
        parse_dir = fa.get_parse_dir(tmp, 'demo3', 'hybrid-engine', 'auto')
        os.makedirs(parse_dir, exist_ok=True)
        with open(os.path.join(parse_dir, 'demo3_layout.pdf'), 'wb') as f:
            f.write(b'%PDF-1.4 fake layout pdf')
        return parse_dir

    def _zip_names(self, tmp, return_layout_pdf):
        import zipfile
        import mineru.cli.fast_api as fa
        zip_path = fa.create_result_zip(
            tmp, ['demo3'], 'hybrid-engine', 'auto',
            return_md=False, return_middle_json=False, return_model_output=False,
            return_content_list=False, return_images=False,
            return_original_file=False, return_layout_pdf=return_layout_pdf,
        )
        try:
            with zipfile.ZipFile(zip_path) as zf:
                return zf.namelist()
        finally:
            os.remove(zip_path)

    def test_layout_pdf_included_when_enabled(self):
        tmp = tempfile.mkdtemp(prefix='lq_zip_on_')
        try:
            self._make_parse_dir_with_layout_pdf(tmp)
            names = self._zip_names(tmp, return_layout_pdf=True)
            self.assertTrue(
                any(n.endswith('demo3_layout.pdf') for n in names),
                f'expected demo3_layout.pdf in zip, got: {names}',
            )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_layout_pdf_excluded_when_disabled(self):
        tmp = tempfile.mkdtemp(prefix='lq_zip_off_')
        try:
            self._make_parse_dir_with_layout_pdf(tmp)
            names = self._zip_names(tmp, return_layout_pdf=False)
            self.assertFalse(
                any(n.endswith('demo3_layout.pdf') for n in names),
                f'expected demo3_layout.pdf NOT in zip, got: {names}',
            )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestLayoutQualityV1API(unittest.TestCase):
    """V1 API (mineru/parser/api_server.py) 的 layout_quality 输出格式与 JobStore 持久化。

    4.0 架构中 layout_quality 是解析任务的输出格式 (在 _run_job 内从内存
    ParseResult 计算), 不再是 3.x 的独立 /layout_quality 端点。
    """

    def _mock_parse_result(self):
        from types import SimpleNamespace

        w, h = 595.0, 842.0
        middle_dict = {
            'schema': 'docvortex.middle', 'schema_version': '2.0',
            'metadata': {'file_suffix': 'pdf',
                         'producer': {'name': 'mineru', 'version': '4.0'}},
            'extensions': {}, 'is_full_document': True,
            'pages': [{
                'page_idx': 0,
                'blocks': [
                    {'type': 'text', 'index': 1,
                     'bbox': [80 / w, 100 / h, 515 / w, 160 / h],
                     'content': [{'type': 'text', 'content': 'hello world'}]},
                    {'type': 'text', 'index': 2,
                     'bbox': [80 / w, 200 / h, 515 / w, 260 / h],
                     'content': [{'type': 'text', 'content': 'second para'}]},
                    {'type': 'text', 'index': 3,
                     'bbox': [80 / w, 300 / h, 515 / w, 360 / h],
                     'content': [{'type': 'text', 'content': 'third para'}]},
                ],
            }],
        }
        model_dict = {
            'schema': 'docvortex.model', 'schema_version': '2.0',
            'metadata': {'file_suffix': 'pdf',
                         'producer': {'name': 'mineru', 'version': '4.0'}},
            'extensions': {'docvortex_layout': {'version': 1, 'pages': [
                {'page_idx': 0, 'width_pt': w, 'height_pt': h}]}},
            'pages': [[
                {'type': 'text', 'bbox': [80 / w, 100 / h, 515 / w, 160 / h]},
                {'type': 'text', 'bbox': [80 / w, 200 / h, 515 / w, 260 / h]},
                {'type': 'text', 'bbox': [80 / w, 300 / h, 515 / w, 360 / h]},
            ]],
            'page_index_map': [],
        }
        return SimpleNamespace(
            to_dict=lambda **kw: middle_dict,
            _model_output=SimpleNamespace(to_dict=lambda **kw: model_dict),
        )

    def test_layout_quality_is_valid_output_format(self):
        from mineru.parser import api_server

        self.assertIn('layout_quality', api_server._OUTPUT_FORMATS_LOCAL)
        self.assertIn('layout_quality', api_server._LOCAL_PARSE_OUTPUT_FORMATS)

    def test_compute_layout_quality_from_parse_result(self):
        """_compute_layout_quality 从内存 ParseResult 计算评分 (mock, 不加载模型)。"""
        from mineru.parser.api_server import _compute_layout_quality

        out = _compute_layout_quality(self._mock_parse_result(), 'mem')
        self.assertEqual(out['book'], 'mem')
        self.assertTrue(0.0 <= out['score']['value'] <= 1.0)
        self.assertIn('grade', out['score'])

    def test_job_store_persistence_roundtrip(self):
        """JobStore SQLite 持久化: 创建 -> 重启恢复 -> 中断任务标记 failed。"""
        from types import SimpleNamespace

        from mineru.parser.api_server import (
            CreateJobRequest,
            FileIdSource,
            JobFileEntry,
            JobStore,
        )

        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, 'jobs.sqlite')
            req = CreateJobRequest(
                files=[JobFileEntry(source=FileIdSource(file_id='f1'), page_range='')],
                tier='standard',
                output_formats=['markdown', 'layout_quality'],
            )
            fs = SimpleNamespace(
                get_file=lambda fid: SimpleNamespace(filename='demo.pdf'))
            store1 = JobStore(concurrency=1, db_path=db)
            rec = store1.create(req, fs)
            rec.status = 'running'
            store1._persist(rec)
            store1._persistence.close()
            store2 = JobStore(concurrency=1, db_path=db)
            restored = store2.get(rec.id)
            self.assertEqual(restored.status, 'failed')
            self.assertEqual(restored.output_formats, ['markdown', 'layout_quality'])
            self.assertEqual(restored.files[0].name, 'demo.pdf')

    def test_job_store_no_persistence_without_db(self):
        from mineru.parser.api_server import JobStore

        store = JobStore(concurrency=1)
        self.assertIsNone(store._persistence)


if __name__ == '__main__':
    unittest.main()

