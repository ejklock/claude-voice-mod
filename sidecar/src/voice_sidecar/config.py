import os
import tomllib
from pathlib import Path

from pydantic import (
    BaseModel,
    ConfigDict,
    ValidationError,
    ValidationInfo,
    field_validator,
)

from voice_sidecar.providers import (
    DEFAULT_TTS_PROVIDER,
    DEFAULT_TTS_VOICE,
    TTS_PROVIDERS,
)


class ConfigError(Exception):
    """The configuration file cannot be used; the message names the file and why."""


class TtsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    provider: str = DEFAULT_TTS_PROVIDER
    voice: str = DEFAULT_TTS_VOICE
    model: str | None = None

    @field_validator("model")
    @classmethod
    def _model_fits_provider(
        cls, value: str | None, info: ValidationInfo
    ) -> str | None:
        if value is None:
            return None
        if not value.strip():
            raise ValueError("the model must not be empty")
        provider = TTS_PROVIDERS.get(info.data.get("provider", ""))
        if provider is not None and not provider.default_models:
            raise ValueError(f"provider {info.data['provider']!r} takes no model")
        return value

    @field_validator("provider")
    @classmethod
    def _known_provider(cls, value: str) -> str:
        if value not in TTS_PROVIDERS:
            known = ", ".join(sorted(TTS_PROVIDERS))
            raise ValueError(f"unknown provider {value!r}; known providers: {known}")
        return value


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    tts: TtsConfig = TtsConfig()


def default_config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "claude-voice" / "config.toml"


def load_config(path: Path | None = None) -> Config:
    path = default_config_path() if path is None else path
    if not path.exists():
        return Config()
    return _parse(path, _read_toml(path))


def _read_toml(path: Path) -> dict[str, object]:
    try:
        return tomllib.loads(path.read_bytes().decode("utf-8"))
    except OSError as error:
        raise ConfigError(f"{path}: cannot be read: {error.strerror}") from error
    except UnicodeDecodeError as error:
        raise ConfigError(f"{path}: is not valid UTF-8") from error
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{path}: invalid TOML: {error}") from error


def _parse(path: Path, data: dict[str, object]) -> Config:
    try:
        return Config.model_validate(data)
    except ValidationError as error:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in issue['loc'])}: "
            f"{issue['msg'].removeprefix('Value error, ')}"
            for issue in error.errors()
        )
        raise ConfigError(f"{path}: {problems}") from error
