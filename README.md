# QShala Quiz Intelligence Platform

An enterprise AI platform engineered for **QShala** to transform 13 years of historical PowerPoint/PDF tournament archives into a searchable, structured knowledge base that generates fresh, validated, age-calibrated quizzes with strict slide-level source provenance.

---

## 🚀 Key Features

1. **Multimodal Document Ingestion Pipeline**:
   - Supports `.pptx`, `.ppt`, and `.pdf` presentation files.
   - Extracts slides, tables, speaker notes, and embedded pictures.
   - Intelligent heuristic slide classifier (distinguishes Questions, Answers, Title slides, and Scoreboards).
   - Reconstructs cross-slide Q&A pairs (linking question on slide $N$ to answer on slide $N+1$).
   - Real-time 7-stage progress visualizer in the UI.

2. **Proprietary Knowledge Base & Hybrid Retrieval**:
   - Dense vector semantic search (`pgvector` / adaptive fallback).
   - Sparse lexical search and full-text keyword matching with query expansion (e.g. *Indigenous Australians* ↔ *Aboriginal*, *First Peoples*, *Dreamtime*).
   - Reciprocal Rank Fusion (RRF) for optimal candidate scoring.
   - Slide Viewer Modal with exact presentation excerpt and notes.

3. **Style-Conditioned Generation**:
   - Four distinct generation modes:
     - **NEW**: Generates novel questions grounded strictly in historical facts.
     - **REMIX**: Pivots perspective on historical questions with fresh clues.
     - **HISTORICAL**: Directly curates existing historical competition questions.
     - **SIMILAR**: Generates sibling questions mirroring the cognitive style of retrieved examples.
   - Swappable AI provider abstraction: Google Gemini, OpenAI, Anthropic, or Local/Offline.

4. **Automated 7-Stage Validation Pipeline**:
   - **Answer Consistency**: Confirms the answer directly resolves the prompt.
   - **Factual Grounding**: Verifies claim against retrieved source slides.
   - **Grade Suitability**: Calibrates reading level and cognitive complexity for target grades (e.g. Grades 3–5).
   - **Duplicate Detection**: Calculates vector cosine similarity against all historical questions (flags duplicates if similarity > 85%).
   - **Internal Consistency**: Verifies 4 distinct, plausible distractors with a single unambiguous answer.
   - **Difficulty Alignment**: Matches Easy, Medium, or Hard cognitive requirements.
   - **Source Provenance**: Links every question to original presentation titles and slide numbers.

5. **Interactive Quiz Review Studio**:
   - Inline question and option editing.
   - Quick regeneration actions: *Make Easier*, *Make Harder*, *Regenerate*, *Generate Similar*.
   - Quality indicator scorecard (Grounding %, Duplicate Risk %, Validation Status).
   - Export to **JSON**, **CSV**, and formatted print sheet.

---

## 🏗️ Architecture

```
User / Admin
     │
     ▼
Next.js 14 Web Frontend (App Router, Tailwind CSS, Lucide Icons)
     │
     ▼ REST API
FastAPI Backend
 ├── Ingestion Pipeline (python-pptx, pdfplumber, cross-slide matcher)
 ├── AI Provider Layer (Gemini, OpenAI, Local Mock)
 ├── Hybrid Retrieval Engine (Dense pgvector + Lexical + RRF)
 ├── Context Builder & QShala Style Exemplars
 ├── LLM Question Generator (New, Remix, Historical, Similar)
 ├── 7-Stage Validation Pipeline & Vector Duplicate Detector
 └── Persistence Layer (PostgreSQL 18 + pgvector / SQLite adaptive fallback)
```

---

## 🛠️ Quickstart & Local Setup

### Prerequisites
- Python 3.10+
- Node.js 18+ and npm

### 1. Backend Setup

```bash
# Activate virtual environment
.\venv\Scripts\activate   # Windows
# or: source venv/bin/activate (Linux/Mac)

# Install dependencies (already pre-installed in this repository)
pip install -r backend/requirements.txt

# Start FastAPI server
python backend/run.py
```
Backend runs at `http://127.0.0.1:8000`. Interactive Swagger API docs are available at `http://127.0.0.1:8000/api/v1/docs`.

### 2. Frontend Setup

```bash
cd frontend
npm install
npm run dev   # or npm run build && npm run start
```
Frontend runs at `http://localhost:3000`.

---

## 📚 Seed Dataset & Demo Instructions

Two authentic QShala-style presentation decks are pre-generated and indexed in the knowledge base:
1. `Australian_History_Quiz_2022.pptx` (Grades 3–5, 21 slides, 10 questions)
2. `World_Geography_and_Oceans_2023.pptx` (Junior Explorers, 5 slides, 2 questions)

### Demo Walkthrough:
1. Navigate to `http://localhost:3000`.
2. View the **Dashboard KPI Cards**: 13 Years of Knowledge, Documents, Extracted Questions, Topics.
3. Open **Knowledge Base** (`/knowledge-base`) and search:
   - `"Australian indigenous history"`
   - Click **View Slide** to inspect original slide text and speaker notes.
4. Open **Upload Center** (`/uploads`):
   - Drag-and-drop any PPTX or PDF file.
   - Watch the live 7-stage progress visualizer.
5. Generate a Quiz:
   - Topic: `Australian History`
   - Grades: `[3] [4] [5]`
   - Questions: `10`
   - Difficulty: `Medium`
   - Click **GENERATE QUIZ**.
6. Review in **Quiz Review Studio**:
   - Inspect question cards with validation scores and slide provenance badges.
   - Click **Make Easier** or **Regenerate** on any question.
   - Click **Export JSON** or **Export CSV** to download the finished quiz.
