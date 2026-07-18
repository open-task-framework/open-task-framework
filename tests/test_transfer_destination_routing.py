# pylint: skip-file
# ruff: noqa

from unittest.mock import MagicMock

import pytest

from opentaskpy.taskhandlers import transfer


class RecordingTransferHandler:
    # Small in-memory test double that records which transfer path was chosen.
    def __init__(self, files=None, supports_direct=True):
        self.files = files or {}
        self.supports_direct = supports_direct
        self.list_files_calls = []
        self.pull_files_to_worker_calls = []
        self.transfer_files_calls = []
        self.push_files_from_worker_calls = []
        self.pull_files_calls = []
        self.tidy_calls = 0

    def supports_direct_transfer(self):
        return self.supports_direct

    def list_files(self, directory=None, file_pattern=None):
        self.list_files_calls.append((directory, file_pattern))
        return self.files

    def pull_files_to_worker(self, files, local_staging_directory):
        self.pull_files_to_worker_calls.append((files, local_staging_directory))
        return 0

    def transfer_files(self, files, remote_spec, dest_remote_handler=None):
        self.transfer_files_calls.append((files, remote_spec, dest_remote_handler))
        return 0

    def push_files_from_worker(self, local_staging_directory, file_list=None):
        self.push_files_from_worker_calls.append((local_staging_directory, file_list))
        return 0

    def pull_files(self, files, source_file_spec=None):
        self.pull_files_calls.append((files, source_file_spec))
        return 0

    def move_files_to_final_location(self, files):
        return 0

    def handle_post_copy_action(self, files):
        return 0

    def tidy(self):
        self.tidy_calls += 1


class AlternateRecordingTransferHandler(RecordingTransferHandler):
    # Separate subclass so the transfer handler sees a different remote handler type.
    pass


def build_transfer_with_handlers(
    tmp_path,
    dest_handlers,
    source_protocol_name="local",
    dest_file_specs=None,
):
    # Build the minimum Transfer object needed to exercise the routing logic in
    # Transfer.run() without depending on real SSH/SFTP/local filesystem transfers.
    source_dir = tmp_path / "source"
    source_dir.mkdir()

    source_file = source_dir / "example.txt"
    source_handler = RecordingTransferHandler(files={str(source_file): {}})

    transfer_obj = transfer.Transfer(None, "routing-regression", {})
    transfer_obj.source_file_spec = {
        "directory": str(source_dir),
        "fileRegex": ".*\\.txt",
        "protocol": {"name": source_protocol_name},
    }
    if dest_file_specs is None:
        dest_file_specs = [
            {
                "directory": str(tmp_path / f"dest-{index}"),
                "protocol": {"name": "local"},
            }
            for index, _ in enumerate(dest_handlers)
        ]
    transfer_obj.dest_file_specs = dest_file_specs
    transfer_obj.source_remote_handler = source_handler
    transfer_obj.dest_remote_handlers = dest_handlers
    transfer_obj.local_staging_dir = str(source_dir)
    transfer_obj._set_remote_handlers = lambda: None

    return transfer_obj, source_handler


def test_mixed_destinations_push_from_worker_when_last_destination_differs(tmp_path):
    # Control case: when the final destination is the different handler type, the
    # current implementation correctly stages once and pushes to both destinations.
    same_type_dest = RecordingTransferHandler()
    different_type_dest = AlternateRecordingTransferHandler()

    transfer_obj, source_handler = build_transfer_with_handlers(
        tmp_path, [same_type_dest, different_type_dest]
    )

    assert transfer_obj.run()

    assert len(source_handler.pull_files_to_worker_calls) == 1
    assert len(source_handler.transfer_files_calls) == 0
    assert len(same_type_dest.push_files_from_worker_calls) == 1
    assert len(different_type_dest.push_files_from_worker_calls) == 1


def test_mixed_destinations_push_from_worker_when_last_destination_matches_source(
    tmp_path,
):
    # Regression case from issue #161: reordering the same destinations should not
    # change behavior, but today the earlier mismatched destination is skipped.
    different_type_dest = AlternateRecordingTransferHandler()
    same_type_dest = RecordingTransferHandler()

    transfer_obj, source_handler = build_transfer_with_handlers(
        tmp_path, [different_type_dest, same_type_dest]
    )

    assert transfer_obj.run()

    assert len(source_handler.pull_files_to_worker_calls) == 1
    assert len(source_handler.transfer_files_calls) == 0
    assert len(different_type_dest.push_files_from_worker_calls) == 1
    assert len(same_type_dest.push_files_from_worker_calls) == 1


def test_invalid_transfer_type_warns_and_fails_fast(tmp_path):
    # Defensive case: if a destination somehow reaches runtime with an unsupported
    # transferType, the handler should warn and fail instead of silently claiming a
    # transfer completed.
    same_type_dest = RecordingTransferHandler()

    transfer_obj, _ = build_transfer_with_handlers(tmp_path, [same_type_dest])
    transfer_obj.dest_file_specs[0]["transferType"] = "invalid"
    transfer_obj.logger = MagicMock(wraps=transfer_obj.logger)

    with pytest.raises(Exception) as exc_info:
        transfer_obj.run()

    assert "No valid transfer method available for destination" in str(exc_info.value)
    transfer_obj.logger.warning.assert_called_once()
    assert len(same_type_dest.push_files_from_worker_calls) == 0
    assert len(same_type_dest.pull_files_calls) == 0


def test_proxy_ssh_destinations_override_direct_capability_in_mixed_transfer(
    tmp_path,
):
    # Even when the source handler supports direct transfer, explicit proxy
    # destinations must still route via local staging. Including a different
    # handler type here mirrors the mixed-destination scenario from issue #161.
    first_proxy_ssh_dest = RecordingTransferHandler()
    different_protocol_dest = AlternateRecordingTransferHandler()
    second_proxy_ssh_dest = RecordingTransferHandler()

    transfer_obj, source_handler = build_transfer_with_handlers(
        tmp_path,
        [
            first_proxy_ssh_dest,
            different_protocol_dest,
            second_proxy_ssh_dest,
        ],
        source_protocol_name="ssh",
        dest_file_specs=[
            {
                "hostname": "172.16.0.12",
                "directory": str(tmp_path / "ssh-dest-1"),
                "transferType": "proxy",
                "protocol": {"name": "ssh"},
            },
            {
                "hostname": "172.16.0.13",
                "directory": str(tmp_path / "sftp-dest"),
                "protocol": {"name": "sftp"},
            },
            {
                "hostname": "172.16.0.14",
                "directory": str(tmp_path / "ssh-dest-2"),
                "transferType": "proxy",
                "protocol": {"name": "ssh"},
            },
        ],
    )

    assert transfer_obj.run()

    assert len(source_handler.pull_files_to_worker_calls) == 1
    assert len(source_handler.transfer_files_calls) == 0
    assert len(first_proxy_ssh_dest.push_files_from_worker_calls) == 1
    assert len(different_protocol_dest.push_files_from_worker_calls) == 1
    assert len(second_proxy_ssh_dest.push_files_from_worker_calls) == 1
