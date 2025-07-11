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
        query = f"""What are the required fields, field types, supporting documents, official submission method,
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
    """Export form data to Excel format and return bytes"""
    try:
        # Create Excel file in memory
        output = io.BytesIO()
        
        # Create workbook and worksheets
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        
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
        
        # Get the Excel file content
        excel_data = output.getvalue()
        output.close()
        
        # Also save to file system for backup
        form_id = form_data.get("form_id", "").replace(" ", "_").replace("/", "_")
        if not form_id:
            form_id = form_data.get("form_name", "unknown").replace(" ", "_").replace("/", "_")
        
        filename = f"data/exports/excel/{form_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        with open(filename, 'wb') as f:
            f.write(excel_data)
        
        return excel_data, filename
        
    except Exception as e:
        st.error(f"Failed to export to Excel: {str(e)}")
        return None, None

def export_to_pdf(form_data):
    """Export form data to PDF format and return bytes"""
    try:
        # Create PDF in memory
        output = io.BytesIO()
        
        # Create PDF document
        doc = SimpleDocTemplate(output, pagesize=letter)
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
        
        # Get the PDF content
        pdf_data = output.getvalue()
        output.close()
        
        # Also save to file system for backup
        form_id = form_data.get("form_id", "").replace(" ", "_").replace("/", "_")
        if not form_id:
            form_id = form_data.get("form_name", "unknown").replace(" ", "_").replace("/", "_")
        
        filename = f"data/exports/pdf/{form_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        with open(filename, 'wb') as f:
            f.write(pdf_data)
        
        return pdf_data, filename
        
    except Exception as e:
        st.error(f"Failed to export to PDF: {str(e)}")
        return None, None

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
                field["type"] = st.selectbox(f"Type {i+1}",
                                           ["text", "number", "date", "email", "phone", "checkbox", "select", "textarea"],
                                          index=0 if field.get("type") == "" else ["text", "number", "date", "email", "phone", "checkbox", "select", "textarea"].index(field.get("type", "text")),
                                          key=f"field_type_{i}")
            
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

def display_saved_forms():
    """Display saved forms page"""
    st.header("📁 Saved Forms")
    
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
            st.error(f"Error loading {form_file.name}: {str(e)}")
    
    if forms_data:
        df = pd.DataFrame(forms_data)
        st.dataframe(df, use_container_width=True)
        
        # Form selection for actions
        st.subheader("🔧 Form Actions")
        
        selected_form = st.selectbox(
            "Select a form to manage:",
            options=[f["File"] for f in forms_data],
            format_func=lambda x: next((f["Form Name"] for f in forms_data if f["File"] == x), x)
        )
        
        if selected_form:
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                if st.button("👁️ View/Edit"):
                    form_data = load_form_data(f"data/forms/{selected_form}")
                    if form_data:
                        st.session_state.current_form_data = form_data
                        st.session_state.editing_form = True
                        st.rerun()
            
            with col2:
                if st.button("📊 Export Excel"):
                    form_data = load_form_data(f"data/forms/{selected_form}")
                    if form_data:
                        excel_data, filename = export_to_excel(form_data)
                        if excel_data:
                            form_name = form_data.get("form_name", "form")
                            st.download_button(
                                label="📥 Download Excel",
                                data=excel_data,
                                file_name=f"{form_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                            )
                            st.success(f"✅ Excel file ready for download!")
            
            with col3:
                if st.button("📄 Export PDF"):
                    form_data = load_form_data(f"data/forms/{selected_form}")
                    if form_data:
                        pdf_data, filename = export_to_pdf(form_data)
                        if pdf_data:
                            form_name = form_data.get("form_name", "form")
                            st.download_button(
                                label="📥 Download PDF",
                                data=pdf_data,
                                file_name=f"{form_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                                mime="application/pdf"
                            )
                            st.success(f"✅ PDF file ready for download!")
            
            with col4:
                if st.button("🗑️ Delete", type="secondary"):
                    if st.session_state.get("confirm_delete", False):
                        if delete_form_data(f"data/forms/{selected_form}"):
                            st.success("✅ Form deleted successfully!")
                            st.session_state.confirm_delete = False
                            st.rerun()
                    else:
                        st.session_state.confirm_delete = True
                        st.warning("Click again to confirm deletion")

def display_system_logs():
    """Display system logs page"""
    st.header("📊 System Logs")
    
    # Get all log files
    logs_dir = Path("data/logs")
    if not logs_dir.exists():
        st.info("No logs found.")
        return
    
    log_files = list(logs_dir.glob("*"))
    
    if not log_files:
        st.info("No logs found.")
        return
    
    # Display logs by type
    tavily_logs = [f for f in log_files if f.name.startswith("tavily_")]
    llm_logs = [f for f in log_files if f.name.startswith("llm_")]
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("🔍 Tavily API Logs")
        if tavily_logs:
            selected_tavily_log = st.selectbox(
                "Select Tavily log:",
                options=[f.name for f in tavily_logs],
                key="tavily_log_select"
            )
            
            if selected_tavily_log and st.button("View Tavily Log"):
                try:
                    with open(f"data/logs/{selected_tavily_log}", 'r', encoding='utf-8') as f:
                        log_data = json.load(f)
                    st.json(log_data)
                except Exception as e:
                    st.error(f"Error reading log: {str(e)}")
        else:
            st.info("No Tavily logs found.")
    
    with col2:
        st.subheader("🤖 LLM Logs")
        if llm_logs:
            selected_llm_log = st.selectbox(
                "Select LLM log:",
                options=[f.name for f in llm_logs],
                key="llm_log_select"
            )
            
            if selected_llm_log and st.button("View LLM Log"):
                try:
                    with open(f"data/logs/{selected_llm_log}", 'r', encoding='utf-8') as f:
                        log_content = f.read()
                    st.text(log_content)
                except Exception as e:
                    st.error(f"Error reading log: {str(e)}")
        else:
            st.info("No LLM logs found.")
    
    # Log cleanup section
    st.subheader("🧹 Log Management")
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("🗑️ Clear All Logs"):
            if st.session_state.get("confirm_clear_logs", False):
                try:
                    for log_file in log_files:
                        log_file.unlink()
                    st.success("✅ All logs cleared successfully!")
                    st.session_state.confirm_clear_logs = False
                    st.rerun()
                except Exception as e:
                    st.error(f"Error clearing logs: {str(e)}")
            else:
                st.session_state.confirm_clear_logs = True
                st.warning("Click again to confirm clearing all logs")
    
    with col2:
        st.info(f"Total log files: {len(log_files)}")

def display_extracted_form_data(form_data, openai_client):
    """Display extracted form data with persistent action buttons"""
    st.subheader("📊 Extracted Form Information")
    
    # Basic info
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Form Name", form_data.get("form_name", "N/A"))
        st.metric("Form ID", form_data.get("form_id", "N/A"))
        st.metric("Authority", form_data.get("governing_authority", "N/A"))
    
    with col2:
        st.metric("Target Users", form_data.get("target_users", "N/A"))
        st.metric("Submission Method", form_data.get("submission_method", "N/A"))
        st.metric("Deadline", form_data.get("frequency_or_deadline", "N/A"))
    
    # Description
    if form_data.get("description"):
        st.subheader("📝 Description")
        st.write(form_data["description"])
    
    # Required fields
    if form_data.get("required_fields"):
        st.subheader("📋 Required Fields")
        fields_df = pd.DataFrame(form_data["required_fields"])
        st.dataframe(fields_df, use_container_width=True)
    
    # Supporting documents
    if form_data.get("supporting_documents"):
        st.subheader("📎 Supporting Documents")
        for doc in form_data["supporting_documents"]:
            st.write(f"• {doc}")
    
    # Validation section
    st.subheader("🔍 Validation & Quality Check")
    
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("🔍 Validate Form Data", key="validate_btn"):
            with st.spinner("🤖 Validating form data..."):
                validation_result = validate_form_data(form_data, openai_client)
                st.session_state.validation_result = validation_result
    
    with col2:
        if st.button("📝 Edit Form Data", key="edit_btn"):
            st.session_state.editing_form = True
            st.rerun()
    
    # Display validation results if available
    if "validation_result" in st.session_state and st.session_state.validation_result:
        validation_result = st.session_state.validation_result
        st.subheader("📊 Validation Results")
        
        # Overall score
        score = validation_result.get("completeness_score", 0)
        st.metric("Completeness Score", f"{score}/100")
        
        # Validation status
        if validation_result.get("validation_passed"):
            st.success("✅ Validation Passed")
        else:
            st.error("❌ Validation Failed")
        
        # Issues found
        if validation_result.get("issues_found"):
            st.subheader("⚠️ Issues Found")
            for issue in validation_result["issues_found"]:
                severity_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}
                st.write(f"{severity_emoji.get(issue.get('severity', 'low'), '⚪')} **{issue.get('field', 'Unknown')}**: {issue.get('issue', 'No description')}")
                if issue.get('suggestion'):
                    st.write(f"   💡 Suggestion: {issue['suggestion']}")
        
        # Overall assessment
        if validation_result.get("overall_assessment"):
            st.subheader("📝 Overall Assessment")
            st.write(validation_result["overall_assessment"])
    
    # Action buttons section
    st.subheader("🔧 Actions")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("💾 Save Form Data", key="save_btn"):
            filename = save_form_data(form_data)
            if filename:
                st.success(f"✅ Form saved successfully!")
                # Create JSON download
                json_str = json.dumps(form_data, indent=2, ensure_ascii=False)
                st.download_button(
                    label="📥 Download JSON",
                    data=json_str,
                    file_name=f"{form_data.get('form_name', 'form')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                    mime="application/json",
                    key="download_json_btn"
                )
    
    with col2:
        if st.button("📊 Export to Excel", key="excel_btn"):
            with st.spinner("Creating Excel file..."):
                excel_data, filename = export_to_excel(form_data)
                if excel_data:
                    st.success(f"✅ Excel file ready for download!")
                    st.download_button(
                        label="📥 Download Excel",
                        data=excel_data,
                        file_name=f"{form_data.get('form_name', 'form')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="download_excel_btn"
                    )
    
    with col3:
        if st.button("📄 Export to PDF", key="pdf_btn"):
            with st.spinner("Creating PDF file..."):
                pdf_data, filename = export_to_pdf(form_data)
                if pdf_data:
                    st.success(f"✅ PDF file ready for download!")
                    st.download_button(
                        label="📥 Download PDF",
                        data=pdf_data,
                        file_name=f"{form_data.get('form_name', 'form')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                        mime="application/pdf",
                        key="download_pdf_btn"
                    )

def main():
    """Main Streamlit application"""
    st.set_page_config(
        page_title="Form Intelligence Platform",
        page_icon="📋",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    # Initialize session state
    if "current_form_data" not in st.session_state:
        st.session_state.current_form_data = None
    if "editing_form" not in st.session_state:
        st.session_state.editing_form = False
    if "confirm_delete" not in st.session_state:
        st.session_state.confirm_delete = False
    if "confirm_clear_logs" not in st.session_state:
        st.session_state.confirm_clear_logs = False
    if "extraction_completed" not in st.session_state:
        st.session_state.extraction_completed = False
    if "validation_result" not in st.session_state:
        st.session_state.validation_result = None
    
    # Ensure directories exist
    ensure_directories()
    
    # Initialize APIs
    openai_client, tavily_api_key = init_apis()
    
    if not openai_client or not tavily_api_key:
        st.error("❌ Failed to initialize APIs. Please check your API keys.")
        st.stop()
    
    # Sidebar navigation
    st.sidebar.title("📋 Form Intelligence Platform")
    
    # Navigation menu
    if st.session_state.editing_form:
        page = "Edit Form"
    else:
        page = st.sidebar.selectbox(
            "Navigate to:",
            ["🔍 Extract Form", "📁 Saved Forms", "📊 System Logs", "ℹ️ About"]
        )
    
    # Main content area
    if page == "🔍 Extract Form":
        st.title("🔍 Form Intelligence Extractor")
        st.markdown("Enter a form name to automatically extract comprehensive form information.")
        
        # Clear extraction state when navigating back to extract form
        if st.sidebar.button("🔄 New Extraction"):
            st.session_state.current_form_data = None
            st.session_state.extraction_completed = False
            st.session_state.validation_result = None
            st.rerun()
        
        # Show extraction form if no data is extracted yet
        if not st.session_state.extraction_completed or st.session_state.current_form_data is None:
            # Form input
            form_name = st.text_input(
                "Enter Form Name:",
                placeholder="e.g., W-4 Tax Form, 1099-NEC, I-9 Employment Eligibility Verification"
            )
            
            if st.button("🚀 Extract Form Information", type="primary"):
                if form_name:
                    with st.spinner("🔍 Searching for form information..."):
                        # Query Tavily API
                        tavily_results = query_tavily_api(form_name, tavily_api_key)
                        
                        if "error" in tavily_results:
                            st.error(f"❌ Search failed: {tavily_results['error']}")
                        else:
                            st.success("✅ Search completed!")
                            
                            # Extract structured data using OpenAI
                            with st.spinner("🤖 Extracting structured form data..."):
                                form_data = extract_form_data(form_name, tavily_results, openai_client)
                                
                                if form_data:
                                    st.session_state.current_form_data = form_data
                                    st.session_state.extraction_completed = True
                                    st.success("✅ Form data extracted successfully!")
                                    st.rerun()
                                else:
                                    st.error("❌ Failed to extract form data")
                else:
                    st.warning("⚠️ Please enter a form name")
        
        # Show extracted data if available
        if st.session_state.extraction_completed and st.session_state.current_form_data:
            display_extracted_form_data(st.session_state.current_form_data, openai_client)
    
    elif page == "📁 Saved Forms":
        display_saved_forms()
    
    elif page == "📊 System Logs":
        display_system_logs()
    
    elif page == "ℹ️ About":
        st.title("ℹ️ About Form Intelligence Platform")
        
        st.markdown("""
        ## 🎯 Purpose
        The Form Intelligence Platform is an AI-powered tool designed to automatically extract, validate, and manage comprehensive information about various forms and documents.
        
        ## 🚀 Features
        - **🔍 Intelligent Form Extraction**: Automatically searches and extracts detailed form information
        - **🤖 AI-Powered Validation**: Uses OpenAI to validate and audit form data quality
        - **📊 Multiple Export Formats**: Export to JSON, Excel, and PDF formats
        - **📁 Form Management**: Save, edit, and manage extracted form data
        - **📊 System Logging**: Track all API calls and system operations
        - **🔧 Data Editing**: Manual editing and refinement of extracted data
        
        ## 🛠️ Technology Stack
        - **Streamlit**: Web application framework
        - **OpenAI GPT-4**: AI model for data extraction and validation
        - **Tavily API**: Web search and information retrieval
        - **ReportLab**: PDF generation
        - **XlsxWriter**: Excel file generation
        - **Pandas**: Data manipulation and analysis
        
        ## 📝 Usage Instructions
        1. **Extract Form**: Enter a form name to automatically extract information
        2. **Validate**: Use AI validation to check data quality and completeness
        3. **Edit**: Manually refine and edit extracted data
        4. **Save**: Store form data for future reference
        5. **Export**: Generate reports in various formats
        6. **Manage**: View and manage all saved forms
        
        ## 🔒 Data Security
        - All data is stored locally
        - API keys are securely managed
        - No sensitive information is transmitted unnecessarily
        - Complete audit trail through system logs
        
        ## 📞 Support
        For technical support or feature requests, please contact the development team.
        """)
    
    elif page == "Edit Form":
        st.title("📝 Edit Form Data")
        
        if st.session_state.current_form_data:
            # Display edit form
            updated_form_data = display_editable_form(st.session_state.current_form_data)
            
            # Action buttons
            col1, col2, col3 = st.columns(3)
            
            with col1:
                if st.button("💾 Save Changes"):
                    filename = save_form_data(updated_form_data)
                    if filename:
                        st.success(f"✅ Form saved successfully!")
                        st.session_state.current_form_data = updated_form_data
            
            with col2:
                if st.button("🔍 Re-validate"):
                    with st.spinner("🤖 Validating form data..."):
                        validation_result = validate_form_data(updated_form_data, openai_client)
                        
                        if validation_result:
                            st.subheader("📊 Validation Results")
                            
                            # Overall score
                            score = validation_result.get("completeness_score", 0)
                            st.metric("Completeness Score", f"{score}/100")
                            
                            # Validation status
                            if validation_result.get("validation_passed"):
                                st.success("✅ Validation Passed")
                            else:
                                st.error("❌ Validation Failed")
                            
                            # Issues found
                            if validation_result.get("issues_found"):
                                st.subheader("⚠️ Issues Found")
                                for issue in validation_result["issues_found"]:
                                    severity_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}
                                    st.write(f"{severity_emoji.get(issue.get('severity', 'low'), '⚪')} **{issue.get('field', 'Unknown')}**: {issue.get('issue', 'No description')}")
                                    if issue.get('suggestion'):
                                        st.write(f"   💡 Suggestion: {issue['suggestion']}")
            
            with col3:
                if st.button("🔙 Back to Extract"):
                    st.session_state.editing_form = False
                    st.rerun()
        else:
            st.warning("⚠️ No form data to edit")
            if st.button("🔙 Back to Extract"):
                st.session_state.editing_form = False
                st.rerun()

if __name__ == "__main__":
    main()
