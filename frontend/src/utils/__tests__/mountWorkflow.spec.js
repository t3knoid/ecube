import { describe, expect, it } from 'vitest'

import { buildMountWorkflowCounts, classifyMountWorkflowBucket, MOUNT_WORKFLOW_BUCKETS } from '../mountWorkflow.js'

describe('mount workflow helpers', () => {
  it('separates active, blocked, custody-pending, completed, and unavailable buckets', () => {
    expect(classifyMountWorkflowBucket({ related_job: { status: 'NO_RELATED_JOB', custody_status: 'NO_RELATED_JOB' } })).toBe(MOUNT_WORKFLOW_BUCKETS.UNASSIGNED)
    expect(classifyMountWorkflowBucket({ related_job: { status: 'PENDING', custody_status: 'PENDING_HANDOFF' } })).toBe(MOUNT_WORKFLOW_BUCKETS.ASSIGNED)
    expect(classifyMountWorkflowBucket({ related_job: { status: 'PREPARING', custody_status: 'PENDING_HANDOFF' } })).toBe(MOUNT_WORKFLOW_BUCKETS.ACTIVE)
    expect(classifyMountWorkflowBucket({ related_job: { status: 'RUNNING', custody_status: 'PENDING_HANDOFF' } })).toBe(MOUNT_WORKFLOW_BUCKETS.ACTIVE)
    expect(classifyMountWorkflowBucket({ related_job: { status: 'FAILED', custody_status: 'PENDING_HANDOFF' } })).toBe(MOUNT_WORKFLOW_BUCKETS.BLOCKED)
    expect(classifyMountWorkflowBucket({ related_job: { status: 'COMPLETED', custody_status: 'PENDING_HANDOFF' } })).toBe(MOUNT_WORKFLOW_BUCKETS.CUSTODY_PENDING)
    expect(classifyMountWorkflowBucket({ related_job: { status: 'ARCHIVED', custody_status: 'HANDOFF_RECORDED' } })).toBe(MOUNT_WORKFLOW_BUCKETS.COMPLETED)
    expect(classifyMountWorkflowBucket({ related_job: { status: 'STATUS_UNAVAILABLE', custody_status: 'STATUS_UNAVAILABLE' } })).toBe(MOUNT_WORKFLOW_BUCKETS.UNAVAILABLE)
  })

  it('counts completed and archived pending-handoff mounts in the custody-pending bucket', () => {
    expect(buildMountWorkflowCounts([
      { related_job: { status: 'COMPLETED', custody_status: 'PENDING_HANDOFF' } },
      { related_job: { status: 'ARCHIVED', custody_status: 'PENDING_HANDOFF' } },
      { related_job: { status: 'COMPLETED', custody_status: 'HANDOFF_RECORDED' } },
    ])).toEqual({
      [MOUNT_WORKFLOW_BUCKETS.UNASSIGNED]: 0,
      [MOUNT_WORKFLOW_BUCKETS.ASSIGNED]: 0,
      [MOUNT_WORKFLOW_BUCKETS.ACTIVE]: 0,
      [MOUNT_WORKFLOW_BUCKETS.BLOCKED]: 0,
      [MOUNT_WORKFLOW_BUCKETS.CUSTODY_PENDING]: 2,
      [MOUNT_WORKFLOW_BUCKETS.COMPLETED]: 1,
      [MOUNT_WORKFLOW_BUCKETS.UNAVAILABLE]: 0,
    })
  })
})