from typing import TypedDict, List, Dict, Any, Literal
from langgraph.graph import StateGraph, START, END
from .nodes import (
    analyze_and_plan_node,
    retrieve_evidence_node,
    dlp_filter_node,
    evaluate_state_node,
    synthesize_and_cite_node
)

class AgentState(TypedDict):
    query: str
    search_plan: List[str]
    current_hypotheses: str
    retrieved_documents: List[Dict[str, Any]]  # chunk text + metadata
    identified_anomalies: List[Dict[str, Any]] # {type, description, doc_ids}
    missing_evidence_flag: bool
    hop_count: int

def should_continue(state: AgentState) -> Literal["retrieve_evidence", "synthesize_and_cite"]:
    # The Judge node should determine if more hops are needed, but for LangGraph's conditional edges,
    # we inspect the state to decide the next route.
    # We will use a dedicated key in the state or just rely on a simple check.
    # Let's say `Evaluate_State` will update `search_plan` by popping the current step if satisfied,
    # or if `hop_count` >= 3, we exit.
    
    if state["hop_count"] >= 10:
        return "synthesize_and_cite"
        
    # If there's still a plan left to execute, we retrieve
    if len(state["search_plan"]) > 0:
        return "retrieve_evidence"
        
    return "synthesize_and_cite"

def build_graph() -> StateGraph:
    workflow = StateGraph(AgentState)
    
    # Add nodes
    workflow.add_node("analyze_and_plan", analyze_and_plan_node)
    workflow.add_node("retrieve_evidence", retrieve_evidence_node)
    workflow.add_node("dlp_filter", dlp_filter_node)
    workflow.add_node("evaluate_state", evaluate_state_node)
    workflow.add_node("synthesize_and_cite", synthesize_and_cite_node)
    
    # Wiring
    workflow.add_edge(START, "analyze_and_plan")
    workflow.add_edge("analyze_and_plan", "retrieve_evidence")
    workflow.add_edge("retrieve_evidence", "dlp_filter")
    workflow.add_edge("dlp_filter", "evaluate_state")
    
    workflow.add_conditional_edges(
        "evaluate_state",
        should_continue,
        {
            "retrieve_evidence": "retrieve_evidence",
            "synthesize_and_cite": "synthesize_and_cite"
        }
    )
    
    workflow.add_edge("synthesize_and_cite", END)
    
    return workflow.compile()
