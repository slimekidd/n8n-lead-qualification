"""Prepare n8n workflow exports for a public portfolio.

Replaces personal identifiers with placeholders, strips instance-specific
metadata and pinned data, fixes known typos. Usage:

    python clean_exports.py <src_dir> <out_dir>
"""
import json
import re
import sys
from pathlib import Path

PLACEHOLDERS = {
    "360338086": "YOUR_TELEGRAM_CHAT_ID",
    "1syEJ95wQNEr4LVqvdS8JwKT0NQrT4f9IVF1h_1ggDh4": "YOUR_GOOGLE_SHEET_ID",
    "http://n8n-portfolio-test:5678": "http://YOUR_N8N_HOST:5678",
}
CREDENTIAL_NAMES = {
    "postgres": "Postgres (leads DB)",
    "telegramApi": "Telegram Bot",
    "googleSheetsOAuth2Api": "Google Sheets OAuth2",
    "googlePalmApi": "Google Gemini API",
    "httpHeaderAuth": "Webhook Header Auth",
    "n8nApi": "n8n API",
}
NODE_RENAMES = {
    "ead no longer owned by this execution": "Lead no longer owned by this execution",
}
STRIP_TOP = {"versionId", "meta", "instanceId", "nodeGroups", "tags", "active"}


def clean_value(v):
    if isinstance(v, str):
        for old, new in PLACEHOLDERS.items():
            v = v.replace(old, new)
        return v
    if isinstance(v, list):
        return [clean_value(x) for x in v]
    if isinstance(v, dict):
        return {k: clean_value(x) for k, x in v.items()}
    return v


def clean_workflow(wf):
    wf = clean_value(wf)
    for key in list(wf):
        if key in STRIP_TOP:
            del wf[key]
    wf["pinData"] = {}
    for node in wf["nodes"]:
        node["name"] = NODE_RENAMES.get(node["name"], node["name"])
        if "credentials" in node:
            for ctype, cred in node["credentials"].items():
                cred["id"] = "REPLACE_ME"
                cred["name"] = CREDENTIAL_NAMES.get(ctype, cred["name"])
        # Google Sheets cached names/urls reveal the test spreadsheet
        p = node.get("parameters", {})
        for field in ("documentId", "sheetName"):
            if isinstance(p.get(field), dict):
                p[field].pop("cachedResultUrl", None)
                if field == "documentId":
                    p[field]["cachedResultName"] = "Leads"
    # connections reference node names
    conns = wf["connections"]
    for old, new in NODE_RENAMES.items():
        if old in conns:
            conns[new] = conns.pop(old)
        for outs in conns.values():
            for branch in outs.get("main", []):
                for c in branch:
                    if c["node"] == old:
                        c["node"] = new
    return wf


def main(src, out):
    src, out = Path(src), Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for f in sorted(src.glob("*.json")):
        wf = json.loads(f.read_text(encoding="utf-8"))
        cleaned = clean_workflow(wf)
        (out / f.name).write_text(json.dumps(cleaned, ensure_ascii=False, indent=2), encoding="utf-8")
        text = (out / f.name).read_text(encoding="utf-8")
        leaks = [k for k in PLACEHOLDERS if k in text]
        print(f"{f.name}: {len(cleaned['nodes'])} nodes, leaks={leaks}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
