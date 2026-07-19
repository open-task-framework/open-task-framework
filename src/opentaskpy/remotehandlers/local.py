"""Local Handler.

This module contains the local handlers for transfers.
"""

import glob
import logging
import os
import random
import re
import shutil
import stat
import subprocess
from collections.abc import Collection
from shlex import quote

import opentaskpy.otflogging
from opentaskpy.remotehandlers.remotehandler import (
    RemoteExecutionHandler,
    RemoteTransferHandler,
)

REMOTE_SCRIPT_BASE_DIR: str = "/tmp"  # nosec B108


class LocalTransfer(RemoteTransferHandler):
    """Local Transfer Handler."""

    TASK_TYPE = "T"

    FILE_NAME_DELIMITER = "|||"

    log_watch_start_row = 0

    def __init__(self, spec: dict):
        """Initialise the handler.

        Args:
            spec (dict): The spec for the transfer. This is either the source, or the
            destination spec.
        """
        self.logger = opentaskpy.otflogging.init_logging(
            __name__, spec["task_id"], self.TASK_TYPE
        )

        # Handle default values
        if "createDirectoryIfNotExists" not in spec:
            spec["createDirectoryIfNotExists"] = False

        super().__init__(spec)

    def supports_direct_transfer(self) -> bool:
        """Return False, as a direct transfer is not supported."""
        return False

    def list_files(
        self, directory: str | None = None, file_pattern: str | None = None
    ) -> dict:
        """Return list of files that match the source definition.

        Args:
            directory (str, optional): The directory to search in. Defaults to None.
            file_pattern (str, optional): The file pattern to search for. Defaults to
            None.

        Returns:
            dict: A dict of files that match the source definition.
        """
        if not directory:
            directory = str(self.spec["directory"])
        if not file_pattern:
            file_pattern = str(self.spec["fileRegex"])

        self.logger.info(
            f"Searching for files in {directory} with pattern {file_pattern}"
        )

        self.logger.log(
            12,
            f"[LOCAL] Searching in {directory} for files with pattern {file_pattern}",
        )

        files = None
        try:
            files = [
                f"{directory}/{f}"
                for f in os.listdir(directory)
                if re.match(file_pattern, f)
            ]
        except FileNotFoundError:
            files = []

        # For each file get the file age and size (in case we need them for file watches)
        result: dict = {}
        for file in files:
            file_stat = os.stat(file)
            modified_time = file_stat.st_mtime
            size = file_stat.st_size
            result[file] = {}
            result[file]["size"] = size
            result[file]["modified_time"] = modified_time
        return result

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
        """Push files from the worker to another local directory.

        Moves files from a local staging directory, to another local destination folder.

        Args:
            local_staging_directory (str): The local staging directory to upload the
            files from.
            file_list (dict, optional): A dictionary of files to transfer. Defaults to

        Returns:
            int: 0 if successful, 1 if not.
        """
        destination_directory = quote(self.spec["directory"])

        # Sanitize the destination directory
        destination_directory = quote(destination_directory)

        self.logger.info("[LOCALHOST] Validating destination dir")
        # Check if the local directory exists
        remote_dir_exists = False
        try:
            os.stat(destination_directory)
            remote_dir_exists = True
        except FileNotFoundError:
            self.logger.info(
                f"[LOCALHOST] Destination dir does not exist: {destination_directory}"
            )

        if not remote_dir_exists and not self.spec["createDirectoryIfNotExists"]:
            self.logger.error(
                f"[LOCALHOST] Destination dir does not exist: {destination_directory}"
            )
            return 1

        if not remote_dir_exists and self.spec["createDirectoryIfNotExists"]:
            self.logger.info(
                f"[LOCALHOST] Creating destination directory: {destination_directory}"
            )
            os.makedirs(destination_directory)

        # Transfer the files
        result = 0

        if file_list:
            files = list(file_list.keys())
        else:
            files = glob.glob(f"{local_staging_directory}/*")

        for file in files:
            file_name = os.path.basename(file)
            final_destination = f"{destination_directory}/{file_name}"
            self.logger.info(
                f"[LOCALHOST] Moving file to new location: {final_destination}"
            )

            # Handle any rename that might be specified in the spec
            if "rename" in self.spec:
                rename_regex = self.spec["rename"]["pattern"]
                rename_sub = self.spec["rename"]["sub"]

                file_name = re.sub(rename_regex, rename_sub, file_name)
                final_destination = f"{destination_directory}/{file_name}"

            mode = self.spec.get("mode", None)

            try:
                shutil.copy(file, final_destination)
                if mode:
                    os.chmod(final_destination, int(mode, base=8))

                self.logger.info(
                    f"[LOCALHOST] Copied file {file} to {final_destination}"
                )
            except Exception as ex:  # pylint: disable=broad-exception-caught
                self.logger.error(f"[LOCALHOST] Failed to move file: {ex}")
                result = 1

        return result

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

    def handle_post_copy_action(self, files: Collection[str]) -> int:
        """Handle the post copy action specified in the config.

        Args:
            files (list[str]): A list of files that need to be handled.

        Returns:
            int: 0 if successful, 1 if not.
        """
        if self.spec["postCopyAction"]["action"] == "delete":
            # Loop through each file and use the sftp client to delete the files

            for file in files:
                try:
                    self.logger.info(f"[LOCALHOST] Deleting file {file}")
                    os.remove(file)
                    self.logger.info(f"[LOCALHOST] Deleted file {file}")
                except OSError:
                    self.logger.error(
                        f"[LOCALHOST] Could not delete file {file} on source host"
                    )
                    return 1

        if (
            self.spec["postCopyAction"]["action"] == "move"
            or self.spec["postCopyAction"]["action"] == "rename"
        ):
            # Check that the destination directory exists
            move_dir = os.path.dirname(self.spec["postCopyAction"]["destination"])

            try:
                stat_result = os.stat(move_dir)
                # If it exists, then we need to ensure its a directory and not just a file
                if not stat.S_ISDIR(stat_result.st_mode):  # type: ignore[arg-type]
                    self.logger.error(
                        f"[LOCALHOST] Destination directory {move_dir} is"
                        " not a directory on source host"
                    )
                    return 1
            except OSError:
                self.logger.error(
                    f"[LOCALHOST] Destination directory {move_dir} does"
                    " not exist on source host"
                )
                return 1

                # Loop through the files and move them

            for file in files:
                try:
                    # If this is a move, then just move the file
                    if self.spec["postCopyAction"]["action"] == "move":
                        self.logger.info(
                            f"[LOCALHOST] Moving {file} to"
                            f" {self.spec['postCopyAction']['destination']}"
                        )
                        # Get the actual file name
                        file_name = os.path.basename(file)
                        os.rename(
                            file,
                            f"{self.spec['postCopyAction']['destination']}/{file_name}",
                        )
                        self.logger.info(
                            f"[LOCALHOST] Renamed file {file} to {self.spec['postCopyAction']['destination']}/{file_name}"
                        )
                    # If this is a rename, then we need to rename the file
                    if self.spec["postCopyAction"]["action"] == "rename":
                        # Determine the new file name
                        new_file_dir = os.path.dirname(
                            self.spec["postCopyAction"]["destination"]
                        )
                        current_file_name = os.path.basename(file)

                        rename_regex = self.spec["postCopyAction"]["pattern"]
                        rename_sub = self.spec["postCopyAction"]["sub"]

                        new_file_name = re.sub(
                            rename_regex, rename_sub, current_file_name
                        )

                        self.logger.info(
                            f"[LOCALHOST] Renaming {file} to"
                            f" {new_file_dir}/{new_file_name}"
                        )
                        os.rename(file, f"{new_file_dir}/{new_file_name}")
                        self.logger.info(
                            f"[LOCALHOST] Renamed file {file} to {new_file_dir}/{new_file_name}"
                        )
                except OSError as e:
                    self.logger.error(f"[LOCALHOST] Error: {e}")
                    self.logger.error(
                        f"[LOCALHOST] Error moving or renaming file {file}"
                    )
                    return 1

        return 0

    def create_flag_files(self) -> int:
        """Create the flag files on the remote host.

        Returns:
            int: 0 if successful, 1 if not.
        """
        filename = self.spec["flags"]["fullPath"]

        try:
            # Create an empty file at this path
            with open(filename, "w", encoding="utf-8"):
                pass

            # Set permissions on the file to whatever was specified in the spec,
            # otherwise we leave them as is
            # We cannot change ownership without using sudo, so we don't bother
            if "permissions" in self.spec:
                os.chmod(filename, int(self.spec["permissions"], base=8))

            self.logger.info(f"[LOCALHOST] Created flag file: {filename}")

        except OSError as e:
            self.logger.error(f"[LOCALHOST] Error: {e}")
            self.logger.error(f"[LOCALHOST] Error creating flag file: {filename}")
            return 1

        return 0


def log_stdout(str_stdout: str, hostname: str, logger: logging.Logger) -> None:
    """Log the stdout from a remote command in a nice format.

    Args:
        str_stdout (str): The stdout from the remote command
        hostname (str): The hostname of the remote host
        logger (logging.Logger): The logger to use
    """
    for line in str_stdout.splitlines():
        logger.info(f"[{hostname}] REMOTE OUTPUT: {line}")


class LocalExecution(RemoteExecutionHandler):
    """Class to handle local execution of commands."""

    TASK_TYPE = "E"
    ps_regex = r"(\S+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(.*)"
    remote_pid: int

    def __init__(self, spec: dict):
        """Initialise the LocalExecution class.

        Args:
            spec (dict): The specification for the command
        """
        self.remote_host: str = "LOCAL"
        self.random: int = random.randint(
            100000, 999999
        )  # Random number used to make sure when we kill stuff, we always kill the right thing

        self.logger = opentaskpy.otflogging.init_logging(
            __name__, spec["task_id"], self.TASK_TYPE
        )

        super().__init__(spec)

    def _get_child_processes(self, parent_pid: int, process_listing: list) -> list:
        """Get the child processes of a given PID.

        Args:
            parent_pid (int): The PID of the parent process
            process_listing (list): The list of processes running on the remote host

        Returns:
            list: A list of child PIDs
        """
        children = []
        for line in process_listing:
            match = re.search(self.ps_regex, line.decode("utf-8"))
            if match:
                if int(match.group(3)) == parent_pid:
                    child_pid = int(match.group(2))
                    # Never add PID 1 or 0!
                    if child_pid in (1, 0):
                        continue
                    self.logger.debug(
                        f"[LOCALHOST] Found child process with PID: {child_pid}"
                    )
                    children.append(child_pid)
                    # Recurse to find the children of this child
                    children.extend(
                        self._get_child_processes(child_pid, process_listing)
                    )
        return children

    def kill(self) -> None:
        """Kill the process."""
        self.logger.info("[LOCALHOST] Killing process")

        # We know the top level remote PID, we need to get all the child processes associated with it
        out = subprocess.check_output(["ps", "-ef"])
        process_listing = out.splitlines()

        # Now we have this, parse it, find the parent PID, and then all the children
        children = self._get_child_processes(self.remote_pid, process_listing)
        children.append(self.remote_pid)
        self.logger.info(
            f"[LOCALHOST] Found {len(children)} child processes to kill - {children}"
        )

        # Now we have the list of children, kill them
        command = f"kill {' '.join([str(x) for x in children])}"
        self.logger.info(f"[LOCALHOST] Killing processes with command: {command}")

        # Make sure we're not killing PID 1 or 0
        if command in ("kill 1", "kill 0"):
            self.logger.error("[LOCALHOST] Refusing to kill PID 1 or 0, aborting")
            return

        subprocess.call(command.split(" "))

    def execute(self) -> bool:
        """Execute the command.

        Returns:
            bool: True if the command was executed successfully, False otherwise
        """
        try:
            directory = quote(self.spec["directory"])

            command = (
                f"echo __OTF_TOKEN__$$_{self.random}__; cd {directory} &&"
                f" {self.spec['command']}"
            )

            self.logger.info(f"[LOCALHOST] Executing command: {command}")

            with subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                shell=True,  # nosec B602
            ) as process:
                # Log the stdout and stderr
                for line in iter(lambda: process.stdout.readline(2048), ""):  # type: ignore[union-attr]
                    # If we get an empty line, then we're done
                    if not line:
                        break
                    line = line.decode("utf-8")
                    log_stdout(line, "LOCALHOST", self.logger)

                    # Check the line for the token and pull out the PID
                    regex = f"__OTF_TOKEN__(\\d+)_{self.random}__"
                    pid_search = re.search(regex, line)
                    if pid_search:
                        self.remote_pid = int(pid_search.group(1))
                        self.logger.info(
                            f"[LOCALHOST] Found remote PID: {self.remote_pid}"
                        )

                # Get the return code
                remote_rc = process.wait()
                if remote_rc != 0:
                    self.logger.error(
                        f"[LOCALHOST] Got return code {remote_rc} from command"
                    )
                    return False

            return True
        except Exception as e:  # pylint: disable=broad-exception-caught
            self.logger.error(f"[LOCALHOST] Exception caught: {e}")
            return False

    def tidy(self) -> None:
        """Tidy up the remote connection."""
