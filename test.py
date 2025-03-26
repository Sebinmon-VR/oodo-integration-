import xmlrpc.client
import sys
import socket

# Odoo server details
url = "http://15.207.36.252/"  # Your Odoo server URL
username = ""
password =  # Default password is the same as the username

# Set timeout for connections to avoid hanging
socket.setdefaulttimeout(15)  # 15 seconds timeout

def test_connection(url):
    try:
        common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common', allow_none=True)
        # Simple version call that should work if server is reachable
        version = common.version()
        print(f"Connection successful. Server info: {version['server_version']}")
        return True
    except Exception as e:
        print(f"Connection test failed: {e}")
        return False

def list_databases(url):
    try:
        # Connect to the database service
        db = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/db')
        # List available databases
        databases = db.list()
        print("Available databases:")
        for i, database in enumerate(databases, 1):
            print(f"{i}. {database}")
        return databases
    except Exception as e:
        print(f"Failed to fetch databases: {e}")
        return []

def fetch_all_models(models, dbname, uid, password):
    """Fetch all available models/tables from the database"""
    try:
        # First, check available fields for ir.model to avoid errors
        fields_info = models.execute_kw(dbname, uid, password, 
                                       'ir.model', 'fields_get', [], 
                                       {'attributes': ['string', 'type']})
        
        print(f"Retrieved {len(fields_info)} fields for ir.model")
        
        # Use only fields that exist - 'description' is missing in this Odoo version
        safe_fields = ['name', 'model']
        if 'info' in fields_info:
            safe_fields.append('info')
        elif 'description' in fields_info:
            safe_fields.append('description')
        
        # Get all models from ir.model
        model_ids = models.execute_kw(dbname, uid, password, 
                                      'ir.model', 'search', [[]])
        
        model_data = models.execute_kw(dbname, uid, password, 
                                       'ir.model', 'read', [model_ids], 
                                       {'fields': safe_fields})
        
        print(f"\nFound {len(model_data)} models/tables in the database '{dbname}':")
        print("=" * 80)
        header = f"{'MODEL NAME':<40} {'TECHNICAL NAME':<40}"
        print(header)
        print("-" * 80)
        
        # Sort models by name for better readability
        for model in sorted(model_data, key=lambda m: m['name']):
            print(f"{model['name']:<40} {model['model']:<40}")
        
        return model_data
    except xmlrpc.client.Fault as e:
        print(f"Error fetching models: {e}")
        # Let's add a more specific troubleshooting suggestion for this error
        if "Invalid field 'description'" in str(e):
            print("Troubleshooting: The 'description' field doesn't exist in this Odoo version.")
        return []

def fetch_products(models, dbname, uid, password, limit=100):
    """Fetch products from the database with all available fields"""
    try:
        # Check if product.template model exists
        model_ids = models.execute_kw(dbname, uid, password, 
                                    'ir.model', 'search', 
                                    [[['model', '=', 'product.template']]])
        
        if not model_ids:
            print("Product model not found in this database.")
            return []
            
        # Get all available fields for product.template
        fields_info = models.execute_kw(dbname, uid, password, 
                                       'product.template', 'fields_get', [], 
                                       {'attributes': ['string', 'type', 'help']})
        
        print(f"Retrieved {len(fields_info)} fields for product.template")
                
        # Get product count first
        product_count = models.execute_kw(dbname, uid, password,
                                         'product.template', 'search_count',
                                         [[]])
        
        print(f"Total products in database: {product_count}")
        
        # Ask user for limit if there are many products
        if product_count > limit:
            try:
                user_limit = input(f"There are {product_count} products. How many would you like to display? [default={limit}]: ")
                if user_limit.strip():
                    limit = int(user_limit)
            except ValueError:
                print(f"Using default limit of {limit}")
        
        # Get product IDs
        product_ids = models.execute_kw(dbname, uid, password,
                                       'product.template', 'search',
                                       [[]], {'limit': limit})
        
        # Get all product data with all fields
        products = models.execute_kw(dbname, uid, password,
                                    'product.template', 'read',
                                    [product_ids])
        
        if not products:
            print("No products found.")
            return []
            
        print(f"\nFound {len(products)} products in database '{dbname}'.")
        
        # Display all product data with all fields
        for i, product in enumerate(products, 1):
            print(f"\nProduct {i}/{len(products)}: {product.get('name', 'Unnamed')}")
            print("=" * 80)
            
            # Sort fields alphabetically for easier reading
            for field_name in sorted(product.keys()):
                # Get field description if available
                field_desc = fields_info.get(field_name, {}).get('string', field_name)
                value = product[field_name]
                
                # Format the value based on its type
                if isinstance(value, tuple) and len(value) == 2:
                    # Typically (id, name) tuples
                    value = f"{value[1]} (ID: {value[0]})"
                elif isinstance(value, list) and all(isinstance(item, tuple) and len(item) == 2 for item in value):
                    # List of (id, name) tuples
                    value = ", ".join([f"{item[1]}" for item in value])
                elif value is False:
                    value = "No"
                elif value is True:
                    value = "Yes"
                
                print(f"{field_desc:<25}: {value}")
            
            if i < len(products):
                print("\n" + "-" * 80)  # Separator between products
                
            # Ask to continue after each product if there are many
            if i < len(products) and i % 3 == 0:
                if input("Press Enter to continue or 'q' to stop displaying: ").lower() == 'q':
                    print(f"Stopped after displaying {i} of {len(products)} products.")
                    break
                    
        return products
    except xmlrpc.client.Fault as e:
        print(f"Error fetching products: {e}")
        return []

try:
    # First test if we can connect to the server
    if not test_connection(url):
        print("Please check if the server URL is correct and the server is running.")
        sys.exit(1)
    
    # List available databases
    databases = list_databases(url)
    if not databases:
        print("No databases found or couldn't retrieve database list.")
        sys.exit(1)
    
    # Select database
    if len(databases) == 1:
        dbname = databases[0]
        print(f"Using the only available database: {dbname}")
    else:
        while True:
            choice = input("Enter the number of the database to use (or 'q' to quit): ")
            if choice.lower() == 'q':
                sys.exit(0)
            try:
                index = int(choice) - 1
                if 0 <= index < len(databases):
                    dbname = databases[index]
                    break
                else:
                    print(f"Please enter a number between 1 and {len(databases)}")
            except ValueError:
                print("Please enter a valid number")
    
    print(f"Using database: {dbname}")
    
    # Authenticate
    common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common', allow_none=True)
    uid = common.authenticate(dbname, username, password, {})

    if uid:
        print(f"Authenticated successfully with UID: {uid}")
        
        # Create object proxy for executing methods
        models = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object', allow_none=True)
        
        try:
            # Menu for actions
            while True:
                print("\nChoose an action:")
                print("1. List partners (sample)")
                print("2. Show all models/tables in the database")
                print("3. List products")  # New option
                print("q. Quit")
                
                action = input("Enter your choice: ")
                
                if action.lower() == 'q':
                    print("Exiting program.")
                    break
                elif action == '1':
                    # Example: Fetch list of partners
                    partners = models.execute_kw(dbname, uid, password, 'res.partner', 'search_read', 
                                                [[]], {'fields': ['name', 'email'], 'limit': 5})
                    
                    print(f"\nPartners in database '{dbname}':")
                    for partner in partners:
                        print(partner)
                elif action == '2':
                    # Fetch and display all models
                    fetch_all_models(models, dbname, uid, password)
                elif action == '3':
                    # Fetch and display products
                    fetch_products(models, dbname, uid, password)
                else:
                    print("Invalid choice. Please try again.")
                    
        except xmlrpc.client.Fault as e:
            print(f"Error executing API call: {e}")
    else:
        print("Authentication failed! Check your credentials.")
except socket.timeout:
    print("Connection timed out. The server took too long to respond.")
    print("Solutions: 1) Check if the URL is correct, 2) Verify the server is running, 3) Check network connectivity")
except xmlrpc.client.Fault as e:
    print(f"XMLRPC Fault: {e}")
except ConnectionRefusedError:
    print("Connection refused. Check if the Odoo server is running and the URL is correct.")
    print("The server might be down or blocked by a firewall.")
except Exception as e:
    print(f"Unexpected error: {e}")
    print("Try using a different URL format or check if you need to use HTTPS instead of HTTP.")
    sys.exit(1)
