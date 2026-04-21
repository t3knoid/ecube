import { describe, expect, it } from 'vitest'

import { classifySourcePathOverlap, resolveMountedSourcePath } from '@/utils/pathOverlap.js'

describe('pathOverlap', () => {
  it('resolves root-relative source paths within the selected mount', () => {
    expect(resolveMountedSourcePath('/Evidence1/SubFolder', '/nfs/project-001')).toBe('/nfs/project-001/Evidence1/SubFolder')
    expect(resolveMountedSourcePath('/', '/nfs/project-001')).toBe('/nfs/project-001')
  })

  it('classifies exact overlaps', () => {
    expect(classifySourcePathOverlap('/nfs/project-001/Evidence1/', '/nfs/project-001/Evidence1')).toBe('exact')
  })

  it('classifies ancestor overlaps', () => {
    expect(classifySourcePathOverlap('/nfs/project-001/Evidence1', '/nfs/project-001')).toBe('ancestor')
  })

  it('classifies descendant overlaps', () => {
    expect(classifySourcePathOverlap('/nfs/project-001', '/nfs/project-001/Evidence1/SubFolder')).toBe('descendant')
  })

  it('respects component boundaries', () => {
    expect(classifySourcePathOverlap('/nfs/project-001/Evidence1', '/nfs/project-001/Evidence10')).toBe('none')
  })
})