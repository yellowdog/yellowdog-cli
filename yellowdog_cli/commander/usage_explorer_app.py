"""
The Usage Explorer run on its own (`yd commander --usage-explorer`), without
Commander's main window: StandaloneExplorer stands in for the main window,
giving the explorer its configuration (with a Select... button to change it),
its `yd usage` base arguments, its working directory and its appearance (with
a Dark Mode checkbox, sharing Commander's setting).
With no output window its log lines go nowhere: a failure is said beneath
the table, and nothing is printed to the terminal it was launched from.
"""

import sys
from collections.abc import Callable
from os.path import abspath, basename, dirname, isfile

from PyQt6.QtWidgets import QWidget

from yellowdog_cli.commander import file_dialogs
from yellowdog_cli.commander.arguments import split_arguments
from yellowdog_cli.commander.commander import (
    SETTING_DARK_MODE,
    apply_application_appearance,
    initial_dark_mode,
    make_application,
)
from yellowdog_cli.commander.output_pane import default_output_font
from yellowdog_cli.commander.startup import StartupSettings
from yellowdog_cli.commander.usage_explorer import UsageExplorer
from yellowdog_cli.utils.output_style import ERROR_MARKER
from yellowdog_cli.utils.paths import default_config_file

SELECT_CAPTION = "Please select a configuration file"
SELECT_FILTER = "*.toml"


def explorer_title(config_file: str) -> str:
    return f"Usage Explorer \N{EM DASH} {config_file}"


def chosen_config_file(
    given: str | None, ask: Callable[[str], str | None]
) -> str | None:
    """
    The configuration to explore, made absolute: the one given at launch,
    else the one the CLI reads by default (./config.toml, else the user's
    own), else the one 'ask' is given the current directory to choose, None
    if it chooses none.
    """
    if given is not None:
        return abspath(given)
    default = default_config_file()
    if isfile(default):
        return abspath(default)
    chosen = ask(".")
    return abspath(chosen) if chosen else None


class StandaloneExplorer:
    """
    The Usage Explorer as the application's one window: its configuration,
    the properties given at launch (passed to every run, as Commander's
    Properties field is) and its appearance, as Commander would give them.
    """

    def __init__(self, settings: StartupSettings, config_file: str) -> None:
        self._config_file = config_file
        # The launcher quotes each property for Commander's field; split back
        # into the arguments they are, as the field is when a command is built
        self._properties = split_arguments(" ".join(settings.properties))
        dark = initial_dark_mode()
        apply_application_appearance(dark)
        self.explorer = UsageExplorer(
            explorer_title(config_file),
            self._working_dir,
            self._base_args,
            default_output_font(),
            dark,
        )
        self._dialogs = file_dialogs.FileDialogs(self.explorer, default_output_font())
        self.explorer.select_configuration.connect(self._select_configuration)
        self.explorer.show_configuration(config_file)
        self.explorer.offer_dark_mode(dark)
        self.explorer.dark_mode_chosen.connect(self._set_dark_mode)
        if settings.namespace:
            self.explorer.set_namespace(settings.namespace)

    @property
    def config_file(self) -> str:
        return self._config_file

    def _working_dir(self) -> str:
        """
        The configuration file's directory, which Commander runs commands in.
        """
        return dirname(self._config_file)

    def _base_args(self) -> list[str]:
        """
        What every run is given, as Commander gives it: the configuration by
        its name in the directory run in, '--nf', '--quiet', '--json' and the
        properties.
        """
        return [
            "-c",
            basename(self._config_file),
            "--nf",
            "-q",
            "--json",
            *(f"--property={entry}" for entry in self._properties),
        ]

    def _set_dark_mode(self, dark: bool) -> None:
        """
        Dark Mode ticked or unticked: the application's appearance and the
        explorer's colours, remembered as Commander's checkbox remembers it,
        so that the next start, of either, opens the same way.
        """
        apply_application_appearance(dark)
        self.explorer.set_dark(dark)
        file_dialogs.dialog_settings().setValue(SETTING_DARK_MODE, dark)

    def _select_configuration(self) -> None:
        """
        Select...: another configuration, the explorer reset for it, awaiting
        Fetch Report, as a new selection in Commander resets it.
        """
        chosen = self._dialogs.select_file(
            caption=SELECT_CAPTION,
            directory=self._working_dir(),
            file_pattern=SELECT_FILTER,
        )
        if not chosen:
            return
        self._config_file = abspath(chosen)
        self.explorer.show_configuration(self._config_file)
        self.explorer.reset(explorer_title(self._config_file))


def run_usage_explorer(settings: StartupSettings) -> None:
    """
    `yd commander --usage-explorer`: the explorer alone, until it is closed.
    With no configuration given or found, a file dialog asks for one, and
    choosing none ends the launch.
    """
    try:
        app = make_application()
        # The start-up dialog's parent: there is no window yet
        holder = QWidget()
        dialogs = file_dialogs.FileDialogs(holder, default_output_font())
        config_file = chosen_config_file(
            settings.config_file,
            lambda directory: dialogs.select_file(
                caption=SELECT_CAPTION, directory=directory, file_pattern=SELECT_FILTER
            ),
        )
        if config_file is None:
            sys.exit(0)
        standalone = StandaloneExplorer(settings, config_file)
        explorer = standalone.explorer
        explorer.setWindowIcon(app.windowIcon())
        # Quitting by Cmd-Q or the Dock stops any run, as closing the window does
        app.aboutToQuit.connect(explorer.shut_down)
        explorer.show()
        sys.exit(app.exec())
    except Exception as exc:
        print(f"{ERROR_MARKER}{exc}", file=sys.stderr)
        sys.exit(1)
