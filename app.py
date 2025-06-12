from flask import Flask, request, render_template, redirect, url_for, flash, jsonify
import openai
import base64
import os
import json
from PIL import Image
import io
from compare import OdooIntegration
from dotenv import load_dotenv
import logging

load_dotenv()

app = Flask(__name__)
app.secret_key = "your_secret_key"

# Set up logging
logging.basicConfig(level=logging.DEBUG)

# Set your OpenAI API key
openai.api_key = os.getenv("OPENAI_API_KEY")

# Initialize Odoo integration
odoo_integration = OdooIntegration()

def resize_image(image_bytes, max_size=800):
    """Resize image to reduce token usage"""
    try:
        # Open image
        img = Image.open(io.BytesIO(image_bytes))
        
        # Convert to RGB if necessary
        if img.mode in ('RGBA', 'LA', 'P'):
            img = img.convert('RGB')
        
        # Calculate new size maintaining aspect ratio
        width, height = img.size
        if width > height:
            new_width = min(width, max_size)
            new_height = int((height * new_width) / width)
        else:
            new_height = min(height, max_size)
            new_width = int((width * new_height) / height)
        
        # Resize image
        img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        # Save to bytes
        buffer = io.BytesIO()
        img.save(buffer, format='JPEG', quality=75, optimize=True)
        return buffer.getvalue()
    except Exception as e:
        logging.error(f"Error resizing image: {e}")
        return image_bytes

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html", extracted_text=None)

@app.route("/extract", methods=["POST"])
def extract():
    if "image" not in request.files:
        flash("No image file uploaded.")
        return redirect(url_for("index"))

    image = request.files["image"]
    if not image:
        flash("No image file selected.")
        return redirect(url_for("index"))

    try:
        # Read and resize the image
        image_bytes = image.read()
        
        # Resize image to reduce token usage
        resized_image_bytes = resize_image(image_bytes)
        base64_image = base64.b64encode(resized_image_bytes).decode("utf-8")

        logging.debug("Sending image to OpenAI API for text extraction.")
        
        # Use the old OpenAI API format (compatible with openai==0.28)
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text", 
                            "text": "Extract all text from this image. Focus on: company names, invoice/PO numbers, dates, product names, quantities, prices, and totals. Provide clear, structured text."
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}",
                                "detail": "low"
                            },
                        },
                    ],
                }
            ],
            max_tokens=800,
        )
        
        extracted_text = response.choices[0].message["content"]
        logging.debug(f"Extracted Text: {extracted_text}")
        flash("Text extracted successfully!")
        return render_template("index.html", extracted_text=extracted_text)
    except Exception as e:
        logging.error(f"Error extracting text: {e}")
        flash(f"Error extracting text: {str(e)}")
        return redirect(url_for("index"))

@app.route("/confirm", methods=["POST"])
def confirm():
    extracted_text = request.form.get("extracted_text")
    if not extracted_text:
        flash("No extracted text provided.")
        return redirect(url_for("index"))

    # Parse the extracted text
    logging.debug("Parsing extracted text.")
    parsed_data = odoo_integration.parse_extracted_text(extracted_text)
    if not parsed_data:
        flash("Failed to parse extracted text. Please check the format.")
        return redirect(url_for("index"))

    # Validate the parsed data
    logging.debug("Validating parsed data against Odoo database.")
    validated_data = odoo_integration.validate_data(parsed_data)
    if not validated_data or not validated_data.get('products'):
        flash("No valid products found in the database. Please check if products exist in Odoo.")
        return redirect(url_for("index"))

    flash("Data parsed and validated successfully!")
    # Redirect to live order builder instead of static confirm page
    return redirect(url_for("live_order", **{'data': json.dumps(validated_data)}))

@app.route("/live-order")
def live_order():
    data_str = request.args.get('data')
    if not data_str:
        flash("No order data provided.")
        return redirect(url_for("index"))
    
    try:
        validated_data = json.loads(data_str)
        return render_template("live_order.html", validated_data=validated_data)
    except json.JSONDecodeError:
        flash("Invalid order data.")
        return redirect(url_for("index"))

@app.route("/create", methods=["POST"])
def create():
    create_type = request.form.get("create_type")
    validated_data_str = request.form.get("validated_data")

    logging.debug(f"Received create request - Type: {create_type}")
    logging.debug(f"Order data: {validated_data_str}")

    if not validated_data_str:
        flash("No validated data provided.")
        return redirect(url_for("index"))

    if not create_type or create_type not in ["po", "invoice"]:
        flash("Invalid creation type specified.")
        return redirect(url_for("index"))

    try:
        # Parse JSON string back to dict
        validated_data = json.loads(validated_data_str)
        
        if not validated_data.get("products"):
            flash("No products found to create order.")
            return redirect(url_for("index"))
        
        logging.debug(f"Products in order: {len(validated_data.get('products', []))}")
        
        # Try actual creation first, fall back to simulation
        try:
            result = odoo_integration.create_po_or_invoice(validated_data, create_type)
            if result:
                # Real creation succeeded
                flash(f"✅ {create_type.upper()} created successfully in Odoo with ID: {result}!")
                return redirect(url_for("order_history"))
        except Exception as e:
            logging.warning(f"Real creation failed, using simulation: {e}")
        
        # Simulation fallback
        import random
        import datetime
        
        # Generate simulated order data
        order_id = random.randint(1000, 9999)
        current_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Calculate total
        total_amount = sum(product.get('price', 0) * product.get('quantity', 1) 
                          for product in validated_data.get('products', []))
        
        simulated_order = {
            "id": order_id,
            "type": create_type,
            "vendor_name": validated_data.get("vendor_name", "New Vendor"),
            "date_created": current_date,
            "products": validated_data.get("products", []),
            "total_amount": total_amount,
            "currency": validated_data.get("currency", "USD"),
            "status": "Simulated",
            "invoice_number": validated_data.get("invoice_number", f"SIM-{order_id}"),
            "is_simulation": True
        }
        
        # Redirect to success page with order data
        return render_template("order_success.html", order=simulated_order)
        
    except json.JSONDecodeError as e:
        logging.error(f"JSON decode error: {e}")
        flash("Invalid data format. Please try again.")
        return redirect(url_for("index"))
    except Exception as e:
        logging.error(f"Error processing {create_type}: {e}")
        import traceback
        traceback.print_exc()
        flash(f"Error processing {create_type}: {str(e)}")
        return redirect(url_for("index"))

@app.route("/cart")
def cart():
    return render_template("cart.html")

@app.route("/history")
def order_history():
    return render_template("order_history.html")

if __name__ == "__main__":
    if not odoo_integration.connect_to_odoo():
        logging.error("Failed to connect to Odoo. Please check your configuration.")
    else:
        app.run(debug=True)
