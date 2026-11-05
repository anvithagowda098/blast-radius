#!/usr/bin/env bash
# Run the whole Blast Radius pipeline offline and print what each agent would post.
# Same as: python -m blast_radius demo   (which also works on Windows)
set -euo pipefail
cd "$(dirname "$0")/.."
exec "${PYTHON:-python3}" -m blast_radius demo "$@"
