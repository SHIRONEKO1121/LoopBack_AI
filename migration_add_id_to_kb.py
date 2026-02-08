import csv
import uuid
from pathlib import Path

KB_FILE = Path("knowledge_base/Workplace_IT_Support_Database.csv")
TEMP_FILE = Path("knowledge_base/kb_temp.csv")

def migrate():
    if not KB_FILE.exists():
        print("KB file not found.")
        return

    with open(KB_FILE, 'r', encoding='utf-8') as infile, \
         open(TEMP_FILE, 'w', newline='', encoding='utf-8') as outfile:
        
        reader = csv.DictReader(infile)
        fieldnames = ['ID'] + reader.fieldnames
        writer = csv.DictWriter(outfile, fieldnames=fieldnames)
        
        writer.writeheader()
        
        for row in reader:
            # Generate ID if not present (which it isn't)
            row['ID'] = str(uuid.uuid4())[:8] # Short UUID for readability
            writer.writerow(row)
            
    # Replace original file
    TEMP_FILE.replace(KB_FILE)
    print("Migration complete: Added 'ID' column to KB CSV.")

if __name__ == "__main__":
    migrate()
