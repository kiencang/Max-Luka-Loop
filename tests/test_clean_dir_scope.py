"""Scope of `safe_clean_dir`: only workspace work/ or <CWD>/work inside the system temp dir (stdlib only)."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "tools" / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import path_guards as pg  # noqa: E402


class TestCleanDirScope(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_ctx = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp_ctx.name)
        self.fake_repo = self.tmp / "repo"
        self.fake_repo.mkdir()
        self.cwd_dir = self.tmp / "somewhere"
        (self.cwd_dir / "work" / "sub").mkdir(parents=True)
        self._prev = os.getcwd()
        os.chdir(self.cwd_dir)

    def tearDown(self) -> None:
        os.chdir(self._prev)
        self._tmp_ctx.cleanup()

    def test_temp_dir_detection(self) -> None:
        self.assertTrue(pg._is_within_system_temp(str(self.cwd_dir)))
        self.assertTrue(pg._is_within_system_temp(tempfile.gettempdir()))

    def test_cwd_work_inside_temp_is_allowed(self) -> None:
        pg.safe_clean_dir("work", repo_root=self.fake_repo)
        self.assertFalse((self.cwd_dir / "work").exists())

    def test_cwd_work_outside_temp_is_refused(self) -> None:
        with mock.patch.object(pg, "_is_within_system_temp", return_value=False):
            roots = pg.get_allowed_work_roots(repo_root=self.fake_repo)
            self.assertEqual([r.lower() for r in roots], [str(Path(os.path.abspath(self.fake_repo / "work"))).lower()])
            with self.assertRaisesRegex(ValueError, "Refusing to clean unsafe directory"):
                pg.safe_clean_dir("work", repo_root=self.fake_repo)
        self.assertTrue((self.cwd_dir / "work" / "sub").is_dir(), "unrelated work/ must survive")

    def test_validate_clean_dir_checks_without_deleting(self) -> None:
        target = pg.validate_clean_dir("work", repo_root=self.fake_repo)
        self.assertEqual(target.lower(), str(self.cwd_dir / "work").lower())
        self.assertTrue((self.cwd_dir / "work" / "sub").is_dir(), "validation must never delete")
        self.assertIsNone(pg.validate_clean_dir("", repo_root=self.fake_repo))
        self.assertIsNone(pg.validate_clean_dir("work\\missing", repo_root=self.fake_repo))

    def test_validate_clean_dir_rejects_output_inside_even_before_it_exists(self) -> None:
        future_output = self.cwd_dir / "work" / "later" / "doc_vi.html"
        with self.assertRaisesRegex(ValueError, "resides inside it"):
            pg.validate_clean_dir("work", protected_paths=[future_output], repo_root=self.fake_repo)

    def test_workspace_work_always_allowed(self) -> None:
        (self.fake_repo / "work" / "x").mkdir(parents=True)
        with mock.patch.object(pg, "_is_within_system_temp", return_value=False):
            pg.safe_clean_dir(str(self.fake_repo / "work"), repo_root=self.fake_repo)
        self.assertFalse((self.fake_repo / "work").exists())


if __name__ == "__main__":
    unittest.main()
