# Copyright (c) Opendatalab. All rights reserved.
import unittest

from mineru.backend.utils.para_block_utils import (
    _assign_uuid_to_block,
    _build_index_map_recursively,
    _collect_block_ids_from_block,
    assign_block_uuids,
)


class TestAssignUuidToBlock(unittest.TestCase):
    """测试递归 UUID 分配功能。"""

    def test_single_block(self):
        block = {"type": "text", "index": 0}
        _assign_uuid_to_block(block)
        self.assertIn("block_id", block)
        self.assertTrue(isinstance(block["block_id"], str))
        self.assertEqual(len(block["block_id"]), 36)  # UUID v4 format

    def test_block_with_one_level_nesting(self):
        block = {
            "type": "text",
            "index": 0,
            "blocks": [{"type": "text", "index": 1}],
        }
        _assign_uuid_to_block(block)
        self.assertIn("block_id", block)
        self.assertIn("block_id", block["blocks"][0])
        self.assertNotEqual(block["block_id"], block["blocks"][0]["block_id"])

    def test_block_with_deep_nesting(self):
        """测试三层嵌套（深层嵌套场景）。"""
        block = {
            "type": "text",
            "index": 0,
            "blocks": [
                {
                    "type": "text",
                    "index": 1,
                    "blocks": [
                        {"type": "text", "index": 2}
                    ],
                }
            ],
        }
        _assign_uuid_to_block(block)
        self.assertIn("block_id", block)
        self.assertIn("block_id", block["blocks"][0])
        self.assertIn("block_id", block["blocks"][0]["blocks"][0])

        # 验证所有 UUID 互不相同
        uuids = [
            block["block_id"],
            block["blocks"][0]["block_id"],
            block["blocks"][0]["blocks"][0]["block_id"],
        ]
        self.assertEqual(len(uuids), len(set(uuids)))

    def test_block_without_blocks_key(self):
        block = {"type": "text", "index": 0}
        _assign_uuid_to_block(block)
        self.assertIn("block_id", block)


class TestBuildIndexMapRecursively(unittest.TestCase):
    """测试递归构建 index -> block_id 映射。"""

    def test_single_block_with_index(self):
        block = {"type": "text", "index": 0, "block_id": "uuid-0"}
        index_map = {}
        _build_index_map_recursively(block, index_map)
        self.assertEqual(index_map[0], "uuid-0")

    def test_single_block_without_index(self):
        block = {"type": "text", "block_id": "uuid-0"}
        index_map = {}
        _build_index_map_recursively(block, index_map)
        self.assertEqual(len(index_map), 0)

    def test_nested_blocks_with_indices(self):
        block = {
            "type": "text",
            "index": 0,
            "block_id": "uuid-0",
            "blocks": [
                {"type": "text", "index": 1, "block_id": "uuid-1"},
                {"type": "text", "index": 2, "block_id": "uuid-2"},
            ],
        }
        index_map = {}
        _build_index_map_recursively(block, index_map)
        self.assertEqual(index_map[0], "uuid-0")
        self.assertEqual(index_map[1], "uuid-1")
        self.assertEqual(index_map[2], "uuid-2")

    def test_deep_nested_blocks(self):
        """测试三层嵌套的 index 映射。"""
        block = {
            "type": "text",
            "index": 0,
            "block_id": "uuid-0",
            "blocks": [
                {
                    "type": "text",
                    "index": 1,
                    "block_id": "uuid-1",
                    "blocks": [
                        {"type": "text", "index": 2, "block_id": "uuid-2"}
                    ],
                }
            ],
        }
        index_map = {}
        _build_index_map_recursively(block, index_map)
        self.assertEqual(index_map[0], "uuid-0")
        self.assertEqual(index_map[1], "uuid-1")
        self.assertEqual(index_map[2], "uuid-2")


class TestCollectBlockIdsFromBlock(unittest.TestCase):
    """测试递归收集 block_ids。"""

    def test_single_block_with_matching_index(self):
        block = {"type": "text", "index": 0}
        index_map = {0: "uuid-0"}
        block_ids = []
        _collect_block_ids_from_block(block, index_map, block_ids)
        self.assertEqual(block_ids, ["uuid-0"])

    def test_single_block_without_matching_index(self):
        block = {"type": "text", "index": 5}
        index_map = {0: "uuid-0"}
        block_ids = []
        _collect_block_ids_from_block(block, index_map, block_ids)
        self.assertEqual(block_ids, [])

    def test_nested_blocks_collect_multiple_ids(self):
        block = {
            "type": "text",
            "index": 0,
            "blocks": [
                {"type": "text", "index": 1},
                {"type": "text", "index": 2},
            ],
        }
        index_map = {0: "uuid-0", 1: "uuid-1", 2: "uuid-2"}
        block_ids = []
        _collect_block_ids_from_block(block, index_map, block_ids)
        self.assertIn("uuid-0", block_ids)
        self.assertIn("uuid-1", block_ids)
        self.assertIn("uuid-2", block_ids)

    def test_no_duplicate_ids(self):
        """当嵌套 block 的 index 与父 block 相同时，不重复添加。"""
        block = {
            "type": "text",
            "index": 0,
            "blocks": [
                {"type": "text", "index": 0},
            ],
        }
        index_map = {0: "uuid-0"}
        block_ids = []
        _collect_block_ids_from_block(block, index_map, block_ids)
        self.assertEqual(block_ids, ["uuid-0"])


class TestAssignBlockUuids(unittest.TestCase):
    """测试完整的 assign_block_uuids 流程。"""

    def test_empty_pdf_info_list(self):
        assign_block_uuids([])
        # Should not raise any errors

    def test_page_with_empty_blocks(self):
        pdf_info_list = [
            {
                "page_idx": 0,
                "preproc_blocks": [],
                "para_blocks": [],
                "discarded_blocks": [],
            }
        ]
        assign_block_uuids(pdf_info_list)
        # Should not raise any errors

    def test_basic_flow(self):
        """测试基本流程：preproc/para/discarded 各一个 block。"""
        pdf_info_list = [
            {
                "page_idx": 0,
                "preproc_blocks": [{"type": "text", "index": 0}],
                "para_blocks": [{"type": "text", "index": 0}],
                "discarded_blocks": [{"type": "text", "index": 1}],
            }
        ]
        assign_block_uuids(pdf_info_list)

        page = pdf_info_list[0]

        # 验证 preproc_blocks 有 block_id
        self.assertIn("block_id", page["preproc_blocks"][0])

        # 验证 para_blocks 有 block_id 和 block_ids
        self.assertIn("block_id", page["para_blocks"][0])
        self.assertIn("block_ids", page["para_blocks"][0])
        self.assertIn(
            page["preproc_blocks"][0]["block_id"],
            page["para_blocks"][0]["block_ids"],
        )

        # 验证 discarded_blocks 有 block_id
        self.assertIn("block_id", page["discarded_blocks"][0])

        # 验证所有 UUID 唯一
        all_uuids = (
            [page["preproc_blocks"][0]["block_id"]]
            + [page["para_blocks"][0]["block_id"]]
            + [page["discarded_blocks"][0]["block_id"]]
        )
        self.assertEqual(len(all_uuids), len(set(all_uuids)))

    def test_nested_blocks_in_preproc(self):
        """测试 preproc_blocks 中有嵌套 blocks 的场景。"""
        pdf_info_list = [
            {
                "page_idx": 0,
                "preproc_blocks": [
                    {
                        "type": "text",
                        "index": 0,
                        "blocks": [
                            {"type": "text", "index": 1},
                            {
                                "type": "text",
                                "index": 2,
                                "blocks": [
                                    {"type": "text", "index": 3}
                                ],
                            },
                        ],
                    }
                ],
                "para_blocks": [
                    {
                        "type": "text",
                        "index": 0,
                        "blocks": [
                            {"type": "text", "index": 2}
                        ],
                    }
                ],
                "discarded_blocks": [],
            }
        ]
        assign_block_uuids(pdf_info_list)

        page = pdf_info_list[0]
        preproc = page["preproc_blocks"][0]

        # 验证所有嵌套 block 都有 block_id
        self.assertIn("block_id", preproc)
        self.assertIn("block_id", preproc["blocks"][0])
        self.assertIn("block_id", preproc["blocks"][1])
        self.assertIn("block_id", preproc["blocks"][1]["blocks"][0])

        # 验证 para_blocks 的 block_ids 正确引用
        para = page["para_blocks"][0]
        self.assertIn("block_ids", para)
        # index=0 和 index=2 都应在 block_ids 中
        self.assertIn(preproc["block_id"], para["block_ids"])
        self.assertIn(preproc["blocks"][1]["block_id"], para["block_ids"])

    def test_multiple_pages(self):
        """测试多页场景。"""
        pdf_info_list = [
            {
                "page_idx": 0,
                "preproc_blocks": [{"type": "text", "index": 0}],
                "para_blocks": [{"type": "text", "index": 0}],
                "discarded_blocks": [],
            },
            {
                "page_idx": 1,
                "preproc_blocks": [{"type": "text", "index": 0}],
                "para_blocks": [{"type": "text", "index": 0}],
                "discarded_blocks": [],
            },
        ]
        assign_block_uuids(pdf_info_list)

        # 每页独立处理，index=0 在不同页会生成不同的 UUID
        self.assertNotEqual(
            pdf_info_list[0]["preproc_blocks"][0]["block_id"],
            pdf_info_list[1]["preproc_blocks"][0]["block_id"],
        )

    def test_para_block_without_index(self):
        """测试 para_blocks 中的 block 没有 index 字段时不添加 block_ids。"""
        pdf_info_list = [
            {
                "page_idx": 0,
                "preproc_blocks": [{"type": "text", "index": 0}],
                "para_blocks": [{"type": "text"}],  # 无 index
                "discarded_blocks": [],
            }
        ]
        assign_block_uuids(pdf_info_list)

        page = pdf_info_list[0]
        self.assertIn("block_id", page["para_blocks"][0])
        self.assertNotIn("block_ids", page["para_blocks"][0])


if __name__ == "__main__":
    unittest.main()