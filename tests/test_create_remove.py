import uuid

import pytest
from cli_test_helpers import shell

R = "tests/resource-examples"


@pytest.mark.system
@pytest.mark.parametrize(
    "create_args,remove_args",
    [
        (f"{R}/compute-sources.json", f"-y {R}/compute-sources.json"),
        (f"{R}/compute-template.json", f"-y {R}/compute-template.json"),
        (f"{R}/configured-worker-pool.json", f"-y {R}/configured-worker-pool.json"),
        (f"{R}/image-family.json", f"-y {R}/image-family.json"),
        (
            f"{R}/keyring.json {R}/credential.json",
            f"-y {R}/credential.json {R}/keyring.json",
        ),
        (f"{R}/namespace.json", f"-y {R}/namespace.json"),
        (f"{R}/allowances.json", f"-My {R}/allowances.json"),
        (f"{R}/stringattribute.json", f"-y {R}/stringattribute.json"),
        (f"{R}/numericattribute.json", f"-y {R}/numericattribute.json"),
        (f"-y {R}/namespace_policies.json", f"-y {R}/namespace_policies.json"),
        (f"-y {R}/group.json", f"-y {R}/group.json"),
        (f"-y {R}/application.json", f"-y {R}/application.json"),
        (f"-y {R}/user.json", f"-y {R}/user.json"),
        (
            f"-y {R}/application-with-keyring.json",
            f"-y {R}/application-with-keyring.json",
        ),
    ],
    ids=[
        "source_template",
        "requirement_template",
        "configured_worker_pool",
        "image_family",
        "keyring_and_credential",
        "namespace",
        "allowance",
        "string_attribute",
        "numeric_attribute",
        "namespace_policy",
        "group",
        "application",
        "user",
        "application_with_keyring_grant",
    ],
)
def test_create_remove(create_args, remove_args):
    suffix = uuid.uuid4().hex[:8]
    env = f"YD_VAR_SUFFIX={suffix}"
    assert shell(f"{env} yd-create {create_args}").exit_code == 0
    assert shell(f"{env} yd-remove {remove_args}").exit_code == 0
