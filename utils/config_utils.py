# -*- coding: utf-8 -*-
"""
配置工具模块

提供配置读取功能，优先从配置文件读取，如果配置值为空字符串则从环境变量读取。
"""

import os
import json
from pathlib import Path
from typing import Any, Dict, Optional


def load_configuration() -> Dict[str, Any]:
    """从配置文件加载设置参数"""
    config_path = Path(__file__).parent.parent / "configs" / "config.json"
    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在：{config_path}")
    
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        raise RuntimeError(f"读取配置文件失败：{e}")


def get_config_value(config: Dict[str, Any], config_key: str, env_var: str, default: Optional[str] = None) -> str:
    """
    优先从配置文件读取配置值，如果配置值为空字符串则从环境变量读取
    
    Args:
        config: 配置字典
        config_key: 配置文件中的键名
        env_var: 环境变量名
        default: 默认值（可选）
    
    Returns:
        配置值
    """
    # 优先从配置文件读取
    config_value = config.get(config_key, "")
    
    # 如果配置值为空字符串，则从环境变量读取
    if config_value == "":
        config_value = os.getenv(env_var, default or "")
    
    return config_value