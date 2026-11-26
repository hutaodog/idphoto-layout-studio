"""Real QThread/event-loop regressions for the single-photo workbench.

Inference is gated, not timed: tests decide exactly when each request can finish.
The actual worker, queued signals, renderer, export code and window lifecycle run.
"""
import os
import threading
import time
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from app.core import settings
from app.core.pipeline import Processor, ProcessResult
from app.core.specs import SpecLibrary
from app.ui import main_window as ui


def wait_for(app, condition, timeout=8):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if condition():
            return True
        time.sleep(0.005)
    app.processEvents()
    return condition()


class GatedProcessor(Processor):
    def __init__(self, lib):
        super().__init__(lib=lib)
        self.started = []
        self.gates = [threading.Event() for _ in range(12)]
        self.fail = set()

    def process(self, img, spec, bg=None, hollow_fix=True, **kw):
        call = len(self.started)
        self.started.append((int(img[0, 0, 0]), spec.id, hollow_fix))
        if not self.gates[call].wait(10):
            raise TimeoutError("test did not release inference gate")
        if call in self.fail:
            raise RuntimeError("deliberate inference failure")
        source = img.copy()
        rgba = np.dstack([source, np.zeros(source.shape[:2], np.uint8)])
        original = cv2.resize(source, spec.px_size)
        standard = np.zeros((spec.hw[0], spec.hw[1], 4), np.uint8)
        return ProcessResult(standard_bgr=standard.copy(), standard_rgba=standard,
                             matting_bgra=rgba, face={"rectangle": (20, 15, 25, 35)},
                             spec=spec, bg=None,
                             original_bgr=source, original_standard=original)


@pytest.fixture
def scene(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    monkeypatch.setenv("IDPHOTO_NO_UPDATE", "1")
    monkeypatch.setattr(ui.MainWindow, "_open_output_folder", staticmethod(lambda directory: None))
    monkeypatch.setattr(settings, "settings_path", lambda: str(tmp_path / "settings.json"))
    monkeypatch.setattr(ui, "default_out_dir", lambda: str(tmp_path / "output"))
    monkeypatch.setattr(ui.MainWindow, "_check_weights", lambda self: None)
    monkeypatch.setattr(ui.updater, "cleanup_stale", lambda: None)
    monkeypatch.setattr(ui.MainWindow, "_report_last_update", lambda self: None)
    messages = []
    monkeypatch.setattr(ui, "show_message", lambda *a, **kw: messages.append((a, kw)))
    w = ui.MainWindow(SpecLibrary.load())
    proc = GatedProcessor(w.lib)
    w.proc = proc
    w.show()
    app.processEvents()

    def photo(name, value):
        path = tmp_path / name
        image = np.full((100, 80, 3), (value, value + 5, value + 10), np.uint8)
        cv2.imencode(".png", image)[1].tofile(str(path))
        return str(path)

    yield SimpleNamespace(app=app, w=w, proc=proc, photo=photo,
                          wait=lambda f: wait_for(app, f), messages=messages,
                          output=tmp_path / "output")
    for gate in proc.gates:
        gate.set()
    w.close()
    assert wait_for(app, lambda: not w._active_qthreads())
    app.processEvents()
    w.close()
    w.deleteLater()
    app.processEvents()


def finish(s, index):
    s.proc.gates[index].set()
    assert s.wait(lambda: s.w._worker is None and s.w._can_export())


def test_rapid_replacement_discards_a_and_skips_queued_b(scene):
    s = scene
    a, b, c = [s.photo(name + ".png", v) for name, v in (("a", 20), ("b", 60), ("c", 100))]
    s.w.add_photos([a])
    assert s.wait(lambda: len(s.proc.started) == 1)
    s.w.add_photos([b])
    s.w.add_photos([c])
    assert not s.w._can_export() and s.w.result is None
    assert s.w.act_import.isEnabled()
    s.proc.gates[0].set()
    assert s.wait(lambda: len(s.proc.started) == 2)
    assert [x[0] for x in s.proc.started] == [20, 100]
    assert s.w.result is None and not s.w._can_export()
    finish(s, 1)
    assert s.w.current.path == c
    assert s.w._processed.original_bgr[0, 0, 0] == 100


def test_reimport_same_path_uses_new_file_contents(scene):
    s = scene
    path = s.photo("same.png", 25)
    s.w.add_photos([path])
    assert s.wait(lambda: len(s.proc.started) == 1)
    old_id = s.w._request.id
    s.photo("same.png", 110)
    s.w.add_photos([path])
    assert s.w._request.id != old_id and s.w.result is None
    s.proc.gates[0].set()
    assert s.wait(lambda: len(s.proc.started) == 2)
    finish(s, 1)
    assert [x[0] for x in s.proc.started] == [25, 110]
    assert s.w._processed.original_bgr[0, 0, 0] == 110


def test_latest_view_settings_apply_and_exports_match_preview(scene):
    s = scene
    s.w.add_photos([s.photo("original.png", 45)])
    assert s.wait(lambda: len(s.proc.started) == 1)
    s.w.on_bg_changed("red")
    s.w.cb_keep_original_bg.setChecked(True)
    s.w.rb_manual.setChecked(True)
    s.w.sl_rotate.setValue(25)
    finish(s, 0)
    assert len(s.proc.started) == 1
    assert s.w.result.preserve_original
    assert not s.w._color_buttons["red"].isEnabled()
    original_pixels = s.w.result.standard_bgr.copy()
    s.w.rb_auto.setChecked(True)
    np.testing.assert_array_equal(s.w.result.standard_bgr, s.w._processed.original_standard)
    s.w.rb_manual.setChecked(True)
    np.testing.assert_array_equal(s.w.result.standard_bgr, original_pixels)
    # Every output consumes the current rendered pixels; record native encoder input.
    captures = []
    real_save = ui.save_image
    def capture(image, path, **kwargs):
        captures.append((image.copy(), path, kwargs))
        return real_save(image, path, **kwargs)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(ui, "save_image", capture)
        s.w._do_export(True, True)
    assert len(captures) == 2
    dpi = s.w._output_dpi(s.w.result.spec)
    plan = s.w._layout_plan()[1]
    np.testing.assert_array_equal(captures[0][0], s.w._photo_for_output(s.w.result, dpi))
    np.testing.assert_array_equal(captures[1][0], s.w._sheet_for_output(s.w.result, plan))
    assert "original" in os.path.basename(captures[0][1])
    assert captures[1][2].get("max_kb") is None
    assert all(os.path.exists(x[1]) for x in captures)
    s.w.cb_keep_original_bg.setChecked(False)
    assert s.w._color_buttons["red"].isEnabled()
    assert not np.array_equal(s.w.result.standard_bgr, original_pixels)
    assert len(s.proc.started) == 1


def test_spec_and_hollow_change_queue_latest_request(scene):
    s = scene
    s.w.add_photos([s.photo("spec.png", 50)])
    assert s.wait(lambda: len(s.proc.started) == 1)
    row = next(i for i in range(s.w.lst_specs.count())
               if s.w.lst_specs.item(i).data(Qt.UserRole) == "cn_ercun")
    s.w.lst_specs.setCurrentRow(row)
    s.w.cb_hollow.setChecked(False)
    s.w.ed_search.setText("no-matching-photo-size")
    assert s.w.current_spec().id == "cn_ercun"
    assert s.w.result is None
    s.proc.gates[0].set()
    assert s.wait(lambda: len(s.proc.started) == 2)
    assert s.proc.started[1][1:] == ("cn_ercun", False)
    finish(s, 1)
    assert s.w.result.spec.id == "cn_ercun"
    s.w.ed_search.clear()
    assert s.w.current_spec().id == "cn_ercun"


def test_failure_clears_export_and_next_import_recovers(scene):
    s = scene
    s.w.add_photos([s.photo("good.png", 30)])
    assert s.wait(lambda: len(s.proc.started) == 1)
    finish(s, 0)
    s.proc.fail.add(1)
    s.w.add_photos([s.photo("bad.png", 70)])
    assert s.w.result is None and not s.w._can_export()
    assert s.wait(lambda: len(s.proc.started) == 2)
    s.proc.gates[1].set()
    assert s.wait(lambda: s.w._worker is None)
    assert s.w.result is None and not s.w._can_export()
    s.w.add_photos([s.photo("recovery.png", 100)])
    assert s.wait(lambda: len(s.proc.started) == 3)
    finish(s, 2)
    assert s.w._processed.original_bgr[0, 0, 0] == 100


def test_close_waits_for_live_worker_and_late_update_does_not_reopen(scene):
    s = scene
    s.w.add_photos([s.photo("closing.png", 50)])
    assert s.wait(lambda: len(s.proc.started) == 1)
    s.w.close()
    assert s.w._close_pending and s.w.isVisible()
    s.proc.gates[0].set()
    assert s.wait(lambda: not s.w.isVisible() and s.w._worker is None)
    assert s.w._close_pending and not s.w._active_qthreads()
    task = SimpleNamespace(close=lambda: None)
    s.w._restore_after_failed_update(task)
    s.w._on_update_error("late failure", False)
    assert not s.w.isVisible() and not s.messages


def test_rebuild_preserves_controls_and_dpi_refreshes_pixels(scene):
    s = scene
    s.w.add_photos([s.photo("layout.png", 55)])
    assert s.wait(lambda: len(s.proc.started) == 1)
    finish(s, 0)
    s.w.rb_manual.setChecked(True)
    s.w.sl_zoom.setValue(25)
    s.w.sp_gap.setValue(3.5)
    s.w.sp_margin.setValue(4)
    s.w.cb_hollow.setChecked(False)
    assert s.wait(lambda: len(s.proc.started) == 2)
    finish(s, 1)
    s.w.cb_keep_original_bg.setChecked(True)
    s.w.cmb_dpi.setCurrentIndex(s.w.cmb_dpi.findData(350))
    target = s.w.current_spec().px_at(350)
    assert (s.w.canvas._pixmap.width(), s.w.canvas._pixmap.height()) == target
    expected = s.w.result.standard_bgr.copy()
    s.w.set_layout("dashboard")
    s.app.processEvents()
    s.w.set_layout("studio")
    s.app.processEvents()
    assert s.w.rb_manual.isChecked() and s.w.sl_zoom.value() == 25
    assert s.w.sp_gap.value() == 3.5 and s.w.sp_margin.value() == 4
    assert s.w.cmb_dpi.currentData() == 350 and not s.w.cb_hollow.isChecked()
    assert not hasattr(s.w, "lst_photos") and not s.w._color_buttons["white"].isEnabled()
    np.testing.assert_array_equal(s.w.result.standard_bgr, expected)
    assert len(s.proc.started) == 2 and s.w._can_export()
