import os
import time
import uuid
import json
import tarfile
import tempfile
from datetime import datetime, timezone
from functools import partial
from concurrent.futures import ThreadPoolExecutor
import flame_hub

# ---------------------------------------------------------
# Configuration & Endpoints
# ---------------------------------------------------------
AUTH_URL = "https://auth.staging.privateaim.net"
CORE_URL = "https://core.staging.privateaim.net"
STORAGE_URL = "https://storage.staging.privateaim.net"
USERNAME = os.environ["FLAME_USERNAME"]
PASSWORD = os.environ["FLAME_PASSWORD"]
# Unset GitHub secrets expand to empty strings rather than missing env vars.
assert USERNAME, "FLAME_USERNAME is empty - set the repository secret."
assert PASSWORD, "FLAME_PASSWORD is empty - set the repository secret."

TARGET_NODE_NAMES = ["aggregator-1", "default-1", "default-2"]
PROJECT_NAME = "health-check"
TIMEOUT_SHORT_SECONDS = 10.0  # Authentication
TIMEOUT_MEDIUM_SECONDS = 120.0  # Build and distribution
TIMEOUT_LONG_SECONDS = 240.0  # Execution
LATENCY_LIMIT_SECONDS = (
    2 * TIMEOUT_SHORT_SECONDS + 2 * TIMEOUT_MEDIUM_SECONDS + TIMEOUT_LONG_SECONDS
)  # Threshold for a single pair-run's E2E latency
# Only active analyses older than a full run budget are considered stale and
# deleted during cleanup. This protects the in-flight parallel jobs of a
# concurrently running (or overlapping) execution from being torn down.
STALE_ANALYSIS_MIN_AGE_SECONDS = LATENCY_LIMIT_SECONDS + 60.0

# Pipeline steps measured inside each per-node pair run. "login" is measured
# once in the shared phase and is not part of a pair run.
PAIR_STEP_KEYS = ["upload", "distribute", "execute", "results", "latency"]

# ---------------------------------------------------------
# Status & Duration Tracking
# ---------------------------------------------------------
# The step cards aggregate across the parallel per-node runs; the node_* cards
# carry each node's independent verdict. Everything starts "unknown" and is
# filled by the merge step in the main thread (workers never touch these).
statuses = {"login": "unknown"}
step_durations = {"login": 0.0}
for _step in PAIR_STEP_KEYS:
    statuses[_step] = "unknown"
    step_durations[_step] = None
for _node_name in TARGET_NODE_NAMES:
    statuses[f"node_{_node_name}"] = "unknown"
    step_durations[f"node_{_node_name}"] = None


def append_log(key: str, status: str, duration: float | None, date_str: str):
    log_dir = os.path.join("docs", "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, f"{key}_report.log")

    existing_lines = []
    if os.path.exists(log_path):
        with open(log_path, "r", encoding="utf-8") as f:
            existing_lines = f.readlines()

    # Keep last 1999 lines to maintain 2000 lines max including the new one
    existing_lines = existing_lines[-1999:]
    duration_str = f"{duration:.2f}" if duration is not None else ""
    existing_lines.append(f"{date_str}, {status}, {duration_str}\n")

    with open(log_path, "w", encoding="utf-8") as f:
        f.writelines(existing_lines)


def write_all_reports(final_statuses: dict[str, str], final_durations: dict[str, float]):
    date_str = time.strftime("%Y-%m-%d %H:%M", time.gmtime())
    for key in final_statuses.keys():
        duration = final_durations[key]
        append_log(key, final_statuses[key], duration, date_str)
        duration_str = f"{duration:.2f}s" if duration is not None else "n/a"
        print(f"Logged status for {key}: {final_statuses[key]} ({duration_str})")


def fetch_analysis(core_client, analysis_id):
    # The hub occasionally returns 404 (-> None) for an analysis that
    # demonstrably exists mid-poll (it was just created, built and distributed).
    # Absorb such a transient miss with a short retry; a genuinely missing
    # analysis still fails after the retry budget is exhausted.
    for _ in range(5):
        analysis = core_client.get_analysis(analysis_id)
        if analysis is not None:
            return analysis
        time.sleep(2.0)
    raise AssertionError(f"Analysis {analysis_id} not retrievable from hub.")


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


def make_clients():
    auth = flame_hub.auth.PasswordAuth(
        username=USERNAME, password=PASSWORD, base_url=AUTH_URL
    )
    core_client = flame_hub.CoreClient(base_url=CORE_URL, auth=auth)
    storage_client = flame_hub.StorageClient(base_url=STORAGE_URL, auth=auth)
    return core_client, storage_client


def prepare_project(core_client, target_node_ids: list[str]):
    # Resolve (or create) the project, kill stale analyses from previous runs,
    # ensure all target nodes are members, and pick a master image. Runs once,
    # before the parallel pair runs, so siblings are never deleted mid-run.
    projects = core_client.find_projects(name=PROJECT_NAME)
    matching_projects = [p for p in projects if p.name == PROJECT_NAME]
    if len(matching_projects) == 0:
        project = core_client.create_project(name=PROJECT_NAME)
        print(f"[!] Project '{PROJECT_NAME}' created.")
    else:
        project = matching_projects[0]
        existing_analyses = core_client.find_analyses(filter={"project_id": project.id})

        # Terminal states no longer occupy cluster resources.
        TERMINAL_STATUSES = {"finished", "failed"}
        now = datetime.now(timezone.utc)
        for old_analysis in existing_analyses:
            phases = [
                old_analysis.build_status,
                old_analysis.distribution_status,
                old_analysis.execution_status,
            ]
            is_active = any(p is not None and p not in TERMINAL_STATUSES for p in phases)
            # Spare young analyses: they may be the in-flight parallel jobs of an
            # overlapping run. Only genuinely stuck (old) ones are removed.
            age_seconds = (now - old_analysis.created_at).total_seconds()
            is_stale = age_seconds > STALE_ANALYSIS_MIN_AGE_SECONDS
            if is_active and is_stale:
                print(
                    f"[!] Deleting stale active analysis {old_analysis.id} "
                    f"(age={age_seconds:.0f}s, build={old_analysis.build_status}, "
                    f"dist={old_analysis.distribution_status}, "
                    f"exec={old_analysis.execution_status})"
                )
                core_client.delete_analysis(old_analysis.id)
        print("[+] Cleanup complete.")

    existing_project_nodes = core_client.get_project_nodes()
    existing_node_ids = [
        str(pn.node_id)
        for pn in existing_project_nodes
        if str(pn.project_id) == str(project.id)
    ]
    for node_id in target_node_ids:
        if node_id not in existing_node_ids:
            core_client.create_project_node(project_id=project.id, node_id=node_id)
            print(f"[+] Added node {node_id} to project.")

    images = core_client.get_master_images()
    assert len(images) > 0, "No master images found on hub."
    master_image_id = images[0].id
    return project, master_image_id


def run_pair(aggregator, compute_node, project_id, master_image_id) -> dict:
    # Run a minimal federated analysis pairing the aggregator with a single
    # compute node. The outcome is that compute node's independent verdict.
    record = {
        "compute_name": compute_node.name,
        "success": False,
        "latency": None,
        "step_status": {k: "unknown" for k in PAIR_STEP_KEYS},
        "step_duration": {k: None for k in PAIR_STEP_KEYS},
    }

    # The hub's node.online flag is unreliable on staging - it reports False even
    # for nodes that successfully run analyses - so it is informational only.
    # Actual availability is decided by the pair run itself: a truly down node
    # makes its run fail or time out and is marked down by the merge.
    print(
        f"[*] {compute_node.name}: starting pair run "
        f"(reported online: aggregator={aggregator.online}, "
        f"{compute_node.name}={compute_node.online})."
    )

    core_client, storage_client = make_clients()
    run_start_time = time.time()
    current_step = "upload"
    try:
        # ---- Upload: create analysis, provision code bucket, upload script ----
        t_start = time.time()
        try:
            node_ids = [str(aggregator.id), str(compute_node.id)]
            analysis_name = f"HealthCheck-{compute_node.name}-{uuid.uuid4().hex[:8]}"
            analysis = core_client.create_analysis(
                name=analysis_name, project_id=project_id, master_image_id=master_image_id
            )
            for node_id in node_ids:
                core_client.create_analysis_node(analysis_id=analysis.id, node_id=node_id)

            code_bucket_deadline = time.time() + 60.0
            code_bucket = None
            while True:
                buckets = core_client.find_analysis_buckets(filter={"analysis_id": analysis.id})
                code_buckets = [b for b in buckets if b.type == "CODE"]
                if len(code_buckets) > 0:
                    code_bucket = code_buckets[0]
                    assert code_bucket.bucket_id is not None, "Bucket ID is missing on CODE bucket."
                    break
                assert (
                    time.time() < code_bucket_deadline
                ), "Timeout waiting for code bucket creation."
                time.sleep(1.0)

            code_bucket_data = code_bucket.model_dump()
            code_bucket_core_id = str(code_bucket_data["id"])
            storage_bucket_id = str(
                code_bucket_data["external_id"] or code_bucket_data["bucket_id"]
            )

            script_name = "00_test_connection.py"
            script_path = os.path.join("flame_checks", script_name)
            assert os.path.exists(
                script_path
            ), f"Connection test script not found at: {script_path}"

            with open(script_path, "rb") as f:
                script_bytes = f.read()

            upload_response = storage_client.upload_to_bucket(
                storage_bucket_id, {"file_name": script_name, "content": script_bytes}
            )
            assert len(upload_response) > 0, "Upload response from storage was empty."

            time.sleep(2.0)
            response = core_client._client.get(
                f"analysis-bucket-files?filter[analysis_bucket_id]={code_bucket_core_id}"
            )
            bucket_file_payload = response.json()["data"]
            file_ids = [
                entry["id"] for entry in bucket_file_payload if entry["path"] == script_name
            ]
            assert (
                len(file_ids) == 1
            ), f"Expected exactly one entrypoint file record for {script_name}."

            core_client.update_analysis_bucket_file(
                analysis_bucket_file_id=file_ids[0],
                is_entrypoint=True,
            )
            record["step_status"]["upload"] = "success"
        finally:
            record["step_duration"]["upload"] = time.time() - t_start

        # ---- Distribute: config lock, build, distribution ----
        current_step = "distribute"
        t_start = time.time()
        try:
            core_client.send_analysis_command(analysis.id, "configurationLock")
            core_client.send_analysis_command(analysis.id, "buildStart")

            poll_start_time = time.time()
            distribution_started = False
            while time.time() - poll_start_time < TIMEOUT_MEDIUM_SECONDS:
                analysis = fetch_analysis(core_client, analysis.id)
                assert analysis.build_status != "failed", "Analysis build failed."
                assert analysis.distribution_status != "failed", "Analysis distribution failed."

                if analysis.build_status == "executed":
                    if not distribution_started and analysis.distribution_status is None:
                        core_client.send_analysis_command(analysis.id, "distributionStart")
                        distribution_started = True
                    elif analysis.distribution_status == "executed":
                        break

                time.sleep(3.0)
            else:
                raise AssertionError("Timeout waiting for build/distribution phase.")

            record["step_status"]["distribute"] = "success"
        finally:
            record["step_duration"]["distribute"] = time.time() - t_start

        # ---- Execute ----
        current_step = "execute"
        t_start = time.time()
        try:
            poll_start_time = time.time()
            while time.time() - poll_start_time < TIMEOUT_LONG_SECONDS:
                analysis = fetch_analysis(core_client, analysis.id)
                assert analysis.execution_status != "failed", "Analysis execution failed."

                if analysis.execution_status in ["executed", "finished"]:
                    break

                time.sleep(3.0)
            else:
                raise AssertionError("Timeout waiting for execution phase.")

            record["step_status"]["execute"] = "success"
        finally:
            record["step_duration"]["execute"] = time.time() - t_start

        # ---- Results: download, parse, verify both nodes reported ok ----
        current_step = "results"
        t_start = time.time()
        try:
            buckets = core_client.find_analysis_buckets(filter={"analysis_id": analysis.id})
            result_buckets = [b for b in buckets if b.type == "RESULT"]
            assert len(result_buckets) > 0, f"No RESULT bucket found for analysis {analysis.id}."
            result_bucket = result_buckets[0]

            with tempfile.NamedTemporaryFile(suffix=".tar", delete=False) as tmp:
                result_tar_path = tmp.name
                for chunk in storage_client.stream_bucket_tarball(result_bucket.bucket_id):
                    tmp.write(chunk)

            try:
                with tarfile.open(result_tar_path, "r:*") as archive:
                    file_members = [m for m in archive.getmembers() if m.isfile()]
                    assert len(file_members) > 0, "No files inside the result archive tar."
                    payload_file = archive.extractfile(file_members[0])
                    assert payload_file is not None, "Failed to read result file from archive."
                    payload = json.loads(payload_file.read().decode("utf-8"))

                assert isinstance(payload, dict), "Parsed payload is not a JSON object dictionary."
                assert (
                    payload["overall_success"] is True
                ), "Result payload reports failure."

                # Both participants must have reported back through the aggregator.
                node_results = payload["node_results"]
                assert (
                    node_results[str(aggregator.id)] == "ok"
                ), "Aggregator did not report ok."
                assert (
                    node_results[str(compute_node.id)] == "ok"
                ), f"Compute node {compute_node.name} did not report ok."
            finally:
                if os.path.exists(result_tar_path):
                    os.remove(result_tar_path)

            record["step_status"]["results"] = "success"
        finally:
            record["step_duration"]["results"] = time.time() - t_start

        # ---- Latency: the node is reachable; record its E2E run time ----
        # The verdict (up/down) is reachability, independent of the time budget;
        # the latency step only flags whether the run stayed within the limit.
        record["success"] = True
        elapsed_time = time.time() - run_start_time
        record["latency"] = elapsed_time
        record["step_duration"]["latency"] = elapsed_time
        record["step_status"]["latency"] = (
            "success" if elapsed_time <= LATENCY_LIMIT_SECONDS else "failed"
        )
        print(f"[+] {compute_node.name}: pair run complete ({elapsed_time:.2f}s).")
    except BaseException as exc:
        record["step_status"][current_step] = "failed"
        print(f"[!] {compute_node.name}: pair run failed at '{current_step}': {exc}")
    return record


def merge_records(records: list[dict], aggregator):
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

    # Step cards aggregate across the runs: status merged, duration averaged.
    for step in PAIR_STEP_KEYS:
        statuses[step] = merge_step_status([record["step_status"][step] for record in records])
        step_durations[step] = average([record["step_duration"][step] for record in records])


def main():
    try:
        # ---------------------------------------------------------
        # Shared Step 1: Login (Authentication), once for all nodes
        # ---------------------------------------------------------
        print("[*] Step 1: Authenticating with FLAME Hub...")
        t_start = time.time()
        try:
            core_client, _ = make_clients()
            nodes = core_client.get_nodes()
            assert len(nodes) > 0, "No nodes returned from core client."
            login_elapsed = time.time() - t_start
            assert (
                login_elapsed <= TIMEOUT_SHORT_SECONDS
            ), f"Authentication took {login_elapsed:.2f}s, exceeding {TIMEOUT_SHORT_SECONDS}s limit."
            statuses["login"] = "success"
            print("[+] Login successful.")
        except BaseException:
            statuses["login"] = "failed"
            raise
        finally:
            step_durations["login"] = time.time() - t_start

        # ---------------------------------------------------------
        # Resolve target nodes and split aggregator / compute
        # ---------------------------------------------------------
        selected_nodes = [node for node in nodes if node.name in TARGET_NODE_NAMES]
        assert len(selected_nodes) > 0, f"Target nodes {TARGET_NODE_NAMES} not found."
        aggregators = [node for node in selected_nodes if node.type == "aggregator"]
        compute_nodes = [node for node in selected_nodes if node.type == "default"]
        assert (
            len(aggregators) == 1
        ), f"Expected exactly one aggregator node, found {len(aggregators)}."
        assert len(compute_nodes) >= 1, "Expected at least one default (compute) node."
        aggregator = aggregators[0]
        print(
            f"[*] Aggregator: {aggregator.name} (online={aggregator.online}); "
            f"compute nodes: "
            + ", ".join(f"{n.name} (online={n.online})" for n in compute_nodes)
        )

        # ---------------------------------------------------------
        # Shared project preparation (cleanup, membership, image)
        # ---------------------------------------------------------
        print("[*] Step 2: Preparing project and clearing stale analyses...")
        project, master_image_id = prepare_project(
            core_client, [str(node.id) for node in selected_nodes]
        )

        # ---------------------------------------------------------
        # Parallel per-node pair runs
        # ---------------------------------------------------------
        print(f"[*] Step 3: Running {len(compute_nodes)} node check(s) in parallel...")
        worker = partial(
            run_pair,
            aggregator,
            project_id=project.id,
            master_image_id=master_image_id,
        )
        with ThreadPoolExecutor(max_workers=len(compute_nodes)) as executor:
            records = list(executor.map(worker, compute_nodes))

        # ---------------------------------------------------------
        # Merge per-node runs into step cards + node cards
        # ---------------------------------------------------------
        merge_records(records, aggregator)

    finally:
        print("[*] Writing health status reports...")
        write_all_reports(statuses, step_durations)
        print("[*] Finished health checks execution.")


if __name__ == "__main__":
    main()
