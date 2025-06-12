import xmlrpc.client
import socket
import os
import json
import openai
import datetime
import requests
from getpass import getpass
from tabulate import tabulate
import pkg_resources
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration from environment variables
ODOO_URL = os.getenv("ODOO_URL", "http://localhost:8069/")
ODOO_DB = os.getenv("ODOO_DB")
ODOO_USERNAME = os.getenv("ODOO_USERNAME", "admin")
ODOO_PASSWORD = os.getenv("ODOO_PASSWORD")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Set timeout for connections
socket.setdefaulttimeout(15)

# Check OpenAI version to use the appropriate API call
try:
    OPENAI_VERSION = pkg_resources.get_distribution("openai").version
    IS_NEW_OPENAI = int(OPENAI_VERSION.split('.')[0]) >= 1
except:
    IS_NEW_OPENAI = False

class OdooIntegration:
    def __init__(self):
        self.uid = None
        self.models = None
        self.currency_rates = {}
        self.base_currency = "USD"

        # OpenAI configuration
        if OPENAI_API_KEY:
            openai.api_key = OPENAI_API_KEY
        else:
            print("Warning: OPENAI_API_KEY not found in environment variables")

    def connect_to_odoo(self):
        """Connect to the Odoo server and authenticate."""
        try:
            common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
            self.uid = common.authenticate(ODOO_DB, ODOO_USERNAME, ODOO_PASSWORD, {})
            if self.uid:
                self.models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")
                print("Connected to Odoo successfully.")
                return True
            else:
                print("Failed to authenticate with Odoo.")
                return False
        except Exception as e:
            print(f"Error connecting to Odoo: {e}")
            return False

    def get_exchange_rate(self, from_currency, to_currency):
        """Get exchange rate between currencies"""
        if from_currency == to_currency:
            return 1.0
            
        # Check cache first
        cache_key = f"{from_currency}_to_{to_currency}"
        if cache_key in self.currency_rates:
            return self.currency_rates[cache_key]
        
        try:
            # Try to get from Odoo first
            if self.models:
                currency_from = self.models.execute_kw(
                    ODOO_DB, self.uid, ODOO_PASSWORD,
                    "res.currency", "search_read",
                    [[["name", "=", from_currency]]],
                    {"fields": ["rate"], "limit": 1}
                )
                
                currency_to = self.models.execute_kw(
                    ODOO_DB, self.uid, ODOO_PASSWORD,
                    "res.currency", "search_read",
                    [[["name", "=", to_currency]]],
                    {"fields": ["rate"], "limit": 1}
                )
                
                if currency_from and currency_to:
                    rate = currency_to[0]["rate"] / currency_from[0]["rate"]
                    self.currency_rates[cache_key] = rate
                    return rate
            
            # Fallback to exchange rate API
            try:
                response = requests.get(f"https://api.exchangerate-api.com/v4/latest/{from_currency}", timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    if to_currency in data["rates"]:
                        rate = data["rates"][to_currency]
                        self.currency_rates[cache_key] = rate
                        return rate
            except:
                pass
            
            # Default fallback rates for common currencies
            fallback_rates = {
                "USD_to_EUR": 0.85,
                "EUR_to_USD": 1.18,
                "USD_to_GBP": 0.73,
                "GBP_to_USD": 1.37,
                "USD_to_INR": 83.0,
                "INR_to_USD": 0.012
            }
            
            if cache_key in fallback_rates:
                rate = fallback_rates[cache_key]
                self.currency_rates[cache_key] = rate
                return rate
                
        except Exception as e:
            print(f"Error getting exchange rate: {e}")
        
        # Return 1.0 as fallback
        return 1.0

    def get_vendor_currency(self, vendor_id):
        """Get vendor's preferred currency"""
        if not vendor_id or not self.models:
            return "USD"
            
        try:
            vendor_data = self.models.execute_kw(
                ODOO_DB, self.uid, ODOO_PASSWORD,
                "res.partner", "read",
                [vendor_id],
                {"fields": ["property_purchase_currency_id"]}
            )
            
            if vendor_data and vendor_data[0].get("property_purchase_currency_id"):
                currency_id = vendor_data[0]["property_purchase_currency_id"][0]
                currency_data = self.models.execute_kw(
                    ODOO_DB, self.uid, ODOO_PASSWORD,
                    "res.currency", "read",
                    [currency_id],
                    {"fields": ["name"]}
                )
                return currency_data[0]["name"]
        except Exception as e:
            print(f"Error getting vendor currency: {e}")
        
        return "USD"

    def convert_price(self, price, from_currency, to_currency):
        """Convert price from one currency to another"""
        if from_currency == to_currency:
            return price
            
        rate = self.get_exchange_rate(from_currency, to_currency)
        return round(price * rate, 2)

    def parse_extracted_text(self, extracted_text):
        """Parse the extracted text to identify company, vendor, and product details."""
        try:
            prompt = f"""
            Parse this invoice/PO text and return ONLY valid JSON:
            {{
                "vendor": "company name",
                "invoice_number": "number if found",
                "date": "date if found", 
                "products": [
                    {{
                        "name": "product name",
                        "quantity": 1,
                        "price": 0.0,
                        "description": "description"
                    }}
                ],
                "total": 0.0,
                "currency": "USD"
            }}
            
            Text: {extracted_text[:1500]}
            """
            
            # Use the old OpenAI API format (compatible with openai==0.28)
            response = openai.ChatCompletion.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "Extract data and return only valid JSON, no other text."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=800
            )
            
            result_text = response["choices"][0]["message"]["content"].strip()
            
            # Clean and extract JSON
            import re
            # Remove markdown code blocks if present
            result_text = re.sub(r'```json\s*|\s*```', '', result_text)
            
            # Find JSON object
            json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
            if json_match:
                json_str = json_match.group()
                parsed_data = json.loads(json_str)
                return parsed_data
            else:
                print("No valid JSON found in response")
                return None
                
        except Exception as e:
            print(f"Error parsing extracted text: {e}")
            # Return a default structure if parsing fails
            return {
                "vendor": "Unknown Vendor",
                "invoice_number": "",
                "date": "",
                "products": [
                    {
                        "name": "Sample Product",
                        "quantity": 1,
                        "price": 0.0,
                        "description": "Extracted from document"
                    }
                ],
                "total": 0.0,
                "currency": "USD"
            }

    def validate_data(self, parsed_data):
        """Validate the parsed data against the Odoo database."""
        if not parsed_data:
            return None
            
        try:
            # Validate vendor
            vendor_name = parsed_data.get("vendor", "").strip()
            vendor_id = None
            vendor_currency = "USD"
            
            if vendor_name and vendor_name != "Unknown Vendor":
                vendor_ids = self.models.execute_kw(
                    ODOO_DB, self.uid, ODOO_PASSWORD,
                    "res.partner", "search",
                    [[["name", "ilike", vendor_name], ["supplier_rank", ">", 0]]]
                )
                if vendor_ids:
                    vendor_id = vendor_ids[0]
                    vendor_currency = self.get_vendor_currency(vendor_id)
                    print(f"Found vendor: {vendor_name} (Currency: {vendor_currency})")
                else:
                    print(f"Vendor '{vendor_name}' not found. Will create new vendor.")

            # Get document currency
            document_currency = parsed_data.get("currency", "USD")
            
            # Get products from database
            products = parsed_data.get("products", [])
            validated_products = []
            
            # First, try to match products from the extracted text
            for product in products:
                product_name = product.get("name", "").strip()
                if not product_name or product_name == "Sample Product":
                    continue
                    
                # Try multiple search strategies
                search_terms = [
                    [["name", "ilike", product_name]],
                    [["name", "ilike", f"%{product_name}%"]],
                    [["default_code", "ilike", product_name]]
                ]
                
                found = False
                for search_term in search_terms:
                    if found:
                        break
                        
                    product_ids = self.models.execute_kw(
                        ODOO_DB, self.uid, ODOO_PASSWORD,
                        "product.product", "search",
                        [search_term],
                        {"limit": 5}
                    )
                    
                    if product_ids:
                        for product_id in product_ids:
                            product_data = self.models.execute_kw(
                                ODOO_DB, self.uid, ODOO_PASSWORD,
                                "product.product", "read",
                                [product_id],
                                {"fields": ["name", "list_price", "default_code"]}
                            )[0]
                            
                            # Convert price from document currency to vendor currency
                            original_price = float(product.get("price", product_data.get("list_price", 0)))
                            converted_price = self.convert_price(original_price, document_currency, vendor_currency)
                            
                            validated_products.append({
                                "id": product_id,
                                "name": product_data["name"],
                                "code": product_data.get("default_code", ""),
                                "quantity": float(product.get("quantity", 1)),
                                "price": converted_price,
                                "original_price": original_price,
                                "original_currency": document_currency
                            })
                            found = True
                        
                        print(f"Found {len(product_ids)} products matching: {product_name}")
                        break

            # If no products found from text, get sample products from database
            if not validated_products:
                print("No products matched from extracted text. Getting sample products from database...")
                sample_product_ids = self.models.execute_kw(
                    ODOO_DB, self.uid, ODOO_PASSWORD,
                    "product.product", "search",
                    [[["sale_ok", "=", True], ["active", "=", True]]],
                    {"limit": 10}
                )
                
                for product_id in sample_product_ids:
                    product_data = self.models.execute_kw(
                        ODOO_DB, self.uid, ODOO_PASSWORD,
                        "product.product", "read",
                        [product_id],
                        {"fields": ["name", "list_price", "default_code"]}
                    )[0]
                    
                    # Convert price from base currency to vendor currency
                    original_price = float(product_data.get("list_price", 0.0))
                    converted_price = self.convert_price(original_price, self.base_currency, vendor_currency)
                    
                    validated_products.append({
                        "id": product_id,
                        "name": product_data["name"],
                        "code": product_data.get("default_code", ""),
                        "quantity": 1.0,
                        "price": converted_price,
                        "original_price": original_price,
                        "original_currency": self.base_currency
                    })

            print(f"Total validated products: {len(validated_products)}")

            # Return validated data
            return {
                "vendor_id": vendor_id,
                "vendor_name": vendor_name or "New Vendor",
                "vendor_currency": vendor_currency,
                "products": validated_products,
                "invoice_number": parsed_data.get("invoice_number", ""),
                "date": parsed_data.get("date", ""),
                "total": self.convert_price(parsed_data.get("total", 0), document_currency, vendor_currency),
                "currency": vendor_currency,
                "original_currency": document_currency,
                "exchange_rate": self.get_exchange_rate(document_currency, vendor_currency)
            }
            
        except Exception as e:
            print(f"Error validating data: {e}")
            import traceback
            traceback.print_exc()
            return None

    def create_po_or_invoice(self, validated_data, create_type="po"):
        """Create a Purchase Order or Invoice in Odoo."""
        try:
            print(f"Starting to create {create_type}...")
            
            if not validated_data.get("products"):
                print("No products to create order with")
                return False
                
            # Create or get vendor
            vendor_id = validated_data.get("vendor_id")
            if not vendor_id:
                print("Creating new vendor...")
                # Create a new vendor
                vendor_data = {
                    "name": validated_data.get("vendor_name", "New Vendor"),
                    "is_company": True,
                    "supplier_rank": 1,
                    "customer_rank": 0
                }
                vendor_id = self.models.execute_kw(
                    ODOO_DB, self.uid, ODOO_PASSWORD,
                    "res.partner", "create",
                    [vendor_data]
                )
                print(f"Created new vendor with ID: {vendor_id}")

            if create_type == "po":
                print("Creating Purchase Order...")
                # Create a Purchase Order
                order_lines = []
                for product in validated_data["products"]:
                    # Get product template ID for purchase order
                    product_template_id = self.models.execute_kw(
                        ODOO_DB, self.uid, ODOO_PASSWORD,
                        "product.product", "read",
                        [product["id"]],
                        {"fields": ["product_tmpl_id"]}
                    )[0]["product_tmpl_id"][0]
                    
                    order_lines.append((0, 0, {
                        "product_id": product["id"],
                        "product_qty": product["quantity"],
                        "price_unit": product.get("price", 0.0),
                        "name": product.get("name", "Product")
                    }))
                
                po_data = {
                    "partner_id": vendor_id,
                    "order_line": order_lines,
                    "state": "draft"
                }
                
                print(f"Creating PO with data: {po_data}")
                
                po_id = self.models.execute_kw(
                    ODOO_DB, self.uid, ODOO_PASSWORD,
                    "purchase.order", "create",
                    [po_data]
                )
                print(f"Purchase Order created with ID: {po_id}")
                return po_id
                
            elif create_type == "invoice":
                print("Creating Invoice...")
                # Create an Invoice
                invoice_lines = []
                for product in validated_data["products"]:
                    invoice_lines.append((0, 0, {
                        "product_id": product["id"],
                        "quantity": product["quantity"],
                        "price_unit": product.get("price", 0.0),
                        "name": product.get("name", "Product")
                    }))
                
                invoice_data = {
                    "move_type": "in_invoice",
                    "partner_id": vendor_id,
                    "invoice_line_ids": invoice_lines,
                    "state": "draft"
                }
                
                print(f"Creating invoice with data: {invoice_data}")
                
                invoice_id = self.models.execute_kw(
                    ODOO_DB, self.uid, ODOO_PASSWORD,
                    "account.move", "create",
                    [invoice_data]
                )
                print(f"Invoice created with ID: {invoice_id}")
                return invoice_id
                
        except Exception as e:
            print(f"Error creating {create_type}: {e}")
            import traceback
            traceback.print_exc()
            return False

def main():
    extracted_text = input("Enter the extracted text: ")
    odoo_integration = OdooIntegration()

    if not odoo_integration.connect_to_odoo():
        return

    parsed_data = odoo_integration.parse_extracted_text(extracted_text)
    if not parsed_data:
        print("Failed to parse extracted text.")
        return

    validated_data = odoo_integration.validate_data(parsed_data)
    if not validated_data:
        print("Failed to validate data.")
        return

    create_type = input("Enter 'po' to create a Purchase Order or 'invoice' to create an Invoice: ").strip().lower()
    if create_type not in ["po", "invoice"]:
        print("Invalid choice.")
        return

    odoo_integration.create_po_or_invoice(validated_data, create_type)

if __name__ == "__main__":
    main()

