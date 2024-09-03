"""
EOF V1 Code Validation tests
"""

import pytest

from ethereum_test_tools import EOFException, EOFTestFiller
from ethereum_test_tools.eof.v1 import Container, Section
from ethereum_test_tools.eof.v1.constants import MAX_INITCODE_SIZE
from ethereum_test_tools.vm.opcode import Opcodes as Op

from .. import EOF_FORK_NAME

REFERENCE_SPEC_GIT_PATH = "EIPS/eip-7480.md"
REFERENCE_SPEC_VERSION = "3ee1334ef110420685f1c8ed63e80f9e1766c251"

pytestmark = pytest.mark.valid_from(EOF_FORK_NAME)

smallest_runtime_subcontainer = Container(
    name="Runtime Subcontainer",
    sections=[
        Section.Code(code=Op.STOP),
    ],
)


@pytest.mark.parametrize(
    "container",
    [
        Container(
            name="empty_data_section",
            sections=[
                Section.Code(
                    code=Op.ADDRESS + Op.POP + Op.STOP,
                ),
                Section.Data(data=""),
            ],
        ),
        Container(
            name="small_data_section",
            sections=[
                Section.Code(
                    code=Op.ADDRESS + Op.POP + Op.STOP,
                ),
                Section.Data(data="1122334455667788" * 4),
            ],
        ),
        Container(
            name="large_data_section",
            sections=[
                Section.Code(
                    code=Op.ADDRESS + Op.POP + Op.STOP,
                ),
                Section.Data(data="1122334455667788" * 3 * 1024),
            ],
        ),
        Container(
            name="max_data_section",
            sections=[
                Section.Code(code=Op.STOP),
                # Hits the 49152 bytes limit for the entire container
                Section.Data(
                    data=b"\x00" * (MAX_INITCODE_SIZE - len(smallest_runtime_subcontainer))
                ),
            ],
        ),
        Container(
            name="DATALOADN_zero",
            sections=[
                Section.Code(
                    code=Op.DATALOADN[0] + Op.POP + Op.STOP,
                ),
                Section.Data(data="1122334455667788" * 16),
            ],
        ),
        Container(
            name="DATALOADN_middle",
            sections=[
                Section.Code(
                    code=Op.DATALOADN[16] + Op.POP + Op.STOP,
                ),
                Section.Data(data="1122334455667788" * 16),
            ],
        ),
        Container(
            name="DATALOADN_edge",
            sections=[
                Section.Code(
                    code=Op.DATALOADN[128 - 32] + Op.POP + Op.STOP,
                ),
                Section.Data(data="1122334455667788" * 16),
            ],
        ),
    ],
    ids=lambda c: c.name,
)
def test_valid_containers(
    eof_test: EOFTestFiller,
    container: Container,
):
    """
    Test creating various types of valid EOF V1 contracts using legacy
    initcode and a contract creating transaction.
    """
    eof_test(data=container)


@pytest.mark.parametrize(
    "container",
    [
        Container(
            name="DATALOADN_max_empty_data",
            sections=[
                Section.Code(
                    code=Op.DATALOADN[0xFFFF - 32] + Op.POP + Op.STOP,
                ),
            ],
            validity_error=EOFException.INVALID_DATALOADN_INDEX,
        ),
        Container(
            name="DATALOADN_max_small_data",
            sections=[
                Section.Code(
                    code=Op.DATALOADN[0xFFFF - 32] + Op.POP + Op.STOP,
                ),
                Section.Data(data="1122334455667788" * 16),
            ],
            validity_error=EOFException.INVALID_DATALOADN_INDEX,
        ),
        Container(
            name="DATALOADN_max_half_data",
            sections=[
                Section.Code(
                    code=Op.DATALOADN[0xFFFF - 32] + Op.POP + Op.STOP,
                ),
                Section.Data(data=("1122334455667788" * 4 * 1024)[2:]),
            ],
            validity_error=EOFException.INVALID_DATALOADN_INDEX,
        ),
        Container(
            name="data_section_over_container_limit",
            sections=[
                Section.Code(code=Op.STOP),
                # Over the 49152 bytes limit for the entire container
                Section.Data(
                    data=(b"12345678" * 6 * 1024)[len(smallest_runtime_subcontainer) - 1 :]
                ),
            ],
            validity_error=EOFException.CONTAINER_SIZE_ABOVE_LIMIT,
        ),
    ],
    ids=lambda c: c.name,
)
def test_invalid_containers(
    eof_test: EOFTestFiller,
    container: Container,
):
    """
    Test creating various types of valid EOF V1 contracts using legacy
    initcode and a contract creating transaction.
    """
    eof_test(
        data=container,
        expect_exception=container.validity_error,
    )
