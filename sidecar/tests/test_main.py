import pytest

from voice_sidecar.cli import main


def test_version_prints_the_plugin_version(
    capsys: pytest.CaptureFixture[str], plugin_version: str
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out == f"{plugin_version}\n"


def test_help_names_the_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])

    assert exit_info.value.code == 0
    assert "--version" in capsys.readouterr().out


def test_unknown_flag_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--bogus"])

    captured = capsys.readouterr()
    assert exit_info.value.code == 2
    assert captured.err.startswith("usage:")
    assert captured.out == ""


def test_no_argument_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main([])

    captured = capsys.readouterr()
    assert exit_info.value.code == 2
    assert captured.err.startswith("usage: voice-sidecar ")
    assert captured.err.endswith("voice-sidecar: error: a flag is required\n")
    assert captured.out == ""


def test_omitted_argv_reads_the_process_arguments(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    plugin_version: str,
) -> None:
    monkeypatch.setattr("sys.argv", ["voice-sidecar", "--version"])

    with pytest.raises(SystemExit) as exit_info:
        main()

    assert exit_info.value.code == 0
    assert capsys.readouterr().out == f"{plugin_version}\n"


def test_omitted_argv_without_arguments_is_a_usage_error(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.argv", ["voice-sidecar"])

    with pytest.raises(SystemExit) as exit_info:
        main()

    assert exit_info.value.code == 2
    assert "a flag is required" in capsys.readouterr().err
