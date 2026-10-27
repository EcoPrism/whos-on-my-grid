import os

# Before any app import: Settings is cached at first use.
os.environ["GRID_LLM_PROVIDER"] = "fake"
os.environ["GRID_BRIEF_SOURCE"] = "fixtures"

import pytest  # noqa: E402


def pytest_addoption(parser) -> None:
    """`live` tests cost real tokens, so they need an explicit opt-in on top
    of the `-m live` selection in pyproject's addopts."""
    parser.addoption(
        "--run-live",
        action="store_true",
        default=False,
        help="run tests marked `live` against the real LLM endpoints",
    )


def pytest_collection_modifyitems(config, items) -> None:
    if config.getoption("--run-live"):
        return
    skip = pytest.mark.skip(reason="needs --run-live (real model call, costs tokens)")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)
