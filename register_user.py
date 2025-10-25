import json
import os
from pathlib import Path

def get_secure_user_input():
    """
    Collect sensitive user information and save to a secure JSON file.
    This should be run separately and the JSON file should NOT be committed to version control.
    """
    print("=== Secure Pizza Ordering Information Setup ===")
    print("This information will be stored locally and NOT shared with the LLM.\n")
    
    # Address information
    print("--- Delivery Address ---")
    street = input("Street Address: ").strip()
    city = input("City: ").strip()
    state = input("State (2-letter code, e.g., NY): ").strip().upper()
    zip_code = input("ZIP Code: ").strip()
    
    # Customer details
    print("\n--- Customer Information ---")
    first_name = input("First Name: ").strip()
    last_name = input("Last Name: ").strip()
    email = input("Email: ").strip()
    phone = input("Phone (10 digits): ").strip()
    
    # Payment details
    print("\n--- Payment Information ---")
    print("WARNING: This will be stored in plain text. Use a test card or be cautious!")
    card_number = input("Card Number: ").strip()
    expiration = input("Expiration (MMYY format): ").strip()
    security_code = input("Security Code (CVV): ").strip()
    billing_zip = input("Billing ZIP Code: ").strip()
    
    # Create secure data structure
    secure_data = {
        "address": {
            "street": street,
            "city": city,
            "state": state,
            "zip_code": zip_code
        },
        "customer": {
            "first_name": first_name,
            "last_name": last_name,
            "email": email,
            "phone": phone
        },
        "payment": {
            "card_number": card_number,
            "expiration": expiration,
            "security_code": security_code,
            "zip_code": billing_zip
        }
    }
    
    # Save to file
    secure_file_path = "mcp_servers/user/secure_user_data.json"
    
    with open(secure_file_path, 'w') as f:
        json.dump(secure_data, f, indent=2)
    
    print(f"\n✓ Secure information saved to: {secure_file_path}")
    print("\nIMPORTANT SECURITY NOTES:")
    print("1. Add 'secure_user_data.json' to your .gitignore file")
    print("2. Do not share this file with anyone")
    print("3. Consider using environment variables or a proper secrets manager for production")
    print("4. This file contains sensitive payment information in plain text!")
    
    return secure_file_path

if __name__ == "__main__":
    get_secure_user_input()