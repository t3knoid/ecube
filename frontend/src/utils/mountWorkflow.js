export const MOUNT_WORKFLOW_BUCKETS = Object.freeze({
  UNASSIGNED: 'UNASSIGNED',
  ASSIGNED: 'ASSIGNED',
  ACTIVE: 'ACTIVE',
  BLOCKED: 'BLOCKED',
  CUSTODY_PENDING: 'CUSTODY_PENDING',
  COMPLETED: 'COMPLETED',
  UNAVAILABLE: 'UNAVAILABLE',
})

export function classifyMountWorkflowBucket(mount) {
  const status = String(mount?.related_job?.status || '').toUpperCase()
  const custodyStatus = String(mount?.related_job?.custody_status || 'STATUS_UNAVAILABLE').toUpperCase()

  if (!status || status === 'STATUS_UNAVAILABLE') {
    return MOUNT_WORKFLOW_BUCKETS.UNAVAILABLE
  }

  if (status === 'NO_RELATED_JOB') {
    return MOUNT_WORKFLOW_BUCKETS.UNASSIGNED
  }

  if (status === 'PENDING') {
    return MOUNT_WORKFLOW_BUCKETS.ASSIGNED
  }

  if (['PREPARING', 'RUNNING', 'PAUSING', 'VERIFYING'].includes(status)) {
    return MOUNT_WORKFLOW_BUCKETS.ACTIVE
  }

  if (['PAUSED', 'FAILED'].includes(status)) {
    return MOUNT_WORKFLOW_BUCKETS.BLOCKED
  }

  if (['COMPLETED', 'ARCHIVED'].includes(status)) {
    if (custodyStatus === 'HANDOFF_RECORDED') {
      return MOUNT_WORKFLOW_BUCKETS.COMPLETED
    }
    if (custodyStatus === 'PENDING_HANDOFF') {
      return MOUNT_WORKFLOW_BUCKETS.CUSTODY_PENDING
    }
    return MOUNT_WORKFLOW_BUCKETS.UNAVAILABLE
  }

  return MOUNT_WORKFLOW_BUCKETS.UNAVAILABLE
}

export function buildMountWorkflowCounts(mounts) {
  const counts = {
    [MOUNT_WORKFLOW_BUCKETS.UNASSIGNED]: 0,
    [MOUNT_WORKFLOW_BUCKETS.ASSIGNED]: 0,
    [MOUNT_WORKFLOW_BUCKETS.ACTIVE]: 0,
    [MOUNT_WORKFLOW_BUCKETS.BLOCKED]: 0,
    [MOUNT_WORKFLOW_BUCKETS.CUSTODY_PENDING]: 0,
    [MOUNT_WORKFLOW_BUCKETS.COMPLETED]: 0,
    [MOUNT_WORKFLOW_BUCKETS.UNAVAILABLE]: 0,
  }

  for (const mount of mounts || []) {
    counts[classifyMountWorkflowBucket(mount)] += 1
  }

  return counts
}