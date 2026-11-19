#!/bin/sh
# Copy the result files the worker machines pushed (branches societies-w1, -w2, -w3) into this tree.
set -e
cd "$(dirname "$0")/.."
for w in w1 w2 w3; do
  if git fetch -q --depth 60 origin "societies-$w:refs/remotes/origin/societies-$w" 2>/dev/null; then
    git checkout -q "origin/societies-$w" -- "runs/$w" 2>/dev/null && echo "$w: $(ls runs/$w | grep -v -E '\.(out|log|jsonl|md)$' | wc -l) runs" || echo "$w: nothing yet"

  else
    echo "$w: no branch"
  fi
done
