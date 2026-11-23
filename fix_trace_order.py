from pathlib import Path
p = Path("scripts/trace_show.py")
s = p.read_text(encoding="utf-8")
old1 = '    in_prompt = set((r.get("rerank") or {}).get("order") or [])\n'
new1 = '    order = list((r.get("rerank") or {}).get("order") or [])\n    in_prompt = set(order)\n'
old2 = "f\"; order sent to the model: {', '.join(in_prompt) if in_prompt else '(none)'}\")"
new2 = "f\"; order sent to the model: {', '.join(order) if order else '(none)'}\")"
assert old1 in s and old2 in s, "already fixed or file differs"
p.write_text(s.replace(old1, new1).replace(old2, new2), encoding="utf-8")
print("fixed")