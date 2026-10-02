"""
BoardSnap Detector — Python + OpenCV + NumPy
Implements spec pipeline:
- Threshold dark pixels <95 to find letter glyphs; connected components with centroid merging
- Detect bubble circles via HoughCircles + contour analysis
- Cross-check, identify empty bubbles, snap rows
- OCR via template matching (with optional EasyOCR fallback)
"""
import cv2
import numpy as np
from typing import List, Dict, Tuple
import os
from PIL import Image, ImageDraw, ImageFont

SCRABBLE_VALUES = {
    'A': 1, 'B': 3, 'C': 3, 'D': 2, 'E': 1, 'F': 4, 'G': 2,
    'H': 4, 'I': 1, 'J': 8, 'K': 5, 'L': 1, 'M': 3, 'N': 1,
    'O': 1, 'P': 3, 'Q': 10,'R': 1, 'S': 1, 'T': 1, 'U': 1,
    'V': 4, 'W': 4, 'X': 8, 'Y': 4, 'Z': 10
}

# ---------------- Template OCR -----------------
_templates = None
_template_size = 40

def _get_font(size=40):
    # Try DejaVu Sans Bold
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except:
                pass
    return ImageFont.load_default()

def _build_templates():
    global _templates
    if _templates is not None:
        return _templates
    _templates = {}
    font = _get_font(38)
    for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        # create 60x60 image white background, black letter
        img = Image.new('L', (60,60), color=255)
        draw = ImageDraw.Draw(img)
        # center text
        # get bbox
        try:
            bbox = draw.textbbox((0,0), ch, font=font)
            w = bbox[2]-bbox[0]
            h = bbox[3]-bbox[1]
            x = (60-w)//2 - bbox[0]
            y = (60-h)//2 - bbox[1]
            draw.text((x,y), ch, fill=0, font=font)
        except:
            draw.text((10,10), ch, fill=0, font=font)
        arr = np.array(img)  # 0 black, 255 white
        # invert to have letter white on black then crop
        # Threshold and crop to bbox
        _, bin_img = cv2.threshold(arr, 200, 255, cv2.THRESH_BINARY_INV)
        # find bounding rect
        coords = cv2.findNonZero(bin_img)
        if coords is not None:
            x,y,w,h = cv2.boundingRect(coords)
            # add padding
            pad = 4
            x = max(0, x-pad); y = max(0, y-pad)
            w = min(60-x, w+2*pad); h = min(60-y, h+2*pad)
            crop = bin_img[y:y+h, x:x+w]
            # resize to template size keeping aspect
            resized = cv2.resize(crop, (_template_size, _template_size), interpolation=cv2.INTER_AREA)
        else:
            resized = cv2.resize(bin_img, (_template_size, _template_size))
        _templates[ch] = resized
    return _templates

def _ocr_template_match(crop_gray: np.ndarray):
    """
    crop_gray: grayscale image around bubble center, expecting black letter on light bubble.
    Returns (letter, confidence 0-1)
    """
    templates = _build_templates()
    # preprocess crop: convert to binary where letter is white
    # Estimate: letter is dark, background light.
    # We need to isolate letter.
    if crop_gray is None or crop_gray.size == 0:
        return '?', 0.0
    # upscale if small
    h,w = crop_gray.shape[:2]
    # Ensure reasonable size
    # Threshold
    # Use adaptive or Otsu after blur
    blur = cv2.GaussianBlur(crop_gray, (3,3), 0)
    # Otsu inverted: letter dark -> white in binary
    _, binary = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    # If mean of binary is too high (mostly white), maybe no letter
    # Clean small noise
    kernel = np.ones((2,2), np.uint8)
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
    # Find largest contour (letter)
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return '?', 0.0
    # Sort by area descending
    contours = sorted(contours, key=cv2.contourArea, reverse=True)
    largest = contours[0]
    area = cv2.contourArea(largest)
    if area < 30:  # too small, likely noise or empty
        return '?', 0.0
    # Special handling for I/J dots? We'll merge later, but here crop contains whole bubble so dot separation not issue?
    # Get bounding rect and crop binary to letter region
    x,y,wc,hc = cv2.boundingRect(largest)
    # Include nearby small contours that are dots (distance close)
    # For I/J, the dot is separate small contour near top. Merge bounding boxes if distance small.
    # Find contours very close above
    # Expand rect to include any contour whose centroid is within 20px vertically above
    # Actually we already have binary of whole crop; if I has dot + stem, they are separate contours but both in binary.
    # We'll create mask that includes multiple top components by taking bounding box of all contours that are within crop and reasonable?
    # Simpler: take combined bounding rect of contours whose area >5 and centroid y within height
    # If there are 2 contours separated but both significant, combine
    if len(contours) > 1:
        # Get bounding rect of top 2-3 largest that are not too small
        # Find dot candidate: small area, high up
        # Merge if second largest area >10 and distance between centroids < 30
        second = contours[1]
        area2 = cv2.contourArea(second)
        if 10 < area2 < 200:
            M1 = cv2.moments(largest)
            M2 = cv2.moments(second)
            if M1['m00'] !=0 and M2['m00']!=0:
                cx1 = M1['m10']/M1['m00']; cy1 = M1['m01']/M1['m00']
                cx2 = M2['m10']/M2['m00']; cy2 = M2['m01']/M2['m00']
                dist = np.hypot(cx1-cx2, cy1-cy2)
                if dist < 25 and abs(cy1-cy2) < 30:
                    # merge bounding boxes
                    x2,y2,w2,h2 = cv2.boundingRect(second)
                    x = min(x, x2); y = min(y, y2)
                    wc = max(x+wc, x2+w2) - x
                    hc = max(y+hc, y2+h2) - y
                    # create combined binary region
                    # We'll later extract region that covers both
    # Crop
    pad = 3
    x = max(0, x-pad); y = max(0, y-pad)
    wc = min(binary.shape[1]-x, wc+2*pad)
    hc = min(binary.shape[0]-y, hc+2*pad)
    letter_bin = binary[y:y+hc, x:x+wc]
    # Resize to template size
    try:
        resized = cv2.resize(letter_bin, (_template_size, _template_size), interpolation=cv2.INTER_AREA)
    except:
        return '?',0.0
    # Compare to each template via normalized correlation
    best_ch = '?'
    best_score = -1
    # Normalize resized to 0-255
    for ch, tmpl in templates.items():
        # TM_CCOEFF_NORMED needs both same size
        res = cv2.matchTemplate(resized, tmpl, cv2.TM_CCOEFF_NORMED)
        score = float(res[0][0])
        if score > best_score:
            best_score = score
            best_ch = ch
    # confidence mapping: score is -1 to 1, typical good is 0.5-0.8
    confidence = max(0.0, min(1.0, (best_score+1)/2))  # map to 0-1 but rescale?
    # Better: if best_score <0.3, low confidence
    # We'll return best_score as raw but also threshold
    # Map raw 0.3->0, 0.7->1
    conf_adj = (best_score - 0.3) / 0.4
    conf_adj = max(0.0, min(1.0, conf_adj))
    # But if score very low, mark ?
    if best_score < 0.25:
        return '?', conf_adj
    return best_ch, conf_adj

def _ocr_with_tesseract_if_available(crop_gray):
    # Try to use pytesseract if installed and tesseract binary exists
    try:
        import pytesseract
        # Check binary
        # This will raise if not found
        # Preprocess: upscale 3x, threshold, whitelist
        h,w = crop_gray.shape[:2]
        scale = 3
        big = cv2.resize(crop_gray, (w*scale, h*scale), interpolation=cv2.INTER_CUBIC)
        # Threshold
        _, thr = cv2.threshold(big, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        # Invert if needed? Letters black, background white -> tesseract expects black on white? Actually we have black letter white bg already, so keep
        config = '--psm 10 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ'
        txt = pytesseract.image_to_string(thr, config=config)
        txt = txt.strip().upper()
        # Take first character if any
        for ch in txt:
            if 'A' <= ch <= 'Z':
                return ch, 0.85
        return None
    except Exception as e:
        return None


# ---------------- Circle / Bubble Detection -----------------

def _estimate_bubble_radius(image_shape, num_expected=50):
    h,w = image_shape[:2]
    # heuristic: board width ~ 0.6-0.8 of image width, tile diameter ~ width/6
    # For 470px screenshot board width, radius ~23
    # So radius ≈ min(w,h)*0.045
    # Scale adaptively
    # Use w as reference
    r = int(min(w,h) * 0.045)
    r = max(18, min(45, r))
    return r

def detect_circles_hough(gray, est_radius):
    # Multiple scales
    blurred = cv2.GaussianBlur(gray, (9,9), 2)
    circles_all = []
    # param sets to try
    configs = [
        (100, 22),
        (100, 24),
        (80, 22),
    ]
    for p1,p2 in configs:
        try:
            circles = cv2.HoughCircles(blurred, cv2.HOUGH_GRADIENT, dp=1.2, minDist=est_radius*1.6,
                                       param1=p1, param2=p2, minRadius=int(est_radius*0.7), maxRadius=int(est_radius*1.4))
            if circles is not None:
                circles = np.uint16(np.around(circles))
                for x,y,r in circles[0,:]:
                    circles_all.append((int(x),int(y),int(r)))
        except:
            pass
    # NMS to deduplicate: if two circles distance < r*0.8, keep one with closer to est_radius
    if not circles_all:
        return []
    # Sort by how close radius to est
    circles_all.sort(key=lambda c: abs(c[2]-est_radius))
    filtered = []
    for x,y,r in circles_all:
        keep=True
        for fx,fy,fr in filtered:
            if np.hypot(x-fx, y-fy) < est_radius*0.8:
                keep=False
                break
        if keep:
            filtered.append((x,y,r))
    return filtered

def detect_circles_contours(gray, est_radius):
    # Threshold light bubbles: tray is light, bubbles are lighter/white
    # Use adaptive threshold + color? For gray, bubbles are high V.
    # Try threshold at >160
    # But wood background is darker, tray light.
    # We'll attempt to isolate tray first.
    # Simple: threshold high
    _, thr_light = cv2.threshold(gray, 160, 255, cv2.THRESH_BINARY)
    # Clean
    kernel = np.ones((3,3), np.uint8)
    # Opening to separate bubbles? Actually bubbles are circles touching? Hex grid has small gap, so opening helps separate.
    # No, just try to find contours of white regions that are circular
    # Use adaptive threshold on blurred?
    # Let's use canny + find contours of light tray holes?
    # Alternative: Use HSV style: For gray, bubbles are bright, so thr_light white are bubble interiors + tray.
    # But tray is also bright, so threshold alone gives large tray contour with holes (bubbles) maybe not.
    # In game screenshot, tray is rounded rectangle light beige, bubbles are white circles ON tray, so bubbles are slightly brighter than tray? Or same? Difficult.

    # Let's attempt contour on inverted dark letters? Not.

    # We'll try: Blur then use adaptiveThreshold to highlight edges,
    # then find circles via contour circularity on thresholded where edges are detected.

    # Simplify: Use Hough is primary, contour as fallback for empty bubbles (white circles without letter have same brightness).
    # Another method: Use MSER or simple blob detection.

    # Let's attempt blob detection via LoG
    params = cv2.SimpleBlobDetector_Params()
    params.filterByArea = True
    params.minArea = np.pi*(est_radius*0.6)**2
    params.maxArea = np.pi*(est_radius*1.4)**2
    params.filterByCircularity = True
    params.minCircularity = 0.6
    params.filterByConvexity = True
    params.minConvexity = 0.7
    params.filterByInertia = True
    params.minInertiaRatio = 0.5
    params.filterByColor = True
    params.blobColor = 255  # light blobs
    params.minThreshold = 150
    params.maxThreshold = 255
    try:
        detector = cv2.SimpleBlobDetector_create(params)
        keypoints = detector.detect(gray)
        circles = [(int(k.pt[0]), int(k.pt[1]), int(k.size/2)) for k in keypoints]
        return circles
    except Exception as e:
        return []

def detect_letter_centroids(gray):
    """
    Threshold dark pixels <95, find connected components, merge dots.
    Returns list of (x,y) centroids for each glyph.
    """
    # threshold dark
    _, dark = cv2.threshold(gray, 95, 255, cv2.THRESH_BINARY_INV)
    # Clean small noise
    kernel = np.ones((2,2), np.uint8)
    dark = cv2.morphologyEx(dark, cv2.MORPH_OPEN, kernel)
    # Find contours
    contours, _ = cv2.findContours(dark, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    centroids = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < 20 or area > 2000:  # filter by letter size (depends on scale)
            continue
        # Also filter by aspect and extent?
        x,y,w,h = cv2.boundingRect(cnt)
        # Letters should be somewhat square, not too thin line
        if w < 5 or h < 10:
            continue
        if h > 60 or w > 60:  # too big, maybe tray edge
            continue
        M = cv2.moments(cnt)
        if M['m00'] == 0:
            continue
        cx = int(M['m10']/M['m00'])
        cy = int(M['m01']/M['m00'])
        centroids.append((cx,cy, area, w, h))
    # Merge dots: I/J dots are small small area ~20-80 and close to another centroid (stem)
    # Group by proximity <15px
    merged = []
    used = [False]*len(centroids)
    for i, (cx,cy,area,w,h) in enumerate(centroids):
        if used[i]:
            continue
        # Find neighbors within 18px
        group = [(cx,cy,area)]
        used[i]=True
        for j in range(i+1, len(centroids)):
            if used[j]:
                continue
            cx2,cy2,a2,w2,h2 = centroids[j]
            dist = np.hypot(cx-cx2, cy-cy2)
            if dist < 22:  # dots close to stem
                # Check if one is small dot
                small = min(area, a2) < 120
                if small:
                    group.append((cx2,cy2,a2))
                    used[j]=True
        # Average centroid weighted by area?
        if len(group) == 1:
            merged.append((cx,cy))
        else:
            # weighted avg
            xs = [g[0] for g in group]
            ys = [g[1] for g in group]
            # Use larger area as primary but average
            # For I, dot is above stem, average will be slightly above stem center but closer to stem
            # Let's weight by area
            weights = [g[2] for g in group]
            total = sum(weights)
            avgx = sum(g[0]*g[2] for g in group)/total
            avgy = sum(g[1]*g[2] for g in group)/total
            merged.append((int(avgx), int(avgy)))
    return merged

def _cluster_rows(centers: List[Tuple[int,int]], y_thresh: float = None):
    """
    Cluster bubble centers into rows by y-coordinate.
    Allows tilt of 1-3 degrees by using generous threshold.
    Returns list of rows, each row sorted by x.
    """
    if not centers:
        return []
    if y_thresh is None:
        # estimate from median radius or from y spread
        ys = sorted([c[1] for c in centers])
        # estimate median vertical spacing: diff between sorted ys
        # Use overall height / estimated rows (10)
        heights = max(ys)-min(ys) if len(ys)>1 else 100
        est_row_spacing = heights / 9 if len(centers)>20 else 55
        y_thresh = est_row_spacing * 0.55  # half spacing
        y_thresh = max(25, min(45, y_thresh))
    # sort by y
    sorted_centers = sorted(centers, key=lambda c: c[1])
    rows = []
    current_row = [sorted_centers[0]]
    last_y = sorted_centers[0][1]
    for c in sorted_centers[1:]:
        if abs(c[1] - last_y) < y_thresh:  # but need to compare to row mean?
            # Compare to mean of current row
            mean_y = np.mean([p[1] for p in current_row])
            if abs(c[1] - mean_y) < y_thresh:
                current_row.append(c)
                # update last_y to mean? keep
            else:
                # new row
                rows.append(sorted(current_row, key=lambda p: p[0]))
                current_row = [c]
        else:
            rows.append(sorted(current_row, key=lambda p: p[0]))
            current_row = [c]
        # update last_y as current row mean?
        # We'll update last_y to mean of current_row for tilt tolerance
        # Actually just keep as current center's y
        # But better to use row mean
        # So recompute mean
        # last_y = np.mean([p[1] for p in current_row])
        last_y = c[1]
    if current_row:
        rows.append(sorted(current_row, key=lambda p: p[0]))
    return rows


def detect_board(image_bgr: np.ndarray, debug=False) -> Dict:
    """
    Main detection pipeline. Returns dict with tiles, counts, debug info.
    image_bgr: OpenCV BGR image
    """
    orig_h, orig_w = image_bgr.shape[:2]
    # Resize for processing if huge (max 1000 width) to keep speed consistent, but remember scale
    scale = 1.0
    max_side = 800
    if max(orig_h, orig_w) > max_side:
        scale = max_side / max(orig_h, orig_w)
        image_bgr_small = cv2.resize(image_bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    else:
        image_bgr_small = image_bgr
    small_h, small_w = image_bgr_small.shape[:2]

    gray = cv2.cvtColor(image_bgr_small, cv2.COLOR_BGR2GRAY)

    est_r = _estimate_bubble_radius((small_h, small_w))
    # Hough detection
    hough_circles = detect_circles_hough(gray, est_r)
    contour_circles = detect_circles_contours(gray, est_r)
    # Merge circles
    all_circles = hough_circles + contour_circles
    # If Hough found many, trust it more. If none, try fallback morphological
    # Additional fallback: use contour detection on threshold light (if both failed)
    if len(all_circles) < 10:
        # Try threshold-based contour of light circles: use adaptive
        # Apply Gaussian blur then threshold + find contours of circular shapes
        blur = cv2.GaussianBlur(gray, (5,5), 0)
        # Use adaptive threshold to isolate light circles edge
        # Instead, detect light blobs via threshold 180 + morphology
        _, thr = cv2.threshold(blur, 175, 255, cv2.THRESH_BINARY)
        # invert? Actually bubbles white -> 255
        # Find contours of white regions
        contours, _ = cv2.findContours(thr, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            area = cv2.contourArea(cnt)
            perim = cv2.arcLength(cnt, True)
            if perim == 0:
                continue
            circ = 4*np.pi*area/(perim*perim) if perim else 0
            if circ < 0.6:
                continue
            # estimate radius from area
            r_est = np.sqrt(area/np.pi)
            if est_r*0.5 < r_est < est_r*1.6:
                M = cv2.moments(cnt)
                if M['m00']==0:
                    continue
                cx = int(M['m10']/M['m00']); cy = int(M['m01']/M['m00'])
                # check duplicate
                dup=False
                for (x,y,r) in all_circles:
                    if np.hypot(cx-x, cy-y) < est_r*0.7:
                        dup=True; break
                if not dup:
                    all_circles.append((cx,cy,int(r_est)))

    # Deduplicate all_circles with NMS — use 1.0*est to merge highlight duplicates (tiles are >2.5*est apart)
    # Sort by radius closeness to est_r
    all_circles = sorted(all_circles, key=lambda c: abs(c[2]-est_r))
    filtered = []
    for x,y,r in all_circles:
        keep=True
        for fx,fy,fr in filtered:
            if np.hypot(x-fx, y-fy) < est_r*1.0:
                keep=False; break
        if keep:
            filtered.append((x,y,r))
    circles = filtered

    # Color filter: reject circles whose center region is dark wood (not light tray)
    # Tray is light (gray >170), wood is darker (~80-120). Check mean grayscale in small window around center.
    filtered_color=[]
    for x,y,r in circles:
        # ensure inside image
        x1=max(0, x-5); y1=max(0, y-5); x2=min(small_w, x+5); y2=min(small_h, y+5)
        patch=gray[y1:y2, x1:x2]
        if patch.size==0:
            continue
        mean=int(np.mean(patch))
        # Also check surrounding ring: if many dark pixels, it's wood
        if mean < 125:  # dark wood
            continue
        filtered_color.append((x,y,r))
    # Only apply if we keep at least 10
    if len(filtered_color) >= 10:
        circles=filtered_color

    # If still too few, fallback to letter centroids + estimate bubble positions?
    letter_centroids = detect_letter_centroids(gray)

    # Cross-check: If we have letter centroids but no circles, estimate bubble centers as letter centroids offset slightly down
    if len(circles) < 10 and len(letter_centroids) >= 10:
        # Use letter centroids as bubble centers approximation
        # But we also need empty bubbles — they will be missing!
        # We'll try to infer grid and fill missing?
        # For now just use letter centroids as circles with est_r
        circles = [(int(x), int(y+4), est_r) for x,y in letter_centroids]  # slight offset

    # Also need to detect empty bubbles: circles with no dark glyph inside
    # For each circle, check distance to nearest letter centroid
    tiles = []
    # Need OCR for each circle
    # Preprocess for OCR: we need gray at original scale? Use small gray for now then scale back coordinates

    # Build letter centroid list for empty check
    # letter_centroids are in small image coordinates
    # circles also in small coordinates

    # If we have very few circles but many letter centroids, we might still be okay.

    # Decide final bubble positions: Use circles as primary; but also ensure any letter centroid that is far from any circle (>r*0.7) should create a new bubble (missed detection)
    # Add missing
    for lx, ly in letter_centroids:
        found=False
        for cx,cy,r in circles:
            if np.hypot(lx-cx, ly-cy) < est_r*0.9:
                found=True; break
        if not found:
            # Add new circle at letter position
            circles.append((int(lx), int(ly+4), est_r))

    # Now for each circle, determine if empty and OCR letter
    # Sort circles by y then x for consistent indexing before row snap?
    # But we will later assign row/col

    # Filter circles that are obviously outside tray? Tray is central vertical rectangle. Circles should be within central area, not on wood.
    # Heuristic: Compute median x, filter outliers far away
    if circles:
        xs = [c[0] for c in circles]
        ys = [c[1] for c in circles]
        median_x = np.median(xs)
        median_y = np.median(ys)
        # Estimate board size: use data-driven height (max_y-min_y) and width, but fallback to 18*18*28 heuristics
        # Keep generous but data-driven to avoid cutting top/bottom rows while rejecting far outliers
        ys_sorted=sorted(ys)
        xs_sorted=sorted(xs)
        data_h = max(ys)-min(ys) if len(ys)>1 else 28*est_r
        data_w = max(xs)-min(xs) if len(xs)>1 else 18*est_r
        # Expand by 1 tile margin
        board_w_est = max(18*est_r, data_w + 2*est_r)
        board_h_est = max(28*est_r, data_h + 2*est_r)
        # Filter circles far from median — use 0.90* width and 0.80* height (generous)
        filtered2=[]
        for x,y,r in circles:
            if abs(x-median_x) < board_w_est*0.60 and abs(y-median_y) < board_h_est*0.60:
                filtered2.append((x,y,r))
        # If filtered removes too many (keep at least 10), apply
        if len(filtered2) >= 10:
            circles = filtered2

    # Now OCR
    results_tiles = []
    for idx, (cx,cy,r) in enumerate(circles):
        # Determine empty: check if any letter centroid within r*0.65
        is_empty = True
        nearest_dist = float('inf')
        for lx,ly in letter_centroids:
            d = np.hypot(lx-cx, ly-cy)
            if d < nearest_dist:
                nearest_dist = d
            if d < r*0.65:
                is_empty = False
                break
        letter = ''
        conf = 0.0
        value = 0
        if not is_empty:
            # Crop region around center: radius *1.4 square
            crop_r = int(r*1.1)
            x1 = max(0, cx-crop_r); y1 = max(0, cy-crop_r)
            x2 = min(small_w, cx+crop_r); y2 = min(small_h, cy+crop_r)
            crop = gray[y1:y2, x1:x2]
            # Try tesseract first via template fallback
            # Try template matching
            # If crop is too small, skip
            if crop.size > 0:
                # Try template matching
                ch, c = _ocr_template_match(crop)
                if ch != '?' and c > 0.3:
                    letter = ch
                    conf = c
                else:
                    # fallback try tesseract wrapper if available
                    t_res = _ocr_with_tesseract_if_available(crop)
                    if t_res is not None:
                        ch2, c2 = t_res
                        if ch2:
                            letter = ch2
                            conf = c2
                    # if still ? use template best even if low
                    if not letter:
                        letter = ch if ch!='?' else ''
                        conf = c
        else:
            letter = ''
            conf = 0.0

        # If detection left letter empty but we have near letter centroid, try OCR again with tighter crop around letter centroid
        if not is_empty and not letter:
            # find nearest letter centroid's position
            best_lx, best_ly, best_d = None,None,float('inf')
            for lx,ly in letter_centroids:
                d=np.hypot(lx-cx, ly-cy)
                if d<best_d:
                    best_d=d; best_lx, best_ly = lx,ly
            if best_lx is not None and best_d < r:
                # crop around letter centroid tightly
                cs = int(r*0.9)
                x1 = max(0, best_lx-cs); y1 = max(0, best_ly-cs)
                x2 = min(small_w, best_lx+cs); y2 = min(small_h, best_ly+cs)
                crop2 = gray[y1:y2, x1:x2]
                ch,c = _ocr_template_match(crop2)
                if ch!='?':
                    letter=ch; conf=c

        if letter:
            value = SCRABBLE_VALUES.get(letter, 1)
        else:
            if is_empty:
                value = 0
            else:
                # Unknown letter, mark as ? but still need guess
                letter = '?'
                conf = 0.0
                value = 1

        # Scale back to original image coordinates
        orig_x = int(cx / scale)
        orig_y = int(cy / scale)
        orig_r = int(r / scale)
        # For Word vs Word, blank bubbles are wildcards (can be any letter, 0 pts)
        # not holes. is_empty previously meant hole; now we map blank -> wildcard.
        # is_wildcard = True means this tile can be any A-Z (scores 0), is_empty = True means true hole (skip)
        # By default, treat detected blanks as wildcards (game's backend behavior)
        # Set is_wildcard = is_empty (blank), and keep is_empty=False for wildcards so they are traversable.
        is_wildcard = bool(is_empty)
        # keep original is_empty for hole logic if needed, but wildcards are not holes
        # For solver compatibility we store both; solver treats is_wildcard as playable even if is_empty would otherwise be hole.
        results_tiles.append({
            'x': orig_x,
            'y': orig_y,
            'r': orig_r,
            'letter': letter,
            'value': value,
            'is_empty': False if is_wildcard else is_empty,
            'is_wildcard': is_wildcard,
            'is_blank': is_wildcard,
            'confidence': float(conf),
            'cx_small': cx,
            'cy_small': cy,
        })

    # Filter: Remove tiles with very low confidence '?' and is_empty False but maybe false positive? Keep but mark.
    # Row snapping for ordering
    # Use small coordinates for clustering then map back? Use orig coordinates
    centers_for_rows = [(t['x'], t['y']) for t in results_tiles]
    rows = _cluster_rows(centers_for_rows)

    # Assign row/col based on clustering
    # We need to map each tile to its row index and col within row
    # Build lookup from (x,y) to index
    coord_to_idx = {(t['x'],t['y']): i for i,t in enumerate(results_tiles)}
    # Actually need to handle duplicates due to rounding? Use list search
    # Instead iterate rows and find matching tile by nearest
    for r_idx, row in enumerate(rows):
        # row sorted by x already
        for c_idx, (rx,ry) in enumerate(row):
            # find tile index with closest coordinates
            best_i=None; best_d=float('inf')
            for i,t in enumerate(results_tiles):
                d=np.hypot(t['x']-rx, t['y']-ry)
                if d<best_d:
                    best_d=d; best_i=i
            if best_i is not None:
                results_tiles[best_i]['row']=r_idx
                results_tiles[best_i]['col']=c_idx
    # For any tile not assigned (due to clustering bug), assign -1
    for t in results_tiles:
        if 'row' not in t:
            t['row']=-1; t['col']=-1

    # Sort final tiles by row then col for consistent output
    results_tiles_sorted = sorted(results_tiles, key=lambda t: (t['row'], t['col']))

    # Build stats
    detected = len(results_tiles_sorted)
    # playable = normal letters + wildcards (blanks that can be any letter)
    playable = len([t for t in results_tiles_sorted if (t.get('is_wildcard') or (not t['is_empty'] and t['letter'] not in ('','?')))])
    empties = len([t for t in results_tiles_sorted if t['is_empty']])
    wildcards = len([t for t in results_tiles_sorted if t.get('is_wildcard')])
    low_conf = len([t for t in results_tiles_sorted if t['confidence'] < 0.5 and not t['is_empty']])

    return {
        'tiles': results_tiles_sorted,
        'detected_count': detected,
        'playable_count': playable,
        'empty_count': empties,
        'wildcard_count': wildcards,
        'low_conf_count': low_conf,
        'est_radius': est_r,
        'scale': scale,
        'circles_small': circles,
        'letter_centroids_small': letter_centroids,
        'image_shape': (orig_h, orig_w),
        'small_shape': (small_h, small_w),
    }

def tiles_to_solver_format(det_result: Dict) -> List[Dict]:
    """Convert detector tiles to solver expected format."""
    tiles=[]
    for t in det_result['tiles']:
        tiles.append({
            'x': t['x'],
            'y': t['y'],
            'letter': t['letter'] if not t.get('is_wildcard') and not t['is_empty'] else '',
            'value': t['value'],
            'is_empty': t['is_empty'],
            'is_wildcard': bool(t.get('is_wildcard') or t.get('is_blank')),
            'is_blank': bool(t.get('is_wildcard') or t.get('is_blank')),
        })
    return tiles

