import subprocess
from pathlib import Path


def test_container_os_auth_prep_installs_pam_and_password_policy_baseline(tmp_path):
    repo_root = Path(__file__).resolve().parent.parent
    pam_source = tmp_path / "ecube-pam"
    pam_dest = tmp_path / "pam.d" / "ecube"
    common_password = tmp_path / "pam.d" / "common-password"
    pwquality_conf = tmp_path / "security" / "pwquality.conf"

    pam_source.write_text("auth sufficient pam_unix.so\n", encoding="utf-8")
    common_password.parent.mkdir(parents=True)
    common_password.write_text(
        "password requisite pam_cracklib.so retry=3\n"
        "password [success=1 default=ignore] pam_unix.so obscure use_authtok yescrypt\n",
        encoding="utf-8",
    )
    pwquality_conf.parent.mkdir(parents=True)
    pwquality_conf.write_text("# existing policy\nminlen = 8\n", encoding="utf-8")

    result = subprocess.run(
        ["bash", str(repo_root / "deploy" / "ecube-host" / "configure-os-auth.sh")],
        capture_output=True,
        text=True,
        cwd=repo_root,
        env={
            "PAM_SOURCE_PATH": str(pam_source),
            "PAM_DEST_PATH": str(pam_dest),
            "COMMON_PASSWORD_PAM_PATH": str(common_password),
            "PWQUALITY_CONF_PATH": str(pwquality_conf),
            "PAM_SSS_DETECTED": "false",
        },
    )

    assert result.returncode == 0, result.stderr
    pam_text = pam_dest.read_text(encoding="utf-8")
    assert "auth    sufficient  pam_unix.so nullok" in pam_text
    assert "account sufficient  pam_unix.so" in pam_text
    assert "pam_sss.so" not in pam_text

    common_password_text = common_password.read_text(encoding="utf-8")
    assert "pam_cracklib.so" not in common_password_text
    assert "password\trequisite\tpam_pwquality.so local_users_only" in common_password_text
    assert "password\trequired\tpam_pwhistory.so remember=12 use_authtok enforce_for_root" in common_password_text
    assert common_password_text.index("pam_pwquality.so") < common_password_text.index("pam_unix.so")

    pwquality_text = pwquality_conf.read_text(encoding="utf-8")
    assert "minlen = 8" in pwquality_text
    assert "minclass = 3" in pwquality_text
    assert "maxrepeat = 3" in pwquality_text
    assert "maxsequence = 4" in pwquality_text
    assert "maxclassrepeat = 0" in pwquality_text
    assert "dictcheck = 1" in pwquality_text
    assert "usercheck = 1" in pwquality_text
    assert "difok = 5" in pwquality_text
    assert "retry = 3" in pwquality_text
    assert "enforce_for_root = 1" in pwquality_text


def test_container_os_auth_prep_is_idempotent_for_existing_policy(tmp_path):
    repo_root = Path(__file__).resolve().parent.parent
    pam_source = tmp_path / "ecube-pam"
    pam_dest = tmp_path / "pam.d" / "ecube"
    common_password = tmp_path / "pam.d" / "common-password"
    pwquality_conf = tmp_path / "security" / "pwquality.conf"

    pam_source.write_text("auth sufficient pam_unix.so\n", encoding="utf-8")
    common_password.parent.mkdir(parents=True)
    common_password.write_text(
        "password\trequisite\tpam_pwquality.so local_users_only\n"
        "password\trequired\tpam_pwhistory.so remember=12 use_authtok enforce_for_root\n"
        "password\t[success=1 default=ignore]\tpam_unix.so obscure use_authtok yescrypt\n",
        encoding="utf-8",
    )
    pwquality_conf.parent.mkdir(parents=True)
    pwquality_conf.write_text("enforce_for_root = 1\n", encoding="utf-8")

    result = subprocess.run(
        ["bash", str(repo_root / "deploy" / "ecube-host" / "configure-os-auth.sh")],
        capture_output=True,
        text=True,
        cwd=repo_root,
        env={
            "PAM_SOURCE_PATH": str(pam_source),
            "PAM_DEST_PATH": str(pam_dest),
            "COMMON_PASSWORD_PAM_PATH": str(common_password),
            "PWQUALITY_CONF_PATH": str(pwquality_conf),
            "PAM_SSS_DETECTED": "false",
        },
    )

    assert result.returncode == 0, result.stderr
    common_password_text = common_password.read_text(encoding="utf-8")
    assert common_password_text.count("pam_pwquality.so") == 1
    assert common_password_text.count("pam_pwhistory.so") == 1


def test_container_os_auth_prep_keeps_sssd_template_when_module_is_present(tmp_path):
    repo_root = Path(__file__).resolve().parent.parent
    pam_source = tmp_path / "ecube-pam"
    pam_dest = tmp_path / "pam.d" / "ecube"
    common_password = tmp_path / "pam.d" / "common-password"
    pwquality_conf = tmp_path / "security" / "pwquality.conf"
    pam_source.write_text("auth [success=done ignore=ignore user_unknown=ignore default=die] pam_sss.so use_first_pass\n", encoding="utf-8")
    common_password.parent.mkdir(parents=True)
    common_password.write_text(
        "password [success=1 default=ignore] pam_unix.so obscure use_authtok yescrypt\n",
        encoding="utf-8",
    )
    pwquality_conf.parent.mkdir(parents=True)
    pwquality_conf.write_text("", encoding="utf-8")

    result = subprocess.run(
        ["bash", str(repo_root / "deploy" / "ecube-host" / "configure-os-auth.sh")],
        capture_output=True,
        text=True,
        cwd=repo_root,
        env={
            "PAM_SOURCE_PATH": str(pam_source),
            "PAM_DEST_PATH": str(pam_dest),
            "COMMON_PASSWORD_PAM_PATH": str(common_password),
            "PWQUALITY_CONF_PATH": str(pwquality_conf),
            "PAM_SSS_DETECTED": "true",
        },
    )

    assert result.returncode == 0, result.stderr
    assert pam_dest.read_text(encoding="utf-8") == "auth [success=done ignore=ignore user_unknown=ignore default=die] pam_sss.so use_first_pass\n"