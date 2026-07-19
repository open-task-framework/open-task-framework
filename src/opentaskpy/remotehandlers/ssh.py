"""SSH Remote Handlers.

This module contains the SSH remote handlers for transfers and executions.
"""

import glob
import logging
import os
import random
import re
import stat
import time
from collections.abc import Collection
from io import StringIO
from shlex import quote

from paramiko import RSAKey, SFTPClient, SSHClient, Transport
from paramiko.channel import ChannelFile, ChannelStderrFile
from tenacity import (
    retry,
    retry_if_exception,
    retry_if_not_exception_message,
    stop_after_attempt,
    wait_exponential,
)

import opentaskpy.otflogging
from opentaskpy.exceptions import SSHClientError
from opentaskpy.remotehandlers.remotehandler import (
    RemoteExecutionHandler,
    RemoteTransferHandler,
)

from .ssh_utils import setup_host_key_validation

SSH_OPTIONS: str = "-o StrictHostKeyChecking=no -o BatchMode=yes -o ConnectTimeout=5"
REMOTE_SCRIPT_BASE_DIR: str = "/tmp"  # nosec B108


class SSHTransfer(RemoteTransferHandler):
    """SSH Transfer Handler."""

    TASK_TYPE = "T"

    FILE_NAME_DELIMITER = "|||"

    ssh_client: SSHClient | None = None
    sftp_connection: SFTPClient | None = None
    log_watch_start_row = 0

    def __init__(self, spec: dict):
        """Initialise the SSHTransfer handler.

        Args:
            spec (dict): The spec for the transfer. This is either the source, or the
            destination spec.
        """
        self.logger = opentaskpy.otflogging.init_logging(
            __name__, spec["task_id"], self.TASK_TYPE
        )

        client = SSHClient()
        client.set_log_channel(f"{__name__}.{ spec['task_id']}.paramiko.transport")
        setup_host_key_validation(client, spec, self.logger)
        self.ssh_client = client

        # Handle default values
        if "createDirectoryIfNotExists" not in spec:
            spec["createDirectoryIfNotExists"] = False

        super().__init__(spec)

    def supports_direct_transfer(self) -> bool:
        """Return True, as SSH allows direct transfers by using the scp command."""
        return True

    def connect(self, hostname: str, ssh_client: SSHClient | None = None) -> None:
        """Connect to the remote host.

        Args:
            hostname (str): The hostname to connect to.
            ssh_client (SSHClient, optional): An existing SSHClient to use. Defaults to None.
        """
        is_remote_host = False
        if ssh_client is not None:
            is_remote_host = True
        else:
            ssh_client = self.ssh_client

        if ssh_client is None:
            self.logger.error(f"[{self.spec['hostname']}] SSH client not initialised")
            raise SSHClientError("SSH Client not initialised")

        if ssh_client.get_transport() and ssh_client.get_transport().is_active():  # type: ignore[union-attr]
            self.logger.debug(
                f"[{self.spec['hostname']}] SSH connection to {hostname} already active"
            )
            return

        kwargs = {
            "hostname": hostname,
            "port": (self.spec["protocol"].get("port", 22)),
            "username": self.spec["protocol"]["credentials"]["username"],
            "timeout": 3,
            "allow_agent": False,
        }
        # If a custom key is set via env vars, then set that
        if (
            os.environ.get("OTF_SSH_KEY")
            and os.path.exists(str(os.environ.get("OTF_SSH_KEY")))
        ) and "keyFile" not in self.spec["protocol"]["credentials"]:
            self.logger.info("Loading custom private SSH key from OTF_SSH_KEY env var")
            key = RSAKey.from_private_key_file(str(os.environ.get("OTF_SSH_KEY")))
            kwargs["pkey"] = key

        # If a specific key file has been defined, then use that
        elif "keyFile" in self.spec["protocol"]["credentials"]:
            self.logger.info("Using key file from task spec")
            kwargs["key_filename"] = self.spec["protocol"]["credentials"]["keyFile"]

        # If a private key has been defined as a string, then use that instead
        elif "key" in self.spec["protocol"]["credentials"]:
            self.logger.info("Using private key from task spec")
            key = RSAKey.from_private_key(
                StringIO(self.spec["protocol"]["credentials"]["key"])
            )
            kwargs["pkey"] = key

        self.connect_with_retry(ssh_client, kwargs)

        _, stdout, _ = ssh_client.exec_command("uname -a")  # nosec B601
        with stdout as stdout_fh:
            self.logger.log(
                11,
                f"[{self.spec['hostname']}] Remote uname:"
                f" {stdout_fh.read().decode('UTF-8')}",
            )

        sftp = ssh_client.open_sftp()

        if not is_remote_host:
            self.sftp_connection = sftp

    @retry(
        reraise=True,
        stop=stop_after_attempt(6),
        wait=wait_exponential(multiplier=2, min=5, max=60),
        retry=(
            retry_if_not_exception_message(
                match=r".*(not found in known_hosts|Name or service not known).*"
            )
            & retry_if_exception(lambda ex: isinstance(ex, Exception))
        ),
    )
    def connect_with_retry(self, ssh_client: SSHClient, kwargs: dict) -> None:
        """Connect to the remote host with retry.

        Args:
            ssh_client (SSHClient): The SSH client to use.
            kwargs (dict): The keyword arguments to use to connect to the remote host.
        """
        try:
            self.logger.info(f"Connecting to {kwargs['hostname']}")
            ssh_client.connect(**kwargs)

        except Exception as ex:
            self.logger.error(
                f"[{self.spec['hostname']}] Unable to connect to {kwargs['hostname']}: {ex}"
            )
            raise ex

    def tidy(self) -> None:
        """Tidy up the SSH connection.

        Shut down the SSH connection and remove the remote transfer script from the
        remote host.
        """
        # Remove remote scripts
        if self.sftp_connection:

            self.logger.info(f"[{self.spec['hostname']}] Closing SFTP connection")
            self.sftp_connection.get_channel().close()  # type: ignore[union-attr]

            # Wait until the channel is closed
            time.sleep(0.25)
            for _ in range(2):
                if not self.sftp_connection.get_channel().closed:  # type: ignore[union-attr]
                    time.sleep(0.5)
                else:
                    break

            self.sftp_connection.close()

        if self.ssh_client:
            self.logger.info(f"[{self.spec['hostname']}] Closing SSH connection")
            self.ssh_client.close()

    def get_staging_directory(self, remote_spec: dict) -> str:
        """Get the staging directory for the remote host.

        Args:
            remote_spec (dict): The remote spec.

        Returns:
            str: The staging directory on the remote host.
        """
        # Get the user's home directory
        if "stagingDirectory" in remote_spec:
            return str(remote_spec["stagingDirectory"])

        # Check SSH connection is established
        if not self.ssh_client.get_transport().is_active():  # type: ignore[union-attr]
            raise SSHClientError("SSH connection not active")

        _, stdout, _ = self.ssh_client.exec_command("echo $HOME")  # type: ignore[union-attr]  # nosec B601
        with stdout as stdout_fh:
            home_dir = stdout_fh.read().decode("UTF-8").strip()

        return f"{home_dir}/otf/{ self.spec['task_id']}/"

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
        self.connect(self.spec["hostname"])
        if not directory:
            directory = str(self.spec["directory"])
        if not file_pattern:
            file_pattern = str(self.spec["fileRegex"])

        self.logger.info(
            f"Searching for files in {directory} with pattern {file_pattern}"
        )

        self.logger.log(
            12,
            f"[{self.spec['hostname']}] Searching in {directory} for files with"
            f" pattern {file_pattern}",
        )
        remote_files: dict = {}
        # Check the remote directory exists
        try:
            self.sftp_connection.stat(directory)  # type: ignore[union-attr]
        except FileNotFoundError:
            self.logger.error(
                f"[{self.spec['hostname']}] Directory {directory} does not exist"
            )
            return remote_files

        remote_file_list = self.sftp_connection.listdir(directory)  # type: ignore[union-attr]
        for file in list(remote_file_list):
            if re.match(file_pattern, file):
                # Get the file attributes
                file_attr = self.sftp_connection.lstat(f"{directory}/{file}")  # type: ignore[union-attr]
                self.logger.log(12, f"File attributes {file_attr}")
                remote_files[f"{directory}/{file}"] = {
                    "size": file_attr.st_size,
                    "modified_time": file_attr.st_mtime,
                }

        return remote_files

    def pull_files_to_worker(
        self, files: Collection[str], local_staging_directory: str
    ) -> int:
        """Pull files to the worker.

        This function is used when we need to download source files from the source
        server onto the worker. These are then later pushed to the destination server

        Args:
            files (list): A list of files to download.
            local_staging_directory (str): The local staging directory to download the
            files to.

        Returns:
            int: 0 if successful, 1 if not.
        """
        result = 0
        # Connect to the source
        self.connect(self.spec["hostname"])

        # Create the staging directory locally
        if not os.path.exists(local_staging_directory):
            os.makedirs(local_staging_directory)

        # Download the files via SFTP
        for file in files:
            self.logger.info(
                f"[LOCALHOST] Downloading file {file} to {local_staging_directory}"
            )
            file_name = os.path.basename(file)
            try:
                self.sftp_connection.get(file, f"{local_staging_directory}/{file_name}")  # type: ignore[union-attr]
            except Exception as ex:  # pylint: disable=broad-exception-caught
                self.logger.error(
                    f"[LOCALHOST] Unable to download file locally via SFTP: {ex}"
                )
                result = 1

        return result

    def push_files_from_worker(
        self, local_staging_directory: str, file_list: dict | None = None
    ) -> int:
        """Push files from the worker to the destination server.

        This function is used when the source files have been downloaded locally and
        need to be uploaded to the destination server. This would be expected to be
        called against the remote handler for the destination server.

        Args:
            local_staging_directory (str): The local staging directory to upload the
            files from.
            file_list (dict, optional): A list of files to upload. Defaults to None.

        Returns:
            int: 0 if successful, 1 if not.
        """
        # Connect to the destination server
        self.connect(self.spec["hostname"])
        # Check that the SFTP client is connected and active
        if not isinstance(self.sftp_connection, SFTPClient):
            self.logger.error(f"[{self.spec['hostname']}] Cannot connect via SFTP")
            return 1

        # Handle the staging directory
        destination_directory = self.get_staging_directory(self.spec)

        # Sanitize the destination directory
        destination_directory = quote(destination_directory)

        # Use SFTP connection to check if the directory exists
        try:
            self.sftp_connection.stat(destination_directory)
        except FileNotFoundError:
            # Create the directory
            self.logger.info(
                f"[{self.spec['hostname']}] Creating destination directory"
                f" {destination_directory}"
            )
            mkdir_p(self.sftp_connection, destination_directory)

        # Transfer the files, just use SFTP
        result = 0

        if file_list:
            files = list(file_list.keys())
        else:
            # Get list of files in local_staging_directory
            files = glob.glob(f"{local_staging_directory}/*")
        for file in files:
            self.logger.info(f"[LOCALHOST] Transferring file via SFTP: {file}")
            file_name = os.path.basename(file)
            try:
                self.sftp_connection.put(file, f"{destination_directory}{file_name}")
            except Exception as ex:  # pylint: disable=broad-exception-caught
                self.logger.error(f"[LOCALHOST] Unable to transfer file via SFTP: {ex}")
                result = 1

        return result

    def transfer_files(
        self,
        files: Collection[str],
        remote_spec: dict,
        dest_remote_handler: RemoteTransferHandler | None = None,
    ) -> int:
        """Transfer files from the source server to the destination server.

        Args:
            files (dict): A dictionary of files to transfer.
            remote_spec (dict): The remote specification for the destination server.
            dest_remote_handler (RemoteTransferHandler, optional): The remote handler
            for the destination server. Defaults to None.

        Returns:
            int: 0 if successful, if not, the return code from the remotely executed SCP
            command.
        """
        remote_host = remote_spec["hostname"]
        self.connect(remote_host)

        # If we are given a destination handler, make sure we connect to the host
        if dest_remote_handler:
            self.connect(remote_host, dest_remote_handler.ssh_client)  # type: ignore[attr-defined]

        # Construct an SCP command to transfer the files to the destination server
        remote_user = (
            remote_spec["protocol"]["credentials"]["transferUsername"]
            if "transferUsername" in remote_spec["protocol"]["credentials"]
            else remote_spec["protocol"]["credentials"]["username"]
        )

        # Handle staging directory if there is one
        destination_directory = self.get_staging_directory(remote_spec)

        # Check that the SFTP client is connected and active
        if dest_remote_handler:
            dest_sftp_client = dest_remote_handler.ssh_client.open_sftp()  # type: ignore[attr-defined]

        # Create/validate staging directory exists on destination
        # Use SFTP connection to check if the directory exists
        if dest_remote_handler:
            try:
                dest_sftp_client.stat(destination_directory)
            except FileNotFoundError:
                # Create the directory
                self.logger.info(
                    f"[{dest_remote_handler.spec['hostname']}] Creating destination"
                    f" directory {destination_directory}"
                )
                mkdir_p(dest_sftp_client, destination_directory)

        # Sanitise arguments
        files = [quote(file) for file in files]
        destination_directory = quote(destination_directory)
        remote_user = quote(remote_user)
        remote_host = quote(remote_host)

        remote_command = f'scp {SSH_OPTIONS} {" ".join(files)} {remote_user}@{remote_host}:"{destination_directory}"'

        self.logger.info(
            f"[{self.spec['hostname']}] Transferring files via SCP: {remote_command}"
        )

        _, stdout, stderr = self.ssh_client.exec_command(remote_command)  # type: ignore[union-attr] # nosec B601

        self._log_remote_output(stdout, stderr)

        remote_rc = stdout.channel.recv_exit_status()
        self.logger.info(
            f"[{self.spec['hostname']}] Got return code {remote_rc} from SCP command"
        )

        return remote_rc

    def pull_files(
        self, files: Collection[str], remote_spec: dict | None = None
    ) -> int:
        """Pull files from the source server to the destination server.

        Args:
            files (list[str]): A list of files to pull.
            remote_spec (dict): The remote specification for the source server.

        Returns:
            int: 0 if successful, if not, the return code from the remotely executed SCP
        """
        self.connect(self.spec["hostname"])
        # Construct an SCP command to transfer the files from the source server
        source_user = self.spec["protocol"]["credentials"]["transferUsername"]
        source_host = remote_spec["hostname"] if remote_spec else self.spec["hostname"]

        # Handle staging directory if there is one
        destination_directory = self.get_staging_directory(self.spec)

        # Get an SFTP client to use to create the staging directory
        sftp_client = self.ssh_client.open_sftp()  # type: ignore[union-attr]

        # Create/validate staging directory exists on destination
        # Use SFTP connection to check if the directory exists
        try:
            sftp_client.stat(destination_directory)
        except FileNotFoundError:
            # Create the directory
            self.logger.info(
                f"[{self.spec['hostname']}] Creating destination directory"
                f" {destination_directory}"
            )
            mkdir_p(sftp_client, destination_directory)

        files_str = ""
        for file in files:
            # Sanitise file
            file = quote(file)
            source_host = quote(source_host)
            source_user = quote(source_user)

            files_str += f"{source_user}@{source_host}:{file} "

        destination_directory = quote(destination_directory)

        remote_command = (
            f"scp {SSH_OPTIONS} {files_str.strip()} {destination_directory}"
        )
        self.logger.info(
            f"[{self.spec['hostname']}] Transferring files via SCP: {remote_command}"
        )

        _, stdout, stderr = self.ssh_client.exec_command(remote_command)  # type: ignore[union-attr] # nosec B601

        self._log_remote_output(stdout, stderr)
        remote_rc = stdout.channel.recv_exit_status()
        self.logger.info(
            f"[{self.spec['hostname']}] Got return code {remote_rc} from SCP command"
        )

        return remote_rc

    def move_files_to_final_location(self, files: Collection[str]) -> int:
        """Move files from the staging directory to their final location.

        Args:
            files (dict): A dictionary of files to move.

        Returns:
            int: 0 if successful, 1 if not.
        """
        self.connect(self.spec["hostname"])

        # Convert all the source file names into the filename with the destination directory as a prefix
        files_with_directory = []
        for file in list(files):
            files_with_directory.append(
                f"{self.get_staging_directory(self.spec)}{os.path.basename(file)}"
            )
        self.FILE_NAME_DELIMITER.join(files_with_directory).strip()

        directory = self.spec["directory"]

        # Get an SFTP connection if it doesn't exist
        if not isinstance(self.sftp_connection, SFTPClient):
            self.sftp_connection = self.ssh_client.open_sftp()  # type: ignore[union-attr]

        # Check if the destination directory exists on the remote host
        try:
            self.sftp_connection.stat(directory)
        except FileNotFoundError:
            if self.spec["createDirectoryIfNotExists"]:
                # Create the directory
                self.logger.info(
                    f"[{self.spec['hostname']}] Creating destination directory"
                    f" {directory}"
                )
                mkdir_p(self.sftp_connection, directory)
            else:
                self.logger.error(
                    f"[{self.spec['hostname']}] Destination directory {directory}"
                    " does not exist"
                )
                return 1

        # Move the files to the right place and apply any renames and permissions that
        # are needed
        for file in list(files):
            current_path = (
                f"{self.get_staging_directory(self.spec)}{os.path.basename(file)}"
            )
            self.logger.info(f"{self.spec['hostname']} Processing {current_path}")

            file_name = os.path.basename(file)

            # Handle any rename that might be specified in the spec
            if "rename" in self.spec:
                rename_regex = self.spec["rename"]["pattern"]
                rename_sub = self.spec["rename"]["sub"]

                file_name = re.sub(rename_regex, rename_sub, file_name)
                self.logger.info(
                    f"{self.spec['hostname']} Renaming file to {file_name}"
                )

            try:

                # This cannot use the standard rename, because it will fail if the file
                # is moving across filesystems. This is expected behaviour in the SFTP
                # protocol
                # Instead, we have to issue it as a command over the SSH connection
                remote_command = f"mv {current_path} {directory}/{file_name}"
                _, stdout, stderr = self.ssh_client.exec_command(remote_command)  # type: ignore[union-attr] # nosec B601
                self._log_remote_output(stdout, stderr)
                # Check the return code of the command
                remote_rc = stdout.channel.recv_exit_status()
                if remote_rc != 0:
                    self.logger.error(
                        f"[{self.spec['hostname']}] Got return code {remote_rc} from"
                        " SSH mv command"
                    )
                    return 1

                if "mode" in self.spec:
                    self.sftp_connection.chmod(
                        f"{directory}/{file_name}", int(self.spec["mode"], base=8)
                    )

                if "permissions" in self.spec:
                    # Unfortunately, this is easier to do with a proper SSH command
                    # than with the SFTP client
                    if "owner" in self.spec["permissions"]:
                        remote_command = (
                            "chown"
                            f" {self.spec['permissions']['owner']} {directory}/{file_name}"
                        )
                        _, stdout, stderr = self.ssh_client.exec_command(remote_command)  # type: ignore[union-attr] # nosec B601

                    if "group" in self.spec["permissions"]:
                        remote_command = (
                            "chgrp"
                            f" {self.spec['permissions']['group']} {directory}/{file_name}"
                        )
                        _, stdout, stderr = self.ssh_client.exec_command(remote_command)  # type: ignore[union-attr] # nosec B601

            except Exception as ex:  # pylint: disable=broad-exception-caught
                self.logger.error(
                    f"{self.spec['hostname']} Failed moving file to final location:"
                    f" {ex}"
                )
                return 1

        return 0

    def _log_remote_output(
        self, stdout: ChannelFile, stderr: ChannelStderrFile
    ) -> None:
        self.logger.info("### START OF REMOTE OUTPUT ###")
        with stdout as stdout_fh:
            str_stdout = stdout_fh.read().decode("UTF-8")
            if str_stdout:
                log_stdout(str_stdout, self.spec["hostname"], self.logger)

        with stderr as stderr_fh:
            str_stderr = stderr_fh.read().decode("UTF-8")
            if str_stderr and len(str_stderr) > 0:
                self.logger.info(
                    f"[{self.spec['hostname']}] Remote stderr returned:\n{str_stderr}"
                )

        self.logger.info("### END OF REMOTE OUTPUT ###")

    def handle_post_copy_action(self, files: Collection[str]) -> int:
        """Handle the post copy action specified in the config.

        Args:
            files (list[str]): A list of files that need to be handled.

        Returns:
            int: 0 if successful, 1 if not.
        """
        self.connect(self.spec["hostname"])
        sftp_client = self.ssh_client.open_sftp()  # type: ignore[union-attr]

        if self.spec["postCopyAction"]["action"] == "delete":
            # Loop through each file and use the sftp client to delete the files

            for file in files:
                try:
                    self.logger.info(f"Deleting file {file}")
                    sftp_client.remove(file)
                except OSError:
                    self.logger.error(
                        f"[{self.spec['hostname']}] Could not delete file {file} on"
                        " source host"
                    )
                    return 1

        if (
            self.spec["postCopyAction"]["action"] == "move"
            or self.spec["postCopyAction"]["action"] == "rename"
        ):
            # Use the SFTP client, and check that the destination directory exists
            move_dir = os.path.dirname(self.spec["postCopyAction"]["destination"])

            try:
                stat_result = sftp_client.stat(move_dir)
                # If it exists, then we need to ensure its a directory and not just a file
                if not stat.S_ISDIR(stat_result.st_mode):  # type: ignore[arg-type]
                    self.logger.error(
                        f"[{self.spec['hostname']}] Destination directory {move_dir} is"
                        " not a directory on source host"
                    )
                    return 1
            except OSError:
                self.logger.error(
                    f"[{self.spec['hostname']}] Destination directory {move_dir} does"
                    " not exist on source host"
                )
                return 1

                # Loop through the files and move them

            for file in files:
                try:
                    # If this is a move, then just move the file
                    if self.spec["postCopyAction"]["action"] == "move":
                        self.logger.info(
                            f"[{self.spec['hostname']}] Moving {file} to"
                            f" {self.spec['postCopyAction']['destination']}"
                        )
                        # Get the actual file name
                        file_name = os.path.basename(file)
                        sftp_client.posix_rename(
                            file,
                            f"{self.spec['postCopyAction']['destination']}/{file_name}",
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
                            f"[{self.spec['hostname']}] Renaming {file} to"
                            f" {new_file_dir}/{new_file_name}"
                        )
                        sftp_client.posix_rename(
                            file, f"{new_file_dir}/{new_file_name}"
                        )
                except OSError as e:
                    self.logger.error(f"[{self.spec['hostname']}] Error: {e}")
                    self.logger.error(
                        f"[{self.spec['hostname']}] Error moving or renaming file"
                        f" {file}"
                    )
                    return 1

        return 0

    def init_logwatch(self) -> int:
        """Initialise the logwatch process.

        Returns:
            int: 0 if successful, 1 if not.
        """
        self.connect(self.spec["hostname"])
        if not isinstance(self.sftp_connection, SFTPClient):
            self.logger.error(f"[{self.spec['hostname']}] Cannot connect via SFTP")
            return 1

        # There are 2 options for logwatches. One is to watch for new entries, the other is to scan the entire log.
        # Default if not specified is to watch for new entries

        # Determine the log details and check it exists first
        log_file = (
            f"{self.spec['logWatch']['directory']}/{self.spec['logWatch']['log']}"
        )

        # Stat the file
        try:
            _ = self.sftp_connection.lstat(f"{log_file}")
        except FileNotFoundError:
            self.logger.error(
                f"[{self.spec['hostname']}] Log file {log_file} does not exist"
            )
            return 1
        except PermissionError:
            self.logger.error(
                f"[{self.spec['hostname']}] Log file {log_file} cannot be accessed"
            )
            return 1

        # Open the existing file and determine the number of rows
        with self.sftp_connection.open(log_file) as log_fh:
            rows = 0
            for _, _ in enumerate(log_fh):
                pass
            self.logger.log(
                12, f"[{self.spec['hostname']}] Found {rows+1} lines in log"
            )
            self.log_watch_start_row = rows + 1

        return 0

    def do_logwatch(self) -> int:
        """Perform the logwatch process.

        Returns:
            int: 0 if successful, 1 if not.
        """
        self.connect(self.spec["hostname"])
        if not isinstance(self.sftp_connection, SFTPClient):
            self.logger.error(f"[{self.spec['hostname']}] Cannot connect via SFTP")
            return 1

        # Determine if the config requires scanning the entire log, or just from the start_row determine in the init function
        start_row = (
            self.log_watch_start_row
            if "tail" in self.spec["logWatch"] and self.spec["logWatch"]["tail"]
            else 0
        )
        self.logger.log(
            12, f"[{self.spec['hostname']}] Starting logwatch from row {start_row}"
        )

        # Open the remote log file and parse each line for the pattern
        log_file = (
            f"{self.spec['logWatch']['directory']}/{self.spec['logWatch']['log']}"
        )

        with self.sftp_connection.open(log_file) as log_fh:
            for i, line in enumerate(log_fh):
                # We need to start after the previous line in the log
                if i >= start_row:
                    self.logger.log(
                        11, f"[{self.spec['hostname']}] Log line: {line.strip()}"
                    )
                    if re.search(self.spec["logWatch"]["contentRegex"], line.strip()):
                        self.logger.log(
                            12,
                            f"[{self.spec['hostname']}] Found matching line in log:"
                            f" {line.strip()} on line: {i+1}",
                        )
                        return 0

        return 1

    def create_flag_files(self) -> int:
        """Create the flag files on the remote host.

        Returns:
            int: 0 if successful, 1 if not.
        """
        self.connect(self.spec["hostname"])

        if not isinstance(self.ssh_client, SSHClient):
            self.logger.error(f"[{self.spec['hostname']}] Cannot connect via SSH")
            return 1

        # Manually open SFTP client
        sftp_client = self.ssh_client.open_sftp()
        filename = self.spec["flags"]["fullPath"]

        try:
            # Use the SFTP client to create an empty file at this path
            sftp_client.file(filename, "w").close()

            # Set permissions on the file to whatever was specified in the spec,
            # otherwise we leave them as is
            # We cannot change ownership without using sudo, so we don't bother
            if "permissions" in self.spec:
                sftp_client.chmod(filename, int(self.spec["permissions"], base=8))

        except OSError as e:
            self.logger.error(f"[{self.spec['hostname']}] Error: {e}")
            self.logger.error(
                f"[{self.spec['hostname']}] Error creating flag file: {filename}"
            )
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


def mkdir_p(sftp: SFTPClient, remote_directory: str) -> bool:
    """Change to this directory, recursively making new folders if needed.

    Thanks to: https://stackoverflow.com/a/14819803

    Args:
        sftp (SFTPClient): The SFTP client to use
        remote_directory (str): The remote directory to create

    Returns:
        bool: True if successful, False if not.
    """
    if remote_directory == "/":
        # absolute path so change directory to root
        sftp.chdir("/")
        return False
    if remote_directory == "":
        # top-level relative directory must exist
        return False
    try:
        sftp.chdir(remote_directory)  # sub-directory exists
    except FileNotFoundError:
        dirname, basename = os.path.split(remote_directory.rstrip("/"))
        mkdir_p(sftp, dirname)  # make parent directories
        sftp.mkdir(basename)  # sub-directory missing, so created it
        sftp.chdir(basename)
        return True

    return False


class SSHExecution(RemoteExecutionHandler):
    """Class to handle SSH execution of remote commands."""

    TASK_TYPE = "E"
    ps_regex = r"(\S+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(.*)"
    ssh_client: SSHClient
    remote_pid: int

    def tidy(self) -> None:
        """Tidy up the SSH connection."""
        if self.ssh_client:
            self.logger.info(f"[{self.remote_host}] Closing SFTP connection")
            self.ssh_client.close()

    def __init__(self, remote_host: str, spec: dict):
        """Initialise the SSHExecution class.

        Args:
            remote_host (str): The hostname of the remote host
            spec (dict): The specification for the remote command
        """
        self.remote_host: str = remote_host
        self.random: int = random.randint(
            100000, 999999
        )  # Random number used to make sure when we kill stuff, we always kill the right thing

        self.logger = opentaskpy.otflogging.init_logging(
            __name__, spec["task_id"], self.TASK_TYPE
        )

        super().__init__(spec)

        client = SSHClient()
        client.set_log_channel(f"{__name__}.{ spec['task_id']}.paramiko.transport")

        setup_host_key_validation(client, spec, self.logger)

        self.ssh_client = client

    def connect(self) -> None:
        """Connect to the remote host."""
        if self.ssh_client and isinstance(self.ssh_client, SSHClient):
            transport = self.ssh_client.get_transport()
            if (
                transport is not None
                and isinstance(transport, Transport)
                and transport.is_active()
            ):
                return

        kwargs = {
            "hostname": self.remote_host,
            "port": (self.spec["protocol"].get("port", 22)),
            "username": self.spec["protocol"]["credentials"]["username"],
            "timeout": 5,
        }

        # If a custom key is set via env vars, then set that
        if (
            os.environ.get("OTF_SSH_KEY")
            and os.path.exists(str(os.environ.get("OTF_SSH_KEY")))
        ) and "keyFile" not in self.spec["protocol"]["credentials"]:
            self.logger.info("Loading custom private SSH key from OTF_SSH_KEY env var")
            key = RSAKey.from_private_key_file(str(os.environ.get("OTF_SSH_KEY")))
            kwargs["pkey"] = key

        # If a specific key file has been defined, then use that
        elif "keyFile" in self.spec["protocol"]["credentials"]:
            self.logger.info("Using key file from task spec")
            kwargs["key_filename"] = self.spec["protocol"]["credentials"]["keyFile"]

        try:
            self.ssh_client.connect(**kwargs)
            _, stdout, _ = self.ssh_client.exec_command("uname -a")  # nosec B601
            with stdout as stdout_fh:
                output = stdout_fh.read().decode("UTF-8")
                self.logger.log(11, f"[{self.remote_host}] Remote uname: {output}")
        except Exception as ex:
            self.logger.error(f"Unable to connect to {self.remote_host}: {ex}")
            raise ex

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
            match = re.search(self.ps_regex, line)
            if match:
                if int(match.group(3)) == parent_pid:
                    child_pid = int(match.group(2))
                    # Never add PID 1 or 0!
                    if child_pid in (1, 0):
                        continue
                    self.logger.debug(
                        f"[{self.remote_host}] Found child process with PID:"
                        f" {child_pid}"
                    )
                    children.append(child_pid)
                    # Recurse to find the children of this child
                    children.extend(
                        self._get_child_processes(child_pid, process_listing)
                    )
        return children

    def kill(self) -> None:
        """Kill the remote process."""
        self.logger.info(f"[{self.remote_host}] Killing remote process")

        self.connect()
        # We know the top level remote PID, we need to get all the child processes associated with it
        _, stdout, _ = self.ssh_client.exec_command("ps -ef")  # nosec B601
        process_listing = []
        # Get the process listing
        with stdout as stdout_fh:
            process_listing = stdout_fh.read().decode("UTF-8").splitlines()

        # Now we have this, parse it, find the parent PID, and then all the children
        children = self._get_child_processes(self.remote_pid, process_listing)
        children.append(self.remote_pid)
        self.logger.info(
            f"[{self.remote_host}] Found {len(children)} child processes to kill -"
            f" {children}"
        )

        # Now we have the list of children, kill them
        command = f"kill {' '.join([str(x) for x in children])}"
        self.logger.info(
            f"[{self.remote_host}] Killing remote processes with command: {command}"
        )

        # Make sure we're not killing PID 1 or 0
        if command in ("kill 1", "kill 0"):
            self.logger.error(
                f"[{self.remote_host}] Refusing to kill PID 1 or 0, aborting"
            )
            return
        _, stdout, _ = self.ssh_client.exec_command(command)  # nosec B601
        # Wait for the command to finish
        while not stdout.channel.exit_status_ready():
            time.sleep(0.1)

        # Disconnect SSH
        self.tidy()

    def execute(self) -> bool:
        """Execute the remote command.

        Returns:
            bool: True if the command was executed successfully, False otherwise
        """
        try:
            self.connect()

            directory = quote(self.spec["directory"])

            command = (
                f"echo __OTF_TOKEN__$$_{self.random}__; cd {directory} &&"
                f" {self.spec['command']}"
            )

            self.logger.info(f"[{self.remote_host}] Executing command: {command}")

            _, stdout, stderr = self.ssh_client.exec_command(command)  # nosec B601

            # Log the stdout and stderr
            for line in iter(lambda: str(stdout.readline(2048)), ""):
                log_stdout(line, self.remote_host, self.logger)

                # Check the line for the token and pull out the PID
                regex = f"__OTF_TOKEN__(\\d+)_{self.random}__"
                pid_search = re.search(regex, line)
                if pid_search:
                    self.remote_pid = int(pid_search.group(1))
                    self.logger.info(
                        f"[{self.remote_host}] Found remote PID: {self.remote_pid}"
                    )

            with stderr as stderr_fh:
                str_stderr = stderr_fh.read().decode("UTF-8")
                if str_stderr and len(str_stderr) > 0:
                    self.logger.info(
                        f"[{self.remote_host}] Remote stderr returned:\n{str_stderr}"
                    )

            # Get the return code
            remote_rc = stdout.channel.recv_exit_status()
            self.tidy()
            if remote_rc != 0:
                self.logger.error(
                    f"[{self.remote_host}] Got return code {remote_rc} from SSH command"
                )
                return False

            return True
        except Exception as e:  # pylint: disable=broad-exception-caught
            self.logger.error(f"[{self.remote_host}] Exception caught: {e}")
            return False
