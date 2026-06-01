import os
import sys

# Add parent directory to sys.path so we can import app and models
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from models import BlogPost

# Set up test configuration
app.config['TESTING'] = True
client = app.test_client()

# Disable rate limiting for testing if present
app.config['RATELIMIT_ENABLED'] = False

with app.app_context():
    # Print SQLAlchemy configuration for debugging
    print(f"Database URI in use: {app.config.get('SQLALCHEMY_DATABASE_URI')}")
    
    # Count blog posts in the database
    post_count = BlogPost.query.count()
    print(f"Total blog posts in DB: {post_count}")
    
    # Start a nested transaction savepoint to avoid writing persistent test data
    db.session.begin_nested()
    
    try:
        # If no posts are found, seed a temporary blog post to verify dynamic retrieval
        if post_count == 0:
            print("No blog posts found. Creating a temporary test blog post...")
            test_post = BlogPost(
                title="Test Blog Post",
                slug="test-blog-post-sitemap-verification",
                content="This is a test blog post content.",
                meta_description="Test meta description"
            )
            db.session.add(test_post)
            db.session.flush()
            print(f"Temporary blog post created with slug: {test_post.slug}")
            
        # Execute the GET request to /sitemap.xml
        response = client.get('/sitemap.xml')
        
        print("\n--- RESPONSE VERIFICATION ---")
        print(f"Status Code: {response.status_code}")
        print(f"Content-Type: {response.content_type}")
        
        # Verify HTTP status and Content-Type headers
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        assert 'application/xml' in response.content_type, f"Expected application/xml header, got {response.content_type}"
        
        # Parse XML structure
        import xml.etree.ElementTree as ET
        root = ET.fromstring(response.data)
        print("XML parsing: SUCCESS")
        
        # Define XML namespaces (sitemaps.org namespace)
        namespace = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        urls = root.findall('ns:url', namespace)
        print(f"Total URLs found in sitemap: {len(urls)}")
        
        assert len(urls) > 0, "Sitemap should contain at least one URL"
        
        # Verify each url block matches Google's sitemap requirements
        for url in urls:
            loc = url.find('ns:loc', namespace)
            lastmod = url.find('ns:lastmod', namespace)
            changefreq = url.find('ns:changefreq', namespace)
            priority = url.find('ns:priority', namespace)
            
            assert loc is not None and loc.text, "URL element missing <loc>"
            assert lastmod is not None and lastmod.text, "URL element missing <lastmod>"
            assert changefreq is not None and changefreq.text, "URL element missing <changefreq>"
            assert priority is not None and priority.text, "URL element missing <priority>"
            
            # Print sample outputs (homepage or test blog post)
            if "test-blog-post" in loc.text or loc.text.endswith('/') or len(urls) <= 10:
                print(f" - Loc: {loc.text}")
                print(f"   Lastmod: {lastmod.text} | Changefreq: {changefreq.text} | Priority: {priority.text}")
                
        print("\nSitemap XML Structure & Tags: VALID")
        print("TESTS PASSED SUCCESSFULLY!")
        
    except AssertionError as e:
        print(f"\nAssertion Failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\nTest Execution Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        # Rollback all changes made in the savepoint transaction
        db.session.rollback()
