#!/usr/bin/env python3
"""独立运行启动器：从任意目录都能启动 ``core.standalone``。

AstrBot 里插件是包（``data.plugins.astrbot_plugin_study_bridge.main``），
而独立运行时 ``core`` 是顶层包。为了两种导入方式都能工作，这里把
**插件目录的父目录** 加进 sys.path，再按插件真实目录名导入。
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT.parent))

module = importlib.import_module(f"{ROOT.name}.core.standalone")

if __name__ == "__main__":
    raise SystemExit(module.main())
