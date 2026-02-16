#!/usr/bin/env python3
"""Koddi Ads implementation health check CLI tool."""

import json
import os
import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

import click
import httpx
from rich.console import Console
from rich.table import Table
from rich.text import Text


class Status(Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    SKIPPED = "skipped"


@dataclass
class CheckResult:
    number: int
    name: str
    status: Status
    details: str
    extra: dict = field(default_factory=dict)


console = Console()


def status_icon(status: Status) -> str:
    return {
        Status.PASS: "[green]✅ PASS[/green]",
        Status.WARN: "[yellow]⚠️  WARN[/yellow]",
        Status.FAIL: "[red]❌ FAIL[/red]",
        Status.SKIPPED: "[dim]⏭️  SKIPPED[/dim]",
    }[status]


def status_plain(status: Status) -> str:
    return {
        Status.PASS: "PASS",
        Status.WARN: "WARN",
        Status.FAIL: "FAIL",
        Status.SKIPPED: "SKIPPED",
    }[status]


def print_result(result: CheckResult, use_json: bool) -> None:
    if use_json:
        return
    icon = status_icon(result.status)
    console.print(f"  {icon} — {result.details}")
    console.print()


def print_check_header(number: int, name: str, use_json: bool) -> None:
    if use_json:
        return
    console.print(f"[bold]🔄 Running Check {number}: {name}...[/bold]")


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
# Check 1: Authentication
# ---------------------------------------------------------------------------
def check_auth(
    client: httpx.Client, base_url: str, email: str, password: str, member_group_id: int
) -> tuple[CheckResult, Optional[str]]:
    name = "Authentication"
    try:
        resp = make_request(
            client,
            "POST",
            f"{base_url}/session/login",
            json_body={
                "email": email,
                "password": password,
                "member_group_id": member_group_id,
            },
        )
        data = resp.json()
        if data.get("status") == "success":
            token = data.get("result", {}).get("token", {}).get("id_token")
            if token:
                return (
                    CheckResult(1, name, Status.PASS, "Authenticated successfully"),
                    token,
                )
            return (
                CheckResult(1, name, Status.FAIL, "No id_token in response"),
                None,
            )
        error_code = data.get("error_code", "unknown")
        error_msg = data.get("message", data.get("error", "unknown error"))
        return (
            CheckResult(
                1, name, Status.FAIL, f"Login failed — code {error_code}: {error_msg}"
            ),
            None,
        )
    except httpx.TimeoutException:
        return CheckResult(1, name, Status.FAIL, "Request timed out"), None
    except httpx.ConnectError:
        return CheckResult(1, name, Status.FAIL, "Connection error — cannot reach API"), None
    except Exception as exc:
        return CheckResult(1, name, Status.FAIL, f"Unexpected error: {exc}"), None


# ---------------------------------------------------------------------------
# Check 2: Advertiser Exists
# ---------------------------------------------------------------------------
def check_advertiser(
    client: httpx.Client,
    base_url: str,
    token: str,
    member_group_id: int,
    advertiser_id: int,
) -> CheckResult:
    name = "Advertiser Exists"
    try:
        url = f"{base_url}/member_groups/{member_group_id}/advertisers/{advertiser_id}"
        resp = make_request(client, "GET", url, token=token)
        data = resp.json()
        if data.get("status") == "success":
            result = data.get("result", {})
            adv_name = result.get("name", "N/A")
            adv_status = result.get("status", "N/A")
            entity_count = result.get("entity_count", "N/A")
            currency = result.get("currency_code", "N/A")
            details = (
                f"Found: {adv_name} | status={adv_status} | "
                f"entities={entity_count} | currency={currency}"
            )
            return CheckResult(2, name, Status.PASS, details)
        error_code = data.get("error_code", "unknown")
        error_msg = data.get("message", data.get("error", "unknown error"))
        return CheckResult(
            2, name, Status.FAIL, f"Error {error_code}: {error_msg}"
        )
    except httpx.TimeoutException:
        return CheckResult(2, name, Status.FAIL, "Request timed out")
    except httpx.ConnectError:
        return CheckResult(2, name, Status.FAIL, "Connection error")
    except Exception as exc:
        return CheckResult(2, name, Status.FAIL, f"Unexpected error: {exc}")


# ---------------------------------------------------------------------------
# Check 3: Campaigns Report
# ---------------------------------------------------------------------------
def check_campaigns(
    client: httpx.Client,
    base_url: str,
    token: str,
    member_group_id: int,
    advertiser_id: int,
) -> CheckResult:
    name = "Campaigns Report"
    try:
        url = (
            f"{base_url}/member_groups/{member_group_id}"
            f"/advertisers/{advertiser_id}/campaigns_report"
        )
        resp = make_request(
            client, "POST", url, token=token, json_body={"pagination": {"start": 0}}
        )
        data = resp.json()
        if data.get("status") != "success":
            error_code = data.get("error_code", "unknown")
            error_msg = data.get("message", data.get("error", "unknown error"))
            return CheckResult(
                3, name, Status.FAIL, f"Error {error_code}: {error_msg}"
            )
        result = data.get("result", {})
        campaigns = result.get("campaigns", [])
        total = result.get("total", len(campaigns))

        if total == 0:
            return CheckResult(
                3, name, Status.WARN, "⚠️  Zero campaigns found for this advertiser"
            )

        lines = [f"Found {total} campaign(s)"]
        for c in campaigns:
            c_name = c.get("name", "N/A")
            c_status = c.get("status", "N/A")
            always_on = c.get("always_on", "N/A")
            budget_type = c.get("budget_type", "N/A")
            budget_amount = c.get("budget_amount", "N/A")
            lines.append(
                f"  • {c_name} | status={c_status} | always_on={always_on} "
                f"| budget={budget_type}/{budget_amount}"
            )
        return CheckResult(3, name, Status.PASS, "\n".join(lines))
    except httpx.TimeoutException:
        return CheckResult(3, name, Status.FAIL, "Request timed out")
    except httpx.ConnectError:
        return CheckResult(3, name, Status.FAIL, "Connection error")
    except Exception as exc:
        return CheckResult(3, name, Status.FAIL, f"Unexpected error: {exc}")


# ---------------------------------------------------------------------------
# Check 4: Entity Registration Failures
# ---------------------------------------------------------------------------
def check_entity_failures(
    client: httpx.Client,
    base_url: str,
    token: str,
    member_group_id: int,
    advertiser_id: int,
) -> CheckResult:
    name = "Entity Registration Failures"
    try:
        url = (
            f"{base_url}/member_groups/{member_group_id}"
            f"/advertisers/{advertiser_id}/entity_registrations/failed/report"
        )
        resp = make_request(
            client,
            "POST",
            url,
            token=token,
            json_body={"pagination": {"count": 50, "start": 0}},
        )
        data = resp.json()
        if data.get("status") != "success":
            error_code = data.get("error_code", "unknown")
            error_msg = data.get("message", data.get("error", "unknown error"))
            return CheckResult(
                4, name, Status.FAIL, f"Error {error_code}: {error_msg}"
            )
        result = data.get("result", {})
        total = result.get("total", 0)
        if total == 0:
            return CheckResult(4, name, Status.PASS, "No entity registration failures")

        failures = result.get("entity_registrations", [])[:5]
        lines = [f"⚠️  {total} registration failure(s) found. First {len(failures)}:"]
        for f in failures:
            err_msg = f.get("error_message", "N/A")
            err_code = f.get("error_code", "N/A")
            lines.append(f"  • [{err_code}] {err_msg}")
        return CheckResult(4, name, Status.WARN, "\n".join(lines))
    except httpx.TimeoutException:
        return CheckResult(4, name, Status.FAIL, "Request timed out")
    except httpx.ConnectError:
        return CheckResult(4, name, Status.FAIL, "Connection error")
    except Exception as exc:
        return CheckResult(4, name, Status.FAIL, f"Unexpected error: {exc}")


# ---------------------------------------------------------------------------
# Check 5: Active Bidders Cache
# ---------------------------------------------------------------------------
def check_active_bidders(
    client: httpx.Client,
    base_url: str,
    token: str,
    member_group_id: int,
) -> CheckResult:
    name = "Active Bidders Cache"
    try:
        url = f"{base_url}/member_groups/{member_group_id}/active_bidders"
        resp = make_request(client, "GET", url, token=token)
        data = resp.json()
        if data.get("status") != "success":
            error_code = data.get("error_code", "unknown")
            error_msg = data.get("message", data.get("error", "unknown error"))
            return CheckResult(
                5, name, Status.FAIL, f"Error {error_code}: {error_msg}"
            )
        bidders = data.get("result", {}).get("active_bidders", [])
        if not bidders:
            return CheckResult(
                5,
                name,
                Status.WARN,
                "⚠️  Active bidders list is empty — no ad groups are active",
            )
        return CheckResult(
            5, name, Status.PASS, f"{len(bidders)} active bidder(s) in cache"
        )
    except httpx.TimeoutException:
        return CheckResult(5, name, Status.FAIL, "Request timed out")
    except httpx.ConnectError:
        return CheckResult(5, name, Status.FAIL, "Connection error")
    except Exception as exc:
        return CheckResult(5, name, Status.FAIL, f"Unexpected error: {exc}")


# ---------------------------------------------------------------------------
# Check 6: Attributable Entities Cache
# ---------------------------------------------------------------------------
def check_attributable_entities(
    client: httpx.Client,
    base_url: str,
    token: str,
    member_group_id: int,
) -> CheckResult:
    name = "Attributable Entities Cache"
    try:
        url = f"{base_url}/member_groups/{member_group_id}/attributable_entities"
        resp = make_request(client, "GET", url, token=token)
        data = resp.json()
        if data.get("status") != "success":
            error_code = data.get("error_code", "unknown")
            error_msg = data.get("message", data.get("error", "unknown error"))
            return CheckResult(
                6, name, Status.FAIL, f"Error {error_code}: {error_msg}"
            )
        entities = data.get("result", {}).get("attributable_entities", [])
        if not entities:
            return CheckResult(
                6,
                name,
                Status.WARN,
                "⚠️  No attributable entities — conversions won't attribute",
            )
        return CheckResult(
            6, name, Status.PASS, f"{len(entities)} attributable entit(ies) in cache"
        )
    except httpx.TimeoutException:
        return CheckResult(6, name, Status.FAIL, "Request timed out")
    except httpx.ConnectError:
        return CheckResult(6, name, Status.FAIL, "Connection error")
    except Exception as exc:
        return CheckResult(6, name, Status.FAIL, f"Unexpected error: {exc}")


# ---------------------------------------------------------------------------
# Check 7: Winning Ads (Test Auction)
# ---------------------------------------------------------------------------
def check_winning_ads(
    client: httpx.Client,
    client_name: str,
    site_id: str,
    experience_name: Optional[str],
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
        if experience_name is not None:
            body["experience_name"] = experience_name

        resp = make_request(client, "POST", url, json_body=body)
        if resp.status_code != 200:
            return CheckResult(
                7,
                name,
                Status.FAIL,
                f"HTTP {resp.status_code} — auction engine may be misconfigured "
                f"or client '{client_name}' is not provisioned",
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
        return CheckResult(
            7,
            name,
            Status.FAIL,
            f"Connection error — cannot reach {client_name}.koddi.io",
        )
    except Exception as exc:
        return CheckResult(7, name, Status.FAIL, f"Unexpected error: {exc}")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
def print_summary(results: list[CheckResult]) -> None:
    console.print()
    console.rule("[bold]Health Check Summary[/bold]")
    console.print()

    table = Table(show_header=True, header_style="bold")
    table.add_column("Check #", justify="center", width=8)
    table.add_column("Name", min_width=30)
    table.add_column("Status", justify="center", width=12)
    table.add_column("Details", max_width=60)

    for r in results:
        style_map = {
            Status.PASS: "green",
            Status.WARN: "yellow",
            Status.FAIL: "red",
            Status.SKIPPED: "dim",
        }
        style = style_map[r.status]
        # Truncate multiline details for the summary table
        short_detail = r.details.split("\n")[0]
        if len(short_detail) > 60:
            short_detail = short_detail[:57] + "..."
        table.add_row(
            str(r.number),
            r.name,
            Text(status_plain(r.status), style=style),
            Text(short_detail, style=style),
        )

    console.print(table)

    passes = sum(1 for r in results if r.status == Status.PASS)
    warns = sum(1 for r in results if r.status == Status.WARN)
    fails = sum(1 for r in results if r.status == Status.FAIL)
    skips = sum(1 for r in results if r.status == Status.SKIPPED)

    console.print()
    console.print(
        f"  [green]{passes} passed[/green]  "
        f"[yellow]{warns} warning(s)[/yellow]  "
        f"[red]{fails} failed[/red]  "
        f"[dim]{skips} skipped[/dim]"
    )
    console.print()


def results_to_json(results: list[CheckResult]) -> str:
    output = []
    for r in results:
        output.append(
            {
                "check": r.number,
                "name": r.name,
                "status": r.status.value,
                "details": r.details,
            }
        )
    has_failure = any(r.status == Status.FAIL for r in results)
    return json.dumps(
        {"checks": output, "overall": "fail" if has_failure else "pass"},
        indent=2,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
@click.command()
@click.option("--email", envvar="KODDI_EMAIL", required=True, help="Koddi account email")
@click.option(
    "--password", envvar="KODDI_PASSWORD", required=True, help="Koddi account password"
)
@click.option(
    "--member-group-id",
    envvar="KODDI_MEMBER_GROUP_ID",
    required=True,
    type=int,
    help="Member group ID",
)
@click.option(
    "--advertiser-id",
    envvar="KODDI_ADVERTISER_ID",
    required=True,
    type=int,
    help="Advertiser ID",
)
@click.option(
    "--client-name",
    envvar="KODDI_CLIENT_NAME",
    required=True,
    help="Client name for auction engine (e.g. myretailer)",
)
@click.option(
    "--site-id",
    default="homepage",
    help="Site ID for test auction (default: homepage)",
)
@click.option(
    "--experience-name",
    default=None,
    help="Experience name for test auction (optional)",
)
@click.option(
    "--base-url",
    default="https://koddi.io/console/v1",
    show_default=True,
    help="Base URL for Koddi Console API",
)
@click.option(
    "--timeout",
    default=30,
    type=int,
    show_default=True,
    help="Request timeout in seconds",
)
@click.option(
    "--json-output",
    "use_json",
    is_flag=True,
    default=False,
    help="Output results as JSON",
)
def main(
    email: str,
    password: str,
    member_group_id: int,
    advertiser_id: int,
    client_name: str,
    site_id: str,
    experience_name: Optional[str],
    base_url: str,
    timeout: int,
    use_json: bool,
) -> None:
    """Koddi Ads implementation health check — validates your setup end-to-end."""
    base_url = base_url.rstrip("/")
    results: list[CheckResult] = []
    token: Optional[str] = None
    has_failure = False

    if not use_json:
        console.print()
        console.rule("[bold blue]Koddi Health Check[/bold blue]")
        console.print(
            f"  member_group_id={member_group_id}  advertiser_id={advertiser_id}  "
            f"client={client_name}"
        )
        console.print()

    with httpx.Client(timeout=timeout) as client:
        # -- Check 1: Auth --
        print_check_header(1, "Authentication", use_json)
        auth_result, token = check_auth(
            client, base_url, email, password, member_group_id
        )
        results.append(auth_result)
        print_result(auth_result, use_json)
        if auth_result.status == Status.FAIL:
            has_failure = True

        # Checks 2-6 require auth
        auth_dependent = [
            (2, "Advertiser Exists"),
            (3, "Campaigns Report"),
            (4, "Entity Registration Failures"),
            (5, "Active Bidders Cache"),
            (6, "Attributable Entities Cache"),
        ]

        if token is None:
            # Skip all auth-dependent checks
            for num, name in auth_dependent:
                r = CheckResult(num, name, Status.SKIPPED, "Skipped — authentication failed")
                results.append(r)
                print_check_header(num, name, use_json)
                print_result(r, use_json)
        else:
            # -- Check 2: Advertiser --
            print_check_header(2, "Advertiser Exists", use_json)
            r2 = check_advertiser(
                client, base_url, token, member_group_id, advertiser_id
            )
            results.append(r2)
            print_result(r2, use_json)
            if r2.status == Status.FAIL:
                has_failure = True
                # Skip checks 3-4 that depend on advertiser
                for num, name in auth_dependent[1:3]:
                    r = CheckResult(
                        num, name, Status.SKIPPED, "Skipped — advertiser check failed"
                    )
                    results.append(r)
                    print_check_header(num, name, use_json)
                    print_result(r, use_json)
            else:
                # -- Check 3: Campaigns --
                print_check_header(3, "Campaigns Report", use_json)
                r3 = check_campaigns(
                    client, base_url, token, member_group_id, advertiser_id
                )
                results.append(r3)
                print_result(r3, use_json)
                if r3.status == Status.FAIL:
                    has_failure = True

                # -- Check 4: Entity Failures --
                print_check_header(4, "Entity Registration Failures", use_json)
                r4 = check_entity_failures(
                    client, base_url, token, member_group_id, advertiser_id
                )
                results.append(r4)
                print_result(r4, use_json)
                if r4.status == Status.FAIL:
                    has_failure = True

            # -- Check 5: Active Bidders (depends on auth, not advertiser) --
            print_check_header(5, "Active Bidders Cache", use_json)
            r5 = check_active_bidders(client, base_url, token, member_group_id)
            results.append(r5)
            print_result(r5, use_json)
            if r5.status == Status.FAIL:
                has_failure = True

            # -- Check 6: Attributable Entities (depends on auth, not advertiser) --
            print_check_header(6, "Attributable Entities Cache", use_json)
            r6 = check_attributable_entities(
                client, base_url, token, member_group_id
            )
            results.append(r6)
            print_result(r6, use_json)
            if r6.status == Status.FAIL:
                has_failure = True

        # -- Check 7: Winning Ads (no auth needed, but needs client_name) --
        print_check_header(7, "Winning Ads (Test Auction)", use_json)
        r7 = check_winning_ads(client, client_name, site_id, experience_name)
        results.append(r7)
        print_result(r7, use_json)
        if r7.status == Status.FAIL:
            has_failure = True

    if use_json:
        click.echo(results_to_json(results))
    else:
        print_summary(results)

    sys.exit(1 if has_failure else 0)


if __name__ == "__main__":
    main()
