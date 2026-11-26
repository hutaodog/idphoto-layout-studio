import concurrent.futures
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from app.core.export_paths import export_stem, reserve_export_path, safe_filename_part
from app.core.exporter import save_image
from app.core.specs import SpecLibrary


@pytest.mark.parametrize("value", ['CON', 'con.txt', 'LPT1', 'COM²', '<不合法>:照片?/\\*|', '尾随. ', '', '😀' * 200])
def test_safe_windows_names(value):
    part = safe_filename_part(value)
    assert part and len(part.encode('utf-16-le')) <= 128
    assert not any(c in part for c in '<>:"/\\|?*')
    assert not part.endswith((' ', '.'))
    if value.lower().startswith(('con', 'lpt', 'com')):
        assert part.startswith('_')


def test_specs_are_readable_distinct_and_fit_filename_limit():
    lib = SpecLibrary.load()
    stems = [export_stem('原照片😀' * 100, lib.photo(id), '白色')
             for id in ('cn_yicun', 'cn_ercun', 'cn_resume_wide')]
    assert len(set(stems)) == 3
    for id, stem in zip(('cn_yicun', 'cn_ercun', 'cn_resume_wide'), stems):
        assert id in stem and 'mm' in stem
        assert len(stem.encode('utf-16-le')) // 2 <= 224
    assert '一寸' in stems[0] and '二寸' in stems[1]


def test_existing_bytes_and_real_jpeg_both_remain(tmp_path):
    first = tmp_path / '同名.jpg'
    first.write_bytes(b'existing photograph bytes')
    image = np.full((413, 295, 3), 90, dtype=np.uint8)
    with reserve_export_path(str(tmp_path), '同名') as path:
        report = save_image(image, path, dpi=300)
    assert Path(path).name == '同名_2.jpg'
    assert first.read_bytes() == b'existing photograph bytes'
    assert report.ok()
    with Image.open(path) as output:
        assert output.size == (295, 413)
    with reserve_export_path(str(tmp_path), '同名') as third:
        save_image(image, third, dpi=300)
    assert Path(third).name == '同名_3.jpg'
    assert first.read_bytes() == b'existing photograph bytes'


def test_concurrent_reservations_never_reuse_names(tmp_path):
    def write(i):
        with reserve_export_path(str(tmp_path), '同一张照片') as path:
            Path(path).write_bytes(bytes([i]) * 8)
            return path
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        paths = list(pool.map(write, range(24)))
    assert len(set(paths)) == 24
    assert {Path(p).read_bytes() for p in paths} == {bytes([i]) * 8 for i in range(24)}


def test_failed_write_cleans_only_new_reservation(tmp_path):
    existing = tmp_path / '照片.jpg'
    existing.write_bytes(b'keep me')
    with pytest.raises(RuntimeError, match='encoder failure'):
        with reserve_export_path(str(tmp_path), '照片') as path:
            Path(path).write_bytes(b'partial')
            raise RuntimeError('encoder failure')
    assert list(tmp_path.iterdir()) == [existing]
    assert existing.read_bytes() == b'keep me'


def test_empty_output_is_failure_and_removed(tmp_path):
    with pytest.raises(OSError, match='未写入'):
        with reserve_export_path(str(tmp_path), '照片'):
            pass
    assert not list(tmp_path.iterdir())


def test_directory_with_matching_name_is_skipped(tmp_path):
    (tmp_path / '照片.jpg').mkdir()
    with reserve_export_path(str(tmp_path), '照片') as path:
        Path(path).write_bytes(b'result')
    assert Path(path).name == '照片_2.jpg'
    assert (tmp_path / '照片.jpg').is_dir()
