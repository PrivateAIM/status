import time
from contextlib import contextmanager


@contextmanager
def logged_operation(context: str, operation: str):
    """Identify the actual operation within a broad status-page step."""
    started = time.monotonic()
    print(f"[*] {context}: {operation}...", flush=True)
    try:
        yield
    except Exception as exc:
        raise RuntimeError(
            f"{context}: {operation} failed ({type(exc).__name__}): {exc}"
        ) from exc
    else:
        print(
            f"[+] {context}: {operation} completed ({time.monotonic() - started:.2f}s).",
            flush=True,
        )


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
