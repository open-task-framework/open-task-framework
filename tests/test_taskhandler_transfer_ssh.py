# pylint: skip-file
# ruff: noqa
import os
from copy import deepcopy
from datetime import datetime

import pytest
from paramiko.ssh_exception import SSHException
from pytest_shell import fs

from opentaskpy import exceptions
from opentaskpy.taskhandlers import transfer
from tests.fixtures.ssh_clients import *  # noqa: F403, F401

os.environ["OTF_NO_LOG"] = "1"
os.environ["OTF_LOG_LEVEL"] = "DEBUG"

# Create a task definition
scp_task_definition = {
    "type": "transfer",
    "source": {
        "hostname": "172.16.0.11",
        "directory": "/tmp/testFiles/src",
        "fileRegex": ".*taskhandler.*\\.txt",
        "protocol": {"name": "ssh", "credentials": {"username": "application"}},
    },
    "destination": [
        {
            "hostname": "172.16.0.12",
            "directory": "/tmp/testFiles/dest",
            "protocol": {"name": "ssh", "credentials": {"username": "application"}},
        },
    ],
}


scp_task_definition_no_permissions = {
    "type": "transfer",
    "source": {
        "hostname": "172.16.0.11",
        "directory": "/tmp/testFiles/src",
        "fileRegex": ".*taskhandler.*\\.txt",
        "protocol": {"name": "ssh", "credentials": {"username": "application"}},
    },
    "destination": [
        {
            "hostname": "172.16.0.12",
            "directory": "/etc",
            "rename": {
                "pattern": ".*taskhandler.*\\.txt",
                "sub": "passwd",
            },
            "protocol": {"name": "ssh", "credentials": {"username": "application"}},
        },
    ],
}

scp_file_watch_task_no_error_definition = {
    "type": "transfer",
    "source": {
        "hostname": "172.16.0.11",
        "directory": "/tmp/testFiles/src",
        "fileRegex": ".*nofileexists.*\\.txt",
        "fileWatch": {"timeout": 1},
        "error": False,
        "protocol": {"name": "ssh", "credentials": {"username": "application"}},
    },
}

scp_with_fin_task_definition = {
    "type": "transfer",
    "source": {
        "hostname": "172.16.0.11",
        "directory": "/tmp/testFiles/src",
        "fileRegex": ".*taskhandler.fin.*\\.txt",
        "protocol": {"name": "ssh", "credentials": {"username": "application"}},
    },
    "destination": [
        {
            "hostname": "172.16.0.12",
            "directory": "/tmp/testFiles/dest",
            "flags": {
                "fullPath": "/tmp/testFiles/dest/scp_with_fin.fin",
            },
            "protocol": {"name": "ssh", "credentials": {"username": "application"}},
        },
    ],
}

# PCA move
scp_pca_move_task_definition_1 = {
    "type": "transfer",
    "source": {
        "hostname": "172.16.0.11",
        "directory": "/tmp/testFiles/src",
        "fileRegex": "pca_move\\.txt",
        "protocol": {"name": "ssh", "credentials": {"username": "application"}},
        "postCopyAction": {
            "action": "move",
            "destination": "/tmp/testFiles/archive",
        },
    },
    "destination": [
        {
            "hostname": "172.16.0.12",
            "directory": "/tmp/testFiles/dest",
            "protocol": {"name": "ssh", "credentials": {"username": "application"}},
        },
    ],
}

scp_pca_move_task_definition_2 = {
    "type": "transfer",
    "source": {
        "hostname": "172.16.0.11",
        "directory": "/tmp/testFiles/src",
        "fileRegex": "pca_move_2\\.txt",
        "protocol": {"name": "ssh", "credentials": {"username": "application"}},
        "postCopyAction": {
            "action": "move",
            "destination": "/tmp/testFiles/archive/",
        },
    },
    "destination": [
        {
            "hostname": "172.16.0.12",
            "directory": "/tmp/testFiles/dest",
            "protocol": {"name": "ssh", "credentials": {"username": "application"}},
        },
    ],
}

scp_pca_invalid_move_task_definition = {
    "type": "transfer",
    "source": {
        "hostname": "172.16.0.11",
        "directory": "/tmp/testFiles/src",
        "fileRegex": "pca_move_3\\.txt",
        "protocol": {"name": "ssh", "credentials": {"username": "application"}},
        "postCopyAction": {
            "action": "move",
            "destination": "/tmp/testFiles/archive/pca_move_bad.txt",
        },
    },
    "destination": [
        {
            "hostname": "172.16.0.12",
            "directory": "/tmp/testFiles/dest",
            "protocol": {"name": "ssh", "credentials": {"username": "application"}},
        },
    ],
}

scp_pca_rename_task_definition_1 = {
    "type": "transfer",
    "source": {
        "hostname": "172.16.0.11",
        "directory": "/tmp/testFiles/src",
        "fileRegex": "pca_rename_1\\.txt",
        "protocol": {"name": "ssh", "credentials": {"username": "application"}},
        "postCopyAction": {
            "action": "rename",
            "destination": "/tmp/testFiles/archive/",
            "pattern": "rename",
            "sub": "renamed",
        },
    },
    "destination": [
        {
            "hostname": "172.16.0.12",
            "directory": "/tmp/testFiles/dest",
            "protocol": {"name": "ssh", "credentials": {"username": "application"}},
        },
    ],
}

scp_pca_rename_many_task_definition_1 = {
    "type": "transfer",
    "source": {
        "hostname": "172.16.0.11",
        "directory": "/tmp/testFiles/src",
        "fileRegex": "pca_rename_many.*\\.txt",
        "protocol": {"name": "ssh", "credentials": {"username": "application"}},
        "postCopyAction": {
            "action": "rename",
            "destination": "/tmp/testFiles/archive/",
            "pattern": "rename",
            "sub": "renamed",
        },
    },
    "destination": [
        {
            "hostname": "172.16.0.12",
            "directory": "/tmp/testFiles/dest",
            "protocol": {"name": "ssh", "credentials": {"username": "application"}},
        },
    ],
}

# Proxy task definition
scp_proxy_task_definition = {
    "type": "transfer",
    "source": {
        "hostname": "172.16.0.11",
        "directory": "/tmp/testFiles/src",
        "fileRegex": ".*taskhandler.proxy\\.txt",
        "protocol": {"name": "ssh", "credentials": {"username": "application"}},
    },
    "destination": [
        {
            "hostname": "172.16.0.12",
            "transferType": "proxy",
            "directory": "/tmp/testFiles/dest",
            "protocol": {"name": "ssh", "credentials": {"username": "application"}},
        },
    ],
}

scp_mixed_proxy_task_definition = {
    "type": "transfer",
    "source": {
        "hostname": "172.16.0.11",
        "directory": "/tmp/testFiles/src",
        "fileRegex": ".*taskhandler.proxy.mixed\\.txt",
        "protocol": {"name": "ssh", "credentials": {"username": "application"}},
    },
    "destination": [
        {
            "hostname": "172.16.0.22",
            "directory": "/home/application/testFiles/dest",
            "rename": {
                "pattern": "^(.*)\\.txt$",
                "sub": "\\1-sftp.txt",
            },
            "protocol": {"name": "sftp", "credentials": {"username": "application"}},
        },
        {
            "hostname": "172.16.0.12",
            "transferType": "proxy",
            "directory": "/tmp/testFiles/dest",
            "rename": {
                "pattern": "^(.*)\\.txt$",
                "sub": "\\1-ssh-1.txt",
            },
            "protocol": {"name": "ssh", "credentials": {"username": "application"}},
        },
        {
            "hostname": "172.16.0.12",
            "transferType": "proxy",
            "directory": "/tmp/testFiles/dest",
            "rename": {
                "pattern": "^(.*)\\.txt$",
                "sub": "\\1-ssh-2.txt",
            },
            "protocol": {"name": "ssh", "credentials": {"username": "application"}},
        },
    ],
}

scp_destination_file_rename = {
    "type": "transfer",
    "source": {
        "hostname": "172.16.0.11",
        "directory": "/tmp/testFiles/src",
        "fileRegex": "dest_rename.*taskhandler.*\\.txt",
        "protocol": {"name": "ssh", "credentials": {"username": "application"}},
    },
    "destination": [
        {
            "hostname": "172.16.0.12",
            "directory": "/tmp/testFiles/dest",
            "rename": {
                "pattern": "t(askha)ndler",
                "sub": "T\\1NDLER",
            },
            "protocol": {"name": "ssh", "credentials": {"username": "application"}},
        },
    ],
}

fail_invalid_protocol_task_definition = {
    "type": "transfer",
    "source": {
        "hostname": "172.16.0.11",
        "directory": "/tmp/testFiles/src",
        "fileRegex": ".*taskhandler.*\\.txt",
        "protocol": {"name": "nonexistent"},
    },
}

# Count conditional tests
scp_task_with_counts = {
    "type": "transfer",
    "source": {
        "hostname": "172.16.0.11",
        "directory": "/tmp/testFiles/src",
        "fileRegex": "counts[0-9]\\.txt",
        "conditionals": {
            "count": {
                "minCount": 2,
                "maxCount": 2,
            },
        },
        "protocol": {"name": "ssh", "credentials": {"username": "application"}},
    },
    "destination": [
        {
            "hostname": "172.16.0.12",
            "directory": "/tmp/testFiles/dest",
            "protocol": {"name": "ssh", "credentials": {"username": "application"}},
        },
    ],
}

scp_file_watch_task_with_counts = {
    "type": "transfer",
    "source": {
        "hostname": "172.16.0.11",
        "directory": "/tmp/testFiles/src",
        "fileRegex": "counts_watch[0-9]\\.txt",
        "fileWatch": {"timeout": 5},
        "conditionals": {
            "count": {
                "minCount": 2,
                "maxCount": 2,
            },
            "checkDuringFilewatch": True,
        },
        "protocol": {"name": "ssh", "credentials": {"username": "application"}},
    },
    "destination": [
        {
            "hostname": "172.16.0.12",
            "directory": "/tmp/testFiles/dest",
            "protocol": {"name": "ssh", "credentials": {"username": "application"}},
        },
    ],
}


def test_invalid_protocol():
    transfer_obj = transfer.Transfer(
        None, "invalid-protocol", fail_invalid_protocol_task_definition
    )
    # Expect a UnknownProtocolError exception
    with pytest.raises(exceptions.UnknownProtocolError):
        transfer_obj._set_remote_handlers()

    # Try one with a longer protocol name
    fail_invalid_protocol_task_definition["source"]["protocol"][
        "name"
    ] = "some.module.path.ProtocolClass"
    transfer_obj = transfer.Transfer(
        None, "invalid-protocol", fail_invalid_protocol_task_definition
    )
    # Expect a UnknownProtocolError exception
    with pytest.raises(exceptions.UnknownProtocolError):
        transfer_obj._set_remote_handlers()


def test_remote_handler(setup_ssh_keys):
    # Validate that given a transfer with ssh protocol, that we get a remote handler of type SSH

    transfer_obj = transfer.Transfer(None, "scp-basic", scp_task_definition)

    transfer_obj._set_remote_handlers()

    # Validate some things were set as expected
    assert transfer_obj.source_remote_handler.__class__.__name__ == "SSHTransfer"

    # dest_remote_handler should be an array
    assert isinstance(transfer_obj.dest_remote_handlers, list)
    assert len(transfer_obj.dest_remote_handlers) == 1
    #  of SSHTransfer objects
    assert transfer_obj.dest_remote_handlers[0].__class__.__name__ == "SSHTransfer"


def test_scp_basic(root_dir, setup_ssh_keys):
    # Create a test file
    fs.create_files(
        [
            {
                f"{root_dir}/testFiles/ssh_1/src/test.taskhandler.txt": {
                    "content": "test1234"
                }
            }
        ]
    )

    # Create a transfer object
    transfer_obj = transfer.Transfer(None, "scp-basic", scp_task_definition)

    # Run the transfer and expect a true status
    assert transfer_obj.run()
    # Check the destination file exists
    assert os.path.exists(f"{root_dir}/testFiles/ssh_2/dest/test.taskhandler.txt")


def test_ssh_basic_host_key_validation(root_dir, setup_ssh_keys):
    # Run the above test again, but this time with host key validation
    ssh_validation_task_definition = deepcopy(scp_task_definition)
    ssh_validation_task_definition["source"]["fileRegex"] = ".*hostValidation.*\\.txt"
    ssh_validation_task_definition["source"]["protocol"]["hostKeyValidation"] = True
    ssh_validation_task_definition["destination"][0]["protocol"][
        "hostKeyValidation"
    ] = True

    # Create a test file
    fs.create_files(
        [
            {
                f"{root_dir}/testFiles/ssh_1/src/test.hostValidation.txt": {
                    "content": "test1234"
                }
            }
        ]
    )

    print("Running test")
    # Delete the known hosts file if it exists
    user_home = os.path.expanduser("~")
    known_hosts_file = f"{user_home}/.ssh/known_hosts"
    if os.path.exists(known_hosts_file):
        os.remove(known_hosts_file)

    print("Running first transfer")

    transfer_obj = transfer.Transfer(
        None, "ssh-host-key-validation", ssh_validation_task_definition
    )

    # Run the execution and expect a false status
    with pytest.raises(SSHException):
        transfer_obj.run()

    print("Done first transfer")

    # SSH onto the host manually and accept the host key so it's saved to the system known hosts
    cmd = "ssh -o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=1 application@172.16.0.11 echo 'test'; ssh -o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=1 application@172.16.0.12 echo 'test' "
    result = subprocess.run(cmd, shell=True, capture_output=True)

    print("Done SSH")

    # Now rerun the execution, but this time it should work
    assert transfer_obj.run()

    print("Done second transfer")

    # Move the known host file elsewhere and pass the new location to the protocol definition
    known_hosts_file = f"{user_home}/.ssh/known_hosts"
    new_known_hosts_file = f"{user_home}/known_hosts.new"
    os.rename(known_hosts_file, new_known_hosts_file)

    ssh_validation_task_definition["source"]["protocol"][
        "knownHostsFile"
    ] = new_known_hosts_file
    ssh_validation_task_definition["destination"][0]["protocol"][
        "knownHostsFile"
    ] = new_known_hosts_file

    transfer_obj = transfer.Transfer(
        None, "ssh-host-key-validation", ssh_validation_task_definition
    )

    # Run the execution and expect a false status
    assert transfer_obj.run()


def test_scp_basic_ultra_debug(root_dir, setup_ssh_keys):
    # Create a test file
    fs.create_files(
        [
            {
                f"{root_dir}/testFiles/ssh_1/src/test.taskhandler.txt": {
                    "content": "test1234"
                }
            }
        ]
    )

    # Create a transfer object
    transfer_obj = transfer.Transfer(None, "scp-basic", scp_task_definition)

    # Set the OTF_PARAMIKO_ULTRA_DEBUG environment variable
    os.environ["OTF_PARAMIKO_ULTRA_DEBUG"] = "1"

    # Run the transfer and expect a true status
    assert transfer_obj.run()
    # Check the destination file exists
    assert os.path.exists(f"{root_dir}/testFiles/ssh_2/dest/test.taskhandler.txt")


def test_scp_basic_key_from_protocol_definition(root_dir, ssh_key_file):
    # Create a test file
    fs.create_files(
        [
            {
                f"{root_dir}/testFiles/ssh_1/src/test.taskhandler.txt": {
                    "content": "test1234"
                }
            }
        ]
    )

    # Create a transfer object
    scp_task_definition_copy = deepcopy(scp_task_definition)
    scp_task_definition_copy["source"]["protocol"]["credentials"]["key"] = ssh_key_file
    transfer_obj = transfer.Transfer(None, "scp-basic", scp_task_definition_copy)

    # Run the transfer and expect a true status
    assert transfer_obj.run()
    # Check the destination file exists
    assert os.path.exists(f"{root_dir}/testFiles/ssh_2/dest/test.taskhandler.txt")


def test_scp_basic_create_dest_dir(root_dir, setup_ssh_keys):
    # Create a test file
    fs.create_files(
        [
            {
                f"{root_dir}/testFiles/ssh_1/src/test.taskhandler.txt": {
                    "content": "test1234"
                }
            }
        ]
    )

    # Create a transfer object
    scp_task_definition_copy = deepcopy(scp_task_definition)
    scp_task_definition_copy["destination"][0][
        "directory"
    ] = f"/tmp/testFiles/{datetime.now().strftime('%s')}"
    scp_task_definition_copy["destination"][0]["createDirectoryIfNotExists"] = True
    transfer_obj = transfer.Transfer(None, "scp-basic", scp_task_definition_copy)

    # Run the transfer and expect a true status
    assert transfer_obj.run()
    # Check the destination file exists
    assert os.path.exists(f"{root_dir}/testFiles/ssh_2/dest/test.taskhandler.txt")


def test_scp_basic_no_permissions(root_dir, setup_ssh_keys):
    # Create a test file
    fs.create_files(
        [
            {
                f"{root_dir}/testFiles/ssh_1/src/test.taskhandler.txt": {
                    "content": "test1234"
                }
            }
        ]
    )

    # Create a transfer object
    transfer_obj = transfer.Transfer(
        None, "scp-basic-no-permissions", scp_task_definition_no_permissions
    )

    # Run the transfer and expect a true status
    with pytest.raises(exceptions.RemoteTransferError):
        transfer_obj.run()


def test_scp_filewatch_no_error(setup_ssh_keys):
    # Create a transfer object
    transfer_obj = transfer.Transfer(
        None, "scp-no-file-no-error", scp_file_watch_task_no_error_definition
    )

    # Run the transfer and expect a true status
    assert transfer_obj.run()


def test_scp_basic_write_fin(root_dir, setup_ssh_keys):
    # Delete any fin files that exist
    for file in os.listdir(f"{root_dir}/testFiles/ssh_2/dest"):
        if file.endswith(".fin"):
            os.remove(f"{root_dir}/testFiles/ssh_2/dest/{file}")

    # Create a test file
    fs.create_files(
        [
            {
                f"{root_dir}/testFiles/ssh_1/src/test.taskhandler.fin.txt": {
                    "content": "test1234"
                }
            }
        ]
    )

    # Create a transfer object
    transfer_obj = transfer.Transfer(None, "scp-basic", scp_with_fin_task_definition)

    # Run the transfer and expect a true status
    assert transfer_obj.run()
    # Check the destination file exists
    assert os.path.exists(f"{root_dir}/testFiles/ssh_2/dest/test.taskhandler.fin.txt")

    # Check the fin file exists
    assert os.path.exists(f"{root_dir}/testFiles/ssh_2/dest/scp_with_fin.fin")


def test_pca_move(root_dir, setup_ssh_keys):
    # Empty the PCA archive directory
    for file in os.listdir(f"{root_dir}/testFiles/ssh_1/archive"):
        os.remove(f"{root_dir}/testFiles/ssh_1/archive/{file}")

    # Create the test file
    fs.create_files(
        [{f"{root_dir}/testFiles/ssh_1/src/pca_move.txt": {"content": "test1234"}}]
    )
    # Create a transfer object
    transfer_obj = transfer.Transfer(
        None, "scp-pca-move", scp_pca_move_task_definition_1
    )

    # Run the transfer and expect a true status
    assert transfer_obj.run()
    # Check the destination file exists
    assert os.path.exists(f"{root_dir}/testFiles/ssh_2/dest/pca_move.txt")
    # Check the source file no longer exists
    assert not os.path.exists(f"{root_dir}/testFiles/ssh_1/src/pca_move.txt")

    # Check the source file has been archived
    assert os.path.exists(f"{root_dir}/testFiles/ssh_1/archive/pca_move.txt")

    # Create the next test file
    fs.create_files(
        [{f"{root_dir}/testFiles/ssh_1/src/pca_move_2.txt": {"content": "test1234"}}]
    )
    transfer_obj = transfer.Transfer(
        None, "scp-pca-move-2", scp_pca_move_task_definition_2
    )

    # Run the transfer and expect a true status
    assert transfer_obj.run()

    # Check the destination file exists
    assert os.path.exists(f"{root_dir}/testFiles/ssh_2/dest/pca_move_2.txt")
    # Check the source file no longer exists
    assert not os.path.exists(f"{root_dir}/testFiles/ssh_1/src/pca_move_2.txt")

    # Check the source file has been archived
    assert os.path.exists(f"{root_dir}/testFiles/ssh_1/archive/pca_move_2.txt")

    fs.create_files(
        [{f"{root_dir}/testFiles/ssh_1/src/pca_move_3.txt": {"content": "test1234"}}]
    )
    transfer_obj = transfer.Transfer(
        None, "scp-pca-move-invalid", scp_pca_invalid_move_task_definition
    )

    # Run the transfer and expect a true status
    with pytest.raises(exceptions.RemoteTransferError):
        transfer_obj.run()
    # Check the destination file exists
    assert os.path.exists(f"{root_dir}/testFiles/ssh_2/dest/pca_move_3.txt")
    # Check the source file should still exist
    assert os.path.exists(f"{root_dir}/testFiles/ssh_1/src/pca_move_3.txt")

    # Check the source file has not been archived
    assert not os.path.exists(f"{root_dir}/testFiles/ssh_1/archive/pca_move_bad.txt")


def test_destination_file_rename(root_dir, setup_ssh_keys):
    # Random number
    import random

    random_no = random.randint(1, 1000)

    # Create the test file
    fs.create_files(
        [
            {
                f"{root_dir}/testFiles/ssh_1/src/dest_rename_{random_no}_taskhandler.txt": {
                    "content": "test1234"
                }
            }
        ]
    )
    # Create a transfer object
    transfer_obj = transfer.Transfer(
        None, "scp-dest-rename", scp_destination_file_rename
    )

    # Run the transfer and expect a true status
    assert transfer_obj.run()
    # Check the destination file exists
    assert os.path.exists(
        f"{root_dir}/testFiles/ssh_2/dest/dest_rename_{random_no}_TaskhaNDLER.txt"
    )


def test_pca_rename(root_dir, setup_ssh_keys):
    # Empty the PCA archive directory
    for file in os.listdir(f"{root_dir}/testFiles/ssh_1/archive"):
        os.remove(f"{root_dir}/testFiles/ssh_1/archive/{file}")

    # Create the test file
    fs.create_files(
        [{f"{root_dir}/testFiles/ssh_1/src/pca_rename_1.txt": {"content": "test1234"}}]
    )
    # Create a transfer object
    transfer_obj = transfer.Transfer(
        None, "scp-pca-rename", scp_pca_rename_task_definition_1
    )

    # Run the transfer and expect a true status
    assert transfer_obj.run()
    # Check the destination file exists
    assert os.path.exists(f"{root_dir}/testFiles/ssh_2/dest/pca_rename_1.txt")
    # Check the source file no longer exists
    assert not os.path.exists(f"{root_dir}/testFiles/ssh_1/src/pca_rename_1.txt")

    # Check the source file has been archived
    assert os.path.exists(f"{root_dir}/testFiles/ssh_1/archive/pca_renamed_1.txt")


def test_pca_rename_many(root_dir, setup_ssh_keys):
    # Create the test file
    # Empty the PCA archive directory
    for file in os.listdir(f"{root_dir}/testFiles/ssh_1/archive"):
        os.remove(f"{root_dir}/testFiles/ssh_1/archive/{file}")

    # for 1 to 10
    for i in range(1, 10):
        fs.create_files(
            [
                {
                    f"{root_dir}/testFiles/ssh_1/src/pca_rename_many_{i}.txt": {
                        "content": "test1234"
                    }
                }
            ]
        )
    # Create a transfer object
    transfer_obj = transfer.Transfer(
        None, "scp-pca-rename-name", scp_pca_rename_many_task_definition_1
    )

    # Run the transfer and expect a true status
    assert transfer_obj.run()
    # Check the destination file exists
    for i in range(1, 10):
        assert os.path.exists(
            f"{root_dir}/testFiles/ssh_2/dest/pca_rename_many_{i}.txt"
        )
        # Check the source file no longer exists
        assert not os.path.exists(
            f"{root_dir}/testFiles/ssh_1/src/pca_rename_many_{i}.txt"
        )

        # Check the source file has been archived
        assert os.path.exists(
            f"{root_dir}/testFiles/ssh_1/archive/pca_renamed_many_{i}.txt"
        )


def test_scp_proxy(root_dir, setup_ssh_keys):
    # Create a test file
    fs.create_files(
        [
            {
                f"{root_dir}/testFiles/ssh_1/src/test.taskhandler.proxy.txt": {
                    "content": "test1234"
                }
            }
        ]
    )

    # Create a transfer object
    transfer_obj = transfer.Transfer(None, "scp-basic", scp_proxy_task_definition)
    local_staging_dir = transfer_obj.local_staging_dir

    # Run the transfer and expect a true status
    assert transfer_obj.run()
    # Check the destination file exists
    assert os.path.exists(f"{root_dir}/testFiles/ssh_2/dest/test.taskhandler.proxy.txt")

    # Ensure that local files are tidied up
    assert not os.path.exists(local_staging_dir)


def test_scp_proxy_mixed_destinations(root_dir, setup_ssh_keys, setup_sftp_keys):
    import random

    random_no = random.randint(1, 1000)
    expected_content = f"test1234-mixed-proxy-route-{random_no}"
    source_file = f"{root_dir}/testFiles/ssh_1/src/test.taskhandler.proxy.mixed.txt"
    destination_files = [
        f"{root_dir}/testFiles/sftp_2/dest/test.taskhandler.proxy.mixed-sftp.txt",
        f"{root_dir}/testFiles/ssh_2/dest/test.taskhandler.proxy.mixed-ssh-1.txt",
        f"{root_dir}/testFiles/ssh_2/dest/test.taskhandler.proxy.mixed-ssh-2.txt",
    ]

    if os.path.exists(source_file):
        os.remove(source_file)

    for destination_file in destination_files:
        if os.path.exists(destination_file):
            os.remove(destination_file)

    # Create a test file
    fs.create_files([{source_file: {"content": expected_content}}])

    # Create a transfer object
    transfer_obj = transfer.Transfer(None, "scp-basic", scp_mixed_proxy_task_definition)
    local_staging_dir = transfer_obj.local_staging_dir

    # Run the transfer and expect a true status
    assert transfer_obj.run()

    # The first destination uses a different protocol, while the later ssh
    # destinations explicitly force proxy mode. All three should receive the file.
    for destination_file in destination_files:
        assert os.path.exists(destination_file)
        with open(destination_file, "r") as file_handle:
            assert file_handle.read() == expected_content

    # Ensure that local files are tidied up
    assert not os.path.exists(local_staging_dir)


def test_invalid_ssh_decryption_direct():
    # Create a transfer object
    scp_task_definition_copy = deepcopy(scp_task_definition)
    scp_task_definition_copy["source"]["encryption"] = {"decrypt": True}
    transfer_obj = transfer.Transfer(None, "scp-basic", scp_task_definition_copy)

    # Expect a DecryptionNotSupportedError exception
    with pytest.raises(exceptions.DecryptionNotSupportedError):
        transfer_obj.run()


def test_invalid_ssh_encryption_direct():
    # Create a transfer object
    scp_task_definition_copy = deepcopy(scp_task_definition)
    scp_task_definition_copy["destination"][0]["encryption"] = {"encrypt": True}
    transfer_obj = transfer.Transfer(None, "scp-basic", scp_task_definition_copy)

    # Expect a EncryptionNotSupportedError exception
    with pytest.raises(exceptions.EncryptionNotSupportedError):
        transfer_obj.run()


def test_scp_counts(root_dir, setup_ssh_keys):
    # Create a test file
    fs.create_files(
        [
            {f"{root_dir}/testFiles/ssh_1/src/counts1.txt": {"content": "test1234"}},
            {f"{root_dir}/testFiles/ssh_1/src/counts2.txt": {"content": "test1234"}},
        ]
    )

    # Create a transfer object
    transfer_obj = transfer.Transfer(None, "ssh-counts", scp_task_with_counts)

    # Run the transfer and expect a true status
    assert transfer_obj.run()


def test_scp_counts_error(root_dir, setup_ssh_keys):
    # Create a test file
    fs.create_files(
        [
            {
                f"{root_dir}/testFiles/ssh_1/src/counts_error1.txt": {
                    "content": "test1234"
                }
            },
        ]
    )
    scp_task_with_counts_error = deepcopy(scp_task_with_counts)
    scp_task_with_counts_error["source"]["fileRegex"] = "counts_error[0-9]\\.txt"

    # Create a transfer object
    transfer_obj = transfer.Transfer(
        None,
        "ssh-filewatch-counts-error-min",
        scp_task_with_counts_error,
    )
    # Test 1 file < minCount of 2 errors
    # Run the transfer and expect a FilesDoNotMeetConditionsError exception
    with pytest.raises(exceptions.FilesDoNotMeetConditionsError):
        transfer_obj.run()

    fs.create_files(
        [
            {
                f"{root_dir}/testFiles/ssh_1/src/counts_error2.txt": {
                    "content": "test1234"
                }
            },
            {
                f"{root_dir}/testFiles/ssh_1/src/counts_error3.txt": {
                    "content": "test1234"
                }
            },
        ]
    )

    transfer_obj = transfer.Transfer(
        None,
        "ssh-filewatch-counts-error-max",
        scp_task_with_counts_error,
    )
    #  Test 3 files > maxCount of 2 errors
    # Run the transfer and expect a FilesDoNotMeetConditionsError exception
    with pytest.raises(exceptions.FilesDoNotMeetConditionsError):
        transfer_obj.run()


def test_scp_filewatch_counts(root_dir, setup_ssh_keys):
    # Create a test file
    fs.create_files(
        [
            {
                f"{root_dir}/testFiles/ssh_1/src/counts_watch1.txt": {
                    "content": "test1234"
                }
            },
            {
                f"{root_dir}/testFiles/ssh_1/src/counts_watch2.txt": {
                    "content": "test1234"
                }
            },
        ]
    )

    # Create a transfer object
    transfer_obj = transfer.Transfer(
        None, "ssh-filewatch-counts", scp_file_watch_task_with_counts
    )

    # Run the transfer and expect a true status
    assert transfer_obj.run()


def test_scp_filewatch_counts_error(root_dir, setup_ssh_keys):
    # Create a test file
    fs.create_files(
        [
            {
                f"{root_dir}/testFiles/ssh_1/src/counts_watch_error1.txt": {
                    "content": "test1234"
                }
            },
        ]
    )
    scp_file_watch_task_with_counts_error = deepcopy(scp_file_watch_task_with_counts)
    scp_file_watch_task_with_counts_error["source"][
        "fileRegex"
    ] = "counts_watch_error[0-9]\\.txt"

    # Create a transfer object
    transfer_obj = transfer.Transfer(
        None,
        "ssh-filewatch-counts-error-min",
        scp_file_watch_task_with_counts_error,
    )
    # Test 1 file < minCount of 2 errors
    # Run the transfer and expect a RemoteFileNotFoundError exception
    with pytest.raises(exceptions.RemoteFileNotFoundError):
        transfer_obj.run()

    fs.create_files(
        [
            {
                f"{root_dir}/testFiles/ssh_1/src/counts_watch_error2.txt": {
                    "content": "test1234"
                }
            },
            {
                f"{root_dir}/testFiles/ssh_1/src/counts_watch_error3.txt": {
                    "content": "test1234"
                }
            },
        ]
    )

    transfer_obj = transfer.Transfer(
        None,
        "ssh-filewatch-counts-error-max",
        scp_file_watch_task_with_counts_error,
    )
    #  Test 3 files > maxCount of 2 errors
    # Run the transfer and expect a RemoteFileNotFoundError exception
    with pytest.raises(exceptions.RemoteFileNotFoundError):
        transfer_obj.run()
