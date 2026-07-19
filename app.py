import http.server
import json
import socketserver
import urllib.parse
import webbrowser
from datetime import datetime, timezone
import requests

PORT = 8000
BASE_URL = "https://services.arcgis.com/NzlPQPKn5QF9v2US/arcgis/rest/services/IrishPlanningApplications/FeatureServer/0/query"


def fetch_planning_data(counties, filter_type="all", start_date_str=None, end_date_str=None):
    if not counties:
        return []

    sub_clauses = [
        f"UPPER(PlanningAuthority) LIKE '%{c.upper().strip()}%'" for c in counties
    ]
    where_clause = " OR ".join(sub_clauses)

    active_date_field = "DecisionDate" if filter_type == "granted" else "ReceivedDate"

    params = {
        "where": where_clause,
        "outFields": "ApplicationNumber,PlanningAuthority,DevelopmentDescription,DevelopmentAddress,ReceivedDate,DecisionDate,LinkAppDetails,Decision,ApplicantForename,ApplicantSurname",
        "f": "json",
        "returnGeometry": "true",
        "outSR": "4326",
        "orderByFields": f"{active_date_field} DESC",
    }

    start_bound = None
    end_bound = None

    if start_date_str and start_date_str.strip() != "":
        start_bound = datetime.strptime(start_date_str, "%Y-%m-%d").replace(
            tzinfo=timezone.utc
        )

    if end_date_str and end_date_str.strip() != "":
        end_bound = datetime.strptime(end_date_str, "%Y-%m-%d").replace(
            hour=23, minute=59, second=59, tzinfo=timezone.utc
        )

    params["resultRecordCount"] = 2000

    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(BASE_URL, params=params, headers=headers, timeout=15)
        response.raise_for_status()
        features = response.json().get("features", [])

        results = []
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
            
            if forename or surname:
                applicant = f"{forename} {surname}".strip().title()
            else:
                applicant = "Unknown Applicant"

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
            
            # Construct the direct ArcGIS WebApp Viewer link searching for the planning ref
            arcgis_url = f"https://roscoco.maps.arcgis.com/apps/webappviewer/index.html?id=84b0356c3b45483c9da36ecccbd3aa93&find={app_ref}" if app_ref else None

            results.append(
                {
                    "ref": app_ref or "N/A",
                    "applicant": applicant,
                    "address": address,
                    "county": county_name,
                    "desc": attrs.get(
                        "DevelopmentDescription", "No description provided."
                    ),
                    "date": f"{target_date.strftime('%d-%m-%Y')} (Decision Date)" if filter_type == "granted" else target_date.strftime('%d-%m-%Y'),
                    "link": attrs.get("LinkAppDetails", "#"),
                    "map_link": map_url,
                    "arcgis_link": arcgis_url,
                    "decision": attrs.get("Decision", "N/A")
                }
            )
        return results
    except Exception as e:
        print(f"Error querying data payload: {e}")
        return []


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
    print(f"Starting your local dashboard at http://localhost:{PORT}")
    webbrowser.open(f"http://localhost:{PORT}")

    with socketserver.TCPServer(("", PORT), LocalPlanningServer) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down server.")