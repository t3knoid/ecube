#!/usr/bin/env bash

set -euo pipefail

project_id="${1:-1}"
starting_id="${2:-1}"

if [[ ! "${project_id}" =~ ^[1-9][0-9]*$ ]]; then
  echo "project_id must be a positive integer" >&2
  exit 1
fi

if [[ ! "${starting_id}" =~ ^[1-9][0-9]*$ ]]; then
  echo "starting_id must be a positive integer" >&2
  exit 1
fi

current_id="${starting_id}"
first=true

for dev in /dev/sd?; do
  [[ -b "${dev}" ]] || continue

  props="$(udevadm info --query=property --name="${dev}" 2>/dev/null || true)"
  [[ -n "${props}" ]] || continue

  serial="$(printf '%s\n' "${props}" | sed -n 's/^ID_SERIAL_SHORT=//p' | head -n1)"
  devpath="$(printf '%s\n' "${props}" | sed -n 's/^DEVPATH=//p' | head -n1)"

  if [[ "${devpath}" != *"/usb"* ]]; then
    continue
  fi

  port="$(printf '%s\n' "${devpath}" | sed -n 's#.*\/usb[0-9]\+/\([0-9][0-9-]*\)\(/.*\|:[0-9].*\)$#\1#p' | head -n1)"

  if [[ -z "${port}" || -z "${serial}" ]]; then
    continue
  fi

  if [[ "${first}" == false ]]; then
    printf ',\n'
  fi

  printf '{\n'
  printf '  "id": %s,\n' "${current_id}"
  printf '  "port_system_path": "%s",\n' "${port}"
  printf '  "project_id": %s,\n' "${project_id}"
  printf '  "device_identifier": "%s"\n' "${serial}"
  printf '}'

  first=false
  current_id=$((current_id + 1))
done

printf '\n'
