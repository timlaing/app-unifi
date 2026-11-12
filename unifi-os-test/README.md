# UniFi OS Server: experimental Home Assistant test

A separate local app for testing UniFi OS Server 5.1.42 on Home Assistant OS.
It does not upgrade, import, or modify the existing `unifi` app.

**Disposable hosts only.** This experiment grants `SYS_ADMIN`, disables
AppArmor, and relaxes mount protections in separate worker namespaces. Ubiquiti does not
support distributing UniFi OS Server as a standalone Docker container.

Both `aarch64` and `amd64` installer paths are provided. Native ARM64 testing
is available locally; native AMD64 and actual Supervisor testing remain
required. No prebuilt images are published.

See [installation, migration notes and the test checklist](DOCS.md).
