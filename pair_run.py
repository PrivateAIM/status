import os
import time
import uuid
import json
import tarfile
import tempfile
from contextlib import contextmanager

from config import (
    BUCKET_POLL_INTERVAL_SECONDS,
    CONNECTION_SCRIPT_NAME,
    LATENCY_LIMIT_SECONDS,
    PAIR_STEP_KEYS,
    POLL_INTERVAL_SECONDS,
    TIMEOUT_BUCKET_SECONDS,
    TIMEOUT_LONG_SECONDS,
    TIMEOUT_MEDIUM_SECONDS,
    TIMEOUT_RESULTS_SECONDS,
    UPLOAD_SETTLE_SECONDS,
)
from hub_client import fetch_analysis, make_clients


@contextmanager
def _timed_step(record: dict, step: str):
    # Record the wall-clock duration of a step regardless of outcome, and mark
    # the step success on a clean exit or failed when an error propagates. The
    # error is re-raised so run_pair can abort the remaining steps.
    t_start = time.time()
    try:
        yield
        record["step_status"][step] = "success"
    except BaseException:
        record["step_status"][step] = "failed"
        raise
    finally:
        record["step_duration"][step] = time.time() - t_start


def _upload(core_client, storage_client, project_id, master_image_id, compute_node):
    # Create the analysis, wait for its CODE bucket, upload the connection test
    # script, and mark it the entrypoint. Returns the created analysis.
    analysis_name = f"HealthCheck-{compute_node.name}-{uuid.uuid4().hex[:8]}"
    analysis = core_client.create_analysis(
        name=analysis_name, project_id=project_id, master_image_id=master_image_id
    )

    code_bucket_deadline = time.time() + TIMEOUT_BUCKET_SECONDS
    code_bucket = None
    while True:
        buckets = core_client.find_analysis_buckets(filter={"analysis_id": analysis.id})
        code_buckets = [b for b in buckets if b.type == "CODE"]
        if len(code_buckets) > 0:
            code_bucket = code_buckets[0]
            assert code_bucket.bucket_id is not None, "Bucket ID is missing on CODE bucket."
            break
        assert time.time() < code_bucket_deadline, "Timeout waiting for code bucket creation."
        time.sleep(BUCKET_POLL_INTERVAL_SECONDS)

    code_bucket_data = code_bucket.model_dump()
    code_bucket_core_id = str(code_bucket_data["id"])
    storage_bucket_id = str(code_bucket_data["bucket_id"])

    script_path = os.path.join("flame_checks", CONNECTION_SCRIPT_NAME)
    assert os.path.exists(script_path), f"Connection test script not found at: {script_path}"
    with open(script_path, "rb") as f:
        script_bytes = f.read()

    upload_response = storage_client.upload_to_bucket(
        storage_bucket_id, {"file_name": CONNECTION_SCRIPT_NAME, "content": script_bytes}
    )
    assert len(upload_response) > 0, "Upload response from storage was empty."

    time.sleep(UPLOAD_SETTLE_SECONDS)
    response = core_client._client.get(
        f"analysis-bucket-files?filter[analysis_bucket_id]={code_bucket_core_id}"
    )
    bucket_file_payload = response.json()["data"]
    file_ids = [
        entry["id"] for entry in bucket_file_payload if entry["path"] == CONNECTION_SCRIPT_NAME
    ]
    assert len(file_ids) == 1, f"Expected exactly one entrypoint file record for {CONNECTION_SCRIPT_NAME}."

    core_client.update_analysis_bucket_file(
        analysis_bucket_file_id=file_ids[0],
        is_entrypoint=True,
    )
    return analysis


def _distribute(core_client, analysis, aggregator, compute_node):
    # Trim the analysis to exactly this pair, lock its config, then drive the
    # build and distribution phases to completion.
    #
    # The hub seeds an analysis with all project nodes, so reduce it to exactly
    # this pair (aggregator + compute node) before locking config: remove any
    # unrelated node and add either of the pair if missing.
    required_node_ids = {str(aggregator.id), str(compute_node.id)}
    analysis_nodes = core_client.find_analysis_nodes(filter={"analysis_id": analysis.id})
    present_node_ids = {str(an.node_id) for an in analysis_nodes}
    for analysis_node in analysis_nodes:
        if str(analysis_node.node_id) not in required_node_ids:
            core_client.delete_analysis_node(analysis_node.id)
            print(
                f"[+] {compute_node.name}: removed unrelated node "
                f"{analysis_node.node_id} from analysis."
            )
    for node_id in required_node_ids:
        if node_id not in present_node_ids:
            core_client.create_analysis_node(analysis_id=analysis.id, node_id=node_id)

    core_client.send_analysis_command(analysis.id, "configurationLock")
    core_client.send_analysis_command(analysis.id, "buildStart")

    # Build and distribution are sequential phases, each allowed its own full
    # budget (mirrored by the 2 * TIMEOUT_MEDIUM_SECONDS term in the latency
    # limit). Sharing one window lets a slow build starve an otherwise healthy
    # distribution.
    build_deadline = time.time() + TIMEOUT_MEDIUM_SECONDS
    while True:
        analysis = fetch_analysis(core_client, analysis.id)
        assert analysis.build_status != "failed", "Analysis build failed."
        if analysis.build_status == "executed":
            break
        assert time.time() < build_deadline, "Timeout waiting for build phase."
        time.sleep(POLL_INTERVAL_SECONDS)

    core_client.send_analysis_command(analysis.id, "distributionStart")
    distribution_deadline = time.time() + TIMEOUT_MEDIUM_SECONDS
    while True:
        analysis = fetch_analysis(core_client, analysis.id)
        assert analysis.distribution_status != "failed", "Analysis distribution failed."
        if analysis.distribution_status == "executed":
            break
        assert time.time() < distribution_deadline, "Timeout waiting for distribution phase."
        time.sleep(POLL_INTERVAL_SECONDS)


def _execute(core_client, analysis):
    poll_start_time = time.time()
    while time.time() - poll_start_time < TIMEOUT_LONG_SECONDS:
        analysis = fetch_analysis(core_client, analysis.id)
        assert analysis.execution_status != "failed", "Analysis execution failed."

        if analysis.execution_status in ["executed", "finished"]:
            break

        time.sleep(POLL_INTERVAL_SECONDS)
    else:
        raise AssertionError("Timeout waiting for execution phase.")


def _fetch_results(core_client, storage_client, analysis, aggregator, compute_node):
    # Download the result tarball, parse its single payload, and verify that
    # both pair members reported back through the aggregator.
    buckets = core_client.find_analysis_buckets(filter={"analysis_id": analysis.id})
    result_buckets = [b for b in buckets if b.type == "RESULT"]
    assert len(result_buckets) > 0, f"No RESULT bucket found for analysis {analysis.id}."
    result_bucket = result_buckets[0]

    tmp = tempfile.NamedTemporaryFile(suffix=".tar", delete=False)
    result_tar_path = tmp.name
    tmp.close()
    try:
        # Bound the streaming download: a stalled transfer would otherwise hang
        # this worker forever, and with no per-step budget the whole health
        # check would never finish or report.
        download_deadline = time.time() + TIMEOUT_RESULTS_SECONDS
        with open(result_tar_path, "wb") as f:
            for chunk in storage_client.stream_bucket_tarball(result_bucket.bucket_id):
                f.write(chunk)
                assert time.time() < download_deadline, "Timeout streaming result tarball."

        with tarfile.open(result_tar_path, "r:*") as archive:
            file_members = [m for m in archive.getmembers() if m.isfile()]
            assert len(file_members) > 0, "No files inside the result archive tar."
            payload_file = archive.extractfile(file_members[0])
            assert payload_file is not None, "Failed to read result file from archive."
            payload = json.loads(payload_file.read().decode("utf-8"))

        assert isinstance(payload, dict), "Parsed payload is not a JSON object dictionary."
        assert payload["overall_success"] is True, "Result payload reports failure."

        # Both participants must have reported back through the aggregator.
        node_results = payload["node_results"]
        assert node_results[str(aggregator.id)] == "ok", "Aggregator did not report ok."
        assert (
            node_results[str(compute_node.id)] == "ok"
        ), f"Compute node {compute_node.name} did not report ok."
    finally:
        if os.path.exists(result_tar_path):
            os.remove(result_tar_path)


def _record_latency(record, run_start_time):
    # The verdict (up/down) is reachability, independent of the time budget; the
    # latency step only flags whether the run stayed within the limit.
    record["success"] = True
    elapsed_time = time.time() - run_start_time
    record["latency"] = elapsed_time
    record["step_duration"]["latency"] = elapsed_time
    record["step_status"]["latency"] = (
        "success" if elapsed_time <= LATENCY_LIMIT_SECONDS else "failed"
    )


def run_pair(aggregator, compute_node, project_id, master_image_id) -> dict:
    # Run a minimal federated analysis pairing the aggregator with a single
    # compute node. The outcome is that compute node's independent verdict.
    #
    # Availability is decided by the pair run itself: a truly down node makes its
    # run fail or time out and is marked down by the merge.
    record = {
        "compute_name": compute_node.name,
        "success": False,
        "latency": None,
        "step_status": {k: "unknown" for k in PAIR_STEP_KEYS},
        "step_duration": {k: None for k in PAIR_STEP_KEYS},
    }
    print(f"[*] {compute_node.name}: starting pair run.")

    core_client, storage_client = make_clients()
    run_start_time = time.time()
    try:
        with _timed_step(record, "upload"):
            analysis = _upload(
                core_client, storage_client, project_id, master_image_id, compute_node
            )
        with _timed_step(record, "distribute"):
            _distribute(core_client, analysis, aggregator, compute_node)
        with _timed_step(record, "execute"):
            _execute(core_client, analysis)
        with _timed_step(record, "results"):
            _fetch_results(core_client, storage_client, analysis, aggregator, compute_node)

        _record_latency(record, run_start_time)
        print(f"[+] {compute_node.name}: pair run complete ({record['latency']:.2f}s).")
    except BaseException as exc:
        failed_step = next(
            (s for s, v in record["step_status"].items() if v == "failed"), "upload"
        )
        print(f"[!] {compute_node.name}: pair run failed at '{failed_step}': {exc}")
    return record
