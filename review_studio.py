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

PORT = 8001
ROOT = Path(__file__).resolve().parent
DISPUTES_CSV = ROOT / "docs" / "gold_disputes.csv"
SESSION_JSON = ROOT / "docs" / "gold_disputes_session.json"
GOLD_CSV = ROOT / "backend" / "eval_data" / "gold_labels_145.csv"
CHANGELOG_MD = ROOT / "backend" / "eval_data" / "gold_changelog.md"
TAXONOMY_JSON = ROOT / "backend" / "app" / "services" / "tagging" / "qshala_taxonomy_v4.json"

IN_MEMORY_DISPUTES = None

def load_disputes():
    global IN_MEMORY_DISPUTES
    if IN_MEMORY_DISPUTES is not None:
        return IN_MEMORY_DISPUTES
    
    # 1. Base CSV rows
    csv_rows = []
    if DISPUTES_CSV.exists():
        try:
            with open(DISPUTES_CSV, encoding="utf-8-sig") as f:
                csv_rows = list(csv.DictReader(f))
        except Exception as e:
            print(f"Notice reading CSV: {e}")

    # 2. Overlay session JSON if available
    if SESSION_JSON.exists():
        try:
            with open(SESSION_JSON, encoding="utf-8") as f:
                session_rows = json.load(f)
                session_map = {r["id"]: r for r in session_rows}
                for row in csv_rows:
                    if row["id"] in session_map:
                        s = session_map[row["id"]]
                        if s.get("decision"):
                            row["decision"] = s["decision"]
                        if s.get("reviewer_notes"):
                            row["reviewer_notes"] = s["reviewer_notes"]
                        if s.get("run2_pred_l2"):
                            row["run2_pred_l2"] = s["run2_pred_l2"]
        except Exception as e:
            print(f"Notice reading session JSON: {e}")

    IN_MEMORY_DISPUTES = csv_rows
    return IN_MEMORY_DISPUTES

def save_disputes(rows):
    global IN_MEMORY_DISPUTES
    IN_MEMORY_DISPUTES = rows
    
    # Always persist in session JSON first (immune to Excel CSV locks)
    try:
        with open(SESSION_JSON, "w", encoding="utf-8") as f:
            json.dump(rows, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Notice saving session JSON: {e}")

    # Try writing to DISPUTES_CSV
    if not rows:
        return True
    fieldnames = list(rows[0].keys())
    try:
        with open(DISPUTES_CSV, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        return True
    except PermissionError:
        print("Notice: gold_disputes.csv is currently open in Excel or another editor. Saved to session JSON.")
        return False
    except Exception as e:
        print(f"Error saving disputes CSV: {e}")
        return False

def load_taxonomy():
    with open(TAXONOMY_JSON, encoding="utf-8") as f:
        data = json.load(f)
    items = []
    for d in data["level1"]:
        for s in d["level2"]:
            items.append({
                "l1": d["name"],
                "l2": s["name"],
                "desc": s.get("description", "")
            })
    return items

def apply_to_gold():
    disputes = load_disputes()
    try:
        with open(GOLD_CSV, encoding="utf-8-sig") as f:
            gold_rows = list(csv.DictReader(f))
    except Exception as e:
        return 0, f"Error reading gold CSV: {e}"
    
    gold_map = {r["id"]: r for r in gold_rows}
    tax_items = load_taxonomy()
    l2_to_l1 = {x["l2"]: x["l1"] for x in tax_items}
    
    changelog_entries = []
    
    for d in disputes:
        qid = d["id"]
        dec = (d.get("decision") or "").strip().upper()
        if not dec or qid not in gold_map:
            continue
            
        g = gold_map[qid]
        old_l2 = g["gold_l2"]
        old_alt = g.get("alt_l2", "")
        
        if dec == "UPDATE_GOLD":
            new_l2 = d["run2_pred_l2"] or d["run1_pred_l2"]
            g["gold_l2"] = new_l2
            g["gold_l1"] = l2_to_l1.get(new_l2, g["gold_l1"])
            g["label_status"] = "VERIFIED"
            changelog_entries.append({
                "id": qid, "old": old_l2, "new": new_l2,
                "reason": d.get("reviewer_notes") or "Updated from model prediction in Review Studio"
            })
        elif dec == "ADD_ALT":
            alt_to_add = d["run2_pred_l2"] or d["run1_pred_l2"]
            current_alts = [a.strip() for a in old_alt.split("|") if a.strip()]
            if alt_to_add not in current_alts:
                current_alts.append(alt_to_add)
            g["alt_l2"] = "|".join(current_alts)
            g["label_status"] = "VERIFIED"
            changelog_entries.append({
                "id": qid, "old": f"{old_l2} (alts: {old_alt})",
                "new": f"{old_l2} (alts: {g['alt_l2']})",
                "reason": d.get("reviewer_notes") or "Added alternative L2 from Review Studio"
            })
        elif dec == "KEEP_GOLD":
            g["label_status"] = "VERIFIED"
            changelog_entries.append({
                "id": qid, "old": old_l2, "new": old_l2,
                "reason": d.get("reviewer_notes") or "Confirmed Gold is correct over model in Review Studio"
            })
            
    # Save gold CSV safely
    fieldnames = list(gold_rows[0].keys())
    try:
        with open(GOLD_CSV, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(gold_rows)
    except PermissionError:
        return 0, "PermissionError: gold_labels_145.csv is currently open in Excel. Please close Excel and try again."
        
    # Append to changelog
    if changelog_entries:
        lines = []
        if not CHANGELOG_MD.exists():
            lines.append("# Gold Dataset Changelog\n\n| ID | Old Value | New Value | Reason | Date |\n|---|---|---|---|---|")
        else:
            lines.append(CHANGELOG_MD.read_text(encoding="utf-8"))
            
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        for c in changelog_entries:
            lines.append(f"| {c['id']} | {c['old']} | {c['new']} | {c['reason']} | {now_str} |")
            
        CHANGELOG_MD.write_text("\n".join(lines), encoding="utf-8")
        
    # Try flushing disputes back to CSV
    try:
        with open(DISPUTES_CSV, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=list(disputes[0].keys()))
            writer.writeheader()
            writer.writerows(disputes)
    except Exception:
        pass
        
    return len(changelog_entries), "OK"

HTML_CONTENT = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>QShala Ground Truth Review Studio</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    body { background-color: #0d1117; color: #c9d1d9; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; }
    .card-glow:hover { box-shadow: 0 0 15px rgba(59, 130, 246, 0.4); border-color: #3b82f6; }
    kbd { background-color: #21262d; border: 1px solid #30363d; border-radius: 4px; padding: 2px 6px; font-size: 11px; color: #8b949e; }
  </style>
</head>
<body class="min-h-screen flex flex-col justify-between">
  <!-- Top Navigation -->
  <header class="border-b border-gray-800 bg-[#161b22] px-6 py-4 flex items-center justify-between sticky top-0 z-50">
    <div class="flex items-center space-x-3">
      <div class="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center font-bold text-white shadow">Q</div>
      <div>
        <h1 class="text-base font-bold text-white leading-tight">QShala Review Studio</h1>
        <p class="text-xs text-gray-400">Ground Truth & Dispute Resolution</p>
      </div>
    </div>
    
    <div class="flex items-center space-x-6">
      <div class="flex items-center space-x-3">
        <div class="w-48 bg-gray-700 h-2 rounded-full overflow-hidden">
          <div id="prog-bar" class="bg-blue-500 h-full transition-all duration-300" style="width: 0%"></div>
        </div>
        <span id="prog-text" class="text-xs font-mono font-bold text-gray-300">0 / 46</span>
      </div>
      <button onclick="applyAll()" class="bg-green-600 hover:bg-green-500 text-white text-xs font-semibold px-4 py-2 rounded-lg shadow flex items-center space-x-2 transition cursor-pointer">
        <span>Apply Decisions to Dataset</span>
      </button>
    </div>
  </header>

  <!-- Excel Lock Warning Banner (Shown only if Excel is open) -->
  <div id="lock-warning" class="hidden bg-amber-950/90 border-b border-amber-600 text-amber-200 px-6 py-2.5 text-xs flex items-center justify-between">
    <div class="flex items-center space-x-2">
      <span class="font-bold">⚠️ Notice:</span>
      <span>Microsoft Excel currently has <code>gold_disputes.csv</code> open. All your choices are <strong>safely saved</strong> in memory and session cache. Close Excel whenever you want changes synced to the CSV file.</span>
    </div>
    <button onclick="document.getElementById('lock-warning').classList.add('hidden')" class="text-amber-300 hover:text-white font-bold ml-4 text-sm">✕</button>
  </div>

  <!-- Main Review Container -->
  <main class="max-w-5xl w-full mx-auto p-6 flex-grow flex flex-col justify-center">
    <div id="loading" class="text-center py-20 text-gray-400">Loading disputes...</div>

    <div id="review-card" class="hidden space-y-6">
      <!-- Question Metadata Header -->
      <div class="flex items-center justify-between">
        <div class="flex items-center space-x-3">
          <span id="q-id" class="text-sm font-mono font-bold text-blue-400 bg-blue-950/60 px-2.5 py-1 rounded border border-blue-800/80"></span>
          <span id="q-badge" class="text-xs font-bold px-2 py-0.5 rounded"></span>
          <span id="q-rec" class="text-xs text-gray-400 bg-gray-800 px-2 py-0.5 rounded border border-gray-700"></span>
        </div>
        <div class="text-xs text-gray-400 space-x-2">
          <span>Shortcuts: <kbd>1</kbd> Keep Gold &nbsp; <kbd>2</kbd> Accept Model &nbsp; <kbd>3</kbd> Add Alt &nbsp; <kbd>←</kbd> <kbd>→</kbd> Prev/Next</span>
        </div>
      </div>

      <!-- Question & Answer Box -->
      <div class="bg-[#161b22] border border-gray-800 rounded-xl p-6 shadow-xl space-y-4">
        <div>
          <span class="text-xs font-semibold text-gray-400 uppercase tracking-wider">Question</span>
          <p id="q-text" class="text-lg text-white font-medium mt-1 leading-relaxed"></p>
        </div>
        <div class="bg-[#0d1117] border border-gray-800/90 rounded-lg p-3.5 flex items-start space-x-3">
          <span class="bg-emerald-950 text-emerald-400 border border-emerald-800 text-[11px] font-bold px-2 py-0.5 rounded mt-0.5">ANSWER</span>
          <p id="q-ans" class="text-emerald-300 font-semibold text-sm"></p>
        </div>
      </div>

      <!-- Decision Cards Grid (Clicking immediately selects, saves, and advances) -->
      <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
        <!-- Option 1: Keep Gold -->
        <div id="card-opt-1" onclick="chooseDecision('KEEP_GOLD')" class="card-glow bg-[#161b22] border border-gray-800 rounded-xl p-5 cursor-pointer flex flex-col justify-between transition group">
          <div class="space-y-2">
            <div class="flex justify-between items-center">
              <span class="text-xs font-bold text-amber-400 uppercase tracking-wider flex items-center space-x-1.5">
                <span>Option 1: Keep Gold</span>
              </span>
              <div class="flex items-center space-x-1.5">
                <span id="sel-badge-1" class="hidden text-[10px] font-bold px-2 py-0.5 rounded bg-amber-400 text-black shadow">✓ SELECTED</span>
                <kbd>1</kbd>
              </div>
            </div>
            <p id="card-gold-l2" class="text-base font-bold text-white group-hover:text-amber-400 transition"></p>
            <p id="card-gold-l1" class="text-xs text-gray-400 font-mono"></p>
          </div>
          <div class="mt-4 pt-3 border-t border-gray-800/60 text-xs text-gray-400">
            Gold label is accurate; model pick was wrong.
          </div>
        </div>

        <!-- Option 2: Accept Model Prediction -->
        <div id="card-opt-2" onclick="chooseDecision('UPDATE_GOLD')" class="card-glow bg-[#161b22] border border-gray-800 rounded-xl p-5 cursor-pointer flex flex-col justify-between transition group">
          <div class="space-y-2">
            <div class="flex justify-between items-center">
              <span class="text-xs font-bold text-blue-400 uppercase tracking-wider flex items-center space-x-1.5">
                <span>Option 2: Accept Model</span>
              </span>
              <div class="flex items-center space-x-1.5">
                <span id="sel-badge-2" class="hidden text-[10px] font-bold px-2 py-0.5 rounded bg-blue-400 text-black shadow">✓ SELECTED</span>
                <kbd>2</kbd>
              </div>
            </div>
            <p id="card-pred-l2" class="text-base font-bold text-white group-hover:text-blue-400 transition"></p>
            <p id="card-pred-details" class="text-xs text-gray-400 font-mono"></p>
          </div>
          <div class="mt-4 pt-3 border-t border-gray-800/60 text-xs text-gray-400">
            Model pick is strictly better; overwrite gold label.
          </div>
        </div>

        <!-- Option 3: Both Defensible (Add as Alt) -->
        <div id="card-opt-3" onclick="chooseDecision('ADD_ALT')" class="card-glow bg-[#161b22] border border-gray-800 rounded-xl p-5 cursor-pointer flex flex-col justify-between transition group">
          <div class="space-y-2">
            <div class="flex justify-between items-center">
              <span class="text-xs font-bold text-purple-400 uppercase tracking-wider flex items-center space-x-1.5">
                <span>Option 3: Both Defensible</span>
              </span>
              <div class="flex items-center space-x-1.5">
                <span id="sel-badge-3" class="hidden text-[10px] font-bold px-2 py-0.5 rounded bg-purple-400 text-black shadow">✓ SELECTED</span>
                <kbd>3</kbd>
              </div>
            </div>
            <p class="text-base font-bold text-white group-hover:text-purple-400 transition">Add Model as Alt</p>
            <p id="card-alt-preview" class="text-xs text-gray-400 font-mono"></p>
          </div>
          <div class="mt-4 pt-3 border-t border-gray-800/60 text-xs text-gray-400">
            Both categories are valid perspectives. Add to accepted alts.
          </div>
        </div>
      </div>

      <!-- Custom Dropdown & Notes Bar -->
      <div class="bg-[#161b22] border border-gray-800 rounded-xl p-4 flex flex-col md:flex-row items-center justify-between gap-4">
        <div class="flex items-center space-x-3 w-full md:w-auto">
          <span class="text-xs text-gray-400 whitespace-nowrap">Or pick custom:</span>
          <select id="custom-l2" onchange="chooseCustom()" class="bg-[#0d1117] border border-gray-700 text-xs text-white rounded-lg px-3 py-2 w-full md:w-64 focus:outline-none focus:border-blue-500">
            <option value="">-- Choose from 38 Subtopics --</option>
          </select>
        </div>
        <div class="flex items-center space-x-3 w-full md:flex-grow">
          <input id="notes-input" type="text" placeholder="Optional reviewer notes (why you made this choice)..." 
                 class="bg-[#0d1117] border border-gray-700 text-xs text-white rounded-lg px-3 py-2 w-full focus:outline-none focus:border-blue-500">
        </div>
        <div class="flex items-center space-x-2">
          <button onclick="nav(-1)" class="bg-gray-800 hover:bg-gray-700 text-gray-300 text-xs px-3 py-2 rounded-lg transition cursor-pointer">← Prev</button>
          <button onclick="nav(1)" class="bg-gray-800 hover:bg-gray-700 text-gray-300 text-xs px-3 py-2 rounded-lg transition cursor-pointer">Next →</button>
        </div>
      </div>
    </div>
  </main>

  <!-- Bottom Drawer: Question Grid Overview -->
  <footer class="border-t border-gray-800 bg-[#161b22] px-6 py-3">
    <div class="max-w-5xl mx-auto flex items-center justify-between">
      <div class="text-xs text-gray-400 font-medium">Quick Jump:</div>
      <div id="grid-pills" class="flex items-center space-x-1.5 overflow-x-auto py-1 max-w-3xl"></div>
    </div>
  </footer>

  <script>
    let disputes = [];
    let taxonomy = [];
    let currentIndex = 0;

    async function init() {
      try {
        const rTax = await fetch('/api/taxonomy');
        taxonomy = await rTax.json();
        
        const sel = document.getElementById('custom-l2');
        taxonomy.forEach(t => {
          const opt = document.createElement('option');
          opt.value = t.l2;
          opt.textContent = `${t.l1} → ${t.l2}`;
          sel.appendChild(opt);
        });

        const rDisp = await fetch('/api/disputes');
        disputes = await rDisp.json();

        document.getElementById('loading').classList.add('hidden');
        document.getElementById('review-card').classList.remove('hidden');

        renderCurrent();
        renderGrid();
      } catch (e) {
        console.error("Init failed:", e);
      }
    }

    function renderCurrent() {
      if (!disputes.length) return;
      const d = disputes[currentIndex];

      document.getElementById('q-id').textContent = d.id;
      document.getElementById('q-text').textContent = d.question_text;
      document.getElementById('q-ans').textContent = d.answer;

      const badge = document.getElementById('q-badge');
      if (d.verified === 'VERIFIED') {
        badge.className = 'text-xs font-bold px-2 py-0.5 rounded bg-purple-950 text-purple-400 border border-purple-800';
        badge.textContent = 'VERIFIED';
      } else {
        badge.className = 'text-xs font-bold px-2 py-0.5 rounded bg-amber-950 text-amber-400 border border-amber-800';
        badge.textContent = 'SILVER DRAFT';
      }

      document.getElementById('q-rec').textContent = d.action_recommendation || 'Dispute';

      // Card Contents
      document.getElementById('card-gold-l2').textContent = d.gold_l2;
      document.getElementById('card-gold-l1').textContent = `L1: ${d.gold_l1}`;

      const predL2 = d.run2_pred_l2 || d.run1_pred_l2;
      document.getElementById('card-pred-l2').textContent = predL2;
      document.getElementById('card-pred-details').textContent = `Run 1: ${d.run1_pred_l2} | Run 2: ${d.run2_pred_l2}`;

      document.getElementById('card-alt-preview').textContent = `Keep "${d.gold_l2}" + Add "${predL2}"`;

      document.getElementById('notes-input').value = d.reviewer_notes || '';

      // Highlight selected card
      const c1 = document.getElementById('card-opt-1');
      const c2 = document.getElementById('card-opt-2');
      const c3 = document.getElementById('card-opt-3');
      const b1 = document.getElementById('sel-badge-1');
      const b2 = document.getElementById('sel-badge-2');
      const b3 = document.getElementById('sel-badge-3');

      c1.className = "card-glow bg-[#161b22] border border-gray-800 rounded-xl p-5 cursor-pointer flex flex-col justify-between transition group";
      c2.className = "card-glow bg-[#161b22] border border-gray-800 rounded-xl p-5 cursor-pointer flex flex-col justify-between transition group";
      c3.className = "card-glow bg-[#161b22] border border-gray-800 rounded-xl p-5 cursor-pointer flex flex-col justify-between transition group";
      b1.classList.add('hidden');
      b2.classList.add('hidden');
      b3.classList.add('hidden');

      if (d.decision === 'KEEP_GOLD') {
        c1.className = "card-glow bg-amber-950/30 border-2 border-amber-500 rounded-xl p-5 cursor-pointer flex flex-col justify-between transition group ring-2 ring-amber-500/30";
        b1.classList.remove('hidden');
      } else if (d.decision === 'UPDATE_GOLD') {
        c2.className = "card-glow bg-blue-950/30 border-2 border-blue-500 rounded-xl p-5 cursor-pointer flex flex-col justify-between transition group ring-2 ring-blue-500/30";
        b2.classList.remove('hidden');
      } else if (d.decision === 'ADD_ALT') {
        c3.className = "card-glow bg-purple-950/30 border-2 border-purple-500 rounded-xl p-5 cursor-pointer flex flex-col justify-between transition group ring-2 ring-purple-500/30";
        b3.classList.remove('hidden');
      }

      // Progress bar
      const reviewedCount = disputes.filter(x => x.decision).length;
      document.getElementById('prog-text').textContent = `${reviewedCount} / ${disputes.length}`;
      document.getElementById('prog-bar').style.width = `${(reviewedCount / disputes.length) * 100}%`;

      renderGrid();
    }

    function renderGrid() {
      const container = document.getElementById('grid-pills');
      container.innerHTML = '';
      disputes.forEach((d, i) => {
        const btn = document.createElement('button');
        btn.textContent = i + 1;
        let colorClass = 'bg-gray-800 text-gray-400 border border-gray-700';
        if (d.decision === 'KEEP_GOLD') colorClass = 'bg-amber-900/70 text-amber-300 border border-amber-700 font-bold';
        if (d.decision === 'UPDATE_GOLD') colorClass = 'bg-blue-900/70 text-blue-300 border border-blue-700 font-bold';
        if (d.decision === 'ADD_ALT') colorClass = 'bg-purple-900/70 text-purple-300 border border-purple-700 font-bold';
        if (i === currentIndex) colorClass += ' ring-2 ring-white scale-110 shadow';
        btn.className = `w-7 h-7 text-xs font-mono rounded flex items-center justify-center transition cursor-pointer ${colorClass}`;
        btn.onclick = () => { currentIndex = i; renderCurrent(); };
        container.appendChild(btn);
      });
    }

    function chooseDecision(type) {
      if (!disputes.length) return;
      const d = disputes[currentIndex];
      d.decision = type;
      d.reviewer_notes = document.getElementById('notes-input').value;

      // Instant tactile feedback on card
      const c1 = document.getElementById('card-opt-1');
      const c2 = document.getElementById('card-opt-2');
      const c3 = document.getElementById('card-opt-3');
      const b1 = document.getElementById('sel-badge-1');
      const b2 = document.getElementById('sel-badge-2');
      const b3 = document.getElementById('sel-badge-3');

      b1.classList.toggle('hidden', type !== 'KEEP_GOLD');
      b2.classList.toggle('hidden', type !== 'UPDATE_GOLD');
      b3.classList.toggle('hidden', type !== 'ADD_ALT');

      if (type === 'KEEP_GOLD') {
        c1.className = "card-glow bg-amber-950/50 border-2 border-amber-400 rounded-xl p-5 cursor-pointer flex flex-col justify-between transition group ring-4 ring-amber-400/40 scale-[1.02]";
      } else if (type === 'UPDATE_GOLD') {
        c2.className = "card-glow bg-blue-950/50 border-2 border-blue-400 rounded-xl p-5 cursor-pointer flex flex-col justify-between transition group ring-4 ring-blue-400/40 scale-[1.02]";
      } else if (type === 'ADD_ALT') {
        c3.className = "card-glow bg-purple-950/50 border-2 border-purple-400 rounded-xl p-5 cursor-pointer flex flex-col justify-between transition group ring-4 ring-purple-400/40 scale-[1.02]";
      }

      // Asynchronous background persist
      fetch('/api/decision', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: d.id, decision: type, notes: d.reviewer_notes })
      }).then(r => r.json()).then(res => {
        if (res && res.csv_locked) {
          document.getElementById('lock-warning').classList.remove('hidden');
        }
      }).catch(err => {
        console.warn('Network issue saving decision:', err);
      });

      // Advance to next question after 140ms crisp feedback
      setTimeout(() => {
        nav(1);
      }, 140);
    }

    function chooseCustom() {
      const val = document.getElementById('custom-l2').value;
      if (!val) return;
      const d = disputes[currentIndex];
      d.decision = 'UPDATE_GOLD';
      d.run2_pred_l2 = val;
      d.reviewer_notes = `Custom override to ${val}. ` + (document.getElementById('notes-input').value || '');

      fetch('/api/decision', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: d.id, decision: 'UPDATE_GOLD', custom_l2: val, notes: d.reviewer_notes })
      }).then(r => r.json()).then(res => {
        if (res && res.csv_locked) {
          document.getElementById('lock-warning').classList.remove('hidden');
        }
      }).catch(e => console.warn(e));

      document.getElementById('custom-l2').value = '';
      setTimeout(() => nav(1), 140);
    }

    function nav(delta) {
      const target = currentIndex + delta;
      if (target >= disputes.length && delta > 0) {
        // reached end
        const count = disputes.filter(x => x.decision).length;
        if (count === disputes.length) {
          alert("🎉 All 46 disputes have been reviewed! Click 'Apply Decisions to Dataset' to finalize.");
        }
        return;
      }
      currentIndex = Math.max(0, Math.min(disputes.length - 1, target));
      renderCurrent();
    }

    async function applyAll() {
      if (!confirm("Are you sure you want to write all decisions to gold_labels_145.csv and update gold_changelog.md?")) return;
      try {
        const r = await fetch('/api/apply', { method: 'POST' });
        const res = await r.json();
        if (res.status === 'ok') {
          alert(`✅ Success! Applied ${res.applied} changes to gold_labels_145.csv and updated gold_changelog.md.`);
        } else {
          alert(`⚠️ Notice: ${res.message}`);
        }
      } catch (e) {
        alert(`Network error applying decisions: ${e}`);
      }
    }

    window.addEventListener('keydown', (e) => {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;
      if (e.key === '1') chooseDecision('KEEP_GOLD');
      if (e.key === '2') chooseDecision('UPDATE_GOLD');
      if (e.key === '3') chooseDecision('ADD_ALT');
      if (e.key === 'ArrowRight') nav(1);
      if (e.key === 'ArrowLeft') nav(-1);
    });

    init();
  </script>
</body>
</html>
"""

class ReviewHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        if url.path == "/" or url.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_CONTENT.encode("utf-8"))
        elif url.path == "/api/disputes":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(load_disputes()).encode("utf-8"))
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
        
        if url.path == "/api/decision":
            disputes = load_disputes()
            for d in disputes:
                if d["id"] == body.get("id"):
                    d["decision"] = body.get("decision", "")
                    d["reviewer_notes"] = body.get("notes", "")
                    if body.get("custom_l2"):
                        d["run2_pred_l2"] = body.get("custom_l2")
                    break
            saved_csv = save_disputes(disputes)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "csv_locked": not saved_csv}).encode("utf-8"))
        elif url.path == "/api/apply":
            applied_count, msg = apply_to_gold()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            if msg == "OK":
                self.wfile.write(json.dumps({"status": "ok", "applied": applied_count}).encode("utf-8"))
            else:
                self.wfile.write(json.dumps({"status": "error", "message": msg}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

def run():
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), ReviewHandler) as httpd:
        print(f"============================================================")
        print(f"QSHALA REVIEW STUDIO IS LIVE ON: http://localhost:{PORT}")
        print(f"Press Ctrl+C to stop the server.")
        print(f"============================================================")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down server.")

if __name__ == "__main__":
    run()
