"""Tests for models, persistent mapping storage, and unit conservation."""

from datetime import date

import pytest

from commsec_pairing.models import (
    MatchLeg,
    MatchRecord,
    ParsedTrade,
    TradeAction,
    Transaction,
)
from commsec_pairing.storage import MappingStorageManager


def test_persistent_storage_sync_and_match(tmp_path):
    storage_file = tmp_path / "mapping.json"
    manager = MappingStorageManager(storage_file, "commsec-test")
    store = manager.load_or_create()

    # Create 2 buy transactions
    txs = [
        Transaction(
            date=date(2022, 1, 19),
            reference="C128785129",
            details="B 16 A200 @ 122.00",
            parsed_trade=ParsedTrade(
                action=TradeAction.BUY, units=16, security="A200", unit_price=122.0
            ),
        ),
        Transaction(
            date=date(2022, 3, 4),
            reference="C130687745",
            details="B 50 VDHG @ 60.00",
            parsed_trade=ParsedTrade(
                action=TradeAction.BUY, units=50, security="VDHG", unit_price=60.0
            ),
        ),
    ]

    store = manager.sync_inventory_from_transactions(store, txs)
    assert len(store.buy_inventory) == 2
    assert store.buy_inventory[0].remaining_units == 16
    assert store.buy_inventory[1].remaining_units == 50

    # Record a match of 10 units from C128785129
    match1 = MatchRecord(
        match_id="m1",
        financial_year=2024,
        security="A200",
        matched_units=10,
        buy=MatchLeg(
            contract_ref="C128785129",
            trade_date=date(2022, 1, 19),
            unit_price_aud=122.0,
        ),
        sell=MatchLeg(
            contract_ref="C150000000",
            trade_date=date(2024, 1, 15),
            unit_price_aud=135.0,
        ),
        holding_period_days=726,
        cgt_discount_eligible=True,
        gross_gain_loss_aud=130.0,
        taxable_gain_loss_aud=65.0,
    )

    manager.record_match(store, match1)
    assert store.buy_inventory[0].matched_units == 10
    assert store.buy_inventory[0].remaining_units == 6
    assert not store.buy_inventory[0].is_exhausted

    # Attempt to match 10 more units when only 6 remain (must fail unit conservation)
    match2 = MatchRecord(
        match_id="m2",
        financial_year=2024,
        security="A200",
        matched_units=10,
        buy=MatchLeg(
            contract_ref="C128785129",
            trade_date=date(2022, 1, 19),
            unit_price_aud=122.0,
        ),
        sell=MatchLeg(
            contract_ref="C150000001",
            trade_date=date(2024, 2, 15),
            unit_price_aud=136.0,
        ),
        holding_period_days=757,
        cgt_discount_eligible=True,
        gross_gain_loss_aud=140.0,
        taxable_gain_loss_aud=70.0,
    )

    with pytest.raises(ValueError, match="Insufficient units"):
        manager.record_match(store, match2)

    # Save to disk and reload
    manager.save(store)
    reloaded_store = manager.load_or_create()
    assert len(reloaded_store.matches) == 1
    assert reloaded_store.buy_inventory[0].remaining_units == 6
