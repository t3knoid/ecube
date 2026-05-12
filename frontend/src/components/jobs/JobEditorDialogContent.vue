<script setup>
import DirectoryBrowser from '@/components/browse/DirectoryBrowser.vue'

const threadCountOptions = Array.from({ length: 32 }, (_unused, index) => index + 1)

const props = defineProps({
  title: {
    type: String,
    required: true,
  },
  description: {
    type: String,
    default: '',
  },
  errorMessage: {
    type: String,
    default: '',
  },
  noProjectsMessage: {
    type: String,
    default: '',
  },
  noEligibleMountsMessage: {
    type: String,
    default: '',
  },
  noEligibleDrivesMessage: {
    type: String,
    default: '',
  },
  projectSelected: {
    type: Boolean,
    default: false,
  },
  projectEditable: {
    type: Boolean,
    default: true,
  },
  evidenceEditable: {
    type: Boolean,
    default: true,
  },
  showNotesField: {
    type: Boolean,
    default: true,
  },
  notesEditable: {
    type: Boolean,
    default: true,
  },
  showOverflowPanel: {
    type: Boolean,
    default: true,
  },
  overflowSelectionEnabled: {
    type: Boolean,
    default: true,
  },
  showExecutionGroup: {
    type: Boolean,
    default: true,
  },
  showSourceGroup: {
    type: Boolean,
    default: true,
  },
  sourceEditable: {
    type: Boolean,
    default: true,
  },
  showPrimaryDriveField: {
    type: Boolean,
    default: true,
  },
  primaryDriveEditable: {
    type: Boolean,
    default: true,
  },
  showCallbackUrlField: {
    type: Boolean,
    default: true,
  },
  callbackUrlEditable: {
    type: Boolean,
    default: true,
  },
  showSourceBrowserToggle: {
    type: Boolean,
    default: true,
  },
  showSourceBrowser: {
    type: Boolean,
    default: false,
  },
  canBrowseSelectedMount: {
    type: Boolean,
    default: false,
  },
  selectedMountRecord: {
    type: Object,
    default: null,
  },
  availableProjects: {
    type: Array,
    default: () => [],
  },
  eligibleMounts: {
    type: Array,
    default: () => [],
  },
  primaryEligibleDrives: {
    type: Array,
    default: () => [],
  },
  overflowEligibleDrives: {
    type: Array,
    default: () => [],
  },
  form: {
    type: Object,
    required: true,
  },
  saving: {
    type: Boolean,
    default: false,
  },
  canSubmit: {
    type: Boolean,
    default: false,
  },
  submitLabel: {
    type: String,
    required: true,
  },
  loadingLabel: {
    type: String,
    required: true,
  },
  cancelLabel: {
    type: String,
    required: true,
  },
  submitId: {
    type: String,
    default: 'job-submit',
  },
  closeLabel: {
    type: String,
    default: '',
  },
  browseLabel: {
    type: String,
    default: '',
  },
  projectLabel: {
    type: String,
    required: true,
  },
  chooseProjectLabel: {
    type: String,
    required: true,
  },
  evidenceLabel: {
    type: String,
    required: true,
  },
  notesLabel: {
    type: String,
    required: true,
  },
  notesHint: {
    type: String,
    required: true,
  },
  callbackUrlLabel: {
    type: String,
    required: true,
  },
  callbackUrlHint: {
    type: String,
    required: true,
  },
  threadCountLabel: {
    type: String,
    required: true,
  },
  allowThreadCountDefaultOption: {
    type: Boolean,
    default: false,
  },
  threadCountDefaultOptionLabel: {
    type: String,
    default: '',
  },
  jobDetailsGroupLabel: {
    type: String,
    required: true,
  },
  sourceGroupLabel: {
    type: String,
    required: true,
  },
  selectMountLabel: {
    type: String,
    required: true,
  },
  chooseMountLabel: {
    type: String,
    required: true,
  },
  sourcePathLabel: {
    type: String,
    required: true,
  },
  sourcePathHint: {
    type: String,
    required: true,
  },
  destinationGroupLabel: {
    type: String,
    required: true,
  },
  selectDriveLabel: {
    type: String,
    required: true,
  },
  chooseDriveLabel: {
    type: String,
    required: true,
  },
  overflowPanelTitle: {
    type: String,
    required: true,
  },
  overflowPanelHelp: {
    type: String,
    required: true,
  },
  noEligibleOverflowDrivesLabel: {
    type: String,
    required: true,
  },
  executionGroupLabel: {
    type: String,
    required: true,
  },
  runImmediatelyLabel: {
    type: String,
    required: true,
  },
  formatMountLabel: {
    type: Function,
    required: true,
  },
  formatDriveLabel: {
    type: Function,
    required: true,
  },
})

const emit = defineEmits(['close', 'submit', 'toggle-source-browser'])
</script>

<template>
  <div class="dialog-header job-create-summary">
    <h2 id="job-editor-title">{{ title }}</h2>
    <p v-if="description" class="muted">{{ description }}</p>
    <p v-if="errorMessage" class="error-banner dialog-error-banner" role="alert" aria-live="assertive">{{ errorMessage }}</p>
    <p v-if="noProjectsMessage" class="muted">{{ noProjectsMessage }}</p>
    <p v-else-if="projectSelected && noEligibleMountsMessage" class="muted">{{ noEligibleMountsMessage }}</p>
    <p v-else-if="projectSelected && noEligibleDrivesMessage" class="muted">{{ noEligibleDrivesMessage }}</p>
  </div>

  <div class="dialog-body job-create-scroll-region">
    <div class="dialog-groups">
      <fieldset class="dialog-group dialog-group--details">
        <legend>{{ jobDetailsGroupLabel }}</legend>

        <div class="details-primary-row">
          <div class="details-primary-field details-primary-field--project">
            <label for="job-project">
              {{ projectLabel }}
              <span class="required-indicator" aria-hidden="true">
                <svg class="required-indicator-icon" viewBox="0 0 16 16" focusable="false">
                  <path d="M8 0.75 9.41 5.59 14.25 4.18 10.82 8l3.43 3.82-4.84-1.41L8 15.25l-1.41-4.84-4.84 1.41L5.18 8 1.75 4.18l4.84 1.41L8 0.75Z" />
                </svg>
              </span>
              <span class="sr-only">required</span>
            </label>
            <select v-if="projectEditable" id="job-project" v-model="form.project_id" required aria-required="true">
              <option value="">{{ chooseProjectLabel }}</option>
              <option v-for="project in availableProjects" :key="project" :value="project">{{ project }}</option>
            </select>
            <input v-else id="job-project" :value="form.project_id" type="text" disabled aria-required="true" />
          </div>

          <div class="details-primary-field details-primary-field--evidence">
            <label for="job-evidence">
              {{ evidenceLabel }}
              <span class="required-indicator" aria-hidden="true">
                <svg class="required-indicator-icon" viewBox="0 0 16 16" focusable="false">
                  <path d="M8 0.75 9.41 5.59 14.25 4.18 10.82 8l3.43 3.82-4.84-1.41L8 15.25l-1.41-4.84-4.84 1.41L5.18 8 1.75 4.18l4.84 1.41L8 0.75Z" />
                </svg>
              </span>
              <span class="sr-only">required</span>
            </label>
            <input id="job-evidence" v-model="form.evidence_number" type="text" :disabled="!projectSelected || !evidenceEditable" required aria-required="true" />
          </div>
        </div>

        <template v-if="showNotesField">
          <label for="job-notes">{{ notesLabel }}</label>
          <textarea id="job-notes" v-model="form.notes" rows="3" :disabled="!projectSelected || !notesEditable" :placeholder="notesHint"></textarea>
        </template>

        <div class="details-secondary-row">
          <div v-if="showCallbackUrlField" class="details-secondary-field details-secondary-field--callback">
            <label for="job-callback-url">{{ callbackUrlLabel }}</label>
            <input
              id="job-callback-url"
              v-model="form.callback_url"
              type="url"
              :disabled="!projectSelected || !callbackUrlEditable"
              :placeholder="callbackUrlHint"
            />
          </div>

          <div class="thread-count-row">
            <label for="job-thread-count">
              {{ threadCountLabel }}
              <span class="required-indicator" aria-hidden="true">
                <svg class="required-indicator-icon" viewBox="0 0 16 16" focusable="false">
                  <path d="M8 0.75 9.41 5.59 14.25 4.18 10.82 8l3.43 3.82-4.84-1.41L8 15.25l-1.41-4.84-4.84 1.41L5.18 8 1.75 4.18l4.84 1.41L8 0.75Z" />
                </svg>
              </span>
              <span class="sr-only">required</span>
            </label>
            <select
              id="job-thread-count"
              v-model.number="form.thread_count"
              :disabled="!projectSelected"
              :required="!allowThreadCountDefaultOption"
              :aria-required="!allowThreadCountDefaultOption"
            >
              <option v-if="allowThreadCountDefaultOption" :value="null">{{ threadCountDefaultOptionLabel }}</option>
              <option v-for="count in threadCountOptions" :key="count" :value="count">{{ count }}</option>
            </select>
          </div>
        </div>
      </fieldset>

      <fieldset v-if="showSourceGroup" class="dialog-group dialog-group--source">
        <legend>{{ sourceGroupLabel }}</legend>

        <label for="job-mount">
          {{ selectMountLabel }}
          <span class="required-indicator" aria-hidden="true">
            <svg class="required-indicator-icon" viewBox="0 0 16 16" focusable="false">
              <path d="M8 0.75 9.41 5.59 14.25 4.18 10.82 8l3.43 3.82-4.84-1.41L8 15.25l-1.41-4.84-4.84 1.41L5.18 8 1.75 4.18l4.84 1.41L8 0.75Z" />
            </svg>
          </span>
          <span class="sr-only">required</span>
        </label>
        <select id="job-mount" v-model="form.mount_id" :disabled="!projectSelected || !sourceEditable" required aria-required="true">
          <option :value="null">{{ chooseMountLabel }}</option>
          <option v-for="mount in eligibleMounts" :key="mount.id" :value="mount.id">
            {{ formatMountLabel(mount) }}
          </option>
        </select>

        <label for="job-source-path">
          {{ sourcePathLabel }}
          <span class="required-indicator" aria-hidden="true">
            <svg class="required-indicator-icon" viewBox="0 0 16 16" focusable="false">
              <path d="M8 0.75 9.41 5.59 14.25 4.18 10.82 8l3.43 3.82-4.84-1.41L8 15.25l-1.41-4.84-4.84 1.41L5.18 8 1.75 4.18l4.84 1.41L8 0.75Z" />
            </svg>
          </span>
          <span class="sr-only">required</span>
        </label>
        <input id="job-source-path" v-model="form.source_path" type="text" :disabled="!projectSelected || !sourceEditable" :readonly="projectSelected || undefined" :placeholder="sourcePathHint" required aria-required="true" />
        <div v-if="showSourceBrowserToggle" class="source-browser-actions">
          <button
            id="job-source-browse-toggle"
            type="button"
            class="btn"
            :disabled="!canBrowseSelectedMount || !sourceEditable"
            @click="emit('toggle-source-browser')"
          >
            {{ showSourceBrowser ? closeLabel : browseLabel }}
          </button>
        </div>

        <div v-if="showSourceBrowser && selectedMountRecord" class="source-browser-content">
          <DirectoryBrowser
            v-model:current-directory="form.source_path"
            :mount-id="Number(selectedMountRecord.id)"
            root-label=""
            :directories-only="true"
            :show-breadcrumb="false"
            :show-parent-entry="true"
          />
        </div>
      </fieldset>

      <fieldset class="dialog-group dialog-group--destination">
        <legend>{{ destinationGroupLabel }}</legend>

        <template v-if="showPrimaryDriveField">
          <label for="job-drive">
            {{ selectDriveLabel }}
            <span class="required-indicator" aria-hidden="true">
              <svg class="required-indicator-icon" viewBox="0 0 16 16" focusable="false">
                <path d="M8 0.75 9.41 5.59 14.25 4.18 10.82 8l3.43 3.82-4.84-1.41L8 15.25l-1.41-4.84-4.84 1.41L5.18 8 1.75 4.18l4.84 1.41L8 0.75Z" />
              </svg>
            </span>
            <span class="sr-only">required</span>
          </label>
          <select id="job-drive" v-model="form.drive_id" :disabled="!projectSelected || !primaryDriveEditable" required aria-required="true">
            <option :value="null">{{ chooseDriveLabel }}</option>
            <option v-for="drive in primaryEligibleDrives" :key="drive.id" :value="drive.id">
              {{ formatDriveLabel(drive) }}
            </option>
          </select>
        </template>

        <div v-if="showOverflowPanel" class="overflow-panel">
          <p class="overflow-panel-title">{{ overflowPanelTitle }}</p>
          <p class="muted field-hint">{{ overflowPanelHelp }}</p>
          <p v-if="projectSelected && !overflowEligibleDrives.length" class="muted">{{ noEligibleOverflowDrivesLabel }}</p>
          <div v-else class="overflow-drive-list">
            <label v-for="drive in overflowEligibleDrives" :key="drive.id" class="checkbox-row overflow-drive-option">
              <input v-model="form.overflow_drive_ids" type="checkbox" :value="drive.id" :disabled="!projectSelected || !overflowSelectionEnabled" />
              <span>{{ formatDriveLabel(drive) }}</span>
            </label>
          </div>
        </div>
      </fieldset>

      <fieldset v-if="showExecutionGroup" class="dialog-group dialog-group--execution">
        <legend>{{ executionGroupLabel }}</legend>
        <label class="checkbox-row" for="job-run-immediately">
          <input id="job-run-immediately" v-model="form.run_immediately" type="checkbox" :disabled="!projectSelected" />
          <span>{{ runImmediatelyLabel }}</span>
        </label>
      </fieldset>
    </div>
  </div>

  <div class="dialog-actions dialog-footer">
    <p class="required-legend muted">
      <span class="required-indicator" aria-hidden="true">
        <svg class="required-indicator-icon" viewBox="0 0 16 16" focusable="false">
          <path d="M8 0.75 9.41 5.59 14.25 4.18 10.82 8l3.43 3.82-4.84-1.41L8 15.25l-1.41-4.84-4.84 1.41L5.18 8 1.75 4.18l4.84 1.41L8 0.75Z" />
        </svg>
      </span>
      <span>Required field</span>
    </p>
    <div class="dialog-action-buttons">
      <button class="btn" @click="emit('close')">{{ cancelLabel }}</button>
      <button :id="submitId" class="btn btn-primary" :disabled="saving || !canSubmit" @click="emit('submit')">
        {{ saving ? loadingLabel : submitLabel }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.field-hint {
  margin-top: calc(var(--space-xs) * -1);
}

.source-browser-actions {
  display: flex;
  justify-content: flex-start;
}

.source-browser-content {
  margin-top: var(--space-sm);
}

.overflow-panel {
  margin-top: var(--space-md);
  padding-top: var(--space-sm);
  border-top: 1px solid var(--color-border);
}

.overflow-panel-title {
  margin: 0;
  font-weight: var(--font-weight-semibold);
}

.overflow-drive-list {
  display: grid;
  gap: var(--space-xs);
  margin-top: var(--space-sm);
}

.overflow-drive-option {
  padding: var(--space-xs) var(--space-sm);
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius);
  background: var(--color-bg-secondary);
}

input,
select,
textarea {
  border: 1px solid var(--color-border);
  background: var(--color-bg-input);
  color: var(--color-text-primary);
  border-radius: var(--border-radius);
  padding: var(--space-xs) var(--space-sm);
}

textarea {
  resize: vertical;
}

.error-banner {
  color: var(--color-alert-danger-text);
  background: var(--color-alert-danger-bg);
  border: 1px solid var(--color-alert-danger-border);
  border-radius: var(--border-radius);
  padding: var(--space-sm);
}

.muted {
  color: var(--color-text-secondary);
}

.dialog-header,
.dialog-footer {
  flex-shrink: 0;
}

.dialog-body {
  min-height: 0;
  overflow-y: auto;
  padding-right: var(--space-xs);
}

.job-create-summary {
  position: sticky;
  top: 0;
  z-index: 1;
  background: var(--color-bg-secondary);
  padding-bottom: var(--space-xs);
  border-bottom: 1px solid var(--color-border);
}

.dialog-error-banner {
  margin: 0;
}

.job-create-scroll-region {
  display: grid;
}

.dialog-groups {
  display: grid;
  gap: var(--space-md);
  grid-template-columns: repeat(2, minmax(0, 1fr));
  align-items: start;
}

.dialog-group {
  display: grid;
  gap: var(--space-xs);
  align-content: start;
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius);
  padding: var(--space-md);
}

.dialog-group legend {
  padding: 0 var(--space-xs);
  font-weight: 600;
}

.details-primary-row {
  display: grid;
  gap: var(--space-sm);
  grid-template-columns: minmax(0, 1fr) minmax(0, 1.5fr);
  align-items: start;
}

.details-primary-field {
  display: grid;
  gap: var(--space-xs);
}

.details-secondary-row {
  display: grid;
  gap: var(--space-sm);
  grid-template-columns: minmax(0, 2.5fr) auto;
  align-items: start;
}

.details-secondary-field {
  display: grid;
  gap: var(--space-xs);
  min-width: 0;
}

.thread-count-row {
  display: grid;
  gap: var(--space-xs);
  justify-self: start;
  align-self: start;
  width: max-content;
}

.thread-count-row input {
  width: 100%;
  min-width: 0;
}

.required-indicator {
  display: inline-flex;
  align-items: center;
  color: var(--color-danger, #b91c1c);
  margin-left: 0.15rem;
}

.required-indicator-icon {
  width: 0.65em;
  height: 0.65em;
  fill: currentColor;
}

.required-legend {
  display: inline-flex;
  align-items: center;
  gap: var(--space-xs);
  margin: 0;
}

.dialog-group--details {
  grid-column: 1 / span 2;
  grid-row: 1;
}

.dialog-group--source {
  grid-column: 1;
  grid-row: 2;
}

.dialog-group--destination {
  grid-column: 2;
  grid-row: 2;
}

.dialog-group--execution {
  grid-column: 1 / span 2;
  grid-row: 3;
}

.checkbox-row {
  display: inline-flex;
  align-items: center;
  gap: var(--space-sm);
}

.dialog-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-sm);
}

.dialog-action-buttons {
  display: inline-flex;
  justify-content: flex-end;
  gap: var(--space-sm);
}

.dialog-footer {
  padding-top: var(--space-xs);
  border-top: 1px solid var(--color-border);
}

@media (max-width: 768px) {
  .dialog-groups {
    grid-template-columns: 1fr;
  }

  .details-primary-row {
    grid-template-columns: 1fr;
  }

  .details-secondary-row {
    grid-template-columns: 1fr;
  }

  .dialog-actions {
    align-items: stretch;
    flex-direction: column;
  }

  .dialog-action-buttons {
    justify-content: flex-end;
  }

  .dialog-group--details,
  .dialog-group--source,
  .dialog-group--destination,
  .dialog-group--execution {
    grid-column: auto;
    grid-row: auto;
  }
}
</style>