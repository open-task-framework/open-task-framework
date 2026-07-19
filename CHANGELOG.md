# Changelog

# v26.28.1

- Fix batch timeout handling so tasks are not marked failed immediately when a timeout is reached, allowing tasks that continue running and complete successfully to be recorded as successful. This is significant for S3 transfers for example where the transfer cannot be killed, and may complete successfully if there is an in-flight transfer actively downloading/uploading. Closes [#162](https://github.com/open-task-framework/open-task-framework/issues/162)

# v26.28.0

- Fix the transfer routing bug where destinations could be skipped when a task had multiple destinations with mixed handler types and the final destination matched the source handler type. Closes [#161](https://github.com/open-task-framework/open-task-framework/issues/161)

# v26.18.1

- Fix memory leak in batches caused by now tidying up the remote handler objects after a task has completed.
- Fixed potential but very small memory leak in logger where loggers were not being removed from the logger dictionary after they were closed.
- Add `OTF_LOG_MEMORY_USAGE` environment variable to allow logging of RSS memory usage at each batch poll interval using the batch logger. This is useful for diagnosing memory growth in long-running batches. Added optional dev dependency `psutil` to allow this. Needs to be installed manually, otherwise log will just output `-1.0` for RSS memory usage.

# v26.18.0

- Disable logging of initialisation events by default, can be enabled by setting env var `OTG_LOG_INIT_EVENTS=1`
- Ensure that setting `OTF_LOG_LEVEL` to `DEBUG` actually sets the log level to `DEBUG` in the root logger, which ensures addons like the AWS addon will trigger `botocore` to log it's debug messages too.
- Update `README.md` and help text to include new environment variables, and any missing ones.

# v26.15.0

- Add `OTF_STALE_RUNNING_LOG_SECONDS` environment variable to allow resuming of batches from a `_running` log file that is older than the specified number of seconds.
- Update GPG key used for testing with a 10 year expiry to stop tests failing.
- Bump minimum versions dependencies to:
  - `jsonpath-ng >= 1.8`
  - `jsonschema >= 4.26`
  - `paramiko >= 4.0`
  - `requests >= 2.33`
  - `referencing >= 0.37`
  - `tenacity >= 9.1`
  - `python-gnupg >= 0.5.6`

# No release

- Update docs

# v26.10.0

- Resolve Jinja-templated lookup arguments before invoking lookup plugins.
- Make lookup plugin `globals` resolution lazy so plugins can access needed variables without forcing unrelated deep variable chains to resolve.
- Preserve lookup compatibility when lazy variable loading is enabled.

# v25.8.1

- Handle race condition when creating directories in logging module, triggered byu many threads trying to create the same directory at the same time.
- Enforce log output bufering to flush after newline characters.

# v25.37.0

- Add additional logging to `sftp` & `local` protocol.
- Add `rename` option to `email` destination protocol.
- Tidy GPG logic and move gpghome creation into a temporary directory to avoid issues with multiple processes (or retries) finding broken keychains. Hopefully fixes an issue encountered when uusing EFS as a staging location and the contents of the .gnupg directory being locked.
- Performance improvements to config loading

# v25.35.2

- Fix race condition when importing addons too. See previous release notes for more details.

# v25.35.1

- Fix race condition in concurrent protocol imports by implementing thread-safe class-level cache with double-checked locking pattern
- Add `OTF_NO_THREAD_SLEEP` environment variable to disable the 1-second sleep between batch task thread creation (primarily for testing)

# v25.35.0

- Alter connectivity check for SFTP connections to ensure that the connection is actually active before continuing

# v25.32.0

- Email destination task handler to load the email message once instead of once per recipient
- Email message content file deletion now occurs only if all emails are sent successfully

# v25.26.1

- Add the ability to add custom filters for Jinja2 templates under the `<config>/filters` directory.
- Allow email destination task handler to load the email body content from a file

# v25.26.0

- Improved environment variable override logic for nested variables in both global and task-specific contexts.
- Allow overriding of nested variables using dot notation e.g. `export SOME_VARIABLE.NESTED_VARIABLE=new_value`.

# v25.22.0

- Support for attribute overrides where there are multiple nested keys with underscores (using `!!` override syntax)

# v25.16.2

- Support for HTML email body

# v25.16.1

- Add handling for overriding vars with underscores

# v25.16.0

- Fix schema for email destination task handler to include missing `message` attribute
- Remove requirement for `accessToken` in dummy handler
- Prevent `transfer.py` throwing an error when `dummy` protocol is used as the source and no files are returned
- Add test to test email destination task handler with a custom email body

# v25.15.0

- Added new devcontainer for working with the OTF Addons in a single dev environment
- Add retry boolean to SFTP protocol definition. Allows bypassing exponential backoff, with no retrying
- Better simulate SFTP timeout test by adding a firewall rule to drop packets on port 1234

# v25.3.1

- Adjust email_destination TaskHandler to allow use of TLS/credentials to be optional, and set default port to 587
- Adjust email_destination protocol schema to ensure that smtp_server and sender are set

# v25.3.0

- Add ignore_errors=True to problematic .gnupg removal

# v24.51.0

- Fixing dependency checker in batches
- Including Runnable task checker before breaking execution loop
- Improved code readability

# v24.47.1

- Add missing try/catch to decryption code when trying to delete gnupg directory

# v24.47.0

- Refactored dependency checker method to support Running/Failed state

# v24.46.0

- Added support for PostCopyAction dir auto-creation

# v24.45.1

- Add additional delta_hours helper function to config loader

# v24.45.0

- Add further exception handling for deleting .gnupg directories after handling file decryption

# v24.44.2

- Make SFTP timeout configurable within protocol definition

# v24.44.1

- Fix batch logic to ensure that all tasks run before exiting

# v24.44.0

- Try to fix issue where SFTP connections were not being closed properly
- Force setting timeout for SFTP transport after connection is established
- Add extra log to SFTP transfers
- Change sleep log message to show how long it's actually sleeping for

# v24.42.0

- Fix issue where different protocols where not being detected properly, and proxy had to be explicitly defined when it was unnecessary
- When creating a destination directory with SFTP, it will now check whether lower level directories exist, and create them if not
- Always check for a directory before trying to delete it and thowing an exception if it doesn't exist.
- Moved exception printing for transfers to earlier in th code to ensure log messages aren't confusing.
- Add ability to check for SSH host key and validate it before proceeding with connection

# No release

- Bump `black` to 24.10.0

# v24.37.2

- Fix issue where nested variables were not being resolved correctly when using lazy loading

# v24.37.1

- Allow loading of multiple variables files via `OTF_VARIABLES_FILE` by specifying them comma-separated
- Ensure global time-based variables resolve when rendering nested variables

# v24.37.0

- Fix issue where new lazy loading code conflicts with `NOOP` mode, where it was trying to resolve variables regardless

# v24.36.2

- Add OTF_PARAMIKO_ULTRA_DEBUG environment variable to enable the hidden `ultra_debug` option for Paramiko (SFTP only).
- Add some more logging to the SFTP transfers
- Set `sftp_client` to `None` when closing the SFTP connection
- Added `OTF_LAZY_LOAD_VARIABLES` environment variable to enable lazy loading of variables.
- Updated `otflogging` to redact sensitive data from logs
- Increate the number of retries for SSH and SFTP connections

# v24.36.1

- Revert removal of some local transfer tests

# v24.36.0

- Add the option to specify conditionals for minimum and maximum expected counts of files matching regex to local, sftp and ssh sources

# v24.32.0

- Add dependabot config.
- Add debug logging to `get_latest_log_file` function
- Fix test for `get_latest_log_file` function to clear the log directory before running the test

# v24.30.0

- Add `supportsPosixRename` option to SFTP source so that post copy actions will work on server that don't support POSIX renames

# v24.25.0

- Remove stray `\\n` characters from private and public keys when doing encryption/decryption, and replace with proper newlines
- Fix workflow for changelog checking

# v24.23.0

- Added new `cacheableVariables` option for transfers. This allows you to specify a list of variables that should be cached and written back to somewhere (depending on the `cachingPlugin` referenced). This is useful for dynamically updated variables that need to be stored centrally. For more detail see the `README.md`ß

# v24.21.0

- Fixed renaming encrypted files when uploading via SFTP - Fixes [#79](https://github.com/adammcdonagh/open-task-framework/issues/79)
- Fix WRAPPER log file to ensure it closes when a child task fails due to an Exception - Fixes [#81](https://github.com/adammcdonagh/open-task-framework/issues/81)
- Allow different file extension for encrypted files. Added `output_extension` to allow a different file extension for GPG encrypted files, instead of the default `.gpg`
- When decrypting, handle both .gpg and .pgp file extensions by default before reverting to .decrypted exetnsion

# v24.19.1

- Add additional timeout values for SFTP connections - Attempting to fix [#68](https://github.com/adammcdonagh/open-task-framework/issues/68)
- Add more steps to capture all log output better

# v24.19.0

- When creating directories, ensure entire path is created recursively rather than just attempting to create rightmost path part

# v24.18.0

- Add the option to sign encrypted files using a private key, by setting `"sign": true`, and supplying the `private_key` property.

# v24.17.3

- Fix issue where using decryption meant that the encrypted file was also transferred to the destination.
- Improved some logging.

# v24.17.2

- Fix further issues relating to encryption and decryption.
- Added some additional tests to test via SFTP instead of just local transfers.

# v24.17.1

- Fix issue where PCA when encrypting files would only handle the encrypted file(s), and not the original file(s)

# v24.17.0

- Add protocol option for SFTP destination - `supportsStatAfterUpload` - When set to false this will prevent `stat` being run after upload. This helps when certain custom SFTP servers do not allow you to see your uploaded file, or they move it out of the way as soon as it's written to.
- Minor update to SFTP transfer when uploading to `/` to prevent destination path starting with `//`

# No release

- Updated linting rules and some formatting in the tests
- Updated devcontainer config etc to reflect the new linting etc

# v24.14.0

- Replace existing `now` Jinja function with `utc_now`. This always returns the UTC time. `now` will always return the localtime of the machine running the task instead.

# v24.13.1

- Fix an issue where local transfers were still deleting the source directory when tidying up the staging area, causing post copy actions to fail too

# v24.13.0

- Add PGP encryption to transfers - N.B. This is only possible where the files are being pulled onto the worker first, and then transferred to the destination. This is because the PGP encryption is done on the worker, and not on the source machine.
- Fixed an issue where files pushed from local worker would transfer more than just the files that matched the regex if they lived in the source directory
- BREAKING: Due to the above. `push_files_from_worker` now requires a file list to be passed when the source protocol is `local`. This is because the worker doesn't have the same context as the source machine, so it doesn't know what files are in the source directory. This is a breaking change, but it's necessary to ensure that the worker only pushes the files that are required.
- Added new option to SFTP destination in case `posix-rename` feature is not supported by the server. This prevents files being uploaded with a `.partial` extension, and instead uploads directly as the final filename. This is done by setting `supportsPosixRename` to `false` in the destination protocol definition.

# v24.11.0

- Fix an issue with batches not killing transfers when the task times out

# v24.10.0

- Update otflogging to be more thread safe when closing log file
- Fix [#60](https://github.com/adammcdonagh/open-task-framework/issues/60) by ensuring log file creation doesn't rely on OTF_TASK_ID env var, which is different between threads when running a batch task

# v24.9.0

- Fix timed out batch and transfer logging to ensure that the log file is closed correctly
- Reorder log format to bring log level to the front
- Add retry logic to SSH based connections
- Prevent local based transfers from using the staging directory

# v24.8.0

- Update `--noop` to work correctly for batch
- Add a simple batch config validator. This checks that there are consecutive tasks, tasks definitions exist, and dependencies are valid

# v24.5.1

- Add ability to specify a key string for SSH type connections

# v24.5.0

- Change versioning format
- Fixed file transfers to ensure that only files matching the regex are actually transferred

# v0.15.2

- Fix issue loading modules too fast with multiple steps in a batch

# v0.15.1

- Fix issue with logs not renaming correctly when an exception is thrown that's not caught
- Fix issue where `"error": false` for a transfer still caused the transfer to exit with a non-zero exit code

# v0.15.0

- Fix issue with chmods not actually working as intended
- Ensure valid test for chmod exists
- NEW: Allow independent environment variable based override of variables file while using same config file.
- NEW: Add `--noop` argument. This allows you to validate the config without executing anything.

# v0.14.3

- Fix issue with local file move when cross filesystem.

# v0.14.2

- Minor log verbosity update

# v0.14.1

- Fix issue where port number is being ignored because the schema definition doesn't match the code that uses it.

# v0.14.0

- Add mode override docs to `--help`
- Allow task definitions to use a whole templated object within them. e.g a protocol definition could be defined as a global variable to define SFTP connectivity to a commonly used source/destination. This is done using `.j2` task definition file instead of `.json`

# v0.13.1

- Fix protocol schemas to allow protocols other that SSH to actually be used for transfers
- Add some more documentation to the `--help` output

# v0.13.0

- Add additional tests to improve coverage
- Fix some SSH code to use SFTP client whenever possible
- Improve logging for batch tasks
- Fix a bug in local executions where timeouts were failing to parse the process listing, and run the `kill` command correctly
- Altered log format to include `filename` and `lineno` for log messages
- Remove `transfer.py` script. All transfer related commands for SSH protocol are now done natively using the SSH connection or SFTP commands

# v0.12.1

- Enforce source `directory` definition in transfer schemas for SSH and SFTP
- Ensure a recent `pylint` is being used
- Remove comment from CODEOWNERS file
- Add codecov to CI steps
- Add badges to `README.md`

# v0.12.0

- Added JSON formatter for logging to stderr. This replaces the default Python logging format with structured JSON output. This is enabled by setting the `OTF_LOG_JSON` environment variable to `1`. Log files are not impact, as these are always in standard format, as this is required for the batch log parsing to allow for rerunability.
- Tidy up logging
- Fix SSH transfers to ensure that SSH connections are fully closed after use
- Update SFTP transfers to use .partial file extension while files are being uploaded, and then rename them to their final name the transfer is complete.
- Altered log level for some messages
- Added `OTF_BATCH_RESUME_LOG_DATE` to allow resuming of batch runs from a specific date. This is useful if you want to rerun a batch from a specific date, especially if the failure happens just after midnight and the date is no longer the same as the original run.

# v0.11.0

- Added ability to run local transfers and executions using new `local` protocol. This is based on the same syntax as the SSH based protocols but doesn't need a `hostname` to be defined.
- Fixed an issue in the transfer taskhandler to ensure that protocols are handled correctly.
- Added missing `rename` functionality to the `sftp` protocol on destination files.

# v0.10.0

- Migrated deprecated jsonschema validation to use `referencing` package instead of `RefResolver`
- Added default SFTP protocol for transfers
- Added optional (unused) `createDirectoryIfNotExists` property to transfers for transfer destinations (SSH & SFTP). If `true` directory will be created with default permissions

# v0.9.0

- Linting updates
- Added new pre-commit tasks
- Add argument sanitisation when passing arguments for remote execution

# v0.8.1

- Added pre-commit config to devcontainer
- Applied pre-commit fixes
- Fixed task-run so that errors we actually get a non-zero return code on failures
- Update docs

# v0.8

- Added ability to override global variables at runtime. e.g. Override date variables to pick up files from previous days

## v0.7.1

- Removed old setup.py
- Removed old TODO message

## v0.7

- Add some Dockerfiles to allow `task-run` to be run via a Docker container
- Update documentation
- Add the ability to use a globally overridden SSH private key for connectivity via the `OTF_SSH_KEY` env var
- Update test fixture for SSH clients to ensure that the private key file being used is actually valid
- Fix protocol definition JSON schema to validate the use of `keyFile` in credentials section
- Permission issues with Docker tests

## v0.6.3

- Force requirement for protocol definition in JSON schemas

## v0.6.2

- Update package config to link to changelog
- Update `README.md` to show new workflow badge

## v0.6.1

- Added proper JSON validation code

## v0.4.2

- Updated batches to better kill threads.
- Fixed logging class to handle checking previous runs when the log dir doesn't already exist

## v0.4.1

- Fixed a bug in executions causing them not to generate an error if an exception is thrown when executing them .
