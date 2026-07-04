import tomllib
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.toml"


@dataclass
class AsrConfig:
    model: str = "mlx-community/parakeet-tdt-0.6b-v3"


@dataclass
class CleanupConfig:
    enabled: bool = True
    model: str = "qwen3:4b-instruct"
    timeout: float = 6.0


@dataclass
class InjectionConfig:
    method: str = "ax"  # "ax" | "paste"
    restore_clipboard: bool = True


@dataclass
class Config:
    hotkey: str = "fn"  # "fn" | "right_option" | "ctrl_option"
    min_duration: float = 0.3
    asr: AsrConfig = field(default_factory=AsrConfig)
    cleanup: CleanupConfig = field(default_factory=CleanupConfig)
    injection: InjectionConfig = field(default_factory=InjectionConfig)


def load(path: Path = CONFIG_PATH) -> Config:
    if not path.exists():
        return Config()
    with open(path, "rb") as f:
        raw = f.read()
    data = tomllib.loads(raw.decode())
    return Config(
        hotkey=data.get("hotkey", "fn"),
        min_duration=data.get("min_duration", 0.3),
        asr=AsrConfig(**data.get("asr", {})),
        cleanup=CleanupConfig(**data.get("cleanup", {})),
        injection=InjectionConfig(**data.get("injection", {})),
    )
