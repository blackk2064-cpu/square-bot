import os
import yaml

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")

_cache = None


def load_config():
    global _cache
    if _cache is not None:
        return _cache
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        _cache = yaml.safe_load(f)
    return _cache
