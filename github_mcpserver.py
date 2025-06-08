import os
import json
import re
import asyncio
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
        "name": "create_repository",
        "description": "Create a new GitHub repository with the specified name.",
        "inputs": [
            {
                "name": "repo_name",
                "type": "string",
                "description": "The name of the repository to create",
                "required": True
            },
            {
                "name": "private",
                "type": "boolean",
                "description": "Whether the repository should be private (default: false)",
                "required": False
            },
            {
                "name": "initialize_readme",
                "type": "boolean",
                "description": "Whether to initialize the repository with a README (default: false)",
                "required": False
            }
        ],
        "output": {
            "type": "string",
            "description": "URL of the created repository or error message"
        }
    },
    {
        "name": "create_file",
        "description": "Create a new file in a specified GitHub repository.",
        "inputs": [
            {
                "name": "repo_name",
                "type": "string",
                "description": "The name of the repository (format: owner/repo)",
                "required": True
            },
            {
                "name": "file_path",
                "type": "string",
                "description": "The path of the file to create (e.g., src/main.py)",
                "required": True
            },
            {
                "name": "content",
                "type": "string",
                "description": "The content of the file",
                "required": True
            },
            {
                "name": "commit_message",
                "type": "string",
                "description": "The commit message for the file creation",
                "required": False
            }
        ],
        "output": {
            "type": "string",
            "description": "Success message or error message"
        }
    },
    {
        "name": "delete_repository",
        "description": "Delete a specified GitHub repository.",
        "inputs": [
            {
                "name": "repo_name",
                "type": "string",
                "description": "The name of the repository to delete (e.g., my-test-repo)",
                "required": True
            }
        ],
        "output": {
            "type": "string",
            "description": "Success message or error message"
        }
    },
    {
        "name": "delete_file",
        "description": "Delete a file from a specified GitHub repository.",
        "inputs": [
            {
                "name": "repo_name",
                "type": "string",
                "description": "The name of the repository (format: owner/repo)",
                "required": True
            },
            {
                "name": "file_path",
                "type": "string",
                "description": "The path of the file to delete (e.g., notes.txt)",
                "required": True
            },
            {
                "name": "commit_message",
                "type": "string",
                "description": "The commit message for the file deletion",
                "required": False
            }
        ],
        "output": {
            "type": "string",
            "description": "Success message or error message"
        }
    },
    {
        "name": "update_file",
        "description": "Update the content of an existing file in a specified GitHub repository.",
        "inputs": [
            {
                "name": "repo_name",
                "type": "string",
                "description": "The name of the repository (format: owner/repo)",
                "required": True
            },
            {
                "name": "file_path",
                "type": "string",
                "description": "The path of the file to update (e.g., src/main.py)",
                "required": True
            },
            {
                "name": "content",
                "type": "string",
                "description": "The new content of the file",
                "required": True
            },
            {
                "name": "commit_message",
                "type": "string",
                "description": "The commit message for the file update",
                "required": False
            }
        ],
        "output": {
            "type": "string",
            "description": "Success message or error message"
        }
    },
    {
        "name": "update_file_from_local",
        "description": "Update a file in a specified GitHub repository with content from a local file.",
        "inputs": [
            {
                "name": "repo_name",
                "type": "string",
                "description": "The name of the repository (format: owner/repo)",
                "required": True
            },
            {
                "name": "file_path",
                "type": "string",
                "description": "The path of the file in the repository to update (e.g., github_mcp.py)",
                "required": True
            },
            {
                "name": "local_file_path",
                "type": "string",
                "description": "The absolute path to the local file (e.g., /path/to/github_mcp.py)",
                "required": True
            },
            {
                "name": "commit_message",
                "type": "string",
                "description": "The commit message for the file update",
                "required": False
            }
        ],
        "output": {
            "type": "string",
            "description": "Success message or error message"
        }
    }
]

# Pydantic model for tool invocation
class ToolInvocation(BaseModel):
    tool: str
    inputs: Dict[str, Any]

def parse_prompt_for_tool_calls(prompt: str) -> list:
    """Parse a natural language prompt to extract MCP tool calls.
    
    Args:
        prompt: The raw prompt from Copilot.
    
    Returns:
        List of tool calls in the format [{"name": str, "inputs": dict}].
    """
    try:
        tool_calls = []
        prompt = prompt[:100_000]  # Limit prompt size to 100,000 characters
        
        # Parse for repository creation
        repo_match = re.search(r"create a repo with the name ['\"]?([^'\"]+)['\"]? ?(private)? ?(with a README)?", prompt, re.IGNORECASE)
        if repo_match:
            repo_name = repo_match.group(1)
            private = bool(repo_match.group(2))
            initialize_readme = bool(repo_match.group(3))
            tool_calls.append({
                "name": "create_repository",
                "inputs": {
                    "repo_name": repo_name,
                    "private": private,
                    "initialize_readme": initialize_readme
                }
            })
        
        # Parse for file creation
        file_match = re.search(r"create a file ['\"]?([^'\"]+)['\"]? in ['\"]?([^'\"]+)['\"]? with the content:? ?([\s\S]*?)(?=(?:commit message:|$))", prompt, re.IGNORECASE)
        commit_match = re.search(r"commit message: ['\"]?([^'\"]+)['\"]?", prompt, re.IGNORECASE)
        if file_match:
            file_path = file_match.group(1)
            repo_name = file_match.group(2)
            content = file_match.group(3).strip()
            commit_message = commit_match.group(1) if commit_match else f"Add {file_path} via MCP"
            tool_calls.append({
                "name": "create_file",
                "inputs": {
                    "repo_name": repo_name,
                    "file_path": file_path,
                    "content": content,
                    "commit_message": commit_message
                }
            })
        
        # Parse for repository deletion
        delete_repo_match = re.search(r"delete the repo named ['\"]?([^'\"]+)['\"]?", prompt, re.IGNORECASE)
        if delete_repo_match:
            repo_name = delete_repo_match.group(1)
            tool_calls.append({
                "name": "delete_repository",
                "inputs": {
                    "repo_name": repo_name
                }
            })
        
        # Parse for file deletion
        delete_file_match = re.search(r"delete the file ['\"]?([^'\"]+)['\"]? in ['\"]?([^'\"]+)['\"]? ?(?:(?:with|using) commit message: ['\"]?([^'\"]+)['\"]?)?", prompt, re.IGNORECASE)
        if delete_file_match:
            file_path = delete_file_match.group(1)
            repo_name = delete_file_match.group(2)
            commit_message = delete_file_match.group(3) or f"Delete {file_path} via MCP"
            tool_calls.append({
                "name": "delete_file",
                "inputs": {
                    "repo_name": repo_name,
                    "file_path": file_path,
                    "commit_message": commit_message
                }
            })

        # Parse for file update
        update_file_match = re.search(r"update the file ['\"]?([^'\"]+)['\"]? in ['\"]?([^'\"]+)['\"]? with the content:? ?([\s\S]*?)(?=(?:commit message:|$))", prompt, re.IGNORECASE)
        update_commit_match = re.search(r"commit message: ['\"]?([^'\"]+)['\"]?", prompt, re.IGNORECASE)
        if update_file_match:
            file_path = update_file_match.group(1)
            repo_name = update_file_match.group(2)
            content = update_file_match.group(3).strip()
            commit_message = update_commit_match.group(1) if update_commit_match else f"Update {file_path} via MCP"
            tool_calls.append({
                "name": "update_file",
                "inputs": {
                    "repo_name": repo_name,
                    "file_path": file_path,
                    "content": content,
                    "commit_message": commit_message
                }
            })
        
        # Parse for updating file from local path
        update_local_match = re.search(r"update the file ['\"]?([^'\"]+)['\"]? in ['\"]?([^'\"]+)['\"]? with content from ['\"]?([^'\"]+)['\"]? ?(?:(?:with|using) commit message: ['\"]?([^'\"]+)['\"]?)?", prompt, re.IGNORECASE)
        if update_local_match:
            file_path = update_local_match.group(1)
            repo_name = update_local_match.group(2)
            local_file_path = update_local_match.group(3)
            commit_message = update_local_match.group(4) or f"Update {file_path} from local file via MCP"
            tool_calls.append({
                "name": "update_file_from_local",
                "inputs": {
                    "repo_name": repo_name,
                    "file_path": file_path,
                    "local_file_path": local_file_path,
                    "commit_message": commit_message
                }
            })
        
        return tool_calls
    except Exception as e:
        print(f"Error parsing prompt: {str(e)}")
        return []

# MCP Tool Discovery Endpoint
@app.get("/mcp/tools")
async def get_tools():
    return tools

# MCP Tool Invocation Endpoint
@app.post("/mcp/invoke")
async def invoke_tool(invocation: ToolInvocation):
    try:
        MAX_CONTENT_SIZE = 1_000_000  # 1 MB limit for GitHub API
        
        if invocation.tool == "create_repository":
            repo_name = invocation.inputs.get("repo_name")
            private = invocation.inputs.get("private", False)
            initialize_readme = invocation.inputs.get("initialize_readme", False)
            if not repo_name:
                raise HTTPException(status_code=400, detail="repo_name is required")
            user = github_client.get_user()
            repo = user.create_repo(
                name=repo_name,
                private=private,
                auto_init=initialize_readme
            )
            return {"status": "success", "result": repo.html_url}
        
        elif invocation.tool == "create_file":
            repo_name = invocation.inputs.get("repo_name")
            file_path = invocation.inputs.get("file_path")
            content = invocation.inputs.get("content")
            commit_message = invocation.inputs.get("commit_message", f"Add {file_path} via MCP")
            
            if not all([repo_name, file_path, content]):
                raise HTTPException(status_code=400, detail="repo_name, file_path, and content are required")
            
            content_bytes = content.encode('utf-8')
            if len(content_bytes) > MAX_CONTENT_SIZE:
                raise HTTPException(status_code=400, detail=f"Content size ({len(content_bytes)} bytes) exceeds 1 MB limit")
            
            try:
                repo = github_client.get_repo(repo_name)
                repo.create_file(file_path, commit_message, content)
                return {"status": "success", "result": f"File {file_path} created in {repo_name}"}
            except GithubException as e:
                raise HTTPException(status_code=500, detail=f"GitHub API error: {str(e)}")
        
        elif invocation.tool == "delete_repository":
            repo_name = invocation.inputs.get("repo_name")
            if not repo_name:
                raise HTTPException(status_code=400, detail="repo_name is required")
            try:
                user = github_client.get_user()
                repo = github_client.get_repo(f"{user.login}/{repo_name}")
                repo.delete()
                return {"status": "success", "result": f"Repository {repo_name} deleted successfully"}
            except GithubException as e:
                raise HTTPException(status_code=500, detail=f"GitHub API error: {str(e)}")
            
        elif invocation.tool == "delete_file":
            repo_name = invocation.inputs.get("repo_name")
            file_path = invocation.inputs.get("file_path")
            commit_message = invocation.inputs.get("commit_message", f"Delete {file_path} via MCP")
            
            if not all([repo_name, file_path]):
                raise HTTPException(status_code=400, detail="repo_name and file_path are required")
            
            try:
                repo = github_client.get_repo(repo_name)
                file = repo.get_contents(file_path)
                repo.delete_file(
                    path=file_path,
                    message=commit_message,
                    sha=file.sha
                )
                return {"status": "success", "result": f"File {file_path} deleted from {repo_name}"}
            except GithubException as e:
                if e.status == 404:
                    raise HTTPException(status_code=404, detail=f"File {file_path} not found in {repo_name}")
                raise HTTPException(status_code=500, detail=f"GitHub API error: {str(e)}")
        
        elif invocation.tool == "update_file":
            repo_name = invocation.inputs.get("repo_name")
            file_path = invocation.inputs.get("file_path")
            content = invocation.inputs.get("content")
            commit_message = invocation.inputs.get("commit_message", f"Update {file_path} via MCP")
            
            if not all([repo_name, file_path, content]):
                raise HTTPException(status_code=400, detail="repo_name, file_path, and content are required")
            
            content_bytes = content.encode('utf-8')
            if len(content_bytes) > MAX_CONTENT_SIZE:
                raise HTTPException(status_code=400, detail=f"Content size ({len(content_bytes)} bytes) exceeds 1 MB limit")
            
            try:
                repo = github_client.get_repo(repo_name)
                file = repo.get_contents(file_path)
                repo.update_file(
                    path=file_path,
                    message=commit_message,
                    content=content,
                    sha=file.sha
                )
                return {"status": "success", "result": f"File {file_path} updated in {repo_name}"}
            except GithubException as e:
                raise HTTPException(status_code=500, detail=f"GitHub API error: {str(e)}")
        
        elif invocation.tool == "update_file_from_local":
            repo_name = invocation.inputs.get("repo_name")
            file_path = invocation.inputs.get("file_path")
            local_file_path = invocation.inputs.get("local_file_path")
            commit_message = invocation.inputs.get("commit_message", f"Update {file_path} from local file via MCP")
            
            if not all([repo_name, file_path, local_file_path]):
                raise HTTPException(status_code=400, detail="repo_name, file_path, and local_file_path are required")
            
            if not os.path.isfile(local_file_path):
                raise HTTPException(status_code=400, detail=f"Local file {local_file_path} does not exist")
            
            try:
                # Read content from local file
                with open(local_file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                content_bytes = content.encode('utf-8')
                if len(content_bytes) > MAX_CONTENT_SIZE:
                    raise HTTPException(status_code=400, detail=f"Content size ({len(content_bytes)} bytes) exceeds 1 MB limit")
                
                repo = github_client.get_repo(repo_name)
                file = repo.get_contents(file_path)
                repo.update_file(
                    path=file_path,
                    message=commit_message,
                    content=content,
                    sha=file.sha
                )
                return {"status": "success", "result": f"File {file_path} updated in {repo_name} from {local_file_path}"}
            except GithubException as e:
                raise HTTPException(status_code=500, detail=f"GitHub API error: {str(e)}")
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Server error: {str(e)}")
        
        else:
            raise HTTPException(status_code=400, detail="Unknown tool")
    
    except GithubException as e:
        raise HTTPException(status_code=500, detail=f"GitHub API error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)}")

# MCP Prompt Parsing Endpoint
@app.post("/mcp/parse_prompt")
async def parse_prompt(prompt: Dict[str, str]):
    prompt_text = prompt.get("prompt", "")
    tool_calls = parse_prompt_for_tool_calls(prompt_text)
    return {"tool_calls": tool_calls}

# SSE Transport for MCP
@app.get("/mcp/sse")
async def sse():
    async def event_stream():
        yield f"event: tools\ndata: {json.dumps(tools)}\n\n"
        while True:
            yield "event: ping\ndata: {}\n\n"
            await asyncio.sleep(15)
    
    return StreamingResponse(event_stream(), media_type="text/event-stream")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="debug")