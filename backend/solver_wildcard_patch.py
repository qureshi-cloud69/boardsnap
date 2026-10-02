import pathlib
p = pathlib.Path('/home/user/backend/solver.py')
text = p.read_text()
# Patch build_adjacency to support wildcards
old = """    # Build adjacency
    adj: Dict[int, List[int]] = {i: [] for i in range(n)}
    for i in range(n):
        if tiles[i].get('is_empty') or tiles[i].get('empty'):
            continue
        for j in range(n):
            if i == j: continue
            if tiles[j].get('is_empty') or tiles[j].get('empty'):
                continue
            d = math.hypot(xs[i]-xs[j], ys[i]-ys[j])
            if d < threshold:
                adj[i].append(j)
    return adj"""
new = """    # Build adjacency — holes (is_empty without wildcard) are not traversable.
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
    return adj"""
if old in text:
    text = text.replace(old, new)
    p.write_text(text)
    print("patched build_adjacency")
else:
    print("build_adjacency old not found")

# Now patch solve_board for wildcard handling
old2 = """    # Map index -> letter
    letters = []
    values = []
    for t in tiles:
        letters.append(t.get('letter','') if not t.get('is_empty') else '')
        values.append(t.get('value',0) if not t.get('is_empty') else 0)

    # Only consider indices that are playable (non-empty and letter A-Z)
    playable = [i for i,t in enumerate(tiles) if not t.get('is_empty') and letters[i] and letters[i].isalpha()]"""
new2 = """    # Map index -> letter / wildcard
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
            playable.append(i)"""
if old2 in text:
    text = p.read_text()
    text = text.replace(old2, new2)
    p.write_text(text)
    print("patched letters/playable")
else:
    print("playable old not found")
    # debug search
    import difflib, re
    print(text[text.find("    # Map index"):text.find("    # Map index")+600])
