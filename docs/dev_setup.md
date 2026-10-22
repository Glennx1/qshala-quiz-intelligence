# QShala Quiz Intelligence — Development Setup

## Environment & Prerequisites
- Python 3.11+ (Windows / Linux / macOS)
- Node.js 18+ (for frontend)
- Git

## Backend Setup & Verification Commands

1. **Activate Python Environment:**
   Ensure Python 3.11 with virtual environment or system packages is available.

2. **Run Pytest Suite:**
   ```bash
   cd C:\Users\aaksh\Downloads\qshala\qshala-quiz-intelligence
   pytest
   ```
   *Result: 24 passed (all tests green).*

3. **Verify FastAPI Application Startup:**
   ```bash
   python -c "from backend.app.main import app; print('App loaded successfully:', app.title)"
   ```
   *Result: "QShala Quiz Intelligence Platform" loads cleanly.*

4. **Run Backend Development Server:**
   ```bash
   uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
   ```

5. **Run Evaluation Harness:**
   ```powershell
   $env:GEMINI_API_KEY = "<your-key>"
   python -u backend/eval_qshala_tagger.py --limit 10 --throttle 1.0
   ```
