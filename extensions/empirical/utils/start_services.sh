#!/bin/bash
# Start persistent data services for the pipeline.
# Run this once at the start of each Claude session:
#   bash code/utils/start_services.sh
#
# Starts the WRDS server if credentials are configured.
# Safe to run multiple times — checks for existing server.

set -e
cd "$(dirname "$0")/../.."

load_env_file() {
    local env_file="$1"
    local preserve_existing="${2:-0}"
    [ -f "$env_file" ] || return 0
    while IFS='=' read -r key value; do
        [[ "$key" =~ ^[[:space:]]*# || -z "$key" ]] && continue
        [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
        if [ "$preserve_existing" = "1" ] && [ -n "$(printenv "$key" 2>/dev/null || true)" ]; then
            continue
        fi
        value="${value%$'\r'}"
        export "$key=$value"
    done < "$env_file"
}

# Prefer host-scoped credentials outside the project workspace. Project .env is
# retained for backwards compatibility with older deployments.
load_env_file "$HOME/.zeropaper/env"
load_env_file ".env" 1

# Start WRDS server if credentials are configured
if [ -n "$WRDS_USER" ] && [ "$WRDS_USER" != "your-username" ] && [ -n "$WRDS_PASS" ] && [ "$WRDS_PASS" != "your-password" ]; then
    # Check if ANY wrds server is already responding on the port (could be from another project)
    if PYTHONPATH=code python3 -c "from utils.wrds_client import wrds_ping; exit(0 if wrds_ping() else 1)" 2>/dev/null; then
        echo "WRDS server already running (reusing existing connection)"
    else
        echo "Starting WRDS server (approve Duo when prompted)..."
        # wrds_client redirects server output to code/utils/wrds_server.log and
        # handles legacy pre-token server shutdown before starting a fresh one.
        PGPASSWORD="$WRDS_PASS" PYTHONPATH=code python3 -c "from utils.wrds_client import wrds_start; wrds_start()" \
            || echo "⚠ WRDS server did not start within 2 min (check Duo)"
    fi
else
    echo "WRDS: credentials not configured (prefer ~/.zeropaper/env; project .env fallback supported), skipping"
fi

echo "Services ready."
