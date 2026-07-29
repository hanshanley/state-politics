"""Ingest state legislators and their party from Open States.

This is the join key for the whole bills stream: a bill tells you who sponsored it, and this
tells you which party that sponsor belongs to. Without it, "what are Republican legislators
filing?" cannot be answered at all.

Source
------
Open States / Plural Policy publish one CSV per jurisdiction of currently-serving legislators
at ``https://data.openstates.org/people/current/{code}.csv``. These files are **public and
need no authentication**, unlike the per-session bill archives, which are login-gated.

Scope
-----
Only the 50 state legislatures. The publisher also exposes ``us`` (Congress) and the
territories; Congress is explicitly out of scope for this project, and the territories are
excluded by default so a careless join cannot quietly widen the population being described.
"""

from __future__ import annotations

import argparse
import csv
import io
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from ..provenance import ProvenanceLog, fetch

__all__ = [
    "PEOPLE_CSV_URL",
    "SOURCE_ORG",
    "STATE_CODES",
    "Legislator",
    "download_people",
    "normalize_party",
    "parse_people_csv",
]

PEOPLE_CSV_URL = "https://data.openstates.org/people/current/{code}.csv"

#: Credit the organization that collected and standardized the data. Open States compiles it
#: by scraping the state legislatures' own sites, which are the originating source.
SOURCE_ORG = "Open States / Plural Policy (current legislator CSVs)"

#: The 50 states, lowercased to match the publisher's file naming.
STATE_CODES = (
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga",
    "hi", "id", "il", "in", "ia", "ks", "ky", "la", "me", "md",
    "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj",
    "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc",
    "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv", "wi", "wy",
)

#: Party strings seen in the source, mapped to the project's canonical codes. Anything else
#: becomes "other" with the original string preserved, because several states seat genuine
#: third parties and Nebraska's legislature is formally nonpartisan.
_PARTY_MAP = {
    "democratic": "D",
    "democrat": "D",
    "democratic-farmer-labor": "D",
    "democratic-npl": "D",
    "republican": "R",
}


@dataclass(frozen=True, slots=True)
class Legislator:
    """One currently-serving state legislator."""

    state: str
    openstates_id: str
    name: str
    party: str
    party_raw: str
    chamber: str
    district: str

    @property
    def is_major_party(self) -> bool:
        return self.party in ("D", "R")


def normalize_party(value: str | None) -> str:
    """Map a source party string to ``"D"``, ``"R"`` or ``"other"``.

    Nebraska's unicameral is officially nonpartisan and several states seat independents and
    third parties, so an unrecognised value is kept as "other" rather than forced into one of
    the two major parties.
    """
    return _PARTY_MAP.get((value or "").strip().lower(), "other")


def parse_people_csv(text: str, state: str) -> list[Legislator]:
    """Parse one jurisdiction's legislator CSV."""
    rows = csv.DictReader(io.StringIO(text))
    people = []
    for row in rows:
        party_raw = (row.get("current_party") or row.get("party") or "").strip()
        people.append(Legislator(
            state=state.upper(),
            openstates_id=(row.get("id") or "").strip(),
            name=(row.get("name") or "").strip(),
            party=normalize_party(party_raw),
            party_raw=party_raw,
            chamber=(row.get("current_chamber") or row.get("chamber") or "").strip(),
            district=(row.get("current_district") or row.get("district") or "").strip(),
        ))
    return people


def download_people(
    *,
    states: tuple[str, ...] = STATE_CODES,
    log: ProvenanceLog | None = None,
    transport=None,
    delay: float = 0.5,
    sleep=time.sleep,
) -> tuple[list[Legislator], dict[str, str]]:
    """Fetch every state's legislator CSV. Returns ``(legislators, errors_by_state)``.

    A state whose download fails is reported in ``errors`` rather than silently contributing
    zero legislators, so a partial run cannot be mistaken for a complete one.
    """
    people: list[Legislator] = []
    errors: dict[str, str] = {}
    for index, code in enumerate(states):
        body, record = fetch(
            PEOPLE_CSV_URL.format(code=code),
            source_org=SOURCE_ORG,
            log=log,
            transport=transport,
            timeout=60.0,
            max_attempts=3,
            sleep=sleep,
            note=f"current legislators for {code.upper()}",
        )
        if not record.ok or body is None:
            errors[code.upper()] = f"status={record.http_status} error={record.error}"
        else:
            people.extend(parse_people_csv(body.decode("utf-8", errors="replace"), code))
        if delay and index < len(states) - 1:
            sleep(delay)
    return people, errors


def main(argv: list[str] | None = None) -> int:
    import pandas as pd

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out-dir", default="data/processed")
    parser.add_argument("--provenance", default="data/provenance.jsonl")
    parser.add_argument("--delay", type=float, default=0.5)
    args = parser.parse_args(argv)

    log = ProvenanceLog(args.provenance)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    with log.session():
        people, errors = download_people(log=log, delay=args.delay)

    frame = pd.DataFrame(
        [asdict(person) | {"is_major_party": person.is_major_party} for person in people]
    )
    path = out_dir / "legislators_current.parquet"
    frame.to_parquet(path, index=False)

    print(f"legislators:      {len(frame)}")
    print(f"states covered:   {frame['state'].nunique()}/50")
    print(f"by party:         {frame['party'].value_counts().to_dict()}")
    print(f"chambers:         {frame['chamber'].value_counts().to_dict()}")
    if errors:
        print(f"FAILED states:    {errors}")
    print(f"wrote {path}")
    return 1 if errors else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
