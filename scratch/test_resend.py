import os
from dotenv import load_dotenv
load_dotenv()

try:
    import resend
    print(f"Resend version: {resend.__version__ if hasattr(resend, '__version__') else 'unknown'}")
    
    # Check if Resend class exists
    if hasattr(resend, 'Resend'):
        print("Resend class found")
    else:
        print("Resend class NOT found")
        
    if hasattr(resend, 'Emails'):
        print("resend.Emails found")
        
except ImportError as e:
    print(f"Import error: {e}")
except Exception as e:
    print(f"Error: {e}")
