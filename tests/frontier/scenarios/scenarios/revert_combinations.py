"""
Define Scenario that will run a given program and then revert
"""

from typing import List

from ethereum_test_tools.vm.opcode import Macro
from ethereum_test_tools.vm.opcode import Macros as Om
from ethereum_test_tools.vm.opcode import Opcode
from ethereum_test_tools.vm.opcode import Opcodes as Op

from ..common import Scenario, ScenarioEnvironment, ScenarioGeneratorInput


def scenarios_revert_combinations(input: ScenarioGeneratorInput) -> List[Scenario]:
    """Generate Scenarios for revert combinations"""
    list: List[Scenario] = []
    keep_gas = 100000
    # TODO stack underflow cause
    revert_types: List[Opcode | Macro] = [Op.STOP, Om.OOG]
    if Op.REVERT in input.fork.valid_opcodes():
        revert_types.append(Op.REVERT)
    for revert in revert_types:
        operation_contract = input.pre.deploy_contract(code=input.operation_code)
        scenario_contract = input.pre.deploy_contract(
            code=Op.CALLCODE(gas=Op.SUB(Op.GAS, keep_gas), address=operation_contract, ret_size=32)
            + revert(0, 32, unchecked=True)
            + Op.RETURN(0, 32)
        )
        env: ScenarioEnvironment = ScenarioEnvironment(
            code_address=scenario_contract,
            code_caller=scenario_contract,
            selfbalance=0,
            ext_balance=input.external_balance,
            call_value=0,
            call_dataload_0=0,
            call_datasize=0,
        )
        list.append(
            Scenario(
                name=f"scenario_revert_by_{revert}",
                code=scenario_contract,
                env=env,
                halts=False if revert == Op.REVERT else True,
            )
        )

    return list
