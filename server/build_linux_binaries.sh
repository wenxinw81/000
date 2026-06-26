#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

python3 -m pip install --upgrade pip
python3 -m pip install -r build_requirements.txt

rm -rf build dist
python3 -m PyInstaller -F app.py -n app
python3 -m PyInstaller -F rs485.py -n rs485

chmod +x dist/app dist/rs485

echo "构建完成："
ls -lh dist/app dist/rs485
echo
echo "请把 dist/app 和 dist/rs485 复制到 Linux 端 python_RS485 根目录，覆盖原文件。"
