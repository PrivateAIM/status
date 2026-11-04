import time
from contextlib import contextmanager


@contextmanager
def timed_step(record: dict, step: str):
    # Keep all work up to the next step inside this scope, including setup.
    t_start = time.time()
    try:
        yield
        record["step_status"][step] = "success"
    except BaseException:
        record["step_status"][step] = "failed"
        raise
    finally:
        record["step_duration"][step] = time.time() - t_start
