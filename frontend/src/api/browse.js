import apiClient from './client.js'
import { toData } from './data.js'
import { API_BASE } from '@/constants/routes.js'

/**
 * Fetch a paginated directory listing for an active mount point.
 *
 * @param {string} path       - The mount root (USB mount_path or network local_mount_point).
 * @param {string} [subdir]   - Relative subdirectory within the mount root (default: root).
 * @param {number} [page]     - Page number, 1-based (default: 1).
 * @param {number} [pageSize] - Entries per page (default: 100, max: 500).
 * @returns {Promise<BrowseResponse>}
 */
export function getDirectory(path, subdir = '', page = 1, pageSize = 100) {
  const params = new URLSearchParams({ path })
  if (subdir) params.set('subdir', subdir)
  params.set('page', String(page))
  params.set('page_size', String(pageSize))
  return toData(apiClient.get(`${API_BASE}/browse?${params.toString()}`))
}
