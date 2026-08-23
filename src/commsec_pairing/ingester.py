"""Transaction ingestion, trade parsing, union, and deduplication (Task 2)."""

import csv
import re
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from commsec_pairing.models import ParsedTrade, TradeAction, Transaction

TRADE_PATTERN = re.compile(
    r"^\s*(?P<action>[BS])\s+(?P<units>\d+)\s+(?P<security>[A-Z0-9]+)\s*@\s*(?P<price>[\d\.]+)",
    re.IGNORECASE,
)


def parse_date_str(date_str: str) -> date:
    """Parse date strings supporting DD/MM/YYYY and YYYY-MM-DD formats."""
    cleaned = date_str.strip()
    if "/" in cleaned:
        day_str, month_str, year_str = cleaned.split("/")
        return date(int(year_str), int(month_str), int(day_str))
    elif "-" in cleaned:
        return date.fromisoformat(cleaned)
    raise ValueError(f"Unsupported date format: '{date_str}'")


def parse_trade_details(details_str: str) -> ParsedTrade | None:
    """Extract trade action, quantity, security ticker, and price from details string."""
    if not details_str:
        return None
    match = TRADE_PATTERN.search(details_str.strip())
    if not match:
        return None

    action_char = match.group("action").upper()
    action = TradeAction.BUY if action_char == "B" else TradeAction.SELL
    units = int(match.group("units"))
    security = match.group("security").upper()
    unit_price = float(match.group("price"))

    return ParsedTrade(
        action=action,
        units=units,
        security=security,
        unit_price=unit_price,
    )


def _clean_float(val: str | None) -> float | None:
    if not val:
        return None
    cleaned = val.strip().replace("$", "").replace(",", "")
    if not cleaned:
        return None
    return float(cleaned)


def load_transactions_csv(file_path: str | Path) -> list[Transaction]:
    """Load and parse transactions from a single CommSec CSV file."""
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Transaction CSV file not found: {path}")

    transactions: list[Transaction] = []
    with open(path, mode="r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            normalized_row = {k.strip(): v for k, v in row.items() if k is not None}

            raw_date = normalized_row.get("Date", "")
            if not raw_date:
                continue

            parsed_d = parse_date_str(raw_date)
            reference = normalized_row.get("Reference", "").strip()
            details = normalized_row.get("Details", "").strip()
            debit = _clean_float(normalized_row.get("Debit($)") or normalized_row.get("Debit"))
            credit = _clean_float(normalized_row.get("Credit($)") or normalized_row.get("Credit"))
            balance = _clean_float(
                normalized_row.get("Balance($)") or normalized_row.get("Balance")
            )

            parsed_trade = parse_trade_details(details) if reference.startswith("C") else None

            transactions.append(
                Transaction(
                    date=parsed_d,
                    reference=reference,
                    details=details,
                    debit=debit,
                    credit=credit,
                    balance=balance,
                    parsed_trade=parsed_trade,
                )
            )

    return transactions


def discover_transaction_csvs(entity_dir: str | Path) -> list[Path]:
    """Find all transaction CSV files in an entity directory."""
    path = Path(entity_dir)
    if not path.is_dir():
        raise NotADirectoryError(f"Entity directory does not exist: {path}")

    return sorted(path.glob("Transactions_*.csv"))


def get_deduplication_fingerprint(tx: Transaction) -> tuple:
    """
    Generate deduplication fingerprint for a transaction.
    For trade contracts, the fingerprint strictly consists of:
    (contract reference, date, security ticker, number of units, action B/S).
    """
    if tx.is_contract and tx.parsed_trade:
        return (
            tx.reference,
            tx.date,
            tx.parsed_trade.security,
            tx.parsed_trade.units,
            tx.parsed_trade.action,
        )
    return (
        tx.reference,
        tx.date,
        tx.details,
        tx.debit,
        tx.credit,
    )


def union_and_deduplicate(csv_paths: Sequence[str | Path]) -> list[Transaction]:
    """Union multiple transaction CSV files and deduplicate records by fingerprint."""
    seen = set()
    unified: list[Transaction] = []

    for path in csv_paths:
        txs = load_transactions_csv(path)
        for tx in txs:
            key = get_deduplication_fingerprint(tx)
            if key not in seen:
                seen.add(key)
                unified.append(tx)

    unified.sort(key=lambda x: (x.date, x.reference))
    return unified


def save_transactions_to_csv(
    transactions: Sequence[Transaction], output_path: str | Path
) -> None:
    """Save normalized transactions to CSV format."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    with open(out, mode="w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Date", "Reference", "Details", "Debit($)", "Credit($)", "Balance($)"])
        for tx in transactions:
            writer.writerow([
                tx.date.strftime("%d/%m/%Y"),
                tx.reference,
                tx.details,
                f"{tx.debit:.2f}" if tx.debit is not None else "",
                f"{tx.credit:.2f}" if tx.credit is not None else "",
                f"{tx.balance:.2f}" if tx.balance is not None else "",
            ])
