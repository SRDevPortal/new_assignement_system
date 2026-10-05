"""Customer-number privacy at assignment response and storage boundaries."""
from __future__ import annotations

from copy import deepcopy
from functools import wraps
import re

import frappe


PHONE_KEYS = frozenset({
    "customer_number",
    "customer_phone",
    "mobile",
    "mobile_no",
    "mobile_norm",
    "sr_mobile_norm",
    "phone",
    "phone_number",
})
TEXT_KEYS = frozenset({
    "error",
    "message",
    "reason",
    "warning",
})
PHONE_TEXT = re.compile(r"(?<![0-9*])\+?[0-9](?:[0-9 ()+.-]*[0-9])?(?![0-9*])")
DATE_LIKE = re.compile(r"^(?:[0-9]{4}[-./][0-9]{1,2}[-./][0-9]{1,2}|[0-9]{1,2}[-./][0-9]{1,2}[-./][0-9]{4})$")


def enabled() -> bool:
    return bool(frappe.conf.get("privacy_shield_desk_enabled", False)) and (
        "privacy_shield" in frappe.get_installed_apps()
    )


def restricted(user=None) -> bool:
    if not enabled():
        return False
    from privacy_shield.policy import current_capabilities

    return not current_capabilities(user).view_full


def mask_text(value):
    """Mask phone-like text when privacy is enabled, including background jobs."""
    if not enabled() or not isinstance(value, str):
        return value

    from privacy_shield.masking import mask_number

    def replace(match):
        token = match.group(0)
        if DATE_LIKE.fullmatch(token.strip()):
            return token
        digits = "".join(char for char in token if char.isdigit())
        return mask_number(digits) if 7 <= len(digits) <= 15 else token

    return PHONE_TEXT.sub(replace, value)


def sanitize_for_storage(value):
    if isinstance(value, dict):
        return {key: sanitize_for_storage(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_for_storage(item) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_for_storage(item) for item in value)
    return mask_text(value)


def project_response(payload):
    """Copy and mask browser-visible responses for restricted users."""
    if not restricted():
        return payload

    from privacy_shield.display_text import mask_display
    from privacy_shield.masking import mask_number

    def clean(value, context=None):
        if isinstance(value, list):
            return [clean(item, context) for item in value]
        if isinstance(value, tuple):
            return tuple(clean(item, context) for item in value)
        if not isinstance(value, dict):
            if context in TEXT_KEYS and isinstance(value, str):
                return mask_display(value)
            return deepcopy(value)

        result = {}
        for key, item in value.items():
            if key in PHONE_KEYS:
                result[key] = mask_number(item)
            elif key in TEXT_KEYS:
                result[key] = clean(item, key)
            else:
                result[key] = clean(item, key)
        return result

    return clean(payload)


def browser_response(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        return project_response(fn(*args, **kwargs))

    return wrapped
