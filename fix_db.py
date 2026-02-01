import json
import re

DB_PATH = "tickets_db.json"

def fix_db():
    with open(DB_PATH, "r") as f:
        data = json.load(f)
    
    # Sort by ID to keep rough order, or by something else?
    # Actually, keep original order, just re-assign IDs.
    
    new_data = []
    id_counter = 1001
    
    for t in data:
        # Re-assign ID
        new_id = f"TKT-{id_counter}"
        old_id = t.get("id")
        t["id"] = new_id
        
        # Determine Group logic:
        # If group_id matched old_id, update it to new_id.
        # This is tricky if groups link distinct tickets.
        # Simple fix: If group_id == old_id, set to new_id.
        if t.get("group_id") == old_id:
            t["group_id"] = new_id
        
        # Auto-fix missing categories based on keywords
        if not t.get("category"):
            q = t.get("query", "").lower()
            
            # Account / Access
            if any(k in q for k in ["password", "login", "account", "user name", "access", "sign in", "sso", "mfa"]):
                t["category"] = "Account"
            
            # Network / Wi-Fi
            elif any(k in q for k in ["wifi", "wi-fi", "internet", "connect", "signal", "network", "slow", "offline", "wan", "router"]):
                t["category"] = "Network"
            
            # Software / Apps
            elif any(k in q for k in ["zoom", "teams", "slack", "outlook", "email", "install", "update", "software", "app", "microsoft"]):
                t["category"] = "Software"
            
            # Hardware
            elif any(k in q for k in ["laptop", "screen", "monitor", "mouse", "keyboard", "printer", "battery", "hardware", "device"]):
                t["category"] = "Hardware"
            
            # Facility / General
            elif any(k in q for k in ["room", "light", "chair", "desk", "coffee", "facility", "building"]):
                t["category"] = "Facility"
            
            # Fallback
            else:
                t["category"] = "Software" # Default catch-all
                
            print(f"Fixed Category for {new_id}: {t['category']}")
        
        new_data.append(t)
        id_counter += 1
        
    with open(DB_PATH, "w") as f:
        json.dump(new_data, f, indent=4)
        print(f"Fixed {len(new_data)} tickets. IDs reset 1001-{id_counter-1}.")

if __name__ == "__main__":
    fix_db()
