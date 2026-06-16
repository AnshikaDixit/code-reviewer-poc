from pydantic import BaseModel, Field
from typing import Optional, List

class CodeReviewComment(BaseModel):
    path: str = Field(description="The path of the file being reviewed")
    start_line: Optional[int] = Field(None, description="The starting line number for multi-line comments")
    line: int = Field(description="The absolute integer line number prepended to the valid diff line (e.g., if you see '42: + code', output 42)")
    side: str = Field(description="'RIGHT' for added/modified, 'LEFT' for deleted")
    severity: str = Field(description="critical | high | medium | low | info")
    category: str = Field(description="security | bug | performance | etc.")
    title: str = Field(description="Short imperative summary of the issue")
    description: str = Field(description="What the problem is, why it matters, and the impact")
    suggestion: Optional[str] = Field(None, description="Suggested code fix or improvement")
    confidence: float = Field(description="Confidence score between 0.0 and 1.0")
    owasp: Optional[str] = Field(None, description="OWASP category if security issue")

class SeverityStats(BaseModel):
    critical: int = Field(default=0)
    high: int = Field(default=0)
    medium: int = Field(default=0)
    low: int = Field(default=0)
    info: int = Field(default=0)

class ReviewStats(BaseModel):
    files_reviewed: int
    total_issues: int
    by_severity: SeverityStats

class CodeReviewResult(BaseModel):
    summary: str = Field(description="Overall summary of the PR and code quality")
    verdict: str = Field(description="APPROVE | COMMENT | REQUEST_CHANGES")
    overall_confidence: float
    stats: ReviewStats
    comments: List[CodeReviewComment] = Field(description="List of specific code review findings")
    non_blocking_notes: List[str] = Field(default_factory=list)

class FileTriage(BaseModel):
    filename: str = Field(description="The path of the file being triaged")
    risk_score: float = Field(description="The final risk score for this file, taking into account heuristics and AI analysis. Higher is riskier.")
    reasoning: str = Field(description="Brief reasoning for the assigned risk score")

class TriageResult(BaseModel):
    files: List[FileTriage] = Field(description="List of triaged files with their updated risk scores")

class SummaryReviewResult(BaseModel):
    summary: str = Field(description="High-level risk summary of the entire PR")
    module_risks: List[str] = Field(description="Module-level risk flags (e.g. 'auth/ heavily modified — manual review recommended')")