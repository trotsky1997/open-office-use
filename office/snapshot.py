"""Freeze a saved Office file for one operation and identify its bytes."""
import hashlib
import os
from pathlib import Path


def copy(source, directory):
    source = Path(source).resolve(strict=True)
    destination = Path(directory) / source.name
    def identity(stat):
        return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns
    with source.open('rb') as original:
        before = os.fstat(original.fileno())
        if before.st_size > 128 * 1024 * 1024: raise ValueError('Document exceeds the 128 MiB size limit')
        digest = hashlib.sha256(); total = 0
        frozen = destination.open('xb')
        try:
            with frozen:
                for block in iter(lambda: original.read(1024 * 1024), b''):
                    total += len(block)
                    if total > 128 * 1024 * 1024: raise ValueError('Document exceeds the 128 MiB size limit')
                    frozen.write(block); digest.update(block)
                if total != before.st_size or identity(os.fstat(original.fileno())) != identity(before) or identity(source.stat()) != identity(before):
                    raise ValueError('Document changed while creating snapshot; retry with a saved file')
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
    return destination, digest.hexdigest()
