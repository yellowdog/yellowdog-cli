"""
The data client's remotes, built from [aws], so that [data] need hold only
the bucket. The local remote carries the AWS keys and is a secret, given to
'yd' as YD_DATA_CLIENT_REMOTE and masked; the Task remote is keyless
(env_auth), since it travels to the Platform inside a Work Requirement, and
works on an instance through its IAM instance profile.
"""

from __future__ import annotations

from harness.config import LiveConfig

DATA_LABEL = "[data] the S3 remote built from [aws]"


def local_remote(config: LiveConfig) -> str | None:
    aws = config.providers.get("aws")
    if config.data is None or aws is None:
        return None
    return (
        f":s3,provider=AWS,env_auth=false,region={aws['region']},"
        f"access_key_id={aws['access_key_id']},"
        f"secret_access_key={aws['secret_access_key']}"
    )


def task_remote(config: LiveConfig) -> str | None:
    aws = config.providers.get("aws")
    if config.data is None or aws is None:
        return None
    return f":s3,provider=AWS,env_auth=true,region={aws['region']}"


def unavailable(config: LiveConfig) -> str | None:
    """
    Why the data scenarios cannot run, or None when they can.
    """
    if config.data is None:
        return "no [data] section"
    if config.primary != "aws":
        return f"the primary is {config.primary}; the data scenarios need AWS"
    if not config.providers["aws"]["iam_instance_profile_arn"]:
        return "[aws] has no iam_instance_profile_arn, which Tasks need to reach S3"
    return None
