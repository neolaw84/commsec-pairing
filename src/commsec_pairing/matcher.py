"""Bipartite matching and Capital Gains Tax (CGT) minimization engine."""

import uuid
from datetime import date

import pulp

from commsec_pairing.models import (
    BuyInventoryLot,
    MatchingStrategy,
    MatchLeg,
    MatchRecord,
    PersistentMappingStore,
    TradeAction,
    Transaction,
)


def get_financial_year(trade_date: date) -> int:
    """
    Compute Australian Financial Year (FY) for a given date.
    July 1st Year k to June 30th Year k+1 belongs to FY (k+1).
    E.g. 2025-07-01 -> FY 2026; 2026-06-30 -> FY 2026.
    """
    return trade_date.year + 1 if trade_date.month >= 7 else trade_date.year


def calculate_cgt_unit_cost(
    buy_unit_price: float,
    sell_unit_price: float,
    buy_date: date,
    sell_date: date,
    buy_brokerage_per_unit: float = 0.0,
    sell_brokerage_per_unit: float = 0.0,
) -> tuple[int, bool, float, float]:
    """
    Calculate holding period, discount eligibility, gross gain/loss, and taxable gain/loss.
    Enforces that buy date must not be after sell date.
    """
    if buy_date > sell_date:
        raise ValueError(
            f"Temporal violation: Buy date ({buy_date}) cannot be after Sell date ({sell_date})."
        )

    holding_days = (sell_date - buy_date).days
    discount_eligible = holding_days > 365

    cost_base = buy_unit_price + buy_brokerage_per_unit
    net_proceeds = sell_unit_price - sell_brokerage_per_unit
    gross_gain_loss = net_proceeds - cost_base

    if gross_gain_loss > 0:
        taxable_gain_loss = (0.5 * gross_gain_loss) if discount_eligible else gross_gain_loss
    else:
        taxable_gain_loss = gross_gain_loss  # Capital loss (100% offsets capital gains)

    return holding_days, discount_eligible, gross_gain_loss, taxable_gain_loss


class CGTMatcher:
    """Formulates and solves the bipartite unit matching optimization problem."""

    def __init__(self, store: PersistentMappingStore):
        self.store = store

    def optimize_financial_year(
        self,
        transactions: list[Transaction],
        target_fy: int,
        strategy: MatchingStrategy = MatchingStrategy.GRANULAR,
    ) -> list[MatchRecord]:
        """
        Match all sell transactions in the target financial year with available
        buy inventory lots to minimize total taxable capital gains.
        """
        # Filter sell transactions for target FY
        sell_txs = [
            tx
            for tx in transactions
            if tx.reference.startswith("C")
            and tx.parsed_trade
            and tx.parsed_trade.action == TradeAction.SELL
            and get_financial_year(tx.date) == target_fy
        ]

        # Check existing matches to avoid duplicate matching for already paired sell contracts
        already_matched_sell_refs = {
            m.sell.contract_ref for m in self.store.matches if m.financial_year == target_fy
        }
        unmatched_sells = [
            tx for tx in sell_txs if tx.reference not in already_matched_sell_refs
        ]

        if not unmatched_sells:
            return []

        # Group by security ticker
        sells_by_security: dict[str, list[Transaction]] = {}
        for s in unmatched_sells:
            sec = s.parsed_trade.security
            sells_by_security.setdefault(sec, []).append(s)

        new_matches: list[MatchRecord] = []

        # Optimize each security independently
        for security, sells in sells_by_security.items():
            available_buys = [
                lot
                for lot in self.store.buy_inventory
                if lot.security == security and lot.remaining_units > 0
            ]

            if strategy == MatchingStrategy.WHOLE_BUY:
                sec_matches = self._solve_whole_buy_matching(
                    security, available_buys, sells, target_fy
                )
            elif strategy == MatchingStrategy.FIFO:
                sec_matches = self._solve_fifo_matching(
                    security, available_buys, sells, target_fy
                )
            else:
                sec_matches = self._solve_granular_matching(
                    security, available_buys, sells, target_fy
                )

            new_matches.extend(sec_matches)

        return new_matches

    def _solve_fifo_matching(
        self,
        security: str,
        buys: list[BuyInventoryLot],
        sells: list[Transaction],
        fy: int,
    ) -> list[MatchRecord]:
        """
        Solve unit-based FIFO (First-In, First-Out) matching.
        Greedily allocates units from the earliest unexhausted buy lots to chronological sells.
        """
        sells_sorted = sorted(sells, key=lambda s: (s.date, s.reference))
        buys_sorted = sorted(buys, key=lambda b: (b.trade_date, b.contract_ref))

        # Local tracking of remaining units across buy lots
        remaining_units = {b.contract_ref: b.remaining_units for b in buys_sorted}

        matches: list[MatchRecord] = []

        for sell in sells_sorted:
            demand = sell.parsed_trade.units
            sell_unit_p = sell.parsed_trade.unit_price

            for buy in buys_sorted:
                # Strict temporal constraint: do not match with future buy
                if buy.trade_date > sell.date:
                    continue

                available = remaining_units[buy.contract_ref]
                if available <= 0:
                    continue

                alloc_units = min(demand, available)
                buy_unit_p = buy.unit_price_aud

                holding_days, discount_ok, gross_gain_unit, tax_gain_unit = (
                    calculate_cgt_unit_cost(
                        buy_unit_price=buy_unit_p,
                        sell_unit_price=sell_unit_p,
                        buy_date=buy.trade_date,
                        sell_date=sell.date,
                    )
                )

                matches.append(
                    MatchRecord(
                        match_id=f"m_{fy}_{uuid.uuid4().hex[:8]}",
                        financial_year=fy,
                        security=security,
                        matched_units=alloc_units,
                        buy=MatchLeg(
                            contract_ref=buy.contract_ref,
                            trade_date=buy.trade_date,
                            unit_price_aud=buy_unit_p,
                        ),
                        sell=MatchLeg(
                            contract_ref=sell.reference,
                            trade_date=sell.date,
                            unit_price_aud=sell_unit_p,
                        ),
                        holding_period_days=holding_days,
                        cgt_discount_eligible=discount_ok,
                        gross_gain_loss_aud=round(gross_gain_unit * alloc_units, 2),
                        taxable_gain_loss_aud=round(tax_gain_unit * alloc_units, 2),
                        strategy=MatchingStrategy.FIFO,
                    )
                )

                remaining_units[buy.contract_ref] -= alloc_units
                demand -= alloc_units

                if demand == 0:
                    break

            if demand > 0:
                raise RuntimeError(
                    f"FIFO matching failed for {security} in FY{fy}: "
                    f"Insufficient prior buy units to fulfill sell {sell.reference} on {sell.date} "
                    f"(deficit: {demand} units)."
                )

        return matches

    def _solve_granular_matching(
        self,
        security: str,
        buys: list[BuyInventoryLot],
        sells: list[Transaction],
        fy: int,
    ) -> list[MatchRecord]:
        """
        Solve default granular matching via Continuous Linear Programming (LP).
        Because the bipartite transportation constraint matrix is Totally Unimodular (TUM),
        the continuous LP relaxation is mathematically guaranteed to yield exact integer extreme points.
        """
        prob = pulp.LpProblem(f"CGT_Minimization_Granular_{security}_{fy}", pulp.LpMinimize)

        x_vars = {}
        cost_coefficients = {}

        for i, buy in enumerate(buys):
            for j, sell in enumerate(sells):
                # Strict temporal constraint: do not match with a future buy
                if buy.trade_date > sell.date:
                    continue

                var_name = f"x_{i}_{j}"
                x_vars[(i, j)] = pulp.LpVariable(var_name, lowBound=0, cat=pulp.LpContinuous)

                buy_unit_price = buy.unit_price_aud
                sell_unit_price = sell.parsed_trade.unit_price

                _, _, _, taxable_gain_unit = calculate_cgt_unit_cost(
                    buy_unit_price=buy_unit_price,
                    sell_unit_price=sell_unit_price,
                    buy_date=buy.trade_date,
                    sell_date=sell.date,
                )
                cost_coefficients[(i, j)] = taxable_gain_unit

        if not x_vars:
            raise RuntimeError(
                f"No eligible prior buy contracts found for {security} sales in FY{fy}. "
                f"All available buy lots post-date the sell dates."
            )

        # Objective Function: Minimize taxable capital gains
        prob += pulp.lpSum([x_vars[k] * cost_coefficients[k] for k in x_vars])

        # Constraint 1: Satisfy each sell contract's units
        for j, sell in enumerate(sells):
            sell_vars = [x_vars[(i, j)] for i in range(len(buys)) if (i, j) in x_vars]
            if not sell_vars:
                raise RuntimeError(
                    f"No prior buy contracts available to satisfy sell {sell.reference} ({sell.date})."
                )
            prob += (
                pulp.lpSum(sell_vars) == sell.parsed_trade.units,
                f"Sell_Demand_{sell.reference}",
            )

        # Constraint 2: Inventory capacity for each buy lot
        for i, buy in enumerate(buys):
            buy_vars = [x_vars[(i, j)] for j in range(len(sells)) if (i, j) in x_vars]
            if buy_vars:
                prob += (
                    pulp.lpSum(buy_vars) <= buy.remaining_units,
                    f"Buy_Capacity_{buy.contract_ref}",
                )

        prob.solve(pulp.PULP_CBC_CMD(msg=False))

        if prob.status != pulp.LpStatusOptimal:
            raise RuntimeError(
                f"Optimization failed for {security} in FY{fy} (Status: {pulp.LpStatus[prob.status]}). "
                f"Likely insufficient historical buy units."
            )

        matches: list[MatchRecord] = []
        for (i, j), var in x_vars.items():
            raw_val = var.varValue or 0.0
            allocated_units = round(raw_val)
            if allocated_units > 0:
                if abs(raw_val - allocated_units) > 1e-4:
                    raise RuntimeError(
                        f"Numerical precision error: LP returned non-integer allocation {raw_val} for {var.name}."
                    )

                buy = buys[i]
                sell = sells[j]
                buy_unit_p = buy.unit_price_aud
                sell_unit_p = sell.parsed_trade.unit_price

                holding_days, discount_ok, gross_gain_unit, tax_gain_unit = (
                    calculate_cgt_unit_cost(
                        buy_unit_price=buy_unit_p,
                        sell_unit_price=sell_unit_p,
                        buy_date=buy.trade_date,
                        sell_date=sell.date,
                    )
                )

                matches.append(
                    MatchRecord(
                        match_id=f"m_{fy}_{uuid.uuid4().hex[:8]}",
                        financial_year=fy,
                        security=security,
                        matched_units=allocated_units,
                        buy=MatchLeg(
                            contract_ref=buy.contract_ref,
                            trade_date=buy.trade_date,
                            unit_price_aud=buy_unit_p,
                        ),
                        sell=MatchLeg(
                            contract_ref=sell.reference,
                            trade_date=sell.date,
                            unit_price_aud=sell_unit_p,
                        ),
                        holding_period_days=holding_days,
                        cgt_discount_eligible=discount_ok,
                        gross_gain_loss_aud=round(gross_gain_unit * allocated_units, 2),
                        taxable_gain_loss_aud=round(tax_gain_unit * allocated_units, 2),
                        strategy=MatchingStrategy.GRANULAR,
                    )
                )

        return matches

    def _solve_whole_buy_matching(
        self,
        security: str,
        buys: list[BuyInventoryLot],
        sells: list[Transaction],
        fy: int,
    ) -> list[MatchRecord]:
        """
        Solve Whole Buy Contract matching (Buy Contract to Sell Contract is 1 to Many).
        Each buy contract is matched as an indivisible whole parcel.
        NP-hard Exact Multi-Knapsack problem with problem size ceiling and timeout.
        """
        MAX_WHOLE_BUY_LOTS = 500
        MAX_WHOLE_BUY_COMBINATIONS = 5000
        WHOLE_BUY_TIMEOUT_SECONDS = 60

        if len(buys) > MAX_WHOLE_BUY_LOTS:
            raise RuntimeError(
                f"Whole Buy matching exceeds safety ceiling: {len(buys)} candidate buy lots found for {security} "
                f"(maximum allowed: {MAX_WHOLE_BUY_LOTS}). The 0-1 Knapsack problem is NP-hard. "
                f"Please use the polynomial-time default 'granular' strategy."
            )

        if len(buys) * len(sells) > MAX_WHOLE_BUY_COMBINATIONS:
            raise RuntimeError(
                f"Whole Buy matching search space exceeds safety ceiling: {len(buys)} buys * {len(sells)} sells = "
                f"{len(buys) * len(sells)} pairings (maximum allowed: {MAX_WHOLE_BUY_COMBINATIONS}). "
                f"Please use the polynomial-time default 'granular' strategy."
            )

        prob = pulp.LpProblem(f"CGT_Minimization_WholeBuy_{security}_{fy}", pulp.LpMinimize)

        # Binary decision variable: y[i, j] = 1 if whole buy lot i is allocated to sell j
        y_vars = {}
        cost_coefficients = {}

        for i, buy in enumerate(buys):
            for j, sell in enumerate(sells):
                # Strict temporal constraint: do not match with a future buy
                if buy.trade_date > sell.date:
                    continue

                var_name = f"y_{i}_{j}"
                y_vars[(i, j)] = pulp.LpVariable(var_name, cat=pulp.LpBinary)

                buy_unit_price = buy.unit_price_aud
                sell_unit_price = sell.parsed_trade.unit_price

                _, _, _, taxable_gain_unit = calculate_cgt_unit_cost(
                    buy_unit_price=buy_unit_price,
                    sell_unit_price=sell_unit_price,
                    buy_date=buy.trade_date,
                    sell_date=sell.date,
                )
                # Cost for allocating the whole buy lot
                cost_coefficients[(i, j)] = taxable_gain_unit * buy.remaining_units

        if not y_vars:
            raise RuntimeError(
                f"No eligible prior buy contracts found for {security} sales in FY{fy}."
            )

        # Objective Function: Minimize total taxable capital gains
        prob += pulp.lpSum([y_vars[k] * cost_coefficients[k] for k in y_vars])

        # Constraint 1: Satisfy each sell contract's units exactly with whole buy contracts
        for j, sell in enumerate(sells):
            sell_vars = [y_vars[(i, j)] for i in range(len(buys)) if (i, j) in y_vars]
            if not sell_vars:
                raise RuntimeError(
                    f"No prior buy contracts available to satisfy sell {sell.reference} ({sell.date})."
                )
            prob += (
                pulp.lpSum([y_vars[(i, j)] * buys[i].remaining_units for i in range(len(buys)) if (i, j) in y_vars])
                == sell.parsed_trade.units,
                f"Sell_Demand_WholeBuy_{sell.reference}",
            )

        # Constraint 2: Each whole buy lot can be allocated to at most ONE sell contract
        for i, buy in enumerate(buys):
            buy_vars = [y_vars[(i, j)] for j in range(len(sells)) if (i, j) in y_vars]
            if buy_vars:
                prob += (
                    pulp.lpSum(buy_vars) <= 1,
                    f"WholeBuy_Allocation_Limit_{buy.contract_ref}",
                )

        prob.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=WHOLE_BUY_TIMEOUT_SECONDS))

        if prob.status == pulp.LpStatusInfeasible or prob.status == pulp.LpStatusUndefined:
            raise RuntimeError(
                f"Whole Buy Contract matching infeasible for {security} in FY{fy}. "
                f"No exact subset-sum combination of whole buy parcels can fulfill the sell parcel quantities. "
                f"Please use the default 'granular' matching strategy."
            )
        elif prob.status != pulp.LpStatusOptimal:
            raise RuntimeError(
                f"Whole Buy Contract matching failed for {security} in FY{fy} (Status: {pulp.LpStatus[prob.status]}). "
                f"The solver exceeded the {WHOLE_BUY_TIMEOUT_SECONDS}s time limit or encountered a solver limit."
            )

        matches: list[MatchRecord] = []
        for (i, j), var in y_vars.items():
            if int(var.varValue or 0) == 1:
                buy = buys[i]
                sell = sells[j]
                allocated_units = buy.remaining_units

                buy_unit_p = buy.unit_price_aud
                sell_unit_p = sell.parsed_trade.unit_price

                holding_days, discount_ok, gross_gain_unit, tax_gain_unit = (
                    calculate_cgt_unit_cost(
                        buy_unit_price=buy_unit_p,
                        sell_unit_price=sell_unit_p,
                        buy_date=buy.trade_date,
                        sell_date=sell.date,
                    )
                )

                matches.append(
                    MatchRecord(
                        match_id=f"m_{fy}_{uuid.uuid4().hex[:8]}",
                        financial_year=fy,
                        security=security,
                        matched_units=allocated_units,
                        buy=MatchLeg(
                            contract_ref=buy.contract_ref,
                            trade_date=buy.trade_date,
                            unit_price_aud=buy_unit_p,
                        ),
                        sell=MatchLeg(
                            contract_ref=sell.reference,
                            trade_date=sell.date,
                            unit_price_aud=sell_unit_p,
                        ),
                        holding_period_days=holding_days,
                        cgt_discount_eligible=discount_ok,
                        gross_gain_loss_aud=round(gross_gain_unit * allocated_units, 2),
                        taxable_gain_loss_aud=round(tax_gain_unit * allocated_units, 2),
                        strategy=MatchingStrategy.WHOLE_BUY,
                    )
                )

        return matches
