from app.utils.validators import normalize_phone_number


def test_bare_10_digit_indian_number_gets_plus_91():
    assert normalize_phone_number("7600181441") == "+917600181441"


def test_91_prefixed_without_plus_gets_a_plus():
    assert normalize_phone_number("917600181441") == "+917600181441"


def test_already_e164_is_left_unchanged():
    assert normalize_phone_number("+917600181441") == "+917600181441"


def test_spaces_dashes_and_parens_are_stripped_before_normalizing():
    assert normalize_phone_number("76001 81441") == "+917600181441"
    assert normalize_phone_number("7600-181-441") == "+917600181441"
    assert normalize_phone_number("(760) 018 1441") == "+917600181441"


def test_a_real_foreign_number_is_never_forced_into_plus_91():
    # A US number already carries its own country code — must not be reinterpreted as Indian.
    assert normalize_phone_number("+15551234567") == "+15551234567"


def test_unrecognized_shape_is_left_alone_rather_than_guessed():
    # Not 10 digits, not already E.164 — too ambiguous to guess a country code for.
    assert normalize_phone_number("12345") == "12345"


def test_empty_string_is_returned_as_is():
    assert normalize_phone_number("") == ""
