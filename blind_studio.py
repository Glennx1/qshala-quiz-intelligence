import http.server
import socketserver
import json
import csv
import webbrowser
import os
import sys
from pathlib import Path
import urllib.parse
import datetime

PORT = 8002
ROOT = Path(__file__).resolve().parent
BLIND_CSV = ROOT / "backend" / "eval_data" / "test_blind_150.csv"
SESSION_JSON = ROOT / "backend" / "eval_data" / "test_blind_150_session.json"
TAXONOMY_JSON = ROOT / "backend" / "app" / "services" / "tagging" / "qshala_taxonomy_v5.json"

IN_MEMORY_BLIND = None

def load_taxonomy():
    with open(TAXONOMY_JSON, encoding="utf-8") as f:
        data = json.load(f)
    domains = []
    l2_to_l1 = {}
    l2_desc = {}
    l2_code = {}
    for d in data["level1"]:
        subtopics = []
        for s in d["level2"]:
            subtopics.append({
                "code": s.get("code", ""),
                "l2": s["name"],
                "desc": s.get("description", "")
            })
            l2_to_l1[s["name"]] = d["name"]
            l2_desc[s["name"]] = s.get("description", "")
            l2_code[s["name"]] = s.get("code", "")
        domains.append({
            "l1": d["name"],
            "subtopics": subtopics
        })
    return {
        "version": data.get("version", "v5"),
        "domains": domains,
        "l2_to_l1": l2_to_l1,
        "l2_desc": l2_desc,
        "l2_code": l2_code
    }

def load_blind():
    global IN_MEMORY_BLIND
    if IN_MEMORY_BLIND is not None:
        return IN_MEMORY_BLIND
    
    csv_rows = []
    if BLIND_CSV.exists():
        try:
            with open(BLIND_CSV, encoding="utf-8-sig") as f:
                csv_rows = list(csv.DictReader(f))
        except Exception as e:
            print(f"Error reading blind CSV: {e}")

    # Overlay session JSON if available
    if SESSION_JSON.exists():
        try:
            with open(SESSION_JSON, encoding="utf-8") as f:
                session_rows = json.load(f)
                session_map = {r["id"]: r for r in session_rows}
                for r in csv_rows:
                    if r["id"] in session_map:
                        s = session_map[r["id"]]
                        for k in ["human_l1", "human_l2", "human_alt_l2", "ambiguous", "note", "labeller", "labelled_at"]:
                            if s.get(k):
                                r[k] = s[k]
        except Exception as e:
            print(f"Error reading session JSON: {e}")

    IN_MEMORY_BLIND = csv_rows
    return IN_MEMORY_BLIND

def save_blind(rows):
    global IN_MEMORY_BLIND
    IN_MEMORY_BLIND = rows
    
    # Always save to session JSON (Excel-proof)
    try:
        with open(SESSION_JSON, "w", encoding="utf-8") as f:
            json.dump(rows, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving session JSON: {e}")

    # Try saving to CSV
    if not rows:
        return True
    fieldnames = list(rows[0].keys())
    try:
        with open(BLIND_CSV, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(rows)
        return True
    except PermissionError:
        print("Notice: test_blind_150.csv is open in Excel. Saved safely to session JSON.")
        return False
    except Exception as e:
        print(f"Error saving blind CSV: {e}")
        return False

HTML_CONTENT = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>QShala Blind-Labelling Studio (Taxonomy v5 — 61 Subtopics)</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    body { background-color: #0b0f17; color: #cbd5e1; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
    kbd { background-color: #1e293b; border: 1px solid #334155; border-radius: 4px; padding: 2px 6px; font-size: 11px; color: #94a3b8; }
  </style>
</head>
<body class="min-h-screen flex flex-col justify-between">
  <!-- Top Navigation Bar -->
  <header class="border-b border-slate-800 bg-[#111827] px-6 py-4 flex items-center justify-between sticky top-0 z-50 shadow-md">
    <div class="flex items-center space-x-3">
      <div class="w-8 h-8 rounded-lg bg-indigo-600 flex items-center justify-center font-bold text-white shadow">B</div>
      <div>
        <h1 class="text-base font-bold text-white leading-tight">QShala Blind-Labelling Studio</h1>
        <p class="text-xs text-indigo-400 font-medium">Taxonomy v5 (8 Domains, 61 Subtopics) &bull; Frozen Test Set</p>
      </div>
    </div>
    
    <div class="flex items-center space-x-6">
      <div class="flex items-center space-x-2">
        <label class="text-xs text-slate-400">Labeller:</label>
        <input id="labeller-input" type="text" value="GB" class="bg-slate-900 border border-slate-700 text-xs text-white rounded px-2.5 py-1 w-20 focus:outline-none focus:border-indigo-500">
      </div>
      <div class="flex items-center space-x-3">
        <div class="w-44 bg-slate-800 h-2 rounded-full overflow-hidden">
          <div id="prog-bar" class="bg-indigo-500 h-full transition-all duration-300" style="width: 0%"></div>
        </div>
        <span id="prog-text" class="text-xs font-mono font-bold text-slate-300">0 / 150</span>
      </div>
    </div>
  </header>

  <!-- Excel Warning Banner (hidden by default) -->
  <div id="lock-warning" class="hidden bg-amber-950/90 border-b border-amber-600 text-amber-200 px-6 py-2.5 text-xs flex items-center justify-between">
    <span>⚠️ Notice: <code>test_blind_150.csv</code> is currently open in Excel. Your labels are <strong>safely saved</strong> in session cache. Close Excel to sync to CSV.</span>
    <button onclick="document.getElementById('lock-warning').classList.add('hidden')" class="text-amber-300 font-bold ml-4">✕</button>
  </div>

  <!-- Main Question Box -->
  <main class="max-w-4xl w-full mx-auto p-6 flex-grow flex flex-col justify-center space-y-6">
    <div id="loading" class="text-center py-24 text-slate-400">Loading blind test set...</div>

    <div id="review-card" class="hidden space-y-6">
      <!-- Question Card (QUESTION & ANSWER ONLY - STRICTLY NO MODEL PREDICTIONS) -->
      <div class="bg-[#111827] border border-slate-800 rounded-2xl p-6 shadow-xl space-y-4">
        <div class="flex items-center justify-between border-b border-slate-800/80 pb-3">
          <div class="flex items-center space-x-3">
            <span id="q-id" class="text-xs font-mono font-bold text-indigo-400 bg-indigo-950/70 px-2.5 py-1 rounded border border-indigo-800"></span>
            <span class="text-xs bg-slate-800 text-slate-400 px-2.5 py-0.5 rounded border border-slate-700 font-medium">Blind Test Set</span>
          </div>
          <span class="text-xs text-slate-400">Shortcuts: <kbd>Enter</kbd> Save & Next &nbsp; <kbd>←</kbd> <kbd>→</kbd> Prev/Next</span>
        </div>

        <div>
          <span class="text-[11px] font-bold text-slate-400 uppercase tracking-wider">Question Text</span>
          <p id="q-text" class="text-lg text-white font-medium mt-1 leading-relaxed"></p>
        </div>

        <div class="bg-[#0b0f17] border border-emerald-900/60 rounded-xl p-4 flex items-start space-x-3 shadow-inner">
          <span class="bg-emerald-600 text-white text-[10px] font-bold px-2 py-0.5 rounded shadow">ANSWER</span>
          <p id="q-ans" class="text-emerald-300 font-semibold text-sm leading-snug"></p>
        </div>
      </div>

      <!-- Human Label Form (Taxonomy v5 Ground Truth) -->
      <div class="bg-[#111827] border border-slate-800 rounded-2xl p-6 shadow-xl space-y-5">
        <div class="flex items-center justify-between">
          <h3 class="text-xs font-bold text-slate-400 uppercase tracking-wider">Human Ground Truth Classification (Taxonomy v5)</h3>
          <span class="text-[11px] font-mono text-indigo-400 bg-indigo-950/50 px-2 py-0.5 rounded border border-indigo-900/60">61 Subtopics Available</span>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-5">
          <!-- L1 Domain Dropdown -->
          <div class="space-y-1.5">
            <label class="text-xs font-semibold text-slate-300">1. Macro Domain (Level 1) *</label>
            <select id="sel-l1" onchange="onL1Change()" class="w-full bg-[#0b0f17] border border-slate-700 text-xs text-white rounded-xl px-3.5 py-2.5 focus:outline-none focus:border-indigo-500">
              <option value="">-- Choose Macro Domain (8) --</option>
            </select>
          </div>

          <!-- L2 Subtopic Dropdown -->
          <div class="space-y-1.5">
            <label class="text-xs font-semibold text-slate-300">2. Subtopic (Level 2) *</label>
            <select id="sel-l2" onchange="onL2Change()" class="w-full bg-[#0b0f17] border border-slate-700 text-xs text-white rounded-xl px-3.5 py-2.5 focus:outline-none focus:border-indigo-500" disabled>
              <option value="">-- First choose Domain above --</option>
            </select>
          </div>
        </div>

        <!-- Description Tooltip Box -->
        <div id="desc-box" class="hidden text-xs text-slate-300 bg-slate-900/80 border border-slate-800 p-3 rounded-xl">
          <span class="font-bold text-indigo-400" id="desc-title"></span>
          <p id="desc-text" class="mt-0.5 text-slate-300 italic"></p>
        </div>

        <!-- Second Acceptable L2 (Optional) -->
        <div class="grid grid-cols-1 md:grid-cols-2 gap-5 pt-1">
          <div class="space-y-1.5">
            <label class="text-xs font-semibold text-slate-400">Second Acceptable Subtopic (Optional alternative)</label>
            <select id="sel-alt-l2" class="w-full bg-[#0b0f17] border border-slate-700 text-xs text-white rounded-xl px-3.5 py-2.5 focus:outline-none focus:border-indigo-500">
              <option value="">-- None (Single primary topic) --</option>
            </select>
          </div>

          <div class="space-y-1.5">
            <label class="text-xs font-semibold text-slate-400">Reviewer Note (Optional context / why)</label>
            <input id="note-input" type="text" placeholder="Why this category, or context notes..." class="w-full bg-[#0b0f17] border border-slate-700 text-xs text-white rounded-xl px-3.5 py-2.5 focus:outline-none focus:border-indigo-500">
          </div>
        </div>

        <!-- Ambiguous Checkbox -->
        <div class="flex items-center space-x-2 pt-2">
          <input id="chk-ambiguous" type="checkbox" class="w-4 h-4 text-indigo-600 rounded bg-slate-900 border-slate-700 focus:ring-indigo-500">
          <label for="chk-ambiguous" class="text-xs text-slate-300 select-none cursor-pointer">
            <strong>Ambiguous question:</strong> genuinely dual-topic or multiple defensible perspectives.
          </label>
        </div>

        <!-- Action Buttons -->
        <div class="flex items-center justify-between pt-4 border-t border-slate-800">
          <div class="flex items-center space-x-2">
            <button onclick="nav(-1)" class="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold rounded-xl transition cursor-pointer">
              ← Prev
            </button>
            <button onclick="nav(1)" class="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold rounded-xl transition cursor-pointer">
              Next →
            </button>
          </div>

          <button onclick="saveAndNext()" class="px-6 py-2.5 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-bold rounded-xl shadow-lg transition flex items-center space-x-2 cursor-pointer">
            <span>Save & Next Question (<kbd class="text-indigo-200 bg-indigo-800/80 border-indigo-700">Enter</kbd>)</span>
          </button>
        </div>
      </div>
    </div>
  </main>

  <!-- Bottom Drawer: Question Pills -->
  <footer class="border-t border-slate-800 bg-[#111827] px-6 py-3">
    <div class="max-w-4xl mx-auto flex items-center justify-between">
      <div class="text-xs text-slate-400 font-medium">Quick Jump:</div>
      <div id="grid-pills" class="flex items-center space-x-1 overflow-x-auto py-1 max-w-2xl"></div>
    </div>
  </footer>

  <script>
    let taxonomy = null;
    let questions = [];
    let currentIndex = 0;

    async function init() {
      const [rTax, rQ] = await Promise.all([
        fetch('/api/taxonomy'),
        fetch('/api/questions')
      ]);
      taxonomy = await rTax.json();
      questions = await rQ.json();

      // Populate L1 dropdown (8 Macro Domains)
      const selL1 = document.getElementById('sel-l1');
      taxonomy.domains.forEach(d => {
        const opt = document.createElement('option');
        opt.value = d.l1;
        opt.textContent = `${d.l1} (${d.subtopics.length} subtopics)`;
        selL1.appendChild(opt);
      });

      // Populate Alt L2 dropdown with all 61 subtopics grouped by domain
      const selAlt = document.getElementById('sel-alt-l2');
      taxonomy.domains.forEach(d => {
        const grp = document.createElement('optgroup');
        grp.label = d.l1;
        d.subtopics.forEach(s => {
          const opt = document.createElement('option');
          opt.value = s.l2;
          opt.textContent = `${s.l2} [${s.code}]`;
          opt.title = s.desc;
          grp.appendChild(opt);
        });
        selAlt.appendChild(grp);
      });

      document.getElementById('loading').classList.add('hidden');
      document.getElementById('review-card').classList.remove('hidden');

      renderCurrent();
      renderGrid();
    }

    function onL1Change() {
      const l1 = document.getElementById('sel-l1').value;
      const selL2 = document.getElementById('sel-l2');
      selL2.innerHTML = '<option value="">-- Choose Subtopic (Level 2) --</option>';
      document.getElementById('desc-box').classList.add('hidden');

      if (!l1) {
        selL2.disabled = true;
        return;
      }

      const domain = taxonomy.domains.find(d => d.l1 === l1);
      if (domain) {
        domain.subtopics.forEach(s => {
          const opt = document.createElement('option');
          opt.value = s.l2;
          opt.textContent = `${s.l2} [${s.code}]`;
          opt.title = s.desc;
          selL2.appendChild(opt);
        });
        selL2.disabled = false;
      }
    }

    function onL2Change() {
      const l2 = document.getElementById('sel-l2').value;
      const descBox = document.getElementById('desc-box');
      if (l2 && taxonomy.l2_desc[l2]) {
        const code = taxonomy.l2_code[l2] || '';
        document.getElementById('desc-title').textContent = `${l2} [${code}]:`;
        document.getElementById('desc-text').textContent = `"${taxonomy.l2_desc[l2]}"`;
        descBox.classList.remove('hidden');
      } else {
        descBox.classList.add('hidden');
      }
    }

    function renderCurrent() {
      if (!questions.length) return;
      const q = questions[currentIndex];

      document.getElementById('q-id').textContent = q.id;
      document.getElementById('q-text').textContent = q.question_text;
      document.getElementById('q-ans').textContent = q.answer;

      // Reset / Fill form fields
      document.getElementById('sel-l1').value = q.human_l1 || '';
      onL1Change();
      document.getElementById('sel-l2').value = q.human_l2 || '';
      onL2Change();
      document.getElementById('sel-alt-l2').value = q.human_alt_l2 || '';
      document.getElementById('chk-ambiguous').checked = q.ambiguous === 'Y';
      document.getElementById('note-input').value = q.note || '';

      // Progress count
      const labelledCount = questions.filter(x => x.human_l2).length;
      document.getElementById('prog-text').textContent = `${labelledCount} / ${questions.length}`;
      document.getElementById('prog-bar').style.width = `${(labelledCount / questions.length) * 100}%`;

      renderGrid();
    }

    function renderGrid() {
      const container = document.getElementById('grid-pills');
      container.innerHTML = '';
      questions.forEach((q, i) => {
        const btn = document.createElement('button');
        btn.textContent = i + 1;
        let colorClass = 'bg-slate-800 text-slate-400 border border-slate-700';
        if (q.human_l2) {
          colorClass = 'bg-indigo-900/80 text-indigo-200 border border-indigo-600 font-bold';
        }
        if (i === currentIndex) {
          colorClass += ' ring-2 ring-white scale-110 shadow';
        }
        btn.className = `w-6 h-6 text-[10px] font-mono rounded flex items-center justify-center transition cursor-pointer shrink-0 ${colorClass}`;
        btn.onclick = () => { currentIndex = i; renderCurrent(); };
        container.appendChild(btn);
      });
    }

    async function saveAndNext() {
      const q = questions[currentIndex];
      const l1 = document.getElementById('sel-l1').value;
      const l2 = document.getElementById('sel-l2').value;

      if (!l1 || !l2) {
        alert('Please select both Macro Domain (L1) and Subtopic (L2) before saving.');
        return;
      }

      q.human_l1 = l1;
      q.human_l2 = l2;
      q.human_alt_l2 = document.getElementById('sel-alt-l2').value;
      q.ambiguous = document.getElementById('chk-ambiguous').checked ? 'Y' : 'N';
      q.note = document.getElementById('note-input').value;
      q.labeller = document.getElementById('labeller-input').value || 'GB';
      q.labelled_at = new Date().toISOString();

      fetch('/api/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(q)
      }).then(r => r.json()).then(res => {
        if (res && res.csv_locked) {
          document.getElementById('lock-warning').classList.remove('hidden');
        }
      }).catch(err => console.warn(err));

      if (currentIndex < questions.length - 1) {
        nav(1);
      } else {
        alert('🎉 Congratulations! You have labelled all 150 questions in the blind test set!');
      }
    }

    function nav(delta) {
      currentIndex = Math.max(0, Math.min(questions.length - 1, currentIndex + delta));
      renderCurrent();
    }

    window.addEventListener('keydown', (e) => {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') {
        if (e.key === 'Enter') {
          saveAndNext();
        }
        return;
      }
      if (e.key === 'Enter') saveAndNext();
      if (e.key === 'ArrowRight') nav(1);
      if (e.key === 'ArrowLeft') nav(-1);
    });

    init();
  </script>
</body>
</html>
"""

class BlindHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        if url.path == "/" or url.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_CONTENT.encode("utf-8"))
        elif url.path == "/api/questions":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(load_blind()).encode("utf-8"))
        elif url.path == "/api/taxonomy":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(load_taxonomy()).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        url = urllib.parse.urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length).decode("utf-8")) if length > 0 else {}
        
        if url.path == "/api/save":
            rows = load_blind()
            for r in rows:
                if r["id"] == body.get("id"):
                    for k in ["human_l1", "human_l2", "human_alt_l2", "ambiguous", "note", "labeller", "labelled_at"]:
                        r[k] = body.get(k, "")
                    break
            saved_csv = save_blind(rows)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "csv_locked": not saved_csv}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

def run():
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), BlindHandler) as httpd:
        print("=" * 60)
        print(f"QSHALA BLIND-LABELLING STUDIO (v5) IS LIVE ON: http://localhost:{PORT}")
        print("Taxonomy v5: 8 Domains, 61 Subtopics.")
        print("Shows Question + Answer ONLY. No predictions, no hints.")
        print("Press Ctrl+C to stop.")
        print("=" * 60)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down server.")

if __name__ == "__main__":
    run()
