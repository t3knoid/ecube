#!/usr/bin/env bash
set -euo pipefail

PAM_SOURCE_PATH="${PAM_SOURCE_PATH:-/opt/ecube/deploy/ecube-pam}"
PAM_DEST_PATH="${PAM_DEST_PATH:-/etc/pam.d/ecube}"
COMMON_PASSWORD_PAM_PATH="${COMMON_PASSWORD_PAM_PATH:-/etc/pam.d/common-password}"
PWQUALITY_CONF_PATH="${PWQUALITY_CONF_PATH:-/etc/security/pwquality.conf}"
PAM_SSS_DETECTED="${PAM_SSS_DETECTED:-auto}"

set_or_append_pwquality_key() {
  local policy_file="$1"
  local key="$2"
  local value="$3"
  local replace_existing="${4:-true}"
  local tmp_file
  tmp_file="$(mktemp)"

  awk -v key="$key" -v value="$value" -v replace_existing="$replace_existing" '
    BEGIN { updated = 0 }
    {
      line = $0
      stripped = line
      sub(/^[[:space:]]+/, "", stripped)

      if (stripped ~ /^#/) {
        print line
        next
      }

      if (stripped ~ ("^" key "[[:space:]]*=")) {
        if (replace_existing == "true") {
          print key " = " value
        } else {
          print line
        }
        updated = 1
        next
      }

      print line
    }
    END {
      if (!updated) {
        print key " = " value
      }
    }
  ' "$policy_file" > "$tmp_file"

  mv -f "$tmp_file" "$policy_file"
}

ensure_common_password_stack() {
  local common_password_path="$1"
  local common_password_tmp

  common_password_tmp="$(mktemp)"
  awk '
    BEGIN {
      inserted = 0
    }
    {
      line = $0
      stripped = line
      sub(/^[[:space:]]+/, "", stripped)

      if (stripped ~ /^password[[:space:]].*pam_pwquality\.so([[:space:]]|$)/) {
        next
      }

      if (stripped ~ /^password[[:space:]].*pam_cracklib\.so([[:space:]]|$)/) {
        next
      }

      if (stripped ~ /^password[[:space:]].*pam_pwhistory\.so([[:space:]]|$)/) {
        next
      }

      if (!inserted && stripped ~ /^password[[:space:]].*pam_unix\.so([[:space:]]|$)/) {
        print "password\trequisite\tpam_pwquality.so local_users_only"
        print "password\trequired\tpam_pwhistory.so remember=12 use_authtok enforce_for_root"
        inserted = 1
      }

      print line
      next
    }
    END {
      if (!inserted) {
        print "password\trequisite\tpam_pwquality.so local_users_only"
        print "password\trequired\tpam_pwhistory.so remember=12 use_authtok enforce_for_root"
      }
    }
  ' "$common_password_path" > "$common_password_tmp"

  mv -f "$common_password_tmp" "$common_password_path"
  chmod 0644 "$common_password_path"
  if [[ "$(id -u)" == "0" ]]; then
    chown root:root "$common_password_path"
  fi
}

install_pam_service() {
  local sss_detected="false"

  if [[ "$PAM_SSS_DETECTED" == "true" ]]; then
    sss_detected="true"
  elif [[ "$PAM_SSS_DETECTED" == "auto" ]] && ( command -v sssd >/dev/null 2>&1 || [[ -f /lib/security/pam_sss.so || -f /lib/x86_64-linux-gnu/security/pam_sss.so ]] ); then
    sss_detected="true"
  fi

  install -d -m 0755 "$(dirname -- "$PAM_DEST_PATH")"
  if [[ "$sss_detected" == "true" ]]; then
    if [[ "$(id -u)" == "0" ]]; then
      install -m 0644 -o root -g root "$PAM_SOURCE_PATH" "$PAM_DEST_PATH"
    else
      install -m 0644 "$PAM_SOURCE_PATH" "$PAM_DEST_PATH"
    fi
  else
    cat > "$PAM_DEST_PATH" <<'EOF_PAM'
# /etc/pam.d/ecube
# Local-only PAM configuration (SSSD not detected at install time).
# Re-run the installer after installing SSSD to enable domain user authentication.
auth    sufficient  pam_unix.so nullok
auth    required    pam_deny.so
account sufficient  pam_unix.so
account required    pam_deny.so
EOF_PAM
    chmod 0644 "$PAM_DEST_PATH"
  fi
}

ensure_password_policy_defaults() {
  if [[ -f "$COMMON_PASSWORD_PAM_PATH" ]]; then
    ensure_common_password_stack "$COMMON_PASSWORD_PAM_PATH"
  fi

  install -d -m 0755 "$(dirname -- "$PWQUALITY_CONF_PATH")"
  touch "$PWQUALITY_CONF_PATH"

  set_or_append_pwquality_key "$PWQUALITY_CONF_PATH" minlen 14 false
  set_or_append_pwquality_key "$PWQUALITY_CONF_PATH" minclass 3 false
  set_or_append_pwquality_key "$PWQUALITY_CONF_PATH" maxrepeat 3 false
  set_or_append_pwquality_key "$PWQUALITY_CONF_PATH" maxsequence 4 false
  set_or_append_pwquality_key "$PWQUALITY_CONF_PATH" maxclassrepeat 0 false
  set_or_append_pwquality_key "$PWQUALITY_CONF_PATH" dictcheck 1 false
  set_or_append_pwquality_key "$PWQUALITY_CONF_PATH" usercheck 1 false
  set_or_append_pwquality_key "$PWQUALITY_CONF_PATH" difok 5 false
  set_or_append_pwquality_key "$PWQUALITY_CONF_PATH" retry 3 false
  set_or_append_pwquality_key "$PWQUALITY_CONF_PATH" enforce_for_root 1

  chmod 0644 "$PWQUALITY_CONF_PATH"
  if [[ "$(id -u)" == "0" ]]; then
    chown root:root "$PWQUALITY_CONF_PATH"
  fi
}

install_pam_service
ensure_password_policy_defaults