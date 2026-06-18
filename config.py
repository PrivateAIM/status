import os

# ---------------------------------------------------------
# Endpoints & credentials
# ---------------------------------------------------------
AUTH_URL = "https://auth.staging.privateaim.net"
CORE_URL = "https://core.staging.privateaim.net"
STORAGE_URL = "https://storage.staging.privateaim.net"

USERNAME = os.environ["FLAME_USERNAME"]
PASSWORD = os.environ["FLAME_PASSWORD"]
# Unset GitHub secrets expand to empty strings rather than missing env vars.
assert USERNAME, "FLAME_USERNAME is empty - set the repository secret."
assert PASSWORD, "FLAME_PASSWORD is empty - set the repository secret."

# ---------------------------------------------------------
# Targets
# ---------------------------------------------------------
TARGET_NODE_NAMES = ["aggregator-1", "default-1", "default-2"]
PROJECT_NAME = "health-check"
CONNECTION_SCRIPT_NAME = "00_test_connection.py"

# ---------------------------------------------------------
# Timeouts & poll cadences (seconds)
# ---------------------------------------------------------
TIMEOUT_SHORT_SECONDS = 10.0  # Authentication
TIMEOUT_MEDIUM_SECONDS = 120.0  # Build and distribution
TIMEOUT_LONG_SECONDS = 240.0  # Execution

TIMEOUT_BUCKET_SECONDS = 60.0  # Wait for CODE bucket provisioning
TIMEOUT_RESULTS_SECONDS = 60.0  # Streaming download of the result tarball
POLL_INTERVAL_SECONDS = 3.0  # Build / distribution / execution poll cadence
BUCKET_POLL_INTERVAL_SECONDS = 1.0  # CODE bucket creation poll cadence
UPLOAD_SETTLE_SECONDS = 2.0  # Settle time after upload before listing files
ANALYSIS_RETRY_DELAY_SECONDS = 2.0  # Backoff between transient analysis 404 retries
ANALYSIS_RETRY_ATTEMPTS = 5  # Retries for a transient analysis 404
STALE_ANALYSIS_MAX_AGE_SECONDS = 3600.0  # Delete analyses older than this (1 hour)

# Threshold for a single pair-run's end-to-end latency: the sum of the worst-
# case per-step budgets that make up a pair run - the CODE-bucket wait of the
# upload, the build and distribution phases (each a full TIMEOUT_MEDIUM),
# execution, and the result download. Login is measured in the shared phase and
# is not part of a pair run.
LATENCY_LIMIT_SECONDS = (
    TIMEOUT_BUCKET_SECONDS
    + 2 * TIMEOUT_MEDIUM_SECONDS
    + TIMEOUT_LONG_SECONDS
    + TIMEOUT_RESULTS_SECONDS
)

# Pipeline steps measured inside each per-node pair run. "login" is measured
# once in the shared phase and is not part of a pair run.
PAIR_STEP_KEYS = ["upload", "distribute", "execute", "results", "latency"]
