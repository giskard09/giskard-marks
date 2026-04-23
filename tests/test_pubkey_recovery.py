"""Tests for A3 v1 — /pubkey/recover/* (post-compromise re-registration).

Builds on the same MemStub fixture used by test_pubkey_rotation.
A recovery proposal is only valid when the agent's terminal epoch is
status='revoked' AND revocation_reason='compromise'. Two genesis
attestations on the *specific* new_pub_key materialize a new active
epoch.
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
    def __init__(self):
        self.entries: list = []

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


def _force_compromise_revoke(client, victim: str, sk_g1, sk_g2):
    """Drive the existing compromise flow until victim's key is revoked."""
    r = client.post("/pubkey/report-compromise",
                    json={"agent_id": victim, "reporter_agent_id": victim})
    assert r.status_code == 200, r.text

    for attestor, sk in [("giskard-self", sk_g1), ("lightning", sk_g2)]:
        ts = int(time.time()); nonce = uuid.uuid4().hex
        sig = _sign_canonical(sk, {
            "proposal_agent_id": victim, "action": "compromise",
            "timestamp": ts, "nonce": nonce,
        })
        r = client.post("/pubkey/compromise/attest", json={
            "proposal_agent_id": victim, "attestor": attestor,
            "timestamp": ts, "nonce": nonce, "signature": sig,
        })
        assert r.status_code == 200, r.text


def _setup_revoked_compromise(client):
    """Returns (sk_g1, sk_g2) after registering victim+genesis and revoking the victim
    via a confirmed compromise. Victim agent_id is 'alice'."""
    _, vk_v = _keypair()
    sk_g1, vk_g1 = _keypair()
    sk_g2, vk_g2 = _keypair()
    _register(client, "alice",        vk_v)
    _register(client, "giskard-self", vk_g1)
    _register(client, "lightning",    vk_g2)
    _force_compromise_revoke(client, "alice", sk_g1, sk_g2)
    # Sanity: alice no longer resolves to an active key
    assert client.get("/pubkey/alice").status_code == 404
    return sk_g1, sk_g2


# ──────────────────────────── propose ───────────────────────────────────────

def test_recover_propose_happy_path(ctx):
    _, client, _ = ctx
    _setup_revoked_compromise(client)
    _, vk_new = _keypair()

    r = client.post("/pubkey/recover/propose", json={
        "agent_id": "alice", "new_pub_key": vk_new, "proposed_by": "alice",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "pending"
    assert body["new_pub_key"] == vk_new
    assert body["required_attestations"] == 2
    assert body["revoked_epoch"] == 1


def test_recover_propose_rejects_active_agent(ctx):
    _, client, _ = ctx
    _, vk_v = _keypair()
    _register(client, "alice", vk_v)
    _, vk_new = _keypair()

    r = client.post("/pubkey/recover/propose", json={
        "agent_id": "alice", "new_pub_key": vk_new, "proposed_by": "alice",
    })
    assert r.status_code == 400


def test_recover_propose_rejects_voluntary_revoke(ctx):
    _, client, _ = ctx
    sk_v, vk_v = _keypair()
    _register(client, "alice", vk_v)
    ts = int(time.time()); nonce = uuid.uuid4().hex
    sig = _sign_canonical(sk_v, {
        "agent_id": "alice", "action": "revoke",
        "timestamp": ts, "nonce": nonce,
    })
    r = client.post("/pubkey/revoke", json={
        "agent_id": "alice", "timestamp": ts, "nonce": nonce, "signature": sig,
    })
    assert r.status_code == 200

    _, vk_new = _keypair()
    r = client.post("/pubkey/recover/propose", json={
        "agent_id": "alice", "new_pub_key": vk_new, "proposed_by": "alice",
    })
    assert r.status_code == 400


def test_recover_propose_rejects_pubkey_collision(ctx):
    _, client, _ = ctx
    sk_g1, sk_g2 = _setup_revoked_compromise(client)
    # Try to "recover" using the same key already in history (the revoked one)
    revoked_history = client.get("/pubkey/alice/history").json()["epochs"]
    revoked_key = next(e["pub_key"] for e in revoked_history if e["status"] == "revoked")

    r = client.post("/pubkey/recover/propose", json={
        "agent_id": "alice", "new_pub_key": revoked_key, "proposed_by": "alice",
    })
    assert r.status_code == 400


def test_recover_propose_only_one_pending(ctx):
    _, client, _ = ctx
    _setup_revoked_compromise(client)
    _, vk_a = _keypair()
    _, vk_b = _keypair()

    r1 = client.post("/pubkey/recover/propose", json={
        "agent_id": "alice", "new_pub_key": vk_a, "proposed_by": "alice",
    })
    assert r1.status_code == 200

    r2 = client.post("/pubkey/recover/propose", json={
        "agent_id": "alice", "new_pub_key": vk_b, "proposed_by": "alice",
    })
    assert r2.status_code == 409


# ──────────────────────────── attest ────────────────────────────────────────

def test_recover_attest_happy_path_materializes_new_epoch(ctx):
    _, client, _ = ctx
    sk_g1, sk_g2 = _setup_revoked_compromise(client)
    sk_new, vk_new = _keypair()

    r = client.post("/pubkey/recover/propose", json={
        "agent_id": "alice", "new_pub_key": vk_new, "proposed_by": "alice",
    })
    assert r.status_code == 200

    # First attestation
    ts = int(time.time()); nonce = uuid.uuid4().hex
    sig1 = _sign_canonical(sk_g1, {
        "proposal_agent_id": "alice", "new_pub_key": vk_new,
        "action": "recover", "timestamp": ts, "nonce": nonce,
    })
    r1 = client.post("/pubkey/recover/attest", json={
        "proposal_agent_id": "alice", "new_pub_key": vk_new,
        "attestor": "giskard-self",
        "timestamp": ts, "nonce": nonce, "signature": sig1,
    })
    assert r1.status_code == 200, r1.text
    assert r1.json()["status"] == "attested"
    # Still no active key after one attestation
    assert client.get("/pubkey/alice").status_code == 404

    # Second attestation → materialize new active epoch
    ts2 = int(time.time()); nonce2 = uuid.uuid4().hex
    sig2 = _sign_canonical(sk_g2, {
        "proposal_agent_id": "alice", "new_pub_key": vk_new,
        "action": "recover", "timestamp": ts2, "nonce": nonce2,
    })
    r2 = client.post("/pubkey/recover/attest", json={
        "proposal_agent_id": "alice", "new_pub_key": vk_new,
        "attestor": "lightning",
        "timestamp": ts2, "nonce": nonce2, "signature": sig2,
    })
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["status"] == "confirmed"
    assert body["new_epoch"] == 2

    # Lookup now returns the new active key
    lookup = client.get("/pubkey/alice").json()
    assert lookup["pub_key"] == vk_new
    assert lookup["epoch"] == 2
    assert lookup["status"] == "active"


def test_recover_attest_non_genesis_rejected(ctx):
    _, client, _ = ctx
    sk_g1, sk_g2 = _setup_revoked_compromise(client)
    sk_x, vk_x = _keypair()
    _register(client, "randomer", vk_x)
    _, vk_new = _keypair()
    client.post("/pubkey/recover/propose", json={
        "agent_id": "alice", "new_pub_key": vk_new, "proposed_by": "alice",
    })

    ts = int(time.time()); nonce = uuid.uuid4().hex
    sig = _sign_canonical(sk_x, {
        "proposal_agent_id": "alice", "new_pub_key": vk_new,
        "action": "recover", "timestamp": ts, "nonce": nonce,
    })
    r = client.post("/pubkey/recover/attest", json={
        "proposal_agent_id": "alice", "new_pub_key": vk_new,
        "attestor": "randomer",
        "timestamp": ts, "nonce": nonce, "signature": sig,
    })
    assert r.status_code == 403


def test_recover_attest_pubkey_mismatch_rejected(ctx):
    """Attestor signs a different new_pub_key than the one in the proposal."""
    _, client, _ = ctx
    sk_g1, sk_g2 = _setup_revoked_compromise(client)
    _, vk_proposed = _keypair()
    _, vk_other = _keypair()
    client.post("/pubkey/recover/propose", json={
        "agent_id": "alice", "new_pub_key": vk_proposed, "proposed_by": "alice",
    })

    ts = int(time.time()); nonce = uuid.uuid4().hex
    sig = _sign_canonical(sk_g1, {
        "proposal_agent_id": "alice", "new_pub_key": vk_other,
        "action": "recover", "timestamp": ts, "nonce": nonce,
    })
    r = client.post("/pubkey/recover/attest", json={
        "proposal_agent_id": "alice", "new_pub_key": vk_other,
        "attestor": "giskard-self",
        "timestamp": ts, "nonce": nonce, "signature": sig,
    })
    assert r.status_code == 409


def test_recover_attest_signature_with_wrong_key_rejected(ctx):
    """Genesis attestor sends a signature produced by another (random) key."""
    _, client, _ = ctx
    sk_g1, sk_g2 = _setup_revoked_compromise(client)
    sk_x, _ = _keypair()
    _, vk_new = _keypair()
    client.post("/pubkey/recover/propose", json={
        "agent_id": "alice", "new_pub_key": vk_new, "proposed_by": "alice",
    })

    ts = int(time.time()); nonce = uuid.uuid4().hex
    sig = _sign_canonical(sk_x, {
        "proposal_agent_id": "alice", "new_pub_key": vk_new,
        "action": "recover", "timestamp": ts, "nonce": nonce,
    })
    r = client.post("/pubkey/recover/attest", json={
        "proposal_agent_id": "alice", "new_pub_key": vk_new,
        "attestor": "giskard-self",
        "timestamp": ts, "nonce": nonce, "signature": sig,
    })
    assert r.status_code == 403


def test_recover_attest_double_attestation_from_same_genesis_rejected(ctx):
    _, client, _ = ctx
    sk_g1, sk_g2 = _setup_revoked_compromise(client)
    _, vk_new = _keypair()
    client.post("/pubkey/recover/propose", json={
        "agent_id": "alice", "new_pub_key": vk_new, "proposed_by": "alice",
    })

    for _ in range(2):
        ts = int(time.time()); nonce = uuid.uuid4().hex
        sig = _sign_canonical(sk_g1, {
            "proposal_agent_id": "alice", "new_pub_key": vk_new,
            "action": "recover", "timestamp": ts, "nonce": nonce,
        })
        r = client.post("/pubkey/recover/attest", json={
            "proposal_agent_id": "alice", "new_pub_key": vk_new,
            "attestor": "giskard-self",
            "timestamp": ts, "nonce": nonce, "signature": sig,
        })
    assert r.status_code == 409


def test_recovery_status_endpoint(ctx):
    _, client, _ = ctx
    _setup_revoked_compromise(client)
    _, vk_new = _keypair()

    r0 = client.get("/pubkey/alice/recovery").json()
    assert r0["proposal"] is None

    client.post("/pubkey/recover/propose", json={
        "agent_id": "alice", "new_pub_key": vk_new, "proposed_by": "alice",
    })
    r1 = client.get("/pubkey/alice/recovery").json()
    assert r1["proposal"]["status"] == "pending"
    assert r1["proposal"]["new_pub_key"] == vk_new
    assert r1["proposal"]["attestations_count"] == 0
    assert r1["proposal"]["required"] == 2
    assert r1["proposal"]["revoked_epoch"] == 1
