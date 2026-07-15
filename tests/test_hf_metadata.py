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


class DirUpdateCheckTests(unittest.TestCase):
    def test_directory_checkpoint_uses_newest_shard_mtime(self) -> None:
        import tempfile
        from pathlib import Path as P
        from unittest import mock
        from lcc_core import hf_metadata

        with tempfile.TemporaryDirectory() as tmp:
            ckpt = P(tmp) / "Fake-NVFP4"
            ckpt.mkdir()
            shard = ckpt / "model-00001-of-00001.safetensors"
            shard.write_bytes(b"x" * 128)

            fake_info = {"success": True, "model_id": "org/fake", "url": "u", "query": "q"}
            # Repo modified long before the local shard -> no update.
            fake_meta = {"lastModified": "2020-01-01T00:00:00.000Z"}
            with mock.patch.object(hf_metadata, "fetch_model_info", return_value=fake_info), \
                 mock.patch.object(hf_metadata, "_get_json", return_value=fake_meta):
                result = hf_metadata.check_model_update(name="Fake", path=str(ckpt))

        self.assertTrue(result["success"])
        self.assertIsNone(result["file_differs"])  # no single-file compare for dirs
        self.assertFalse(result["update_available"])
        self.assertIn("directory", result["reason"].lower())


if __name__ == "__main__":
    unittest.main()
