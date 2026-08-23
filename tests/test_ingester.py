"""Tests for CSV transaction ingestion, trade parsing, union and deduplication."""

from datetime import date

from commsec_pairing.ingester import (
    load_transactions_csv,
    parse_date_str,
    parse_trade_details,
    save_transactions_to_csv,
    union_and_deduplicate,
)
from commsec_pairing.models import TradeAction


def test_parse_date_str():
    assert parse_date_str("07/05/2025") == date(2025, 5, 7)
    assert parse_date_str("2024-08-09") == date(2024, 8, 9)


def test_parse_trade_details():
    buy_trade = parse_trade_details("B 24 IAF @ 101.000000")
    assert buy_trade is not None
    assert buy_trade.action == TradeAction.BUY
    assert buy_trade.units == 24
    assert buy_trade.security == "IAF"
    assert buy_trade.unit_price == 101.0

    sell_trade = parse_trade_details("S 100 ATEC @ 23.430000  ")
    assert sell_trade is not None
    assert sell_trade.action == TradeAction.SELL
    assert sell_trade.units == 100
    assert sell_trade.security == "ATEC"
    assert sell_trade.unit_price == 23.43

    transfer = parse_trade_details("Direct Transfer - Payee ENTITY ONE")
    assert transfer is None


def test_union_and_deduplicate(tmp_path):
    f1 = tmp_path / "Transactions_1.csv"
    f2 = tmp_path / "Transactions_2.csv"

    content1 = (
        "Date,Reference,Details,Debit($),Credit($),Balance($)\n"
        "05/05/2025,C161775901,S 29 IHHY @ 92.400000,,2669.60,-5130.16\n"
        "13/08/2024,P32804915,Direct Transfer,2333.00,,0.00\n"
    )
    content2 = (
        "Date,Reference,Details,Debit($),Credit($),Balance($)\n"
        "05/05/2025,C161775901,S 29 IHHY @ 92.400000,,2669.60,-5130.16\n"
        "09/08/2024,C154234444,S 100 ATEC @ 23.430000,,2333.00,-2333.00\n"
    )

    f1.write_text(content1)
    f2.write_text(content2)

    unioned = union_and_deduplicate([f1, f2])
    assert len(unioned) == 3

    # Check order is chronological
    assert unioned[0].date == date(2024, 8, 9)
    assert unioned[1].date == date(2024, 8, 13)
    assert unioned[2].date == date(2025, 5, 5)


def test_trade_fingerprint_deduplication(tmp_path):
    # Two files with the same trade but differing non-critical whitespace or balance column
    f1 = tmp_path / "T1.csv"
    f2 = tmp_path / "T2.csv"

    # Same contract reference, date, security, units, and action
    f1.write_text(
        "Date,Reference,Details,Debit($),Credit($),Balance($)\n"
        "05/05/2025,C161775901,S 29 IHHY @ 92.400000,,2669.60,-5130.16\n"
    )
    f2.write_text(
        "Date,Reference,Details,Debit($),Credit($),Balance($)\n"
        "05/05/2025,C161775901,S 29 IHHY @ 92.400000,,2669.60,0.00\n"
    )

    unioned = union_and_deduplicate([f1, f2])
    # Must deduplicate to 1 trade record based on (contract, date, security, units, action)
    assert len(unioned) == 1
    assert unioned[0].reference == "C161775901"
    assert unioned[0].parsed_trade.units == 29


def test_save_and_reload_csv(tmp_path):
    f_in = tmp_path / "in.csv"
    f_in.write_text(
        "Date,Reference,Details,Debit($),Credit($),Balance($)\n"
        "05/05/2025,C161775901,S 29 IHHY @ 92.400000,,2669.60,-5130.16\n"
    )

    txs = load_transactions_csv(f_in)
    out_file = tmp_path / "out.csv"
    save_transactions_to_csv(txs, out_file)

    reloaded = load_transactions_csv(out_file)
    assert len(reloaded) == 1
    assert reloaded[0].reference == "C161775901"
    assert reloaded[0].parsed_trade.units == 29
