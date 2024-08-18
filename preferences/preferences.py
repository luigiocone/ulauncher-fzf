import logging
from os import path
from typing import Optional, List, Callable

logger = logging.getLogger(__name__)


class Preference:
    def __init__(self, name: str, value=None, mandatory=False):
        """
        :param name: id of the preference
        :param mandatory: the extension will not do anything if a mandatory preference has errors
        """
        self.name = name
        self.value = value
        self.mandatory = mandatory
        self.error: str = None

    def set(self, value, parse=True) -> bool:
        if parse:
            try:
                value = self.parse_from_str(value)
            except ValueError as ve:
                self.error = str(ve)
                self.value = None
                return False

        error = self.check_error(value)
        if error is not None:
            self.error = error
            self.value = None
            return False
        self.error = None
        self.value = value
        return True

    def parse_from_str(self, str_value: str):
        raise NotImplementedError

    def check_error(self, parsed_value):
        raise NotImplementedError


class PathPreference(Preference):
    def __init__(self, name: str, value=None, mandatory=False, is_dir=False):
        super().__init__(name, value, mandatory)
        self.is_dir = is_dir

    def parse_from_str(self, str_value: str):
        if str_value is None:
            raise ValueError("path is None")
        return path.expanduser(str_value)

    def check_error(self, parsed_value) -> str:
        if self.is_dir and not path.isdir(parsed_value):
            return f"Value '{parsed_value}' of preference '{self.name}' is not a directory"
        if not self.is_dir and not path.isfile(parsed_value):
            return f"Value '{parsed_value}' of preference '{self.name}' is not a file"
        return None


class IntPreference(Preference):
    def __init__(self, name: str, value=None, mandatory=False, constraints: List[Callable] = None):
        super().__init__(name, value, mandatory)
        self.constraints = constraints

    def parse_from_str(self, str_value: str):
        return int(str_value)

    def check_error(self, parsed_value) -> str:
        for cnt in self.constraints:
            error = cnt(parsed_value)
            if error:
                return error
        return None


class FloatPreference(IntPreference):
    def parse_from_str(self, str_value: str):
        return float(str_value)


