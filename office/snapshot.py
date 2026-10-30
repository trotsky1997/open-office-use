"""Freeze a saved Office file for one operation and identify its bytes."""
import hashlib
import shutil
from pathlib import Path


def copy(source, directory):
    source = Path(source).resolve(strict=True)
    if source.stat().st_size > 128 * 1024 * 1024: raise ValueError('Document exceeds the 128 MiB size limit')
    destination = Path(directory) / source.name
    shutil.copyfile(source, destination)
    if destination.stat().st_size > 128 * 1024 * 1024: raise ValueError('Document exceeds the 128 MiB size limit')
    digest = hashlib.sha256()
    with destination.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''): digest.update(block)
    return destination, digest.hexdigest()
