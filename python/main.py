import logging
import os
import time

from dotenv import load_dotenv
from predict import predict
from base import check_are_unprocessed

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("job-runner")

INTERVAL_SECONDS = int(os.getenv("JOB_INTERVAL_SECONDS", "60"))


def run_job() -> None:
    if check_are_unprocessed():
        logger.info("Running job")
        predict()


def main() -> None:
    logger.info("Job runner started (interval=%ds)", INTERVAL_SECONDS)
    while True:
        try:
            run_job()
        except Exception:
            logger.exception("Job failed")
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
