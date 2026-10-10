# Prompt CAD Studio 3.0.0

V3 retains CAD/circuit documents, history and PCAD compatibility.

Timeline rows and tooltips omit automatic AI prefixes, including saved legacy steps. Original history, response provenance, restoration data and manually authored names remain intact.

- Open AI explicitly from the toolbar, View menu or Ctrl+Shift+A. An active AI tab stays visible while selecting CAD targets.
- Automatic discovery prefers the installed Codex desktop CLI over obsolete default paths; explicit custom paths remain authoritative. Select models/efforts from the actual account catalog. This PC returned gpt-6.1-sol with Low, Medium, High, Extra high, Max and Ultra.
- Model/effort changes preserve running responses and completed drafts. A later design stage samples new settings; streaming requests/retries keep captured settings. Application records actual response provenance. Changed CAD baselines still prevent stale application.
- Recover transient transport errors, preserve completed JSON after EOF, and avoid restarting healthy servers for every upstream error. Authentication/quota/unsupported settings require intervention. Retries can consume subscription usage; there is no paid API fallback.
- Import bounded local folder/ZIP library snapshots in the firmware editor's Libraries tab. Record exact versions/hashes and inspect sources. Pinned external dependency references remain uninstalled/unverified. Sources and firmware-dependencies.json survive PCAD save/reopen/export.
- Explicit source checks cover Python syntax, recognizable imports/C includes and board/netlist bindings. They do not prove SDK/link builds, full MCU/Linux/FOC execution or hardware operation. Code is never automatically executed, installed or flashed.
- Electrical photo/symptom diagnosis compares entered readings and stored circuit/ratings locally. A separate explicit Codex send button transmits selected photos/evidence; opening the dialog or attaching images sends nothing. Reports export separately and never edit the circuit.
- Photo findings are hypotheses with required confirmations. Hidden continuity, actual ampacity/current/temperature and safe operation remain unverified. Missing ratings and unsuitable measurement conditions remain unknown.

An actual subscription gpt-6.1-sol request generated a harmless multi-file Pi 4 candidate with a pure Python parser library. Source checks and PCAD save/reopen/export passed; source was not executed. Ultra, synthetic photo and native workflow results are recorded separately. Target SDK builds and equipment validation remain unverified.

See [OpenAI model documentation](https://developers.openai.com/api/docs/models/gpt-6.1-sol) and [Codex app-server documentation](https://developers.openai.com/codex/app-server). Actual installed CLI/account catalogs determine available settings.
