import re

E164_PATTERN = re.compile(r"^\+[1-9]\d{6,14}$")


def is_valid_e164(phone_number: str) -> bool:
    return bool(E164_PATTERN.match(phone_number))
