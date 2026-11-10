import os
import base64
import re
import subprocess
import sys

print("=== Building PDF Report with Real Inline Output Images ===")

repo_root = "/home/cloud_automator/setu-starter"
img_dir = os.path.join(repo_root, "docs/images")
html_path = os.path.join(repo_root, "report/report.html")
pdf_path = os.path.join(repo_root, "report/SETU_SWFW_5S_02_Project_Report.pdf")

# Helper to load image as base64 data URI
def img_b64(filename):
    p = os.path.join(img_dir, filename)
    with open(p, "rb") as f:
        data = f.read()
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:image/png;base64,{b64}"

img_doctor = img_b64("01_doctor.png")
img_ps = img_b64("02_compose_ps.png")
img_failover = img_b64("03_demo_failover.png")
img_failback = img_b64("04_demo_failback_gate.png")
img_banner = img_b64("05_demo_banner_exit0.png")
img_chaos_table = img_b64("06_chaos_summary_table.png")
img_rto_stats = img_b64("07_e1_e2_rto_stats.png")
img_e4 = img_b64("08_e4_partition_lww.png")
img_audit = img_b64("09_deep_audit_json.png")
img_rollback = img_b64("10_gitops_rollback.png")
img_arch = img_b64("11_diagram_architecture.png")
img_fsm = img_b64("12_diagram_dr_state_machine.png")
img_chart = img_b64("13_chart_rto_e1_e2.png")

html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>SETU SWFW_5S_02 Project Report</title>
<style>
  @page {{
    size: A4 portrait;
    margin: 12mm 14mm 14mm 14mm;
    @bottom-right {{
      content: "Page " counter(page);
      font-size: 8pt;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      color: #64748b;
    }}
    @bottom-left {{
      content: "SETU SWFW_5S_02: Local Multi-Region Data Platform";
      font-size: 8pt;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      color: #94a3b8;
    }}
  }}

  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    color: #1e293b;
    background-color: #ffffff;
    font-size: 8.8pt;
    line-height: 1.4;
    margin: 0;
    padding: 0;
  }}

  .page-break {{
    page-break-after: always;
    break-after: page;
  }}

  /* Cover Page */
  .cover {{
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    min-height: 255mm;
    box-sizing: border-box;
    padding: 10mm 6mm 6mm 6mm;
  }}
  .cover-badge {{
    display: inline-block;
    background: #0f172a;
    color: #38bdf8;
    font-size: 9pt;
    font-weight: 700;
    padding: 5px 14px;
    border-radius: 4px;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    margin-bottom: 12px;
  }}
  .cover-title {{
    font-size: 23pt;
    font-weight: 800;
    line-height: 1.25;
    color: #0f172a;
    margin: 0 0 10px 0;
  }}
  .cover-subtitle {{
    font-size: 11pt;
    color: #475569;
    font-weight: 500;
    line-height: 1.4;
    margin: 0 0 20px 0;
    border-bottom: 2px solid #e2e8f0;
    padding-bottom: 15px;
  }}
  .cover-meta-grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
    background: #f8fafc;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 14px 18px;
    margin-bottom: 16px;
  }}
  .cover-meta-item strong {{
    display: block;
    font-size: 7.5pt;
    text-transform: uppercase;
    color: #64748b;
    letter-spacing: 0.5px;
    margin-bottom: 2px;
  }}
  .cover-meta-item span {{
    font-size: 9.5pt;
    font-weight: 600;
    color: #0f172a;
  }}
  .cover-abstract {{
    background: #ffffff;
    border-left: 4px solid #0284c7;
    padding: 10px 14px;
    font-size: 8.8pt;
    color: #334155;
    line-height: 1.45;
    margin-top: 10px;
  }}

  /* Headings */
  h1 {{
    font-size: 14pt;
    font-weight: 800;
    color: #0f172a;
    margin: 0 0 7px 0;
    padding-bottom: 4px;
    border-bottom: 1.5px solid #0284c7;
  }}
  h2 {{
    font-size: 10.5pt;
    font-weight: 700;
    color: #0369a1;
    margin: 9px 0 4px 0;
  }}
  h3 {{
    font-size: 9.2pt;
    font-weight: 700;
    color: #1e293b;
    margin: 7px 0 3px 0;
  }}
  p {{
    margin: 0 0 6px 0;
  }}

  /* Tables */
  table {{
    width: 100%;
    border-collapse: collapse;
    margin: 5px 0 8px 0;
    font-size: 7.8pt;
    page-break-inside: avoid;
  }}
  th {{
    background: #0f172a;
    color: #ffffff;
    font-weight: 600;
    text-align: left;
    padding: 4px 6px;
    border: 1px solid #0f172a;
  }}
  td {{
    padding: 3.5px 6px;
    border: 1px solid #cbd5e1;
    vertical-align: top;
  }}
  tr:nth-child(even) td {{
    background: #f8fafc;
  }}
  .source-tag {{
    font-size: 6.8pt;
    color: #64748b;
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    display: block;
    margin-top: 2px;
  }}
  .pass-badge {{
    color: #047857;
    font-weight: 700;
  }}

  /* Callouts & Code */
  .callout {{
    background: #f0f9ff;
    border-left: 3.5px solid #0284c7;
    padding: 6px 9px;
    margin: 5px 0 7px 0;
    font-size: 8.2pt;
    page-break-inside: avoid;
  }}
  code {{
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    font-size: 7.8pt;
    background: #f1f5f9;
    padding: 1px 3px;
    border-radius: 3px;
    color: #0f172a;
  }}
  pre {{
    background: #0f172a;
    color: #f8fafc;
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    font-size: 7.2pt;
    padding: 7px 9px;
    border-radius: 4px;
    margin: 5px 0 7px 0;
    line-height: 1.3;
    overflow-x: hidden;
    page-break-inside: avoid;
  }}

  /* Output Images */
  .img-box {{
    margin: 6px 0 8px 0;
    text-align: center;
    page-break-inside: avoid;
  }}
  .img-box img {{
    max-width: 100%;
    height: auto;
    border-radius: 5px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.12);
  }}
  .img-caption {{
    font-size: 7.2pt;
    color: #64748b;
    margin-top: 3px;
    font-style: italic;
  }}

  /* Table of Contents */
  .toc {{
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 5px;
    padding: 9px 12px;
    margin-bottom: 10px;
  }}
  .toc-title {{
    font-size: 10pt;
    font-weight: 700;
    color: #0f172a;
    margin-bottom: 5px;
    border-bottom: 1px solid #cbd5e1;
    padding-bottom: 3px;
  }}
  .toc-grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 3px 16px;
    font-size: 8pt;
  }}
  .toc-item {{
    display: flex;
    justify-content: space-between;
    border-bottom: 1px dotted #cbd5e1;
    padding: 1px 0;
  }}
  .toc-item span:first-child {{
    color: #1e293b;
    font-weight: 500;
  }}
  .toc-item span:last-child {{
    color: #0284c7;
    font-weight: 600;
  }}
</style>
</head>
<body>

<!-- ================= PAGE 1: COVER PAGE ================= -->
<div class="cover">
  <div>
    <div class="cover-badge">SETU 2026–27 | Project SWFW_5S_02</div>
    <h1 class="cover-title">Local Multi-Region Highly Available Data Platform</h1>
    <div class="cover-subtitle">Automated Disaster Recovery, Chaos Engineering, and Autonomous GitOps Continuous Delivery</div>

    <div class="cover-meta-grid">
      <div class="cover-meta-item">
        <strong>Student Name</strong>
        <span>Abhishek Kothe</span>
      </div>
      <div class="cover-meta-item">
        <strong>GitHub Account</strong>
        <span>@Abhishek7439</span>
      </div>
      <div class="cover-meta-item">
        <strong>Academic Institution</strong>
        <span>YCCE Nagpur (Computer Technology)</span>
      </div>
      <div class="cover-meta-item">
        <strong>Academic Term</strong>
        <span>5th Semester</span>
      </div>
      <div class="cover-meta-item">
        <strong>Course Track</strong>
        <span>SETU 2026–27 (SWFW_5S_02)</span>
      </div>
      <div class="cover-meta-item">
        <strong>Submission Date</strong>
        <span>10 November 2026</span>
      </div>
    </div>

    <div class="cover-abstract">
      <strong>Executive Brief:</strong> This project designs, implements, and empirically validates an enterprise-grade multi-region object storage platform running locally on standard Linux (WSL2/Ubuntu) with 16 GB host memory. It delivers active-active cross-region data replication, sub-5-second automated failover via HAProxy active health checking, cryptographic integrity-gated failback, pull-based GitOps continuous deployment with automated self-healing rollback, and a 5-scenario chaos engineering suite. Crucially, the entire control and proof plane is implemented in Python's standard library with zero third-party dependencies, and every performance metric is backed by immutable runtime evidence.
    </div>
  </div>

  <div style="border-top: 1px solid #cbd5e1; padding-top: 8px; font-size: 7.5pt; color: #64748b; display: flex; justify-content: space-between;">
    <span>Demonstration Status: Recorded execution in <code>demo/demo-run.log</code> | Live evaluation available</span>
    <span>Host Environment: Ubuntu 26.04.1 LTS on WSL2</span>
  </div>
</div>
<div class="page-break"></div>

<!-- ================= PAGE 2: SUMMARY & TOC ================= -->
<h1>1. Executive Summary & Table of Contents</h1>

<div class="toc">
  <div class="toc-title">Table of Contents</div>
  <div class="toc-grid">
    <div class="toc-item"><span>1. Executive Summary & Table of Contents</span> <span>Page 2</span></div>
    <div class="toc-item"><span>2. Problem Statement & Requirements</span> <span>Page 3</span></div>
    <div class="toc-item"><span>3. Architectural Design & Topology</span> <span>Page 4</span></div>
    <div class="toc-item"><span>4. Operational Mechanics & Failure Story</span> <span>Page 5</span></div>
    <div class="toc-item"><span>5. DR State Machine & GitOps Workflow</span> <span>Page 6</span></div>
    <div class="toc-item"><span>6. Implementation Decisions & Repo Map</span> <span>Page 7</span></div>
    <div class="toc-item"><span>7. Setup & Operator Runbook</span> <span>Page 8</span></div>
    <div class="toc-item"><span>8. Real Troubleshooting & Root Causes</span> <span>Page 9</span></div>
    <div class="toc-item"><span>9. Acceptance Test Results (AT1–AT7)</span> <span>Page 10</span></div>
    <div class="toc-item"><span>10. Chaos Engineering Suite (E1–E5)</span> <span>Page 11</span></div>
    <div class="toc-item"><span>11. Cryptographic Deep Audit Proof</span> <span>Page 12</span></div>
    <div class="toc-item"><span>12. Mandatory Scope & Limitations</span> <span>Page 13</span></div>
    <div class="toc-item"><span>13. Real Engineering Bugs & Learnings</span> <span>Page 14</span></div>
    <div class="toc-item"><span>14. Future Directions & Live Demo Guide</span> <span>Page 15</span></div>
    <div class="toc-item"><span>15. Appendix: Commands & Reviewer Q&A</span> <span>Page 16</span></div>
  </div>
</div>

<h2>What I Built and What It Proves</h2>
<p>
I built an active-active, dual-region distributed object storage platform running entirely on a single developer workstation without relying on Kubernetes or heavy third-party Python packages. The architecture combines containerized MinIO object storage across isolated Docker bridge networks, an active Layer-7 reverse proxy gateway (HAProxy 3.4.7), an autonomous disaster recovery controller implemented as a 5-state deterministic finite state machine, a pull-based GitOps reconciler with automated rollback capabilities, and programmatic network degradation injection via Toxiproxy.
</p>
<p>
The system demonstrates that enterprise-grade disaster recovery, zero-data-loss failover under crash conditions, and continuous deployment safety gates can be modeled deterministically, inspected at the raw socket and HTTP layer, and evaluated objectively on modest commodity hardware.
</p>

<h2>Headline Empirical Results in 5 Lines</h2>
<div class="callout">
  <strong>1. High Availability Failover:</strong> Active health checking and Layer-7 redispatch achieve an RTO of <strong>3448 ms</strong> (including a 3-second anti-flapping grace window) with zero dropped client writes.<br>
  <strong>2. Zero Data Loss Under Crash:</strong> Measured RPO is exactly <strong>0 missing objects</strong> across sequential burst writes during both graceful stop and abrupt SIGKILL crashes.<br>
  <strong>3. Fast Cryptographic Failback:</strong> The metadata inventory gate matches 143+ objects in <strong>1.2 seconds</strong> (a 123x speedup over sequential downloads), preventing premature un-fencing.<br>
  <strong>4. Autonomous GitOps Self-Healing:</strong> Broken infrastructure changes trigger automated post-apply health gate failure and stack rollback to <code>last_good</code> in <strong>19.0 seconds</strong>.<br>
  <strong>5. Cryptographic Parity Audit:</strong> Byte-for-byte SHA-256 payload audit confirms <strong>153 of 153 objects identical</strong> across both region volumes with zero silent data corruption (bit rot).
</div>
<div class="page-break"></div>

<!-- ================= PAGE 3: PROBLEM STATEMENT & REQUIREMENTS ================= -->
<h1>2. Problem Statement & Requirements Traceability</h1>

<h2>Official SETU Course Problem Statement</h2>
<p style="font-style: italic; color: #334155; background: #f8fafc; border-left: 3px solid #64748b; padding: 5px 8px;">
"Design and implement a multi-region, highly available data platform running locally with automated disaster recovery, chaos engineering resilience validation, and GitOps-driven continuous deployment. The platform must provide transparent failover, zero or minimal data loss (measured via Recovery Point Objective), automated integrity-checked failback, self-healing continuous delivery, and comprehensive failure injection testing without relying on proprietary cloud services or unvetted external dependencies."
</p>

<h2>Requirements Traceability Matrix</h2>
<table>
  <thead>
    <tr>
      <th style="width: 20%;">Requirement Domain</th>
      <th style="width: 45%;">Engineering Realization in Codebase</th>
      <th style="width: 15%;">Status</th>
      <th style="width: 20%;">Primary Evidence</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><strong>Multi-Region Isolation</strong></td>
      <td>Two independent Docker bridge networks (<code>setu_region_a</code>, <code>setu_region_b</code>) with isolated named volumes; joined only via <code>setu_global</code> transit network.</td>
      <td><span class="pass-badge">PASS</span></td>
      <td><code>m0-at1-at2.md</code><span class="source-tag">Source: docs/04-test-evidence/</span></td>
    </tr>
    <tr>
      <td><strong>Active Data Replication</strong></td>
      <td>MinIO two-way active-active site replication over port 9000 with bidirectional sync and Last-Write-Wins (LWW) conflict resolution.</td>
      <td><span class="pass-badge">PASS</span></td>
      <td><code>m0-at1-at2.md</code><span class="source-tag">Source: docs/04-test-evidence/</span></td>
    </tr>
    <tr>
      <td><strong>Layer-7 Ingress & HA</strong></td>
      <td>HAProxy 3.4.7 ingress proxy (<code>:8080</code>) with dynamic DNS resolution, active <code>/minio/health/live</code> polling, and Layer-7 HTTP redispatch.</td>
      <td><span class="pass-badge">PASS</span></td>
      <td><code>m1-gateway.md</code><span class="source-tag">Source: docs/04-test-evidence/</span></td>
    </tr>
    <tr>
      <td><strong>Automated Disaster Recovery</strong></td>
      <td>Deterministic 5-state Python FSM (<code>dr_controller.py</code>) executing automated failover, administrative socket fencing (<code>MAINT</code>), and RTO measurement.</td>
      <td><span class="pass-badge">PASS</span></td>
      <td><code>m2-controller.md</code><span class="source-tag">Source: docs/04-test-evidence/</span></td>
    </tr>
    <tr>
      <td><strong>Integrity Failback Gate</strong></td>
      <td>Fast listing and ETag parity comparison (<code>compare_sites</code>) holding Region A fenced in <code>MAINT</code> until 100% object parity is confirmed.</td>
      <td><span class="pass-badge">PASS</span></td>
      <td><code>m3-failback-rpo.md</code><span class="source-tag">Source: docs/04-test-evidence/</span></td>
    </tr>
    <tr>
      <td><strong>RPO Measurement</strong></td>
      <td>Numbered write stream testing verifying zero missing writes on backup across graceful stop and SIGKILL crashes (<code>rpo_objects: 0</code>).</td>
      <td><span class="pass-badge">PASS</span></td>
      <td><code>m3-failback-rpo.md</code><span class="source-tag">Source: docs/04-test-evidence/</span></td>
    </tr>
    <tr>
      <td><strong>GitOps Continuous Delivery</strong></td>
      <td>Pull-based reconciler (<code>gitops/reconciler.py</code>) with syntax pre-flight, targeted container re-creation, post-apply health gate, and auto-rollback.</td>
      <td><span class="pass-badge">PASS</span></td>
      <td><code>m4-gitops.md</code><span class="source-tag">Source: docs/04-test-evidence/</span></td>
    </tr>
    <tr>
      <td><strong>Chaos Engineering Suite</strong></td>
      <td>Automated test suite (<code>make chaos</code>) testing 5 failure modes: crash (E1), socket freeze (E2), WAN latency (E3), one-way partition (E4), and deploy failure (E5).</td>
      <td><span class="pass-badge">PASS</span></td>
      <td><code>m5-chaos.md</code><span class="source-tag">Source: docs/04-test-evidence/</span></td>
    </tr>
    <tr>
      <td><strong>Cryptographic Audit</strong></td>
      <td>Deep payload verification engine (<code>make audit</code>) computing full SHA-256 digests of all 153 objects to guarantee zero bit rot across volumes.</td>
      <td><span class="pass-badge">PASS</span></td>
      <td><code>m6-deep-audit.md</code><span class="source-tag">Source: docs/04-test-evidence/</span></td>
    </tr>
  </tbody>
</table>
<div class="page-break"></div>

<!-- ================= PAGE 4: ARCHITECTURE ================= -->
<h1>3. Architectural Design & Topology</h1>

<h2>Component Architecture</h2>
<p>
The platform models two geographically distinct availability zones on a single host kernel. Cross-region communication is constrained to a single bridge transit network, providing a programmatic choke point for network fault injection.
</p>

<div class="img-box">
  <img src="{img_arch}" alt="Architecture Diagram">
  <div class="img-caption">Terminal output rendered from docker-compose.yml & docs/03-architecture.md, 10 November 2026</div>
</div>

<h2>Data Flow for a Normal S3 Write Operation</h2>
<ol style="margin: 0; padding-left: 18px;">
  <li><strong>Client Request:</strong> An S3 client crafts an HTTP PUT request with AWS SigV4 authorization headers targeting HAProxy on <code>http://127.0.0.1:8080/demo/object.txt</code>.</li>
  <li><strong>Ingress Evaluation:</strong> HAProxy checks backend status. Because <code>minio-a</code> is reporting healthy (HTTP 200 on <code>/minio/health/live</code>), HAProxy forwards the stream directly to <code>minio-a:9000</code>.</li>
  <li><strong>Persistence & Header Stamp:</strong> <code>minio-a</code> commits the payload to the local named volume <code>minio_a_data</code> and returns HTTP 200. HAProxy injects <code>X-Backend-Server: minio-a</code> into the response to client.</li>
  <li><strong>Asynchronous Cross-Region Sync:</strong> MinIO's internal site replication engine queues the mutation in its replication log. The worker transmits the payload across <code>setu_global</code> directly to Region B (or via Toxiproxy port 9002 during chaos runs). <code>minio-b</code> commits the object to <code>minio_b_data</code> with identical ETag and metadata.</li>
</ol>
<div class="page-break"></div>

<!-- ================= PAGE 5: HOW IT WORKS ================= -->
<h1>4. Operational Mechanics & The Narrated Failure Story</h1>

<h2>The Complete Narrated Failure Story (End-to-End Self-Healing)</h2>
<p>
The sequence below narrates the exact chain of events executed during the automated demonstration (<code>make demo</code>), illustrating how the platform detects failure, protects data integrity, and restores service:
</p>

<div class="img-box">
  <img src="{img_failover}" alt="Demo Failover">
  <div class="img-caption">Terminal output rendered from demo/demo-run.log, 10 November 2026</div>
</div>

<h3>Step 1: Disaster Strikes (Region A Dies)</h3>
<p>Disaster is injected by abruptly stopping Region A (<code>docker stop setu-multiregion-minio-a-1</code>). Region A's container stops acknowledging TCP connections.</p>

<h3>Step 2: Layer-7 Gateway Redispatch</h3>
<p>An in-flight client write arriving at HAProxy immediately encounters a closed socket. Because HAProxy is configured with <code>option redispatch</code> and active health checking, it instantly routes the request to the standby server (Region B) on port 9200. The client write succeeds without returning HTTP 502/503.</p>

<h3>Step 3: DR Controller Detects Failure & Fences Primary</h3>
<p>The DR controller daemon (<code>controller/dr_controller.py</code>) probes Region A's health endpoint every second. Upon receiving a connection failure, it transitions from <code>HEALTHY</code> to <code>DEGRADED</code>. It initiates a 3-second grace window to suppress false alarms from transient network spikes. When Region A remains unreachable after 3 seconds, the controller transitions to <code>FAILOVER</code> and performs administrative ingress fencing: <code>set server minio_api/minio-a state maint</code>. This locks Region A into maintenance mode. The controller issues a write probe to Region B, verifying that the failover path is fully functional, and records the empirical RTO of <strong>3448 ms</strong> (or <strong>4011 ms</strong> in demo-run.log).</p>

<div class="img-box">
  <img src="{img_failback}" alt="Demo Failback Gate">
  <div class="img-caption">Terminal output rendered from demo/demo-run.log, 10 November 2026</div>
</div>

<h3>Step 4: Cryptographic Verification & Safe Failback</h3>
<p>Region A restarts into quarantine. The DR controller transitions to <code>RECOVERING</code> and holds Region A fenced in <code>MAINT</code>. While MinIO resyncs, <code>compare_sites</code> reports <code>match: false</code>. Once parity is confirmed (<code>match: true</code>), the controller transitions to <code>FAILBACK</code>, issues <code>set server minio_api/minio-a state ready</code>, and returns to <code>HEALTHY</code>.</p>
<div class="page-break"></div>

<!-- ================= PAGE 6: DR STATE MACHINE & GITOPS ================= -->
<h1>5. DR State Machine & GitOps Reconciler</h1>

<h2>The 5-State Deterministic Disaster Recovery FSM</h2>
<p>
The disaster recovery controller enforces strict monotonic progression through failure and recovery:
</p>

<div class="img-box">
  <img src="{img_fsm}" alt="DR State Machine">
  <div class="img-caption">Terminal output rendered from controller/dr_controller.py, 10 November 2026</div>
</div>

<h2>Autonomous GitOps Continuous Delivery & Rollback</h2>
<p>
The GitOps engine (<code>gitops/reconciler.py</code>) operates as an autonomous background daemon implementing pull-based reconciliation directly on Docker Compose infrastructure without Kubernetes:
</p>

<div class="img-box">
  <img src="{img_rollback}" alt="GitOps Rollback">
  <div class="img-caption">Terminal output rendered from demo/demo-run.log, 10 November 2026</div>
</div>

<ol style="margin: 0; padding-left: 18px;">
  <li><strong>Continuous Polling:</strong> The reconciler monitors the target deployment branch for new commits at a configurable interval (default 3 seconds).</li>
  <li><strong>Pre-Flight Syntax Validation:</strong> Before applying any configuration changes, it executes <code>docker compose config</code>. Syntactically invalid YAML is rejected immediately without touching containers.</li>
  <li><strong>Targeted Container Re-creation:</strong> By inspecting git diffs between active and candidate commits, the reconciler re-creates <em>only modified stateless services</em> (e.g., updating <code>haproxy.cfg</code> re-creates only the gateway container, never restarting healthy stateful storage volumes).</li>
  <li><strong>Active Health Gate & Rollback:</strong> Following deployment, the reconciler queries <code>/minio/health/live</code> across all endpoints. If any health probe fails within 15 seconds, it immediately reverts the worktree to <code>last_good</code>, restores the healthy configuration in <strong>19.0 seconds</strong>, and blacklists the bad commit hash in <code>.gitops_state.json</code>.</li>
</ol>
<div class="page-break"></div>

<!-- ================= PAGE 7: IMPLEMENTATION DECISIONS ================= -->
<h1>6. Implementation Choices & Design Decisions</h1>

<h2>Technology Stack Rationale</h2>
<ul>
  <li><strong>Docker Compose over Kubernetes:</strong> Running Kubernetes locally requires 2–4 GB just for the control plane and introduces non-deterministic scheduling. Docker Compose executes natively with minimal memory footprint (~1.2 GB total), keeping networking visible and student-explainable.</li>
  <li><strong>Chainguard MinIO Image:</strong> The official MinIO Docker image was withdrawn from Docker Hub in 2024. We pinned the free, verified Chainguard build (<code>cgr.dev/chainguard/minio</code> by digest <code>sha256:3c60a2a8...</code>).</li>
  <li><strong>HAProxy over Nginx:</strong> Nginx fails to start or reload when an upstream host is down (<code>host not found in upstream "minio-a"</code>). HAProxy resolves hostnames dynamically, supports active health checking, and exposes a runtime UNIX/TCP admin socket for instantaneous zero-reload server fencing.</li>
  <li><strong>Python Standard Library:</strong> The entire controller, proof module, AWS SigV4 signer, and chaos suite are implemented using <code>urllib</code>, <code>socket</code>, <code>hashlib</code>, and <code>hmac</code>. Zero third-party packages (no <code>boto3</code>, <code>botocore</code>, or <code>requests</code>).</li>
  <li><strong>Toxiproxy over <code>tc netem</code>:</strong> Host Traffic Control requires <code>CAP_NET_ADMIN</code> root capabilities, which failed inside unprivileged WSL2. Toxiproxy operates entirely in user-space, providing programmatic REST-controlled WAN simulation.</li>
</ul>

<h2>Design Decisions Summary (D1–D12)</h2>
<table>
  <thead>
    <tr>
      <th style="width: 10%;">ID</th>
      <th style="width: 25%;">Decision Domain</th>
      <th style="width: 25%;">Selected Choice</th>
      <th style="width: 40%;">Primary Engineering Rationale</th>
    </tr>
  </thead>
  <tbody>
    <tr><td>D1</td><td>Storage Image</td><td>Chainguard MinIO pinned by digest</td><td>Official image withdrawn; pinned digest ensures reproducible multi-region bootstrap.</td></tr>
    <tr><td>D2</td><td>Region Isolation</td><td>Isolated networks & named volumes</td><td>Prevents shared-memory side channels; models real distributed boundaries.</td></tr>
    <tr><td>D3</td><td>Ingress Proxy</td><td>HAProxy 3.4.7 with admin socket</td><td>Nginx crashed when upstream down; HAProxy provides active health & live fencing.</td></tr>
    <tr><td>D4</td><td>Directory Layout</td><td>Linux home (WSL2 native)</td><td>Docker Desktop bind-mounts under Windows paths corrupt inode events.</td></tr>
    <tr><td>D5</td><td>WAN Emulation</td><td>Toxiproxy v2.9.0</td><td>Host <code>tc netem</code> failed with <code>Operation not permitted</code>; Toxiproxy is root-free.</td></tr>
    <tr><td>D6</td><td>Memory Limits</td><td>MinIO 512M, GW 128M, Monitor 64M</td><td>Prevents 2 storage nodes from exhausting 7.6 GiB WSL2 virtual memory.</td></tr>
    <tr><td>D7</td><td>DR Controller</td><td>5-State Python FSM (stdlib only)</td><td>Enforces 3s anti-flap grace, admin fencing, and integrity-checked failback.</td></tr>
    <tr><td>D8</td><td>Integrity Gate</td><td>Fast listing parity (1.2s)</td><td>Sequential downloads took 145.7s; metadata fast-path achieves 123x speedup.</td></tr>
    <tr><td>D9</td><td>GitOps Reconciler</td><td>Targeted apply + active health gate</td><td>Avoids blanket container recreation; autonomous rollback on health failure.</td></tr>
    <tr><td>D10</td><td>S3 Client Signer</td><td>AWS SigV4 stdlib implementation</td><td>Strict zero-package requirement; avoids 100+ MB <code>boto3</code> wheel dependencies.</td></tr>
    <tr><td>D11</td><td>Proxy Placement</td><td>Surgical on A&rarr;B replication path</td><td>Isolates inter-region WAN chaos without affecting client-to-gateway traffic.</td></tr>
    <tr><td>D12</td><td>E3 WAN Thresholds</td><td>500ms latency, 32KB/s bandwidth</td><td>Exploratory runs at 100ms were masked by TCP buffers; 500ms produced real lag.</td></tr>
  </tbody>
</table>
<div class="page-break"></div>

<!-- ================= PAGE 8: SETUP & PROCEDURE ================= -->
<h1>7. Operational Setup & Procedure</h1>

<h2>System Prerequisites & Pre-Flight Check</h2>
<div class="img-box">
  <img src="{img_doctor}" alt="Make Doctor Output">
  <div class="img-caption">Terminal output rendered from scripts/doctor.sh, 10 November 2026</div>
</div>

<h2>Platform Topology & Container Vitality</h2>
<div class="img-box">
  <img src="{img_ps}" alt="Docker Compose PS Output">
  <div class="img-caption">Terminal output rendered from docker compose ps, 10 November 2026</div>
</div>

<h2>Exact Step-by-Step Operator Sequence</h2>
<ol style="margin: 0; padding-left: 18px;">
  <li><strong>Clone Repository:</strong> <code>git clone &lt;repo-url&gt; &amp;&amp; cd setu-starter</code></li>
  <li><strong>Verify Environment:</strong> <code>make doctor</code> (validates memory, Docker, Python 3 in ~2s).</li>
  <li><strong>Start Stack:</strong> <code>make up</code> (starts all 5 containers in ~10s).</li>
  <li><strong>Run End-to-End Demo:</strong> <code>make demo</code> (runs full 10-step self-healing verification in ~1m50s).</li>
  <li><strong>Run Chaos Suite:</strong> <code>make chaos</code> (executes E1–E5 resilience suite in ~4m30s).</li>
  <li><strong>Run Deep Cryptographic Audit:</strong> <code>make audit</code> (verifies 153/153 SHA-256 payload digests in ~5s).</li>
</ol>
<div class="page-break"></div>

<!-- ================= PAGE 9: TROUBLESHOOTING ================= -->
<h1>8. Real Troubleshooting & Field Issues Encountered</h1>

<p>
During the development of Milestones M0 through M6, several subtle real-world failure modes were encountered and resolved:
</p>

<h3>Issue 1: Unprivileged <code>tc</code> Network Emulation Failed (<code>Operation not permitted</code>)</h3>
<ul>
  <li><strong>Symptom:</strong> Executing <code>tc qdisc add dev eth0 root netem delay 50ms</code> on the host returned <code>RTNETLINK answers: Operation not permitted</code>.</li>
  <li><strong>Root Cause:</strong> Linux kernel network namespace manipulation requires the <code>CAP_NET_ADMIN</code> capability. Non-root users inside WSL2 or standard containers cannot modify host traffic control queues.</li>
  <li><strong>Resolution:</strong> Deployed <strong>Toxiproxy v2.9.0</strong> on the transit bridge. Toxiproxy operates entirely in user-space as a TCP socket proxy, manipulating streams via standard socket I/O without requiring root permissions.</li>
</ul>

<h3>Issue 2: Stale Bind-Mount Cache After Multi-Project Execution</h3>
<ul>
  <li><strong>Symptom:</strong> After running tests on a throwaway project, restarting the main stack caused HAProxy to fail to boot, complaining of missing socket paths.</li>
  <li><strong>Root Cause:</strong> Docker Desktop on WSL2 caches bind-mount inode mappings when containers are recreated across differing compose project names without purging container metadata.</li>
  <li><strong>Resolution:</strong> Use <code>docker compose up -d --force-recreate</code> when switching between project configurations to ensure fresh inode binding.</li>
</ul>

<h3>Issue 3: Nginx Upstream Name Resolution Failure During Backend Outage</h3>
<ul>
  <li><strong>Symptom:</strong> In Milestone M1, when Region A was stopped and Nginx was restarted, Nginx crashed with <code>host not found in upstream "minio-a:9000"</code>, causing total ingress failure.</li>
  <li><strong>Root Cause:</strong> Nginx resolves upstream DNS at configuration parse time by default. If a backend container is stopped during startup, Nginx halts entirely.</li>
  <li><strong>Resolution:</strong> Replaced Nginx with <strong>HAProxy 3.4.7</strong>, which performs dynamic runtime DNS resolution and active Layer-7 health probing without crashing.</li>
</ul>

<h3>Issue 4: Gray Failure Bimodal RTO During <code>docker pause</code></h3>
<ul>
  <li><strong>Symptom:</strong> In Experiment E2, RTO measurements clustered bimodally around either ~3.6s or ~7.2s.</li>
  <li><strong>Root Cause:</strong> <code>docker pause</code> freezes container execution without closing TCP sockets or sending TCP RST packets. Client worker threads with a 2.0-second timeout were expiring before HAProxy's 2-second connection timeout and redispatch completed.</li>
  <li><strong>Resolution:</strong> Tuned client request timeout to <strong>3.5 seconds</strong> in <code>chaos/experiments/e2_pause.py</code>, allowing HAProxy's connect timeout and Layer-7 redispatch to complete gracefully.</li>
</ul>
<div class="page-break"></div>

<!-- ================= PAGE 10: ACCEPTANCE RESULTS ================= -->
<h1>9. Acceptance Test Results (AT1–AT7)</h1>

<p>
The platform was evaluated against the seven formal acceptance criteria defined in the project specification. All tests passed with empirical evidence preserved in <code>docs/04-test-evidence/</code>:
</p>

<table>
  <thead>
    <tr>
      <th style="width: 10%;">ID</th>
      <th style="width: 25%;">Acceptance Test</th>
      <th style="width: 35%;">Empirical Measured Outcome</th>
      <th style="width: 12%;">Status</th>
      <th style="width: 18%;">Evidence File</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><strong>AT1</strong></td>
      <td>Multi-Region Health Endpoints</td>
      <td>Region A (<code>:9100</code>), Region B (<code>:9200</code>), and Gateway (<code>:8080</code>) all return HTTP 200 on <code>/minio/health/live</code>.</td>
      <td><span class="pass-badge">PASS</span></td>
      <td><code>m0-at1-at2.md</code><span class="source-tag">Source: docs/04-test-evidence/</span></td>
    </tr>
    <tr>
      <td><strong>AT2</strong></td>
      <td>Normal Cross-Region Replication</td>
      <td>Object written via Gateway replicates to Region B; bit-for-bit identical SHA-256 (<code>2cf99d0e...</code>).</td>
      <td><span class="pass-badge">PASS</span></td>
      <td><code>m0-at1-at2.md</code><span class="source-tag">Source: docs/04-test-evidence/</span></td>
    </tr>
    <tr>
      <td><strong>AT3</strong></td>
      <td>Automated Failover & Fencing</td>
      <td>Region A stopped; HAProxy redispatches to B; DR controller fences A (<code>MAINT</code>); RTO measured at <strong>3448 ms</strong>.</td>
      <td><span class="pass-badge">PASS</span></td>
      <td><code>m2-controller.md</code><span class="source-tag">Source: docs/04-test-evidence/</span></td>
    </tr>
    <tr>
      <td><strong>AT4</strong></td>
      <td>Integrity Failback Gate</td>
      <td>Region A restarted; held in <code>MAINT</code> until fast listing parity matches; failback to <code>HEALTHY</code> in <strong>1.2s</strong>.</td>
      <td><span class="pass-badge">PASS</span></td>
      <td><code>m3-failback-rpo.md</code><span class="source-tag">Source: docs/04-test-evidence/</span></td>
    </tr>
    <tr>
      <td><strong>AT5</strong></td>
      <td>GitOps Deploy & Auto-Rollback</td>
      <td>Valid config deployed in <strong>8.0s</strong>; faulty config detected by health gate and rolled back in <strong>19.0s</strong>.</td>
      <td><span class="pass-badge">PASS</span></td>
      <td><code>m4-gitops.md</code><span class="source-tag">Source: docs/04-test-evidence/</span></td>
    </tr>
    <tr>
      <td><strong>AT6</strong></td>
      <td>Resilience Under Burst & Freeze</td>
      <td>Crash RTO median <strong>4732 ms</strong>; pause RTO median <strong>7192 ms</strong>; 0 missing writes across all iterations.</td>
      <td><span class="pass-badge">PASS</span></td>
      <td><code>m5-chaos.md</code><span class="source-tag">Source: docs/04-test-evidence/</span></td>
    </tr>
    <tr>
      <td><strong>AT7</strong></td>
      <td>Degraded Network & Partition</td>
      <td>500ms latency replication lag: <strong>3.05s</strong>; one-way partition catch-up: <strong>4.91s</strong>; Last-Write-Wins verified.</td>
      <td><span class="pass-badge">PASS</span></td>
      <td><code>m5-chaos.md</code><span class="source-tag">Source: docs/04-test-evidence/</span></td>
    </tr>
  </tbody>
</table>

<div class="img-box">
  <img src="{img_banner}" alt="Demo Banner Exit 0">
  <div class="img-caption">Terminal output rendered from demo/demo-run.log, 10 November 2026</div>
</div>

<h2>Independent Recovery Point Objective (RPO) Measurement</h2>
<ul>
  <li><strong>Graceful Stop RPO:</strong> 12 writes acknowledged; 12 writes found on Region B upon failover (<code>missing: []</code>, <code>rpo_objects: 0</code>). Stop duration: 8156 ms.</li>
  <li><strong>Abrupt SIGKILL RPO:</strong> 12 writes acknowledged; 12 writes found on Region B upon failover (<code>missing: []</code>, <code>rpo_objects: 0</code>). Kill duration: 8641 ms.</li>
  <li><strong>Source Citation:</strong> <code>docs/04-test-evidence/m3-failback-rpo.md</code> and <code>demo/demo-run.log</code>.</li>
</ul>
<div class="page-break"></div>

<!-- ================= PAGE 11: CHAOS SUITE ================= -->
<h1>10. Chaos Engineering Resilience Suite (E1–E5)</h1>

<p>
The chaos engineering framework (<code>chaos/runner.py</code>) validates platform behavior against explicit, falsifiable hypotheses under real concurrent client write workloads (30–42 req/s):
</p>

<div class="img-box">
  <img src="{img_chaos_table}" alt="Chaos Summary Table">
  <div class="img-caption">Terminal output rendered from docs/04-test-evidence/m5-chaos.md, 10 November 2026</div>
</div>

<div class="img-box">
  <img src="{img_chart}" alt="RTO Chart Comparison">
  <div class="img-caption">Terminal output rendered from docs/04-test-evidence/m5-chaos.md, 10 November 2026</div>
</div>

<div class="img-box">
  <img src="{img_e4}" alt="E4 Partition and LWW Conflict">
  <div class="img-caption">Terminal output rendered from docs/04-test-evidence/m5-chaos.md, 10 November 2026</div>
</div>
<div class="page-break"></div>

<!-- ================= PAGE 12: DEEP AUDIT PROOF ================= -->
<h1>11. Cryptographic Deep Audit & Demo Timings</h1>

<h2>Byte-for-Byte Cryptographic Payload Verification</h2>
<p>
To provide undeniable mathematical proof that no silent data corruption (bit rot) or object drift occurred across any of the disaster recovery drills, failover events, or chaos experiments, I executed a deep cryptographic audit across the entire storage estate:
</p>

<div class="img-box">
  <img src="{img_audit}" alt="Deep Audit Output">
  <div class="img-caption">Terminal output rendered from controller/proof.py compare --deep, 10 November 2026</div>
</div>

<div class="callout">
  <strong>Audit Findings:</strong><br>
  - Total Objects in Region A: <strong>153</strong> (across <code>demo</code> and <code>rpo</code> buckets)<br>
  - Total Objects in Region B: <strong>153</strong><br>
  - Payload Hashes Computed: <strong>153</strong> full SHA-256 digests streamed from both endpoints<br>
  - Mismatches or Corrupted Objects: <strong>0</strong> (<code>different: []</code>)<br>
  - Result: <strong>100% Cryptographic Parity Verified</strong>.<br>
  - Source: <code>controller/proof.py compare --deep</code> and <code>docs/04-test-evidence/m6-deep-audit.md</code>.
</div>

<h2>Consecutive <code>make demo</code> Execution Timings</h2>
<table>
  <thead>
    <tr>
      <th>Execution Run</th>
      <th>Duration</th>
      <th>Exit Code</th>
      <th>Failover RTO</th>
      <th>Fast Gate Parity</th>
      <th>GitOps Auto-Rollback</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><strong>Run 1</strong></td>
      <td>1m 49s</td>
      <td>0</td>
      <td>4011 ms</td>
      <td>MATCH (151 objects)</td>
      <td>PASS (19.0s)</td>
    </tr>
    <tr>
      <td><strong>Run 2</strong></td>
      <td>1m 54s</td>
      <td>0</td>
      <td>3982 ms</td>
      <td>MATCH (151 objects)</td>
      <td>PASS (19.0s)</td>
    </tr>
    <tr>
      <td><strong>Run 3 (demo-run.log)</strong></td>
      <td>1m 51s</td>
      <td>0</td>
      <td>4011 ms</td>
      <td>MATCH (151 objects)</td>
      <td>PASS (19.0s)</td>
    </tr>
  </tbody>
</table>
<div class="page-break"></div>

<!-- ================= PAGE 13: LIMITATIONS ================= -->
<h1>12. Mandatory Scope & System Limitations</h1>

<p>
To maintain rigorous engineering honesty, the following constraints and physical boundaries of this platform are explicitly documented:
</p>

<h2>1. Eventual Consistency & Last-Write-Wins (LWW)</h2>
<p>
MinIO site replication is an active-active, eventually consistent distributed storage engine. In scenarios where an un-fenced network partition occurs and concurrent dual-primary writes are issued to identical object keys, MinIO resolves the conflict strictly by object timestamp (Last-Write-Wins). The older version is silently overwritten. Application-level semantic conflict merging is not supported.
</p>

<h2>2. RPO Measurement Scope & Disk-Loss Boundary</h2>
<p>
The measured RPO of <code>0</code> missing objects was empirically validated under workloads of approximately 35–42 writes/sec with small objects (4 KB – 20 KB) and with <strong>surviving disk volumes</strong>. This demonstrates replication throughput and socket reliability under test conditions, not a mathematical zero-data-loss guarantee. Physical storage destruction or sudden disk wipe (catastrophic disk destruction) was not tested.
</p>

<h2>3. RTO Includes Client Timeouts</h2>
<p>
During gray failures (such as <code>docker pause</code> in Experiment E2), RTO measurements include the client HTTP request timeout (3.5 seconds) in addition to HAProxy's 2-second connection timeout and redispatch window, resulting in measured RTO clustering around ~7.2 seconds.
</p>

<h2>4. Fast Failback Gate vs. Deep Cryptographic Audit</h2>
<p>
The automated failback gate (<code>compare_sites</code> in routine operation) evaluates object listings, sizes, and ETags only (<code>sha256_checked: 0</code>) to achieve sub-2-second failback evaluation (1.2s across 140+ objects). Full cryptographic payload streaming and SHA-256 digest computation across every stored object is performed separately via <code>make audit</code> / <code>--deep</code> (<code>sha256_checked: 153</code>).
</p>

<h2>5. Experiment E3 Run-to-Run Noise</h2>
<p>
In Experiment E3, measured replication lag under combined latency + bandwidth (2.21s) was lower than the latency-only scenario (3.05s). These differences were within run-to-run timing noise, and the specific underlying cause was not investigated. No trend or causal relationship is claimed.
</p>

<h2>6. Asymmetric One-Way Partition (E4 Toxiproxy Placement)</h2>
<p>
Toxiproxy sits specifically on the <code>site-a -&gt; site-b</code> replication path (port 9002). In Experiment E4, timeout toxics severed traffic from <code>site-a</code> to <code>site-b</code> only. <code>site-b</code>'s replication endpoint to <code>site-a</code> remained direct (<code>http://minio-a:9000</code>), meaning writes to <code>site-b</code> continued to reach <code>site-a</code> during the cut. This was a <strong>one-way (asymmetric) partition</strong>, not a complete bidirectional severance.
</p>

<h2>7. Single-Machine Simulation</h2>
<p>
Both "regions" execute as Docker containers on a single host Linux kernel. Inter-region WAN characteristics (propagation delay, packet loss, bandwidth caps) were simulated programmatically via Toxiproxy rather than traversing actual cross-continental fiber.
</p>
<div class="page-break"></div>

<!-- ================= PAGE 14: CHALLENGES & LEARNINGS ================= -->
<h1>13. Engineering Challenges & What I Learned</h1>

<h2>Real Bugs Found and Corrected</h2>
<ul>
  <li><strong>First-Run Replication Bootstrap Timing:</strong> In Milestone M0, initial site replication configuration failed intermittently because <code>minio-a</code> attempted to join <code>minio-b</code> before MinIO's internal server pool was fully initialized. Fixed by implementing an active polling readiness loop that verifies HTTP 200 on both backends before issuing <code>mc admin replicate add</code>.</li>
  <li><strong>Throwaway Test Project-Name Collisions:</strong> When testing isolated volume lifecycle scripts, running <code>docker compose</code> without explicit project scoping reused the default project network and named volumes. Resolved by enforcing strict <code>COMPOSE_PROJECT_NAME=setu-fresh-test</code> and isolated volume naming.</li>
  <li><strong>Demo Pipeline Exit Code Masking:</strong> When piping terminal output through <code>tee</code> in <code>scripts/demo.sh</code>, bash masked non-zero exit codes from failed sub-steps. Fixed by capturing <code>${{PIPESTATUS[0]}}</code> and asserting positive exit status on every critical gate.</li>
  <li><strong>Gray Failure Client Socket Deadlock:</strong> Paused containers do not emit TCP RST packets. Client workers with short timeouts deadlocked waiting on stale sockets. Resolved by configuring explicit 3.5s client timeouts and tuning HAProxy connect timeouts.</li>
  <li><strong>Correction of Overstated Early Metrics:</strong> In exploratory chaos runs, Experiment E2's hypothesis claimed pause RTO would exceed kill RTO, but measured values varied. Rather than forcing hardcoded pass criteria, the evaluation harness was refactored so that every assertion evaluates real, explicit clauses that can fail, ensuring honest scientific reporting.</li>
</ul>

<h2>Core Systems Engineering Takeaways</h2>
<ol style="margin: 0; padding-left: 18px;">
  <li><strong>Crash vs. Gray Failure Semantics:</strong> A hard process termination (SIGKILL) is clean from a networking standpoint because the operating system kernel immediately tears down open file descriptors and emits TCP RST packets. A gray failure (socket freeze / process freeze) is far more hazardous in distributed systems because sockets remain in <code>ESTABLISHED</code> state, forcing reliance on application and proxy connect timeouts.</li>
  <li><strong>Ingress Fencing is Essential:</strong> Restoring a recovered primary without administrative ingress fencing creates severe split-brain hazards. Fencing primary in HAProxy (<code>MAINT</code>) until cryptographic parity is proven is the only safe method to prevent silent data overwrite.</li>
  <li><strong>Targeted GitOps Re-creation:</strong> In infrastructure managing persistent state, blanket <code>--force-recreate</code> must never be used. Computing diffs to recreate only modified stateless containers (e.g. gateway) prevents unnecessary storage outages.</li>
  <li><strong>User-Space Fault Injection:</strong> Programmatic TCP proxying (via Toxiproxy) provides far greater portability and safety than host kernel manipulation (<code>tc netem</code>), avoiding root requirements and privilege leaks.</li>
</ol>
<div class="page-break"></div>

<!-- ================= PAGE 15: FUTURE WORK & DEMO ================= -->
<h1>14. Future Directions & Demonstration Materials</h1>

<h2>Future Architectural Extensions</h2>
<ul>
  <li><strong>Catastrophic Disk-Loss Testing:</strong> Extending the chaos suite to simulate unrecoverable physical disk destruction (purging <code>minio_a_data</code> entirely) and measuring recovery time from cold backup volumes.</li>
  <li><strong>Multi-Host Bare-Metal Deployment:</strong> Migrating the platform from a single WSL2 host to two physically separated Linux servers connected via a real wide-area network (e.g., WireGuard VPN over internet).</li>
  <li><strong>Kubernetes Operator Variant:</strong> Packaging the DR state machine and GitOps reconciler as a custom Kubernetes Operator with Custom Resource Definitions (CRDs) for enterprise adoption.</li>
  <li><strong>Prometheus & OpenTelemetry Observability:</strong> Integrating Prometheus metrics scraping and Grafana dashboards for real-time visualization of replication lag, HAProxy queue depth, and failover latency.</li>
</ul>

<h2>Demonstration Materials & Live Evaluation Protocol</h2>
<div class="callout">
  <strong>Live Demonstration Notice:</strong><br>
  Live demonstration will be conducted during project evaluation.<br>
  A recorded terminal run of <code>make demo</code> (concluding with exit code 0) is included directly in the submission package as <code>demo/demo-run.log</code>.
</div>

<p>
For evaluators inspecting the terminal run log, the table below maps the 10 sequential demonstration steps to the real execution log:
</p>

<table>
  <thead>
    <tr>
      <th style="width: 15%;">Step #</th>
      <th style="width: 30%;">Demonstration Action</th>
      <th style="width: 35%;">Observed Behavior in Log</th>
      <th style="width: 20%;">Timestamp / Duration</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><strong>Step 1</strong></td>
      <td>Stack Health Verification</td>
      <td>Region A, Region B, and Gateway all report UP (HTTP 200).</td>
      <td>T+0s (Immediate)</td>
    </tr>
    <tr>
      <td><strong>Step 2</strong></td>
      <td>Normal Operation Write</td>
      <td>Write to GW; read from B; SHA-256 match confirmed.</td>
      <td>T+8s</td>
    </tr>
    <tr>
      <td><strong>Step 3</strong></td>
      <td>Start DR Controller</td>
      <td>Controller initializes in HEALTHY state (PID 72085).</td>
      <td>T+11s</td>
    </tr>
    <tr>
      <td><strong>Step 4</strong></td>
      <td>Inject Disaster (Kill A)</td>
      <td>Region A stopped; HAProxy redispatches to Region B.</td>
      <td>T+13s</td>
    </tr>
    <tr>
      <td><strong>Step 5</strong></td>
      <td>Failover & Fencing</td>
      <td>Controller enters FAILOVER; fences A (MAINT); RTO: <strong>4011 ms</strong>.</td>
      <td>T+18s</td>
    </tr>
    <tr>
      <td><strong>Step 6</strong></td>
      <td>Recovery & Failback Gate</td>
      <td>Region A restarted; held in MAINT; synced; un-fenced (UP).</td>
      <td>T+32s (14s sync)</td>
    </tr>
    <tr>
      <td><strong>Step 7 & 8</strong></td>
      <td>Independent RPO Measure</td>
      <td>Numbered write stream under stop & kill: <strong>0 missing</strong>.</td>
      <td>T+45s</td>
    </tr>
    <tr>
      <td><strong>Step 9</strong></td>
      <td>Ephemeral Bucket Cleanup</td>
      <td>Temporary RPO test buckets cleanly deleted.</td>
      <td>T+52s</td>
    </tr>
    <tr>
      <td><strong>Step 10</strong></td>
      <td>GitOps Deploy & Rollback</td>
      <td>Valid commit in 8s; bad commit rolled back in <strong>19s</strong>.</td>
      <td>T+1m 15s – 1m 51s</td>
    </tr>
  </tbody>
</table>
<div class="page-break"></div>

<!-- ================= PAGE 16: APPENDIX ================= -->
<h1>15. Appendix: Command Cheat Sheet & Glossary</h1>

<h2>Operator Command Cheat Sheet</h2>
<table>
  <thead>
    <tr>
      <th style="width: 25%;">Command</th>
      <th style="width: 45%;">Operation Performed</th>
      <th style="width: 30%;">Target Outcome</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>make doctor</code></td>
      <td>Validates system dependencies, Docker, Python 3, and memory allocation.</td>
      <td>Pre-flight validation (0 errors).</td>
    </tr>
    <tr>
      <td><code>make up</code></td>
      <td>Starts all platform containers (minio-a, minio-b, gateway, toxiproxy, monitor).</td>
      <td>Multi-region stack UP.</td>
    </tr>
    <tr>
      <td><code>make health</code></td>
      <td>Queries HTTP 200 health status across all endpoints.</td>
      <td>Reports status of all nodes.</td>
    </tr>
    <tr>
      <td><code>make demo</code></td>
      <td>Executes complete 10-step end-to-end self-healing demonstration.</td>
      <td>Proves AT1–AT5 in ~1m50s (Exit code 0).</td>
    </tr>
    <tr>
      <td><code>make chaos</code></td>
      <td>Executes automated 5-experiment chaos engineering resilience suite.</td>
      <td>Generates <code>m5-chaos.md</code>.</td>
    </tr>
    <tr>
      <td><code>make audit</code></td>
      <td>Executes deep cryptographic SHA-256 payload audit across all objects.</td>
      <td>Outputs JSON confirmation of parity.</td>
    </tr>
    <tr>
      <td><code>make package</code></td>
      <td>Builds final submission directory and verified archive.</td>
      <td>Produces verified <code>.zip</code> (&lt;20 MB).</td>
    </tr>
    <tr>
      <td><code>make down</code></td>
      <td>Stops platform containers while safely preserving volume data.</td>
      <td>Clean stack shutdown.</td>
    </tr>
  </tbody>
</table>

<h2>Technical Glossary</h2>
<ul>
  <li><strong>RTO (Recovery Time Objective):</strong> The elapsed duration between primary failure detection and the first successful write acknowledged on the standby region.</li>
  <li><strong>RPO (Recovery Point Objective):</strong> The quantity of data lost during disaster, measured here as acknowledged client writes missing from the backup region.</li>
  <li><strong>Failback:</strong> The controlled process of restoring primary traffic to Region A after resynchronization is mathematically confirmed.</li>
  <li><strong>Administrative Fencing:</strong> Forcibly locking a failed or recovering node into <code>MAINT</code> state on HAProxy's admin socket to prevent split-brain dual-primary writing.</li>
  <li><strong>Site Replication:</strong> MinIO's active-active bucket and object synchronization mechanism operating over S3 HTTP APIs.</li>
  <li><strong>GitOps Continuous Delivery:</strong> Declarative infrastructure deployment where git commits drive container convergence with automated pre-flight checks and rollback.</li>
  <li><strong>Chaos Engineering:</strong> The discipline of experimenting on a distributed system to build confidence in its capability to withstand turbulent conditions.</li>
</ul>

<div class="callout">
  <strong>Technical Defense Reference:</strong><br>
  For detailed technical answers to 15 key architectural and distributed systems questions (including split-brain prevention, Nginx vs HAProxy tradeoffs, Toxiproxy user-space mechanics, and SigV4 signer architecture), refer to <code>docs/06-reviewer-qa.md</code>.
</div>

</body>
</html>
"""

with open(html_path, "w", encoding="utf-8") as f:
    f.write(html_content)

print(f"Updated HTML report with embedded images: {html_path} ({os.path.getsize(html_path)} bytes)")

# Convert to PDF using Edge headless
edge_exe = "/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"
if not os.path.exists(edge_exe):
    edge_exe = "/mnt/c/Program Files/Microsoft/Edge/Application/msedge.exe"

w_html = subprocess.check_output(["wslpath", "-w", html_path], text=True).strip()
w_pdf = subprocess.check_output(["wslpath", "-w", pdf_path], text=True).strip()

cmd = [
    edge_exe,
    "--headless=new",
    "--disable-gpu",
    "--no-pdf-header-footer",
    f"--print-to-pdf={w_pdf}",
    w_html
]
subprocess.check_call(cmd)

pdf_size = os.path.getsize(pdf_path)
print(f"Generated PDF Report: {pdf_path} ({pdf_size} bytes)")

# Check page count
with open(pdf_path, "rb") as f:
    pdf_bytes = f.read()

pages = re.findall(rb"/Type\s*/Page\b", pdf_bytes)
print(f"Total Page Count: {len(pages)}")

# Check placeholders
placeholders = re.findall(r"(TODO|placeholder|\[SETU_|FIXME)", html_content, re.IGNORECASE)
print(f"Placeholder matches in HTML: {len(placeholders)}")

if len(pages) < 12 or len(pages) > 18:
    print(f"ERROR: Page count {len(pages)} outside 12-18 page target range!")
    sys.exit(1)

if len(placeholders) > 0:
    print(f"ERROR: Found placeholders: {placeholders}")
    sys.exit(1)

print("=== PDF REPORT BUILD SUCCESS: In range (12-18 pages), zero placeholders, real inline images! ===")

