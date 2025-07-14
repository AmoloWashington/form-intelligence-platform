import streamlit as st
import json
import os
import pandas as pd
from datetime import datetime
import requests
from openai import OpenAI
import traceback
from pathlib import Path
import xlsxwriter
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
import io
import base64

# Initialize APIs
def init_apis():
    """Initialize OpenAI and Tavily APIs"""
    try:
        # Initialize OpenAI client (new v1+ API)
        openai_client = OpenAI(
            api_key=st.secrets.get("openai_api_key") or os.getenv("OPENAI_API_KEY")
        )
        
        # Tavily API key
        tavily_api_key = st.secrets.get("tavily_api_key") or os.getenv("TAVILY_API_KEY")
        
        return openai_client, tavily_api_key
    except Exception as e:
        st.error(f"Failed to initialize APIs: {str(e)}")
        return None, None

# Define the comprehensive JSON schema for form metadata
FORM_SCHEMA = {
    "form_name": "",
    "form_id": "",
    "description": "",
    "governing_authority": "",
    "target_users": "",
    "required_fields": [],
    "supporting_documents": [],
    "submission_method": "",
    "frequency_or_deadline": "",
    "official_source_url": "",
    "notes_or_instructions": "",
    "created_at": "",
    "last_updated": "",
    "validation_status": "pending"
}

def ensure_directories():
    """Create necessary directories if they don't exist"""
    directories = [
        "data/forms",
        "data/logs",
        "data/exports/excel",
        "data/exports/pdf"
    ]
    
    for directory in directories:
        Path(directory).mkdir(parents=True, exist_ok=True)

def query_tavily_api(form_name, tavily_api_key):
    """Query Tavily API for form information"""
    if not tavily_api_key:
        return {"error": "Tavily API key not found"}
    
    try:
        url = "https://api.tavily.com/search"
        
        # Craft a comprehensive search query
        query = f"""What are all the required fields, field types, supporting documents, official submission method,
                    governing authority, target users, and submission deadlines for the {form_name} form?
                    Include official source URLs and detailed instructions."""
        
        payload = {
            "api_key": tavily_api_key,
            "query": query,
            "search_depth": "advanced",
            "include_answer": True,
            "include_raw_content": False,
            "max_results": 10
        }
        
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        
        # Log the raw response
        log_tavily_response(form_name, data)
        
        return data
        
    except requests.exceptions.RequestException as e:
        return {"error": f"Tavily API request failed: {str(e)}"}
    except Exception as e:
        return {"error": f"Unexpected error: {str(e)}"}

def log_tavily_response(form_name, response_data):
    """Log Tavily API response for traceability"""
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = f"data/logs/tavily_{form_name.replace(' ', '_')}_{timestamp}.json"
        
        with open(log_file, 'w', encoding='utf-8') as f:
            json.dump(response_data, f, indent=2, ensure_ascii=False)
        
    except Exception as e:
        st.warning(f"Failed to log Tavily response: {str(e)}")

def extract_form_data(form_name, tavily_results, openai_client):
    """Use OpenAI to extract structured form data from Tavily results"""
    try:
        # Prepare the search results text
        search_text = ""
        
        if "results" in tavily_results:
            for result in tavily_results["results"]:
                search_text += f"Title: {result.get('title', '')}\n"
                search_text += f"Content: {result.get('content', '')}\n"
                search_text += f"URL: {result.get('url', '')}\n\n"
        
        if "answer" in tavily_results:
            search_text += f"Summary Answer: {tavily_results['answer']}\n\n"
        
        # Create the extraction prompt
        prompt = f"""
        You are a form intelligence expert. Extract comprehensive information about the "{form_name}" form from the search results below and structure it into a JSON object.

        CRITICAL REQUIREMENTS:
        1. ALWAYS include ALL fields from the schema, even if information is not available (use empty string "" or empty array [])
        2. For required_fields, each field must have: name, type, description, required (boolean)
        3. Be as comprehensive and detailed as possible
        4. Extract actual field names and types from the search results
        5. Include all supporting documents mentioned
        6. Capture submission methods and deadlines precisely

        JSON Schema to follow:
        {{
            "form_name": "string",
            "form_id": "string", 
            "description": "string",
            "governing_authority": "string",
            "target_users": "string",
            "required_fields": [
                {{
                    "name": "string",
                    "type": "string", 
                    "description": "string",
                    "required": boolean
                }}
            ],
            "supporting_documents": ["string"],
            "submission_method": "string",
            "frequency_or_deadline": "string",
            "official_source_url": "string",
            "notes_or_instructions": "string",
            "created_at": "{datetime.now().isoformat()}",
            "last_updated": "{datetime.now().isoformat()}",
            "validation_status": "extracted"
        }}

        Search Results:
        {search_text}

        Return ONLY the JSON object, no other text:
        """
        
        response = openai_client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a precise form intelligence extraction expert. Always return valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=2000
        )
        
        # Extract and parse the JSON response
        json_text = response.choices[0].message.content.strip()
        
        # Log the LLM response
        log_llm_response(form_name, "extraction", json_text)
        
        # Parse the JSON
        form_data = json.loads(json_text)
        
        # Ensure all required fields are present
        for key in FORM_SCHEMA:
            if key not in form_data:
                form_data[key] = FORM_SCHEMA[key]
        
        return form_data
        
    except json.JSONDecodeError as e:
        st.error(f"Failed to parse JSON from OpenAI response: {str(e)}")
        return create_empty_form_data(form_name)
    except Exception as e:
        st.error(f"Error extracting form data: {str(e)}")
        return create_empty_form_data(form_name)

def create_empty_form_data(form_name):
    """Create empty form data structure"""
    form_data = FORM_SCHEMA.copy()
    form_data["form_name"] = form_name
    form_data["created_at"] = datetime.now().isoformat()
    form_data["last_updated"] = datetime.now().isoformat()
    return form_data

def validate_form_data(form_data, openai_client):
    """Use OpenAI to validate and audit the form data"""
    try:
        prompt = f"""
        You are a form validation expert. Review the following form metadata and identify any issues:
        
        1. Missing or incomplete required information
        2. Incorrect field types or descriptions
        3. Missing supporting documents that should be included
        4. Unclear or incorrect submission methods
        5. Missing deadlines or frequency information
        6. Any other obvious errors or omissions
        
        Form Data:
        {json.dumps(form_data, indent=2)}
        
        Provide your analysis in the following JSON format:
        {{
            "validation_passed": boolean,
            "issues_found": [
                {{
                    "field": "field_name",
                    "issue": "description of the issue",
                    "severity": "high|medium|low",
                    "suggestion": "specific suggestion for fix"
                }}
            ],
            "overall_assessment": "string",
            "completeness_score": number (0-100)
        }}
        
        Return ONLY the JSON object:
        """
        
        response = openai_client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a thorough form validation expert. Always return valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=1000
        )
        
        validation_result = json.loads(response.choices[0].message.content.strip())
        
        # Log validation response
        log_llm_response(form_data["form_name"], "validation", response.choices[0].message.content)
        
        return validation_result
        
    except Exception as e:
        st.error(f"Error validating form data: {str(e)}")
        return {
            "validation_passed": False,
            "issues_found": [{"field": "system", "issue": f"Validation failed: {str(e)}", "severity": "high", "suggestion": "Manual review required"}],
            "overall_assessment": "Validation system error",
            "completeness_score": 0
        }

def log_llm_response(form_name, operation, response_text):
    """Log LLM responses for traceability"""
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = f"data/logs/llm_{operation}_{form_name.replace(' ', '_')}_{timestamp}.txt"
        
        with open(log_file, 'w', encoding='utf-8') as f:
            f.write(f"Operation: {operation}\n")
            f.write(f"Form: {form_name}\n")
            f.write(f"Timestamp: {timestamp}\n")
            f.write(f"Response:\n{response_text}\n")
        
    except Exception as e:
        st.warning(f"Failed to log LLM response: {str(e)}")

def save_form_data(form_data):
    """Save form data to JSON file"""
    try:
        form_id = form_data.get("form_id", "").replace(" ", "_").replace("/", "_")
        if not form_id:
            form_id = form_data.get("form_name", "unknown").replace(" ", "_").replace("/", "_")
        
        filename = f"data/forms/{form_id}.json"
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(form_data, f, indent=2, ensure_ascii=False)
        
        return filename
        
    except Exception as e:
        st.error(f"Failed to save form data: {str(e)}")
        return None

def export_to_excel(form_data):
    """Export form data to Excel format"""
    try:
        form_id = form_data.get("form_id", "").replace(" ", "_").replace("/", "_")
        if not form_id:
            form_id = form_data.get("form_name", "unknown").replace(" ", "_").replace("/", "_")
        
        filename = f"data/exports/excel/{form_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        
        # Create workbook and worksheets
        workbook = xlsxwriter.Workbook(filename)
        
        # Main form info worksheet
        main_sheet = workbook.add_worksheet('Form Information')
        
        # Header format
        header_format = workbook.add_format({
            'bold': True,
            'font_size': 14,
            'bg_color': '#D7E4BC',
            'border': 1
        })
        
        # Data format
        data_format = workbook.add_format({
            'text_wrap': True,
            'valign': 'top',
            'border': 1
        })
        
        # Write main form information
        row = 0
        main_sheet.write(row, 0, 'Field', header_format)
        main_sheet.write(row, 1, 'Value', header_format)
        
        for key, value in form_data.items():
            if key not in ['required_fields', 'supporting_documents']:
                row += 1
                main_sheet.write(row, 0, key.replace('_', ' ').title(), data_format)
                main_sheet.write(row, 1, str(value), data_format)
        
        # Required fields worksheet
        if form_data.get('required_fields'):
            fields_sheet = workbook.add_worksheet('Required Fields')
            
            # Headers
            headers = ['Field Name', 'Type', 'Description', 'Required']
            for col, header in enumerate(headers):
                fields_sheet.write(0, col, header, header_format)
            
            # Data
            for row, field in enumerate(form_data['required_fields'], 1):
                fields_sheet.write(row, 0, field.get('name', ''), data_format)
                fields_sheet.write(row, 1, field.get('type', ''), data_format)
                fields_sheet.write(row, 2, field.get('description', ''), data_format)
                fields_sheet.write(row, 3, str(field.get('required', False)), data_format)
        
        # Supporting documents worksheet
        if form_data.get('supporting_documents'):
            docs_sheet = workbook.add_worksheet('Supporting Documents')
            
            docs_sheet.write(0, 0, 'Document', header_format)
            
            for row, doc in enumerate(form_data['supporting_documents'], 1):
                docs_sheet.write(row, 0, doc, data_format)
        
        # Adjust column widths
        main_sheet.set_column(0, 0, 25)
        main_sheet.set_column(1, 1, 50)
        
        workbook.close()
        
        return filename
        
    except Exception as e:
        st.error(f"Failed to export to Excel: {str(e)}")
        return None

def export_to_pdf(form_data):
    """Export form data to PDF format"""
    try:
        form_id = form_data.get("form_id", "").replace(" ", "_").replace("/", "_")
        if not form_id:
            form_id = form_data.get("form_name", "unknown").replace(" ", "_").replace("/", "_")
        
        filename = f"data/exports/pdf/{form_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        
        # Create PDF document
        doc = SimpleDocTemplate(filename, pagesize=letter)
        styles = getSampleStyleSheet()
        story = []
        
        # Title
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=18,
            spaceAfter=30,
            textColor=colors.darkblue
        )
        
        story.append(Paragraph(f"Form Information: {form_data.get('form_name', 'Unknown')}", title_style))
        story.append(Spacer(1, 12))
        
        # Main form information
        main_data = []
        for key, value in form_data.items():
            if key not in ['required_fields', 'supporting_documents'] and value:
                main_data.append([key.replace('_', ' ').title(), str(value)])
        
        if main_data:
            main_table = Table(main_data, colWidths=[2*inch, 4*inch])
            main_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), colors.beige),
                ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
                ('BACKGROUND', (0, 0), (0, -1), colors.grey),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            story.append(main_table)
            story.append(Spacer(1, 20))
        
        # Required fields
        if form_data.get('required_fields'):
            story.append(Paragraph("Required Fields", styles['Heading2']))
            story.append(Spacer(1, 12))
            
            fields_data = [['Field Name', 'Type', 'Description', 'Required']]
            for field in form_data['required_fields']:
                fields_data.append([
                    field.get('name', ''),
                    field.get('type', ''),
                    field.get('description', ''),
                    str(field.get('required', False))
                ])
            
            fields_table = Table(fields_data, colWidths=[1.5*inch, 1*inch, 2.5*inch, 1*inch])
            fields_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            story.append(fields_table)
            story.append(Spacer(1, 20))
        
        # Supporting documents
        if form_data.get('supporting_documents'):
            story.append(Paragraph("Supporting Documents", styles['Heading2']))
            story.append(Spacer(1, 12))
            
            for doc in form_data['supporting_documents']:
                story.append(Paragraph(f"• {doc}", styles['Normal']))
            story.append(Spacer(1, 12))
        
        # Build PDF
        doc.build(story)
        
        return filename
        
    except Exception as e:
        st.error(f"Failed to export to PDF: {str(e)}")
        return None

def display_editable_form(form_data):
    """Display editable form in Streamlit"""
    st.subheader("📝 Edit Form Information")
    
    # Create columns for better layout
    col1, col2 = st.columns(2)
    
    with col1:
        form_data["form_name"] = st.text_input("Form Name", value=form_data.get("form_name", ""))
        form_data["form_id"] = st.text_input("Form ID", value=form_data.get("form_id", ""))
        form_data["governing_authority"] = st.text_input("Governing Authority", value=form_data.get("governing_authority", ""))
        form_data["submission_method"] = st.text_input("Submission Method", value=form_data.get("submission_method", ""))
        form_data["official_source_url"] = st.text_input("Official Source URL", value=form_data.get("official_source_url", ""))
    
    with col2:
        form_data["target_users"] = st.text_input("Target Users", value=form_data.get("target_users", ""))
        form_data["frequency_or_deadline"] = st.text_input("Frequency/Deadline", value=form_data.get("frequency_or_deadline", ""))
        form_data["validation_status"] = st.selectbox("Validation Status",
                                                     ["pending", "extracted", "validated", "approved"],
                                                    index=["pending", "extracted", "validated", "approved"].index(form_data.get("validation_status", "pending")))
    
    # Description and notes
    form_data["description"] = st.text_area("Description", value=form_data.get("description", ""), height=100)
    form_data["notes_or_instructions"] = st.text_area("Notes/Instructions", value=form_data.get("notes_or_instructions", ""), height=100)
    
    # Required fields section
    st.subheader("📋 Required Fields")
    
    if "required_fields" not in form_data:
        form_data["required_fields"] = []
    
    # Add new field button
    if st.button("➕ Add New Field"):
        form_data["required_fields"].append({
            "name": "",
            "type": "",
            "description": "",
            "required": True
        })
    
    # Edit existing fields
    fields_to_remove = []
    for i, field in enumerate(form_data["required_fields"]):
        with st.expander(f"Field {i+1}: {field.get('name', 'Unnamed')}"):
            col1, col2, col3 = st.columns([2, 1, 1])
            
            with col1:
                field["name"] = st.text_input(f"Field Name {i+1}", value=field.get("name", ""), key=f"field_name_{i}")
                field["description"] = st.text_input(f"Description {i+1}", value=field.get("description", ""), key=f"field_desc_{i}")
            
            with col2:
                # Define comprehensive field types
                field_types = [
                    "text", "number", "date", "email", "phone", 
                    "checkbox", "select", "textarea", "financial",
                    "boolean", "currency", "percentage", "file",
                    "signature", "ssn", "tax_id", "passport", "other"
                ]
                
                # Get current type with fallback
                current_type = field.get("type", "text")
                
                # Handle unknown types
                if current_type not in field_types:
                    field_types.append(current_type)
                
                # Get index safely
                try:
                    index = field_types.index(current_type)
                except ValueError:
                    index = 0
                
                field["type"] = st.selectbox(
                    f"Type {i+1}",
                    options=field_types,
                    index=index,
                    key=f"field_type_{i}"
                )
            
            with col3:
                field["required"] = st.checkbox(f"Required {i+1}", value=field.get("required", True), key=f"field_req_{i}")
            
            if st.button(f"🗑️ Remove", key=f"remove_field_{i}"):
                fields_to_remove.append(i)
    
    # Remove fields marked for deletion
    for i in reversed(fields_to_remove):
        form_data["required_fields"].pop(i)
    
    # Supporting documents section
    st.subheader("📎 Supporting Documents")
    
    if "supporting_documents" not in form_data:
        form_data["supporting_documents"] = []
    
    # Add new document
    new_doc = st.text_input("Add Supporting Document")
    if st.button("➕ Add Document") and new_doc:
        form_data["supporting_documents"].append(new_doc)
    
    # Edit existing documents
    docs_to_remove = []
    for i, doc in enumerate(form_data["supporting_documents"]):
        col1, col2 = st.columns([4, 1])
        with col1:
            form_data["supporting_documents"][i] = st.text_input(f"Document {i+1}", value=doc, key=f"doc_{i}")
        with col2:
            if st.button(f"🗑️", key=f"remove_doc_{i}"):
                docs_to_remove.append(i)
    
    # Remove documents marked for deletion
    for i in reversed(docs_to_remove):
        form_data["supporting_documents"].pop(i)
    
    # Update timestamp
    form_data["last_updated"] = datetime.now().isoformat()
    
    return form_data

def load_form_data(filename):
    """Load form data from JSON file"""
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        st.error(f"Failed to load form data: {str(e)}")
        return None

def delete_form_data(filename):
    """Delete form data file"""
    try:
        os.remove(filename)
        return True
    except Exception as e:
        st.error(f"Failed to delete form data: {str(e)}")
        return False

def get_download_link(filename, link_text):
    """Generate download link for files"""
    try:
        with open(filename, 'rb') as f:
            bytes_data = f.read()
        
        b64 = base64.b64encode(bytes_data).decode()
        file_ext = Path(filename).suffix
        
        if file_ext == '.json':
            mime_type = 'application/json'
        elif file_ext == '.xlsx':
            mime_type = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        elif file_ext == '.pdf':
            mime_type = 'application/pdf'
        else:
            mime_type = 'application/octet-stream'
        
        href = f'<a href="data:{mime_type};base64,{b64}" download="{Path(filename).name}">{link_text}</a>'
        return href
    except Exception as e:
        st.error(f"Failed to create download link: {str(e)}")
        return None

def display_saved_forms():
    """Display and manage saved forms"""
    st.header("💾 Saved Forms")
    
    # Get all saved forms
    forms_dir = Path("data/forms")
    if not forms_dir.exists():
        st.info("No saved forms found.")
        return
    
    form_files = list(forms_dir.glob("*.json"))
    
    if not form_files:
        st.info("No saved forms found.")
        return
    
    # Display forms in a table
    forms_data = []
    for form_file in form_files:
        try:
            with open(form_file, 'r', encoding='utf-8') as f:
                form_data = json.load(f)
            
            forms_data.append({
                "Form Name": form_data.get("form_name", "Unknown"),
                "Form ID": form_data.get("form_id", ""),
                "Authority": form_data.get("governing_authority", ""),
                "Status": form_data.get("validation_status", "pending"),
                "Last Updated": form_data.get("last_updated", ""),
                "File": form_file.name
            })
        except Exception as e:
            st.warning(f"Failed to load {form_file.name}: {str(e)}")
    
    if forms_data:
        df = pd.DataFrame(forms_data)
        st.dataframe(df, use_container_width=True)
        
        # Form selection for actions
        selected_form = st.selectbox("Select form for actions:", 
                                   options=[f["File"] for f in forms_data],
                                   format_func=lambda x: next(f["Form Name"] for f in forms_data if f["File"] == x))
        
        if selected_form:
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                if st.button("📖 View/Edit"):
                    form_data = load_form_data(f"data/forms/{selected_form}")
                    if form_data:
                        st.session_state.current_form_data = form_data
                        st.session_state.editing_form = True
            
            with col2:
                if st.button("📊 Export Excel"):
                    form_data = load_form_data(f"data/forms/{selected_form}")
                    if form_data:
                        filename = export_to_excel(form_data)
                        if filename:
                            st.success(f"✅ Excel exported: {filename}")
            
            with col3:
                if st.button("📄 Export PDF"):
                    form_data = load_form_data(f"data/forms/{selected_form}")
                    if form_data:
                        filename = export_to_pdf(form_data)
                        if filename:
                            st.success(f"✅ PDF exported: {filename}")
            
            with col4:
                if st.button("🗑️ Delete", type="secondary"):
                    if delete_form_data(f"data/forms/{selected_form}"):
                        st.success("Form deleted successfully!")
                        st.rerun()
    
    # Display editing form if in edit mode
    if st.session_state.get("editing_form") and "current_form_data" in st.session_state:
        st.divider()
        form_data = display_editable_form(st.session_state.current_form_data)
        st.session_state.current_form_data = form_data
        
        if st.button("💾 Save Changes"):
            filename = save_form_data(form_data)
            if filename:
                st.success("Changes saved successfully!")
                st.session_state.editing_form = False
                st.rerun()

def display_system_logs():
    """Display system logs and analytics"""
    st.header("📊 System Logs & Analytics")
    
    # Logs directory
    logs_dir = Path("data/logs")
    if not logs_dir.exists():
        st.info("No logs found.")
        return
    
    # Get log files
    tavily_logs = list(logs_dir.glob("tavily_*.json"))
    llm_logs = list(logs_dir.glob("llm_*.txt"))
    
    # Display statistics
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("Tavily API Calls", len(tavily_logs))
    
    with col2:
        st.metric("LLM Operations", len(llm_logs))
    
    with col3:
        forms_count = len(list(Path("data/forms").glob("*.json"))) if Path("data/forms").exists() else 0
        st.metric("Total Forms", forms_count)
    
    # Recent activity
    st.subheader("📈 Recent Activity")
    
    all_logs = []
    
    # Process Tavily logs
    for log_file in tavily_logs:
        try:
            timestamp = log_file.stem.split('_')[-1]
            form_name = '_'.join(log_file.stem.split('_')[1:-1])
            all_logs.append({
                "Timestamp": timestamp,
                "Type": "Tavily API",
                "Form": form_name,
                "File": log_file.name
            })
        except:
            continue
    
    # Process LLM logs
    for log_file in llm_logs:
        try:
            parts = log_file.stem.split('_')
            timestamp = parts[-1]
            operation = parts[1]
            form_name = '_'.join(parts[2:-1])
            all_logs.append({
                "Timestamp": timestamp,
                "Type": f"LLM {operation.title()}",
                "Form": form_name,
                "File": log_file.name
            })
        except:
            continue
    
    if all_logs:
        # Sort by timestamp (most recent first)
        all_logs.sort(key=lambda x: x["Timestamp"], reverse=True)
        
        # Display recent logs
        df = pd.DataFrame(all_logs[:20])  # Show last 20 entries
        st.dataframe(df, use_container_width=True)
        
        # Log viewer
        st.subheader("🔍 Log Viewer")
        selected_log = st.selectbox("Select log to view:", 
                                  options=[log["File"] for log in all_logs],
                                  format_func=lambda x: f"{next(log['Type'] for log in all_logs if log['File'] == x)} - {next(log['Form'] for log in all_logs if log['File'] == x)}")
        
        if selected_log and st.button("View Log"):
            log_path = logs_dir / selected_log
            try:
                if selected_log.endswith('.json'):
                    with open(log_path, 'r', encoding='utf-8') as f:
                        log_content = json.load(f)
                    st.json(log_content)
                else:
                    with open(log_path, 'r', encoding='utf-8') as f:
                        log_content = f.read()
                    st.text(log_content)
            except Exception as e:
                st.error(f"Failed to load log: {str(e)}")
    else:
        st.info("No logs found.")

def main():
    st.set_page_config(
        page_title="AI Form Intelligence Pipeline",
        page_icon="📋",
        layout="wide"
    )
    
    # Initialize directories
    ensure_directories()
    
    # Initialize APIs
    openai_client, tavily_api_key = init_apis()
    
    if not openai_client or not tavily_api_key:
        st.error("❌ API configuration failed. Please check your API keys.")
        return
    
    # Header
    st.title("🤖 AI Form Intelligence Pipeline")
    st.markdown("**Automated form data extraction, validation, and management system**")
    
    # Sidebar for navigation
    st.sidebar.title("📋 Navigation")
    page = st.sidebar.radio("Select Page", ["New Form Analysis", "Saved Forms", "System Logs"])
    
    if page == "New Form Analysis":
        # Main form input
        st.header("🔍 Form Analysis")
        
        form_input = st.text_input("Enter Form Name (e.g., 'DS-160 Immigration Form', 'Form 1040 Tax Return')")
        
        if st.button("🚀 Analyze Form", type="primary"):
            if not form_input:
                st.error("Please enter a form name")
                return
            
            # Progress tracking
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            # Step 1: Query Tavily API
            status_text.text("🔍 Searching for form information...")
            progress_bar.progress(25)
            
            tavily_results = query_tavily_api(form_input, tavily_api_key)
            
            if "error" in tavily_results:
                st.error(f"Tavily API Error: {tavily_results['error']}")
                return
            
            # Step 2: Extract form data using OpenAI
            status_text.text("🧠 Extracting structured data...")
            progress_bar.progress(50)
            
            form_data = extract_form_data(form_input, tavily_results, openai_client)
            
            # Step 3: Store in session state for editing
            st.session_state.current_form_data = form_data
            
            status_text.text("✅ Analysis complete!")
            progress_bar.progress(100)
            
            st.success("Form analysis completed successfully!")
        
        # Display and edit form data if available
        if "current_form_data" in st.session_state:
            form_data = display_editable_form(st.session_state.current_form_data)
            st.session_state.current_form_data = form_data
            
            # Action buttons
            st.header("🔧 Actions")
            
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                if st.button("🔍 Validate with AI", type="secondary"):
                    with st.spinner("Validating form data..."):
                        validation_result = validate_form_data(form_data, openai_client)
                        st.session_state.validation_result = validation_result
            
            with col2:
                if st.button("💾 Save as JSON"):
                    filename = save_form_data(form_data)
                    if filename:
                        st.success(f"✅ Form saved to: {filename}")
            
            with col3:
                if st.button("📊 Export to Excel"):
                    filename = export_to_excel(form_data)
                    if filename:
                        st.success(f"✅ Excel exported to: {filename}")
            
            with col4:
                if st.button("📄 Export to PDF"):
                    filename = export_to_pdf(form_data)
                    if filename:
                        st.success(f"✅ PDF exported to: {filename}")
            
            # Display validation results
            if "validation_result" in st.session_state:
                st.header("🔍 Validation Results")
                
                validation = st.session_state.validation_result
                
                if validation["validation_passed"]:
                    st.success("✅ Validation passed!")
                else:
                    st.warning("⚠️ Issues found during validation")
                
                # Completeness score
                score = validation.get("completeness_score", 0)
                st.metric("Completeness Score", f"{score}%")
                
                # Issues
                if validation.get("issues_found"):
                    st.subheader("Issues Found")
                    for issue in validation["issues_found"]:
                        severity_color = {"high": "🔴", "medium": "🟡", "low": "🟢"}
                        color = severity_color.get(issue.get("severity", "medium"), "🟡")
                        
                        with st.expander(f"{color} {issue.get('field', 'Unknown')} - {issue.get('severity', 'medium').title()} Priority"):
                            st.write(f"**Issue:** {issue.get('issue', 'No description')}")
                            st.write(f"**Suggestion:** {issue.get('suggestion', 'No suggestion')}")
                
                # Overall assessment
                if validation.get("overall_assessment"):
                    st.subheader("Overall Assessment")
                    st.write(validation["overall_assessment"])
    
    elif page == "Saved Forms":
        display_saved_forms()
    
    elif page == "System Logs":
        display_system_logs()

if __name__ == "__main__":
    main()