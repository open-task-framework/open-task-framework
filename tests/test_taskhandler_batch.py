# pylint: skip-file
# ruff: noqa
import os
import random
import shutil
import time

import pytest
from pytest_shell import fs

import opentaskpy.otflogging
from opentaskpy.config.loader import ConfigLoader

# from opentaskpy.taskhandlers.batch import Batch
from opentaskpy.taskhandlers import batch, execution, transfer
from tests.file_helper import *  # noqa: F403
from tests.fixtures.ssh_clients import *  # noqa: F403

os.environ["OTF_NO_LOG"] = "1"
os.environ["OTF_LOG_LEVEL"] = "DEBUG"


# Create a task definition
basic_batch_definition = {
    "type": "batch",
    "tasks": [
        {
            "order_id": 1,
            "task_id": "touch",
        }
    ],
}

timeout_batch_definition = {
    "type": "batch",
    "tasks": [
        {
            "order_id": 1,
            "task_id": "sleep-300",
            "timeout": 10,
        },
        {
            "order_id": 2,
            "task_id": "sleep-300-local",
            "timeout": 10,
        },
    ],
}

timeout_batch_transfer_definition = {
    "type": "batch",
    "tasks": [
        {
            "order_id": 1,
            "task_id": "filewatch-300",
            "timeout": 10,
        },
        {
            "order_id": 2,
            "task_id": "filewatch-local-300",
            "timeout": 10,
        },
    ],
}

parallel_batch_definition = {
    "type": "batch",
    "tasks": [
        {
            "order_id": 1,
            "task_id": "touch",
        },
        {
            "order_id": 2,
            "task_id": "scp-basic",
        },
    ],
}

parallel_batch_with_single_failure_definition = {
    "type": "batch",
    "tasks": [
        {
            "order_id": 1,
            "task_id": "touch",
        },
        {
            "order_id": 2,
            "task_id": "fail-command",
        },
    ],
}

parallel_batch_with_single_failure_with_retry_definition = {
    "type": "batch",
    "tasks": [
        {
            "order_id": 1,
            "task_id": "touch",
            "retry_on_rerun": True,
        },
        {
            "order_id": 2,
            "task_id": "fail-command",
        },
    ],
}

parallel_batch_many_definition = {
    "type": "batch",
    "tasks": [
        {
            "order_id": 1,
            "task_id": "sleep-5",
        },
        {
            "order_id": 2,
            "task_id": "sleep-5",
        },
        {
            "order_id": 3,
            "task_id": "sleep-5",
        },
        {
            "order_id": 4,
            "task_id": "sleep-5",
        },
        {
            "order_id": 5,
            "task_id": "sleep-5",
        },
        {
            "order_id": 6,
            "task_id": "sleep-5",
        },
        {
            "order_id": 7,
            "task_id": "sleep-5",
        },
        {
            "order_id": 8,
            "task_id": "sleep-5",
        },
        {
            "order_id": 9,
            "task_id": "sleep-5",
        },
        {
            "order_id": 10,
            "task_id": "sleep-5",
        },
    ],
}

dependent_batch_definition = {
    "type": "batch",
    "tasks": [
        {
            "order_id": 1,
            "task_id": "touch",
        },
        {
            "order_id": 2,
            "task_id": "scp-basic",
            "dependencies": [
                1,
            ],
        },
    ],
}

dependent_batch_continue_on_fail_definition = {
    "type": "batch",
    "tasks": [
        {
            "order_id": 1,
            "task_id": "fail-command",
            "continue_on_fail": True,
        },
        {
            "order_id": 2,
            "task_id": "scp-basic",
            "dependencies": [
                1,
            ],
        },
    ],
}

touch_task_definition = {
    "type": "execution",
    "hosts": ["172.16.0.11", "172.16.0.12"],
    "username": "application",
    "directory": "/tmp",
    "command": "touch /tmp/testFiles/dest/execution.txt",
    "protocol": {"name": "ssh", "credentials": {"username": "application"}},
}

fail_batch_definition = {
    "type": "batch",
    "tasks": [
        {
            "order_id": 1,
            "task_id": "non-existent",
        }
    ],
}

fail_batch_definition_dependencies = {
    "type": "batch",
    "tasks": [
        {
            "order_id": 1,
            "task_id": "sleep-5-local",
        },
        {
            "order_id": 2,
            "task_id": "exit-1-local",
        },
        {
            "order_id": 3,
            "task_id": "sleep-5-local",
        },
        {"order_id": 4, "task_id": "exit-1-local", "dependencies": [1, 2]},
        {"order_id": 5, "task_id": "exit-1-local", "dependencies": [3]},
        {"order_id": 6, "task_id": "exit-1-local", "dependencies": [4]},
    ],
}

# Create a variable with a random number
RANDOM = random.randint(10000, 99999)


def test_basic_batch(setup_ssh_keys, env_vars, root_dir, clear_logs):
    # Create a test file
    fs.create_files(
        [{f"{root_dir}/testFiles/ssh_1/src/test.txt": {"content": "test1234"}}]
    )

    # We need a config loader object, so that the batch class can load in the configs for
    # the sub tasks
    config_loader = ConfigLoader("test/cfg")
    batch_obj = batch.Batch(
        None, f"basic-{RANDOM}", basic_batch_definition, config_loader
    )

    # Check that the batch_obj contains an execution type task
    # batch_obj.tasks[0] should be an instance of a execution task handler class
    assert isinstance(
        batch_obj.task_order_tree[1]["task_handler"],
        execution.Execution,
    )

    # Run the batch and expect a true status
    assert batch_obj.run()

    # Check the execution task was run
    assert os.path.exists(f"{root_dir}/testFiles/ssh_1/src/touchedFile.txt")


def test_batch_parallel(setup_ssh_keys, env_vars, root_dir, clear_logs):
    # Create a test file
    fs.create_files(
        [{f"{root_dir}/testFiles/ssh_1/src/test.txt": {"content": "test1234"}}]
    )

    # We need a config loader object, so that the batch class can load in the configs for
    # the sub tasks
    config_loader = ConfigLoader("test/cfg")
    batch_obj = batch.Batch(
        None, f"parallel-{RANDOM}", parallel_batch_definition, config_loader
    )

    # Check that the batch_obj contains an execution type task
    # batch_obj.tasks[0] should be an instance of a execution task handler class
    assert isinstance(batch_obj.task_order_tree[1]["task_handler"], execution.Execution)
    assert isinstance(batch_obj.task_order_tree[2]["task_handler"], transfer.Transfer)

    # Run the batch and expect a true status
    assert batch_obj.run()


def test_batch_dependencies(root_dir, setup_ssh_keys, env_vars, clear_logs):
    # Create a test file
    fs.create_files(
        [{f"{root_dir}/testFiles/ssh_1/src/test.txt": {"content": "test1234"}}]
    )

    # We need a config loader object, so that the batch class can load in the configs for
    # the sub tasks
    config_loader = ConfigLoader("test/cfg")
    batch_obj = batch.Batch(
        None, f"dependencies-1-{RANDOM}", dependent_batch_definition, config_loader
    )

    # Check that the batch_obj contains an execution type task
    # batch_obj.tasks[0] should be an instance of a execution task handler class
    assert isinstance(batch_obj.task_order_tree[1]["task_handler"], execution.Execution)
    assert isinstance(batch_obj.task_order_tree[2]["task_handler"], transfer.Transfer)

    # Run the batch and expect a true status
    assert batch_obj.run()


def test_batch_invalid_task_id(root_dir, setup_ssh_keys, env_vars, clear_logs):
    # Create a test file
    fs.create_files(
        [{f"{root_dir}/testFiles/ssh_1/src/test.txt": {"content": "test1234"}}]
    )

    # We need a config loader object, so that the batch class can load in the configs for
    # the sub tasks
    config_loader = ConfigLoader("test/cfg")
    # Expect a FileNotFoundError as the task_id is non-existent
    with pytest.raises(FileNotFoundError):
        batch.Batch(None, f"fail-{RANDOM}", fail_batch_definition, config_loader)


def test_batch_execution_timeout(setup_ssh_keys, env_vars, root_dir, clear_logs):
    # Set a log file prefix for easy identification
    # Get a random number

    os.environ["OTF_LOG_RUN_PREFIX"] = f"testbatch_timeout_{RANDOM}"

    config_loader = ConfigLoader("test/cfg")
    batch_obj = batch.Batch(None, "timeout", timeout_batch_definition, config_loader)
    assert not batch_obj.run()

    # Validate that a log has been created with the correct status
    # Use the logging module to get the right log file name
    log_file_name_batch = opentaskpy.otflogging._define_log_file_name("timeout", "B")
    log_file_name_task = opentaskpy.otflogging._define_log_file_name("sleep-300", "E")
    log_file_name_task_local = opentaskpy.otflogging._define_log_file_name(
        "sleep-300-local", "E"
    )

    # Check that both exist, but renamed with _failed
    assert os.path.exists(log_file_name_batch.replace("_running", "_failed"))
    assert os.path.exists(log_file_name_task.replace("_running", "_failed"))
    assert os.path.exists(log_file_name_task_local.replace("_running", "_failed"))

    # Check the contents of the batch log, and verify that it states each task has timed
    # out (and not that it has errored for another reason)
    with open(
        log_file_name_batch.replace("_running", "_failed"), encoding="utf-8"
    ) as f:
        batch_log = f.read()
        assert "Task 1 (sleep-300) has timed out" in batch_log
        assert "Task 2 (sleep-300-local) has timed out" in batch_log


def test_batch_transfer_timeout(setup_ssh_keys, env_vars, root_dir, clear_logs):
    # Set a log file prefix for easy identification
    # Get a random number

    os.environ["OTF_LOG_RUN_PREFIX"] = f"testbatch_transfer_timeout_{RANDOM}"

    config_loader = ConfigLoader("test/cfg")
    batch_obj = batch.Batch(
        None, "transfer_timeout", timeout_batch_transfer_definition, config_loader
    )
    assert not batch_obj.run()

    # Validate that a log has been created with the correct status
    # Use the logging module to get the right log file name
    log_file_name_batch = opentaskpy.otflogging._define_log_file_name(
        "transfer_timeout", "B"
    )
    log_file_name_task = opentaskpy.otflogging._define_log_file_name(
        "filewatch-300", "T"
    )
    log_file_name_task_local = opentaskpy.otflogging._define_log_file_name(
        "filewatch-local-300", "T"
    )

    # Check that both exist, but renamed with _failed
    assert os.path.exists(log_file_name_batch.replace("_running", "_failed"))
    assert os.path.exists(log_file_name_task.replace("_running", "_failed"))
    assert os.path.exists(log_file_name_task_local.replace("_running", "_failed"))

    # Check the contents of the batch log, and verify that it states each task has timed
    # out (and not that it has errored for another reason)
    with open(
        log_file_name_batch.replace("_running", "_failed"), encoding="utf-8"
    ) as f:
        batch_log = f.read()
        assert "Task 1 (filewatch-300) has timed out" in batch_log
        assert "Task 2 (filewatch-local-300) has timed out" in batch_log


def test_batch_parallel_single_success(setup_ssh_keys, env_vars, root_dir, clear_logs):
    # Forcing a prefix makes it easy to identify log files, as well as
    # ensuring that any rerun logic doesn't get hit
    os.environ["OTF_LOG_RUN_PREFIX"] = f"testbatch_timeout_{RANDOM}"

    task_id = f"parallel-single-failure-{RANDOM}"

    config_loader = ConfigLoader("test/cfg")
    batch_obj = batch.Batch(
        None,
        task_id,
        parallel_batch_with_single_failure_definition,
        config_loader,
    )
    # Run and expect a false status
    assert not batch_obj.run()

    # Validate that a log has been created with the correct status
    # Use the logging module to get the right log file name
    log_file_name_batch = opentaskpy.otflogging._define_log_file_name(task_id, "B")
    log_file_name_touch_task = opentaskpy.otflogging._define_log_file_name("touch", "E")
    log_file_name_failed_task = opentaskpy.otflogging._define_log_file_name(
        "fail-command", "E"
    )

    # Check that all exist, with the right status
    assert os.path.exists(log_file_name_batch.replace("_running", "_failed"))
    assert os.path.exists(log_file_name_touch_task.replace("_running", ""))
    assert os.path.exists(log_file_name_failed_task.replace("_running", "_failed"))


def test_batch_resume_after_failure(setup_ssh_keys, env_vars, root_dir, clear_logs):
    task_id = f"parallel-single-failure-1-{RANDOM}"
    # Ensure there are no logs for this batch
    shutil.rmtree(
        f"{opentaskpy.otflogging.LOG_DIRECTORY}/{task_id}", ignore_errors=True
    )

    config_loader = ConfigLoader("test/cfg")
    batch_obj = batch.Batch(
        None,
        task_id,
        parallel_batch_with_single_failure_definition,
        config_loader,
    )
    # Run and expect a false status
    assert not batch_obj.run()

    # Validate that a log has been created with the correct status
    # Use the logging module to get the right log file name
    log_file_name_batch = opentaskpy.otflogging._define_log_file_name(task_id, "B")
    log_file_name_touch_task = opentaskpy.otflogging._define_log_file_name("touch", "E")
    log_file_name_failed_task = opentaskpy.otflogging._define_log_file_name(
        "fail-command", "E"
    )

    # Check that all exist, with the right status
    assert os.path.exists(log_file_name_batch.replace("_running", "_failed"))
    assert os.path.exists(log_file_name_touch_task.replace("_running", ""))
    assert os.path.exists(log_file_name_failed_task.replace("_running", "_failed"))

    # Reset the prefix so it doesn't get reused
    del os.environ["OTF_LOG_RUN_PREFIX"]

    # Run it again, but this time, expect it to only run the failed task
    batch_obj = batch.Batch(
        None,
        task_id,
        parallel_batch_with_single_failure_definition,
        config_loader,
    )

    # Check the task_order_tree to only have the failed task in a NOT_STARTED state
    assert batch_obj.task_order_tree[1]["status"] == "COMPLETED"
    assert batch_obj.task_order_tree[2]["status"] == "NOT_STARTED"

    # Run and expect a false status
    assert not batch_obj.run()

    # Validate that the touch task has been skipped, so there's no log file
    log_file_name_batch = opentaskpy.otflogging._define_log_file_name(task_id, "B")
    log_file_name_touch_task = opentaskpy.otflogging._define_log_file_name("touch", "E")
    log_file_name_failed_task = opentaskpy.otflogging._define_log_file_name(
        "fail-command", "E"
    )

    # Check that all exist, with the right status
    assert os.path.exists(log_file_name_batch.replace("_running", "_failed"))
    assert not os.path.exists(log_file_name_touch_task)
    assert os.path.exists(log_file_name_failed_task.replace("_running", "_failed"))


def test_batch_resume_after_failure_retry_successful_tasks(
    setup_ssh_keys, env_vars, root_dir, clear_logs
):
    task_id = f"parallel-single-failure-2-{RANDOM}"
    # Ensure there are no logs for this batch
    shutil.rmtree(
        f"{opentaskpy.otflogging.LOG_DIRECTORY}/{task_id}", ignore_errors=True
    )

    config_loader = ConfigLoader("test/cfg")
    batch_obj = batch.Batch(
        None,
        task_id,
        parallel_batch_with_single_failure_with_retry_definition,
        config_loader,
    )
    # Run and expect a false status
    assert not batch_obj.run()

    # Validate that a log has been created with the correct status
    # Use the logging module to get the right log file name
    log_file_name_batch = opentaskpy.otflogging._define_log_file_name(task_id, "B")
    log_file_name_touch_task = opentaskpy.otflogging._define_log_file_name("touch", "E")
    log_file_name_failed_task = opentaskpy.otflogging._define_log_file_name(
        "fail-command", "E"
    )

    # Check that all exist, with the right status
    assert os.path.exists(log_file_name_batch.replace("_running", "_failed"))
    assert os.path.exists(log_file_name_touch_task.replace("_running", ""))
    assert os.path.exists(log_file_name_failed_task.replace("_running", "_failed"))

    # Reset the prefix so it doesn't get reused
    del os.environ["OTF_LOG_RUN_PREFIX"]

    # Run it again, but this time, expect it to only run the failed task
    batch_obj = batch.Batch(
        None,
        task_id,
        parallel_batch_with_single_failure_with_retry_definition,
        config_loader,
    )

    # Check the task_order_tree to check both tasks have a NOT_STARTED state
    assert batch_obj.task_order_tree[1]["status"], "NOT_STARTED"
    assert batch_obj.task_order_tree[2]["status"], "NOT_STARTED"

    # Run and expect a false status
    assert not batch_obj.run()

    # Validate that the touch task has been skipped, so there's no log file
    log_file_name_batch = opentaskpy.otflogging._define_log_file_name(task_id, "B")
    log_file_name_touch_task = opentaskpy.otflogging._define_log_file_name("touch", "E")
    log_file_name_failed_task = opentaskpy.otflogging._define_log_file_name(
        "fail-command", "E"
    )

    # Check that all exist, with the right status
    assert os.path.exists(log_file_name_batch.replace("_running", "_failed"))
    assert os.path.exists(log_file_name_touch_task.replace("_running", ""))
    assert os.path.exists(log_file_name_failed_task.replace("_running", "_failed"))


def test_batch_parallel_many(setup_ssh_keys, env_vars, root_dir, clear_logs):
    # Forcing a prefix makes it easy to identify log files, as well as
    # ensuring that any rerun logic doesn't get hit
    os.environ["OTF_LOG_RUN_PREFIX"] = f"testbatch_many_parallel_{RANDOM}"

    config_loader = ConfigLoader("test/cfg")
    batch_obj = batch.Batch(
        None, f"parallel-many-{RANDOM}", parallel_batch_many_definition, config_loader
    )
    # Run and expect a true status
    assert batch_obj.run()


def test_batch_continue_on_failure(setup_ssh_keys, env_vars, root_dir, clear_logs):
    task_id = f"dependency-continue-on-fail-1-{RANDOM}"
    # Ensure there are no logs for this batch
    shutil.rmtree(
        f"{opentaskpy.otflogging.LOG_DIRECTORY}/{task_id}", ignore_errors=True
    )

    config_loader = ConfigLoader("test/cfg")
    batch_obj = batch.Batch(
        None,
        task_id,
        dependent_batch_continue_on_fail_definition,
        config_loader,
    )
    # Run and expect a false status
    assert not batch_obj.run()

    # Validate that a log has been created with the correct status
    # Use the logging module to get the right log file name
    log_file_name_batch = opentaskpy.otflogging._define_log_file_name(task_id, "B")
    log_file_name_fail_task = opentaskpy.otflogging._define_log_file_name(
        "fail-command", "E"
    )
    log_file_name_scp_task = opentaskpy.otflogging._define_log_file_name(
        "scp-basic", "T"
    )

    # Check that all exist, with the right status
    assert os.path.exists(log_file_name_batch.replace("_running", "_failed"))

    # The failed task that we continue on, should still have a failed log
    assert os.path.exists(log_file_name_fail_task.replace("_running", "_failed"))

    # The successful task should have a successful
    assert os.path.exists(log_file_name_scp_task.replace("_running", ""))


def test_batch_task_id_failed_dependencies(root_dir, env_vars, clear_logs):

    # We need a config loader object, so that the batch class can load in the configs for
    # the sub tasks
    config_loader = ConfigLoader("test/cfg")
    # Expect a FileNotFoundError as the task_id is non-existent
    batchObj = batch.Batch(
        None, f"fail-{RANDOM}", fail_batch_definition_dependencies, config_loader
    )

    assert not batchObj.run()


def test_batch_check_all_dependencies_fail():
    batch_task = {
        "task_id": "test-batch-deps-checker",
        "batch_task_spec": {"order_id": 1, "task_id": "sleep-5-local"},
        "task": {"type": "execution", "directory": "/tmp", "command": "sleep 5"},
    }
    assert not batch.Batch.check_all_dependency_statuses(
        None, batch_task, ["COMPLETED"]
    )


@pytest.fixture
def no_thread_sleep():
    """Temporarily set OTF_NO_THREAD_SLEEP for testing."""
    old_value = os.environ.get("OTF_NO_THREAD_SLEEP")
    os.environ["OTF_NO_THREAD_SLEEP"] = "1"
    yield
    if old_value is None:
        del os.environ["OTF_NO_THREAD_SLEEP"]
    else:
        os.environ["OTF_NO_THREAD_SLEEP"] = old_value


def test_batch_concurrent_protocol_imports(
    env_vars, root_dir, clear_logs, no_thread_sleep
):
    """Test concurrent protocol imports don't cause partial initialization errors."""
    # Create a batch with multiple transfers using the same protocol
    concurrent_protocol_batch = {
        "type": "batch",
        "tasks": [{"order_id": i, "task_id": "df-local"} for i in range(1, 6)],
    }

    config_loader = ConfigLoader("test/cfg")
    batch_obj = batch.Batch(
        None, f"concurrent-protocols-{RANDOM}", concurrent_protocol_batch, config_loader
    )

    # This should complete without partial initialization errors
    assert batch_obj.run()

    # Verify all tasks completed
    for i in range(1, 6):
        assert batch_obj.task_order_tree[i]["status"] == "COMPLETED"


def test_protocol_cache_reuse(env_vars, root_dir, clear_logs):
    """Test that protocol classes are properly cached and reused."""
    # Run two batches sequentially using the same protocol
    config_loader = ConfigLoader("test/cfg")

    # First batch
    batch1 = batch.Batch(
        None,
        f"cache-test-1-{RANDOM}",
        {"type": "batch", "tasks": [{"order_id": 1, "task_id": "df-local"}]},
        config_loader,
    )
    assert batch1.run()

    # Second batch
    batch2 = batch.Batch(
        None,
        f"cache-test-2-{RANDOM}",
        {"type": "batch", "tasks": [{"order_id": 1, "task_id": "df-local"}]},
        config_loader,
    )
    assert batch2.run()

    # The second batch should use the cached protocol class
    # This can be verified through logs, but we're mainly ensuring no errors occur


def test_batch_log_memory_usage(
    env_vars, root_dir, clear_logs, no_thread_sleep, caplog
):
    """Test that OTF_LOG_MEMORY_USAGE causes RSS memory to be logged each poll cycle."""
    import logging

    old_value = os.environ.get("OTF_LOG_MEMORY_USAGE")
    os.environ["OTF_LOG_MEMORY_USAGE"] = "1"
    # Use a fast poll interval so the test doesn't wait on the default 5s
    old_poll = os.environ.get("OTF_BATCH_POLL_INTERVAL")
    os.environ["OTF_BATCH_POLL_INTERVAL"] = "0.1"
    try:
        mem_batch = {
            "type": "batch",
            "tasks": [{"order_id": i, "task_id": "df-local"} for i in range(1, 4)],
        }
        config_loader = ConfigLoader("test/cfg")
        batch_obj = batch.Batch(None, f"mem-log-{RANDOM}", mem_batch, config_loader)

        with caplog.at_level(logging.INFO):
            result = batch_obj.run()

        assert result, "Batch should complete successfully"

        memory_log_lines = [
            r.message for r in caplog.records if "[memory] RSS:" in r.message
        ]
        assert len(memory_log_lines) > 0, (
            "Expected at least one '[memory] RSS:' log entry when OTF_LOG_MEMORY_USAGE=1, "
            f"but none were found. All log messages: {[r.message for r in caplog.records]}"
        )
        # Each entry should contain a positive numeric MB value — a value of -1.0
        # means psutil was not importable, which is a missing-dependency error.
        import re

        for line in memory_log_lines:
            assert re.search(
                r"\[memory\] RSS: \d+\.\d+ MB", line
            ), f"Memory log line has unexpected format: {line!r}"
            rss_value = float(re.search(r"\[memory\] RSS: ([\d.]+) MB", line).group(1))
            assert rss_value > 0, (
                f"RSS value is {rss_value} MB — a value of -1.0 means psutil is not "
                "installed. Add 'psutil' to the project dependencies."
            )
    finally:
        if old_value is None:
            os.environ.pop("OTF_LOG_MEMORY_USAGE", None)
        else:
            os.environ["OTF_LOG_MEMORY_USAGE"] = old_value
        if old_poll is None:
            os.environ.pop("OTF_BATCH_POLL_INTERVAL", None)
        else:
            os.environ["OTF_BATCH_POLL_INTERVAL"] = old_poll


def test_batch_timeout_can_complete_if_kill_does_not_interrupt(
    env_vars, root_dir, clear_logs, no_thread_sleep
):
    class SlowSuccessfulTaskHandler:
        def __init__(self):
            self.task_id = "slow-success"

        def run(self, kill_event=None):
            time.sleep(0.2)
            return True

    old_poll = os.environ.get("OTF_BATCH_POLL_INTERVAL")
    os.environ["OTF_BATCH_POLL_INTERVAL"] = "0.01"
    try:
        config_loader = ConfigLoader("test/cfg")
        batch_obj = batch.Batch(
            None,
            f"timeout-success-{RANDOM}",
            basic_batch_definition,
            config_loader,
        )
        batch_obj.task_order_tree = {
            1: {
                "task_id": "slow-success",
                "batch_task_spec": {"order_id": 1, "task_id": "slow-success"},
                "task": {"type": "execution"},
                "task_handler": SlowSuccessfulTaskHandler(),
                "timeout": 0.05,
                "continue_on_fail": False,
                "retry_on_rerun": False,
                "status": "NOT_STARTED",
                "result": None,
            }
        }

        assert batch_obj.run()
        assert batch_obj.task_order_tree[1]["status"] == "COMPLETED"
        assert batch_obj.task_order_tree[1]["result"] is True
        assert batch_obj.task_order_tree[1]["kill_event"].is_set()
    finally:
        if old_poll is None:
            os.environ.pop("OTF_BATCH_POLL_INTERVAL", None)
        else:
            os.environ["OTF_BATCH_POLL_INTERVAL"] = old_poll
