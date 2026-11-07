#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 abel0x <https://github.com/abel0x>
# Run "./steamledger.sh" for the menu, or "./steamledger.sh <command>".
cd "$(dirname "$0")" || exit 1
for python in python3 python; do
    if command -v "$python" >/dev/null 2>&1; then
        exec "$python" -m steamledger "$@"
    fi
done
echo "Python 3.10 or newer is required: https://www.python.org/downloads/" >&2
exit 1
