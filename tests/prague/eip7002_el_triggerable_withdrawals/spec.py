"""
Common procedures to test
[EIP-7002: Execution layer triggerable withdrawals](https://eips.ethereum.org/EIPS/eip-7002)
"""  # noqa: E501

from dataclasses import dataclass

from ethereum_test_addresses import SYSTEM_ADDRESS, SystemContract


@dataclass(frozen=True)
class ReferenceSpec:
    """
    Defines the reference spec version and git path.
    """

    git_path: str
    version: str


ref_spec_7002 = ReferenceSpec("EIPS/eip-7002.md", "9fe721f56f45bd5cf2d2958c0e6867aa81f82ebc")


# Constants
@dataclass(frozen=True)
class Spec:
    """
    Parameters from the EIP-7002 specifications as defined at
    https://eips.ethereum.org/EIPS/eip-7002#configuration

    If the parameter is not currently used within the tests, it is commented
    out.
    """

    WITHDRAWAL_REQUEST_PREDEPLOY_ADDRESS = SystemContract.WITHDRAWAL_REQUESTS
    SYSTEM_ADDRESS = SYSTEM_ADDRESS

    EXCESS_WITHDRAWAL_REQUESTS_STORAGE_SLOT = 0
    WITHDRAWAL_REQUEST_COUNT_STORAGE_SLOT = 1
    WITHDRAWAL_REQUEST_QUEUE_HEAD_STORAGE_SLOT = (
        2  # Pointer to head of the withdrawal request message queue
    )
    WITHDRAWAL_REQUEST_QUEUE_TAIL_STORAGE_SLOT = (
        3  # Pointer to the tail of the withdrawal request message queue
    )
    WITHDRAWAL_REQUEST_QUEUE_STORAGE_OFFSET = (
        4  # The start memory slot of the in-state withdrawal request message queue
    )
    MAX_WITHDRAWAL_REQUESTS_PER_BLOCK = (
        16  # Maximum number of withdrawal requests that can be de-queued into a block
    )
    TARGET_WITHDRAWAL_REQUESTS_PER_BLOCK = 2
    MIN_WITHDRAWAL_REQUEST_FEE = 1
    WITHDRAWAL_REQUEST_FEE_UPDATE_FRACTION = 17
    EXCESS_RETURN_GAS_STIPEND = 2300

    MAX_AMOUNT = 2**64 - 1

    @staticmethod
    def fake_exponential(factor: int, numerator: int, denominator: int) -> int:
        """
        Used to calculate the withdrawal request fee.
        """
        i = 1
        output = 0
        numerator_accumulator = factor * denominator
        while numerator_accumulator > 0:
            output += numerator_accumulator
            numerator_accumulator = (numerator_accumulator * numerator) // (denominator * i)
            i += 1
        return output // denominator

    @staticmethod
    def get_fee(excess_withdrawal_requests: int) -> int:
        """
        Calculate the fee for the excess withdrawal requests.
        """
        return Spec.fake_exponential(
            Spec.MIN_WITHDRAWAL_REQUEST_FEE,
            excess_withdrawal_requests,
            Spec.WITHDRAWAL_REQUEST_FEE_UPDATE_FRACTION,
        )

    @staticmethod
    def get_excess_withdrawal_requests(previous_excess: int, count: int) -> int:
        """
        Calculate the new excess withdrawal requests.
        """
        if previous_excess + count > Spec.TARGET_WITHDRAWAL_REQUESTS_PER_BLOCK:
            return previous_excess + count - Spec.TARGET_WITHDRAWAL_REQUESTS_PER_BLOCK
        return 0
