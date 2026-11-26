#!/usr/bin/env bash
# Screenshots of the local app (http://localhost:8502) with headless Microsoft Edge: nothing to install.
# Usage: bash scripts/screenshots.sh PREFIX page1 page2 ...   (page "home" = the start page)
E="/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"
OUT="$(cd "$(dirname "$0")/.." && pwd -W)/docs/figures/v11"
prefix=$1; shift
for p in "$@"; do
  u="http://localhost:8502/"; [ "$p" != home ] && u="http://localhost:8502/$p"
  for s in "1280,800 desktop" "375,812 phone" "1280,2200 full"; do
    set -- $s
    "$E" --headless=new --disable-gpu --hide-scrollbars --virtual-time-budget=40000 --window-size=$1 --screenshot="$OUT/${prefix}_${p}_$2.png" "$u" 2>/dev/null
  done
done
