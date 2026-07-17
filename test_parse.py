import json
import sys
sys.path.insert(0, 'src')
from gitlab_rag.evaluate_faithfulness import parse_judge_response

response = """The user wants me to evaluate the faithfulness of the provided answer against the given chunks. I need to break the answer into claims, check each claim against the chunks, label them, and compute a faithfulness score. The output must be a single JSON object with specific keys.

First, I need to analyze the answer and the chunks.

Chunks provided:
- Chunk 1: Seems to be about hazard regions, polygons, colors. Not directly about GPIO control. It mentions `h_regin['polygon']`, `hazard_coord`, `haz"""

result = parse_judge_response(response)
print('Parsed:', json.dumps(result, ensure_ascii=False, indent=2))