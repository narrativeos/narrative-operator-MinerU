# Copyright (c) Opendatalab. All rights reserved.
"""Unit tests for block traceability utilities (MinerU 4.0 raw model_list)."""
import unittest

from mineru.utils.block_trace import (
    assign_block_uuids_to_model_list,
    build_block_id_map,
    strip_block_ids_from_model_list,
)


def _make_model_list() -> list[list[dict]]:
    """构造 4.0 格式的 raw model_list（2 页）。"""
    return [
        [
            {"type": "text", "index": 0, "bbox": [0.1, 0.1, 0.5, 0.2],
             "content": [{"type": "text", "content": "hello"}],
             "lines": [{"bbox": [0.1, 0.1, 0.5, 0.2]}]},
            {"type": "equation", "index": 1, "bbox": [0.3, 0.5, 0.7, 0.6],
             "content": "\\frac{a}{b}",
             "lines": [{"bbox": [0.3, 0.5, 0.7, 0.6]}]},
        ],
        [
            {"type": "image_body", "index": 0, "bbox": [0.1, 0.1, 0.9, 0.5],
             "image_path": "imgs/0.png",
             "lines": []},
        ],
    ]


class TestAssignBlockUuids(unittest.TestCase):
    """测试 block_id 分配。"""

    def test_assigns_uuid_to_all_blocks(self):
        model_list = _make_model_list()
        assign_block_uuids_to_model_list(model_list)
        for page in model_list:
            for block in page:
                self.assertIn("block_id", block)
                self.assertEqual(len(block["block_id"]), 36)  # UUID 字符串长度

    def test_unique_ids(self):
        model_list = _make_model_list()
        assign_block_uuids_to_model_list(model_list)
        ids = [b["block_id"] for page in model_list for b in page]
        self.assertEqual(len(ids), len(set(ids)))

    def test_idempotent(self):
        model_list = _make_model_list()
        assign_block_uuids_to_model_list(model_list)
        first_id = model_list[0][0]["block_id"]
        assign_block_uuids_to_model_list(model_list)
        self.assertEqual(model_list[0][0]["block_id"], first_id)

    def test_preserves_existing_block_id(self):
        model_list = _make_model_list()
        model_list[0][0]["block_id"] = "custom-id"
        assign_block_uuids_to_model_list(model_list)
        self.assertEqual(model_list[0][0]["block_id"], "custom-id")


class TestBuildBlockIdMap(unittest.TestCase):
    """测试 block_id 映射构建。"""

    def test_map_structure(self):
        model_list = _make_model_list()
        assign_block_uuids_to_model_list(model_list)
        mapping = build_block_id_map(model_list)
        self.assertEqual(set(mapping.keys()), {"0", "1"})
        self.assertEqual(set(mapping["0"].keys()), {"0", "1"})
        self.assertEqual(mapping["0"]["0"], model_list[0][0]["block_id"])
        self.assertEqual(mapping["0"]["1"], model_list[0][1]["block_id"])
        self.assertEqual(mapping["1"]["0"], model_list[1][0]["block_id"])

    def test_falls_back_to_position_without_index(self):
        model_list = [[{"type": "text", "content": "x"}]]
        assign_block_uuids_to_model_list(model_list)
        mapping = build_block_id_map(model_list)
        self.assertEqual(mapping["0"]["0"], model_list[0][0]["block_id"])

    def test_skips_blocks_without_id(self):
        model_list = _make_model_list()
        # 不分配 block_id，映射应为空
        self.assertEqual(build_block_id_map(model_list), {})


class TestStripBlockIds(unittest.TestCase):
    """测试 block_id 剥离（postprocess 前使用）。"""

    def test_removes_block_id(self):
        model_list = _make_model_list()
        assign_block_uuids_to_model_list(model_list)
        clean = strip_block_ids_from_model_list(model_list)
        for page in clean:
            for block in page:
                self.assertNotIn("block_id", block)

    def test_does_not_mutate_original(self):
        model_list = _make_model_list()
        assign_block_uuids_to_model_list(model_list)
        first_id = model_list[0][0]["block_id"]
        strip_block_ids_from_model_list(model_list)
        self.assertEqual(model_list[0][0]["block_id"], first_id)

    def test_preserves_other_fields(self):
        model_list = _make_model_list()
        assign_block_uuids_to_model_list(model_list)
        clean = strip_block_ids_from_model_list(model_list)
        self.assertEqual(clean[0][0]["content"], model_list[0][0]["content"])
        self.assertEqual(clean[0][0]["bbox"], model_list[0][0]["bbox"])
        self.assertEqual(clean[1][0]["image_path"], model_list[1][0]["image_path"])


if __name__ == "__main__":
    unittest.main()
