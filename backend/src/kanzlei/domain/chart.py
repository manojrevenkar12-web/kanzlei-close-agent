"""A firm's chart of accounts: family + tax code -> account, and back.

Accounts that a firm uses but the standard excerpt does not know are mapped at onboarding by the
group engineer (table firm_accounts); `Chart.extend` adds them.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from functools import lru_cache
from typing import Any

import yaml

from kanzlei.config import config_dir

# Tax codes that a BU key cannot express: these need an automatic account.
AUTO_ONLY = {"RC_EU19", "RC_BAU19", "RC_DRITT19", "IGE19", "IGL", "EU_SVC", "RC_OUT", "FREI"}


@dataclass(frozen=True)
class Account:
    number: int
    name: str
    family: str
    tax: str
    auto: bool = False
    role: str | None = None


@dataclass(frozen=True)
class Chart:
    name: str
    length: int
    debtors: tuple[int, int]
    creditors: tuple[int, int]
    system: dict[str, int]
    bu_keys: dict[str, str]
    accounts: tuple[Account, ...]
    _by_number: dict[int, Account] = field(default_factory=dict, compare=False, repr=False)

    def __post_init__(self) -> None:
        self._by_number.update({a.number: a for a in self.accounts})

    def extend(self, extra: list[Account]) -> Chart:
        known = {a.number for a in self.accounts}
        return replace(self, accounts=self.accounts + tuple(a for a in extra if a.number not in known), _by_number={})

    def fmt(self, account: int) -> str:
        return str(account).zfill(self.length)

    def get(self, account: int) -> Account | None:
        return self._by_number.get(account)

    def name_of(self, account: int) -> str:
        a = self.get(account)
        if a:
            return a.name
        if self.is_creditor(account):
            return "Kreditor"
        if self.is_debtor(account):
            return "Debitor"
        for k, v in self.system.items():
            if v == account:
                return {
                    "bank": "Bank",
                    "cash": "Kasse",
                    "receivables": "Forderungen",
                    "payables": "Verbindlichkeiten",
                }.get(k, k)
        return ""

    def is_creditor(self, account: int) -> bool:
        return self.creditors[0] <= account <= self.creditors[1]

    def is_debtor(self, account: int) -> bool:
        return self.debtors[0] <= account <= self.debtors[1]

    def is_personal(self, account: int) -> bool:
        return self.is_creditor(account) or self.is_debtor(account)

    def account_for(self, family: str, tax: str, role: str | None = None) -> int | None:
        """The account for a family under a tax code; None if the chart cannot express it."""

        def pick(fam: str, tx: str) -> Account | None:
            for a in self.accounts:
                if a.family == fam and a.tax == tx and a.role == role:
                    return a
            return None

        hit = pick(family, tax) or (pick("*", tax) if role is None else None)
        if hit:
            return hit.number
        if tax in AUTO_ONLY:
            return None
        hit = pick(family, "*")
        return hit.number if hit else None

    def family_of(self, account: int) -> tuple[str, str | None] | None:
        a = self.get(account)
        return (a.family, a.role) if a else None

    def bu_key(self, account: int, tax: str) -> str:
        """The BU key the DATEV export writes for a tax code on this account ('' for automatic)."""
        a = self.get(account)
        if a and a.auto:
            return ""
        return self.bu_keys.get(tax, "")

    def tax_of(self, account: int, bu: str) -> str | None:
        """Reverse of bu_key (reading a DATEV history): the internal tax code of a booking line."""
        a = self.get(account)
        if a and a.auto:
            return a.tax
        if not bu:
            return "NONE"
        for code, key in self.bu_keys.items():
            if key == bu.strip():
                return code
        return None


def _load(name: str) -> dict[str, Any]:
    path = config_dir() / "charts" / f"{name.lower()}.yaml"
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data


@lru_cache
def chart(name: str) -> Chart:
    d = _load(name)
    accounts = tuple(
        Account(
            number=int(str(a["account"])),
            name=a["name"],
            family=a["family"],
            tax=str(a["tax"]),
            auto=bool(a.get("auto", False)),
            role=a.get("role"),
        )
        for a in d["accounts"]
    )
    return Chart(
        name=d["chart"],
        length=int(d["account_length"]),
        debtors=(int(d["debtors"][0]), int(d["debtors"][1])),
        creditors=(int(d["creditors"][0]), int(d["creditors"][1])),
        system={k: int(v) for k, v in d["system"].items()},
        bu_keys={str(k): str(v) for k, v in d["bu_keys"].items()},
        accounts=accounts,
    )
