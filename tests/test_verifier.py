"""Tests for PDF contract verification against CSV ground truth."""

from datetime import date
from pathlib import Path

from commsec_pairing.models import ParsedTrade, TradeAction, Transaction
from commsec_pairing.verifier import extract_contract_from_pdf_content, verify_entity_contracts


def _create_mock_contract_pdf(
    path: Path,
    confirmation_no: str,
    action_text: str,
    units: int,
    security: str,
    trade_date_str: str,
) -> None:
    """Generate a synthetic CommSec confirmation PDF for unit testing."""
    lines = [
        "CONFIRMATION NO",
        str(confirmation_no),
        f"WE HAVE THIS DAY {action_text}",
        security,
        "ORDER COMPLETED",
        f"DATE {trade_date_str}",
        "UNITS AT PRICE",
        str(units),
    ]
    stream_text = "BT\n/F1 12 Tf\n72 712 Td\n"
    for line in lines:
        stream_text += f"({line}) Tj\n0 -20 Td\n"
    stream_text += "ET"
    stream_bytes = stream_text.encode("latin1")
    pdf_content = (
        b"%PDF-1.4\n"
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj\n"
        b"4 0 obj << /Length "
        + str(len(stream_bytes)).encode("ascii")
        + b" >> stream\n"
        + stream_bytes
        + b"\nendstream\nendobj\n"
        b"5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n"
        b"xref\n0 6\n0000000000 65535 f \ntrailer << /Size 6 /Root 1 0 R >>\nstartxref\n0\n%%EOF\n"
    )
    path.write_bytes(pdf_content)


def test_extract_contract_from_pdf_content_arbitrary_filename(tmp_path):
    mock_pdf = tmp_path / "some_random_contract_name.pdf"
    _create_mock_contract_pdf(
        mock_pdf,
        confirmation_no="103966253",
        action_text="BOUGHT",
        units=19,
        security="A200",
        trade_date_str="05/08/2020",
    )

    contract = extract_contract_from_pdf_content(mock_pdf)
    assert contract.contract_id == "103966253"
    assert contract.contract_ref == "C103966253"
    assert contract.action == TradeAction.BUY
    assert contract.security == "A200"
    assert contract.units == 19
    assert contract.trade_date == date(2020, 8, 5)


def test_verify_entity_contracts_ignores_filenames(tmp_path):
    entity_dir = tmp_path / "entity-test"
    entity_dir.mkdir()

    # Generate synthetic PDFs with intentionally scrambled/misleading filenames
    _create_mock_contract_pdf(
        entity_dir / "completely_arbitrary_name_1.pdf",
        confirmation_no="103966253",
        action_text="BOUGHT",
        units=19,
        security="A200",
        trade_date_str="05/08/2020",
    )
    _create_mock_contract_pdf(
        entity_dir / "misleading_filename_9999999.pdf",
        confirmation_no="105691414",
        action_text="BOUGHT",
        units=8,
        security="IVV",
        trade_date_str="04/09/2020",
    )

    txs = [
        Transaction(
            date=date(2020, 8, 5),
            reference="C103966253",
            details="B 19 A200 @ 99.950000",
            parsed_trade=ParsedTrade(
                action=TradeAction.BUY, units=19, security="A200", unit_price=99.95
            ),
        ),
        Transaction(
            date=date(2020, 9, 4),
            reference="C105691414",
            details="B 8 IVV @ 475.500000",
            parsed_trade=ParsedTrade(
                action=TradeAction.BUY, units=8, security="IVV", unit_price=475.5
            ),
        ),
        Transaction(
            date=date(2020, 9, 10),
            reference="C88888888",
            details="B 10 IVV @ 500.0",
            parsed_trade=ParsedTrade(
                action=TradeAction.BUY, units=10, security="IVV", unit_price=500.0
            ),
        ),
    ]

    report = verify_entity_contracts(entity_dir, transactions=txs)
    assert report.total_csv_trades == 3
    assert report.total_pdf_contracts == 2
    assert report.matched_contracts == 2
    assert len(report.missing_contracts_errors) == 1
    assert "C88888888" in report.missing_contracts_errors[0]
    assert len(report.unreferenced_contracts_warnings) == 0
