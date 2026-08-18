import requests

# In v6, the raw OpenAPI spec is usually at the root or under api/v1
URLS_TO_TRY = [
    "http://localhost:9090/openapi.json",
    "http://localhost:9090/api/v1/openapi.json"
]

for url in URLS_TO_TRY:
    try:
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            # Node types are found in the 'components' schemas
            nodes = data.get('components', {}).get('schemas', {}).keys()
            print(f"✅ Success at {url}. Found key nodes:")
            # Filter for common generation nodes
            found = [n for n in nodes if any(x in n.lower() for x in ['denoise', 'loader', 'compel', 'noise'])]
            for f in found[:10]: print(f" - {f}")
            break
    except:
        continue