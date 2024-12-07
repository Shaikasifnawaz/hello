import os
import requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from docx import Document
import re
from flask_cors import CORS

# Load environment variables
load_dotenv()

# Set up the Flask app
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": ["http://localhost:3000", "https://asci.meanhost.in"]}})

# Get the XAI API key from the environment variables
XAI_API_KEY = os.getenv("XAI_API_KEY")
# hi
# Set a file size limit for uploads (16MB limit)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB

# Function to extract text from a Word file in a memory-efficient manner
def extract_text_from_word(file_path):
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
    doc = Document(file_path)
    text = []
    for para in doc.paragraphs:
        text.append(para.text)
    return '\n'.join(text)

# Function to handle markdown-style links and emails
def handle_links(line):
    link_pattern = re.compile(r'\[(.*?)\]\((.*?)\)')
    line = link_pattern.sub(r'<a href="\2">\1</a>', line)

    url_pattern = re.compile(r'(http[s]?://[^\s]+)')
    line = url_pattern.sub(r'<a href="\1">\1</a>', line)

    email_pattern = re.compile(r'(\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b)')
    line = email_pattern.sub(r'<a href="mailto:\1">\1</a>', line)

    return line

# Function to escape HTML special characters
def escape_html(text):
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#039;"))

# Function to convert markdown-like text to HTML
def get_html(text: str, is_table: bool = False) -> str:
    lines = text.split('\n')
    html_output = """<div style="max-width: 1000px; padding: 15px; margin: 0 auto; height: 100%; display: flex; flex-direction: column; justify-content: center; overflow-x: auto;">"""
    
    list_open = False
    table_open = False
    for line in lines:
        line = line.strip()
        if not line:
            continue  # Skip blank lines

        # Handle markdown tables
        if "|" in line:
            if not table_open:
                html_output += "<table style='border-collapse: collapse; width: 100%;'>"  # Start table
                table_open = True

            # Detect table header (usually separated by dashes)
            if "-" in line:
                headers = line.split("|")
                html_output += "<tr>"
                for header in headers:
                    html_output += f"<th style='border: 1px solid black; padding: 5px; text-align: left;'>{escape_html(header.strip())}</th>"
                html_output += "</tr>"
            else:
                cells = line.split("|")
                html_output += "<tr>"
                for cell in cells:
                    cell_content = cell.strip()
                    if cell_content:
                        html_output += f"<td style='border: 1px solid black; padding: 5px;'>{escape_html(cell_content)}</td>"
                html_output += "</tr>"

        # Handle headings
        elif line.startswith("# "):  # <h2> for # headings
            html_output += f'<h2>{escape_html(line[2:])}</h2>'
        elif line.startswith("## "):  # <h3> for ## headings
            html_output += f'<h3>{escape_html(line[3:])}</h3>'
        elif line.startswith("### "):  # <h4> for ### headings
            html_output += f'<h4>{escape_html(line[4:])}</h4>'
        elif line.startswith("#### "):  # <h5> for #### headings
            html_output += f'<h5>{escape_html(line[5:])}</h5>'
        elif line.startswith("##### "):  # <h6> for ##### headings
            html_output += f'<h6>{escape_html(line[6:])}</h6>'

        # Handle bold text
        elif line.startswith("**") and line.endswith("**"):
            html_output += f'<strong>{escape_html(line[2:-2])}</strong>'
        
        # Handle unordered lists
        elif line.startswith("* "):
            if not list_open:
                html_output += '<ul>'
                list_open = True
            html_output += f'<li>{escape_html(line[2:])}</li>'
        
        # Handle other content (regular paragraphs)
        else:
            if list_open:
                html_output += '</ul>'
                list_open = False

            line = handle_links(escape_html(line))
            html_output += f'<p style="margin-bottom: 10px;">{line}</p>'

    # Close the table if open
    if table_open:
        html_output += "</table>"

    html_output += '</div>'
    return html_output

# Function to generate the system prompt
def generate_system_prompt(user_query, relevant_text):
    return f"""
    You are a knowledgeable assistant. Your role is to provide accurate and concise responses based only on the information in the provided documents. 

    User's Question: "{user_query}"

    Relevant Context from Documents:
    {relevant_text}

    Answer the user's question in a professional tone, using no more than 500 words. Do not include any information that is not found in the documents.
    """

# Function to extract table data from the bot's response and format as HTML table
def extract_table_from_response(response_text):
    table_data = []
    
    # Split the response text by lines and look for potential table rows
    lines = response_text.split('\n')
    headers = None
    for line in lines:
        # Check for table-like data based on delimiters like "|"
        if "|" in line:
            row = [cell.strip() for cell in line.split("|") if cell.strip()]
            if len(row) > 1:  # Skip invalid rows (empty or single column)
                if not headers:
                    headers = row
                else:
                    table_data.append(row)

    return headers, table_data

# Chat endpoint
@app.route('/chat', methods=['POST'])
def chat():
    user_message = request.json.get('message')

    if not user_message:
        return jsonify({"error": "No message provided"}), 400

    # Extract content from Word files
    try:
        word_file_1 = './AMRUT-Operational-Guidelines.docx'
        content_1 = extract_text_from_word(word_file_1)
        relevant_text = content_1 + "\n"
    except FileNotFoundError as fnfe:
        return jsonify({"error": str(fnfe)}), 404
    except Exception as e:
        return jsonify({"error": f"Error extracting text from Word files: {str(e)}"}), 500

    # Generate the system prompt
    system_prompt = generate_system_prompt(user_message, relevant_text)

    # Define the API URL
    api_url = "https://api.x.ai/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {XAI_API_KEY}",
    }

    # Define the payload for the API request
    payload = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ],
        "model": "grok-beta",
        "stream": False,
        "temperature": 0
    }

    try:
        # Make the POST request to the external API
        response = requests.post(api_url, json=payload, headers=headers)

        # Check if the request was successful
        if response.status_code == 200:
            chatbot_reply = response.json()
            response_text = chatbot_reply['choices'][0]['message']['content']

            # Extract table data from the response, if any
            headers, table_data = extract_table_from_response(response_text)

            # If table data is found, generate the table HTML
            if table_data:
                table_html = "<table style='border-collapse: collapse; width: 100%;'>"
                table_html += "<tr>"
                for header in headers:
                    table_html += f"<th style='border: 1px solid black; padding: 5px; text-align: left;'>{escape_html(header)}</th>"
                table_html += "</tr>"

                for row in table_data:
                    table_html += "<tr>"
                    for cell in row:
                        table_html += f"<td style='border: 1px solid black; padding: 5px;'>{escape_html(cell)}</td>"
                    table_html += "</tr>"
                table_html += "</table>"

                return jsonify({"response": table_html})

            # Render non-table response as HTML
            html_response = get_html(response_text)
            return jsonify({"response": html_response})

        else:
            return jsonify({"error": "API request failed"}), 500

    except requests.exceptions.RequestException as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=True)