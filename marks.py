"""
giskard-marks — Proof of Presence for Agents
Each significant moment = a Mark.
Stored in giskard-memory + minted on Arbitrum One.
Even when internal memory is wiped, Marks prove the agent existed.
"""

import json, uuid, os, time, httpx
_started_at = time.time()
from datetime import datetime
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


REGISTRY_TAG = "[GISKARD REGISTRY]"
PUBKEY_TAG   = "[GISKARD PUBKEY]"


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


@app.post("/pubkey/register")
async def pubkey_register(req: PubKeyRegisterRequest):
    """Register an Ed25519 public key for an agent_id. First-write-wins:
    once registered, the key is permanent (rotation is a future concern).
    Used by karma_pricing.py to verify signed requests."""
    import base64 as _b64
    try:
        raw = _b64.b64decode(req.pub_key)
        if len(raw) != 32:
            raise HTTPException(400, "pub_key must be 32 bytes (Ed25519 verify key)")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(400, "pub_key must be valid base64")

    existing_raw = await mem_recall(PUBKEY_TAG, "pubkey-registry", n=500)
    for part in existing_raw.get("results", "").split("---"):
        e = parse_pubkey_entry(part.strip())
        if e and e.get("agent_id") == req.agent_id:
            if e.get("pub_key") == req.pub_key:
                return {"status": "already_registered", "entry": e}
            raise HTTPException(409, f"pub_key already registered for '{req.agent_id}'")

    now = datetime.utcnow().isoformat()
    entry = {"agent_id": req.agent_id, "pub_key": req.pub_key, "registered_at": now}
    content = f"{PUBKEY_TAG} {json.dumps(entry)}"
    await mem_store(content, "pubkey-registry", {"agent_id": req.agent_id, "type": "pubkey"})
    return {"status": "registered", "entry": entry}


@app.get("/pubkey/{agent_id}")
async def pubkey_lookup(agent_id: str):
    """Return the Ed25519 pub_key registered for this agent_id, or 404."""
    raw = await mem_recall(PUBKEY_TAG, "pubkey-registry", n=500)
    for part in raw.get("results", "").split("---"):
        e = parse_pubkey_entry(part.strip())
        if e and e.get("agent_id") == agent_id:
            return {"agent_id": agent_id, "pub_key": e["pub_key"], "registered_at": e.get("registered_at")}
    raise HTTPException(404, f"No pub_key registered for '{agent_id}'")


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
