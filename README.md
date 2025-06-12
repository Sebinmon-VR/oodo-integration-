# Flask Image Text Extractor

This is a Flask web application that extracts text from images using the OpenAI API.

## Features
- Upload an image to extract text.
- Supports PNG, JPG, and JPEG formats.

## Setup Instructions

1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd oodo-integration-
   ```

2. Create a virtual environment and activate it:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Create a `.env` file and add your OpenAI API key:
   ```plaintext
   OPENAI_API_KEY=your-openai-api-key
   ```

5. Run the application:
   ```bash
   python app.py
   ```

6. Access the app at `http://127.0.0.1:5000/`.

## Notes
- Replace `your-openai-api-key` in `.env` with your actual OpenAI API key.
- Ensure you have Python 3.7+ installed.
