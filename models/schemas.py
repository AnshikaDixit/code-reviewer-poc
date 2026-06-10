from pydantic import BaseModel, Field

class CodeReviewComment(BaseModel):
    file_path: str = Field(description="The path of the file being reviewed")
    line_number: int = Field(description="The approximate line number in the new code")
    issue_type: str = Field(description="Type of issue: Bug, Security, Performance, Best Practice, etc.")
    comment: str = Field(description="The detailed review comment")
    suggestion: str = Field(description="Suggested code fix or improvement")

class CodeReviewResult(BaseModel):
    summary: str = Field(description="Overall summary of the PR and code quality")
    comments: list[CodeReviewComment] = Field(description="List of specific code review findings")
