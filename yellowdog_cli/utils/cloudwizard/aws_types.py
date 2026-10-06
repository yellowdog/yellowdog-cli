"""
Types for AWS things.
"""

from dataclasses import dataclass


@dataclass(order=True)
class AWSSecurityGroup:
    name: str
    id: str


@dataclass(order=True)
class AWSAvailabilityZone:
    region: str
    az: str
    default_subnet_id: str
    default_sec_grp: AWSSecurityGroup | None


@dataclass
class AWSAccessKey:
    access_key_id: str
    secret_access_key: str | None = None


@dataclass
class AWSUser:
    arn: str
    user_id: str
