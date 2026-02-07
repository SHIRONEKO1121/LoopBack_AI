# Project LoopBack
`LoopBack` is an AI-powered IT Support Helpdesk system that acts as a first line of defense for support teams. It intelligently handles user inquiries using a Knowledge Base (KB) and escalates complex issues to human agents when necessary. Crucially, it learns from every resolved ticket to improve its future responses.

## Key Features

*   **Intelligent Chat Interface**: Users converse naturally with the AI to troubleshoot issues.
*   **Automatic Escalation**: If the AI cannot resolve an issue (or if hardware/admin intervention is required), it automatically drafts a ticket with a summary of the problem and the full conversation history.
*   **Knowledge Base Integration**:
    *   **Retrieval**: Uses fuzzy search logic to find relevant solutions from a CSV database (`knowledge_base/Workplace_IT_Support_Database.csv`).
    *   **Robust Search**: Matches against "Issue", "Question", and "Tags", ignoring punctuation and case.
    *   **Duplicate Prevention**: Automatically blocks duplicate or highly similar questions from being added to the KB to keep it clean.
*   **Self-Learning**: When an admin marks a ticket as "Resolved" with a quality answer, the system automatically adds that solution to the Knowledge Base for future use.
*   **Admin Dashboard**: View and manage tickets, see AI-drafted solutions, and monitor KB updates.

## Technology Stack

*   **Backend**: Python (FastAPI)
*   **Frontend**: React (Vite + Tailwind CSS + Lucide Icons)
*   **AI Model**: Google Gemini 1.5 Flash (`gemini-1.5-flash-latest` or `gemini-3-flash-preview` if configured)
*   **Database**: JSON file (`tickets_db.json`) for tickets, CSV file for Knowledge Base.

## Setup Instructions

### Prerequisites
*   Python 3.9+
*   Node.js & npm
*   Google Gemini API Key

### Backend Setup
1.  Navigate to the project root:
    ```bash
    cd LoopBack
    ```
2.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```
3.  Set up your environment variables:
    *   Create a `.env` file in the root directory.
    *   add your API key: `GOOGLE_API_KEY=your_api_key_here`
    *   If you wish to use Langsmith services, add 
    `LANGSMITH_TRACING=true`
    `LANGSMITH_ENDPOINT=https://api.smith.langchain.com`
    `LANGSMITH_API_KEY=<your-api-key>`
    `LANGSMITH_PROJECT=<your-project-name>`
    *   Else, simply add the line `LANGSMITH_TRACING=true`


4.  Start the backend server:
    ```bash
    python3 server.py
    ```
    The server will run on `http://localhost:8000`.

### Frontend Setup
1.  Navigate to the frontend directory:
    ```bash
    cd frontend
    ```
2.  Install dependencies:
    ```bash
    npm install
    ```
3.  Start the development server:
    ```bash
    npm run dev
    ```
    The application will be available at `http://localhost:5173`.

## Usage

1.  **User Portal**: Users open the app and type their IT issue. The AI attempts to solve it using the Knowledge Base.
2.  **Ticket Creation**: If unresolved, a ticket is created.
3.  **Admin Resolution**: An admin reviews the ticket via the dashboard (or simulates resolution via API) and provides a final answer.
4.  **Learning**: The system detects the high-quality resolution and adds it to the Knowledge Base for next time.

## Project Structure

*   `server.py`: Main backend logic (App, API endpoints, AI integration).
*   `tickets_db.json`: Stores all ticket data.
*   `knowledge_base/`: Contains the CSV database used for RAG (Retrieval-Augmented Generation).
*   `frontend/`: React source code.
    *   `src/UserPortal.jsx`: The chat interface for end-users.
    *   `src/AdminDashboard.jsx`: Interface for support agents.
