#!/usr/bin/env bash
# Install nothing; run from the uploaded project root using board Python 3.10.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
exec "${PYTHON:-python3}" -m ocr_link.board_cli "$@"
