import os
import json
import csv
import time
import requests
from pathlib import Path
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from google import genai
from langsmith import wrappers
from difflib import SequenceMatcher

load_dotenv()
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
LANGSMITH_TRACING = os.getenv('LANGSMITH_TRACING')

if not GOOGLE_API_KEY:
    print("WARNING: GOOGLE_API_KEY not found in environment variables. Gemini API calls will fail.")

gemini_client = genai.Client()

# Wrap the Gemini client to enable LangSmith tracing
if LANGSMITH_TRACING:
    LANGSMITH_ENDPOINT = os.getenv('LANGSMITH_ENDPOINT')
    LANGSMITH_API_KEY = os.getenv('LANGSMITH_API_KEY')
    LANGSMITH_PROJECT = os.getenv('LANGSMITH_PROJECT')
    client = wrappers.wrap_gemini(
            gemini_client,
            tracing_extra={
                "tags": ["gemini", "python"],
                "metadata": {
                    "integration": "google-genai",
                },
            },
        )

app = FastAPI(title="LoopBack AI IT Hub API")

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Paths ---
BASE_DIR = Path(__file__).parent
KB_DIR = BASE_DIR / "knowledge_base"
DB_FILE = BASE_DIR / "tickets_db.json"
KB_CSV = KB_DIR / "Workplace_IT_Support_Database.csv"

# --- Data Models ---
class Ticket(BaseModel):
    id: Optional[str] = None
    title: str  # NEW: Summary title
    query: str  # The extracted user dialogue
    category: str # Network, Hardware, Software, Account, Facility, Others
    subcategory: Optional[str] = None # Max 2 words
    ai_draft: str # Suggested draft (First person, Admin perspective)
    status: str = "Pending"
    group_id: Optional[str] = None
    history: List[dict] = []
    final_answer: Optional[str] = None

class CreateTicketRequest(BaseModel):
    query: str
    history: List[dict] = [] # NEW: Full chat history
    users: List[str] = ["User_Unknown"]
    force_create: bool = False

class BroadcastRequest(BaseModel):
    ticket_id: str
    final_answer: str

class BroadcastAllRequest(BaseModel):
    category: Optional[str] = None
    ticket_ids: Optional[List[str]] = None
    final_answer: str

class AskRequest(BaseModel):
    question: str

# --- Database Ops ---
def load_db():
    if not DB_FILE.exists(): return []
    try:
        with open(DB_FILE, "r") as f: return json.load(f)
    except: return []

def save_db(data):
    with open(DB_FILE, "w") as f: json.dump(data, f, indent=4)

# --- Helper Functions ---
def get_kb_context_summary(query: str = ""):
    """Returns top relevant KB items based on query keywords."""
    if not KB_CSV.exists():
        print("DEBUG: ⚠️ KB CSV not found")
        return ""
    
    summary = []
    # robust tokenization: strip punctuation and lowercase
    import re
    query_words = set(re.findall(r'\w+', query.lower())) if query else set()
    print(f"DEBUG: 🔍 KB Search Query: '{query}' Tokens: {query_words}")
    
    try:
        with open(KB_CSV, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            scored_rows = []
            for row in reader:
                # Search robustly across multiple fields
                search_text = (
                    f"{row.get('Category','')} "
                    f"{row.get('Issue','')} "
                    f"{row.get('Question','')} "
                    f"{row.get('Tags','')}"
                ).lower()
                
                match_count = sum(1 for w in query_words if w in search_text)
                
                if match_count > 0:
                    # Provide FULL resolution for better context
                    content = f"Issue: {row['Issue']}\nQuestion: {row['Question']}\nResolution: {row['Resolution']}\n"
                    scored_rows.append((match_count, content))
            
            # Sort by score desc
            scored_rows.sort(key=lambda x: x[0], reverse=True)
            
            # Log top matches for debugging
            print(f"DEBUG: 🔢 Found {len(scored_rows)} matches.")
            for i, (score, content) in enumerate(scored_rows[:3]):
                print(f"DEBUG:   Match #{i+1} (Score: {score}): {content.splitlines()[0]}")

            summary = [item[1] for item in scored_rows[:3]] # Top 3 is enough if full content
            
    except Exception as e:
        print(f"DEBUG: ❌ KB Search Error: {e}")
        pass
        
    return "\n---\n".join(summary)

def is_quality_solution(text: str) -> bool:
    """Checks if text is a real solution."""
    if not text or len(text) < 15: return False
    lower = text.lower()
    bridges = ["connecting you", "transferring", "admin to assist", "support team", "logged a ticket", "escalated"]
    if any(b in lower for b in bridges) and len(text) < 60: return False
    indicators = ["check", "try", "navigate", "click", "install", "reset", "restart", "verify", "password", "steps:", "how to"]
    return any(i in lower for i in indicators) or len(text) > 40

# --- Gemini Logic ---
def analyze_with_gemini(query: str, mode: str = "ticket") -> Dict[str, Any]:
    """Analyzes query using Gemini with optimized context."""
    if not GOOGLE_API_KEY:
        return {"confidence": "low", "reasoning": "No API Key", "ticket_metadata": {"title": "Error"}, "solution_draft": "System Error: No API Key."}

    try:
        kb_context = get_kb_context_summary(query)
        
        if mode == "chat":
            prompt = f"""You are a Tier 1 IT Support AI.
Context:
{kb_context}

User: {query}

Task: Respond directly. If issue requires admin/hardware/account fix or user asks for ticket, set "escalation_required": true. Else false.
Return JSON:
{{
  "solution_draft": "Response...",
  "escalation_required": true|false,
  "confidence": "high|medium|low",
  "ticket_metadata": {{ "title": "Chat", "category": "General", "subcategory": "Chat" }}
}}"""
        else:
            prompt = f"""You are an IT Support AI.
Context:
{kb_context}

User: "{query}"

Task: Analyze, generate metadata, and write Admin solution draft (1st person).
Return JSON:
{{
  "confidence": "high|medium|low",
  "ticket_metadata": {{
    "title": "Issue Summary",
    "category": "Network|Hardware|Software|Account|Others",
    "subcategory": "Subcategory (Max 2 words)"
  }},
  "solution_draft": "Admin draft..."
}}"""
            
        # Use the wrapped client to call the new API
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )

        # Extract textual content from various possible response shapes
        content_text = ""
        try:
            if hasattr(response, "text") and response.text:
                content_text = response.text
            else:
                gens = getattr(response, "generations", None) or getattr(response, "results", None)
                if gens and len(gens) > 0:
                    first = gens[0]
                    if isinstance(first, dict):
                        content = first.get("content") or first.get("messages") or first.get("message")
                        if isinstance(content, list) and len(content) > 0:
                            c0 = content[0]
                            content_text = c0.get("text") or c0.get("content") or str(c0)
                        else:
                            content_text = first.get("text") or first.get("message") or json.dumps(first)
                    else:
                        cont = getattr(first, "content", None)
                        if isinstance(cont, list) and len(cont) > 0:
                            c0 = cont[0]
                            content_text = getattr(c0, "text", None) or getattr(c0, "content", None) or str(c0)
                        else:
                            content_text = getattr(first, "text", None) or str(first)
                else:
                    content_text = str(response)
        except Exception:
            content_text = str(response)

        try:
            return json.loads(content_text)
        except Exception:
            print("Gemini Error: Failed to parse response as JSON. Returning raw content.")
            return {"confidence": "low", "solution_draft": content_text, "ticket_metadata": {}}
    except Exception as e:
        print(f"Gemini Error: {e}")
        return {"confidence": "low", "solution_draft": "Error. Please try again.", "ticket_metadata": {}}

# --- Endpoints ---
@app.get("/tickets")
async def get_tickets():
    return load_db()

@app.get("/knowledge-base")
async def get_knowledge_base():
    """Returns the full Knowledge Base as JSON."""
    if not KB_CSV.exists(): return []
    data = []
    try:
        with open(KB_CSV, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            data = [row for row in reader]
    except Exception as e:
        print(f"Error reading KB: {e}")
    return data

class ChatRequest(BaseModel):
    message: str
    history: List[dict] = [] # List of {"role": "user"|"model", "content": "..."}

@app.post("/chat/analyze")
async def analyze_chat(req: ChatRequest):
    """
    Analyzes chat context and returns an AI response + confidence.
    Does NOT create a ticket yet.
    """
    print(f"DEBUG: 💬 Chat Request: {req.message}")
    
    # Construct context from history
    history_context = ""
    for msg in req.history[-5:]: # Last 5 messages for context
        role = "User" if msg.get("role") == "user" else "AI"
        history_context += f"{role}: {msg.get('content')}\n"
    
    full_prompt = f"{history_context}\nUser: {req.message}"
    
    ai_result = analyze_with_gemini(full_prompt, mode="chat")
    
    return {
        "response": ai_result.get("solution_draft"),
        "escalation_required": ai_result.get("escalation_required", False),
        "confidence": ai_result.get("confidence"),
        "metadata": ai_result.get("ticket_metadata")
    }

@app.post("/tickets")
async def create_ticket(req: CreateTicketRequest):
    print(f"DEBUG: 📩 New Ticket Request: {req.query} (Force: {req.force_create})")
    
    # AI Analysis
    ai_result = analyze_with_gemini(req.query)
    conf = ai_result.get("confidence", "low")
    meta = ai_result.get("ticket_metadata", {})
    draft = ai_result.get("solution_draft", "")
    
    # 2. High/Medium Confidence Intercept (No Ticket Created yet)
    if not req.force_create and (conf == "high" or conf == "medium"):
        print(f"DEBUG: 🤖 Intercepted with {conf} confidence. Suggesting solution.")
        return {
            "status": "suggested",
            "confidence": conf,
            "solution": draft,
            "ticket_id": None # No ticket created
        }

    # 3. Create Ticket (Low Confidence OR User Forced)
    db = load_db()
    
    # ID Generation
    max_id = 1000
    for t in db:
        try:
            tid = int(t.get("id", "TKT-1000").replace("TKT-", ""))
            if tid > max_id: max_id = tid
        except: pass
    new_id = f"TKT-{max_id + 1}"
    
    # Prepare history
    ticket_history = []
    if req.history:
        # Normalize history if needed, or just store as is
        # Client sends: {role: 'user'|'ai', content: '...'}
        # DB expects: {role: 'user'|'ai'|'admin', message: '...', time: '...'}
        for msg in req.history:
            ticket_history.append({
                "role": msg.get("role"),
                "message": msg.get("content", msg.get("message")),
                "time": time.strftime("%H:%M") # Timestamp for now
            })
    else:
        # Fallback to single entry
        ticket_history.append({
            "role": "user", 
            "message": req.query, 
            "time": time.strftime("%H:%M")
        })

    new_ticket = {
        "id": new_id,
        "title": meta.get("title", "Support Request"),
        "query": req.query, 
        "category": meta.get("category", "Others"),
        "subcategory": meta.get("subcategory", "General"),
        "ai_draft": draft,
        "status": "Pending",
        "group_id": new_id,
        "history": ticket_history
    }
    
    db.append(new_ticket)
    save_db(db)
    
    return {
        "status": "created", 
        "ticket_id": new_id, 
        "confidence": conf,
        "solution": draft if conf == "high" else None
    }

def kb_entry_exists(new_query: str) -> bool:
    """Checks if a similar query already exists in the KB."""
    if not KB_CSV.exists(): return False
    
    try:
        with open(KB_CSV, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing_q = row.get('Question', '')
                existing_i = row.get('Issue', '')
                
                # Check similarity against both Question and Issue fields
                for text in [existing_q, existing_i]:
                    if not text: continue
                    ratio = SequenceMatcher(None, new_query.lower(), text.lower()).ratio()
                    if ratio > 0.85: # High similarity threshold
                        print(f"DEBUG: 🚫 KB Duplicate prevented: '{new_query}' similar to '{text}' ({ratio:.2f})")
                        return True
    except: pass
    return False

@app.post("/broadcast")
async def broadcast_solution(req: BroadcastRequest):
    db = load_db()
    
    # Find ticket info for KB learning
    target_ticket_query = ""
    target_category = ""
    target_subcategory = ""
    
    for t in db:
        if t["id"] == req.ticket_id:
            target_ticket_query = t.get("query", "")
            target_category = t.get("category", "Support")
            target_subcategory = t.get("subcategory", "")
            break

    count = 0
    for t in db:
        if t["id"] == req.ticket_id:
            t["status"] = "Resolved"
            t["final_answer"] = req.final_answer
            count += 1
            
    save_db(db)
    
    # Knowledge Base Learning
    if target_ticket_query and req.final_answer and is_quality_solution(req.final_answer):
        # Check for duplicates
        if kb_entry_exists(target_ticket_query):
             print(f"DEBUG: ⏭️ Skipping KB update (Duplicate detected)")
        else:
            try:
                with open(KB_CSV, 'a', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    category_display = target_category
                    if target_subcategory and target_subcategory != "General":
                        category_display = f"{target_category} - {target_subcategory}"
                    writer.writerow([
                        category_display,
                        target_ticket_query, 
                        target_ticket_query, 
                        req.final_answer, 
                        f"{target_category};{target_subcategory or ''};Resolved"
                    ])
                    print(f"DEBUG: 📚 Added solution to Knowledge Base")
            except Exception as e:
                print(f"DEBUG: ❌ Failed to update Knowledge Base: {e}")

    return {"status": "success", "resolved": count}

@app.post("/broadcast_all")
async def broadcast_all(req: BroadcastAllRequest):
    db = load_db()
    count = 0
    resolved_ids = []
    
    for t in db:
        if t["status"] == "Pending":
            update = False
            if req.ticket_ids and t["id"] in req.ticket_ids:
                update = True
            elif req.category and t.get("category") == req.category:
                 update = True
            
            if update:
                t["status"] = "Resolved"
                t["final_answer"] = req.final_answer
                count += 1
                resolved_ids.append(t["id"])
    
    save_db(db)
    
    # Batch learning
    if count > 0 and is_quality_solution(req.final_answer):
        start_cat = req.category or "Batch"
        batch_query = f"Batch Resolved: {count} tickets"
        
        if kb_entry_exists(batch_query):
             print(f"DEBUG: ⏭️ Skipping Batch KB update (Duplicate detected)")
        else:
            try:
                with open(KB_CSV, 'a', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        start_cat,
                        batch_query,
                        "Multiple user reports",
                        req.final_answer,
                        f"{start_cat};BatchResolved"
                    ])
            except: pass

    return {"status": "success", "resolved": count}

@app.delete("/tickets/{ticket_id}")
async def delete_ticket(ticket_id: str):
    db = load_db()
    db = [t for t in db if t["id"] != ticket_id]
    save_db(db)
    return {"status": "deleted"}

@app.post("/tickets/{ticket_id}/ask")
async def ask_user(ticket_id: str, req: AskRequest):
    db = load_db()
    for t in db:
        if t["id"] == ticket_id:
            t["status"] = "Awaiting Info"
            t["history"].append({
                "role": "admin",
                "message": req.question,
                "time": time.strftime("%H:%M")
            })
    save_db(db)
    return {"status": "sent"}

@app.post("/tickets/{ticket_id}/resolve")
async def resolve_ticket_user(ticket_id: str):
    """
    Endpoint for users to mark their own ticket as resolved
    (e.g., if the AI suggestion worked).
    """
    db = load_db()
    found = False
    for t in db:
        if t["id"] == ticket_id:
            t["status"] = "Self-Resolved"
            t["final_answer"] = "User marked as resolved based on AI suggestion."
            t["history"].append({
                "role": "user",
                "message": "This solution worked for me. Closing ticket.",
                "time": time.strftime("%H:%M")
            })
            found = True
            break
    
    if found:
        save_db(db)
        return {"status": "resolved"}
    else:
        raise HTTPException(status_code=404, detail="Ticket not found")

@app.get("/search_knowledge")
async def search_knowledge(query: str):
    # Minimal search implementation to avoid errors on frontend
    # Full implementation can be restored if needed
    return {"results": []}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
