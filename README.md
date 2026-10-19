# sparse-file-detector

Identifies sparse files on disk and reports their logical size versus actual block usage.

```python
from sparse_file_detector import detect, is_sparse, SparseFileInfo

info = detect("/etc/hostname")
print(info.logical_size, info.allocated_bytes, info.sparse, info.hole_count)

if is_sparse("/etc/hostname"):
    print("file is sparse")
```

`SparseFileInfo` exposes `path`, `logical_size`, `block_size`, `allocated_bytes`,
`sparse_bytes`, `hole_count`, and `sparse`.

## Why

Backup tools, image exporters, and container runtimes need to know whether a
file is sparse so they can decide between copying bytes and preserving holes.
Reading the whole file to detect zero runs is wasteful when the OS can tell you
the hole layout directly. This library walks `SEEK_DATA`/`SEEK_HOLE` when
available and falls back to `st_blocks` accounting when it is not — one probe,
no file reads, standard library only.

## Trade-off

The `st_blocks`-based fallback detects that *some* storage is saved, but it
cannot enumerate individual hole regions. When `SEEK_HOLE` is unavailable,
`hole_count` is 0 even for files that are sparse by the block test. This is
deliberate: the count reflects regions actually walked, not a guess.

## Edge cases

On filesystems that do not support sparse files at all (tmpfs, some network
filesystems, overlay configurations), a file created with a hole will be
written out as real zeros and `sparse` will be `false`. That is correct
behaviour, not a bug — the file genuinely occupies that storage on that
filesystem.

The library only inspects regular files. Directories, fifos, devices, and
symlinks raise `ValueError` from `detect`.
