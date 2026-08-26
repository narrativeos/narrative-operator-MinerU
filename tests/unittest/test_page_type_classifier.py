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
    _page_is_magazine_toc,
    _count_magazine_toc_lines_in_page,
    _is_garbled_block_text,
    remove_garbled_blocks,
)
from mineru.utils.enum_class import BlockType, PageType


def _assert_page_type(result, expected_primary, expected_secondary=None):
    """Helper to assert page type result (primary, secondary) tuple."""
    assert isinstance(result, tuple), f"Expected tuple, got {type(result)}: {result}"
    primary, secondary = result
    assert primary == expected_primary, f"Expected primary={expected_primary}, got {primary}"
    assert secondary == expected_secondary, f"Expected secondary={expected_secondary}, got {secondary}"


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
        result = infer_page_type(page_info, 0, 1)
        _assert_page_type(result, PageType.BLANK)

    def test_cover_page(self):
        blocks = [
            {"type": BlockType.DOC_TITLE, "bbox": [100, 100, 700, 200], "lines": [{"spans": [{"content": "My Document Title"}]}]},
            {"type": BlockType.TEXT, "bbox": [100, 300, 700, 400], "lines": [{"spans": [{"content": "Author Name"}]}]},
        ]
        page_info = self._make_page_info(blocks)
        result = infer_page_type(page_info, 0, 10)
        _assert_page_type(result, PageType.COVER)

    def test_back_cover_page(self):
        blocks = [
            {"type": BlockType.IMAGE, "bbox": [100, 100, 700, 200], "lines": []},
        ]
        page_info = self._make_page_info(blocks)
        result = infer_page_type(page_info, 9, 10)
        _assert_page_type(result, PageType.BACK_COVER)

    def test_toc_page(self):
        blocks = [
            {"type": BlockType.INDEX, "bbox": [100, 100 + i * 50, 700, 200 + i * 50], "lines": [{"spans": [{"content": f"Chapter {i}"}]}]}
            for i in range(5)
        ]
        blocks.append({"type": BlockType.TEXT, "bbox": [100, 350, 700, 400], "lines": [{"spans": [{"content": "Other"}]}]})
        page_info = self._make_page_info(blocks)
        result = infer_page_type(page_info, 2, 10)
        _assert_page_type(result, PageType.TOC)

    def test_reference_page(self):
        blocks = [
            {"type": BlockType.REF_TEXT, "bbox": [100, 100 + i * 30, 700, 200 + i * 30], "lines": [{"spans": [{"content": f"Ref {i}"}]}]}
            for i in range(6)
        ]
        page_info = self._make_page_info(blocks)
        result = infer_page_type(page_info, 8, 10)
        _assert_page_type(result, PageType.REFERENCE)

    def test_chapter_start_page(self):
        blocks = [
            {"type": BlockType.DOC_TITLE, "bbox": [100, 50, 700, 150], "lines": [{"spans": [{"content": "Chapter 1"}]}]},
            {"type": BlockType.TEXT, "bbox": [100, 200, 700, 400], "lines": [{"spans": [{"content": "Introduction text..."}]}]},
            {"type": BlockType.TEXT, "bbox": [100, 450, 700, 600], "lines": [{"spans": [{"content": "More text..."}]}]},
        ]
        page_info = self._make_page_info(blocks)
        result = infer_page_type(page_info, 3, 20)
        _assert_page_type(result, PageType.CHAPTER_START)

    def test_copyright_page(self):
        blocks = [
            {"type": BlockType.TEXT, "bbox": [100, 100, 700, 900], "lines": [{"spans": [{"content": "Copyright 2024. ISBN 123-456."}]}]},
        ]
        page_info = self._make_page_info(blocks)
        result = infer_page_type(page_info, 1, 10)
        _assert_page_type(result, PageType.COPYRIGHT)

    def test_image_dominant_page(self):
        # Page 800x1000, image covers most of the page
        blocks = [
            {"type": BlockType.IMAGE, "bbox": [50, 50, 750, 950], "lines": []},
        ]
        page_info = self._make_page_info(blocks)
        result = infer_page_type(page_info, 5, 10)
        _assert_page_type(result, PageType.IMAGE_DOMINANT)

    def test_body_page(self):
        # Body page: multiple text blocks, no title at top, no special keywords
        blocks = [
            {"type": BlockType.TEXT, "bbox": [100, 100, 700, 200], "lines": [{"spans": [{"content": "Normal paragraph one with enough content"}]}]},
            {"type": BlockType.TEXT, "bbox": [100, 300, 700, 400], "lines": [{"spans": [{"content": "Another paragraph two with more content"}]}]},
            {"type": BlockType.TEXT, "bbox": [100, 500, 700, 600], "lines": [{"spans": [{"content": "Third paragraph continues the discussion"}]}]},
        ]
        page_info = self._make_page_info(blocks)
        result = infer_page_type(page_info, 5, 20)
        _assert_page_type(result, PageType.BODY)

    def test_glossary_page(self):
        blocks = [
            {"type": BlockType.TITLE, "bbox": [100, 50, 700, 100], "lines": [{"spans": [{"content": "术语表 Glossary"}]}]},
            {"type": BlockType.TEXT, "bbox": [100, 150, 700, 900], "lines": [{"spans": [{"content": "Term A: Definition A"}]}]},
        ]
        page_info = self._make_page_info(blocks)
        result = infer_page_type(page_info, 15, 20)
        _assert_page_type(result, PageType.GLOSSARY)


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
        result = infer_page_type(page_info, 5, 20, body_start=12)
        _assert_page_type(result, PageType.PREFACE)

    def test_cover_front_matter_not_first_page(self):
        # 重复扉页（非首页）：居中大标题 + 稀疏 + 无表格 → cover
        blocks = [
            {"type": BlockType.TITLE, "bbox": [150, 100, 350, 200], "lines": [{"spans": [{"content": "现代液压气动手册 Modern Pneumatics"}]}]},
            {"type": BlockType.TEXT, "bbox": [200, 300, 300, 320], "lines": [{"spans": [{"content": "第1卷"}]}]},
        ]
        page_info = {"preproc_blocks": blocks, "page_size": [500, 700]}
        result = infer_page_type(page_info, 3, 20, body_start=12)
        _assert_page_type(result, PageType.COVER)

    def test_toc_page_not_cover(self):
        # 目录页（在 toc_pages 内）不得判为 cover，即使有居中章节标题
        blocks = [
            {"type": BlockType.TITLE, "bbox": [150, 100, 350, 200], "lines": [{"spans": [{"content": "第1篇 液压技术基础"}]}]},
            {"type": BlockType.TEXT, "bbox": [50, 200, 400, 600], "lines": [{"spans": [{"content": "第1章 液压理论与工作介质\n基础 …… 3\n1.1 液压流体力学常用公式 …… 5"}]}]},
        ]
        page_info = {"preproc_blocks": blocks, "page_size": [500, 700]}
        result = infer_page_type(page_info, 11, 20, toc_pages={12}, body_start=22)
        _assert_page_type(result, PageType.TOC)

    def test_cover_excludes_table_page(self):
        # 含表格块的页面不得判为 cover（如 手册总览 层级表 → preface）
        blocks = [
            {"type": BlockType.TITLE, "bbox": [150, 50, 350, 80], "lines": [{"spans": [{"content": "《手册》总览"}]}]},
            {"type": BlockType.TABLE, "bbox": [30, 90, 220, 600], "lines": []},
            {"type": BlockType.TABLE, "bbox": [240, 90, 460, 590], "lines": []},
        ]
        page_info = {"preproc_blocks": blocks, "page_size": [500, 700]}
        result = infer_page_type(page_info, 2, 20, body_start=12)
        _assert_page_type(result, PageType.PREFACE)


class TestCopyrightColophonStructuredSignal(unittest.TestCase):
    """版权/版本记录页改为"结构化元数据信号"判定的单测。

    背景：出版类书籍正文中"版权/著作权/印刷/开本"等通用词高频出现，
    仅凭关键词会把大量正文页误判为 copyright/colophon（《出版学基础》正文
    曾出现 67 版权 + 140 版本记录误判）。现要求出现结构化元数据信号才判定。
    """

    def _make_page_info(self, blocks, page_size=(800, 1000)):
        return {"preproc_blocks": blocks, "page_size": list(page_size)}

    def test_body_page_mentioning_copyright_word(self):
        # 正文中"版权/著作权/版权所有"高频出现，但无 ISBN/CIP/定价/© → 仍为正文
        blocks = [
            {"type": BlockType.TEXT, "bbox": [100, 100, 700, 300], "lines": [{"spans": [{"content": "版权贸易是出版业的重要组成部分，版权保护意识日益增强。"}]}]},
            {"type": BlockType.TEXT, "bbox": [100, 350, 700, 550], "lines": [{"spans": [{"content": "著作权法对出版物的保护范围作出了明确规定，出版单位应当尊重著作权。"}]}]},
            {"type": BlockType.TEXT, "bbox": [100, 600, 700, 800], "lines": [{"spans": [{"content": "版权所有是出版合同中的常见条款，涉及版权归属与利益分配。"}]}]},
        ]
        page_info = self._make_page_info(blocks)
        result = infer_page_type(page_info, 5, 20)
        _assert_page_type(result, PageType.BODY)

    def test_body_page_mentioning_printing_words(self):
        # 正文中"印刷/开本/印张/字数"以散文形式出现（非"标签: 值"）→ 仍为正文
        blocks = [
            {"type": BlockType.TEXT, "bbox": [100, 100, 700, 300], "lines": [{"spans": [{"content": "印刷技术是出版业的基础，平版印刷是最常用的印刷方式。"}]}]},
            {"type": BlockType.TEXT, "bbox": [100, 350, 700, 550], "lines": [{"spans": [{"content": "开本的设计影响图书的版式与阅读体验，印张数决定了用纸量。"}]}]},
            {"type": BlockType.TEXT, "bbox": [100, 600, 700, 800], "lines": [{"spans": [{"content": "字数与印张共同影响图书的成本核算，这是出版管理的重要内容。"}]}]},
        ]
        page_info = self._make_page_info(blocks)
        result = infer_page_type(page_info, 5, 20)
        _assert_page_type(result, PageType.BODY)

    def test_real_copyright_page(self):
        # 真实版权页：含 ISBN + CIP + 定价 等结构化元数据 → copyright
        blocks = [
            {"type": BlockType.TEXT, "bbox": [100, 100, 700, 900], "lines": [{"spans": [{"content": "图书在版编目（CIP）数据\n出版学基础／方卿等编著．－武汉：武汉大学出版社，2020.1\nISBN 978-7-307-20000-0\n出版发行 武汉大学出版社\n地址 湖北省武汉市珞珈山 邮编 430072\n定价 68.00元"}]}]},
        ]
        page_info = self._make_page_info(blocks)
        result = infer_page_type(page_info, 1, 10)
        _assert_page_type(result, PageType.COPYRIGHT)

    def test_copyright_isbn_only(self):
        # 仅含 ISBN（后跟数字）也足以判定为版权页
        blocks = [
            {"type": BlockType.TEXT, "bbox": [100, 100, 700, 900], "lines": [{"spans": [{"content": "ISBN 978-7-307-20000-0"}]}]},
        ]
        page_info = self._make_page_info(blocks)
        result = infer_page_type(page_info, 1, 10)
        _assert_page_type(result, PageType.COPYRIGHT)

    def test_real_colophon_page(self):
        # 真实版本记录页：含 版次/印次/印数/开本/印张/字数 等"标签: 值"元数据 → colophon
        blocks = [
            {"type": BlockType.TEXT, "bbox": [100, 100, 700, 900], "lines": [{"spans": [{"content": "版次 2020年1月第1版\n印次 2020年1月第1次印刷\n印数 1-5000册\n开本 787mm×1092mm 1/16\n印张 15.5\n字数 300千字"}]}]},
        ]
        page_info = self._make_page_info(blocks)
        result = infer_page_type(page_info, 1, 10)
        _assert_page_type(result, PageType.COLOPHON)

    def test_colophon_needs_multiple_fields(self):
        # 仅 1-2 个"标签: 值"字段不足以判定为版本记录页 → 正文
        blocks = [
            {"type": BlockType.TEXT, "bbox": [100, 100, 700, 300], "lines": [{"spans": [{"content": "本书开本 787mm，印张 15.5。"}]}]},
            {"type": BlockType.TEXT, "bbox": [100, 350, 700, 550], "lines": [{"spans": [{"content": "这是关于图书装帧设计的正文段落，讨论版式与纸张的选择。"}]}]},
            {"type": BlockType.TEXT, "bbox": [100, 600, 700, 800], "lines": [{"spans": [{"content": "继续阅读正文内容，了解出版流程的各个环节。"}]}]},
        ]
        page_info = self._make_page_info(blocks)
        result = infer_page_type(page_info, 5, 20)
        _assert_page_type(result, PageType.BODY)

    def test_magazine_toc_with_copyright(self):
        # 杂志目录页 + 版权信息（ISSN）→ 主类型 TOC，次要类型 COPYRIGHT（保留既有行为）
        blocks = [
            {"type": BlockType.TITLE, "bbox": [100, 50, 700, 100], "lines": [{"spans": [{"content": "专题 Feature"}]}]},
            {"type": BlockType.TEXT, "bbox": [100, 150, 700, 500], "lines": [{"spans": [{"content": "010 京沪高铁让旅客出行更美好\n012 铁路客票便民惠旅新升级\n014 高铁上看风景好\n016 高邮活虾鲜\n018 山城步道游"}]}]},
            {"type": BlockType.TEXT, "bbox": [100, 700, 700, 900], "lines": [{"spans": [{"content": "ISSN: 1000-0000\n印刷单位：北京盛通印刷股份有限公司"}]}]},
        ]
        page_info = self._make_page_info(blocks)
        result = infer_page_type(page_info, 2, 10)
        _assert_page_type(result, PageType.TOC, PageType.COPYRIGHT)


class TestGarbledBlockRemoval(unittest.TestCase):
    """乱码 block 识别与删除（OCR 误识别的纯符号装饰符）。"""

    def _make_block(self, content, btype=BlockType.TITLE):
        return {
            "type": btype,
            "bbox": [100, 100, 300, 120],
            "lines": [{"spans": [{"content": content}]}],
        }

    def test_is_garbled_horizontal(self):
        # 横向乱码：! " # $ %
        self.assertTrue(_is_garbled_block_text('! " # $ %'))

    def test_is_garbled_vertical(self):
        # 纵向乱码：! " # $ % 各占一行
        self.assertTrue(_is_garbled_block_text('!\r\n"\r\n#\r\n$\r\n%'))

    def test_not_garbled_chinese(self):
        self.assertFalse(_is_garbled_block_text("出版学基础理论"))

    def test_not_garbled_english(self):
        self.assertFalse(_is_garbled_block_text("Copyright 2024"))

    def test_not_garbled_page_number(self):
        # 页码（纯数字）不应被删
        self.assertFalse(_is_garbled_block_text("123"))

    def test_not_garbled_short_symbols(self):
        # 去空白后长度 < 3 的符号串不视为乱码
        self.assertFalse(_is_garbled_block_text('!'))
        self.assertFalse(_is_garbled_block_text('"'))
        self.assertFalse(_is_garbled_block_text('! '))
        self.assertFalse(_is_garbled_block_text("   "))

    def test_remove_garbled_blocks(self):
        pdf_info = [
            {
                "preproc_blocks": [
                    self._make_block("第一章 出版学", BlockType.TITLE),
                    self._make_block('! " # $ %', BlockType.TITLE),
                    self._make_block("正文内容……", BlockType.TEXT),
                ]
            },
            {
                "preproc_blocks": [
                    self._make_block('!\r\n"\r\n#\r\n$\r\n%', BlockType.TITLE),
                    self._make_block("第二节 出版活动", BlockType.TITLE),
                ]
            },
        ]
        removed = remove_garbled_blocks(pdf_info)
        self.assertEqual(removed, 2)
        # 第一页保留 2 个正常 block
        self.assertEqual(len(pdf_info[0]["preproc_blocks"]), 2)
        # 第二页保留 1 个正常 block
        self.assertEqual(len(pdf_info[1]["preproc_blocks"]), 1)
        # 乱码 block 已被删除
        all_texts = [
            "".join(sp["content"] for l in b["lines"] for sp in l["spans"])
            for page in pdf_info
            for b in page["preproc_blocks"]
        ]
        self.assertNotIn('! " # $ %', all_texts)

    def test_remove_garbled_blocks_empty(self):
        self.assertEqual(remove_garbled_blocks([]), 0)


if __name__ == "__main__":
    unittest.main()