# Ticket: Add Edit Share Option Using Existing Add Share Dialog

## Summary
Add an Edit option for existing shares on the Mounts screen by reusing the current Add Share dialog with fields pre-populated from the selected share.

## Background
Operators can add, validate, and remove shares, but cannot edit an existing share in place.
This causes unnecessary delete-and-recreate workflows and increases operational risk.

## User Story
As an admin or manager, I want to edit an existing share from the Mounts list so I can correct remote path or credentials without deleting and recreating the share.

## Goals
- Add an Edit action in the Mounts list for eligible roles.
- Reuse the Add Share dialog in edit mode.
- Pre-fill dialog fields with the selected share values.
- Persist edits via API and refresh the mount row/state.

## Non-Goals
- Changing role permissions for mount management.
- Changing mount validation semantics.
- Introducing a separate edit-only modal.

## Functional Requirements
- Mount list rows include an Edit action for users with existing mount-write permissions.
- Clicking Edit opens the existing Add Share dialog in edit mode.
- Edit mode pre-populates editable fields from the selected share.
- In edit mode, submit updates the existing share record instead of creating a new one.
- On success, the list updates and a success notification is shown.
- On failure, dialog stays open and shows actionable error text.

## Data and API Requirements
- Add update endpoint for mounts (for example `PATCH /mounts/{mount_id}`) with role guards aligned to add/remove.
- Update schema supports editable fields for mount type/path/credentials as approved.
- Sensitive credential handling remains unchanged (no credential values returned in list responses).
- Audit log records a dedicated update action (for example `MOUNT_UPDATED`) with actor and changed fields.

## UX Requirements
- Dialog title and primary button change by mode:
  - Create mode: Add Share / Create
  - Edit mode: Edit Share / Save
- Existing field validation rules are reused.
- Local mount point behavior follows current product behavior:
  - If system-generated, do not allow freeform user override.
  - If displayed, show as read-only informational value.

## Acceptance Criteria
1. Mount list includes Edit action for admin/manager and does not expose it to unauthorized roles.
2. Edit action opens the existing dialog pre-filled with current share values.
3. Saving valid edits updates the existing share and does not create a new share.
4. API returns expected error codes for invalid payload, not found, unauthorized, and conflicts.
5. Audit log includes `MOUNT_UPDATED` entries with user and mount id.
6. Existing Add Share and Remove Share flows continue to work unchanged.
7. UI tests cover create mode and edit mode behavior in the same dialog component.

## Implementation Tasks
- Backend:
  - Add mount update schema and service/repository update flow.
  - Add mount update route and role guard.
  - Add audit event emission for updates.
- Frontend:
  - Add Edit action in Mounts list.
  - Refactor Add dialog to support create/edit modes.
  - Pre-fill and submit update payload in edit mode.
  - Maintain existing validation and error rendering.
- Tests:
  - Backend unit/integration tests for update route/service/audit.
  - Frontend component tests for dialog mode switching and prefill.
  - E2E scenario: create share -> edit share -> validate share.

## Risks and Notes
- Editing mount type/path may require remount/revalidation behavior decisions.
- Credential edit UX should avoid exposing stored secrets in clear text.
- If local mountpoint is generated, editing remote path may require explicit rules for keeping or regenerating the local path.

## Definition of Done
- All acceptance criteria are met.
- Relevant backend/frontend tests are added and passing.
- Operations and user-facing docs are updated for the new Edit Share workflow.
