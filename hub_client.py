import time
from datetime import datetime, timezone

import flame_hub

from config import (
    ANALYSIS_RETRY_ATTEMPTS,
    ANALYSIS_RETRY_DELAY_SECONDS,
    AUTH_URL,
    CORE_URL,
    PASSWORD,
    PROJECT_NAME,
    STALE_ANALYSIS_MIN_AGE_SECONDS,
    STORAGE_URL,
    USERNAME,
)


def make_clients():
    auth = flame_hub.auth.PasswordAuth(username=USERNAME, password=PASSWORD, base_url=AUTH_URL)
    core_client = flame_hub.CoreClient(base_url=CORE_URL, auth=auth)
    storage_client = flame_hub.StorageClient(base_url=STORAGE_URL, auth=auth)
    return core_client, storage_client


def get_master_image_id(core_client):
    images = core_client.get_master_images()
    assert len(images) > 0, "No master images found on hub."
    return images[0].id


def fetch_analysis(core_client, analysis_id):
    # The hub occasionally returns 404 (-> None) for an analysis that
    # demonstrably exists mid-poll (it was just created, built and distributed).
    # Absorb such a transient miss with a short retry; a genuinely missing
    # analysis still fails after the retry budget is exhausted.
    for _ in range(ANALYSIS_RETRY_ATTEMPTS):
        analysis = core_client.get_analysis(analysis_id)
        if analysis is not None:
            return analysis
        time.sleep(ANALYSIS_RETRY_DELAY_SECONDS)
    raise AssertionError(f"Analysis {analysis_id} not retrievable from hub.")


def cleanup_stale_analyses(core_client, project):
    # Clear out leftovers from earlier runs so each run starts clean: delete
    # every analysis old enough that it cannot belong to an in-flight run -
    # both previous (finished/failed) analyses and genuinely stuck active ones.
    # Young analyses may be the in-flight job of an overlapping run, so they are
    # spared regardless of phase.
    existing_analyses = core_client.find_analyses(filter={"project_id": project.id})

    now = datetime.now(timezone.utc)
    for old_analysis in existing_analyses:
        age_seconds = (now - old_analysis.created_at).total_seconds()
        is_stale = age_seconds > STALE_ANALYSIS_MIN_AGE_SECONDS
        if is_stale:
            print(
                f"[!] Deleting stale analysis {old_analysis.id} "
                f"(age={age_seconds:.0f}s, build={old_analysis.build_status}, "
                f"dist={old_analysis.distribution_status}, "
                f"exec={old_analysis.execution_status})"
            )
            core_client.delete_analysis(old_analysis.id)


def prepare_project(core_client, target_node_ids: list[str]):
    # Resolve (or create) the single shared health-check project, clear stale
    # analyses, and ensure all target nodes are members. Each per-node analysis
    # is later trimmed down to just its pair (see run_pair). Runs once, before
    # the parallel pair runs, so siblings are never deleted mid-run.
    projects = core_client.find_projects(name=PROJECT_NAME)
    matching_projects = [p for p in projects if p.name == PROJECT_NAME]
    if len(matching_projects) == 0:
        project = core_client.create_project(name=PROJECT_NAME)
        print(f"[!] Project '{PROJECT_NAME}' created.")
    else:
        project = matching_projects[0]
        cleanup_stale_analyses(core_client, project)

    existing_project_nodes = core_client.get_project_nodes()
    member_ids = [
        str(pn.node_id) for pn in existing_project_nodes if str(pn.project_id) == str(project.id)
    ]
    for node_id in target_node_ids:
        if node_id not in member_ids:
            core_client.create_project_node(project_id=project.id, node_id=node_id)
            print(f"[+] Added node {node_id} to project '{PROJECT_NAME}'.")
    return project
