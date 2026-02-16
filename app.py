"""Koddi Health Check — Streamlit UI."""

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

import httpx
import streamlit as st

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

class Status(Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    SKIPPED = "skipped"


STATUS_DISPLAY = {
    Status.PASS: ("✅", "PASS", "green"),
    Status.WARN: ("⚠️", "WARN", "orange"),
    Status.FAIL: ("❌", "FAIL", "red"),
    Status.SKIPPED: ("⏭️", "SKIPPED", "gray"),
}


@dataclass
class CheckResult:
    number: int
    name: str
    status: Status
    details: str
    extra: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def make_request(
    client: httpx.Client,
    method: str,
    url: str,
    token: Optional[str] = None,
    json_body: Optional[dict] = None,
) -> httpx.Response:
    headers = {}
    if token:
        headers["Authorization"] = token
    if method == "GET":
        return client.get(url, headers=headers)
    return client.post(url, headers=headers, json=json_body)


# ---------------------------------------------------------------------------
# Health checks
# ---------------------------------------------------------------------------

def check_auth(
    client: httpx.Client, base_url: str, email: str, password: str, member_group_id: int
) -> tuple[CheckResult, Optional[str]]:
    name = "Authentication"
    try:
        resp = make_request(
            client, "POST", f"{base_url}/session/login",
            json_body={"email": email, "password": password, "member_group_id": member_group_id},
        )
        data = resp.json()
        if data.get("status") == "success":
            token = data.get("result", {}).get("token", {}).get("id_token")
            if token:
                return CheckResult(1, name, Status.PASS, "Authenticated successfully"), token
            return CheckResult(1, name, Status.FAIL, "No id_token in response"), None
        error_code = data.get("error_code", "unknown")
        error_msg = data.get("message", data.get("error", "unknown error"))
        return CheckResult(1, name, Status.FAIL, f"Login failed — code {error_code}: {error_msg}"), None
    except httpx.TimeoutException:
        return CheckResult(1, name, Status.FAIL, "Request timed out"), None
    except httpx.ConnectError:
        return CheckResult(1, name, Status.FAIL, "Connection error — cannot reach API"), None
    except Exception as exc:
        return CheckResult(1, name, Status.FAIL, f"Unexpected error: {exc}"), None


def check_advertiser(
    client: httpx.Client, base_url: str, token: str, member_group_id: int, advertiser_id: int,
) -> CheckResult:
    name = "Advertiser Exists"
    try:
        url = f"{base_url}/member_groups/{member_group_id}/advertisers/{advertiser_id}"
        resp = make_request(client, "GET", url, token=token)
        data = resp.json()
        if data.get("status") == "success":
            r = data.get("result", {})
            details = (
                f"Found: {r.get('name', 'N/A')} | status={r.get('status', 'N/A')} | "
                f"entities={r.get('entity_count', 'N/A')} | currency={r.get('currency_code', 'N/A')}"
            )
            return CheckResult(2, name, Status.PASS, details)
        error_code = data.get("error_code", "unknown")
        error_msg = data.get("message", data.get("error", "unknown error"))
        return CheckResult(2, name, Status.FAIL, f"Error {error_code}: {error_msg}")
    except httpx.TimeoutException:
        return CheckResult(2, name, Status.FAIL, "Request timed out")
    except httpx.ConnectError:
        return CheckResult(2, name, Status.FAIL, "Connection error")
    except Exception as exc:
        return CheckResult(2, name, Status.FAIL, f"Unexpected error: {exc}")


def check_campaigns(
    client: httpx.Client, base_url: str, token: str, member_group_id: int, advertiser_id: int,
) -> CheckResult:
    name = "Campaigns Report"
    try:
        url = f"{base_url}/member_groups/{member_group_id}/advertisers/{advertiser_id}/campaigns_report"
        resp = make_request(client, "POST", url, token=token, json_body={"pagination": {"start": 0}})
        data = resp.json()
        if data.get("status") != "success":
            error_code = data.get("error_code", "unknown")
            error_msg = data.get("message", data.get("error", "unknown error"))
            return CheckResult(3, name, Status.FAIL, f"Error {error_code}: {error_msg}")
        result = data.get("result", {})
        campaigns = result.get("campaigns", [])
        total = result.get("total", len(campaigns))
        if total == 0:
            return CheckResult(3, name, Status.WARN, "Zero campaigns found for this advertiser")
        lines = [f"Found {total} campaign(s)"]
        for c in campaigns:
            lines.append(
                f"  \u2022 {c.get('name', 'N/A')} | status={c.get('status', 'N/A')} | "
                f"always_on={c.get('always_on', 'N/A')} | budget={c.get('budget_type', 'N/A')}/{c.get('budget_amount', 'N/A')}"
            )
        return CheckResult(3, name, Status.PASS, "\n".join(lines))
    except httpx.TimeoutException:
        return CheckResult(3, name, Status.FAIL, "Request timed out")
    except httpx.ConnectError:
        return CheckResult(3, name, Status.FAIL, "Connection error")
    except Exception as exc:
        return CheckResult(3, name, Status.FAIL, f"Unexpected error: {exc}")


def check_entity_failures(
    client: httpx.Client, base_url: str, token: str, member_group_id: int, advertiser_id: int,
) -> CheckResult:
    name = "Entity Registration Failures"
    try:
        url = f"{base_url}/member_groups/{member_group_id}/advertisers/{advertiser_id}/entity_registrations/failed/report"
        resp = make_request(client, "POST", url, token=token, json_body={"pagination": {"count": 50, "start": 0}})
        data = resp.json()
        if data.get("status") != "success":
            error_code = data.get("error_code", "unknown")
            error_msg = data.get("message", data.get("error", "unknown error"))
            return CheckResult(4, name, Status.FAIL, f"Error {error_code}: {error_msg}")
        result = data.get("result", {})
        total = result.get("total", 0)
        if total == 0:
            return CheckResult(4, name, Status.PASS, "No entity registration failures")
        failures = result.get("entity_registrations", [])[:5]
        lines = [f"{total} registration failure(s) found. First {len(failures)}:"]
        for f in failures:
            lines.append(f"  \u2022 [{f.get('error_code', 'N/A')}] {f.get('error_message', 'N/A')}")
        return CheckResult(4, name, Status.WARN, "\n".join(lines))
    except httpx.TimeoutException:
        return CheckResult(4, name, Status.FAIL, "Request timed out")
    except httpx.ConnectError:
        return CheckResult(4, name, Status.FAIL, "Connection error")
    except Exception as exc:
        return CheckResult(4, name, Status.FAIL, f"Unexpected error: {exc}")


def check_active_bidders(
    client: httpx.Client, base_url: str, token: str, member_group_id: int,
) -> CheckResult:
    name = "Active Bidders Cache"
    try:
        url = f"{base_url}/member_groups/{member_group_id}/active_bidders"
        resp = make_request(client, "GET", url, token=token)
        data = resp.json()
        if data.get("status") != "success":
            error_code = data.get("error_code", "unknown")
            error_msg = data.get("message", data.get("error", "unknown error"))
            return CheckResult(5, name, Status.FAIL, f"Error {error_code}: {error_msg}")
        bidders = data.get("result", {}).get("active_bidders", [])
        if not bidders:
            return CheckResult(5, name, Status.WARN, "Active bidders list is empty — no ad groups are active")
        return CheckResult(5, name, Status.PASS, f"{len(bidders)} active bidder(s) in cache")
    except httpx.TimeoutException:
        return CheckResult(5, name, Status.FAIL, "Request timed out")
    except httpx.ConnectError:
        return CheckResult(5, name, Status.FAIL, "Connection error")
    except Exception as exc:
        return CheckResult(5, name, Status.FAIL, f"Unexpected error: {exc}")


def check_attributable_entities(
    client: httpx.Client, base_url: str, token: str, member_group_id: int,
) -> CheckResult:
    name = "Attributable Entities Cache"
    try:
        url = f"{base_url}/member_groups/{member_group_id}/attributable_entities"
        resp = make_request(client, "GET", url, token=token)
        data = resp.json()
        if data.get("status") != "success":
            error_code = data.get("error_code", "unknown")
            error_msg = data.get("message", data.get("error", "unknown error"))
            return CheckResult(6, name, Status.FAIL, f"Error {error_code}: {error_msg}")
        entities = data.get("result", {}).get("attributable_entities", [])
        if not entities:
            return CheckResult(6, name, Status.WARN, "No attributable entities — conversions won't attribute")
        return CheckResult(6, name, Status.PASS, f"{len(entities)} attributable entit(ies) in cache")
    except httpx.TimeoutException:
        return CheckResult(6, name, Status.FAIL, "Request timed out")
    except httpx.ConnectError:
        return CheckResult(6, name, Status.FAIL, "Connection error")
    except Exception as exc:
        return CheckResult(6, name, Status.FAIL, f"Unexpected error: {exc}")


def check_winning_ads(
    client: httpx.Client, client_name: str, site_id: str, experience_name: Optional[str],
) -> CheckResult:
    name = "Winning Ads (Test Auction)"
    try:
        url = f"https://{client_name}.koddi.io/auction-engine/winning_ads"
        body: dict[str, Any] = {
            "client_name": client_name,
            "site_id": site_id,
            "slots_available": 1,
            "max_requested": 1,
            "user": {"guid": "healthcheck-test-user"},
            "bidders": [],
        }
        if experience_name:
            body["experience_name"] = experience_name
        resp = make_request(client, "POST", url, json_body=body)
        if resp.status_code != 200:
            return CheckResult(
                7, name, Status.FAIL,
                f"HTTP {resp.status_code} — auction engine may be misconfigured or client '{client_name}' is not provisioned",
            )
        data = resp.json()
        listings = data.get("sponsored_listings", [])
        count = len(listings)
        detail = (
            f"Auction responded OK — {count} sponsored listing(s) returned"
            if count
            else "Auction responded OK — 0 listings (expected with empty bidders)"
        )
        return CheckResult(7, name, Status.PASS, detail)
    except httpx.TimeoutException:
        return CheckResult(7, name, Status.FAIL, "Request timed out")
    except httpx.ConnectError:
        return CheckResult(7, name, Status.FAIL, f"Connection error — cannot reach {client_name}.koddi.io")
    except Exception as exc:
        return CheckResult(7, name, Status.FAIL, f"Unexpected error: {exc}")


# ---------------------------------------------------------------------------
# Run all checks
# ---------------------------------------------------------------------------

def run_checks(
    email: str,
    password: str,
    member_group_id: int,
    advertiser_id: int,
    client_name: str,
    site_id: str,
    experience_name: Optional[str],
    base_url: str,
    timeout: int,
    progress_callback=None,
) -> list[CheckResult]:
    base_url = base_url.rstrip("/")
    results: list[CheckResult] = []
    token: Optional[str] = None

    def report(step: int, total: int, name: str):
        if progress_callback:
            progress_callback(step, total, name)

    with httpx.Client(timeout=timeout) as client:
        # Check 1
        report(1, 7, "Authentication")
        auth_result, token = check_auth(client, base_url, email, password, member_group_id)
        results.append(auth_result)

        auth_dependent = [
            (2, "Advertiser Exists"),
            (3, "Campaigns Report"),
            (4, "Entity Registration Failures"),
            (5, "Active Bidders Cache"),
            (6, "Attributable Entities Cache"),
        ]

        if token is None:
            for num, name in auth_dependent:
                report(num, 7, name)
                results.append(CheckResult(num, name, Status.SKIPPED, "Skipped — authentication failed"))
        else:
            # Check 2
            report(2, 7, "Advertiser Exists")
            r2 = check_advertiser(client, base_url, token, member_group_id, advertiser_id)
            results.append(r2)

            if r2.status == Status.FAIL:
                for num, name in auth_dependent[1:3]:
                    report(num, 7, name)
                    results.append(CheckResult(num, name, Status.SKIPPED, "Skipped — advertiser check failed"))
            else:
                # Check 3
                report(3, 7, "Campaigns Report")
                results.append(check_campaigns(client, base_url, token, member_group_id, advertiser_id))

                # Check 4
                report(4, 7, "Entity Registration Failures")
                results.append(check_entity_failures(client, base_url, token, member_group_id, advertiser_id))

            # Check 5
            report(5, 7, "Active Bidders Cache")
            results.append(check_active_bidders(client, base_url, token, member_group_id))

            # Check 6
            report(6, 7, "Attributable Entities Cache")
            results.append(check_attributable_entities(client, base_url, token, member_group_id))

        # Check 7 (no auth)
        report(7, 7, "Winning Ads (Test Auction)")
        results.append(check_winning_ads(client, client_name, site_id, experience_name))

    return results


# ---------------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Koddi Health Check", page_icon="🩺", layout="wide")

st.title("🩺 Koddi Health Check")
st.caption("Validate your Koddi Ads implementation end-to-end")

# --- Sidebar: Configuration ---
with st.sidebar:
    st.header("Configuration")

    email = st.text_input("Email", placeholder="bob@company.com")
    password = st.text_input("Password", type="password")
    member_group_id = st.number_input("Member Group ID", min_value=1, step=1, value=None, placeholder="1234")
    advertiser_id = st.number_input("Advertiser ID", min_value=1, step=1, value=None, placeholder="5678")
    client_name = st.text_input("Client Name", placeholder="myretailer")

    st.divider()
    st.subheader("Optional")

    site_id = st.text_input("Site ID", value="homepage")
    experience_name = st.text_input("Experience Name", placeholder="Sponsored Products")
    base_url = st.text_input("Base URL", value="https://koddi.io/console/v1")
    timeout = st.slider("Timeout (seconds)", min_value=5, max_value=120, value=30)

    st.divider()
    can_run = all([email, password, member_group_id, advertiser_id, client_name])
    run_button = st.button(
        "🚀 Run Health Check",
        type="primary",
        disabled=not can_run,
        use_container_width=True,
    )
    if not can_run:
        st.info("Fill in all required fields above to run.")

# --- Main area ---
if run_button:
    progress_bar = st.progress(0, text="Starting health checks...")

    def on_progress(step: int, total: int, name: str):
        progress_bar.progress(step / total, text=f"Running Check {step}/{total}: {name}...")

    results = run_checks(
        email=email,
        password=password,
        member_group_id=int(member_group_id),
        advertiser_id=int(advertiser_id),
        client_name=client_name,
        site_id=site_id or "homepage",
        experience_name=experience_name or None,
        base_url=base_url,
        timeout=timeout,
        progress_callback=on_progress,
    )

    progress_bar.empty()

    # --- Summary metrics ---
    passes = sum(1 for r in results if r.status == Status.PASS)
    warns = sum(1 for r in results if r.status == Status.WARN)
    fails = sum(1 for r in results if r.status == Status.FAIL)
    skips = sum(1 for r in results if r.status == Status.SKIPPED)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Passed", passes)
    col2.metric("Warnings", warns)
    col3.metric("Failed", fails)
    col4.metric("Skipped", skips)

    if fails == 0:
        st.success("All checks passed!")
    else:
        st.error(f"{fails} check(s) failed.")

    st.divider()

    # --- Detailed results ---
    for r in results:
        icon, label, color = STATUS_DISPLAY[r.status]

        with st.expander(f"{icon}  Check {r.number}: {r.name} — **{label}**", expanded=(r.status in (Status.FAIL, Status.WARN))):
            if "\n" in r.details:
                st.code(r.details, language=None)
            else:
                st.markdown(f":{color}[{r.details}]")

    # --- JSON export ---
    st.divider()
    json_output = json.dumps(
        {
            "checks": [
                {"check": r.number, "name": r.name, "status": r.status.value, "details": r.details}
                for r in results
            ],
            "overall": "fail" if fails > 0 else "pass",
        },
        indent=2,
    )
    st.download_button(
        "📥 Download JSON Report",
        data=json_output,
        file_name="koddi_healthcheck_results.json",
        mime="application/json",
    )

elif "results" not in st.session_state:
    st.markdown(
        """
        ### How to use

        1. Fill in your Koddi credentials and IDs in the sidebar
        2. Click **Run Health Check**
        3. Review the results — expand any check for details
        4. Download the JSON report to share with your team

        ---

        | Check | What it validates |
        |---|---|
        | 1. Authentication | Login and token retrieval |
        | 2. Advertiser Exists | Advertiser is configured correctly |
        | 3. Campaigns Report | Campaigns are set up for the advertiser |
        | 4. Entity Registration Failures | No failed entity registrations |
        | 5. Active Bidders Cache | Ad groups are active and cached |
        | 6. Attributable Entities Cache | Entities are ready for conversion attribution |
        | 7. Winning Ads | Auction engine is reachable and responding |
        """
    )
