# 21. Copy Workload Profile Decision Logic

| Field | Value |
|---|---|
| Title | Copy Workload Profile Decision Logic |
| Purpose | Describes the current production logic that classifies startup-analysis results into a workload profile and the tuning bundle each profile applies. |
| Updated on | 05/29/26 |
| Audience | Engineers, implementers, maintainers, performance reviewers, and operators who need to understand why ECUBE recommends a given profile. |

## 21.1 Scope

This document describes the current behavior implemented in [app/services/workload_profiles.py](../../app/services/workload_profiles.py), the startup-analysis summary path in [app/services/job_service.py](../../app/services/job_service.py), and the matching Configuration-page profile shortcuts in [frontend/src/components/configuration/ConfigurationEditor.vue](../../frontend/src/components/configuration/ConfigurationEditor.vue).

It documents the production decision logic that ECUBE executes today. It does not describe future tuning experiments or alternative heuristic proposals.

## 21.2 Summary

- ECUBE classifies a job's startup-analysis file set into one of four workload profiles: `small_files`, `mixed`, `large_files`, or `greedy`.
- The recommendation is deterministic. The same persisted startup-analysis rows always produce the same recommendation.
- The recommendation uses only file-size distribution data derived from persisted startup-analysis rows.
- The recommendation does not inspect file extensions, directory depth, media type, source protocol, or historical throughput.
- The selected profile maps to a fixed tuning bundle for `copy_chunk_size_bytes`, `copy_progress_flush_bytes`, `copy_default_thread_count`, and `copy_file_fsync_enabled`.

## 21.3 Source Of Truth

The workload-profile logic has two authoritative implementation surfaces:

- Backend recommendation and profile values in [app/services/workload_profiles.py](../../app/services/workload_profiles.py)
- Matching UI profile shortcuts in [frontend/src/components/configuration/ConfigurationEditor.vue](../../frontend/src/components/configuration/ConfigurationEditor.vue)

Startup analysis obtains the file-size summary through [app/services/job_service.py](../../app/services/job_service.py), which asks the repository layer to count files by size bucket using the same backend thresholds.

## 21.4 Size Buckets

Startup-analysis recommendation begins by assigning each analyzed file to one of three size buckets:

| Bucket | Rule |
|---|---|
| Small | file size `<= 64 KiB` |
| Medium | file size `> 64 KiB` and `< 8 MiB` |
| Large | file size `>= 8 MiB` |

These thresholds are defined in [app/services/workload_profiles.py](../../app/services/workload_profiles.py) as:

- `SMALL_FILE_MAX_BYTES = 64 * 1024`
- `LARGE_FILE_MIN_BYTES = 8 * 1024 * 1024`

## 21.5 Derived Summary Values

After counting files in each bucket, ECUBE builds a summary with these derived values:

- `small_files`
- `medium_files`
- `large_files`
- `small_files_percent`
- `medium_files_percent`
- `large_files_percent`
- `average_file_size_bytes`
- `total_files`
- `total_bytes`

The percentages are calculated against `total_files` and rounded to one decimal place. `average_file_size_bytes` uses integer division of `total_bytes / total_files`.

If `total_files <= 0`, ECUBE returns a zeroed summary and no recommendation.

## 21.6 Recommendation Decision Order

The recommendation is evaluated in a fixed top-to-bottom order. The first matching rule wins.

| Order | Condition | Result |
|---|---|---|
| 1 | `small_files_percent >= 60.0` | `small_files` |
| 2 | `large_files_percent >= 60.0` | `large_files` |
| 3 | `large_files_percent >= 25.0` and `small_files_percent <= 20.0` and `average_file_size_bytes >= 16 MiB` | `greedy` |
| 4 | anything else with at least one analyzed file | `mixed` |

Equivalent pseudocode:

```text
if total_files <= 0:
    return none
if small_ratio >= 0.60:
    return small_files
if large_ratio >= 0.60:
    return large_files
if large_ratio >= 0.25 and small_ratio <= 0.20 and average_size >= 16 MiB:
    return greedy
return mixed
```

## 21.7 Why Evaluation Order Matters

The recommendation order is intentional.

- `small_files` wins before any large-file-oriented profile because a workload dominated by small files is primarily constrained by per-file overhead.
- `large_files` wins before `greedy` when the file set is overwhelmingly large-file-heavy.
- `greedy` is reserved for workloads that are substantially large-file-oriented without also being polluted by many small files, and where the average file size is high enough to justify the most aggressive chunk and flush thresholds.
- `mixed` is the fallback for workloads that do not strongly match any specialized rule.

This means `greedy` is not the default large-file recommendation. It is a narrower large-file-oriented classification that requires all three of its gating conditions.

## 21.8 Profile Bundles

Each recommendation maps to a fixed tuning bundle.

| Profile | Chunk Size | Progress Flush Threshold | Default Thread Count | Per-file `fsync` |
|---|---|---|---|---|
| `small_files` | `1 MiB` | `32 MiB` | `12` | `false` |
| `mixed` | `4 MiB` | `64 MiB` | `12` | `false` |
| `large_files` | `8 MiB` | `128 MiB` | `6` | `false` |
| `greedy` | `16 MiB` | `256 MiB` | `12` | `false` |

These values are currently identical between the backend profile map and the Configuration-page shortcut buttons.

## 21.9 Where The Recommendation Appears

When startup analysis has enough persisted rows to build a summary, ECUBE exposes:

- the size-distribution summary on Job Detail
- the `startup_analysis_recommended_workload_profile` field on job responses
- an `Apply Recommended Profile` action on Job Detail
- an `Auto-apply startup analysis profile` checkbox in the Create Job workflow

The Configuration page also exposes manual profile shortcut buttons for the same four tuning bundles. Those buttons apply the bundle immediately to the editable configuration form, independent of startup analysis.

## 21.10 Auto-Apply Guardrails

Auto-apply after startup analysis is intentionally conservative.

- ECUBE only auto-applies the recommended profile when the job has `startup_analysis_auto_apply_recommended_profile = true`.
- ECUBE does not auto-apply when the job already has explicit per-job copy-tuning overrides.
- Explicit overrides are detected by comparing the job's `thread_count`, `copy_chunk_size_bytes`, `copy_progress_flush_bytes`, and `copy_file_fsync_enabled` against the current configuration defaults.

This preserves operator intent. If an operator already changed job-specific tuning away from the defaults, startup analysis will still compute and display the recommendation, but ECUBE will not overwrite those explicit per-job values automatically.

## 21.11 Inputs That Do Not Affect The Decision

The current recommendation logic does not consider:

- source or destination drive type
- observed throughput or latency
- number of directories
- path depth or file-name shape
- file extension or MIME class
- hash cost by content type
- current CPU load, memory pressure, or device queue depth
- whether separate hashing is enabled

Those factors may still affect real-world performance, but they are not part of the current recommendation heuristic.

## 21.12 Operational Consequences

Operators and reviewers should interpret the recommendation as a deterministic tuning heuristic, not as a live benchmark result.

- It reflects the analyzed file-size distribution, not measured copy performance.
- Re-running startup analysis on the same persisted file set should produce the same recommendation.
- If the source tree changes enough to shift the size distribution, the recommendation can change on the next analysis run.
- Manual configuration-page profile shortcuts can intentionally diverge from the startup-analysis recommendation.

## 21.13 Maintenance Expectations

Any future change to this logic should update all of the following together:

- [app/services/workload_profiles.py](../../app/services/workload_profiles.py)
- [frontend/src/components/configuration/ConfigurationEditor.vue](../../frontend/src/components/configuration/ConfigurationEditor.vue) when shortcut bundle values change
- API and user-facing docs that describe recommendation semantics
- this design document

Tests should continue to cover both recommendation classification and profile-application behavior so the docs remain aligned with the implementation.