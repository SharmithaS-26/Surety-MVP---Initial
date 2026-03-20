import sys
sys.path.insert(0, '.')
from src.pymupdf_engine import extract_tokens

tokens = extract_tokens('data/Built_Right_Sample_CQ.pdf', 2)  # page 3

print(f"Total tokens: {len(tokens)}")
print(f"Y range: {min(t['cy'] for t in tokens)} to {max(t['cy'] for t in tokens)}")
print()
print("=== ALL PAGE 3 TOKENS ===")
for t in tokens:
    print(f"  cy={t['cy']:4}  cx={t['cx']:4}  x={t['x']:4}  x2={t['x2']:4}  [{t['text']}]")