import requests

# Check the API key from setup
response = requests.get(
    "https://saferun-api.up.railway.app/v1/auth/status",
    headers={"X-API-Key": "sr_LPJyzBIUPAV5-jwURugmwBbtUyvrmsa_zkDn2g9yO0Y"}
)

import json
print("Status check:")
print(json.dumps(response.json(), indent=2))
print(f"Status code: {response.status_code}")
