"""Run AiPayGen's background jobs (settlements, renewals, webhooks, trading sim).

Start exactly ONE of these per deployment, next to the web workers:

    python run_scheduler.py

Web workers never run jobs themselves, so a job can't run twice in parallel.
"""
import os
import signal
import threading

os.environ["AIPAYGEN_RUN_SCHEDULER"] = "1"

import app  # noqa: E402  (importing app registers and starts the jobs)


def main():
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    stop.wait()
    app.get_scheduler().shutdown(wait=True)


if __name__ == "__main__":
    main()
