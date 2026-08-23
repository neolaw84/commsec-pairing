"""Command-line interface for CommSec Pairing with Rich formatting."""

import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from commsec_pairing.exporter import compute_annual_tax_summary, export_reports
from commsec_pairing.ingester import (
    discover_transaction_csvs,
    save_transactions_to_csv,
    union_and_deduplicate,
)
from commsec_pairing.matcher import CGTMatcher
from commsec_pairing.models import MatchingStrategy
from commsec_pairing.storage import MappingStorageManager, load_store_from_path_or_dir
from commsec_pairing.verifier import verify_entity_contracts

console = Console()


def resolve_target_dir(args: argparse.Namespace) -> tuple[Path, str]:
    """Resolve target directory and entity name from either --dir or --entity/--data-dir."""
    if getattr(args, "dir", None):
        target_dir = Path(args.dir)
        entity_name = getattr(args, "entity", None) or target_dir.name
    elif getattr(args, "entity", None):
        target_dir = Path(args.data_dir) / args.entity
        entity_name = args.entity
    else:
        raise ValueError("Either --dir or --entity must be specified.")
    return target_dir, entity_name


def handle_verify(args: argparse.Namespace) -> int:
    """Verify completeness of contract PDFs against transaction CSV ground truth."""
    target_dir, entity_name = resolve_target_dir(args)
    if not target_dir.is_dir():
        console.print(f"[bold red]Error:[/] Directory not found: {target_dir}", file=sys.stderr)
        return 1

    console.print(Panel(f"[bold cyan]Verifying Contract Notes for Entity:[/] {entity_name} ({target_dir})"))

    txs = None
    if getattr(args, "transactions_csv", None):
        csv_path = Path(args.transactions_csv)
        if not csv_path.is_file():
            console.print(f"[bold red]Error:[/] Transactions CSV not found: {csv_path}", file=sys.stderr)
            return 1
        txs = union_and_deduplicate([csv_path])
        console.print(f"[dim]Using explicit transaction ground truth:[/] {csv_path} ({len(txs)} records)")

    report = verify_entity_contracts(target_dir, transactions=txs)

    summary_table = Table(title="Reconciliation Summary", show_header=True)
    summary_table.add_column("Metric", style="bold")
    summary_table.add_column("Count", justify="right")

    summary_table.add_row("Total CSV Trade Transactions", str(report.total_csv_trades))
    summary_table.add_row("Total Contract PDFs Scanned", str(report.total_pdf_contracts))
    summary_table.add_row("Matched Contracts", f"[green]{report.matched_contracts}[/]")
    summary_table.add_row("Missing Contract Errors", f"[red]{len(report.missing_contracts_errors)}[/]")
    summary_table.add_row("Unreferenced Warnings", f"[yellow]{len(report.unreferenced_contracts_warnings)}[/]")

    console.print(summary_table)

    if report.has_errors:
        console.print("\n[bold red]Missing Contract Errors (Action Required):[/]")
        for err in report.missing_contracts_errors:
            console.print(f"  {err}")

    if report.has_warnings:
        console.print("\n[bold yellow]Unreferenced Contract Warnings:[]")
        for warn in report.unreferenced_contracts_warnings:
            console.print(f"  {warn}")

    if not report.has_errors and not report.has_warnings:
        console.print("\n[bold green]✓ All contracts reconciled perfectly with 100% integrity![/]")

    return 0


def handle_union_csv(args: argparse.Namespace) -> int:
    """Union multiple transaction CSVs and deduplicate overlaps."""
    target_dir, _ = resolve_target_dir(args)
    if not target_dir.is_dir():
        console.print(f"[bold red]Error:[/] Directory not found: {target_dir}", file=sys.stderr)
        return 1

    csv_files = discover_transaction_csvs(target_dir)
    console.print(f"[bold cyan]Discovered {len(csv_files)} transaction CSV(s) in {target_dir}[/]")

    transactions = union_and_deduplicate(csv_files)
    console.print(f"[bold green]Successfully unioned and deduplicated: {len(transactions)} total records.[/]")

    if args.output_file:
        out_path = Path(args.output_file)
        save_transactions_to_csv(transactions, out_path)
        console.print(f"[bold green]Saved unified transactions to:[/] {out_path}")
    else:
        preview_table = Table(title="Unified Transactions Preview (First 10)", show_header=True)
        preview_table.add_column("Date")
        preview_table.add_column("Reference")
        preview_table.add_column("Details")
        preview_table.add_column("Debit($)", justify="right")
        preview_table.add_column("Credit($)", justify="right")

        for tx in transactions[:10]:
            preview_table.add_row(
                tx.date.strftime("%d/%m/%Y"),
                tx.reference,
                tx.details,
                f"{tx.debit:.2f}" if tx.debit is not None else "",
                f"{tx.credit:.2f}" if tx.credit is not None else "",
            )
        console.print(preview_table)

    return 0


def handle_status(args: argparse.Namespace) -> int:
    """Display persistent mapping inventory status."""
    target_dir, entity_name = resolve_target_dir(args)
    default_mapping_file = target_dir / "mapping.json"

    manager = MappingStorageManager(default_mapping_file, entity_name)
    store = manager.load_or_create(custom_input_path=args.input_mapping)

    active_file = args.input_mapping or str(default_mapping_file)
    console.print(Panel(f"[bold cyan]Mapping Ledger Status for Entity:[/] {entity_name}\n[dim]Source:[/] {active_file}"))
    console.print(f"Total Matches Recorded: [bold green]{len(store.matches)}[/]")
    console.print(f"Total Buy Inventory Lots: [bold green]{len(store.buy_inventory)}[/]")

    if store.buy_inventory:
        inv_table = Table(title="Buy Inventory Lots", show_header=True)
        inv_table.add_column("Contract Ref")
        inv_table.add_column("Date")
        inv_table.add_column("Security")
        inv_table.add_column("Unit Price", justify="right")
        inv_table.add_column("Total Units", justify="right")
        inv_table.add_column("Matched", justify="right")
        inv_table.add_column("Remaining", justify="right")
        inv_table.add_column("Status")

        for lot in store.buy_inventory:
            status = "[red]Exhausted[/]" if lot.is_exhausted else "[green]Available[/]"
            inv_table.add_row(
                lot.contract_ref,
                lot.trade_date.strftime("%Y-%m-%d"),
                lot.security,
                f"${lot.unit_price_aud:.2f}",
                str(lot.total_units),
                str(lot.matched_units),
                str(lot.remaining_units),
                status,
            )
        console.print(inv_table)

    return 0


def handle_match(args: argparse.Namespace) -> int:
    """Run CGT minimization matcher for a financial year."""
    target_dir, entity_name = resolve_target_dir(args)

    if getattr(args, "transactions_csv", None):
        csv_path = Path(args.transactions_csv)
        if not csv_path.is_file():
            console.print(f"[bold red]Error:[/] Transactions CSV not found: {csv_path}", file=sys.stderr)
            return 1
        transactions = union_and_deduplicate([csv_path])
        console.print(f"[dim]Using explicit transaction ground truth:[/] {csv_path} ({len(transactions)} records)")
    else:
        csv_files = discover_transaction_csvs(target_dir)
        transactions = union_and_deduplicate(csv_files)

    default_mapping_file = target_dir / "mapping.json"
    manager = MappingStorageManager(default_mapping_file, entity_name)

    # Load prior-year mapping if specified, else default mapping
    store = manager.load_or_create(custom_input_path=args.input_mapping)
    store = manager.sync_inventory_from_transactions(store, transactions, max_fy=args.fy)

    # Strategy selection
    if args.strategy == "whole-buy":
        strategy = MatchingStrategy.WHOLE_BUY
    elif args.strategy == "fifo":
        strategy = MatchingStrategy.FIFO
    else:
        strategy = MatchingStrategy.GRANULAR

    matcher = CGTMatcher(store)
    try:
        new_matches = matcher.optimize_financial_year(transactions, args.fy, strategy=strategy)
    except RuntimeError as err:
        console.print(f"[bold red]Matching Error:[/] {err}", file=sys.stderr)
        return 1

    if not new_matches:
        console.print(f"[bold yellow]No unmatched sell transactions found for FY{args.fy}.[/]")
        if args.save or args.output_mapping:
            saved_path = manager.save(store, custom_output_path=args.output_mapping)
            console.print(f"[bold green]✓ Updated mapping ledger with inventory up to FY{args.fy} saved to:[/] {saved_path}")
        return 0

    console.print(
        Panel(
            f"[bold cyan]CGT Pairing Matches for FY{args.fy} (Entity: {entity_name})[/]\n"
            f"[dim]Strategy:[/] {strategy.value.upper()} | "
            f"[dim]Prior Mapping:[/] {args.input_mapping or 'default/fresh'}"
        )
    )

    match_table = Table(title=f"Optimized Pairing Matches - FY{args.fy} ({strategy.value})", show_header=True)
    match_table.add_column("Security")
    match_table.add_column("Units", justify="right")
    match_table.add_column("Buy Ref / Date")
    match_table.add_column("Sell Ref / Date")
    match_table.add_column("Holding Days", justify="right")
    match_table.add_column("50% Discount?")
    match_table.add_column("Gross Gain/Loss", justify="right")
    match_table.add_column("Taxable Gain/Loss", justify="right")

    total_gross = 0.0
    total_taxable = 0.0

    for m in new_matches:
        total_gross += m.gross_gain_loss_aud
        total_taxable += m.taxable_gain_loss_aud
        match_table.add_row(
            m.security,
            str(m.matched_units),
            f"{m.buy.contract_ref} ({m.buy.trade_date})",
            f"{m.sell.contract_ref} ({m.sell.trade_date})",
            str(m.holding_period_days),
            "Yes" if m.cgt_discount_eligible else "No",
            f"${m.gross_gain_loss_aud:,.2f}",
            f"${m.taxable_gain_loss_aud:,.2f}",
        )

    console.print(match_table)
    console.print(f"\n[bold]Total Realized Gross Gain/Loss:[/] ${total_gross:,.2f}")
    console.print(f"[bold]Total Taxable Gain/Loss (after CGT Discount):[/] [bold green]${total_taxable:,.2f}[/]")

    if args.save or args.output_mapping:
        for m in new_matches:
            manager.record_match(store, m)
        saved_path = manager.save(store, custom_output_path=args.output_mapping)
        console.print(f"[bold green]✓ Successfully saved {len(new_matches)} match records to:[/] {saved_path}")

    return 0


def handle_export(args: argparse.Namespace) -> int:
    """Generate multi-format human-readable and accountant CSV/Markdown reports from matching store."""
    entity_name = getattr(args, "entity", "") or ""
    input_path = getattr(args, "input_mapping", None)
    target_dir = None

    if getattr(args, "dir", None):
        target_dir = Path(args.dir)
        if not entity_name:
            entity_name = target_dir.name
    elif entity_name:
        # Check standard matched entity directory or raw entity directory
        matched_candidate = Path(args.data_dir) / f"matched-{entity_name}"
        raw_candidate = Path(args.data_dir) / entity_name
        if matched_candidate.is_dir():
            target_dir = matched_candidate
        elif raw_candidate.is_dir():
            target_dir = raw_candidate
        else:
            target_dir = matched_candidate

    if input_path:
        source_path = Path(input_path)
    elif target_dir:
        source_path = target_dir
    else:
        console.print("[bold red]Error:[/] Either --dir, --entity, or --input-mapping must be provided.", file=sys.stderr)
        return 1

    store = load_store_from_path_or_dir(source_path, entity=entity_name)
    if not store.matches and not store.buy_inventory:
        console.print(f"[bold yellow]Warning:[/] No matches or buy inventory found in {source_path}.", file=sys.stderr)

    # Determine destination directory
    out_dir = Path(args.output_dir) if getattr(args, "output_dir", None) else (
        target_dir if target_dir else Path(".")
    )

    parcels_csv = Path(args.parcels_csv) if getattr(args, "parcels_csv", None) else None
    summary_csv = Path(args.summary_csv) if getattr(args, "summary_csv", None) else None
    report_md = Path(args.report_md) if getattr(args, "report_md", None) else None

    exported = export_reports(
        store,
        output_dir=out_dir,
        parcels_csv=parcels_csv,
        summary_csv=summary_csv,
        report_md=report_md,
    )

    console.print(Panel(f"[bold cyan]Portfolio Tax & Inventory Report Export[/]\n[dim]Entity:[/] {store.entity or entity_name} | [dim]Source:[/] {source_path}"))

    # Display Rich summary table in terminal
    summary_rows = compute_annual_tax_summary(store)
    tax_table = Table(title="Annual Capital Gains Tax (CGT) Summary", show_header=True)
    tax_table.add_column("Tax Year", style="bold")
    tax_table.add_column("Strategy")
    tax_table.add_column("Disposals", justify="right")
    tax_table.add_column("Gross Gains", justify="right")
    tax_table.add_column("Gross Losses", justify="right")
    tax_table.add_column("Net Gross P/L", justify="right")
    tax_table.add_column("CGT Discount", justify="right")
    tax_table.add_column("Net Taxable P/L", justify="right", style="bold green")

    for r in summary_rows:
        tax_table.add_row(
            f"FY {r['financial_year']}",
            r["strategy"],
            str(r["total_disposals"]),
            f"${r['gross_gains']:,.2f}",
            f"${r['gross_losses']:,.2f}",
            f"${r['net_gross']:,.2f}",
            f"${r['cgt_discount_deductions']:,.2f}",
            f"${r['net_taxable']:,.2f}",
        )
    console.print(tax_table)

    console.print("\n[bold green]✓ Successfully generated multi-format reports:[/] ")
    console.print(f"  • [bold]Matched Parcels CSV:[/]        {exported['parcels_csv']}")
    console.print(f"  • [bold]Annual Tax Summary CSV:[/]     {exported['summary_csv']}")
    console.print(f"  • [bold]Audit Report Markdown:[/]      {exported['report_md']}")

    if getattr(args, "stdout", False):
        console.print("\n" + exported["report_md"].read_text(encoding="utf-8"))

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="commsec-pairing",
        description="CommSec Transaction Ingestion, Verification, and CGT Pairing Engine",
    )
    parser.add_argument("--data-dir", default="data", help="Root path to data directory")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Verify subcommand
    p_verify = subparsers.add_parser("verify", help="Verify contract PDFs against CSV ground truth")
    p_verify.add_argument("--entity", help="Entity name (e.g. entity-1)")
    p_verify.add_argument("--dir", help="Direct path to custom directory (e.g. data/entity-1 or /path/to/dir)")
    p_verify.add_argument(
        "--transactions-csv",
        "--input-csv",
        dest="transactions_csv",
        help="Optional path to explicit/unified transaction CSV file (defaults to auto-discovering all CSVs in directory)",
    )
    p_verify.set_defaults(func=handle_verify)

    # Union CSV subcommand
    p_union = subparsers.add_parser("union-csv", help="Union and deduplicate transaction CSVs")
    p_union.add_argument("--entity", help="Entity name (e.g. entity-1)")
    p_union.add_argument("--dir", help="Direct path to custom directory (e.g. data/entity-1 or /path/to/dir)")
    p_union.add_argument("--output-file", help="Optional output path for unified CSV")
    p_union.set_defaults(func=handle_union_csv)

    # Status subcommand
    p_status = subparsers.add_parser("status", help="Inspect inventory and match status")
    p_status.add_argument("--entity", help="Entity name (e.g. entity-1)")
    p_status.add_argument("--dir", help="Direct path to custom directory")
    p_status.add_argument("--input-mapping", help="Optional path to prior mapping JSON file")
    p_status.set_defaults(func=handle_status)

    # Match subcommand
    p_match = subparsers.add_parser("match", help="Run CGT minimization pairing for an FY")
    p_match.add_argument("--entity", help="Entity name (e.g. entity-1)")
    p_match.add_argument("--dir", help="Direct path to custom directory")
    p_match.add_argument("--fy", type=int, required=True, help="Target financial year (e.g. 2026)")
    p_match.add_argument(
        "--transactions-csv",
        "--input-csv",
        dest="transactions_csv",
        help="Optional path to explicit/unified transaction CSV file (defaults to auto-discovering all CSVs in directory)",
    )
    p_match.add_argument(
        "--strategy",
        choices=["granular", "whole-buy", "fifo"],
        default="granular",
        help="Matching strategy: 'granular' (default tax-minimizing parcel split), 'whole-buy' (intact buy contracts), or 'fifo' (first-in first-out)",
    )
    p_match.add_argument("--input-mapping", help="Optional path to prior-year mapping JSON file to chain balances")
    p_match.add_argument("--output-mapping", help="Optional path to output the updated mapping JSON file")
    p_match.add_argument("--save", action="store_true", help="Persist matches to default or output mapping file")
    p_match.set_defaults(func=handle_match)

    # Export / Report subcommand
    for cmd in ["export", "report"]:
        p_export = subparsers.add_parser(cmd, help="Export human-readable Markdown and accountant CSV reports")
        p_export.add_argument("--entity", help="Entity name (e.g. entity-1)")
        p_export.add_argument("--dir", help="Directory containing mapping JSON files (e.g. data/matched-entity-1)")
        p_export.add_argument("--input-mapping", help="Direct path to mapping JSON file")
        p_export.add_argument("--output-dir", "--out-dir", dest="output_dir", help="Base directory to save output reports")
        p_export.add_argument("--parcels-csv", help="Custom output path for matched parcels CSV")
        p_export.add_argument("--summary-csv", help="Custom output path for annual CGT tax summary CSV")
        p_export.add_argument("--report-md", help="Custom output path for Markdown audit report")
        p_export.add_argument("--stdout", action="store_true", help="Print Markdown report directly to terminal stdout")
        p_export.set_defaults(func=handle_export)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
