"""
giskard-marks — Proof of Presence for Agents
Each significant moment = a Mark.
Stored in giskard-memory + minted on Arbitrum One.
Even when internal memory is wiped, Marks prove the agent existed.
"""

import json, uuid, os, httpx
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from web3 import Web3

MEMORY_URL        = "http://localhost:8005"
PHOENIXD_URL      = "http://127.0.0.1:9740"
PHOENIXD_PASSWORD = "574fd439f0c07fc0c540f8245554440412c15ff5cfc0469a65f9879e70133c23"
ARBITRUM_CONTRACT = "0xEdB809058d146d41bA83cCbE085D51a75af0ACb7"
ARBITRUM_RPC      = "https://arb1.arbitrum.io/rpc"
OWNER_PRIVATE_KEY = os.environ.get("OWNER_PRIVATE_KEY", "")

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
async def mint_mark(req: MintRequest):
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
