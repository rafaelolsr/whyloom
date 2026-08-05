"""Render the indexed graph as a self-contained, offline HTML view.

The map is a *view* over the generated graph, never a new source of truth. It
embeds the current nodes and edges plus a summary, and draws them with a small
dependency-free force layout so the file opens in any browser with no network
access. Governed records are marked authoritative; rationale and inferred edges
are visually distinguished so the picture never overstates what is trusted."""

from __future__ import annotations

import html
import json
from collections import Counter

from .store import GraphStore

# Node types shown in the map, in legend order, with display colors.
_TYPE_COLORS = {
    "Decision": "#fbbf24",
    "Constraint": "#f97316",
    "Architecture": "#f59e0b",
    "Incident": "#ef4444",
    "File": "#38bdf8",
    "Symbol": "#5eead4",
    "ConfigKey": "#a78bfa",
    "Community": "#64748b",
    "Rationale": "#94a3b8",
}
_AUTHORITATIVE = {"Decision", "Constraint", "Architecture", "Incident"}


def build_map_payload(store: GraphStore, max_nodes: int = 600) -> dict:
    """Collect a bounded, view-only snapshot of the graph for rendering."""
    nodes = store.all_nodes()
    edges = store.all_edges()
    type_counts = Counter(node["type"] for node in nodes)
    edge_counts = Counter(edge["type"] for edge in edges)

    # Bound the drawing for readability; keep records and communities first so
    # the governed layer is never dropped by truncation.
    priority = {"Decision": 0, "Constraint": 0, "Architecture": 0, "Incident": 0, "Community": 1}
    ordered = sorted(nodes, key=lambda node: priority.get(node["type"], 2))
    kept = ordered[:max_nodes]
    kept_ids = {node["id"] for node in kept}
    truncated = len(nodes) - len(kept)

    view_nodes = [
        {
            "id": node["id"],
            "type": node["type"],
            "label": node["label"][:80],
            "authoritative": node["type"] in _AUTHORITATIVE
            and node.get("data", {}).get("status") in {"stable", "accepted", "implemented"},
        }
        for node in kept
    ]
    view_edges = [
        {"source": edge["source"], "target": edge["target"], "type": edge["type"], "provenance": edge["provenance"]}
        for edge in edges
        if edge["source"] in kept_ids and edge["target"] in kept_ids
    ]
    return {
        "nodes": view_nodes,
        "edges": view_edges,
        "summary": {
            "node_counts": dict(sorted(type_counts.items())),
            "edge_counts": dict(sorted(edge_counts.items())),
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "drawn_nodes": len(view_nodes),
            "truncated_nodes": max(0, truncated),
        },
    }


def render_map_html(payload: dict, title: str = "Whyloom map") -> str:
    """Return a complete, standalone HTML document for the payload."""
    data_json = json.dumps(payload)
    colors_json = json.dumps(_TYPE_COLORS)
    summary = payload["summary"]
    safe_title = html.escape(title)
    counts_rows = "".join(
        f"<tr><td><span class='dot' style='background:{_TYPE_COLORS.get(node_type, '#888')}'></span>{html.escape(node_type)}</td><td>{count}</td></tr>"
        for node_type, count in summary["node_counts"].items()
    )
    trunc_note = (
        f"<p class='note'>Showing {summary['drawn_nodes']} of {summary['total_nodes']} nodes "
        f"({summary['truncated_nodes']} not drawn for readability).</p>"
        if summary["truncated_nodes"]
        else ""
    )
    return _TEMPLATE.format(
        title=safe_title,
        data_json=data_json,
        colors_json=colors_json,
        total_nodes=summary["total_nodes"],
        total_edges=summary["total_edges"],
        counts_rows=counts_rows,
        trunc_note=trunc_note,
    )


# Standalone document: inline CSS + a tiny force layout on canvas. No CDN.
_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{ margin:0; font-family: system-ui, sans-serif; background:#0b1018; color:#e2e8f0; }}
  header {{ padding:14px 20px; border-bottom:1px solid #1e293b; }}
  header h1 {{ margin:0; font-size:18px; letter-spacing:1px; }}
  header p {{ margin:4px 0 0; color:#94a3b8; font-size:13px; }}
  .layout {{ display:flex; height:calc(100vh - 62px); }}
  aside {{ width:280px; padding:16px 20px; overflow:auto; border-right:1px solid #1e293b; }}
  main {{ flex:1; position:relative; }}
  canvas {{ width:100%; height:100%; display:block; }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  td {{ padding:3px 0; }}
  td:last-child {{ text-align:right; color:#94a3b8; }}
  .dot {{ display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:8px; vertical-align:middle; }}
  .note {{ color:#f59e0b; font-size:12px; }}
  h2 {{ font-size:12px; text-transform:uppercase; letter-spacing:1px; color:#64748b; margin:18px 0 6px; }}
  #tip {{ position:absolute; pointer-events:none; background:#111827; border:1px solid #334155; padding:6px 9px; border-radius:6px; font-size:12px; display:none; max-width:320px; }}
  .trust {{ font-size:12px; color:#94a3b8; margin-top:16px; border-top:1px solid #1e293b; padding-top:12px; }}
</style></head><body>
<header>
  <h1>WHYLOOM MAP</h1>
  <p>A view over the generated graph — {total_nodes} nodes, {total_edges} edges. The graph is a cache, never the source of truth.</p>
</header>
<div class="layout">
  <aside>
    <h2>Nodes by type</h2>
    <table>{counts_rows}</table>
    {trunc_note}
    <div class="trust">Gold-ringed nodes are accepted governing records. Dashed edges are inferred, not extracted. Hover a node for detail.</div>
  </aside>
  <main><canvas id="c"></canvas><div id="tip"></div></main>
</div>
<script>
const DATA = {data_json};
const COLORS = {colors_json};
const canvas = document.getElementById('c'), ctx = canvas.getContext('2d'), tip = document.getElementById('tip');
let W=0,H=0;
function resize(){{ W=canvas.width=canvas.offsetWidth; H=canvas.height=canvas.offsetHeight; }}
resize(); addEventListener('resize', resize);
// Deterministic seeded layout (no Math.random) so the same graph looks the same.
let seed=1; function rnd(){{ seed=(seed*1103515245+12345)&0x7fffffff; return seed/0x7fffffff; }}
const idx = new Map(DATA.nodes.map((n,i)=>[n.id,i]));
const P = DATA.nodes.map(()=>({{x:rnd()*W, y:rnd()*H, vx:0, vy:0}}));
const E = DATA.edges.filter(e=>idx.has(e.source)&&idx.has(e.target)).map(e=>({{s:idx.get(e.source),t:idx.get(e.target),inf:e.provenance!=='EXTRACTED'}}));
function step(){{
  for(let i=0;i<P.length;i++){{ for(let j=i+1;j<P.length;j++){{
    let dx=P[i].x-P[j].x, dy=P[i].y-P[j].y, d=Math.hypot(dx,dy)||1, f=1400/(d*d);
    let ux=dx/d, uy=dy/d; P[i].vx+=ux*f; P[i].vy+=uy*f; P[j].vx-=ux*f; P[j].vy-=uy*f;
  }} }}
  for(const e of E){{ let a=P[e.s],b=P[e.t],dx=b.x-a.x,dy=b.y-a.y,d=Math.hypot(dx,dy)||1,f=(d-90)*0.02,ux=dx/d,uy=dy/d;
    a.vx+=ux*f; a.vy+=uy*f; b.vx-=ux*f; b.vy-=uy*f; }}
  for(const p of P){{ p.x+=p.vx*=0.85; p.y+=p.vy*=0.85; p.x=Math.max(20,Math.min(W-20,p.x)); p.y=Math.max(20,Math.min(H-20,p.y)); }}
}}
function draw(){{
  ctx.clearRect(0,0,W,H);
  for(const e of E){{ let a=P[e.s],b=P[e.t]; ctx.strokeStyle=e.inf?'#334155':'#475569';
    ctx.setLineDash(e.inf?[4,4]:[]); ctx.beginPath(); ctx.moveTo(a.x,a.y); ctx.lineTo(b.x,b.y); ctx.stroke(); }}
  ctx.setLineDash([]);
  DATA.nodes.forEach((n,i)=>{{ let p=P[i], r=n.type==='Community'?9:(n.authoritative?8:6);
    ctx.fillStyle=COLORS[n.type]||'#888'; ctx.beginPath(); ctx.arc(p.x,p.y,r,0,7); ctx.fill();
    if(n.authoritative){{ ctx.strokeStyle='#fde68a'; ctx.lineWidth=2; ctx.beginPath(); ctx.arc(p.x,p.y,r+3,0,7); ctx.stroke(); ctx.lineWidth=1; }}
  }});
}}
let frames=0; (function loop(){{ if(frames++<180){{ step(); }} draw(); requestAnimationFrame(loop); }})();
canvas.addEventListener('mousemove', ev=>{{
  const mx=ev.offsetX,my=ev.offsetY; let hit=null;
  DATA.nodes.forEach((n,i)=>{{ if(Math.hypot(P[i].x-mx,P[i].y-my)<9) hit=n; }});
  if(hit){{ tip.style.display='block'; tip.style.left=(mx+12)+'px'; tip.style.top=(my+12)+'px';
    tip.textContent=hit.type+(hit.authoritative?' (accepted)':'')+': '+hit.label; }}
  else tip.style.display='none';
}});
</script></body></html>
"""
