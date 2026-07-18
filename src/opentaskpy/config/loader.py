"""Config loader."""

import importlib
import importlib.util
import inspect
import json
import os
import sys
from collections.abc import MutableMapping
from glob import glob
from typing import Any

import jinja2
from jinja2 import meta

import opentaskpy.otflogging
from opentaskpy.exceptions import (
    DuplicateConfigFileError,
    VariableResolutionTooDeepError,
)
from opentaskpy.filters import default_filters

MAX_DEPTH = 5


class LazyResolvedDict(dict):
    """Dictionary wrapper that resolves values only when accessed."""

    def __init__(
        self,
        values: dict[str, Any],
        resolver: Any,
        resolve_lookups: bool = False,
    ) -> None:
        """Initialise the wrapper around a dictionary of unresolved values."""
        super().__init__(values)
        self._resolver = resolver
        self._resolve_lookups = resolve_lookups

    def _wrap(self, value: Any) -> Any:
        if isinstance(value, dict):
            return LazyResolvedDict(
                value,
                self._resolver,
                resolve_lookups=self._resolve_lookups,
            )

        if isinstance(value, list):
            return [self._wrap(item) for item in value]

        return self._resolver(value, resolve_lookups=self._resolve_lookups)

    def __getitem__(self, key: str) -> Any:
        """Return a lazily resolved value for the requested key."""
        return self._wrap(super().__getitem__(key))

    def get(self, key: str, default: Any = None) -> Any:
        """Return a lazily resolved value when the key exists."""
        if key not in self:
            return default

        return self[key]


class ConfigLoader:
    """Class responsible for loading and validating config files."""

    def __init__(self, config_dir: str) -> None:
        """Parse config files and expand variables.

        Args:
            config_dir (str): The path to the config files to load.
        """
        self.logger = opentaskpy.otflogging.init_logging(__name__)
        self.config_dir = config_dir
        self.global_variables: dict = {}
        self.loaded_filters: dict = {}
        self.file_cache: dict[str, str] = {}  # Cache for preloaded files

        self.logger.log(12, f"Looking in {self.config_dir}")

        # Force Jinja2 to log undefined variables
        jinja2.make_logging_undefined(logger=self.logger, base=jinja2.Undefined)
        self.template_env = jinja2.Environment(undefined=jinja2.StrictUndefined)

        self._load_filters(self.template_env.filters)
        self.loaded_filters = self.template_env.filters

        self._load_global_variables()

        self.lazy_load = False
        if os.environ.get("OTF_LAZY_LOAD_VARIABLES", None) == "1":
            self.lazy_load = True

        self._resolve_templated_variables(lazy_load=self.lazy_load)

        # Preload all files in the config directory
        self._preload_files()

    def _preload_files(self) -> None:
        """Preload all JSON and Jinja2 files in the config directory into memory."""
        self.file_cache = {}
        file_patterns = [
            f"{self.config_dir}/**/*.json",
            f"{self.config_dir}/**/*.json.j2",
        ]
        for pattern in file_patterns:
            for file_path in glob(pattern, recursive=True):
                with open(file_path, encoding="utf-8") as file:
                    self.file_cache[file_path] = file.read()
        self.logger.log(12, f"Preloaded {len(self.file_cache)} files into memory.")

    def _load_filters(self, destination: MutableMapping[str, Any]) -> None:
        """Load default filters from opentaskpy.filters.default_filters.

        Args:
            destination (dict): The destination dictionary to load the filters into
        """
        # Prevent multiple loads
        if self.loaded_filters:
            destination.update(self.loaded_filters)
            return

        # Check what functions exist in the module
        for name, func in inspect.getmembers(default_filters, inspect.isfunction):
            destination[name] = func
            self.logger.log(12, f"Registered default filter: {name}")

        # Support for custom filters
        filters_dir = f"{self.config_dir}/filters"
        if os.path.isdir(filters_dir):
            for filter_file in glob(f"{self.config_dir}/filters/*.py", recursive=True):
                module_name = f"{os.path.basename(filter_file).replace('.py', '')}"
                spec = importlib.util.spec_from_file_location(module_name, filter_file)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    # Register all functions in the module as Jinja2 filters
                    for name, func in inspect.getmembers(module, inspect.isfunction):
                        destination[name] = func
                        self.logger.log(
                            12, f"Registered custom filter: {name} from {filter_file}"
                        )
                else:
                    self.logger.log(12, f"Couldn't import custom filter: {filter_file}")

        destination = self.loaded_filters

    def _override_variables_from_env(self, variables: dict, variable_type: str) -> None:
        """Overrides variables with environment variables."""
        for (  # pylint: disable=too-many-nested-blocks
            env_var_name,
            env_var_value,
        ) in os.environ.items():
            if "." in env_var_name:
                key_path = env_var_name.split(".")
                current_dict = variables
                self.logger.log(12, f"Searching for {env_var_name}")
                for i, key in enumerate(key_path):
                    if isinstance(current_dict, dict) and key in current_dict:
                        if i == len(key_path) - 1:
                            # It's the final key, override the value
                            self.logger.info(
                                f"Overriding nested {variable_type} variable '{env_var_name}' with environment variable."
                            )
                            # Check the original type of the variable, if it was an int, then cast it to an int
                            if isinstance(current_dict[key], int):
                                current_dict[key] = int(env_var_value)
                            else:
                                current_dict[key] = env_var_value
                        else:
                            # Traverse deeper
                            current_dict = current_dict[key]
                    else:
                        # The key path does not exist in the dictionary
                        break

            elif env_var_name in variables:
                self.logger.info(
                    f"Overriding {variable_type} variable ({env_var_name}: {variables[env_var_name]}) with environment variable ({env_var_value})"
                )
                # Check the original type of the variable, if it was an int, then cast it to an int
                if isinstance(variables[env_var_name], int):
                    variables[env_var_name] = int(env_var_value)
                else:
                    variables[env_var_name] = env_var_value

    def get_global_variables(self) -> dict:
        """Return the set of global variables that have been assigned via config files.

        This will first check for anything that has been overridden in the environment
        first, and replace those if necessary.

        Returns:
            dict: _description_
        """
        # Before we return the variables, we need to check for any environment variables that match the same name, and are set
        # if this is the case, then we replace the value with the environment variable
        self._override_variables_from_env(self.global_variables, "global")

        return self.global_variables

    def _resolve_lookup_value(self, value: Any, resolve_lookups: bool = True) -> Any:
        """Resolve templated values before they are passed to a lookup plugin."""
        if isinstance(value, dict):
            return {
                key: self._resolve_lookup_value(item, resolve_lookups=resolve_lookups)
                for key, item in value.items()
            }

        if isinstance(value, list):
            return [
                self._resolve_lookup_value(item, resolve_lookups=resolve_lookups)
                for item in value
            ]

        if isinstance(value, str):
            if not resolve_lookups and "lookup(" in value:
                return value

            return self._resolve_templated_variables_from_string(value)

        return value

    def template_lookup(self, plugin: str, **kwargs) -> str:  # type: ignore[no-untyped-def]
        """Lookup function used by Jinja.

        This function is responsible for calling the lookup plugins to evaluate custom
        variables. This imports the necessary Python module and calls the lookup
        function's run method.

        Args:
            plugin (str): The name of the plugin to call
            **kwargs: The arguments to pass to the plugin

        Returns:
            str: The result of the lookup plugin
        """
        self.logger.log(
            11, f"Got call to lookup function {plugin} with kwargs {kwargs}"
        )

        kwargs = {
            key: self._resolve_lookup_value(value) for key, value in kwargs.items()
        }

        # Append the globals to the kwargs
        kwargs["globals"] = LazyResolvedDict(
            self.global_variables,
            self._resolve_lookup_value,
            resolve_lookups=False,
        )

        # Import the plugin if its not already loaded
        if f"opentaskpy.plugins.lookup.{plugin}" not in sys.modules:
            # Check the module is loadable
            try:
                importlib.import_module(f"opentaskpy.plugins.lookup.{plugin}")
            except ModuleNotFoundError:
                self.logger.log(
                    11,
                    (
                        f"Module not found: opentaskpy.plugins.lookup.{plugin}. Looking"
                        " in plugins directory instead"
                    ),
                )

        # If we haven't loaded the plugin yet, then look in the cfg/plugins directory and see if we can find it
        if f"opentaskpy.plugins.lookup.{plugin}" not in sys.modules:
            plugin_path = f"{self.config_dir}/plugins/lookup/{plugin}.py"
            if os.path.isfile(plugin_path):
                spec = importlib.util.spec_from_file_location(
                    f"opentaskpy.plugins.lookup.{plugin}", plugin_path
                )
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                sys.modules[f"opentaskpy.plugins.lookup.{plugin}"] = module

        # If we are in noop mode, then don't actually run the plugin
        if "OTF_NOOP" in os.environ and os.environ["OTF_NOOP"] == "true":
            return "noop"

        # Run the run function of the imported module
        return str(
            getattr(  # noqa: B009
                sys.modules[f"opentaskpy.plugins.lookup.{plugin}"], "run"
            )(**kwargs)
        )

    # TASK DEFINITION FIND FILE
    def load_task_definition(self, task_id: str, cache: bool = True) -> dict:
        """Load the task definition from the config directory.

        Args:
            task_id (str): The id of the task to load
            cache (bool, optional): Whether to use the cache or load from disk. Defaults to True.

        Raises:
            DuplicateConfigFileError: Raised if more than one config file is found
            matching the task_id
            FileNotFoundError: Raised if no config file is found matching the task_id

        Returns:
            dict: A dictionary representing the task definition
        """
        if not cache:
            self._preload_files()

        # Search for files matching the task_id in the preloaded cache
        matching_files = [
            path
            for path in self.file_cache
            if path.endswith(f"{task_id}.json") or path.endswith(f"{task_id}.json.j2")
        ]

        if not matching_files or len(matching_files) != 1:
            if len(matching_files) > 1:
                raise DuplicateConfigFileError(
                    f"Found more than one task with name: {task_id}"
                )

            raise FileNotFoundError(f"Couldn't find task with name: {task_id}")

        found_file = matching_files[0]
        self.logger.log(12, f"Found: {found_file}")

        task_definition = self._enrich_variables(found_file)

        # If the task has any variables, we need to check if they're overridden by environment variables
        if "variables" in task_definition:
            self._override_variables_from_env(task_definition["variables"], "task")

        # Check to see if this is not a batch type
        if "type" in task_definition and task_definition["type"] == "batch":
            self.logger.debug("Cannot apply overrides to batch tasks")
            return task_definition

        # Finally, attributes of the task definition can also be overridden by environment variables
        # e.g. OTF_OVERRIDE_TRANSFER_SOURCE_HOSTNAME will override ["source"]["hostname"], we need to handle this
        # The format is OTF_OVERRIDE_<TASK_TYPE>_<ATTRIBUTE>_<ATTRIBUTE>_<ATTRIBUTE>
        # e.g. OTF_OVERRIDE_TRANSFER_SOURCE_HOSTNAME
        # Some special cases need to be handled, e.g. OTF_OVERRIDE_EXECUTION_PROTOCOL!!SOME_ATTRIBUTE
        # This is where the attribute contains the delimiter itself, so a split by _ will not work
        for key, value in os.environ.items():
            if key.startswith("OTF_OVERRIDE_"):
                # Split the key by _ but handle !! special case first
                split_key: list[str] = []
                while "!!" in key:
                    # Split into parts before and after !! from right
                    prefix, property_name = key.rsplit("!!", maxsplit=1)
                    # Add the property name to the start of the split key list
                    split_key.insert(0, property_name)
                    key = prefix
                # Split the prefix normally by _ and remove OTF_OVERRIDE_
                split_key = key.split("_")[3:] + split_key

                self._apply_env_var_overrides_to_task_definition(
                    task_definition, split_key, value
                )

        return task_definition

    def _apply_env_var_overrides_to_task_definition(
        self, task_definition: dict, split_key: list[str], value: str
    ) -> None:
        attribute = split_key[0]

        # Match the attribute, to an attribute in the task_definition, bearing in mind that the case may not match
        # e.g. "source" may be "Source"
        for task_definition_attribute in task_definition:
            if task_definition_attribute.lower() == attribute.lower():
                attribute = task_definition_attribute
                break

        # Check that the attribute exists in the definition, if not just ignore it and move on to the next override
        if attribute not in task_definition:
            return

        if len(split_key) == 1:
            self.logger.info(
                f"Overriding {attribute}: {task_definition[attribute]} with {value}"
            )
            task_definition[attribute] = value
        elif isinstance(task_definition[attribute], list):
            # If the current attribute is a list, then we need to get the index from the next element
            # e.g. ["source"]["files"][0]["filename"]
            index = int(split_key[1])
            self._apply_env_var_overrides_to_task_definition(
                task_definition[attribute][index], split_key[2:], value
            )
        else:
            self._apply_env_var_overrides_to_task_definition(
                task_definition[attribute], split_key[1:], value
            )

    # POPULATE VARIABLES INSIDE TASK DEFINITION
    # AND LOAD ADDITIONAL VARIABLES FROM TASK DEFINITION
    def _enrich_variables(self, task_definition_file: str) -> dict:
        active_task_definition = None
        with open(task_definition_file, encoding="utf-8") as json_file:
            json_content = json_file.read()
            template = self.template_env.from_string(json_content)

            # If the file is a Jinja2 template, then we do not allow additional
            # variables to be defined in the task definition.
            # Check the file extension
            if not task_definition_file.endswith(".j2"):
                # From this, convert it to JSON and pull out the variables key if there is one
                task_definition = json.loads(json_content)
                # Extend or replace any local variables for this task
                if "variables" in task_definition:
                    self.global_variables = (
                        self.global_variables | task_definition["variables"]
                    )

                template = self.template_env.from_string(json_content)

            self._load_filters(template.globals)

            # Define lookup function
            template.globals["lookup"] = self.template_lookup

            # Using the active task definition, resolve any templated variables
            # Find any variables that are templated from the template object
            if self.lazy_load:

                ast = self.template_env.parse(json_content)
                undeclared_variables = meta.find_undeclared_variables(ast)

                self.logger.log(
                    12,
                    f"Found undeclared variables: {undeclared_variables}",
                )

                # For each undeclared variable, resolve it
                for undeclared_variable in undeclared_variables:

                    # Get the value of the variable from global variables, if it exists,
                    # if it doesn't it must be a task variable, so this can be resolved below
                    if undeclared_variable not in self.global_variables:
                        self.logger.log(
                            12,
                            f"Variable {undeclared_variable} not found in global variables, must be a task variable",
                        )
                        continue

                    unresolved_variable = self.global_variables[undeclared_variable]

                    # Check the type of the variable, if it's not a string, then dump it into a JSON string
                    converted_variable = False
                    if not isinstance(unresolved_variable, str):
                        self.logger.debug(
                            "Converted unresolved variable into a RAW string"
                        )
                        unresolved_variable = json.dumps(unresolved_variable)
                        converted_variable = True

                    self.logger.info(f"Resolving variable {undeclared_variable}")
                    evaluated_variable = self._resolve_templated_variables_from_string(
                        unresolved_variable
                    )

                    self.logger.log(
                        12,
                        f"Resolved variable {undeclared_variable}",
                    )

                    # If the variable was not a string, then convert it back to the original type
                    if converted_variable:
                        self.logger.debug("Converting variable back into a JSON object")
                        evaluated_variable = json.loads(evaluated_variable)

                    # Now update the global variables with the resolved value
                    self.global_variables[undeclared_variable] = evaluated_variable

            rendered_template = template.render(self.global_variables)
            active_task_definition = dict(json.loads(rendered_template))
            self.logger.log(
                12,
                f"Evaluated task definition: {opentaskpy.otflogging.redact(json.dumps(active_task_definition))}",
            )

        return active_task_definition

    # READ AND PARSE ACTUAL VARIABLE FILES
    def _load_global_variables(self) -> None:
        global_variables: dict = {}
        variable_configs: list[str] = []

        # See if variables file(s) have been overridden via environment variable
        if "OTF_VARIABLES_FILE" in os.environ:
            new_variables_files = os.environ["OTF_VARIABLES_FILE"].split(",")
            for new_variables_file in new_variables_files:
                self.logger.info(f"Overriding variables file with {new_variables_file}")
                # Validate that the file exists
                if not os.path.isfile(new_variables_file):
                    raise FileNotFoundError(
                        f"Couldn't find variables file: {new_variables_file}"
                    )
                variable_configs.append(new_variables_file)

        else:
            file_types = (".json.j2", ".json")
            for file_type in file_types:
                variable_configs.extend(
                    glob(f"{self.config_dir}/**/variables{file_type}", recursive=True)
                )

            if not variable_configs:
                raise FileNotFoundError(
                    "Couldn't find any variables.(json|json.j2) files under"
                    f" {self.config_dir}"
                )

        for variable_file in variable_configs:
            with open(variable_file, encoding="utf-8") as json_file:
                this_variable_config = json.load(json_file)
                global_variables = global_variables | this_variable_config

        self.global_variables = global_variables

    # RESOLVE ANY VARIABLES THAT USE OTHER VARIABLES IN THE VARIABLE FILES
    def _resolve_templated_variables(self, lazy_load: bool = False) -> None:
        # We need to evaluate the variables themselves, in case there's any recursion
        # Convert the variables to a JSON string which we can process with the jinja2 templater
        current_depth = 0
        previous_render = None

        template = self.global_variables

        variables_template = self.template_env.from_string(json.dumps(template))
        self._load_filters(variables_template.globals)

        # Define lookup function
        variables_template.globals["lookup"] = self.template_lookup

        # Don't do anything if lazy loading is enabled
        if lazy_load:
            return

        evaluated_variables = variables_template.render(template)

        while evaluated_variables != previous_render and current_depth < MAX_DEPTH:
            previous_render = evaluated_variables

            variables_template = self.template_env.from_string(evaluated_variables)
            self._load_filters(variables_template.globals)

            # Define lookup function
            variables_template.globals["lookup"] = self.template_lookup
            evaluated_variables = variables_template.render(
                json.loads(evaluated_variables)
            )

            current_depth += 1
            if current_depth >= MAX_DEPTH:
                self.logger.error(
                    "Reached max depth of recursive template evaluation. Please check"
                    " the task as variable definitions for infinite recursion"
                )
                raise VariableResolutionTooDeepError(
                    "Reached max depth of recursive template evaluation"
                )

        self.global_variables = json.loads(evaluated_variables)

    def _resolve_templated_variables_from_string(self, json_content: str) -> str:
        # This has some code duplication with _resolve_templated_variables, but it's
        # easier to keep them separate for now

        # We need to evaluate the variables themselves, in case there's any recursion
        # Convert the variables to a JSON string which we can process with the jinja2 templater
        current_depth = 0
        previous_render = None

        variables_template = self.template_env.from_string(json_content)
        self._load_filters(variables_template.globals)

        # Define lookup function
        variables_template.globals["lookup"] = self.template_lookup

        evaluated_variables = variables_template.render(self.global_variables)

        while evaluated_variables != previous_render and current_depth < MAX_DEPTH:
            previous_render = evaluated_variables

            variables_template = self.template_env.from_string(evaluated_variables)

            self._load_filters(variables_template.globals)

            # Define lookup function
            variables_template.globals["lookup"] = self.template_lookup
            evaluated_variables = variables_template.render(self.global_variables)

            current_depth += 1
            if current_depth >= MAX_DEPTH:
                self.logger.error(
                    "Reached max depth of recursive template evaluation. Please check"
                    " the task as variable definitions for infinite recursion"
                )
                raise VariableResolutionTooDeepError(
                    "Reached max depth of recursive template evaluation"
                )

        return str(evaluated_variables)
