"""Dummy Handler.

This module doesn't actually do anything, it's just used for testing the cacheable
variables.
"""

from collections.abc import Collection
from random import randint

from opentaskpy.config.variablecaching import cache_utils
from opentaskpy.remotehandlers.remotehandler import RemoteTransferHandler


class DummyTransfer(RemoteTransferHandler):
    """Dummy Transfer Handler."""

    TASK_TYPE = "T"

    def __init__(self, spec: dict):
        """Initialise the handler.

        Args:
            spec (dict): The spec for the transfer. This is either the source, or the
            destination spec.
        """
        super().__init__(spec)

        # Pretend that this handler does something, and gets a new accessToken, we need
        # to update the cache with this new value
        self.spec["accessToken"] = randint(1, 100000)

        # If there's cacheable variables, handle them
        if "cacheableVariables" in spec:
            self.handle_cacheable_variables()

    def handle_cacheable_variables(self) -> None:
        """Handle the cacheable variables."""
        # Obtain the "updated" value from the spec
        for cacheable_variable in self.spec["cacheableVariables"]:

            updated_value = self.obtain_variable_from_spec(
                cacheable_variable["variableName"], self.spec
            )

            cache_utils.update_cache(cacheable_variable, updated_value)

    def supports_direct_transfer(self) -> bool:
        """Return False, as a direct transfer is not supported."""
        return False

    def list_files(
        self,
        directory: str | None = None,  # noqa: ARG002
        file_pattern: str | None = None,  # noqa: ARG002
    ) -> dict:
        """Return list of files that match the source definition.

        Args:
            directory (str, optional): The directory to search in. Defaults to None.
            file_pattern (str, optional): The file pattern to search for. Defaults to
            None.

        Returns:
            dict: A dict of files that match the source definition.
        """
        return {}

    def pull_files_to_worker(
        self, files: Collection[str], local_staging_directory: str  # noqa: ARG002
    ) -> int:
        """Pull files to the worker.

        This is not applicable for a local transfer, since the files are local already.
        The files will not be transferred as they'll just fill up the worker's disk for
        no reason.

        All args are not used because this function literally does nothing.

        Args:
            files (list): A list of files to download.
            local_staging_directory (str): The local staging directory to move the files
            into.

        Returns:
            int: Always returns 0
        """
        return 0

    def push_files_from_worker(
        self, local_staging_directory: str, file_list: dict | None = None
    ) -> int:
        """Not implemented for this handler."""
        raise NotImplementedError

    def transfer_files(
        self,
        files: Collection[str],
        remote_spec: dict,
        dest_remote_handler: RemoteTransferHandler | None = None,
    ) -> int:
        """Not implemented for this handler."""
        raise NotImplementedError

    def pull_files(
        self, files: Collection[str], remote_spec: dict | None = None
    ) -> int:
        """Not implemented for this handler."""
        raise NotImplementedError

    def move_files_to_final_location(self, files: Collection[str]) -> int:
        """Not implemented for this handler."""
        raise NotImplementedError

    def handle_post_copy_action(self, files: Collection[str]) -> int:  # noqa: ARG002
        """Handle the post copy action specified in the config.

        Args:
            files (list[str]): A list of files that need to be handled.

        Returns:
            int: 0 if successful, 1 if not.
        """
        return 0

    def create_flag_files(self) -> int:
        """Create the flag files on the remote host.

        Raises:
            NotImplementedError: This method is not implemented for this handler.
        """
        raise NotImplementedError
