"""CLI serializers — re-export shim over stays.serialize.

Every public and private name the pre-refactor module exposed is
preserved here so existing tests and CLI code keep importing from
this path without changes.
"""

from __future__ import annotations

from stays.serialize import (  # noqa: F401
    _DATA_SOURCE,
    _amenities_as_names,
    _serialize_cancellation,
    _serialize_rate_plan,
    _serialize_room,
    build_error,
    build_success,
    serialize_hotel_detail,
    serialize_hotel_result,
)
