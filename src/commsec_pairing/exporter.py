"""Multi-format reporting and export engine for CommSec Pairing ledgers."""

import csv
from collections import defaultdict
from pathlib import Path
from typing import Any

from commsec_pairing.models import PersistentMappingStore


def generate_parcels_csv(store: PersistentMappingStore, output_path: Path) -> Path:
    """Generate granular matched parcels CSV ledger for accounting audit."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "FinancialYear",
            "Security",
            "MatchedUnits",
            "BuyContractRef",
            "BuyTradeDate",
            "BuyUnitPriceAUD",
            "SellContractRef",
            "SellTradeDate",
            "SellUnitPriceAUD",
            "HoldingPeriodDays",
            "CGTDiscountEligible",
            "GrossGainLossAUD",
            "TaxableGainLossAUD",
            "Strategy",
            "MatchID",
        ])
        for m in store.matches:
            strategy_val = m.strategy.value if hasattr(m.strategy, "value") else str(m.strategy)
            writer.writerow([
                m.financial_year,
                m.security,
                m.matched_units,
                m.buy.contract_ref,
                m.buy.trade_date.strftime("%Y-%m-%d"),
                f"{m.buy.unit_price_aud:.2f}",
                m.sell.contract_ref,
                m.sell.trade_date.strftime("%Y-%m-%d"),
                f"{m.sell.unit_price_aud:.2f}",
                m.holding_period_days,
                m.cgt_discount_eligible,
                f"{m.gross_gain_loss_aud:.2f}",
                f"{m.taxable_gain_loss_aud:.2f}",
                strategy_val,
                m.match_id,
            ])
    return output_path


def compute_annual_tax_summary(store: PersistentMappingStore) -> list[dict[str, Any]]:
    """Compute aggregated tax figures grouped by Australian Financial Year."""
    by_fy: dict[int, list] = defaultdict(list)
    for m in store.matches:
        by_fy[m.financial_year].append(m)

    # Collect all FYs present in matches and buy inventory
    all_fys = set(by_fy.keys())
    for lot in store.buy_inventory:
        from commsec_pairing.matcher import get_financial_year
        all_fys.add(get_financial_year(lot.trade_date))

    sorted_fys = sorted(all_fys)
    summary_rows: list[dict[str, Any]] = []

    for fy in sorted_fys:
        matches = by_fy.get(fy, [])
        total_disposals = len(matches)
        gross_gains = sum(m.gross_gain_loss_aud for m in matches if m.gross_gain_loss_aud > 0)
        gross_losses = sum(m.gross_gain_loss_aud for m in matches if m.gross_gain_loss_aud < 0)
        net_gross = sum(m.gross_gain_loss_aud for m in matches)
        cgt_discount_deductions = sum(
            (m.gross_gain_loss_aud - m.taxable_gain_loss_aud)
            for m in matches
            if m.cgt_discount_eligible and m.gross_gain_loss_aud > 0
        )
        net_taxable = sum(m.taxable_gain_loss_aud for m in matches)

        strategies = sorted({m.strategy.value if hasattr(m.strategy, "value") else str(m.strategy) for m in matches})
        strategy_label = ", ".join(strategies) if strategies else "N/A"

        summary_rows.append({
            "financial_year": fy,
            "total_disposals": total_disposals,
            "strategy": strategy_label,
            "gross_gains": gross_gains,
            "gross_losses": gross_losses,
            "net_gross": net_gross,
            "cgt_discount_deductions": cgt_discount_deductions,
            "net_taxable": net_taxable,
            "matches": matches,
        })
    return summary_rows


def generate_tax_summary_csv(store: PersistentMappingStore, output_path: Path) -> Path:
    """Generate annual CGT tax summary CSV directly aligned with ATO Tax Return filing."""
    summary_rows = compute_annual_tax_summary(store)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "FinancialYear",
            "Strategy",
            "TotalDisposals",
            "TotalGrossGainsAUD",
            "TotalGrossLossesAUD",
            "NetGrossGainLossAUD",
            "CGTDiscountDeductionAUD",
            "NetTaxableGainLossAUD",
        ])
        for row in summary_rows:
            writer.writerow([
                f"FY{row['financial_year']}",
                row["strategy"],
                row["total_disposals"],
                f"{row['gross_gains']:.2f}",
                f"{row['gross_losses']:.2f}",
                f"{row['net_gross']:.2f}",
                f"{row['cgt_discount_deductions']:.2f}",
                f"{row['net_taxable']:.2f}",
            ])
    return output_path


def generate_audit_report_md(store: PersistentMappingStore, output_path: Path) -> Path:
    """Generate comprehensive Markdown audit report with annual tables and active inventory."""
    summary_rows = compute_annual_tax_summary(store)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = [
        f"# Portfolio Tax & Inventory Audit Report: `{store.entity or 'Portfolio'}`",
        f"*Generated on {store.last_updated.strftime('%Y-%m-%d %H:%M:%S UTC')}*",
        "",
        "## 1. Annual Capital Gains Tax (CGT) Summary",
        "",
        "| Financial Year | Strategy | Disposals | Gross Gains | Gross Losses | Net Gross P/L | CGT Discount | Net Taxable Gain / (Loss) |",
        "| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]

    total_gross = 0.0
    total_disc = 0.0
    total_taxable = 0.0
    total_disposals_count = 0

    for r in summary_rows:
        total_disposals_count += r["total_disposals"]
        total_gross += r["net_gross"]
        total_disc += r["cgt_discount_deductions"]
        total_taxable += r["net_taxable"]

        lines.append(
            f"| **FY {r['financial_year']}** | `{r['strategy']}` | {r['total_disposals']} | "
            f"${r['gross_gains']:,.2f} | ${r['gross_losses']:,.2f} | "
            f"${r['net_gross']:,.2f} | ${r['cgt_discount_deductions']:,.2f} | "
            f"**${r['net_taxable']:,.2f}** |"
        )

    lines.append(
        f"| **Total** | — | **{total_disposals_count}** | — | — | "
        f"**${total_gross:,.2f}** | **${total_disc:,.2f}** | **${total_taxable:,.2f}** |"
    )
    lines.append("")

    # Section 2: Detailed Matches per FY
    lines.append("## 2. Realized Disposals & Match Details")
    lines.append("")

    fys_with_matches = [r for r in summary_rows if r["total_disposals"] > 0]
    if not fys_with_matches:
        lines.append("*No sell transactions matched yet.*")
        lines.append("")
    else:
        for r in fys_with_matches:
            lines.append(f"### FY {r['financial_year']} (Strategy: `{r['strategy']}`)")
            lines.append("")
            lines.append("| Security | Units | Buy Contract | Sell Contract | Holding (Days) | 50% CGT Disc? | Gross Gain / (Loss) | Taxable Gain / (Loss) |")
            lines.append("| :--- | :---: | :--- | :--- | :---: | :---: | :---: | :---: |")
            for m in r["matches"]:
                disc_label = "Yes" if m.cgt_discount_eligible else "No"
                lines.append(
                    f"| **{m.security}** | {m.matched_units} | "
                    f"`{m.buy.contract_ref}` ({m.buy.trade_date}) @ ${m.buy.unit_price_aud:.2f} | "
                    f"`{m.sell.contract_ref}` ({m.sell.trade_date}) @ ${m.sell.unit_price_aud:.2f} | "
                    f"{m.holding_period_days} | {disc_label} | "
                    f"${m.gross_gain_loss_aud:,.2f} | ${m.taxable_gain_loss_aud:,.2f} |"
                )
            lines.append("")

    # Section 3: Active Buy Inventory Ledger
    lines.append("## 3. Active Buy Inventory Ledger")
    lines.append("")
    if not store.buy_inventory:
        lines.append("*No buy inventory recorded.*")
    else:
        lines.append("| Security | Contract Ref | Trade Date | Unit Price | Total Units | Matched | Remaining | Status |")
        lines.append("| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :--- |")
        for lot in store.buy_inventory:
            status = "🔴 Exhausted" if lot.is_exhausted else ("🟡 Partial" if lot.matched_units > 0 else "🟢 Available")
            lines.append(
                f"| **{lot.security}** | `{lot.contract_ref}` | {lot.trade_date.strftime('%Y-%m-%d')} | "
                f"${lot.unit_price_aud:.2f} | {lot.total_units} | {lot.matched_units} | "
                f"**{lot.remaining_units}** | {status} |"
            )
    lines.append("")

    with open(output_path, mode="w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return output_path


def export_reports(
    store: PersistentMappingStore,
    output_dir: Path,
    parcels_csv: Path | None = None,
    summary_csv: Path | None = None,
    report_md: Path | None = None,
) -> dict[str, Path]:
    """
    Export all reports (parcels CSV, annual summary CSV, markdown audit report)
    to default or user-overridden paths.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    p_csv = parcels_csv or (output_dir / "matched_parcels.csv")
    s_csv = summary_csv or (output_dir / "cgt_annual_tax_summary.csv")
    r_md = report_md or (output_dir / "audit_report.md")

    generated_parcels = generate_parcels_csv(store, p_csv)
    generated_summary = generate_tax_summary_csv(store, s_csv)
    generated_md = generate_audit_report_md(store, r_md)

    return {
        "parcels_csv": generated_parcels,
        "summary_csv": generated_summary,
        "report_md": generated_md,
    }
