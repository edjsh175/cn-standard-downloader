#!/bin/sh
set -eu

mkdir -p /app/artifacts /app/.tmp /app/temp_step2 /app/debug_output /app/pdf

exec python /app/run_worker.py
