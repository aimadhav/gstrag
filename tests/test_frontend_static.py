"""The public UI build must not turn private workspace files into web assets."""

from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from gst_rag.api import create_app
from gst_rag.auth import Settings


class StaticFrontendTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.settings = Settings(self.root, self.root / "db", "x" * 32, worker_enabled=False)

    def build(self):
        output = self.root / "frontend/dist"
        output.mkdir(parents=True)
        (output / "index.html").write_text("<!doctype html><title>SYNTHETIC_PUBLIC_LOGIN</title>", encoding="utf-8")
        (output / "asset.js").write_text("// SYNTHETIC_PUBLIC_ASSET", encoding="utf-8")
        return output

    def test_no_build_keeps_api_usable_without_ui_mount(self):
        with TestClient(create_app(self.settings)) as client:
            self.assertEqual(client.get("/health").status_code, 200)
            self.assertEqual(client.get("/app/").status_code, 404)

    def test_built_login_and_assets_are_public_but_queries_still_require_auth(self):
        self.build()
        with TestClient(create_app(self.settings)) as client:
            response = client.get("/app/")
            self.assertEqual(response.status_code, 200)
            self.assertIn("SYNTHETIC_PUBLIC_LOGIN", response.text)
            self.assertEqual(client.get("/app/asset.js").status_code, 200)
            self.assertEqual(client.get("/queries").status_code, 401)
            self.assertEqual(client.get("/admin/reviews").status_code, 401)

    def test_private_files_and_parent_paths_never_served(self):
        self.build()
        (self.root / ".env").write_text("SYNTHETIC_PRIVATE_NOT_A_SECRET", encoding="utf-8")
        private = self.root / "data/private.txt"
        private.parent.mkdir()
        private.write_text("SYNTHETIC_PRIVATE_NOT_A_SECRET", encoding="utf-8")
        with TestClient(create_app(self.settings)) as client:
            for path in ["/app/.env", "/app/data/private.txt", "/app/%2e%2e/.env", "/app/%2e%2e/data/private.txt"]:
                response = client.get(path)
                self.assertEqual(response.status_code, 404)
                self.assertNotIn("SYNTHETIC_PRIVATE_NOT_A_SECRET", response.text)


if __name__ == "__main__":
    unittest.main()
