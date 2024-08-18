import logging
import shutil
import subprocess
import time
from enum import Enum
from os import path
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass

from ulauncher.api.client.EventListener import EventListener
from ulauncher.api.client.Extension import Extension
from ulauncher.api.shared.action.BaseAction import BaseAction
from ulauncher.api.shared.action.CopyToClipboardAction import CopyToClipboardAction
from ulauncher.api.shared.action.DoNothingAction import DoNothingAction
from ulauncher.api.shared.action.OpenAction import OpenAction
from ulauncher.api.shared.action.RenderResultListAction import RenderResultListAction
from ulauncher.api.shared.event import KeywordQueryEvent, PreferencesEvent, PreferencesUpdateEvent
from ulauncher.api.shared.item.ExtensionResultItem import ExtensionResultItem
from ulauncher.api.shared.item.ExtensionSmallResultItem import ExtensionSmallResultItem

from preferences.preferences import Preference

logger = logging.getLogger(__name__)


class AltEnterAction(Enum):
    OPEN_PATH = 0
    COPY_PATH = 1


class SearchType(Enum):
    BOTH = 0
    FILES = 1
    DIRS = 2


@dataclass
class FileSystemSnapshot:
    snapshot: str = ""
    timestamp: int = -1


BinNames = Dict[str, str]
ExtensionPreferences = Dict[str, str]
FuzzyFinderPreferences = Dict[str, Preference]


class FuzzyFinderExtension(Extension):
    def __init__(self) -> None:
        super().__init__()
        self.fss = FileSystemSnapshot()
        from preferences.listeners import PreferencesInitEventListener, PreferencesUpdateEventListener
        self.prefs: FuzzyFinderPreferences = {}
        self.subscribe(PreferencesEvent, PreferencesInitEventListener())
        self.subscribe(PreferencesUpdateEvent, PreferencesUpdateEventListener())
        self.subscribe(KeywordQueryEvent, KeywordQueryEventListener())

    @staticmethod
    def _assign_bin_name(bin_names: BinNames, bin_cmd: str, testing_cmd: str) -> BinNames:
        try:
            if shutil.which(testing_cmd):
                bin_names[bin_cmd] = testing_cmd
        except subprocess.CalledProcessError:
            pass

        return bin_names

    @staticmethod
    def _generate_fd_cmd(fd_bin: str, preferences: FuzzyFinderPreferences) -> List[str]:
        cmd = [fd_bin, ".", preferences["base_dir"].value]
        if preferences["search_type"].value == SearchType.FILES:
            cmd.extend(["--type", "f"])
        elif preferences["search_type"].value == SearchType.DIRS:
            cmd.extend(["--type", "d"])

        if preferences["allow_hidden"].value:
            cmd.extend(["--hidden"])

        if preferences["follow_symlinks"].value:
            cmd.extend(["--follow"])

        if preferences["ignore_file"].error is None:
            cmd.extend(["--ignore-file", preferences["ignore_file"].value])

        return cmd

    def get_binaries(self) -> Tuple[BinNames, List[str]]:
        logger.debug("Checking and getting binaries for dependencies")
        bin_names: BinNames = {}
        bin_names = FuzzyFinderExtension._assign_bin_name(bin_names, "fzf_bin", "fzf")
        bin_names = FuzzyFinderExtension._assign_bin_name(bin_names, "fd_bin", "fd")
        if bin_names.get("fd_bin") is None:
            bin_names = FuzzyFinderExtension._assign_bin_name(bin_names, "fd_bin", "fdfind")

        errors = []
        if bin_names.get("fzf_bin") is None:
            errors.append("Missing dependency fzf. Please install fzf.")
        if bin_names.get("fd_bin") is None:
            errors.append("Missing dependency fd. Please install fd.")

        if not errors:
            logger.debug("Using binaries %s", bin_names)

        return bin_names, errors

    def _refresh(self, fd_cmd: List[str], preferences: FuzzyFinderPreferences):
        # Re-use the previous file system reading if it was recent enough
        timestamp = time.time()
        elapsed = timestamp - self.fss.timestamp
        scan_period = preferences["scan_period"].value
        if elapsed < scan_period:
            logger.debug(f"Reusing previous snapshot - elapsed_time ({elapsed}) < refresh_period ({scan_period})")
            return

        # Update the file system reading
        logger.debug(f"Updating snapshot - elapsed time ({elapsed}) >= refresh_period ({scan_period})")
        fd_process = subprocess.Popen(fd_cmd, stdout=subprocess.PIPE, text=True)
        try:
            outs, errs = fd_process.communicate(timeout=preferences["scan_timeout"].value)
        except subprocess.TimeoutExpired:
            fd_process.kill()
            raise

        self.fss.timestamp = timestamp
        self.fss.snapshot = outs

    def search(self, query: str, preferences: FuzzyFinderPreferences, fd_bin: str, fzf_bin: str) -> List[str]:
        logger.debug("Finding results for %s", query)

        # Check if the filesystem snapshot needs a refresh
        fd_cmd = FuzzyFinderExtension._generate_fd_cmd(fd_bin, preferences)
        self._refresh(fd_cmd, preferences)

        # Run fzf
        fzf_cmd = [fzf_bin, "--filter", query]
        fzf_process = subprocess.Popen(fzf_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        fzf_process.stdin.write(self.fss.snapshot)
        outs, _ = fzf_process.communicate()

        # Get the last 'limit' results
        limit = preferences["result_limit"].value
        results = outs.splitlines()[:limit]
        logger.info("Found results: %s", results)
        return results


class KeywordQueryEventListener(EventListener):
    @staticmethod
    def _get_dirname(path_name: str) -> str:
        dirname = path_name if path.isdir(path_name) else path.dirname(path_name)
        return dirname

    @staticmethod
    def _no_op_result_items(msgs: List[str], icon: str = "icon") -> List[ExtensionResultItem]:
        items = [
            ExtensionResultItem(icon=f"images/{icon}.png", name=msg, on_enter=DoNothingAction())
            for msg in msgs
        ]
        return items

    @staticmethod
    def _get_alt_enter_action(action_type: AltEnterAction, filename: str) -> BaseAction:
        # Default to opening directory, even if invalid action provided
        action = OpenAction(KeywordQueryEventListener._get_dirname(filename))
        if action_type == AltEnterAction.COPY_PATH:
            action = CopyToClipboardAction(filename)
        return action

    @staticmethod
    def _get_path_prefix(results: List[str], trim_path: bool) -> Optional[str]:
        path_prefix = None
        if trim_path:
            common_path = path.commonpath(results)
            common_path_parent = path.dirname(common_path)
            if common_path_parent not in ("/", ""):
                path_prefix = common_path_parent

        logger.debug("path_prefix for results is '%s'", path_prefix or "")

        return path_prefix

    @staticmethod
    def _get_display_name(path_name: str, path_prefix: Optional[str] = None) -> str:
        display_path = path_name
        if path_prefix is not None:
            display_path = path_name.replace(path_prefix, "...")
        return display_path

    @staticmethod
    def _generate_result_items(
        preferences: FuzzyFinderPreferences, results: List[str]
    ) -> List[ExtensionSmallResultItem]:
        path_prefix = KeywordQueryEventListener._get_path_prefix(
            results, preferences["trim_display_path"].value
        )

        def create_result_item(path_name: str) -> ExtensionSmallResultItem:
            return ExtensionSmallResultItem(
                icon="images/sub-icon.png",
                name=KeywordQueryEventListener._get_display_name(path_name, path_prefix),
                on_enter=OpenAction(path_name),
                on_alt_enter=KeywordQueryEventListener._get_alt_enter_action(
                    preferences["alt_enter_action"].value, path_name
                ),
            )

        return list(map(create_result_item, results))

    def on_event(self, event: KeywordQueryEvent, extension: FuzzyFinderExtension) -> RenderResultListAction:
        bin_names, errors = extension.get_binaries()

        # TODO: cache error presence instead of checking them on each event
        warnings = []
        for value in extension.prefs.values():
            if value.error is None:
                continue
            msg = value.formatted_error_msg()
            if value.mandatory:
                errors.append(msg)
            else:
                warnings.append(msg)

        # TODO: Handle warning and errors differently
        if errors:
            errors_items = KeywordQueryEventListener._no_op_result_items(errors, "error")
            warnings_items = KeywordQueryEventListener._no_op_result_items(warnings, "warning")
            return RenderResultListAction(errors_items + warnings_items)

        query = event.get_argument()
        if not query:
            return KeywordQueryEventListener._no_op_result_items(["Enter your search criteria."])

        preferences = extension.prefs
        try:
            results = extension.search(query, preferences, **bin_names)
        except subprocess.CalledProcessError as error:
            failing_cmd = error.cmd[0]
            if failing_cmd == "fzf" and error.returncode == 1:
                return KeywordQueryEventListener._no_op_result_items(["No results found."])

            logger.debug("Subprocess %s failed with status code %s", error.cmd, error.returncode)
            return KeywordQueryEventListener._no_op_result_items(
                ["There was an error running this extension."], "error"
            )
        except subprocess.TimeoutExpired as error:
            long_msg = f"Process '{' '.join(error.cmd)}' timed out after {error.timeout} seconds"
            short_msg = f"{error.cmd[0]} timed out after {error.timeout} s"
            logger.error(long_msg)
            return KeywordQueryEventListener._no_op_result_items([short_msg], "error")

        items = KeywordQueryEventListener._generate_result_items(preferences, results)
        return RenderResultListAction(items)


if __name__ == "__main__":
    FuzzyFinderExtension().run()
