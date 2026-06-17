import os
import time
import uuid
import json
import tarfile
import tempfile
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
)  # Threshold for overall E2E latency

# ---------------------------------------------------------
# Status & Duration Tracking
# ---------------------------------------------------------
# Steps start as "unknown"; the step that raises is marked "failed",
# later steps stay "unknown".
statuses = {
    "login": "unknown",
    "upload": "unknown",
    "distribute": "unknown",
    "execute": "unknown",
    "results": "unknown",
    "latency": "unknown",
}

step_durations = {
    "login": 0.0,
    "upload": 0.0,
    "distribute": 0.0,
    "execute": 0.0,
    "results": 0.0,
    "latency": 0.0,
}


def append_log(key: str, status: str, duration: float, date_str: str):
    log_dir = os.path.join("docs", "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, f"{key}_report.log")

    existing_lines = []
    if os.path.exists(log_path):
        with open(log_path, "r", encoding="utf-8") as f:
            existing_lines = f.readlines()

    # Keep last 1999 lines to maintain 2000 lines max including the new one
    existing_lines = existing_lines[-1999:]
    existing_lines.append(f"{date_str}, {status}, {duration:.2f}\n")

    with open(log_path, "w", encoding="utf-8") as f:
        f.writelines(existing_lines)


def write_all_reports(final_statuses: dict[str, str], final_durations: dict[str, float]):
    date_str = time.strftime("%Y-%m-%d %H:%M", time.gmtime())
    for key in final_statuses.keys():
        append_log(key, final_statuses[key], final_durations[key], date_str)
        print(f"Logged status for {key}: {final_statuses[key]} ({final_durations[key]:.2f}s)")


def main():
    run_start_time = time.time()
    current_step = "login"
    try:
        # ---------------------------------------------------------
        # Step 1: Login (Authentication)
        # ---------------------------------------------------------
        print("[*] Step 1: Authenticating with FLAME Hub...")
        t_start = time.time()
        try:
            auth = flame_hub.auth.PasswordAuth(
                username=USERNAME, password=PASSWORD, base_url=AUTH_URL
            )
            core_client = flame_hub.CoreClient(base_url=CORE_URL, auth=auth)
            storage_client = flame_hub.StorageClient(base_url=STORAGE_URL, auth=auth)

            # Test basic client functionality to confirm login
            nodes = core_client.get_nodes()
            assert len(nodes) > 0, "No nodes returned from core client."
            login_elapsed = time.time() - t_start
            assert (
                login_elapsed <= TIMEOUT_SHORT_SECONDS
            ), f"Authentication took {login_elapsed:.2f}s, exceeding {TIMEOUT_SHORT_SECONDS}s limit."
            statuses["login"] = "success"
            print("[+] Login successful.")
        finally:
            step_durations["login"] = time.time() - t_start

        # ---------------------------------------------------------
        # Step 1.5: Cleanup (Kill stale analyses from previous runs)
        # ---------------------------------------------------------
        print("[*] Step 1.5: Cleaning up previous analyses...")
        projects = core_client.find_projects(name=PROJECT_NAME)
        matching_projects = [p for p in projects if p.name == PROJECT_NAME]
        if len(matching_projects) == 0:
            project = core_client.create_project(name=PROJECT_NAME)
            print(f"[!] Project '{PROJECT_NAME}' created.")
        else:
            project = matching_projects[0]
            existing_analyses = core_client.find_analyses(filter={"project_id": project.id})

            # Terminal states: once an analysis reaches these, it is no longer
            # occupying cluster resources and can be left for log inspection.
            TERMINAL_STATUSES = {"finished", "failed"}

            for old_analysis in existing_analyses:
                # An analysis is considered active if any of its pipeline
                # phases is in a non-terminal, non-None state.
                phases = [
                    old_analysis.build_status,
                    old_analysis.distribution_status,
                    old_analysis.execution_status,
                ]
                is_active = any(p is not None and p not in TERMINAL_STATUSES for p in phases)

                if is_active:
                    print(
                        f"[!] Deleting active analysis {old_analysis.id} "
                        f"(build={old_analysis.build_status}, "
                        f"dist={old_analysis.distribution_status}, "
                        f"exec={old_analysis.execution_status})"
                    )
                    core_client.delete_analysis(old_analysis.id)

            print("[+] Cleanup complete.")

        # ---------------------------------------------------------
        # Step 2: Upload (Project and Script Setup)
        # ---------------------------------------------------------
        print("[*] Step 2: Resolving Project & Nodes...")
        current_step = "upload"
        t_start = time.time()
        try:
            selected_nodes = [node for node in nodes if node.name in TARGET_NODE_NAMES]
            assert len(selected_nodes) > 0, f"Target nodes {TARGET_NODE_NAMES} not found."

            node_ids = [str(node.id) for node in selected_nodes]
            existing_project_nodes = core_client.get_project_nodes()
            existing_node_ids = [
                str(pn.node_id)
                for pn in existing_project_nodes
                if str(pn.project_id) == str(project.id)
            ]
            for node_id in node_ids:
                if str(node_id) not in existing_node_ids:
                    core_client.create_project_node(project_id=project.id, node_id=node_id)
                    print(f"[+] Added node {node_id} to project.")

            print("[*] Creating analysis and uploading script...")
            analysis_name = f"HealthCheck-{uuid.uuid4().hex[:8]}"
            images = core_client.get_master_images()
            assert len(images) > 0, "No master images found on hub."
            master_image_id = images[0].id

            analysis = core_client.create_analysis(
                name=analysis_name, project_id=project.id, master_image_id=master_image_id
            )
            for node_id in node_ids:
                core_client.create_analysis_node(analysis_id=analysis.id, node_id=node_id)

            # Wait for CODE bucket creation
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
                code_bucket_data.get("external_id") or code_bucket_data["bucket_id"]
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
            statuses["upload"] = "success"
            print("[+] Upload successful.")
        finally:
            step_durations["upload"] = time.time() - t_start

        # ---------------------------------------------------------
        # Step 3: Distribute (Config Lock and Distribution)
        # ---------------------------------------------------------
        print("[*] Step 3: Starting build and distribution...")
        current_step = "distribute"
        t_start = time.time()
        try:
            core_client.send_analysis_command(analysis.id, "configurationLock")
            core_client.send_analysis_command(analysis.id, "buildStart")

            poll_start_time = time.time()
            distribution_started = False

            while time.time() - poll_start_time < TIMEOUT_MEDIUM_SECONDS:
                analysis = core_client.get_analysis(analysis.id)
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

            statuses["distribute"] = "success"
            print("[+] Distribution successful.")
        finally:
            step_durations["distribute"] = time.time() - t_start

        # ---------------------------------------------------------
        # Step 4: Execute (Analysis execution)
        # ---------------------------------------------------------
        print("[*] Step 4: Waiting for execution...")
        current_step = "execute"
        t_start = time.time()
        try:
            poll_start_time = time.time()
            while time.time() - poll_start_time < TIMEOUT_LONG_SECONDS:
                analysis = core_client.get_analysis(analysis.id)
                assert analysis.execution_status != "failed", "Analysis execution failed."

                if analysis.execution_status in ["executed", "finished"]:
                    break

                time.sleep(3.0)
            else:
                raise AssertionError("Timeout waiting for execution phase.")

            statuses["execute"] = "success"
            print("[+] Execution successful.")
        finally:
            step_durations["execute"] = time.time() - t_start

        # ---------------------------------------------------------
        # Step 5: Results (Download and Verify results payload)
        # ---------------------------------------------------------
        print("[*] Step 5: Retrieving results payload...")
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
                    json_candidate = file_members[0]
                    payload_file = archive.extractfile(json_candidate)
                    assert payload_file is not None, "Failed to read result file from archive."
                    payload = json.loads(payload_file.read().decode("utf-8"))

                assert isinstance(payload, dict), "Parsed payload is not a JSON object dictionary."
                assert (
                    payload.get("overall_success") is True
                ), "Result payload reports failure or is missing success."
            finally:
                if os.path.exists(result_tar_path):
                    os.remove(result_tar_path)

            statuses["results"] = "success"
            print("[+] Results download and validation successful.")
        finally:
            step_durations["results"] = time.time() - t_start

        # ---------------------------------------------------------
        # Step 6: Latency check
        # ---------------------------------------------------------
        current_step = "latency"
        elapsed_time = time.time() - run_start_time
        print(f"[*] Step 6: Checking total E2E latency ({elapsed_time:.2f}s)...")
        assert (
            elapsed_time <= LATENCY_LIMIT_SECONDS
        ), f"Total execution time ({elapsed_time:.2f}s) exceeded limit of {LATENCY_LIMIT_SECONDS}s."
        statuses["latency"] = "success"
        print("[+] Latency threshold check passed.")

    except BaseException:
        statuses[current_step] = "failed"
        raise
    finally:
        # Calculate final latency (total E2E run duration)
        step_durations["latency"] = time.time() - run_start_time

        # Write reports to logs under logs/ directory.
        print("[*] Writing health status reports...")
        write_all_reports(statuses, step_durations)
        print("[*] Finished health checks execution.")


if __name__ == "__main__":
    main()
