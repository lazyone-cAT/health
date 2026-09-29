"""Hardcoded federated analytics demo.

No real federation runs here — this payload mimics what a cross-district
federated query would return: each PHC node shares aggregates only,
never raw inventory rows.
"""

FEDERATED_DEMO = {
    "query": "district_federated_stockout_risk_v1",
    "coordinator": "District Node — Kalahandi",
    "federation_id": "FED-KAL-2026-09",
    "rounds": 3,
    "privacy": {
        "raw_rows_shared": False,
        "mechanism": "Local aggregate computation + secure sum aggregation",
        "min_node_rows": 5,
        "noise": "None (demo mode — deterministic mock values)",
    },
    "nodes": [
        {
            "node_id": "NODE-KHARIAR",
            "phc": "Khariar PHC",
            "status": "online",
            "latency_ms": 41,
            "rounds_joined": 3,
            "local_aggregates": {
                "lines_reported": 20,
                "stock_out": 2,
                "critical": 3,
                "low": 4,
                "avg_days_cover": 16.4,
            },
        },
        {
            "node_id": "NODE-JUNAGARH",
            "phc": "Junagarh PHC",
            "status": "online",
            "latency_ms": 58,
            "rounds_joined": 3,
            "local_aggregates": {
                "lines_reported": 20,
                "stock_out": 1,
                "critical": 2,
                "low": 5,
                "avg_days_cover": 18.1,
            },
        },
        {
            "node_id": "NODE-DHARAMGARH",
            "phc": "Dharamgarh PHC",
            "status": "online",
            "latency_ms": 73,
            "rounds_joined": 3,
            "local_aggregates": {
                "lines_reported": 20,
                "stock_out": 0,
                "critical": 4,
                "low": 2,
                "avg_days_cover": 21.7,
            },
        },
        {
            "node_id": "NODE-BODEN",
            "phc": "Boden PHC",
            "status": "degraded",
            "latency_ms": 312,
            "rounds_joined": 2,
            "local_aggregates": {
                "lines_reported": 20,
                "stock_out": 3,
                "critical": 2,
                "low": 3,
                "avg_days_cover": 12.9,
            },
        },
        {
            "node_id": "NODE-NARLA",
            "phc": "Narla PHC",
            "status": "offline",
            "latency_ms": None,
            "rounds_joined": 0,
            "local_aggregates": None,
            "last_seen": "2026-09-28T18:42:00",
        },
    ],
    "aggregated_result": {
        "nodes_reporting": 4,
        "nodes_total": 5,
        "stock_out": 6,
        "critical": 11,
        "low": 14,
        "weighted_avg_days_cover": 17.3,
        "agreement_rate": 0.96,
    },
    "round_log": [
        {"round": 1, "phase": "query_dispatch", "participants": 4, "result": "ack 4/5"},
        {"round": 2, "phase": "local_aggregate", "participants": 4, "result": "4 aggregate vectors returned"},
        {"round": 3, "phase": "secure_sum", "participants": 4, "result": "district totals converged"},
    ],
    "demo_note": (
        "Hardcoded demonstration data. In a live deployment each PHC would run a "
        "local agent that computes these aggregates on-premise and only the "
        "aggregated vectors leave the node."
    ),
}
