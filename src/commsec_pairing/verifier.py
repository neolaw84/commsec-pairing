"""Contract completeness verification and reconciliation engine (Task 3)."""

import logging
import re
from datetime import date
from pathlib import Path

import pypdf

from commsec_pairing.ingester import (
    discover_transaction_csvs,
    parse_date_str,
    union_and_deduplicate,
)
from commsec_pairing.models import (
    ContractNote,
    ReconciliationReport,
    TradeAction,
    Transaction,
)

logger = logging.getLogger(__name__)


def extract_contract_from_pdf_content(pdf_path: str | Path) -> ContractNote:
    """
    Extract contract confirmation number and trade metadata strictly from PDF file contents.
    Does NOT rely on the filename.
    """
    path = Path(pdf_path)
    file_name = path.name

    contract_id = ""
    action: TradeAction | None = None
    security: str | None = None
    units: int | None = None
    trade_date: date | None = None

    try:
        reader = pypdf.PdfReader(path)
        if len(reader.pages) > 0:
            text = reader.pages[0].extract_text() or ""
            lines = [line.strip() for line in text.split("\n") if line.strip()]

            # 1. Extract Confirmation Number
            conf_match = re.search(r"CONFIRMATION\s*NO:?\s*(\d{7,10})", text, re.IGNORECASE)
            if conf_match:
                contract_id = conf_match.group(1)
            else:
                for i, line in enumerate(lines):
                    if "CONFIRMATION NO" in line.upper():
                        for j in range(i + 1, min(i + 15, len(lines))):
                            if re.match(r"^\d{7,10}$", lines[j]):
                                contract_id = lines[j]
                                break
                        if contract_id:
                            break

            # 2. Extract Action: BUY vs SELL
            upper_text = text.upper()
            if "BOUGHT" in upper_text or "\nBUY\n" in upper_text:
                action = TradeAction.BUY
            elif "SOLD" in upper_text or "\nSELL\n" in upper_text or "\nSALE\n" in upper_text:
                action = TradeAction.SELL

            # 3. Extract Security / Ticker (line before ORDER COMPLETED)
            for i, line in enumerate(lines):
                if "ORDER COMPLETED" in line.upper() and i > 0:
                    security = lines[i - 1].upper()
                    break

            # 4. Extract Trade Date (first valid date in DD/MM/YYYY format)
            date_matches = re.findall(r"\b(\d{2}/\d{2}/\d{4})\b", text)
            if date_matches:
                try:
                    trade_date = parse_date_str(date_matches[0])
                except ValueError:
                    trade_date = None

            # 5. Extract Units (from line under UNITS AT PRICE)
            for i, line in enumerate(lines):
                if "UNITS AT PRICE" in line.upper() and i + 1 < len(lines):
                    candidate = lines[i + 1]
                    if re.match(r"^\d+$", candidate):
                        units = int(candidate)
                        break

    except (pypdf.errors.PdfReadError, OSError, ValueError) as err:
        logger.warning("Could not read PDF contents of %s: %s", path, err)

    contract_ref = f"C{contract_id}" if contract_id else ""

    return ContractNote(
        file_path=str(path),
        file_name=file_name,
        contract_id=contract_id,
        contract_ref=contract_ref,
        action=action,
        security=security,
        units=units,
        trade_date=trade_date,
    )


def discover_contract_pdfs(entity_dir: str | Path) -> list[ContractNote]:
    """Scan and parse all contract PDFs in the entity directory by reading file contents."""
    path = Path(entity_dir)
    if not path.is_dir():
        raise NotADirectoryError(f"Directory not found: {path}")

    pdf_files = sorted(path.glob("*.pdf"))
    return [extract_contract_from_pdf_content(p) for p in pdf_files]


def verify_entity_contracts(
    entity_dir: str | Path,
    transactions: list[Transaction] | None = None,
) -> ReconciliationReport:
    """
    Verify the completeness of contract PDFs against transaction CSV ground truth
    by inspecting PDF file contents directly.
    Outputs ERRORS (without halting) for missing contract PDFs,
    and WARNINGS for contract PDFs with no corresponding CSV transaction.
    """
    dir_path = Path(entity_dir)
    entity_name = dir_path.name

    if transactions is None:
        csv_files = discover_transaction_csvs(dir_path)
        transactions = union_and_deduplicate(csv_files)

    # Filter CSV transactions to only trade contracts (starting with 'C')
    csv_trade_contracts: dict[str, Transaction] = {
        tx.reference: tx for tx in transactions if tx.reference.startswith("C")
    }

    # Discover and parse available PDF contracts from content
    pdf_contracts = discover_contract_pdfs(dir_path)
    pdf_contract_map: dict[str, list[ContractNote]] = {}
    for contract in pdf_contracts:
        if contract.contract_ref:
            pdf_contract_map.setdefault(contract.contract_ref, []).append(contract)

    missing_errors: list[str] = []
    unreferenced_warnings: list[str] = []
    matched_count = 0

    # 1. Check for missing PDFs (ERRORS)
    for ref, tx in sorted(csv_trade_contracts.items(), key=lambda item: item[1].date):
        if ref not in pdf_contract_map:
            missing_errors.append(
                f"[ERROR] Missing contract note PDF for trade on {tx.date}: "
                f"Ref {ref} | {tx.details}"
            )
        else:
            matched_count += 1

    # 2. Check for extra/unreferenced PDFs (WARNINGS)
    for ref, contracts in sorted(pdf_contract_map.items()):
        if ref not in csv_trade_contracts:
            for contract in contracts:
                unreferenced_warnings.append(
                    f"[WARNING] Contract note PDF exists without matching CSV transaction record: "
                    f"{contract.file_name} (Ref: {ref})"
                )

    return ReconciliationReport(
        entity=entity_name,
        total_csv_trades=len(csv_trade_contracts),
        total_pdf_contracts=len(pdf_contracts),
        matched_contracts=matched_count,
        missing_contracts_errors=missing_errors,
        unreferenced_contracts_warnings=unreferenced_warnings,
    )
