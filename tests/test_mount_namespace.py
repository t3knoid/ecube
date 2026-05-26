from app.infrastructure.mount_namespace import shares_host_mount_namespace


def test_shares_host_mount_namespace_returns_true_when_namespaces_match(monkeypatch):
    def fake_readlink(path: str) -> str:
        mapping = {
            "/proc/self/ns/mnt": "mnt:[4026531840]",
            "/proc/1/ns/mnt": "mnt:[4026531840]",
        }
        return mapping[path]

    monkeypatch.setattr("app.infrastructure.mount_namespace.os.readlink", fake_readlink)

    assert shares_host_mount_namespace() is True


def test_shares_host_mount_namespace_uses_host_read_error_policy(monkeypatch):
    seen: list[str] = []

    def fake_readlink(path: str) -> str:
        if path == "/proc/self/ns/mnt":
            return "mnt:[4026531840]"
        raise PermissionError("denied")

    monkeypatch.setattr("app.infrastructure.mount_namespace.os.readlink", fake_readlink)

    assert shares_host_mount_namespace(
        on_host_read_error=False,
        on_host_read_error_callback=lambda exc: seen.append(type(exc).__name__),
    ) is False
    assert seen == ["PermissionError"]