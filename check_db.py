import requests

response = requests.get(
    "https://saferun-api.up.railway.app/api/changes/fabdfbec-0468-4f07-a483-f0223751a527",
    headers={"X-API-Key": "sr_UgLp_t3NnTDzjPqyGTQ2NUVQmSIIQzd-dXl9KshDCSM"}
)

import json
print(json.dumps(response.json(), indent=2))
