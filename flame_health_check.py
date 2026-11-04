import time
from functools import partial
from concurrent.futures import ThreadPoolExecutor

from config import TARGET_NODE_NAMES, TIMEOUT_SHORT_SECONDS
from hub_client import find_all, get_master_image_id, make_clients, prepare_project
from pair_run import run_pair
from aggregate import init_tracking, merge_records
from reporting import write_all_reports
from step_tracking import timed_step


def authenticate():
    # Shared step, once for all nodes: authenticate and resolve the node list.
    print("[*] Step 1: Authenticating with FLAME Hub...")
    t_start = time.time()
    core_client, _ = make_clients()
    # The target nodes are matched by name below, and the hub has no "in"
    # filter operator to do that server-side, so every node has to be seen -
    # a first-page-only listing would silently lose a target on a cluster
    # that outgrows one page.
    nodes = find_all(core_client.find_nodes)
    assert len(nodes) > 0, "No nodes returned from core client."
    login_elapsed = time.time() - t_start
    assert (
        login_elapsed <= TIMEOUT_SHORT_SECONDS
    ), f"Authentication took {login_elapsed:.2f}s, exceeding {TIMEOUT_SHORT_SECONDS}s limit."
    return core_client, nodes


def split_nodes(nodes):
    # Resolve target nodes and split into the single aggregator and its compute
    # nodes.
    selected_nodes = [node for node in nodes if node.name in TARGET_NODE_NAMES]
    assert len(selected_nodes) > 0, f"Target nodes {TARGET_NODE_NAMES} not found."
    aggregators = [node for node in selected_nodes if node.type == "aggregator"]
    compute_nodes = [node for node in selected_nodes if node.type == "default"]
    assert len(aggregators) == 1, f"Expected exactly one aggregator node, found {len(aggregators)}."
    assert len(compute_nodes) >= 1, "Expected at least one default (compute) node."
    aggregator = aggregators[0]
    print(
        f"[*] Aggregator: {aggregator.name}; "
        f"compute nodes: " + ", ".join(n.name for n in compute_nodes)
    )
    return selected_nodes, aggregator, compute_nodes


def main():
    statuses, step_durations = init_tracking()
    try:
        record = {"step_status": statuses, "step_duration": step_durations}
        # Login remains responsible for shared setup until upload starts.
        # Permission errors here must not leave a successful login followed by
        # only unknown steps on the status page.
        with timed_step(record, "login"):
            core_client, nodes = authenticate()
            selected_nodes, aggregator, compute_nodes = split_nodes(nodes)

            # Shared project preparation (one project, all target nodes).
            print("[*] Preparing project and clearing previous analyses...")
            project = prepare_project(core_client, [str(node.id) for node in selected_nodes])
            master_image_id = get_master_image_id(core_client)

            worker = partial(
                run_pair,
                aggregator,
                project_id=project.id,
                master_image_id=master_image_id,
            )
            executor = ThreadPoolExecutor(max_workers=len(compute_nodes))

        print("[+] Login and shared setup successful.")
        # Parallel per-node runs (each analysis trimmed to its pair).
        print(f"[*] Running {len(compute_nodes)} node check(s) in parallel...")
        with executor:
            records = list(executor.map(worker, compute_nodes))

        # Merge per-node runs into step cards + node cards.
        merge_records(records, aggregator, statuses, step_durations)

    finally:
        print("[*] Writing health status reports...")
        write_all_reports(statuses, step_durations)
        print("[*] Finished health checks execution.")


if __name__ == "__main__":
    main()
