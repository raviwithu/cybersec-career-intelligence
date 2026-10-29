import logging
import os
import time

from .config import get_settings
from .logging_config import configure_logging
from .job_search_pipeline import run_due_job_searches
from .phase6_pipeline import run_due_schedules
from .yahoo_mail_service import run_due_yahoo_mail

configure_logging()
logger = logging.getLogger("cybersec.research_scheduler")
HEARTBEAT_PATH = "/tmp/scheduler-heartbeat"


def _touch_heartbeat() -> None:
    with open(HEARTBEAT_PATH, "a"):
        pass
    os.utime(HEARTBEAT_PATH, None)


def main() -> None:
    settings = get_settings()
    if not settings.research_scheduler_enabled:
        logger.warning("research_scheduler_disabled")
        while True:
            _touch_heartbeat()
            time.sleep(settings.research_scheduler_poll_seconds)
    while True:
        _touch_heartbeat()
        try:
            processed = run_due_schedules(settings) + run_due_job_searches(settings) + run_due_yahoo_mail(settings)
            if processed:
                logger.info("scheduled_research_runs_completed count=%d", processed)
        except Exception:
            logger.exception("scheduled_research_poll_failed")
        time.sleep(settings.research_scheduler_poll_seconds)


if __name__ == "__main__":
    main()
