from flask import Flask, request, jsonify
import logging
import os
import requests
import yaml
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Disable SSL warnings for GLPI
requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)


class GLPIClient:
    """Simple GLPI REST API Client for ticket creation"""
    
    def __init__(self, url: str, app_token: str, user_token: str):
        self.url = url
        self.app_token = app_token
        self.user_token = user_token
        self.session_token = None
        self.session = requests.Session()
        self.session.verify = False
        # Load assignment group mapping from YAML
        self.assignment_mapping = self._load_assignment_mapping()
    
    def _load_assignment_mapping(self) -> dict:
        """Load ServiceNow sys_id to GLPI group mapping from YAML file"""
        mapping_file = 'assignment_group_mapping.yaml'
        sys_id_to_glpi = {}
        
        try:
            if os.path.exists(mapping_file):
                with open(mapping_file, 'r') as f:
                    data = yaml.safe_load(f)
                    mappings = data.get('assignment_group_mappings', [])
                    for mapping in mappings:
                        snow_sys_id = mapping.get('servicenow_group')
                        glpi_group = mapping.get('glpi_group')
                        if snow_sys_id and glpi_group:
                            sys_id_to_glpi[snow_sys_id] = glpi_group
                logger.info(f"Loaded {len(sys_id_to_glpi)} assignment group mappings from {mapping_file}")
            else:
                logger.warning(f"Assignment mapping file not found: {mapping_file}")
        except Exception as e:
            logger.error(f"Failed to load assignment mapping: {e}")
        
        return sys_id_to_glpi
    
    def get_glpi_group_id(self, group_name: str) -> int:
        """Search for GLPI group ID by name"""
        if not self.session_token:
            self.init_session()
        
        headers = {
            "App-Token": self.app_token,
            "Session-Token": self.session_token,
            "Content-Type": "application/json"
        }
        
        try:
            # Get all groups and search locally (more reliable than search API with special chars)
            response = self.session.get(
                f"{self.url}/Group?range=0-1000",
                headers=headers
            )
            
            if response.status_code == 200:
                groups = response.json()
                for group in groups:
                    if group.get('name') == group_name:
                        group_id = group.get('id')
                        logger.info(f"Found GLPI group ID {group_id} for '{group_name}'")
                        return group_id
            
            logger.warning(f"GLPI group not found: {group_name}")
            return None
            
        except Exception as e:
            logger.error(f"Error searching for GLPI group '{group_name}': {e}")
            return None
    
    def init_session(self):
        """Initialize GLPI session"""
        headers = {
            "App-Token": self.app_token,
            "Authorization": f"user_token {self.user_token}",
            "Content-Type": "application/json"
        }
        
        logger.info("Initializing GLPI session...")
        response = self.session.get(f"{self.url}/initSession", headers=headers)
        response.raise_for_status()
        
        self.session_token = response.json()["session_token"]
        logger.info(f"✓ GLPI session initialized: {self.session_token}")
        return self.session_token
    
    def kill_session(self):
        """Close GLPI session"""
        if not self.session_token:
            return
        
        headers = {
            "App-Token": self.app_token,
            "Session-Token": self.session_token
        }
        
        self.session.get(f"{self.url}/killSession", headers=headers)
        logger.info("GLPI session closed")
    
    def create_ticket(self, ticket_data: dict) -> dict:
        """Create GLPI ticket with full field support"""
        if not self.session_token:
            self.init_session()
        
        headers = {
            "App-Token": self.app_token,
            "Session-Token": self.session_token,
            "Content-Type": "application/json"
        }
        
        payload = {"input": ticket_data}
        
        logger.info(f"Creating GLPI ticket: {ticket_data.get('name', 'N/A')[:50]}")
        logger.debug(f"Full payload: {payload}")
        
        response = self.session.post(
            f"{self.url}/Ticket",
            headers=headers,
            json=payload
        )
        
        if response.status_code >= 400:
            logger.error(f"GLPI Error: {response.text}")
            response.raise_for_status()
        
        result = response.json()
        ticket_id = result.get("id")
        logger.info(f"✓ GLPI ticket created: {ticket_id}")
        
        return result


# Initialize GLPI client
glpi_client = GLPIClient(
    url=os.getenv("GLPI_URL"),
    app_token=os.getenv("GLPI_APP_TOKEN"),
    user_token=os.getenv("GLPI_USER_TOKEN")
)


@app.post('/api/data')
def handle_post_request():
    """
    Endpoint to accept POST requests and create GLPI tickets.
    
    Expected JSON fields:
    - name (string: ticket title) - REQUIRED
    - content (string: ticket description in HTML or plain text) - REQUIRED
    - priority (integer: 2=Low, 3=Medium, 4=High, 5=Very High) - OPTIONAL, default=3
      Priority automatically maps to urgency/impact:
      * priority=2 → urgency=2, impact=2 (Low)
      * priority=3 → urgency=3, impact=3 (Medium)
      * priority=4 → urgency=4, impact=3 (High)
      * priority=5 → urgency=4, impact=4 (Very High)
    - assign_sys_id (string: ServiceNow assignment group sys_id) - OPTIONAL
    - internal_reference_id (string: external reference ID, maps to kyn_correlation_id) - OPTIONAL
    - internal_reference_number (string: external reference number, maps to kyn_correlation_display) - OPTIONAL
    - type (integer: 1=incident, 2=request) - OPTIONAL, default=1
    - status (integer: 1=New, 2=Processing, etc.) - OPTIONAL, default=1
    """
    # Check if request contains JSON data
    if not request.is_json:
        logger.warning("Received non-JSON request")
        return jsonify({'error': 'Content-Type must be application/json'}), 415
    
    # Get JSON data from request
    data = request.get_json()
    
    # Extract the required fields
    name = data.get('name')
    content = data.get('content')
    priority = data.get('priority', 3)  # Default to Medium (3)
    assign_sys_id = data.get('assign_sys_id')
    internal_reference_id = data.get('internal_reference_id')  # Maps to kyn_correlation_id
    internal_reference_number = data.get('internal_reference_number')  # Maps to kyn_correlation_display
    ticket_type = data.get('type', 1)   # Default to incident
    status = data.get('status', 1)      # Default to New
    
    # Map priority to urgency and impact based on GLPI priority matrix
    # Priority 2 (Low) → urgency=2, impact=2
    # Priority 3 (Medium) → urgency=3, impact=3
    # Priority 4 (High) → urgency=4, impact=3
    # Priority 5 (Very High) → urgency=4, impact=4
    priority_mapping = {
        2: {"urgency": 2, "impact": 2},  # Low
        3: {"urgency": 3, "impact": 3},  # Medium
        4: {"urgency": 4, "impact": 3},  # High
        5: {"urgency": 4, "impact": 4},  # Very High
    }
    
    # Get urgency and impact from priority mapping, default to medium if invalid
    mapped_values = priority_mapping.get(priority, {"urgency": 3, "impact": 3})
    urgency = mapped_values["urgency"]
    impact = mapped_values["impact"]
    
    # Log the received data
    logger.info("=" * 80)
    logger.info("Received POST request at /api/data")
    logger.info(f"Name: {name}")
    logger.info(f"Content: {content[:100] if content else 'N/A'}...")
    logger.info(f"Priority (requested): {priority}")
    logger.info(f"Urgency (calculated): {urgency}")
    logger.info(f"Impact (calculated): {impact}")
    logger.info(f"Assignment sys_id: {assign_sys_id}")
    logger.info(f"Internal Reference ID: {internal_reference_id}")
    logger.info(f"Internal Reference Number: {internal_reference_number}")
    logger.info(f"Type: {ticket_type}")
    logger.info(f"Status: {status}")
    logger.info("=" * 80)
    
    # Validate required fields
    if not name:
        return jsonify({
            'success': False,
            'error': 'name is required'
        }), 400
    
    if not content:
        return jsonify({
            'success': False,
            'error': 'content is required'
        }), 400
    
    try:
        # Build GLPI ticket payload (direct GLPI format)
        # Ensure content is proper HTML
        if content.startswith('<'):
            # Already HTML formatted
            ticket_content = content
        else:
            # Wrap plain text in paragraph tags
            ticket_content = f"<p>{content}</p>"
        
        glpi_ticket_data = {
            "name": name,
            "content": ticket_content,
            "priority": int(priority),
            "urgency": int(urgency),
            "impact": int(impact),
            "type": int(ticket_type),
            "status": int(status),
        }
        
        # Handle assign_sys_id - lookup GLPI group from ServiceNow sys_id
        glpi_group_id = None
        if assign_sys_id:
            logger.info(f"Assignment sys_id requested: {assign_sys_id}")
            
            # Look up GLPI group from mapping
            glpi_group_name = glpi_client.assignment_mapping.get(assign_sys_id)
            
            if glpi_group_name:
                logger.info(f"Found GLPI group mapping: {assign_sys_id} -> {glpi_group_name}")
                # Get the GLPI group ID
                glpi_group_id = glpi_client.get_glpi_group_id(glpi_group_name)
                if glpi_group_id:
                    glpi_ticket_data["_groups_id_assign"] = glpi_group_id
                    logger.info(f"Assigning ticket to GLPI group ID: {glpi_group_id}")
            else:
                logger.warning(f"No GLPI group mapping found for sys_id: {assign_sys_id}")
        
        # Do NOT set entities_id - let GLPI use the user's default active entity (1757)
        # This avoids permission errors
        logger.info("Using user's default active entity (no explicit entities_id)")
        
        # Add correlation fields if provided
        if internal_reference_id:
            glpi_ticket_data["kyn_correlation_id"] = internal_reference_id
            logger.info(f"Set kyn_correlation_id: {internal_reference_id}")
        
        if internal_reference_number:
            glpi_ticket_data["kyn_correlation_display"] = internal_reference_number
            logger.info(f"Set kyn_correlation_display: {internal_reference_number}")
        
        logger.info(f"Creating GLPI ticket with data: {glpi_ticket_data}")
        
        # Create ticket in GLPI
        result = glpi_client.create_ticket(glpi_ticket_data)
        
        glpi_ticket_id = result.get('id')
        glpi_ticket_identifier = f"IN{glpi_ticket_id}"
        
        # Determine GLPI URL based on current instance
        glpi_base_url = os.getenv("GLPI_URL", "").replace("/apirest.php", "")
        ticket_url = f"{glpi_base_url}/front/ticket.form.php?id={glpi_ticket_id}"
        
        # Return success response
        return jsonify({
            'success': True,
            'message': 'Incident received',
            'glpi_ticket_id': glpi_ticket_id,
            'glpi_ticket_identifier': glpi_ticket_identifier,
            'glpi_ticket_url': ticket_url,
            'kyn_correlation_id': internal_reference_id,
            'kyn_correlation_display': internal_reference_number
        }), 201
        
    except Exception as e:
        logger.error(f"Failed to create GLPI ticket: {type(e).__name__}: {e}")
        return jsonify({
            'success': False,
            'error': f'Failed to create GLPI ticket: {str(e)}'
        }), 500


@app.route('/')
def index():
    """Health check endpoint"""
    return jsonify({
        'status': 'running',
        'message': 'API is active - Creates tickets in GLPI',
        'endpoint': '/api/data (POST)',
        'glpi_url': os.getenv("GLPI_URL")
    })


if __name__ == '__main__':
    logger.info("=" * 80)
    logger.info("Starting Flask API server...")
    logger.info(f"GLPI URL: {os.getenv('GLPI_URL')}")
    logger.info("POST endpoint available at: http://127.0.0.1:5000/api/data")
    logger.info("Tickets will be created in GLPI automatically")
    logger.info("=" * 80)
    
    try:
        app.run(debug=False, host='0.0.0.0', port=5000)
    finally:
        # Clean up GLPI session on shutdown
        try:
            glpi_client.kill_session()
        except:
            pass
