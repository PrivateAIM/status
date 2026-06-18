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
POLL_INTERVAL_SECONDS = 3.0  # Build / distribution / execution poll cadence
BUCKET_POLL_INTERVAL_SECONDS = 1.0  # CODE bucket creation poll cadence
UPLOAD_SETTLE_SECONDS = 2.0  # Settle time after upload before listing files
ANALYSIS_RETRY_DELAY_SECONDS = 2.0  # Backoff between transient analysis 404 retries
ANALYSIS_RETRY_ATTEMPTS = 5  # Retries for a transient analysis 404
STALE_ANALYSIS_AGE_BUFFER_SECONDS = 60.0  # Margin over a full run before stale

# Threshold for a single pair-run's end-to-end latency.
LATENCY_LIMIT_SECONDS = (
    2 * TIMEOUT_SHORT_SECONDS + 2 * TIMEOUT_MEDIUM_SECONDS + TIMEOUT_LONG_SECONDS
)

# Only active analyses older than a full run budget are considered stale and
# deleted during cleanup. This protects the in-flight parallel jobs of a
# concurrently running (or overlapping) execution from being torn down.
STALE_ANALYSIS_MIN_AGE_SECONDS = LATENCY_LIMIT_SECONDS + STALE_ANALYSIS_AGE_BUFFER_SECONDS

# Pipeline steps measured inside each per-node pair run. "login" is measured
# once in the shared phase and is not part of a pair run.
PAIR_STEP_KEYS = ["upload", "distribute", "execute", "results", "latency"]
