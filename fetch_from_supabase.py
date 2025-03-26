from supabase import create_client, Client

# Supabase credentials
SUPABASE_URL = "https://nndoncmxmhhgvnidqbng.supabase.co"
SUPABASE_KEY = ""

# Create a Supabase client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Fetch data from a table (e.g., 'users')
response = supabase.table("PO_details").select("*").execute()

# Print the retrieved data
if response.data:
    print("Fetched Data:", response.data)
else:
    print("No data found or an error occurred:", response.error)
