from app import app

client = app.test_client()

print("--- Requesting /logout ---")
response = client.get('/logout')
print(f"Status: {response.status_code}")
print(f"Headers: {dict(response.headers)}")
print(f"Data snippet: {response.data[:200]}")

if response.status_code in (301, 302):
    location = response.headers.get('Location')
    print(f"\n--- Redirecting to {location} ---")
    redirect_response = client.get(location)
    print(f"Status: {redirect_response.status_code}")
    print(f"Data snippet: {redirect_response.data[:200]}")
