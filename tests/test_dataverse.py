"""Tests for the Harvard Dataverse platform-corpus ingest.

The filename cases below are all real names taken from the authoritative archive, and the
reconciliation test encodes the correctness point that actually matters for this dataset:
the two shipped zips are *not* additive, and unioning them silently inflates the corpus.
"""

from __future__ import annotations

import re
import zipfile

import pytest

from state_politics.platforms.dataverse import (
    DATASET_FILES,
    MAJOR_PARTIES,
    US_STATES,
    coverage_matrix,
    decode_text,
    load_changelog,
    load_corpus,
    normalize_party,
    parse_filename,
    reconcile,
    strip_rtf,
)


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("TX-2016-R-B-GG.txt", ("TX", 2016, "R", ("B", "GG"))),
        ("OH-1966-D.txt", ("OH", 1966, "D", ())),
        ("SD-1920-Non Partisan League-B.txt", ("SD", 1920, "Non Partisan League", ("B",))),
        ("US-1948-States' Rights-B-EA.txt", ("US", 1948, "States' Rights", ("B", "EA"))),
        ("US-1916-Socialist-B-EA.rtf", ("US", 1916, "Socialist", ("B", "EA"))),
        ("IA-2002-D-R.txt", ("IA", 2002, "D", ("R",))),
        ("WI-1998-US Taxpayers-B-GG.txt", ("WI", 1998, "US Taxpayers", ("B", "GG"))),
        ("TX-1894-Peoples.txt", ("TX", 1894, "Peoples", ())),
    ],
)
def test_parse_filename_handles_real_corpus_names(filename, expected):
    assert parse_filename(filename) == expected


@pytest.mark.parametrize(
    "bad",
    ["notaplatform.txt", "TXX-2016-R.txt", "TX-2016x-R.txt", "TX-2016-.txt"],
)
def test_parse_filename_rejects_rather_than_skips(bad):
    """A silently skipped file would be an invisible hole in the corpus."""
    with pytest.raises(ValueError):
        parse_filename(bad)


def test_normalize_party_keeps_factions_separate():
    assert normalize_party("D") == "D"
    assert normalize_party("R") == "R"
    # Gold Democrats and Radical Republicans were rival organizations, not the state party
    # of record, so folding them into D/R would misstate what that party said.
    assert normalize_party("GoldD") == "other"
    assert normalize_party("RadR") == "other"


def test_decode_text_handles_bom_and_cp1252():
    curly = "caf\u00e9 \u201cquoted\u201d"
    assert decode_text("plank".encode("utf-8-sig")) == "plank"
    assert decode_text(curly.encode("cp1252")) == curly
    assert decode_text(b"plain ascii") == "plain ascii"


def _write_zip(path, entries: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)


def test_load_corpus_ignores_applesingle_sidecars(tmp_path):
    """__MACOSX sidecars are ~half of every name list; counting them doubles the corpus."""
    zip_path = tmp_path / "platforms.zip"
    _write_zip(
        zip_path,
        {
            "OH_WY/TX-2016-R-B.txt": b"republican planks",
            "__MACOSX/OH_WY/._TX-2016-R-B.txt": b"\x00sidecar",
            "OH_WY/TX-2016-D-B.txt": b"democratic planks here",
        },
    )
    frame = load_corpus(zip_path)
    assert len(frame) == 2
    assert set(frame["party"]) == {"D", "R"}
    assert frame["n_words"].tolist() == [3, 2]


def test_reconcile_confirms_update_supersedes_older_archive(tmp_path):
    new_zip = tmp_path / "new.zip"
    old_zip = tmp_path / "old.zip"
    changelog = tmp_path / "file_changes.txt"

    _write_zip(new_zip, {
        "SC-2017-D.txt": b"added doc",          # in changelog Added
        "TX-2016-R-B.txt": b"revised text",     # shared, content differs
        "OH-1966-D.txt": b"same",               # shared, identical
    })
    _write_zip(old_zip, {
        "MN-2008-D-B.txt": b"deleted doc",      # in changelog Deleted
        "TX-2016-R-B.txt": b"original text",
        "OH-1966-D.txt": b"same",
    })
    changelog.write_text(
        "Notes about the archive.\n\nAdded\n-----\nSC-2017-D.txt\n\n"
        "Deleted\n-------\nMN-2008-D-B.txt\n",
        encoding="utf-8",
    )

    added, deleted = load_changelog(changelog)
    assert added == {"SC-2017-D.txt"}
    assert deleted == {"MN-2008-D-B.txt"}

    report = reconcile(new_zip, old_zip, changelog)
    assert report.consistent
    assert report.authoritative_count == 3
    assert report.superseded_count == 3
    assert report.added_confirmed == {"SC-2017-D.txt"}
    assert report.deleted_confirmed == {"MN-2008-D-B.txt"}
    assert report.revised_in_place == 1


def test_reconcile_flags_a_changelog_that_does_not_match(tmp_path):
    new_zip = tmp_path / "new.zip"
    old_zip = tmp_path / "old.zip"
    changelog = tmp_path / "file_changes.txt"
    _write_zip(new_zip, {"OH-1966-D.txt": b"x"})
    _write_zip(old_zip, {"OH-1966-D.txt": b"x"})
    changelog.write_text("Added\n-----\nNOT-1999-D.txt\n\nDeleted\n-------\n", encoding="utf-8")

    report = reconcile(new_zip, old_zip, changelog)
    assert not report.consistent
    assert report.added_unconfirmed == {"NOT-1999-D.txt"}


def test_coverage_matrix_shows_absent_states_as_explicit_zeros(tmp_path):
    """Maryland is absent from the real corpus; an absence must be visible, not a missing row."""
    zip_path = tmp_path / "platforms.zip"
    _write_zip(zip_path, {
        "TX-2016-R-B.txt": b"a",
        "TX-2012-R-B.txt": b"b",
        "TX-2016-D-B.txt": b"c",
        "US-2016-D-B.txt": b"national",
    })
    coverage = coverage_matrix(load_corpus(zip_path))

    assert len(coverage) >= len(US_STATES)
    md = coverage.loc[coverage["state"] == "MD"].iloc[0]
    assert md["n_D"] == 0 and md["n_R"] == 0
    assert md["n_total"] == 0

    tx = coverage.loc[coverage["state"] == "TX"].iloc[0]
    assert tx["n_R"] == 2
    assert tx["n_D"] == 1
    assert tx["latest_R"] == 2016
    assert tx["n_total"] == 3


def test_major_parties_are_exactly_d_and_r():
    assert sorted(MAJOR_PARTIES) == ["D", "R"]


def test_strip_rtf_removes_metadata_groups_not_just_control_words():
    """A regex-only strip leaves the font table's payload behind as fake words."""
    rtf = (
        r"{\rtf1\ansi\ansicpg1252\cocoartf2513"
        r"{\fonttbl\f0\fswiss\fcharset0 Helvetica;\f1 HelveticaNeue;}"
        r"{\colortbl;\red255\green255\blue255;}"
        r"{\*\expandedcolortbl;;}"
        r"\deftab560\pard\tx560 Socialist Platform of 1916\par "
        r"We demand \'93justice\'94 for all.}"
    )
    out = strip_rtf(rtf)
    assert "Socialist Platform of 1916" in out
    assert "We demand \u201cjustice\u201d for all." in out
    for junk in ("Helvetica", "fonttbl", "colortbl", "cocoartf", "deftab", "expandedcolortbl"):
        assert junk not in out


def test_strip_rtf_leaves_plain_text_untouched():
    plain = "We support public education.\nAnd fair wages."
    assert strip_rtf(plain) == plain


def test_dataset_files_carry_publisher_digests():
    """Downloads are checked against Dataverse's own MD5s, so substituted content fails loudly."""
    assert len(DATASET_FILES) == 3
    for spec in DATASET_FILES:
        assert re.fullmatch(r"[0-9a-f]{32}", spec.md5), spec.filename
