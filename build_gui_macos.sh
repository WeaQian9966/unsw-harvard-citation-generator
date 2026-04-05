#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

pyinstaller \
  --noconfirm \
  --clean \
  --windowed \
  --name UNSWHarvardCiteGenerator \
  unsw_harvard_cite_generator_gui.py

echo "Built macOS app at: dist/UNSWHarvardCiteGenerator.app"
