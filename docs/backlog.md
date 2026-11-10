# Backlog (do not build these during the current milestone)

- M3: HAProxy currently prefers Region A again as soon as A is healthy. Fail back only after checksums match.
- M5: retest `tc netem` with sudo. If it still fails inside containers, use Toxiproxy for the latency experiment.

- Host port parametrization: intentionally omitted per design decision. Hardcoded host ports (8080, 9100, 9200, 9999) and network names stay to keep local architecture simple; only one stack runs on the host at a time.
