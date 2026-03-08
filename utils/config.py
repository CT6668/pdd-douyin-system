"""
配置加载工具
优先加载 config.local.yaml（私密配置），再加载 config.yaml（默认配置）
"""

import os
import yaml
from pathlib import Path

_ROOT = Path(__file__).parent.parent
_CONFIG_PATH = _ROOT / "config" / "config.yaml"
_LOCAL_CONFIG_PATH = _ROOT / "config" / "config.local.yaml"

_config_cache = None


def load_config() -> dict:
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    # 加载默认配置
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # 加载本地覆盖配置（如果存在）
    if _LOCAL_CONFIG_PATH.exists():
        with open(_LOCAL_CONFIG_PATH, "r", encoding="utf-8") as f:
            local = yaml.safe_load(f) or {}
        _deep_merge(config, local)

    _config_cache = config
    return config


def _deep_merge(base: dict, override: dict):
    """深度合并 override 到 base（就地修改 base）"""
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


def get(key_path: str, default=None):
    """
    按点路径获取配置值
    例如：get("scoring.min_total_score") → 60
    """
    config = load_config()
    keys = key_path.split(".")
    val = config
    for k in keys:
        if isinstance(val, dict) and k in val:
            val = val[k]
        else:
            return default
    return val


if __name__ == "__main__":
    cfg = load_config()
    print("系统名称:", get("system.name"))
    print("评分最低分:", get("scoring.min_total_score"))
    print("聚焦类目:", get("focus.categories.0.name"))
