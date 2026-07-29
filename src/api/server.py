import os
import json
from fastapi import FastAPI, Depends, HTTPException, Security, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import asyncio
from dotenv import load_dotenv
from src.agent.graph import build_graph

load_dotenv()

app = FastAPI(title="NovaCart Global RAG API")
security = HTTPBearer()

API_TOKEN = os.getenv("API_TOKEN", "supersecrettoken")

def verify_token(credentials: HTTPAuthorizationCredentials = Security(security)):
    if credentials.credentials != API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid or missing token")
    return credentials.credentials

class QueryRequest(BaseModel):
    question: str

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

async def stream_generator(question: str):
    graph = build_graph()
    
    # Run the graph with async streaming
    # We will use graph.astream_events to intercept token generation and node executions
    try:
        async for event in graph.astream_events({"query": question}, version="v2"):
            kind = event["event"]
            name = event.get("name")
            
            # 1. Status Events (Emitted during planning/retrieval hops)
            if kind == "on_chain_start" and name in ["analyze_and_plan", "retrieve_evidence", "dlp_filter", "evaluate_state"]:
                node_name = name.replace("_", " ").title()
                yield f"data: {json.dumps({'type': 'status', 'message': f'Running {node_name}...'})}\n\n"
            
            # 2. Token Events — ONLY from the final Synthesis node
            #    (skip tokens from plan/judge structured output calls)
            elif kind == "on_chat_model_stream":
                # Check if this LLM call originates from the synthesis node
                tags = event.get("tags", [])
                parent_ids = event.get("parent_ids", [])
                metadata = event.get("metadata", {})
                
                # LangGraph tags events with the node name
                is_synthesis = (
                    "synthesize_and_cite" in tags
                    or metadata.get("langgraph_node") == "synthesize_and_cite"
                )
                
                if not is_synthesis:
                    continue
                    
                chunk = event["data"]["chunk"]
                content = chunk.content
                if content:
                    # Newer Gemini models may return content as a list of parts
                    if isinstance(content, list):
                        content = "".join(
                            part if isinstance(part, str) else part.get("text", "")
                            for part in content
                        )
                    if content:
                        yield f"data: {json.dumps({'type': 'token', 'content': content})}\n\n"
                    
            # 3. Final Payload
            # When the overall graph completes, we can emit the final state
            elif kind == "on_chain_end" and name == "LangGraph":
                # LangGraph emits the final state here
                final_state = event["data"]["output"]
                # We need to construct the citations, anomalies, missing_evidence payload
                citations = []
                for doc in final_state.get("retrieved_documents", []):
                    meta = doc.get("metadata", {})
                    citations.append({
                        "doc_id": meta.get("doc_id"),
                        "source_type": meta.get("source_type"),
                        "claim": "Used for context" # Simplified for prototype
                    })
                    
                final_payload = {
                    "type": "complete",
                    "citations": citations,
                    "anomalies_detected": final_state.get("identified_anomalies", []),
                    "missing_evidence": final_state.get("missing_evidence_flag", False)
                }
                yield f"data: {json.dumps(final_payload)}\n\n"
                
    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

@app.post("/query/stream")
async def query_stream(request: QueryRequest, token: str = Depends(verify_token)):
    return StreamingResponse(
        stream_generator(request.question), 
        media_type="text/event-stream"
    )
