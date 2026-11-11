"""Which rail can carry money to whom, and what it costs.

Coverage and rates are data, not code: sanctions, local data rules and fee
contracts all change, and none of them belong inside an if-statement. A rail
that cannot reach a country stops a payment before it is attempted. A rail whose
country map was never verified stops nothing — an invented refusal is worse than
a provider declining the charge, because the state machine handles a decline
honestly and a policy cannot handle a policy that lied.

Amounts are integer minor units of one currency throughout this application, so
"cents" means 1/100 in USD, 1 unit in JPY and 1/1000 in BHD.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parents[1] / "data" / "rails.json"
HARD_BLOCKS = ("unavailable", "cannot_receive")
SOFT_FLAGS = ("no_local_withdrawal", "no_domestic", "limited")
# "Nothing leaves this machine" is not a rail in the catalog: it has no fees, no
# coverage and no currency list, so it lives here rather than in the data file.
SANDBOX_RAIL = "sandbox"


def _bps(amount_cents: int, basis_points: int) -> int:
    """Round half up, so a quote does not depend on floating point."""
    return (int(amount_cents) * int(basis_points) + 5_000) // 10_000


@dataclass(frozen=True)
class Rail:
    name: str
    label: str
    transport: str
    live: bool
    fee_bps: int
    fixed_cents: int
    cross_border_bps: int
    fx_spread_bps: int
    dispute_fee_cents: int
    chargeback_fee_cents: int
    settlement_note: str
    currencies: tuple[str, ...]
    coverage: dict[str, dict[str, str]]

    @property
    def verified(self) -> bool:
        return bool(self.coverage.get("unavailable") or self.coverage.get("cannot_receive"))

    def carries(self, currency: str) -> bool:
        return not currency or not self.currencies or currency in self.currencies

    def blocks(self, recipient_country: str, sender_country: str = "") -> str | None:
        """The reason this rail cannot deliver, or None if nothing is known against it."""
        if not recipient_country:
            return None
        for gate in HARD_BLOCKS:
            reason = self.coverage.get(gate, {}).get(recipient_country.upper())
            if reason:
                return f"{self.label} cannot reach {recipient_country.upper()}: {reason}"
        home = sender_country.upper() if sender_country else ""
        if home and home == recipient_country.upper():
            reason = self.coverage.get("no_domestic", {}).get(home)
            if reason:
                return f"{self.label} cannot pay domestically in {home}: {reason}"
        return None

    def flags(self, recipient_country: str) -> list[str]:
        """Soft warnings: the money can move, but the recipient's experience suffers."""
        country = (recipient_country or "").upper()
        return [
            f"{gate}: {reason}"
            for gate in SOFT_FLAGS
            for reason in [self.coverage.get(gate, {}).get(country)]
            if reason
        ]

    def fee_cents(
        self,
        amount_cents: int,
        *,
        sender_country: str = "",
        recipient_country: str = "",
        sender_currency: str = "",
        recipient_currency: str = "",
    ) -> int:
        fee = _bps(amount_cents, self.fee_bps) + self.fixed_cents
        if sender_country and recipient_country and sender_country.upper() != recipient_country.upper():
            fee += _bps(amount_cents, self.cross_border_bps)
        if sender_currency and recipient_currency and sender_currency.upper() != recipient_currency.upper():
            fee += _bps(amount_cents, self.fx_spread_bps)
        return fee


@dataclass(frozen=True)
class Catalog:
    compiled_on: str
    note: str
    sources: tuple[str, ...]
    minor_units: dict[str, int]
    exponent_overrides: dict[str, int]
    rails: dict[str, Rail]

    def exponent(self, currency: str) -> int:
        code = (currency or "USD").upper()
        if code in self.exponent_overrides:
            return self.exponent_overrides[code]
        return self.minor_units.get(code, 2)

    def amount_string(self, amount_cents: int, currency: str) -> str:
        """Minor units in the shape a provider asks for: '12.34', '150', '1.234'."""
        exponent = self.exponent(currency)
        value = int(amount_cents)
        if exponent <= 0:
            return str(value)
        whole, frac = divmod(value, 10**exponent)
        return f"{whole}.{frac:0{exponent}d}"

    def reachable(self, recipient_country: str, sender_country: str = "", currency: str = "") -> list[str]:
        """Rails that both deliver to that country and settle in that currency."""
        return [
            name
            for name, rail in sorted(self.rails.items())
            if rail.blocks(recipient_country, sender_country) is None and rail.carries(currency)
        ]

    def quote(
        self,
        amount_cents: int,
        *,
        sender_country: str = "",
        recipient_country: str = "",
        sender_currency: str = "",
        recipient_currency: str = "",
    ) -> list[dict]:
        """Every rail, cheapest first, with the reason any of them is excluded."""
        rows = []
        for name, rail in sorted(self.rails.items()):
            block = rail.blocks(recipient_country, sender_country)
            currency_ok = rail.carries(recipient_currency or sender_currency)
            fee = rail.fee_cents(
                amount_cents,
                sender_country=sender_country,
                recipient_country=recipient_country,
                sender_currency=sender_currency,
                recipient_currency=recipient_currency,
            )
            rows.append(
                {
                    "rail": name,
                    "label": rail.label,
                    "live": rail.live,
                    "fee_cents": fee,
                    "fee_dollars": round(fee / 100, 2),
                    "total_cents": int(amount_cents) + fee,
                    "flags": rail.flags(recipient_country),
                    "excluded": block or (None if currency_ok else f"{rail.label} does not settle in {recipient_currency or sender_currency}"),
                }
            )
        rows.sort(key=lambda row: (row["excluded"] is not None, row["fee_cents"], row["rail"]))
        return rows

    def summary(self) -> dict:
        return {
            "compiled_on": self.compiled_on,
            "note": self.note,
            "sources": list(self.sources),
            "rails": [
                {
                    "name": rail.name,
                    "label": rail.label,
                    "live": rail.live,
                    "coverage_verified": rail.verified,
                    "settlement_note": rail.settlement_note,
                    "flags": {gate: sorted(countries) for gate, countries in (rail.coverage.items())
                              if gate in {*HARD_BLOCKS, *SOFT_FLAGS} and countries},
                }
                for rail in sorted(self.rails.values(), key=lambda r: r.name)
            ],
        }


@lru_cache(maxsize=1)
def load_catalog(path: Path | None = None) -> Catalog:
    raw = json.loads((path or CATALOG_PATH).read_text(encoding="utf-8"))
    rails = {}
    for item in raw["rails"]:
        coverage = {gate: dict(item.get("coverage", {}).get(gate, {})) for gate in (*HARD_BLOCKS, *SOFT_FLAGS)}
        rails[item["name"]] = Rail(
            name=item["name"],
            label=item["label"],
            transport=item.get("transport", "sandbox"),
            live=bool(item.get("live", False)),
            fee_bps=int(item.get("fee_bps", 0)),
            fixed_cents=int(item.get("fixed_cents", 0)),
            cross_border_bps=int(item.get("cross_border_bps", 0)),
            fx_spread_bps=int(item.get("fx_spread_bps", 0)),
            dispute_fee_cents=int(item.get("dispute_fee_cents", 0)),
            chargeback_fee_cents=int(item.get("chargeback_fee_cents", 0)),
            settlement_note=item.get("settlement_note", ""),
            currencies=tuple(item.get("currencies", ())),
            coverage=coverage,
        )
    return Catalog(
        compiled_on=raw.get("compiled_on", ""),
        note=raw.get("note", ""),
        sources=tuple(raw.get("sources", ())),
        minor_units={code: int(exp) for code, exp in raw.get("minor_units", {}).items()},
        exponent_overrides={
            code: int(exp) for code, exp in raw.get("exponent_overrides", {}).get("values", {}).items()
        },
        rails=rails,
    )
