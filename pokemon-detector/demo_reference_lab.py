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


def create_demo(root: str | Path="private", *, test_match=True,
                resume: bool=False) -> dict:
    """Build demo without clobbering files; --resume repairs interrupted setup.

    All existing demo assets must exactly match generated geometric originals.
    Arbitrary user files are never overwritten or treated as demo evidence.
    """
    root=Path(root)
    ref_dir=root/"demo_references"
    query_dir=root/"demo_queries"
    target=root/"demo_cards.sqlite"
    catalog_file=root/"demo_catalog.json"
    manifest_file=root/"demo_reference_manifest.json"
    files=[target,catalog_file,manifest_file,
           ref_dir/"demo_reference_A.png",ref_dir/"demo_reference_B.png",
           query_dir/"demo_query_A.png"]
    if target.exists():
        raise ValueError("Demo index already exists; refusing to overwrite private files")
    if not resume and any(p.exists() for p in files):
        raise ValueError("Demo already exists; refusing to overwrite private files")
    cv2,np,_=_modules()
    images={"A":_demo_card(1),"B":_demo_card(2)}
    query=cv2.convertScaleAbs(images["A"],alpha=.92,beta=5)
    expected_manifest={"references":[{
        "reference_id":f"synthetic_{label}_generated",
        "identity_key":f"bigsten:synthetic:{label}",
        "image_file":f"demo_reference_{label}.png",
        "rights_basis":"user_owned",
        "permission_reference":"COMPUTER_GENERATED_GEOMETRIC_DEMO",
    } for label in ("A","B")]}

    def keep_or_create_image(path, expected):
        if path.exists():
            if not path.is_file():
                raise ValueError("Demo asset path is not a file: "+str(path))
            existing=cv2.imread(str(path),cv2.IMREAD_COLOR)
            if existing is None or not np.array_equal(existing,expected):
                raise ValueError("Existing demo image differs; refusing to overwrite: "+str(path))
            return
        path.parent.mkdir(parents=True,exist_ok=True)
        if not cv2.imwrite(str(path),expected):
            raise ValueError("Unable to create synthetic image: "+str(path))

    def keep_or_create_json(path, expected):
        if path.exists():
            if not path.is_file():
                raise ValueError("Demo asset path is not a file: "+str(path))
            try:
                existing=json.loads(path.read_text(encoding="utf-8"))
            except (OSError,UnicodeError,json.JSONDecodeError) as exc:
                raise ValueError("Existing demo JSON invalid; refusing to overwrite") from exc
            if existing != expected:
                raise ValueError("Existing demo JSON differs; refusing to overwrite: "+str(path))
            return
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(expected,indent=2)+"\n",encoding="utf-8")

    # If a previous run failed on Windows after writing the photos and
    # manifest, --resume safely rebuilds only the missing index.
    for label,image in images.items():
        keep_or_create_image(ref_dir/f"demo_reference_{label}.png",image)
    keep_or_create_image(query_dir/"demo_query_A.png",query)
    keep_or_create_json(catalog_file,DEMO_CATALOG)
    keep_or_create_json(manifest_file,expected_manifest)

    stats=build_reference_index(expected_manifest,ref_dir,target,DEMO_CATALOG)
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
    p.add_argument("--resume",action="store_true",
                   help="Resume interrupted demo by validating existing generated assets, without overwriting")
    args=p.parse_args(argv)
    result=create_demo(args.root,resume=args.resume)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    print("Now run local_app.py --catalog "+result["catalog"]+" --reference-index "+result["index"])
    print("Upload "+result["query_image"]+" from the browser.")


if __name__=="__main__":
    main()
