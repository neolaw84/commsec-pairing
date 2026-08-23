"""Tests for CGT minimization bipartite matching solver and strategies."""

from datetime import date

import pytest

from commsec_pairing.matcher import CGTMatcher, calculate_cgt_unit_cost, get_financial_year
from commsec_pairing.models import (
    MatchingStrategy,
    ParsedTrade,
    TradeAction,
    Transaction,
)
from commsec_pairing.storage import MappingStorageManager


def test_get_financial_year():
    assert get_financial_year(date(2025, 6, 30)) == 2025
    assert get_financial_year(date(2025, 7, 1)) == 2026
    assert get_financial_year(date(2026, 1, 15)) == 2026


def test_calculate_cgt_unit_cost():
    # Long term gain (> 365 days) -> 50% discount
    days, discount, gross, taxable = calculate_cgt_unit_cost(
        buy_unit_price=100.0,
        sell_unit_price=150.0,
        buy_date=date(2022, 1, 1),
        sell_date=date(2024, 1, 1),
    )
    assert days == 730
    assert discount is True
    assert gross == 50.0
    assert taxable == 25.0

    # Short term gain (<= 365 days) -> 100% taxable
    days, discount, gross, taxable = calculate_cgt_unit_cost(
        buy_unit_price=100.0,
        sell_unit_price=150.0,
        buy_date=date(2024, 1, 1),
        sell_date=date(2024, 6, 1),
    )
    assert discount is False
    assert gross == 50.0
    assert taxable == 50.0

    # Capital loss -> 100% loss offsets
    days, discount, gross, taxable = calculate_cgt_unit_cost(
        buy_unit_price=100.0,
        sell_unit_price=80.0,
        buy_date=date(2022, 1, 1),
        sell_date=date(2024, 1, 1),
    )
    assert gross == -20.0
    assert taxable == -20.0


def test_temporal_validation_prevents_future_buys():
    # Attempting to calculate cost with buy date after sell date must raise ValueError
    with pytest.raises(ValueError, match="Temporal violation"):
        calculate_cgt_unit_cost(
            buy_unit_price=100.0,
            sell_unit_price=150.0,
            buy_date=date(2025, 1, 1),
            sell_date=date(2024, 1, 1),
        )


def test_cgt_matcher_optimal_selection(tmp_path):
    storage_file = tmp_path / "mapping.json"
    manager = MappingStorageManager(storage_file, "commsec-test")
    store = manager.load_or_create()

    # Two buy lots:
    # Lot A: 10 units at $100 bought 2 years ago (taxable gain: ($150-$100)*0.5 = $25/unit)
    # Lot B: 10 units at $140 bought 6 months ago (taxable gain: ($150-$140)*1.0 = $10/unit)
    # Sell: 10 units at $150
    # Optimal choice: Lot B ($100 total taxable gain vs $250)
    txs = [
        Transaction(
            date=date(2022, 1, 1),
            reference="C_BUY_A",
            details="B 10 A200 @ 100.0",
            parsed_trade=ParsedTrade(
                action=TradeAction.BUY, units=10, security="A200", unit_price=100.0
            ),
        ),
        Transaction(
            date=date(2024, 1, 1),
            reference="C_BUY_B",
            details="B 10 A200 @ 140.0",
            parsed_trade=ParsedTrade(
                action=TradeAction.BUY, units=10, security="A200", unit_price=140.0
            ),
        ),
        Transaction(
            date=date(2024, 6, 1),  # FY 2024
            reference="C_SELL_1",
            details="S 10 A200 @ 150.0",
            parsed_trade=ParsedTrade(
                action=TradeAction.SELL, units=10, security="A200", unit_price=150.0
            ),
        ),
    ]

    store = manager.sync_inventory_from_transactions(store, txs)
    matcher = CGTMatcher(store)
    matches = matcher.optimize_financial_year(txs, target_fy=2024, strategy=MatchingStrategy.GRANULAR)

    assert len(matches) == 1
    assert matches[0].buy.contract_ref == "C_BUY_B"
    assert matches[0].matched_units == 10
    assert matches[0].taxable_gain_loss_aud == 100.0
    assert matches[0].strategy == MatchingStrategy.GRANULAR


def test_whole_buy_strategy(tmp_path):
    storage_file = tmp_path / "mapping.json"
    manager = MappingStorageManager(storage_file, "commsec-test")
    store = manager.load_or_create()

    # Three buy lots: 10 units, 20 units, 30 units
    # Sell: 30 units
    # Whole Buy mode: must pick exactly one 30-unit buy lot or combination of intact lots (10+20)
    txs = [
        Transaction(
            date=date(2022, 1, 1),
            reference="C_BUY_10",
            details="B 10 A200 @ 100.0",
            parsed_trade=ParsedTrade(
                action=TradeAction.BUY, units=10, security="A200", unit_price=100.0
            ),
        ),
        Transaction(
            date=date(2022, 2, 1),
            reference="C_BUY_20",
            details="B 20 A200 @ 110.0",
            parsed_trade=ParsedTrade(
                action=TradeAction.BUY, units=20, security="A200", unit_price=110.0
            ),
        ),
        Transaction(
            date=date(2022, 3, 1),
            reference="C_BUY_30",
            details="B 30 A200 @ 130.0",
            parsed_trade=ParsedTrade(
                action=TradeAction.BUY, units=30, security="A200", unit_price=130.0
            ),
        ),
        Transaction(
            date=date(2024, 5, 1),
            reference="C_SELL_30",
            details="S 30 A200 @ 150.0",
            parsed_trade=ParsedTrade(
                action=TradeAction.SELL, units=30, security="A200", unit_price=150.0
            ),
        ),
    ]

    store = manager.sync_inventory_from_transactions(store, txs)
    matcher = CGTMatcher(store)
    matches = matcher.optimize_financial_year(txs, target_fy=2024, strategy=MatchingStrategy.WHOLE_BUY)

    # In whole-buy mode to minimize tax: C_BUY_30 ($130 unit price) minimizes gain ($150 - $130 = $20)
    assert len(matches) == 1
    assert matches[0].buy.contract_ref == "C_BUY_30"
    assert matches[0].matched_units == 30
    assert matches[0].strategy == MatchingStrategy.WHOLE_BUY


def test_multi_year_chaining_persistence(tmp_path):
    # Year 1 (FY 2023) mapping saved to mapping_fy23.json
    mapping_fy23_path = tmp_path / "mapping_fy23.json"
    mapping_fy24_path = tmp_path / "mapping_fy24.json"

    manager = MappingStorageManager(mapping_fy23_path, "commsec-test")
    store = manager.load_or_create()

    txs = [
        # Buy 50 units
        Transaction(
            date=date(2022, 1, 1),
            reference="C_BUY_50",
            details="B 50 A200 @ 100.0",
            parsed_trade=ParsedTrade(
                action=TradeAction.BUY, units=50, security="A200", unit_price=100.0
            ),
        ),
        # Sell 20 units in FY 2023
        Transaction(
            date=date(2023, 3, 1),
            reference="C_SELL_20",
            details="S 20 A200 @ 120.0",
            parsed_trade=ParsedTrade(
                action=TradeAction.SELL, units=20, security="A200", unit_price=120.0
            ),
        ),
        # Sell 30 units in FY 2024
        Transaction(
            date=date(2024, 3, 1),
            reference="C_SELL_30",
            details="S 30 A200 @ 140.0",
            parsed_trade=ParsedTrade(
                action=TradeAction.SELL, units=30, security="A200", unit_price=140.0
            ),
        ),
    ]

    store = manager.sync_inventory_from_transactions(store, txs)
    matcher = CGTMatcher(store)
    matches_fy23 = matcher.optimize_financial_year(txs, target_fy=2023)

    assert len(matches_fy23) == 1
    assert matches_fy23[0].matched_units == 20
    manager.record_match(store, matches_fy23[0])
    manager.save(store, custom_output_path=mapping_fy23_path)

    # Now simulate Year 2 (FY 2024) loading from mapping_fy23.json and outputting to mapping_fy24.json
    store_fy24 = manager.load_or_create(custom_input_path=mapping_fy23_path)
    store_fy24 = manager.sync_inventory_from_transactions(store_fy24, txs)

    # Remaining units in C_BUY_50 must be 30
    assert store_fy24.buy_inventory[0].remaining_units == 30
    assert store_fy24.buy_inventory[0].matched_units == 20

    matcher_fy24 = CGTMatcher(store_fy24)
    matches_fy24 = matcher_fy24.optimize_financial_year(txs, target_fy=2024)

    assert len(matches_fy24) == 1
    assert matches_fy24[0].matched_units == 30

    manager.record_match(store_fy24, matches_fy24[0])
    manager.save(store_fy24, custom_output_path=mapping_fy24_path)

    # Final verification of mapping_fy24.json
    final_store = manager.load_or_create(custom_input_path=mapping_fy24_path)
    assert len(final_store.matches) == 2
    assert final_store.buy_inventory[0].remaining_units == 0
    assert final_store.buy_inventory[0].is_exhausted is True


def test_fifo_matching_strategy(tmp_path):
    storage_file = tmp_path / "mapping.json"
    manager = MappingStorageManager(storage_file, "commsec-test")
    store = manager.load_or_create()

    # Buy Lot A: 2020-01-01, 10 units @ $50
    # Buy Lot B: 2021-01-01, 10 units @ $100
    # Buy Lot C: 2022-01-01, 10 units @ $140
    # Sell: 2024-01-01, 15 units @ $150
    # Under granular tax-minimization: chooses Lot C (10 units) + Lot B (5 units) to minimize gain
    # Under FIFO: must choose Lot A (10 units) first, then Lot B (5 units)
    txs = [
        Transaction(
            date=date(2020, 1, 1),
            reference="C_BUY_A",
            details="B 10 A200 @ 50.0",
            parsed_trade=ParsedTrade(
                action=TradeAction.BUY, units=10, security="A200", unit_price=50.0
            ),
        ),
        Transaction(
            date=date(2021, 1, 1),
            reference="C_BUY_B",
            details="B 10 A200 @ 100.0",
            parsed_trade=ParsedTrade(
                action=TradeAction.BUY, units=10, security="A200", unit_price=100.0
            ),
        ),
        Transaction(
            date=date(2022, 1, 1),
            reference="C_BUY_C",
            details="B 10 A200 @ 140.0",
            parsed_trade=ParsedTrade(
                action=TradeAction.BUY, units=10, security="A200", unit_price=140.0
            ),
        ),
        Transaction(
            date=date(2024, 1, 1),
            reference="C_SELL_15",
            details="S 15 A200 @ 150.0",
            parsed_trade=ParsedTrade(
                action=TradeAction.SELL, units=15, security="A200", unit_price=150.0
            ),
        ),
    ]

    store = manager.sync_inventory_from_transactions(store, txs)
    matcher = CGTMatcher(store)
    fifo_matches = matcher.optimize_financial_year(txs, target_fy=2024, strategy=MatchingStrategy.FIFO)

    assert len(fifo_matches) == 2
    # First match must be Lot A (10 units)
    assert fifo_matches[0].buy.contract_ref == "C_BUY_A"
    assert fifo_matches[0].matched_units == 10
    assert fifo_matches[0].strategy == MatchingStrategy.FIFO
    # Second match must be Lot B (5 units)
    assert fifo_matches[1].buy.contract_ref == "C_BUY_B"
    assert fifo_matches[1].matched_units == 5
    assert fifo_matches[1].strategy == MatchingStrategy.FIFO


def test_whole_buy_infeasible_error(tmp_path):
    storage_file = tmp_path / "mapping.json"
    manager = MappingStorageManager(storage_file, "entity-test")
    store = manager.load_or_create()

    # Buy lots: 10 units and 20 units
    # Sell lot: 25 units (impossible to form 25 with intact 10 and 20 lots)
    txs = [
        Transaction(
            date=date(2022, 1, 1),
            reference="C_BUY_10",
            details="B 10 A200 @ 100.0",
            parsed_trade=ParsedTrade(
                action=TradeAction.BUY, units=10, security="A200", unit_price=100.0
            ),
        ),
        Transaction(
            date=date(2022, 2, 1),
            reference="C_BUY_20",
            details="B 20 A200 @ 110.0",
            parsed_trade=ParsedTrade(
                action=TradeAction.BUY, units=20, security="A200", unit_price=110.0
            ),
        ),
        Transaction(
            date=date(2024, 5, 1),
            reference="C_SELL_25",
            details="S 25 A200 @ 150.0",
            parsed_trade=ParsedTrade(
                action=TradeAction.SELL, units=25, security="A200", unit_price=150.0
            ),
        ),
    ]

    store = manager.sync_inventory_from_transactions(store, txs)
    matcher = CGTMatcher(store)

    with pytest.raises(RuntimeError, match="Whole Buy Contract matching infeasible"):
        matcher.optimize_financial_year(txs, target_fy=2024, strategy=MatchingStrategy.WHOLE_BUY)


def test_whole_buy_safety_ceiling(tmp_path):
    storage_file = tmp_path / "mapping.json"
    manager = MappingStorageManager(storage_file, "entity-test")
    store = manager.load_or_create()

    # Generate 501 buy lots (exceeding MAX_WHOLE_BUY_LOTS = 500)
    txs = [
        Transaction(
            date=date(2022, 1, 1),
            reference=f"C_BUY_{i}",
            details="B 1 A200 @ 100.0",
            parsed_trade=ParsedTrade(
                action=TradeAction.BUY, units=1, security="A200", unit_price=100.0
            ),
        )
        for i in range(501)
    ]
    txs.append(
        Transaction(
            date=date(2024, 5, 1),
            reference="C_SELL_1",
            details="S 1 A200 @ 150.0",
            parsed_trade=ParsedTrade(
                action=TradeAction.SELL, units=1, security="A200", unit_price=150.0
            ),
        )
    )

    store = manager.sync_inventory_from_transactions(store, txs)
    matcher = CGTMatcher(store)

    with pytest.raises(RuntimeError, match="Whole Buy matching exceeds safety ceiling"):
        matcher.optimize_financial_year(txs, target_fy=2024, strategy=MatchingStrategy.WHOLE_BUY)
