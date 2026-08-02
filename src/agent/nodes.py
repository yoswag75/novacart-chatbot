import os
import re
import json
import time
import logging
from typing import Dict, Any, List
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field
import chromadb
from chromadb.config import Settings
from google import genai

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Dynamic model discovery + fallback
# ---------------------------------------------------------------------------

# Preferred order — models we'd like to use first (best → lightest).
PREFERRED_MODELS = [
    "gemma-4-31b-it",
    "gemma-4-26b-it",
    "gemini-3.5-flash",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-2.0-flash-thinking-exp",
]

def _discover_available_models() -> List[str]:
    """Query the Gemini API for models that support generateContent."""
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        logger.warning("No GOOGLE_API_KEY set — using hardcoded fallback list.")
        return list(PREFERRED_MODELS)

    try:
        client = genai.Client(api_key=api_key)
        available = []
        # Patterns that indicate non-text-generation models
        _skip_patterns = ["tts", "image", "embedding", "vision", "banana", "preview-image"]
        
        for m in client.models.list():
            m_name = getattr(m, "name", None)
            if not m_name:
                continue
            clean_name = m_name.replace("models/", "")
            # Skip non-text-generation models
            if any(pat in clean_name.lower() for pat in _skip_patterns):
                continue
            methods = getattr(m, "supported_generation_methods", [])
            if "generateContent" in methods or "gemini" in clean_name.lower() or "gemma" in clean_name.lower():
                available.append(clean_name)
        if available:
            logger.info(f"Discovered {len(available)} models from API.")
            return available
    except Exception as e:
        logger.warning(f"Could not discover models from API: {e}")

    return list(PREFERRED_MODELS)


def _build_fallback_order(available: List[str]) -> List[str]:
    """Order models: preferred ones first (in priority order), then any extras."""
    ordered = []
    # 1. Preferred models that are actually available
    for pref in PREFERRED_MODELS:
        if pref in available:
            ordered.append(pref)
    # 2. Any 'flash' models we didn't list as preferred
    for m in available:
        if m not in ordered and "flash" in m:
            ordered.append(m)
    # 3. Last resort — anything remaining
    for m in available:
        if m not in ordered:
            ordered.append(m)
    # 4. If discovery returned nothing useful, use hardcoded list
    if not ordered:
        ordered = list(PREFERRED_MODELS)
    return ordered


# Discover models once at module load
_available_models = _discover_available_models()
FALLBACK_MODELS = _build_fallback_order(_available_models)
logger.info(f"Model fallback order: {FALLBACK_MODELS[:6]}{'…' if len(FALLBACK_MODELS) > 6 else ''}")

MAX_RETRY_ROUNDS = 1       # Single pass through all models — no retries to save tokens
DELAY_BETWEEN_MODELS = 1   # Seconds between trying different models


def _is_retryable_error(e: Exception) -> bool:
    """Check if an error is a rate-limit or model-unavailable error."""
    s = str(e)
    return any(x in s for x in ["429", "404", "500", "RESOURCE_EXHAUSTED", "NOT_FOUND", "INTERNAL", "no longer available"])


def _is_rate_limit_error(e: Exception) -> bool:
    """Check if an error is specifically a rate-limit (429) error (not a 404)."""
    s = str(e)
    return "429" in s or "RESOURCE_EXHAUSTED" in s


def _extract_retry_delay(e: Exception) -> float:
    """Extract the suggested retry delay from the error message, default to 30s."""
    match = re.search(r'retryDelay.*?(\d+)', str(e))
    if match:
        return min(float(match.group(1)), 60)  # Cap at 60 seconds
    return 30.0


def invoke_with_fallback(operation):
    """Try an LLM operation across all discovered models until one succeeds.

    - Cycles through FALLBACK_MODELS on retryable errors.
    - If ALL models fail with rate-limits, waits for the suggested retry delay
      and retries (up to MAX_RETRY_ROUNDS full rounds).
    - 404 / 'no longer available' models are skipped within a round.
    """
    for round_num in range(MAX_RETRY_ROUNDS):
        last_error = None
        all_rate_limited = True

        for model_name in FALLBACK_MODELS:
            try:
                llm = ChatGoogleGenerativeAI(model=model_name, temperature=0.0)
                return operation(llm)
            except Exception as e:
                if _is_retryable_error(e):
                    logger.warning(f"[Round {round_num+1}] Model '{model_name}' failed: {type(e).__name__}")
                    if not _is_rate_limit_error(e):
                        all_rate_limited = False
                    last_error = e
                    time.sleep(DELAY_BETWEEN_MODELS)
                    continue
                raise

        # All models failed this round
        if all_rate_limited and round_num < MAX_RETRY_ROUNDS - 1:
            wait = _extract_retry_delay(last_error)
            logger.warning(f"All models rate-limited. Waiting {wait:.0f}s before retry round {round_num+2}...")
            time.sleep(wait)
        elif round_num < MAX_RETRY_ROUNDS - 1:
            time.sleep(5)
    if last_error:
        raise last_error
    raise RuntimeError("Fallback loop failed: No models were available to try.")

class SearchPlan(BaseModel):
    plan: List[str] = Field(description="List of ordered retrieval steps/queries to execute")

def analyze_and_plan_node(state: Dict[str, Any]) -> Dict[str, Any]:
    query = state["query"]
    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are an agent planning a multi-hop information retrieval strategy. Decompose the user's question into at most 2 focused search queries that will pull evidence across multiple document types (support tickets, refund logs, order records, quality reports, internal emails). Keep the plan short to save resources. Return a JSON with a 'plan' array containing the queries."),
        ("human", "{query}")
    ])
    
    # Use regular invoke and parse JSON, allowing Gemma to work without native function calling
    response = invoke_with_fallback(
        lambda llm: prompt.pipe(llm).invoke({"query": query})
    )
    
    # Try to parse the JSON output
    try:
        content = response.content
        if isinstance(content, list):
            content = "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
        # Strip markdown code blocks if present
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
        parsed = json.loads(content)
        raw_plan = parsed.get("plan", [])
        if isinstance(raw_plan, str):
            plan_list = [raw_plan]
        elif isinstance(raw_plan, list):
            plan_list = [str(x) for x in raw_plan]
        else:
            plan_list = [str(raw_plan)]
    except Exception as e:
        logger.error(f"Failed to parse plan JSON: {e}")
        plan_list = [query] # Fallback
        
    return {
        "search_plan": plan_list,
        "current_hypotheses": "Initial plan formulated.",
        "retrieved_documents": [],
        "identified_anomalies": [],
        "missing_evidence_flag": False,
        "hop_count": 0
    }

def retrieve_evidence_node(state: Dict[str, Any]) -> Dict[str, Any]:
    plan = state["search_plan"]
    if not plan:
        return state
        
    current_step = plan[0] # we will pop it in the judge node if successful
    hop_count = state.get("hop_count", 0) + 1
    
    # Connect to ChromaDB
    # Note: In a real app, initialize once. For prototype, fast enough.
    client = chromadb.PersistentClient(path="data/chroma_db")
    
    # Use embedding function if we have api key
    api_key = os.getenv("GOOGLE_API_KEY")
    embedding_function = None
    if api_key:
        try:
            from chromadb.api.types import Documents, EmbeddingFunction, Embeddings
            from langchain_google_genai import GoogleGenerativeAIEmbeddings
            
            class LangchainGoogleEmbeddingFunction(EmbeddingFunction):
                def __init__(self, key: str):
                    self.embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-2", google_api_key=key)
                    
                def __call__(self, input: Documents) -> Embeddings:
                    return self.embeddings.embed_documents(list(input))
                    
            embedding_function = LangchainGoogleEmbeddingFunction(key=api_key)
        except ImportError:
            pass
            
    try:
        collection = client.get_collection(name="novacart_docs", embedding_function=embedding_function)
    except Exception:
        # Fallback to default
        collection = client.get_collection(name="novacart_docs")
        
    # We should let LLM extract metadata filters ideally, but for now we do a pure semantic search 
    # to find top k chunks related to current_step
    results = collection.query(
        query_texts=[current_step],
        n_results=3
    )
    
    new_docs = []
    if results and results.get('documents') and results['documents'][0]:
        for i, doc_text in enumerate(results['documents'][0]):
            meta = results['metadatas'][0][i]
            new_docs.append({
                "content": doc_text,
                "metadata": meta
            })
            
    current_retrieved = state.get("retrieved_documents", [])
    current_retrieved.extend(new_docs)
    
    return {
        "retrieved_documents": current_retrieved,
        "hop_count": hop_count
    }

def dlp_filter_node(state: Dict[str, Any]) -> Dict[str, Any]:
    # Scans retrieved chunks for sensitive patterns and masks them.
    # regex for basic credit card (e.g., 4111 2222 3333 4444)
    cc_regex = re.compile(r'\b(?:\d[ -]*?){13,16}\b')
    
    filtered_docs = []
    for doc in state.get("retrieved_documents", []):
        content = doc.get("content", "")
        if cc_regex.search(content):
            content = cc_regex.sub("[REDACTED-CC]", content)
        
        filtered_docs.append({
            "content": content,
            "metadata": doc.get("metadata", {})
        })
        
    return {"retrieved_documents": filtered_docs}

class JudgeEvaluation(BaseModel):
    found_data: bool = Field(description="Did we find relevant data for the current step?")
    anomalies: List[Dict[str, str]] = Field(description="List of dicts with 'type' (e.g., conflicting_data) and 'description'")
    pop_step: bool = Field(description="Should we pop the current step from the plan and move to the next?")

def evaluate_state_node(state: Dict[str, Any]) -> Dict[str, Any]:
    plan = state.get("search_plan", [])
    if not plan:
        return state
        
    current_step = plan[0]
    retrieved = state.get("retrieved_documents", [])
    
    # We ask the LLM to judge the evidence against the plan step
    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are the Judge. Evaluate if the recently retrieved evidence satisfies the current search step. Identify any contradictions, missing data, or anomalies in the evidence compared to standard expectations. Return structured JSON."),
        ("human", "Current Step: {step}\nEvidence: {evidence}")
    ])
    
    evidence_str = json.dumps(retrieved)
    try:
        response = invoke_with_fallback(
            lambda llm: prompt.pipe(llm).invoke(
                {"step": current_step, "evidence": evidence_str}
            )
        )
        content = response.content
        if isinstance(content, list):
            content = "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
        parsed = json.loads(content)
        
        raw_anomalies = parsed.get("anomalies", [])
        sanitized_anomalies = []
        if isinstance(raw_anomalies, str):
            sanitized_anomalies.append({"type": "unknown", "description": raw_anomalies})
        elif isinstance(raw_anomalies, list):
            for a in raw_anomalies:
                if isinstance(a, dict) and "description" in a:
                    sanitized_anomalies.append(a)
                elif isinstance(a, str):
                    sanitized_anomalies.append({"type": "unknown", "description": a})
                else:
                    sanitized_anomalies.append({"type": "unknown", "description": str(a)})
        
        evaluation = JudgeEvaluation(
            found_data=parsed.get("found_data", True),
            anomalies=sanitized_anomalies,
            pop_step=parsed.get("pop_step", True)
        )
    except Exception as e:
        logger.error(f"All models failed for judge evaluation: {e}")
        # Hard fallback — assume step is done so graph doesn't stall
        evaluation = JudgeEvaluation(found_data=True, anomalies=[], pop_step=True)
        
    missing_evidence = not evaluation.found_data
    identified_anomalies = state.get("identified_anomalies", [])
    if evaluation.anomalies:
        identified_anomalies.extend(evaluation.anomalies)
        
    new_plan = list(plan)
    if evaluation.pop_step and new_plan:
        new_plan.pop(0)
        
    return {
        "search_plan": new_plan,
        "missing_evidence_flag": missing_evidence or state.get("missing_evidence_flag", False),
        "identified_anomalies": identified_anomalies
    }

def synthesize_and_cite_node(state: Dict[str, Any]) -> Dict[str, Any]:
    query = state["query"]
    evidence = state["retrieved_documents"]
    anomalies = state["identified_anomalies"]
    missing = state["missing_evidence_flag"]
    
    sys_prompt = """You are the final synthesizer. Answer the user's business query using ONLY the provided evidence. 
    Strictly cite the 'doc_id' and 'source_type' for your claims. 
    Explicitly surface any identified anomalies (like conflicting data, missing foreign keys, etc.) and state if evidence was missing.
    Do not hallucinate. Format nicely."""
    
    human_msg = f"Query: {query}\nEvidence: {json.dumps(evidence)}\nAnomalies: {json.dumps(anomalies)}\nMissing Evidence: {missing}"
    
    # We don't invoke it here synchronously because we need to stream it via API.
    # In LangGraph, node execution usually happens and returns state. 
    # To support streaming tokens in FastAPI, we can just return a final state and let the server stream the LLM call, 
    # or we can stream the node itself. Since LangGraph supports .astream_events(), we just return the final structured state 
    # or we do the generation here if we want token events from this node.
    
    messages = [
        SystemMessage(content=sys_prompt),
        HumanMessage(content=human_msg)
    ]
    
    # Invoke with fallback. astream_events() on the graph will still capture token events.
    response = invoke_with_fallback(lambda llm: llm.invoke(messages))
    
    return {
        "current_hypotheses": response.content  # store final answer
    }
