"""
Sample configurations for the live harness's offline tests. Every value is a
dummy; nothing here reaches a real account.
"""

from pathlib import Path

PLATFORM = """
[platform]
key = "app-key-1234567890"
secret = "app-secret-abcdefghijklmnop"
"""

AWS = """
[aws]
access_key_id = "AKIADUMMYDUMMYDUMMY"
secret_access_key = "dummyDummyDummyDummyDummyDummyDummyDummy"
region = "eu-west-2"
security_group_id = "sg-00000000000000000"
subnet_id = "subnet-00000000000000000"
availability_zone = "eu-west-2a"
image_id = "ami-00000000000000000"
"""

AZURE = """
[azure]
tenant_id = "00000000-0000-0000-0000-000000000001"
client_id = "00000000-0000-0000-0000-000000000002"
client_secret = "dummy-azure-client-secret"
subscription_id = "00000000-0000-0000-0000-000000000003"
region = "uksouth"
network_resource_group = "yd-dummy-rg"
network_name = "yd-dummy-vnet"
subnet_name = "yd-dummy-subnet"
image_id = "/subscriptions/00000000-0000-0000-0000-000000000003/dummy"
"""

SERVICE_ACCOUNT_KEY = (
    '{"type": "service_account", "project_id": "yd-dummy",'
    ' "private_key_id": "0123456789abcdef0123456789abcdef",'
    ' "private_key": "-----BEGIN PRIVATE KEY-----\\nMIIEdummyDummyDummyDummyDummy\\n'
    '-----END PRIVATE KEY-----\\n", "client_email": "x@yd-dummy.iam.gserviceaccount.com"}'
)

PRIVATE_KEY_PEM = "-----BEGIN PRIVATE KEY-----\nMIIEociDummyDummyDummyDummyDummy\n-----END PRIVATE KEY-----\n"


def gcp(key_file: Path) -> str:
    """
    A [gcp] section whose service-account key is the given file.
    """
    return f"""
[gcp]
service_account_key_file = "{key_file}"
project = "yd-dummy-project"
region = "europe-west2"
"""


def oci(key_file: Path) -> str:
    """
    An [oci] section whose private key is the given file.
    """
    return f"""
[oci]
tenancy_id = "ocid1.tenancy.oc1..dummy"
user_id = "ocid1.user.oc1..dummy"
fingerprint = "00:11:22:33:44:55:66:77:88:99:aa:bb:cc:dd:ee:ff"
private_key_file = "{key_file}"
region = "uk-london-1"
compartment_id = "ocid1.compartment.oc1..dummy"
subnet_id = "ocid1.subnet.oc1..dummy"
shape = "VM.Standard.E4.Flex"
image_id = "ocid1.image.oc1..dummy"
"""


def write_config(tmp_path: Path, text: str) -> dict[str, str]:
    """
    Write a configuration file, returning the environment that names it.
    """
    path = tmp_path / "system-tests.toml"
    path.write_text(text, encoding="utf-8")
    return {"YDST_CONFIG": str(path)}


def key_files(tmp_path: Path) -> tuple[Path, Path]:
    """
    The GCP service-account key and the OCI private key, as files.
    """
    gcp_key = tmp_path / "gcp.json"
    gcp_key.write_text(SERVICE_ACCOUNT_KEY, encoding="utf-8")
    oci_key = tmp_path / "oci.pem"
    oci_key.write_text(PRIVATE_KEY_PEM, encoding="utf-8")
    return gcp_key, oci_key


DATA = """
[data]
bucket = "yd-dummy-bucket"
"""

PROFILE = (
    'iam_instance_profile_arn = "arn:aws:iam::000000000000:instance-profile/yd-dummy"\n'
)
