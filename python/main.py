import hashlib
import logging
import os
import time

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("job-runner")

INTERVAL_SECONDS = int(os.getenv("JOB_INTERVAL_SECONDS", "60"))


def _log_model_integrity() -> None:
    """Log size + SHA256 of MODEL_PATH so we can verify integrity against the
    local copy after an upload. Runs ONCE at startup, before importing predict
    (which would crash hard on a corrupt pickle)."""
    path = os.environ.get('MODEL_PATH',
                           os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        'model', 'model.pkl'))
    if not os.path.exists(path):
        logger.error("MODEL integrity check: %s does not exist", path)
        return
    size = os.path.getsize(path)
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    logger.info("MODEL %s  size=%d  sha256=%s", path, size, h.hexdigest())


def main() -> None:
    _log_model_integrity()

    # Imports deferred until after the integrity log so even a crashing
    # load_learner leaves the hash + size visible in the logs.
    from predict import predict
    from base import check_are_unprocessed

    def run_job() -> None:
        # if check_are_unprocessed():
        logger.info("Running job")
        predict()

    logger.info("Job runner started (interval=%ds)", INTERVAL_SECONDS)
    while True:
        try:
            run_job()
        except Exception:
            logger.exception("Job failed")
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
