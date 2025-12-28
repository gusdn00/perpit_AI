#config 필드가 올바른지 검사
from pathlib import Path


class ConfigError(ValueError):
    pass


def validate_config(config: dict) -> None:
    required = {"file", "title", "purpose", "style", "difficulty"}
    missing = required - set(config.keys())
    if missing:
        raise ConfigError(f"Missing required keys: {sorted(missing)}")

    file_path = Path(config["file"])
    if not file_path.exists():
        raise ConfigError(f"File not found: {file_path}")

    if str(file_path).lower().endswith((".mp3", ".wav")) is False:
        raise ConfigError("file must be .mp3 or .wav")

    if not isinstance(config["title"], str) or not config["title"].strip():
        raise ConfigError("title must be a non-empty string")

    if config["purpose"] not in {"1", "2"}:
        raise ConfigError("purpose must be '1' or '2'")

    if config["style"] not in {"1", "2", "3"}:
        raise ConfigError("style must be '1', '2', or '3'")

    if config["difficulty"] not in {"1", "2"}:
        raise ConfigError("difficulty must be '1' or '2'")
