"""Generate an installation identity; keep the output private and persistent."""
import argparse
import json
import secrets
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gostream_license import LicenseConfig

parser = argparse.ArgumentParser()
parser.add_argument("--api-url", required=True)
parser.add_argument("--deployment-url", required=True)
parser.add_argument("--output", required=True)
args = parser.parse_args()
config = LicenseConfig.from_mapping({"api_url": args.api_url, "deployment_url": args.deployment_url,
                                     "installation_id": secrets.token_urlsafe(36)})
path = Path(args.output)
path.parent.mkdir(parents=True, exist_ok=True)
with path.open("x", encoding="utf-8") as file:
    file.write("[gostream_license]\n")
    for key in ("api_url", "installation_id", "deployment_url"):
        file.write(f"{key} = {json.dumps(getattr(config, key))}\n")
print(f"Private installation configuration saved to: {path}")
