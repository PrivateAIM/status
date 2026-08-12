import time
from functools import partial
from concurrent.futures import ThreadPoolExecutor

from config import TARGET_NODE_NAMES, TIMEOUT_SHORT_SECONDS
from hub_client import find_all, get_master_image_id, make_clients, prepare_project
from pair_run import run_pair
from aggregate import init_tracking, merge_records
from reporting import write_all_reports


def authenticate(statuses, step_durations):
    # Shared step, once for all nodes: authenticate and resolve the node list.
    print("[*] Step 1: Authenticating with FLAME Hub...")
    t_start = time.time()
    try:
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
        statuses["login"] = "success"
        print("[+] Login successful.")
    except BaseException:
        statuses["login"] = "failed"
        raise
    finally:
        step_durations["login"] = time.time() - t_start
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
        core_client, nodes = authenticate(statuses, step_durations)
        selected_nodes, aggregator, compute_nodes = split_nodes(nodes)

        # Shared project preparation (one project, all target nodes).
        print("[*] Step 2: Preparing project and clearing previous analyses...")
        project = prepare_project(core_client, [str(node.id) for node in selected_nodes])
        master_image_id = get_master_image_id(core_client)

        # Parallel per-node runs (each analysis trimmed to its pair).
        print(f"[*] Step 3: Running {len(compute_nodes)} node check(s) in parallel...")
        worker = partial(
            run_pair,
            aggregator,
            project_id=project.id,
            master_image_id=master_image_id,
        )
        with ThreadPoolExecutor(max_workers=len(compute_nodes)) as executor:
            records = list(executor.map(worker, compute_nodes))

        # Merge per-node runs into step cards + node cards.
        merge_records(records, aggregator, statuses, step_durations)

    finally:
        print("[*] Writing health status reports...")
        write_all_reports(statuses, step_durations)
        print("[*] Finished health checks execution.")


if __name__ == "__main__":
    main()
