"""
MCPizza - Domino's Pizza Ordering MCP Server using FastMCP

This server provides tools for ordering pizza through the unofficial Domino's API.
"""

import sys
import json
import logging
from typing import Any, Dict, Optional

from mcp.server.fastmcp import FastMCP

try:
    from pizzapi import (
        StoreLocator,
        Customer,
        Address,
        Order,
        PaymentObject
    )
except ImportError:
    # Print to stderr to avoid interfering with JSON-RPC on stdout
    print("ERROR: pizzapi not installed. Install with: pip install pizzapi", file=sys.stderr)
    sys.exit(1)

# Configure logging to stderr only
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("mcpizza")

# Initialize FastMCP server
mcp = FastMCP("mcpizza")

class PizzaOrder:
    """Manages a pizza order state"""
    def __init__(self):
        self.store = None
        self.customer = None
        self.order = None
        self.items = []

# Global order state
pizza_order = PizzaOrder()


@mcp.tool()
def find_dominos_store(address: str) -> str:
    """
    Find the nearest Domino's store by address or zip code.
    
    Args:
        address: Full address or zip code to search near
    
    Returns:
        Store information including ID, phone, address, and wait times
    """
    try:
        logger.info(f"Finding store for address: {address}")
        
        # Find nearest store
        my_local_dominos = StoreLocator.find_closest_store_to_customer(address)
        
        if not my_local_dominos:
            return "No Domino's stores found near that address."
        
        # Store the found store globally for use in other tools
        pizza_order.store = my_local_dominos
        
        store_info = {
            "store_id": my_local_dominos.data.get("StoreID"),
            "phone": my_local_dominos.data.get("Phone"),
            "address": f"{my_local_dominos.data.get('StreetName', '')} {my_local_dominos.data.get('City', '')}",
            "is_delivery_store": my_local_dominos.data.get("IsDeliveryStore"),
            "min_delivery_order_amount": my_local_dominos.data.get("MinDeliveryOrderAmount"),
            "delivery_minutes": my_local_dominos.data.get("ServiceEstimatedWaitMinutes", {}).get("Delivery"),
            "pickup_minutes": my_local_dominos.data.get("ServiceEstimatedWaitMinutes", {}).get("Carryout")
        }
        
        logger.info(f"Found store: {store_info['store_id']}")
        return f"Found Domino's store:\n{json.dumps(store_info, indent=2)}"
        
    except Exception as e:
        logger.error(f"Error finding store: {e}")
        return f"Error finding store: {str(e)}"


@mcp.tool()
def get_store_menu() -> str:
    """
    Get the full menu categories from the selected Domino's store.
    Must call find_dominos_store first.
    
    Returns:
        List of available menu categories
    """
    try:
        if not pizza_order.store:
            return "No store selected. Use find_dominos_store first."
        
        menu = pizza_order.store.get_menu()
        
        # Extract useful menu categories
        categories = {}
        for category_name, items in menu.data.items():
            if isinstance(items, dict) and "Products" in items:
                products = []
                for product_code, product_data in items["Products"].items():
                    if isinstance(product_data, dict):
                        products.append({
                            "code": product_code,
                            "name": product_data.get("Name", ""),
                            "description": product_data.get("Description", ""),
                            "price": product_data.get("Price", "")
                        })
                categories[category_name] = products
        
        return f"Store menu categories:\n{json.dumps(list(categories.keys()), indent=2)}\n\nUse search_menu to find specific items."
        
    except Exception as e:
        logger.error(f"Error getting menu: {e}")
        return f"Error getting menu: {str(e)}"


@mcp.tool()
def search_menu(query: str) -> str:
    """
    Search for specific items in the store menu.
    Must call find_dominos_store first.
    
    Args:
        query: Search term (e.g., 'pepperoni pizza', 'wings', 'pasta')
    
    Returns:
        List of matching menu items with codes, names, descriptions, and prices
    """
    try:
        if not pizza_order.store:
            return "No store selected. Use find_dominos_store first."
        
        query_lower = query.lower()
        menu = pizza_order.store.get_menu()
        
        matching_items = []
        
        # Search through menu categories
        for category_name, items in menu.data.items():
            if isinstance(items, dict) and "Products" in items:
                for product_code, product_data in items["Products"].items():
                    if isinstance(product_data, dict):
                        name = product_data.get("Name", "").lower()
                        description = product_data.get("Description", "").lower()
                        
                        if query_lower in name or query_lower in description:
                            matching_items.append({
                                "category": category_name,
                                "code": product_code,
                                "name": product_data.get("Name", ""),
                                "description": product_data.get("Description", ""),
                                "price": product_data.get("Price", "")
                            })
        
        if not matching_items:
            return f"No items found matching '{query}'"
        
        logger.info(f"Found {len(matching_items)} items for query: {query}")
        return f"Found {len(matching_items)} items:\n{json.dumps(matching_items, indent=2)}"
        
    except Exception as e:
        logger.error(f"Error searching menu: {e}")
        return f"Error searching menu: {str(e)}"


@mcp.tool()
def add_to_order(item_code: str, quantity: int = 1, options: Optional[Dict[str, Any]] = None) -> str:
    """
    Add items to the pizza order.
    Must call find_dominos_store first.
    
    Args:
        item_code: Product code from menu search
        quantity: Number of items to add (default: 1)
        options: Item customization options (optional)
    
    Returns:
        Confirmation message
    """
    try:
        if not pizza_order.store:
            return "No store selected. Use find_dominos_store first."
        
        if not pizza_order.order:
            # Initialize order
            pizza_order.order = Order(pizza_order.store)
        
        if options is None:
            options = {}
        
        # Add item to order
        for _ in range(quantity):
            pizza_order.order.add_item(item_code, options)
        
        pizza_order.items.append({
            "code": item_code,
            "quantity": quantity,
            "options": options
        })
        
        logger.info(f"Added {quantity}x {item_code} to order")
        return f"Added {quantity}x {item_code} to order"
        
    except Exception as e:
        logger.error(f"Error adding item: {e}")
        return f"Error adding item: {str(e)}"


@mcp.tool()
def view_order() -> str:
    """
    View current order contents and details.
    
    Returns:
        Current order information
    """
    try:
        if not pizza_order.order:
            return "No items in order yet."
        
        order_data = pizza_order.order.data
        
        return f"Current order:\n{json.dumps(pizza_order.items, indent=2)}\n\nOrder data: {json.dumps(order_data, indent=2)}"
        
    except Exception as e:
        logger.error(f"Error viewing order: {e}")
        return f"Error viewing order: {str(e)}"


@mcp.tool()
def set_customer_info(
    first_name: str,
    last_name: str,
    email: str,
    phone: str,
    street: str,
    city: str,
    region: str,
    zip_code: str
) -> str:
    """
    Set customer information for delivery.
    
    Args:
        first_name: Customer's first name
        last_name: Customer's last name
        email: Customer's email address
        phone: Customer's phone number
        street: Street address
        city: City
        region: State/region (e.g., 'TX', 'CA')
        zip_code: Postal/ZIP code
    
    Returns:
        Confirmation message
    """
    try:
        pizza_order.customer = Customer(
            first_name=first_name,
            last_name=last_name,
            email=email,
            phone=phone,
            address=Address(
                street=street,
                city=city,
                state=region,
                zip=zip_code
            )
        )
        
        logger.info(f"Set customer info for {first_name} {last_name}")
        return "Customer information set successfully"
        
    except Exception as e:
        logger.error(f"Error setting customer info: {e}")
        return f"Error setting customer info: {str(e)}"


@mcp.tool()
def calculate_order_total() -> str:
    """
    Calculate order total with tax and delivery fees.
    
    Returns:
        Order pricing breakdown
    """
    try:
        if not pizza_order.order:
            return "No order to calculate."
        
        if pizza_order.customer:
            pizza_order.order.set_customer(pizza_order.customer)
        
        # Get order pricing
        order_data = pizza_order.order.data
        
        return f"Order total calculation:\n{json.dumps(order_data.get('Amounts', {}), indent=2)}"
        
    except Exception as e:
        logger.error(f"Error calculating total: {e}")
        return f"Error calculating total: {str(e)}"


@mcp.tool()
def apply_coupon(coupon_code: str) -> str:
    """
    Apply a coupon code to the order.
    
    Args:
        coupon_code: Domino's coupon code
    
    Returns:
        Confirmation message
    """
    try:
        if not pizza_order.order:
            return "No order to apply coupon to."
        
        # Apply coupon
        pizza_order.order.add_coupon(coupon_code)
        
        logger.info(f"Applied coupon: {coupon_code}")
        return f"Applied coupon: {coupon_code}"
        
    except Exception as e:
        logger.error(f"Error applying coupon: {e}")
        return f"Error applying coupon: {str(e)}"


@mcp.tool()
def place_order(
    payment_type: str,
    card_number: Optional[str] = None,
    expiration: Optional[str] = None,
    cvv: Optional[str] = None,
    billing_zip: Optional[str] = None,
    tip_amount: float = 0.0
) -> str:
    """
    Place the pizza order (requires customer info and payment).
    NOTE: Actual order placement is disabled by default for safety.
    
    Args:
        payment_type: Payment method ('card' or 'cash')
        card_number: Credit card number (required for card payments)
        expiration: Card expiration in MMYY format (required for card payments)
        cvv: 3-digit security code (required for card payments)
        billing_zip: Billing zip code (required for card payments)
        tip_amount: Tip amount (default: 0.0)
    
    Returns:
        Order confirmation or error message
    """
    try:
        if not pizza_order.order:
            return "No order to place."
        
        if not pizza_order.customer:
            return "Customer information required. Use set_customer_info first."
        
        # Set customer info on order
        pizza_order.order.set_customer(pizza_order.customer)
        
        # Handle payment based on type
        if payment_type == "cash":
            # For cash orders, just validate and prepare
            result = {
                "Status": "Success",
                "OrderID": "CASH_ORDER_PREVIEW",
                "Message": "Cash order prepared (PREVIEW MODE - not actually placed)"
            }
            
        elif payment_type == "card":
            # Validate required card fields
            if not all([card_number, expiration, cvv, billing_zip]):
                return "Missing required card information: card_number, expiration, cvv, billing_zip"
            
            # Return preview instead of actually placing order (safety feature)
            result = {
                "Status": "Success",
                "OrderID": "CARD_ORDER_PREVIEW",
                "Message": "Card order prepared (PREVIEW MODE - not actually placed)"
            }
            
            # Uncomment below to actually place orders (USE AT YOUR OWN RISK!)
            # card = PaymentObject(
            #     number=card_number,
            #     expiration=expiration,
            #     cvv=cvv,
            #     zip=billing_zip
            # )
            # if tip_amount > 0:
            #     pizza_order.order.add_item({'Code': 'DELIVERY_TIP', 'Qty': 1, 'Price': tip_amount})
            # result = pizza_order.order.place(card)
            
        else:
            return "Invalid payment type. Must be 'card' or 'cash'."
        
        # Format success response
        if isinstance(result, dict) and result.get("Status") == "Success":
            order_id = result.get("OrderID", "Unknown")
            message = result.get("Message", "")
            logger.info(f"Order preview created: {order_id}")
            return f"🍕 Order Preview:\n\nOrder ID: {order_id}\nPayment: {payment_type}\n\n{message}\n\n⚠️ SAFETY MODE: This is a preview only. Real order placement is disabled."
        else:
            return f"Order preparation failed: {result}"
        
    except Exception as e:
        logger.error(f"Error preparing order: {e}")
        return f"Error preparing order: {str(e)}"


if __name__ == "__main__":
    # Run the server
    logger.info("Starting MCPizza server...")
    mcp.run()