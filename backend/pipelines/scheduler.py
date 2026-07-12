"""Interval scheduler for workflows with {"type": "interval", "minutes": N}
triggers.

Started as a daemon thread from PipelinesConfig.ready() (guarded against the
runserver autoreloader's double start). Every TICK_SECONDS it scans workflows:
any with an interval trigger, no pending/running run, and no run within the
last `minutes` gets a fresh start_run(). A tick never raises.
"""

import logging
import threading
import time
from datetime import timedelta

TICK_SECONDS = 30

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_started = False


def start():
    """Start the scheduler thread (idempotent)."""
    global _started
    with _lock:
        if _started:
            return
        _started = True
    thread = threading.Thread(target=_loop, name="sift-scheduler", daemon=True)
    thread.start()
    logger.info("scheduler: started (tick every %ss)", TICK_SECONDS)


def _loop():
    from django.db import close_old_connections

    while True:
        time.sleep(TICK_SECONDS)
        try:
            close_old_connections()
            _tick()
        except Exception:  # noqa: BLE001 — the scheduler must never die
            logger.exception("scheduler: tick failed")
        finally:
            try:
                close_old_connections()
            except Exception:
                pass


def _interval_minutes(workflow):
    trigger = (workflow.dsl or {}).get("trigger") if isinstance(workflow.dsl, dict) else None
    if not isinstance(trigger, dict) or trigger.get("type") != "interval":
        return None
    minutes = trigger.get("minutes")
    if not isinstance(minutes, int) or isinstance(minutes, bool) or minutes < 1:
        return None
    return minutes


def _tick():
    from django.utils import timezone

    from crm.models import Workflow

    from .engine import start_run

    now = timezone.now()
    for workflow in Workflow.objects.all():
        minutes = _interval_minutes(workflow)
        if minutes is None:
            continue
        if workflow.runs.filter(status__in=("pending", "running")).exists():
            continue  # one at a time
        last = workflow.runs.order_by("-id").first()
        if last is not None:
            reference = last.finished_at or last.started_at
            if reference is not None and reference > now - timedelta(minutes=minutes):
                continue  # ran recently enough
        logger.info(
            "scheduler: interval trigger firing for workflow %s (%r, every %sm)",
            workflow.pk, workflow.name, minutes,
        )
        start_run(workflow)
