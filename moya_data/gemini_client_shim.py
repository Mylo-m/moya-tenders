"""Shim: reads a tender-text file path (arg1), prints Gemini shred output.

Called by moya_ai.php (mylo_moya_gemini_shred). Reads GEMINI_API_KEY from the
environment (set by the host bootstrap). Exits non-zero on any failure so PHP
falls back to the heuristic analyzer.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gemini_client as g

if len(sys.argv) < 2:
    sys.exit("usage: gemini_client_shim.py <tender_text_file>")
if not g.gemini_configured():
    sys.exit("GEMINI_API_KEY not set")

with open(sys.argv[1], "r", encoding="utf-8", errors="replace") as f:
    text = f.read()

try:
    out = g.gemini_shred(text)
except Exception as e:
    sys.exit(f"gemini error: {e}")

if not out:
    sys.exit("empty output")
print(out)
