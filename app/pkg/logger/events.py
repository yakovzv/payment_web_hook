"""Структурированные (JSON) события по оплате и выдаче с корреляцией по
order_id / event_id / request_id / supplier."""

import json
import logging
from datetime import datetime, timezone

_logger = logging.getLogger("events")
_logger.setLevel(logging.INFO)
if not _logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(_handler)
    _logger.propagate = False

__all__ = ["log_event"]


def log_event(event: str, **fields) -> None:
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
    }
    for key, value in fields.items():
        if value is not None:
            record[key] = value
    _logger.info(json.dumps(record, ensure_ascii=False))