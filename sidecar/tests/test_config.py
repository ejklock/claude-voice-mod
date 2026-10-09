from collections.abc import Mapping
from pathlib import Path

import pytest

from voice_sidecar.config import ConfigError, default_config_path, load_config
from voice_sidecar.ports.tts import TextToSpeech
from voice_sidecar.providers import TTS_PROVIDERS, TtsProvider


def write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(content, encoding="utf-8")
    return path


def test_missing_file_resolves_to_say_luciana(tmp_path: Path) -> None:
    config = load_config(tmp_path / "absent.toml")

    assert config.tts.provider == "say"
    assert config.tts.voice == "Luciana"


def test_valid_file_sets_the_values(tmp_path: Path) -> None:
    path = write(tmp_path, '[tts]\nprovider = "say"\nvoice = "Eddy"\n')

    config = load_config(path)

    assert config.tts.provider == "say"
    assert config.tts.voice == "Eddy"


def test_empty_file_keeps_the_defaults(tmp_path: Path) -> None:
    config = load_config(write(tmp_path, ""))

    assert (config.tts.provider, config.tts.voice) == ("say", "Luciana")


def test_unknown_provider_names_the_field_and_lists_the_known_ones(
    tmp_path: Path,
) -> None:
    path = write(tmp_path, '[tts]\nprovider = "nope"\n')

    with pytest.raises(ConfigError) as error:
        load_config(path)

    assert str(error.value) == (
        f"{path}: tts.provider: unknown provider 'nope'; "
        "known providers: elevenlabs, kokoro, openai, piper, say"
    )


def test_every_problem_in_the_file_is_listed(tmp_path: Path) -> None:
    path = write(tmp_path, '[tts]\nprovider = "nope"\nvoice = 3\n')

    with pytest.raises(ConfigError) as error:
        load_config(path)

    assert str(error.value) == (
        f"{path}: tts.provider: unknown provider 'nope'; "
        "known providers: elevenlabs, kokoro, openai, piper, say; "
        "tts.voice: Input should be a valid string"
    )


def test_non_string_voice_names_the_field(tmp_path: Path) -> None:
    path = write(tmp_path, "[tts]\nvoice = 3\n")

    with pytest.raises(ConfigError) as error:
        load_config(path)

    assert str(path) in str(error.value)
    assert "tts.voice" in str(error.value)


def test_unknown_key_names_the_field(tmp_path: Path) -> None:
    path = write(tmp_path, "[tts]\nspeed = 2\n")

    with pytest.raises(ConfigError) as error:
        load_config(path)

    assert str(path) in str(error.value)
    assert "tts.speed" in str(error.value)


def test_unknown_table_names_the_field(tmp_path: Path) -> None:
    path = write(tmp_path, "[stt]\nmodel = 1\n")

    with pytest.raises(ConfigError) as error:
        load_config(path)

    assert "stt" in str(error.value)


def test_malformed_toml_names_the_file_and_the_line(tmp_path: Path) -> None:
    path = write(tmp_path, '[tts]\nprovider = "say"\nvoice = = 1\n')

    with pytest.raises(ConfigError) as error:
        load_config(path)

    assert str(path) in str(error.value)
    assert "line 3" in str(error.value)


def test_file_that_is_not_utf8_names_the_file(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_bytes(b'[tts]\nvoice = "\xff\xfe"\n')

    with pytest.raises(ConfigError) as error:
        load_config(path)

    assert str(path) in str(error.value)
    assert "UTF-8" in str(error.value)


def test_unreadable_path_names_the_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as error:
        load_config(tmp_path)

    assert str(tmp_path) in str(error.value)


def test_default_path_follows_xdg_config_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    assert default_config_path() == tmp_path / "claude-voice" / "config.toml"


def test_default_path_without_xdg_is_under_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    assert default_config_path() == (
        tmp_path / ".config" / "claude-voice" / "config.toml"
    )


def test_empty_xdg_config_home_counts_as_unset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", "")
    monkeypatch.setenv("HOME", str(tmp_path))

    assert default_config_path() == (
        tmp_path / ".config" / "claude-voice" / "config.toml"
    )


def test_load_without_a_path_reads_the_default_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    (tmp_path / "claude-voice").mkdir()
    (tmp_path / "claude-voice" / "config.toml").write_text(
        '[tts]\nvoice = "Eddy"\n', encoding="utf-8"
    )

    assert load_config().tts.voice == "Eddy"


@pytest.fixture
def modelled(monkeypatch: pytest.MonkeyPatch) -> None:
    def factory(options: Mapping[str, str]) -> TextToSpeech:
        raise AssertionError("the configuration never builds an adapter")

    monkeypatch.setitem(TTS_PROVIDERS, "fake", TtsProvider(factory, ("v",), ("m1",)))


def test_model_is_absent_by_default(tmp_path: Path) -> None:
    assert load_config(tmp_path / "absent.toml").tts.model is None
    assert load_config(write(tmp_path, '[tts]\nvoice = "x"\n')).tts.model is None


@pytest.mark.usefixtures("modelled")
def test_model_outside_the_defaults_is_accepted(tmp_path: Path) -> None:
    path = write(tmp_path, '[tts]\nprovider = "fake"\nmodel = "m9"\n')

    assert load_config(path).tts.model == "m9"


def test_openai_accepts_a_model_outside_its_defaults(tmp_path: Path) -> None:
    path = write(
        tmp_path, '[tts]\nprovider = "openai"\nvoice = "marin"\nmodel = "gpt-x"\n'
    )

    config = load_config(path)

    assert (config.tts.provider, config.tts.model) == ("openai", "gpt-x")


def test_elevenlabs_accepts_a_model_outside_its_defaults(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        '[tts]\nprovider = "elevenlabs"\nvoice = "auto"\nmodel = "eleven_v3"\n',
    )

    config = load_config(path)

    assert (config.tts.provider, config.tts.model) == ("elevenlabs", "eleven_v3")


@pytest.mark.usefixtures("modelled")
@pytest.mark.parametrize(
    ("value", "reason"),
    [
        ('""', "the model must not be empty"),
        ('"  "', "the model must not be empty"),
        ("3", "Input should be a valid string"),
    ],
)
def test_bad_model_names_the_field(tmp_path: Path, value: str, reason: str) -> None:
    path = write(tmp_path, f'[tts]\nprovider = "fake"\nmodel = {value}\n')

    with pytest.raises(ConfigError) as error:
        load_config(path)

    assert str(error.value) == f"{path}: tts.model: {reason}"


def test_provider_without_models_rejects_a_model(tmp_path: Path) -> None:
    path = write(tmp_path, '[tts]\nmodel = "m1"\n')

    with pytest.raises(ConfigError) as error:
        load_config(path)

    assert str(error.value) == f"{path}: tts.model: provider 'say' takes no model"


def test_unknown_provider_with_a_model_reports_only_the_provider(
    tmp_path: Path,
) -> None:
    path = write(tmp_path, '[tts]\nprovider = "nope"\nmodel = "m1"\n')

    with pytest.raises(ConfigError) as error:
        load_config(path)

    assert str(error.value) == (
        f"{path}: tts.provider: unknown provider 'nope'; "
        "known providers: elevenlabs, kokoro, openai, piper, say"
    )


@pytest.mark.usefixtures("modelled")
def test_every_problem_is_listed_with_a_bad_model(tmp_path: Path) -> None:
    path = write(tmp_path, '[tts]\nprovider = "fake"\nvoice = 3\nmodel = ""\n')

    with pytest.raises(ConfigError) as error:
        load_config(path)

    assert str(error.value) == (
        f"{path}: tts.voice: Input should be a valid string; "
        "tts.model: the model must not be empty"
    )
