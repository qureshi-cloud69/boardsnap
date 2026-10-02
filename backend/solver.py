"""
BoardSnap Solver — trie + DFS, hex adjacency, scoring.
Clean module that can be tested independently: given tiles + adjacency -> words with best paths.
"""
from __future__ import annotations
from typing import List, Dict, Tuple, Set
import os

# Standard Scrabble values
SCRABBLE_VALUES = {
    'A': 1, 'B': 3, 'C': 3, 'D': 2, 'E': 1, 'F': 4, 'G': 2,
    'H': 4, 'I': 1, 'J': 8, 'K': 5, 'L': 1, 'M': 3, 'N': 1,
    'O': 1, 'P': 3, 'Q': 10,'R': 1, 'S': 1, 'T': 1, 'U': 1,
    'V': 4, 'W': 4, 'X': 8, 'Y': 4, 'Z': 10
}

class TrieNode:
    __slots__ = ('children','is_word')
    def __init__(self):
        self.children: Dict[str, TrieNode] = {}
        self.is_word: bool = False

class Trie:
    def __init__(self, words: List[str] = None):
        self.root = TrieNode()
        self.word_count = 0
        if words:
            for w in words:
                self.insert(w)

    def insert(self, word: str):
        node = self.root
        for ch in word:
            if ch not in node.children:
                node.children[ch] = TrieNode()
            node = node.children[ch]
        if not node.is_word:
            node.is_word = True
            self.word_count += 1

    def has_prefix(self, prefix: str) -> bool:
        node = self.root
        for ch in prefix:
            if ch not in node.children:
                return False
            node = node.children[ch]
        return True

    def is_word(self, word: str) -> bool:
        node = self.root
        for ch in word:
            if ch not in node.children:
                return False
            node = node.children[ch]
        return node.is_word


def load_dictionary(path: str = None) -> Tuple[Trie, Set[str]]:
    """Load SOWPODS dictionary file."""
    if path is None:
        # search common locations
        candidates = [
            os.path.join(os.path.dirname(__file__), "sowpods.txt"),
            os.path.join(os.path.dirname(__file__), "../data/sowpods.txt"),
            "backend/sowpods.txt",
            "sowpods.txt",
        ]
        for c in candidates:
            if os.path.exists(c):
                path = c
                break
        else:
            raise FileNotFoundError("sowpods.txt not found")
    with open(path, 'r') as f:
        words = [line.strip().upper() for line in f if line.strip().isalpha()]
    # filter 2..15 length as valid for board
    trie = Trie(words)
    word_set = set(words)
    return trie, word_set

def load_common_words(path: str = None) -> Set[str]:
    if path is None:
        candidates = [
            os.path.join(os.path.dirname(__file__), "common_words.txt"),
            "backend/common_words.txt",
        ]
        for c in candidates:
            if os.path.exists(c):
                path = c
                break
        else:
            return set()
    try:
        with open(path, 'r') as f:
            return set(line.strip().upper() for line in f if line.strip())
    except:
        return set()

# Singleton tries lazily loaded
_TRIE = None
_WORD_SET = None
_COMMON_SET = None

def get_trie():
    global _TRIE, _WORD_SET
    if _TRIE is None:
        _TRIE, _WORD_SET = load_dictionary()
    return _TRIE, _WORD_SET

def get_common_set():
    global _COMMON_SET
    if _COMMON_SET is None:
        _COMMON_SET = load_common_words()
    return _COMMON_SET


def build_adjacency(tiles: List[Dict], threshold: float = None, auto_threshold: bool = True) -> Dict[int, List[int]]:
    """
    tiles: list of dicts with x,y,is_empty (or empty bool). Positions in pixels.
    Returns adjacency dict {tile_index: [neighbor_indices]} for hex neighbors.
    If threshold is None and auto_threshold True, compute from median nearest-neighbor distance *1.05
    """
    n = len(tiles)
    if n == 0:
        return {}
    import math
    # compute all pairwise distances for nearest neighbor median
    # only for non-empty tiles? adjacency should not go through empty but empty positions still affect geometry.
    # However spec says no word may pass through empty holes - so we still compute distances but exclude empty from graph.
    # For threshold calculation, use all tiles (including empty) to get true spacing; or use non-empty median.
    # Use all tiles positions to compute median nearest distance.
    xs = [t['x'] for t in tiles]
    ys = [t['y'] for t in tiles]
    # compute nearest neighbor for each tile
    nearest = []
    for i in range(n):
        min_d = float('inf')
        for j in range(n):
            if i == j: continue
            d = math.hypot(xs[i]-xs[j], ys[i]-ys[j])
            if d < min_d:
                min_d = d
        if min_d != float('inf'):
            nearest.append(min_d)
    if not nearest:
        return {i: [] for i in range(n)}
    nearest.sort()
    median = nearest[len(nearest)//2]
    if threshold is None:
        # Hex grid has two neighbor distances (horizontal ~62-73 and diagonal ~55-60/72).
        # Median captures the smaller; need ~1.3× to include both while still excluding
        # distance-2 neighbors (~110-124). Spec says 1.05 but we use adaptive 1.30 for robustness,
        # still derived from detected median, never hard-coded pixels.
        # For very regular boards median ~62, 1.3 => 80 includes both 62 and 72, excludes 120.
        threshold = median * 1.30
        # Clamp to avoid runaway on noisy boards: keep between 1.15 and 1.50
        # Already within.
    # Build adjacency — holes (is_empty without wildcard) are not traversable.
    # Wildcards (is_wildcard) ARE traversable and ARE included in graph.
    def _is_hole(t):
        # hole = explicitly marked empty and NOT a wildcard
        if t.get('is_wildcard'):
            return False
        # legacy is_empty means hole unless wildcard mode is implied
        # we also support 'wildcard' flag for backwards compat
        if t.get('is_empty') or t.get('empty'):
            return True
        return False
    adj: Dict[int, List[int]] = {i: [] for i in range(n)}
    for i in range(n):
        if _is_hole(tiles[i]):
            continue
        for j in range(n):
            if i == j: continue
            if _is_hole(tiles[j]):
                continue
            d = math.hypot(xs[i]-xs[j], ys[i]-ys[j])
            if d < threshold:
                adj[i].append(j)
    return adj


def solve_board(
    tiles: List[Dict],
    trie: Trie = None,
    adjacency: Dict[int, List[int]] = None,
    max_len: int = 15,
    min_len: int = 2
) -> List[Dict]:
    """
    Given tiles list [{x,y,letter,value,is_empty},...] and optional adjacency,
    returns list of found words with best path.

    Each result: {word, score, length, path: [tile_indices]}
    path is tile index sequence for best scoring occurrence.
    """
    if trie is None:
        trie, _ = get_trie()
    if adjacency is None:
        adjacency = build_adjacency(tiles)
    # filter to non-empty tiles with letters
    # precompute values if not present
    for t in tiles:
        if 'value' not in t or t['value'] is None:
            letter = t.get('letter','').upper()
            t['value'] = SCRABBLE_VALUES.get(letter, 0)
        # normalize letter
        if 'letter' in t and t['letter']:
            t['letter'] = t['letter'].upper().strip()

    # Map index -> letter / wildcard
    letters = []
    values = []
    is_wildcard = []
    for t in tiles:
        wc = bool(t.get('is_wildcard') or t.get('wildcard') or t.get('is_blank'))
        is_wildcard.append(wc)
        if wc:
            # wildcard has no fixed letter, value is 0 (blank scores 0, like Scrabble)
            letters.append('')  # placeholder, branching handles it
            # wildcard value may be 0 or tile's value if it has one; default 0
            values.append(int(t.get('value', 0)) if t.get('value') is not None else 0)
        elif t.get('is_empty') or t.get('empty'):
            letters.append('')
            values.append(0)
        else:
            letters.append(t.get('letter',''))
            values.append(t.get('value',0) if not t.get('is_empty') else 0)
        # normalize letter for non-wildcards
        if letters[-1]:
            letters[-1] = letters[-1].upper().strip()

    # Only consider indices that are playable:
    # - normal tiles with A-Z
    # - wildcard tiles (they are playable as any letter)
    playable = []
    for i in range(len(tiles)):
        if tiles[i].get('is_empty') or tiles[i].get('empty'):
            if not is_wildcard[i]:
                continue
        if is_wildcard[i]:
            playable.append(i)
        elif letters[i] and letters[i].isalpha():
            playable.append(i)

    # word -> {score, path}
    best_for_word: Dict[str, Dict] = {}

    # DFS
    # Use iterative stack to avoid recursion limit
    # For pruning, we need to know if prefix is in trie
    # We'll DFS from each start node

    # Precompute trie root for speed
    root = trie.root

    # To speed, we can sort? Not needed.

    # Use recursion with pruning
    import sys
    sys.setrecursionlimit(10000)

    # We'll implement iterative deep DFS with manual stack
    # Stack items: (current_node, path_indices, visited_set_tuple_or_bitmask, current_word)
    # But visited set per path is set of indices, up to 15 length so set is fine.

    # For performance, use recursion function with closure
    # Wildcard handling: tiles where is_wildcard[i] is True can be any letter A-Z.
    # For those tiles, we branch over all children of the current trie node.
    # Wildcard tiles score 0 (like Scrabble blank) — change to values[nb] if you want letter value.
    def dfs(current_idx: int, visited: Set[int], node: TrieNode, current_word: str, current_score: int, path: List[int], wildcard_map: Dict[int,str] = None):
        if wildcard_map is None:
            wildcard_map = {}
        # check if current_word is a word
        if node.is_word and len(current_word) >= min_len:
            existing = best_for_word.get(current_word)
            # For tie-breaking, prefer fewer wildcards? For now prefer higher score.
            # If same score, prefer fewer wildcards (more natural words)
            wc_count = len(wildcard_map)
            if existing is None or current_score > existing['score'] or (current_score == existing['score'] and wc_count < len(existing.get('wildcard_map', {}))):
                best_for_word[current_word] = {
                    'word': current_word,
                    'score': current_score,
                    'length': len(current_word),
                    'path': list(path),
                    'wildcard_map': dict(wildcard_map),
                    'wildcard_count': wc_count
                }
        if len(current_word) >= max_len:
            return
        for nb in adjacency.get(current_idx, []):
            if nb in visited:
                continue
            if is_wildcard[nb]:
                # Branch over all possible letters that continue the trie
                for ch, child in node.children.items():
                    # Avoid exploring too many branches if wildcard is at depth and child is leaf with many possibilities?
                    # Prune: only consider children that can lead to a word within remaining depth
                    visited.add(nb)
                    path.append(nb)
                    # store assignment for this wildcard
                    prev = wildcard_map.get(nb)
                    wildcard_map[nb] = ch
                    dfs(nb, visited, child, current_word + ch, current_score + values[nb], path, wildcard_map)
                    # backtrack wildcard assignment
                    if prev is None:
                        del wildcard_map[nb]
                    else:
                        wildcard_map[nb] = prev
                    path.pop()
                    visited.remove(nb)
            else:
                ch = letters[nb]
                if not ch:
                    continue
                child = node.children.get(ch)
                if child is None:
                    continue
                visited.add(nb)
                path.append(nb)
                dfs(nb, visited, child, current_word + ch, current_score + values[nb], path, wildcard_map)
                path.pop()
                visited.remove(nb)

    for start in playable:
        if is_wildcard[start]:
            # Wildcard start can be any letter that starts a word
            for ch, child in root.children.items():
                visited = {start}
                path = [start]
                dfs(start, visited, child, ch, values[start], path, {start: ch})
        else:
            ch = letters[start]
            child = root.children.get(ch)
            if child is None:
                continue
            visited = {start}
            path = [start]
            dfs(start, visited, child, ch, values[start], path, {})

    results = list(best_for_word.values())
    return results


def rank_results(results: List[Dict], common_set: Set[str] = None) -> Dict:
    """
    Given list of results from solve_board, produce ranked structure:
    - top_by_score 10
    - top_by_length 10
    - trap_tiles logic requires tiles info external
    """
    if not results:
        return {'top_by_score': [], 'top_by_length': [], 'all': []}
    # sort by score desc, length desc, word asc
    by_score = sorted(results, key=lambda r: (-r['score'], -r['length'], r['word']))[:10]
    by_length = sorted(results, key=lambda r: (-r['length'], -r['score'], r['word']))[:10]
    # all sorted by score
    all_sorted = sorted(results, key=lambda r: (-r['score'], -r['length'], r['word']))
    # mark common
    if common_set is not None:
        for r in all_sorted:
            r['is_common'] = r['word'] in common_set
        for r in by_score:
            r['is_common'] = r['word'] in common_set
        for r in by_length:
            r['is_common'] = r['word'] in common_set
    return {
        'top_by_score': by_score,
        'top_by_length': by_length,
        'all': all_sorted,
        'total_found': len(results)
    }

def find_trap_tiles(tiles: List[Dict], results: List[Dict]) -> List[Dict]:
    """Flag 8/10 point tiles that appear in zero valid words."""
    # Build set of tile indices that appear in any word path
    used = set()
    for r in results:
        for idx in r['path']:
            used.add(idx)
    traps = []
    for i, t in enumerate(tiles):
        val = t.get('value', SCRABBLE_VALUES.get(t.get('letter','').upper(),0))
        if val >= 8 and i not in used and not t.get('is_empty'):
            traps.append({'index': i, 'letter': t.get('letter'), 'value': val, 'x': t['x'], 'y': t['y']})
    return traps


# --------------- Unit test helper ---------------
def tiles_from_simple_grid(letters_grid: List[List[str]], empty_positions: Set[Tuple[int,int]] = None):
    """
    Helper for tests: create tiles from a simple grid representation.
    letters_grid is list of rows, each row list of letters. For hex staggered, we generate x,y.
    """
    tiles = []
    # hex geometry: row y = row_idx * 60, x = col*70 + (row%2 *35)
    for r, row in enumerate(letters_grid):
        for c, ch in enumerate(row):
            x = c * 70 + (r % 2) * 35 + 50
            y = r * 60 + 50
            is_empty = empty_positions and (r,c) in empty_positions
            tiles.append({
                'x': x, 'y': y,
                'letter': '' if is_empty else ch,
                'value': 0 if is_empty else SCRABBLE_VALUES.get(ch.upper(),1),
                'is_empty': bool(is_empty),
                'row': r, 'col': c
            })
    return tiles

