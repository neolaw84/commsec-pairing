import csv
from datetime import date

from commsec_pairing.exporter import (
    compute_annual_tax_summary,
    export_reports,
    generate_audit_report_md,
    generate_parcels_csv,
    generate_tax_summary_csv,
)
from commsec_pairing.models import (
    BuyInventoryLot,
    MatchingStrategy,
    MatchLeg,
    MatchRecord,
    PersistentMappingStore,
)


def create_sample_store() -> PersistentMappingStore:
    """Create sample store spanning multiple financial years with various match cases."""
    store = PersistentMappingStore(entity="test-portfolio")

    # Match 1: FY 2022 short term gain (BBOZ)
    store.matches.append(
        MatchRecord(
            match_id="m_2022_001",
            financial_year=2022,
            security="BBOZ",
            matched_units=100,
            buy=MatchLeg(
                contract_ref="C_BUY_1",
                trade_date=date(2021, 9, 27),
                unit_price_aud=4.36,
            ),
            sell=MatchLeg(
                contract_ref="C_SELL_1",
                trade_date=date(2021, 10, 1),
                unit_price_aud=4.59,
            ),
            holding_period_days=4,
            cgt_discount_eligible=False,
            gross_gain_loss_aud=23.00,
            taxable_gain_loss_aud=23.00,
            strategy=MatchingStrategy.FIFO,
        )
    )

    # Match 2: FY 2022 long term gain (IVV, 50% discount)
    store.matches.append(
        MatchRecord(
            match_id="m_2022_002",
            financial_year=2022,
            security="IVV",
            matched_units=5,
            buy=MatchLeg(
                contract_ref="C_BUY_2",
                trade_date=date(2020, 1, 9),
                unit_price_aud=475.00,
            ),
            sell=MatchLeg(
                contract_ref="C_SELL_2",
                trade_date=date(2022, 1, 12),
                unit_price_aud=654.00,
            ),
            holding_period_days=734,
            cgt_discount_eligible=True,
            gross_gain_loss_aud=895.00,
            taxable_gain_loss_aud=447.50,
            strategy=MatchingStrategy.FIFO,
        )
    )

    # Match 3: FY 2026 capital loss (AIM)
    store.matches.append(
        MatchRecord(
            match_id="m_2026_001",
            financial_year=2026,
            security="AIM",
            matched_units=1000,
            buy=MatchLeg(
                contract_ref="C_BUY_3",
                trade_date=date(2025, 11, 7),
                unit_price_aud=0.86,
            ),
            sell=MatchLeg(
                contract_ref="C_SELL_3",
                trade_date=date(2026, 3, 19),
                unit_price_aud=0.23,
            ),
            holding_period_days=132,
            cgt_discount_eligible=False,
            gross_gain_loss_aud=-630.00,
            taxable_gain_loss_aud=-630.00,
            strategy=MatchingStrategy.GRANULAR,
        )
    )

    # Buy inventory lots
    store.buy_inventory.append(
        BuyInventoryLot(
            contract_ref="C_BUY_1",
            trade_date=date(2021, 9, 27),
            security="BBOZ",
            unit_price_aud=4.36,
            total_units=100,
            matched_units=100,
            remaining_units=0,
            is_exhausted=True,
        )
    )
    store.buy_inventory.append(
        BuyInventoryLot(
            contract_ref="C_BUY_4",
            trade_date=date(2023, 7, 10),
            security="NDQ",
            unit_price_aud=32.50,
            total_units=50,
            matched_units=0,
            remaining_units=50,
            is_exhausted=False,
        )
    )

    return store


def test_compute_annual_tax_summary():
    store = create_sample_store()
    summary = compute_annual_tax_summary(store)
    assert len(summary) >= 2

    # FY 2022 check
    fy22 = next(r for r in summary if r["financial_year"] == 2022)
    assert fy22["total_disposals"] == 2
    assert fy22["net_gross"] == 23.00 + 895.00
    assert fy22["cgt_discount_deductions"] == 447.50
    assert fy22["net_taxable"] == 23.00 + 447.50

    # FY 2026 check
    fy26 = next(r for r in summary if r["financial_year"] == 2026)
    assert fy26["total_disposals"] == 1
    assert fy26["net_gross"] == -630.00
    assert fy26["net_taxable"] == -630.00


def test_generate_parcels_csv(tmp_path):
    store = create_sample_store()
    csv_file = tmp_path / "matched_parcels.csv"
    out = generate_parcels_csv(store, csv_file)

    assert out.is_file()
    with open(out, mode="r", encoding="utf-8") as f:
        reader = list(csv.reader(f))
        assert reader[0][0] == "FinancialYear"
        assert reader[0][1] == "Security"
        assert len(reader) == 4  # Header + 3 matches
        assert reader[1][0] == "2022"
        assert reader[1][1] == "BBOZ"


def test_generate_tax_summary_csv(tmp_path):
    store = create_sample_store()
    csv_file = tmp_path / "cgt_annual_tax_summary.csv"
    out = generate_tax_summary_csv(store, csv_file)

    assert out.is_file()
    with open(out, mode="r", encoding="utf-8") as f:
        reader = list(csv.reader(f))
        assert reader[0][0] == "FinancialYear"
        assert reader[0][5] == "NetGrossGainLossAUD"
        assert reader[0][7] == "NetTaxableGainLossAUD"


def test_generate_audit_report_md(tmp_path):
    store = create_sample_store()
    md_file = tmp_path / "audit_report.md"
    out = generate_audit_report_md(store, md_file)

    assert out.is_file()
    content = md_file.read_text(encoding="utf-8")
    assert "# Portfolio Tax & Inventory Audit Report: `test-portfolio`" in content
    assert "FY 2022" in content
    assert "FY 2026" in content
    assert "Active Buy Inventory Ledger" in content
    assert "NDQ" in content


def test_export_reports_with_custom_paths(tmp_path):
    store = create_sample_store()
    out_dir = tmp_path / "custom_reports"
    p_csv = tmp_path / "custom_parcels.csv"
    s_csv = tmp_path / "custom_summary.csv"
    r_md = tmp_path / "custom_report.md"

    exported = export_reports(
        store,
        output_dir=out_dir,
        parcels_csv=p_csv,
        summary_csv=s_csv,
        report_md=r_md,
    )

    assert exported["parcels_csv"] == p_csv
    assert exported["summary_csv"] == s_csv
    assert exported["report_md"] == r_md
    assert p_csv.is_file()
    assert s_csv.is_file()
    assert r_md.is_file()
