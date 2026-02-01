import os
import json
import csv
import time
import requests
from pathlib import Path
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv('API_KEY')
ORCHESTRATION_ID = os.getenv('ORCHESTRATION_ID')
INSTANCE_ID = os.getenv('INSTANCE_ID')
AGENT_ID = os.getenv('AGENT_ID')
HOST_URL = os.getenv('HOST_URL')

app = FastAPI(title="LoopBack AI IT Hub API")

# Enable CORS for React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Configuration & Paths ---
BASE_DIR = Path(__file__).parent
KB_DIR = BASE_DIR / "knowledge_base"
DB_FILE = BASE_DIR / "tickets_db.json"

# --- Data Models ---
class Ticket(BaseModel):
    id: Optional[str] = None
    group_id: Optional[str] = None
    category: Optional[str] = None # Major category (e.g., Network, Hardware)
    subcategory: Optional[str] = None # Specific detail (e.g., VPN VPN-101 error)
    query: str
    ai_draft: str # Technical summary/findings
    admin_draft: Optional[str] = None # Polished draft for the end-user
    status: str = "Pending" # Pending, Resolved, Awaiting Info
    users: List[str] = ["User_Unknown"]
    final_answer: Optional[str] = None
    history: List[dict] = [] # List of {role: admin/user, message: str, time: str}

class AskRequest(BaseModel):
    message: str

class BroadcastRequest(BaseModel):
    ticket_id: str
    # group_id: Optional[str] = None
    final_answer: str

class BroadcastAllRequest(BaseModel):
    category: Optional[str] = None  # If specified, filter by category
    ticket_ids: Optional[List[str]] = None # If specified, filter by these IDs specifically
    final_answer: str

class ClarifyRequest(BaseModel):
    question: str

# --- Database Mock ---
def load_db():
    if not DB_FILE.exists():
        return []
    with open(DB_FILE, "r") as f:
        try:
            return json.load(f)
        except:
            return []

def save_db(data):
    with open(DB_FILE, "w") as f:
        json.dump(data, f, indent=4)

def get_iam_token():
    """Get IBM Cloud IAM token for Watsonx API calls"""
    try:
        response = requests.post(
            "https://iam.cloud.ibm.com/identity/token",
            data={
                "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
                "apikey": API_KEY
            },
            timeout=10
        )
        response.raise_for_status()
        return response.json().get("access_token")
    except Exception as e:
        print(f"DEBUG: ❌ IAM token error: {e}")
        return None

# --- Endpoints ---

@app.get("/tickets")
async def get_tickets():
    return load_db()

@app.post("/tickets")
async def create_ticket(ticket: Ticket):
    print(f"DEBUG: 📩 Ticket creation request received!")
    print(f"DEBUG: 📦 Payload: {ticket.dict()}")
    db = load_db()
    
    # 1. Get Token for AI similarity checking
    token = None
    try:
        print(f"DEBUG: 🔑 Getting IAM token for AI grouping...")
        token = get_iam_token()
        if token:
            print(f"DEBUG: ✅ Got IAM token successfully")
        else:
            print(f"DEBUG: ⚠️ IAM token is None - using fallback grouping")
    except Exception as e:
        print(f"DEBUG: ❌ Failed to get IAM token: {e} - using fallback grouping")
        token = None

    # 2. Check for Similarity - PRIORITY: Category-based grouping (from Agent)
    group_id = None
    
    # Strategy 1: If Agent provided category + subcategory, use high-precision grouping
    if ticket.category:
        print(f"DEBUG: 📂 Ticket has category: {ticket.category} | Subcategory: {ticket.subcategory or 'None'}")
        query_lower = ticket.query.lower().strip()
        
        for existing_ticket in db:
            if existing_ticket.get("status") != "Pending":
                continue
            
            # Same major category
            if existing_ticket.get("category") == ticket.category:
                # If subcategories also match, it's a very strong group signal
                if ticket.subcategory and existing_ticket.get("subcategory") == ticket.subcategory:
                    group_id = existing_ticket.get("group_id", existing_ticket["id"])
                    print(f"DEBUG: 🎯 Perfect match! Category & Subcategory match: {ticket.category} > {ticket.subcategory}")
                    break
                
                # Otherwise fall back to text similarity within the same category
                existing_query = existing_ticket.get("query", "").lower().strip()
                query_words = set(query_lower.split())
                existing_words = set(existing_query.split())
                
                if query_words and existing_words:
                    overlap = len(query_words & existing_words)
                    similarity = overlap / max(len(query_words), len(existing_words))
                    
                    if similarity >= 0.4: # Lower threshold because category already matches
                        group_id = existing_ticket.get("group_id", existing_ticket["id"])
                        print(f"DEBUG: 🔗 Category match! Grouped with {existing_ticket['id']} (similarity: {similarity:.0%})")
                        break
    
    # Strategy 2: AI-powered grouping (if token available and no category match)
    if not group_id and token:
        print(f"DEBUG: 🤖 Trying AI-powered grouping...")
        group_id = check_similarity_ai(ticket.query, db, token)
    
    # Strategy 3: FALLBACK - Simple text-based grouping
    if not group_id:
        print(f"DEBUG: 🔄 Using fallback similarity check...")
        query_lower = ticket.query.lower().strip()
        
        for existing_ticket in db:
            if existing_ticket.get("status") != "Pending":
                continue
            
            existing_query = existing_ticket.get("query", "").lower().strip()
            
            # Exact match
            if existing_query == query_lower:
                group_id = existing_ticket.get("group_id", existing_ticket["id"])
                print(f"DEBUG: 🎯 Found exact match with {existing_ticket['id']}")
                break
            
            # 45%+ word similarity (Lowered from 0.7 to catch more follow-ups)
            query_words = set(query_lower.split())
            existing_words = set(existing_query.split())
            if query_words and existing_words:
                overlap = len(query_words & existing_words)
                similarity = overlap / max(len(query_words), len(existing_words))
                if similarity >= 0.45:
                    group_id = existing_ticket.get("group_id", existing_ticket["id"])
                    print(f"DEBUG: 🔗 Found similar ticket {existing_ticket['id']} ({similarity:.0%} match)")
                    break
    
    # 3. Robust ID Generation (Max + 1)
    max_id = 1000
    for t in db:
        try:
            tid = int(t["id"].replace("TKT-", ""))
            if tid > max_id:
                max_id = tid
        except:
            pass
    
    ticket.id = f"TKT-{max_id + 1}"
    
    if group_id:
        print(f"DEBUG: 🔗 Linking new ticket {ticket.id} to Group {group_id}")
        ticket.group_id = group_id
        
        # Update existing tickets in the same group
        for t in db:
            if t.get("group_id") == group_id or t["id"] == group_id:
                # If group was waiting for info, set back to Pending
                if t.get("status") == "Awaiting Info":
                    t["status"] = "Pending"
                    print(f"DEBUG: 🔄 Pushing Group {group_id} back to Pending (User replied)")
                
                # Add to history
                if "history" not in t: t["history"] = []
                t["history"].append({
                    "role": "user",
                    "message": ticket.query,
                    "time": time.strftime("%H:%M")
                })
    else:
        print(f"DEBUG: 🆕 New Group established for {ticket.id}")
        ticket.group_id = ticket.id
        # Initialize history for new group
        if not ticket.history:
            ticket.history = [{
                "role": "user",
                "message": ticket.query,
                "time": time.strftime("%H:%M")
            }]

    db.append(ticket.dict())
    save_db(db)
    print(f"DEBUG: ✅ Ticket created: {ticket.id}")
    return {"status": "created", "ticket_id": ticket.id, "group_id": ticket.group_id}

@app.delete("/tickets/{ticket_id}")
async def delete_ticket(ticket_id: str):
    print(f"DEBUG: 🗑️ Delete request for ticket: {ticket_id}")
    db = load_db()
    original_count = len(db)
    db = [t for t in db if t.get("id") != ticket_id]
    
    if len(db) < original_count:
        save_db(db)
        print(f"DEBUG: ✅ Ticket {ticket_id} deleted successfully")
        return {"status": "deleted", "ticket_id": ticket_id}
    else:
        print(f"DEBUG: ⚠️ Ticket {ticket_id} not found")
        raise HTTPException(status_code=404, detail="Ticket not found")

@app.post("/tickets/{ticket_id}/ask")
async def ask_clarifying_question(ticket_id: str, req: ClarifyRequest):
    print(f"DEBUG: ❓ Admin asking question for ticket: {ticket_id}")
    db = load_db()
    
    ticket_found = False
    for ticket in db:
        if ticket["id"] == ticket_id:
            ticket["status"] = "Awaiting Info"
            if "history" not in ticket:
                ticket["history"] = []
            
            ticket["history"].append({
                "role": "admin",
                "message": req.question,
                "time": time.strftime("%H:%M")
            })
            ticket_found = True
            break
            
    if ticket_found:
        save_db(db)
        print(f"DEBUG: ✅ Question sent for {ticket_id}")
        return {"status": "success", "message": "Question sent to user"}
    else:
        raise HTTPException(status_code=404, detail="Ticket not found")

@app.post("/broadcast")
async def broadcast_solution(req: BroadcastRequest):
    db = load_db()
    
    # Check if we can find the group_ID first
    target_category = None
    target_subcategory = None

    for ticket in db:
        if ticket["id"] == req.ticket_id:
            target_group = ticket.get("group_id", ticket["id"])
            target_ticket_query = ticket.get("query", "")
            target_category = ticket.get("category", "Support")
            target_subcategory = ticket.get("subcategory", "General")
            break
            
    if target_group:
        print(f"DEBUG: 📢 Broadcasting solution to Group: {target_group}")
        count = 0
        for ticket in db:
            # Update matching group OR if it's the exact ticket ID (legacy case)
            if ticket.get("group_id") == target_group or ticket["id"] == req.ticket_id:
                ticket["status"] = "Resolved"
                ticket["final_answer"] = req.final_answer
                count += 1
        print(f"DEBUG: ✅ Resolved {count} tickets in group.")
        
        # --- NEW: Save to Knowledge Base CSV ---
        if target_ticket_query and req.final_answer:
                if not is_quality_solution(req.final_answer):
                    print(f"DEBUG: ⏭️ Skipping KB update (not a quality solution)")
                else:
                    try:
                        csv_file = KB_DIR / "Workplace_IT_Support_Database.csv"
                        with open(csv_file, 'a', newline='', encoding='utf-8') as f:
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
                        print(f"DEBUG: 📚 Added solution to Knowledge Base: {csv_file}")
                    except Exception as e:
                        print(f"DEBUG: ❌ Failed to update Knowledge Base: {e}")

    else:
        print("DEBUG: ⚠️ Ticket ID not found for broadcast.")

    save_db(db)
    return {"status": "broadcast_complete"}

@app.post("/broadcast_all")
async def broadcast_all(req: BroadcastAllRequest):
    """
    Broadcast solution to multiple tickets at once.
    Can filter by category or resolve all pending tickets.
    """
    print(f"DEBUG: 📢 Batch broadcast request - Category: {req.category or 'ALL'}")
    db = load_db()
    updated_count = 0
    resolved_ids = []
    
    for ticket in db:
        # Only update pending tickets
        if ticket.get("status") != "Pending":
            continue
        
        # Filter by IDs if provided (highest priority)
        if req.ticket_ids is not None:
            if ticket.get("id") not in req.ticket_ids:
                continue
        # Otherwise filter by category if specified
        elif req.category and ticket.get("category") != req.category:
            continue
        
        # Update ticket
        ticket["status"] = "Resolved"
        ticket["final_answer"] = req.final_answer
        updated_count += 1
        resolved_ids.append(ticket["id"])
        print(f"DEBUG: ✅ Resolved {ticket['id']}")
    
    save_db(db)
    
    # Add to knowledge base
    kb_category = req.category
    if not kb_category and updated_count > 0:
        # Try to find a common category from the resolved tickets
        cats = [t.get("category") for t in db if t["id"] in resolved_ids and t.get("category")]
        if cats:
            kb_category = cats[0] # Use the first one as representative

    if kb_category and updated_count > 0:
        if not is_quality_solution(req.final_answer):
            print(f"DEBUG: ⏭️ Skipping batch KB update (not a quality solution)")
        else:
            try:
                csv_file = KB_DIR / "Workplace_IT_Support_Database.csv"
                with open(csv_file, 'a', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        kb_category,
                        f"Batch Resolved: {kb_category} Issues",
                        f"Resolution for {updated_count} user report(s)",
                        req.final_answer,
                        f"{kb_category};BatchResolved"
                    ])
                print(f"DEBUG: 📚 Added batch solution to Knowledge Base")
            except Exception as e:
                print(f"DEBUG: ⚠️ Failed to update KB: {e}")
    
    print(f"DEBUG: 🎉 Batch broadcast complete - {updated_count} tickets resolved")
    return {
        "status": "success",
        "tickets_resolved": updated_count,
        "category": req.category or "All",
        "resolved_ticket_ids": resolved_ids
    }


@app.get("/search_knowledge")
async def search_knowledge(query: str):
    """
    Search knowledge base - prioritizes CSV Q&A matches heavily.
    CSV questions get 10x higher scores than general text matches.
    """
    print(f"DEBUG: 🔍 Knowledge search: '{query}'")
    results = []
    query_lower = query.lower().strip()
    
    # Synonym expansion for better matching
    synonyms = {
        'broken': ['cracked', 'damaged', 'not working', 'broken'],
        'connect': ['setup', 'install', 'add', 'configure', 'connect'],
        'fix': ['repair', 'solve', 'troubleshoot', 'fix'],
        'slow': ['lag', 'lagging', 'sluggish', 'slow'],
        'issue': ['problem', 'error', 'issue', 'trouble'],
        'get': ['request', 'obtain', 'get', 'need'],
        'pc': ['computer', 'laptop', 'pc', 'machine'],
        'screen': ['display', 'monitor', 'screen'],
        'share': ['present', 'show', 'share', 'display'],
        'wifi': ['wi-fi', 'wireless', 'network', 'wifi'],
        'guest': ['visitor', 'guest', 'external'],
    }
    
    # Expand query with synonyms
    expanded_query = query_lower
    for word, alternatives in synonyms.items():
        for alt in alternatives:
            if alt in query_lower:
                expanded_query += " " + " ".join(alternatives)
                break
    
    # Remove stopwords and punctuation for word matching
    stopwords = {'the', 'how', 'what', 'where', 'when', 'why', 'can', 'could', 'should', 'would', 'will', 'are', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'from', 'by', 'a', 'an', 'is', 'do', 'does', 'my', 'i', 'it'}
    query_words = [w.lower() for w in expanded_query.replace('?', '').replace(',', '').replace('.', '').split() 
                   if len(w) >= 3 and w.lower() not in stopwords]
    
    # Remove duplicates
    query_words = list(set(query_words))
    
    print(f"DEBUG: Query words (expanded): {query_words[:10]}")
    
    # === PRIORITY 1: Search CSV (structured Q&A) ===
    csv_file = KB_DIR / "Workplace_IT_Support_Database.csv"
    if csv_file.exists():
        try:
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if not row.get('Question'):  # Skip rows without questions
                        continue
                        
                    question = str(row['Question']).lower()
                    resolution = str(row.get('Resolution', '')).lower()
                    category = str(row.get('Category', '')).lower()
                    tags = str(row.get('Tags', '')).lower()
                    
                    score = 0
                    
                    # HIGHEST: Exact query match in Question
                    if query_lower in question:
                        score += 1000
                        print(f"DEBUG: 🎯 Exact phrase in Q: {row['Question'][:60]}...")
                    
                    # VERY HIGH: Question contains query (reversed)  
                    if question in query_lower and len(question) > 10:
                        score += 900
                        print(f"DEBUG: 🎯 Question phrase in query: {row['Question'][:60]}...")
                    
                    # HIGH: Most query words match question or tags
                    if query_words:
                        question_matches = sum(1 for word in query_words if word in question or word in tags)
                        match_ratio = question_matches / len(query_words)
                        
                        if match_ratio >= 0.7:  # 70%+ match
                            score += 700
                        elif match_ratio >= 0.5:  # 50%+ match
                            score += 500
                        elif match_ratio >= 0.3:  # 30%+ match
                            score += 300
                        else:
                            score += question_matches * 40
                    
                    # MEDIUM: Partial matches in resolution, category, or tags
                    if query_lower in resolution:
                        score += 100
                    if query_lower in category:
                        score += 150  # Boost category matches
                    if query_lower in tags:
                        score += 120  # Boost tag matches
                    
                    if score > 0:
                        results.append({
                            "source": csv_file.name,
                            "content": row,
                            "score": score
                        })
        except Exception as e:
            print(f"DEBUG: Error reading CSV: {e}")
    
    # === PRIORITY 2: Search TXT files (only if needed for context) ===
    # Only use TXT files as supplementary material with lower scores
    for file_path in KB_DIR.glob("*.txt"):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                content_lower = content.lower()
                
                score = 0
                
                # Exact phrase match in TXT
                if query_lower in content_lower:
                    score += 200  # Much lower than CSV
                    
                    # Bonus for title match
                    if query_lower in content_lower[:100]:
                        score += 30
                
                # Word matching in TXT (even lower priority)
                if query_words:
                    word_matches = sum(1 for word in query_words if word in content_lower)
                    match_ratio = word_matches / len(query_words)
                    
                    if match_ratio >= 0.7:
                        score += 100
                    elif match_ratio >= 0.5:
                        score += 60
                    else:
                        score += word_matches * 5
                
                if score > 0:
                    results.append({
                        "source": file_path.name,
                        "content": content[:500],  # First 500 chars
                        "score": score
                    })
        except Exception as e:
            print(f"DEBUG: Error reading {file_path.name}: {e}")
    
    # Sort by score (highest first)
    results.sort(key=lambda x: x['score'], reverse=True)
    
    print(f"DEBUG: ✅ Found {len(results)} results")
    if results:
        print(f"DEBUG: Top 3: {[(r['source'], r['score']) for r in results[:3]]}")
    
    # Return top 5, remove score field
    return {"results": [{"source": r["source"], "content": r["content"]} for r in results[:5]]}

def is_quality_solution(text: str) -> bool:
    """
    Checks if the text is a real solution or just an escalation bridge.
    Returns True if it's a high-quality resolution worth saving.
    """
    if not text or len(text) < 15:
        return False
        
    lower_text = text.lower()
    
    # Phrases that indicate it's just a "bridge" or escalation, NOT a solution
    bridge_phrases = [
        "connecting you", "transferring you", "it admin to assist", 
        "support team will", "logged a ticket", "escalated to",
        "will address this issue", "further help", "investigate further",
        "contact you shortly", "sent this request", "flagged this for our"
    ]
    
    # If it contains bridge phrases AND is very short, it's definitely not a solution
    if any(p in lower_text for p in bridge_phrases):
        # Allow it only if it's actually long (might contain a solution + escalation)
        if len(text) < 60:
            return False
            
    # Phrases that indicate real technical steps or answers
    solution_indicators = [
        "check", "try", "navigate to", "click", "install", 
        "reset", "restart", "verify", "password is", "location is",
        "steps:", "guide", "procedure", "how to"
    ]
    
    # If it contains real instructions, it's likely a solution
    if any(p in lower_text for p in solution_indicators):
        return True
        
    # Default: if it doesn't look like a tiny bridge, keep it
    return len(text) > 40

def check_similarity_ai(new_query: str, existing_tickets: List[dict], token: str) -> Optional[str]:
    """
    Uses Watsonx.ai to check if new_query matches any existing ticket.
    Returns the group_id (ticket ID of the match) or None.
    """
    if not existing_tickets:
        return None
        
    # Prepare a summary list for the prompt to save tokens
    # We only check 'Pending' tickets to group active issues
    active_tickets = [t for t in existing_tickets if t.get("status") == "Pending"]
    if not active_tickets:
        return None

    # Construct the prompt
    candidates_text = "\n".join([f"- ID: {t['id']}, Issue: {t['query']}" for t in active_tickets[:20]]) # Limit to 20 recent
    
    prompt = f"""You are an IT Support Triage AI.
Check if the New Issue matches any of the Existing Issues. 
They match if they are about the EXACT SAME technical problem (e.g., "wifi broken" vs "cannot connect to internet").
If they match, return ONLY the ID of the existing issue.
If they do not match, return "None".

Existing Issues:
{candidates_text}

New Issue: {new_query}

Match ID:"""

    url = "https://us-south.ml.cloud.ibm.com/ml/v1/text/generation?version=2023-05-29"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    # Using Granite or similar model available in standard Watsonx
    body = {
        "input": prompt,
        "parameters": {
            "decoding_method": "greedy",
            "max_new_tokens": 10,
            "min_new_tokens": 1,
            "stop_sequences": ["\n"],
            "repetition_penalty": 1.0
        },
        "model_id": "ibm/granite-13b-chat-v2",
        "project_id": os.getenv("INSTANCE_ID", "your-project-id-here") 
    }

    try:
        print("DEBUG: 🤖 Asking Watsonx.ai to group tickets...")
        response = requests.post(url, headers=headers, json=body)
        if response.status_code != 200:
            print(f"DEBUG: ⚠️ AI Grouping failed: {response.text}")
            return None
            
        result_text = response.json()['results'][0]['generated_text'].strip()
        print(f"DEBUG: 🤖 AI Decision: {result_text}")
        
        # Check if result is a valid ID from our list
        for t in active_tickets:
            if t['id'] in result_text:
                return t.get("group_id", t['id'])
                
        return None

    except Exception as e:
        print(f"DEBUG: ❌ AI Grouping error: {e}")
        return None

def extract_ai_response(data: dict) -> Optional[str]:
    """
    Extract AI response from Watsonx API response.
    Scans multiple possible JSON paths where the text might be.
    """
    candidates = []
    
    # ⭐ Path 0: step_history (MOST IMPORTANT - contains actual workflow responses)
    try:
        result = data.get("result")
        if result and isinstance(result, dict):
            data_obj = result.get("data")
            if data_obj and isinstance(data_obj, dict):
                message = data_obj.get("message")
                if message and isinstance(message, dict):
                    step_history = message.get("step_history", [])
                    for step in step_history:
                        if step.get("role") == "assistant":
                            step_details = step.get("step_details", [])
                            for detail in step_details:
                                # Check for tool_response type (contains the actual AI answer)
                                if detail.get("type") == "tool_response":
                                    # Try to get the response content
                                    tool_resp = detail.get("response", {})
                                    
                                    # Check various response formats
                                    if isinstance(tool_resp, dict):
                                        # Format 1: Direct text field
                                        if "text" in tool_resp:
                                            candidates.append(("step_history.tool_response.text", tool_resp["text"]))
                                        # Format 2: Message content
                                        if "message" in tool_resp:
                                            msg_content = tool_resp["message"]
                                            if isinstance(msg_content, str):
                                                candidates.append(("step_history.tool_response.message", msg_content))
                                            elif isinstance(msg_content, dict) and "text" in msg_content:
                                                candidates.append(("step_history.tool_response.message.text", msg_content["text"]))
                                        # Format 3: Content array
                                        if "content" in tool_resp:
                                            content = tool_resp["content"]
                                            if isinstance(content, str):
                                                candidates.append(("step_history.tool_response.content", content))
                                            elif isinstance(content, list):
                                                for item in content:
                                                    if isinstance(item, dict) and item.get("type") == "text":
                                                        candidates.append(("step_history.tool_response.content[]", item.get("text")))
                                    elif isinstance(tool_resp, str):
                                        candidates.append(("step_history.tool_response", tool_resp))
    except Exception as e:
        print(f"DEBUG: ⚠️ Error parsing step_history: {e}")
    
    # Path 1: messages array (most reliable for conversational responses)
    messages = data.get("messages", [])
    for msg in messages:
        if msg.get("role") == "assistant":
            content = msg.get("content")
            if content:
                candidates.append(("messages", content))
    
    # Path 2: result.data.message.content (structured output)
    try:
        content_blocks = data.get("result", {}).get("data", {}).get("message", {}).get("content", [])
        if isinstance(content_blocks, list):
            for block in content_blocks:
                if block.get("response_type") == "text":
                    text = block.get("text")
                    if text:
                        candidates.append(("result.data.message.content", text))
    except: pass
    
    # Path 3: output.text (legacy API format)
    output = data.get("output")
    if output and isinstance(output, dict):
        output_text = output.get("text")
        if output_text:
            candidates.append(("output.text", output_text))
    
    # Path 4: result.output (alternative format)
    result = data.get("result")
    if result and isinstance(result, dict):
        result_output = result.get("output")
        if result_output and isinstance(result_output, str):
            candidates.append(("result.output", result_output))
    
    return candidates

@app.post("/ask")
async def ask_ai(req: AskRequest):
    """
    OPTIMIZED VERSION: Handles async Agent tool calls properly
    """
    print(f"\n{'='*60}")
    print(f"DEBUG: 💬 New question: {req.message}")
    print(f"{'='*60}\n")
    
    try:
        # 1. Get IAM Token
        print("DEBUG: 🔑 Getting IAM token...")
        tr = requests.post("https://iam.cloud.ibm.com/identity/token", 
                          data={"grant_type": "urn:ibm:params:oauth:grant-type:apikey", "apikey": API_KEY})
        tr.raise_for_status()
        token = tr.json()["access_token"]
        print("DEBUG: ✅ Token acquired")

        # 2. Start Agent Run
        msg_url = f"{HOST_URL}/v1/orchestrate/runs"
        headers = {
            "Authorization": f"Bearer {token}", 
            "X-IBM-Orchestrate-ID": ORCHESTRATION_ID, 
            "Content-Type": "application/json"
        }
        
        print("DEBUG: 🚀 Starting Agent run...")
        res = requests.post(msg_url, headers=headers, json={
            "message": {"role": "user", "content": req.message}, 
            "agent_id": AGENT_ID
        })
        res.raise_for_status()
        run_id = res.json().get("run_id")
        print(f"DEBUG: ✅ Run started: {run_id}")
        
        # 3. Intelligent Polling with Async Run Support
        poll_url = f"{msg_url}/{run_id}"
        IGNORABLE_PHRASES = ["A new flow has started", "flow has started", "tool is processing"]
        MAX_ATTEMPTS = 60  # 2 minutes max
        POLL_INTERVAL = 2  # seconds
        
        current_run_id = run_id
        async_depth = 0  # Track how many async jumps we've made
        
        for attempt in range(1, MAX_ATTEMPTS + 1):
            time.sleep(POLL_INTERVAL)
            
            current_url = f"{msg_url}/{current_run_id}"
            poll_resp = requests.get(current_url, headers=headers)
            poll_resp.raise_for_status()
            data = poll_resp.json()
            
            status = data.get("status", "unknown")
            result = data.get("result") or {}
            result_type = result.get("type") if isinstance(result, dict) else None
            
            print(f"DEBUG: 📊 Attempt {attempt}/{MAX_ATTEMPTS} - run_id={current_run_id[:8]}..., status={status}, type={result_type}")
            
            # 🔍 DEBUG: Print details periodically
            if attempt <= 3 or (attempt % 10 == 0):
                print(f"DEBUG: 📄 Raw JSON snapshot (first 3000 chars):")
                print(json.dumps(data, indent=2, ensure_ascii=False)[:3000])
            
            # ⭐ CRITICAL: Check if this is an async_initiated response
            if result_type == "async_initiated" and status == "completed":
                target_run_id = data.get("result", {}).get("data", {}).get("target_run_id")
                if target_run_id and target_run_id != current_run_id:
                    print(f"DEBUG: � Async workflow detected! Switching from {current_run_id[:8]}... to target {target_run_id[:8]}...")
                    current_run_id = target_run_id
                    async_depth += 1
                    
                    if async_depth > 3:
                        print(f"DEBUG: ⚠️ Too many async jumps ({async_depth}), stopping")
                        break
                    
                    # Reset attempt counter for the new run
                    continue
            
            # Extract all possible responses
            candidates = extract_ai_response(data)
            
            if candidates:
                print(f"DEBUG: 🔍 Found {len(candidates)} response candidate(s):")
                for path, text in candidates:
                    preview = text[:80] + "..." if len(text) > 80 else text
                    print(f"  - From '{path}': {preview}")
                
                # Filter out placeholder messages
                real_responses = [
                    (path, text) for path, text in candidates 
                    if not any(phrase.lower() in text.lower() for phrase in IGNORABLE_PHRASES)
                ]
                
                if real_responses:
                    path, final_text = real_responses[-1]  # Take the last real response
                    print(f"DEBUG: ✅ Real AI response found via '{path}'!")
                    print(f"DEBUG: 📝 Preview: {final_text[:150]}...")
                    return {"response": final_text}
            
            # Handle terminal states
            if status == "completed" and result_type != "async_initiated":
                print(f"DEBUG: ⚠️ Run completed but no real response found")
                break
            elif status in ["failed", "cancelled"]:
                print(f"DEBUG: ❌ Run {status}")
                return {"response": f"The AI agent encountered an issue (Status: {status}). Please try again."}
        
        # Timeout or no response
        print(f"DEBUG: ⏰ Timeout after {MAX_ATTEMPTS} attempts")
        return {"response": "The request is taking longer than expected. Please try asking in the IBM UI or try again later."}
        
    except requests.exceptions.HTTPError as he:
        print(f"ERROR: ❌ HTTP Error: {he}")
        print(f"ERROR: Response: {he.response.text if hasattr(he, 'response') else 'N/A'}")
        return {"response": f"Connection error: {str(he)}"}
    except Exception as e:
        print(f"ERROR: ❌ Unexpected error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return {"response": "System error. Please check server logs."}

@app.get("/knowledge-base")
async def get_knowledge_base():
    """Returns the content of the Knowledge Base CSV."""
    import csv 
    # Use KB_DIR defined earlier
    csv_path = KB_DIR / "Workplace_IT_Support_Database.csv"
    
    if not os.path.exists(csv_path):
        return []
    
    data = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            data.append(row)
    return data

if __name__ == "__main__":
    import uvicorn
    print("\n🚀 Starting LoopBack AI IT Hub API...")
    print(f"📍 Knowledge Base: {KB_DIR}")
    print(f"📍 Tickets DB: {DB_FILE}")
    print(f"🤖 Watsonx Agent: {AGENT_ID}\n")
    uvicorn.run(app, host="0.0.0.0", port=8000)
