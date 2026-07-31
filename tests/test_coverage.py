"""Tests for machine-readable analytical capability reporting."""

from __future__ import annotations

import pandas as pd

from state_politics.analysis.coverage import build_capability_report


def test_capability_report_distinguishes_unsupported_questions(tmp_path):
    pd.DataFrame(
        [
            {
                "state": "TX", "party": "D", "confirmed": True, "year": 2024,
                "subject": "", "sponsor_party": "D",
            }
        ]
    ).drop(columns=["subject", "sponsor_party"]).to_parquet(
        tmp_path / "platforms_2018_present.parquet"
    )
    pd.DataFrame(
        [{"state": "KY", "party": "R"}]
    ).to_parquet(tmp_path / "caucus_priorities.parquet")
    pd.DataFrame(
        [{"state": "TX", "sponsor_party": "D", "subject": "Elections"}]
    ).to_parquet(tmp_path / "bills.parquet")
    pd.DataFrame(
        [
            {
                "state": "TX", "party": "D", "stated_focus_reliable": True,
            }
        ]
    ).to_csv(tmp_path / "state_party_focus.csv", index=False)
    pd.DataFrame(
        [{"state": "TX", "party": "D", "n_election_bills": 1}]
    ).to_csv(tmp_path / "election_focus_by_state_party.csv", index=False)
    pd.DataFrame(
        [{"state": "TX", "party": "D", "n_confirmed": 1}]
    ).to_csv(tmp_path / "platform_gap_report.csv", index=False)

    report = build_capability_report(tmp_path).set_index("question")

    assert report.loc["Bill enactment/pass rates", "support"] == "unsupported"
    assert report.loc["Roll-call voting behavior", "support"] == "unsupported"
    assert report.loc["Policy stance or ideological direction", "support"] == "limited"
    assert report.loc["Current stated state-level agenda", "support"] == "supported"
