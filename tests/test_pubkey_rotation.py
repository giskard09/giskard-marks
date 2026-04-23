"""Tests for A3 — key rotation / revocation / compromise flow in giskard-marks.

The giskard-marks service stores pub_key entries in giskard-memory. These tests
replace mem_store / mem_recall with an in-memory stub so they can run hermetic
in CI.
"""
import base64
import json
import os
import sys
import time
import uuid

import pytest
from fastapi.testclient import TestClient
from nacl.signing import SigningKey

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class MemStub:
    """In-memory replacement for giskard-memory behind marks.mem_store/mem_recall."""

    def __init__(self):
        self.entries: list = []  # list of (agent_id, content, metadata)

    def store(self, content, agent_id, metadata=None):
        self.entries.append((agent_id, content, metadata or {}))

    def recall(self, query, agent_id, n=50):
        matches = [c for (aid, c, _m) in self.entries if aid == agent_id and query in c]
        return {"results": "\n---\n".join(matches) if matches else ""}


@pytest.fixture
def ctx():
    for mod in [m for m in list(sys.modules) if m == "marks"]:
        del sys.modules[mod]
    import marks
    stub = MemStub()

    async def _mem_store(content, agent_id, metadata=None):
        stub.store(content, agent_id, metadata)
        return {"ok": True}

    async def _mem_recall(query, agent_id, n=50):
        return stub.recall(query, agent_id, n)

    marks.mem_store = _mem_store
    marks.mem_recall = _mem_recall
    return marks, TestClient(marks.app), stub


def _keypair():
    sk = SigningKey.generate()
    return sk, base64.b64encode(bytes(sk.verify_key)).decode("ascii")


def _sign_canonical(sk: SigningKey, payload: dict) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(sk.sign(body).signature).decode("ascii")


def _register(client, agent_id: str, vk_b64: str):
    r = client.post("/pubkey/register", json={"agent_id": agent_id, "pub_key": vk_b64})
    assert r.status_code == 200, r.text
    return r.json()


# ───────────────────────────── register + lookup ─────────────────────────────

def test_register_creates_epoch_1_active(ctx):
    _, client, _ = ctx
    sk, vk = _keypair()
    body = _register(client, "alice", vk)
    assert body["status"] == "registered"
    assert body["entry"]["epoch"] == 1
    assert body["entry"]["status"] == "active"

    r = client.get("/pubkey/alice")
    assert r.status_code == 200
    assert r.json()["pub_key"] == vk
    assert r.json()["epoch"] == 1


def test_register_twice_same_key_is_idempotent(ctx):
    _, client, _ = ctx
    sk, vk = _keypair()
    _register(client, "alice", vk)
    r = client.post("/pubkey/register", json={"agent_id": "alice", "pub_key": vk})
    assert r.status_code == 200
    assert r.json()["status"] == "already_registered"


def test_register_twice_different_key_is_rejected(ctx):
    _, client, _ = ctx
    _, vk1 = _keypair()
    _, vk2 = _keypair()
    _register(client, "alice", vk1)
    r = client.post("/pubkey/register", json={"agent_id": "alice", "pub_key": vk2})
    assert r.status_code == 409
    assert "rotate" in r.text.lower()


# ───────────────────────────── rotate ─────────────────────────────

def test_rotate_happy_path_and_history(ctx):
    marks, client, _ = ctx
    sk1, vk1 = _keypair()
    sk2, vk2 = _keypair()
    _register(client, "alice", vk1)

    ts = int(time.time())
    nonce = uuid.uuid4().hex
    proof = _sign_canonical(sk1, {
        "agent_id": "alice", "new_pub_key": vk2,
        "timestamp": ts, "nonce": nonce, "action": "rotate",
    })
    r = client.post("/pubkey/rotate", json={
        "agent_id": "alice", "new_pub_key": vk2,
        "timestamp": ts, "nonce": nonce, "rotation_proof": proof,
    })
    assert r.status_code == 200, r.text
    assert r.json()["new_epoch"] == 2

    # current active is epoch 2
    cur = client.get("/pubkey/alice").json()
    assert cur["pub_key"] == vk2 and cur["epoch"] == 2

    # history has both epochs
    hist = client.get("/pubkey/alice/history").json()
    assert [e["epoch"] for e in hist["epochs"]] == [1, 2]
    assert hist["epochs"][0]["status"] == "rotated"
    assert hist["epochs"][1]["status"] == "active"


def test_rotate_with_wrong_proof_is_rejected(ctx):
    _, client, _ = ctx
    sk1, vk1 = _keypair()
    sk_attacker, _ = _keypair()
    _, vk2 = _keypair()
    _register(client, "alice", vk1)

    ts = int(time.time())
    nonce = uuid.uuid4().hex
    bogus_proof = _sign_canonical(sk_attacker, {
        "agent_id": "alice", "new_pub_key": vk2,
        "timestamp": ts, "nonce": nonce, "action": "rotate",
    })
    r = client.post("/pubkey/rotate", json={
        "agent_id": "alice", "new_pub_key": vk2,
        "timestamp": ts, "nonce": nonce, "rotation_proof": bogus_proof,
    })
    assert r.status_code == 403


def test_rotate_rate_limit(ctx):
    _, client, _ = ctx
    sk1, vk1 = _keypair()
    sk2, vk2 = _keypair()
    _register(client, "alice", vk1)

    ts = int(time.time())
    nonce = uuid.uuid4().hex
    proof = _sign_canonical(sk1, {
        "agent_id": "alice", "new_pub_key": vk2,
        "timestamp": ts, "nonce": nonce, "action": "rotate",
    })
    assert client.post("/pubkey/rotate", json={
        "agent_id": "alice", "new_pub_key": vk2,
        "timestamp": ts, "nonce": nonce, "rotation_proof": proof,
    }).status_code == 200

    # Second rotate inside the cooldown window
    sk3, vk3 = _keypair()
    ts2 = int(time.time())
    nonce2 = uuid.uuid4().hex
    proof2 = _sign_canonical(sk2, {
        "agent_id": "alice", "new_pub_key": vk3,
        "timestamp": ts2, "nonce": nonce2, "action": "rotate",
    })
    r = client.post("/pubkey/rotate", json={
        "agent_id": "alice", "new_pub_key": vk3,
        "timestamp": ts2, "nonce": nonce2, "rotation_proof": proof2,
    })
    assert r.status_code == 429


# ───────────────────────────── revoke ─────────────────────────────

def test_revoke_happy_path(ctx):
    _, client, _ = ctx
    sk1, vk1 = _keypair()
    _register(client, "alice", vk1)

    ts = int(time.time())
    nonce = uuid.uuid4().hex
    sig = _sign_canonical(sk1, {
        "agent_id": "alice", "action": "revoke",
        "timestamp": ts, "nonce": nonce,
    })
    r = client.post("/pubkey/revoke", json={
        "agent_id": "alice", "timestamp": ts, "nonce": nonce, "signature": sig,
    })
    assert r.status_code == 200, r.text

    # No active anymore
    assert client.get("/pubkey/alice").status_code == 404
    status = client.get("/pubkey/alice/status").json()
    assert status["status"] == "revoked"
    assert status["reason"] == "voluntary"


def test_revoke_with_wrong_signature_is_rejected(ctx):
    _, client, _ = ctx
    sk1, vk1 = _keypair()
    sk_attacker, _ = _keypair()
    _register(client, "alice", vk1)

    ts = int(time.time())
    nonce = uuid.uuid4().hex
    bogus = _sign_canonical(sk_attacker, {
        "agent_id": "alice", "action": "revoke",
        "timestamp": ts, "nonce": nonce,
    })
    r = client.post("/pubkey/revoke", json={
        "agent_id": "alice", "timestamp": ts, "nonce": nonce, "signature": bogus,
    })
    assert r.status_code == 403


# ───────────────────────────── compromise flow ─────────────────────────────

def test_compromise_flow_needs_two_genesis(ctx):
    marks, client, _ = ctx
    # Victim + 2 genesis attestors
    sk_v, vk_v = _keypair()
    sk_g1, vk_g1 = _keypair()
    sk_g2, vk_g2 = _keypair()
    _register(client, "alice",         vk_v)
    _register(client, "giskard-self",  vk_g1)
    _register(client, "lightning",     vk_g2)

    # Open proposal
    r = client.post("/pubkey/report-compromise", json={
        "agent_id": "alice", "reporter_agent_id": "alice",
    })
    assert r.status_code == 200, r.text
    assert r.json()["required_attestations"] == 2

    # First attestation
    ts = int(time.time()); nonce = uuid.uuid4().hex
    sig1 = _sign_canonical(sk_g1, {
        "proposal_agent_id": "alice", "action": "compromise",
        "timestamp": ts, "nonce": nonce,
    })
    r1 = client.post("/pubkey/compromise/attest", json={
        "proposal_agent_id": "alice", "attestor": "giskard-self",
        "timestamp": ts, "nonce": nonce, "signature": sig1,
    })
    assert r1.status_code == 200 and r1.json()["status"] == "attested"

    # Victim's key still active after one attestation
    assert client.get("/pubkey/alice").status_code == 200

    # Second attestation → confirmed, victim revoked
    ts2 = int(time.time()); nonce2 = uuid.uuid4().hex
    sig2 = _sign_canonical(sk_g2, {
        "proposal_agent_id": "alice", "action": "compromise",
        "timestamp": ts2, "nonce": nonce2,
    })
    r2 = client.post("/pubkey/compromise/attest", json={
        "proposal_agent_id": "alice", "attestor": "lightning",
        "timestamp": ts2, "nonce": nonce2, "signature": sig2,
    })
    assert r2.status_code == 200 and r2.json()["status"] == "confirmed"

    # Victim's active lookup returns 404 now
    assert client.get("/pubkey/alice").status_code == 404
    status = client.get("/pubkey/alice/status").json()
    assert status["status"] == "revoked" and status["reason"] == "compromise"


def test_non_genesis_attestor_rejected(ctx):
    _, client, _ = ctx
    sk_v, vk_v = _keypair()
    sk_x, vk_x = _keypair()
    _register(client, "alice",    vk_v)
    _register(client, "randomer", vk_x)
    client.post("/pubkey/report-compromise",
                json={"agent_id": "alice", "reporter_agent_id": "alice"})

    ts = int(time.time()); nonce = uuid.uuid4().hex
    sig = _sign_canonical(sk_x, {
        "proposal_agent_id": "alice", "action": "compromise",
        "timestamp": ts, "nonce": nonce,
    })
    r = client.post("/pubkey/compromise/attest", json={
        "proposal_agent_id": "alice", "attestor": "randomer",
        "timestamp": ts, "nonce": nonce, "signature": sig,
    })
    assert r.status_code == 403


# ───────────────────────────── historical lookup ─────────────────────────────

def test_lookup_at_ts_returns_epoch_active_at_that_time(ctx):
    marks, client, stub = ctx
    sk1, vk1 = _keypair()
    sk2, vk2 = _keypair()
    _register(client, "alice", vk1)

    # Wall-clock moment that falls AFTER the epoch-1 registered_at but BEFORE
    # the rotation below.
    time.sleep(1.1)
    ts_between = int(time.time())
    time.sleep(1.1)

    ts = int(time.time())
    nonce = uuid.uuid4().hex
    proof = _sign_canonical(sk1, {
        "agent_id": "alice", "new_pub_key": vk2,
        "timestamp": ts, "nonce": nonce, "action": "rotate",
    })
    assert client.post("/pubkey/rotate", json={
        "agent_id": "alice", "new_pub_key": vk2,
        "timestamp": ts, "nonce": nonce, "rotation_proof": proof,
    }).status_code == 200

    # Historical timestamp → epoch 1 (original key)
    r = client.get(f"/pubkey/alice?at_ts={ts_between}")
    assert r.status_code == 200, r.text
    assert r.json()["pub_key"] == vk1
    assert r.json()["epoch"] == 1

    # Now → epoch 2 (new key)
    r2 = client.get("/pubkey/alice")
    assert r2.json()["pub_key"] == vk2
    assert r2.json()["epoch"] == 2
