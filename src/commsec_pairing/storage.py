"""Persistent buy-sell mapping data structure and inventory management (Task 1)."""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

from commsec_pairing.models import (
    BuyInventoryLot,
    MatchRecord,
    PersistentMappingStore,
    TradeAction,
    Transaction,
)


def load_mapping_store(file_path: str | Path, entity: str = "") -> PersistentMappingStore:
    """Load persistent store from a JSON file path, or create a fresh instance if file is missing."""
    path = Path(file_path)
    if not path.is_file():
        return PersistentMappingStore(entity=entity)

    with open(path, mode="r", encoding="utf-8") as f:
        data = json.load(f)
        return PersistentMappingStore.model_validate(data)


def load_store_from_path_or_dir(target_path: str | Path, entity: str = "") -> PersistentMappingStore:
    """
    Load persistent store from either a JSON file or a directory containing mapping JSON files.
    If a directory is passed, prefers 'mapping.json', then the latest 'mapping_fy*.json',
    then falls back to any *.json file (skipping files that fail validation with a warning).
    """
    p = Path(target_path)
    if p.is_file():
        return load_mapping_store(p, entity=entity)

    if p.is_dir():
        mapping_file = p / "mapping.json"
        if mapping_file.is_file():
            return load_mapping_store(mapping_file, entity=entity or p.name)

        # Look for mapping_fy*.json sorted descending (prefer most recent)
        fy_files = sorted(p.glob("mapping_fy*.json"))
        if fy_files:
            return load_mapping_store(fy_files[-1], entity=entity or p.name)

        # Fallback: scan any *.json, warn and skip files that fail validation
        json_files = sorted(p.glob("*.json"))
        for jf in reversed(json_files):  # most recently named last → try last first
            try:
                with open(jf, mode="r", encoding="utf-8") as f:
                    data = json.load(f)
                store = PersistentMappingStore.model_validate(data)
                logger.warning(
                    "load_store_from_path_or_dir: loaded fallback mapping file '%s'", jf
                )
                return store
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "load_store_from_path_or_dir: skipping '%s' — not a valid mapping store (%s: %s)",
                    jf,
                    type(exc).__name__,
                    exc,
                )

    return PersistentMappingStore(entity=entity or (p.name if p.is_dir() else ""))



def save_mapping_store(store: PersistentMappingStore, file_path: str | Path) -> None:
    """Save mapping store to a JSON file path."""
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    store.last_updated = datetime.now(UTC)
    with open(path, mode="w", encoding="utf-8") as f:
        json.dump(store.model_dump(mode="json"), f, indent=2)


class MappingStorageManager:
    """Manages reading, writing, and synchronizing persistent mapping stores."""

    def __init__(self, default_file_path: str | Path, entity: str):
        self.default_file_path = Path(default_file_path)
        self.entity = entity

    def load_or_create(self, custom_input_path: str | Path | None = None) -> PersistentMappingStore:
        """Load persistent store from custom path or default path."""
        target_path = Path(custom_input_path) if custom_input_path else self.default_file_path
        return load_mapping_store(target_path, entity=self.entity)

    def save(
        self, store: PersistentMappingStore, custom_output_path: str | Path | None = None
    ) -> Path:
        """Persist mapping store to custom path or default path."""
        target_path = Path(custom_output_path) if custom_output_path else self.default_file_path
        save_mapping_store(store, target_path)
        return target_path

    def sync_inventory_from_transactions(
        self,
        store: PersistentMappingStore,
        transactions: list[Transaction],
        max_fy: int | None = None,
    ) -> PersistentMappingStore:
        """
        Synchronize buy inventory lots with unified transactions while preserving
        existing matches and remaining unit balances.
        If max_fy is specified, transactions occurring in future financial years are ignored.
        """
        from commsec_pairing.matcher import get_financial_year

        updated_lots: list[BuyInventoryLot] = []
        for tx in transactions:
            if not (tx.is_contract and tx.parsed_trade):
                continue
            if tx.parsed_trade.action != TradeAction.BUY:
                continue
            if max_fy is not None and get_financial_year(tx.date) > max_fy:
                continue

            ref = tx.reference
            total_units = tx.parsed_trade.units
            security = tx.parsed_trade.security
            trade_date = tx.date
            unit_price = tx.parsed_trade.unit_price

            # Calculate units already matched in previous runs
            already_matched = sum(
                m.matched_units for m in store.matches if m.buy.contract_ref == ref
            )
            remaining = total_units - already_matched
            if remaining < 0:
                raise ValueError(
                    f"Integrity error for {ref}: matched {already_matched} units "
                    f"exceeds total bought units {total_units}."
                )

            updated_lots.append(
                BuyInventoryLot(
                    contract_ref=ref,
                    trade_date=trade_date,
                    security=security,
                    unit_price_aud=unit_price,
                    total_units=total_units,
                    matched_units=already_matched,
                    remaining_units=remaining,
                    is_exhausted=(remaining == 0),
                    is_short=tx.parsed_trade.is_short,
                )
            )

        store.buy_inventory = sorted(updated_lots, key=lambda x: (x.trade_date, x.contract_ref))
        return store

    def record_match(
        self, store: PersistentMappingStore, match: MatchRecord
    ) -> PersistentMappingStore:
        """
        Record a new pairing match, enforcing strict unit conservation
        (1 purchased unit -> at most 1 sold unit).
        """
        # Find corresponding buy lot
        buy_lot: BuyInventoryLot | None = None
        for lot in store.buy_inventory:
            if lot.contract_ref == match.buy.contract_ref:
                buy_lot = lot
                break

        if not buy_lot:
            raise ValueError(
                f"Buy contract {match.buy.contract_ref} not found in inventory."
            )

        if buy_lot.remaining_units < match.matched_units:
            raise ValueError(
                f"Insufficient units in {buy_lot.contract_ref}: requested {match.matched_units}, "
                f"available {buy_lot.remaining_units}."
            )

        # Update buy lot state
        buy_lot.matched_units += match.matched_units
        buy_lot.remaining_units -= match.matched_units
        buy_lot.is_exhausted = (buy_lot.remaining_units == 0)

        # Append match
        store.matches.append(match)
        return store
