import logging

from ulauncher.api.client.EventListener import EventListener
from ulauncher.api.shared.event import PreferencesEvent, PreferencesUpdateEvent

from main import FuzzyFinderExtension, AltEnterAction, SearchType
from preferences.preferences import Preference, PathPreference, IntPreference, FloatPreference

logger = logging.getLogger(__name__)


# Event listener for the "PreferencesEvent" (received only once at startup)
class PreferencesInitEventListener(EventListener):
    @staticmethod
    def add_secure_preferences(event: PreferencesEvent, extension: FuzzyFinderExtension):
        """ Preferences that do not cause errors (trusting ulauncher) """
        prefs = {
            "alt_enter_action": AltEnterAction(int(event.preferences["alt_enter_action"])),
            "search_type": SearchType(int(event.preferences["search_type"])),
            "allow_hidden": bool(int(event.preferences["allow_hidden"])),
            "follow_symlinks": bool(int(event.preferences["follow_symlinks"])),
            "trim_display_path": bool(int(event.preferences["trim_display_path"]))
        }
        for key, value in prefs.items():
            extension.prefs[key] = Preference(name=key, value=value, mandatory=True)

    @staticmethod
    def add_base_dir(event: PreferencesEvent, extension: FuzzyFinderExtension):
        key = "base_dir"
        extension.prefs[key] = PathPreference(name=key, mandatory=True, is_dir=True)
        value = event.preferences[key] if key in event.preferences else None
        extension.prefs[key].set(value=value, parse=True)

    @staticmethod
    def add_ignore_file(event: PreferencesEvent, extension: FuzzyFinderExtension):
        key = "ignore_file"
        extension.prefs[key] = PathPreference(name=key, mandatory=False, is_dir=False)
        value = event.preferences[key] if key in event.preferences else None
        extension.prefs[key].set(value=value, parse=True)

    @staticmethod
    def add_result_limit(event: PreferencesEvent, extension: FuzzyFinderExtension):
        key = "result_limit"
        constraint = lambda x: "value must be > 0" if x <= 0 else None
        extension.prefs[key] = IntPreference(name=key, mandatory=True, constraints=[constraint])
        value = event.preferences[key] if key in event.preferences else None
        extension.prefs[key].set(value=value, parse=True)

    @staticmethod
    def add_scan_period(event: PreferencesEvent, extension: FuzzyFinderExtension):
        key = "scan_period"
        constraint = lambda x: "value must be >= 0" if x < 0 else None
        extension.prefs[key] = FloatPreference(name=key, mandatory=True, constraints=[constraint])
        value = event.preferences[key] if key in event.preferences else None
        extension.prefs[key].set(value=value, parse=True)

    @staticmethod
    def add_scan_timeout(event: PreferencesEvent, extension: FuzzyFinderExtension):
        key = "scan_timeout"
        constraint = lambda x: "value must be > 0" if x <= 0 else None
        extension.prefs[key] = FloatPreference(name=key, mandatory=False, constraints=[constraint])
        value = event.preferences[key] if key in event.preferences else None
        extension.prefs[key].set(value=value, parse=True)

    def on_event(self, event: PreferencesEvent, extension: FuzzyFinderExtension):
        logger.debug("Received user preferences, checking their validity")

        self.add_secure_preferences(event, extension)
        self.add_base_dir(event, extension)
        self.add_ignore_file(event, extension)
        self.add_result_limit(event, extension)
        self.add_scan_period(event, extension)
        self.add_scan_timeout(event, extension)

        for key, value in extension.prefs.items():
            if value.error is None:
                continue
            if value.mandatory:
                extension.prefs_error = True
                logger.error(f"Preference '{key}': {value.error}")
            else:
                extension.prefs_warning = True
                logger.warning(f"Preference '{key}': {value.error}")
        logger.debug("Using user preferences %s", extension.prefs.keys())

        # if not extension.errors:
        #     logger.debug("No errors detected in user preferences")
        #     logger.debug("Using user preferences %s", extension.prefs)


# Event listener for the "PreferencesUpdateEvent"
class PreferencesUpdateEventListener(EventListener):
    def on_event(self, event: PreferencesUpdateEvent, extension: FuzzyFinderExtension):
        logger.debug(f"Received request to change '{event.id}' from '{event.old_value}' to '{event.new_value}'")
        valid = extension.prefs[event.id].set(event.new_value)
        if valid:
            logger.debug(f"'{event.id}' changed from '{event.old_value}' to '{event.new_value}'")
        else:
            logger.error(f"'{event.id}' new_value '{event.new_value}' is not valid")
