"""Generate a local, read-only HTML visual review report from vision.py JSON.

No network fetches, no JS, no CDN. Optional embedded local images must be
explicitly supplied via --photo-dir; original photo bytes stay on the machine.
All text is escaped; never trust sellers' titles or model output as markup.
"""
from __future__ import annotations

import argparse
import base64
import html
import json
from pathlib import Path

from photo_inputs import prepare_photo_inputs, PhotoInputError, _public_url

CSS = """
:root{font-family:system-ui,Arial,sans-serif;color:#e4eafa;background:#101723}
*{box-sizing:border-box}
body{max-width:1340px;margin:auto;padding:28px 18px 80px}
h1{font-size:28px;margin:0 0 8px}
h2{font-size:18px;margin:24px 0 14px}
p,li{line-height:1.55}
.small{font-size:12px;color:#a4b1ca}
.card{border:1px solid #30405b;background:#172236;border-radius:14px;padding:18px;margin-bottom:18px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px}
.metric{display:inline-block;min-width:160px;margin:12px 28px 4px 0}
.metric strong{display:block;font-size:24px}
.warn{color:#ffd18e}
.bad{color:#ff9f9f}
.ok{color:#86dfbe}
.tag{display:inline-block;padding:4px 8px;border-radius:5px;background:#273957;margin:4px}
.imgwrap{position:relative;display:inline-block;max-width:100%;line-height:0}
.imgwrap img{display:block;max-width:100%;max-height:640px;height:auto;width:auto;border-radius:6px}
.bound{position:absolute;border:2px solid #72e1b5;background:rgba(114,225,181,.12);pointer-events:none}
.bound span{position:absolute;left:0;bottom:100%;background:#0c6b56;color:white;font-size:12px;
line-height:1.25;padding:3px 5px;white-space:nowrap;max-width:160px;overflow:hidden}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{padding:10px 8px;border-bottom:1px solid #33415c;text-align:left;vertical-align:top}
th{color:#afbed6}
a{color:#93c3fc;overflow-wrap:anywhere}
.placeholder{width:320px;height:220px;display:grid;place-items:center;color:#b5c1d8;background:#202d42}
"""

def esc(x) -> str:
    return html.escape(str(x if x is not None else ""), quote=True)


def _image_source(manifest: dict, photo_dir: str | None) -> str | None:
    if manifest.get("source_type") == "url":
        try:
            return _public_url(manifest["reference"])
        except (PhotoInputError, KeyError):
            return None
    if manifest.get("source_type") == "local" and photo_dir:
        # No path traversal: only basename is read from the dedicated photo folder.
        name = Path(str(manifest.get("reference") or "")).name
        if not name:
            return None
        path = Path(photo_dir) / name
        try:
            prepared = prepare_photo_inputs({"image_files": [str(path)]}, encode_local=True)
            return prepared["image_messages"][0]["image_url"]["url"]
        except (PhotoInputError, KeyError, IndexError):
            return None
    return None


def render_report(result: dict, *, photo_dir: str | None = None) -> str:
    if not isinstance(result, dict):
        raise ValueError("Result must be a JSON object")
    visual, assessment = result.get("visual_evidence") or {}, result.get("assessment") or {}
    observations = visual.get("observations") or []
    inventory = result.get("inventory_review") or {}
    manifest = result.get("image_manifest") or []
    if not isinstance(observations, list) or not isinstance(manifest, list):
        raise ValueError("Malformed vision output")
    resolutions = result.get("catalog_resolutions") or []
    if not isinstance(resolutions, list):
        raise ValueError("Malformed catalog resolutions")
    decisions = {
        "BUY_CANDIDATE": "Candidat — confirmare manuală obligatorie",
        "REVIEW": "Necesită verificare",
        "REJECT": "Respins pe baza dovezilor",
    }
    state = decisions.get(assessment.get("decision"), "Analiză incompletă")
    status_cls = "bad" if assessment.get("decision") == "REJECT" else "warn"
    amount = lambda value: "necunoscut" if value is None else f"{float(value):,.2f} €"
    profit, roi = assessment.get("net_profit_eur"), assessment.get("roi")
    html_out = [f"<!doctype html><html lang='ro'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>BIGSTEN Pokémon — review</title><style>{CSS}</style></head><body>"]
    html_out.append("<h1>BIGSTEN Pokémon — Photo Intelligence</h1>")
    html_out.append(f"<p class='small'>Listing: {esc(result.get('listing_id'))} · Raport de revizuire local; nu validează autenticitatea sau profitul.</p>")
    html_out.append("<section class='card'>")
    html_out.append(f"<span class='{status_cls}'>{esc(state)}</span><div>")
    html_out.append(f"<div class='metric'><span class='small'>Preț de cumpărare afișat</span><strong>{esc(amount(assessment.get('asking_eur')))}</strong></div>")
    html_out.append(f"<div class='metric'><span class='small'>Profit net documentat</span><strong>{esc(amount(profit))}</strong></div>")
    html_out.append(f"<div class='metric'><span class='small'>ROI net</span><strong>{esc(f'{100 * float(roi):.1f}%' if roi is not None else 'necunoscut')}</strong></div>")
    html_out.append("</div>")
    if result.get("listing_url"):
        link = result["listing_url"]
        if isinstance(link, str) and link.startswith("https://") and not any(ch in link for ch in ("\\n", "\\r")):
            html_out.append(f"<p><a href='{esc(link)}' rel='noopener noreferrer' target='_blank'>Deschide anunțul original</a></p>")
    html_out.append("<p class='warn'>Fotografiile singure nu pot confirma gradarea, autenticitatea, volumul real al lotului sau vânzările comparabile.</p>")
    html_out.append("</section>")
    html_out.append("<h2>Fotografii și observații AI</h2><div class='grid'>")
    for entry in manifest:
        idx = entry.get("index")
        if not isinstance(idx, int):
            continue
        photo_src = _image_source(entry, photo_dir)
        html_out.append("<article class='card'>")
        html_out.append(f"<p class='small'>Imaginea #{idx+1} · {esc(entry.get('reference'))}</p>")
        if photo_src:
            html_out.append(f"<div class='imgwrap'><img src='{esc(photo_src)}' alt='Fotografie anunț #{idx+1}'>")
            for oindex, observation in enumerate(observations):
                if not isinstance(observation, dict) or observation.get("image_index") != idx:
                    continue
                box = observation.get("bbox_xyxy") or []
                if (not isinstance(box, list) or len(box) != 4 or
                    any(not isinstance(v, (int,float)) or isinstance(v,bool) or v < 0 or v > 1 for v in box)
                    or box[2] <= box[0] or box[3] <= box[1]):
                    continue
                left, top, right, bottom = box
                tag = observation.get("name") or "Card necunoscut"
                num = observation.get("number") or "?"
                html_out.append(
                    f"<div class='bound' style='left:{100*left:.3f}%;top:{100*top:.3f}%;width:{100*(right-left):.3f}%;height:{100*(bottom-top):.3f}%'>"
                    f"<span>{oindex+1}: {esc(tag)} · {esc(num)}</span></div>"
                )
            html_out.append("</div>")
        else:
            html_out.append("<div class='placeholder'>Imaginea nu este inclusă în raport. Folosește --photo-dir pentru fișiere locale.</div>")
        html_out.append("</article>")
    html_out.append("</div>")
    html_out.append("<h2>Observații și potriviri</h2><section class='card'><table><thead><tr>")
    html_out.append("<th>#</th><th>Carte / produs</th><th>Set / număr</th><th>Limba / variantă</th><th>Stare vizibilă</th><th>Identitate catalog</th><th>Semnale</th></tr></thead><tbody>")
    for i, o in enumerate(observations):
        if not isinstance(o, dict):
            continue
        match = resolutions[i].get("identity_key") if i < len(resolutions) and isinstance(resolutions[i], dict) else None
        flags = ", ".join(o.get("flags") or []) or "—"
        html_out.append("<tr>" +
            f"<td>{i+1}</td><td>{esc(o.get('name') or '?')}</td><td>{esc(o.get('set') or '?')} / {esc(o.get('number') or '?')}</td>"
            f"<td>{esc(o.get('language'))} / {esc(o.get('finish'))}</td><td>{esc(o.get('condition'))}</td>"
            f"<td>{esc(match or 'NECONFIRMAT')}</td><td>{esc(flags)}</td></tr>")
    html_out.append("</tbody></table></section>")
    if inventory:
        html_out.append("<h2>Inventar fizic — neconfirmat</h2><section class='card'>")
        lo, hi = inventory.get("quantity_lower_bound_if_detections_correct"), inventory.get("quantity_upper_bound_if_detections_correct")
        html_out.append(f"<p>Interval estimativ al obiectelor distincte observate: <strong>{esc(lo)}–{esc(hi)}</strong>. Aceste limite presupun că detecțiile din imagini sunt corecte.</p>")
        html_out.append(f"<p class='warn'>Grupuri de verificat: {esc(inventory.get('groups_requiring_review'))}. Nu transforma aceste cifre în valoare de revânzare fără verificare fizică.</p>")
        for g in inventory.get("groups") or []:
            if g.get("review_required"):
                html_out.append(f"<p class='small'>{esc(g.get('identity_group'))}: {esc(g.get('possible_distinct_copies_min'))}–{esc(g.get('possible_distinct_copies_max'))} posibile exemplare; fotografii {esc(g.get('image_indices'))}</p>")
        html_out.append("</section>")
    html_out.append("<h2>Întrebări și dovezi lipsă</h2><section class='card'><ul>")
    for line in (result.get("open_questions") or []) + (assessment.get("warnings") or []) + (assessment.get("reasons") or []):
        html_out.append(f"<li>{esc(line)}</li>")
    html_out.append("</ul></section>")
    html_out.append("<p class='small'>Generated by BIGSTEN Visual Intelligence V2. Read-only. No automated buying. All model observations require independent validation.</p></body></html>")
    return "".join(html_out)


def main(argv=None):
    p = argparse.ArgumentParser(description="Render a private review HTML from vision.py JSON")
    p.add_argument("result_json", help="Output from vision.py or analyze_listing")
    p.add_argument("--photo-dir", help="Folder containing local photos, embedded in HTML when supplied")
    p.add_argument("--out", default="review.html")
    args = p.parse_args(argv)
    data = json.loads(Path(args.result_json).read_text(encoding="utf-8"))
    rendered = render_report(data, photo_dir=args.photo_dir)
    Path(args.out).write_text(rendered, encoding="utf-8")
    print(f"Saved local review report: {args.out}")


if __name__ == "__main__":
    main()
