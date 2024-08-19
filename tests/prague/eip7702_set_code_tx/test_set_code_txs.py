"""
abstract: Tests use of set-code transactions from [EIP-7702: Set EOA account code for one transaction](https://eips.ethereum.org/EIPS/eip-7702)
    Tests use of set-code transactions from [EIP-7702: Set EOA account code for one transaction](https://eips.ethereum.org/EIPS/eip-7702).
"""  # noqa: E501

from enum import Enum
from itertools import count
from typing import List

import pytest
from ethereum.crypto.hash import keccak256

from ethereum_test_tools import (
    Account,
    Address,
    Alloc,
    AuthorizationTuple,
    Block,
    BlockchainTestFiller,
    Bytecode,
    CodeGasMeasure,
    Conditional,
    Environment,
    EVMCodeType,
    Hash,
    Initcode,
)
from ethereum_test_tools import Macros as Om
from ethereum_test_tools import Opcodes as Op
from ethereum_test_tools import (
    StateTestFiller,
    Storage,
    Transaction,
    TransactionException,
    compute_create_address,
)
from ethereum_test_tools.eof.v1 import Container, Section

from .spec import Spec, ref_spec_7702

REFERENCE_SPEC_GIT_PATH = ref_spec_7702.git_path
REFERENCE_SPEC_VERSION = ref_spec_7702.version

pytestmark = pytest.mark.valid_from("Prague")

auth_account_start_balance = 0


@pytest.mark.parametrize(
    "tx_value",
    [0, 1],
)
@pytest.mark.parametrize(
    "suffix,succeeds",
    [
        pytest.param(Op.STOP, True, id="stop"),
        pytest.param(Op.RETURN(0, 0), True, id="return"),
        pytest.param(Op.REVERT, False, id="revert"),
        pytest.param(Op.INVALID, False, id="invalid"),
        pytest.param(Om.OOG, False, id="out-of-gas"),
    ],
)
def test_self_sponsored_set_code(
    state_test: StateTestFiller,
    pre: Alloc,
    suffix: Bytecode,
    succeeds: bool,
    tx_value: int,
):
    """
    Test the executing a self-sponsored set-code transaction.

    The transaction is sent to the sender, and the sender is the signer of the only authorization
    tuple in the authorization list.

    The authorization tuple has a nonce of 1 because the self-sponsored transaction increases the
    nonce of the sender from zero to one first.

    The expected nonce at the end of the transaction is 2.
    """
    storage = Storage()
    sender = pre.fund_eoa()

    set_code = (
        Op.SSTORE(storage.store_next(sender), Op.ORIGIN)
        + Op.SSTORE(storage.store_next(sender), Op.CALLER)
        + Op.SSTORE(storage.store_next(tx_value), Op.CALLVALUE)
        + suffix
    )
    set_code_to_address = pre.deploy_contract(
        set_code,
    )

    tx = Transaction(
        gas_limit=10_000_000,
        to=sender,
        value=tx_value,
        authorization_list=[
            AuthorizationTuple(
                address=set_code_to_address,
                nonce=1,
                signer=sender,
            ),
        ],
        sender=sender,
    )

    state_test(
        env=Environment(),
        pre=pre,
        tx=tx,
        post={
            set_code_to_address: Account(storage={k: 0 for k in storage}),
            sender: Account(nonce=2, code=b"", storage=storage if succeeds else {}),
        },
    )


@pytest.mark.parametrize(
    "eoa_balance",
    [0, 1],
)
@pytest.mark.parametrize(
    "tx_value",
    [0, 1],
)
@pytest.mark.parametrize(
    "suffix,succeeds",
    [
        pytest.param(Op.STOP, True, id="stop"),
        pytest.param(Op.RETURN(0, 0), True, id="return"),
        pytest.param(Op.REVERT, False, id="revert"),
        pytest.param(Op.INVALID, False, id="invalid"),
        pytest.param(Om.OOG, False, id="out-of-gas"),
    ],
)
def test_set_code_to_sstore(
    state_test: StateTestFiller,
    pre: Alloc,
    suffix: Bytecode,
    succeeds: bool,
    tx_value: int,
    eoa_balance: int,
):
    """
    Test the executing a simple SSTORE in a set-code transaction.
    """
    storage = Storage()
    auth_signer = pre.fund_eoa(eoa_balance)
    sender = pre.fund_eoa()

    set_code = (
        Op.SSTORE(storage.store_next(sender), Op.ORIGIN)
        + Op.SSTORE(storage.store_next(sender), Op.CALLER)
        + Op.SSTORE(storage.store_next(tx_value), Op.CALLVALUE)
        + suffix
    )
    set_code_to_address = pre.deploy_contract(
        set_code,
    )

    tx = Transaction(
        gas_limit=10_000_000,
        to=auth_signer,
        value=tx_value,
        authorization_list=[
            AuthorizationTuple(
                address=set_code_to_address,
                nonce=0,
                signer=auth_signer,
            ),
        ],
        sender=sender,
    )

    state_test(
        env=Environment(),
        pre=pre,
        tx=tx,
        post={
            set_code_to_address: Account(storage={k: 0 for k in storage}),
            auth_signer: Account(nonce=1, code=b"", storage=storage if succeeds else {}),
        },
    )


def test_set_code_to_sstore_then_sload(
    blockchain_test: BlockchainTestFiller,
    pre: Alloc,
):
    """
    Test the executing a simple SSTORE then SLOAD in two separate set-code transactions.
    """
    auth_signer = pre.fund_eoa(auth_account_start_balance)
    sender = pre.fund_eoa()

    storage_key_1 = 0x1
    storage_key_2 = 0x2
    storage_value = 0x1234

    set_code_1 = Op.SSTORE(storage_key_1, storage_value) + Op.STOP
    set_code_1_address = pre.deploy_contract(set_code_1)

    set_code_2 = Op.SSTORE(storage_key_2, Op.ADD(Op.SLOAD(storage_key_1), 1)) + Op.STOP
    set_code_2_address = pre.deploy_contract(set_code_2)

    tx_1 = Transaction(
        gas_limit=100_000,
        to=auth_signer,
        value=0,
        authorization_list=[
            AuthorizationTuple(
                address=set_code_1_address,
                nonce=0,
                signer=auth_signer,
            ),
        ],
        sender=sender,
    )

    tx_2 = Transaction(
        gas_limit=100_000,
        to=auth_signer,
        value=0,
        authorization_list=[
            AuthorizationTuple(
                address=set_code_2_address,
                nonce=1,
                signer=auth_signer,
            ),
        ],
        sender=sender,
    )

    block = Block(
        txs=[tx_1, tx_2],
    )

    blockchain_test(
        pre=pre,
        post={
            auth_signer: Account(
                nonce=2,
                code=b"",
                storage={
                    storage_key_1: storage_value,
                    storage_key_2: storage_value + 1,
                },
            ),
        },
        blocks=[block],
    )


@pytest.mark.parametrize(
    "return_opcode",
    [
        Op.RETURN,
        Op.REVERT,
    ],
)
@pytest.mark.with_all_call_opcodes
def test_set_code_to_tstore_reentry(
    state_test: StateTestFiller,
    pre: Alloc,
    call_opcode: Op,
    return_opcode: Op,
    evm_code_type: EVMCodeType,
):
    """
    Test the executing a simple TSTORE in a set-code transaction, which also performs a
    re-entry to TLOAD the value.
    """
    auth_signer = pre.fund_eoa(auth_account_start_balance)

    tload_value = 0x1234
    set_code = Conditional(
        condition=Op.ISZERO(Op.TLOAD(1)),
        if_true=Op.TSTORE(1, tload_value)
        + call_opcode(address=Op.ADDRESS)
        + Op.RETURNDATACOPY(0, 0, 32)
        + Op.SSTORE(2, Op.MLOAD(0)),
        if_false=Op.MSTORE(0, Op.TLOAD(1)) + return_opcode(size=32),
        evm_code_type=evm_code_type,
    )
    set_code_to_address = pre.deploy_contract(set_code)

    tx = Transaction(
        gas_limit=100_000,
        to=auth_signer,
        value=0,
        authorization_list=[
            AuthorizationTuple(
                address=set_code_to_address,
                nonce=0,
                signer=auth_signer,
            ),
        ],
        sender=pre.fund_eoa(),
    )

    state_test(
        env=Environment(),
        pre=pre,
        tx=tx,
        post={
            auth_signer: Account(nonce=1, code=b"", storage={2: tload_value}),
        },
    )


@pytest.mark.parametrize(
    "external_sendall_recipient",
    [False, True],
)
@pytest.mark.parametrize(
    "balance",
    [0, 1],
)
def test_set_code_to_self_destruct(
    state_test: StateTestFiller,
    pre: Alloc,
    external_sendall_recipient: bool,
    balance: int,
):
    """
    Test the executing self-destruct opcode in a set-code transaction.
    """
    auth_signer = pre.fund_eoa(balance)
    if external_sendall_recipient:
        recipient = pre.fund_eoa(0)
    else:
        recipient = auth_signer

    set_code_to_address = pre.deploy_contract(Op.SSTORE(1, 1) + Op.SELFDESTRUCT(recipient))

    tx = Transaction(
        gas_limit=10_000_000,
        to=auth_signer,
        value=0,
        authorization_list=[
            AuthorizationTuple(
                address=set_code_to_address,
                nonce=0,
                signer=auth_signer,
            ),
        ],
        sender=pre.fund_eoa(),
    )

    post = {
        auth_signer: Account(
            nonce=1,
            code=b"",
            storage={1: 1},
            balance=balance if not external_sendall_recipient else 0,
        ),
    }

    if external_sendall_recipient and balance > 0:
        post[recipient] = Account(balance=balance)

    state_test(
        env=Environment(),
        pre=pre,
        tx=tx,
        post=post,
    )


@pytest.mark.with_all_create_opcodes
def test_set_code_to_contract_creator(
    state_test: StateTestFiller,
    pre: Alloc,
    create_opcode: Op,
    evm_code_type: EVMCodeType,
):
    """
    Test the executing a contract-creating opcode in a set-code transaction.
    """
    storage = Storage()
    auth_signer = pre.fund_eoa(auth_account_start_balance)

    deployed_code: Bytecode | Container = Op.STOP
    initcode: Bytecode | Container

    if evm_code_type == EVMCodeType.LEGACY:
        initcode = Initcode(deploy_code=deployed_code)
    elif evm_code_type == EVMCodeType.EOF_V1:
        deployed_code = Container.Code(deployed_code)
        initcode = Container.Init(deploy_container=deployed_code)
    else:
        raise ValueError(f"Unsupported EVM code type: {evm_code_type}")

    salt = 0

    deployed_contract_address = compute_create_address(
        address=auth_signer,
        nonce=1,
        salt=salt,
        initcode=initcode,
        opcode=create_opcode,
    )

    creator_code: Bytecode | Container
    if evm_code_type == EVMCodeType.LEGACY:
        creator_code = Op.CALLDATACOPY(0, 0, Op.CALLDATASIZE) + Op.SSTORE(
            storage.store_next(deployed_contract_address),
            create_opcode(value=0, offset=0, size=Op.CALLDATASIZE, salt=salt),
        )
    elif evm_code_type == EVMCodeType.EOF_V1:
        creator_code = Container(
            sections=[
                Section.Code(
                    code=Op.EOFCREATE[0](0, 0, 0, 0) + Op.STOP(),
                ),
                Section.Container(
                    container=initcode,
                ),
            ]
        )
    else:
        raise ValueError(f"Unsupported EVM code type: {evm_code_type}")

    creator_code_address = pre.deploy_contract(creator_code)

    tx = Transaction(
        gas_limit=10_000_000,
        to=auth_signer,
        value=0,
        data=initcode if evm_code_type == EVMCodeType.LEGACY else b"",
        authorization_list=[
            AuthorizationTuple(
                address=creator_code_address,
                nonce=0,
                signer=auth_signer,
            ),
        ],
        sender=pre.fund_eoa(),
    )

    state_test(
        env=Environment(),
        pre=pre,
        tx=tx,
        post={
            creator_code_address: Account(storage={}),
            auth_signer: Account(nonce=2, code=b"", storage=storage),
            deployed_contract_address: Account(
                code=deployed_code,
                storage={},
            ),
        },
    )


@pytest.mark.parametrize(
    "value",
    [0, 1],
)
@pytest.mark.with_all_call_opcodes
def test_set_code_to_self_caller(
    state_test: StateTestFiller,
    pre: Alloc,
    call_opcode: Op,
    value: int,
    evm_code_type: EVMCodeType,
):
    """
    Test the executing a self-call in a set-code transaction.
    """
    storage = Storage()
    auth_signer = pre.fund_eoa(auth_account_start_balance)

    static_call = call_opcode in [Op.STATICCALL, Op.EXTSTATICCALL]

    first_entry_slot = storage.store_next(True)
    re_entry_success_slot = storage.store_next(not static_call)
    re_entry_call_return_code_slot = storage.store_next(not static_call)
    set_code = Conditional(
        condition=Op.ISZERO(Op.SLOAD(first_entry_slot)),
        if_true=Op.SSTORE(first_entry_slot, 1)
        + Op.SSTORE(re_entry_call_return_code_slot, call_opcode(address=auth_signer, value=value))
        + Op.STOP,
        if_false=Op.SSTORE(re_entry_success_slot, 1) + Op.STOP,
        evm_code_type=evm_code_type,
    )
    set_code_to_address = pre.deploy_contract(set_code)

    tx = Transaction(
        gas_limit=10_000_000,
        to=auth_signer,
        value=value,
        authorization_list=[
            AuthorizationTuple(
                address=set_code_to_address,
                nonce=0,
                signer=auth_signer,
            ),
        ],
        sender=pre.fund_eoa(),
    )

    state_test(
        env=Environment(),
        pre=pre,
        tx=tx,
        post={
            set_code_to_address: Account(storage={}),
            auth_signer: Account(
                nonce=1,
                code=b"",
                storage=storage,
                balance=auth_account_start_balance + value,
            ),
        },
    )


@pytest.mark.with_all_call_opcodes
@pytest.mark.parametrize(
    "value",
    [0, 1],
)
def test_set_code_call_set_code(
    state_test: StateTestFiller,
    pre: Alloc,
    call_opcode: Op,
    value: int,
):
    """
    Test the calling a set-code account from another set-code account.
    """
    auth_signer_1 = pre.fund_eoa(auth_account_start_balance)
    storage_1 = Storage()

    static_call = call_opcode in [Op.STATICCALL, Op.EXTSTATICCALL]

    set_code_1_call_result_slot = storage_1.store_next(not static_call)
    set_code_1_success = storage_1.store_next(True)

    auth_signer_2 = pre.fund_eoa(auth_account_start_balance)
    storage_2 = Storage().set_next_slot(storage_1.peek_slot())
    set_code_2_success = storage_2.store_next(not static_call)

    set_code_1 = (
        Op.SSTORE(set_code_1_call_result_slot, call_opcode(address=auth_signer_2, value=value))
        + Op.SSTORE(set_code_1_success, 1)
        + Op.STOP
    )
    set_code_to_address_1 = pre.deploy_contract(set_code_1)

    set_code_2 = Op.SSTORE(set_code_2_success, 1) + Op.STOP
    set_code_to_address_2 = pre.deploy_contract(set_code_2)

    tx = Transaction(
        gas_limit=10_000_000,
        to=auth_signer_1,
        value=value,
        authorization_list=[
            AuthorizationTuple(
                address=set_code_to_address_1,
                nonce=0,
                signer=auth_signer_1,
            ),
            AuthorizationTuple(
                address=set_code_to_address_2,
                nonce=0,
                signer=auth_signer_2,
            ),
        ],
        sender=pre.fund_eoa(),
    )

    state_test(
        env=Environment(),
        pre=pre,
        tx=tx,
        post={
            set_code_to_address_1: Account(storage={k: 0 for k in storage_1}),
            set_code_to_address_2: Account(storage={k: 0 for k in storage_2}),
            auth_signer_1: Account(
                nonce=1,
                storage=storage_1
                if call_opcode in [Op.CALL, Op.STATICCALL, Op.EXTCALL, Op.EXTSTATICCALL]
                else storage_1 + storage_2,
                balance=(0 if call_opcode in [Op.CALL, Op.EXTCALL] else value)
                + auth_account_start_balance,
            ),
            auth_signer_2: Account(
                nonce=1,
                storage=storage_2 if call_opcode in [Op.CALL, Op.EXTCALL] else {},
                balance=(value if call_opcode in [Op.CALL, Op.EXTCALL] else 0)
                + auth_account_start_balance,
            ),
        },
    )


def test_address_from_set_code(
    state_test: StateTestFiller,
    pre: Alloc,
):
    """
    Test the address opcode in a set-code transaction.
    """
    storage = Storage()
    auth_signer = pre.fund_eoa(auth_account_start_balance)

    set_code = Op.SSTORE(storage.store_next(auth_signer), Op.ADDRESS) + Op.STOP
    set_code_to_address = pre.deploy_contract(set_code)

    tx = Transaction(
        gas_limit=10_000_000,
        to=auth_signer,
        value=0,
        authorization_list=[
            AuthorizationTuple(
                address=set_code_to_address,
                nonce=0,
                signer=auth_signer,
            ),
        ],
        sender=pre.fund_eoa(),
    )

    state_test(
        env=Environment(),
        pre=pre,
        tx=tx,
        post={
            set_code_to_address: Account(storage={}),
            auth_signer: Account(nonce=1, code=b"", storage=storage),
        },
    )


def test_tx_into_self_delegating_set_code(
    state_test: StateTestFiller,
    pre: Alloc,
):
    """
    Test a transaction that has entry-point into a set-code address that delegates to itself.
    """
    auth_signer = pre.fund_eoa(auth_account_start_balance)

    tx = Transaction(
        gas_limit=10_000_000,
        to=auth_signer,
        value=0,
        authorization_list=[
            AuthorizationTuple(
                address=auth_signer,
                nonce=0,
                signer=auth_signer,
            ),
        ],
        sender=pre.fund_eoa(),
    )

    state_test(
        env=Environment(),
        pre=pre,
        tx=tx,
        post={
            auth_signer: Account(nonce=1, code=b""),
        },
    )


def test_tx_into_chain_delegating_set_code(
    state_test: StateTestFiller,
    pre: Alloc,
):
    """
    Test a transaction that has entry-point into a set-code address that delegates to itself.
    """
    auth_signer_1 = pre.fund_eoa(auth_account_start_balance)
    auth_signer_2 = pre.fund_eoa(auth_account_start_balance)

    tx = Transaction(
        gas_limit=10_000_000,
        to=auth_signer_1,
        value=0,
        authorization_list=[
            AuthorizationTuple(
                address=auth_signer_2,
                nonce=0,
                signer=auth_signer_1,
            ),
            AuthorizationTuple(
                address=auth_signer_1,
                nonce=0,
                signer=auth_signer_2,
            ),
        ],
        sender=pre.fund_eoa(),
    )

    state_test(
        env=Environment(),
        pre=pre,
        tx=tx,
        post={
            auth_signer_1: Account(nonce=1, code=b""),
            auth_signer_2: Account(nonce=1, code=b""),
        },
    )


@pytest.mark.with_all_call_opcodes
def test_call_into_self_delegating_set_code(
    state_test: StateTestFiller,
    pre: Alloc,
    call_opcode: Op,
):
    """
    Test a transaction that has entry-point into a set-code address that delegates to itself.
    """
    auth_signer = pre.fund_eoa(auth_account_start_balance)

    storage = Storage()
    entry_code = Op.SSTORE(storage.store_next(False), call_opcode(address=auth_signer)) + Op.STOP
    entry_address = pre.deploy_contract(entry_code)

    tx = Transaction(
        gas_limit=10_000_000,
        to=entry_address,
        value=0,
        authorization_list=[
            AuthorizationTuple(
                address=auth_signer,
                nonce=0,
                signer=auth_signer,
            ),
        ],
        sender=pre.fund_eoa(),
    )

    state_test(
        env=Environment(),
        pre=pre,
        tx=tx,
        post={
            entry_address: Account(storage=storage),
            auth_signer: Account(nonce=1, code=b""),
        },
    )


@pytest.mark.with_all_call_opcodes
def test_call_into_chain_delegating_set_code(
    state_test: StateTestFiller,
    pre: Alloc,
    call_opcode: Op,
):
    """
    Test a transaction that has entry-point into a set-code address that delegates to itself.
    """
    auth_signer_1 = pre.fund_eoa(auth_account_start_balance)
    auth_signer_2 = pre.fund_eoa(auth_account_start_balance)

    storage = Storage()
    entry_code = Op.SSTORE(storage.store_next(False), call_opcode(address=auth_signer_1)) + Op.STOP
    entry_address = pre.deploy_contract(entry_code)

    tx = Transaction(
        gas_limit=10_000_000,
        to=entry_address,
        value=0,
        authorization_list=[
            AuthorizationTuple(
                address=auth_signer_2,
                nonce=0,
                signer=auth_signer_1,
            ),
            AuthorizationTuple(
                address=auth_signer_1,
                nonce=0,
                signer=auth_signer_2,
            ),
        ],
        sender=pre.fund_eoa(),
    )

    state_test(
        env=Environment(),
        pre=pre,
        tx=tx,
        post={
            entry_address: Account(storage=storage),
            auth_signer_1: Account(nonce=1, code=b""),
            auth_signer_2: Account(nonce=1, code=b""),
        },
    )


@pytest.mark.parametrize(
    "balance",
    [0, 1],
)
def test_ext_code_on_set_code(
    state_test: StateTestFiller,
    pre: Alloc,
    balance: int,
):
    """
    Test different ext*code operations on a set-code address.
    """
    auth_signer = pre.fund_eoa(balance)

    slot = count(1)
    slot_call_success = next(slot)
    slot_caller = next(slot)
    slot_ext_code_size_result = next(slot)
    slot_ext_code_hash_result = next(slot)
    slot_ext_code_copy_result = next(slot)
    slot_ext_balance_result = next(slot)

    callee_code = (
        Op.SSTORE(slot_caller, Op.CALLER)
        + Op.SSTORE(slot_ext_code_size_result, Op.EXTCODESIZE(Op.CALLER))
        + Op.SSTORE(slot_ext_code_hash_result, Op.EXTCODEHASH(Op.CALLER))
        + Op.EXTCODECOPY(Op.CALLER, 0, 0, Op.EXTCODESIZE(Op.CALLER))
        + Op.SSTORE(slot_ext_code_copy_result, Op.MLOAD(0))
        + Op.SSTORE(slot_ext_balance_result, Op.BALANCE(Op.CALLER))
        + Op.STOP
    )
    callee_address = pre.deploy_contract(callee_code)
    callee_storage = Storage()

    auth_signer_storage = Storage()
    set_code = Op.SSTORE(slot_call_success, Op.CALL(address=callee_address)) + Op.STOP
    auth_signer_storage[slot_call_success] = True
    set_code_to_address = pre.deploy_contract(set_code)

    callee_storage[slot_caller] = auth_signer
    callee_storage[slot_ext_code_size_result] = len(set_code)
    callee_storage[slot_ext_code_hash_result] = set_code.keccak256()
    callee_storage[slot_ext_code_copy_result] = bytes(set_code).ljust(32, b"\x00")[:32]
    callee_storage[slot_ext_balance_result] = balance

    tx = Transaction(
        gas_limit=10_000_000,
        to=auth_signer,
        authorization_list=[
            AuthorizationTuple(
                address=set_code_to_address,
                nonce=0,
                signer=auth_signer,
            ),
        ],
        sender=pre.fund_eoa(),
    )

    state_test(
        env=Environment(),
        pre=pre,
        tx=tx,
        post={
            set_code_to_address: Account(storage={}),
            auth_signer: Account(nonce=1, code=b"", storage=auth_signer_storage, balance=balance),
            callee_address: Account(storage=callee_storage),
        },
    )


@pytest.mark.with_all_call_opcodes(
    lambda opcode: opcode
    not in [Op.STATICCALL, Op.CALLCODE, Op.DELEGATECALL, Op.EXTDELEGATECALL, Op.EXTSTATICCALL]
)
@pytest.mark.parametrize(
    "set_code_address_first",
    [
        pytest.param(True, id="call_set_code_address_first_then_authority"),
        pytest.param(False, id="call_authority_first_then_set_code_address"),
    ],
)
def test_set_code_address_and_authority_warm_state(
    state_test: StateTestFiller,
    pre: Alloc,
    call_opcode: Op,
    set_code_address_first: bool,
):
    """
    Test set to code address and authority warm status after a call to
    authority address, or viceversa.
    """
    auth_signer = pre.fund_eoa(auth_account_start_balance)

    slot = count(1)
    slot_call_success = next(slot)
    slot_set_code_to_warm_state = next(slot)
    slot_authority_warm_state = next(slot)

    set_code = Op.STOP
    set_code_to_address = pre.deploy_contract(set_code)

    overhead_cost = 3 * len(call_opcode.kwargs)  # type: ignore
    if call_opcode == Op.CALL:
        overhead_cost -= 1  # GAS opcode is less expensive than a PUSH

    code_gas_measure_set_code = CodeGasMeasure(
        code=call_opcode(address=set_code_to_address),
        overhead_cost=overhead_cost,
        extra_stack_items=1,
        sstore_key=slot_set_code_to_warm_state,
        stop=False,
    )
    code_gas_measure_authority = CodeGasMeasure(
        code=call_opcode(address=auth_signer),
        overhead_cost=overhead_cost,
        extra_stack_items=1,
        sstore_key=slot_authority_warm_state,
        stop=False,
    )

    callee_code = Bytecode()
    if set_code_address_first:
        callee_code += code_gas_measure_set_code + code_gas_measure_authority
    else:
        callee_code += code_gas_measure_authority + code_gas_measure_set_code
    callee_code += Op.SSTORE(slot_call_success, 1) + Op.STOP

    callee_address = pre.deploy_contract(callee_code)
    callee_storage = Storage()
    callee_storage[slot_call_success] = 1
    callee_storage[slot_set_code_to_warm_state] = 2_600
    callee_storage[slot_authority_warm_state] = 100

    tx = Transaction(
        gas_limit=1_000_000,
        to=callee_address,
        authorization_list=[
            AuthorizationTuple(
                address=set_code_to_address,
                nonce=0,
                signer=auth_signer,
            ),
        ],
        sender=pre.fund_eoa(),
    )

    state_test(
        env=Environment(),
        pre=pre,
        tx=tx,
        post={
            callee_address: Account(storage=callee_storage),
        },
    )


@pytest.mark.parametrize(
    "balance",
    [0, 1],
)
def test_ext_code_on_self_delegating_set_code(
    state_test: StateTestFiller,
    pre: Alloc,
    balance: int,
):
    """
    Test different ext*code operations on a set-code address that delegates to itself.
    """
    auth_signer = pre.fund_eoa(balance)

    slot = count(1)
    slot_ext_code_size_result = next(slot)
    slot_ext_code_hash_result = next(slot)
    slot_ext_code_copy_result = next(slot)
    slot_ext_balance_result = next(slot)

    callee_code = (
        Op.SSTORE(slot_ext_code_size_result, Op.EXTCODESIZE(auth_signer))
        + Op.SSTORE(slot_ext_code_hash_result, Op.EXTCODEHASH(auth_signer))
        + Op.EXTCODECOPY(auth_signer, 0, 0, Op.EXTCODESIZE(auth_signer))
        + Op.SSTORE(slot_ext_code_copy_result, Op.MLOAD(0))
        + Op.SSTORE(slot_ext_balance_result, Op.BALANCE(auth_signer))
        + Op.STOP
    )
    callee_address = pre.deploy_contract(callee_code)
    callee_storage = Storage()

    set_code = b"\xef\x01\x00" + bytes(auth_signer)
    callee_storage[slot_ext_code_size_result] = len(set_code)
    callee_storage[slot_ext_code_hash_result] = keccak256(set_code)
    callee_storage[slot_ext_code_copy_result] = bytes(set_code).ljust(32, b"\x00")[:32]
    callee_storage[slot_ext_balance_result] = balance

    tx = Transaction(
        gas_limit=10_000_000,
        to=callee_address,
        authorization_list=[
            AuthorizationTuple(
                address=auth_signer,
                nonce=0,
                signer=auth_signer,
            ),
        ],
        sender=pre.fund_eoa(),  # TODO: Test with sender as auth_signer
    )

    state_test(
        env=Environment(),
        pre=pre,
        tx=tx,
        post={
            auth_signer: Account(nonce=1, code=b"", balance=balance),
            callee_address: Account(storage=callee_storage),
        },
    )


def test_ext_code_on_chain_delegating_set_code(
    state_test: StateTestFiller,
    pre: Alloc,
):
    """
    Test different ext*code operations on a set-code address that references another delegated
    address.
    """
    auth_signer_1_balance = 1
    auth_signer_2_balance = 0

    auth_signer_1 = pre.fund_eoa(auth_signer_1_balance)
    auth_signer_2 = pre.fund_eoa(auth_signer_2_balance)

    slot = count(1)

    slot_ext_code_size_result_1 = next(slot)
    slot_ext_code_hash_result_1 = next(slot)
    slot_ext_code_copy_result_1 = next(slot)
    slot_ext_balance_result_1 = next(slot)

    slot_ext_code_size_result_2 = next(slot)
    slot_ext_code_hash_result_2 = next(slot)
    slot_ext_code_copy_result_2 = next(slot)
    slot_ext_balance_result_2 = next(slot)

    callee_code = (
        # Address 1
        Op.SSTORE(slot_ext_code_size_result_1, Op.EXTCODESIZE(auth_signer_1))
        + Op.SSTORE(slot_ext_code_hash_result_1, Op.EXTCODEHASH(auth_signer_1))
        + Op.EXTCODECOPY(auth_signer_1, 0, 0, Op.EXTCODESIZE(auth_signer_1))
        + Op.SSTORE(slot_ext_code_copy_result_1, Op.MLOAD(0))
        + Op.SSTORE(slot_ext_balance_result_1, Op.BALANCE(auth_signer_1))
        # Address 2
        + Op.SSTORE(slot_ext_code_size_result_2, Op.EXTCODESIZE(auth_signer_2))
        + Op.SSTORE(slot_ext_code_hash_result_2, Op.EXTCODEHASH(auth_signer_2))
        + Op.EXTCODECOPY(auth_signer_2, 0, 0, Op.EXTCODESIZE(auth_signer_2))
        + Op.SSTORE(slot_ext_code_copy_result_2, Op.MLOAD(0))
        + Op.SSTORE(slot_ext_balance_result_2, Op.BALANCE(auth_signer_2))
        + Op.STOP
    )
    callee_address = pre.deploy_contract(callee_code)
    callee_storage = Storage()

    set_code_1 = Spec.DELEGATION_DESIGNATION + bytes(auth_signer_2)
    set_code_2 = Spec.DELEGATION_DESIGNATION + bytes(auth_signer_1)

    callee_storage[slot_ext_code_size_result_1] = len(set_code_2)
    callee_storage[slot_ext_code_hash_result_1] = keccak256(set_code_2)
    callee_storage[slot_ext_code_copy_result_1] = bytes(set_code_2).ljust(32, b"\x00")[:32]
    callee_storage[slot_ext_balance_result_1] = auth_signer_1_balance

    callee_storage[slot_ext_code_size_result_2] = len(set_code_1)
    callee_storage[slot_ext_code_hash_result_2] = keccak256(set_code_1)
    callee_storage[slot_ext_code_copy_result_2] = bytes(set_code_1).ljust(32, b"\x00")[:32]
    callee_storage[slot_ext_balance_result_2] = auth_signer_2_balance

    tx = Transaction(
        gas_limit=10_000_000,
        to=callee_address,
        authorization_list=[
            AuthorizationTuple(
                address=auth_signer_2,
                nonce=0,
                signer=auth_signer_1,
            ),
            AuthorizationTuple(
                address=auth_signer_1,
                nonce=0,
                signer=auth_signer_2,
            ),
        ],
        sender=pre.fund_eoa(),  # TODO: Test with sender as auth_signer
    )

    state_test(
        env=Environment(),
        pre=pre,
        tx=tx,
        post={
            auth_signer_1: Account(nonce=1, code=b"", balance=auth_signer_1_balance),
            auth_signer_2: Account(nonce=1, code=b"", balance=auth_signer_2_balance),
            callee_address: Account(storage=callee_storage),
        },
    )


@pytest.mark.parametrize(
    "balance",
    [0, 1],
)
def test_self_code_on_set_code(
    state_test: StateTestFiller,
    pre: Alloc,
    balance: int,
):
    """
    Test codesize and codecopy operations on a set-code address.
    """
    auth_signer = pre.fund_eoa(balance)

    slot = count(1)
    slot_code_size_result = next(slot)
    slot_code_copy_result = next(slot)
    slot_self_balance_result = next(slot)

    set_code = (
        Op.SSTORE(slot_code_size_result, Op.CODESIZE)
        + Op.CODECOPY(0, 0, Op.CODESIZE)
        + Op.SSTORE(slot_code_copy_result, Op.MLOAD(0))
        + Op.SSTORE(slot_self_balance_result, Op.SELFBALANCE)
        + Op.STOP
    )
    set_code_to_address = pre.deploy_contract(set_code)

    storage = Storage()
    storage[slot_code_size_result] = len(set_code)
    storage[slot_code_copy_result] = bytes(set_code).ljust(32, b"\x00")[:32]
    storage[slot_self_balance_result] = balance

    tx = Transaction(
        gas_limit=10_000_000,
        to=auth_signer,
        authorization_list=[
            AuthorizationTuple(
                address=set_code_to_address,
                nonce=0,
                signer=auth_signer,
            ),
        ],
        sender=pre.fund_eoa(),
    )

    state_test(
        env=Environment(),
        pre=pre,
        tx=tx,
        post={
            set_code_to_address: Account(storage={}),
            auth_signer: Account(nonce=1, code=b"", storage=storage, balance=balance),
        },
    )


@pytest.mark.with_all_create_opcodes
def test_set_code_to_account_deployed_in_same_tx(
    state_test: StateTestFiller,
    pre: Alloc,
    create_opcode: Op,
    evm_code_type: EVMCodeType,
):
    """
    Test setting the code of an account to an address that is deployed in the same transaction,
    and test calling the set-code address and the deployed contract.
    """
    auth_signer = pre.fund_eoa(auth_account_start_balance)

    success_slot = 1

    deployed_code: Bytecode | Container = Op.SSTORE(success_slot, 1) + Op.STOP
    initcode: Bytecode | Container

    if evm_code_type == EVMCodeType.LEGACY:
        initcode = Initcode(deploy_code=deployed_code)
    elif evm_code_type == EVMCodeType.EOF_V1:
        deployed_code = Container.Code(deployed_code)
        initcode = Container.Init(deploy_container=deployed_code)
    else:
        raise ValueError(f"Unsupported EVM code type: {evm_code_type}")

    deployed_contract_address_slot = 1
    signer_call_return_code_slot = 2
    deployed_contract_call_return_code_slot = 3

    salt = 0
    call_opcode = Op.CALL if evm_code_type == EVMCodeType.LEGACY else Op.EXTCALL

    if create_opcode == Op.EOFCREATE:
        create_opcode = Op.EOFCREATE[0]  # type: ignore

    contract_creator_code: Bytecode | Container = (
        Op.CALLDATACOPY(0, 0, Op.CALLDATASIZE)  # NOOP on EOF
        + Op.SSTORE(
            deployed_contract_address_slot,
            create_opcode(offset=0, salt=salt, size=Op.CALLDATASIZE),
        )
        + Op.SSTORE(signer_call_return_code_slot, call_opcode(address=auth_signer))
        + Op.SSTORE(
            deployed_contract_call_return_code_slot,
            call_opcode(address=Op.SLOAD(deployed_contract_address_slot)),
        )
        + Op.STOP()
    )

    if evm_code_type == EVMCodeType.EOF_V1:
        contract_creator_code = Container(
            sections=[
                Section.Code(contract_creator_code),
                Section.Container(container=initcode),
            ],
        )

    contract_creator_address = pre.deploy_contract(contract_creator_code)

    deployed_contract_address = compute_create_address(
        address=contract_creator_address,
        nonce=1,
        salt=salt,
        initcode=initcode,
        opcode=create_opcode,
    )

    tx = Transaction(
        gas_limit=10_000_000,
        to=contract_creator_address,
        value=0,
        data=initcode if evm_code_type == EVMCodeType.LEGACY else b"",
        authorization_list=[
            AuthorizationTuple(
                address=deployed_contract_address,
                nonce=0,
                signer=auth_signer,
            ),
        ],
        sender=pre.fund_eoa(),
    )

    state_test(
        env=Environment(),
        pre=pre,
        tx=tx,
        post={
            deployed_contract_address: Account(
                storage={success_slot: 1},
            ),
            auth_signer: Account(
                nonce=1,
                code=b"",
                storage={success_slot: 1},
            ),
            contract_creator_address: Account(
                storage={
                    deployed_contract_address_slot: deployed_contract_address,
                    signer_call_return_code_slot: 1,
                    deployed_contract_call_return_code_slot: 1,
                }
            ),
        },
    )


@pytest.mark.parametrize(
    "external_sendall_recipient",
    [False, True],
)
@pytest.mark.parametrize(
    "balance",
    [0, 1],
)
@pytest.mark.parametrize("call_set_code_first", [False, True])
@pytest.mark.parametrize(
    "create_opcode", [Op.CREATE, Op.CREATE2]
)  # EOF code does not support SELFDESTRUCT
def test_set_code_to_self_destructing_account_deployed_in_same_tx(
    state_test: StateTestFiller,
    pre: Alloc,
    create_opcode: Op,
    call_set_code_first: bool,
    external_sendall_recipient: bool,
    balance: int,
):
    """
    Test setting the code of an account to an account that contains the SELFDESTRUCT opcode and
    was deployed in the same transaction, and test calling the set-code address and the deployed
    in both sequence orders.
    """
    auth_signer = pre.fund_eoa(balance)
    if external_sendall_recipient:
        recipient = pre.fund_eoa(0)
    else:
        recipient = auth_signer

    success_slot = 1

    deployed_code = Op.SSTORE(success_slot, 1) + Op.SELFDESTRUCT(recipient)
    initcode = Initcode(deploy_code=deployed_code)

    deployed_contract_address_slot = 1
    signer_call_return_code_slot = 2
    deployed_contract_call_return_code_slot = 3

    salt = 0
    call_opcode = Op.CALL

    contract_creator_code: Bytecode = Op.CALLDATACOPY(0, 0, Op.CALLDATASIZE) + Op.SSTORE(
        deployed_contract_address_slot,
        create_opcode(offset=0, salt=salt, size=Op.CALLDATASIZE),
    )
    if call_set_code_first:
        contract_creator_code += Op.SSTORE(
            signer_call_return_code_slot, call_opcode(address=auth_signer)
        ) + Op.SSTORE(
            deployed_contract_call_return_code_slot,
            call_opcode(address=Op.SLOAD(deployed_contract_address_slot)),
        )
    else:
        contract_creator_code += Op.SSTORE(
            deployed_contract_call_return_code_slot,
            call_opcode(address=Op.SLOAD(deployed_contract_address_slot)),
        ) + Op.SSTORE(signer_call_return_code_slot, call_opcode(address=auth_signer))

    contract_creator_code += Op.STOP

    contract_creator_address = pre.deploy_contract(contract_creator_code)

    deployed_contract_address = compute_create_address(
        address=contract_creator_address,
        nonce=1,
        salt=salt,
        initcode=initcode,
        opcode=create_opcode,
    )

    tx = Transaction(
        gas_limit=10_000_000,
        to=contract_creator_address,
        value=0,
        data=initcode,
        authorization_list=[
            AuthorizationTuple(
                address=deployed_contract_address,
                nonce=0,
                signer=auth_signer,
            ),
        ],
        sender=pre.fund_eoa(),
    )

    post = {
        deployed_contract_address: Account.NONEXISTENT,
        auth_signer: Account(
            nonce=1,
            code=b"",
            storage={success_slot: 1},
            balance=balance if not external_sendall_recipient else 0,
        ),
        contract_creator_address: Account(
            storage={
                deployed_contract_address_slot: deployed_contract_address,
                signer_call_return_code_slot: 1,
                deployed_contract_call_return_code_slot: 1,
            }
        ),
    }

    if external_sendall_recipient and balance > 0:
        post[recipient] = Account(balance=balance)

    state_test(
        env=Environment(),
        pre=pre,
        tx=tx,
        post=post,
    )


def test_set_code_multiple_valid_authorization_tuples_same_signer(
    state_test: StateTestFiller,
    pre: Alloc,
):
    """
    Test setting the code of an account with multiple authorization tuples from the same signer.
    """
    auth_signer = pre.fund_eoa(auth_account_start_balance)

    tuple_count = 10

    success_slot = 0

    addresses = [pre.deploy_contract(Op.SSTORE(i, 1) + Op.STOP) for i in range(tuple_count)]

    tx = Transaction(
        gas_limit=10_000_000,
        to=auth_signer,
        value=0,
        authorization_list=[
            AuthorizationTuple(
                address=address,
                nonce=0,
                signer=auth_signer,
            )
            for address in addresses
        ],
        sender=pre.fund_eoa(),
    )

    state_test(
        env=Environment(),
        pre=pre,
        tx=tx,
        post={
            auth_signer: Account(
                nonce=1,
                code=b"",
                storage={
                    success_slot: 1,
                },
            ),
        },
    )


def test_set_code_multiple_valid_authorization_tuples_same_signer_increasing_nonce(
    state_test: StateTestFiller,
    pre: Alloc,
):
    """
    Test setting the code of an account with multiple authorization tuples from the same signer
    and each authorization tuple has an increasing nonce, therefore the last tuple is executed.
    """
    auth_signer = pre.fund_eoa(auth_account_start_balance)

    tuple_count = 10

    success_slot = tuple_count - 1

    addresses = [pre.deploy_contract(Op.SSTORE(i, 1) + Op.STOP) for i in range(tuple_count)]

    tx = Transaction(
        gas_limit=10_000_000,  # TODO: Reduce gas limit of all tests
        to=auth_signer,
        value=0,
        authorization_list=[
            AuthorizationTuple(
                address=address,
                nonce=i,
                signer=auth_signer,
            )
            for i, address in enumerate(addresses)
        ],
        sender=pre.fund_eoa(),
    )

    state_test(
        env=Environment(),
        pre=pre,
        tx=tx,
        post={
            auth_signer: Account(
                nonce=10,
                code=b"",
                storage={
                    success_slot: 1,
                },
            ),
        },
    )


def test_set_code_multiple_valid_authorization_tuples_same_signer_increasing_nonce_self_sponsored(
    state_test: StateTestFiller,
    pre: Alloc,
):
    """
    Test setting the code of an account with multiple authorization tuples from the same signer
    and each authorization tuple has an increasing nonce, therefore the last tuple is executed,
    and the transaction is self-sponsored.
    """
    auth_signer = pre.fund_eoa()

    tuple_count = 10

    success_slot = tuple_count - 1

    addresses = [pre.deploy_contract(Op.SSTORE(i, 1) + Op.STOP) for i in range(tuple_count)]

    tx = Transaction(
        gas_limit=10_000_000,  # TODO: Reduce gas limit of all tests
        to=auth_signer,
        value=0,
        authorization_list=[
            AuthorizationTuple(
                address=address,
                nonce=i + 1,
                signer=auth_signer,
            )
            for i, address in enumerate(addresses)
        ],
        sender=auth_signer,
    )

    state_test(
        env=Environment(),
        pre=pre,
        tx=tx,
        post={
            auth_signer: Account(
                nonce=11,
                code=b"",
                storage={
                    success_slot: 1,
                },
            ),
        },
    )


def test_set_code_multiple_valid_authorization_tuples_first_invalid_same_signer(
    state_test: StateTestFiller,
    pre: Alloc,
):
    """
    Test setting the code of an account with multiple authorization tuples from the same signer
    but the first tuple is invalid.
    """
    auth_signer = pre.fund_eoa(auth_account_start_balance)

    success_slot = 1

    tuple_count = 10

    addresses = [pre.deploy_contract(Op.SSTORE(i, 1) + Op.STOP) for i in range(tuple_count)]

    tx = Transaction(
        gas_limit=10_000_000,
        to=auth_signer,
        value=0,
        authorization_list=[
            AuthorizationTuple(
                address=address,
                nonce=1 if i == 0 else 0,
                signer=auth_signer,
            )
            for i, address in enumerate(addresses)
        ],
        sender=pre.fund_eoa(),
    )

    state_test(
        env=Environment(),
        pre=pre,
        tx=tx,
        post={
            auth_signer: Account(
                nonce=1,
                code=b"",
                storage={
                    success_slot: 1,
                },
            ),
        },
    )


def test_set_code_all_invalid_authorization_tuples(
    state_test: StateTestFiller,
    pre: Alloc,
):
    """
    Test setting the code of an account with multiple authorization tuples from the same signer
    but the first tuple is invalid.
    """
    auth_signer = pre.fund_eoa(auth_account_start_balance)

    tuple_count = 10

    addresses = [pre.deploy_contract(Op.SSTORE(i, 1) + Op.STOP) for i in range(tuple_count)]

    tx = Transaction(
        gas_limit=10_000_000,
        to=auth_signer,
        value=0,
        authorization_list=[
            AuthorizationTuple(
                address=address,
                nonce=1,
                signer=auth_signer,
            )
            for _, address in enumerate(addresses)
        ],
        sender=pre.fund_eoa(),
    )

    state_test(
        env=Environment(),
        pre=pre,
        tx=tx,
        post={
            auth_signer: Account(
                nonce=0,
                code=b"",
                storage={},
            ),
        },
    )


class InvalidityReason(Enum):
    """
    Reasons for invalidity of a set-code transaction.
    """

    NONCE = "nonce"
    MULTIPLE_NONCE = "multiple_nonce"
    CHAIN_ID = "chain_id"
    ZERO_LENGTH_AUTHORIZATION_LIST = "zero_length_authorization_list"
    INVALID_SIGNATURE_S_VALUE = "invalid_signature_s_value"  # TODO: Implement


@pytest.mark.parametrize(
    "invalidity_reason,transaction_exception",
    [
        pytest.param(
            InvalidityReason.NONCE,
            None,
        ),
        pytest.param(
            InvalidityReason.MULTIPLE_NONCE,
            None,
            marks=pytest.mark.xfail(reason="test issue"),
        ),
        pytest.param(
            InvalidityReason.CHAIN_ID,
            None,
        ),
        pytest.param(
            InvalidityReason.CHAIN_ID,
            TransactionException.TYPE_4_EMPTY_AUTHORIZATION_LIST,
        ),
    ],
)
def test_set_code_invalid_authorization_tuple(
    state_test: StateTestFiller,
    pre: Alloc,
    invalidity_reason: InvalidityReason,
    transaction_exception: TransactionException | None,
):
    """
    Test attempting to set the code of an account with invalid authorization tuple.
    """
    auth_signer = pre.fund_eoa(auth_account_start_balance)

    success_slot = 1

    set_code = Op.SSTORE(success_slot, 1) + Op.STOP
    set_code_to_address = pre.deploy_contract(set_code)

    authorization_list: List[AuthorizationTuple] = []

    if invalidity_reason != InvalidityReason.ZERO_LENGTH_AUTHORIZATION_LIST:
        authorization_list = [
            AuthorizationTuple(
                address=set_code_to_address,
                nonce=1
                if invalidity_reason == InvalidityReason.NONCE
                else [0, 1]
                if invalidity_reason == InvalidityReason.MULTIPLE_NONCE
                else 0,
                chain_id=2 if invalidity_reason == InvalidityReason.CHAIN_ID else 0,
                signer=auth_signer,
            )
        ]

    tx = Transaction(
        gas_limit=10_000_000,
        to=auth_signer,
        value=0,
        authorization_list=authorization_list,
        error=transaction_exception,
        sender=pre.fund_eoa(),
    )

    state_test(
        env=Environment(),
        pre=pre,
        tx=tx,
        post={
            auth_signer: Account.NONEXISTENT,
        },
    )


def test_set_code_using_chain_specific_id(
    state_test: StateTestFiller,
    pre: Alloc,
):
    """
    Test sending a transaction to set the code of an account using a chain-specific ID.
    """
    auth_signer = pre.fund_eoa(auth_account_start_balance)

    success_slot = 1

    set_code = Op.SSTORE(success_slot, 1) + Op.STOP
    set_code_to_address = pre.deploy_contract(set_code)

    tx = Transaction(
        gas_limit=100_000,
        to=auth_signer,
        value=0,
        authorization_list=[
            AuthorizationTuple(
                address=set_code_to_address,
                nonce=0,
                chain_id=1,
                signer=auth_signer,
            )
        ],
        sender=pre.fund_eoa(),
    )

    state_test(
        env=Environment(),
        pre=pre,
        tx=tx,
        post={
            auth_signer: Account(
                storage={success_slot: 1},
            ),
        },
    )


SECP256K1N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
SECP256K1N_OVER_2 = SECP256K1N // 2


@pytest.mark.parametrize(
    "v,r,s",
    [
        pytest.param(0, 1, 1, id="v=0,r=1,s=1"),
        pytest.param(1, 1, 1, id="v=1,r=1,s=1"),
        pytest.param(
            2, 1, 1, id="v=2,r=1,s=1", marks=pytest.mark.xfail(reason="invalid signature")
        ),
        pytest.param(
            1, 0, 1, id="v=1,r=0,s=1", marks=pytest.mark.xfail(reason="invalid signature")
        ),
        pytest.param(
            1, 1, 0, id="v=1,r=1,s=0", marks=pytest.mark.xfail(reason="invalid signature")
        ),
        pytest.param(
            0,
            SECP256K1N - 0,
            1,
            id="v=0,r=SECP256K1N,s=1",
            marks=pytest.mark.xfail(reason="invalid signature"),
        ),
        pytest.param(
            0,
            SECP256K1N - 1,
            1,
            id="v=0,r=SECP256K1N-1,s=1",
            marks=pytest.mark.xfail(reason="invalid signature"),
        ),
        pytest.param(0, SECP256K1N - 2, 1, id="v=0,r=SECP256K1N-2,s=1"),
        pytest.param(1, SECP256K1N - 2, 1, id="v=1,r=SECP256K1N-2,s=1"),
        pytest.param(0, 1, SECP256K1N_OVER_2, id="v=0,r=1,s=SECP256K1N_OVER_2"),
        pytest.param(1, 1, SECP256K1N_OVER_2, id="v=1,r=1,s=SECP256K1N_OVER_2"),
        pytest.param(
            0,
            1,
            SECP256K1N_OVER_2 + 1,
            id="v=0,r=1,s=SECP256K1N_OVER_2+1",
            marks=pytest.mark.xfail(reason="invalid signature"),
        ),
    ],
)
def test_set_code_using_valid_synthetic_signatures(
    state_test: StateTestFiller,
    pre: Alloc,
    v: int,
    r: int,
    s: int,
):
    """
    Test sending a transaction to set the code of an account using synthetic signatures.
    """
    success_slot = 1

    set_code = Op.SSTORE(success_slot, 1) + Op.STOP
    set_code_to_address = pre.deploy_contract(set_code)

    authorization_tuple = AuthorizationTuple(
        address=set_code_to_address,
        nonce=0,
        chain_id=1,
        v=v,
        r=r,
        s=s,
    )

    auth_signer = authorization_tuple.signer

    tx = Transaction(
        gas_limit=100_000,
        to=auth_signer,
        value=0,
        authorization_list=[authorization_tuple],
        sender=pre.fund_eoa(),
    )

    state_test(
        env=Environment(),
        pre=pre,
        tx=tx,
        post={
            auth_signer: Account(
                storage={success_slot: 1},
            ),
        },
    )


# TODO: invalid RLP in the rest of the authority tuple fields
@pytest.mark.parametrize(
    "v,r,s",
    [
        pytest.param(2, 1, 1, id="v=2,r=1,s=1"),
        pytest.param(1, 0, 1, id="v=1,r=0,s=1"),
        pytest.param(1, 1, 0, id="v=1,r=1,s=0"),
        pytest.param(
            0,
            SECP256K1N,
            1,
            id="v=0,r=SECP256K1N,s=1",
        ),
        pytest.param(
            0,
            SECP256K1N - 1,
            1,
            id="v=0,r=SECP256K1N-1,s=1",
        ),
        pytest.param(
            0,
            1,
            SECP256K1N_OVER_2 + 1,
            id="v=0,r=1,s=SECP256K1N_OVER_2+1",
        ),
        pytest.param(
            2**256 - 1,
            1,
            1,
            id="v=2**256-1,r=1,s=1",
        ),
        pytest.param(
            0,
            1,
            2**256 - 1,
            id="v=0,r=1,s=2**256-1",
        ),
        pytest.param(
            1,
            2**256 - 1,
            1,
            id="v=1,r=2**256-1,s=1",
        ),
    ],
)
def test_set_code_using_invalid_signatures(
    state_test: StateTestFiller,
    pre: Alloc,
    v: int,
    r: int,
    s: int,
):
    """
    Test sending a transaction to set the code of an account using synthetic signatures.
    """
    success_slot = 1

    callee_code = Op.SSTORE(success_slot, 1) + Op.STOP
    callee_address = pre.deploy_contract(callee_code)

    authorization_tuple = AuthorizationTuple(
        address=0,
        nonce=0,
        chain_id=1,
        v=v,
        r=r,
        s=s,
    )

    tx = Transaction(
        gas_limit=100_000,
        to=callee_address,
        value=0,
        authorization_list=[authorization_tuple],
        error=TransactionException.TYPE_4_INVALID_AUTHORITY_SIGNATURE,
        sender=pre.fund_eoa(),
    )

    state_test(
        env=Environment(),
        pre=pre,
        tx=tx,
        post={
            callee_address: Account(
                storage={success_slot: 0},
            ),
        },
    )


@pytest.mark.parametrize(
    "log_opcode",
    [
        Op.LOG0,
        Op.LOG1,
        Op.LOG2,
        Op.LOG3,
        Op.LOG4,
    ],
)
@pytest.mark.with_all_evm_code_types
def test_set_code_to_log(
    state_test: StateTestFiller,
    pre: Alloc,
    log_opcode: Op,
):
    """
    Test setting the code of an account to a contract that performs the log operation.
    """
    sender = pre.fund_eoa()

    set_to_code = (
        Op.MSTORE(0, 0x1234)
        + log_opcode(size=32, topic_1=1, topic_2=2, topic_3=3, topic_4=4)
        + Op.STOP
    )
    set_to_address = pre.deploy_contract(set_to_code)

    tx = Transaction(
        gas_limit=10_000_000,
        to=sender,
        value=0,
        authorization_list=[
            AuthorizationTuple(
                address=set_to_address,
                nonce=1,
                signer=sender,
            ),
        ],
        sender=sender,
    )

    state_test(
        env=Environment(),
        pre=pre,
        tx=tx,
        post={},
    )


@pytest.mark.with_all_call_opcodes(
    lambda opcode: opcode
    not in [Op.STATICCALL, Op.CALLCODE, Op.DELEGATECALL, Op.EXTDELEGATECALL, Op.EXTSTATICCALL]
)
@pytest.mark.with_all_precompiles
def test_set_code_to_precompile(
    state_test: StateTestFiller,
    pre: Alloc,
    precompile: int,
    call_opcode: Op,
):
    """
    Test setting the code of an account to a pre-compile address.
    """
    auth_signer = pre.fund_eoa(auth_account_start_balance)

    caller_code_storage = Storage()
    caller_code = (
        Op.SSTORE(caller_code_storage.store_next(True), call_opcode(address=auth_signer))
        + Op.SSTORE(caller_code_storage.store_next(0), Op.RETURNDATASIZE)
        + Op.STOP
    )
    caller_code_address = pre.deploy_contract(caller_code)

    tx = Transaction(
        sender=pre.fund_eoa(),
        gas_limit=500_000,
        to=caller_code_address,
        authorization_list=[
            AuthorizationTuple(
                address=Address(precompile),
                nonce=0,
                signer=auth_signer,
            ),
        ],
    )

    state_test(
        env=Environment(),
        pre=pre,
        tx=tx,
        post={
            auth_signer: Account(
                nonce=1,
                code=b"",
            ),
            caller_code_address: Account(
                storage=caller_code_storage,
            ),
        },
    )


@pytest.mark.with_all_call_opcodes(
    lambda opcode: opcode
    not in [Op.STATICCALL, Op.CALLCODE, Op.DELEGATECALL, Op.EXTDELEGATECALL, Op.EXTSTATICCALL]
)
@pytest.mark.with_all_system_contracts
def test_set_code_to_system_contract(
    blockchain_test: BlockchainTestFiller,
    pre: Alloc,
    system_contract: int,
    call_opcode: Op,
):
    """
    Test setting the code of an account to a pre-compile address.
    """
    auth_signer = pre.fund_eoa(auth_account_start_balance)

    caller_code_storage = Storage()
    call_return_code_slot = caller_code_storage.store_next(True)
    call_return_data_size_slot = caller_code_storage.store_next(0)
    caller_code = (
        Op.SSTORE(call_return_code_slot, call_opcode(address=auth_signer))
        + Op.SSTORE(call_return_data_size_slot, Op.RETURNDATASIZE)
        + Op.STOP
    )
    txs: List[Transaction] = []
    match system_contract:
        case Address(0x000F3DF6D732807EF1319FB7B8BB8522D0BEAC02):  # EIP-4788
            caller_payload = Hash(0)
            caller_code_storage[call_return_data_size_slot] = 0
        case Address(0x00000000219AB540356CBB839CBE05303D7705FA):  # EIP-6110
            caller_payload = Hash(0)
            caller_code_storage[call_return_data_size_slot] = 0
        case Address(0x00A3CA265EBCB825B45F985A16CEFB49958CE017):  # EIP-7002
            caller_payload = Hash(0)
            caller_code_storage[call_return_data_size_slot] = 0
        case Address(0x00B42DBF2194E931E80326D950320F7D9DBEAC02):  # EIP-7251
            caller_payload = Hash(0)
            caller_code_storage[call_return_data_size_slot] = 0
        case Address(0x0AAE40965E6800CD9B1F4B05FF21581047E3F91E):  # EIP-2935
            caller_payload = Hash(0)
            caller_code_storage[call_return_data_size_slot] = 0
        case _:
            raise ValueError(f"Unsupported system contract: {system_contract}")

    caller_code_address = pre.deploy_contract(caller_code)

    txs += [
        Transaction(
            sender=pre.fund_eoa(),
            gas_limit=500_000,
            to=caller_code_address,
            data=caller_payload,
            authorization_list=[
                AuthorizationTuple(
                    address=Address(system_contract),
                    nonce=0,
                    signer=auth_signer,
                ),
            ],
        )
    ]

    blockchain_test(
        pre=pre,
        blocks=[Block(txs=txs)],
        post={
            auth_signer: Account(
                nonce=1,
                code=b"",
            ),
            caller_code_address: Account(
                storage=caller_code_storage,
            ),
        },
    )
