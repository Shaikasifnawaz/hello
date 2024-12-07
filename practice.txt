import os
import requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from docx import Document
import re
from flask_cors import CORS
from pymongo import MongoClient
import uuid
from datetime import datetime

# Load environment variables
load_dotenv()

# Set up the Flask app
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": ["http://localhost:3000", "https://asci.meanhost.in"]}})

# Get the XAI API key from the environment variables
XAI_API_KEY = os.getenv("XAI_API_KEY")
MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME")
COLLECTION_NAME = os.getenv("COLLECTION_NAME")

# Set a file size limit for uploads (16MB limit)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB

# MongoDB connection setup
client = MongoClient(MONGO_URI)
db = client[DB_NAME]
collection = db[COLLECTION_NAME]

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

# New GET endpoint to retrieve messages based on conversationId
@app.route('/conversation/<conversation_id>', methods=['GET'])
def get_conversation(conversation_id):
    # Fetch the conversation from MongoDB based on conversationId
    conversation = collection.find_one({"conversationId": conversation_id})
    
    if conversation:
        messages = conversation.get("messages", [])
        title = conversation.get("title", "Untitled Conversation")
        return jsonify({"title": title, "messages": messages}), 200
    else:
        return jsonify({"error": "Conversation not found"}), 404


# Chat endpoint (POST method)
@app.route('/chat', methods=['POST'])
def chat():
    user_message = request.json.get('message')
    conversation_id = request.json.get('conversationId', str(uuid.uuid4()))  # Use existing or create new
    title = request.json.get('title', None)  # Optional title from user

    if not user_message:
        return jsonify({"error": "No message provided"}), 400

    # Set conversation title if not provided
    if title is None:
        title = user_message[:50]  # Default title as the first 50 characters of the user's message

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

            # Store both user and bot messages in the conversation
            collection.update_one(
                {"conversationId": conversation_id},
                {"$push": {"messages": {"role": "user", "content": user_message, "timestamp": datetime.now()}}},
                upsert=True
            )
            collection.update_one(
                {"conversationId": conversation_id},
                {"$push": {"messages": {"role": "assistant", "content": response_text, "timestamp": datetime.now()}}},
                upsert=True
            )

            # Store title if it's the first message
            collection.update_one(
                {"conversationId": conversation_id},
                {"$set": {"title": title}},
                upsert=True
            )

            # Return the HTML or table response
            html_response = get_html(response_text)

            return jsonify({"response": html_response, "messages": [{"role": "user", "content": user_message}, {"role": "assistant", "content": response_text}]})

        else:
            return jsonify({"error": "API request failed"}), 500

    except requests.exceptions.RequestException as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=True)
