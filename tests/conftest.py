"""pytest 全局配置。

`services/*/app/main.py` 以 `from shared import ...` 导入共享库，需要把
`services/` 目录加入 `sys.path`；同时以 `services.<svc>.app` 形式导入服务模块
需要仓库根目录在 `sys.path` 中。

此前这些路径依赖各测试文件自行插入，导致单独运行某个文件时会因找不到
`shared` 而导入失败（隐性顺序依赖）。在此统一注入，保证任一测试文件均可独立运行。
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SERVICES = os.path.join(_ROOT, "services")

for _path in (_SERVICES, _ROOT):
    if _path not in sys.path:
        sys.path.insert(0, _path)
