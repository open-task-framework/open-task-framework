"""Execution task handler."""

import threading
from concurrent.futures import ThreadPoolExecutor, wait
from typing import Any, NamedTuple, cast

import opentaskpy.otflogging
from opentaskpy.remotehandlers.remotehandler import RemoteExecutionHandler
from opentaskpy.taskhandlers.taskhandler import TaskHandler


class DefaultProtocolCharacteristics(NamedTuple):
    """Class defining the configuration for default protocols."""

    module: str
    class_: str


TASK_TYPE = "E"


class Execution(TaskHandler):
    """Execution task handler."""

    remote_handlers: list[RemoteExecutionHandler] | None = None
    overall_result: bool = False

    _protocol_classes: dict[str, type] = {}  # Class-level cache
    _protocol_lock = threading.Lock()  # Lock for class-level cache

    def __init__(
        self,
        global_config: dict[str, Any] | None,
        task_id: str,
        execution_definition: dict,
    ):
        """Initialize the execution handler.

        Args:
            global_config (dict): The global config.
            task_id (str): The task ID.
            execution_definition (dict): The execution definition.
        """
        self.task_id = task_id
        self.execution_definition = execution_definition

        self.logger = opentaskpy.otflogging.init_logging(
            "opentaskpy.taskhandlers.execution", self.task_id, TASK_TYPE
        )

        super().__init__(global_config)

    def return_result(
        self,
        status: int,
        message: str | None = None,
        exception: type[Exception] | Exception | None = None,
    ) -> bool:
        """Return the result of the task run.

        Args:
            status (int): The status code to return.
            message (str, optional): The message to return. Defaults to None.
            exception (Exception, optional): The exception to return. Defaults to None.

        Returns:
            bool: The result of the task run.
        """
        # Delete the remote connection objects
        if self.remote_handlers:
            for remote_handler in self.remote_handlers:
                remote_host = self._get_remote_host_name(remote_handler)

                self.logger.log(
                    12,
                    f"[{remote_host}] Closing source connection for {remote_handler}",
                )
                remote_handler.tidy()

        # Call super to do the rest
        return super().return_result(status, message, exception)  # type: ignore[no-any-return]

    def _get_remote_host_name(self, remote_handler: RemoteExecutionHandler) -> str:
        return (
            str(remote_handler.remote_host)
            if hasattr(remote_handler, "remote_host")
            else "REMOTE"
        )

    def _set_remote_handlers(self) -> None:
        """Set the remote handlers.

        Determine which protocols are in use and create the appropriate objects for
        each.
        """
        # Based on the transfer definition, determine what to do first
        # Based on the remote protocol pick the appropriate remote handler
        # For each host, create a remote handler
        self.remote_handlers = []
        remote_protocol = self.execution_definition["protocol"]["name"]
        self.execution_definition["task_id"] = self.task_id

        if remote_protocol in super().DEFAULT_PROTOCOL_MAP[TASK_TYPE]:
            if "hosts" in self.execution_definition:
                for host in self.execution_definition["hosts"]:
                    handler_class = cast(
                        Any, super()._get_default_class(TASK_TYPE, remote_protocol)
                    )
                    remote_handler = cast(
                        RemoteExecutionHandler,
                        handler_class(host, self.execution_definition),
                    )

                    self.remote_handlers.append(remote_handler)
            else:
                handler_class = cast(
                    Any, super()._get_default_class(TASK_TYPE, remote_protocol)
                )
                remote_handler = cast(
                    RemoteExecutionHandler, handler_class(self.execution_definition)
                )

                self.remote_handlers.append(remote_handler)
        else:
            remote_handler = cast(
                RemoteExecutionHandler,
                super()._get_handler_for_protocol(
                    remote_protocol, self.execution_definition
                ),
            )
            self.remote_handlers.append(remote_handler)

            super()._set_handler_vars(remote_protocol, remote_handler)

    def run(self, kill_event: threading.Event | None = None) -> bool:
        """Run the execution.

        Args:
            kill_event (threading.Event, optional): An event to kill the execution. Defaults to None.

        Returns:
            bool: The result of the execution.
        """
        self.logger.info("Running execution")

        self._set_remote_handlers()

        # Check that we have remote handlers, if not something has gone very wrong
        if not self.remote_handlers:
            self.logger.error("No remote handlers set")
            return self.return_result(1, "No remote handlers set")

        # This is where we could potentially be waiting for a while. So,
        # for each remote handler, we should spawn a new thread to run
        # the command. Then we can wait for all threads to complete.

        ex = None

        with ThreadPoolExecutor(len(self.remote_handlers)) as executor:
            futures = [
                executor.submit(self._execute, remote_handler)
                for remote_handler in self.remote_handlers
            ]
            self.logger.debug("Triggered all threads")

            while True:
                try:
                    # Sleep 5 seconds for each loop
                    wait(futures, timeout=5)
                    self.logger.info("Waiting for threads to complete...")

                except TimeoutError:
                    pass

                if kill_event and kill_event.is_set():
                    self.logger.info("Kill event received, stopping threads")

                    # Before we terminate everything locally, we need to make sure that the processes
                    # on the remote hosts are terminated as well
                    for remote_handler in self.remote_handlers:
                        remote_host = self._get_remote_host_name(remote_handler)
                        self.logger.info(f"Killing remote processes on {remote_host}")
                        remote_handler.kill()

                    executor.shutdown(wait=False)
                    # Make sure all threaeds are dead
                    for future in futures:
                        future.cancel()
                        # Check it's dead
                        if future.running():
                            self.logger.error(
                                f"Thread {future} is still running after kill. Cannot"
                                " kill a running thread. Will have to wait for it to"
                                " complete. Consider altering the plugin so that it"
                                " cannot block."
                            )

                    return self.return_result(
                        1, "Execution(s) failed - Kill signal received"
                    )

                # Break once all threads are done
                if all(future.done() for future in futures):
                    break

            # Check the results
            failures = False
            for future in futures:
                try:
                    result = future.result()
                    if not result:
                        failures = True
                except Exception as e:  # pylint: disable=broad-exception-caught
                    self.overall_result = False
                    ex = e
                    self.logger.error("Thread returned exception")
                    # Ensure we log the exception
                    self.logger.exception(e)
                    failures = True

            if not failures:
                self.overall_result = True

        if self.overall_result:
            return self.return_result(0, "All executions completed successfully")

        return self.return_result(1, "Execution(s) failed", ex)

    def _execute(self, remote_handler: RemoteExecutionHandler) -> bool:
        result: bool = remote_handler.execute()
        remote_host = self._get_remote_host_name(remote_handler)
        self.logger.info(f"[{remote_host}] Execution returned {result}")
        return result
