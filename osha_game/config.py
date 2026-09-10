"""config.toml loader with code-side defaults. Every key is optional."""
import tomllib
from . import paths

DEFAULTS = {
    "ollama": {"model": "auto", "url": "http://localhost:11434", "per_lesson": 3, "temperature": 0.7},
    "agy": {"model": "", "per_lesson": 3},
    "game": {"shift_size": 15, "exam_questions": 30, "exam_seconds": 1800, "exam_pass_pct": 70},
    "ui": {"animations": True, "fps": 10},
}


def load() -> dict:
    cfg = {section: dict(values) for section, values in DEFAULTS.items()}
    if paths.CONFIG_TOML.exists():
        with open(paths.CONFIG_TOML, "rb") as fh:
            user = tomllib.load(fh)
        for section, values in user.items():
            if isinstance(values, dict):
                cfg.setdefault(section, {}).update(values)
    return cfg
