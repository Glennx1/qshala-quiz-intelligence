import math
from typing import List, Tuple, Any
import numpy as np

def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    
    dot = sum(a * b for a, b in zip(v1, v2))
    norm_a = math.sqrt(sum(a * a for a in v1))
    norm_b = math.sqrt(sum(b * b for b in v2))
    
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
        
    return dot / (norm_a * norm_b)

def batch_cosine_similarities(query_vec: List[float], target_vecs: List[List[float]]) -> np.ndarray:
    """Fast vectorized cosine similarity using numpy."""
    if not target_vecs or not query_vec:
        return np.array([])
    
    q = np.array(query_vec, dtype=np.float32)
    q_norm = np.linalg.norm(q)
    if q_norm == 0:
        return np.zeros(len(target_vecs))
    
    targets = np.array(target_vecs, dtype=np.float32)
    target_norms = np.linalg.norm(targets, axis=1)
    target_norms[target_norms == 0] = 1e-10  # Prevent divide by zero
    
    dots = np.dot(targets, q)
    similarities = dots / (target_norms * q_norm)
    return similarities
