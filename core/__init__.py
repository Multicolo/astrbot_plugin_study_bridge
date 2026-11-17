"""学习桥梁核心包（不依赖 astrbot，可独立测试）。"""

from .app import PLUGIN_NAME, PLUGIN_VERSION, StudyApp
from .config import Settings

__all__ = ["StudyApp", "Settings", "PLUGIN_NAME", "PLUGIN_VERSION"]
