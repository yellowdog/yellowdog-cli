"""
Runtime limits: batch sizes, retries, timeouts, polling intervals and
concurrency. Imports nothing.
"""

# The most rclone listings a data client command runs at once: a wildcard
# download lists each matched directory's files to record them under '--json'
# or to flatten them, and these run concurrently
DATA_CLIENT_LISTING_WORKERS = 8

# The MCP server's default bound on a tool call, since a client gives up on one
# after a fixed time; yd_follow's is shorter, its result being the events
# collected in that time
MCP_TOOL_TIMEOUT_SECONDS = 300
MCP_FOLLOW_TIMEOUT_SECONDS = 60

# The longest name the Platform accepts; format_yd_name() cuts one to it
YD_NAME_MAX_LENGTH = 60

# yd-submit's Task batches
TASK_BATCH_SIZE_DEFAULT = 1_000
DEFAULT_PARALLEL_TASK_BATCH_UPLOAD_THREADS = 1
MAX_BATCH_SUBMIT_ATTEMPTS = 4  # Initial attempt plus retries
BATCH_SUBMIT_RETRY_DELAY = 2.0  # Seconds before the first retry, doubled for each

# (connect, read) for the CLI's direct Platform requests ('--json-raw', and
# yd-provision's and yd-instantiate's raw paths): the read allows for a large
# Task batch, while a silently dropped connection no longer hangs forever
RAW_REQUEST_TIMEOUT = (10.0, 300.0)  # Seconds

CR_MAX_INSTANCES = (
    10_000  # This is enforced by the platform (MAX_WORKER_POOL_NODE_COUNT)
)

# Reconnecting a dropped event stream: the first wait, doubling to the most,
# for at most an outage this long before giving up
EVENT_STREAM_RETRY_INTERVAL = 5.0  # Seconds
EVENT_STREAM_MAX_RETRY_INTERVAL = 30.0  # Seconds
EVENT_STREAM_MAX_OUTAGE = 300.0  # Seconds
# The wait before reconnecting a stream closed while its entity is still live
EVENT_STREAM_RECONNECT_DELAY = 1.0  # Seconds
EVENT_STREAM_CONNECT_TIMEOUT = 10.0  # Seconds
# Generous read timeout: a silently dropped connection must not block the
# event stream forever; a timeout during a quiet period just reconnects
EVENT_STREAM_READ_TIMEOUT = 300.0  # Seconds

NODE_ACTION_QUEUE_POLL_INTERVAL = 5.0  # Seconds
# '--wait' on yd-resize and yd-compute-reprovision
CAPACITY_POLL_INTERVAL = 5.0  # Seconds
DOCTOR_DEFAULT_TIMEOUT = 10  # yd-doctor: seconds, per network call

# The most in-situ substitution passes a specification is given to settle; a
# pass that changes nothing ends them. Real chains of references settle in two
# or three, so reaching this means a circular one.
VAR_SUBSTITUTION_MAX_PASSES = 10
