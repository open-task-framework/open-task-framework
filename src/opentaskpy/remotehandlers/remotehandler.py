"""Abstract classes for remote handlers."""

from abc import ABC, abstractmethod
from typing import Any

TransferFileSet = list[str] | dict[str, Any]


class RemoteHandler(ABC):
    """Parent class for remote handlers."""

    def __init__(self, spec: dict):
        """Initialise the handler.

        Args:
            spec (dict): The spec for the handler.
        """
        self.spec = spec

    def tidy(self) -> None:
        """Tidy up any underlying connection state."""

    def kill(self) -> None:
        """Attempt to stop any remote work in progress."""

    def set_handler_vars(self, protocol_vars: dict) -> None:
        """Set any protocol-specific variables for the handler."""


class RemoteTransferHandler(RemoteHandler):
    """Abstract class for remote transfer handlers."""

    def __init__(self, spec: dict, remote_spec: dict | None = None):
        """Initialise the handler.

        Args:
            spec (dict): The spec for the transfer.
            remote_spec (dict, optional): The remote spec for the transfer. Defaults to None.
        """
        self.remote_spec = remote_spec
        # Call super with the spec
        super().__init__(spec)

    @abstractmethod
    def supports_direct_transfer(self) -> bool:
        """Check if the remote handler supports direct transfers."""

    @abstractmethod
    def list_files(
        self, directory: str | None = None, file_pattern: str | None = None
    ) -> dict:
        """Generate a list of files to transfer."""

    @abstractmethod
    def transfer_files(
        self,
        files: TransferFileSet,
        remote_spec: dict,
        dest_remote_handler: "RemoteTransferHandler" | None = None,
    ) -> int:
        """Transfer files to the remote location.

        Args:
            files (list[str]): The files to transfer.
            remote_spec (dict): The remote spec for the transfer.
            dest_remote_handler (RemoteTransferHandler, optional): The remote handler for the destination. Defaults to None.

        Returns:
            int: The result of the transfer. 0 for success, 1 for failure.
        """

    @abstractmethod
    def push_files_from_worker(
        self, local_staging_directory: str, file_list: dict | None = None
    ) -> int:
        """Push files from the worker to the remote location.

        This is used when files have been either generated on the worker, or copied
        as a proxy transfer onto the worker.

        Args:
            local_staging_directory (str): The local staging directory.
            file_list (dict, optional): The list of files to transfer. Defaults to None.

        Returns:
            int: The result of the transfer. 0 for success, 1 for failure.
        """

    @abstractmethod
    def pull_files_to_worker(
        self, files: TransferFileSet, local_staging_directory: str
    ) -> int:
        """Pull files from the remote location to the worker.

        Args:
            files (list[str]): The files to pull.
            local_staging_directory (str): The local staging directory.

        Returns:
            int: The result of the transfer. 0 for success, 1 for failure.
        """

    @abstractmethod
    def pull_files(
        self, files: TransferFileSet, remote_spec: dict | None = None
    ) -> int:
        """Pull files from the remote location to the destination system.

        Used when a direct push cannot be done, and the files need to be pulled instead.

        Args:
            files (list[str]): The files to pull.
            remote_spec (dict, optional): The remote spec for the transfer. Defaults to None.

        Returns:
            int: The result of the transfer. 0 for success, 1 for failure.
        """

    @abstractmethod
    def move_files_to_final_location(self, files: TransferFileSet) -> int:
        """Move files to their final location.

        Once dropped on the destination system, the files may need to be moved to their
        final location.

        Args:
            files (dict): The files to move.

        Returns:
            int: The result of the transfer. 0 for success, 1 for failure.
        """

    @abstractmethod
    def handle_post_copy_action(self, files: TransferFileSet) -> int:
        """Handle any post copy actions.

        Post Copy Actions (PCA) are actions that need to be performed after the files
        have been copied to the destination system and are in their final location. The
        PCA acts on the source files, and will typically delete them, move them, or
        rename them.

        Args:
            files (list[str]): The files to act on.

        Returns:
            int: The result of the transfer. 0 for success, 1 for failure.
        """

    def handle_cacheable_variables(self) -> None:
        """Handle cacheable variables.

        This method is called whenever appropriate in the flow of the remote handler. It
        should handle any cacheable variables that need to be updated by calling the
        appropriate caching plugin.
        """

    def init_logwatch(self) -> int:
        """Initialise log watch support if the handler implements it."""
        raise NotImplementedError

    def do_logwatch(self) -> int:
        """Perform one log watch poll if the handler implements it."""
        raise NotImplementedError

    def create_flag_files(self) -> int:
        """Create any remote flag files required by the handler."""
        raise NotImplementedError

    def obtain_variable_from_spec(self, variable_name: str, spec: dict) -> str:
        """Using the spec, obtain the current value of the variable.

        Args:
            variable_name (str): The name of the variable to obtain.
            spec (dict): The spec to search for the variable.

        Returns:
            str: The value of the variable.
        """
        # Look in the dictionary for the variable based on the variable name
        # e.g. if the variable name is x.y obtain the value of spec['x']['y']
        # We also need to handle arrays e.g. x.y[0] should return spec['x']['y'][0]

        # Not ideal, but don't want this loading all the time for no reason
        from re import match  # pylint: disable=import-outside-toplevel

        from omegaconf import OmegaConf  # pylint: disable=import-outside-toplevel

        # pylint: disable-next=unused-variable
        dotted_dict = OmegaConf.create(spec)  # noqa: F841

        # Validate the variable_name is something safe, and just a string
        if not match(r"^[\w.\[\]]+$", variable_name):
            raise ValueError(
                f"Variable name {variable_name} is not a valid variable name."
            )

        # Eval is needed explicitly here, the above should prevent the majority of bad
        # code being executed
        return str(eval(f"dotted_dict.{variable_name}"))  # nosec: B307


class RemoteExecutionHandler(RemoteHandler):
    """Abstract class for remote execution handlers."""

    @abstractmethod
    def execute(self) -> bool:
        """Execute the command.

        Returns:
            bool: True if the command was successful, False otherwise.
        """
