"""Abstract task handler class."""

import threading
from abc import ABC, abstractmethod
from importlib import import_module
from logging import Logger
from sys import modules
from typing import Any, NamedTuple, cast

import opentaskpy.otflogging
from opentaskpy.exceptions import UnknownProtocolError
from opentaskpy.remotehandlers.remotehandler import RemoteHandler


class DefaultProtocolCharacteristics(NamedTuple):
    """Class defining the configuration for default protocols."""

    module: str
    class_: str


class TaskHandler(ABC):
    """Abstract task handler class."""

    TASK_TYPE: str = ""

    DEFAULT_PROTOCOL_MAP = {
        "T": {
            "ssh": DefaultProtocolCharacteristics(
                "opentaskpy.remotehandlers.ssh", "SSHTransfer"
            ),
            "sftp": DefaultProtocolCharacteristics(
                "opentaskpy.remotehandlers.sftp", "SFTPTransfer"
            ),
            "email": DefaultProtocolCharacteristics(
                "opentaskpy.remotehandlers.email", "EmailTransfer"
            ),
            "local": DefaultProtocolCharacteristics(
                "opentaskpy.remotehandlers.local", "LocalTransfer"
            ),
            "dummy": DefaultProtocolCharacteristics(
                "opentaskpy.remotehandlers.dummy", "DummyTransfer"
            ),
        },
        "E": {
            "ssh": DefaultProtocolCharacteristics(
                "opentaskpy.remotehandlers.ssh", "SSHExecution"
            ),
            "local": DefaultProtocolCharacteristics(
                "opentaskpy.remotehandlers.local", "LocalExecution"
            ),
        },
    }

    logger: Logger
    overall_result: bool
    task_id: str
    handled_exception: bool = False

    _protocol_classes: dict[str, type[RemoteHandler]] = {}  # Class-level cache
    _addon_packages: dict[str, type[RemoteHandler]] = (
        {}
    )  # Class-level cache for addon packages
    _protocol_lock = threading.Lock()  # Lock for class-level cache

    def __init__(self, global_config: dict[str, Any] | None):
        """Initialize the class."""
        self.global_config = global_config

    def return_result(
        self,
        status: int,
        message: str | None = None,
        exception: type[Exception] | Exception | None = None,
    ) -> bool:
        """Return the result of the task run.

        Args:
            status (int): The return code of the task run. 0 is success, anything else is failure.
            message (str): Message to return.
            exception (Exception, optional): Exception to return. Defaults to None.

        Returns:
            bool: True if the task was successful, False otherwise.
        """
        if message:
            if status == 0:
                self.logger.info(message)
            else:
                self.logger.error(message)

        if status == 0:
            self.overall_result = True

        opentaskpy.otflogging.close_log_file(self.logger, self.overall_result)

        # Throw an exception if we have one
        if exception and not self.handled_exception:
            self.handled_exception = True
            if isinstance(exception, type) and issubclass(exception, Exception):
                raise exception(message or "")

            raise Exception(message or "")  # pylint: disable=broad-exception-raised

        return status == 0

    @abstractmethod
    def _set_remote_handlers(self) -> None: ...

    @abstractmethod
    def run(self, kill_event: threading.Event | None = None) -> bool:
        """Run the task handler.

        Returns:
            bool: True if the task was successful, False otherwise.
        """

    def _set_handler_vars(
        self, source_protocol: str, remote_handler: RemoteHandler
    ) -> None:
        # If remote handler has a set handler vars method, call it and pass in any variables it might want
        if hasattr(remote_handler, "set_handler_vars"):
            self.logger.log(12, f"Setting handler vars for {source_protocol}")

            # Read the protocol specific variables from the global config
            if (
                self.global_config
                and "global_protocol_vars" in self.global_config
                and next(
                    (
                        item
                        for item in self.global_config["global_protocol_vars"]
                        if item["name"] == source_protocol
                    ),
                )
            ):
                protocol_vars = next(
                    (
                        item
                        for item in self.global_config["global_protocol_vars"]
                        if item["name"] == source_protocol
                    ),
                ).copy()
                # Remove "name" from the dict
                del protocol_vars["name"]

                remote_handler.set_handler_vars(protocol_vars)

    def _get_handler_for_protocol(
        self, protocol_name: str, spec: dict[str, Any]
    ) -> RemoteHandler:
        """Get the handler for a protocol.

        Looks for the protocol package to import. An addon must be accessible in the
        PYTHONPATH to be found and loaded.

        Args:
            protocol_name (str): The name of the protocol.
            spec (dict): The spec for the protocol.

        Raises:
            UnknownProtocolError: Raised if the protocol is unknown.

        Returns:
            RemoteHandler: The remote handler for the protocol.
        """
        # Remove the class name from the end of addon_protocol
        addon_package = ".".join(protocol_name.split(".")[:-1])

        if addon_package == "":
            raise UnknownProtocolError(f"Unknown protocol {protocol_name}")

        try:
            addon_class = self._addon_packages[protocol_name]
            self.logger.debug(f"Using cached addon class for {protocol_name}")
            return addon_class(spec)
        except KeyError:
            self.logger.debug(
                f"Addon package {protocol_name} not yet loaded, importing..."
            )
            with self._protocol_lock:
                if protocol_name not in self._addon_packages:
                    try:
                        if addon_package not in modules:
                            self.logger.debug(
                                f"Thread {threading.current_thread().name} importing {addon_package}"
                            )
                            import_module(addon_package)

                        addon_class = cast(
                            type[RemoteHandler],
                            getattr(
                                modules[addon_package], protocol_name.split(".")[-1]
                            ),
                        )
                        self._addon_packages[protocol_name] = addon_class
                    except ModuleNotFoundError as exc:
                        raise UnknownProtocolError(
                            f"Unknown protocol {protocol_name}"
                        ) from exc
                else:
                    self.logger.debug(
                        f"Thread {threading.current_thread().name} addon {protocol_name} already loaded (inside lock)"
                    )
                addon_class = self._addon_packages[protocol_name]

        return addon_class(spec)

    def _get_default_class(
        self, task_type: str, protocol_name: str
    ) -> type[RemoteHandler]:
        try:
            return self._protocol_classes[protocol_name]  # Fast path when cached
        except KeyError:
            self.logger.debug(
                f"Protocol: {protocol_name} - has not yet been loaded, importing..."
            )
            self.logger.debug(
                f"Thread {threading.current_thread().name} waiting for protocol lock"
            )
            with self._protocol_lock:  # Slow path with lock
                self.logger.debug(
                    f"Thread {threading.current_thread().name} acquired protocol lock"
                )
                if protocol_name not in self._protocol_classes:  # Double-check
                    class_name = self.DEFAULT_PROTOCOL_MAP[task_type][
                        protocol_name
                    ].class_
                    module_name = self.DEFAULT_PROTOCOL_MAP[task_type][
                        protocol_name
                    ].module
                    if module_name not in modules:
                        self.logger.debug(
                            f"Thread {threading.current_thread().name} importing {module_name}"
                        )
                        import_module(module_name)
                    self._protocol_classes[protocol_name] = getattr(
                        modules[module_name], class_name
                    )
                else:
                    self.logger.debug(
                        f"Thread {threading.current_thread().name} protocol {protocol_name} already loaded (inside lock)"
                    )
                self.logger.debug(
                    f"Thread {threading.current_thread().name} releasing protocol lock"
                )
                return self._protocol_classes[protocol_name]
