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
    """Initialize OpenAI and Tavily APIs with improved error handling for quota issues"""
    try:
        # Initialize OpenAI client (new v1+ API)
        openai_api_key = None
        tavily_api_key = None
        
        # Try to get API keys from different sources
        try:
            # First try Streamlit secrets
            openai_api_key = st.secrets.get("openai_api_key")
            tavily_api_key = st.secrets.get("tavily_api_key")
        except:
            pass
        
        # Fallback to environment variables
        if not openai_api_key:
            openai_api_key = os.getenv("OPENAI_API_KEY")
        if not tavily_api_key:
            tavily_api_key = os.getenv("TAVILY_API_KEY")
        
        # Validate API keys
        if not openai_api_key:
            st.error("❌ OpenAI API key not found. Please check your secrets.toml file or environment variables.")
            return None, None
            
        if not tavily_api_key:
            st.error("❌ Tavily API key not found. Please check your secrets.toml file or environment variables.")
            return None, None
        
        # Clean API keys
        openai_api_key = openai_api_key.strip()
        tavily_api_key = tavily_api_key.strip()
        
        # Validate API key formats
        if not openai_api_key.startswith('sk-'):
            st.error("❌ Invalid OpenAI API key format. Should start with 'sk-'")
            return None, None
            
        if not tavily_api_key.startswith('tvly-'):
            st.error("❌ Invalid Tavily API key format. Should start with 'tvly-'")
            return None, None
        
        # Initialize OpenAI client
        openai_client = OpenAI(api_key=openai_api_key)
        
        # Test OpenAI connection with improved error handling
        try:
            test_response = openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": "Hello"}],
                max_tokens=5
            )
            st.success("✅ OpenAI API connection successful")
        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "quota" in error_str.lower() or "insufficient_quota" in error_str.lower():
                st.warning("⚠️ OpenAI API quota exceeded. The application will continue with limited functionality.")
                st.info("💡 To restore full functionality, please check your OpenAI billing and upgrade your plan if needed.")
                # Return the client anyway - it might work for actual requests
                return openai_client, tavily_api_key
            elif "401" in error_str or "unauthorized" in error_str.lower():
                st.error("❌ OpenAI API key is invalid or unauthorized")
                return None, None
            elif "403" in error_str or "forbidden" in error_str.lower():
                st.error("❌ OpenAI API access forbidden. Please check your API key permissions.")
                return None, None
            else:
                st.warning(f"⚠️ OpenAI API test failed: {error_str}")
                st.info("The application will continue - the API might work for actual requests.")
                # Return the client anyway - the test might fail but actual requests might work
                return openai_client, tavily_api_key
        
        st.success("✅ Tavily API key loaded successfully")
        
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
    "all_fields": [],  # Changed from required_fields to all_fields
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
    """Query Tavily API for form information with improved error handling"""
    if not tavily_api_key:
        return {"error": "Tavily API key not found"}
    
    # Clean and validate the API key
    tavily_api_key = tavily_api_key.strip()
    if not tavily_api_key.startswith('tvly-'):
        return {"error": "Invalid Tavily API key format"}
    
    try:
        url = "https://api.tavily.com/search"
        
        # Shortened query to stay under 400 character limit
        query = f"{form_name} form fields required optional types descriptions supporting documents submission method authority deadlines instructions"
        
        # Ensure query is under 400 characters
        if len(query) > 400:
            query = f"{form_name} form all fields required optional types descriptions documents submission"
        
        # Simplified payload to avoid issues
        payload = {
            "api_key": tavily_api_key,
            "query": query,
            "search_depth": "basic",
            "include_answer": True,
            "include_raw_content": False,
            "max_results": 10
        }
        
        # Add headers
        headers = {
            "Content-Type": "application/json"
        }
        
        # Debug information
        st.info(f"🔍 Making API request to Tavily...")
        st.info(f"📝 Query ({len(query)} chars): {query}")
        
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        
        # Debug response
        st.info(f"📊 Response Status: {response.status_code}")
        
        # Handle different error codes
        if response.status_code == 400:
            error_detail = ""
            try:
                error_data = response.json()
                error_detail = error_data.get('detail', error_data.get('message', error_data.get('error', 'Unknown error')))
            except:
                error_detail = response.text
            
            return {"error": f"Bad Request (400): {error_detail}. Please check your API key and query format."}
        
        elif response.status_code == 401:
            return {"error": "Unauthorized (401): Invalid API key. Please check your Tavily API key."}
        
        elif response.status_code == 403:
            return {"error": "Forbidden (403): API key doesn't have permission or quota exceeded."}
        
        elif response.status_code == 429:
            return {"error": "Rate Limited (429): Too many requests. Please wait and try again."}
        
        elif response.status_code != 200:
            return {"error": f"HTTP {response.status_code}: {response.text}"}
        
        response.raise_for_status()
        
        data = response.json()
        
        # Validate response structure
        if not isinstance(data, dict):
            return {"error": "Invalid response format from Tavily API"}
        
        # Log the raw response
        log_tavily_response(form_name, data)
        
        st.success(f"✅ Tavily API call successful! Found {len(data.get('results', []))} results")
        
        return data
        
    except requests.exceptions.Timeout:
        return {"error": "Request timeout. Please try again."}
    except requests.exceptions.ConnectionError:
        return {"error": "Connection error. Please check your internet connection."}
    except requests.exceptions.RequestException as e:
        return {"error": f"Request failed: {str(e)}"}
    except json.JSONDecodeError:
        return {"error": "Invalid JSON response from Tavily API"}
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
    """Use OpenAI to extract structured form data from Tavily results with improved error handling"""
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
        
        # Enhanced extraction prompt for ALL fields
        prompt = f"""
        You are a comprehensive form intelligence expert. Extract ALL information about the "{form_name}" form 
        from the search results below and structure it into a JSON object.

        CRITICAL REQUIREMENTS:
        1. ALWAYS include ALL fields from the schema, even if information is not available (use empty string "" or empty array [])
        2. For all_fields, extract EVERY SINGLE FIELD that appears on the form, whether required OR optional
        3. Each field must have: name, type, description, required (boolean), optional (boolean)
        4. Be extremely comprehensive - don't miss any fields, sections, or parts of the form
        5. Extract actual field names, types, and detailed descriptions from the search results
        6. Include all supporting documents mentioned
        7. Capture submission methods and deadlines precisely
        8. Look for field sections, parts, lines, boxes - everything that needs to be filled out

        JSON Schema to follow:
        {{
            "form_name": "string",
            "form_id": "string", 
            "description": "string",
            "governing_authority": "string",
            "target_users": "string",
            "all_fields": [
                {{
                    "name": "string",
                    "type": "string", 
                    "description": "string",
                    "required": boolean,
                    "optional": boolean,
                    "section": "string",
                    "line_number": "string",
                    "instructions": "string"
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

        IMPORTANT: Make sure to capture ALL fields - required fields, optional fields, signature fields, 
        date fields, checkboxes, text areas, everything that appears on the form. Don't leave anything out.

        Search Results:
        {search_text}

        Return ONLY the JSON object, no other text:
        """
        
        try:
            response = openai_client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": "You are a comprehensive form intelligence extraction expert who captures EVERY field on a form. Always return valid JSON with complete field information."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=3000  # Increased for more comprehensive extraction
            )
            
            # Extract and parse the JSON response
            json_text = response.choices[0].message.content.strip()
            
        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "quota" in error_str.lower():
                st.error("❌ OpenAI API quota exceeded. Cannot extract form data.")
                st.info("💡 Please check your OpenAI billing and upgrade your plan to continue.")
                return create_empty_form_data(form_name)
            elif "401" in error_str:
                st.error("❌ OpenAI API unauthorized. Please check your API key.")
                return create_empty_form_data(form_name)
            else:
                st.error(f"❌ OpenAI API error: {error_str}")
                return create_empty_form_data(form_name)
        
        # Log the LLM response
        log_llm_response(form_name, "extraction", json_text)
        
        # Parse the JSON
        form_data = json.loads(json_text)
        
        # Ensure all required fields are present
        for key in FORM_SCHEMA:
            if key not in form_data:
                form_data[key] = FORM_SCHEMA[key]
        
        # Ensure all_fields has the required structure
        if "all_fields" in form_data:
            for field in form_data["all_fields"]:
                # Ensure each field has all required properties
                field_defaults = {
                    "name": "",
                    "type": "text",
                    "description": "",
                    "required": False,
                    "optional": True,
                    "section": "",
                    "line_number": "",
                    "instructions": ""
                }
                for prop, default_val in field_defaults.items():
                    if prop not in field:
                        field[prop] = default_val
        
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
    """Use OpenAI to validate and audit the form data with improved error handling"""
    try:
        prompt = f"""
        You are a comprehensive form validation expert. Review the following form metadata and identify any issues:
        
        1. Missing or incomplete field information (both required and optional)
        2. Incorrect field types or descriptions
        3. Missing supporting documents that should be included
        4. Unclear or incorrect submission methods
        5. Missing deadlines or frequency information
        6. Any fields that might have been overlooked
        7. Any other obvious errors or omissions
        
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
            "completeness_score": number (0-100),
            "total_fields_found": number,
            "missing_fields_likely": ["string"]
        }}
        
        Return ONLY the JSON object:
        """
        
        try:
            response = openai_client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": "You are a thorough form validation expert who ensures ALL fields are captured. Always return valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=1500
            )
            
            validation_result = json.loads(response.choices[0].message.content.strip())
            
            # Log validation response
            log_llm_response(form_data["form_name"], "validation", response.choices[0].message.content)
            
            return validation_result
            
        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "quota" in error_str.lower():
                st.error("❌ OpenAI API quota exceeded. Cannot validate form data.")
                st.info("💡 Please check your OpenAI billing and upgrade your plan to continue.")
                return {
                    "validation_passed": False,
                    "issues_found": [{"field": "system", "issue": "Validation unavailable due to API quota limits", "severity": "high", "suggestion": "Manual review required"}],
                    "overall_assessment": "Validation system unavailable due to API quota limits",
                    "completeness_score": 0,
                    "total_fields_found": len(form_data.get("all_fields", [])),
                    "missing_fields_likely": []
                }
            else:
                raise e
        
    except Exception as e:
        st.error(f"Error validating form data: {str(e)}")
        return {
            "validation_passed": False,
            "issues_found": [{"field": "system", "issue": f"Validation failed: {str(e)}", "severity": "high", "suggestion": "Manual review required"}],
            "overall_assessment": "Validation system error",
            "completeness_score": 0,
            "total_fields_found": len(form_data.get("all_fields", [])),
            "missing_fields_likely": []
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
            if key not in ['all_fields', 'supporting_documents']:
                row += 1
                main_sheet.write(row, 0, key.replace('_', ' ').title(), data_format)
                main_sheet.write(row, 1, str(value), data_format)
        
        # All fields worksheet (updated from required_fields)
        if form_data.get('all_fields'):
            fields_sheet = workbook.add_worksheet('All Form Fields')
            
            # Headers
            headers = ['Field Name', 'Type', 'Description', 'Required', 'Optional', 'Section', 'Line Number', 'Instructions']
            for col, header in enumerate(headers):
                fields_sheet.write(0, col, header, header_format)
            
            # Data
            for row, field in enumerate(form_data['all_fields'], 1):
                fields_sheet.write(row, 0, field.get('name', ''), data_format)
                fields_sheet.write(row, 1, field.get('type', ''), data_format)
                fields_sheet.write(row, 2, field.get('description', ''), data_format)
                fields_sheet.write(row, 3, str(field.get('required', False)), data_format)
                fields_sheet.write(row, 4, str(field.get('optional', True)), data_format)
                fields_sheet.write(row, 5, field.get('section', ''), data_format)
                fields_sheet.write(row, 6, field.get('line_number', ''), data_format)
                fields_sheet.write(row, 7, field.get('instructions', ''), data_format)
        
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
        pdf_buffer = io.BytesIO()
        
        # Create PDF document with explicit variable name to avoid conflicts
        pdf_document = SimpleDocTemplate(pdf_buffer, pagesize=letter)
        pdf_styles = getSampleStyleSheet()
        pdf_story = []
        
        # Title
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=pdf_styles['Heading1'],
            fontSize=18,
            spaceAfter=30,
            textColor=colors.darkblue
        )
        
        form_name = form_data.get('form_name', 'Unknown Form')
        pdf_story.append(Paragraph(f"Complete Form Information: {form_name}", title_style))
        pdf_story.append(Spacer(1, 12))
        
        # Main form information
        main_data = []
        for key, value in form_data.items():
            if key not in ['all_fields', 'supporting_documents'] and value:
                display_key = key.replace('_', ' ').title()
                display_value = str(value)
                # Escape special characters for ReportLab
                display_value = display_value.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                main_data.append([display_key, display_value])
        
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
            pdf_story.append(main_table)
            pdf_story.append(Spacer(1, 20))
        
        # All fields (updated from required_fields)
        if form_data.get('all_fields'):
            pdf_story.append(Paragraph("All Form Fields", pdf_styles['Heading2']))
            pdf_story.append(Spacer(1, 12))
            
            # Group fields by required/optional for better organization
            required_fields = [f for f in form_data['all_fields'] if f.get('required', False)]
            optional_fields = [f for f in form_data['all_fields'] if not f.get('required', False)]
            
            if required_fields:
                pdf_story.append(Paragraph("Required Fields", pdf_styles['Heading3']))
                pdf_story.append(Spacer(1, 6))
                
                req_fields_data = [['Field Name', 'Type', 'Description', 'Section']]
                for field in required_fields:
                    field_name = str(field.get('name', '')).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                    field_type = str(field.get('type', '')).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                    field_desc = str(field.get('description', '')).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                    field_section = str(field.get('section', '')).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                    
                    req_fields_data.append([field_name, field_type, field_desc, field_section])
                
                req_fields_table = Table(req_fields_data, colWidths=[1.5*inch, 1*inch, 2*inch, 1.5*inch])
                req_fields_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.darkred),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, -1), 8),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                    ('BACKGROUND', (0, 1), (-1, -1), colors.lightcoral),
                    ('GRID', (0, 0), (-1, -1), 1, colors.black)
                ]))
                pdf_story.append(req_fields_table)
                pdf_story.append(Spacer(1, 15))
            
            if optional_fields:
                pdf_story.append(Paragraph("Optional Fields", pdf_styles['Heading3']))
                pdf_story.append(Spacer(1, 6))
                
                opt_fields_data = [['Field Name', 'Type', 'Description', 'Section']]
                for field in optional_fields:
                    field_name = str(field.get('name', '')).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                    field_type = str(field.get('type', '')).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                    field_desc = str(field.get('description', '')).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                    field_section = str(field.get('section', '')).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                    
                    opt_fields_data.append([field_name, field_type, field_desc, field_section])
                
                opt_fields_table = Table(opt_fields_data, colWidths=[1.5*inch, 1*inch, 2*inch, 1.5*inch])
                opt_fields_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.darkblue),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, -1), 8),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                    ('BACKGROUND', (0, 1), (-1, -1), colors.lightblue),
                    ('GRID', (0, 0), (-1, -1), 1, colors.black)
                ]))
                pdf_story.append(opt_fields_table)
                pdf_story.append(Spacer(1, 15))
        
        # Supporting documents
        if form_data.get('supporting_documents'):
            pdf_story.append(Paragraph("Supporting Documents", pdf_styles['Heading2']))
            pdf_story.append(Spacer(1, 12))
            
            for doc in form_data['supporting_documents']:
                safe_doc = str(doc).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                pdf_story.append(Paragraph(f"• {safe_doc}", pdf_styles['Normal']))
            pdf_story.append(Spacer(1, 12))
        
        # Build PDF with explicit document reference
        pdf_document.build(pdf_story)
        
        # Get the PDF content
        pdf_data = pdf_buffer.getvalue()
        pdf_buffer.close()
        
        # Also save to file system for backup
        form_id = form_data.get("form_id", "").replace(" ", "_").replace("/", "_")
        if not form_id:
            form_id = form_data.get("form_name", "unknown").replace(" ", "_").replace("/", "_")
        
        backup_filename = f"data/exports/pdf/{form_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        with open(backup_filename, 'wb') as f:
            f.write(pdf_data)
        
        return pdf_data, backup_filename
        
    except Exception as e:
        st.error(f"Failed to export to PDF: {str(e)}")
        st.error(f"Error details: {traceback.format_exc()}")
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
    
    # All fields section (updated from required_fields)
    st.subheader("📋 All Form Fields")
    
    if "all_fields" not in form_data:
        form_data["all_fields"] = []
    
    # Add new field button
    if st.button("➕ Add New Field", key="add_new_field_btn"):
        form_data["all_fields"].append({
            "name": "",
            "type": "text",
            "description": "",
            "required": False,
            "optional": True,
            "section": "",
            "line_number": "",
            "instructions": ""
        })
    
    # Edit existing fields
    fields_to_remove = []
    field_types = ["text", "number", "date", "email", "phone", "checkbox", "select", "textarea", "signature", "file", "url"]
    
    # Display field statistics
    total_fields = len(form_data["all_fields"])
    required_count = sum(1 for f in form_data["all_fields"] if f.get('required', False))
    optional_count = total_fields - required_count
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Fields", total_fields)
    with col2:
        st.metric("Required Fields", required_count)
    with col3:
        st.metric("Optional Fields", optional_count)
    
    for i, field in enumerate(form_data["all_fields"]):
        field_status = "🔴 Required" if field.get('required', False) else "🔵 Optional"
        with st.expander(f"Field {i+1}: {field.get('name', 'Unnamed')} ({field_status})"):
            col1, col2, col3 = st.columns([2, 1, 1])
            
            with col1:
                field["name"] = st.text_input(f"Field Name {i+1}", value=field.get("name", ""), key=f"field_name_{i}")
                field["description"] = st.text_input(f"Description {i+1}", value=field.get("description", ""), key=f"field_desc_{i}")
                field["section"] = st.text_input(f"Section {i+1}", value=field.get("section", ""), key=f"field_section_{i}")
            
            with col2:
                # Fix the field type selection issue
                current_type = field.get("type", "text")
                if current_type not in field_types:
                    current_type = "text"  # Default to text if type is not in list
                
                field["type"] = st.selectbox(
                    f"Type {i+1}",
                    field_types,
                    index=field_types.index(current_type),
                    key=f"field_type_{i}"
                )
                
                field["line_number"] = st.text_input(f"Line # {i+1}", value=field.get("line_number", ""), key=f"field_line_{i}")
            
            with col3:
                field["required"] = st.checkbox(f"Required {i+1}", value=field.get("required", False), key=f"field_req_{i}")
                field["optional"] = not field["required"]  # Auto-set opposite
            
            field["instructions"] = st.text_area(f"Instructions {i+1}", value=field.get("instructions", ""), height=80, key=f"field_inst_{i}")
            
            if st.button(f"🗑️ Remove", key=f"remove_field_{i}"):
                fields_to_remove.append(i)
    
    # Remove fields marked for deletion
    for i in reversed(fields_to_remove):
        form_data["all_fields"].pop(i)
    
    # Supporting documents section
    st.subheader("📎 Supporting Documents")
    
    if "supporting_documents" not in form_data:
        form_data["supporting_documents"] = []
    
    # Add new document
    new_doc = st.text_input("Add Supporting Document")
    if st.button("➕ Add Document", key="add_document_btn") and new_doc:
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
            data = json.load(f)
            
        # Handle backward compatibility - convert required_fields to all_fields
        if "required_fields" in data and "all_fields" not in data:
            data["all_fields"] = data["required_fields"]
            del data["required_fields"]
        
        return data
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
            
            # Handle backward compatibility
            all_fields = form_data.get("all_fields", form_data.get("required_fields", []))
            total_fields = len(all_fields)
            required_fields = sum(1 for f in all_fields if f.get('required', False))
            
            forms_data.append({
                "Form Name": form_data.get("form_name", "Unknown"),
                "Form ID": form_data.get("form_id", ""),
                "Authority": form_data.get("governing_authority", ""),
                "Total Fields": total_fields,
                "Required": required_fields,
                "Optional": total_fields - required_fields,
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
                if st.button("👁️ View/Edit", key=f"view_edit_{selected_form}"):
                    form_data = load_form_data(f"data/forms/{selected_form}")
                    if form_data:
                        st.session_state.current_form_data = form_data
                        st.session_state.editing_form = True
                        st.rerun()
            
            with col2:
                if st.button("📊 Export Excel", key=f"export_excel_{selected_form}"):
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
                if st.button("📄 Export PDF", key=f"export_pdf_{selected_form}"):
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
                if st.button("🗑️ Delete", type="secondary", key=f"delete_{selected_form}"):
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
            
            if selected_tavily_log and st.button("View Tavily Log", key="view_tavily_log_btn"):
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
            
            if selected_llm_log and st.button("View LLM Log", key="view_llm_log_btn"):
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
        if st.button("🗑️ Clear All Logs", key="clear_logs_btn"):
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
    
    # All fields (updated from required_fields)
    if form_data.get("all_fields"):
        st.subheader("📋 All Form Fields")
        
        # Field statistics
        all_fields = form_data["all_fields"]
        total_fields = len(all_fields)
        required_fields = [f for f in all_fields if f.get('required', False)]
        optional_fields = [f for f in all_fields if not f.get('required', False)]
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Fields", total_fields)
        with col2:
            st.metric("Required Fields", len(required_fields))
        with col3:
            st.metric("Optional Fields", len(optional_fields))
        
        # Display fields in tabs
        tab1, tab2, tab3 = st.tabs(["All Fields", "Required Only", "Optional Only"])
        
        with tab1:
            if all_fields:
                fields_df = pd.DataFrame(all_fields)
                st.dataframe(fields_df, use_container_width=True)
        
        with tab2:
            if required_fields:
                req_df = pd.DataFrame(required_fields)
                st.dataframe(req_df, use_container_width=True)
            else:
                st.info("No required fields found.")
        
        with tab3:
            if optional_fields:
                opt_df = pd.DataFrame(optional_fields)
                st.dataframe(opt_df, use_container_width=True)
            else:
                st.info("No optional fields found.")
    
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
        
        # Enhanced validation metrics
        col1, col2, col3 = st.columns(3)
        with col1:
            score = validation_result.get("completeness_score", 0)
            st.metric("Completeness Score", f"{score}/100")
        with col2:
            total_found = validation_result.get("total_fields_found", 0)
            st.metric("Fields Found", total_found)
        with col3:
            missing_likely = validation_result.get("missing_fields_likely", [])
            st.metric("Likely Missing", len(missing_likely))
        
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
        
        # Likely missing fields
        if missing_likely:
            st.subheader("🔍 Likely Missing Fields")
            for missing_field in missing_likely:
                st.write(f"• {missing_field}")
        
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
    
    # Initialize APIs with improved error handling
    openai_client, tavily_api_key = init_apis()
    
    if not openai_client or not tavily_api_key:
        st.error("❌ Failed to initialize APIs. Please check your API keys.")
        st.info("💡 Make sure your secrets.toml file contains valid API keys and you have sufficient quota.")
        st.stop()
    
    # Sidebar navigation
    st.sidebar.title("📋 Form Intelligence Platform")
    
    # Add API status indicator
    st.sidebar.subheader("🔌 API Status")
    if openai_client:
        st.sidebar.success("✅ OpenAI Connected")
    else:
        st.sidebar.error("❌ OpenAI Disconnected")
    
    if tavily_api_key:
        st.sidebar.success("✅ Tavily Connected")
    else:
        st.sidebar.error("❌ Tavily Disconnected")
    
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
        st.title("🔍 Comprehensive Form Intelligence Extractor")
        st.markdown("Enter a form name to automatically extract **ALL fields** (required and optional) with comprehensive form information.")
        
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
            
            st.info("💡 **Tip**: This tool extracts ALL fields from forms - both required and optional fields will be captured!")
            
            if st.button("🚀 Extract Complete Form Information", type="primary"):
                if form_name:
                    with st.spinner("🔍 Searching for comprehensive form information..."):
                        # Query Tavily API
                        tavily_results = query_tavily_api(form_name, tavily_api_key)
                        
                        if "error" in tavily_results:
                            st.error(f"❌ Search failed: {tavily_results['error']}")
                        else:
                            st.success("✅ Search completed!")
                            
                            # Extract structured data using OpenAI
                            with st.spinner("🤖 Extracting ALL form fields and data..."):
                                form_data = extract_form_data(form_name, tavily_results, openai_client)
                                
                                if form_data:
                                    st.session_state.current_form_data = form_data
                                    st.session_state.extraction_completed = True
                                    st.success("✅ Complete form data extracted successfully!")
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
        The Form Intelligence Platform is an AI-powered tool designed to automatically extract,validate, and manage **comprehensive information** about various forms and documents, capturing **ALL fields** whether required or optional.
        
        ## 🚀 Features
        - **🔍 Complete Field Extraction**: Captures ALL fields from forms - required, optional, and everything in between
        - **🤖 AI-Powered Validation**: Uses OpenAI to validate and audit form data quality and completeness
        - **📊 Multiple Export Formats**: Export to JSON, Excel, and PDF formats with complete field information
        - **📁 Form Management**: Save, edit, and manage extracted form data with full field details
        - **📊 System Logging**: Track all API calls and system operations
        - **🔧 Data Editing**: Manual editing and refinement of extracted data with field categorization
        
        ## 🛠️ Technology Stack
        - **Streamlit**: Web application framework
        - **OpenAI GPT-4**: AI model for comprehensive data extraction and validation
        - **Tavily API**: Web search and information retrieval
        - **ReportLab**: PDF generation with field categorization
        - **XlsxWriter**: Excel file generation with complete field data
        - **Pandas**: Data manipulation and analysis
        
        ## 📝 Usage Instructions
        1. **Extract Form**: Enter a form name to automatically extract ALL field information
        2. **Validate**: Use AI validation to check data quality and field completeness
        3. **Edit**: Manually refine and edit extracted data with field categorization
        4. **Save**: Store complete form data for future reference
        5. **Export**: Generate reports in various formats with all field details
        6. **Manage**: View and manage all saved forms with field statistics
        
        ## 🔒 Data Security
        - All data is stored locally
        - API keys are securely managed
        - No sensitive information is transmitted unnecessarily
        - Complete audit trail through system logs
        
        ## 📞 Support
        For technical support or feature requests, please contact the development team.
        """)
    
    elif page == "Edit Form":
        st.title("📝 Edit Complete Form Data")
        
        if st.session_state.current_form_data:
            # Display edit form
            updated_form_data = display_editable_form(st.session_state.current_form_data)
            
            # Action buttons
            col1, col2, col3, col4 = st.columns(4)

            with col1:
                if st.button("💾 Save Changes", key="save_changes_btn"):
                    filename = save_form_data(updated_form_data)
                    if filename:
                        st.success(f"✅ Form saved successfully!")
                        st.session_state.current_form_data = updated_form_data

            with col2:
                if st.button("🔍 Re-validate", key="revalidate_btn"):
                    with st.spinner("🤖 Validating complete form data..."):
                        validation_result = validate_form_data(updated_form_data, openai_client)
                        st.session_state.validation_result = validation_result
                        
                        if validation_result:
                            st.subheader("📊 Validation Results")
                            
                            # Enhanced validation metrics
                            col1, col2, col3 = st.columns(3)
                            with col1:
                                score = validation_result.get("completeness_score", 0)
                                st.metric("Completeness Score", f"{score}/100")
                            with col2:
                                total_found = validation_result.get("total_fields_found", 0)
                                st.metric("Fields Found", total_found)
                            with col3:
                                missing_likely = validation_result.get("missing_fields_likely", [])
                                st.metric("Likely Missing", len(missing_likely))
                            
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
                if st.button("📊 Export Excel", key="edit_export_excel_btn"):
                    with st.spinner("Creating Excel file..."):
                        excel_data, filename = export_to_excel(updated_form_data)
                        if excel_data:
                            st.success(f"✅ Excel file ready for download!")
                            st.download_button(
                                label="📥 Download Excel",
                                data=excel_data,
                                file_name=f"{updated_form_data.get('form_name', 'form')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                key="edit_download_excel_btn"
                            )

            with col4:
                if st.button("🔙 Back to Extract", key="back_to_extract_btn"):
                    st.session_state.editing_form = False
                    st.rerun()
        else:
            st.warning("⚠️ No form data to edit")
            if st.button("🔙 Back to Extract"):
                st.session_state.editing_form = False
                st.rerun()

if __name__ == "__main__":
    main()
