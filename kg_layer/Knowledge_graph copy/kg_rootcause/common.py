from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_EVEN
import hashlib
import json


def timestamp(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Timestamp must have a timezone")
    return result.astimezone(timezone.utc)


def cents(value):
    return int((Decimal(str(value)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_EVEN))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
