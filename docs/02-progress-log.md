# Progress log (5 lines a day is enough)

| Date | What I did | What broke | What I learned |
|------|-----------|------------|----------------|
| 2026-11-03 | M0. Project root is ~/setu-starter. Both MinIO regions and the gateway returned HTTP 200 on /minio/health/live. Site replication was already enabled (site-a and site-b). Wrote gw/demo/m0b-20261103T144944Z.txt through the gateway. First read on Region B returned the same bytes. Upper bound from ACK to that read: 772 ms. A prior mc ls took 380 ms, so the copy itself is inside that window. | tc netem as a normal user: Operation not permitted. sudo needs a password. Local git identity set only in this repo. | Chainguard image digest 3c60a2a8c4d3 is MinIO RELEASE.2026-10-23T20-06-51Z and site replication works. WSL shows 7.6 GiB RAM and 12 logical CPUs, not the full 16 GB. |
