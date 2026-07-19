"""Schemas for the configuration files."""

import copy
import importlib
import json
import sys
from importlib.resources import files
from pathlib import Path
from typing import cast

from jsonschema import Draft202012Validator, validate, validators
from jsonschema.exceptions import ValidationError
from referencing import Registry, Resource

import opentaskpy.otflogging

TRANSFER_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "type": {"type": "string"},
        "source": {
            "type": "object",
            "properties": {
                "protocol": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                    },
                    "required": ["name"],
                },
            },
            "required": ["protocol"],
        },
        "destination": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "protocol": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                        },
                        "required": ["name"],
                    },
                },
                "required": ["protocol"],
            },
        },
        "variables": {"type": "object"},
    },
    "required": ["type", "source"],
}

# Determine the type of transfer, and apply the correct sub schema based on the protocol used

EXECUTION_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "type": {"type": "string"},
        "protocol": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
            },
            "required": ["name"],
        },
        "variables": {"type": "object"},
    },
    "required": ["type", "protocol"],
}

# Declare a constant that cannot be changed


BATCH_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "type": {"type": "string"},
        "tasks": {
            "type": "array",
            "items": {"$ref": "http://localhost/batch/tasks.json"},
        },
    },
    "required": ["type", "tasks"],
}

logger = opentaskpy.otflogging.init_logging(__name__)

SCHEMAS = Path(str(files("opentaskpy.config").joinpath("schemas")))


def _extend_with_default(validator_class):  # type: ignore[no-untyped-def]
    validate_properties = validator_class.VALIDATORS["properties"]

    def set_defaults(validator, properties, instance, schema):  # type: ignore[no-untyped-def]
        for _property, subschema in properties.items():
            if "default" in subschema:
                instance.setdefault(_property, subschema["default"])

        yield from validate_properties(
            validator,
            properties,
            instance,
            schema,
        )

    return validators.extend(
        validator_class,
        {"properties": set_defaults},
    )


DefaultValidatingValidator = _extend_with_default(Draft202012Validator)  # type: ignore[no-untyped-call]


def _retrieve_from_filesystem(uri: str):  # type: ignore[no-untyped-def]
    if uri.startswith("http://localhost/"):
        path = SCHEMAS.joinpath(Path(uri.removeprefix("http://localhost/")))
    else:
        path = Path(uri.removeprefix("file://"))
    contents = json.loads(path.read_text(encoding="utf-8"))

    return Resource.from_contents(contents)


def validate_transfer_json(json_data: dict) -> bool:
    """Validate the JSON data against the transfer schema.

    Args:
        json_data (dict): The Transfer JSON definition

    Returns:
        bool: Whether the JSON data is valid or not
    """
    new_schema: dict

    try:

        # Load the schema file for XXX_source
        resolver = Registry(retrieve=_retrieve_from_filesystem)  # type: ignore[call-arg]

        validator = DefaultValidatingValidator(
            TRANSFER_SCHEMA,
            registry=resolver,
        )
        validator.validate(json_data)

        # If this works, then determine the protocol and apply the correct sub schema
        # Source protocol
        source_protocol = json_data["source"]["protocol"]["name"]

        # Dynamically apply the correct sub schema based on the protocol
        # We need to locate the schema files from the base location of this package
        # Get the directory of this package

        schema_dir = files("opentaskpy.config").joinpath("schemas")
        # This gets us the right path for default protocol schemas. But we need to be able to load custom schemas too
        # based on the protocol name, we need to find the location of the package using the files() function

        # source_protocol is the class name within the plugin, we need to determine if it's a default protocol or a custom one
        # If it's a default protocol, then we can use the files() function to get the path to the schema file
        # If it's a custom protocol, then we need to look in the plugins directory for the schema file
        # Default protocols are the only ones that aren't prefixed with a package name, and we don't need to do anything more
        if "." in source_protocol:
            # Get the full package name from the class name (strip the class off the end)
            if (
                package_name := ".".join(source_protocol.split(".")[:-2])
            ) not in sys.modules:
                # Check the module is loadable
                importlib.import_module(package_name)
            # Get the path to the module
            module_path = files(package_name).joinpath("schemas")

            # Shorten the source_protocol to just the name of the class
            source_protocol = source_protocol.split(".")[-2]

            # Append new path to the resolver
            resolver.with_resource(cast(Path, module_path).as_uri(), module_path)  # type: ignore[arg-type]
        else:
            # Default protocol
            module_path = schema_dir

        # Schema reference name should be schemas/transfer/xxx_source
        source_schema_name = Path(
            f"{module_path}/transfer/{source_protocol}_source.json"
        ).as_uri()

        # Destination protocol can be different for each destination in the array. Loop through each destination and get the protocol name
        schema_refs = []
        if "destination" in json_data:
            for destination in json_data["destination"]:
                # Get the protocol name
                destination_protocol = destination["protocol"]["name"]
                # As above, we need to determine the path of the protocol schema file if it's not a default protocol
                if "." in destination_protocol:
                    # Get the full package name from the class name (strip the class off the end)
                    package_name = ".".join(destination_protocol.split(".")[:-2])

                    if package_name not in sys.modules:
                        # Check the module is loadable
                        importlib.import_module(package_name)
                    # Get the path to the module
                    module_path = files(package_name).joinpath("schemas")

                    # Shorten the destination_protocol to just the name of the class
                    destination_protocol = destination_protocol.split(".")[-2]

                    # Append new path to the resolver
                    resolver.with_resource(cast(Path, module_path).as_uri(), module_path)  # type: ignore[arg-type]
                else:
                    # Default protocol
                    module_path = schema_dir

                schema_def = {
                    "$ref": (
                        Path(
                            f"{module_path}/transfer/{destination_protocol}_destination.json"
                        ).as_uri()
                    )
                }

                # If schema_refs does not already contain the schema_def, then append it
                if schema_def not in schema_refs:
                    schema_refs.append(schema_def)

        # Update the TRANSFER_SCHEMA with the correct sub schema reference
        new_schema = copy.deepcopy(TRANSFER_SCHEMA)
        new_schema["properties"]["source"] = {"$ref": source_schema_name}

        # Now update the new_schema so that ["properties"]["destination"]["items"]["$ref"] = the list of destination protocols schema references
        # Schema reference name should be schemas/transfer/xxx_destination

        if "destination" in json_data and len(json_data["destination"]) > 0:
            new_schema["properties"]["destination"] = {
                "type": "array",
                "minItems": 0,
                "items": {
                    "oneOf": schema_refs,
                },
            }

        # Validate the new schema
        validator = DefaultValidatingValidator(
            new_schema,
            registry=resolver,
        )
        validator.validate(json_data)

    except ValidationError as err:
        print(err.message)  # noqa: T201
        logger.error(err.message)
        return False
    return True


def validate_execution_json(json_data: dict) -> bool:
    """Validate the JSON data against the execution schema.

    Args:
        json_data (dict): The Execution JSON definition

    Returns:
        bool: Whether the JSON data is valid or not
    """
    try:
        validate(instance=json_data, schema=EXECUTION_SCHEMA)

        # If this works, then determine the protocol and apply the correct sub schema
        protocol = json_data["protocol"]["name"]

        # Dynamically apply the correct sub schema based on the protocol
        # We need to locate the schema files from the base location of this package
        # Get the directory of this package
        schema_dir = files("opentaskpy.config").joinpath("schemas")

        # Load the schema file for xxx
        resolver = Registry(retrieve=_retrieve_from_filesystem)  # type: ignore[call-arg]

        if "." in protocol:
            # Get the full package name from the class name (strip the class off the end)
            if (package_name := ".".join(protocol.split(".")[:-2])) not in sys.modules:
                # Check the module is loadable
                importlib.import_module(package_name)
            # Get the path to the module
            module_path = files(package_name).joinpath("schemas")

            # Shorten the protocol to just the name of the class
            protocol = protocol.split(".")[-2]

            # Append new path to the resolver
            resolver.with_resource(cast(Path, module_path).as_uri(), module_path)  # type: ignore[arg-type]
        else:
            # Default protocol
            module_path = schema_dir

        # Schema reference name should be schemas/execution/xxx
        schema_name = Path(
            f"{module_path}/execution/{protocol}/{protocol}.json"
        ).as_uri()

        # Update the schema with the correct sub schema reference
        new_schema = {}
        new_schema["$ref"] = schema_name

        # Validate the new schema
        # Validate the new schema
        validator = DefaultValidatingValidator(
            new_schema,
            registry=resolver,
        )
        validator.validate(json_data)

    except ValidationError as err:
        print(err.message)  # noqa: T201
        logger.error(err.message)
        return False
    return True


def validate_batch_json(json_data: dict) -> bool:
    """Validate the JSON data against the batch schema.

    Args:
        json_data (dict): The Batch JSON definition

    Returns:
        bool: Whether the JSON data is valid or not
    """
    try:
        # Load the schema file for xxx
        resolver = Registry(retrieve=_retrieve_from_filesystem)  # type: ignore[call-arg]

        validator = DefaultValidatingValidator(
            BATCH_SCHEMA,
            registry=resolver,
        )
        validator.validate(json_data)

    except ValidationError as err:
        print(err.message)  # noqa: T201
        logger.error(err.message)
        return False
    return True
