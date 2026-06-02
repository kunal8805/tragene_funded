import os
import sys

# Add parent directory to sys.path so we can import app and models
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app

# Set up test configuration
app.config['TESTING'] = True
client = app.test_client()

# Disable rate limiting for testing if present
app.config['RATELIMIT_ENABLED'] = False

try:
    # Execute the GET request to /robots.txt
    response = client.get('/robots.txt')
    
    print("\n--- ROBOTS.TXT RESPONSE VERIFICATION ---")
    print(f"Status Code: {response.status_code}")
    print(f"Content-Type: {response.content_type}")
    
    # Verify HTTP status and Content-Type headers
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    assert 'text/plain' in response.content_type, f"Expected text/plain header, got {response.content_type}"
    
    # Decode and parse response data
    content = response.data.decode('utf-8')
    print("\n--- CONTENT ---")
    print(content)
    print("----------------")
    
    # Check that crucial disallows are present
    assert "Disallow: /admin/" in content, "Missing /admin/ disallow rule"
    assert "Disallow: /user/" in content, "Missing /user/ disallow rule"
    assert "Disallow: /partner/" in content, "Missing /partner/ disallow rule"
    assert "Disallow: /api/" in content, "Missing /api/ disallow rule"
    
    # Check that sitemap URL is referenced
    assert "Sitemap: http" in content and "sitemap.xml" in content, "Robots.txt does not link to sitemap.xml"
    
    print("\nRobots.txt Content & Structure: VALID")
    print("TESTS PASSED SUCCESSFULLY!")
    
except AssertionError as e:
    print(f"\nAssertion Failed: {e}")
    sys.exit(1)
except Exception as e:
    print(f"\nTest Execution Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
