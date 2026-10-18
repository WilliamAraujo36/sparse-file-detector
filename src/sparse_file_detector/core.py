"""Core logic for identifying sparse files on disk.

A sparse file is one that reports a large logical size but occupies fewer
blocks on disk because some regions are holes (zeros not backed by storage).

Implementation note:
    POSIX.1-2008 specifies SEEK_DATA / SEEK_HOLE, which lets a process walk
    the data/hole segments of a file without reading its contents. Python's
    standard library does not expose those constants directly, but on Linux
    and BSD they are fixed values defined in <fcntl.h>: SEEK_DATA=3 and
    SEEK_HOLE=4. We try os.SEEK_* aliases first (some platforms define them)
    and fall back to the raw integers.

    On platforms that do not provide sparse semantics (Windows, or any OS
    where lseek with SEEK_HOLE raises EINVAL/ENOTSUP), we fall back to
    comparing st_blocks*512 against st_size. The st_blocks value is filled
    in by stat(2) on Linux/BSD; it is the count of 512-byte blocks actually
    allocated. (The 512-byte block size is fixed by POSIX and is independent
    of the filesystem's actual block size, which is why no ioctl is needed.)
"""

import os
import stat
import sys


# We prefer the named constants if the current Python build exposes them.
# On Linux/BSD, SEEK_DATA is 3 and SEEK_HOLE is 4 (per <fcntl.h>).
_SEEK_DATA = getattr(os, "SEEK_DATA", 3)
_SEEK_HOLE = getattr(os, "SEEK_HOLE", 4)


class SparseFileInfo:
    """Summary of a file's logical vs. on-disk footprint.

    Attributes:
        path:        Absolute path of the inspected file.
        logical_size: Size reported by stat(), i.e. the number of bytes a
                      reader would see.
        block_size:  The 512-byte allocation unit used by st_blocks.
                      (Fixed by POSIX; not the filesystem block size.)
        allocated_bytes: Bytes of physical storage currently allocated.
                         Computed as st_blocks * 512.
        sparse_bytes: logical_size - allocated_bytes (>=0). When the file
                      is not sparse this is 0.
        hole_count:  Number of hole regions discovered. 0 when the
                      SEEK_HOLE probe is unavailable.
        sparse:      True when the file uses less storage than its logical
                      size, or when at least one hole region was found.
    """

    __slots__ = (
        "path",
        "logical_size",
        "block_size",
        "allocated_bytes",
        "sparse_bytes",
        "hole_count",
        "sparse",
    )

    def __init__(
        self,
        path,
        logical_size,
        block_size,
        allocated_bytes,
        sparse_bytes,
        hole_count,
        sparse,
    ):
        self.path = path
        self.logical_size = logical_size
        self.block_size = block_size
        self.allocated_bytes = allocated_bytes
        self.sparse_bytes = sparse_bytes
        self.hole_count = hole_count
        self.sparse = sparse

    def __repr__(self):
        return (
            f"SparseFileInfo(path={self.path!r}, logical_size={self.logical_size}, "
            f"allocated_bytes={self.allocated_bytes}, sparse={self.sparse})"
        )


def _seek_hole_count(fd, size):
    """Count hole regions using SEEK_DATA / SEEK_HOLE.

    A file begins in either data or hole state. A hole at offset 0 still
    counts as a hole region. We scan alternating hole/data segments until
    we reach EOF.

    Returns (hole_count, used_seek) or (0, False) if unsupported.
    """
    if size <= 0:
        return 0, False
    try:
        cur = os.lseek(fd, 0, _SEEK_HOLE)
    except (OSError, ValueError):
        return 0, False

    holes = 0
    pos = cur
    if pos > 0:
        # File starts with data; the hole reported by SEEK_HOLE is beyond it.
        pos = os.lseek(fd, pos, _SEEK_DATA)

    while pos < size:
        hole = os.lseek(fd, pos, _SEEK_HOLE)
        if hole >= size:
            break
        holes += 1
        data = os.lseek(fd, hole, _SEEK_DATA)
        if data <= hole:
            # No further data — trailing hole to EOF already counted.
            break
        pos = data

    return holes, True


def detect(path):
    """Inspect a file and return its sparse-file summary.

    Args:
        path: Path to the file (str or path-like).

    Returns:
        SparseFileInfo.

    Raises:
        FileNotFoundError: path does not exist or is not a file.
        OSError: stat() or open() failed.
    """
    st = os.stat(path)
    if not stat.S_ISREG(st.st_mode):
        raise ValueError(f"not a regular file: {path}")

    logical_size = st.st_size
    # st_blocks is in 512-byte units per POSIX, regardless of FS block size.
    block_size = 512
    allocated = st.st_blocks * block_size

    hole_count = 0
    seek_used = False
    try:
        with open(path, "rb") as fh:
            hole_count, seek_used = _seek_hole_count(fh.fileno(), logical_size)
    except OSError:
        pass

    sparse_bytes = max(0, logical_size - allocated)
    sparse = sparse_bytes > 0 or hole_count > 0

    return SparseFileInfo(
        path=os.path.abspath(path),
        logical_size=logical_size,
        block_size=block_size,
        allocated_bytes=allocated,
        sparse_bytes=sparse_bytes,
        hole_count=hole_count,
        sparse=sparse,
    )


def is_sparse(path):
    """Return True if the file at path is sparse (uses less storage than size)."""
    return detect(path).sparse
