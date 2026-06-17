#!/usr/bin/env bash
set -euo pipefail

DISPLAY="${DISPLAY:-:0}" xset q >/dev/null 2>&1
pgrep -f x11vnc >/dev/null 2>&1
pgrep -f websockify >/dev/null 2>&1
