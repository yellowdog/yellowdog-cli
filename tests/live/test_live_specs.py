"""
The live suite's specifications, loaded offline through the CLI's own loader
with a run's variables, as 'yd resource create' would load them, and checked
against the resources schema as '--validate' checks them.
"""

import hashlib
import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from harness import config
from harness.config import load_live_config
from harness.run import INSTALLER, SPECS, Run
from live_samples import AWS, AZURE, PLATFORM, gcp, oci, write_config

# The jsonnet extra; tox installs it, a bare environment may not. (Not
# resource_corpus.require_jsonnet(): tests/ is not on sys.path when only
# tests/live is collected.)
pytest.importorskip("_jsonnet")


@pytest.fixture(autouse=True)
def _no_default_file(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DEFAULT_PATH", tmp_path / "absent.toml")


def _run(tmp_path, extra: str = "", aws_extra: str = "", oci_extra: str = "") -> Run:
    text = (
        PLATFORM
        + AWS
        + aws_extra
        + AZURE
        + extra
        + gcp()
        + oci()
        + oci_extra
        + '[run]\nprimary_provider = "aws"\n'
    )
    return Run.start(load_live_config(write_config(tmp_path, text)), tmp_path / "runs")


@contextmanager
def _variables(run: Run, **extra: str):
    """
    The run's variables (and its namespace and tag, and any extra) forced
    into the CLI's substitutions, put back afterwards.
    """
    from yellowdog_cli.utils.variable_substitution import (
        VARIABLE_SUBSTITUTIONS,
        _update_and_resolve_substitutions,
    )

    subs = {
        **run.variables(),
        **run.secret_variables(),
        "namespace": run.namespace,
        "tag": run.tag,
        **extra,
    }
    previous = {key: VARIABLE_SUBSTITUTIONS.get(key) for key in subs}
    _update_and_resolve_substitutions({**VARIABLE_SUBSTITUTIONS, **subs})
    try:
        yield
    finally:
        merged = dict(VARIABLE_SUBSTITUTIONS)
        for key, value in previous.items():
            if value is None:
                merged.pop(key, None)
            else:
                merged[key] = value
        _update_and_resolve_substitutions(merged)


def _load(run: Run, files, validate: bool = False) -> list[dict]:
    """
    Load the files as 'yd resource create' does, with the run's variables.
    With 'validate', as '--validate' does: check them against the schema and
    exit.
    """
    from yellowdog_cli.utils.load_resources import load_resource_specifications

    with _variables(run):
        return load_resource_specifications(
            SimpleNamespace(
                resource_specifications=[str(path) for path in files],
                jsonnet_dry_run=False,
                validate=validate,
                no_resequence=False,
            )
        )


def _load_one(run: Run, name: str, family: str, provider: str) -> dict:
    """
    One Worker Pool or Work Requirement specification, loaded as 'yd wp
    provision' or 'yd wr submit' loads it, for one provider.
    """
    from yellowdog_cli.utils.specs.loading import load_specification
    from yellowdog_cli.utils.specs.schema import Family
    from yellowdog_cli.utils.variable_syntax import (
        WP_VARIABLES_POSTFIX,
        WP_VARIABLES_PREFIX,
    )

    pool = family == "worker-pool"
    with _variables(run, provider=provider):
        return load_specification(
            str(SPECS / name),
            name,
            family=Family(family),
            prefix=WP_VARIABLES_PREFIX if pool else "",
            postfix=WP_VARIABLES_POSTFIX if pool else "",
            other_extensions_as_json=pool,
        )


def _by_type(resources: list[dict], resource_type: str) -> list[dict]:
    return [r for r in resources if r["resource"] == resource_type]


def test_the_specifications_are_valid_against_the_schema(tmp_path):
    run = _run(tmp_path)
    with pytest.raises(SystemExit) as exited:
        _load(run, [SPECS / "namespace.jsonnet", *run.spec_files()], validate=True)
    assert exited.value.code == 0


def test_every_provider_gets_a_credential_source_and_requirement_template(tmp_path):
    run = _run(tmp_path)
    resources = _load(run, run.spec_files())
    assert len(_by_type(resources, "Keyring")) == 1
    assert len(_by_type(resources, "Allowance")) == 1
    assert len(_by_type(resources, "Credential")) == 4
    assert {
        r["source"]["name"] for r in _by_type(resources, "ComputeSourceTemplate")
    } == {run.source_template(p) for p in ("aws", "azure", "gcp", "oci")}
    assert {r["name"] for r in _by_type(resources, "ComputeRequirementTemplate")} == {
        run.requirement_template(p) for p in ("aws", "azure", "gcp", "oci")
    }


def test_nothing_is_left_unsubstituted(tmp_path):
    run = _run(tmp_path)
    assert "{{" not in json.dumps(_load(run, run.spec_files()))


def test_the_keyring_comes_before_its_credentials(tmp_path):
    run = _run(tmp_path)
    types = [r["resource"] for r in _load(run, run.spec_files())]
    assert types.index("Keyring") < types.index("Credential")
    assert types.index("ComputeSourceTemplate") < types.index(
        "ComputeRequirementTemplate"
    )


def test_a_source_names_its_credential_in_the_runs_keyring(tmp_path):
    run = _run(tmp_path)
    (aws,) = [
        r["source"]
        for r in _by_type(_load(run, run.spec_files()), "ComputeSourceTemplate")
        if r["source"]["name"] == run.source_template("aws")
    ]
    assert aws["credential"] == f"{run.keyring}/{run.credential_name('aws')}"


def _source(run: Run, provider: str) -> dict:
    (source,) = [
        r["source"]
        for r in _by_type(_load(run, run.spec_files()), "ComputeSourceTemplate")
        if r["source"]["name"] == run.source_template(provider)
    ]
    return source


# Each provider's configured image, its key, its region and the Platform's
# name for the provider, as live_samples.py configures them
_IMAGES = {
    "aws": ("image_id", "ami-00000000000000000", "eu-west-2", "AWS"),
    "azure": (
        "image_id",
        "/subscriptions/00000000-0000-0000-0000-000000000003/dummy",
        "uksouth",
        "AZURE",
    ),
    "gcp": (
        "image",
        "projects/ubuntu-os-cloud/global/images/family/ubuntu-2404-lts-amd64",
        "europe-west2",
        "GOOGLE",
    ),
    "oci": ("image_id", "ocid1.image.oc1..dummy", "uk-london-1", "OCI"),
}


@pytest.mark.parametrize("provider", ["aws", "azure", "gcp", "oci"])
def test_each_provider_has_an_image_family_holding_its_configured_image(
    tmp_path, provider
):
    run = _run(tmp_path)
    (family,) = [
        r
        for r in _by_type(_load(run, run.spec_files()), "MachineImageFamily")
        if r["name"] == run.image_family(provider)
    ]
    assert family["namespace"] == run.namespace
    (group,) = family["imageGroups"]
    (image,) = group["images"]
    _, image_id, region, platform_provider = _IMAGES[provider]
    assert image["providerImageId"] == image_id
    assert image["provider"] == platform_provider
    assert image["regions"] == [region]
    assert family["osType"] == group["osType"] == image["osType"] == "LINUX"


@pytest.mark.parametrize("provider", ["aws", "azure", "gcp", "oci"])
def test_each_providers_template_names_its_image_family(tmp_path, provider):
    run = _run(tmp_path)
    key = "image" if provider == "gcp" else "imageId"
    assert (
        _source(run, provider)[key] == f"{run.namespace}/{run.image_family(provider)}"
    )


def test_the_aws_subnet_and_its_zone_are_given(tmp_path):
    source = _source(_run(tmp_path), "aws")
    assert source["subnetId"] == "subnet-00000000000000000"
    assert source["availabilityZone"] == "eu-west-2a"


@pytest.mark.parametrize("provider", ["aws", "azure", "gcp", "oci"])
def test_every_instance_gets_a_public_ip(tmp_path, provider):
    # The Agent reaches the Platform over the internet
    assert _source(_run(tmp_path), provider)["assignPublicIp"] is True


def test_an_unset_optional_value_is_left_out(tmp_path):
    assert "sshKey" not in _source(_run(tmp_path), "azure")


def test_a_set_optional_value_is_kept(tmp_path):
    # AZURE ends inside the [azure] table, so the line joins it
    run = _run(tmp_path, extra='ssh_public_key = "ssh-ed25519 AAAA test"\n')
    assert _source(run, "azure")["sshKey"] == "ssh-ed25519 AAAA test"


def test_the_aws_instance_profile_is_optional(tmp_path):
    assert "iamInstanceProfileArn" not in _source(_run(tmp_path), "aws")


def test_the_aws_instance_profile_is_given_when_set(tmp_path):
    arn = "arn:aws:iam::000000000000:instance-profile/yd-dummy"
    run = _run(tmp_path, aws_extra=f'iam_instance_profile_arn = "{arn}"\n')
    assert _source(run, "aws")["iamInstanceProfileArn"] == arn


def test_azures_credential_takes_the_configured_key(tmp_path):
    run = _run(tmp_path)
    credentials = {
        r["credential"]["name"]: r["credential"]
        for r in _by_type(_load(run, run.spec_files()), "Credential")
    }
    azure = credentials[run.credential_name("azure")]
    assert azure["key"] == "dummy-azure-client-secret"
    assert azure["clientId"] == "00000000-0000-0000-0000-000000000002"
    assert azure["tenantId"] == "00000000-0000-0000-0000-000000000001"
    assert azure["subscriptionId"] == "00000000-0000-0000-0000-000000000003"


def test_azures_source_takes_its_network_from_the_configuration(tmp_path):
    source = _source(_run(tmp_path), "azure")
    assert source["networkResourceGroupName"] == "yd-dummy-rg"
    assert source["networkName"] == "yd-dummy-vnet"
    assert source["subnetName"] == "yd-dummy-subnet"


def _credential(run: Run, provider: str) -> dict:
    (credential,) = [
        r["credential"]
        for r in _by_type(_load(run, run.spec_files()), "Credential")
        if r["credential"]["name"] == run.credential_name(provider)
    ]
    return credential


def test_ocis_source_takes_its_shape_alone(tmp_path):
    source = _source(_run(tmp_path), "oci")
    assert source["shape"] == "VM.Standard.E4.Flex"
    assert not {"flexOcpus", "flexRam", "availabilityDomain"} & set(source)


def test_oci_takes_no_flex_sizes_or_availability_domain(tmp_path):
    text = (
        PLATFORM
        + oci()
        + 'flex_ocpus = 1.0\nflex_ram = 8.0\navailability_domain = "AD-1"\n'
    )
    # Retired: ignored, each with a warning
    loaded = load_live_config(write_config(tmp_path, text))
    assert [w.split(" is ")[0] for w in loaded.warnings] == [
        "[oci] flex_ocpus",
        "[oci] flex_ram",
        "[oci] availability_domain",
    ]
    assert not {"flex_ocpus", "flex_ram", "availability_domain"} & set(
        loaded.providers["oci"].values
    )


def test_ocis_credential_takes_every_value_inline(tmp_path):
    credential = _credential(_run(tmp_path), "oci")
    assert credential["userId"] == "ocid1.user.oc1..dummy"
    assert credential["tenantId"] == "ocid1.tenancy.oc1..dummy"
    assert (
        credential["fingerprint"] == "00:11:22:33:44:55:66:77:88:99:aa:bb:cc:dd:ee:ff"
    )
    assert credential["privateKey"].startswith("-----BEGIN PRIVATE KEY-----")
    assert "passphrase" not in credential


def test_ocis_credential_takes_a_passphrase_when_set(tmp_path):
    # OCI is the last section, so the line joins it
    run = _run(tmp_path, oci_extra='passphrase = "dummy-oci-passphrase"\n')
    assert _credential(run, "oci")["passphrase"] == "dummy-oci-passphrase"


def test_multi_line_and_json_secrets_arrive_intact(tmp_path):
    run = _run(tmp_path)
    credentials = {
        r["credential"]["name"]: r["credential"]
        for r in _by_type(_load(run, run.spec_files()), "Credential")
    }
    secrets = run.secret_variables()
    assert (
        credentials[run.credential_name("gcp")]["serviceAccountKeyJson"]
        == (secrets["secret_gcp_service_account_key_json"])
    )
    assert (
        credentials[run.credential_name("oci")]["privateKey"]
        == (secrets["secret_oci_private_key"])
    )


def test_the_allowance_caps_hours_as_a_number(tmp_path):
    run = _run(tmp_path)
    (allowance,) = _by_type(_load(run, run.spec_files()), "Allowance")
    assert allowance["allowedHours"] == 4
    assert allowance["tag"] == run.tag
    assert allowance["description"] == run.allowance_description


def test_the_namespace_spec_names_the_runs_namespace(tmp_path):
    run = _run(tmp_path)
    (namespace,) = _load(run, [SPECS / "namespace.jsonnet"])
    assert namespace["name"] == "yd-cli-system-tests"


def test_the_keyring_names_its_namespace_as_the_sweep_reads_it(tmp_path):
    from harness.lifecycle import KEYRING_NAMESPACE

    run = _run(tmp_path)
    (keyring,) = _by_type(_load(run, run.spec_files()), "Keyring")
    assert keyring["description"].endswith(
        KEYRING_NAMESPACE.format(namespace=run.namespace)
    )


def _load_one_wr(run: Run, name: str, **variables: str) -> dict:
    extra = dict(variables)
    if run.config.data is not None:
        extra["dataClient.bucket"] = run.config.data["bucket"]
        extra["dataClient.prefix"] = f"{run.namespace}/{run.tag}"
    from yellowdog_cli.utils.specs.loading import load_specification
    from yellowdog_cli.utils.specs.schema import Family

    with _variables(run, **extra):
        return load_specification(
            str(SPECS / name), name, family=Family.WORK_REQUIREMENT
        )


# Upstream: python-examples-demos/userdata-scripts/install-agent.sh at b811a73
INSTALLER_SHA256 = "c4eacd0358b9fa981cef0ef1edd36ea69fd4739707aafd0ac0242ee03b4e3699"


def test_the_installer_is_the_pinned_upstream_script():
    assert hashlib.sha256(INSTALLER.read_bytes()).hexdigest() == INSTALLER_SHA256


@pytest.mark.parametrize("provider", ["aws", "azure", "gcp", "oci"])
def test_the_pool_uses_the_providers_static_template_and_worker_tag(tmp_path, provider):
    run = _run(tmp_path)
    pool = _load_one(run, "pool.jsonnet", "worker-pool", provider)
    usage, properties = pool["requirementTemplateUsage"], pool["provisionedProperties"]
    assert (
        usage["templateId"] == f"{run.namespace}/{run.requirement_template(provider)}"
    )
    assert usage["requirementName"] == run.pool_name(provider)
    assert usage["requirementNamespace"] == run.namespace
    assert usage["requirementTag"] == run.tag
    assert usage["targetInstanceCount"] == 1
    assert properties["workerTag"] == run.worker_tag(provider)


def test_the_pool_shuts_itself_down_when_idle(tmp_path):
    properties = _load_one(_run(tmp_path), "pool.jsonnet", "worker-pool", "aws")[
        "provisionedProperties"
    ]
    for key in ("idleNodeShutdown", "idlePoolShutdown"):
        assert properties[key]["enabled"] is True, key
        assert properties[key]["timeout"] == "PT30M", key


@pytest.mark.parametrize("provider", ["aws", "gcp"])
def test_the_smoke_work_requirement_runs_on_the_providers_workers(tmp_path, provider):
    run = _run(tmp_path)
    smoke = _load_one(run, "smoke-wr.jsonnet", "work-requirement", provider)
    assert smoke["name"] == run.name(provider, "smoke")
    assert smoke["workerTags"] == [run.worker_tag(provider)]
    assert smoke["taskType"] == "bash"
    ((task,),) = [group["tasks"] for group in smoke["taskGroups"]]
    assert task["arguments"][0] == "-c"
    assert f"ydst smoke {run.run_id} {provider}" in task["arguments"][1]


def test_the_actions_pool_is_two_nodes_of_two_workers(tmp_path):
    run = _run(tmp_path)
    pool = _load_one(run, "actions-pool.jsonnet", "worker-pool", run.config.primary)
    usage, properties = pool["requirementTemplateUsage"], pool["provisionedProperties"]
    assert (
        usage["templateId"]
        == f"{run.namespace}/{run.requirement_template(run.config.primary)}"
    )
    assert usage["requirementName"] == run.actions_pool_name()
    assert usage["targetInstanceCount"] == 2
    assert properties["maxNodes"] == 3
    assert properties["createNodeWorkers"] == {
        "targetCount": 2,
        "targetType": "PER_NODE",
    }
    assert properties["workerTag"] == run.actions_worker_tag()
    assert properties["idlePoolShutdown"]["timeout"] == "PT30M"


def test_the_work_requirement_runs_its_tasks_on_the_given_tag(tmp_path):
    run = _run(tmp_path)
    spec = _load_one_wr(
        run, "work-wr.jsonnet", wr="life", worker_tag="t-1", seconds="7"
    )
    assert spec["name"] == f"{run.run_id}-life"
    assert spec["workerTags"] == ["t-1"]
    assert [len(g["tasks"]) for g in spec["taskGroups"]] == [2, 2]
    assert spec["taskGroups"][0]["tasks"][0]["arguments"] == ["-c", "sleep 7; exit 0"]


def test_the_task_io_work_requirement_reads_and_writes_through_the_task_remote(
    tmp_path,
):
    from live_samples import AWS, DATA, PLATFORM, PROFILE, write_config

    config = load_live_config(write_config(tmp_path, PLATFORM + AWS + PROFILE + DATA))
    run = Run.start(config, tmp_path / "runs")
    spec = _load_one_wr(run, "task-io-wr.jsonnet", worker_tag="t-1")
    (task,) = spec["taskGroups"][0]["tasks"]
    remote = ":s3,provider=AWS,env_auth=true,region=eu-west-2"
    prefix = f"{remote}:yd-dummy-bucket/{run.namespace}/{run.run_id}/task-io"
    # The Platform requires 'rclone:' on the remote side and 'local:' on the
    # Task's (live run ydst-2610131521-hh32: "must start with 'rclone:'")
    assert spec["taskDataInputs"] == [
        {"source": f"rclone:{prefix}/input.bin", "destination": "local:input.bin"}
    ]
    assert spec["taskDataOutputs"] == [
        {
            "source": "local:output.txt",
            "destination": f"rclone:{prefix}/output.txt",
            "alwaysUpload": True,
        }
    ]
    assert task["name"] == "hash"


def test_the_task_io_paths_resolve_through_the_clis_own_configuration(tmp_path):
    # 'yd wr submit --dry-run' with the run's generated configuration: the
    # data client's bucket and prefix must be defined for a submission, not
    # only for the data client commands
    import sys

    from harness.yd import Yd
    from live_samples import AWS, DATA, PLATFORM, PROFILE, write_config

    config = load_live_config(write_config(tmp_path, PLATFORM + AWS + PROFILE + DATA))
    run = Run.start(config, tmp_path / "runs")
    yd = Yd(run, program=(sys.executable, "-m", "yellowdog_cli.yd"))
    spec = yd(
        "wr",
        "submit",
        str(SPECS / "task-io-wr.jsonnet"),
        "--variable",
        "worker_tag=t-1",
        "--dry-run",
        "--json",
        "--quiet",
    ).document
    sources = json.dumps(spec)
    assert "{{" not in sources, sources
    assert f"yd-dummy-bucket/{run.namespace}/{run.run_id}/task-io/input.bin" in sources


def test_the_configured_pool_is_the_runs(tmp_path):
    run = _run(tmp_path)
    (pool,) = _load(run, [SPECS / "configured-pool.jsonnet"])
    assert pool["resource"] == "ConfiguredWorkerPool"
    assert pool["name"] == run.configured_pool_name()
    assert pool["namespace"] == run.namespace


def test_the_node_actions_write_a_file_and_read_it_back(tmp_path):
    from yellowdog_cli.utils.specs.loading import load_specification
    from yellowdog_cli.utils.specs.schema import Family
    from yellowdog_cli.utils.variable_syntax import (
        WP_VARIABLES_POSTFIX,
        WP_VARIABLES_PREFIX,
    )

    run = _run(tmp_path)
    with _variables(run):
        spec = load_specification(
            str(SPECS / "node-actions.jsonnet"),
            "node actions",
            family=Family.NODE_ACTIONS,
            prefix=WP_VARIABLES_PREFIX,
            postfix=WP_VARIABLES_POSTFIX,
            other_extensions_as_json=True,
        )
    write, check = spec["actions"]
    assert write["type"] == "writeFile" and write["content"] == run.run_id
    assert check["type"] == "runCommand" and check["arguments"][-1] == write["path"]
