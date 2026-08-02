# Copyright (c) Opendatalab. All rights reserved.
"""Unit tests for the page type classifier."""
import unittest
from mineru.backend.pipeline.page_type_classifier import (
    infer_page_type,
    classify_all_pages,
    _get_block_type_counts,
    _get_block_text,
    _contains_keyword,
    _calculate_visual_area_ratio,
    _count_toc_lines_in_page,
    _detect_toc_page_set,
)
from mineru.utils.enum_class import BlockType, PageType


class TestHelperFunctions(unittest.TestCase):
    def test_get_block_type_counts(self):
        blocks = [
            {"type": BlockType.TEXT},
            {"type": BlockType.INDEX},
            {"type": BlockType.INDEX},
            {"type": BlockType.DOC_TITLE},
        ]
        counts = _get_block_type_counts(blocks)
        self.assertEqual(counts.get(BlockType.TEXT, 0), 1)
        self.assertEqual(counts.get(BlockType.INDEX, 0), 2)
        self.assertEqual(counts.get(BlockType.DOC_TITLE, 0), 1)

    def test_get_block_text(self):
        blocks = [
            {
                "lines": [
                    {"spans": [{"content": "Hello"}, {"content": "World"}]},
                ]
            },
            {
                "lines": [
                    {"spans": [{"content": "Foo"}]},
                ]
            },
        ]
        text = _get_block_text(blocks)
        self.assertIn("Hello", text)
        self.assertIn("World", text)
        self.assertIn("Foo", text)

    def test_contains_keyword(self):
        self.assertTrue(_contains_keyword("This is a copyright notice", ["copyright"]))
        self.assertTrue(_contains_keyword("This is a COPYRIGHT notice", ["copyright"]))
        self.assertFalse(_contains_keyword("This is normal text", ["copyright"]))

    def test_calculate_visual_area_ratio(self):
        # Page 100x100, one image block covering 50x50 = 2500 / 10000 = 0.25
        blocks = [
            {
                "type": BlockType.IMAGE,
                "bbox": [0, 0, 50, 50],
            }
        ]
        ratio = _calculate_visual_area_ratio(blocks, 100, 100)
        self.assertAlmostEqual(ratio, 0.25)

    def test_calculate_visual_area_ratio_empty(self):
        ratio = _calculate_visual_area_ratio([], 100, 100)
        self.assertEqual(ratio, 0.0)


class TestInferPageType(unittest.TestCase):
    def _make_page_info(self, blocks, page_size=(800, 1000)):
        return {
            "preproc_blocks": blocks,
            "page_size": list(page_size),
        }

    def test_blank_page(self):
        page_info = self._make_page_info([])
        self.assertEqual(infer_page_type(page_info, 0, 1), PageType.BLANK)

    def test_cover_page(self):
        blocks = [
            {"type": BlockType.DOC_TITLE, "bbox": [100, 100, 700, 200], "lines": [{"spans": [{"content": "My Document Title"}]}]},
            {"type": BlockType.TEXT, "bbox": [100, 300, 700, 400], "lines": [{"spans": [{"content": "Author Name"}]}]},
        ]
        page_info = self._make_page_info(blocks)
        self.assertEqual(infer_page_type(page_info, 0, 10), PageType.COVER)

    def test_back_cover_page(self):
        blocks = [
            {"type": BlockType.IMAGE, "bbox": [100, 100, 700, 200], "lines": []},
        ]
        page_info = self._make_page_info(blocks)
        self.assertEqual(infer_page_type(page_info, 9, 10), PageType.BACK_COVER)

    def test_toc_page(self):
        blocks = [
            {"type": BlockType.INDEX, "bbox": [100, 100 + i * 50, 700, 200 + i * 50], "lines": [{"spans": [{"content": f"Chapter {i}"}]}]}
            for i in range(5)
        ]
        blocks.append({"type": BlockType.TEXT, "bbox": [100, 350, 700, 400], "lines": [{"spans": [{"content": "Other"}]}]})
        page_info = self._make_page_info(blocks)
        self.assertEqual(infer_page_type(page_info, 2, 10), PageType.TOC)

    def test_reference_page(self):
        blocks = [
            {"type": BlockType.REF_TEXT, "bbox": [100, 100 + i * 30, 700, 200 + i * 30], "lines": [{"spans": [{"content": f"Ref {i}"}]}]}
            for i in range(6)
        ]
        page_info = self._make_page_info(blocks)
        self.assertEqual(infer_page_type(page_info, 8, 10), PageType.REFERENCE)

    def test_chapter_start_page(self):
        blocks = [
            {"type": BlockType.DOC_TITLE, "bbox": [100, 50, 700, 150], "lines": [{"spans": [{"content": "Chapter 1"}]}]},
            {"type": BlockType.TEXT, "bbox": [100, 200, 700, 400], "lines": [{"spans": [{"content": "Introduction text..."}]}]},
            {"type": BlockType.TEXT, "bbox": [100, 450, 700, 600], "lines": [{"spans": [{"content": "More text..."}]}]},
        ]
        page_info = self._make_page_info(blocks)
        self.assertEqual(infer_page_type(page_info, 3, 20), PageType.CHAPTER_START)

    def test_copyright_page(self):
        blocks = [
            {"type": BlockType.TEXT, "bbox": [100, 100, 700, 900], "lines": [{"spans": [{"content": "Copyright 2024. ISBN 123-456."}]}]},
        ]
        page_info = self._make_page_info(blocks)
        self.assertEqual(infer_page_type(page_info, 1, 10), PageType.COPYRIGHT)

    def test_image_dominant_page(self):
        # Page 800x1000, image covers most of the page
        blocks = [
            {"type": BlockType.IMAGE, "bbox": [50, 50, 750, 950], "lines": []},
        ]
        page_info = self._make_page_info(blocks)
        self.assertEqual(infer_page_type(page_info, 5, 10), PageType.IMAGE_DOMINANT)

    def test_body_page(self):
        # Body page: multiple text blocks, no title at top, no special keywords
        blocks = [
            {"type": BlockType.TEXT, "bbox": [100, 100, 700, 200], "lines": [{"spans": [{"content": "Normal paragraph one with enough content"}]}]},
            {"type": BlockType.TEXT, "bbox": [100, 300, 700, 400], "lines": [{"spans": [{"content": "Another paragraph two with more content"}]}]},
            {"type": BlockType.TEXT, "bbox": [100, 500, 700, 600], "lines": [{"spans": [{"content": "Third paragraph continues the discussion"}]}]},
        ]
        page_info = self._make_page_info(blocks)
        self.assertEqual(infer_page_type(page_info, 5, 20), PageType.BODY)

    def test_glossary_page(self):
        blocks = [
            {"type": BlockType.TITLE, "bbox": [100, 50, 700, 100], "lines": [{"spans": [{"content": "术语表 Glossary"}]}]},
            {"type": BlockType.TEXT, "bbox": [100, 150, 700, 900], "lines": [{"spans": [{"content": "Term A: Definition A"}]}]},
        ]
        page_info = self._make_page_info(blocks)
        self.assertEqual(infer_page_type(page_info, 15, 20), PageType.GLOSSARY)


class TestClassifyAllPages(unittest.TestCase):
    def test_classify_all_pages_modifies_in_place(self):
        pdf_info_list = [
            {
                "preproc_blocks": [
                    {"type": BlockType.DOC_TITLE, "bbox": [100, 100, 700, 200], "lines": [{"spans": [{"content": "Title"}]}]},
                ],
                "page_size": [800, 1000],
            },
            {
                "preproc_blocks": [
                    {"type": BlockType.TEXT, "bbox": [100, 100, 700, 200], "lines": [{"spans": [{"content": "Body text with enough content to not be sparse"}]}]},
                    {"type": BlockType.TEXT, "bbox": [100, 300, 700, 400], "lines": [{"spans": [{"content": "More body content here"}]}]},
                    {"type": BlockType.TEXT, "bbox": [100, 500, 700, 600], "lines": [{"spans": [{"content": "Even more content"}]}]},
                    {"type": BlockType.TEXT, "bbox": [100, 700, 700, 800], "lines": [{"spans": [{"content": "Fourth paragraph"}]}]},
                ],
                "page_size": [800, 1000],
            },
            {
                "preproc_blocks": [
                    {"type": BlockType.TEXT, "bbox": [100, 100, 700, 200], "lines": [{"spans": [{"content": "Last page content"}]}]},
                ],
                "page_size": [800, 1000],
            },
        ]
        classify_all_pages(pdf_info_list)
        self.assertIn("page_type", pdf_info_list[0])
        self.assertIn("page_type", pdf_info_list[1])
        self.assertIn("page_type", pdf_info_list[2])
        self.assertEqual(pdf_info_list[0]["page_type"], PageType.COVER)
        self.assertEqual(pdf_info_list[1]["page_type"], PageType.BODY)
        self.assertEqual(pdf_info_list[2]["page_type"], PageType.BACK_COVER)


class TestTocLineDensityEnhancement(unittest.TestCase):
    """Phase A': TOC 行密度 + 区间检测增强的单测。"""

    def test_count_toc_lines_in_page(self):
        blocks = [
            {"lines": [{"spans": [{"content": "7.3 工业4.0下液压故障诊断与健康管理 …… 372"}]}]},
            {"lines": [{"spans": [{"content": "7.3.1 液压智能故障诊断 …… 373"}]}]},
            {"lines": [{"spans": [{"content": "正文普通段落，不含页码"}]}]},
        ]
        page = {"preproc_blocks": blocks}
        self.assertEqual(_count_toc_lines_in_page(page), 2)

    def test_count_toc_lines_ignores_decimal_fragment(self):
        # "7.3 工业4.0" 的小数点不得被误判为引导符（Phase 0 Q3 回归）
        blocks = [{"lines": [{"spans": [{"content": "7.3 工业4.0"}]}]}]
        self.assertEqual(_count_toc_lines_in_page({"preproc_blocks": blocks}), 0)

    def test_detect_toc_page_set_keeps_dominant_range(self):
        def page(toc_lines, header=""):
            content = "".join(f"{i}.1 标题 …… {i*10}\n" for i in range(toc_lines))
            if header:
                content = header + "\n" + content
            return {"preproc_blocks": [{"lines": [{"spans": [{"content": content}]}]}]}

        pdf_info_list = []
        # 前 11 页：普通内容
        for _ in range(11):
            pdf_info_list.append({"preproc_blocks": [{"lines": [{"spans": [{"content": "普通内容"}]}]}]})
        # 目录区间 12-22：每页 30 行 TOC（总 330 行）
        for _ in range(11):
            pdf_info_list.append(page(30))
        # 正文 50 页
        for _ in range(50):
            pdf_info_list.append({"preproc_blocks": [{"lines": [{"spans": [{"content": "正文内容"}]}]}]})
        # 稀疏"索引"区间：每页 5 行（总 50 行 < 330*0.2=66），应被主导区间排除
        for _ in range(10):
            pdf_info_list.append(page(5))

        toc = _detect_toc_page_set(pdf_info_list)
        self.assertEqual(toc, set(range(12, 23)))

    def test_detect_toc_page_set_toc_header_fallback(self):
        # 独立简短目录页：仅 2 行 TOC + "目 录" 页眉 → 兜底纳入
        page = {
            "preproc_blocks": [
                {"lines": [{"spans": [{"content": "目 录\n1.1 标题 …… 10\n1.2 标题 …… 20"}]}]}
            ]
        }
        pdf_info_list = [page]
        toc = _detect_toc_page_set(pdf_info_list)
        self.assertEqual(toc, {1})

    def test_classify_all_pages_detects_toc_via_density(self):
        content = "".join(f"{i}.1 标题 …… {i*10}\n" for i in range(8))
        pdf_info_list = []
        for _ in range(11):
            pdf_info_list.append({"preproc_blocks": [{"lines": [{"spans": [{"content": "正文"}]}]}], "page_size": [800, 1000]})
        for _ in range(5):
            pdf_info_list.append({"preproc_blocks": [{"lines": [{"spans": [{"content": content}]}]}], "page_size": [800, 1000]})
        # 尾部补普通页，避免 TOC 页落在末页被 back_cover 截胡
        for _ in range(2):
            pdf_info_list.append({"preproc_blocks": [{"lines": [{"spans": [{"content": "结尾内容"}]}]}], "page_size": [800, 1000]})
        classify_all_pages(pdf_info_list)
        for i in range(11, 16):
            self.assertEqual(pdf_info_list[i]["page_type"], PageType.TOC)


class TestPrefaceCoverEnhancement(unittest.TestCase):
    """Phase A' 延伸：PREFACE 类别 + 封面放宽（居中大标题 + 前置页边界）。"""

    def test_preface_page(self):
        # 前置页（正文开始前，非封面/版权/目录）→ preface
        blocks = [
            {"type": BlockType.TITLE, "bbox": [200, 50, 240, 80], "lines": [{"spans": [{"content": "序"}]}]},
            {"type": BlockType.TEXT, "bbox": [50, 100, 400, 200], "lines": [{"spans": [{"content": "工业 4.0 是信息技术..."}]}]},
        ]
        page_info = {"preproc_blocks": blocks, "page_size": [500, 700]}
        self.assertEqual(infer_page_type(page_info, 5, 20, body_start=12), PageType.PREFACE)

    def test_cover_front_matter_not_first_page(self):
        # 重复扉页（非首页）：居中大标题 + 稀疏 + 无表格 → cover
        blocks = [
            {"type": BlockType.TITLE, "bbox": [150, 100, 350, 200], "lines": [{"spans": [{"content": "现代液压气动手册 Modern Pneumatics"}]}]},
            {"type": BlockType.TEXT, "bbox": [200, 300, 300, 320], "lines": [{"spans": [{"content": "第1卷"}]}]},
        ]
        page_info = {"preproc_blocks": blocks, "page_size": [500, 700]}
        self.assertEqual(infer_page_type(page_info, 3, 20, body_start=12), PageType.COVER)

    def test_toc_page_not_cover(self):
        # 目录页（在 toc_pages 内）不得判为 cover，即使有居中章节标题
        blocks = [
            {"type": BlockType.TITLE, "bbox": [150, 100, 350, 200], "lines": [{"spans": [{"content": "第1篇 液压技术基础"}]}]},
            {"type": BlockType.TEXT, "bbox": [50, 200, 400, 600], "lines": [{"spans": [{"content": "第1章 液压理论与工作介质\n基础 …… 3\n1.1 液压流体力学常用公式 …… 5"}]}]},
        ]
        page_info = {"preproc_blocks": blocks, "page_size": [500, 700]}
        self.assertEqual(
            infer_page_type(page_info, 11, 20, toc_pages={12}, body_start=22),
            PageType.TOC,
        )

    def test_cover_excludes_table_page(self):
        # 含表格块的页面不得判为 cover（如 手册总览 层级表 → preface）
        blocks = [
            {"type": BlockType.TITLE, "bbox": [150, 50, 350, 80], "lines": [{"spans": [{"content": "《手册》总览"}]}]},
            {"type": BlockType.TABLE, "bbox": [30, 90, 220, 600], "lines": []},
            {"type": BlockType.TABLE, "bbox": [240, 90, 460, 590], "lines": []},
        ]
        page_info = {"preproc_blocks": blocks, "page_size": [500, 700]}
        self.assertEqual(infer_page_type(page_info, 2, 20, body_start=12), PageType.PREFACE)


if __name__ == "__main__":
    unittest.main()