#!/usr/bin/env bash
# Reset the demo so it can run again:
#   - deletes the pipeline state this tool wrote in out/ and out/demo/
#   - discards any changes under seed/repos (git restore + git clean, seed/repos only)
# Same as: python -m blast_radius reset --seed   (which also works on Windows)
set -euo pipefail
cd "$(dirname "$0")/.."
exec "${PYTHON:-python3}" -m blast_radius reset --seed "$@"
