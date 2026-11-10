# M6 Test Evidence: Full Cryptographic Deep Audit (`--deep`)

**Execution Timestamp**: `2026-11-10 11:59:02 UTC`  
**Command**: `python3 controller/proof.py compare --deep` (`make audit`)  
**Mode**: `deep` (full byte-for-byte SHA-256 computation of every stored object payload)  

---

## 1. Deep Audit Execution Output

```json
{
  "match": true,
  "count_a": 149,
  "count_b": 149,
  "only_a": [],
  "only_b": [],
  "different": [],
  "sha256_checked": 149,
  "mode": "deep"
}
```

---

## 2. Integrity Analysis & Verification

1. **Object Population**: Exactly 149 objects exist in `site-a` (`demo` and `rpo` buckets combined), and exactly 149 objects exist in `site-b`.
2. **Cryptographic Verification**: Unlike the routine fast-path failback gate (which checks object listings, sizes, and ETags with `sha256_checked: 0`), this deep audit streamed the raw bytes of all 149 objects from both regions (`sha256_checked: 149`) and computed full SHA-256 digests.
3. **Parity Proof**:
   - `only_a`: `[]` (0 objects missing on Region B)
   - `only_b`: `[]` (0 objects missing on Region A)
   - `different`: `[]` (0 corrupted or divergent payloads)
   - `match`: `true`
4. **Conclusion**: Cryptographic proof confirms 100% byte-for-byte parity across both storage volumes (`minio_a_data` and `minio_b_data`) with zero silent data corruption (bit rot) after all failover, failback, GitOps, and chaos experiments.
