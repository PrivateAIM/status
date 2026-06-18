from config import PAIR_STEP_KEYS, TARGET_NODE_NAMES


def init_tracking() -> tuple[dict[str, str], dict[str, float | None]]:
    # The step cards aggregate across the parallel per-node runs; the node_*
    # cards carry each node's independent verdict. Everything starts "unknown"
    # and is filled by the merge step in the main thread (workers never touch
    # these). "login" is measured once in the shared phase.
    statuses = {"login": "unknown"}
    step_durations = {"login": 0.0}
    for step in PAIR_STEP_KEYS:
        statuses[step] = "unknown"
        step_durations[step] = None
    for node_name in TARGET_NODE_NAMES:
        statuses[f"node_{node_name}"] = "unknown"
        step_durations[f"node_{node_name}"] = None
    return statuses, step_durations


def merge_step_status(values: list[str]) -> str:
    # A step is success only if every attempted run passed it; failed if any
    # attempted run failed; unknown if no run reached it. The log format carries
    # only success/failed/unknown - the "partial" colour emerges on the frontend
    # from the uptime ratio over the lookback window.
    attempted = [v for v in values if v != "unknown"]
    if len(attempted) == 0:
        return "unknown"
    return "success" if all(v == "success" for v in attempted) else "failed"


def average(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return sum(present) / len(present) if present else None


def merge_records(records: list[dict], aggregator, statuses: dict, step_durations: dict):
    # Per-node verdicts: each compute node from its own run; the aggregator is
    # up if it completed any pair (it takes part in all of them).
    for record in records:
        name = record["compute_name"]
        statuses[f"node_{name}"] = "success" if record["success"] else "failed"
        step_durations[f"node_{name}"] = record["latency"] if record["success"] else None

    any_success = any(record["success"] for record in records)
    statuses[f"node_{aggregator.name}"] = "success" if any_success else "failed"
    aggregator_latencies = [
        record["latency"]
        for record in records
        if record["success"] and record["latency"] is not None
    ]
    step_durations[f"node_{aggregator.name}"] = average(aggregator_latencies)

    # Step cards aggregate across the runs: status merged across every run, but
    # duration averaged over only the nodes that actually completed the step - a
    # broken node's partial (timed-out) duration is not a meaningful timing.
    # E2E latency is exempt: it is recorded only for reachable nodes already, so
    # averaging its present values keeps slow-but-up nodes in the number.
    for step in PAIR_STEP_KEYS:
        statuses[step] = merge_step_status([record["step_status"][step] for record in records])
        if step == "latency":
            step_durations[step] = average([record["step_duration"][step] for record in records])
        else:
            step_durations[step] = average(
                [
                    record["step_duration"][step]
                    for record in records
                    if record["step_status"][step] == "success"
                ]
            )
