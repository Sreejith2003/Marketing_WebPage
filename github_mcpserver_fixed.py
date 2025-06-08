import os
import json
import re
import asyncio
import base64
import pathlib
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from github import Github, GithubException
from pydantic import BaseModel
from typing import Dict, Any
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = FastAPI()

# Initialize GitHub client with Personal Access Token
GITHUB_PAT = os.getenv("Github_PAT_API")
if not GITHUB_PAT:
    raise ValueError("Github_PAT_API environment variable not set")
github_client = Github(GITHUB_PAT)

# MCP Tools Definition
tools = [
    {
        "name": "push_project",
        "description": "Push an entire local project directory to a GitHub repository.",
        "inputs": [
            {
                "name": "repo_name",
                "type": "string",
                "description": "The name of the repository (format: owner/repo)",
                "required": True
            },
            {
                "name": "project_path",
                "type": "string",
                "description": "The absolute path to the local project directory",
                "required": True
            },
            {
                "name": "commit_message",
                "type": "string",
                "description": "The commit message for the upload",
                "required": False
            }
        ],
        "output": {
            "type": "string",
            "description": "Success message or error message"
        }
    }
]

class ToolInvocation(BaseModel):
    tool: str
    inputs: Dict[str, Any]

@app.post("/mcp/invoke")
async def invoke_tool(invocation: ToolInvocation):
    try:
        if invocation.tool == "push_project":
            repo_name = invocation.inputs.get("repo_name")
            project_path = invocation.inputs.get("project_path")
            commit_message = invocation.inputs.get("commit_message", "Push project via MCP")

            if not all([repo_name, project_path]):
                raise HTTPException(status_code=400, detail="repo_name and project_path are required")

            if not os.path.isdir(project_path):
                raise HTTPException(status_code=400, detail=f"Directory {project_path} does not exist")

            try:
                # Get or create repository
                try:
                    repo = github_client.get_repo(repo_name)
                except GithubException as e:
                    if e.status == 404:
                        user = github_client.get_user()
                        repo_name_short = repo_name.split('/')[-1]
                        repo = user.create_repo(name=repo_name_short)
                    else:
                        raise e

                # Walk through project directory
                success_files = []
                failed_files = []
                project_dir = pathlib.Path(project_path)
                
                # Files/directories to ignore
                ignore_patterns = {'.git', '__pycache__', '.env', 'node_modules', '.pytest_cache'}
                
                for file_path in project_dir.rglob('*'):
                    if not file_path.is_file() or any(p in file_path.parts for p in ignore_patterns):
                        continue
                        
                    try:
                        # Get relative path for GitHub
                        rel_path = str(file_path.relative_to(project_dir)).replace('\\', '/')
                        
                        # Read file content
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                            
                        try:
                            # Check if file exists
                            file = repo.get_contents(rel_path)
                            # Update existing file
                            repo.update_file(
                                path=rel_path,
                                message=f"{commit_message}: Update {rel_path}",
                                content=content,
                                sha=file.sha
                            )
                        except GithubException as e:
                            if e.status == 404:
                                # Create new file
                                repo.create_file(
                                    path=rel_path,
                                    message=f"{commit_message}: Add {rel_path}",
                                    content=content
                                )
                            else:
                                raise e
                                
                        success_files.append(rel_path)
                        
                    except Exception as e:
                        failed_files.append(f"{rel_path}: {str(e)}")
                        continue

                result = {
                    "status": "success",
                    "message": f"Project pushed to {repo_name}",
                    "success_files": success_files,
                    "failed_files": failed_files
                }
                
                return result

            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Error pushing project: {str(e)}")
        
        else:
            raise HTTPException(status_code=400, detail="Unknown tool")
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="debug")
