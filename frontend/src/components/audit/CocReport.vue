<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import StatusBadge from '@/components/common/StatusBadge.vue'
import { asUtcDate } from '@/utils/dateTime.js'

const props = defineProps({
  report: {
    type: Object,
    required: true,
  },
  selectorMode: {
    type: String,
    required: true,
  },
  projectId: {
    type: String,
    default: '',
  },
  generatedAt: {
    type: String,
    required: true,
  },
  generatedBy: {
    type: String,
    default: '',
  },
  manifestTotalsFootnote: {
    type: String,
    required: true,
  },
})

const { t } = useI18n()

const displayedProjectId = computed(() => props.projectId || props.report.project_id || '-')
const deliveryDetails = computed(() => props.report.chain_of_custody_events.find((event) => event.event_type === 'COC_HANDOFF_CONFIRMED')?.details || {})

function formatEventDetails(details) {
  if (!details || typeof details !== 'object' || Array.isArray(details)) return '-'

  const lines = Object.entries(details)
    .filter(([, value]) => value !== null && value !== undefined && value !== '')
    .map(([key, value]) => `${key}: ${typeof value === 'object' ? JSON.stringify(value) : String(value)}`)

  return lines.length ? lines.join('; ') : '-'
}

function manifestPath(value) {
  return typeof value === 'string' && value.trim() ? value : '-'
}
</script>

<template>
  <article class="coc-card coc-print-card">
    <header class="report-header">
      <div>
        <h3>{{ t('audit.cocDriveHeader', { driveId: report.drive_id, driveSn: report.drive_sn }) }}</h3>
        <p class="muted">{{ t('audit.cocReportIntro') }}</p>
      </div>
      <StatusBadge :status="report.custody_complete ? 'COMPLETED' : 'PENDING'" :label="report.custody_complete ? t('audit.custodyComplete') : t('audit.custodyIncomplete')" />
    </header>

    <section class="report-section">
      <h4>{{ t('audit.reportHeaderTitle') }}</h4>
      <dl class="report-grid">
        <div>
          <dt>{{ t('audit.generatedAt') }}</dt>
          <dd>{{ asUtcDate(generatedAt) }}</dd>
        </div>
        <div>
          <dt>{{ t('audit.generatedBy') }}</dt>
          <dd>{{ generatedBy || '-' }}</dd>
        </div>
        <div>
          <dt>{{ t('audit.selectorMode') }}</dt>
          <dd>{{ selectorMode }}</dd>
        </div>
        <div>
          <dt>{{ t('audit.projectBinding') }}</dt>
          <dd>{{ displayedProjectId }}</dd>
        </div>
      </dl>
    </section>

    <section class="report-section">
      <h4>{{ t('audit.driveIdentityTitle') }}</h4>
      <dl class="report-grid">
        <div>
          <dt>{{ t('audit.driveIdLabel') }}</dt>
          <dd>{{ report.drive_id }}</dd>
        </div>
        <div>
          <dt>{{ t('audit.driveSerialLabel') }}</dt>
          <dd>{{ report.drive_sn }}</dd>
        </div>
        <div>
          <dt>{{ t('audit.driveManufacturerLabel') }}</dt>
          <dd>{{ report.drive_manufacturer || '-' }}</dd>
        </div>
        <div>
          <dt>{{ t('audit.driveModelLabel') }}</dt>
          <dd>{{ report.drive_model || '-' }}</dd>
        </div>
        <div>
          <dt>{{ t('audit.projectBinding') }}</dt>
          <dd>{{ report.project_id || '-' }}</dd>
        </div>
      </dl>
    </section>

    <section class="report-section">
      <h4>{{ t('audit.custodyStatusTitle') }}</h4>
      <dl class="report-grid">
        <div>
          <dt>{{ t('audit.statusLabel') }}</dt>
          <dd>{{ report.custody_complete ? t('audit.custodyComplete') : t('audit.custodyIncomplete') }}</dd>
        </div>
        <div>
          <dt>{{ t('audit.deliveryTime') }}</dt>
          <dd>{{ asUtcDate(report.delivery_time) }}</dd>
        </div>
        <div>
          <dt>{{ t('audit.possessor') }}</dt>
          <dd>{{ deliveryDetails.possessor || '-' }}</dd>
        </div>
        <div>
          <dt>{{ t('audit.receivedBy') }}</dt>
          <dd>{{ deliveryDetails.received_by || '-' }}</dd>
        </div>
        <div>
          <dt>{{ t('audit.receiptRef') }}</dt>
          <dd>{{ deliveryDetails.receipt_ref || '-' }}</dd>
        </div>
        <div>
          <dt>{{ t('audit.notes') }}</dt>
          <dd>{{ deliveryDetails.notes || '-' }}</dd>
        </div>
      </dl>
    </section>

    <section class="report-section">
      <h4>{{ t('audit.eventsTimelineTitle') }}</h4>
      <p v-if="!report.chain_of_custody_events.length" class="muted">{{ t('audit.cocEventsEmpty') }}</p>
      <table v-else class="coc-report-table" :aria-label="t('audit.cocEventsTableLabel', { driveId: report.drive_id, driveSn: report.drive_sn })">
        <thead>
          <tr>
            <th>{{ t('audit.sequenceNumber') }}</th>
            <th>{{ t('common.labels.date') }}</th>
            <th>{{ t('auth.username') }}</th>
            <th>{{ t('audit.action') }}</th>
            <th>{{ t('audit.details') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(event, index) in report.chain_of_custody_events" :key="event.event_id">
            <td>{{ index + 1 }}</td>
            <td>{{ asUtcDate(event.timestamp) }}</td>
            <td>{{ event.actor || '-' }}</td>
            <td>{{ event.action }}</td>
            <td>{{ formatEventDetails(event.details) }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section class="report-section">
      <h4>{{ t('audit.manifestSummaryTitle') }}</h4>
      <p v-if="!report.manifest_summary.length" class="muted">{{ t('audit.manifestSummaryEmpty') }}</p>
      <template v-else>
        <table class="coc-report-table" :aria-label="t('audit.manifestSummaryTableLabel', { driveId: report.drive_id, driveSn: report.drive_sn })">
          <thead>
            <tr>
              <th>{{ t('jobs.jobId') }}</th>
              <th>{{ t('jobs.evidence') }}</th>
              <th>{{ t('audit.processorNotes') }}</th>
              <th>{{ t('audit.totalFiles') }}</th>
              <th>{{ t('audit.totalBytes') }}</th>
              <th>{{ t('audit.manifestCount') }}</th>
              <th>{{ t('audit.latestManifestPath') }}</th>
              <th>{{ t('audit.latestManifestFormat') }}</th>
              <th>{{ t('audit.latestManifestCreatedAt') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="manifest in report.manifest_summary" :key="manifest.job_id">
              <td>{{ manifest.job_id }}</td>
              <td>{{ manifest.evidence_number || '-' }}</td>
              <td>{{ manifest.processor_notes || '-' }}</td>
              <td>{{ manifest.total_files }}</td>
              <td>{{ manifest.total_bytes }}</td>
              <td>{{ manifest.manifest_count }}</td>
              <td class="path-cell">{{ manifestPath(manifest.latest_manifest_path) }}</td>
              <td>{{ manifest.latest_manifest_format || '-' }}</td>
              <td>{{ asUtcDate(manifest.latest_manifest_created_at) }}</td>
            </tr>
          </tbody>
        </table>
        <p class="muted footnote">{{ manifestTotalsFootnote }}</p>
      </template>
    </section>

    <section class="report-section attestation-block">
      <h4>{{ t('audit.attestationTitle') }}</h4>
      <p>{{ t('audit.attestationPrintedBy') }}</p>
      <p>{{ t('audit.attestationDate') }}</p>
    </section>
  </article>
</template>

<style scoped>
.coc-card {
  display: grid;
  gap: var(--space-sm);
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius-lg);
  background: var(--color-bg-secondary);
  padding: var(--space-md);
}

.report-header {
  display: flex;
  justify-content: space-between;
  align-items: start;
  gap: var(--space-sm);
}

.report-section {
  display: grid;
  gap: var(--space-xs);
}

.report-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: var(--space-sm);
  margin: 0;
}

.report-grid div {
  display: grid;
  gap: 2px;
}

dt {
  color: var(--color-text-secondary);
  font-size: var(--font-size-xs);
  font-weight: 600;
}

dd {
  margin: 0;
}

.coc-report-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--font-size-xs);
}

.coc-report-table th,
.coc-report-table td {
  text-align: left;
  vertical-align: top;
  padding: var(--space-xs) var(--space-sm);
  border-bottom: 1px solid var(--color-border);
}

.coc-report-table th {
  color: var(--color-text-secondary);
  font-weight: 600;
}

.path-cell {
  word-break: break-word;
}

.attestation-block {
  border: 2px solid var(--color-border);
  padding: var(--space-sm);
}

.footnote,
.muted {
  color: var(--color-text-secondary);
}

@media (max-width: 700px) {
  .report-header {
    flex-direction: column;
    align-items: stretch;
  }

  .coc-report-table {
    display: block;
    overflow-x: auto;
  }
}
</style>

<style>
@media print {
  .app-sidebar,
  .app-header,
  .app-footer,
  .shell-backdrop,
  .header-row,
  .filters,
  .handoff-form,
  .data-table-shell,
  .pagination,
  .audit-log-section,
  .audit-toolbar,
  .coc-toolbar,
  .coc-status,
  .coc-actions {
    display: none !important;
  }

  .view-root,
  .coc-section,
  .coc-results,
  .coc-print-card {
    display: block !important;
  }

  .shell-content {
    padding: 0 !important;
    overflow: visible !important;
  }

  .coc-section {
    margin: 0;
    padding: 0;
  }

  .coc-print-card {
    break-after: page;
    page-break-after: always;
    box-shadow: none;
    margin: 0 0 1.25rem;
  }

  .coc-print-card:last-child {
    break-after: auto;
    page-break-after: auto;
  }

  .attestation-block {
    border: 2px solid #000 !important;
  }
}
</style>