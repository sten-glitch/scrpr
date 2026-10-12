"""Generate a completely synthetic, copyright-free BIGSTEN reference demo.

Creates reference photos, a local catalog, a private pHash+ORB SQLite
index and a separate slightly altered query image without downloading
Pokemon artwork or using a commercial AI API.

RUN from pokemon-detector:
  .venv\\Scripts\\python.exe demo_reference_lab.py

Then open:
  .venv\\Scripts\\python.exe local_app.py --catalog private/demo_catalog.json --reference-index private/demo_cards.sqlite

Upload private/demo_queries/demo_query_A.png in browser and examine
VISUAL_CANDIDATE/ABSTAIN output. This is ONLY a code demonstration.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from reference_matcher import build_reference_index, ReferenceMatcher
from local_cv import _modules

DEMO_CATALOG=[
    {"identity_key":"bigsten:synthetic:A","name":"Synthetic Geometric Card A",
     "set":"DEMO-ONLY","number":"1/2","finish":"normal","language":"en"},
    {"identity_key":"bigsten:synthetic:B","name":"Synthetic Geometric Card B",
     "set":"DEMO-ONLY","number":"2/2","finish":"normal","language":"en"},
]


def _demo_card(seed: int):
    cv2,np,_ = _modules()
    rng=np.random.default_rng(seed)
    w,h=360,500
    img=np.full((h,w,3),250,dtype=np.uint8)
    # A clearly artificial, non-Pokémon abstract geometric pattern with ORB
    # features. Not a scan, derivative or recreation of franchise artwork.
    cv2.rectangle(img,(14,14),(w-14,h-14),(8,25,42),7)
    cv2.rectangle(img,(28,70),(w-28,390),(90,120,155),2)
    cv2.putText(img,f"DEMO {seed}",(32,56),cv2.FONT_HERSHEY_SIMPLEX,
                .94,(18,42,60),2,cv2.LINE_AA)
    cv2.putText(img,f"{seed}/2",(270,467),cv2.FONT_HERSHEY_SIMPLEX,
                .68,(18,42,60),2,cv2.LINE_AA)
    for k in range(60):
        x=int(rng.integers(38,w-38))
        y=int(rng.integers(84,365))
        r=int(rng.integers(2,14))
        color=tuple(int(x) for x in rng.integers(30,210,size=3))
        cv2.circle(img,(x,y),r,color,2,cv2.LINE_AA)
    for k in range(14):
        x1=int(rng.integers(35,w-35))
        y1=int(rng.integers(85,372))
        x2=int(rng.integers(35,w-35))
        y2=int(rng.integers(85,372))
        cv2.line(img,(x1,y1),(x2,y2),(25,25,25),1,cv2.LINE_AA)
    return img


def create_demo(root: str | Path="private", *, test_match=True) -> dict:
    root=Path(root)
    ref_dir=root/"demo_references"
    query_dir=root/"demo_queries"
    target=root/"demo_cards.sqlite"
    catalog_file=root/"demo_catalog.json"
    manifest_file=root/"demo_reference_manifest.json"
    # Refuse replacement of private user-created files; keep demonstration
    # opt-in and non-destructive.
    files=[target,catalog_file,manifest_file,
           ref_dir/"demo_reference_A.png",ref_dir/"demo_reference_B.png",
           query_dir/"demo_query_A.png"]
    if any(p.exists() for p in files):
        raise ValueError("Demo already exists; refusing to overwrite private files")
    ref_dir.mkdir(parents=True,exist_ok=True)
    query_dir.mkdir(parents=True,exist_ok=True)
    cv2,np,_=_modules()
    manifest={"references":[]}
    for seed, label in ((1,"A"),(2,"B")):
        picture=_demo_card(seed)
        reference_name=f"demo_reference_{label}.png"
        if not cv2.imwrite(str(ref_dir/reference_name),picture):
            raise ValueError("Unable to create synthetic reference")
        manifest["references"].append({
            "reference_id":f"synthetic_{label}_generated",
            "identity_key":f"bigsten:synthetic:{label}",
            "image_file":reference_name,
            "rights_basis":"user_owned",
            "permission_reference":"COMPUTER_GENERATED_GEOMETRIC_DEMO",
        })
        if seed==1:
            # Separate file and modest brightness change; close enough for
            # demonstrator, but NOT independent real-world model validation.
            query=cv2.convertScaleAbs(picture,alpha=.92,beta=5)
            if not cv2.imwrite(str(query_dir/"demo_query_A.png"),query):
                raise ValueError("Unable to create synthetic query")
    catalog_file.write_text(json.dumps(DEMO_CATALOG,indent=2)+"\n",encoding="utf-8")
    manifest_file.write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf-8")
    stats=build_reference_index(manifest,ref_dir,target,DEMO_CATALOG)
    result={
        "status":"SYNTHETIC_DEMONSTRATION_ONLY",
        "reference_count":stats["reference_count"],
        "catalog":str(catalog_file),
        "index":str(target),
        "reference_manifest":str(manifest_file),
        "query_image":str(query_dir/"demo_query_A.png"),
        "note":"No real Pokémon art, no performance claim, no cloud/paid API calls",
    }
    if test_match:
        m=ReferenceMatcher(target)
        image=(query_dir/"demo_query_A.png").read_bytes()
        output=m.match_entire_photo(image)
        result["self_test"]={
            "status":output["status"],
            "matched_identity_key":output["matched_identity_key"],
            "candidates":output["candidates"][:2],
        }
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description="Offline geometric card image matching demo (not Pokémon imagery)")
    p.add_argument("--root",default="private",help="Private local output folder")
    args=p.parse_args(argv)
    result=create_demo(args.root)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    print("Now run local_app.py --catalog "+result["catalog"]+" --reference-index "+result["index"])
    print("Upload "+result["query_image"]+" from the browser.")


if __name__=="__main__":
    main()
