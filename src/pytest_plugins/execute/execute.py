"""
Test execution plugin for pytest, to run Ethereum tests using in live networks.
"""

import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Generator, List, Type

import pytest
from pytest_metadata.plugin import metadata_key  # type: ignore

from ethereum_test_base_types import Number
from ethereum_test_execution import BaseExecute, ExecuteFormats
from ethereum_test_forks import (
    Fork,
    Frontier,
    get_closest_fork_with_solc_support,
    get_forks_with_solc_support,
)
from ethereum_test_rpc import EthRPC
from ethereum_test_tools import SPEC_TYPES, BaseTest, TestInfo, Transaction, Yul
from ethereum_test_tools.code import Solc
from ethereum_test_types import TransactionDefaults
from pytest_plugins.spec_version_checker.spec_version_checker import EIPSpecTestItem

from .pre_alloc import Alloc


def default_html_report_file_path() -> str:
    """
    The default file to store the generated HTML test report. Defined as a
    function to allow for easier testing.
    """
    return "./execution_results/report_execute.html"


def pytest_addoption(parser):
    """
    Adds command-line options to pytest.
    """
    execute_group = parser.getgroup("execute", "Arguments defining test execution behavior")
    execute_group.addoption(
        "--default-gas-price",
        action="store",
        dest="default_gas_price",
        type=int,
        default=10**9,
        help=("Default gas price used for transactions, unless overridden by the test."),
    )
    execute_group.addoption(
        "--default-max-fee-per-gas",
        action="store",
        dest="default_max_fee_per_gas",
        type=int,
        default=10**9,
        help=("Default max fee per gas used for transactions, unless overridden by the test."),
    )
    execute_group.addoption(
        "--default-max-priority-fee-per-gas",
        action="store",
        dest="default_max_priority_fee_per_gas",
        type=int,
        default=10**9,
        help=(
            "Default max priority fee per gas used for transactions, "
            "unless overridden by the test."
        ),
    )

    report_group = parser.getgroup("tests", "Arguments defining html report behavior")
    report_group.addoption(
        "--no-html",
        action="store_true",
        dest="disable_html",
        default=False,
        help=(
            "Don't generate an HTML test report. "
            "The --html flag can be used to specify a different path."
        ),
    )


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    """
    Pytest hook called after command line options have been parsed and before
    test collection begins.

    Couple of notes:
    1. Register the plugin's custom markers and process command-line options.

        Custom marker registration:
        https://docs.pytest.org/en/7.1.x/how-to/writing_plugins.html#registering-custom-markers

    2. `@pytest.hookimpl(tryfirst=True)` is applied to ensure that this hook is
        called before the pytest-html plugin's pytest_configure to ensure that
        it uses the modified `htmlpath` option.
    """
    for execute_format in ExecuteFormats:
        config.addinivalue_line(
            "markers",
            (f"{execute_format.name.lower()}: {execute_format.description()}"),
        )
    config.addinivalue_line(
        "markers",
        "yul_test: a test case that compiles Yul code.",
    )
    config.addinivalue_line(
        "markers",
        "compile_yul_with(fork): Always compile Yul source using the corresponding evm version.",
    )
    config.addinivalue_line(
        "markers",
        "fill: Markers to be added in fill mode only.",
    )
    config.addinivalue_line(
        "markers",
        "execute: Markers to be added in execute mode only.",
    )
    if config.option.collectonly:
        return
    if config.getoption("disable_html") and config.getoption("htmlpath") is None:
        # generate an html report by default, unless explicitly disabled
        config.option.htmlpath = Path(default_html_report_file_path())
    config.solc_version = Solc(config.getoption("solc_bin")).version
    if config.solc_version < Frontier.solc_min_version():
        pytest.exit(
            f"Unsupported solc version: {config.solc_version}. Minimum required version is "
            f"{Frontier.solc_min_version()}",
            returncode=pytest.ExitCode.USAGE_ERROR,
        )

    config.stash[metadata_key]["Tools"] = {
        "solc": str(config.solc_version),
    }
    command_line_args = "fill " + " ".join(config.invocation_params.args)
    config.stash[metadata_key]["Command-line args"] = f"<code>{command_line_args}</code>"


@pytest.hookimpl(trylast=True)
def pytest_report_header(config, start_path):
    """Add lines to pytest's console output header"""
    if config.option.collectonly:
        return
    solc_version = config.stash[metadata_key]["Tools"]["solc"]
    return [(f"{solc_version}")]


def pytest_metadata(metadata):
    """
    Add or remove metadata to/from the pytest report.
    """
    metadata.pop("JAVA_HOME", None)


def pytest_html_results_table_header(cells):
    """
    Customize the table headers of the HTML report table.
    """
    cells.insert(3, '<th class="sortable" data-column-type="sender">Sender</th>')
    cells.insert(4, '<th class="sortable" data-column-type="fundedAccounts">Funded Accounts</th>')
    cells.insert(
        5, '<th class="sortable" data-column-type="fundedAccounts">Deployed Contracts</th>'
    )
    del cells[-1]  # Remove the "Links" column


def pytest_html_results_table_row(report, cells):
    """
    Customize the table rows of the HTML report table.
    """
    if hasattr(report, "user_properties"):
        user_props = dict(report.user_properties)
        if "sender_address" in user_props and user_props["sender_address"] is not None:
            sender_address = user_props["sender_address"]
            cells.insert(3, f"<td>{sender_address}</td>")
        else:
            cells.insert(3, "<td>Not available</td>")

        if "funded_accounts" in user_props and user_props["funded_accounts"] is not None:
            funded_accounts = user_props["funded_accounts"]
            cells.insert(4, f"<td>{funded_accounts}</td>")
        else:
            cells.insert(4, "<td>Not available</td>")

    del cells[-1]  # Remove the "Links" column


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """
    This hook is called when each test is run and a report is being made.

    Make each test's fixture json path available to the test report via
    user_properties.
    """
    outcome = yield
    report = outcome.get_result()

    if call.when == "call":
        for property_name in ["sender_address", "funded_accounts"]:
            if hasattr(item.config, property_name):
                report.user_properties.append((property_name, getattr(item.config, property_name)))


def pytest_html_report_title(report):
    """
    Set the HTML report title (pytest-html plugin).
    """
    report.title = "Execute Test Report"


@pytest.fixture(autouse=True, scope="session")
def solc_bin(request):
    """
    Returns the configured solc binary path.
    """
    return request.config.getoption("solc_bin")


@pytest.fixture(scope="session")
def default_gas_price(request) -> int:
    """
    Returns the default gas price used for transactions.
    """
    return request.config.getoption("default_gas_price")


@pytest.fixture(scope="session")
def default_max_fee_per_gas(request) -> int:
    """
    Returns the default max fee per gas used for transactions.
    """
    return request.config.getoption("default_max_fee_per_gas")


@pytest.fixture(scope="session")
def default_max_priority_fee_per_gas(request) -> int:
    """
    Returns the default max priority fee per gas used for transactions.
    """
    return request.config.getoption("default_max_priority_fee_per_gas")


@pytest.fixture(autouse=True, scope="session")
def modify_transaction_defaults(
    default_gas_price: int, default_max_fee_per_gas: int, default_max_priority_fee_per_gas: int
):
    """
    Modify transaction defaults to values better suited for live networks.
    """
    TransactionDefaults.gas_price = default_gas_price
    TransactionDefaults.max_fee_per_gas = default_max_fee_per_gas
    TransactionDefaults.max_priority_fee_per_gas = default_max_priority_fee_per_gas


@dataclass(kw_only=True)
class Collector:
    """
    A class that collects transactions and post-allocations for every test case.
    """

    eth_rpc: EthRPC
    collected_tests: Dict[str, BaseExecute] = field(default_factory=dict)

    def collect(self, test_name: str, execute_format: BaseExecute):
        """
        Collects the transactions and post-allocations for the test case.
        """
        self.collected_tests[test_name] = execute_format


@pytest.fixture(scope="session")
def collector(
    request,
    eth_rpc: EthRPC,
) -> Generator[Collector, None, None]:
    """
    Returns the configured fixture collector instance used for all tests
    in one test module.
    """
    collector = Collector(eth_rpc=eth_rpc)
    yield collector


@pytest.fixture(autouse=True)
def eips():
    """
    A fixture specifying that, by default, no EIPs should be activated for
    tests.

    This fixture (function) may be redefined in test filler modules in order
    to overwrite this default and return a list of integers specifying which
    EIPs should be activated for the tests in scope.
    """
    return []


@pytest.fixture
def yul(fork: Fork, request):
    """
    A fixture that allows contract code to be defined with Yul code.

    This fixture defines a class that wraps the ::ethereum_test_tools.Yul
    class so that upon instantiation within the test case, it provides the
    test case's current fork parameter. The forks is then available for use
    in solc's arguments for the Yul code compilation.

    Test cases can override the default value by specifying a fixed version
    with the @pytest.mark.compile_yul_with(FORK) marker.
    """
    solc_target_fork: Fork | None
    marker = request.node.get_closest_marker("compile_yul_with")
    if marker:
        if not marker.args[0]:
            pytest.fail(
                f"{request.node.name}: Expected one argument in 'compile_yul_with' marker."
            )
        for fork in request.config.forks:
            if fork.name() == marker.args[0]:
                solc_target_fork = fork
                break
        else:
            pytest.fail(f"{request.node.name}: Fork {marker.args[0]} not found in forks list.")
        assert solc_target_fork in get_forks_with_solc_support(request.config.solc_version)
    else:
        solc_target_fork = get_closest_fork_with_solc_support(fork, request.config.solc_version)
        assert solc_target_fork is not None, "No fork supports provided solc version."
        if solc_target_fork != fork and request.config.getoption("verbose") >= 1:
            warnings.warn(f"Compiling Yul for {solc_target_fork.name()}, not {fork.name()}.")

    class YulWrapper(Yul):
        def __new__(cls, *args, **kwargs):
            return super(YulWrapper, cls).__new__(cls, *args, **kwargs, fork=solc_target_fork)

    return YulWrapper


SPEC_TYPES_PARAMETERS: List[str] = [s.pytest_parameter_name() for s in SPEC_TYPES]


def node_to_test_info(node) -> TestInfo:
    """
    Returns the test info of the current node item.
    """
    return TestInfo(
        name=node.name,
        id=node.nodeid,
        original_name=node.originalname,
        path=Path(node.path),
    )


@pytest.fixture(scope="function")
def fixture_description(request):
    """Fixture to extract and combine docstrings from the test class and the test function."""
    description_unavailable = (
        "No description available - add a docstring to the python test class or function."
    )
    test_class_doc = f"Test class documentation:\n{request.cls.__doc__}" if request.cls else ""
    test_function_doc = (
        f"Test function documentation:\n{request.function.__doc__}"
        if request.function.__doc__
        else ""
    )
    if not test_class_doc and not test_function_doc:
        return description_unavailable
    combined_docstring = f"{test_class_doc}\n\n{test_function_doc}".strip()
    return combined_docstring


def base_test_parametrizer(cls: Type[BaseTest]):
    """
    Generates a pytest.fixture for a given BaseTest subclass.

    Implementation detail: All spec fixtures must be scoped on test function level to avoid
    leakage between tests.
    """

    @pytest.fixture(
        scope="function",
        name=cls.pytest_parameter_name(),
    )
    def base_test_parametrizer_func(
        request: Any,
        fork: Fork,
        pre: Alloc,
        eips: List[int],
        eth_rpc: EthRPC,
        collector: Collector,
        default_gas_price: int,
    ):
        """
        Fixture used to instantiate an auto-fillable BaseTest object from within
        a test function.

        Every test that defines a test filler must explicitly specify its parameter name
        (see `pytest_parameter_name` in each implementation of BaseTest) in its function
        arguments.

        When parametrize, indirect must be used along with the fixture format as value.
        """
        execute_format = request.param
        assert isinstance(execute_format, ExecuteFormats)

        class BaseTestWrapper(cls):  # type: ignore
            def __init__(self, *args, **kwargs):
                kwargs["t8n_dump_dir"] = None
                if "pre" not in kwargs:
                    kwargs["pre"] = pre
                elif kwargs["pre"] != pre:
                    raise ValueError("The pre-alloc object was modified by the test.")

                request.node.config.sender_address = str(pre._sender)

                super(BaseTestWrapper, self).__init__(*args, **kwargs)

                # wait for pre-requisite transactions to be included in blocks
                pre.wait_for_transactions()
                for deployed_contract, deployed_code in pre._deployed_contracts:

                    if eth_rpc.get_code(deployed_contract) == deployed_code:
                        pass
                    else:
                        raise Exception(
                            f"Deployed test contract didn't match expected code at address "
                            f"{deployed_contract} (not enough gas_limit?)."
                        )
                request.node.config.funded_accounts = ", ".join(
                    [str(eoa) for eoa in pre._funded_eoa]
                )

                execute = self.execute(fork=fork, execute_format=execute_format, eips=eips)
                execute.execute(eth_rpc)
                collector.collect(request.node.nodeid, execute)

        sender_start_balance = eth_rpc.get_balance(pre._sender)

        yield BaseTestWrapper

        # Refund all EOAs (regardless of whether the test passed or failed)
        refund_txs = []
        for eoa in pre._funded_eoa:
            remaining_balance = eth_rpc.get_balance(eoa)
            eoa.nonce = Number(eth_rpc.get_transaction_count(eoa))
            refund_gas_limit = 21_000
            tx_cost = refund_gas_limit * default_gas_price
            if remaining_balance < tx_cost:
                continue
            refund_txs.append(
                Transaction(
                    sender=eoa,
                    to=pre._sender,
                    gas_limit=21_000,
                    gas_price=default_gas_price,
                    value=remaining_balance - tx_cost,
                ).with_signature_and_sender()
            )
        eth_rpc.send_wait_transactions(refund_txs)

        sender_end_balance = eth_rpc.get_balance(pre._sender)
        used_balance = sender_start_balance - sender_end_balance
        print(f"Used balance={used_balance / 10**18:.18f}")

    return base_test_parametrizer_func


# Dynamically generate a pytest fixture for each test spec type.
for cls in SPEC_TYPES:
    # Fixture needs to be defined in the global scope so pytest can detect it.
    globals()[cls.pytest_parameter_name()] = base_test_parametrizer(cls)


def pytest_generate_tests(metafunc: pytest.Metafunc):
    """
    Pytest hook used to dynamically generate test cases for each fixture format a given
    test spec supports.
    """
    for test_type in SPEC_TYPES:
        if test_type.pytest_parameter_name() in metafunc.fixturenames:
            metafunc.parametrize(
                [test_type.pytest_parameter_name()],
                [
                    pytest.param(
                        execute_format,
                        id=execute_format.name.lower(),
                        marks=[getattr(pytest.mark, execute_format.name.lower())],
                    )
                    for execute_format in test_type.supported_execute_formats
                ],
                scope="function",
                indirect=True,
            )


def pytest_collection_modifyitems(config: pytest.Config, items: List[pytest.Item]):
    """
    Remove pre-Paris tests parametrized to generate hive type fixtures; these
    can't be used in the Hive Pyspec Simulator.

    This can't be handled in this plugins pytest_generate_tests() as the fork
    parametrization occurs in the forks plugin.
    """
    for item in items[:]:  # use a copy of the list, as we'll be modifying it
        if isinstance(item, EIPSpecTestItem):
            continue
        for marker in item.iter_markers():
            if marker.name == "execute":
                for mark in marker.args:
                    item.add_marker(mark)
            elif marker.name == "valid_at_transition_to":
                item.add_marker(pytest.mark.skip(reason="transition tests not executable"))
        if "yul" in item.fixturenames:  # type: ignore
            item.add_marker(pytest.mark.yul_test)


def pytest_make_parametrize_id(config, val, argname):
    """
    Pytest hook called when generating test ids. We use this to generate
    more readable test ids for the generated tests.
    """
    return f"{argname}_{val}"


def pytest_runtest_call(item):
    """
    Pytest hook called in the context of test execution.
    """
    if isinstance(item, EIPSpecTestItem):
        return

    class InvalidFiller(Exception):
        def __init__(self, message):
            super().__init__(message)

    if "state_test" in item.fixturenames and "blockchain_test" in item.fixturenames:
        raise InvalidFiller(
            "A filler should only implement either a state test or " "a blockchain test; not both."
        )

    # Check that the test defines either test type as parameter.
    if not any([i for i in item.funcargs if i in SPEC_TYPES_PARAMETERS]):
        pytest.fail(
            "Test must define either one of the following parameters to "
            + "properly generate a test: "
            + ", ".join(SPEC_TYPES_PARAMETERS)
        )
