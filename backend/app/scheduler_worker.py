import logging
import time

from .config import get_settings
from .logging_config import configure_logging
from .phase6_pipeline import run_due_schedules

configure_logging()
logger = logging.getLogger("cybersec.research_scheduler")


def main() -> None:
    settings = get_settings()
    if not settings.research_scheduler_enabled:
        logger.warning("research_scheduler_disabled")
        return
    while True:
        try:
            processed = run_due_schedules(settings)
            if processed:
                logger.info("scheduled_research_runs_completed count=%d", processed)
        except Exception:
            logger.exception("scheduled_research_poll_failed")
        time.sleep(settings.research_scheduler_poll_seconds)


if __name__ == "__main__":
    main()
