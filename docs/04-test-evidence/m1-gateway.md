# M1 evidence — gateway reads and writes (2026-11-03)

Commands were run in Ubuntu (`/home/cloud_automator/setu-starter`).

## Nginx, gateway already running, then stop Region A

Health before the stop: A 200, B 200, gateway 200.
`docker compose stop minio-a` took 2509 ms.
First PUT, attempt 1, succeeded.
Object: `gw/demo/m1-nginx-20261103T172806Z.txt`
Body read back through the gateway and from Region B: `m1-nginx-proof 1`
Time from stop completion to that PUT finishing: **1218 ms**.

## Nginx restarted while Region A was stopped

`docker compose restart gateway` while A was stopped.
Log: `nginx: [emerg] host not found in upstream "minio-a:9000" in /etc/nginx/conf.d/default.conf:2`
PUT and GET both failed: `connect: connection refused`.
A and the gateway were started again afterward. Health returned 200.

## HAProxy, same stop test

Image: `haproxy@sha256:2caaf8b1a1ef67f3f1ea9b721f2821675d3ba4500fb518e23884fecb93e8dbaa` (tag 3.4.7-alpine).
`docker compose stop minio-a` took 533 ms.
First PUT, attempt 1, succeeded.
Time from stop completion to that PUT finishing: **2447 ms**.
GET body: `m1-haproxy-proof 1`
Same body on Region B.

## HAProxy restarted while Region A was stopped

Gateway HTTP was down for polls 1–6, then HTTP 200 on poll 7.
PUT `gw/demo/m1-haproxy-restart-174126Z.txt` succeeded.
GET body: `m1-haproxy-restart-proof`
Region A was started again. Health returned on poll 2.

RTO for this milestone is the HAProxy stop-test number: **2447 ms**. It includes one MinIO client container start. It is not an RPO measurement.
