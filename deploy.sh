#!/usr/bin/env bash
# deploy.sh — Sync V2-enabled gateway code to /srv/agent-gateway/ and restart service.
#
# Usage:
#   ./deploy.sh              # dry-run (show what would change)
#   ./deploy.sh --apply      # actually sync and restart
#   ./deploy.sh --force      # skip safety checks

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_DIR="/srv/agent-gateway"
SERVICE_NAME="agent-gateway.service"
VENV_SRC="$REPO_DIR/gateway/venv"
VENV_DST="$SERVICE_DIR/venv"

DRY_RUN=true
FORCE=false

# Parse args
for arg in "$@"; do
    case "$arg" in
        --apply) DRY_RUN=false ;;
        --force) FORCE=true ;;
    esac
done

echo "=== AFK Gateway Deploy ==="
echo "  Source:      $REPO_DIR/gateway"
echo "  Target:      $SERVICE_DIR"
echo "  Mode:        $([ "$DRY_RUN" = true ] && echo 'DRY-RUN' || echo 'LIVE')"
echo ""

# Safety: ensure source repo is clean
if [ "$DRY_RUN" = false ] && [ "$FORCE" = false ]; then
    cd "$REPO_DIR"
    if ! git diff --quiet HEAD -- gateway/; then
        echo "❌ Repo has uncommitted changes in gateway/. Commit or stash first."
        echo "   Use --force to override."
        exit 1
    fi
    echo "✅ Repo is clean."
fi

# Safety: check target exists
if [ ! -d "$SERVICE_DIR" ]; then
    echo "❌ Target directory $SERVICE_DIR does not exist."
    exit 1
fi

echo ""
echo "--- Step 1: Sync gateway package (rsync) ---"

RSYNC_OPTS="-av --delete --exclude=__pycache__ --exclude=.pytest_cache --exclude=*.pyc --exclude=.git --exclude=venv --exclude=gateway.db"

if [ "$DRY_RUN" = true ]; then
    rsync -n $RSYNC_OPTS "$REPO_DIR/gateway/" "$SERVICE_DIR/"
    echo ""
    echo "--- Step 2: Sync test files ---"
    rsync -n $RSYNC_OPTS \
        "$REPO_DIR/gateway/tests/" "$SERVICE_DIR/tests/"
else
    rsync $RSYNC_OPTS "$REPO_DIR/gateway/" "$SERVICE_DIR/"
    echo ""
    echo "--- Step 2: Sync test files ---"
    rsync $RSYNC_OPTS \
        "$REPO_DIR/gateway/tests/" "$SERVICE_DIR/tests/"
    echo "✅ Files synced."
fi

echo ""
echo "--- Step 3: Check venv ---"
if [ "$DRY_RUN" = false ]; then
    if [ -d "$VENV_DST" ]; then
        echo "✅ Virtual environment exists at $VENV_DST"
    else
        # Check if source venv is usable
        if [ -f "$VENV_SRC/pyvenv.cfg" ]; then
            echo "⚠️  Target venv missing. Copying from source..."
            cp -a "$VENV_SRC" "$VENV_DST"
            echo "✅ Virtual environment copied."
        else
            echo "❌ No venv at source ($VENV_SRC) or target ($VENV_DST). Create one."
            exit 1
        fi
    fi
fi

echo ""
echo "--- Step 4: Restart service ---"
if [ "$DRY_RUN" = true ]; then
    echo "  Would run: sudo systemctl restart $SERVICE_NAME"
    echo "  Would run: sudo systemctl status $SERVICE_NAME --no-pager"
else
    # Fix permissions if needed
    chown -R debug:debug "$SERVICE_DIR" 2>/dev/null || true

    echo "  Restarting $SERVICE_NAME..."
    sudo systemctl restart "$SERVICE_NAME"
    sleep 3

    # Check health
    echo "  Checking health..."
    HEALTH=$(curl -s --connect-timeout 5 http://127.0.0.1:3344/health 2>/dev/null || echo "FAILED")
    if [ "$HEALTH" = '{"status":"ok"}' ]; then
        echo "✅ Gateway healthy after restart."
    else
        echo "⚠️  Health check result: $HEALTH"
        echo "  Running: sudo systemctl status $SERVICE_NAME --no-pager"
        sudo systemctl status "$SERVICE_NAME" --no-pager || true
    fi
fi

echo ""
echo "=== Deploy $([ "$DRY_RUN" = true ] && echo 'dry-run' || echo 'complete') ==="
