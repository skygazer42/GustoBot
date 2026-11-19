#!/bin/sh
set -eu

python scripts/migrate_database.py --check
exec "$@"
