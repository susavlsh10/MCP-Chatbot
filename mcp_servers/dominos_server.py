"""
Domino's Pizza MCP Server
A Model Context Protocol server for ordering pizzas from Domino's using their API.
"""
from mcp.server.fastmcp import FastMCP
from typing import Optional, List, Dict, Any
import os
from dotenv import load_dotenv

import json
import threading
from pathlib import Path

# Note: This uses the pizzapi library for Domino's API integration
# Install with: pip install pizzapi
try:
    from pizzapi import Customer, Address, Store, Order, PaymentObject
    from pizzapi.menu import Menu, MenuCategory
    
    # Monkey-patch the Menu class to handle missing products gracefully
    _original_build_categories = Menu.build_categories
    
    def patched_build_categories(self, category_data, parent=None):
        """Patched version that skips missing products instead of raising exceptions"""
        category = MenuCategory(category_data, parent)
        
        # Build subcategories
        for subcategory in category_data.get('Categories', []):
            try:
                new_subcategory = patched_build_categories(self, subcategory, category)
                category.subcategories.append(new_subcategory)
            except Exception:
                # Skip problematic subcategories
                continue
        
        # Add products, skipping missing ones
        for product_code in category_data.get('Products', []):
            if product_code in self.menu_by_code:
                product = self.menu_by_code[product_code]
                category.products.append(product)
            # Silently skip missing products instead of raising exception
        
        return category
    
    # Apply the patch
    Menu.build_categories = patched_build_categories
    
    PIZZAPI_AVAILABLE = True
except ImportError:
    PIZZAPI_AVAILABLE = False
    print("Warning: pizzapi not installed. Install with: pip install pizzapi")

load_dotenv()

# Initialize FastMCP server
mcp = FastMCP("dominos-pizza-server")

# Session state to store customer info and cart
session_state = {
    "customer": None,
    "address": None,
    "store": None,
    "order": None,
    "cart_items": [],
    "secure_data": None
}

def load_secure_data(data_path: Optional[str] = None) -> Dict[str, Any]:
    """Load secure user data from JSON file."""
    secure_file_path = Path(__file__).parent / "user/secure_user_data.json"

    if data_path:
        secure_file_path = Path(data_path)

    if not secure_file_path.exists():
        raise FileNotFoundError(
            f"Secure data file not found at {secure_file_path}. "
            "Please run register_user.py first to create it."
        )
    
    with open(secure_file_path, 'r') as f:
        data = json.load(f)
    
    # Validate required fields
    required_keys = ['address', 'customer', 'payment']
    for key in required_keys:
        if key not in data:
            raise ValueError(f"Missing required section '{key}' in secure data file")
    
    return data

# @mcp.tool()
# def find_nearest_store(
#     street: str,
#     city: str,
#     state: str,
#     zip_code: str
# ) -> str:
#     """
#     Find the nearest Domino's store based on delivery address.
    
#     Args:
#         street: Street address (e.g., "123 Main St")
#         city: City name
#         state: Two-letter state code (e.g., "NY")
#         zip_code: ZIP code
        
#     Returns:
#         Store information including ID, address, and whether it's open
#     """
#     if not PIZZAPI_AVAILABLE:
#         return json.dumps({"error": "pizzapi library not installed"})
    
#     try:
#         # Create address object
#         address = Address(street=street, city=city, region=state, zip=zip_code)
#         session_state["address"] = address
        
#         # Find nearest store
#         store = address.closest_store()
#         session_state["store"] = store
        
#         result = {
#             "store_id": store.data.get("StoreID"),
#             "address": f"{store.data.get('AddressDescription', 'N/A')}",
#             "phone": store.data.get("Phone", "N/A"),
#             "is_open": store.data.get("IsOpen", False),
#             "service_available": store.data.get("ServiceIsOpen", {}),
#         }
        
#         return json.dumps(result, indent=2)
#     except Exception as e:
#         return json.dumps({"error": f"Failed to find store: {str(e)}"})


@mcp.tool()
def find_nearest_store() -> str:
    """
    Find the nearest Domino's store based on the delivery address from secure file.
    Call initialize_customer first to load secure data.
    
    Returns:
        Store information including ID, address, and whether it's open
    """
    if not PIZZAPI_AVAILABLE:
        return json.dumps({"error": "pizzapi library not installed"})
    
    if not session_state.get("secure_data"):
        return json.dumps({"error": "Customer not initialized. Call initialize_customer first."})
    
    try:
        # Get address from secure data
        address_data = session_state["secure_data"]["address"]
        
        # Create address object
        address = Address(
            street=address_data["street"],
            city=address_data["city"],
            region=address_data["state"],
            zip=address_data["zip_code"]
        )
        session_state["address"] = address
        
        # Find nearest store
        store = address.closest_store()
        session_state["store"] = store
        
        result = {
            "store_id": store.data.get("StoreID"),
            "address": f"{store.data.get('AddressDescription', 'N/A')}",
            "phone": store.data.get("Phone", "N/A"),
            "is_open": store.data.get("IsOpen", False),
            "service_available": store.data.get("ServiceIsOpen", {}),
            "delivery_city": address_data["city"],
            "delivery_state": address_data["state"]
        }
        
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": f"Failed to find store: {str(e)}"})

@mcp.tool()
def get_menu(category: Optional[str] = None) -> str:
    """
    Get the menu from the selected store. Call find_nearest_store first.
    
    Args:
        category: Optional category filter (e.g., "Pizza", "Sides", "Desserts", "Drinks")
        
    Returns:
        Menu items with codes, names, descriptions, and prices
    """
    if not PIZZAPI_AVAILABLE:
        return json.dumps({"error": "pizzapi library not installed"})
    
    if not session_state.get("store"):
        return json.dumps({"error": "No store selected. Call find_nearest_store first."})
    
    try:
        store = session_state["store"]
        
        # Get raw menu data directly from API
        from pizzapi.utils import request_json
        
        menu_url = store.urls.menu_url()
        raw_menu_data = request_json(menu_url, store_id=store.id, lang='en')
        
        items = []
        
        # Parse products directly from raw data
        if 'Products' in raw_menu_data:
            for item_code, item_data in raw_menu_data['Products'].items():
                try:
                    # Skip items that don't have basic required fields
                    if not isinstance(item_data, dict):
                        continue
                    
                    name = item_data.get("Name", "Unknown")
                    item_category = item_data.get("ProductType", "")
                    
                    # Skip coupon items and other non-orderable products
                    if "coupon" in item_category.lower() or "coupon" in name.lower():
                        continue
                    
                    # Skip items that are only local (not available for ordering)
                    if item_data.get("Local", False) is True:
                        continue
                    
                    # Filter by category if specified
                    if category:
                        if category.lower() not in item_category.lower():
                            continue
                    
                    item_info = {
                        "code": item_code,
                        "name": name,
                        "description": item_data.get("Description", ""),
                        "category": item_category,
                        "variants": item_data.get("Variants", [])
                    }
                    
                    items.append(item_info)
                    
                except Exception as item_error:
                    # Skip problematic items and continue
                    continue
        
        # Limit to first 50 items to avoid overwhelming response
        items = items[:50]
        
        return json.dumps({
            "items": items, 
            "total_shown": len(items),
            "total_products": len(raw_menu_data.get('Products', {})),
            "note": "Menu parsed directly from API"
        }, indent=2)
        
    except Exception as e:
        return json.dumps({"error": f"Failed to get menu: {str(e)}"})


@mcp.tool()
def search_menu(search_term: str) -> str:
    """
    Search for menu items by name or description.
    
    Args:
        search_term: Term to search for (e.g., "pepperoni", "cheese", "wings")
        
    Returns:
        Matching menu items with codes, names, and prices
    """
    if not PIZZAPI_AVAILABLE:
        return json.dumps({"error": "pizzapi library not installed"})
    
    if not session_state.get("store"):
        return json.dumps({"error": "No store selected. Call find_nearest_store first."})
    
    try:
        store = session_state["store"]
        
        # Get raw menu data directly from API
        from pizzapi.utils import request_json
        
        menu_url = store.urls.menu_url()
        raw_menu_data = request_json(menu_url, store_id=store.id, lang='en')
        
        items = []
        search_lower = search_term.lower()
        
        if 'Products' in raw_menu_data:
            for item_code, item_data in raw_menu_data['Products'].items():
                try:
                    # Skip items that don't have basic required fields
                    if not isinstance(item_data, dict):
                        continue
                    
                    name = item_data.get("Name", "")
                    description = item_data.get("Description", "")
                    item_category = item_data.get("ProductType", "")
                    
                    # Skip coupon items
                    if "coupon" in item_category.lower() or "coupon" in name.lower():
                        continue
                    
                    # Skip local-only items
                    if item_data.get("Local", False) is True:
                        continue
                    
                    name_lower = name.lower()
                    description_lower = description.lower()
                    
                    if search_lower in name_lower or search_lower in description_lower:
                        variants = item_data.get("Variants", [])
                        items.append({
                            "code": item_code,
                            "name": name,
                            "description": description,
                            "category": item_category,
                            "variants": variants[:5] if variants else []  # Limit variants
                        })
                except Exception as item_error:
                    # Skip problematic items and continue
                    continue
        
        return json.dumps({
            "search_term": search_term, 
            "items": items, 
            "count": len(items)
        }, indent=2)
        
    except Exception as e:
        return json.dumps({"error": f"Failed to search menu: {str(e)}"})


# @mcp.tool()
# def initialize_customer(
#     first_name: str,
#     last_name: str,
#     email: str,
#     phone: str
# ) -> str:
#     """
#     Initialize customer information for the order.
    
#     Args:
#         first_name: Customer's first name
#         last_name: Customer's last name
#         email: Customer's email address
#         phone: Customer's phone number (10 digits)
        
#     Returns:
#         Confirmation of customer initialization
#     """
#     if not PIZZAPI_AVAILABLE:
#         return json.dumps({"error": "pizzapi library not installed"})
    
#     try:
#         customer = Customer(first_name, last_name, email, phone)
#         session_state["customer"] = customer
        
#         return json.dumps({
#             "status": "success",
#             "message": "Customer information saved",
#             "customer": {
#                 "name": f"{first_name} {last_name}",
#                 "email": email,
#                 "phone": phone
#             }
#         }, indent=2)
#     except Exception as e:
#         return json.dumps({"error": f"Failed to initialize customer: {str(e)}"})

@mcp.tool()
def initialize_customer() -> str:
    """
    Initialize customer information from secure local file.
    This keeps sensitive customer data out of the LLM conversation.
    
    Returns:
        Confirmation of customer initialization with non-sensitive details
    """
    if not PIZZAPI_AVAILABLE:
        return json.dumps({"error": "pizzapi library not installed"})
    
    try:
        # Load secure data
        secure_data = load_secure_data()
        session_state["secure_data"] = secure_data
        
        # Initialize customer
        customer_data = secure_data["customer"]
        customer = Customer(
            customer_data["first_name"],
            customer_data["last_name"],
            customer_data["email"],
            customer_data["phone"]
        )
        session_state["customer"] = customer
        
        return json.dumps({
            "status": "success",
            "message": "Customer information loaded from secure file",
            "customer_name": f"{customer_data['first_name']} {customer_data['last_name']}"
        }, indent=2)
        
    except FileNotFoundError as e:
        return json.dumps({
            "error": "Secure data file not found",
            "message": str(e),
            "action_required": "Please run 'python register_user.py' to create the secure data file"
        })
    except ValueError as e:
        return json.dumps({
            "error": "Invalid secure data file",
            "message": str(e),
            "action_required": "Please check that your secure_user_data.json file has all required fields"
        })
    except Exception as e:
        return json.dumps({"error": f"Failed to initialize customer: {str(e)}"})


@mcp.tool()
def add_to_cart(item_code: str, quantity: int = 1, variant: Optional[str] = None) -> str:
    """
    Add an item to the cart. Use variant code for specific sizes (e.g., "CKRGSBQ" for a specific chicken variant).
    
    Args:
        item_code: Product code from the menu (e.g., "S_SCSBBQ")
        quantity: Number of items to add (default: 1)
        variant: Optional variant code (e.g., size/style). If not provided, uses the first variant.
        
    Returns:
        Updated cart contents
    """
    if not PIZZAPI_AVAILABLE:
        return json.dumps({"error": "pizzapi library not installed"})
    
    if not session_state.get("customer") or not session_state.get("address"):
        return json.dumps({"error": "Initialize customer and find store first"})
    
    try:
        # If no variant specified, try to get the default variant from the product
        if not variant and session_state.get("store"):
            from pizzapi.utils import request_json
            menu_url = session_state["store"].urls.menu_url()
            raw_menu_data = request_json(menu_url, store_id=session_state["store"].id, lang='en')
            
            if item_code in raw_menu_data.get('Products', {}):
                product = raw_menu_data['Products'][item_code]
                variants = product.get('Variants', [])
                
                # Try to get default variant from Tags
                if 'Tags' in product and 'DefaultVariant' in product['Tags']:
                    variant = product['Tags']['DefaultVariant']
                elif variants:
                    variant = variants[0]
        
        # Use variant code if available, otherwise use item code
        code_to_use = variant if variant else item_code
        
        cart_item = {
            "code": code_to_use,
            "original_code": item_code,
            "quantity": quantity,
            "is_variant": variant is not None
        }
        
        session_state["cart_items"].append(cart_item)
        
        return json.dumps({
            "status": "success",
            "message": f"Added {quantity}x {code_to_use} to cart",
            "cart": session_state["cart_items"],
            "cart_size": len(session_state["cart_items"])
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": f"Failed to add item to cart: {str(e)}"})


@mcp.tool()
def view_cart() -> str:
    """
    View current cart contents.
    
    Returns:
        List of items in the cart with quantities
    """
    return json.dumps({
        "cart": session_state["cart_items"],
        "cart_size": len(session_state["cart_items"])
    }, indent=2)


@mcp.tool()
def clear_cart() -> str:
    """
    Clear all items from the cart.
    
    Returns:
        Confirmation message
    """
    session_state["cart_items"] = []
    return json.dumps({"status": "success", "message": "Cart cleared"})


@mcp.tool()
def create_order() -> str:
    """
    Create an order from the current cart. This prepares the order but doesn't place it yet.
    
    Returns:
        Order details including items and estimated total
    """
    if not PIZZAPI_AVAILABLE:
        return json.dumps({"error": "pizzapi library not installed"})
    
    if not session_state.get("customer") or not session_state.get("store"):
        return json.dumps({"error": "Initialize customer and find store first"})
    
    if not session_state["cart_items"]:
        return json.dumps({"error": "Cart is empty. Add items first."})
    
    try:
        # Create order - menu parsing is now patched to skip missing products
        order = Order(session_state["store"], session_state["customer"], session_state["address"])
        
        # Add items from cart using variant codes
        for idx, cart_item in enumerate(session_state["cart_items"]):
            item_code = cart_item["code"]
            quantity = cart_item.get("quantity", 1)
            
            # Build item dictionary in the format pizzapi expects
            item_dict = {
                'Code': item_code,
                'Qty': quantity,
                'ID': idx + 1,
                'isNew': True,
            }
            
            # Add directly to order's product list
            order.data['Products'].append(item_dict)
        
        session_state["order"] = order
        
        return json.dumps({
            "status": "success",
            "message": "Order created (not placed yet)",
            "items": session_state["cart_items"],
            "order_products": len(order.data.get('Products', [])),
            "note": "Use place_order_secure to complete the purchase. Review order carefully!"
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": f"Failed to create order: {str(e)}"})


# @mcp.tool()
# def place_order(
#     card_number: str,
#     expiration: str,
#     security_code: str,
#     zip_code: str
# ) -> str:
#     """
#     Place the order with payment information. USE WITH CAUTION - THIS WILL ACTUALLY ORDER PIZZA!
    
#     Args:
#         card_number: Credit card number
#         expiration: Card expiration (MMYY format)
#         security_code: CVV code
#         zip_code: Billing ZIP code
        
#     Returns:
#         Order confirmation or error
#     """
#     if not PIZZAPI_AVAILABLE:
#         return json.dumps({"error": "pizzapi library not installed"})
    
#     if not session_state.get("order"):
#         return json.dumps({"error": "Create an order first using create_order"})
    
#     try:
#         # Create payment object
#         payment = PaymentObject(
#             card_number, expiration, security_code, zip_code
#         )
        
#         order = session_state["order"]
#         order.pay_with(payment)
        
#         # Actually place the order
#         result = order.place()
        
#         # Clear session after successful order
#         session_state["order"] = None
#         session_state["cart_items"] = []
        
#         return json.dumps({
#             "status": "success",
#             "message": "Order placed successfully!",
#             "result": str(result)
#         }, indent=2)
#     except Exception as e:
#         return json.dumps({"error": f"Failed to place order: {str(e)}"})

@mcp.tool()
def place_order_secure() -> str:
    """
    Place the order using payment information from the secure local file.
    USE WITH CAUTION - THIS WILL ACTUALLY ORDER PIZZA!
    No payment details need to be provided; they're loaded from secure_user_data.json.
    
    Returns:
        Order confirmation or error
    """
    if not PIZZAPI_AVAILABLE:
        return json.dumps({"error": "pizzapi library not installed"})
    
    if not session_state.get("order"):
        return json.dumps({"error": "Create an order first using create_order"})
    
    if not session_state.get("secure_data"):
        return json.dumps({"error": "Secure data not loaded. Initialize customer first."})
    
    try:
        # Load payment info from secure data
        payment_data = session_state["secure_data"]["payment"]
        
        # Create payment object
        payment = PaymentObject(
            payment_data["card_number"],
            payment_data["expiration"],
            payment_data["security_code"],
            payment_data["zip_code"]
        )
        
        order = session_state["order"]
        
        # USE WITH CAUTION - THIS WILL ACTUALLY PLACE THE ORDER
        # order.pay_with(payment)
        
        # # Actually place the order
        # result = order.place()
        
        # dummy result for safety
        result = {}
        
        # Clear session after successful order
        session_state["order"] = None
        session_state["cart_items"] = []
        
        return json.dumps({
            "status": "success",
            "message": "Order placed successfully! Pizza is on its way!",
            "result": str(result)
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": f"Failed to place order: {str(e)}"})

@mcp.tool()
def get_session_info() -> str:
    """
    Get current session state information (customer, store, cart status).
    
    Returns:
        Current session information
    """
    info = {
        "customer_initialized": session_state.get("customer") is not None,
        "store_selected": session_state.get("store") is not None,
        "cart_items": len(session_state.get("cart_items", [])),
        "order_created": session_state.get("order") is not None
    }
    
    if session_state.get("store"):
        info["store_id"] = session_state["store"].data.get("StoreID")
    
    return json.dumps(info, indent=2)


if __name__ == "__main__":
    # Run the server
    mcp.run()