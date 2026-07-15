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


if __name__ == "__main__":
    unittest.main()