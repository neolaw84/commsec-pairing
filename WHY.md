# WHY.md — The Vision, Scope, and Rationale Behind CommSec Pairing

This document explains the foundational purpose, design philosophy, scope boundaries, and user impact of the **CommSec Pairing** project.

---

## 1. Context & The Core Problem

Investors trading on Commonwealth Bank's **CommSec** platform receive two primary artifacts:
1. **Transaction History CSVs**: Raw 6-column cash/settlement records spanning arbitrary date ranges that often overlap when downloaded across different sessions.
2. **Confirmation Contract Note PDFs**: Individual trade confirmation notes for every purchase and sale, often saved with arbitrary or messy filenames.

### The Problem with Existing Portfolio & Tax Software:
- **Rigid Matching Algorithms**: Most commercial tax tools enforce simple FIFO (First-In, First-Out) or average-cost accounting. Under Australian tax law (ATO), investors have the right to nominate specific parcels for liquidation (Specific Identification), allowing them to legally minimize their Capital Gains Tax (CGT) liability.
- **Fragile File Parsing**: Typical parsers rely on strict PDF filenames or single continuous CSV exports, breaking when files are overlapping, renamed, or formatted differently.
- **Cloud Lock-in & Privacy Risks**: Uploading raw financial exports to third-party cloud services exposes sensitive banking details, account identifiers, and trading patterns.

**CommSec Pairing** was built to solve these issues from first principles: providing a local-first, mathematically optimal, and audit-grade pairing engine directly compatible with raw CommSec downloads.

---

## 2. What This Repo IS Supposed to Do (In Scope)

### 1. Ingest, Deduplicate, and Verify Raw CommSec Downloads
- Ingest multiple overlapping transaction history CSVs and deduplicate rows using a robust 5-field fingerprint `(Reference, Date, Security, Units, Action)`.
- Reconcile CSV trade transactions against contract note PDFs by inspecting text streams directly—**completely agnostic to PDF filenames on disk**.
- Output clear, actionable integrity reports (Error on missing contract notes, Warning on unreferenced PDFs).

### 2. Formulate & Solve Optimal CGT Trade Matching
- Formulate trade allocation as a **Mixed-Integer Linear Program (MILP)** to minimize net taxable capital gains for any given Australian Financial Year (July 1 to June 30).
- Fully incorporate Australian CGT rules: 50% discount for assets held $> 365$ days, 100% taxable for assets held $\le 365$ days, and 1:1 offsetting of capital losses against gains.
- Enforce strict temporal ordering ($D_{\text{buy}} \le D_{\text{sell}}$) and immutable unit conservation ($1 \to [0, 1]$ unit mapping).

### 3. Support Multi-Strategy Matching & Multi-Year State Ledgering
- Provide multiple pairing strategies for comparative tax planning:
  - **`granular` (Default)**: Unit-level bipartite MILP optimization ($M \leftrightarrow N$).
  - **`whole-buy`**: 0-1 Knapsack MILP allocating intact buy contract parcels ($1 \to \text{Many}$).
  - **`fifo`**: Traditional unit-based First-In, First-Out chronological matching.
- Persist state across financial years via clean JSON ledgers (`--input-mapping` and `--output-mapping`), ensuring remaining parcel balances carry forward seamlessly.

---

## 3. What This Repo is NOT Supposed to Do (Out of Scope)

### 1. NOT a Real-Time Trading App or Portfolio Visualizer
- This repository does not provide live market data streaming, candlestick charts, real-time ticker prices, or active order execution. It is an end-of-year tax pairing, reconciliation, and ledgering system.

### 2. NOT an Automated Web Scraper or Login Bot
- This repository does not store CommSec credentials, bypass 2FA, or scrape CommSec web portals. It expects users to download their own statement CSVs and PDF notes securely from their CommSec accounts.

### 3. NOT a Regulated Financial Advisory Tool or Direct ATO Filing Conduit
- This repository does not provide financial advice, nor does it submit tax returns directly to the Australian Taxation Office (ATO) via SBR/API. It produces deterministic mathematical matching schedules and audit records for review by investors and registered tax agents.

---

## 4. Who and How This Repo Helps

### 1. DIY Investors & Traders in Australia
- **How it helps**: Automatically discovers the optimal combination of buy lots to sell against, legally minimizing taxable gains and maximizing after-tax returns. Eliminates hundreds of hours spent wrestling with complex manual Excel spreadsheets.

### 2. Accountants, Tax Agents & Bookkeepers
- **How it helps**: Accepts raw, messy client CommSec downloads directly without requiring manual renaming. Immediately flags missing contract notes and generates transparent, verifiable CGT schedules detailing holding periods, cost bases, and applied discounts.

### 3. Quantitative Developers & Portfolio Engineers
- **How it helps**: Provides an open-source, mathematically rigorous Python codebase with modular models, solver abstractions (PuLP), and CLI tools that can be extended or integrated into broader private accounting pipelines.

---

## 5. Key Design Philosophy

- **Mathematical Rigor**: CGT optimization is treated as an exact optimization problem, not heuristics or arbitrary approximations.
- **Privacy & Security by Default**: Zero telemetry, zero cloud dependencies, and zero storage of personal identifiers or credentials.
- **Content-First Integrity**: File metadata and names are treated as untrusted; ground truth is derived strictly from document content streams and verified balance conservation.

---

## 6. Open-Source Freedom & Friendly Disclaimer

### 🍺 Free as in Beer, 🗽 Free as in Speech
This project is **100% free and open-source**:
- **Free as in Beer (*Gratis*)**: It costs nothing to use, download, or run. There are no subscriptions, paywalls, premium tiers, or hidden monetization.
- **Free as in Speech (*Libre*)**: You have full freedom to inspect the source code, audit the mathematical formulations, modify the logic, and adapt it to your own personal workflow.

### ⚠️ Important Disclaimer: Not Financial, Legal, or Tax Advice
> [!IMPORTANT]
> **Please Read Carefully:**
> - **What This Tool Is**: An open, automated mathematical calculator and reconciliation script that runs algorithms on statement files you provide locally on your machine.
> - **What This Tool Is NOT**: A financial advisor, a tax agent, a legal representative, or an accounting service.
> 
> **Neither this software, this repository, its documentation, nor its creator(s) / contributor(s) provide—and will NEVER be deemed to provide—financial, investment, legal, accounting, or tax advice.**

### 🏢 Non-Affiliation Disclaimer
> [!NOTE]
> This independent open-source project, its repository, and its creator(s) / contributor(s) have **no affiliation, association, authorization, sponsorship, endorsement by, or official connection with Commonwealth Securities Limited (CommSec), Commonwealth Bank of Australia (CBA), or any of their subsidiaries, parent companies, or affiliates**.
> 
> The name "CommSec" and any associated names, marks, logos, and images are registered trademarks of their respective owners. Their mention in this repository is strictly for descriptive and software compatibility purposes.

### 🤝 The Friendly Summary:
- **Provided "As-Is"**: This software is provided on an "as-is" basis, without warranty of any kind, express or implied (including, but not limited to, the warranties of merchantability, fitness for a particular purpose, or accuracy).
- **Your Responsibility**: Tax laws (including Australian CGT rules and ATO rulings) are subject to change and depend on individual financial circumstances. You, in consultation with your qualified, registered tax professional or financial advisor, remain solely responsible for verifying the accuracy of any calculations and for all decisions, records, and tax lodgements.
