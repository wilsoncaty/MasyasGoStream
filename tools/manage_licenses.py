"""Seller-only operations. Administrator credentials never go to buyers."""
import argparse
import json
import urllib.request
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("command", choices=["list", "issue", "revoke", "restore", "reset-installation", "reset-owner", "extend"])
parser.add_argument("--config", default=".private/license-admin.json")
parser.add_argument("--label")
parser.add_argument("--license-id")
parser.add_argument("--days", type=int, default=365)
parser.add_argument("--output")
args = parser.parse_args()
config = json.loads(Path(args.config).read_text(encoding="utf-8"))
endpoint, method, payload = "/admin/licenses", "GET", None
if args.command == "issue":
    if not args.label or not args.output:
        parser.error("issue requires --label and --output (private license file)")
    if Path(args.output).exists():
        parser.error("Output already exists; choose a new private file")
    method, payload = "POST", {"product_id": "masyasgostream", "label": args.label}
elif args.command != "list":
    if not args.license_id:
        parser.error("This operation requires --license-id")
    endpoint, method = "/admin/action", "POST"
    payload = {"product_id": "masyasgostream", "license_id": args.license_id,
               "action": args.command, "days": args.days}
request = urllib.request.Request(config["api_url"].rstrip("/") + endpoint,
    data=json.dumps(payload).encode() if payload is not None else None,
    headers={"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "MasyasGoStream/1.0",
             "Authorization": "Bearer " + config["admin_token"]}, method=method)
with urllib.request.urlopen(request, timeout=30) as response:
    result = json.load(response)
if args.command == "issue":
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as file:
        json.dump(result, file, indent=2)
    print("License created:", result["license_id"])
    print("Private license key saved to:", output)
else:
    print(json.dumps(result, indent=2))
