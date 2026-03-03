"""Thin Apify wrapper — run actors and retrieve results."""
import os
import requests

APIFY_TOKEN = os.getenv("APIFY_TOKEN")
BASE = "https://api.apify.com/v2"


def run_actor_sync(actor_id: str, run_input: dict, max_items: int = 10, timeout: int = 60) -> list:
    """POST synchronous run and return dataset items directly."""
    url = f"{BASE}/acts/{actor_id}/run-sync-get-dataset-items"
    params = {"token": APIFY_TOKEN, "timeout": timeout, "limit": max_items}
    resp = requests.post(url, json=run_input, params=params, timeout=timeout + 10)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, list):
        return data
    return data.get("items", data.get("data", []))


def run_actor_async(actor_id: str, run_input: dict) -> str:
    """POST async run and return run_id."""
    url = f"{BASE}/acts/{actor_id}/runs"
    resp = requests.post(url, json=run_input, params={"token": APIFY_TOKEN}, timeout=30)
    resp.raise_for_status()
    return resp.json()["data"]["id"]


def get_run_status(run_id: str) -> dict:
    """GET actor run status."""
    url = f"{BASE}/actor-runs/{run_id}"
    resp = requests.get(url, params={"token": APIFY_TOKEN}, timeout=15)
    resp.raise_for_status()
    return resp.json().get("data", {})


def get_run_results(dataset_id: str, max_items: int = 50) -> list:
    """GET dataset items from a completed run."""
    url = f"{BASE}/datasets/{dataset_id}/items"
    resp = requests.get(url, params={"token": APIFY_TOKEN, "limit": max_items}, timeout=30)
    resp.raise_for_status()
    return resp.json()
