"""Opt-in real MongoDB format/FCV test; disposable, network-free container."""

import os
import unittest

from docker_fixture import run_container


@unittest.skipUnless(
    os.environ.get("UNIFI_MONGO_TEST_IMAGE"), "requires built Linux image"
)
class MongoUpgradeTest(unittest.TestCase):
    def test_upgrade_failure_resume_noop_and_original_restore(self):
        run_container(
            r"""
runner=/usr/local/bin/unifi-os-mongo
prepare=/usr/local/bin/unifi-os-prepare-mongo
mkdir -p /lib/unifi/data/db
touch /lib/unifi/data/system.properties
start() {
    "$runner" "$1" mongod --dbpath "$2" --bind_ip 127.0.0.1 \
        --port 27118 --nounixsocket --wiredTigerCacheSizeGB 0.25 --logpath /run/test.log &
    pid=$!
    for ((i=0;i<60;i++)); do
        if "$runner" "$1" mongo --quiet --port 27118 --eval 'quit(db.adminCommand({ping:1}).ok === 1 ? 0 : 1)' >/dev/null 2>&1; then return; fi
        sleep 1
    done
    exit 1
}
stop() { kill -TERM "$pid"; wait "$pid"; }
for version in 3.6 4.0 4.2 4.4; do
    "$runner" "$version" mongod --version | head -1
done
start 3.6 /lib/unifi/data/db
"$runner" 3.6 mongo --quiet --port 27118 --eval \
    'db.getSiblingDB("ace").devices.insert({_id:"retained-device",config:{vlan:42}})'
stop

# Fail before the 4.2 FCV write, then prove restart uses MongoDB's checkpoint.
cp "$runner" /usr/local/bin/mongo-real
cat > "$runner" <<'WRAPPER'
#!/bin/bash
if [[ $1 == 4.2 && $2 == mongo && "$*" == *setFeatureCompatibilityVersion* ]]; then exit 42; fi
exec /usr/local/bin/mongo-real "$@"
WRAPPER
if "$prepare"; then echo 'Expected injected failure' >&2; exit 1; fi
test "$(cat /var/lib/unifi-os-app/mongo-runtime)" = 4.2
before=$(sha256sum /var/lib/unifi-os-app/mongo-originals/originals.tar)
cp /usr/local/bin/mongo-real "$runner"
"$prepare"
test "$(cat /var/lib/unifi-os-app/mongo-runtime)" = 4.4
"$prepare"
test "$before" = "$(sha256sum /var/lib/unifi-os-app/mongo-originals/originals.tar)"
test "$(stat -c %a /var/lib/unifi-os-app/mongo-originals)" = 700
test "$(stat -c %a /var/lib/unifi-os-app/mongo-originals/originals.tar)" = 600
start 4.4 /lib/unifi/data/db
"$runner" 4.4 mongo --quiet --port 27118 --eval \
    'assert.eq("4.4",db.adminCommand({getParameter:1,featureCompatibilityVersion:1}).featureCompatibilityVersion.version); assert.eq(42,db.getSiblingDB("ace").devices.findOne({_id:"retained-device"}).config.vlan)'
stop

# Restore only into a different disposable directory, never automatic rollback.
mkdir /run/rollback
tar -xf /var/lib/unifi-os-app/mongo-originals/originals.tar -C /run/rollback
start 3.6 /run/rollback/db
"$runner" 3.6 mongo --quiet --port 27118 --eval \
    'assert.eq("3.6",db.adminCommand({getParameter:1,featureCompatibilityVersion:1}).featureCompatibilityVersion.version); assert.eq(42,db.getSiblingDB("ace").devices.findOne({_id:"retained-device"}).config.vlan)'
stop

# An altered original archive must block startup rather than overwrite it.
printf 'corruption' >> /var/lib/unifi-os-app/mongo-originals/originals.tar
if "$prepare"; then echo 'Expected backup integrity failure' >&2; exit 1; fi
test "$(cat /var/lib/unifi-os-app/mongo-runtime)" = 4.4
""",
            timeout=300,
        )
