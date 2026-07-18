"""Task handler for running transfers."""

import random
import shutil
import threading
import time
from math import ceil, floor
from os import environ, getpid, makedirs, path, remove

import gnupg

import opentaskpy.otflogging
from opentaskpy import exceptions
from opentaskpy.remotehandlers.remotehandler import RemoteTransferHandler
from opentaskpy.taskhandlers.taskhandler import TaskHandler

# Full transfers expect that the remote host has a base install of python3
# We transfer over the wrapper script to the remote host and trigger it, which is responsible
# for doing some of the more complex work, rather than triggering a tonne of shell commands


TASK_TYPE = "T"

DEFAULT_STAGING_DIR_BASE = "/tmp"  # nosec B108


class Transfer(TaskHandler):  # pylint: disable=too-many-instance-attributes
    """Task handler for running transfers."""

    source_remote_handler: RemoteTransferHandler
    dest_remote_handlers: RemoteTransferHandler = None
    source_file_spec: dict
    dest_file_specs: list[dict] | None = None
    overall_result: bool = False

    def __init__(self, global_config: dict, task_id: str, transfer_definition: dict):
        """Create a new transfer task handler.

        Args:
            global_config (dict): Global configuration dictionary
            task_id (str): Task ID
            transfer_definition (dict): Transfer definition
        """
        self.task_id = task_id
        self.transfer_definition = transfer_definition

        # Set up the local staging directory
        # Allow for a custom staging directory to be set via environment variable
        self.local_staging_dir = self._get_staging_directory()

        self.logger = opentaskpy.otflogging.init_logging(
            "opentaskpy.taskhandlers.transfer", self.task_id, TASK_TYPE
        )

        super().__init__(global_config)

    def _get_staging_directory(self) -> str:
        """GEt a unique staging directory path.

        Uses the OTF_STAGING_DIR environment variable if set, otherwise uses the default base.

        Returns:
            str: The full path to the staging directory
        """
        staging_dir_name = f"OTF_STAGING_{getpid()}.{random.randint(0, 1000000)}"
        if "OTF_STAGING_DIR" in environ:
            return f"{environ['OTF_STAGING_DIR']}/{staging_dir_name}"

        return f"{DEFAULT_STAGING_DIR_BASE}/{staging_dir_name}"

    def return_result(
        self,
        status: int,
        message: str | None = None,
        exception: Exception | None = None,
    ) -> bool:
        """Return the result of the task run.

        Args:
            status (int): The status code to return.
            message (str, optional): The message to return. Defaults to None.
            exception (Exception, optional): The exception to return. Defaults to None.

        Returns:
            bool: The result of the task run.
        """
        # Log the exception
        if exception:
            self.logger.exception(exception)

        # Delete the remote connection objects
        if self.source_remote_handler:
            self.logger.info("Closing source connection")
            self.source_remote_handler.tidy()
        if self.dest_remote_handlers:
            for remote_handler in self.dest_remote_handlers:
                self.logger.info(f"Closing dest connection for {remote_handler}")
                remote_handler.tidy()

        # Remove local staging directory if it exists (and this isn't a local transfer)
        if (
            path.exists(self.local_staging_dir)
            and self.source_file_spec["protocol"]["name"] != "dummy"
            and self.local_staging_dir != self.source_file_spec["directory"]
        ):
            self.logger.info(
                f"Removing local staging directory {self.local_staging_dir}"
            )
            shutil.rmtree(self.local_staging_dir)
        else:
            if path.exists(self.local_staging_dir):
                self.logger.info(
                    "Local staging directory is the same as source directory. Not removing",
                )

        # Call super to do the rest
        return super().return_result(status, message, exception)  # type: ignore[no-any-return]

    def _set_remote_handlers(self) -> None:
        # Based on the transfer definition, determine what to do first
        self.source_file_spec = self.transfer_definition["source"]
        self.source_file_spec["task_id"] = self.task_id
        source_protocol = self.source_file_spec["protocol"]["name"]

        # Create a list of destination file specs
        if (
            "destination" in self.transfer_definition
            and self.transfer_definition["destination"]
            and isinstance(self.transfer_definition["destination"], list)
        ):
            self.dest_file_specs = self.transfer_definition["destination"]

        # Set the task_id for each file spec
        if self.dest_file_specs:
            for dest_file_spec in self.dest_file_specs:
                dest_file_spec["task_id"] = self.task_id

        # Based on the source protocol pick the appropriate remote handler
        if source_protocol in super().DEFAULT_PROTOCOL_MAP[TASK_TYPE]:
            handler_class = super()._get_default_class(TASK_TYPE, source_protocol)
            self.source_remote_handler = handler_class(self.source_file_spec)

        # If not SSH, then it's a non-standard protocol, we need to see if it's loadable
        # load it, and then create the remote handler
        else:
            self.source_remote_handler = super()._get_handler_for_protocol(
                source_protocol, self.source_file_spec
            )

        super()._set_handler_vars(source_protocol, self.source_remote_handler)

        # Based on the destination protocol pick the appropriate remote handler
        if self.dest_file_specs:
            self.dest_remote_handlers = []
            for dest_file_spec in self.dest_file_specs:
                remote_protocol = dest_file_spec["protocol"]["name"]

                # For each host, create a remote handler
                remote_handler = None
                if remote_protocol in super().DEFAULT_PROTOCOL_MAP[TASK_TYPE]:
                    handler_class = super()._get_default_class(
                        TASK_TYPE, remote_protocol
                    )
                    remote_handler = handler_class(dest_file_spec)

                else:
                    remote_handler = super()._get_handler_for_protocol(
                        remote_protocol, dest_file_spec
                    )

                self.dest_remote_handlers.append(remote_handler)
                super()._set_handler_vars(remote_protocol, remote_handler)

    def run(self, kill_event: threading.Event | None = None) -> bool:  # noqa: C901
        """Run the transfer task.

        Args:
            kill_event (threading.Event, optional): Event to kill the task. Defaults to None.

        Returns:
            bool: The result of the task run.
        """
        self.logger.info("Running transfer")

        self._set_remote_handlers()

        # If log watching, do that first
        if "logWatch" in self.source_file_spec:
            self.logger.info(
                "Performing a log watch of"
                f" {self.source_file_spec['logWatch']['directory']}/{self.source_file_spec['logWatch']['log']}"
            )

            if self.source_remote_handler.init_logwatch() != 0:
                return self.return_result(
                    1, "Logwatch init failed", exception=exceptions.LogWatchInitError
                )

            timeout_seconds = self.source_file_spec["logWatch"].get("timeout", 60)
            sleep_seconds = self.source_file_spec["logWatch"].get("sleepTime", 10)

            # Now we start the loop to monitor the log file
            start_time = time.time()
            found_log_entry = False
            while floor(time.time() - start_time) <= timeout_seconds:
                if kill_event and kill_event.is_set():
                    return self.return_result(
                        1, "KILLED DUE TO TIMEOUT FROM PARENT BATCH"
                    )

                if self.source_remote_handler.do_logwatch() == 0:
                    found_log_entry = True
                    break

                remaining_seconds = ceil((start_time + timeout_seconds) - time.time())
                if remaining_seconds == 0:
                    break

                # If the sleep time is longer than the time remaining, sleep for that long instead
                if remaining_seconds < sleep_seconds:
                    actual_sleep_seconds = remaining_seconds
                else:
                    actual_sleep_seconds = sleep_seconds

                self.logger.info(
                    f"No entry found in log. Sleeping for {actual_sleep_seconds} secs."
                    f" {remaining_seconds} seconds remain"
                )
                time.sleep(actual_sleep_seconds)

            if found_log_entry:
                self.logger.info("Found pattern in log file")
            else:
                return self.return_result(
                    1,
                    f"No log entry found after {timeout_seconds} seconds",
                    exception=exceptions.LogWatchTimeoutError,
                )

        # If filewatching, do that next
        if "fileWatch" in self.source_file_spec:
            # Setup a loop for the filewatch
            timeout_seconds = self.source_file_spec["fileWatch"].get("timeout", 60)
            sleep_seconds = self.source_file_spec["fileWatch"].get("sleepTime", 10)

            start_time = time.time()
            remote_files: dict = {}

            # Determine if we're doing a plain filewatch, or looking for a different file to what we are transferring
            watch_directory = (
                self.source_file_spec["fileWatch"]["directory"]
                if "directory" in self.source_file_spec["fileWatch"]
                else self.source_file_spec["directory"]
            )
            watch_file_pattern = (
                self.source_file_spec["fileWatch"]["fileRegex"]
                if "fileRegex" in self.source_file_spec["fileWatch"]
                else self.source_file_spec["fileRegex"]
            )
            # Determine if we should check for file conditionals during filewatch, or only after watch is completed
            check_conditionals_during_filewatch = (
                "conditionals" in self.source_file_spec
                and "checkDuringFilewatch" in self.source_file_spec["conditionals"]
            )

            self.logger.info(
                f"Performing a file watch on {watch_directory}/{watch_file_pattern}"
            )

            while (
                not remote_files and floor(time.time() - start_time) <= timeout_seconds
            ):
                if kill_event and kill_event.is_set():
                    return self.return_result(
                        1, "KILLED DUE TO TIMEOUT FROM PARENT BATCH"
                    )

                self.logger.info(
                    f"Searching in {watch_directory} for files with"
                    f" pattern {watch_file_pattern}",
                )
                remote_files = self.source_remote_handler.list_files(
                    directory=watch_directory, file_pattern=watch_file_pattern
                )
                if check_conditionals_during_filewatch and remote_files:
                    self.check_conditionals(remote_files)

                if remote_files:
                    self.logger.info("Filewatch found remote file(s):")
                    self.logger.info(
                        f"Found {len(remote_files)} remote files: {remote_files}"
                    )
                    break

                remaining_seconds = ceil((start_time + timeout_seconds) - time.time())
                if remaining_seconds == 0:
                    break

                # If the sleep time is longer than the time remaining, sleep for that long instead
                if remaining_seconds < sleep_seconds:
                    actual_sleep_seconds = remaining_seconds
                else:
                    actual_sleep_seconds = sleep_seconds

                # Prevent negative sleep times
                actual_sleep_seconds = max(actual_sleep_seconds, 0)

                self.logger.info(
                    f"No valid files found. Sleeping for {sleep_seconds} secs."
                    f" {remaining_seconds} seconds remain"
                )
                time.sleep(actual_sleep_seconds)

            if (
                remote_files
                and "watchOnly" in self.source_file_spec["fileWatch"]
                and self.source_file_spec["fileWatch"]["watchOnly"]
            ):
                return self.return_result(0, "Just performing filewatch")
            if not remote_files:
                # Only error if error is not set to false
                if (
                    "error" in self.source_file_spec
                    and not self.source_file_spec["error"]
                ):
                    self.logger.info(
                        "Valid files not found after timeout, but error is set to false"
                    )
                    return self.return_result(0, "Valid files not found")

                return self.return_result(
                    1,
                    f"No valid files found after {timeout_seconds} seconds",
                    exception=exceptions.RemoteFileNotFoundError,
                )

        # Determine what needs to be transferred
        source_directory = self.source_file_spec.get("directory", None)
        source_file_pattern = self.source_file_spec.get("fileRegex", None)
        remote_files = self.source_remote_handler.list_files(
            directory=source_directory, file_pattern=source_file_pattern
        )
        decrypted_files = {}
        encrypted_files = {}

        # Loop through the returned files to see if they match any conditionals ( file age, size spec, counts) (if defined)
        if "conditionals" in self.source_file_spec and remote_files:
            remote_files = self.check_conditionals(remote_files)

        if not remote_files and self.source_file_spec["protocol"]["name"] != "dummy":
            if "error" in self.source_file_spec and not self.source_file_spec["error"]:
                return self.return_result(
                    0,
                    "Valid remote files could not be found to transfer. But not erroring"
                    " due to config",
                )

            return self.return_result(
                1,
                "Valid remote files could not be found to transfer",
                exception=exceptions.FilesDoNotMeetConditionsError,
            )

        self.logger.info("Found the following file(s) that match all requirements:")
        for file in remote_files:
            self.logger.info(f" * {file}")

        can_do_encryption = False
        original_file_list = remote_files.copy()
        # If there's a destination file spec, then we need to transfer the files
        if self.dest_file_specs:
            source_supports_direct_transfer = (
                self.source_remote_handler.supports_direct_transfer()
            )
            # Loop through all dest_file specs and see if there are any transfers where the source and dest protocols are different
            # If there are, then we need to do a pull transfer first, then a push transfer
            any_different_protocols = False
            destination_protocol_differences = []
            requires_local_staging = False
            for i, dest_file_spec in enumerate(self.dest_file_specs):
                different_protocols = False
                if (
                    (
                        "transferType" not in dest_file_spec
                        or dest_file_spec["transferType"] == "push"
                    )
                    # And the destination and source remote handler classes are not the same
                    and (
                        self.source_remote_handler.__class__
                        != self.dest_remote_handlers[i].__class__
                    )
                ):
                    different_protocols = True
                    any_different_protocols = True
                destination_protocol_differences.append(different_protocols)

                # If there are differences, download the file locally first
                # so it's ready to upload to multiple destinations at once
                if (
                    different_protocols
                    or (
                        "transferType" in dest_file_spec
                        and dest_file_spec["transferType"] == "proxy"
                    )
                    or not source_supports_direct_transfer
                ):
                    requires_local_staging = True

            if requires_local_staging:
                # Create local staging dir (if this isn't using the local protocol)
                if self.source_file_spec["protocol"]["name"] != "local":
                    makedirs(self.local_staging_dir, exist_ok=True)
                else:
                    self.local_staging_dir = self.source_file_spec["directory"]
                transfer_result = self.source_remote_handler.pull_files_to_worker(
                    remote_files, self.local_staging_dir
                )
                # Since files are being pulled locally, encryption/decryption of the files is possible
                can_do_encryption = True
                if transfer_result != 0:
                    return self.return_result(
                        1,
                        "Pull to worker from remote source errored",
                        exception=exceptions.RemoteTransferError,
                    )

            # Before doing any file movements, check to see if file decryption or encryption is
            # required on the source or destination. For any unsupported transferTypes we need to fail here first

            # Supported options are:
            # decrypting when:
            # transferType is proxy, or the protocols are different (in which case it's local anyway)
            # encrypting when:
            # transferType is proxy, or the protocols are different (in which case it's local anyway)

            # Check if decryption is requested
            decryption_requested = (
                "encryption" in self.source_file_spec
                and "decrypt" in self.source_file_spec["encryption"]
                and self.source_file_spec["encryption"]["decrypt"]
            )

            if decryption_requested and not can_do_encryption:
                return self.return_result(
                    1,
                    "Decryption requested but not supported for this transfer",
                    exception=exceptions.DecryptionNotSupportedError,
                )

            # If it's requested and decryption is possible, then we need to decrypt the files
            if decryption_requested and can_do_encryption:
                self.logger.info("Decrypting files")

                # Get the private key from the spec
                private_key = self.source_file_spec["encryption"]["private_key"]

                # For each file in the remote_files list, alter the path to start
                # with the local staging directory instead
                local_files = {}
                for file in remote_files:
                    # Strip the path and replace it with the stating directory
                    local_files[f"{self.local_staging_dir}/{path.basename(file)}"] = (
                        remote_files[file]
                    )

                # Loop through each file and decrypt it using gnupg
                remote_files = self.decrypt_files(local_files, private_key)

                decrypted_files = remote_files.copy()

                self.logger.info(f"Decrypted {len(remote_files)} files")

            i = 0
            for dest_file_spec in self.dest_file_specs:
                encryption_requested = (
                    "encryption" in dest_file_spec
                    and "encrypt" in dest_file_spec["encryption"]
                    and dest_file_spec["encryption"]["encrypt"]
                )
                # Check if encryption is requested
                if encryption_requested and not can_do_encryption:
                    return self.return_result(
                        1,
                        "Encryption requested but not supported for this transfer",
                        exception=exceptions.EncryptionNotSupportedError,
                    )

                # If encryption is requested and its possible, then encrypt the file(s)
                if encryption_requested and can_do_encryption:

                    self.logger.info("Encrypting files")

                    # Get the public key from the spec
                    public_key = dest_file_spec["encryption"]["public_key"]
                    private_key = None

                    if (
                        "sign" in dest_file_spec["encryption"]
                        and dest_file_spec["encryption"]["sign"]
                    ):
                        private_key = dest_file_spec["encryption"]["private_key"]

                    # For each file in the remote_files list, alter the path to start
                    # with the local staging directory instead
                    local_files = {}
                    for file in remote_files:
                        # Strip the path and replace it with the stating directory
                        local_files[
                            f"{self.local_staging_dir}/{path.basename(file)}"
                        ] = remote_files[file]

                    extension = dest_file_spec["encryption"].get(
                        "output_extension", "gpg"
                    )
                    # Loop through each file and encrypt it using gnupg
                    remote_files = self.encrypt_files(
                        local_files, public_key, private_key, extension
                    )

                    encrypted_files = remote_files.copy()

                    self.logger.info(f"Encrypted {len(remote_files)} files")

                # Handle the push transfers first
                associated_dest_remote_handler = self.dest_remote_handlers[i]
                # If this is a default push transfer, and both source and dest protocols are the same
                if (
                    (
                        "transferType" not in dest_file_spec
                        or dest_file_spec["transferType"] == "push"
                        # And the destination and source remote handler classes are the same
                    )
                    and not any_different_protocols
                    and source_supports_direct_transfer
                ):
                    transfer_result = self.source_remote_handler.transfer_files(
                        remote_files,
                        dest_file_spec,
                        dest_remote_handler=associated_dest_remote_handler,
                    )
                    if transfer_result != 0:
                        return self.return_result(
                            1,
                            "Remote transfer errored",
                            exception=exceptions.RemoteTransferError,
                        )

                    self.logger.info("Transfer completed successfully")
                # If this is a default push transfer, and source and dest protocols are different
                elif (
                    "transferType" not in dest_file_spec
                    or (
                        dest_file_spec["transferType"] == "push"
                        or dest_file_spec["transferType"] == "proxy"
                    )
                ) and (
                    any_different_protocols
                    or (
                        "transferType" in dest_file_spec
                        and dest_file_spec["transferType"] == "proxy"
                    )
                    or not source_supports_direct_transfer
                ):
                    self.logger.debug(
                        "Transfer protocols are different, or proxy transfer is"
                        " requested"
                    )

                    # For local transfers, the handler needs the list of local files to push
                    # If there was decryption, then the files will be local regardless, so
                    # needs the list of files then too, so it doesn't upload the encrypted files
                    if (
                        self.source_file_spec["protocol"]["name"] != "local"
                        and not decryption_requested
                        and not encryption_requested
                    ):
                        transfer_result = (
                            associated_dest_remote_handler.push_files_from_worker(
                                self.local_staging_dir
                            )
                        )
                    else:
                        transfer_result = (
                            associated_dest_remote_handler.push_files_from_worker(
                                self.local_staging_dir, file_list=remote_files
                            )
                        )

                    if transfer_result != 0:
                        return self.return_result(
                            1,
                            "Push of files to destination errored",
                            exception=exceptions.RemoteTransferError,
                        )

                elif (
                    "transferType" in dest_file_spec
                    and dest_file_spec["transferType"] == "pull"
                ):
                    transfer_result = associated_dest_remote_handler.pull_files(
                        remote_files, self.source_file_spec
                    )
                    if transfer_result != 0:
                        return self.return_result(
                            1,
                            "Remote PULL transfer errored",
                            exception=exceptions.RemoteTransferError,
                        )

                    self.logger.info("Transfer completed successfully")

                else:
                    transfer_type = dest_file_spec.get("transferType", "push")
                    self.logger.warning(
                        "No valid transfer method available for destination "
                        f"{dest_file_spec.get('hostname', '<unknown>')} with "
                        f"transferType={transfer_type}, "
                        f"source_handler={self.source_remote_handler.__class__.__name__}, "
                        f"dest_handler={associated_dest_remote_handler.__class__.__name__}, "
                        f"source_supports_direct_transfer={source_supports_direct_transfer}"
                    )
                    return self.return_result(
                        1,
                        "No valid transfer method available for destination",
                        exception=exceptions.RemoteTransferError,
                    )

                # Handle any ownership and permissions changes
                if dest_file_spec["protocol"]["name"] == "ssh":
                    move_result = self.dest_remote_handlers[
                        i
                    ].move_files_to_final_location(remote_files)
                    if move_result != 0:
                        return self.return_result(
                            1,
                            "Error moving file into final location",
                            exception=exceptions.RemoteTransferError,
                        )

                # Create any flag files that might need creating
                if "flags" in dest_file_spec:
                    flag_result = self.dest_remote_handlers[i].create_flag_files()
                    if flag_result != 0:
                        return self.return_result(
                            1,
                            "Error creating flag files",
                            exception=exceptions.RemoteTransferError,
                        )

                i += 1

                self.logger.info(f"Transferred {len(remote_files)} files")

            if (
                requires_local_staging
                and self.source_file_spec["protocol"]["name"] != "dummy"
                and self.local_staging_dir != self.source_file_spec["directory"]
            ):
                self.logger.debug("Removing local staging directory")
                if path.exists(self.local_staging_dir):
                    shutil.rmtree(self.local_staging_dir)
        else:
            self.logger.info("Performing filewatch only")

        # If there was encryption done, we need to remove all the encrypted files regardless, and then
        # restore the original remote_files dict
        if encrypted_files.keys():
            for encrypted_file in encrypted_files:
                # Check the file still exists before removing it
                if path.exists(encrypted_file):
                    self.logger.info(f"Removing local encrypted file {encrypted_file}")
                    remove(encrypted_file)

            remote_files = original_file_list

        # Do the same for the decrypted files
        if decrypted_files.keys():
            for decrypted_file in decrypted_files:
                if path.exists(decrypted_file):
                    self.logger.info(f"Removing local decrypted file {decrypted_file}")
                    remove(decrypted_file)

            remote_files = original_file_list

        if "postCopyAction" in self.source_file_spec:
            try:
                self.logger.info("Performing post copy action")
                pca_result = self.source_remote_handler.handle_post_copy_action(
                    remote_files
                )
            except Exception as e:  # pylint: disable=broad-exception-caught
                pca_result = 1
                return self.return_result(
                    1,
                    "Error performing post copy action",
                    exception=e,
                )
            if pca_result != 0:
                return self.return_result(
                    1,
                    "Error performing post copy action",
                    exception=exceptions.RemoteTransferError,
                )

        return self.return_result(0)

    def _setup_gnupg(self) -> gnupg.GPG:
        """Setup gnupg object with homedir set to a temporary directory.

        Returns:
            gnupg.GPG: The gnupg object
        """
        # Make the gnupg home directory in a temporary directory, use the
        # original directory, and create it if it doesn't exist
        gnupg_home_dir = f"{self._get_staging_directory()}/.gnupg"
        makedirs(gnupg_home_dir, exist_ok=True)

        return gnupg.GPG(gnupghome=gnupg_home_dir)

    def _tidy_gnupg_home(self, gpg: gnupg.GPG) -> None:
        """Tidy up the gnupg homedir."""
        if path.exists(gpg.gnupghome):
            try:
                shutil.rmtree(gpg.gnupghome, ignore_errors=True)
            except FileNotFoundError as e:
                self.logger.warning(
                    f".gnupg deletion failed - FileNotFound but continuing: {e}"
                )

    def encrypt_files(
        self,
        files: dict,
        public_key: str,
        private_key: str | None = None,
        extension: str = "gpg",
    ) -> dict:
        """Encrypt files using GPG.

        Args:
            files (dict): Dictionary of files to encrypt.
            public_key (str): Public key to use for encryption.
            private_key (str, optional): Private key to use to sign the files. Defaults to None.
            extension (str, optional): Extension to add to the encrypted files. Defaults to "gpg".

        Returns:
            dict: Dictionary of encrypted files.
        """
        # Set up gnupg
        gpg = self._setup_gnupg()

        # Remove any escaped newline characters from the key
        public_key = public_key.replace("\\n", "\n")

        # Load the public key
        import_result = gpg.import_keys(public_key)

        # Check the key imported OK
        if not import_result.count or import_result.count == 0:
            self.logger.error("Error importing public key")
            raise exceptions.EncryptionError("Error importing public key")

        # Get the fingerprint of the key we just imported
        key_fingerprint = gpg.list_keys()[0]["fingerprint"]
        signing_key = None

        if private_key:
            # Load the private key
            import_result = gpg.import_keys(private_key)

            # Check the key imported OK
            if not import_result.count or import_result.count == 0:
                self.logger.error("Error importing private key")
                raise exceptions.EncryptionError("Error importing private key")

            signing_key = import_result.fingerprints[0]

        encrypted_files = {}
        for file in files:

            # If the filename contains .gpg on the end, then the output file will be just that but without the extension,
            # if it doesn't contain .gpg, then we'll add .gpg to the end
            output_filename = f"{file}.{extension}"

            with open(file, "rb") as input_file:
                encryption_data = gpg.encrypt_file(
                    input_file,
                    recipients=key_fingerprint,
                    output=output_filename,
                    always_trust=True,
                    sign=signing_key,
                )

                # Check whether the encryption worked
                if not encryption_data.ok or encryption_data.status != "encryption ok":
                    self.logger.error(
                        f"Error encrypting file {file}: {encryption_data.status}"
                    )
                    # Print the stderr line too
                    self.logger.error(f"GPG STDERR: {encryption_data.stderr}")
                    self._tidy_gnupg_home(gpg)
                    raise exceptions.EncryptionError(
                        f"Error encrypting file {file}: {encryption_data.status}"
                    )

            encrypted_files[output_filename] = files[file]

        # Remove the temporary gnupg keychain files under gpg.gnupghome
        self._tidy_gnupg_home(gpg)

        return encrypted_files

    def decrypt_files(self, files: dict, private_key: str) -> dict:
        """Decrypt files using GPG.

        Args:
            files (dict): Dictionary of files to decrypt.
            private_key (str): Private key to use for decryption.

        Returns:
            dict: Dictionary of decrypted files.
        """
        # Set up gnupg
        gpg = self._setup_gnupg()

        private_key = private_key.replace("\\n", "\n")

        # Load the private key
        import_result = gpg.import_keys(private_key)
        # Check the key imported OK
        if not import_result.count or import_result.count == 0:
            self.logger.error("Error importing private key")
            raise exceptions.EncryptionError("Error importing private key")

        decrypted_files = {}
        for file in files:

            # If the filename contains .gpg or .pgp on the end, then the output file will be just that but without the extension,
            # if it doesn't contain .gpg or .pgp, then we'll add .decrypted to the end
            output_filename = (
                file.replace(".gpg", "").replace(".pgp", "")
                if file.endswith((".gpg", ".pgp"))
                else f"{file}.decrypted"
            )

            self.logger.info(f"Decrypting {file} to {output_filename}")

            with open(file, "rb") as input_file:
                decryption_data = gpg.decrypt_file(
                    input_file,
                    output=output_filename,
                )

                # Check whether the decryption worked
                if not decryption_data.ok or decryption_data.returncode != 0:
                    self.logger.error(
                        f"Error decrypting file {file}: {decryption_data.status}"
                    )
                    # Print the stderr line too
                    self.logger.error(f"GPG STDERR: {decryption_data.stderr}")

                    self._tidy_gnupg_home(gpg)

                    raise exceptions.DecryptionError(
                        f"Error decrypting file {file}: {decryption_data.status}"
                    )

            decrypted_files[output_filename] = files[file]

        # Tidy up the gnupg homedir
        self._tidy_gnupg_home(gpg)

        self.logger.debug(f"Returning decrypted files: {decrypted_files}")

        return decrypted_files

    def check_conditionals(self, remote_files: dict) -> dict:
        """Check conditionals of found files.

        Args:
            remote_files (dict): Dictionary of files found matching regex.

        Returns:
            dict: Dictionary of decrypted files.
        """
        for remote_file in list(remote_files):
            self.logger.info(f"Checking {remote_file}")

            # Check to see if there's a size condition
            meets_condition = True

            if "size" in self.source_file_spec["conditionals"]:
                self.logger.log(12, "Checking file size")
                min_size = self.source_file_spec["conditionals"]["size"].get("gt", None)
                max_size = self.source_file_spec["conditionals"]["size"].get("lt", None)

                file_size = remote_files[remote_file]["size"]

                if min_size and file_size <= min_size:
                    self.logger.info(
                        f"File is too small: Min size: [{min_size} B] Actual size:"
                        f" [{file_size} B]"
                    )
                    meets_condition = False

                if max_size and file_size >= max_size:
                    self.logger.info(
                        f"File is too big: Max size: [{max_size} B] Actual size:"
                        f" [{file_size} B]"
                    )
                    meets_condition = False

            if "age" in self.source_file_spec["conditionals"]:
                min_age = self.source_file_spec["conditionals"]["age"].get("gt", None)
                max_age = self.source_file_spec["conditionals"]["age"].get("lt", None)

                file_modified_time = remote_files[remote_file]["modified_time"]
                file_age = time.time() - file_modified_time

                self.logger.log(
                    12,
                    "Checking file age - Last modified time:"
                    f" {time.ctime(file_modified_time)} - Age in secs:"
                    f" {file_age} secs",
                )

                if min_age and file_age <= min_age:
                    self.logger.info(
                        f"File is too new: Min age: [{min_age} secs] Actual age:"
                        f" [{file_age} secs]"
                    )
                    meets_condition = False

                if max_age and file_age >= max_age:
                    self.logger.info(
                        f"File is too old: Max age: [{max_age} secs] Actual age:"
                        f" [{file_age} secs]"
                    )
                    meets_condition = False
            if not meets_condition:
                remote_files.pop(remote_file)
        if "count" in self.source_file_spec["conditionals"]:
            min_count = self.source_file_spec["conditionals"]["count"].get(
                "minCount", None
            )
            max_count = self.source_file_spec["conditionals"]["count"].get(
                "maxCount", None
            )
            # clear remote_files to ensure filewatch continues if count conditionals not correct
            if (max_count and (len(remote_files) > max_count)) or (
                min_count and (len(remote_files) < min_count)
            ):
                self.logger.info(
                    f"Number of found files {len(remote_files)} does not meet minCount/maxCount conditional: maxCount:{max_count if max_count else 'n/a'}, minCount:{min_count if min_count else 'n/a'}"
                )
                remote_files.clear()
        return remote_files
