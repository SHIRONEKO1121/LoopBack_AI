import os
import json
import csv
import time
import datetime
import uuid
import requests
from pathlib import Path
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from google import genai
from langsmith import wrappers
from difflib import SequenceMatcher

load_dotenv()
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
LANGSMITH_TRACING = os.getenv('LANGSMITH_TRACING')

if not GOOGLE_API_KEY:
    print("WARNING: GOOGLE_API_KEY not found in environment variables. Gemini API calls will fail.")

gemini_client = genai.Client(api_key=GOOGLE_API_KEY)

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
else:
    client = gemini_client

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

class TicketMetadata(BaseModel):
    title: str = Field(description="Issue Summary")
    category: str = Field(description="Network|Hardware|Software|Account|Others")
    subcategory: str = Field(description="Subcategory (Max 2 words)")

class Response(BaseModel):
    confidence: str = Field(description="high|medium|low")
    summary: str = Field(description="Concise 1-sentence summary of the issue (e.g. 'User needs a smaller keyboard due to injury')")
    ticket_metadata: TicketMetadata
    solution_draft: str = Field(description="Admin draft solution or Chat response")
    escalation_required: bool = Field(default=False, description="True if escalation is required")
    is_it_related: bool = Field(default=True, description="True if query is IT Support related (hardware, software, network, account, etc.). False for chit-chat, weather, general knowledge.")

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
    
    # Exclude transactional/request handling responses
    transactional_phrases = [
        "received your request", "initiate the", "monitor the", "let you know", 
        "approval", "access granted", "deployed", "shipping", "ordered", 
        "will now", "have been added"
    ]
    if any(t in lower for t in transactional_phrases): 
        print(f"DEBUG: 🚫 Skipped KB update (Transactional response detected)")
        return False

    indicators = ["check", "try", "navigate", "click", "install", "reset", "restart", "verify", "password", "steps:", "how to"]
    return any(i in lower for i in indicators) or len(text) > 40

# --- Gemini Logic ---
def analyze_with_gemini(query: str, mode: str = "ticket") -> Dict[str, Any]:
    """Analyzes query using Gemini with optimized context."""
    if not GOOGLE_API_KEY:
        return {"confidence": "low", "reasoning": "No API Key", "ticket_metadata": {"title": "Error"}, "solution_draft": "System Error: No API Key.", "summary": "Error"}

    try:
        kb_context = get_kb_context_summary(query)
        
        if mode == "chat":
            prompt = f"""You are a Tier 1 IT Support AI.
Context:
{kb_context}

User: {query}

Task: Respond directly. If issue requires admin/hardware/account fix or user asks for ticket, or if the message is a test message, set "escalation_required": true. Else false.
If the message is a test message,, set escalation_required to false, and tell the user that the system is running well.
Return JSON:
{{
  "solution_draft": "Response...",
  "escalation_required": true|false,
  "confidence": "high|medium|low",
  "is_it_related": true|false,
  "summary": "Standardized, professional issue title (e.g. 'VPN Access Failure' or 'Laptop Screen Replacement Request'). Avoid 'User reports' or 'Customer needs'. Just state the issue.",
  "ticket_metadata": {{
    "title": "Title",
    "category": "Category",
    "subcategory": "Subcategory"
  }}
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
  "summary": "Standardized, professional issue title (e.g. 'VPN Access Failure'). Avoid 'User reports'. Just state the issue.",
  "ticket_metadata": {{
    "title": "Issue Summary",
    "category": "Network|Hardware|Software|Account|Others",
    "subcategory": "Subcategory (Max 2 words)"
  }},
  "solution_draft": "Admin draft...",
  "escalation_required": true,
  "is_it_related": true
}}"""
            
        # Use the wrapped client to call the new API
        response = client.models.generate_content(
            model="gemini-flash-latest",
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "response_schema": Response.model_json_schema(),
            },
        )

        # Extract textual content
        content_text = ""
        try:
            if hasattr(response, "text") and response.text:
                content_text = response.text
            else:
                content_text = str(response)
        except Exception:
            content_text = str(response)

        try:
            # Clean possible markdown
            content_text = content_text.strip()
            if content_text.startswith("```json"):
                content_text = content_text.split("\n", 1)[1].rsplit("\n", 1)[0]
            elif content_text.startswith("```"):
                content_text = content_text.split("\n", 1)[1].rsplit("\n", 1)[0]
                
            return json.loads(content_text)
        except Exception:
            print("Gemini Error: Failed to parse response as JSON. Returning raw content.")
            return {"confidence": "low", "solution_draft": content_text, "ticket_metadata": {}, "summary": query}

    except Exception as e:
        error_str = str(e)
        print(f"Gemini Error: {error_str}")
        
        if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str or "quota" in error_str.lower():
            msg = "⚠️ AI Service Busy: quota exhausted. Please try again in a few minutes."
        else:
            msg = f"System Error: {error_str}"
            
        return {
            "confidence": "low", 
            "solution_draft": msg, 
            "ticket_metadata": {"title": "Error", "category": "Others", "subcategory": "System Error"}, 
            "summary": "System Error"
        }

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
    
    # Check for keywords to force escalation logic if needed
    escalate = ai_result.get("escalation_required", False)
    if not escalate:
        if "ticket" in req.message.lower() or "admin" in req.message.lower() or "escalate" in req.message.lower():
             escalate = True
    
    return {
        "response": ai_result.get("solution_draft"),
        "escalation_required": escalate,
        "confidence": ai_result.get("confidence"),
        "is_it_related": ai_result.get("is_it_related", True),
        "metadata": ai_result.get("ticket_metadata"),
        "summary": ai_result.get("summary", req.message) # Return summary
    }

@app.post("/tickets")
async def create_ticket(req: CreateTicketRequest):
    print(f"DEBUG: 📩 New Ticket Request: {req.query} (Force: {req.force_create})")
    
    # AI Analysis for categorization (if not provided/if needed)
    # If the frontend passes a 'summary' as 'req.query', we use it.
    # We still run analyze_with_gemini to get metadata categorization based on that summary/query.
    ai_result = analyze_with_gemini(req.query, mode="ticket")
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

def standardize_resolution(text: str) -> str:
    """Uses Gemini to rewrite a response into a standardized KB resolution."""
    if not text or not GOOGLE_API_KEY: return text
    
    try:
        prompt = f"""Rewrite the following support response into a standardized, technical resolution for a Knowledge Base. 
        Rules:
        1. Remove pleasantries (Hi, Thanks, Sorry, 'I will...').
        2. Use imperative or objective tone (e.g., 'Connect to VPN...' or 'Ticket #123 created for hardware replacement').
        3. Keep it concise.
        4. OUTPUT PLAIN TEXT ONLY. Do NOT use markdown formatting (no bold **, no italics *, no code blocks).
        5. Do NOT include prefixes like "KB Resolution:" or "Resolution:". Start directly with the action.
        
        Input: "{text}"
        """
        
        # Use the wrapped client if available, else gemini_client
        c = client if 'client' in globals() else gemini_client
        response = c.models.generate_content(
            model="gemini-flash-latest",
            contents=prompt,
        )
        
        if hasattr(response, "text"):
            return response.text.strip()
        else:
            return str(response).strip()
    except Exception as e:
        print(f"Standardization Error: {e}")
        return text

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
                    
                    # Standardize resolution
                    std_resolution = standardize_resolution(req.final_answer)
                    
                    # Generate ID
                    new_id = str(uuid.uuid4())[:8]

                    writer.writerow([
                        new_id,
                        target_category, # Only Major Category
                        "", # Empty Issue column
                        target_ticket_query, 
                        std_resolution, 
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
                # Standardize batch resolution
                std_batch_res = standardize_resolution(req.final_answer)
                
                # Generate ID
                new_id = str(uuid.uuid4())[:8]

                with open(KB_CSV, 'a', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        new_id,
                        start_cat, # Major Category
                        "", # Empty Issue
                        batch_query,
                        std_batch_res,
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

# --- Knowledge Base CRUD ---

class KBEntry(BaseModel):
    id: Optional[str] = None
    category: str
    issue: Optional[str] = "" # Optional/Deprecated
    question: str
    resolution: str
    tags: Optional[str] = None

@app.get("/knowledge-base")
async def get_kb_entries():
    """Returns all KB entries."""
    if not KB_CSV.exists():
        return []
    
    entries = []
    try:
        with open(KB_CSV, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            entries = list(reader)
    except Exception as e:
        print(f"Error reading KB: {e}")
        return []
    return entries

@app.post("/knowledge-base")
async def create_kb_entry(entry: KBEntry):
    """Creates a new KB entry."""
    new_id = str(uuid.uuid4())[:8]
    entry.id = new_id
    
    # Standardize resolution if not already
    entry.resolution = standardize_resolution(entry.resolution)
    
    fieldnames = ['ID', 'Category', 'Issue', 'Question', 'Resolution', 'Tags']
    
    try:
        # Append to CSV
        file_exists = KB_CSV.exists()
        with open(KB_CSV, 'a', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerow({
                'ID': entry.id,
                'Category': entry.category,
                'Issue': "", # Deprecated/Empty
                'Question': entry.question,
                'Resolution': entry.resolution,
                'Tags': entry.tags or ""
            })
        return {"status": "created", "entry": entry}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/knowledge-base/{entry_id}")
async def update_kb_entry(entry_id: str, entry: KBEntry):
    """Updates an existing KB entry."""
    if not KB_CSV.exists():
        raise HTTPException(status_code=404, detail="KB not found")
        
    updated = False
    temp_file = KB_CSV.with_suffix('.tmp')
    
    try:
        with open(KB_CSV, 'r', encoding='utf-8') as infile, \
             open(temp_file, 'w', newline='', encoding='utf-8') as outfile:
            
            reader = csv.DictReader(infile)
            fieldnames = reader.fieldnames
            writer = csv.DictWriter(outfile, fieldnames=fieldnames)
            writer.writeheader()
            
            for row in reader:
                if row.get('ID') == entry_id:
                    writer.writerow({
                        'ID': entry_id,
                        'Category': entry.category,
                        'Issue': "", # Deprecated/Empty
                        'Question': entry.question,
                        'Resolution': entry.resolution, 
                        'Tags': entry.tags or row.get('Tags', "")
                    })
                    updated = True
                else:
                    writer.writerow(row)
        
        if updated:
            temp_file.replace(KB_CSV)
            return {"status": "updated", "entry": entry}
        else:
            temp_file.unlink(missing_ok=True)
            raise HTTPException(status_code=404, detail="Entry not found")
            
    except Exception as e:
        if temp_file.exists(): temp_file.unlink()
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/knowledge-base/{entry_id}")
async def delete_kb_entry(entry_id: str):
    """Deletes a KB entry."""
    if not KB_CSV.exists():
        raise HTTPException(status_code=404, detail="KB not found")
        
    deleted = False
    temp_file = KB_CSV.with_suffix('.tmp')
    
    try:
        with open(KB_CSV, 'r', encoding='utf-8') as infile, \
             open(temp_file, 'w', newline='', encoding='utf-8') as outfile:
            
            reader = csv.DictReader(infile)
            fieldnames = reader.fieldnames
            writer = csv.DictWriter(outfile, fieldnames=fieldnames)
            writer.writeheader()
            
            for row in reader:
                if row.get('ID') == entry_id:
                    deleted = True
                    continue
                writer.writerow(row)
        
        if deleted:
            temp_file.replace(KB_CSV)
            return {"status": "deleted"}
        else:
            temp_file.unlink(missing_ok=True)
            raise HTTPException(status_code=404, detail="Entry not found")
            
    except Exception as e:
        if temp_file.exists(): temp_file.unlink()
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
