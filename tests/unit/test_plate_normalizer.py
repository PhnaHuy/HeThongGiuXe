"""Unit tests for license plate normalization and validation invariants."""

import pytest

from parking_app.domain.exceptions import ValidationError
from parking_app.domain.plate import (
    format_display_plate,
    normalize_plate,
    validate_normalized_plate,
)


def test_normalize_plate_strips_separators_and_uppercases() -> None:
    cases = [
        ("51F-123.45", "51F12345"),
        ("  29a  888.88  ", "29A88888"),
        ("72-G1-456.78", "72G145678"),
        ("43_b1/1234", "43B11234"),
        ("60.A-12345", "60A12345"),
    ]
    for raw, expected in cases:
        assert normalize_plate(raw) == expected


def test_normalize_plate_does_not_mutate_ambiguous_characters() -> None:
    # Rule: do NOT swap 0/O or 1/I
    assert normalize_plate("51-O1-12345") == "51O112345"
    assert normalize_plate("51-01-12345") == "510112345"
    assert normalize_plate("29-I1-12345") == "29I112345"
    assert normalize_plate("29-11-12345") == "291112345"


def test_normalize_empty_or_none() -> None:
    assert normalize_plate("") == ""
    assert normalize_plate("   ") == ""
    assert normalize_plate(None) == ""


def test_validate_normalized_plate_valid() -> None:
    for valid in ["51F12345", "29A88888", "72G145678", "43B11234"]:
        validate_normalized_plate(valid)


def test_validate_normalized_plate_invalid() -> None:
    with pytest.raises(ValidationError, match="không được để trống"):
        validate_normalized_plate("")

    with pytest.raises(ValidationError, match="quá ngắn"):
        validate_normalized_plate("51A")

    with pytest.raises(ValidationError, match="quá dài"):
        validate_normalized_plate("51A12345678901234")

    with pytest.raises(ValidationError, match="không hợp lệ"):
        validate_normalized_plate("51F@123")


def test_format_display_plate() -> None:
    assert format_display_plate("51f-123.45") == "51F12345"
