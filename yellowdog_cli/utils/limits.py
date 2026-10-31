"""
Runtime limits: batch sizes, retries, timeouts, polling intervals and
concurrency. Imports nothing.
"""

# The most rclone listings a data client command runs at once: a wildcard
# download lists each matched directory's files to record them under '--json'
# or to flatten them, and these run concurrently
DATA_CLIENT_LISTING_WORKERS = 8
# Files a data client command copies one by one, because each is renamed on
# the way (a flattened download or upload), are copied this many at a time
DATA_CLIENT_TRANSFER_WORKERS = 16
# rclone's '--transfers' for a run copying or syncing many files: on S3 a
# small file's transfer is mostly request latency, so the rate rises with the
# number at once (20,000 1 KB files: 686 a second at 32, 1,354 at 64, 2,269 at
# 128), and stops rising beyond 128
DATA_CLIENT_RCLONE_TRANSFERS = 128
# How many names a wildcard's summary line shows before 'and N more'
DATA_CLIENT_NAMES_SHOWN = 10

# The most Keyrings fetched at once to find those an Application can use
# ('yd application', 'yd doctor'): a Keyring's summary carries no accessors
KEYRING_FETCH_WORKERS = 8

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

# How long a Platform request waits for its response before failing, unless
# [common] readTimeout says otherwise (ConfigCommon.read_timeout): the SDK
# client's (ServicesSchema.readTimeout), and the CLI's direct requests'
# (ConfigCommon.request_timeout). A POST that times out is not resent (the
# Platform may still be processing it), but for a Task batch whose Tasks all
# have names (submit_with_retries())
PLATFORM_READ_TIMEOUT = 90.0  # Seconds
# How long the CLI's direct Platform requests wait to connect
RAW_CONNECT_TIMEOUT = 10.0  # Seconds

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
# '--add-to' an existing Task Group whose next Task name is taken: how long
# its Task count, which the Platform updates seconds after Tasks are added,
# is waited for to move on, and how often it is read meanwhile
TASK_COUNT_UPDATE_WAIT = 10.0  # Seconds
TASK_COUNT_UPDATE_POLL_INTERVAL = 1.0  # Seconds
# '--wait' on yd-resize and yd-compute-reprovision
CAPACITY_POLL_INTERVAL = 5.0  # Seconds
DOCTOR_DEFAULT_TIMEOUT = 10  # yd-doctor: seconds, per network call

# Tab completion's Platform lookups (yd-completion): how long a Tab may wait
# for one, how many entities it reads at most, and how long the answer is
# kept on disk for the Tabs that follow
LOOKUP_TIMEOUT_SECONDS = 2.0
LOOKUP_MAX_ITEMS = 200
# Instances and Nodes are searched one Compute Requirement or Worker Pool at
# a time: at most this many of the newest are read, within the Tab's time
LOOKUP_MAX_PARENTS = 10
COMPLETION_CACHE_SECONDS = 30

# The most in-situ substitution passes a specification is given to settle; a
# pass that changes nothing ends them. Real chains of references settle in two
# or three, so reaching this means a circular one.
VAR_SUBSTITUTION_MAX_PASSES = 10
# The variable table's text, all values together, past which resolving it
# stops repeating: only a circular reference grows it so (variable_substitution)
VARIABLE_TABLE_MAX_TEXT = 100_000

# The Tasks, Instances, Nodes or Workers 'yd list' lists by default: enough
# that an ordinary listing never reaches it, few enough that a mistaken one
# returns in seconds rather than reading tens of thousands, or millions of
# Tasks
# ('--limit 0' lists them all)
DEFAULT_LIST_LIMIT = 1000

# A name pattern given to yd-show, yd-follow or yd-wait matching more than
# this many objects is warned of (nothing is changed, so nothing is asked)
PATTERN_MATCH_WARNING = 50
