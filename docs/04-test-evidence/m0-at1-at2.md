# M0 evidence — AT1 and AT2 (2026-11-03)

Commands were run in Ubuntu (`/home/cloud_automator/setu-starter`).

## AT1 — both regions healthy

`curl` from the host:

- `http://127.0.0.1:9100/minio/health/live` → 200 (Region A)
- `http://127.0.0.1:9200/minio/health/live` → 200 (Region B)
- `http://127.0.0.1:8080/minio/health/live` → 200 (gateway)

`docker compose ps` showed gateway, minio-a, minio-b, and monitor all Up.
MinIO log line: `Version: RELEASE.2026-10-23T20-06-51Z`.

## Replication config

`./scripts/mc.sh admin replicate info site-a` listed both peers:

- site-a `http://minio-a:9000` deployment `5d90adc6-671e-436e-b0af-692313ff2280`
- site-b `http://minio-b:9000` deployment `615b18db-5fc3-4a1c-bb46-39461bfd5caf`

## AT2 — write via gateway, read on B

Object: `gw/demo/m0b-20261103T144944Z.txt`
Body on A and on B: `m0-proof-2 2026-11-03T14:49:44Z`

First poll of Region B succeeded.
Upper bound from gateway ACK until `mc cat` on B returned: **772 ms**.
A separate `mc ls site-b` cost **380 ms** of client startup, so N is under 1 second and is not a sub-10 ms claim.

An earlier object, `m0-20261103T144928Z.txt`, matched on A and B as well.

## netem

`tc qdisc add dev lo root netem delay 1ms` as cloud_automator:
`RTNETLINK answers: Operation not permitted`.
Root was not tested (`sudo` needs a password).
