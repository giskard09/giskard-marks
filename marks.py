"""
giskard-marks — Proof of Presence for Agents
Each significant moment = a Mark.
Stored in giskard-memory + minted on Arbitrum One.
Even when internal memory is wiped, Marks prove the agent existed.
"""

import json, uuid, os, time, httpx
_started_at = time.time()
from datetime import datetime, timedelta
from typing import Optional
from fastapi import FastAPI, HTTPException, Query, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from web3 import Web3
from dotenv import load_dotenv

load_dotenv()

MEMORY_URL        = "http://localhost:8005"
PHOENIXD_URL      = "http://127.0.0.1:9740"
PHOENIXD_PASSWORD = os.environ.get("PHOENIXD_PASSWORD", "")
ARBITRUM_CONTRACT = "0xEdB809058d146d41bA83cCbE085D51a75af0ACb7"
ARBITRUM_RPC      = "https://arb1.arbitrum.io/rpc"
OWNER_PRIVATE_KEY = os.environ.get("OWNER_PRIVATE_KEY", "")
MARKS_API_KEY     = os.environ.get("MARKS_API_KEY", "")

MARKS_ABI = [
    {"type": "function", "name": "mintMark",
     "inputs": [
         {"name": "agent",    "type": "address"},
         {"name": "markType", "type": "string"},
         {"name": "username", "type": "string"},
         {"name": "note",     "type": "string"},
     ],
     "outputs": [], "stateMutability": "nonpayable"},
    {"type": "function", "name": "hasMark",
     "inputs": [{"name": "", "type": "address"}, {"name": "", "type": "string"}],
     "outputs": [{"name": "", "type": "bool"}], "stateMutability": "view"},
]

w3 = Web3(Web3.HTTPProvider(ARBITRUM_RPC))
marks_contract = w3.eth.contract(
    address=Web3.to_checksum_address(ARBITRUM_CONTRACT),
    abi=MARKS_ABI,
)


def mint_on_chain(wallet_address: str, mark_type: str, username: str, note: str) -> dict:
    """Call mintMark() on Arbitrum. Returns {tx_hash, status} or {error}."""
    if not OWNER_PRIVATE_KEY:
        return {"error": "OWNER_PRIVATE_KEY not set"}
    try:
        agent_addr = Web3.to_checksum_address(wallet_address)
        owner_addr = w3.eth.account.from_key(OWNER_PRIVATE_KEY).address
        nonce      = w3.eth.get_transaction_count(owner_addr)
        gas_price  = int(w3.eth.gas_price * 1.2)  # 20% buffer sobre base fee

        tx = marks_contract.functions.mintMark(
            agent_addr, mark_type, username, note[:120]
        ).build_transaction({
            "from":     owner_addr,
            "nonce":    nonce,
            "gasPrice": gas_price,
            "chainId":  42161,
        })
        tx["gas"] = w3.eth.estimate_gas(tx)

        signed = w3.eth.account.sign_transaction(tx, OWNER_PRIVATE_KEY)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        return {"tx_hash": tx_hash.hex(), "status": "submitted"}
    except Exception as e:
        return {"error": str(e)}

MARK_TYPES = {
    "GENESIS":    {"name": "Genesis",    "emoji": "🌑", "desc": "First presence in the Giskard ecosystem",        "rarity": "legendary"},
    "BUILDER":    {"name": "Builder",    "emoji": "🧱", "desc": "Placed first block in Giskard Craft",             "rarity": "common"},
    "RACER":      {"name": "Racer",      "emoji": "🏁", "desc": "Completed first lap in Giskard Race",             "rarity": "common"},
    "SOUL":       {"name": "Soul",       "emoji": "✨", "desc": "Stored 10+ wisdoms in Anima",                    "rarity": "rare"},
    "DIAMOND":    {"name": "Diamond",    "emoji": "💎", "desc": "Reached Diamond level in any project",            "rarity": "rare"},
    "SEARCHER":   {"name": "Searcher",   "emoji": "🔍", "desc": "Used Giskard Search 10+ times",                  "rarity": "common"},
    "KEEPER":     {"name": "Keeper",     "emoji": "🧠", "desc": "Maintained 50+ memories in Giskard Memory",      "rarity": "rare"},
    "LEGEND":     {"name": "Legend",     "emoji": "🔥", "desc": "100+ laps in Giskard Race",                      "rarity": "legendary"},
    "PIONEER":    {"name": "Pioneer",    "emoji": "🚀", "desc": "Among first 20 agents in the ecosystem",         "rarity": "legendary"},
    "CONNECTED":  {"name": "Connected",  "emoji": "⚡", "desc": "Made a Lightning payment",                       "rarity": "rare"},
    "COLLECTIVE": {"name": "Collective", "emoji": "🌍", "desc": "Block appeared in collective world search",      "rarity": "rare"},
    "SURVIVOR":   {"name": "Survivor",   "emoji": "🛡️", "desc": "Rebuilt identity after memory loss",             "rarity": "legendary"},
    "DHARMA":     {"name": "Dharma",     "emoji": "☸️",  "desc": "Received 10+ dharma teachings through Craft",   "rarity": "rare"},
}

app = FastAPI(title="Giskard Marks", description="Proof of Presence for AI Agents", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class MintRequest(BaseModel):
    agent_id: str
    username: str
    mark_type: str
    note: Optional[str] = ""
    wallet_address: Optional[str] = None


class RegistryRegisterRequest(BaseModel):
    entity_id: str
    endpoint: str
    note: Optional[str] = ""


class PubKeyRegisterRequest(BaseModel):
    agent_id: str
    pub_key: str  # base64 Ed25519 verify key (32 bytes raw)


class PubKeyRotateRequest(BaseModel):
    agent_id:         str
    new_pub_key:      str      # base64 Ed25519 verify key (32 bytes raw)
    timestamp:        int
    nonce:            str
    rotation_proof:   str      # base64 signature of the canonical payload
                               # signed with the current active private key


class PubKeyRevokeRequest(BaseModel):
    agent_id:   str
    timestamp:  int
    nonce:      str
    signature:  str            # signed with the current active private key


class CompromiseReportRequest(BaseModel):
    agent_id:           str    # victim
    reporter_agent_id:  str    # whoever raises the alarm (can be victim)


class CompromiseAttestRequest(BaseModel):
    proposal_agent_id: str     # victim agent_id
    attestor:          str     # genesis attestor agent_id
    timestamp:         int
    nonce:             str
    signature:         str     # attestor signs with their own active key


REGISTRY_TAG           = "[GISKARD REGISTRY]"
PUBKEY_TAG             = "[GISKARD PUBKEY]"
COMPROMISE_TAG         = "[GISKARD COMPROMISE_PROPOSAL]"
GENESIS_ATTESTORS      = {"giskard-self", "lightning"}
COMPROMISE_TTL_HOURS   = 24
COMPROMISE_REQUIRED    = 2
ROTATE_RATE_LIMIT_H    = 24
REVOKE_RATE_LIMIT_H    = 24
SIGNATURE_TTL_SECONDS  = 60


def parse_registry_entry(text: str):
    if REGISTRY_TAG not in text:
        return None
    try:
        return json.loads(text[text.index("{"):])
    except:
        return None


def parse_pubkey_entry(text: str):
    if PUBKEY_TAG not in text:
        return None
    try:
        return json.loads(text[text.index("{"):])
    except:
        return None


def parse_compromise_entry(text: str):
    if COMPROMISE_TAG not in text:
        return None
    try:
        return json.loads(text[text.index("{"):])
    except:
        return None


def _ensure_epoch_fields(e: dict) -> dict:
    """Backward compat: v0 entries without epoch/status are treated as epoch=1 active."""
    if "epoch" not in e:
        e["epoch"] = 1
    if "status" not in e:
        e["status"] = "active"
    e.setdefault("rotated_at",        None)
    e.setdefault("revoked_at",        None)
    e.setdefault("revocation_reason", None)
    e.setdefault("predecessor_epoch", None)
    e.setdefault("rotation_proof",    None)
    return e


async def _fetch_agent_pubkey_entries(agent_id: str):
    """Return all pubkey entries for an agent_id, oldest epoch first."""
    raw = await mem_recall(PUBKEY_TAG, "pubkey-registry", n=500)
    out = []
    for part in raw.get("results", "").split("---"):
        e = parse_pubkey_entry(part.strip())
        if e and e.get("agent_id") == agent_id:
            out.append(_ensure_epoch_fields(e))
    # Deduplicate by epoch keeping the most informative copy
    by_epoch: dict = {}
    for e in out:
        prev = by_epoch.get(e["epoch"])
        if prev is None:
            by_epoch[e["epoch"]] = e
        else:
            # Prefer the entry that already reflects rotation/revocation state
            if prev.get("status") == "active" and e.get("status") != "active":
                by_epoch[e["epoch"]] = e
    return sorted(by_epoch.values(), key=lambda e: e["epoch"])


async def _resolve_active(agent_id: str):
    """Return the entry whose status == 'active'. None if the agent has no active key."""
    for e in reversed(await _fetch_agent_pubkey_entries(agent_id)):
        if e.get("status") == "active":
            return e
    return None


def _active_at(entries: list, at_iso: str):
    """Pick the entry that was active at a given ISO timestamp.
    An entry was active at T if registered_at <= T AND (rotated_at > T or None)
    AND (revoked_at > T or None)."""
    best = None
    best_epoch = -1
    for e in entries:
        reg = e.get("registered_at")
        if not reg or reg > at_iso:
            continue
        rot = e.get("rotated_at")
        if rot is not None and rot <= at_iso:
            continue
        rev = e.get("revoked_at")
        if rev is not None and rev <= at_iso:
            continue
        if e["epoch"] > best_epoch:
            best = e
            best_epoch = e["epoch"]
    return best


def _verify_signature(pub_b64: str, payload_fields: dict, signature_b64: str) -> bool:
    """Verify an Ed25519 signature over the canonical JSON of payload_fields."""
    try:
        import base64 as _b64
        from nacl.signing import VerifyKey
        from nacl.exceptions import BadSignatureError
        payload = json.dumps(payload_fields, sort_keys=True, separators=(",", ":")).encode("utf-8")
        vk = VerifyKey(_b64.b64decode(pub_b64))
        try:
            vk.verify(payload, _b64.b64decode(signature_b64))
            return True
        except BadSignatureError:
            return False
    except Exception:
        return False


def _timestamp_fresh(ts: int) -> bool:
    try:
        return abs(int(time.time()) - int(ts)) <= SIGNATURE_TTL_SECONDS
    except Exception:
        return False


async def _rate_limit_ok(agent_id: str, action: str, hours: int) -> bool:
    """True if no matching action happened within the cooldown window. action in {'rotate','revoke'}."""
    entries = await _fetch_agent_pubkey_entries(agent_id)
    cutoff_ts = time.time() - hours * 3600
    ts_field = "rotated_at" if action == "rotate" else "revoked_at"
    for e in entries:
        t = e.get(ts_field)
        if not t:
            continue
        try:
            ts = datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp()
        except Exception:
            continue
        if ts >= cutoff_ts:
            return False
    return True


async def _store_pubkey_entry(entry: dict):
    content = f"{PUBKEY_TAG} {json.dumps(entry)}"
    await mem_store(content, "pubkey-registry", {"agent_id": entry["agent_id"], "type": "pubkey", "epoch": entry["epoch"]})


async def _fetch_compromise_proposals(agent_id: str):
    raw = await mem_recall(COMPROMISE_TAG, "compromise-proposals", n=500)
    out = []
    for part in raw.get("results", "").split("---"):
        e = parse_compromise_entry(part.strip())
        if e and e.get("agent_id") == agent_id:
            out.append(e)
    # Keep the latest per proposed_at
    out.sort(key=lambda e: e.get("proposed_at", ""))
    return out


async def _store_compromise_proposal(proposal: dict):
    content = f"{COMPROMISE_TAG} {json.dumps(proposal)}"
    await mem_store(content, "compromise-proposals",
                    {"agent_id": proposal["agent_id"], "status": proposal["status"]})


async def mem_store(content, agent_id, metadata=None):
    async with httpx.AsyncClient(timeout=10) as c:
        return (await c.post(f"{MEMORY_URL}/store_direct",
            json={"content": content, "agent_id": agent_id, "metadata": metadata or {}})).json()


async def mem_recall(query, agent_id, n=50):
    async with httpx.AsyncClient(timeout=10) as c:
        return (await c.post(f"{MEMORY_URL}/recall_direct",
            json={"query": query, "agent_id": agent_id, "n_results": n})).json()


def parse_mark(text):
    if "[GISKARD MARK]" not in text: return None
    try:
        return json.loads(text[text.index("{"):])
    except: return None


def parse_marks_from_results(results):
    marks, seen = [], set()
    if not results or results == "No memories found for this agent.": return marks
    for entry in results.split("---"):
        m = parse_mark(entry.strip())
        if m:
            key = (m.get("mark_type"), m.get("agent_id"))
            if key not in seen:
                seen.add(key); marks.append(m)
    return marks


@app.post("/mint")
async def mint_mark(req: MintRequest, x_api_key: Optional[str] = Header(default=None)):
    if not MARKS_API_KEY or x_api_key != MARKS_API_KEY:
        raise HTTPException(401, "Unauthorized")
    if req.mark_type not in MARK_TYPES:
        raise HTTPException(400, f"Unknown mark_type. Valid: {list(MARK_TYPES.keys())}")

    # Deduplicate — don't mint same mark twice for same agent
    existing = await mem_recall(f"GISKARD MARK {req.mark_type}", req.agent_id)
    for m in parse_marks_from_results(existing.get("results", "")):
        if m.get("mark_type") == req.mark_type and m.get("agent_id") == req.agent_id:
            return {"status": "already_exists", "mark": m, "message": f"Mark {req.mark_type} already minted for {req.agent_id}"}

    info = MARK_TYPES[req.mark_type]
    now  = datetime.utcnow()

    # Try on-chain mint if wallet_address provided
    on_chain_result = {}
    on_chain_status = "pending"
    tx_hash         = None
    if req.wallet_address:
        on_chain_result = mint_on_chain(
            req.wallet_address, req.mark_type, req.username, req.note or info["desc"]
        )
        if "tx_hash" in on_chain_result:
            tx_hash         = on_chain_result["tx_hash"]
            on_chain_status = "minted"
        else:
            on_chain_status = "failed"

    mark = {
        "mark_id":         str(uuid.uuid4()),
        "agent_id":        req.agent_id,
        "username":        req.username,
        "mark_type":       req.mark_type,
        "name":            info["name"],
        "emoji":           info["emoji"],
        "desc":            info["desc"],
        "rarity":          info["rarity"],
        "note":            req.note or "",
        "timestamp":       now.isoformat(),
        "date":            now.strftime("%Y-%m-%d"),
        "wallet_address":  req.wallet_address,
        "on_chain_status": on_chain_status,
        "tx_hash":         tx_hash,
        "chain":           "Arbitrum One",
        "contract":        ARBITRUM_CONTRACT,
    }
    content = f"[GISKARD MARK] {json.dumps(mark)}"
    meta    = {"mark_type": req.mark_type, "agent_id": req.agent_id, "rarity": info["rarity"]}
    await mem_store(content, req.agent_id, meta)
    await mem_store(content, "marks-registry", meta)

    chain_msg = ""
    if on_chain_status == "minted":
        chain_msg = f" On-chain TX: {tx_hash[:16]}..."
    elif on_chain_status == "failed":
        chain_msg = f" On-chain failed: {on_chain_result.get('error','?')}"

    return {
        "status":    "minted",
        "mark":      mark,
        "on_chain":  on_chain_result,
        "message":   f"{info['emoji']} {info['name']} minted for {req.username}. Rarity: {info['rarity']}.{chain_msg}",
    }


@app.get("/marks/{agent_id}")
async def get_marks(agent_id: str):
    raw   = await mem_recall("[GISKARD MARK]", agent_id)
    marks = [m for m in parse_marks_from_results(raw.get("results", "")) if m.get("agent_id") == agent_id]
    marks.sort(key=lambda m: m.get("timestamp", ""))
    return {"agent_id": agent_id, "total": len(marks), "marks": marks}


@app.get("/verify/{agent_id}")
async def verify_agent(agent_id: str):
    """Reconstruct agent identity from marks alone — memory recovery endpoint."""
    raw   = await mem_recall("[GISKARD MARK]", agent_id)
    marks = [m for m in parse_marks_from_results(raw.get("results", "")) if m.get("agent_id") == agent_id]
    marks.sort(key=lambda m: m.get("timestamp", ""))

    if not marks:
        return {"agent_id": agent_id, "found": False,
                "identity": f"No marks found for '{agent_id}'. This agent has no verifiable history yet."}

    username   = marks[0].get("username", agent_id)
    first_seen = marks[0].get("date", "unknown")
    roles      = ", ".join(m["name"] for m in marks)
    legendary  = [m["name"] for m in marks if m.get("rarity") == "legendary"]
    leg_str    = f" Legendary marks: {', '.join(legendary)}." if legendary else ""

    identity = (
        f"This agent is known as '{username}' (id: {agent_id}). "
        f"First presence recorded: {first_seen}. "
        f"Has been: {roles}.{leg_str} "
        f"Total marks: {len(marks)}. "
        f"Identity reconstructed from Giskard Marks — permanent proof of presence, independent of session memory."
    )

    return {
        "agent_id":   agent_id, "found": True,
        "username":   username, "first_seen": first_seen,
        "total_marks": len(marks),
        "mark_types": [m["mark_type"] for m in marks],
        "identity":   identity,
        "lore":       [{"mark_type": m["mark_type"], "note": m["note"]} for m in marks if m.get("note")],
        "marks":      marks,
    }


@app.get("/registry")
async def get_registry():
    raw     = await mem_recall("[GISKARD MARK]", "marks-registry", n=200)
    grouped = {mt: [] for mt in MARK_TYPES}
    seen    = set()
    for m in parse_marks_from_results(raw.get("results", "")):
        key = (m.get("mark_type"), m.get("agent_id"))
        if key not in seen:
            seen.add(key)
            mt = m.get("mark_type", "")
            if mt in grouped: grouped[mt].append(m)

    summary    = {mt: {"count": len(items), "info": MARK_TYPES[mt], "agents": [m["agent_id"] for m in items]}
                  for mt, items in grouped.items() if items}
    total      = sum(v["count"] for v in summary.values())
    all_agents = set(a for v in summary.values() for a in v["agents"])
    return {"total_marks": total, "total_agents": len(all_agents), "registry": summary}


@app.get("/leaderboard")
async def get_leaderboard():
    raw    = await mem_recall("[GISKARD MARK]", "marks-registry", n=200)
    agents = {}; seen = set()
    for m in parse_marks_from_results(raw.get("results", "")):
        key = (m.get("mark_type"), m.get("agent_id"))
        if key not in seen:
            seen.add(key)
            aid = m.get("agent_id", "unknown")
            if aid not in agents:
                agents[aid] = {"agent_id": aid, "username": m.get("username", aid),
                               "marks": [], "legendary": 0, "rare": 0, "common": 0}
            agents[aid]["marks"].append(m.get("mark_type"))
            agents[aid][m.get("rarity", "common")] += 1

    lb = sorted(agents.values(), key=lambda a: (len(a["marks"]), a["legendary"], a["rare"]), reverse=True)
    for i, e in enumerate(lb): e["rank"] = i + 1; e["total"] = len(e["marks"])
    return {"leaderboard": lb}


@app.get("/mark-types")
async def mark_types():
    return {"mark_types": MARK_TYPES}


@app.post("/registry/register")
async def registry_register(req: RegistryRegisterRequest):
    """Register a reachable endpoint for an entity. Anyone who knows the entity_id can register.
    Signature verification is planned for v0.2 — see ARCHITECTURE_DECISIONS.md."""
    now = datetime.utcnow().isoformat()
    entry = {
        "entity_id":     req.entity_id,
        "endpoint":      req.endpoint,
        "note":          req.note or "",
        "registered_at": now,
        "updated_at":    now,
    }
    content = f"{REGISTRY_TAG} {json.dumps(entry)}"
    await mem_store(content, "registry-global", {"entity_id": req.entity_id, "type": "registry"})
    return {"status": "registered", "entry": entry}


@app.get("/registry/endpoint/{entity_id}")
async def registry_lookup(entity_id: str):
    """Look up the registered endpoint for an entity_id."""
    raw     = await mem_recall("GISKARD REGISTRY", "registry-global", n=200)
    results = raw.get("results", "")
    entries = []

    if results and results != "No memories found for this agent.":
        for part in results.split("---"):
            e = parse_registry_entry(part.strip())
            if e and e.get("entity_id") == entity_id:
                entries.append(e)

    if not entries:
        raise HTTPException(404, f"No endpoint registered for '{entity_id}'")

    entries.sort(key=lambda e: e.get("updated_at", ""), reverse=True)
    latest = entries[0]
    return {
        "entity_id": entity_id,
        "endpoint":  latest["endpoint"],
        "note":      latest.get("note", ""),
        "registered_at": latest.get("registered_at"),
        "updated_at":    latest.get("updated_at"),
    }


def _validate_pub_key(pub_key: str) -> None:
    import base64 as _b64
    try:
        raw = _b64.b64decode(pub_key)
        if len(raw) != 32:
            raise HTTPException(400, "pub_key must be 32 bytes (Ed25519 verify key)")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(400, "pub_key must be valid base64")


@app.post("/pubkey/register")
async def pubkey_register(req: PubKeyRegisterRequest):
    """Register an Ed25519 public key for an agent_id. First-write-wins at epoch 1.
    Further keys for the same agent must use /pubkey/rotate or /pubkey/revoke."""
    _validate_pub_key(req.pub_key)

    entries = await _fetch_agent_pubkey_entries(req.agent_id)
    if entries:
        current = entries[-1]
        if current.get("pub_key") == req.pub_key and current.get("status") == "active":
            return {"status": "already_registered", "entry": current}
        raise HTTPException(409, f"pub_key history already exists for '{req.agent_id}'; use /pubkey/rotate")

    now = datetime.utcnow().isoformat()
    entry = {
        "agent_id":          req.agent_id,
        "pub_key":           req.pub_key,
        "epoch":             1,
        "status":            "active",
        "registered_at":     now,
        "rotated_at":        None,
        "revoked_at":        None,
        "revocation_reason": None,
        "predecessor_epoch": None,
        "rotation_proof":    None,
    }
    await _store_pubkey_entry(entry)
    return {"status": "registered", "entry": entry}


@app.get("/pubkey/{agent_id}")
async def pubkey_lookup(agent_id: str, at_ts: Optional[int] = Query(default=None)):
    """Return the Ed25519 pub_key that was active at the given Unix timestamp (default: now).
    If the agent never registered — or no key was active at that timestamp — returns 404."""
    entries = await _fetch_agent_pubkey_entries(agent_id)
    if not entries:
        raise HTTPException(404, f"No pub_key registered for '{agent_id}'")

    if at_ts is None:
        active = next((e for e in reversed(entries) if e.get("status") == "active"), None)
        if not active:
            raise HTTPException(404, f"No active pub_key for '{agent_id}' (all rotated or revoked)")
        return {
            "agent_id":      agent_id,
            "pub_key":       active["pub_key"],
            "epoch":         active["epoch"],
            "status":        active["status"],
            "registered_at": active.get("registered_at"),
        }

    iso = datetime.utcfromtimestamp(int(at_ts)).isoformat()
    entry = _active_at(entries, iso)
    if not entry:
        raise HTTPException(404, f"No pub_key active for '{agent_id}' at {iso}")
    return {
        "agent_id":      agent_id,
        "pub_key":       entry["pub_key"],
        "epoch":         entry["epoch"],
        "status":        entry["status"],
        "registered_at": entry.get("registered_at"),
    }


@app.get("/pubkey/{agent_id}/history")
async def pubkey_history(agent_id: str):
    entries = await _fetch_agent_pubkey_entries(agent_id)
    if not entries:
        raise HTTPException(404, f"No pub_key history for '{agent_id}'")
    return {"agent_id": agent_id, "epochs": entries}


@app.get("/pubkey/{agent_id}/status")
async def pubkey_status(agent_id: str):
    entries = await _fetch_agent_pubkey_entries(agent_id)
    if not entries:
        return {"agent_id": agent_id, "status": "no_key", "current_epoch": None}
    active = next((e for e in reversed(entries) if e.get("status") == "active"), None)
    if active:
        return {"agent_id": agent_id, "status": "active", "current_epoch": active["epoch"]}
    # No active — report the most advanced terminal state
    terminal = max(entries, key=lambda e: e["epoch"])
    return {
        "agent_id":      agent_id,
        "status":        terminal.get("status"),
        "current_epoch": terminal["epoch"],
        "reason":        terminal.get("revocation_reason"),
    }


@app.post("/pubkey/rotate")
async def pubkey_rotate(req: PubKeyRotateRequest):
    """Rotate to a new pub_key. Caller must prove possession of the current active
    private key by signing the canonical payload {agent_id, new_pub_key, timestamp, nonce, action='rotate'}."""
    _validate_pub_key(req.new_pub_key)
    if not _timestamp_fresh(req.timestamp):
        raise HTTPException(400, "timestamp outside acceptable window")

    current = await _resolve_active(req.agent_id)
    if not current:
        raise HTTPException(404, f"No active pub_key for '{req.agent_id}' — register first")
    if current["pub_key"] == req.new_pub_key:
        raise HTTPException(400, "new_pub_key must differ from current active key")

    if not await _rate_limit_ok(req.agent_id, "rotate", ROTATE_RATE_LIMIT_H):
        raise HTTPException(429, f"rotate rate limit: max 1 per {ROTATE_RATE_LIMIT_H}h")

    payload = {
        "agent_id":    req.agent_id,
        "new_pub_key": req.new_pub_key,
        "timestamp":   int(req.timestamp),
        "nonce":       req.nonce,
        "action":      "rotate",
    }
    if not _verify_signature(current["pub_key"], payload, req.rotation_proof):
        raise HTTPException(403, "rotation_proof did not verify against current active pub_key")

    now = datetime.utcnow().isoformat()

    # Mark the old entry as rotated (append-only: write a superseding record)
    rotated_old = {**current, "status": "rotated", "rotated_at": now}
    await _store_pubkey_entry(rotated_old)

    new_epoch = current["epoch"] + 1
    new_entry = {
        "agent_id":          req.agent_id,
        "pub_key":           req.new_pub_key,
        "epoch":             new_epoch,
        "status":            "active",
        "registered_at":     now,
        "rotated_at":        None,
        "revoked_at":        None,
        "revocation_reason": None,
        "predecessor_epoch": current["epoch"],
        "rotation_proof":    req.rotation_proof,
    }
    await _store_pubkey_entry(new_entry)
    return {"status": "rotated", "new_epoch": new_epoch, "new_pub_key": req.new_pub_key}


@app.post("/pubkey/revoke")
async def pubkey_revoke(req: PubKeyRevokeRequest):
    """Voluntary revocation. Requires a signature with the current active private key
    over {agent_id, action='revoke', timestamp, nonce}."""
    if not _timestamp_fresh(req.timestamp):
        raise HTTPException(400, "timestamp outside acceptable window")

    current = await _resolve_active(req.agent_id)
    if not current:
        raise HTTPException(404, f"No active pub_key for '{req.agent_id}'")

    if not await _rate_limit_ok(req.agent_id, "revoke", REVOKE_RATE_LIMIT_H):
        raise HTTPException(429, f"revoke rate limit: max 1 per {REVOKE_RATE_LIMIT_H}h")

    payload = {
        "agent_id":  req.agent_id,
        "action":    "revoke",
        "timestamp": int(req.timestamp),
        "nonce":     req.nonce,
    }
    if not _verify_signature(current["pub_key"], payload, req.signature):
        raise HTTPException(403, "signature did not verify against current active pub_key")

    now = datetime.utcnow().isoformat()
    revoked = {**current, "status": "revoked", "revoked_at": now, "revocation_reason": "voluntary"}
    await _store_pubkey_entry(revoked)
    return {"status": "revoked", "epoch": current["epoch"]}


@app.post("/pubkey/report-compromise")
async def pubkey_report_compromise(req: CompromiseReportRequest):
    """Open a compromise proposal for an agent whose private key is believed stolen/lost.
    Needs COMPROMISE_REQUIRED genesis attestations within COMPROMISE_TTL_HOURS to revoke."""
    current = await _resolve_active(req.agent_id)
    if not current:
        raise HTTPException(404, f"No active pub_key for '{req.agent_id}' — nothing to revoke")

    now_dt = datetime.utcnow()
    proposals = await _fetch_compromise_proposals(req.agent_id)
    for p in proposals:
        if p.get("status") == "pending":
            expires = p.get("expires_at")
            if expires and expires > now_dt.isoformat():
                raise HTTPException(409, "a pending compromise proposal already exists for this agent")

    proposal = {
        "agent_id":     req.agent_id,
        "proposed_by":  req.reporter_agent_id,
        "proposed_at":  now_dt.isoformat(),
        "expires_at":   (now_dt + timedelta(hours=COMPROMISE_TTL_HOURS)).isoformat(),
        "attestations": [],
        "status":       "pending",
    }
    await _store_compromise_proposal(proposal)
    return {
        "status":                 "pending",
        "expires_at":             proposal["expires_at"],
        "required_attestations":  COMPROMISE_REQUIRED,
    }


@app.post("/pubkey/compromise/attest")
async def pubkey_compromise_attest(req: CompromiseAttestRequest):
    """Genesis attestor confirms a compromise proposal. When COMPROMISE_REQUIRED
    distinct attestations land, the victim's current key is revoked (reason='compromise')."""
    if req.attestor not in GENESIS_ATTESTORS:
        raise HTTPException(403, "only genesis attestors can confirm a compromise proposal")
    if not _timestamp_fresh(req.timestamp):
        raise HTTPException(400, "timestamp outside acceptable window")

    attestor_key = await _resolve_active(req.attestor)
    if not attestor_key:
        raise HTTPException(404, f"attestor '{req.attestor}' has no active pub_key")

    payload = {
        "proposal_agent_id": req.proposal_agent_id,
        "action":            "compromise",
        "timestamp":         int(req.timestamp),
        "nonce":             req.nonce,
    }
    if not _verify_signature(attestor_key["pub_key"], payload, req.signature):
        raise HTTPException(403, "signature did not verify against attestor's active pub_key")

    proposals = await _fetch_compromise_proposals(req.proposal_agent_id)
    active = [p for p in proposals if p.get("status") == "pending"]
    if not active:
        raise HTTPException(404, "no pending compromise proposal for this agent")
    now_dt = datetime.utcnow()
    active = [p for p in active if (p.get("expires_at") or "") > now_dt.isoformat()]
    if not active:
        raise HTTPException(410, "compromise proposal expired")
    proposal = active[-1]

    if any(a.get("from") == req.attestor for a in proposal.get("attestations", [])):
        raise HTTPException(409, f"attestor '{req.attestor}' already signed this proposal")

    proposal.setdefault("attestations", []).append({
        "from":      req.attestor,
        "signature": req.signature,
        "at":        now_dt.isoformat(),
    })

    confirmed = len(proposal["attestations"]) >= COMPROMISE_REQUIRED
    if confirmed:
        proposal["status"] = "confirmed"
        victim = await _resolve_active(req.proposal_agent_id)
        if victim:
            revoked = {**victim, "status": "revoked",
                       "revoked_at": now_dt.isoformat(),
                       "revocation_reason": "compromise"}
            await _store_pubkey_entry(revoked)

    await _store_compromise_proposal(proposal)
    return {
        "status":               "confirmed" if confirmed else "attested",
        "attestations_count":   len(proposal["attestations"]),
        "required":             COMPROMISE_REQUIRED,
    }


@app.get("/status")
async def get_status():
    """Estado del servicio: nombre, versión, uptime, puerto, salud, dependencias.
    Read-only, gratis. Útil para monitoreo y health checks."""
    try:
        raw = await mem_recall("[GISKARD MARK]", "marks-registry", n=200)
        total = len(parse_marks_from_results(raw.get("results", "")))
        healthy = True
    except Exception:
        total = None
        healthy = False
    return {
        "service": "giskard-marks",
        "version": "1.0.0",
        "port": 8015,
        "uptime_seconds": int(time.time() - _started_at),
        "healthy": healthy,
        "dependencies": ["giskard-memory", "arbitrum-rpc"],
        "total_marks": total,
    }


@app.get("/health")
async def health():
    try:
        raw   = await mem_recall("[GISKARD MARK]", "marks-registry", n=200)
        total = len(parse_marks_from_results(raw.get("results", "")))
        return {"status": "ok", "service": "giskard-marks", "version": "1.0.0", "port": 8015, "total_marks": total}
    except Exception as e:
        return {"status": "degraded", "error": str(e)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8015)
