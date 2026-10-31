#!/usr/bin/env bash
# NOUT-TRIM regression: the remote DSpark suite (offload/dspark/spark/tests, written for production's package) run
# against another copy of the package. Prepares DEST as a copy of offload/dspark/spark whose remote_dspark/ is PKG's
# *.py plus the suite's hostflag.c (PKG's file set is production's, without the C source); run pytest in DEST/tests:
#   offload/nout_trim/spark_suite.sh offload/upstream_all/overlay/remote_dspark <scratch>/spark-base   # production
#   offload/nout_trim/spark_suite.sh offload/nout_trim/overlay/remote_dspark <scratch>/spark-trim      # the trim
#   (cd <scratch>/spark-trim && python3 -m pytest -q tests --basetemp <scratch>/bt)
# Compare the two pass/fail sets: the trim must not add a failure.
set -euo pipefail
cd "$(dirname "$0")/../.."
pkg=${1:?package dir}; dest=${2:?destination dir}
[ -f "$pkg/roundcore.py" ] || { echo "$pkg is not a remote_dspark package" >&2; exit 2; }
case "$dest" in /|/tmp|/tmp/*) echo "refusing destination $dest" >&2; exit 2 ;; esac
rm -rf "$dest"
mkdir -p "$dest"
cp -r offload/dspark/spark/tests offload/dspark/spark/overlay "$dest/"
mkdir "$dest/remote_dspark"
cp "$pkg"/*.py "$dest/remote_dspark/"
cp offload/dspark/spark/remote_dspark/hostflag.c "$dest/remote_dspark/"
echo "prepared $dest: $(ls "$dest/remote_dspark" | wc -l) package files from $pkg"
