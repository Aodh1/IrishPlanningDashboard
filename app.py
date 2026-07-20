Python

import http.server
import json
import os
import socketserver
import urllib.parse
from datetime import datetime, timezone
import requests

# Use PORT assigned by hosting environment, or default to 8000
PORT = int(os.environ.get("PORT", 8000))
BASE_URL = "https://services.arcgis.com/NzlPQPKn5QF9v2US/arcgis/rest/services/IrishPlanningApplications/FeatureServer/0/query"

# Cork City Agile API Endpoint
CORK_CITY_API_URL = "https://planningapi.agileapplications.ie/api/application/search?query=Bishopstown"


def fetch_cork_city_agile_data(start_date_str=None, end_date_str=None, filter_type="all"):
    """Fetches Cork City planning data directly from the new Agile Applications API."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/json, text/plain, */*",
    }

    try:
        response = requests.get(CORK_CITY_API_URL, headers=headers, timeout=15)
        response.raise_for_status()
        records = response.json()

        if isinstance(records, dict):
            records = records.get("results") or records.get("data") or records.get("items") or []

        results = []
        for item in records:
            ref = item.get("applicationNumber") or item.get("reference") or item.get("id") or "N/A"
            address = item.get("address") or item.get("location") or item.get("siteAddress") or "No Address Provided"
            desc = item.get("proposal") or item.get("description") or item.get("developmentDescription") or "No description provided."
            decision = item.get("decision") or item.get("status") or "N/A"
            
            # Extract applicant name if present
            applicant = item.get("applicantName") or item.get("applicant") or "Unknown Applicant"

            date_raw = item.get("decisionDate") if filter_type == "granted" else (item.get("receivedDate") or item.get("registeredDate"))

            # Decision filtering
            decision_text = str(decision).upper()
            is_granted = "GRANT" in decision_text or "APPROVED" in decision_text or "CONDITIONAL" in decision_text
            if filter_type == "granted" and not is_granted:
                continue

            # Parse date string
            formatted_date = "N/A"
            if date_raw:
                try:
                    dt_obj = datetime.fromisoformat(str(date_raw).replace("Z", ""))
                    formatted_date = dt_obj.strftime("%d-%m-%Y")
                    if filter_type == "granted":
                        formatted_date += " (Decision Date)"
                except ValueError:
                    formatted_date = str(date_raw)

            # Map links
            search_query = f"{address}, Cork City, Ireland"
            map_url = f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote(search_query)}"

            results.append(
                {
                    "ref": ref,
                    "applicant": applicant,
                    "address": str(address).strip().title(),
                    "county": "Cork City",
                    "desc": desc,
                    "date": formatted_date,
                    "link": "https://www.corkcity.ie/en/council-services/services/planning/search-for-a-planning-application/",
                    "map_link": map_url,
                    "arcgis_link": None,
                    "decision": decision,
                }
            )
        return results
    except Exception as e:
        print(f"Error querying Cork City Agile API: {e}")
        return []


def fetch_planning_data(counties, filter_type="all", start_date_str=None, end_date_str=None):
    if not counties:
        return []

    results = []

    # 1. Handle Cork City separately
    fetch_cork_city = any(c.strip().lower() == "cork city" for c in counties)
    
    # 2. Prepare remaining counties for ArcGIS national API
    arcgis_counties = [c for c in counties if c.strip().lower() != "cork city"]

    if arcgis_counties:
        sub_clauses = []
        for c in arcgis_counties:
            clean_c = c.strip()
            if clean_c.lower() == "cork":
                sub_clauses.append("(UPPER(PlanningAuthority) LIKE '%CORK%' AND UPPER(PlanningAuthority) NOT LIKE '%CORK CITY%')")
            elif clean_c.lower() == "galway city":
                sub_clauses.append("UPPER(PlanningAuthority) LIKE '%GALWAY CITY%'")
            elif clean_c.lower() == "galway":
                sub_clauses.append("(UPPER(PlanningAuthority) LIKE '%GALWAY%' AND UPPER(PlanningAuthority) NOT LIKE '%GALWAY CITY%')")
            else:
                sub_clauses.append(f"UPPER(PlanningAuthority) LIKE '%{clean_c.upper()}%'")

        where_clause = " OR ".join(sub_clauses)
        active_date_field = "DecisionDate" if filter_type == "granted" else "ReceivedDate"

        params = {
            "where": where_clause,
            "outFields": "ApplicationNumber,PlanningAuthority,DevelopmentDescription,DevelopmentAddress,ReceivedDate,DecisionDate,LinkAppDetails,Decision,ApplicantForename,ApplicantSurname",
            "f": "json",
            "returnGeometry": "true",
            "outSR": "4326",
            "orderByFields": f"{active_date_field} DESC",
            "resultRecordCount": 2000,
        }

        start_bound = None
        end_bound = None

        if start_date_str and start_date_str.strip() != "":
            start_bound = datetime.strptime(start_date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)

        if end_date_str and end_date_str.strip() != "":
            end_bound = datetime.strptime(end_date_str, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59, tzinfo=timezone.utc
            )

        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            response = requests.get(BASE_URL, params=params, headers=headers, timeout=15)
            response.raise_for_status()
            features = response.json().get("features", [])

            for item in features:
                attrs = item.get("attributes", {})
                geometry = item.get("geometry", {})

                decision_text = str(attrs.get("Decision", "N/A")).upper().strip()
                is_granted_status = (
                    "GRANT" in decision_text or 
                    "CONDITIONAL" in decision_text or 
                    "APPROVED" in decision_text
                )

                if filter_type == "granted" and not is_granted_status:
                    continue

                raw_date = attrs.get(active_date_field)
                if not raw_date:
                    continue

                target_date = datetime.fromtimestamp(raw_date / 1000, tz=timezone.utc)

                if start_bound and target_date < start_bound:
                    continue
                if end_bound and target_date > end_bound:
                    continue

                forename = str(attrs.get("ApplicantForename") or "").strip()
                surname = str(attrs.get("ApplicantSurname") or "").strip()
                applicant = f"{forename} {surname}".strip().title() if (forename or surname) else "Unknown Applicant"

                raw_address = attrs.get("DevelopmentAddress")
                address = str(raw_address).strip().title() if raw_address else "No Address Provided"
                county_name = attrs.get("PlanningAuthority", "Unknown").replace("County Council", "").replace("City Council", "").strip().title()

                search_query = f"{address}, Co. {county_name}, Ireland"
                map_url = f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote(search_query)}"

                if geometry and "y" in geometry and "x" in geometry:
                    lat, lng = geometry["y"], geometry["x"]
                    if -90 <= lat <= 90 and -180 <= lng <= 180:
                        map_url = f"https://www.google.com/maps?q={lat},{lng}"

                app_ref = attrs.get("ApplicationNumber", "")
                arcgis_url = f"https://roscoco.maps.arcgis.com/apps/webappviewer/index.html?id=84b0356c3b45483c9da36ecccbd3aa93&find={app_ref}" if app_ref else None

                results.append(
                    {
                        "ref": app_ref or "N/A",
                        "applicant": applicant,
                        "address": address,
                        "county": county_name,
                        "desc": attrs.get("DevelopmentDescription", "No description provided."),
                        "date": f"{target_date.strftime('%d-%m-%Y')} (Decision Date)" if filter_type == "granted" else target_date.strftime('%d-%m-%Y'),
                        "link": attrs.get("LinkAppDetails", "#"),
                        "map_link": map_url,
                        "arcgis_link": arcgis_url,
                        "decision": attrs.get("Decision", "N/A")
                    }
                )
        except Exception as e:
            print(f"Error querying data payload: {e}")

    # 3. Merge Cork City results if Cork City was selected
    if fetch_cork_city:
        cork_city_data = fetch_cork_city_agile_data(start_date_str, end_date_str, filter_type)
        results.extend(cork_city_data)

    return results


class LocalPlanningServer(http.server.SimpleHTTPRequestHandler):

    def do_POST(self):
        if self.path == "/get-data":
            content_length = int(self.headers["Content-Length"])
            body = self.rfile.read(content_length)
            payload = json.loads(body)

            selected_counties = payload.get("counties", [])
            filter_type = payload.get("filter_type", "all")
            start_date = payload.get("start_date", "")
            end_date = payload.get("end_date", "")

            data = fetch_planning_data(selected_counties, filter_type, start_date, end_date)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode("utf-8"))
        else:
            super().do_POST()


if __name__ == "__main__":
    print(f"Starting server on port {PORT}...")
    with socketserver.TCPServer(("0.0.0.0", PORT), LocalPlanningServer) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down server.")