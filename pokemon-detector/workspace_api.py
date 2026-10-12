"""BIGSTEN localhost workbench REST-ish endpoints.

This adapter intentionally has NO SaaS credentials/authentication. It must
only be used behind local_app.py's localhost + Host + Origin checks.
"""
from __future__ import annotations

import json
from listing_truth import evaluate_listing_truth
from radar_ingest import fetch_own_detector_feed, import_feed
from workspace import WorkspaceError, WorkspaceStore


def workspace_get(store: WorkspaceStore, path: str, params: dict):
    if path == "/api/workspace/dashboard":
        return 200, store.dashboard()
    if path == "/api/workspace/listings":
        status=params.get("status", [None])[0]
        limit=params.get("limit", ["100"])[0]
        if not str(limit).isdigit():
            raise WorkspaceError("limit must be a positive number")
        return 200, {"items":store.list_listings(status=status,limit=int(limit))}
    if path == "/api/workspace/listing":
        identifier=params.get("id", [""])[0]
        return 200, store.get_listing(identifier)
    if path == "/api/workspace/radar":
        return 200, {
            "signals":store.radar(limit=200),
            "evidence_notice":"GUIDE/ASKING DATA ONLY; no verified completed sales or true net ROI",
            "commercial_use_rights_not_verified":True,
        }
    if path == "/api/workspace/export":
        return 200, store.export()
    return 404, {"error":"Unknown workbench API endpoint"}


def workspace_post(store: WorkspaceStore, path: str, payload: dict,
                   *, analyze_listing=None, catalog=None, matcher=None):
    if not isinstance(payload,dict):
        raise WorkspaceError("Expected JSON object")
    if path == "/api/workspace/listings":
        analysis={
            "status":"TEXT_ONLY_NO_VISUAL_PROOF",
            "listing_truth":evaluate_listing_truth(payload),
            "assessment":None,
            "open_questions":["User must supply independently reviewed product photos and completed sale records"],
        }
        return 201, store.create_listing(payload,analysis=analysis)
    if path == "/api/workspace/analyze":
        if analyze_listing is None:
            raise WorkspaceError("Local photo analysis pipeline not available")
        report=analyze_listing(payload,catalog or [],matcher)
        created=store.create_listing(payload,analysis=report)
        return 201, created
    listing_id=payload.get("id")
    if path == "/api/workspace/status":
        return 200, store.set_status(listing_id,payload.get("status"))
    if path == "/api/workspace/scenario":
        return 200, store.save_scenario(listing_id,payload.get("assumptions"))
    if path == "/api/workspace/purchase":
        return 200, store.purchase(listing_id,payload)
    if path == "/api/workspace/sale":
        return 200, store.sale(listing_id,payload)
    if path == "/api/workspace/radar/import-local":
        if set(payload) != {"snapshot"} or not isinstance(payload["snapshot"],dict):
            raise WorkspaceError("Expected a detector snapshot JSON object, not a URL or arbitrary file path")
        # User-selected offline snapshot; no network call or path access.
        raw=json.dumps(payload["snapshot"],separators=(",",":"),ensure_ascii=False).encode()
        return 200, import_feed(store,raw,limit=250)
    if path == "/api/workspace/radar/refresh":
        if payload:
            # Fixed permitted endpoint. No arbitrary URLs or source data
            # injected into the network fetch.
            raise WorkspaceError("Refresh needs an empty JSON object")
        raw=fetch_own_detector_feed()
        return 200, import_feed(store,raw,limit=250)
    return 404, {"error":"Unknown workbench API endpoint"}
