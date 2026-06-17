#!/usr/bin/env python3
import sys
import os

# 获取当前脚本所在目录
current_dir = os.path.dirname(os.path.abspath(__file__))

# 强制将当前目录添加到 Python 路径的最前面
sys.path.insert(0, current_dir)

# 再次确保它在最前面
if sys.path[0] != current_dir:
    sys.path.remove(current_dir)
    sys.path.insert(0, current_dir)

# 现在尝试导入
try:
    from cli_anything.shotcut.shotcut_cli import cli
except ImportError as e:
    print(f"导入错误: {e}", file=sys.stderr)
    print(f"当前目录: {current_dir}", file=sys.stderr)
    print(f"Python 路径前3个: {sys.path[:3]}", file=sys.stderr)
    sys.exit(1)

def main():
    """Entry point for console script."""
    cli()

if __name__ == "__main__":
    main()




