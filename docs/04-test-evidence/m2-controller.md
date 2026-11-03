# M2 evidence — controller RTO (2026-11-03)

Command: `python3 controller/dr_controller.py` in `/home/cloud_automator/setu-starter`.
Then `docker compose stop minio-a`, wait for the RTO line, then `docker compose start minio-a`.

```json
{"event": "start", "state": "HEALTHY", "grace_seconds": 3, "ts": "2026-11-03T18:05:50Z"}
{"event": "transition", "from": "HEALTHY", "to": "DEGRADED", "region_a": "DOWN", "region_b": "UP", "reason": "region A health failed", "ts": "2026-11-03T18:05:53Z"}
{"event": "transition", "from": "DEGRADED", "to": "FAILOVER", "reason": "region A still down after the grace window", "ts": "2026-11-03T18:05:56Z"}
{"event": "rto", "milliseconds": 3448, "write_attempt": 1, "write_ms": 443, "object": "gw/demo/rto-20261103T180556Z.txt", "region_b": "UP", "ts": "2026-11-03T18:05:57Z"}
{"event": "transition", "from": "FAILOVER", "to": "RECOVERING", "reason": "region A is live again; FAILBACK waits for checksums in M3", "ts": "2026-11-03T18:05:58Z"}
```

Gateway read and Region B read of that object both returned `m2-rto-proof`.
After the run, Region A and the gateway health URLs returned 200. The controller process was stopped.

RTO is **3448 ms** from the first failed health check to the successful write. The write call itself was 443 ms. The rest is the 3 second grace window.
