from __future__ import annotations

import unittest

from lcc_core.hf_metadata import infer_query


class InferQueryTests(unittest.TestCase):
    def test_gguf_file_query_keeps_working(self) -> None:
        q = infer_query("Qwen3.6-27B-GGUF", r"C:\Users\x\models\Qwen3.6-27B-GGUF\Qwen3.6-27B-Q6_K.gguf")
        self.assertIn("Qwen3.6 27B", q)
        self.assertNotIn("gguf", q.lower())

    def test_dotted_directory_name_is_not_mangled(self) -> None:
        # Regression: Path.stem split "Qwen3.6-27B-NVFP4" into "Qwen3" and
        # parent.name appended "models", producing a query HF can't match.
        q = infer_query("Qwen3.6-27B-NVFP4", r"C:\Users\x\models\Qwen3.6-27B-NVFP4")
        self.assertEqual(q, "Qwen3.6 27B NVFP4")

    def test_generic_parent_folders_are_dropped(self) -> None:
        q = infer_query(None, r"C:\Users\x\models\Devstral-Small-2-24B")
        self.assertEqual(q, "Devstral Small 2 24B")

    def test_never_returns_empty(self) -> None:
        self.assertTrue(infer_query("", r"C:\models\gguf"))


if __name__ == "__main__":
    unittest.main()
