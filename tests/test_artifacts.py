import hashlib
import tempfile
import unittest
from pathlib import Path

from app.artifacts import build_artifact_metadata


class ArtifactMetadataTests(unittest.TestCase):
    def test_metadata_contains_verifiable_file_identity(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "failed_results.xlsx"
            content = b"artifact-content"
            path.write_bytes(content)

            metadata = build_artifact_metadata(str(path), "failed_results")

        self.assertEqual(metadata["name"], "failed_results")
        self.assertEqual(metadata["content_type"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.assertEqual(metadata["size_bytes"], len(content))
        self.assertEqual(metadata["sha256"], hashlib.sha256(content).hexdigest())
        self.assertNotIn("path", metadata)

    def test_missing_artifact_is_not_reported_as_valid(self):
        with self.assertRaises(FileNotFoundError):
            build_artifact_metadata("missing-file.pdf", "document")


if __name__ == "__main__":
    unittest.main()
