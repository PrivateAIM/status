import time
from datetime import datetime, timezone

import flame_hub

from config import (
    ANALYSIS_RETRY_ATTEMPTS,
    ANALYSIS_RETRY_DELAY_SECONDS,
    AUTH_URL,
    CORE_URL,
    PAGE_SIZE,
    PASSWORD,
    PROJECT_NAME,
    STALE_ANALYSIS_MAX_AGE_SECONDS,
    STORAGE_URL,
    USERNAME,
)


def find_all(find_method, **params):
    # Every hub listing is paginated (50 by default) and reports the real count
    # in meta.total. A plain call therefore returns a silently truncated first
    # page, so page until the reported total is accounted for.
    resources, meta = find_method(meta=True, page={"limit": PAGE_SIZE, "offset": 0}, **params)
    while len(resources) < meta.total:
        page, meta = find_method(
            meta=True, page={"limit": PAGE_SIZE, "offset": len(resources)}, **params
        )
        assert len(page) > 0, (
            f"Hub reports {meta.total} resources but stopped returning them at {len(resources)}."
        )
        resources.extend(page)
    return resources


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
    # Delete every analysis older than the max-age threshold, regardless of
    # phase. Runs are serialized by the workflow concurrency group, so anything
    # that old is a leftover from an earlier, finished run. Done once, before any
    # pair run creates its own analysis, so the current run is never touched.
    # Unbounded by nature: a run that dies after creating its analysis leaves one
    # behind, so a backlog must never hide behind the first page.
    existing_analyses = find_all(core_client.find_analyses, filter={"project_id": project.id})
    now = datetime.now(timezone.utc)
    for old_analysis in existing_analyses:
        age_seconds = (now - old_analysis.created_at).total_seconds()
        if age_seconds > STALE_ANALYSIS_MAX_AGE_SECONDS:
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
    projects = core_client.find_projects(filter={"name": PROJECT_NAME})
    matching_projects = [p for p in projects if p.name == PROJECT_NAME]
    if len(matching_projects) == 0:
        project = core_client.create_project(name=PROJECT_NAME)
        print(f"[!] Project '{PROJECT_NAME}' created.")
    else:
        project = matching_projects[0]
        cleanup_stale_analyses(core_client, project)

    # Filter server-side: the unfiltered listing is paginated (50 per page), so
    # a busy hub would hide existing members and make the loop below re-add them.
    existing_project_nodes = core_client.find_project_nodes(filter={"project_id": project.id})
    member_ids = [str(pn.node_id) for pn in existing_project_nodes]
    for node_id in target_node_ids:
        if node_id not in member_ids:
            core_client.create_project_node(project_id=project.id, node_id=node_id)
            print(f"[+] Added node {node_id} to project '{PROJECT_NAME}'.")
    return project
