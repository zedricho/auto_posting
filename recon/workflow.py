"""Workflow Overview: data model and persistence for operations flow diagram."""

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any


# Team color scheme matching the hand-drawn diagram
TEAM_COLORS = {
    "planners": "#FFB6C1",         # Pink - Planners
    "operations": "#FFFF99",       # Yellow - Log Team
    "management": "#90EE90",       # Green - Management
    "floor_managers": "#87CEEB",   # Blue - Floor Managers (FM)
    "other": "#D3D3D3",            # Gray - Other roles
}

# Darker versions for key team members
TEAM_COLORS_DARK = {
    "planners": "#FF91A4",         # Darker Pink
    "operations": "#FFD700",       # Darker Yellow/Gold
    "management": "#32CD32",       # Darker Green
    "floor_managers": "#4A9FD4",   # Darker Blue
    "other": "#A9A9A9",            # Darker Gray
}

TEAM_LABELS = {
    "planners": "Planners",
    "operations": "Log Team",
    "management": "Management",
    "floor_managers": "Floor Managers (FM)",
    "other": "Other",
}

# Key team member nodes that should be highlighted darker
KEY_TEAM_NODES = {
    "planners": "planners",        # The Planners node
    "operations": "log_team",      # The Log Team node (renamed from log/team)
    "management": "management",    # The Management node
    "floor_managers": "fm",        # The FM node
}


@dataclass
class WorkflowNode:
    """A single node in the workflow diagram."""
    id: str
    label: str
    team: str  # One of TEAM_COLORS keys
    description: str = ""
    notes: List[str] = field(default_factory=list)
    row: int = 0  # Grid row position
    col: int = 0  # Grid column position
    connections: List[str] = field(default_factory=list)  # IDs of connected nodes
    is_key_member: bool = False  # If True, use darker color (key team member)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkflowNode":
        # Handle older data without is_key_member
        if "is_key_member" not in data:
            data["is_key_member"] = False
        return cls(**data)


@dataclass
class WorkflowData:
    """Complete workflow diagram data."""
    nodes: List[WorkflowNode] = field(default_factory=list)
    last_updated: str = ""
    version: str = "1.0"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nodes": [n.to_dict() for n in self.nodes],
            "last_updated": self.last_updated,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkflowData":
        nodes = [WorkflowNode.from_dict(n) for n in data.get("nodes", [])]
        return cls(
            nodes=nodes,
            last_updated=data.get("last_updated", ""),
            version=data.get("version", "1.0"),
        )

    def get_node(self, node_id: str) -> Optional[WorkflowNode]:
        """Get a node by ID."""
        for node in self.nodes:
            if node.id == node_id:
                return node
        return None

    def add_node(self, node: WorkflowNode) -> None:
        """Add a new node."""
        self.nodes.append(node)
        self.last_updated = datetime.now().isoformat()

    def update_node(self, node_id: str, **kwargs) -> bool:
        """Update a node's properties."""
        node = self.get_node(node_id)
        if node is None:
            return False
        for key, value in kwargs.items():
            if hasattr(node, key):
                setattr(node, key, value)
        self.last_updated = datetime.now().isoformat()
        return True

    def add_note(self, node_id: str, note: str) -> bool:
        """Add a note to a node."""
        node = self.get_node(node_id)
        if node is None:
            return False
        node.notes.append(note)
        self.last_updated = datetime.now().isoformat()
        return True

    def delete_node(self, node_id: str) -> bool:
        """Delete a node and remove references to it."""
        node = self.get_node(node_id)
        if node is None:
            return False
        self.nodes.remove(node)
        # Remove connections to this node
        for other_node in self.nodes:
            if node_id in other_node.connections:
                other_node.connections.remove(node_id)
        self.last_updated = datetime.now().isoformat()
        return True


# Default workflow data path
WORKFLOW_FILE = Path(__file__).parent.parent / "workflow_data.json"


def load_workflow(filepath: Optional[Path] = None) -> WorkflowData:
    """Load workflow data from JSON file."""
    filepath = filepath or WORKFLOW_FILE
    if not filepath.exists():
        return get_default_workflow()
    try:
        with open(filepath, "r") as f:
            data = json.load(f)
        return WorkflowData.from_dict(data)
    except (json.JSONDecodeError, KeyError):
        return get_default_workflow()


def save_workflow(data: WorkflowData, filepath: Optional[Path] = None) -> None:
    """Save workflow data to JSON file."""
    filepath = filepath or WORKFLOW_FILE
    data.last_updated = datetime.now().isoformat()
    with open(filepath, "w") as f:
        json.dump(data.to_dict(), f, indent=2)


def get_default_workflow() -> WorkflowData:
    """Create default workflow matching the hand-drawn diagram."""
    nodes = [
        # === LEFT SIDE: Sales & Planning ===
        WorkflowNode(
            id="sales",
            label="Sales",
            team="other",
            description="Initial client contact and event booking",
            row=0, col=0,
            connections=["initial_event"],
        ),
        WorkflowNode(
            id="initial_event",
            label="Initial Event",
            team="planners",
            description="New event created in system",
            row=1, col=0,
            connections=["delphi"],
        ),
        WorkflowNode(
            id="delphi",
            label="Delphi",
            team="planners",
            description="Delphi event management system",
            row=2, col=0,
            connections=["planners", "daily_updates"],
        ),
        WorkflowNode(
            id="planners",
            label="Planners",
            team="planners",
            description="Event planning team - add info to events",
            row=3, col=0,
            connections=["export_eo"],
            is_key_member=True,  # Highlighted darker
        ),
        WorkflowNode(
            id="daily_updates",
            label="Daily/Weekly Updates",
            team="planners",
            description="Regular updates and communications",
            row=3, col=1,
            connections=["delphi"],
        ),
        WorkflowNode(
            id="export_eo",
            label="Export to Final EO",
            team="planners",
            description="Export finalized Event Order",
            row=4, col=0,
            connections=["rapid_go"],
        ),

        # === CENTER-RIGHT: Operations / Log Team ===
        WorkflowNode(
            id="rapid_go",
            label="Rapid/Go",
            team="operations",
            description="Rapid/Go system for event management",
            row=1, col=2,
            connections=["log_team", "linen_orders", "mobile_doc"],
        ),
        WorkflowNode(
            id="log_team",
            label="Log Team",
            team="operations",
            description="Operations logging and team coordination",
            row=2, col=2,
            connections=["packing_sheets", "room_flips", "asset_movement"],
            is_key_member=True,  # Highlighted darker
        ),
        WorkflowNode(
            id="linen_orders",
            label="Linen Orders",
            team="operations",
            description="Linen and fabric requirements",
            row=2, col=3,
        ),
        WorkflowNode(
            id="mobile_doc",
            label="Mobile Doc",
            team="operations",
            description="Mobile documentation system",
            row=2, col=4,
        ),
        WorkflowNode(
            id="packing_sheets",
            label="Packing Sheets",
            team="operations",
            description="Equipment and supplies packing lists",
            row=3, col=2,
        ),
        WorkflowNode(
            id="room_flips",
            label="Room Flips",
            team="operations",
            description="Room setup changes between events",
            row=3, col=3,
        ),
        WorkflowNode(
            id="asset_movement",
            label="Asset Movement",
            team="operations",
            description="Equipment and furniture logistics",
            row=3, col=4,
        ),

        # === CENTER: Management ===
        WorkflowNode(
            id="management",
            label="Management",
            team="management",
            description="Management oversight via WBN",
            row=5, col=1,
            connections=["roster_build"],
            is_key_member=True,  # Highlighted darker
        ),
        WorkflowNode(
            id="roster_build",
            label="Roster Build",
            team="management",
            description="Staff rostering and labour percentage planning",
            row=6, col=1,
            connections=["plan_wtc"],
        ),
        WorkflowNode(
            id="plan_wtc",
            label="Plan (WTC)",
            team="management",
            description="Workforce planning via WTC",
            row=7, col=1,
            connections=["poa", "fm"],
        ),
        WorkflowNode(
            id="poa",
            label="POA",
            team="management",
            description="Plan of Action coordination",
            row=7, col=2,
            connections=["fm"],
        ),

        # === BOTTOM LEFT: Floor Managers (FM) ===
        WorkflowNode(
            id="cross_checks",
            label="Cross Checks",
            team="floor_managers",
            description="Verification and cross-checking processes",
            row=6, col=0,
            connections=["postings"],
        ),
        WorkflowNode(
            id="postings",
            label="Postings",
            team="floor_managers",
            description="Financial postings and allocations",
            row=7, col=0,
            connections=["fm", "buildbooks"],
        ),
        WorkflowNode(
            id="fm",
            label="FM",
            team="floor_managers",
            description="Floor Managers - oversee event delivery",
            row=8, col=1,
            connections=["buildbooks", "fix_pay", "roster_issues", "function_report", "opera"],
            is_key_member=True,  # Highlighted darker
        ),
        WorkflowNode(
            id="buildbooks",
            label="Buildbooks/Reallocations",
            team="floor_managers",
            description="Event buildbooks and resource reallocations",
            row=9, col=0,
        ),
        WorkflowNode(
            id="fix_pay",
            label="Fix Pay Issues",
            team="floor_managers",
            description="Payroll corrections and adjustments",
            row=9, col=1,
        ),
        WorkflowNode(
            id="roster_issues",
            label="Roster Issues",
            team="floor_managers",
            description="Staff roster problems and solutions",
            row=9, col=2,
        ),
        WorkflowNode(
            id="function_report",
            label="Function Report",
            team="floor_managers",
            description="Post-event function reporting",
            row=9, col=3,
            connections=["captains"],
        ),
        WorkflowNode(
            id="opera",
            label="Opera",
            team="floor_managers",
            description="Opera PMS integration",
            row=10, col=0,
        ),

        # === BOTTOM RIGHT: Event Delivery ===
        WorkflowNode(
            id="captains",
            label="Captains",
            team="other",
            description="Event captains and team leads",
            row=10, col=3,
            connections=["floor_management"],
        ),
        WorkflowNode(
            id="floor_management",
            label="Floor Management",
            team="other",
            description="Break allocations, set rooms & bars, etc.",
            row=11, col=3,
        ),
    ]

    return WorkflowData(
        nodes=nodes,
        last_updated=datetime.now().isoformat(),
        version="1.0",
    )
