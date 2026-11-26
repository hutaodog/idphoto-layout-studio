"""Actual UI export encoding and collision protection; only OS/UI prompts mocked."""
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image
from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import QApplication

from app.core import settings
from app.core.pipeline import ProcessResult
from app.core.specs import SpecLibrary
from app.ui import main_window as ui
from app.ui.worker import PhotoRequest


@pytest.fixture
def scene(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    monkeypatch.setenv('IDPHOTO_NO_UPDATE', '1')
    monkeypatch.setattr(settings, 'settings_path', lambda: str(tmp_path / 'settings.json'))
    monkeypatch.setattr(ui, 'default_out_dir', lambda: str(tmp_path / '导出目录'))
    monkeypatch.setattr(ui.MainWindow, '_check_weights', lambda self: None)
    monkeypatch.setattr(ui.MainWindow, '_report_last_update', lambda self: None)
    monkeypatch.setattr(ui.updater, 'cleanup_stale', lambda: None)
    events = []
    monkeypatch.setattr(ui, 'show_message', lambda *a, **kw: events.append(('message', a[1:], kw)))
    monkeypatch.setattr(ui.MainWindow, '_open_output_folder',
                        staticmethod(lambda path: events.append(('folder', path))))
    w = ui.MainWindow(SpecLibrary.load())
    w._out_dir = str(tmp_path / '导出目录')
    def ready(spec_id='cn_yicun'):
        spec = w.lib.photo(spec_id)
        with QSignalBlocker(w.lst_specs):
            row = next(i for i in range(w.lst_specs.count()) if w.lst_specs.item(i).data(Qt.UserRole) == spec_id)
            w.lst_specs.setCurrentRow(row)
        w._selected_spec_id = spec_id
        path = str(tmp_path / '同一张原照片.png')
        w.current = ui.PhotoItem(path=path)
        w._request = PhotoRequest(10, path, spec, w.cb_hollow.isChecked())
        source = np.full((spec.hw[0], spec.hw[1], 3), (20, 70, 180), np.uint8)
        rgba = np.dstack([source, np.full(source.shape[:2], 255, np.uint8)])
        w.result = ProcessResult(standard_bgr=source, standard_rgba=rgba, matting_bgra=rgba,
                                face={}, spec=spec, bg='white')
        assert w._can_export()
    ready()
    yield SimpleNamespace(w=w, events=events, ready=ready, output=Path(w._out_dir))
    w.close()
    app.processEvents()
    w.deleteLater()
    app.processEvents()


def test_one_and_two_inch_reexports_preserve_every_jpeg(scene):
    s = scene
    s.w.on_export_single_only()
    first = next(s.output.glob('*.jpg'))
    saved = first.read_bytes()
    s.ready('cn_ercun')
    s.w.on_export_single_only()
    s.ready('cn_yicun')
    s.w.on_export_single_only()
    files = list(s.output.glob('*.jpg'))
    assert len(files) == 3
    assert first.read_bytes() == saved
    assert sum('cn_yicun' in p.name for p in files) == 2
    assert sum('cn_ercun' in p.name for p in files) == 1
    assert any(p.stem.endswith('_2') for p in files)
    for file in files:
        with Image.open(file) as im:
            assert im.size == ((413, 626) if 'cn_ercun' in file.name else (295, 413))
    assert [event[0] for event in s.events] == ['folder', 'message'] * 3
    assert all(Path(e[1]) == s.output for e in s.events if e[0] == 'folder')


def test_both_outputs_open_folder_once_and_repeat_safely(scene):
    s = scene
    s.w._do_export(True, True)
    first = {p.name: p.read_bytes() for p in s.output.glob('*.jpg')}
    assert len(first) == 2
    s.w._do_export(True, True)
    assert len(list(s.output.glob('*.jpg'))) == 4
    assert all((s.output / name).read_bytes() == data for name, data in first.items())
    assert len([e for e in s.events if e[0] == 'folder']) == 2


def test_open_folder_failure_keeps_saved_image_and_warns(scene, monkeypatch):
    def fail(path):
        raise OSError('Explorer failed')
    monkeypatch.setattr(scene.w, '_open_output_folder', fail)
    scene.w.on_export_single_only()
    assert len(list(scene.output.glob('*.jpg'))) == 1
    message = scene.events[-1]
    assert message[2]['kind'] == 'warn'
    assert '无法打开输出文件夹' in message[1][1]
    assert 'Explorer failed' in message[2]['detail']


def test_no_result_or_no_selection_never_opens_folder(scene):
    scene.w._do_export(False, False)
    scene.w.result = None
    scene.w.on_export_single_only()
    assert not any(e[0] == 'folder' for e in scene.events)
    assert not scene.output.exists()


def test_partial_export_opens_directory_for_successful_file(scene, monkeypatch):
    def fail(*args):
        raise OSError('layout failed')
    monkeypatch.setattr(scene.w, '_sheet_for_output', fail)
    scene.w._do_export(True, True)
    assert len(list(scene.output.glob('*.jpg'))) == 1
    assert [e[0] for e in scene.events] == ['folder', 'message']
    message = scene.events[-1]
    assert message[1][0] == '部分导出成功'
    assert 'layout failed' in message[1][1]


def test_failed_encoder_leaves_no_placeholder_or_folder(scene, monkeypatch):
    def fail(image, path, **kw):
        Path(path).write_bytes(b'partial jpeg')
        raise OSError('disk write failed')
    monkeypatch.setattr(ui, 'save_image', fail)
    scene.w.on_export_single_only()
    assert not list(scene.output.glob('*.jpg'))
    assert not any(e[0] == 'folder' for e in scene.events)
    assert scene.events[-1][2]['kind'] == 'error'
