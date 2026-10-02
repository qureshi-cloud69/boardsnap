"""
Annotator — draw swipe path onto uploaded image.
"""
import cv2
import numpy as np
from typing import List, Dict
import base64

# Color palette for paths (bright distinct)
PALETTE = [
    (255,  62,  62), # red
    ( 59, 130, 246), # blue
    ( 16, 185, 129), # green
    (245, 158,  11), # amber
    (139,  92, 246), # purple
    (236,  72, 153), # pink
    (  6, 182, 212), # cyan
    (249, 115,  22), # orange
]

def _hex_to_bgr(hex_color: str):
    hex_color = hex_color.lstrip('#')
    r = int(hex_color[0:2], 16); g = int(hex_color[2:4],16); b=int(hex_color[4:6],16)
    return (b,g,r)

def annotate_image(image_bgr: np.ndarray, tiles: List[Dict], path: List[int], word: str = "", score: int = 0, color: tuple = None, highlight_index: int = 0, wildcard_map: dict = None) -> np.ndarray:
    """
    Draw path on copy of image.
    - polyline through bubble centers
    - colored ring on each tile
    - numbered order badges
    - legend
    """
    img = image_bgr.copy()
    h,w = img.shape[:2]
    if color is None:
        color = PALETTE[highlight_index % len(PALETTE)]
    # Convert to brighter for overlay? Keep original.

    # Estimate radius from tiles
    if tiles and 'r' in tiles[0]:
        # median radius
        rs = [t.get('r', int(min(h,w)*0.04)) for t in tiles if 'r' in t]
        r = int(np.median(rs)) if rs else int(min(h,w)*0.04)
    else:
        # estimate from spacing via median nearest neighbor
        import math
        xs=[t['x'] for t in tiles]; ys=[t['y'] for t in tiles]
        dists=[]
        for i in range(len(tiles)):
            md=float('inf')
            for j in range(len(tiles)):
                if i==j: continue
                d=math.hypot(xs[i]-xs[j], ys[i]-ys[j])
                if d<md: md=d
            if md!=float('inf'): dists.append(md)
        median = sorted(dists)[len(dists)//2] if dists else 40
        r = int(median*0.45)

    # Draw underlying path polyline (thick)
    if len(path) >= 2:
        pts = np.array([(tiles[i]['x'], tiles[i]['y']) for i in path], dtype=np.int32)
        # Draw thick shadow then colored line
        cv2.polylines(img, [pts], isClosed=False, color=(0,0,0), thickness=8, lineType=cv2.LINE_AA)
        cv2.polylines(img, [pts], isClosed=False, color=color, thickness=5, lineType=cv2.LINE_AA)
        # Arrow heads? optional
        # Draw direction arrows small
        for k in range(len(pts)-1):
            # mid point arrow
            p1 = pts[k]; p2 = pts[k+1]
            # vector
            vx = p2[0]-p1[0]; vy = p2[1]-p1[1]
            mag = np.hypot(vx,vy)
            if mag<1: continue
            mx = int((p1[0]+p2[0])/2); my = int((p1[1]+p2[1])/2)
            # normalize
            ux = vx/mag; uy = vy/mag
            # arrow size
            alen = 10
            # perpendicular
            px = -uy; py = ux
            tip = (int(mx + ux*alen), int(my + uy*alen))
            base1 = (int(mx - ux*alen*0.6 + px*alen*0.6), int(my - uy*alen*0.6 + py*alen*0.6))
            base2 = (int(mx - ux*alen*0.6 - px*alen*0.6), int(my - uy*alen*0.6 - py*alen*0.6))
            # draw small triangle
            tri = np.array([tip, base1, base2], dtype=np.int32)
            cv2.fillPoly(img, [tri], color)

    # Draw rings on each tile in path — wildcards get gold dashed highlight
    if wildcard_map is None:
        wildcard_map = {}
    # normalize keys to int
    try:
        wildcard_map = {int(k): v for k, v in wildcard_map.items()}
    except:
        pass
    for order, idx in enumerate(path):
        x = tiles[idx]['x']; y = tiles[idx]['y']
        is_wc = idx in wildcard_map or tiles[idx].get('is_wildcard') or tiles[idx].get('is_blank')
        # outer ring
        if is_wc:
            # gold + dashed effect: draw thicker gold outer with inner dark
            cv2.circle(img, (x,y), r+5, (0,0,0), 5, lineType=cv2.LINE_AA)
            cv2.circle(img, (x,y), r+5, (0, 215, 255), 3, lineType=cv2.LINE_AA)  # gold BGR 0,215,255
            # inner white dashed hint (draw 12 small arcs)
            for a in range(0, 360, 30):
                # approximate dashed by drawing small circles along circumference
                if (a//30) % 2 == 0:
                    ax = int(x + (r+5)*0.92 * np.cos(np.deg2rad(a)))
                    ay = int(y + (r+5)*0.92 * np.sin(np.deg2rad(a)))
                    cv2.circle(img, (ax,ay), 2, (255,255,255), -1, lineType=cv2.LINE_AA)
            # wildcard badge: show assigned letter small below number
            # will be drawn with number badge; add extra indicator
        else:
            cv2.circle(img, (x,y), r+4, (0,0,0), 4, lineType=cv2.LINE_AA)
            cv2.circle(img, (x,y), r+4, color, 3, lineType=cv2.LINE_AA)
        # numbered badge: small filled circle top-left offset
        badge_r = max(12, int(r*0.45))
        # position badge at upper part of tile
        bx = x + int(r*0.55); by = y - int(r*0.55)
        # ensure inside image
        bx = max(badge_r, min(w-badge_r, bx))
        by = max(badge_r, min(h-badge_r, by))
        cv2.circle(img, (bx,by), badge_r, (0,0,0), -1, lineType=cv2.LINE_AA)
        cv2.circle(img, (bx,by), badge_r, color, 2, lineType=cv2.LINE_AA)
        # text number
        txt = str(order+1)
        font = cv2.FONT_HERSHEY_SIMPLEX
        # center text in badge
        (tw,th), bl = cv2.getTextSize(txt, font, 0.5, 1)
        # scale based on badge
        scale = badge_r / 18
        (tw,th), bl = cv2.getTextSize(txt, font, scale, 2)
        tx = bx - tw//2; ty = by + th//2
        cv2.putText(img, txt, (tx,ty), font, scale, (255,255,255), 2, cv2.LINE_AA)

    # Also draw faint rings on all non-path tiles to show board
    for i,tt in enumerate(tiles):
        if i in path:
            continue
        if tt.get('is_wildcard') or tt.get('is_blank'):
            # blank wildcard not in path: gold faint dashed
            cv2.circle(img, (tt['x'], tt['y']), r, (0, 215, 255), 1, lineType=cv2.LINE_AA)
            # small star hint
            cv2.putText(img, "*", (tt['x']-4, tt['y']+4), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0,215,255), 1, cv2.LINE_AA)
        elif tt.get('is_empty'):
            cv2.circle(img, (tt['x'], tt['y']), r, (200,200,200), 1, lineType=cv2.LINE_AA)
        else:
            cv2.circle(img, (tt['x'], tt['y']), r, (255,255,255), 1, lineType=cv2.LINE_AA)

    # Legend box
    legend_h = 52
    legend_w = min(w-20, 420)
    lx1 = 10; ly1 = h - legend_h - 10
    lx2 = lx1 + legend_w; ly2 = h - 10
    # translucent background
    overlay = img.copy()
    cv2.rectangle(overlay, (lx1, ly1), (lx2, ly2), (0,0,0), -1)
    cv2.rectangle(overlay, (lx1, ly1), (lx2, ly2), color, 2)
    alpha = 0.65
    cv2.addWeighted(overlay, alpha, img, 1-alpha, 0, img)
    # text
    wc_count = len(wildcard_map) if wildcard_map else sum(1 for idx in path if tiles[idx].get('is_wildcard'))
    if wc_count:
        word_txt = f"{word}  •  {score} pts  •  {len(word)} letters  •  {wc_count}★ blank"
    else:
        word_txt = f"{word}  •  {score} pts  •  {len(word)} letters"
    cv2.putText(img, word_txt, (lx1+14, ly1+22), cv2.FONT_HERSHEY_SIMPLEX, 0.60, (255,255,255), 2, cv2.LINE_AA)
    if wc_count:
        sub = f"BoardSnap  •  path {len(path)} tiles  •  ★=blank (0 pts, any letter)"
    else:
        sub = f"BoardSnap  •  path {len(path)} tiles"
    cv2.putText(img, sub, (lx1+14, ly1+38), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200,200,200), 1, cv2.LINE_AA)
    # top-left small logo
    # cv2.putText(img, "BoardSnap", (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255,255,255), 2, cv2.LINE_AA)
    # add shadow
    # CV handles

    return img

def image_to_base64_png(image_bgr: np.ndarray) -> str:
    _, buf = cv2.imencode('.png', image_bgr)
    b64 = base64.b64encode(buf).decode('utf-8')
    return f"data:image/png;base64,{b64}"

def draw_all_mini_previews(image_bgr: np.ndarray, tiles: List[Dict], results: List[Dict], max_count=10) -> List[str]:
    """
    Generate mini preview base64 images for each result (small size)
    """
    previews = []
    for i, res in enumerate(results[:max_count]):
        annotated = annotate_image(image_bgr, tiles, res['path'], res['word'], res['score'], color=PALETTE[i % len(PALETTE)], highlight_index=i)
        # resize to mini
        h,w = annotated.shape[:2]
        scale = 220 / max(h,w) if max(h,w)>220 else 1.0
        if scale < 1:
            small = cv2.resize(annotated, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        else:
            small = annotated
        previews.append(image_to_base64_png(small))
    return previews
