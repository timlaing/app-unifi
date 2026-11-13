# Production release checklist

This candidate is intentionally `stage: experimental` with a breaking-version
marker. Keep its PR in draft until the remaining gates are resolved. Do not
equate a successful migration rehearsal with production certification.

## Evidence available

- [x] Same repository/app identity retained in an ARM64 HAOS update.
- [x] Real legacy bind mount, complete storage-root preservation and persistence.
- [x] Unchanged Ubiquiti installer/executables/generated units; separate overrides.
- [x] Conditional in-place MongoDB/FCV transitions with private original backup.
- [x] Synthetic failure/resume, repeat-startup skip, integrity rejection and rollback.
- [x] Cold-data rehearsal: all 102 UniFi application collections byte-verified.
- [x] Vendor-native authenticated export, matching Network install and restore.
- [x] User confirmed that restored data loaded correctly.

These are rehearsal results, not certification of this final packaging change.

## Blocking release gates

- [ ] Build and execute AMD64 natively, including all MongoDB hops and nested OS.
- [ ] Exercise additional supported ARM64 hardware and resource constraints.
- [ ] Validate a confined AppArmor profile and review the `SYS_ADMIN` boundary.
- [ ] Run a security review of worker namespaces, host protections and privileges.
- [ ] Apply/test retained legacy heap/log options, or approve an explicit migration.
- [ ] Preserve/test custom Supervisor port bindings across changed container keys.
- [ ] Verify real device reconnect/provisioning and portal/discovery behavior during
      an explicitly approved cutover, not against copied production devices.
- [ ] Accept missing historical statistics or resolve the vendor backup omission.
- [ ] Investigate post-restore finalization HTTP 401 and Media Server crash dump.
- [ ] Verify administrator permissions and all imported assets/configuration.
- [ ] Test final image restart, container recreation, host reboot and boot ordering.
- [ ] Test cold HA backup/restore with complete original and nested OS storage.
- [ ] Test interrupted installer/FCV transitions and documented scoped rollback.
- [ ] Design and test subsequent vendor OS/application update behavior.
- [ ] Add recurring architecture/lifecycle checks before changing stage to stable.

## Reproduce local checks

```sh
docker build --platform linux/arm64 -t unifi-os-candidate:arm64 unifi
UNIFI_MONGO_TEST_IMAGE=unifi-os-candidate:arm64 \
  python3 -m unittest discover -s unifi/tests -p 'test_*.py' -v
shellcheck unifi/rootfs/usr/local/bin/unifi-os-* \
  unifi/rootfs/usr/lib/unifi/bin/mongod unifi/build/* unifi/tests/*.sh
hadolint unifi/Dockerfile
```

Use only synthetic/cold disposable data for these checks. Backups, credentials,
vendor-code extracts and database inventories must remain outside Git.
