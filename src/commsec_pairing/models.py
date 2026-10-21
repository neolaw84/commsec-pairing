"""Domain data models and schemas for CommSec Pairing."""

from datetime import UTC, date, datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class TradeAction(str, Enum):
    BUY = "B"
    SELL = "S"


class MatchingStrategy(str, Enum):
    GRANULAR = "granular"
    WHOLE_BUY = "whole_buy"
    FIFO = "fifo"


class ParsedTrade(BaseModel):
    action: TradeAction
    units: int
    security: str
    unit_price: float
    is_short: bool = False


class Transaction(BaseModel):
    date: date
    reference: str
    details: str
    debit: float | None = None
    credit: float | None = None
    balance: float | None = None
    parsed_trade: ParsedTrade | None = None
    is_short: bool = False

    @property
    def is_contract(self) -> bool:
        return bool(self.reference) and self.parsed_trade is not None


class ContractNote(BaseModel):
    file_path: str
    file_name: str
    contract_id: str
    contract_ref: str
    action: TradeAction | None = None
    security: str | None = None
    units: int | None = None
    trade_date: date | None = None


class MatchLeg(BaseModel):
    contract_ref: str
    trade_date: date
    unit_price_aud: float
    allocated_brokerage_aud: float = 0.0


class MatchRecord(BaseModel):
    match_id: str
    financial_year: int
    security: str
    matched_units: int
    buy: MatchLeg
    sell: MatchLeg
    holding_period_days: int
    cgt_discount_eligible: bool
    gross_gain_loss_aud: float
    taxable_gain_loss_aud: float
    strategy: MatchingStrategy = MatchingStrategy.GRANULAR
    is_short: bool = False


class BuyInventoryLot(BaseModel):
    contract_ref: str
    trade_date: date
    security: str
    unit_price_aud: float = 0.0
    total_units: int
    matched_units: int = 0
    remaining_units: int
    is_exhausted: bool = False
    is_short: bool = False

    @field_validator("remaining_units")
    @classmethod
    def validate_remaining(cls, v: int) -> int:
        if v < 0:
            raise ValueError("Remaining units cannot be negative.")
        return v


class PersistentMappingStore(BaseModel):
    version: str = "1.0"
    entity: str
    last_updated: datetime = Field(default_factory=lambda: datetime.now(UTC))
    matches: list[MatchRecord] = Field(default_factory=list)
    buy_inventory: list[BuyInventoryLot] = Field(default_factory=list)


class ReconciliationReport(BaseModel):
    entity: str
    total_csv_trades: int
    total_pdf_contracts: int
    matched_contracts: int
    missing_contracts_errors: list[str] = Field(default_factory=list)
    unreferenced_contracts_warnings: list[str] = Field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return len(self.missing_contracts_errors) > 0

    @property
    def has_warnings(self) -> bool:
        return len(self.unreferenced_contracts_warnings) > 0
