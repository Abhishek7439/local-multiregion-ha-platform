# Design decisions (be ready to explain every one at the review)

## D1 - Object storage image
Options: official minio/minio (withdrawn), build from source, RustFS, SeaweedFS, Chainguard.
Choice: cgr.dev/chainguard/minio, pinned by digest (not a floating tag).
Reason: Chainguard still publishes a free image. Dated tags are not public, so the pin is the digest pulled on 2026-11-03: sha256:3c60a2a8c4d33409a9bc7a623a7fcbfb4605adc3d89422d2f53b3f673a6e5597. `minio --version` reported RELEASE.2026-10-23T20-06-51Z. Site replication with `mc admin replicate add` succeeded on this build.

## D2 - Region isolation
Each region has its own Docker network and volume; only the "global" network
connects them (this is where I can inject latency/partitions later).

## D3 - Gateway: nginx or HAProxy
Options: nginx 1.27 (passive `max_fails` plus `proxy_next_upstream`) and HAProxy 3.4.7 (active `GET /minio/health/live`).
Choice: HAProxy, image digest sha256:2caaf8b1a1ef67f3f1ea9b721f2821675d3ba4500fb518e23884fecb93e8dbaa. Config is gateway/haproxy.cfg. Region B is a `backup` server.
Reason: On 2026-11-03, with nginx already running, stopping Region A still allowed the first PUT (1218 ms after the stop) and a GET. Restarting nginx while A was stopped did not. The log was `host not found in upstream "minio-a:9000"`, and both PUT and GET got connection refused. HAProxy passed the same stop test: first PUT succeeded, 2447 ms from stop completion to write completion, and the GET returned `m1-haproxy-proof 1` from Region B. After a gateway restart with A still down, HAProxy reached HTTP 200 and the next PUT succeeded. Docs: https://www.haproxy.com/documentation/haproxy-configuration-tutorials/reliability/health-checks/ and https://hub.docker.com/_/haproxy/

## D4 - Project directory
Options: OneDrive path on Windows, /mnt/c inside WSL, Linux home.
Choice: /home/cloud_automator/setu-starter.
Reason: Docker bind mounts and shell scripts are reliable on the Linux filesystem. The brief forbids keeping the project under /mnt/c.

## D5 - Cross-region latency tool
Options: tc netem, Toxiproxy.
Choice: not chosen in M0. Do not install Toxiproxy yet.
Reason: `tc` is installed. As user cloud_automator, `tc qdisc add dev lo root netem delay 1ms` returned `RTNETLINK answers: Operation not permitted`. `sudo -n` asked for a password, so root was not tested. The latency experiment (M5) must re-check with sudo before we pick Toxiproxy.

## D6 - Container memory limits
Options: no limits, or caps sized to the WSL VM.
Choice: MinIO 512 MiB each, gateway 128 MiB, monitor 64 MiB.
Reason: The PC has 16 GB, but this WSL VM only exposes about 7.6 GiB to Docker. Caps stop two MinIO processes from taking the whole VM. `docker inspect` showed Memory=536870912 for each MinIO.
