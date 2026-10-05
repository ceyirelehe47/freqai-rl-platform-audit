#!/bin/bash
set -u
echo "=== mounts for /mnt/f ==="
mount | grep -E "/mnt/f " || true
echo "=== symlink test on /mnt/f ==="
T=/mnt/f/trading/local/rcf_r2_review/symtest
rm -rf "$T"; mkdir -p "$T"
echo hello > "$T/target.txt"
if ln -s target.txt "$T/link.txt" 2>err.txt; then
  ls -la "$T"; cat "$T/link.txt" || echo "READ VIA LINK FAILED"
else
  echo "SYMLINK FAILED:"; cat err.txt
fi
rm -f err.txt
echo "=== symlink test on linux fs (/home/cryptorl) ==="
H=/home/cryptorl/rcf_r2_probe_symtest
rm -rf "$H"; mkdir -p "$H"
echo hello > "$H/target.txt"
ln -s target.txt "$H/link.txt" && ls -la "$H" && cat "$H/link.txt"
rm -rf "$H" "$T"
