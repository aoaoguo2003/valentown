import sys
from pathlib import Path

# 确保无论从仓库根目录还是 backend 目录运行 pytest，
# backend 包内的模块都可以被正常导入。
BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
