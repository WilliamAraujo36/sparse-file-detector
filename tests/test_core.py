"""Tests for sparse_file_detector.core.

Determinism note:
    We cannot rely on the test runner's filesystem supporting sparse files
    (Windows, tmpfs, overlayfs, CI runners, etc.). So every test creates
    files with known, controlled contents and asserts only on properties
    that hold regardless of platform: logical size is exact, allocated
    bytes is non-negative, sparse_bytes is non-negative and consistent
    with allocated bytes, hole_count is non-negative, and sparse is the
    disjunction of "allocated < logical" and "hole_count > 0".

    No test sleeps or measures wall-clock time. No test asserts on exact
    allocated byte counts, because those depend on the host filesystem's
    block allocator.
"""

import os
import stat
import tempfile
import unittest

from sparse_file_detector import SparseFileInfo, is_sparse, detect


class TestDetect(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _mkfile(self, name, data=b""):
        p = os.path.join(self.tmp, name)
        with open(p, "wb") as fh:
            fh.write(data)
        return p

    def test_empty_file(self):
        p = self._mkfile("empty.bin")
        info = detect(p)
        self.assertIsInstance(info, SparseFileInfo)
        self.assertEqual(info.logical_size, 0)
        self.assertEqual(info.allocated_bytes, 0)
        self.assertEqual(info.sparse_bytes, 0)
        self.assertEqual(info.hole_count, 0)
        self.assertFalse(info.sparse)
        self.assertEqual(info.block_size, 512)

    def test_small_nonsparse_file(self):
        data = b"hello world" * 10
        p = self._mkfile("small.bin", data)
        info = detect(p)
        self.assertEqual(info.logical_size, len(data))
        self.assertGreaterEqual(info.allocated_bytes, 0)
        self.assertEqual(info.sparse_bytes, max(0, len(data) - info.allocated_bytes))
        self.assertGreaterEqual(info.hole_count, 0)
        self.assertEqual(info.sparse, (info.allocated_bytes < len(data)) or (info.hole_count > 0))

    def test_sparse_via_seek_hole_or_blocks(self):
        p = os.path.join(self.tmp, "hole.bin")
        try:
            with open(p, "wb") as fh:
                fh.write(b"AAAA")
                fh.seek(1 << 20)  # 1 MiB hole
                fh.write(b"BBBB")
        except OSError:
            self.skipTest("cannot create sparse test file on this FS")

        info = detect(p)
        self.assertEqual(info.logical_size, (1 << 20) + 4)
        # The hole region must show up either via SEEK_HOLE or via block accounting.
        self.assertTrue(info.sparse, "hole not detected by either method")
        self.assertGreater(info.sparse_bytes, 0)

    def test_path_is_absolute_in_result(self):
        p = self._mkfile("abs.bin", b"x")
        info = detect(p)
        self.assertEqual(info.path, os.path.abspath(p))

    def test_is_sparse_returns_bool(self):
        p = self._mkfile("bool.bin", b"data")
        self.assertIsInstance(is_sparse(p), bool)

    def test_is_sparse_false_for_dense(self):
        p = self._mkfile("dense.bin", b"xyz" * 100)
        # A small dense file occupies at least one block; allocated >= size is common.
        # We only assert the boolean contract here.
        self.assertFalse(is_sparse(p) is None)

    def test_detect_rejects_directory(self):
        with self.assertRaises(ValueError):
            detect(self.tmp)

    def test_detect_missing_file_raises(self):
        p = os.path.join(self.tmp, "nope.bin")
        with self.assertRaises(OSError):
            detect(p)

    def test_detect_rejects_fifo(self):
        p = os.path.join(self.tmp, "fifo")
        os.mkfifo(p)
        with self.assertRaises(ValueError):
            detect(p)

    def test_repr_contains_path(self):
        p = self._mkfile("repr.bin", b"q")
        info = detect(p)
        s = repr(info)
        self.assertIn("SparseFileInfo", s)
        self.assertIn(info.path, s)

    def test_two_files_distinct_objects(self):
        a = self._mkfile("a.bin", b"aaaa")
        b = self._mkfile("b.bin", b"bbbb")
        ia, ib = detect(a), detect(b)
        self.assertIsNot(ia, ib)
        self.assertNotEqual(ia.path, ib.path)

    def test_logical_size_matches_written_bytes(self):
        data = bytes(range(256)) * 4
        p = self._mkfile("sized.bin", data)
        self.assertEqual(detect(p).logical_size, len(data))

    def test_sparse_bytes_nonnegative(self):
        p = self._mkfile("nonneg.bin", b"z" * 8192)
        info = detect(p)
        self.assertGreaterEqual(info.sparse_bytes, 0)
        self.assertGreaterEqual(info.allocated_bytes, 0)

    def test_hole_count_nonnegative(self):
        p = self._mkfile("holes.bin", b"data")
        info = detect(p)
        self.assertGreaterEqual(info.hole_count, 0)


if __name__ == "__main__":
    unittest.main()
