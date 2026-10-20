"""Exact observations of single and joint New York print identities."""

import pytest

from state_politics.bills.new_york import parse_joint_print_header, parse_single_print_header


def single_header(*, session: str = "", chamber: str = "ASSEMBLY") -> str:
    return (
        "    STATE OF NEW YORK\n"
        "    _____________________________\n"
        "                 9438\n"
        f"{session}"
        f"    IN {chamber}\n"
        "    March 14, 2024\n"
        "    ___________\n"
        "    Introduced by M. of A. MEMBER -- read once\n"
        "    AN ACT referring to bill 9999\n"
    )


@pytest.mark.parametrize(("chamber", "identifier"), [
    ("ASSEMBLY", "A 9438"),
    ("SENATE", "S 9438"),
])
def test_single_header_keeps_printed_identity_without_inventing_session(chamber, identifier):
    source = single_header(chamber=chamber)
    result = parse_single_print_header(source)
    assert result is not None
    assert result.identifier == identifier
    assert source[result.number_source_start:result.number_source_end] == result.printed_number
    assert source[result.chamber_source_start:result.chamber_source_end] == result.printed_chamber
    assert result.printed_session is None
    assert result.session_source_start is result.session_source_end is None
    assert source[result.date_source_start:result.date_source_end] == "March 14, 2024"
    assert result.printed_date == "March 14, 2024"
    assert source[result.source_start:result.source_end].endswith("Introduced by")


def test_single_header_preserves_explicit_session_and_crlf_offsets():
    source = single_header(session="    2023-2024 Regular Sessions\n").replace("\n", "\r\n")
    result = parse_single_print_header(source)
    assert result is not None
    assert result.printed_session == "2023-2024 Regular Sessions"
    assert source[result.session_source_start:result.session_source_end] == result.printed_session
    assert source[result.number_source_start:result.number_source_end] == "9438"
    assert source[result.date_source_start:result.date_source_end] == result.printed_date


@pytest.mark.parametrize("source", [
    "The bill body quotes:\n" + single_header(),
    single_header().replace("9438\n", "9438--A\n"),
    single_header().replace("9438\n", "9438X\n"),
    single_header().replace("IN ASSEMBLY", "IN HOUSE"),
    single_header().replace("Introduced by", "Amended and reprinted"),
])
def test_single_header_rejects_body_references_amendments_and_unsupported_chambers(source):
    assert parse_single_print_header(source) is None


def test_single_header_rejects_nontext_input():
    with pytest.raises(ValueError, match="requires first-page text"):
        parse_single_print_header(None)


def joint_header(*, session: str = "", senate: str = "4044", assembly: str = "3051") -> str:
    return (
        "    STATE OF NEW YORK\n"
        "    _____________________________\n"
        f"    S. {senate}                    A. {assembly}\n"
        f"{session}"
        "    SENATE - ASSEMBLY\n"
        "    February 2, 2023\n"
        "    ___________\n"
        "    IN  SENATE  -- Introduced by a senator\n"
        "    IN ASSEMBLY -- Introduced by an assembly member\n"
        "    AN ACT with a reference to A. 9999 and S. 9998\n"
    )


def test_joint_header_keeps_distinct_identities_and_exact_reader_offsets():
    source = joint_header(session="    2023-2024 Regular Sessions\n")
    result = parse_joint_print_header(source)
    assert result is not None
    assert result.senate_identifier == "S 4044"
    assert result.assembly_identifier == "A 3051"
    assert source[result.senate_source_start:result.senate_source_end] == "S. 4044"
    assert source[result.assembly_source_start:result.assembly_source_end] == "A. 3051"
    assert source[result.session_source_start:result.session_source_end] == result.printed_session
    assert source[result.date_source_start:result.date_source_end] == result.printed_date
    assert result.printed_date == "February 2, 2023"
    assert source[result.source_start:result.source_end].endswith("IN  SENATE  --")


def test_budget_header_does_not_invent_an_unprinted_regular_session():
    source = joint_header(senate="4005", assembly="3005").replace("\n", "\r\n")
    result = parse_joint_print_header(source)
    assert result is not None
    assert (result.senate_identifier, result.assembly_identifier) == ("S 4005", "A 3005")
    assert result.printed_session is None
    assert result.session_source_start is result.session_source_end is None
    assert source[result.date_source_start:result.date_source_end] == "February 2, 2023"


@pytest.mark.parametrize("source", [
    "",
    "The body quotes:\n" + joint_header(),
    joint_header().replace("SENATE - ASSEMBLY", "IN ASSEMBLY"),
    joint_header().replace("S. 4044", "S. 4044--A"),
    joint_header().replace("A. 3051", "A. 3051--B"),
    joint_header().replace("S. 4044", "A. 4044"),
    joint_header().replace("A. 3051", "A. 30510X"),
    joint_header().replace("IN  SENATE  --", "IN ASSEMBLY --"),
])
def test_body_references_and_unobserved_or_amended_formats_do_not_match(source):
    assert parse_joint_print_header(source) is None


def test_nontext_input_fails_explicitly():
    with pytest.raises(ValueError, match="requires first-page text"):
        parse_joint_print_header(None)
