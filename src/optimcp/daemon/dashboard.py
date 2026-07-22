"""Minimal local HTML dashboard for violation rates."""

from __future__ import annotations

import html
from typing import Any, Dict, List

from optimcp.monitor.models import CheckEvent


def render_dashboard(
    stats: Dict[str, Any],
    violations: List[CheckEvent],
) -> str:
    rows = []
    for v in violations:
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(v.timestamp))}</td>"
            f"<td>{html.escape(v.ruleset_id)}</td>"
            f"<td>{html.escape(v.policy)}</td>"
            f"<td>{'yes' if v.refused else 'no'}</td>"
            f"<td><code>{html.escape(v.document_hash[:12])}…</code></td>"
            f"<td>{html.escape(v.summary)}</td>"
            "</tr>"
        )
    by = stats.get("by_ruleset") or []
    rate_rows = []
    for r in by:
        rate_rows.append(
            "<tr>"
            f"<td>{html.escape(r['ruleset_id'])}</td>"
            f"<td>{r['checks']}</td>"
            f"<td>{r['violations']}</td>"
            "</tr>"
        )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>OptiMCP monitor</title>
  <style>
    body {{ font-family: ui-sans-serif, system-ui, sans-serif; margin: 2rem; color: #111; }}
    h1 {{ font-size: 1.4rem; }}
    table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; font-size: 0.9rem; }}
    th, td {{ border: 1px solid #ddd; padding: 0.4rem 0.6rem; text-align: left; vertical-align: top; }}
    th {{ background: #f4f4f4; }}
    code {{ font-size: 0.85em; }}
    .meta {{ color: #555; margin-bottom: 1.5rem; }}
  </style>
</head>
<body>
  <h1>OptiMCP verification monitor</h1>
  <p class="meta">
    Total checks: <strong>{stats.get('total_checks', 0)}</strong> ·
    Violations: <strong>{stats.get('total_violations', 0)}</strong>
  </p>
  <h2>By ruleset</h2>
  <table>
    <thead><tr><th>Ruleset</th><th>Checks</th><th>Violations</th></tr></thead>
    <tbody>
      {''.join(rate_rows) or '<tr><td colspan="3">No checks yet.</td></tr>'}
    </tbody>
  </table>
  <h2>Recent violations</h2>
  <table>
    <thead>
      <tr>
        <th>When</th><th>Ruleset</th><th>Policy</th><th>Refused</th>
        <th>Hash</th><th>Summary</th>
      </tr>
    </thead>
    <tbody>
      {''.join(rows) or '<tr><td colspan="6">No violations logged.</td></tr>'}
    </tbody>
  </table>
  <p class="meta">Send <code>Authorization: Bearer …</code> (token stored in sessionStorage after prompt).</p>
  <script>
    (function () {{
      if (!sessionStorage.getItem('optimcp_token')) {{
        var t = prompt('OptiMCP daemon bearer token (stored in sessionStorage for this tab)');
        if (t) sessionStorage.setItem('optimcp_token', t);
      }}
    }})();
  </script>
</body>
</html>
"""
