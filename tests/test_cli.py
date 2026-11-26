# -*- coding: utf-8 -*-
"""CLI integration at the processor boundary, with real layout and file exports."""
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from app import cli
from app.core.exporter import printed_mm, read_dpi
from app.core.layout import plan_for_spec
from app.core.specs import SpecLibrary


@pytest.fixture
def lib():
    return SpecLibrary.load()


@pytest.fixture
def input_photo(tmp_path):
    path = tmp_path / "输入照片.png"
    Image.new("RGB", (24, 36), (90, 120, 180)).save(path)
    return path


@pytest.fixture
def processor_calls(monkeypatch):
    calls = []

    class FakeProcessor:
        def __init__(self, lib):
            self.lib = lib

        def process(self, image, spec, **options):
            calls.append((image, spec, options))
            pixels = np.random.default_rng(19).integers(
                0, 256, (spec.px[1], spec.px[0], 3), dtype=np.uint8)
            return SimpleNamespace(standard_bgr=pixels, face_rect=(2, 3, 10, 14))

    monkeypatch.setattr(cli, "Processor", FakeProcessor)
    return calls


@pytest.fixture
def saved_images(monkeypatch):
    saved = []
    original_save = cli.save_image

    def capture(image, path, **options):
        report = original_save(image, path, **options)
        saved.append((path, image.shape, options, report))
        return report

    monkeypatch.setattr(cli, "save_image", capture)
    return saved


@pytest.mark.parametrize("spec_id,override,expected_dpi", [
    ("cn_yicun", None, 300), ("cn_idcard", None, 350),
    ("cn_yicun", 350, 350), ("cn_idcard", 300, 300),
])
def test_plan_and_run_share_dpi_counts_and_print_dimensions(
        lib, input_photo, processor_calls, saved_images, capsys, tmp_path,
        spec_id, override, expected_dpi):
    common = ["--spec", spec_id, "--paper", "6inch"]
    if override is not None:
        common += ["--dpi", str(override)]
    args = cli.build_parser().parse_args(["--plan", "--count", "13"] + common)
    assert cli.cmd_plan(lib, args) == 0
    plan_output = capsys.readouterr().out
    run_args = cli.build_parser().parse_args([
        "--input", str(input_photo), "--out", str(tmp_path / "outputs"),
        "--crop-line", "none",
    ] + common)
    assert cli.cmd_run(lib, run_args) == 0
    run_output = capsys.readouterr().out
    spec, paper = lib.photo(spec_id), lib.paper("6inch")
    expected = plan_for_spec(paper, spec, dpi=expected_dpi)
    assert expected.count == 12
    assert expected.summary() in plan_output and expected.summary() in run_output
    assert "最小可用相纸：7inch" in plan_output
    assert processor_calls[0][1].dpi == expected_dpi
    expected_photo_px = spec.px_size if override is None else spec.px_at(expected_dpi)
    assert processor_calls[0][1].px_size == expected_photo_px
    assert spec.dpi == (350 if spec_id == "cn_idcard" else 300)
    assert len(saved_images) == 2
    for (path, shape, options, report), expected_mm in zip(saved_images,
                                                         (spec.mm_size, paper.mm)):
        assert report.ok() and options["dpi"] == expected_dpi
        assert read_dpi(path) == (expected_dpi, expected_dpi)
        assert printed_mm(path) == pytest.approx(expected_mm, abs=0.15)
        with Image.open(path) as image:
            assert image.size == (shape[1], shape[0])
    assert saved_images[0][1][:2] == expected_photo_px[::-1]
    assert saved_images[1][1][:2] == paper.px_at(expected_dpi)[::-1]


@pytest.mark.parametrize("keep_background", [False, True])
def test_run_passes_original_background_and_only_limits_single_photo(
        lib, input_photo, processor_calls, saved_images, tmp_path, keep_background):
    spec = replace(lib.photo("cn_yicun"), upload={"min_kb": 20, "max_kb": 24})
    constrained = SpecLibrary([spec], lib.papers, lib.colors)
    argv = ["--input", str(input_photo), "--out", str(tmp_path / "out"),
            "--kb", "80", "--crop-line", "none"]
    if keep_background:
        argv.append("--keep-background")
    assert cli.cmd_run(constrained, cli.build_parser().parse_args(argv)) == 0
    assert processor_calls[0][2]["preserve_original"] is keep_background
    single, sheet = saved_images
    assert single[2] == {"dpi": 300, "target_kb": 80, "max_kb": 24, "min_kb": 20}
    assert 20 * 1024 <= single[3].bytes <= 24 * 1024
    assert sheet[2] == {"dpi": 300, "max_kb": None}
    assert sheet[3].bytes > 24 * 1024 and sheet[3].ok()
    if keep_background:
        assert "_original" in single[0]


def test_explicit_sheet_limit_is_applied_independently(
        lib, input_photo, processor_calls, saved_images, tmp_path):
    args = cli.build_parser().parse_args([
        "--input", str(input_photo), "--out", str(tmp_path / "limited"),
        "--kb", "24", "--layout-max-kb", "256", "--crop-line", "none",
    ])
    assert cli.cmd_run(lib, args) == 0
    assert saved_images[0][3].bytes <= 24 * 1024
    assert saved_images[1][2] == {"dpi": 300, "max_kb": 256}
    assert saved_images[1][3].bytes <= 256 * 1024


@pytest.mark.parametrize("argument", [
    "--dpi=0", "--dpi=-1", "--dpi=300.5", "--count=0",
    "--gap=-1", "--gap=nan", "--margin=inf", "--margin=-1",
    "--kb=-1", "--kb=nan", "--layout-max-kb=-1", "--layout-max-kb=inf",
])
def test_parser_rejects_invalid_numeric_arguments(argument):
    with pytest.raises(SystemExit) as error:
        cli.build_parser().parse_args(["--plan", argument])
    assert error.value.code == 2


@pytest.mark.parametrize("argument", ["--spec=unknown", "--paper=unknown"])
def test_plan_reports_unknown_spec_or_paper_without_traceback(argument, capsys):
    assert cli.main(["--plan", argument]) == 4
    assert "不存在" in capsys.readouterr().err


def test_main_reports_conflicting_single_limits(
        lib, input_photo, processor_calls, monkeypatch, tmp_path, capsys):
    spec = replace(lib.photo("cn_yicun"), upload={"min_kb": 20, "max_kb": 24})
    constrained = SpecLibrary([spec], lib.papers, lib.colors)
    monkeypatch.setattr(cli.SpecLibrary, "load", lambda: constrained)
    assert cli.main(["--input", str(input_photo), "--out", str(tmp_path / "bad"),
                     "--kb", "10", "--no-layout"]) == 2
    assert "参数无效" in capsys.readouterr().err
    assert not list((tmp_path / "bad").glob("*.jpg"))


def test_main_returns_failure_for_unmet_single_limit(
        lib, input_photo, processor_calls, monkeypatch, tmp_path, capsys):
    spec = replace(lib.photo("cn_yicun"), upload={"max_kb": 1})
    constrained = SpecLibrary([spec], lib.papers, lib.colors)
    monkeypatch.setattr(cli.SpecLibrary, "load", lambda: constrained)
    assert cli.main(["--input", str(input_photo), "--out", str(tmp_path / "tiny"),
                     "--no-layout"]) == 2
    assert "导出未满足约束" in capsys.readouterr().out
