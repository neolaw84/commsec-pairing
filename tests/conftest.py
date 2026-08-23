"""Shared test fixtures for commsec-pairing."""

from datetime import date

import pytest

from commsec_pairing.models import (
    ParsedTrade,
    PersistentMappingStore,
    TradeAction,
    Transaction,
)


@pytest.fixture
def sample_buy_tx():
    return Transaction(
        date=date(2022, 1, 19),
        reference="C128785129",
        details="B 16 A200 @ 122.000000",
        debit=1952.00,
        balance=0.0,
        parsed_trade=ParsedTrade(
            action=TradeAction.BUY,
            units=16,
            security="A200",
            unit_price=122.00,
        ),
    )


@pytest.fixture
def sample_sell_tx():
    return Transaction(
        date=date(2024, 8, 9),
        reference="C154257363",
        details="S 16 A200 @ 135.000000",
        credit=2160.00,
        balance=0.0,
        parsed_trade=ParsedTrade(
            action=TradeAction.SELL,
            units=16,
            security="A200",
            unit_price=135.00,
        ),
    )


@pytest.fixture
def empty_store():
    return PersistentMappingStore(entity="test_entity")
