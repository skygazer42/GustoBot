#!/bin/sh
set -eu

exec sh "$(dirname "$0")/backend_entrypoint.sh" "$@"
