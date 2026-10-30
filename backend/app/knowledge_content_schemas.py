from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError, model_validator

# Strict schemas for the code_examples and architecture sections and for diagrams (D8: diagrams are data).
# Unknown keys are rejected, so content cannot smuggle styling, URLs or markup into the renderers.

CODE_LANGUAGES = ("python", "javascript", "typescript", "java", "go", "csharp", "c", "cpp", "rust", "php", "ruby", "http", "json", "yaml", "bash")
DIAGRAM_ID_PATTERN = r"^[a-z0-9_-]{1,40}$"
MAX_CODE_EXAMPLES = 6
MAX_CODE_LENGTH = 8000
MAX_DIAGRAMS = 12
MAX_DIAGRAM_NODES = 40
MAX_DIAGRAM_EDGES = 80


def _plain_label(value: str) -> str:
    if "<" in value or ">" in value:
        raise ValueError("Diagram labels must be plain text")
    return value


PlainLabel = Annotated[str, AfterValidator(_plain_label)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, populate_by_name=True)


class CodeExample(_Strict):
    title: str = Field(min_length=1, max_length=200)
    language: Literal[CODE_LANGUAGES]
    vulnerable: str = Field(default="", max_length=MAX_CODE_LENGTH)
    secure: str = Field(default="", max_length=MAX_CODE_LENGTH)
    explanation: str = Field(default="", max_length=MAX_CODE_LENGTH)
    security_control: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def require_code(self):
        if not self.vulnerable and not self.secure:
            raise ValueError("A code example needs vulnerable or secure code")
        return self


class CodeExamplesContent(_Strict):
    items: list[CodeExample] = Field(default_factory=list, max_length=MAX_CODE_EXAMPLES)


class DiagramNode(_Strict):
    id: str = Field(pattern=DIAGRAM_ID_PATTERN)
    label: PlainLabel = Field(min_length=1, max_length=120)
    type: Literal["actor", "service", "datastore", "control", "external"] = "service"
    boundary: str | None = Field(default=None, pattern=DIAGRAM_ID_PATTERN)


class DiagramEdge(_Strict):
    source: str = Field(alias="from", pattern=DIAGRAM_ID_PATTERN)
    target: str = Field(alias="to", pattern=DIAGRAM_ID_PATTERN)
    label: PlainLabel = Field(default="", max_length=120)
    order: int | None = Field(default=None, ge=0, le=1000)


class DiagramBoundary(_Strict):
    id: str = Field(pattern=DIAGRAM_ID_PATTERN)
    label: PlainLabel = Field(min_length=1, max_length=120)


class Diagram(_Strict):
    kind: Literal["architecture", "sequence", "trust_boundary", "attack_path", "flow"] = "flow"
    title: PlainLabel = Field(default="", max_length=120)
    variant: Literal["vulnerable", "secure", "neutral"] = "neutral"
    nodes: list[DiagramNode] = Field(default_factory=list, max_length=MAX_DIAGRAM_NODES)
    edges: list[DiagramEdge] = Field(default_factory=list, max_length=MAX_DIAGRAM_EDGES)
    boundaries: list[DiagramBoundary] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def check_references(self):
        node_ids = [node.id for node in self.nodes]
        if len(set(node_ids)) != len(node_ids):
            raise ValueError("Diagram node ids must be unique")
        boundary_ids = {boundary.id for boundary in self.boundaries}
        if len(boundary_ids) != len(self.boundaries):
            raise ValueError("Diagram boundary ids must be unique")
        for node in self.nodes:
            if node.boundary and node.boundary not in boundary_ids:
                raise ValueError(f"Node {node.id} references an unknown boundary")
        known = set(node_ids)
        for edge in self.edges:
            if edge.source not in known or edge.target not in known:
                raise ValueError("Diagram edges must reference existing nodes")
        return self


class ArchitectureContent(_Strict):
    diagrams: list[Diagram] = Field(default_factory=list, max_length=MAX_DIAGRAMS)


NEW_SECTION_SCHEMAS: dict[str, type[_Strict]] = {"code_examples": CodeExamplesContent, "architecture": ArchitectureContent}
# Actions that write whole section content, as opposed to appending one item.
WHOLE_SECTION_ACTIONS = {"ADD_SECTION", "UPDATE_SECTION"}


def _message(error: ValidationError) -> str:
    first = error.errors()[0]
    location = ".".join(str(part) for part in first["loc"])
    return f"{location}: {first['msg']}" if location else first["msg"]


def _dump(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json", by_alias=True, exclude_none=True)


def validate_diagram(value: Any) -> dict[str, Any]:
    try:
        return _dump(Diagram.model_validate(value))
    except ValidationError as error:
        raise ValueError(f"Invalid diagram: {_message(error)}") from error


def validate_section_content(section_type: str | None, action: str, content: dict[str, Any]) -> dict[str, Any]:
    """Validates proposed content for the structured section types. Raises ValueError; returns normalised content."""
    if section_type in NEW_SECTION_SCHEMAS:
        if action == "ADD_DIAGRAM" and section_type == "architecture":
            return {**content, "diagram": validate_diagram(content.get("diagram", content))} if "diagram" in content else validate_diagram(content)
        if action not in WHOLE_SECTION_ACTIONS:
            raise ValueError(f"Use ADD_SECTION or UPDATE_SECTION for the {section_type} section")
        try:
            return _dump(NEW_SECTION_SCHEMAS[section_type].model_validate(content))
        except ValidationError as error:
            raise ValueError(f"Invalid {section_type} content: {_message(error)}") from error
    if section_type == "how_it_works":
        if action == "ADD_DIAGRAM":
            return {**content, "diagram": validate_diagram(content["diagram"])} if "diagram" in content else validate_diagram(content)
        if action in WHOLE_SECTION_ACTIONS and content.get("diagram") is not None:
            return {**content, "diagram": validate_diagram(content["diagram"])}
    return content


def public_section_content(section_type: str, content: dict[str, Any]) -> dict[str, Any]:
    """Read path: drops diagrams that no longer validate (legacy content) instead of failing, and flags them."""
    if section_type == "how_it_works" and content.get("diagram") is not None:
        try:
            content["diagram"] = validate_diagram(content["diagram"])
        except ValueError:
            content["diagram"] = None
            content["diagram_hidden"] = True
    elif section_type == "architecture":
        diagrams = []
        for diagram in content.get("diagrams") or []:
            try:
                diagrams.append(validate_diagram(diagram))
            except ValueError:
                content["hidden_diagram_count"] = content.get("hidden_diagram_count", 0) + 1
        content["diagrams"] = diagrams
    elif section_type == "code_examples":
        items = []
        for item in content.get("items") or []:
            try:
                items.append(_dump(CodeExample.model_validate(item)))
            except ValidationError:
                content["hidden_item_count"] = content.get("hidden_item_count", 0) + 1
        content["items"] = items
    return content
