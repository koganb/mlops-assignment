import sys
import os
from dotenv import load_dotenv

# Add project root to path
sys.path.append(os.getcwd())

load_dotenv()

from agent.graph import graph, AgentState

def test_agent():
    # A question that might be tricky or straightforward
    state = AgentState(
        question="What is the coordinates location of the circuits for Australian grand prix?",
        db_id="formula_1"
    )
    
    print(f"Question: {state.question}")
    print(f"DB ID: {state.db_id}")
    
    # Run the graph
    result = graph.invoke(state)
    
    print("\nFinal Result:")
    print(f"SQL: {result.get('sql')}")
    print(f"Verify OK: {result.get('verify_ok')}")
    print(f"Verify Issue: {result.get('verify_issue')}")
    print(f"Iterations: {result.get('iteration')}")
    
    print("\nHistory:")
    for h in result.get('history', []):
        print(f"  Node: {h.get('node')}")
        if 'sql' in h:
            print(f"    SQL: {h.get('sql')}")
        if 'issue' in h:
            print(f"    Issue: {h.get('issue')}")

if __name__ == "__main__":
    test_agent()
