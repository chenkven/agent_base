"""命令行入口：在项目根目录执行 python main.py。"""

import sys

from app.cli import main


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
