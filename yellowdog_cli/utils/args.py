"""
Class to parse command line arguments for all commands. The options
themselves come from utils/command_registry.py.
"""

import sys

from yellowdog_cli._version import __version__
from yellowdog_cli.utils.command_registry import (
    COMMANDS,
    Command,
    build_parser,
    check_namespace_and_tag_are_no_files,
    command_from_argv0,
    parse_range,
    resize_targets_compute_requirement,
)
from yellowdog_cli.utils.lazy import lazy
from yellowdog_cli.utils.version_info import DOCS_URL


def docs():
    print(
        f"Online documentation for YellowDog CLI v{__version__}: {DOCS_URL}",
        flush=True,
    )


def allow_missing_attribute(func):
    """
    Wrapper function to return None if an option isn't enabled.
    """

    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except AttributeError:
            return None

    return wrapper


class CLIParser:
    def __init__(self, command: str | None = None, argv: list[str] | None = None):
        """
        Build the parser for a command from the registry, parse the
        arguments and run the command's validators. Both default to
        sys.argv: the command from its basename (see command_from_argv0),
        the arguments from the rest. An unknown command gets the common
        options only.
        """
        self.command_name = (
            command_from_argv0(sys.argv[0]) if command is None else command
        )
        self.command: Command | None = COMMANDS.get(self.command_name)
        # prog is the name invoked
        self.parser = build_parser(
            self.command, prog=self.command_name if self.command else None
        )
        argv = sys.argv[1:] if argv is None else argv

        # '--docs', like '--help', is answered before anything else is
        # checked: a required argument missing, or a validator's refusal,
        # would otherwise stand in the way of asking where the docs are
        if "--docs" in argv and any(
            "--docs" in action.option_strings for action in self.parser._actions
        ):
            docs()
            sys.exit(0)

        self.args = self.parser.parse_args(argv)

        if self.command is not None:
            check_namespace_and_tag_are_no_files(self.args, self.parser)
            for validator in self.command.validators:
                validator(self.args, self.parser)

    @property
    def namespace_required(self) -> bool:
        return self.command is not None and self.command.requires_namespace_and_tag

    @property
    def tag_required(self) -> bool:
        return self.namespace_required

    @property
    def credentials_required(self) -> bool:
        """
        Whether the configuration must hold the application key and secret:
        true for every command but those that never use the Platform.
        """
        return self.command is None or self.command.requires_credentials

    # -----------------------------------------------------------------------
    # Common args
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def config_file(self) -> str | None:
        return self.args.config

    @property
    @allow_missing_attribute
    def key(self) -> str | None:
        return self.args.key

    @property
    @allow_missing_attribute
    def secret(self) -> str | None:
        return self.args.secret

    @property
    @allow_missing_attribute
    def url(self) -> str | None:
        return self.args.url

    @property
    @allow_missing_attribute
    def debug(self) -> bool | None:
        return self.args.debug

    @property
    @allow_missing_attribute
    def use_pac(self) -> bool | None:
        return self.args.pac

    @property
    @allow_missing_attribute
    def no_format(self) -> bool | None:
        return self.args.no_format

    @property
    @allow_missing_attribute
    def quiet(self) -> bool | None:
        return self.args.quiet

    @quiet.setter
    def quiet(self, value: bool) -> None:
        self.args.quiet = value

    @property
    @allow_missing_attribute
    def env_override(self) -> bool | None:
        return self.args.env_override

    @property
    @allow_missing_attribute
    def print_pid(self) -> bool | None:
        return self.args.print_pid

    @property
    @allow_missing_attribute
    def no_config(self) -> bool | None:
        return self.args.no_config

    @property
    @allow_missing_attribute
    def property_overrides(self) -> list[str] | None:
        return self.args.property

    # -----------------------------------------------------------------------
    # yd-* (all except yd-compare)
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def variables(self) -> list[str] | None:
        return self.args.variable

    # -----------------------------------------------------------------------
    # yd-* (all except yd-boost, yd-cloudwizard, yd-follow, yd-list, yd-compare)
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def namespace(self) -> str | None:
        return self.args.namespace

    @property
    @allow_missing_attribute
    def tag(self) -> str | None:
        return self.args.tag

    # -----------------------------------------------------------------------
    # yd-list
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def ids_only(self) -> bool | None:
        return self.args.ids_only

    @ids_only.setter
    def ids_only(self, value: bool) -> None:
        self.args.ids_only = value

    @property
    @allow_missing_attribute
    def json_output(self) -> bool | None:
        return self.args.json

    @json_output.setter
    def json_output(self, value: bool) -> None:
        self.args.json = value

    @property
    @allow_missing_attribute
    def offline(self) -> bool | None:
        return self.args.offline

    @property
    @allow_missing_attribute
    def timeout(self) -> int | None:
        return self.args.timeout

    @property
    @allow_missing_attribute
    def count_only(self) -> bool | None:
        return self.args.count

    # -----------------------------------------------------------------------
    # yd-submit
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def work_req_file(self) -> str | None:
        return self.args.work_requirement

    @property
    @allow_missing_attribute
    def json_raw(self) -> str | None:
        return self.args.json_raw

    # Also used by yd-cancel, yd-provision, yd-instantiate, yd-start, yd-hold,
    # yd-finish, yd-shutdown, yd-terminate, yd-resize
    @property
    @allow_missing_attribute
    def follow(self) -> bool:
        return self.args.follow

    @property
    @allow_missing_attribute
    def exit_on_failure(self) -> bool:
        return self.args.exit_on_failure

    @property
    @allow_missing_attribute
    def task_type(self) -> str | None:
        return self.args.task_type

    @property
    @allow_missing_attribute
    def task_count(self) -> int | None:
        return self.args.task_count

    @property
    @allow_missing_attribute
    def task_group_count(self) -> int | None:
        return self.args.task_group_count

    @property
    @allow_missing_attribute
    def task_batch_size(self) -> int | None:
        return self.args.task_batch_size

    @property
    @allow_missing_attribute
    def pause_between_batches(self) -> int | None:
        return self.args.pause_between_batches

    @property
    @allow_missing_attribute
    def csv_files(self) -> list[str] | None:
        return self.args.csv_file

    @property
    @allow_missing_attribute
    def process_csv_only(self) -> bool | None:
        return self.args.process_csv_only

    @property
    @allow_missing_attribute
    def hold(self) -> bool | None:
        return self.args.hold

    @property
    @allow_missing_attribute
    def parallel_batches(self) -> int | None:
        return self.args.parallel_batches

    @property
    @allow_missing_attribute
    def empty(self) -> bool | None:
        return self.args.empty

    @property
    @allow_missing_attribute
    def overwrite(self) -> bool | None:
        return self.args.overwrite

    @property
    @allow_missing_attribute
    def add_to(self) -> str | None:
        return self.args.add_to

    # -----------------------------------------------------------------------
    # yd-provision / yd-instantiate
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def worker_pool_file(self) -> str | None:
        return self.args.worker_pool

    @property
    @allow_missing_attribute
    def target(self) -> int | None:
        return self.args.target

    # -----------------------------------------------------------------------
    # yd-cancel
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def abort(self) -> bool:
        return self.args.abort

    # -----------------------------------------------------------------------
    # yd-cancel / yd-shutdown / yd-terminate / yd-start / yd-hold / yd-finish
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def interactive(self) -> bool | None:
        return self.args.interactive

    @interactive.setter
    def interactive(self, interactive: bool):
        self.args.interactive = interactive

    # -----------------------------------------------------------------------
    # yd-abort / yd-cancel / yd-shutdown / yd-terminate /
    # yd-resize / yd-cloudwizard / yd-boost / yd-hold / yd-start / yd-list /
    # yd-finish  (also yd-create / yd-remove)
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def yes(self) -> bool | None:
        return self.args.yes

    # -----------------------------------------------------------------------
    # yd-list
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def reverse(self) -> bool | None:
        return self.args.reverse

    @property
    @allow_missing_attribute
    def sort(self) -> str | None:
        return self.args.sort

    @property
    @allow_missing_attribute
    def entity_type(self) -> str | None:
        return self.args.entity_type

    @property
    @allow_missing_attribute
    def name_glob(self) -> str | None:
        return self.args.name_glob

    @property
    @allow_missing_attribute
    def active_only(self) -> bool | None:
        return self.args.active_only

    @property
    @allow_missing_attribute
    def status_filter(self) -> list[str] | None:
        return self.args.status_filter

    @property
    @allow_missing_attribute
    def public_ips_only(self) -> bool | None:
        return self.args.public_ips_only

    @property
    @allow_missing_attribute
    def details(self) -> bool | None:
        return self.args.details

    @details.setter
    def details(self, interactive: bool):
        self.args.details = interactive

    @property
    @allow_missing_attribute
    def auto_select_all(self) -> bool | None:
        return self.args.auto_select_all

    # -----------------------------------------------------------------------
    # yd-cloud-info
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def cloud_info_type(self) -> str | None:
        return self.args.cloud_info_type

    @property
    @allow_missing_attribute
    def providers(self) -> list[str] | None:
        return self.args.providers

    @property
    @allow_missing_attribute
    def region(self) -> str | None:
        return self.args.region

    @property
    @allow_missing_attribute
    def sub_region(self) -> str | None:
        return self.args.sub_region

    @property
    @allow_missing_attribute
    def vcpus_range(self) -> tuple[float | None, float | None] | None:
        # The validator has refused a malformed one
        return None if self.args.vcpus is None else parse_range(self.args.vcpus)

    @property
    @allow_missing_attribute
    def ram_range(self) -> tuple[float | None, float | None] | None:
        # The validator has refused a malformed one
        return None if self.args.ram is None else parse_range(self.args.ram)

    @property
    @allow_missing_attribute
    def arch(self) -> str | None:
        return self.args.arch

    @property
    @allow_missing_attribute
    def usage(self) -> str | None:
        return self.args.usage

    @property
    @allow_missing_attribute
    def os_licence(self) -> str | None:
        return self.args.os_licence

    @property
    @allow_missing_attribute
    def prices(self) -> bool | None:
        return self.args.prices

    # -----------------------------------------------------------------------
    # yd-submit / yd-provision / yd-instantiate / yd-create
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def dry_run(self) -> bool | None:
        return self.args.dry_run

    # -----------------------------------------------------------------------
    # yd-instantiate
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def compute_requirement(self) -> str | None:
        return self.args.compute_requirement

    @property
    @allow_missing_attribute
    def report(self) -> bool | None:
        return self.args.report

    # -----------------------------------------------------------------------
    # yd-submit / yd-provision / yd-instantiate / yd-create / yd-remove
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def jsonnet_dry_run(self) -> bool | None:
        return self.args.jsonnet_dry_run

    @property
    @allow_missing_attribute
    def validate(self) -> bool | None:
        # yd-submit, yd-provision, yd-instantiate, yd-create, yd-nodeaction
        return self.args.validate

    # -----------------------------------------------------------------------
    # yd-resize
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def worker_pool_name(self) -> str | None:
        return self.args.worker_pool

    @property
    @allow_missing_attribute
    def worker_pool_size(self) -> int | None:
        return self.args.worker_pool_size

    @property
    @allow_missing_attribute
    def compute_req_resize(self) -> bool | None:
        return resize_targets_compute_requirement(self.args)

    # -----------------------------------------------------------------------
    # yd-boost
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def boost_hours(self) -> int:
        return self.args.boost_hours

    @property
    @allow_missing_attribute
    def allowance_list(self) -> list[str]:
        return self.args.allowances

    # -----------------------------------------------------------------------
    # yd-shutdown
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def worker_pool_nodes_list(self) -> list[str] | None:
        return self.args.worker_pool_nodes_list

    @property
    @allow_missing_attribute
    def terminate(self) -> bool | None:
        return self.args.terminate

    # -----------------------------------------------------------------------
    # yd-priority
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def priority(self) -> float:
        return self.args.priority

    @property
    @allow_missing_attribute
    def priority_targets(self) -> list[str]:
        return self.args.priority_targets

    # -----------------------------------------------------------------------
    # yd-token
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def worker_pools(self) -> list[str]:
        return self.args.worker_pools

    @property
    @allow_missing_attribute
    def regenerate(self) -> bool | None:
        return self.args.regenerate

    @property
    @allow_missing_attribute
    def ttl_hours(self) -> float | None:
        return self.args.ttl_hours

    # -----------------------------------------------------------------------
    # yd-terminate / yd-compute-stop / yd-compute-start / yd-compute-restart /
    # yd-compute-deprovision / yd-compute-reprovision
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def compute_requirements_instances_or_nodes(self) -> list[str]:
        return self.args.compute_reqs_instances_or_nodes

    # -----------------------------------------------------------------------
    # yd-cancel / yd-start / yd-hold / yd-finish  (positional args)
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def work_requirement_names(self) -> list[str]:
        return self.args.work_requirements

    # -----------------------------------------------------------------------
    # yd-create / yd-remove
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def resource_specifications(self) -> list[str]:
        return self.args.resource_specifications

    @property
    @allow_missing_attribute
    def match_allowances_by_description(self) -> bool | None:
        return self.args.match_allowances_by_description

    # -----------------------------------------------------------------------
    # yd-create
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def show_keyring_passwords(self) -> bool | None:
        return self.args.show_keyring_passwords

    @property
    @allow_missing_attribute
    def regenerate_app_keys(self) -> bool | None:
        return self.args.regenerate_app_keys

    # -----------------------------------------------------------------------
    # yd-remove
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def ids(self) -> bool | None:
        return self.args.ids

    # -----------------------------------------------------------------------
    # yd-follow / yd-show
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def yellowdog_ids(self) -> list[str]:
        return self.args.yellowdog_ids

    # -----------------------------------------------------------------------
    # yd-submit / yd-provision / yd-instantiate
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def content_path(self) -> str | None:
        return self.args.content_path

    # -----------------------------------------------------------------------
    # yd-follow / yd-shutdown / yd-provision / yd-resize
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def auto_cr(self) -> bool:
        return self.args.auto_follow_compute_requirements

    # -----------------------------------------------------------------------
    # yd-resize / yd-compute-reprovision
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def wait(self) -> bool | None:
        return self.args.wait

    # -----------------------------------------------------------------------
    # yd-follow / yd-provision / yd-instantiate / yd-resize / yd-shutdown /
    # yd-terminate / yd-submit / yd-cancel / yd-start / yd-hold / yd-finish
    # -----------------------------------------------------------------------

    @property
    def events_as_json(self) -> bool:
        # yd-follow's '--json' prints each event as a JSON document; any
        # other command's '--follow --json' follows through the status
        # messages '--json' silences, its document being the result
        return self.command_name == "yd-follow" and bool(
            getattr(self.args, "json", False)
        )

    # -----------------------------------------------------------------------
    # yd-cloudwizard
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def operation(self) -> str | None:
        return self.args.operation

    @property
    @allow_missing_attribute
    def cloud_provider(self) -> str | None:
        return self.args.cloud_provider

    @property
    @allow_missing_attribute
    def credentials_file(self) -> str | None:
        return self.args.credentials_file

    @property
    @allow_missing_attribute
    def region_name(self) -> str | None:
        return self.args.region_name

    @property
    @allow_missing_attribute
    def instance_type(self) -> str | None:
        return self.args.instance_type

    @property
    @allow_missing_attribute
    def show_secrets(self) -> bool:
        return self.args.show_secrets

    # -----------------------------------------------------------------------
    # yd-nodeaction
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def node_action_spec(self) -> str | None:
        return self.args.actions

    @property
    @allow_missing_attribute
    def node_ids(self) -> list[str] | None:
        return self.args.node

    @property
    @allow_missing_attribute
    def all_nodes(self) -> bool | None:
        return self.args.all_nodes

    @property
    @allow_missing_attribute
    def status(self) -> bool | None:
        return self.args.status

    # -----------------------------------------------------------------------
    # yd-abort
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def task_id_list(self) -> list[str] | None:
        return self.args.task_id_list

    # -----------------------------------------------------------------------
    # yd-submit / yd-provision / yd-instantiate  (positional args)
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def work_requirement_file_positional(self) -> str | None:
        return self.args.work_requirement_file_positional

    @property
    @allow_missing_attribute
    def worker_pool_file_positional(self) -> str | None:
        return self.args.worker_pool_file_positional

    @property
    @allow_missing_attribute
    def compute_requirement_file_positional(self) -> str | None:
        return self.args.compute_requirement_file_positional

    # -----------------------------------------------------------------------
    # yd-create
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def no_resequence(self) -> bool | None:
        return self.args.no_resequence

    # -----------------------------------------------------------------------
    # yd-show
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def show_token(self) -> bool | None:
        return self.args.show_token

    @property
    @allow_missing_attribute
    def show_source_report(self) -> bool | None:
        return self.args.show_source_report

    @property
    @allow_missing_attribute
    def show_exhaustion(self) -> bool | None:
        return self.args.show_exhaustion

    @property
    @allow_missing_attribute
    def show_members(self) -> bool | None:
        return self.args.show_members

    # -----------------------------------------------------------------------
    # yd-variables
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def variable_names(self) -> list[str]:
        return self.args.variable_names

    # -----------------------------------------------------------------------
    # yd-list / yd-show
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def substitute_ids(self) -> bool | None:
        return self.args.substitute_ids

    @property
    @allow_missing_attribute
    def strip_ids(self) -> bool | None:
        return self.args.strip_ids

    @property
    @allow_missing_attribute
    def hide_user_data(self) -> bool | None:
        return self.args.hide_user_data

    @property
    @allow_missing_attribute
    def output_file(self) -> str | None:
        return self.args.output_file

    # -----------------------------------------------------------------------
    # yd-compare
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def wr_or_tg_id(self) -> str | None:
        return self.args.wr_or_tg_id

    @property
    @allow_missing_attribute
    def worker_pool_ids(self) -> list[str] | None:
        return self.args.worker_pool_ids

    @property
    @allow_missing_attribute
    def running_nodes_only(self) -> bool | None:
        return self.args.running_nodes_only

    # -----------------------------------------------------------------------
    # yd-submit
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def upgrade_rclone(self) -> bool | None:
        return self.args.upgrade_rclone

    @property
    @allow_missing_attribute
    def which_rclone(self) -> bool | None:
        return self.args.which_rclone

    @property
    @allow_missing_attribute
    def progress(self) -> bool | None:
        return self.args.progress

    # -----------------------------------------------------------------------
    # yd-upload / yd-download / yd-delete / yd-ls (data client commands)
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def remote(self) -> str | None:
        return self.args.remote

    @property
    @allow_missing_attribute
    def bucket(self) -> str | None:
        return self.args.bucket

    @property
    @allow_missing_attribute
    def prefix(self) -> str | None:
        return self.args.prefix

    @property
    @allow_missing_attribute
    def no_prefix(self) -> bool | None:
        return self.args.no_prefix

    @property
    @allow_missing_attribute
    def data_client_profile(self) -> str | None:
        return self.args.data_client_profile

    # -----------------------------------------------------------------------
    # yd-upload
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def local_paths(self) -> list[str]:
        return self.args.local_paths

    @property
    @allow_missing_attribute
    def destination(self) -> str | None:
        return self.args.destination

    @property
    @allow_missing_attribute
    def into(self) -> str | None:
        return self.args.into

    @property
    @allow_missing_attribute
    def recursive(self) -> bool | None:
        return self.args.recursive

    @property
    @allow_missing_attribute
    def flatten(self) -> bool | None:
        return self.args.flatten

    @property
    @allow_missing_attribute
    def sync(self) -> bool | None:
        return self.args.sync

    # -----------------------------------------------------------------------
    # yd-download / yd-delete / yd-ls
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def remote_paths(self) -> list[str]:
        return self.args.remote_paths

    @property
    @allow_missing_attribute
    def long_listing(self) -> bool | None:
        return self.args.long

    # -----------------------------------------------------------------------
    # yd-copy
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def src_path(self) -> str | None:
        return self.args.src_path

    @property
    @allow_missing_attribute
    def dst_path(self) -> str | None:
        return self.args.dst_path

    @property
    @allow_missing_attribute
    def dst_profile(self) -> str | None:
        return self.args.dst_profile

    @property
    @allow_missing_attribute
    def dst_prefix(self) -> str | None:
        return self.args.dst_prefix

    # -----------------------------------------------------------------------
    # yd-schema
    # -----------------------------------------------------------------------

    @property
    @allow_missing_attribute
    def schema_family(self) -> str | None:
        return self.args.family

    @property
    @allow_missing_attribute
    def schema_write_dir(self) -> str | None:
        return self.args.write

    @property
    @allow_missing_attribute
    def schema_check_dir(self) -> str | None:
        return self.args.check

    @property
    @allow_missing_attribute
    def schema_list(self) -> bool | None:
        return self.args.list


# The command line, parsed on first use rather than at import (see lazy.py),
# so that importing a module that names it parses nothing
ARGS_PARSER: CLIParser = lazy(CLIParser)
