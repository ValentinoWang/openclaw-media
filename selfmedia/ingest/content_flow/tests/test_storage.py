from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from selfmedia.ingest.content_flow.src.storage import build_media_paths, list_image_files


class StorageImageFilesTest(unittest.TestCase):
    def test_list_image_files_ignores_non_image_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = build_media_paths(
                "https://www.iesdouyin.com/share/note/7659313340270923008/",
                base_dir=tmpdir,
            )
            image_dir = Path(paths.image_dir)
            image_dir.mkdir(parents=True)
            (image_dir / "image-01.webp").write_bytes(b"webp")
            (image_dir / "image-01.txt").write_text("ocr", encoding="utf-8")
            (image_dir / "notes.json").write_text("{}", encoding="utf-8")

            self.assertEqual(list_image_files(paths), [str(image_dir / "image-01.webp")])


if __name__ == "__main__":
    unittest.main()
